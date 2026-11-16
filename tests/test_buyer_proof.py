"""Buyer credit holds and consented publication boundaries, entirely offline."""
import asyncio
import hashlib
import io
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from PIL import Image

import buyer_requests as buyers
import credit_wallet as credits
import in_hand as ih
import public_evidence as proof


BASE = "/api/v1/in-hand"
AUTH = {"Authorization": "Bearer buyer"}
NOW = 1_800_003_610.0


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCKX_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LOCKX_CREDITS_ENABLED", "1")
    monkeypatch.setenv("LOCKX_VERIFICATION_QUEUE_ENABLED", "0")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(ih, "limited", lambda *_: None)
    monkeypatch.setattr(ih, "prepare_reference_features", lambda *_: None)
    monkeypatch.setattr(ih, "prepare_scan", lambda *_: None)
    monkeypatch.setattr(ih, "finish_scan_background", lambda *_: None)
    clock = [NOW]
    for module in (ih, buyers, credits, proof):
        monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: clock[0]))
    with credits.database() as db:
        credits.entry(db, "buyer", 3, "test_grant", "initial")
    def authenticate(value):
        if value not in {"Bearer buyer", "Bearer capturer"}:
            raise HTTPException(401, "Sign in")
        return value.split()[1]
    application = FastAPI()
    application.include_router(ih.create_router(authenticate))
    with TestClient(application) as client:
        yield client, clock, monkeypatch


def image(index=0):
    output = io.BytesIO()
    Image.new("RGB", (120, 120), (80 + index, 120, 170)).save(output, "JPEG")
    return output.getvalue()


def create(app, *, key=None, owner=AUTH, count=1, **fields):
    client, *_ = app
    listing = {"title": "Buyer supplied collectible", "consent": True,
               "request_kind": "buyer", "listing_url": "https://market.example/items/123?variant=green",
               "request_key": key or str(uuid4()), "auto_publish": True,
               "publish_matched_photos": True, **fields}
    return client.post(BASE + "/requests", headers=owner,
        data={"payload": json.dumps(listing)},
        files=[("photos", (f"photo-{i}.jpg", image(i), "image/jpeg")) for i in range(count)])


def funds():
    with credits.database() as db:
        return credits.wallet(db, "buyer")["balance"]


def start(app, record, **fields):
    return app[0].post(BASE + f"/seller/{record['token']}/video/start", json=fields)


def test_buyer_creation_holds_one_credit_and_replay_does_not_duplicate(app):
    key = str(uuid4())
    first = create(app, key=key)
    assert first.status_code == 201, first.text
    record = first.json()
    assert funds() == 2
    again = create(app, key=key)
    assert again.status_code == 201 and again.json()["id"] == record["id"]
    assert funds() == 2
    assert record["buyer_request"]["credit_reserved"] is True
    with credits.database() as db:
        assert db.execute("SELECT COUNT(*) FROM ih_requests").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM credit_ledger WHERE kind='verification'").fetchone()[0] == 1
        assert db.execute("SELECT owner_id FROM credit_checks").fetchone()[0] == "buyer"


def test_idempotency_key_cannot_change_listing_or_manual_photos(app):
    key = str(uuid4())
    record = create(app, key=key).json()
    assert create(app, key=key, listing_url="https://another.example/new").status_code == 409
    assert create(app, key=key, count=2).status_code == 409
    assert funds() == 2
    assert create(app, key=key).json()["id"] == record["id"]


def test_concurrent_creation_with_one_key_reserves_once(app):
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=5) as pool:
        responses = list(pool.map(lambda _: create(app, key=key), range(5)))
    assert all(r.status_code == 201 for r in responses), [r.text for r in responses]
    assert len({r.json()["id"] for r in responses}) == 1
    assert funds() == 2


@pytest.mark.parametrize("url", ["http://localhost/a", "http://127.0.0.1/a", "http://[::1]/a",
    "http://metadata.google.internal/a", "https://private.local/a", "https://u:p@example.com/a",
    "ftp://example.com/a", "https://example.com:8080/a", "https://example.com/white space",
    "https://example.com\\@other.example/a", "javascript:alert(1)", "http://127.1/a",
    "http://0177.0.0.1/a", "http://0x7f.0.0.1/a", "http://127.0.1/a"])
