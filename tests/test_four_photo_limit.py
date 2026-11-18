"""Four-reference admission must not invalidate previously accepted evidence."""

import io
import json
import zipfile

import pytest

import in_hand as ih
import verification_worker as worker
from test_buyer_proof import app, create as create_request, funds
from test_in_hand import ALICE, BASE, assessment, create as create_seller, jpeg, setup, video
from test_in_hand_fast import chunk, detail, finish
from test_in_hand_recovery import video_start
from test_in_hand_quality_retry import quality_capture, retry, stored_record
from test_verification_queue import durable


@pytest.mark.parametrize("kind", ["seller", "buyer"])
@pytest.mark.parametrize("count", [1, 4])
def test_new_requests_accept_up_to_four_references(app, kind, count):
    client, *_ = app
    assert client.get(BASE + "/capabilities").json()["max_photos"] == 4
    response = create_request(app, count=count, request_kind=kind,
                              photo_notes=[f"View {i + 1}" for i in range(count)])
    assert response.status_code == 201, response.text
    with ih.database() as db:
        references = db.execute("SELECT id FROM ih_media WHERE request_id=? AND role='listing'",
                                (response.json()["id"],)).fetchall()
    assert len(references) == count
    assert funds() == (2 if kind == "buyer" else 3)


@pytest.mark.parametrize("kind", ["seller", "buyer"])
@pytest.mark.parametrize("count", [5, 6])
def test_fifth_reference_rejected_without_request_evidence_or_credit_hold(app, kind, count):
    response = create_request(app, count=count, request_kind=kind)
    # Multipart admission rejects excess files before Listing validation.
    assert response.status_code in {400, 422}, response.text
    assert funds() == 3
    with ih.database() as db:
        for table in ("ih_requests", "ih_media", "ih_buyer_requests", "credit_checks"):
            assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM credit_ledger WHERE kind='verification'").fetchone()[0] == 0


def test_photo_notes_cannot_bypass_new_reference_limit(app):
    response = create_request(app, count=4, photo_notes=["Reference detail"] * 5)
    assert response.status_code == 422
    assert funds() == 3
    with ih.database() as db:
        assert db.execute("SELECT COUNT(*) FROM ih_requests").fetchone()[0] == 0


def test_no_references_reports_the_current_limit_without_holding_credit(app):
    response = create_request(app, count=0)
    assert response.status_code == 422
    assert response.json()["detail"] == "Select 1–4 reference photos"
    assert funds() == 3


def legacy_request(environment, count):
    """Seed the intact evidence a six-photo release could already have saved."""
    client, _, _, _ = environment
    response = create_seller(client, auto_publish=True, publish_matched_photos=True)
    assert response.status_code == 201, response.text
    record = response.json()
    with ih.database() as db:
        for index in range(4, count):
            ih.store_media(db, record["id"], "listing", "image/jpeg", ih.clean_photo(jpeg(index)),
                           label=f"Reference photo {index + 1}")
        listing = json.loads(db.execute("SELECT listing FROM ih_requests WHERE id=?", (record["id"],)).fetchone()[0])
        listing["photo_notes"] = [f"Original view {i + 1}" for i in range(count)]
        db.execute("UPDATE ih_requests SET listing=? WHERE id=?", (json.dumps(listing), record["id"]))
    return record


@pytest.mark.parametrize("count", [5, 6])
@pytest.mark.parametrize("capture", ["scan", "video"])
def test_preexisting_five_and_six_photo_requests_can_start_capture(setup, count, capture):
    client, _, _, monkeypatch = setup
    monkeypatch.setenv("LOCKX_VERIFICATION_QUEUE_ENABLED", "0")
    record = legacy_request(setup, count)
    response = client.post(BASE + f"/seller/{record['token']}/{capture}/start", json={})
    assert response.status_code == 200, response.text
    with ih.database() as db:
        session = db.execute("SELECT stages FROM ih_sessions WHERE id=?", (response.json()["session_id"],)).fetchone()
        stages = json.loads(session["stages"])
    assert set().union(*(set(step.get("photo_indices", [])) for step in stages)) == set(range(count))


def test_preexisting_six_photo_notes_remain_valid_for_background_scan_planning(setup):
    _, _, _, monkeypatch = setup
    monkeypatch.setenv("LOCKX_VERIFICATION_QUEUE_ENABLED", "0")
    record = legacy_request(setup, 6)
    monkeypatch.setenv("OPENAI_API_KEY", "local-test-placeholder")
    monkeypatch.setenv("LOCKX_IN_HAND_VISION_MODEL", "test-model")
    monkeypatch.setattr(ih, "vision_call", lambda *_a, **_k: ih.ScanPlan(groups=[]))
    ih.prepare_scan(record["id"])
    with ih.database() as db:
        prepared = db.execute("SELECT plan FROM ih_scan_plans WHERE request_id=?", (record["id"],)).fetchone()
    assert prepared is not None
    assert set().union(*(set(step.get("photo_indices", [])) for step in json.loads(prepared[0]))) == set(range(6))


def extend_historical_quality_references(record, count):
    with ih.database() as db:
        row = db.execute("SELECT * FROM ih_requests WHERE id=?", (record["id"],)).fetchone()
        listing = json.loads(row["listing"])
        listing["photo_notes"] = [f"Original view {i + 1}" for i in range(count)]
        for index in range(4, count):
            ih.store_media(db, record["id"], "listing", "image/jpeg", ih.clean_photo(jpeg(index)),
                           label=f"Reference photo {index + 1}")
        analysis = json.loads(row["analysis"]) if row["analysis"] else None
        if analysis:
            photos = analysis["visual"]["photos"]
            photos.extend({**photos[0], "photo_index": index} for index in range(4, count))
        db.execute("UPDATE ih_requests SET listing=?,analysis=? WHERE id=?",
                   (json.dumps(listing), json.dumps(analysis) if analysis else None, record["id"]))


