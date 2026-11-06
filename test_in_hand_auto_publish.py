"""Automatic publication must preserve verification and capability boundaries."""

import io
import secrets
import zipfile

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw

import in_hand as ih
from test_in_hand import BASE, assessment, create, model_ready, setup, video
from test_in_hand_fast import chunk, finish
from test_in_hand_recovery import partial_scan, video_start


def phone_result(client, record):
    response = client.get(BASE + f"/seller/{record['token']}/result")
    assert response.status_code == 200, response.text
    return response.json()


def owner_headers(record):
    return {"X-LockX-Manage-Key": record["manage_key"]}


def owner_detail(client, record):
    response = client.get(BASE + f"/requests/{record['id']}", headers=owner_headers(record))
    assert response.status_code == 200, response.text
    return response.json()


def check_video(setup, *, visual=None, partial=False, comparison_calls=None, **listing):
    client, clock, tmp, monkeypatch = setup
    response = create(client, access_headers={}, **listing)
    assert response.status_code == 201, response.text
    record = response.json()
    stage = partial_scan(client, record, clock) if partial else video_start(client, record)
    seconds = 16 if partial else 10
    assert chunk(client, record, stage, 0, video(tmp, seconds)).status_code == 200
    clock[0] += seconds + .1
    model_result = visual if visual is not None else assessment()
    model_ready(monkeypatch, model_result)
    if comparison_calls is not None:
        def compare(schema, *args, **kwargs):
            comparison_calls.append(schema)
            return model_result
        monkeypatch.setattr(ih, "vision_call", compare)
    response = finish(client, record, stage, recording_seconds=seconds,
                      **({"allow_incomplete": True} if partial else {}))
    assert response.status_code == 202, response.text
    return record