def test_unsafe_listing_references_fail_before_any_credit_hold(app, url):
    assert create(app, listing_url=url).status_code == 422
    assert funds() == 3
    with ih.database() as db:
        assert db.execute("SELECT COUNT(*) FROM ih_requests").fetchone()[0] == 0


def test_listing_reference_is_only_metadata_and_never_fetched(app, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Buyer listing references must never be fetched")
    monkeypatch.setattr(ih, "urlopen", unexpected)
    result = create(app, listing_url="https://unfamiliar-market.example/seller/item#details")
    assert result.status_code == 201, result.text
    assert result.json()["listing_url"] == "https://unfamiliar-market.example/seller/item"


def test_ordinary_public_domain_with_numeric_label_is_still_valid(app):
    assert create(app, listing_url="https://0x7f000001.example/items/1").status_code == 201


@pytest.mark.parametrize("kind", ["cancelled", "declined", "expired"])
def test_pending_close_releases_hold_exactly_once_and_blocks_capture(app, kind):
    client, clock, _ = app
    record = create(app).json()
    if kind == "expired":
        clock[0] += 86401
        with credits.database() as db:
            credits.reconcile(db, "buyer")
            credits.reconcile(db, "buyer")
    else:
        path = (f"/requests/{record['id']}/cancel" if kind == "cancelled"
                else f"/seller/{record['token']}/decline")
        headers = AUTH if kind == "cancelled" else {}
        for _ in range(2):
            result = client.post(BASE + path, json={"consent": True}, headers=headers)
            assert result.status_code == 200, result.text
    assert funds() == 3
    assert start(app, record, share_evidence=True).status_code == 410
    with credits.database() as db:
        check = db.execute("SELECT * FROM credit_checks WHERE request_id=?", (record["id"],)).fetchone()
        assert check["state"] == "refunded"
        assert db.execute("SELECT COUNT(*) FROM credit_ledger WHERE kind='invitation_release'").fetchone()[0] == 1


def test_concurrent_cancel_decline_and_expiry_cannot_double_refund(app):
    record = create(app).json()
    def close(state):
        with credits.database() as db:
            db.execute("BEGIN IMMEDIATE")
            return buyers.close(db, record["id"], state)["state"]
    states = ["cancelled", "declined", "expired"] * 3
    with ThreadPoolExecutor(max_workers=9) as pool:
        results = list(pool.map(close, states))
    assert len(set(results)) == 1
    assert funds() == 3
    with credits.database() as db:
        assert db.execute("SELECT COUNT(*) FROM credit_ledger WHERE kind='invitation_release'").fetchone()[0] == 1


def test_capture_token_grants_neither_buyer_management_nor_another_wallet(app):
    client, *_ = app
    record = create(app).json()
    assert client.post(BASE + f"/requests/{record['id']}/cancel", json={"consent": True}).status_code == 401
    assert client.post(BASE + f"/requests/{record['id']}/cancel", headers={"X-LockX-Manage-Key": record["token"]}, json={"consent": True}).status_code == 404
    assert client.post(BASE + f"/requests/{record['id']}/cancel", headers={"Authorization": "Bearer capturer"}, json={"consent": True}).status_code == 404
    assert client.get(BASE + f"/media/{record['media'][0]['id']}", headers={"Authorization": "Bearer capturer"}).status_code == 404
    assert start(app, record, share_evidence=True).status_code == 200
    assert funds() == 2
    with credits.database() as db:
        assert db.execute("SELECT owner_id FROM credit_checks").fetchone()[0] == "buyer"
        assert not db.execute("SELECT 1 FROM credit_wallets WHERE owner_id='capturer'").fetchone()


@pytest.mark.parametrize("body", [{}, {"share_evidence": False}, {"share_evidence": "true"}, {"share_evidence": 1}])
def test_buyer_capture_requires_explicit_strict_sharing_consent(app, body):
    record = create(app).json()
    result = start(app, record, **body)
    assert result.status_code == 422
    assert funds() == 2
    with ih.database() as db:
        assert db.execute("SELECT COUNT(*) FROM ih_sessions").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM ih_evidence_consent").fetchone()[0] == 0


def test_missing_capture_body_and_legacy_routes_cannot_bypass_buyer_consent(app):
    client, *_ = app
    record = create(app).json()
    assert client.post(BASE + f"/seller/{record['token']}/video/start").status_code == 422
    for path in ("start", "scan/start"):
        assert client.post(BASE + f"/seller/{record['token']}/{path}").status_code == 409


def test_new_take_has_its_own_consent_and_original_session_cannot_be_rebound(app):
    record = create(app).json()
    first = start(app, record, share_evidence=True).json()["session_id"]
    second = start(app, record, share_evidence=True).json()["session_id"]
    assert first != second
    with ih.database() as db:
        rows = db.execute("SELECT session_id,request_id,share_evidence FROM ih_evidence_consent").fetchall()
        assert {row["session_id"] for row in rows} == {first, second}
        assert all(row["request_id"] == record["id"] and row["share_evidence"] == 1 for row in rows)
        with pytest.raises(HTTPException):
            proof.record_capture_consent(db, "different-request", first, True)


@pytest.mark.parametrize("outcome", ["processing", "confirmed", "mismatch", "inconclusive"])
def test_submitted_recording_cannot_be_refunded_by_cancel_decline_or_expiry(app, outcome):
    client, clock, _ = app
    record = create(app).json()
    with ih.database() as db:
        db.execute("UPDATE ih_requests SET submitted=?,status=?,analysis_status=? WHERE id=?",
                   (NOW, outcome, "processing" if outcome == "processing" else "complete", record["id"]))
    assert client.post(BASE + f"/requests/{record['id']}/cancel", headers=AUTH, json={"consent": True}).status_code == 409
    assert client.post(BASE + f"/seller/{record['token']}/decline", json={"consent": True}).status_code == 409
    clock[0] += 86401
    with credits.database() as db:
        credits.reconcile(db, "buyer")
        credits.reconcile(db, "buyer")
        expected = "reserved" if outcome == "processing" else "consumed"
        assert db.execute("SELECT state FROM credit_checks").fetchone()[0] == expected
        assert db.execute("SELECT COUNT(*) FROM credit_ledger WHERE kind='invitation_release'").fetchone()[0] == 0
    assert funds() == 2


def recorded_take(app, record):
    client, clock, _ = app
    session = start(app, record, share_evidence=True).json()["session_id"]
    result = client.post(BASE + f"/seller/{record['token']}/scan/{session}/chunks/0",
                         content=b"\x1aE\xdf\xa3" + b"offline-camera-recording" * 20,
                         headers={"Content-Type": "application/octet-stream"})
    assert result.status_code == 200, result.text
    clock[0] += 10.1
    return {"session_id": session, "consent": True, "source": "browser_camera",
            "chunk_count": 1, "recording_seconds": 10}


def test_durable_recording_submission_and_replay_do_not_charge_buyer_twice(app):
    client, *_ = app
    record = create(app).json()
    payload = recorded_take(app, record)
    for _ in range(2):
        result = client.post(BASE + f"/seller/{record['token']}/scan/finish", json=payload)
        assert result.status_code == 202, result.text
    with credits.database() as db:
        assert db.execute("SELECT COUNT(*) FROM credit_ledger WHERE kind='verification'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM ih_media WHERE role='video'").fetchone()[0] == 1
        assert db.execute("SELECT submitted FROM ih_requests WHERE id=?", (record["id"],)).fetchone()[0]
    assert funds() == 2
    assert client.post(BASE + f"/requests/{record['id']}/cancel", headers=AUTH, json={"consent": True}).status_code == 409


def test_submit_cancel_race_has_one_durable_financial_outcome(app):
    client, *_ = app
    record = create(app).json()
    payload = recorded_take(app, record)
    def submit():
        return client.post(BASE + f"/seller/{record['token']}/scan/finish", json=payload)
    def cancel():
        return client.post(BASE + f"/requests/{record['id']}/cancel", headers=AUTH, json={"consent": True})
    with ThreadPoolExecutor(max_workers=2) as pool:
        submitted = pool.submit(submit)
        cancelled = pool.submit(cancel)
        submission, cancellation = submitted.result(), cancelled.result()
    with credits.database() as db:
        row = db.execute("SELECT * FROM ih_requests WHERE id=?", (record["id"],)).fetchone()
        check = db.execute("SELECT * FROM credit_checks WHERE request_id=?", (record["id"],)).fetchone()
        videos = db.execute("SELECT COUNT(*) FROM ih_media WHERE request_id=? AND role='video'", (record["id"],)).fetchone()[0]
    if row["submitted"]:
        assert submission.status_code == 202 and cancellation.status_code == 409
        assert check["state"] == "reserved" and videos == 1 and funds() == 2
    else:
        assert submission.status_code == 410 and cancellation.status_code == 200
        assert check["state"] == "refunded" and videos == 0 and funds() == 3


def test_parallel_requests_cannot_reserve_last_credit_twice_or_leave_orphans(app):
    with credits.database() as db:
        credits.entry(db, "buyer", -2, "test_adjustment", "one-remaining")
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: create(app), range(2)))
    assert sorted(r.status_code for r in responses) == [201, 402]
    assert funds() == 0
    with ih.database() as db:
        assert db.execute("SELECT COUNT(*) FROM ih_requests").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM ih_media").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM ih_buyer_requests").fetchone()[0] == 1


