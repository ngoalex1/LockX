"""Regression coverage for bounded capture recovery and phone-visible findings."""

import json
import secrets

import cv2
import numpy as np
import pytest

import in_hand as ih
from test_in_hand import ALICE, BASE, assessment, create, jpeg, model_ready, setup, video
from test_in_hand_fast import chunk, detail, finish, scan_progress, scan_start


def result(client, record):
    return client.get(BASE + f"/seller/{record['token']}/result")


def partial_scan(client, record, clock):
    stage = scan_start(client, record)
    clock[0] += stage["stage"]["minimum_seconds"] + .2
    response = scan_progress(client, record, stage, recording_seconds=1.4)
    assert response.status_code == 200, response.text
    return response.json()


def test_phone_result_is_read_only_scoped_and_has_a_finding_for_every_photo(setup):
    client, _, _, _ = setup
    record = create(client, access_headers={}).json()
    other = create(client, access_headers={}).json()
    response = result(client, record)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"id", "status", "analysis_status", "summary", "result", "photos", "scope",
                         "eligible_photo_indices", "verified_count", "total_count", "partial"}
    assert body["id"] == record["id"] and body["status"] == "waiting"
    assert body["eligible_photo_indices"] == [] and body["verified_count"] == 0
    assert body["total_count"] == 4 and body["partial"] is False
    assert [photo["photo_index"] for photo in body["photos"]] == list(range(4))
    assert all(photo["finding"] == "not_established" for photo in body["photos"])
    assert all(set(photo) == {"photo_index", "finding", "evidence"} for photo in body["photos"])
    assert record["token"] not in response.text and record["manage_key"] not in response.text
    assert result(client, other).json()["id"] == other["id"]
    assert client.get(BASE + f"/seller/{secrets.token_urlsafe(32)}/result").status_code == 404
    assert client.get(BASE + "/requests/" + record["id"]).status_code == 401
    assert client.get(BASE + "/media/" + record["media"][0]["id"]).status_code == 401
    headers = {"X-LockX-Manage-Key": record["token"]}
    assert client.post(BASE + f"/requests/{record['id']}/publish", headers=headers,
                       json={"publish_selected_photos": True}).status_code == 404


def test_partial_recording_is_compared_but_cannot_be_confirmed_or_published(setup):
    client, clock, tmp, monkeypatch = setup
    record = create(client).json()
    stage = partial_scan(client, record, clock)
    clock[0] += 50  # Includes a slow final upload, after the camera has stopped.
    assert chunk(client, record, stage, 0, video(tmp, 16)).status_code == 200
    assert finish(client, record, stage).status_code == 409
    calls = []
    model_ready(monkeypatch, assessment())
    def compare(schema, *args, **kwargs):
        calls.append(schema)
        return assessment()
    monkeypatch.setattr(ih, "vision_call", compare)
    response = finish(client, record, stage, allow_incomplete=True, recording_seconds=16)
    assert response.status_code == 202, response.text
    assert calls == [ih.VisualAssessment]
    final = detail(client, record)
    assert final["status"] == "inconclusive" and final["analysis_status"] == "complete"
    assert "Capture ended before every required view was collected." in final["analysis"]["video"]["notes"]
    with ih.database() as db:
        session = db.execute("SELECT * FROM ih_sessions WHERE id=?", (stage["session_id"],)).fetchone()
        assert session["position"] == 1  # Missing views were not fabricated.
        assert session["finished"] is not None
        observations = json.loads(session["observations"])
        assert observations[-1]["partial_capture"] is True
        assert observations[-1]["recording_seconds"] == 16
    assert client.post(BASE + f"/requests/{record['id']}/publish", headers=ALICE,
                       json={"publish_selected_photos": True}).status_code == 409
    phone = result(client, record).json()
    assert phone["status"] == "inconclusive" and len(phone["photos"]) == 4
    assert phone["summary"].startswith("Capture ended before every required view was collected.")
    assert all(photo["finding"] == "supported" for photo in phone["photos"])


@pytest.mark.parametrize("case", ["too_early", "missing_duration"])
def test_partial_finish_cannot_bypass_capture_floor_or_omit_recording_time(setup, case):
    client, clock, tmp, _ = setup
    record = create(client).json()
    stage = partial_scan(client, record, clock)
    if case != "too_early":
        clock[0] += 15
    assert chunk(client, record, stage, 0, video(tmp, 16)).status_code == 200
    payload = {"allow_incomplete": True, "recording_seconds": 16}
    if case == "missing_duration":
        payload.pop("recording_seconds")
    response = finish(client, record, stage, **payload)
    assert response.status_code == 422, response.text
    assert detail(client, record)["status"] == "capturing"


