"""Result notification/outbox invariants, all evidence and mail entirely local."""
import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import pytest

import in_hand as ih
import verification_notifications as notify
from test_in_hand import assessment, jpeg

OWNER = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
REAL_RESOLVER = notify.resolve_identity


@pytest.fixture
def local(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCKX_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LOCKX_VERIFICATION_QUEUE_ENABLED", "0")
    monkeypatch.setenv("LOCKX_CREDITS_ENABLED", "0")
    monkeypatch.setenv("LOCKX_RESULT_EMAIL_RESEND_KEY", "not-a-real-key")
    monkeypatch.setenv("LOCKX_RESULT_EMAIL_FROM", "LockX <results@auth.lockx.ai>")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    async def resolve(owner):
        return profile(owner=owner)
    monkeypatch.setattr(notify, "resolve_identity", resolve)
    return monkeypatch


def profile(owner=OWNER, **changes):
    return {"id": owner, "email": "buyer@example.test", "email_confirmed_at": "2026-01-01T00:00:00Z", **changes}


def seed(db, owner=OWNER, *, count=2, state="confirmed", analysis_status="complete", auto=False, kind="seller", created=None):
    identifier, session = str(uuid4()), str(uuid4())
    created = time.time() if created is None else created
    listing = {"title": "Local collectible", "capture_mode": "handheld", "auto_publish": auto,
               "publish_matched_photos": True, "request_kind": kind}
    visual = assessment(count=count)
    if state != "confirmed":
        visual.same_item = "inconclusive" if state == "inconclusive" else "contradicted"
        for photo in visual.photos:
            photo.finding = "not_established" if state == "inconclusive" else "contradicted"
    analysis = {"result": state, "visual": visual.model_dump(), "video": {"notes": []}}
    db.execute("""INSERT INTO ih_requests(id,owner_id,token,listing,status,created,expires,submitted,plan,analysis,analysis_status,session_id)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (identifier, owner, "capture-secret-" + str(uuid4()), json.dumps(listing), state,
        created, created + 86400, created + 10, "[]", json.dumps(analysis), analysis_status, session))
    db.execute("INSERT INTO ih_sessions VALUES(?,?,?,?,?,0,'[]',?)", (session, identifier, created, created, "[]", created + 10))
    for i in range(count):
        ih.store_media(db, identifier, "listing", "image/jpeg", jpeg(i), label=f"Photo {i+1}")
        ih.store_media(db, identifier, "frame", "image/jpeg", jpeg(i), seconds=float(i))
    if kind == "buyer":
        db.execute("INSERT INTO ih_buyer_requests VALUES(?,?,?,?,?,'pending')", (identifier, owner, "https://market.example/item", str(uuid4()), "local-hash"))
    return identifier


def publish(db, request_id):
    row = db.execute("SELECT * FROM ih_requests WHERE id=?", (request_id,)).fetchone()
    eligible = ih.photo_eligibility(db, row)
    publication = str(uuid4())
    db.execute("INSERT INTO ih_publications VALUES(?,?,?,NULL)", (publication, request_id, time.time()))
    db.execute("INSERT INTO ih_publication_scopes VALUES(?,?)", (publication, eligible["total_count"]))
    for index in eligible["eligible_photo_indices"]:
        media = ih.store_media(db, request_id, "marked", "image/jpeg", jpeg(index))
        db.execute("INSERT INTO ih_publication_photos VALUES(?,?,?)", (publication, index, media))
    return publication


def ready(db, request_id, *, identity=True):
    if identity:
        assert notify.bind_identity(db, profile())
    event_id = notify.refresh_state(db, request_id, assessment_complete=True)
    assert event_id
    return event_id


@pytest.mark.parametrize("change", [
    {"id": "guest:abc"}, {"id": OWNER, "email_confirmed_at": None},
    {"email_confirmed_at": None, "phone_confirmed_at": "2026-01-01T00:00:00Z", "confirmed_at": "2026-01-01T00:00:00Z"},
    {"email": "invalid"}, {"email_confirmed_at": "not-a-date"},
    {"email_confirmed_at": "9999-01-01T00:00:00Z"}, {"is_anonymous": True}, {"deleted_at": "2026-01-01"},
])
def test_only_confirmed_server_identity_binds_recipient(local, change):
    with ih.database() as db:
        assert notify.bind_identity(db, profile(**change)) is False
        assert db.execute("SELECT COUNT(*) FROM verification_identities").fetchone()[0] == 0


def test_identity_uses_only_trusted_top_level_email_and_can_invalidate(local):
    with ih.database() as db:
        assert notify.bind_identity(db, profile(email=" Buyer@Example.Test ", user_metadata={"email": "attacker@example.test"}))
        assert db.execute("SELECT email FROM verification_identities").fetchone()[0] == "buyer@example.test"
        assert not notify.bind_identity(db, profile(email_confirmed_at=None))
        assert db.execute("SELECT COUNT(*) FROM verification_identities").fetchone()[0] == 0


def test_unchanged_verified_login_does_not_write_identity_on_every_account_read(local):
    with ih.database() as db:
        notify.bind_identity(db, profile())
        before = db.total_changes
        assert notify.bind_identity(db, profile())
        assert db.total_changes == before


def test_historical_completion_worker_and_default_refresh_never_bootstrap_mail(local):
    with ih.database() as db:
        request_id = seed(db, created=time.time() - 100000)
        notify.activation(db)
        activation = db.execute("SELECT activated_at FROM verification_notification_control").fetchone()[0]
        assert notify.refresh_state(db, request_id) is None
        notify.bind_identity(db, profile())
    assert asyncio.run(notify.drain_once(ih.database)) is False
    with ih.database() as db:
        notify.schema(db)
        assert db.execute("SELECT activated_at FROM verification_notification_control").fetchone()[0] == activation
        assert db.execute("SELECT COUNT(*) FROM verification_notifications").fetchone()[0] == 0


@pytest.mark.parametrize("state,expected", [("confirmed", "verified"), ("inconclusive", "inconclusive"), ("mismatch", "mismatch")])
def test_each_completed_outcome_is_idempotent_and_account_owned(local, state, expected):
    with ih.database() as db:
        request_id = seed(db, state=state, kind="buyer")
        event_id = ready(db, request_id)
        assert notify.refresh_state(db, request_id) == event_id
        event = db.execute("SELECT * FROM verification_notifications").fetchone()
        assert event["owner_id"] == OWNER and event["outcome"] == expected
        assert event["root_request_id"] == request_id and event["attempt_id"] == request_id
        assert event["email_state"] == "pending" and event["ready_at"]
        assert notify.unread_count(db, OWNER) == 1


def test_local_partial_is_explicit_without_promoting_mismatched_photo(local):
    with ih.database() as db:
        request_id = seed(db)
        row = db.execute("SELECT analysis FROM ih_requests WHERE id=?", (request_id,)).fetchone()
        analysis = json.loads(row["analysis"])
        analysis["visual"]["photos"][1]["finding"] = "contradicted"
        analysis["visual"]["same_item"] = "contradicted"
        db.execute("UPDATE ih_requests SET status='mismatch',analysis=? WHERE id=?", (json.dumps(analysis), request_id))
        event_id = ready(db, request_id)
        event = db.execute("SELECT * FROM verification_notifications WHERE id=?", (event_id,)).fetchone()
        assert (event["outcome"], event["verified_count"], event["total_count"]) == ("partial", 1, 2)


def test_required_publication_waits_for_actual_committed_manifest(local):
    with ih.database() as db:
        request_id = seed(db, auto=True)
        event_id = ready(db, request_id)
        event = db.execute("SELECT * FROM verification_notifications WHERE id=?", (event_id,)).fetchone()
        assert event["email_state"] == "waiting_publication" and event["ready_at"] is None
        assert notify.unread_count(db, OWNER) == 0
        publish(db, request_id)
        assert notify.refresh_state(db, request_id) == event_id
        assert db.execute("SELECT email_state FROM verification_notifications WHERE id=?", (event_id,)).fetchone()[0] == "pending"


def test_terminal_proof_preparation_failure_is_distinct_and_recovery_can_finish(local):
    with ih.database() as db:
        request_id = seed(db, auto=True)
        ready(db, request_id)
        db.execute("INSERT INTO ih_publication_jobs VALUES(?,'failed',2,?)", (request_id, time.time()))
        failure_id = notify.refresh_state(db, request_id)
        event = db.execute("SELECT * FROM verification_notifications WHERE id=?", (failure_id,)).fetchone()
        assert event["kind"] == "proof_preparation_failed" and event["outcome"] == "proof_preparation_failed"
        publish(db, request_id)
        result_id = notify.refresh_state(db, request_id)
        assert result_id != failure_id
        claim = notify._claim(db, time.time())
        assert claim["id"] == result_id


def test_temporary_processing_failures_do_not_notify_and_final_retry_success_can(local):
    with ih.database() as db:
        request_id = seed(db, state="inconclusive", analysis_status="failed")
        notify.bind_identity(db, profile())
        assert notify.refresh_state(db, request_id) is None
        failed_id = notify.refresh_state(db, request_id, final_failure=True)
        assert failed_id
        db.execute("UPDATE ih_requests SET analysis_status='complete' WHERE id=?", (request_id,))
        result_id = notify.refresh_state(db, request_id, assessment_complete=True)
        assert result_id != failed_id
        claim = notify._claim(db, time.time())
        assert claim["id"] == result_id


@pytest.mark.parametrize("queue_state", ["queued", "running", "retrying", "budget_wait"])
def test_active_processing_queue_never_emails_a_premature_result(local, queue_state):
    with ih.database() as db:
        request_id = seed(db)
        db.execute("CREATE TABLE verification_jobs(request_id TEXT,state TEXT)")
        db.execute("INSERT INTO verification_jobs VALUES(?,?)", (request_id, queue_state))
        assert notify.refresh_state(db, request_id, assessment_complete=True) is None
        assert db.execute("SELECT COUNT(*) FROM verification_notification_assessments").fetchone()[0] == 1
        db.execute("UPDATE verification_jobs SET state='completed'")
        assert notify.refresh_state(db, request_id)


def test_result_and_outbox_rollback_together(local):
    with ih.database() as db:
        request_id = seed(db)
        notify.schema(db)
    with pytest.raises(RuntimeError):
        with ih.database() as db:
            ready(db, request_id)
            raise RuntimeError("crash before commit")
    with ih.database() as db:
        assert db.execute("SELECT COUNT(*) FROM verification_notifications").fetchone()[0] == 0


def test_delivery_occurs_after_commit_uses_exact_attempt_account_link_and_acceptance(local, monkeypatch):
    with ih.database() as db:
        request_id = seed(db)
        event_id = ready(db, request_id)
    calls = []
    async def send(payload, key):
        with ih.database() as db:
            db.execute("BEGIN IMMEDIATE")  # Network is not inside the writer transaction.
            assert db.execute("SELECT email_state FROM verification_notifications WHERE id=?", (event_id,)).fetchone()[0] == "sending"
        calls.append((payload, key))
        return {"state": "accepted", "provider_id": "fake-provider-id"}
    monkeypatch.setattr(notify, "deliver", send)
    assert asyncio.run(notify.drain_once(ih.database))
    assert not asyncio.run(notify.drain_once(ih.database))
    payload, key = calls[0]
    assert key == "lockx-result-" + event_id
    assert payload["to"] == ["buyer@example.test"]
    assert f"https://lockx.ai/#in-hand/report/{request_id}?account=1" in payload["text"]
    assert "capture-secret" not in json.dumps(payload) and "manage" not in payload["text"]
    with ih.database() as db:
        event = db.execute("SELECT * FROM verification_notifications").fetchone()
        assert event["email_state"] == "accepted"  # Never claim delivered.


def test_uncertain_retries_freeze_payload_recipient_key_and_fence_late_results(local, monkeypatch):
    with ih.database() as db:
        request_id = seed(db)
        event_id = ready(db, request_id)
        first = notify._claim(db, time.time())
        notify.authorize_delivery(db, first, profile())
        notify.complete(db, first, {"state": "uncertain", "retry_after": 30})
        db.execute("UPDATE verification_notifications SET next_attempt=0")
        second = notify._claim(db, time.time())
        assert first["payload"] == second["payload"] and first["idempotency_key"] == second["idempotency_key"]
        assert not notify.complete(db, first, {"state": "accepted", "provider_id": "late"})
        assert notify.complete(db, second, {"state": "accepted", "provider_id": "current"})


def test_verified_email_change_cancels_uncertain_retry_instead_of_retargeting(local):
    with ih.database() as db:
        request_id = seed(db)
        event_id = ready(db, request_id)
        first = notify._claim(db, time.time())
        notify.authorize_delivery(db, first, profile())
        notify.complete(db, first, {"state": "uncertain"})
        notify.bind_identity(db, profile(email="new@example.test"))
        db.execute("UPDATE verification_notifications SET next_attempt=0")
        assert notify._claim(db, time.time()) is None
        assert db.execute("SELECT email_state FROM verification_notifications WHERE id=?", (event_id,)).fetchone()[0] == "suppressed"


def test_uncertain_retry_expiry_never_creates_new_key_or_mail(local):
    with ih.database() as db:
        request_id = seed(db)
        event_id = ready(db, request_id)
        first = notify._claim(db, time.time())
        notify.authorize_delivery(db, first, profile())
        notify.complete(db, first, {"state": "uncertain"})
        assert notify._claim(db, time.time() + notify.RETRY_SECONDS + 1) is None
        assert db.execute("SELECT email_state FROM verification_notifications WHERE id=?", (event_id,)).fetchone()[0] == "expired"


def test_withdrawal_before_delivery_suppresses_unsent_ready_event(local):
    with ih.database() as db:
        request_id = seed(db, auto=True)
        publish(db, request_id)
        event_id = ready(db, request_id)
        db.execute("UPDATE ih_publications SET revoked=? WHERE request_id=?", (time.time(), request_id))
        assert notify._claim(db, time.time()) is None
        assert db.execute("SELECT email_state FROM verification_notifications WHERE id=?", (event_id,)).fetchone()[0] == "suppressed"


def test_newer_attempt_suppresses_original_result_without_leaking_capture_token(local):
    import capture_attempts
    with ih.database() as db:
        root = seed(db, state="inconclusive")
        original_id = ready(db, root)
        child = seed(db, state="inconclusive")
        db.execute("INSERT INTO ih_capture_retries VALUES(?,?,'verification_failed')", (root, child))
        assert capture_attempts.family(db, child)[0]["id"] == root
        child_id = ready(db, child)
        claim = notify._claim(db, time.time())
        assert claim["id"] == child_id
        assert f"/report/{child}?account=1" in claim["payload"]["text"]
        assert root not in claim["payload"]["text"]
        assert db.execute("SELECT email_state FROM verification_notifications WHERE id=?", (original_id,)).fetchone()[0] == "suppressed"


def test_missing_verified_email_keeps_in_app_event_without_historical_login_blast(local):
    with ih.database() as db:
        request_id = seed(db)
        event_id = ready(db, request_id, identity=False)
        assert notify.unread_count(db, OWNER) == 1
        claim = notify._claim(db, time.time())
        assert claim["id"] == event_id and claim["payload"] is None
        assert notify.authorize_delivery(db, claim, profile())["to"] == ["buyer@example.test"]


def test_concurrent_outbox_claims_have_one_current_lease(local):
    with ih.database() as db:
        request_id = seed(db)
        ready(db, request_id)
    def claim(_):
        with ih.database() as db:
            db.execute("BEGIN IMMEDIATE")
            return notify._claim(db, time.time())
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(claim, range(4)))
    assert sum(value is not None for value in results) == 1


def test_proof_delayed_more_than_23_hours_gets_fresh_ready_window(local, monkeypatch):
    with ih.database() as db:
        request_id = seed(db, auto=True)
        event_id = ready(db, request_id)
        db.execute("UPDATE verification_notifications SET created=created-?", (notify.RETRY_SECONDS + 100,))
        publish(db, request_id)
        notify.refresh_state(db, request_id)
        assert notify._claim(db, time.time())["id"] == event_id


@pytest.mark.parametrize("change", [{"id": OTHER}, {"email_confirmed_at": None}, {"is_anonymous": True}, {"deleted_at": "now"}])
def test_fresh_profile_must_match_exact_owner_and_current_verified_email(local, change):
    with ih.database() as db:
        request_id = seed(db)
        event_id = ready(db, request_id)
        claim = notify._claim(db, time.time())
        assert notify.authorize_delivery(db, claim, profile(**change)) is None
        assert db.execute("SELECT email_state FROM verification_notifications WHERE id=?", (event_id,)).fetchone()[0] == "suppressed"


def test_fresh_email_before_first_provider_call_can_bind_current_address(local):
    with ih.database() as db:
        request_id = seed(db)
        ready(db, request_id)
        claim = notify._claim(db, time.time())
        payload = notify.authorize_delivery(db, claim, profile(email="current@example.test"))
        assert payload["to"] == ["current@example.test"]
        notify.complete(db, claim, {"state": "uncertain"})
        db.execute("UPDATE verification_notifications SET next_attempt=0")
        retry = notify._claim(db, time.time())
        assert notify.authorize_delivery(db, retry, profile(email="changed@example.test")) is None


def test_fresh_profile_lookup_failure_retries_without_calling_email_provider(local, monkeypatch):
    async def unavailable(owner):
        return None
    async def unexpected(*args):
        pytest.fail("No result email without fresh server identity")
    monkeypatch.setattr(notify, "resolve_identity", unavailable)
    monkeypatch.setattr(notify, "deliver", unexpected)
    with ih.database() as db:
        request_id = seed(db)
        ready(db, request_id)
    assert asyncio.run(notify.drain_once(ih.database))
    with ih.database() as db:
        event = db.execute("SELECT * FROM verification_notifications").fetchone()
        assert event["email_state"] == "pending" and event["provider_started"] is None


def test_new_completion_without_cached_email_can_deliver_before_owner_returns(local, monkeypatch):
    with ih.database() as db:
        request_id = seed(db, kind="buyer")
        ready(db, request_id, identity=False)
    calls = []
    async def send(payload, key):
        calls.append(payload)
        return {"state": "accepted", "provider_id": "local-accepted"}
    monkeypatch.setattr(notify, "deliver", send)
    assert asyncio.run(notify.drain_once(ih.database))
    assert len(calls) == 1 and calls[0]["to"] == ["buyer@example.test"]


def test_fresh_identity_lookup_rechecks_revocation_and_current_lease(local):
    with ih.database() as db:
        request_id = seed(db, auto=True)
        publish(db, request_id)
        ready(db, request_id)
        claim = notify._claim(db, time.time())
        db.execute("UPDATE ih_publications SET revoked=?", (time.time(),))
        assert notify.authorize_delivery(db, claim, profile()) is None
        assert not notify.complete(db, claim, {"state": "accepted", "provider_id": "late"})


def test_nonqueued_technical_retry_during_identity_lookup_obsoletes_failure_email(local, monkeypatch):
    with ih.database() as db:
        request_id = seed(db, state="inconclusive", analysis_status="failed")
        notify.bind_identity(db, profile())
        event_id = notify.refresh_state(db, request_id, final_failure=True)
    async def resolve(owner):
        with ih.database() as db:
            # Same-evidence retry in queue-disabled compatibility mode.
            db.execute("UPDATE ih_requests SET status='processing',analysis_status='pending' WHERE id=?", (request_id,))
        return profile()
    async def unexpected(*args):
        pytest.fail("An obsolete processing failure must not be emailed")
    monkeypatch.setattr(notify, "resolve_identity", resolve)
    monkeypatch.setattr(notify, "deliver", unexpected)
    assert asyncio.run(notify.drain_once(ih.database))
    with ih.database() as db:
        assert db.execute("SELECT email_state FROM verification_notifications WHERE id=?", (event_id,)).fetchone()[0] == "suppressed"


def test_exact_uuid_auth_lookup_is_bounded_static_and_outside_sqlite(local, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://auth.example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-server-key")
    calls = []
    class Client:
        def __init__(self, **options):
            assert options == {"timeout": 5, "trust_env": False, "follow_redirects": False}
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def get(self, url, **options):
            with ih.database() as db:
                db.execute("BEGIN IMMEDIATE")
            calls.append((url, options))
            return SimpleNamespace(status_code=200, json=lambda: profile())
    monkeypatch.setattr(notify.httpx, "AsyncClient", Client)
    assert asyncio.run(REAL_RESOLVER(OWNER)) == profile()
    assert calls[0][0] == "https://auth.example.test/auth/v1/admin/users/" + OWNER
    assert calls[0][1]["headers"] == {"apikey": "test-server-key"}


@pytest.mark.parametrize("status,body,expected", [(202, {"id": "provider-id"}, "accepted"), (200, {}, "uncertain"), (500, {}, "uncertain"), (429, {}, "rejected"), (403, {}, "rejected")])
def test_result_email_transport_classifies_acceptance_and_ambiguity_without_network(local, monkeypatch, status, body, expected):
    class Client:
        def __init__(self, **options):
            assert options == {"timeout": 8, "trust_env": False, "follow_redirects": False}
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def post(self, url, **options):
            assert url == "https://api.resend.com/emails"
            assert options["headers"]["Idempotency-Key"] == "stable-key"
            return SimpleNamespace(status_code=status, json=lambda: body, headers={"retry-after": "999999"})
    monkeypatch.setattr(notify.httpx, "AsyncClient", Client)
    result = asyncio.run(notify.deliver({"to": ["buyer@example.test"]}, "stable-key"))
    assert result["state"] == expected
    if "retry_after" in result:
        assert result["retry_after"] <= 3600