@pytest.fixture
def publication(app):
    """Sparse original frame indices and a failed middle reference stay intact."""
    client, clock, monkeypatch = app
    record = create(app, count=3).json()
    session_id = start(app, record, share_evidence=True).json()["session_id"]
    video = bytes(range(256)) * 600
    with ih.database() as db:
        for index in range(6):
            ih.store_media(db, record["id"], "frame", "image/jpeg", image(index + 5), seconds=index * 1.25, label=f"Frame {index}")
        ih.store_media(db, record["id"], "video", "video/mp4", video)
        db.execute("UPDATE ih_sessions SET finished=?,position=1 WHERE id=?", (NOW + 10, session_id))
        visual = {"same_item": "contradicted", "distinguishing_details": ["Individual corner scratch", "Distinctive lower seam wear"],
            "challenge_actions": "followed", "continuity": "consistent", "claims": [], "concerns": [],
            "summary": "PRIVATE FULL ANALYSIS SHOULD NOT APPEAR", "photos": [
                {"photo_index": 0, "finding": "supported", "evidence": "The distinctive corner wear matches.", "frame_indices": [1, 4, 1]},
                {"photo_index": 1, "finding": "contradicted", "evidence": "PRIVATE REJECTED PHOTO REASON", "frame_indices": [1]},
                {"photo_index": 2, "finding": "supported", "evidence": "The lower seam and mark match.", "frame_indices": [4]}]}
        analysis = {"visual": visual, "video": {"frame_selection": {"selected_frame_indices": [1, 4]}, "notes": []}, "evidence_regions": []}
        db.execute("UPDATE ih_requests SET status='mismatch',submitted=?,analysis_status='complete',analysis=? WHERE id=?", (NOW + 10, json.dumps(analysis), record["id"]))
    monkeypatch.setattr(ih, "render_publication", lambda snapshot, preparation=None: ("test-public-proof", {i: b"synthetic-marked-photo" for i in snapshot["eligibility"]["eligible_photo_indices"]}))
    with ih.database() as db:
        row = db.execute("SELECT * FROM ih_requests WHERE id=?", (record["id"],)).fetchone()
        publication_id = ih.publish_confirmed_photos(db, row)
    return {"record": record, "id": publication_id, "session": session_id, "video": video, "app": app}


