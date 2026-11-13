"""Admin grants are authorization-scoped and atomic; no test reaches the network."""
import sys
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

import credit_admin as admin
import credit_wallet as credits

ADMIN = "11111111-1111-4111-8111-111111111111"
OTHER_ADMIN = "22222222-2222-4222-8222-222222222222"
RECIPIENT = "33333333-3333-4333-8333-333333333333"
MEMBER = "44444444-4444-4444-8444-444444444444"
AUTH = {"Authorization": "Bearer admin"}
EMAIL = "recipient@example.test"


def identity(authorization: str | None = Header(default=None)):
    if authorization == "Bearer admin":
        return {"id": ADMIN, "email": "admin@example.test"}
    if authorization == "Bearer other-admin":
        return {"id": OTHER_ADMIN}
    if authorization == "Bearer member":
        return {"id": MEMBER, "email": "admin@example.test", "role": "service_role",
                "user_metadata": {"is_admin": True, "role": "admin", "id": ADMIN}}
    raise HTTPException(401, "Sign in")


def body(**changes):
    return {"email": EMAIL, "credits": 1000, "reason": "Approved complimentary credits",
            "request_key": str(uuid4()), **changes}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCKX_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LOCKX_CREDIT_ADMIN_IDS", ADMIN + ", " + OTHER_ADMIN)
    monkeypatch.setenv("SUPABASE_URL", "https://auth.example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-service-key")
    monkeypatch.setattr(admin.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("Unexpected account-directory network request")))
    app = FastAPI()
    app.include_router(admin.create_router(identity))
    with TestClient(app, raise_server_exceptions=False) as result:
        yield result


@pytest.fixture
def recipient(monkeypatch):
    calls = []
    def lookup(email):
        calls.append(email)
        return {"id": RECIPIENT, "email": email}
    monkeypatch.setattr(admin, "lookup_user", lookup)
    return calls


def db_state():
    with credits.database() as db:
        admin.schema(db)
        return {"balance": db.execute("SELECT balance FROM credit_wallets WHERE owner_id=?", (RECIPIENT,)).fetchone(),
                "audit": [dict(row) for row in db.execute("SELECT * FROM credit_admin_grants")],
                "ledger": [dict(row) for row in db.execute("SELECT * FROM credit_ledger")],
                "payments": db.execute("SELECT COUNT(*) FROM credit_payments").fetchone()[0]}


@pytest.mark.parametrize("path,method", [("/access", "get"), ("/users?email=" + EMAIL, "get"),
                                       ("/grants", "get"), ("/grants", "post"), ("/analytics", "get")])
def test_all_routes_require_verified_admin_id(client, path, method):
    args = {"json": body()} if method == "post" else {}
    route = "/api/v1/credits/admin" + path
    assert getattr(client, method)(route, **args).status_code == 401
    # Admin-looking email, role and writable metadata cannot replace the allowlisted ID.
    assert getattr(client, method)(route, headers={"Authorization": "Bearer member"}, **args).status_code == 403


def test_admin_access_requires_current_server_allowlist(client, monkeypatch):
    result = client.get("/api/v1/credits/admin/access", headers=AUTH)
    assert result.status_code == 200 and result.json() == {"is_admin": True}
    assert result.headers["cache-control"] == "private, no-store"
    monkeypatch.setenv("LOCKX_CREDIT_ADMIN_IDS", "not-a-uuid," + MEMBER)
    assert client.get("/api/v1/credits/admin/access", headers=AUTH).status_code == 403


def test_grant_adds_1000_preserves_existing_credits_and_audits_once(client, recipient):
    with credits.database() as db:
        credits.entry(db, RECIPIENT, 2, "purchase", "existing-paid-payment")
    request = body(email=" Recipient@Example.Test ")
    result = client.post("/api/v1/credits/admin/grants", headers=AUTH, json=request)
    assert result.status_code == 201, result.text
    grant = result.json()
    assert grant["balance"] == 1002 and grant["credits"] == 1000 and not grant["duplicated"]
    assert grant["email"] == EMAIL and grant["admin_id"] == ADMIN and grant["owner_id"] == RECIPIENT
    state = db_state()
    assert len(state["audit"]) == 1 and state["audit"][0]["reason"] == request["reason"]
    assert state["audit"][0]["request_key"] == request["request_key"]
    assert [(row["kind"], row["delta"]) for row in state["ledger"]] == [("purchase", 2), ("admin_grant", 1000)]
    assert state["ledger"][1]["reference"] == grant["grant_id"]
    assert state["payments"] == 0, "A complimentary grant must not invent a PayPal payment."


