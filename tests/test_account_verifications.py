"""Owner-only bounded account dashboard; no capability, email or raw evidence leaks."""
import json
import io
import time

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from PIL import Image

import account_verifications as account
import in_hand as ih
import verification_notifications as notify
from test_verification_notifications import OWNER, OTHER, local, seed, ready

BASE = "/api/v1/account"
AUTH = {"Authorization": "Bearer owner"}


@pytest.fixture
def client(local):
    def authenticate(authorization: str = Header(default="")):
        if authorization == "Bearer owner":
            return OWNER
        if authorization == "Bearer other":
            return OTHER
        if authorization == "Bearer guest":
            return "guest:abc"
        raise HTTPException(401, "Sign in")
    app = FastAPI()
    app.include_router(account.create_router(authenticate))
    with TestClient(app) as result:
        yield result


@pytest.mark.parametrize("path,method", [("/verifications", "get"), ("/notifications", "get"), ("/verifications/id/read", "post"), ("/notifications/id/read", "post")])
def test_every_account_route_requires_uuid_owner_not_capability_or_guest(client, path, method):
    assert getattr(client, method)(BASE + path).status_code == 401
    assert getattr(client, method)(BASE + path, headers={"Authorization": "Bearer guest"}).status_code == 401
    assert getattr(client, method)(BASE + path, headers={"X-LockX-Manage-Key": "private-key", "X-LockX-Guest-Key": "guest-key"}).status_code == 401


def test_dashboard_returns_seller_and_buyer_roots_with_legacy_history_no_new_emails(client):
    with ih.database() as db:
        seller = seed(db, created=time.time() - 1000)
        buyer = seed(db, kind="buyer")
        seed(db, owner=OTHER)
    response = client.get(BASE + "/verifications", headers=AUTH)
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store"
    result = response.json()
    assert {item["id"] for item in result["items"]} == {seller, buyer}
    assert {item["kind"] for item in result["items"]} == {"seller", "buyer"}
    assert result["unread_count"] == 0
    serialized = json.dumps(result)
    for forbidden in ("capture-secret", "token", "manage_key", "owner_id", "email", "analysis\"", "video"):
        assert forbidden not in serialized
    with ih.database() as db:
        assert db.execute("SELECT COUNT(*) FROM verification_notifications").fetchone()[0] == 0


def test_filters_keyset_pagination_and_invalid_cursors_are_bounded(client):
    with ih.database() as db:
        ids = [seed(db, kind="buyer" if i % 2 else "seller", created=1000 + i) for i in range(5)]
    first = client.get(BASE + "/verifications?limit=2", headers=AUTH).json()
    second = client.get(BASE + "/verifications", params={"limit": 2, "cursor": first["next_cursor"]}, headers=AUTH).json()
    third = client.get(BASE + "/verifications", params={"limit": 2, "cursor": second["next_cursor"]}, headers=AUTH).json()
    assert [item["id"] for page in (first, second, third) for item in page["items"]] == list(reversed(ids))
    assert third["next_cursor"] is None
    assert len(client.get(BASE + "/verifications?kind=buyer", headers=AUTH).json()["items"]) == 2
    assert len(client.get(BASE + "/verifications?kind=seller", headers=AUTH).json()["items"]) == 3
    for params in ({"cursor": "bad!"}, {"limit": 51}, {"limit": 0}, {"kind": "admin"}):
        assert client.get(BASE + "/verifications", params=params, headers=AUTH).status_code == 422


def test_root_groups_include_latest_subset_but_never_claim_combined_proof(client):
    with ih.database() as db:
        root = seed(db, state="inconclusive", count=2)
        child = seed(db, count=1)
        # Child is an exact projection of root photo0, with the same claims.
        root_listing = db.execute("SELECT listing FROM ih_requests WHERE id=?", (root,)).fetchone()[0]
        db.execute("UPDATE ih_requests SET listing=? WHERE id=?", (root_listing, child))
        db.execute("INSERT INTO ih_capture_retries VALUES(?,?,'verification_failed')", (root, child))
        db.execute("INSERT INTO ih_capture_selections VALUES(?,?,?)", (child, root, "[0]"))
        ready(db, child)
    result = client.get(BASE + "/verifications", headers=AUTH).json()
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["id"] == root and item["latest_attempt"]["id"] == child
    assert (item["verified_count"], item["total_count"], item["root_total_count"]) == (1, 1, 2)
    assert len(item["attempts"]) == 2 and item["unread_count"] == 1


def test_notification_listing_and_read_are_owner_only_and_idempotent(client):
    with ih.database() as db:
        request_id = seed(db)
        event_id = ready(db, request_id)
        foreign = seed(db, owner=OTHER)
    response = client.get(BASE + "/notifications", headers=AUTH)
    assert response.json()["items"][0]["id"] == event_id
    assert "recipient" not in response.text and "payload" not in response.text
    assert client.post(BASE + "/verifications/" + foreign + "/read", headers=AUTH).status_code == 404
    assert client.post(BASE + "/notifications/" + event_id + "/read", headers={"Authorization": "Bearer other"}).status_code == 404
    first = client.post(BASE + "/verifications/" + request_id + "/read", headers=AUTH).json()
    second = client.post(BASE + "/verifications/" + request_id + "/read", headers=AUTH).json()
    assert first == {"updated": 1, "unread_count": 0} and second == {"updated": 0, "unread_count": 0}
    assert client.get(BASE + "/notifications", headers={"Authorization": "Bearer other"}).json()["items"] == []


def test_old_check_finishing_now_sorts_by_new_activity_not_original_creation(client):
    with ih.database() as db:
        old = seed(db, created=time.time() - 10000)
        recent = seed(db, created=time.time() - 100)
        ready(db, old)
    items = client.get(BASE + "/verifications?limit=1", headers=AUTH).json()["items"]
    assert items[0]["id"] == old and items[0]["updated"] > items[0]["created"]


def test_thumbnail_is_small_cached_and_authorized_even_on_cache_hit(client):
    with ih.database() as db:
        request_id = seed(db)
        foreign = seed(db, owner=OTHER)
    item = client.get(BASE + "/verifications", headers=AUTH).json()["items"][0]
    assert item["preview_url"] == "/account/verifications/" + request_id + "/thumbnail"
    url = BASE + "/verifications/" + request_id + "/thumbnail"
    image = client.get(url, headers=AUTH)
    assert image.status_code == 200 and image.headers["cache-control"] == "private, no-store"
    with Image.open(io.BytesIO(image.content)) as preview:
        assert max(preview.size) <= 256 and preview.format == "JPEG"
    assert client.get(url, headers=AUTH).content == image.content
    assert client.get(url, headers={"Authorization": "Bearer other"}).status_code == 404
    assert client.get(BASE + "/verifications/" + foreign + "/thumbnail", headers=AUTH).status_code == 404
    assert client.get(url).status_code == 401


@pytest.mark.parametrize("publication_state,expected", [("pending", "preparing_proof"), ("withdrawn", "withdrawn"), ("consent_required", "ready_to_publish")])
def test_dashboard_distinguishes_proof_preparation_withdrawal_and_publication_consent(client, monkeypatch, publication_state, expected):
    with ih.database() as db:
        seed(db)
    monkeypatch.setattr(ih, "seller_publication", lambda *args: {"publication_status": publication_state})
    assert client.get(BASE + "/verifications", headers=AUTH).json()["items"][0]["outcome"] == expected
