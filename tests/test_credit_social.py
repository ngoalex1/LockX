import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

import credit_admin
import credit_social as social
import credit_wallet as credits

NOW = datetime(2026, 11, 13, 20, tzinfo=timezone.utc).timestamp()
ALICE = "11111111-1111-4111-8111-111111111111"
BOB = "22222222-2222-4222-8222-222222222222"
AUTH = {"Authorization": "Bearer alice"}
BASE = "/api/v1/credits/traffic"


def current_user(authorization: str | None = Header(default=None)):
    if authorization not in {"Bearer alice", "Bearer bob"}:
        raise HTTPException(401, "Sign in")
    return ALICE if authorization == "Bearer alice" else BOB


def identity(owner=Depends(current_user)):
    return {"id": owner, "user_metadata": {"is_admin": True}}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCKX_DATA_DIR", str(tmp_path))
    for key, value in {"LOCKX_CREDITS_ENABLED": "1", "PAYPAL_ENVIRONMENT": "sandbox",
                       "PAYPAL_CLIENT_ID": "client", "PAYPAL_CLIENT_SECRET": "secret",
                       "PAYPAL_MERCHANT_ID": "MERCHANT", "PAYPAL_WEBHOOK_ID": "hook",
                       "LOCKX_PAYPAL_LINKS_VALIDATED": "1", "LOCKX_CREDIT_ADMIN_IDS": ALICE}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(social, "limited", lambda *_: None)
    monkeypatch.setattr("lost_found.limited", lambda *_: None)
    def fake_provider(*args, **kwargs):
        resource = "PLB-" + str(uuid4())
        return {"id": resource, "links": [{"rel": "payment_link", "href": "https://www.sandbox.paypal.com/ncp/payment/" + resource}]}
    monkeypatch.setattr(credits, "paypal_call", fake_provider)
    with credits.database():
        pass
    app = FastAPI()
    app.include_router(social.create_router(current_user))
    app.include_router(credits.create_router(current_user))
    app.include_router(credit_admin.create_router(identity))
    with TestClient(app) as result:
        yield result


@pytest.fixture
def clock(monkeypatch):
    value = [NOW]
    monkeypatch.setattr(social.time, "time", lambda: value[0])
    return value


def visit(client, **fields):
    result = client.post(BASE + "/visits", json={"source": "instagram", "medium": "social", "campaign": "launch", **fields})
    assert result.status_code == 201, result.text
    return result.json()["visit_id"]


def checkout(client, visit_id=None, request_key=None):
    payload = {"pack_id": "regular", "request_key": request_key or str(uuid4())}
    if visit_id:
        payload["marketing_visit_id"] = visit_id
    result = client.post("/api/v1/credits/checkouts", headers=AUTH, json=payload)
    assert result.status_code == 201, result.text
    return result.json()


def paid(checkout_id, payment_id=None):
    with credits.database() as db:
        db.execute("BEGIN IMMEDIATE")
        credits.grant_purchase(db, checkout_id, payment_id or str(uuid4()), 500, "USD", "MERCHANT")


def inspection(owner=ALICE, status="confirmed", analysis="complete", submitted=True, created=None):
    request_id = str(uuid4())
    with credits.database() as db:
        db.execute("""INSERT INTO ih_requests
            (id,owner_id,token,listing,status,created,expires,submitted,plan,analysis_status)
            VALUES (?,?,?,?,?,?,?,?,?,?)""", (request_id, owner, str(uuid4()), "{}", status,
            social.time.time() if created is None else created, NOW + 999999,
            social.time.time() if submitted else None, "{}", analysis))
    return request_id


def link_inspection(client, visit_id, request_id, headers=AUTH):
    return client.post(BASE + "/verifications", headers=headers,
                       json={"visit_id": visit_id, "request_id": request_id})