def test_safety_deadline_preserves_a_recording_even_when_progress_requests_failed(setup):
    client, clock, tmp, monkeypatch = setup
    record = create(client).json()
    stage = scan_start(client, record)
    clock[0] += 45
    assert chunk(client, record, stage, 0, video(tmp, 16)).status_code == 200
    model_ready(monkeypatch, assessment())
    response = finish(client, record, stage, allow_incomplete=True, recording_seconds=16)
    assert response.status_code == 202, response.text
    final = detail(client, record)
    assert final["status"] == "inconclusive" and final["analysis_status"] == "complete"
    assert "Capture ended before every required view was collected." in final["analysis"]["video"]["notes"]
    with ih.database() as db:
        position = db.execute("SELECT position FROM ih_sessions WHERE id=?",(stage["session_id"],)).fetchone()[0]
    assert position == 0


@pytest.mark.parametrize("duration", [9.4, 90.1, float("inf"), float("nan")])
def test_finish_duration_hint_is_finite_and_bounded(duration):
    with pytest.raises(ValueError):
        ih.ScanFinish(session_id="test", consent=True, chunk_count=1, recording_seconds=duration)


def test_finished_scan_duration_hint_does_not_include_slow_session_or_upload_latency(setup):
    client, clock, tmp, monkeypatch = setup
    record = create(client).json()
    stage = scan_start(client, record)
    for _ in range(10):
        if stage["complete"]:
            break
        clock[0] += 8
        response = scan_progress(client, record, stage)
        assert response.status_code == 200 and not response.json().get("retry"), response.text
        stage = response.json()
    assert stage["complete"]
    with ih.database() as db:
        timing = db.execute("SELECT started,finished FROM ih_sessions WHERE id=?",(stage["session_id"],)).fetchone()
        assert timing["finished"] - timing["started"] >= 40
    assert chunk(client, record, stage, 0, video(tmp, 16)).status_code == 200
    model_ready(monkeypatch, assessment())
    response = finish(client, record, stage, recording_seconds=16)
    assert response.status_code == 202, response.text
    assert detail(client, record)["status"] == "confirmed"
    phone = result(client, record).json()
    assert phone["status"] == "confirmed" and phone["analysis_status"] == "complete"
    assert all(photo["finding"] == "supported" for photo in phone["photos"])
    assert "frame_indices" not in json.dumps(phone) and "media" not in phone


def test_result_retains_placeholders_when_recording_cannot_be_decoded(setup):
    client, clock, _, _ = setup
    record = create(client).json()
    stage = partial_scan(client, record, clock)
    clock[0] += 15
    assert chunk(client, record, stage, 0, b"\x00\x00\x00\x18ftypinvalid-camera-data").status_code == 200
    response = finish(client, record, stage, allow_incomplete=True, recording_seconds=16)
    assert response.status_code == 202, response.text
    body = result(client, record).json()
    assert body["status"] == "inconclusive" and body["analysis_status"] == "failed"
    assert len(body["photos"]) == 4
    assert all(photo["finding"] == "not_established" for photo in body["photos"])


def test_recorded_partial_video_still_has_to_meet_real_duration_floor(setup):
    client, clock, tmp, _ = setup
    record = create(client).json()
    stage = partial_scan(client, record, clock)
    clock[0] += 15
    assert chunk(client, record, stage, 0, video(tmp, 10)).status_code == 200
    response = finish(client, record, stage, allow_incomplete=True, recording_seconds=16)
    assert response.status_code == 202, response.text
    final = detail(client, record)
    assert final["status"] == "inconclusive" and final["analysis_status"] == "failed"


def video_start(client, record):
    response = client.post(BASE + f"/seller/{record['token']}/video/start", json={})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("mode", ["handheld", "flat", "stationary", "digital"])
def test_ten_second_recording_has_one_safe_movement_and_all_reference_indices(setup, mode):
    client, _, _, _ = setup
    record = create(client, capture_mode=mode).json()
    stage = video_start(client, record)
    assert stage["min_capture_seconds"] == stage["recording_seconds"] == 10
    assert stage["max_capture_seconds"] == 15
    assert stage["position"] == 0 and stage["total"] == 1 and stage["complete"] is False
    assert stage["stages"] == [stage["stage"]]
    assert stage["stage"]["id"] == "video-ten-second"
    assert stage["stage"]["kind"] == "motion"
    assert stage["stage"]["minimum_seconds"] == 10
    assert stage["stage"]["photo_indices"] == list(range(4))
    if mode == "stationary":
        assert "Do not move a heavy item" in stage["stage"]["instruction"]
    if mode == "digital":
        assert "Hide usable barcodes" in stage["stage"]["instruction"]
    assert client.get(BASE + "/capabilities").json()["fixed_video_seconds"] == 10