def manifest(db, item):
    row = db.execute("SELECT * FROM ih_requests WHERE id=?", (item["record"]["id"],)).fetchone()
    pub = db.execute("SELECT * FROM ih_publications WHERE id=?", (item["id"],)).fetchone()
    return ih.publication_manifest(db, row, pub)


def test_public_evidence_exposes_only_approved_photos_exact_original_citations_and_no_private_ids(publication):
    client = publication["app"][0]
    response = client.get(BASE + f"/public/{publication['id']}/evidence")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    result = response.json()
    assert result["available"] and [p["photo_index"] for p in result["photos"]] == [0, 2]
    assert [f["frame_index"] for f in result["photos"][0]["frames"]] == [1, 4]
    assert [f["seconds"] for f in result["photos"][0]["frames"]] == [1.25, 5.0]
    assert result["captured"] == NOW + 10
    with ih.database() as db:
        private_ids = [m["id"] for m in db.execute("SELECT id FROM ih_media WHERE request_id=?", (publication["record"]["id"],))]
    serialized = json.dumps(result)
    for private in private_ids + [publication["record"]["id"], publication["record"]["token"], publication["record"]["manage_key"], publication["session"], "PRIVATE REJECTED", "PRIVATE FULL ANALYSIS"]:
        assert private not in serialized
    for key in ("reference-1", "frame-0", "frame-2", "frame-3", "frame-5", "unrecognized"):
        assert client.get(BASE + f"/public/{publication['id']}/evidence/{key}").status_code == 404
    for key in ("reference-0", "reference-2", "frame-1", "frame-4"):
        response = client.get(BASE + f"/public/{publication['id']}/evidence/{key}")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("header,start,end", [("bytes=0-9", 0, 9), ("bytes=65530-65545", 65530, 65545),
    ("bytes=100-", 100, None), ("bytes=-21", -21, None), ("bytes=153590-999999", 153590, None)])