@pytest.mark.parametrize("count", [5, 6])
def test_legacy_quality_failure_cannot_create_new_over_limit_retry(setup, count):
    client, _, _, _ = setup
    record = quality_capture(setup)
    extend_historical_quality_references(record, count)
    before = stored_record(record["id"])
    with ih.database() as db:
        credits_before = [tuple(row) for row in db.execute("SELECT * FROM credit_checks")]
        ledger_before = [tuple(row) for row in db.execute("SELECT * FROM credit_ledger")]
    response = retry(client, record)
    assert response.status_code == 409, response.text
    assert "four" in response.json()["detail"].lower()
    assert stored_record(record["id"]) == before
    with ih.database() as db:
        assert db.execute("SELECT COUNT(*) FROM ih_requests").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM ih_capture_retries").fetchone()[0] == 0
        assert [tuple(row) for row in db.execute("SELECT * FROM credit_checks")] == credits_before
        assert [tuple(row) for row in db.execute("SELECT * FROM credit_ledger")] == ledger_before


def test_existing_legacy_six_photo_retry_is_recovered_without_new_request(setup):
    client, _, _, _ = setup
    parent = quality_capture(setup)
    response = retry(client, parent)
    assert response.status_code == 201, response.text
    child = response.json()
    # Genuine historical retries predate selected-reference projections.
    with ih.database() as db:
        db.execute('DELETE FROM ih_capture_selections WHERE request_id=?',(child['id'],))
    for record in (parent, child):
        extend_historical_quality_references(record, 6)
    before = [stored_record(record["id"]) for record in (parent, child)]
    recovered = retry(client, parent)
    assert recovered.status_code == 201, recovered.text
    assert recovered.json()['id'] == child['id'] and recovered.json()['token'] == child['token']
    assert recovered.json()['root_photo_indices'] == list(range(6))
    assert [stored_record(record["id"]) for record in (parent, child)] == before
    with ih.database() as db:
        assert db.execute("SELECT COUNT(*) FROM ih_requests").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM ih_capture_retries").fetchone()[0] == 1


@pytest.mark.parametrize("count", [5, 6])
def test_saved_queue_and_public_proof_retain_every_legacy_reference(durable, count):
    client, clock, tmp, monkeypatch = durable
    record = legacy_request(durable, count)
    stage = video_start(client, record)
    assert chunk(client, record, stage, 0, video(tmp, 10)).status_code == 200
    clock[0] += 10.1
    receipt = finish(client, record, stage, recording_seconds=10)
    assert receipt.status_code == 202, receipt.text
    assert receipt.json()["queue"]["state"] == "queued"
    with ih.database() as db:
        originals = [tuple(row) for row in db.execute(
            "SELECT id,sha256,content FROM ih_media WHERE request_id=? AND role='listing' ORDER BY rowid", (record["id"],))]
        saved_listing = db.execute("SELECT listing FROM ih_requests WHERE id=?", (record["id"],)).fetchone()[0]
        manifest = json.loads(db.execute("SELECT manifest FROM verification_jobs WHERE request_id=?", (record["id"],)).fetchone()[0])
    assert len([media for media in manifest["media"] if media["role"] == "listing"]) == count
    compared = []
    def compare(schema, *_args, **kwargs):
        strict = ih.strict_vision_schema(schema, kwargs["allowed_frame_indices"], kwargs["photo_count"])
        assert strict["properties"]["photos"]["maxItems"] == count
        assert strict["$defs"]["PhotoFinding"]["properties"]["photo_index"]["enum"] == list(range(count))
        compared.append(kwargs["photo_count"])
        return assessment(count=count, photos=[{
            "photo_index": index, "finding": "supported", "evidence": "Distinct individual marks agree.",
            "frame_indices": [kwargs["allowed_frame_indices"][-1]],
        } for index in range(count)])
    monkeypatch.setattr(ih, "vision_call", compare)
    # Rendering/QR reliability is covered separately; keep this admission and
    # historical-publication regression independent of image rendering speed.
    monkeypatch.setattr(ih, "marked_photo", lambda content, *_a, **_k: content)
    preparations = []
    original_prepare = ih.prepare_exports
    def prepare(*args):
        result = original_prepare(*args)
        preparations.append(result is not None and len(result.references))
        return result
    monkeypatch.setattr(ih, "prepare_exports", prepare)
    assert worker.run_once("legacy-evidence-worker") is True
    final = detail(client, record)
    assert final["queue"]["state"] == "completed" and final["status"] == "confirmed", final
    assert compared == [count] and preparations == [count]
    publication = final["publication"]
    public = client.get(BASE + "/public/" + publication["id"])
    assert public.status_code == 200, public.text
    assert public.json()["photo_count"] == count
    assert [photo["photo_index"] for photo in public.json()["photos"]] == list(range(count))
    for photo in public.json()["photos"]:
        assert client.get(BASE + f"/public/{publication['id']}/photos/{photo['id']}").status_code == 200
    download = client.get(BASE + f"/requests/{record['id']}/marked-photos", headers=ALICE)
    assert download.status_code == 200, download.text
    assert len(zipfile.ZipFile(io.BytesIO(download.content)).namelist()) == count
    with ih.database() as db:
        assert [tuple(row) for row in db.execute(
            "SELECT id,sha256,content FROM ih_media WHERE request_id=? AND role='listing' ORDER BY rowid", (record["id"],))] == originals
        assert db.execute("SELECT listing FROM ih_requests WHERE id=?", (record["id"],)).fetchone()[0] == saved_listing