def test_ten_second_clip_reaches_real_photo_comparison_without_any_progress_calls(setup):
    client, clock, tmp, monkeypatch = setup
    record = create(client).json()
    stage = video_start(client, record)
    assert chunk(client, record, stage, 0, video(tmp, 10)).status_code == 200
    clock[0] += 9.9
    assert finish(client, record, stage, recording_seconds=10).status_code == 422
    assert detail(client, record)["status"] == "capturing"
    clock[0] += .2
    model_ready(monkeypatch, assessment())
    response = finish(client, record, stage, recording_seconds=10)
    assert response.status_code == 202, response.text
    final = detail(client, record)
    assert final["status"] == "confirmed" and final["analysis_status"] == "complete"
    assert final["analysis"]["video"]["duration_seconds"] == 10
    assert final["analysis"]["video"]["notes"] == []
    evidence = [media for media in final["media"] if media["role"] == "frame"]
    assert 18 <= len(evidence) <= 22
    assert len({media["sha256"] for media in evidence}) >= 18
    assert min(media["seconds"] for media in evidence) == 0
    assert max(media["seconds"] for media in evidence) >= 9.4
    assert all(media["label"].startswith("Video evidence at ") for media in evidence)
    assert all(photo["finding"] == "supported" for photo in result(client, record).json()["photos"])
    with ih.database() as db:
        session = db.execute("SELECT * FROM ih_sessions WHERE id=?",(stage["session_id"],)).fetchone()
        observations = json.loads(session["observations"])
        assert session["position"] == 1 and len(observations) == 1
        assert observations[0]["recording_end"] is True and observations[0]["partial_capture"] is False


@pytest.mark.parametrize("seconds", [9, 16])
def test_ten_second_profile_rejects_actual_video_outside_its_bounds(setup, seconds):
    client, clock, tmp, _ = setup
    record = create(client).json()
    stage = video_start(client, record)
    clock[0] += 10.1
    assert chunk(client, record, stage, 0, video(tmp, seconds)).status_code == 200
    response = finish(client, record, stage, recording_seconds=10)
    assert response.status_code == 202, response.text
    final = detail(client, record)
    assert final["status"] == "inconclusive" and final["analysis_status"] == "failed"


@pytest.mark.parametrize("hint", [None, 15.1])
def test_ten_second_profile_requires_its_own_bounded_duration_hint(setup, hint):
    client, clock, tmp, _ = setup
    record = create(client).json()
    stage = video_start(client, record)
    clock[0] += 10.1
    assert chunk(client, record, stage, 0, video(tmp, 10)).status_code == 200
    assert finish(client, record, stage, recording_seconds=hint).status_code == 422


@pytest.mark.parametrize("changes", [
    {"photos": []},
    {"photos": [{"photo_index":i,"finding":"supported","evidence":"Same marks","frame_indices":[0]} for i in range(3)]},
    {"challenge_actions": "unclear"},
    {"distinguishing_details": ["Same model only"]},
])
def test_fixed_video_still_requires_every_photo_and_individual_item_evidence(setup, changes):
    client, clock, tmp, monkeypatch = setup
    record = create(client).json()
    stage = video_start(client, record)
    clock[0] += 10.1
    assert chunk(client, record, stage, 0, video(tmp, 10)).status_code == 200
    model_ready(monkeypatch, assessment(**changes))
    assert finish(client, record, stage, recording_seconds=10).status_code == 202
    assert detail(client, record)["status"] == "inconclusive"
    assert client.post(BASE + f"/requests/{record['id']}/publish", headers=ALICE,
                       json={"publish_selected_photos": True}).status_code == 409


def test_shorter_fixed_profile_hint_cannot_bypass_existing_guided_capture_floor(setup):
    client, clock, tmp, _ = setup
    record = create(client).json()
    stage = partial_scan(client, record, clock)
    clock[0] += 15
    assert chunk(client, record, stage, 0, video(tmp, 16)).status_code == 200
    assert finish(client, record, stage, allow_incomplete=True, recording_seconds=10).status_code == 422


