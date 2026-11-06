"""Behavioral coverage for the automatic, progressively uploaded camera scan."""

import base64
import json
import math

import cv2
import numpy as np
import pytest

import in_hand as ih
from test_in_hand import (
    ALICE, BASE, BOB, assessment, create, jpeg, model_ready, setup, start,
    progress, submit, video,
)


def scan_start(client, record):
    response = client.post(BASE + f"/seller/{record['token']}/scan/start", json={})
    assert response.status_code == 200, response.text
    return response.json()


def scan_progress(client, record, stage, image=None, **changes):
    payload = {
        "session_id": stage["session_id"],
        "stage_id": stage["stage"]["id"],
        "image": "data:image/jpeg;base64," + base64.b64encode(image or jpeg(stage["position"])).decode(),
        **changes,
    }
    return client.post(BASE + f"/seller/{record['token']}/scan/progress", json=payload)


def complete_scan(client, record, clock):
    stage = scan_start(client, record)
    for _ in range(30):
        if stage["complete"]:
            return stage
        clock[0] += stage["stage"]["minimum_seconds"] + .2
        response = scan_progress(client, record, stage)
        assert response.status_code == 200, response.text
        result = response.json()
        if result.get("retry"):
            # Short plans may finish their views before the overall recording floor.
            assert "remaining_seconds" in result, result
            clock[0] += result["remaining_seconds"] + .2
        stage = result
    pytest.fail("A valid scan did not finish within its bounded view plan")


def chunk(client, record, stage, sequence, content):
    return client.post(
        BASE + f"/seller/{record['token']}/scan/{stage['session_id']}/chunks/{sequence}",
        content=content,
        headers={"Content-Type": "application/octet-stream"},
    )


def finish(client, record, stage, count=1, **changes):
    return client.post(BASE + f"/seller/{record['token']}/scan/finish", json={
        "session_id": stage["session_id"], "consent": True,
        "source": "browser_camera", "chunk_count": count, **changes,
    })


def upload_video(client, record, stage, content, pieces=3):
    size = math.ceil(len(content) / pieces)
    parts = [content[offset:offset + size] for offset in range(0, len(content), size)]
    for sequence, part in enumerate(parts):
        response = chunk(client, record, stage, sequence, part)
        assert response.status_code in (200, 201, 204), response.text
    return finish(client, record, stage, len(parts))


def detail(client, record):
    return client.get(BASE + "/requests/" + record["id"], headers=ALICE).json()


def test_automatic_fallback_covers_every_reference_with_a_randomized_motion(setup):
    client, _, _, _ = setup
    record = create(client).json()
    stage = scan_start(client, record)
    assert stage["min_capture_seconds"] == 12
    assert stage["max_capture_seconds"] == 90
    assert stage["stage"] == stage["stages"][stage["position"]]
    assert any(step["kind"] == "motion" for step in stage["stages"])
    assert set().union(*(set(step["photo_indices"]) for step in stage["stages"])) == set(range(4))
    # Without an evidence-based grouping plan, distinct photos retain individual views.
    for photo_index in range(4):
        assert any(step["kind"] == "stable" and step["photo_indices"] == [photo_index]
                   for step in stage["stages"])


def test_grouping_shares_a_view_only_with_an_explicit_complete_coverage_plan():
    listing = ih.Listing(title="Collectible with front and reverse details", consent=True)
    prepared = ih.ScanPlan(groups=[
        ih.ScanGroup(photo_indices=[0, 2], label="Front and front detail",
                     instruction="Show the front, including the lower left scratch."),
        ih.ScanGroup(photo_indices=[1, 3], label="Reverse and reverse detail",
                     instruction="Turn it over and show the label and worn upper edge."),
    ])
    plan = ih.normalize_scan_plan(listing, 4, prepared)
    stable = [step for step in plan if step["kind"] == "stable"]
    assert {tuple(step["photo_indices"]) for step in stable} == {(0, 2), (1, 3)}
    assert any(step["kind"] == "motion" for step in plan)
    assert set().union(*(set(step["photo_indices"]) for step in stable)) == set(range(4))