def test_visit_uses_server_id_time_and_only_normalized_labels(client, clock):
    result = client.post(BASE + "/visits", json={"source": " Instagram ", "medium": "Social", "campaign": "Summer Launch", "content": "Story_1"})
    assert result.status_code == 201
    body = result.json()
    assert body["created"] == NOW and body["expires_at"] == NOW + 86400
    with credits.database() as db:
        row = dict(db.execute("SELECT * FROM marketing_visits").fetchone())
    assert row == {"id": body["visit_id"], "created": NOW, "source": "instagram", "medium": "social",
                   "campaign": "summer-launch", "content": "story_1"}
    assert result.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("payload", [{"source": "https://instagram.com/person?email=x"}, {"campaign": "a@example.test"},
    {"content": "127.0.0.1"}, {"source": "x" * 81}, {"campaign": "x" * 81}, {"content": "x" * 121},
    {"email": "private@example.test"}, {"referrer": "https://example.test"}, {"created": 1}, {"visit_id": str(uuid4())}])
def test_visit_rejects_personal_urls_and_client_identity_time(client, payload):
    assert client.post(BASE + "/visits", json=payload).status_code == 422


def test_ingest_is_rate_limited(client, monkeypatch):
    def reject(*args):
        raise HTTPException(429, "Rate limit")
    monkeypatch.setattr(social, "limited", reject)
    assert client.post(BASE + "/visits", json={}).status_code == 429
    assert client.post(BASE + "/events", json={"visit_id": str(uuid4()), "event": "verify_click"}).status_code == 429


def test_events_deduplicate_and_expire_only_for_new_events(client, clock):
    identifier = visit(client)
    payload = {"visit_id": identifier, "event": "verify_click"}
    assert client.post(BASE + "/events", json=payload).status_code == 201
    assert client.post(BASE + "/events", json=payload).json()["duplicated"]
    clock[0] += 86401
    assert client.post(BASE + "/events", json=payload).json()["duplicated"]
    assert client.post(BASE + "/events", json={**payload, "event": "wallet_open"}).status_code == 410
    assert client.post(BASE + "/events", json={**payload, "visit_id": str(uuid4())}).status_code == 404
    assert client.post(BASE + "/events", json={**payload, "event": "payment_completed"}).status_code == 422
    with credits.database() as db:
        assert db.execute("SELECT COUNT(*) FROM marketing_events").fetchone()[0] == 1


def test_future_visits_cannot_receive_new_events(client, clock):
    identifier = visit(client)
    clock[0] -= 1
    assert client.post(BASE + "/events", json={"visit_id": identifier, "event": "verify_click"}).status_code == 410


def test_verification_mapping_requires_owner_and_cannot_be_reattributed(client, clock):
    first = visit(client); second = visit(client, source="tiktok")
    record = inspection()
    assert link_inspection(client, first, record, headers={}).status_code == 401
    assert link_inspection(client, first, record, headers={"Authorization": "Bearer bob"}).status_code == 404
    assert link_inspection(client, first, record).status_code == 201
    assert link_inspection(client, first, record).json()["duplicated"]
    assert link_inspection(client, second, record).status_code == 409
    clock[0] += 86401
    assert link_inspection(client, first, record).json()["duplicated"]


def test_verification_backfill_unknown_and_expired_visits_rejected(client, clock):
    old = inspection(created=NOW - 1)
    identifier = visit(client)
    assert link_inspection(client, identifier, old).status_code == 409
    assert link_inspection(client, str(uuid4()), inspection()).status_code == 404
    clock[0] += 86401
    assert link_inspection(client, identifier, inspection()).status_code == 410


def test_checkout_attribution_is_atomic_idempotent_and_never_reattributed(client, clock):
    first = visit(client); second = visit(client, source="tiktok")
    key = str(uuid4())
    purchase = checkout(client, first, key)
    assert checkout(client, second, key)["id"] == purchase["id"]
    with credits.database() as db:
        rows = db.execute("SELECT * FROM marketing_checkouts").fetchall()
        assert len(rows) == 1 and rows[0]["visit_id"] == first
    assert social.analytics(7)["summary"]["checkout_starts"] == 1


def test_unmapped_checkout_replay_can_link_only_an_earlier_valid_visit(client, clock):
    first = visit(client)
    key = str(uuid4()); purchase = checkout(client, request_key=key)
    assert checkout(client, first, key)["id"] == purchase["id"]
    other_key = str(uuid4()); old = checkout(client, request_key=other_key)
    clock[0] += 1
    later = visit(client, source="tiktok")
    checkout(client, later, other_key)
    with credits.database() as db:
        assert db.execute("SELECT visit_id FROM marketing_checkouts WHERE checkout_id=?", (purchase["id"],)).fetchone()[0] == first
        assert not db.execute("SELECT 1 FROM marketing_checkouts WHERE checkout_id=?", (old["id"],)).fetchone()