def assert_no_publication(record):
    with ih.database() as db:
        assert db.execute("SELECT COUNT(*) FROM ih_publications WHERE request_id=?", (record["id"],)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM ih_media WHERE request_id=? AND role='marked'", (record["id"],)).fetchone()[0] == 0


def decode_marking(content):
    image = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    decoded, _, _ = cv2.QRCodeDetector().detectAndDecode(image)
    return decoded


def test_opted_in_four_photo_match_automatically_returns_real_qr_photos_and_zip(setup):
    client, _, _, _ = setup
    record = check_video(setup, auto_publish=True)
    result = phone_result(client, record)
    assert result["status"] == "confirmed" and result["analysis_status"] == "complete"
    assert result["auto_publish"] is True and result["publication_status"] == "ready"
    assert len(result["photos"]) == 4 and all(photo["finding"] == "supported" for photo in result["photos"])
    publication = result["publication"]
    assert len(publication["photos"]) == 4
    public_response = client.get(BASE + "/public/" + publication["id"])
    assert public_response.status_code == 200, public_response.text
    public = public_response.json()
    assert public["status"] == "verified" and public["photo_count"] == 4
    assert {photo["id"] for photo in publication["photos"]} == {photo["id"] for photo in public["photos"]}
    expected_qr = "https://lockx.ai/#in-hand/verify/" + publication["id"]
    exported = {}
    for photo in publication["photos"]:
        response = client.get(BASE + f"/public/{publication['id']}/photos/{photo['id']}")
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        assert decode_marking(response.content) == expected_qr
        exported[photo["id"]] = response.content
    zipped = client.get(BASE + f"/seller/{record['token']}/marked-photos")
    assert zipped.status_code == 200, zipped.text
    assert zipped.headers["content-type"].startswith("application/zip")
    assert "no-store" in zipped.headers["cache-control"]
    with zipfile.ZipFile(io.BytesIO(zipped.content)) as archive:
        assert len(archive.namelist()) == 4
        assert all(name.endswith(".jpg") and publication["id"] in name for name in archive.namelist())
        assert sorted(archive.read(name) for name in archive.namelist()) == sorted(exported.values())
    # Every exact selected original is retained privately and distinct from its export.
    original_ids = {photo["id"] for photo in record["media"]}
    assert not original_ids & set(exported)
    assert len([media for media in owner_detail(client, record)["media"] if media["role"] == "marked"]) == 4


@pytest.mark.parametrize("case", ["different_photo", "unclear_photo", "missing_photo", "partial_capture", "digital"])
def test_automatic_marking_never_relaxes_the_complete_physical_item_match(setup, case):
    client, _, _, _ = setup
    visual = assessment()
    if case == "different_photo":
        visual.photos[3].finding = "contradicted"
    elif case == "unclear_photo":
        visual.photos[3].finding = "not_established"
    elif case == "missing_photo":
        visual.photos.pop()
    record = check_video(setup, auto_publish=True, visual=visual,
                         partial=case == "partial_capture",
                         capture_mode="digital" if case == "digital" else "handheld")
    result = phone_result(client, record)
    assert result["status"] != "confirmed"
    assert result["publication_status"] != "ready"
    assert not result.get("publication")
    assert_no_publication(record)
    assert client.get(BASE + f"/seller/{record['token']}/marked-photos").status_code == 409


@pytest.mark.parametrize("listing", [{}, {"auto_publish": False}])
def test_legacy_or_declined_publication_stays_private_even_when_all_photos_match(setup, listing):
    client, _, _, _ = setup
    record = check_video(setup, **listing)
    result = phone_result(client, record)
    assert result["status"] == "confirmed"
    assert result.get("auto_publish", False) is False
    assert result.get("publication_status", "not_requested") == "not_requested"
    assert not result.get("publication")
    assert_no_publication(record)
    # Manual owner publication remains available, without expanding seller scope.
    response = client.post(BASE + f"/requests/{record['id']}/publish", headers=owner_headers(record),
                           json={"publish_selected_photos": True})
    assert response.status_code == 201, response.text
    assert not phone_result(client, record).get("publication")
    assert client.get(BASE + f"/seller/{record['token']}/marked-photos").status_code == 409


def test_automatic_publication_is_idempotent_and_withdrawal_cannot_resurrect_it(setup):
    client, _, _, _ = setup
    record = check_video(setup, auto_publish=True)
    initial = phone_result(client, record)["publication"]
    for _ in range(3):
        ih.auto_publish_confirmed(record["id"])
        assert phone_result(client, record)["publication"] == initial
    manual = client.post(BASE + f"/requests/{record['id']}/publish", headers=owner_headers(record),
                         json={"publish_selected_photos": True})
    assert manual.status_code == 201 and manual.json()["id"] == initial["id"]
    with ih.database() as db:
        assert db.execute("SELECT COUNT(*) FROM ih_publications WHERE request_id=?", (record["id"],)).fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM ih_media WHERE request_id=? AND role='marked'", (record["id"],)).fetchone()[0] == 4
    assert client.delete(BASE + f"/requests/{record['id']}/publication", headers=owner_headers(record)).status_code == 200
    for _ in range(2):
        ih.auto_publish_confirmed(record["id"])
    result = phone_result(client, record)
    assert result["publication_status"] == "withdrawn" and not result.get("publication")
    assert client.get(BASE + "/public/" + initial["id"]).json()["status"] == "withdrawn"
    for photo in initial["photos"]:
        assert client.get(BASE + f"/public/{initial['id']}/photos/{photo['id']}").status_code == 404
    assert client.get(BASE + f"/seller/{record['token']}/marked-photos").status_code == 409


def test_capture_result_and_automatic_download_never_grant_management_or_private_video(setup):
    client, _, _, _ = setup
    record = check_video(setup, auto_publish=True)
    result = phone_result(client, record)
    private = owner_detail(client, record)
    serialized = str(result)
    assert record["manage_key"] not in serialized and record["token"] not in serialized
    assert not {"owner_id", "analysis", "events", "session_id", "media", "manage_key", "token"} & result.keys()
    video_media = next(media for media in private["media"] if media["role"] == "video")
    assert video_media["id"] not in serialized
    token_headers = {"X-LockX-Manage-Key": record["token"]}
    for suffix in ("", "/evidence", "/marked-photos"):
        assert client.get(BASE + f"/requests/{record['id']}" + suffix).status_code == 401
        assert client.get(BASE + f"/requests/{record['id']}" + suffix, headers=token_headers).status_code == 404
    assert client.get(BASE + f"/media/{video_media['id']}").status_code == 401
    assert client.get(BASE + f"/seller/{record['token']}/photos/{video_media['id']}").status_code == 404
    assert client.get(BASE + f"/public/{result['publication']['id']}/photos/{video_media['id']}").status_code == 404
    assert client.delete(BASE + f"/requests/{record['id']}/publication", headers=token_headers).status_code == 404
    assert client.get(BASE + f"/seller/{secrets.token_urlsafe(32)}/marked-photos").status_code == 404
    other_response = create(client, access_headers={}, auto_publish=True)
    assert other_response.status_code == 201
    other = other_response.json()
    assert client.get(BASE + f"/seller/{other['token']}/marked-photos?request_id={record['id']}").status_code == 409
    assert client.get(BASE + f"/seller/{other['token']}/photos/{result['publication']['photos'][0]['id']}").status_code == 404


def test_auto_publish_waits_for_ai_and_polling_does_not_mutate_or_publish(setup):
    client, _, _, monkeypatch = setup
    response = create(client, access_headers={}, auto_publish=True)
    assert response.status_code == 201
    record = response.json()
    calls = []
    monkeypatch.setattr(ih, "marked_photo", lambda *args, **kwargs: calls.append(args) or b"not-an-export")
    for _ in range(3):
        result = phone_result(client, record)
        assert result["status"] == "waiting" and not result.get("publication")
    assert calls == []
    assert_no_publication(record)


def test_failed_partial_render_retries_the_full_set_without_repeating_ai(setup):
    client, _, _, monkeypatch = setup
    original_renderer = ih.marked_photo
    renders, comparisons = [], []
    def fail_once(content, publication_id, captured):
        renders.append(publication_id)
        if len(renders) == 3:
            raise RuntimeError("private renderer detail must never enter the result")
        return original_renderer(content, publication_id, captured)
    monkeypatch.setattr(ih, "marked_photo", fail_once)
    record = check_video(setup, auto_publish=True, comparison_calls=comparisons)
    result = phone_result(client, record)
    assert result["status"] == "confirmed" and result["publication_status"] == "ready"
    assert len(result["publication"]["photos"]) == 4
    assert comparisons == [ih.VisualAssessment]
    assert len(renders) == 7
    assert len(set(renders[:3])) == 1 and len(set(renders[3:])) == 1
    assert renders[0] != renders[3]
    with ih.database() as db:
        assert db.execute("SELECT COUNT(*) FROM ih_media WHERE request_id=? AND role='marked'", (record["id"],)).fetchone()[0] == 4
        assert db.execute("SELECT COUNT(*) FROM ih_publications WHERE request_id=?", (record["id"],)).fetchone()[0] == 1
        job = db.execute("SELECT state,attempts FROM ih_publication_jobs WHERE request_id=?", (record["id"],)).fetchone()
        assert dict(job) == {"state": "ready", "attempts": 2}


def test_persistent_render_failure_is_bounded_atomic_and_preserves_ai_result(setup):
    client, _, _, monkeypatch = setup
    original_renderer = ih.marked_photo
    renders, comparisons = [], []
    def fail_each_attempt(content, publication_id, captured):
        renders.append(publication_id)
        if len(renders) % 3 == 0:
            raise RuntimeError("private renderer detail must never enter the result")
        return original_renderer(content, publication_id, captured)
    monkeypatch.setattr(ih, "marked_photo", fail_each_attempt)
    record = check_video(setup, auto_publish=True, comparison_calls=comparisons)
    for _ in range(3):
        result = phone_result(client, record)
        assert result["status"] == "confirmed" and result["analysis_status"] == "complete"
        assert result["publication_status"] == "failed" and not result.get("publication")
        assert "private renderer detail" not in str(result)
        ih.auto_publish_confirmed(record["id"])
    assert comparisons == [ih.VisualAssessment] and len(renders) == 6
    assert_no_publication(record)
    assert client.get(BASE + f"/seller/{record['token']}/marked-photos").status_code == 409
    final = owner_detail(client, record)
    assert final["analysis"]["result"] == "confirmed"
    assert len(final["analysis"]["visual"]["photos"]) == 4
    assert any(media["role"] == "video" for media in final["media"])


def test_automatic_ten_second_flow_skips_the_unused_guided_scan_planner(setup):
    client, _, _, monkeypatch = setup
    planned = []
    monkeypatch.setattr(ih, "prepare_scan", planned.append)
    response = create(client, access_headers={}, auto_publish=True)
    assert response.status_code == 201, response.text
    assert planned == []
    # The explicit legacy path retains the planner for older guided clients.
    legacy = create(client, access_headers={})
    assert legacy.status_code == 201, legacy.text
    assert planned == [legacy.json()["id"]]


def test_owner_retry_of_failed_ai_creates_one_full_publication_from_retained_video(setup):
    client, _, _, monkeypatch = setup
    incomplete_response = assessment()
    incomplete_response.photos.pop()
    record = check_video(setup, auto_publish=True, visual=incomplete_response)
    initial = phone_result(client, record)
    assert initial["status"] == "inconclusive" and initial["analysis_status"] == "failed"
    assert_no_publication(record)
    initial_video = next(media["id"] for media in owner_detail(client, record)["media"] if media["role"] == "video")
    model_ready(monkeypatch, assessment())
    retry_path = BASE + f"/requests/{record['id']}/analyze"
    # Knowledge of the camera token cannot authorize another paid comparison.
    assert client.post(retry_path, headers={"X-LockX-Manage-Key": record["token"]}).status_code == 404
    response = client.post(retry_path, headers=owner_headers(record))
    assert response.status_code == 202, response.text
    result = phone_result(client, record)
    assert result["status"] == "confirmed" and result["publication_status"] == "ready"
    assert len(result["publication"]["photos"]) == 4
    final = owner_detail(client, record)
    assert [media["id"] for media in final["media"] if media["role"] == "video"] == [initial_video]
    assert len([media for media in final["media"] if media["role"] == "marked"]) == 4
    assert client.post(retry_path, headers=owner_headers(record)).status_code == 409
    assert phone_result(client, record)["publication"] == result["publication"]


@pytest.mark.parametrize("dimensions", [(640, 480), (720, 960), (1080, 1440)])
def test_qr_decodes_from_complete_landscape_and_phone_portrait_photo_exports(setup, dimensions):
    # The 640x480 browser-generated reference reproduced a full-image detector
    # failure even though cropping its QR before decoding succeeded. Scanners
    # receive the complete JPEG, so this assertion must never crop or upscale.
    publication_id = "6b1ac104fd72a6a9"
    expected_url = "https://lockx.ai/#in-hand/verify/" + publication_id
    width, height = dimensions
    for index in range(4):
        picture = Image.new("RGB", dimensions, "#f5f4e8")
        draw = ImageDraw.Draw(picture)
        draw.rounded_rectangle((round(width*.28125), round(height*.125),
                                round(width*.71875), round(height*.875)),
                               radius=16, fill="#163d34")
        draw.text((round(width*.335), round(height*.46)), "PHOTO-ONLY FORM TEST", fill="white")
        # All four reference photos are exported individually, including subtle
        # differences that can affect a decoder's whole-image feature search.
        if index:
            draw.ellipse((12+index*6, 12, 18+index*6, 18), fill="#163d34")
        original = io.BytesIO()
        picture.save(original, "JPEG", quality=92)
        exported = ih.marked_photo(original.getvalue(), publication_id, 1793986980)
        assert decode_marking(exported) == expected_url, (dimensions, index+1)
