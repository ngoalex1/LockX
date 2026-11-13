"""Independent queue invariants. All evidence, provider usage and clocks are local."""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import credit_wallet as credits
import in_hand
import verification_queue as queue


NOW = 1_800_003_610.0
OWNER = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def clock(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCKX_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LOCKX_CREDITS_ENABLED", "1")
    monkeypatch.setenv("LOCKX_VERIFICATION_QUEUE_ENABLED", "1")
    monkeypatch.setenv("LOCKX_IN_HAND_VISION_MODEL", "gpt-4.1")
    monkeypatch.setenv("LOCKX_VERIFICATION_HOURLY_BUDGET_USD", "100")
    monkeypatch.setenv("LOCKX_VERIFICATION_LEASE_SECONDS", "120")
    monkeypatch.setattr(queue.shutil, "disk_usage", lambda _: SimpleNamespace(free=10**12))
    value = [NOW]
    monkeypatch.setattr(queue.time, "time", lambda: value[0])
    with queue.database() as db:
        queue.schema(db)
    yield value


def reserve():
    return queue.reserve_call("gpt-4.1", "Compare the supplied item.", [], {}, 5000)


def reserve_amount():
    return queue.estimate_micros("gpt-4.1", "Compare the supplied item.", [], {}, 5000)


def seed_spend(amount, created):
    with queue.database() as db:
        db.execute("""INSERT INTO verification_calls
            (id,created,model,price_version,reserved_micros,charged_micros,outcome)
            VALUES (?,?,?,?,?,?,'unknown')""",
            (str(uuid4()), created, "gpt-4.1", queue.PRICE_VERSION, amount, amount))


def queued_inspection():
    request_id, session_id = str(uuid4()), str(uuid4())
    listing = in_hand.Listing(title="Same physical item", consent=True, auto_publish=True).model_dump_json()
    with queue.database() as db:
        db.execute("BEGIN IMMEDIATE")
        credits.entry(db, OWNER, 2, "admin_grant", str(uuid4()))
        db.execute("""INSERT INTO ih_requests
            (id,owner_id,token,listing,status,created,expires,submitted,plan,analysis_status,session_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (request_id, OWNER, str(uuid4()), listing, "processing", NOW-20, NOW+86400, NOW,
             "[]", "decoding", session_id))
        db.execute("""INSERT INTO ih_sessions
            (id,request_id,started,issued,stages,observations,finished)
            VALUES (?,?,?,?,?,?,?)""",
            (session_id, request_id, NOW-10, NOW-10, "[]",
             json.dumps([{"recording_end": True, "recording_seconds": 10}]), NOW))
        db.execute("INSERT INTO ih_scan_sessions(session_id,min_seconds,max_seconds) VALUES (?,?,?)",
                   (session_id, 10, 15))
        in_hand.store_media(db, request_id, "listing", "image/jpeg", b"private-reference")
        in_hand.store_media(db, request_id, "video", "video/mp4", b"private-saved-video")
        credits.bind_check(db, request_id, OWNER)
        credits.reserve_check(db, request_id)
        queue.enqueue(db, request_id)
    return request_id, session_id


def test_rolling_budget_does_not_reset_at_clock_hour_boundary(clock):
    amount = reserve_amount()
    # NOW is ten seconds into a clock hour; this charge is from its previous hour.
    assert NOW % 3600 == 10
    seed_spend(100_000_000 - amount + 1, NOW-30)
    with pytest.raises(queue.AdmissionWait) as blocked:
        reserve()
    assert blocked.value.reason == "budget_limit"
    assert blocked.value.retry_at > NOW


def test_eight_concurrent_reservations_cannot_spend_same_headroom(clock):
    amount = reserve_amount()
    seed_spend(100_000_000 - 2*amount, NOW-20)
    # Remove only pacing from this test so all eight race the financial admission.
    with queue.database() as db:
        db.execute("""CREATE TRIGGER test_ignore_api_pacing AFTER UPDATE OF next_api
            ON verification_control BEGIN
            UPDATE verification_control SET next_api=0 WHERE id=NEW.id; END""")
    def attempt(_):
        try:
            reserve()
            return "admitted"
        except queue.AdmissionWait as error:
            return error.reason
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(8)))
    assert results.count("admitted") == 2
    assert results.count("budget_limit") == 6
    with queue.database() as db:
        total = db.execute("SELECT SUM(charged_micros) FROM verification_calls WHERE created>?",
                           (NOW-3600,)).fetchone()[0]
    assert total == 100_000_000


def test_unknown_call_outcome_keeps_full_reservation(clock):
    amount = reserve_amount()
    seed_spend(100_000_000 - amount, NOW-20)
    call_id = reserve()
    clock[0] += 2
    # A timeout, crash or malformed usage cannot manufacture new headroom.
    queue.record_usage(call_id, None)
    with pytest.raises(queue.AdmissionWait) as blocked:
        reserve()
    assert blocked.value.reason == "budget_limit"
    with queue.database() as db:
        row = db.execute("SELECT * FROM verification_calls WHERE id=?", (call_id,)).fetchone()
    assert row["charged_micros"] == row["reserved_micros"] == amount
    assert row["outcome"] == "unknown"


def test_usage_can_settle_known_cost_but_not_release_unknown_calls(clock):
    first = reserve()
    clock[0] += 2
    second = reserve()
    queue.record_usage(first, {"input_tokens": 20_000, "output_tokens": 2_000})
    with queue.database() as db:
        rows = {row["id"]: dict(row) for row in db.execute("SELECT * FROM verification_calls")}
    assert rows[first]["charged_micros"] == 56_000
    assert rows[first]["outcome"] == "known_usage"
    assert rows[second]["charged_micros"] == rows[second]["reserved_micros"]


def test_budget_reopens_only_after_previous_reservation_leaves_rolling_window(clock):
    seed_spend(100_000_000, NOW-3599)
    with pytest.raises(queue.AdmissionWait):
        reserve()
    clock[0] += 2
    assert reserve()


def test_reclaimed_job_rejects_stale_heartbeat_and_terminal_refund(clock):
    request_id, _ = queued_inspection()
    first = queue.claim_job("first-worker")
    assert first and first["request_id"] == request_id
    clock[0] += 121
    second = queue.claim_job("replacement-worker")
    assert second and second["id"] == first["id"] and second["fence"] > first["fence"]
    with queue.database() as db:
        with pytest.raises(queue.LeaseLost):
            queue.ensure_current(db, first)
    with pytest.raises(queue.LeaseLost):
        queue.heartbeat(first)
    assert queue.finish_job(first, RuntimeError("late failure")) is False
    with queue.database() as db:
        job = db.execute("SELECT * FROM verification_jobs WHERE id=?", (first["id"],)).fetchone()
        check = db.execute("SELECT state FROM credit_checks WHERE request_id=?", (request_id,)).fetchone()
        restored = db.execute("SELECT COUNT(*) FROM credit_ledger WHERE kind='technical_refund'").fetchone()[0]
    assert job["state"] == "running" and job["lease_owner"] == "replacement-worker"
    assert check["state"] == "reserved" and restored == 0


def test_reference_tampering_is_detected_even_if_attacker_updates_stored_hash(clock):
    request_id, _ = queued_inspection()
    claim = queue.claim_job("worker")
    replacement = b"a different item reference"
    with queue.database() as db:
        db.execute("UPDATE ih_media SET content=?,sha256=? WHERE request_id=? AND role='listing'",
                   (replacement, hashlib.sha256(replacement).hexdigest(), request_id))
    with queue.database() as db:
        with pytest.raises(ValueError, match="evidence"):
            queue.ensure_current(db, claim)


def test_session_swap_invalidates_previous_saved_evidence_claim(clock):
    request_id, _ = queued_inspection()
    claim = queue.claim_job("worker")
    with queue.database() as db:
        db.execute("UPDATE ih_requests SET session_id=? WHERE id=?", (str(uuid4()), request_id))
    with queue.database() as db:
        with pytest.raises(queue.LeaseLost):
            queue.ensure_current(db, claim)


def test_public_and_admin_queue_status_do_not_disclose_tokens_email_or_evidence(clock):
    request_id, _ = queued_inspection()
    with queue.database() as db:
        public = queue.public_status(db, request_id)
    combined = json.dumps({"public": public, "admin": queue.admin_status()})
    for private in (OWNER, "private-reference", "private-saved-video", "manifest", "lease_owner", "sha256", "access_token", "email"):
        assert private not in combined


def test_changed_reference_terminates_without_publication_and_restores_only_once(clock):
    request_id, _ = queued_inspection()
    claim = queue.claim_job("worker")
    with queue.database() as db:
        db.execute("UPDATE ih_media SET content=? WHERE request_id=? AND role='listing'",
                   (b"tampered after enqueue", request_id))
    with queue.database() as db:
        with pytest.raises(ValueError) as changed:
            queue.ensure_current(db, claim)
    assert queue.finish_job(claim, changed.value) is True
    assert queue.finish_job(claim, changed.value) is False
    with queue.database() as db:
        row = db.execute("SELECT status,analysis_status FROM ih_requests WHERE id=?", (request_id,)).fetchone()
        wallet = db.execute("SELECT balance FROM credit_wallets WHERE owner_id=?", (OWNER,)).fetchone()
        restores = db.execute("SELECT COUNT(*) FROM credit_ledger WHERE kind='technical_refund'").fetchone()[0]
        published = db.execute("SELECT COUNT(*) FROM ih_publications WHERE request_id=?", (request_id,)).fetchone()[0]
    assert row["status"] == "inconclusive" and row["analysis_status"] == "failed"
    assert wallet["balance"] == 2 and restores == 1 and published == 0


def test_new_default_model_does_not_change_already_pinned_evidence(clock, monkeypatch):
    request_id, _ = queued_inspection()
    claim = queue.claim_job("worker")
    assert json.loads(claim["manifest"])["model"] == "gpt-4.1"
    monkeypatch.setenv("LOCKX_IN_HAND_VISION_MODEL", "gpt-4.1-2025-04-14")
    with queue.database() as db:
        # A deployment configuration change must not rewrite or invalidate the
        # original model selection for immutable, already accepted evidence.
        queue.ensure_current(db, claim)
    token = queue.CURRENT_CLAIM.set(claim)
    try:
        assert queue.worker_model() == "gpt-4.1"
    finally:
        queue.CURRENT_CLAIM.reset(token)


def test_old_cleanup_does_not_fail_a_live_durable_worker(clock):
    request_id, _ = queued_inspection()
    claim = queue.claim_job("worker")
    with queue.database() as db:
        db.execute("UPDATE ih_requests SET submitted=?,analysis_status='decoding' WHERE id=?",
                   (NOW-601, request_id))
        in_hand.cleanup_scan_media(db, NOW)
    with queue.database() as db:
        row = db.execute("SELECT analysis_status FROM ih_requests WHERE id=?", (request_id,)).fetchone()
        state = db.execute("SELECT state FROM credit_checks WHERE request_id=?", (request_id,)).fetchone()[0]
        queue.ensure_current(db, claim)
    assert row["analysis_status"] == "decoding" and state == "reserved"


def test_late_model_worker_cannot_change_reclaimed_analysis_or_restore_credit(clock, monkeypatch):
    request_id, _ = queued_inspection()
    stale = queue.claim_job("stale-worker")
    clock[0] += 121
    fresh = queue.claim_job("fresh-worker")
    assert fresh["fence"] > stale["fence"]
    with queue.database() as db:
        db.execute("UPDATE ih_requests SET analysis_status='pending' WHERE id=?", (request_id,))
    def no_provider(*args, **kwargs):
        raise AssertionError("A stale lease must never call the provider")
    monkeypatch.setattr(in_hand, "vision_call", no_provider)
    monkeypatch.setattr(in_hand, "visual_ready", lambda: True)
    token = queue.CURRENT_CLAIM.set(stale)
    try:
        with pytest.raises(queue.LeaseLost):
            in_hand.analyze(request_id, queue_claim=stale)
    finally:
        queue.CURRENT_CLAIM.reset(token)
    with queue.database() as db:
        row = db.execute("SELECT analysis_status FROM ih_requests WHERE id=?", (request_id,)).fetchone()
        state = db.execute("SELECT state FROM credit_checks WHERE request_id=?", (request_id,)).fetchone()[0]
        assert db.execute("SELECT COUNT(*) FROM ih_publications WHERE request_id=?", (request_id,)).fetchone()[0] == 0
    assert row["analysis_status"] == "pending" and state == "reserved"


def matching_assessment():
    return in_hand.VisualAssessment(
        same_item="supported", distinguishing_details=["Distinct edge scratch", "Separate surface marking"],
        challenge_actions="followed", continuity="consistent",
        photos=[{"photo_index": 0, "finding": "supported", "evidence": "Both individual details agree.", "frame_indices": [0]}],
        claims=[], concerns=[], summary="Visible individual details correspond.", identifier_checks=[])


def comparison_ready(request_id):
    with queue.database() as db:
        in_hand.store_media(db, request_id, "frame", "image/jpeg", b"private-derived-frame", 1.0, "Evidence frame")
        db.execute("UPDATE ih_requests SET analysis_status='pending',analysis=? WHERE id=?",
                   (json.dumps({"video": {"notes": []}}), request_id))


def test_model_response_after_lease_reclaim_cannot_commit_a_match(clock, monkeypatch):
    request_id, _ = queued_inspection()
    stale = queue.claim_job("old-model-worker")
    comparison_ready(request_id)
    monkeypatch.setattr(in_hand, "visual_ready", lambda: True)
    monkeypatch.setattr(in_hand, "prepare_exports", lambda *args: None)
    monkeypatch.setattr(in_hand, "select_evidence_frames", lambda *args: ([0], {"selected_frame_indices": [0]}))
    replacement = []
    def delayed_result(*args, **kwargs):
        clock[0] += 121
        replacement.append(queue.claim_job("new-model-worker"))
        return matching_assessment()
    monkeypatch.setattr(in_hand, "vision_call", delayed_result)
    token = queue.CURRENT_CLAIM.set(stale)
    try:
        with pytest.raises(queue.LeaseLost):
            in_hand.analyze(request_id, queue_claim=stale)
    finally:
        queue.CURRENT_CLAIM.reset(token)
    assert replacement[0]["fence"] > stale["fence"]
    with queue.database() as db:
        request = db.execute("SELECT analysis_status,status FROM ih_requests WHERE id=?", (request_id,)).fetchone()
        check = db.execute("SELECT state FROM credit_checks WHERE request_id=?", (request_id,)).fetchone()[0]
        assert db.execute("SELECT COUNT(*) FROM ih_publications WHERE request_id=?", (request_id,)).fetchone()[0] == 0
    assert request["analysis_status"] != "complete" and request["status"] != "confirmed"
    assert check == "reserved"


def test_evidence_changed_during_model_call_cannot_commit_a_match(clock, monkeypatch):
    request_id, _ = queued_inspection()
    claim = queue.claim_job("model-worker")
    comparison_ready(request_id)
    monkeypatch.setattr(in_hand, "visual_ready", lambda: True)
    monkeypatch.setattr(in_hand, "prepare_exports", lambda *args: None)
    monkeypatch.setattr(in_hand, "select_evidence_frames", lambda *args: ([0], {"selected_frame_indices": [0]}))
    def delayed_result(*args, **kwargs):
        content = b"different evidence during model call"
        with queue.database() as db:
            db.execute("UPDATE ih_media SET content=?,sha256=? WHERE request_id=? AND role='listing'",
                       (content, hashlib.sha256(content).hexdigest(), request_id))
        return matching_assessment()
    monkeypatch.setattr(in_hand, "vision_call", delayed_result)
    token = queue.CURRENT_CLAIM.set(claim)
    try:
        with pytest.raises(ValueError, match="evidence") as changed:
            in_hand.analyze(request_id, queue_claim=claim)
    finally:
        queue.CURRENT_CLAIM.reset(token)
    queue.finish_job(claim, changed.value)
    with queue.database() as db:
        request = db.execute("SELECT analysis_status,status FROM ih_requests WHERE id=?", (request_id,)).fetchone()
        assert db.execute("SELECT COUNT(*) FROM ih_publications WHERE request_id=?", (request_id,)).fetchone()[0] == 0
    assert request["analysis_status"] == "failed" and request["status"] == "inconclusive"


def test_render_finishing_after_lease_reclaim_cannot_publish(clock, monkeypatch):
    request_id, _ = queued_inspection()
    stale = queue.claim_job("old-render-worker")
    comparison_ready(request_id)
    with queue.database() as db:
        analysis = {"video": {"notes": [], "frame_selection": {"selected_frame_indices": [0]}},
                    "visual": matching_assessment().model_dump(), "result": "confirmed"}
        db.execute("UPDATE ih_requests SET status='confirmed',analysis_status='complete',analysis=? WHERE id=?",
                   (json.dumps(analysis), request_id))
        credits.settle_check(db, request_id)
    def delayed_render(*args, **kwargs):
        clock[0] += 121
        fresh = queue.claim_job("new-render-worker")
        assert fresh["fence"] > stale["fence"]
        return "unpublished-render-id", {0: b"unpublished-qr-photo"}
    monkeypatch.setattr(in_hand, "render_publication", delayed_render)
    with queue.database() as db:
        row = db.execute("SELECT * FROM ih_requests WHERE id=?", (request_id,)).fetchone()
        with pytest.raises(queue.LeaseLost):
            in_hand.publish_confirmed_photos(db, row, queue_claim=stale)
    with queue.database() as db:
        assert db.execute("SELECT COUNT(*) FROM ih_publications WHERE request_id=?", (request_id,)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM ih_media WHERE request_id=? AND role='marked'", (request_id,)).fetchone()[0] == 0
        assert db.execute("SELECT state FROM credit_checks WHERE request_id=?", (request_id,)).fetchone()[0] == "consumed"


def test_known_usage_releases_waiting_jobs_before_reservation_hour_expires(clock):
    first_id, _ = queued_inspection()
    first = queue.claim_job("first-worker")
    waiting_id, _ = queued_inspection()
    waiting = queue.claim_job("waiting-worker")
    assert first["request_id"] == first_id and waiting["request_id"] == waiting_id
    seed_spend(94_500_000, NOW-20)
    token = queue.CURRENT_CLAIM.set(first)
    try:
        call_id = reserve()
    finally:
        queue.CURRENT_CLAIM.reset(token)
    clock[0] += 2
    token = queue.CURRENT_CLAIM.set(waiting)
    try:
        with pytest.raises(queue.AdmissionWait) as full:
            reserve()
    finally:
        queue.CURRENT_CLAIM.reset(token)
    assert full.value.reason == "budget_limit"
    assert queue.finish_job(waiting, full.value)
    # Settling a successful, already admitted call frees enough spending
    # capacity. Jobs should recheck now rather than sleeping for an hour.
    queue.record_usage(call_id, {"input_tokens": 20_000, "output_tokens": 2_000})
    resumed = queue.claim_job("resumed-worker")
    assert resumed and resumed["request_id"] == waiting_id


def test_recovered_publication_cannot_be_abandoned_as_completed_queue_work(clock, monkeypatch):
    import verification_worker
    request_id, _ = queued_inspection()
    lost = queue.claim_job("crashed-publication-worker")
    comparison_ready(request_id)
    with queue.database() as db:
        analysis = {"video": {"notes": [], "frame_selection": {"selected_frame_indices": [0]}},
                    "visual": matching_assessment().model_dump(), "result": "confirmed"}
        db.execute("UPDATE ih_requests SET status='confirmed',analysis_status='complete',analysis=? WHERE id=?",
                   (json.dumps(analysis), request_id))
        credits.settle_check(db, request_id)
        # The prior worker started rendering just after its final lease renewal.
        db.execute("INSERT INTO ih_publication_jobs VALUES (?,'processing',1,?)", (request_id, NOW+1))
    clock[0] += 120.5
    assert clock[0] > lost["lease_until"]
    monkeypatch.setattr(in_hand, "render_publication", lambda *args: ("recovered-publication", {0: b"recovered-qr"}))
    assert verification_worker.run_once("replacement-publication-worker")
    with queue.database() as db:
        job = db.execute("SELECT state FROM verification_jobs WHERE request_id=?", (request_id,)).fetchone()[0]
        publication = db.execute("SELECT state FROM ih_publication_jobs WHERE request_id=?", (request_id,)).fetchone()[0]
    # A completed durable job will not be rescheduled by subsequent result GETs.
    # It must not leave the export in an unrecoverable pending state.
    assert not (job == "completed" and publication in {"pending", "processing"})


def partial_comparison_with_old_consent(state):
    request_id, session_id = queued_inspection()
    with queue.database() as db:
        in_hand.store_media(db, request_id, "listing", "image/jpeg", b"second-private-reference")
        db.execute("UPDATE verification_jobs SET manifest=? WHERE request_id=?",
                   (json.dumps(queue.evidence_manifest(db, request_id)), request_id))
    claim = queue.claim_job("comparison-worker")
    comparison_ready(request_id)
    assessment = matching_assessment().model_dump()
    assessment["same_item"] = "inconclusive"
    assessment["photos"].append({"photo_index": 1, "finding": "not_established",
                                 "evidence": "This view was not established.", "frame_indices": [0]})
    with queue.database() as db:
        analysis = {"visual": assessment, "result": "inconclusive",
                    "video": {"notes": [], "frame_selection": {"selected_frame_indices": [0]}}}
        db.execute("UPDATE ih_requests SET analysis_status='complete',status='inconclusive',analysis=? WHERE id=?",
                   (json.dumps(analysis), request_id))
        credits.settle_check(db, request_id)
        token = db.execute("SELECT token FROM ih_requests WHERE id=?", (request_id,)).fetchone()[0]
        if state == "queued":
            db.execute("UPDATE verification_jobs SET state='queued',lease_owner=NULL,lease_until=NULL WHERE id=?",
                       (claim["id"],))
    if state == "completed":
        assert queue.finish_job(claim)
    return request_id, session_id, token, claim


def consent_client():
    app = FastAPI()
    app.include_router(in_hand.create_router(lambda authorization: OWNER))
    return TestClient(app)


def approve_subset(client, token):
    return client.post("/api/v1/in-hand/seller/" + token + "/enable-matched-photos",
                       json={"publish_matched_photos": True, "consent": True})


@pytest.mark.parametrize("state", ["queued", "running", "completed"])
def test_subset_consent_requeues_publication_only_without_ai_or_new_debit(clock, monkeypatch, state):
    import verification_worker
    request_id, _, token, previous = partial_comparison_with_old_consent(state)
    if state == "completed":
        clock[0] += 3600  # Approval time must not replace the earlier capture time.
    with queue.database() as db:
        original_media = [tuple(row) for row in db.execute(
            "SELECT id,role,content,sha256 FROM ih_media WHERE request_id=? ORDER BY rowid", (request_id,))]
        balance = db.execute("SELECT balance FROM credit_wallets WHERE owner_id=?", (OWNER,)).fetchone()[0]
    def no_comparison(*args, **kwargs):
        raise AssertionError("Publication consent must never rerun the AI assessment")
    monkeypatch.setattr(in_hand, "vision_call", no_comparison)
    monkeypatch.setattr(in_hand, "render_publication", lambda *args: ("approved-subset-publication", {0: b"approved-photo"}))
    with consent_client() as client:
        response = approve_subset(client, token)
        assert response.status_code == 200, response.text
        assert response.json()["queue"]["state"] == "queued"
        with queue.database() as db:
            job = dict(db.execute("SELECT * FROM verification_jobs WHERE request_id=?", (request_id,)).fetchone())
            request = db.execute("SELECT listing,analysis_status FROM ih_requests WHERE id=?", (request_id,)).fetchone()
        assert job["fence"] > previous["fence"] and job["lease_owner"] is None
        assert request["analysis_status"] == "complete"
        assert json.loads(request["listing"])["publish_matched_photos"] is True
        assert json.loads(job["manifest"])["captured_at"] == NOW
        # A repeat approval does not reset the lease generation or enqueue twice.
        assert approve_subset(client, token).status_code == 200
        with queue.database() as db:
            repeated = db.execute("SELECT fence,queued_at FROM verification_jobs WHERE id=?", (job["id"],)).fetchone()
            with pytest.raises(queue.LeaseLost):
                queue.ensure_current(db, previous)
        assert repeated["fence"] == job["fence"] and repeated["queued_at"] == job["queued_at"]
    assert verification_worker.run_once("publication-only-worker")
    with queue.database() as db:
        assert db.execute("SELECT state FROM verification_jobs WHERE request_id=?", (request_id,)).fetchone()[0] == "completed"
        assert db.execute("SELECT balance FROM credit_wallets WHERE owner_id=?", (OWNER,)).fetchone()[0] == balance
        assert db.execute("SELECT state FROM credit_checks WHERE request_id=?", (request_id,)).fetchone()[0] == "consumed"
        assert db.execute("SELECT COUNT(*) FROM credit_ledger WHERE kind='verification'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM verification_calls").fetchone()[0] == 0
        assert [row[0] for row in db.execute("SELECT photo_index FROM ih_publication_photos")] == [0]
        retained = [tuple(row) for row in db.execute(
            "SELECT id,role,content,sha256 FROM ih_media WHERE request_id=? AND role!='marked' ORDER BY rowid", (request_id,))]
    assert retained == original_media


@pytest.mark.parametrize("tamper", ["listing", "media"])
def test_publication_consent_cannot_reseal_changed_item_evidence(clock, tamper):
    request_id, _, token, _ = partial_comparison_with_old_consent("completed")
    with queue.database() as db:
        before = dict(db.execute("SELECT * FROM verification_jobs WHERE request_id=?", (request_id,)).fetchone())
        if tamper == "listing":
            listing = json.loads(db.execute("SELECT listing FROM ih_requests WHERE id=?", (request_id,)).fetchone()[0])
            listing["description"] = "A different item claim after comparison"
            db.execute("UPDATE ih_requests SET listing=? WHERE id=?", (json.dumps(listing), request_id))
        else:
            replacement = b"a different reference with an updated stored hash"
            db.execute("UPDATE ih_media SET content=?,sha256=? WHERE request_id=? AND role='listing'",
                       (replacement, hashlib.sha256(replacement).hexdigest(), request_id))
    with consent_client() as client:
        result = approve_subset(client, token)
    assert result.status_code == 409, result.text
    with queue.database() as db:
        after = dict(db.execute("SELECT * FROM verification_jobs WHERE request_id=?", (request_id,)).fetchone())
        listing = json.loads(db.execute("SELECT listing FROM ih_requests WHERE id=?", (request_id,)).fetchone()[0])
    assert after == before and listing["publish_matched_photos"] is False


def test_publication_consent_cannot_revive_a_withdrawn_record(clock):
    request_id, _, token, _ = partial_comparison_with_old_consent("completed")
    with queue.database() as db:
        db.execute("INSERT INTO ih_publications VALUES (?,?,?,?)", ("withdrawn-publication", request_id, NOW, NOW))
    with consent_client() as client:
        result = approve_subset(client, token)
    assert result.status_code == 409
    with queue.database() as db:
        assert db.execute("SELECT state FROM verification_jobs WHERE request_id=?", (request_id,)).fetchone()[0] == "completed"
        assert db.execute("SELECT revoked FROM ih_publications WHERE request_id=?", (request_id,)).fetchone()[0] == NOW