def test_invalid_expired_optional_visit_does_not_block_real_checkout(client, clock):
    checkout(client, str(uuid4()))
    identifier = visit(client)
    clock[0] += 86401
    checkout(client, identifier)
    with credits.database() as db:
        assert db.execute("SELECT COUNT(*) FROM credit_checkouts").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM marketing_checkouts").fetchone()[0] == 0


def test_sales_require_paid_canonical_records_free_grants_and_client_claims_do_not_count(client, clock):
    first = visit(client); second = visit(client, source="tiktok")
    client.post(BASE + "/events", json={"visit_id": first, "event": "verify_click"})
    client.post(BASE + "/events", json={"visit_id": first, "event": "wallet_open"})
    purchase = checkout(client, first)
    checkout(client, second)  # unpaid
    paid(purchase["id"], "paid-first"); paid(purchase["id"], "paid-second")
    with credits.database() as db:
        credits.entry(db, ALICE, 1000, "admin_grant", "free-credits")
    for status, analysis, submitted in [("confirmed", "complete", True), ("mismatch", "complete", True),
                                         ("inconclusive", "failed", True), ("waiting", "pending", False)]:
        assert link_inspection(client, first, inspection(status=status, analysis=analysis, submitted=submitted)).status_code == 201
    result = social.analytics(7)
    summary = result["summary"]
    assert {key: summary[key] for key in social.METRICS} == {
        "visits": 2, "verify_clicks": 1, "wallet_opens": 1, "checkout_starts": 2,
        "paying_visits": 1, "payments_count": 2, "gross_sales_cents": 1000,
        "verifications_submitted": 3, "verifications_completed": 2, "verifications_matched": 1}
    assert summary["payment_conversion_rate"] == .5
    assert result["daily"][-1]["gross_sales_cents"] == 1000
    assert result["tracking_since"] == NOW
    assert len(result["sources"]) == len(result["campaigns"]) == 2
    assert ALICE not in json.dumps(result) and first not in json.dumps(result)


def test_utc_visit_cohort_and_later_payment_outcomes(client, clock):
    since = datetime(2026, 11, 7, tzinfo=timezone.utc).timestamp()
    clock[0] = since - 1
    old = visit(client); old_checkout = checkout(client, old); paid(old_checkout["id"])
    clock[0] = since
    included = visit(client); new_checkout = checkout(client, included)
    clock[0] = NOW
    paid(new_checkout["id"])
    future = visit(client)
    with credits.database() as db:
        db.execute("UPDATE marketing_visits SET created=? WHERE id=?", (NOW + 1, future))
    result = social.analytics(7)
    assert result["start"] == "2026-11-07" and result["summary"]["visits"] == 1
    assert result["summary"]["gross_sales_cents"] == 500
    assert result["daily"][0]["gross_sales_cents"] == 500
    assert result["daily"][-1]["gross_sales_cents"] == 0
    assert social.analytics(30)["summary"]["gross_sales_cents"] == 1000


def test_social_empty_history_reports_zero_and_no_invented_conversion(client, clock):
    result = social.analytics(30)
    assert result["tracking_since"] is None
    assert result["summary"]["payment_conversion_rate"] is None
    assert all(result["summary"][key] == 0 for key in social.METRICS)
    assert len(result["daily"]) == 30 and result["sources"] == result["campaigns"] == []


def test_private_social_report_requires_admin_and_bounded_period(client, clock):
    path = "/api/v1/credits/admin/social"
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"Authorization": "Bearer bob"}).status_code == 403
    result = client.get(path + "?days=7", headers=AUTH)
    assert result.status_code == 200 and result.json()["days"] == 7
    assert result.headers["cache-control"] == "private, no-store"
    assert client.get(path + "?days=14", headers=AUTH).status_code == 422


@pytest.mark.parametrize("days", [0, 8, 365])
def test_social_unbounded_ranges_rejected(days):
    with pytest.raises(ValueError):
        social.analytics(days)