def test_replayed_grant_is_idempotent_even_if_directory_later_fails(client, recipient, monkeypatch):
    request = body()
    first = client.post("/api/v1/credits/admin/grants", headers=AUTH, json=request).json()
    monkeypatch.setattr(admin, "lookup_user", lambda *_: (_ for _ in ()).throw(AssertionError("Replay must not lookup")))
    repeated = client.post("/api/v1/credits/admin/grants", headers=AUTH, json=request)
    assert repeated.status_code == 200
    assert repeated.json()["grant_id"] == first["grant_id"] and repeated.json()["duplicated"]
    assert repeated.json()["balance"] == 1000
    assert len(db_state()["audit"]) == len(db_state()["ledger"]) == 1


@pytest.mark.parametrize("change", [{"credits": 999}, {"email": "another@example.test"}, {"reason": "Different reason"}])
def test_replay_key_cannot_change_payload(client, recipient, change):
    request = body()
    assert client.post("/api/v1/credits/admin/grants", headers=AUTH, json=request).status_code == 201
    result = client.post("/api/v1/credits/admin/grants", headers=AUTH, json={**request, **change})
    assert result.status_code == 409
    assert db_state()["balance"]["balance"] == 1000


def test_concurrent_replay_grants_only_once(client, recipient):
    # Production has an existing wallet database; race the new audit-table
    # initialization and grant, rather than SQLite's first WAL activation.
    with credits.database() as db:
        credits.entry(db, RECIPIENT, 2, "purchase", "existing-paid-payment")
    request = body()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.post("/api/v1/credits/admin/grants", headers=AUTH, json=request), range(2)))
    assert sorted(result.status_code for result in results) == [200, 201]
    assert len({result.json()["grant_id"] for result in results}) == 1
    assert db_state()["balance"]["balance"] == 1002
    assert len(db_state()["audit"]) == 1 and len(db_state()["ledger"]) == 2


def test_request_keys_are_scoped_to_the_verified_admin(client, recipient):
    request = body(credits=1)
    first = client.post("/api/v1/credits/admin/grants", headers=AUTH, json=request)
    second = client.post("/api/v1/credits/admin/grants", headers={"Authorization": "Bearer other-admin"}, json=request)
    assert first.status_code == second.status_code == 201
    assert first.json()["grant_id"] != second.json()["grant_id"]
    assert db_state()["balance"]["balance"] == 2


def test_failure_rolls_back_both_audit_and_ledger(client, recipient, monkeypatch):
    original = credits.entry
    def fail_after_entry(*args):
        original(*args)
        raise RuntimeError("Simulated storage failure")
    monkeypatch.setattr(credits, "entry", fail_after_entry)
    assert client.post("/api/v1/credits/admin/grants", headers=AUTH, json=body()).status_code == 500
    state = db_state()
    assert state["audit"] == state["ledger"] == []
    assert state["balance"] is None


@pytest.mark.parametrize("change", [{"email": "not-email"}, {"email": "x@@example.test"},
    {"email": "a..b@example.test"}, {"credits": 0}, {"credits": -1}, {"credits": 10001},
    {"credits": True}, {"credits": "1000"}, {"reason": " "}, {"reason": "x" * 301},
    {"request_key": "not-a-uuid"}, {"owner_id": MEMBER}, {"is_admin": True}])
def test_invalid_or_forged_payload_never_reaches_lookup(client, recipient, change):
    assert client.post("/api/v1/credits/admin/grants", headers=AUTH, json=body(**change)).status_code == 422
    assert recipient == []