def test_original_video_supports_byte_ranges_with_exact_bytes(publication, header, start, end):
    response = publication["app"][0].get(BASE + f"/public/{publication['id']}/evidence/video", headers={"Range": header})
    video = publication["video"]
    start = start if start >= 0 else len(video) + start
    end = len(video) - 1 if end is None else end
    assert response.status_code == 206
    assert response.content == video[start:end + 1]
    assert response.headers["content-range"] == f"bytes {start}-{end}/{len(video)}"
    assert int(response.headers["content-length"]) == end - start + 1
    assert response.headers["accept-ranges"] == "bytes"


@pytest.mark.parametrize("header", ["bytes=999999-", "bytes=9-4", "bytes=-0", "bytes=-", "bytes=0-9,20-30", "nibbles=0-5", "garbage", pytest.param("bytes=" + "9" * 5000 + "-", id="oversized-byte-position")])
def test_invalid_or_unsatisfiable_video_ranges_return_416(publication, header):
    response = publication["app"][0].get(BASE + f"/public/{publication['id']}/evidence/video", headers={"Range": header})
    assert response.status_code == 416
    assert response.headers["content-range"] == f"bytes */{len(publication['video'])}"


def test_video_stream_reads_bounded_chunks_and_stops_after_withdrawal(publication):
    reads = []
    @contextmanager
    def reader_factory(**kwargs):
        reads.append(kwargs)
        with ih.database(**kwargs) as db:
            yield db
    with ih.database() as db:
        response = proof.get_media_response(db, publication["id"], "video", manifest(db, publication), reader_factory=reader_factory)
    async def collect():
        chunks = []
        async for part in response.body_iterator:
            chunks.append(part)
        return chunks
    chunks = asyncio.run(collect())
    assert [len(part) for part in chunks] == [65536, 65536, len(publication["video"]) - 131072]
    assert b"".join(chunks) == publication["video"]
    assert reads == [{"read_only": True}] * 3
    with ih.database() as db:
        response = proof.get_media_response(db, publication["id"], "video", manifest(db, publication), reader_factory=reader_factory)
    async def revoke_midstream():
        iterator = response.body_iterator
        first = await anext(iterator)
        with ih.database() as db:
            db.execute("UPDATE ih_publications SET revoked=? WHERE id=?", (NOW + 20, publication["id"]))
        following = [part async for part in iterator]
        return first, following
    first, following = asyncio.run(revoke_midstream())
    assert first == publication["video"][:65536] and following == []