@pytest.mark.parametrize("groups", [
    [[0, 1], [2]],             # A selected photo was omitted.
    [[0, 1], [1, 2, 3]],      # Conflicting assignments of one photo.
    [[0, 1], [2, 3, 4]],      # A non-existent photo cannot satisfy coverage.
    [[-1, 0, 1, 2, 3]],       # Negative indices are not references.
    [],                       # An empty planner response is not coverage.
])
def test_invalid_grouping_cannot_skip_selected_photo_evidence(groups):
    listing = ih.Listing(title="Sample item", consent=True)
    prepared = ih.ScanPlan(groups=[ih.ScanGroup(photo_indices=indices, label="View",
                                              instruction="Show these details.")
                                   for indices in groups])
    plan = ih.normalize_scan_plan(listing, 4, prepared)
    stable = [step for step in plan if step["kind"] == "stable"]
    assert len(stable) == 4
    assert {tuple(step["photo_indices"]) for step in stable} == {(0,), (1,), (2,), (3,)}


def test_prepared_same_surface_plan_reduces_views_without_dropping_exact_photos(setup):
    client, _, _, monkeypatch = setup
    images = [jpeg(0), jpeg(0), jpeg(9), jpeg(9)]
    response = client.post(BASE + "/requests", headers=ALICE,
                           data={"payload": json.dumps({"title": "Front and back reference pair", "consent": True})},
                           files=[("photos", (f"reference-{index}.jpg", image, "image/jpeg"))
                                  for index, image in enumerate(images)])
    assert response.status_code == 201, response.text
    record = response.json()
    plan = ih.ScanPlan(groups=[
        ih.ScanGroup(photo_indices=[0, 1], label="Front", instruction="Hold the front scratch in focus."),
        ih.ScanGroup(photo_indices=[2, 3], label="Back", instruction="Turn it over to show the back marking."),
    ])
    model_ready(monkeypatch, plan)
    ih.prepare_scan(record["id"])
    stage = scan_start(client, record)
    stable = [step for step in stage["stages"] if step["kind"] == "stable"]
    assert len(stable) == 2
    assert {tuple(step["photo_indices"]) for step in stable} == {(0, 1), (2, 3)}
    assert len([media for media in detail(client, record)["media"] if media["role"] == "listing"]) == 4


def scan_session(stage):
    with ih.database() as db:
        return dict(db.execute("SELECT * FROM ih_sessions WHERE id=?", (stage["session_id"],)).fetchone())


def test_advisory_followups_are_scoped_and_bounded_without_creating_a_verdict(setup):
    client, _, _, monkeypatch = setup
    record = create(client).json()
    stage = scan_start(client, record)
    before = json.loads(scan_session(stage)["stages"])
    review = ih.CoverageReview(follow_ups=[
        ih.ScanGroup(photo_indices=[0], label="Scratch detail", instruction="Move closer to the lower edge scratch."),
        ih.ScanGroup(photo_indices=[3], label="Label detail", instruction="Hold the photographed label steady."),
    ])
    model_ready(monkeypatch, review)
    calls = []
    def one_review(*args, **kwargs):
        calls.append(args)
        return review
    monkeypatch.setattr(ih, "vision_call", one_review)
    ih.review_scan(stage["session_id"])
    ih.review_scan(stage["session_id"])
    assert len(calls) == 1
    after = json.loads(scan_session(stage)["stages"])
    assert len(after) == len(before) + 2
    assert {tuple(step["photo_indices"]) for step in after[len(before):]} == {(0,), (3,)}
    assert detail(client, record)["status"] == "capturing"
    assert detail(client, record)["analysis"] is None
    assert client.post(BASE + f"/requests/{record['id']}/publish", headers=ALICE,
                       json={"publish_selected_photos": True}).status_code == 409


def test_legacy_capture_is_ineligible_for_automatic_followup_review(setup):
    client, _, _, monkeypatch = setup
    record = create(client).json()
    legacy = start(client, record)
    before = json.loads(scan_session(legacy)["stages"])
    calls = []
    def unexpected_review(*args, **kwargs):
        calls.append(args)
        return ih.CoverageReview(follow_ups=[ih.ScanGroup(
            photo_indices=[0], label="Extra", instruction="Show another detail.")])
    monkeypatch.setattr(ih, "vision_call", unexpected_review)
    ih.review_scan(legacy["session_id"])
    assert not calls
    assert json.loads(scan_session(legacy)["stages"]) == before
    assert detail(client, record)["status"] == "capturing"