def test_lookup_returns_only_exact_user_and_existing_balance(client, recipient):
    with credits.database() as db:
        credits.entry(db, RECIPIENT, 5, "admin_grant", "old-grant")
    result = client.get("/api/v1/credits/admin/users", headers=AUTH, params={"email": "RECIPIENT@example.test"})
    assert result.status_code == 200
    assert result.json() == {"id": RECIPIENT, "email": EMAIL, "balance": 5}
    assert client.get("/api/v1/credits/admin/users", headers=AUTH, params={"email": "bad"}).status_code == 422


def test_supabase_directory_is_paginated_and_exact_match_only(client, monkeypatch):
    calls = []
    monkeypatch.setattr(admin, "PAGE_SIZE", 2)
    def fetch(url, **kwargs):
        calls.append((url, kwargs))
        users = [{"id": MEMBER, "email": "prefix-" + EMAIL}, {"id": ADMIN, "email": "admin@example.test"}]
        if kwargs["params"]["page"] == 2:
            users = [{"id": RECIPIENT, "email": EMAIL.upper(), "user_metadata": {"private": "not-returned"}}]
        return httpx.Response(200, json={"users": users}, request=httpx.Request("GET", url))
    monkeypatch.setattr(admin.httpx, "get", fetch)
    result = client.get("/api/v1/credits/admin/users", headers=AUTH, params={"email": EMAIL})
    assert result.status_code == 200 and result.json() == {"id": RECIPIENT, "email": EMAIL, "balance": 0}
    assert [request[1]["params"]["page"] for request in calls] == [1, 2]
    assert all(url == "https://auth.example.test/auth/v1/admin/users" for url, _ in calls)
    assert calls[0][1]["headers"]["apikey"] == "test-service-key"
    assert "test-service-key" not in result.text and "not-returned" not in result.text


@pytest.mark.parametrize("failure", ["missing", "http", "invalid", "timeout", "unconfigured"])
def test_missing_user_or_directory_failure_never_grants(client, monkeypatch, failure):
    def fetch(url, **kwargs):
        if failure == "timeout":
            raise httpx.ConnectError("provider-secret-must-not-leak")
        if failure == "http":
            return httpx.Response(500, text="provider-secret-must-not-leak", request=httpx.Request("GET", url))
        return httpx.Response(200, json={"users": [] if failure == "missing" else "malformed"}, request=httpx.Request("GET", url))
    monkeypatch.setattr(admin.httpx, "get", fetch)
    if failure == "unconfigured":
        monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY")
    result = client.post("/api/v1/credits/admin/grants", headers=AUTH, json=body())
    assert result.status_code == (404 if failure == "missing" else 503)
    assert "provider-secret" not in result.text
    assert db_state()["audit"] == db_state()["ledger"] == []


def test_audit_lists_only_latest_50_and_remains_private(client, recipient):
    for index in range(52):
        assert client.post("/api/v1/credits/admin/grants", headers=AUTH,
                           json=body(credits=1, reason=f"Grant {index}")).status_code == 201
    result = client.get("/api/v1/credits/admin/grants", headers=AUTH)
    assert result.status_code == 200 and result.headers["cache-control"] == "private, no-store"
    rows = result.json()["grants"]
    assert len(rows) == 50 and rows[0]["reason"] == "Grant 51" and rows[-1]["reason"] == "Grant 2"


def test_analytics_route_is_admin_scoped_and_has_bounded_periods(client, monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "credit_analytics", SimpleNamespace(analytics=lambda days: calls.append(days) or {"days": days}))
    assert client.get("/api/v1/credits/admin/analytics?days=7", headers=AUTH).json() == {"days": 7}
    assert client.get("/api/v1/credits/admin/analytics", headers=AUTH).json() == {"days": 30}
    assert client.get("/api/v1/credits/admin/analytics?days=90", headers=AUTH).json() == {"days": 90}
    assert client.get("/api/v1/credits/admin/analytics?days=14", headers=AUTH).status_code == 422
    assert calls == [7, 30, 90]