@pytest.mark.parametrize("mutation", ["revoke", "session", "consent", "subset", "media_hash", "payload_hash", "capture_time", "frame_time", "mime", "label"])
def test_public_evidence_fails_closed_after_binding_changes(publication, mutation):
    with ih.database() as db:
        current = manifest(db, publication)
        if mutation == "revoke":
            db.execute("UPDATE ih_publications SET revoked=? WHERE id=?", (NOW + 20, publication["id"]))
        elif mutation == "session":
            db.execute("UPDATE ih_requests SET session_id='another-take' WHERE id=?", (publication["record"]["id"],))
        elif mutation == "consent":
            db.execute("DELETE FROM ih_evidence_consent WHERE session_id=?", (publication["session"],))
        elif mutation == "subset":
            current = {**current, "eligible_photo_indices": [0]}
        elif mutation == "media_hash":
            db.execute("UPDATE ih_media SET sha256='changed' WHERE request_id=? AND role='video'", (publication["record"]["id"],))
        elif mutation == "payload_hash":
            db.execute("UPDATE ih_publication_evidence SET payload='{}' WHERE publication_id=?", (publication["id"],))
        elif mutation == "capture_time":
            db.execute("UPDATE ih_sessions SET finished=finished+1 WHERE id=?", (publication["session"],))
        elif mutation == "frame_time":
            db.execute("UPDATE ih_media SET seconds=seconds+1 WHERE request_id=? AND role='frame'", (publication["record"]["id"],))
        elif mutation == "mime":
            db.execute("UPDATE ih_media SET mime='text/html' WHERE request_id=? AND role='video'", (publication["record"]["id"],))
        elif mutation == "label":
            db.execute("UPDATE ih_media SET label='another take' WHERE request_id=? AND role='video'", (publication["record"]["id"],))
        with pytest.raises(HTTPException) as unavailable:
            proof.get_payload(db, publication["id"], current)
        assert unavailable.value.status_code in {404, 410}
        with pytest.raises(HTTPException):
            proof.get_media_response(db, publication["id"], "video", current)


def stored_region(db, item, **changes):
    media = db.execute("SELECT role,sha256 FROM ih_media WHERE request_id=? ORDER BY rowid", (item["record"]["id"],)).fetchall()
    reference = [row for row in media if row["role"] == "listing"][0]
    frame = [row for row in media if row["role"] == "frame"][1]
    return {"photo_index": 0, "frame_index": 1, "reference_sha256": reference["sha256"],
        "frame_sha256": frame["sha256"], "label": "Upper corner wear", "evidence": "This individual mark matches.",
        "reference_box": {"x": .1, "y": .1, "width": .2, "height": .2},
        "frame_box": {"x": .2, "y": .2, "width": .2, "height": .2},
        "provenance": "ai_highlight_geometrically_supported", **changes}


@pytest.mark.parametrize("bad", [None, 1, {}, {"frame_index": 1.0}, {"frame_index": True},
    {"frame_index": "1"}, {"frame_index": None}, {"reference_box": None},
    {"frame_box": {"x": -1, "y": .1, "width": .2, "height": .2}}])
def test_malformed_optional_persisted_regions_cannot_break_approved_photo_publication(publication, bad):
    with ih.database() as db:
        row = db.execute("SELECT * FROM ih_requests WHERE id=?", (publication["record"]["id"],)).fetchone()
        analysis = json.loads(row["analysis"])
        candidate = stored_region(db, publication, **bad) if isinstance(bad, dict) and bad else bad
        analysis["evidence_regions"] = [candidate]
        changed = {**dict(row), "analysis": json.dumps(analysis)}
        prepared = proof.prepare(db, changed, [0, 2])
        assert [p["photo_index"] for p in prepared["photos"]] == [0, 2]
        assert prepared["photos"][0]["regions"] == []


def test_optional_region_is_bound_to_cited_frame_and_hash_and_sanitized_before_publication(publication):
    with ih.database() as db:
        row = db.execute("SELECT * FROM ih_requests WHERE id=?", (publication["record"]["id"],)).fetchone()
        analysis = json.loads(row["analysis"])
        analysis["evidence_regions"] = [stored_region(db, publication, label="Read https://secret.example/customer", evidence="The password is visible"),
            stored_region(db, publication, frame_index=2), stored_region(db, publication, reference_sha256="different-item")]
        prepared = proof.prepare(db, {**dict(row), "analysis": json.dumps(analysis)}, [0, 2])
        regions = prepared["photos"][0]["regions"]
        assert len(regions) == 1
        assert "secret.example" not in json.dumps(regions) and "password" not in json.dumps(regions)
        assert "sha256" not in json.dumps(regions)


def test_private_old_capture_has_no_evidence_and_cannot_opt_in_after_finished(app):
    record = create(app, request_kind="seller", request_key="").json()
    session = start(app, record).json()["session_id"]
    with ih.database() as db:
        db.execute("UPDATE ih_sessions SET finished=? WHERE id=?", (NOW + 10, session))
        row = db.execute("SELECT * FROM ih_requests WHERE id=?", (record["id"],)).fetchone()
        assert proof.prepare(db, row, [0]) is None
        with pytest.raises(HTTPException):
            proof.record_capture_consent(db, record["id"], session, True)