@pytest.mark.parametrize("indices", [[99], [-1], []])
def test_unscoped_advisory_cannot_append_or_skip_capture_views(setup, indices):
    client, _, _, monkeypatch = setup
    record = create(client).json()
    stage = scan_start(client, record)
    before = json.loads(scan_session(stage)["stages"])
    model_ready(monkeypatch, ih.CoverageReview(follow_ups=[
        ih.ScanGroup(photo_indices=indices, label="Invalid", instruction="Show something else.")]))
    ih.review_scan(stage["session_id"])
    assert json.loads(scan_session(stage)["stages"]) == before


def test_excessive_followups_and_late_review_do_not_extend_a_new_session(setup):
    client, _, _, monkeypatch = setup
    record = create(client).json()
    old = scan_start(client, record)
    before = json.loads(scan_session(old)["stages"])
    model_ready(monkeypatch, ih.CoverageReview(follow_ups=[
        ih.ScanGroup(photo_indices=[index], label="Extra", instruction="Show this detail.")
        for index in range(3)]))
    ih.review_scan(old["session_id"])
    assert json.loads(scan_session(old)["stages"]) == before
    fresh = scan_start(client, record)
    calls = []
    monkeypatch.setattr(ih, "vision_call", lambda *args, **kwargs: calls.append(args))
    ih.review_scan(old["session_id"])
    assert not calls
    assert not any(step["id"].startswith("scan-follow-up-")
                   for step in json.loads(scan_session(fresh)["stages"]))


def test_followup_model_result_arriving_after_restart_is_discarded(setup):
    client, _, _, monkeypatch = setup
    record = create(client).json()
    old = scan_start(client, record)
    fresh = []
    def restart_during_review(*args, **kwargs):
        fresh.append(scan_start(client, record))
        return ih.CoverageReview(follow_ups=[ih.ScanGroup(
            photo_indices=[0], label="Old missing detail", instruction="Show the old requested detail.")])
    monkeypatch.setattr(ih, "vision_call", restart_during_review)
    ih.review_scan(old["session_id"])
    assert fresh
    assert not any(step["id"].startswith("scan-follow-up-")
                   for step in json.loads(scan_session(old)["stages"]))
    assert not any(step["id"].startswith("scan-follow-up-")
                   for step in json.loads(scan_session(fresh[0])["stages"]))


def test_automatic_scan_preserves_legacy_capture_protocol(setup):
    client, clock, _, _ = setup
    record = create(client).json()
    automatic = scan_start(client, record)
    legacy = start(client, record)
    assert legacy["total"] == 8
    assert legacy["minimum_seconds"] == 4
    assert "stages" not in legacy
    assert chunk(client, record, automatic, 0, b"stale").status_code in (404, 409)
    clock[0] += 4.1
    assert progress(client, record, legacy).status_code == 200


def test_legacy_progress_cannot_advance_an_automatic_session(setup):
    client, clock, _, _ = setup
    record = create(client).json()
    stage = scan_start(client, record)
    clock[0] += 4.1
    response = progress(client, record, stage)
    assert response.status_code == 409
    assert scan_session(stage)["position"] == 0


def test_fast_progress_needs_time_and_usable_evidence_without_a_model_wait(setup):
    client, clock, _, monkeypatch = setup
    record = create(client).json()
    stage = scan_start(client, record)
    calls = []
    monkeypatch.setenv("OPENAI_API_KEY", "placeholder")
    monkeypatch.setenv("LOCKX_IN_HAND_VISION_MODEL", "test-model")
    def unexpected_model_call(*args, **kwargs):
        calls.append(args)
        raise AssertionError("A routine camera step must not synchronously request AI")
    monkeypatch.setattr(ih, "vision_call", unexpected_model_call)
    early = scan_progress(client, record, stage)
    assert early.status_code == 200
    assert early.json()["retry"] and early.json()["position"] == stage["position"]
    assert early.json()["remaining_seconds"] > 0
    clock[0] += stage["stage"]["minimum_seconds"] + .2
    response = scan_progress(client, record, stage, image=jpeg(blank=True))
    assert response.status_code == 200 and response.json()["retry"]
    assert response.json()["position"] == stage["position"]
    response = scan_progress(client, record, stage)
    assert response.status_code == 200, response.text
    assert response.json()["position"] == stage["position"] + 1
    assert not calls