def test_fixed_video_cannot_confirm_digital_ticket_rights(setup):
    client, clock, tmp, monkeypatch = setup
    record = create(client, capture_mode="digital").json()
    stage = video_start(client, record)
    clock[0] += 10.1
    assert chunk(client, record, stage, 0, video(tmp, 10)).status_code == 200
    model_ready(monkeypatch, assessment())
    assert finish(client, record, stage, recording_seconds=10).status_code == 202
    assert result(client, record).json()["status"] == "inconclusive"


def test_fixed_video_samples_the_whole_clip_without_exceeding_thirty_frames(setup):
    client, clock, tmp, monkeypatch = setup
    record = create(client).json()
    stage = video_start(client, record)
    clock[0] += 15
    assert chunk(client, record, stage, 0, video(tmp, 15)).status_code == 200
    model_ready(monkeypatch, assessment())
    assert finish(client, record, stage, recording_seconds=15).status_code == 202
    final = detail(client, record)
    evidence = [media for media in final["media"] if media["role"] == "frame"]
    assert len(evidence) == 30
    assert min(media["seconds"] for media in evidence) == 0
    assert max(media["seconds"] for media in evidence) >= 14.4


def test_fixed_video_quality_notes_from_actual_decoded_frames_prevent_confirmation(setup):
    client, clock, tmp, monkeypatch = setup
    record = create(client).json()
    stage = video_start(client, record)
    path = tmp / "blank-camera.mp4"
    writer = cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*"mp4v"),5,(320,240))
    assert writer.isOpened()
    for _ in range(50):
        writer.write(np.full((240,320,3),128,dtype=np.uint8))
    writer.release()
    clock[0] += 10.1
    assert chunk(client, record, stage, 0, path.read_bytes()).status_code == 200
    supported = assessment()
    for photo in supported.photos:
        photo.frame_indices = [0]  # A real selected anchor; this test isolates the quality gate.
    model_ready(monkeypatch, supported)
    assert finish(client, record, stage, recording_seconds=10).status_code == 202
    final = detail(client, record)
    assert final["analysis_status"] == "complete" and final["status"] == "inconclusive"
    assert final["analysis"]["video"]["sampled_frames"] == 20
    assert "Most sampled views have lighting or focus issues." in final["analysis"]["video"]["notes"]


@pytest.mark.parametrize("publication_id", [
    "3bf1e7d384abb1f1", "5d12534813babfcd", "7c8804118ced2f16",
    "9bd972cf6ccf7592", "eb9ae0eb87b95792", "0123456789abcdef",
])
def test_marked_photo_qr_decodes_from_the_complete_exported_jpeg(publication_id, monkeypatch):
    monkeypatch.setenv("LOCKX_PUBLIC_APP_ORIGIN","https://lockx.ai")
    content = ih.marked_photo(jpeg(),publication_id,1700000000)
    image = cv2.imdecode(np.frombuffer(content,np.uint8),cv2.IMREAD_COLOR)
    decoded, _, _ = cv2.QRCodeDetector().detectAndDecode(image)
    assert decoded == "https://lockx.ai/#in-hand/verify/" + publication_id


@pytest.mark.parametrize("padding_frames,expected_status", [(5,"confirmed"),(40,"inconclusive")])
def test_fixed_video_accepts_short_encoder_padding_but_rejects_material_truncation(setup, padding_frames, expected_status):
    client, clock, tmp, monkeypatch = setup
    record = create(client).json()
    stage = video_start(client, record)
    path = tmp / "padded-browser-camera.mp4"
    writer = cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*"mp4v"),20,(320,240))
    assert writer.isOpened()
    frame = cv2.imdecode(np.frombuffer(jpeg(),np.uint8),cv2.IMREAD_COLOR)
    for index in range(197):
        picture = frame.copy()
        cv2.circle(picture,(20+index%280,30),5,(40,80,100),-1)
        writer.write(picture)
    writer.release()
    content = path.read_bytes()
    real_capture = ih.cv2.VideoCapture
    class PaddedCapture:
        def __init__(self,*args):
            self.inner = real_capture(*args)
        def get(self,prop):
            value = self.inner.get(prop)
            return value+padding_frames if prop == cv2.CAP_PROP_FRAME_COUNT else value
        def read(self):
            return self.inner.read()
        def release(self):
            self.inner.release()
    monkeypatch.setattr(ih.cv2,"VideoCapture",PaddedCapture)
    clock[0] += 10.1
    assert chunk(client,record,stage,0,content).status_code == 200
    model_ready(monkeypatch,assessment())
    assert finish(client,record,stage,recording_seconds=10).status_code == 202
    final = detail(client,record)
    assert final["status"] == expected_status
    if padding_frames == 40:
        assert final["analysis_status"] == "failed"