def test_client_recording_time_cannot_bypass_server_capture_floor(setup):
    client, clock, _, _ = setup
    record = create(client, count=1).json()
    stage = scan_start(client, record)
    early = scan_progress(client, record, stage, recording_seconds=90)
    assert early.status_code == 200 and early.json()["retry"]
    assert early.json()["position"] == stage["position"]
    while stage["position"] < stage["total"] - 1:
        clock[0] += stage["stage"]["minimum_seconds"] + .1
        response = scan_progress(client, record, stage, recording_seconds=90)
        assert response.status_code == 200, response.text
        stage = response.json()
    clock[0] += stage["stage"]["minimum_seconds"] + .1
    response = scan_progress(client, record, stage, recording_seconds=90)
    assert response.status_code == 200, response.text
    pending = response.json()
    assert pending["retry"] and pending["remaining_seconds"] > 0
    assert not pending["complete"]
    assert pending["position"] == stage["position"]
    clock[0] += pending["remaining_seconds"] + .1
    response = scan_progress(client, record, pending)
    assert response.status_code == 200 and response.json()["complete"]


def test_capture_cannot_keep_advancing_past_the_session_limit(setup):
    client, clock, _, _ = setup
    record = create(client).json()
    stage = scan_start(client, record)
    clock[0] += 91
    response = scan_progress(client, record, stage)
    assert response.status_code in (409, 410), response.text
    assert not detail(client, record).get("analysis")


def test_stage_order_cannot_be_skipped_and_restart_invalidates_old_session(setup):
    client, clock, _, _ = setup
    record = create(client).json()
    stage = scan_start(client, record)
    clock[0] += 4
    assert scan_progress(client, record, stage, stage_id="invented-stage").status_code == 409
    later = scan_progress(client, record, stage).json()
    fresh = scan_start(client, record)
    assert fresh["session_id"] != stage["session_id"]
    assert scan_progress(client, record, later).status_code == 409
    assert chunk(client, record, stage, 0, b"old-session").status_code in (404, 409)
    assert finish(client, record, stage).status_code in (404, 409)


def test_chunks_are_idempotent_and_bound_to_the_capture_token(setup):
    client, _, _, _ = setup
    record = create(client).json()
    stage = scan_start(client, record)
    other = create(client).json()
    assert chunk(client, record, stage, 0, b"first bytes").status_code in (200, 201, 204)
    assert chunk(client, record, stage, 0, b"first bytes").status_code in (200, 201, 204)
    assert chunk(client, record, stage, 0, b"different bytes").status_code == 409
    assert chunk(client, other, stage, 1, b"not this item").status_code in (404, 409)


def test_chunk_size_sequence_and_permission_limits(setup):
    client, _, _, _ = setup
    record = create(client).json()
    stage = scan_start(client, record)
    assert chunk(client, record, stage, 0, b"x" * (8 * 1024 * 1024 + 1)).status_code == 413
    assert chunk(client, record, stage, -1, b"x").status_code in (400, 413, 422)
    assert chunk(client, record, stage, 180, b"x").status_code in (400, 413, 422)
    assert finish(client, record, stage, consent=False).status_code == 422
    assert finish(client, record, stage, source="uploaded_file").status_code == 422


def test_total_upload_cap_counts_distinct_chunks_not_retries(setup):
    client, _, _, monkeypatch = setup
    record = create(client).json()
    stage = scan_start(client, record)
    monkeypatch.setattr(ih, "MAX_VIDEO", 10)
    assert chunk(client, record, stage, 0, b"123456").status_code in (200, 201, 204)
    assert chunk(client, record, stage, 0, b"123456").status_code in (200, 201, 204)
    assert chunk(client, record, stage, 1, b"78901").status_code == 413
    # A rejected oversized remainder must leave space for a smaller valid remainder.
    assert chunk(client, record, stage, 1, b"7890").status_code in (200, 201, 204)


def test_finish_rejects_incomplete_views_and_missing_chunks_without_losing_retry(setup):
    client, clock, tmp, _ = setup
    record = create(client).json()
    stage = scan_start(client, record)
    assert finish(client, record, stage).status_code == 409
    stage = complete_scan(client, record, clock)
    content = video(tmp, 16)
    half = len(content) // 2
    assert chunk(client, record, stage, 1, content[half:]).status_code in (200, 201, 204)
    assert finish(client, record, stage, count=2).status_code in (409, 422)
    assert detail(client, record)["status"] == "capturing"
    assert chunk(client, record, stage, 0, content[:half]).status_code in (200, 201, 204)
    response = finish(client, record, stage, count=2)
    assert response.status_code == 202, response.text
    assert detail(client, record)["status"] == "inconclusive"


def test_decoded_video_not_preview_images_is_the_final_evidence(setup):
    client, clock, tmp, _ = setup
    record = create(client).json()
    stage = complete_scan(client, record, clock)
    # Progress JPEGs use variants 0..N; the actual recording has a distinct layout.
    content = video(tmp, 16, variant=17)
    response = upload_video(client, record, stage, content)
    assert response.status_code == 202, response.text
    record_detail = detail(client, record)
    assert record_detail["status"] == "inconclusive"
    assert record_detail["analysis_status"] == "unavailable"
    frames = [media for media in record_detail["media"] if media["role"] == "frame"]
    assert frames
    expected_capture = cv2.VideoCapture(str(tmp / "capture-17.mp4"))
    _, first = expected_capture.read()
    expected_capture.release()
    preview = cv2.imdecode(np.frombuffer(jpeg(0), np.uint8), cv2.IMREAD_COLOR)
    captured_frame = cv2.imdecode(np.frombuffer(client.get(BASE + "/media/" + frames[0]["id"], headers=ALICE).content, np.uint8), cv2.IMREAD_COLOR)
    # Ignore the small moving continuity marker and allow JPEG re-encoding noise.
    region = np.s_[60:165, 40:240]
    distance_to_video = np.mean(np.abs(captured_frame[region].astype(float) - first[region].astype(float)))
    distance_to_preview = np.mean(np.abs(captured_frame[region].astype(float) - preview[region].astype(float)))
    assert distance_to_video < distance_to_preview / 2
    assert client.post(BASE + f"/requests/{record['id']}/publish", headers=ALICE,
                       json={"publish_selected_photos": True}).status_code == 409


def test_whole_video_upload_fallback_keeps_automatic_scan_evidence_checks(setup):
    client, clock, tmp, _ = setup
    record = create(client).json()
    stage = complete_scan(client, record, clock)
    response = submit(client, record, stage, video(tmp, 16))
    assert response.status_code == 202, response.text
    final = detail(client, record)
    assert final["status"] == "inconclusive"
    assert final["analysis_status"] == "unavailable"
    assert final["analysis"]["video"]["duration_seconds"] == 16
    assert any(media["role"] == "frame" for media in final["media"])


def test_repeated_finish_is_idempotent_but_cannot_change_the_assembled_recording(setup):
    client, clock, tmp, _ = setup
    record = create(client).json()
    stage = complete_scan(client, record, clock)
    response = upload_video(client, record, stage, video(tmp, 16), pieces=2)
    assert response.status_code == 202, response.text
    before = detail(client, record)
    assert finish(client, record, stage, count=2).status_code == 202
    assert finish(client, record, stage, count=1).status_code == 409
    assert chunk(client, record, stage, 0, b"replacement").status_code in (404, 409)
    after = detail(client, record)
    assert after["submitted"] == before["submitted"]
    assert [(media["id"], media["sha256"]) for media in after["media"]] == [
        (media["id"], media["sha256"]) for media in before["media"]]


def test_bad_assembled_video_finishes_as_inconclusive_without_sticking(setup):
    client, clock, _, _ = setup
    record = create(client).json()
    stage = complete_scan(client, record, clock)
    response = upload_video(client, record, stage, b"not really a camera recording")
    assert response.status_code in (415, 422, 202), response.text
    record_detail = detail(client, record)
    assert record_detail["status"] != "confirmed"
    if response.status_code == 202:
        assert record_detail["status"] == "inconclusive"
        assert record_detail["analysis_status"] == "failed"
    else:
        assert record_detail["status"] == "capturing"


@pytest.mark.parametrize("failure", ["undecodable_mp4", "recording_too_short"])
def test_background_decoder_failure_never_leaves_a_pending_verification(setup, failure):
    client, clock, tmp, _ = setup
    record = create(client).json()
    stage = complete_scan(client, record, clock)
    content = (b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 100
               if failure == "undecodable_mp4" else video(tmp, 2))
    response = upload_video(client, record, stage, content)
    assert response.status_code == 202, response.text
    final = detail(client, record)
    assert final["status"] == "inconclusive"
    assert final["analysis_status"] == "failed"
    assert not [media for media in final["media"] if media["role"] == "frame"]
    assert client.post(BASE + f"/requests/{record['id']}/publish", headers=ALICE,
                       json={"publish_selected_photos": True}).status_code == 409


def test_one_assembled_video_cannot_verify_a_second_request(setup):
    client, clock, tmp, _ = setup
    content = video(tmp, 16)
    first = create(client).json()
    first_stage = complete_scan(client, first, clock)
    assert upload_video(client, first, first_stage, content).status_code == 202
    other = create(client).json()
    other_stage = complete_scan(client, other, clock)
    assert upload_video(client, other, other_stage, content).status_code == 409
    assert detail(client, other)["status"] == "capturing"


@pytest.mark.parametrize("changes,expected", [
    ({}, "confirmed"),
    ({"same_item": "contradicted"}, "mismatch"),
    ({"photos": []}, "inconclusive"),
    ({"challenge_actions": "unclear"}, "inconclusive"),
    ({"distinguishing_details": ["Same model only"]}, "inconclusive"),
    ({"photos": [{"photo_index": i, "finding": "supported", "evidence": "Invalid video citation", "frame_indices": [999]} for i in range(4)]}, "inconclusive"),
])
def test_fast_scan_keeps_the_existing_photo_specific_approval_gate(setup, changes, expected):
    client, clock, tmp, monkeypatch = setup
    record = create(client).json()
    stage = complete_scan(client, record, clock)
    model_ready(monkeypatch, assessment(**changes))
    response = upload_video(client, record, stage, video(tmp, 16))
    assert response.status_code == 202, response.text
    assert detail(client, record)["status"] == expected


def test_confirmed_no_login_scan_keeps_management_and_publication_separate(setup):
    client, clock, tmp, monkeypatch = setup
    record = create(client, access_headers={}).json()
    stage = complete_scan(client, record, clock)
    model_ready(monkeypatch, assessment())
    assert upload_video(client, record, stage, video(tmp, 16)).status_code == 202
    management = {"X-LockX-Manage-Key": record["manage_key"]}
    assert client.get(BASE + "/requests/" + record["id"]).status_code == 401
    assert client.get(BASE + "/requests/" + record["id"], headers=management).json()["status"] == "confirmed"
    path = BASE + f"/requests/{record['id']}/publish"
    assert client.post(path, headers={"X-LockX-Manage-Key": record["token"]}, json={"publish_selected_photos": True}).status_code == 404
    assert client.post(path, headers=BOB, json={"publish_selected_photos": True}).status_code == 404
    response = client.post(path, headers=management, json={"publish_selected_photos": True})
    assert response.status_code == 201, response.text
    public = client.get(BASE + "/public/" + response.json()["id"]).json()
    assert public["photo_count"] == 4
    assert not {"token", "session_id", "manage_key", "analysis", "media"} & public.keys()


def test_creation_uses_one_grouped_planning_call(setup):
    client, _, _, monkeypatch = setup
    monkeypatch.setenv('OPENAI_API_KEY', 'test-placeholder')
    monkeypatch.setenv('LOCKX_IN_HAND_VISION_MODEL', 'test-model')
    calls = []
    def plan_once(schema, *args, **kwargs):
        calls.append(schema)
        return ih.ScanPlan(groups=[ih.ScanGroup(photo_indices=[i], label=f'View {i}', instruction='Show its identifying detail clearly.') for i in range(4)])
    monkeypatch.setattr(ih, 'vision_call', plan_once)
    record = create(client).json()
    assert calls == [ih.ScanPlan]
    stage = scan_start(client, record)
    assert sorted(i for step in stage['stages'] for i in step['photo_indices']) == list(range(4))
