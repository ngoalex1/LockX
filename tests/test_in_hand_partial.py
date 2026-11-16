"""Only individually established photos may receive a public QR marking."""

import io
import json
import threading
from collections import Counter
import zipfile

import pytest

import in_hand as ih
from test_in_hand import BASE, assessment, jpeg, setup
from test_in_hand_auto_publish import (
    assert_no_publication, check_video, decode_marking, owner_detail,
    owner_headers, phone_result,
)
from test_in_hand_identifiers import identifier


def partial_assessment(*, failed_index=1, finding="contradicted", **changes):
    visual = assessment(**changes)
    visual.photos[failed_index].finding = finding
    visual.photos[failed_index].evidence = "This reference has a different individual mark."
    return visual


def partial_check(setup, *, visual=None, **listing):
    return check_video(setup, visual=visual or partial_assessment(),
                       **{"auto_publish": True, "publish_matched_photos": True, **listing})


def assert_subset(result, expected, *, total=4):
    assert result["eligible_photo_indices"] == expected
    assert result["verified_count"] == len(expected)
    assert result["total_count"] == total
    assert result["partial"] is (0 < len(expected) < total)


def test_three_matches_export_only_three_originally_indexed_qr_photos(setup):
    client, _, _, _ = setup
    record = partial_check(setup)
    result = phone_result(client, record)
    assert result["status"] == result["result"] == "mismatch"
    assert result["analysis_status"] == "complete"
    assert [photo["finding"] for photo in result["photos"]] == [
        "supported", "contradicted", "supported", "supported"]
    assert_subset(result, [0, 2, 3])
    assert result["publication_status"] == "ready"
    publication = result["publication"]
    assert [photo["photo_index"] for photo in publication["photos"]] == [0, 2, 3]
    public_response = client.get(BASE + "/public/" + publication["id"])
    assert public_response.status_code == 200, public_response.text
    public = public_response.json()
    assert public["status"] == "verified" and public["photo_count"] == 3
    assert_subset(public, [0, 2, 3])
    assert public["photos"] == publication["photos"]
    assert [photo["label"] for photo in public["photos"]] == [
        "Verified photo 1", "Verified photo 3", "Verified photo 4"]
    with ih.database() as db:
        persisted = db.execute(
            "SELECT photo_index,media_id FROM ih_publication_photos WHERE publication_id=? ORDER BY photo_index",
            (publication["id"],)).fetchall()
        assert [dict(photo) for photo in persisted] == [
            {"photo_index": photo["photo_index"], "media_id": photo["id"]} for photo in public["photos"]]
        assert db.execute("SELECT total_count FROM ih_publication_scopes WHERE publication_id=?",
                          (publication["id"],)).fetchone()[0] == 4
    expected_qr = "https://lockx.ai/#in-hand/verify/" + publication["id"]
    exported = {}
    for photo in public["photos"]:
        response = client.get(BASE + f"/public/{publication['id']}/photos/{photo['id']}")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        # Decode every complete JPEG, rather than cropping a QR in isolation.
        assert decode_marking(response.content) == expected_qr
        exported[photo["id"]] = response.content
    # Backward-compatible downloads also contain only the approved subset.
    for path, headers in [
        (f"/seller/{record['token']}/marked-photos", {}),
        (f"/requests/{record['id']}/marked-photos", owner_headers(record)),
    ]:
        response = client.get(BASE + path, headers=headers)
        assert response.status_code == 200, response.text
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            assert len(archive.namelist()) == 3
            assert sorted(archive.read(name) for name in archive.namelist()) == sorted(exported.values())
    # Public metadata never includes failed originals, private video or evidence.
    private = owner_detail(client, record)
    originals = [photo for photo in private["media"] if photo["role"] == "listing"]
    assert len(originals) == 4
    private_ids = {media["id"] for media in private["media"] if media["role"] != "marked"}
    assert not private_ids & set(exported)
    for media_id in private_ids:
        assert media_id not in json.dumps(public)
        assert client.get(BASE + f"/public/{publication['id']}/photos/{media_id}").status_code == 404
    assert record["manage_key"] not in json.dumps(public)
    assert record["token"] not in json.dumps(public)
    assert not {"analysis", "events", "session_id", "owner_id", "description", "details"} & public.keys()
    assert len([media for media in private["media"] if media["role"] == "marked"]) == 3


@pytest.mark.parametrize("finding,status", [("contradicted", "mismatch"), ("not_established", "inconclusive")])
def test_unmatched_or_unclear_photo_is_excluded_without_blocking_other_matches(setup, finding, status):
    client, _, _, _ = setup
    record = partial_check(setup, visual=partial_assessment(finding=finding))
    result = phone_result(client, record)
    assert result["status"] == status and result["publication_status"] == "ready"
    assert_subset(result, [0, 2, 3])
    assert [photo["photo_index"] for photo in result["publication"]["photos"]] == [0, 2, 3]


def test_supported_label_without_cited_video_cannot_receive_a_marking(setup):
    client, _, _, _ = setup
    visual = assessment()
    visual.photos[1].frame_indices = []
    record = partial_check(setup, visual=visual)
    result = phone_result(client, record)
    assert result["status"] == "inconclusive"
    assert_subset(result, [0, 2, 3])
    assert result["publication_status"] == "ready"
    assert [photo["photo_index"] for photo in result["publication"]["photos"]] == [0, 2, 3]


@pytest.mark.parametrize("changes,expected_status,expected_finding", [
    ({"reference_text": "001027", "video_text": "001072"}, "mismatch", "contradicted"),
    ({"readability": "unclear", "video_text": "0010?7"}, "inconclusive", "not_established"),
])
def test_number_difference_or_uncertainty_excludes_only_its_reference(setup, changes, expected_status, expected_finding):
    client, _, _, _ = setup
    visual = assessment(identifier_checks=[identifier(photo_index=2, frame_indices=[0], **changes)])
    record = partial_check(setup, visual=visual)
    result = phone_result(client, record)
    assert result["status"] == expected_status
    assert result["photos"][2]["finding"] == expected_finding
    assert result["identifier_checks"][0]["finding"] == expected_finding
    assert_subset(result, [0, 1, 3])
    assert result["publication_status"] == "ready"
    assert [photo["photo_index"] for photo in result["publication"]["photos"]] == [0, 1, 3]


@pytest.mark.parametrize("case", [
    "continuity_suspicious", "continuity_unclear", "challenge_not_followed",
    "challenge_unclear", "concern", "same_model_only", "no_distinctive_marks",
    "unsupported_claim", "missing_claim", "global_wrong_item", "missing_photo",
    "invalid_citation", "partial_capture", "digital", "poor_video",
])
def test_a_supported_subset_cannot_bypass_global_evidence_requirements(setup, case):
    client, _, _, monkeypatch = setup
    visual = partial_assessment()
    listing = {}
    if case.startswith("continuity_"):
        visual.continuity = case.removeprefix("continuity_")
    elif case.startswith("challenge_"):
        visual.challenge_actions = case.removeprefix("challenge_")
    elif case == "concern":
        visual.concerns = ["The object appears replaced between views."]
    elif case == "same_model_only":
        visual.distinguishing_details = ["Same model only"]
    elif case == "no_distinctive_marks":
        visual.distinguishing_details = []
    elif case == "unsupported_claim":
        visual.claims = [ih.Finding(subject="Guaranteed genuine", finding="not_established",
                                    evidence="Authenticity cannot be established.", frame_indices=[0])]
    elif case == "missing_claim":
        listing["description"] = "Guaranteed genuine"
    elif case == "global_wrong_item":
        # A global contradiction with no local explanation must fail closed.
        visual = assessment(same_item="contradicted")
    elif case == "missing_photo":
        visual.photos.pop()
    elif case == "invalid_citation":
        visual.photos[0].frame_indices = [999]
    elif case == "partial_capture":
        listing["partial"] = True
    elif case == "digital":
        listing["capture_mode"] = "digital"
    elif case == "poor_video":
        # Keep the real decode/comparison, adding an authoritative quality note.
        real_analyze = ih.analyze
        def with_quality_note(request_id):
            with ih.database() as db:
                row = db.execute("SELECT analysis FROM ih_requests WHERE id=?", (request_id,)).fetchone()
                analysis = json.loads(row[0])
                analysis["video"]["notes"].append("Most sampled views have lighting or focus issues.")
                db.execute("UPDATE ih_requests SET analysis=? WHERE id=?", (json.dumps(analysis), request_id))
            return real_analyze(request_id)
        monkeypatch.setattr(ih, "analyze", with_quality_note)
    record = partial_check(setup, visual=visual, **listing)
    result = phone_result(client, record)
    assert result["status"] != "confirmed"
    assert_subset(result, [])
    assert result["publication_status"] != "ready" and not result.get("publication")
    assert_no_publication(record)
    assert client.get(BASE + f"/seller/{record['token']}/marked-photos").status_code == 409
    assert client.post(BASE + f"/requests/{record['id']}/publish", headers=owner_headers(record),
                       json={"publish_selected_photos": True}).status_code == 409


@pytest.mark.parametrize("same_item", ["supported", "contradicted", "inconclusive"])
def test_local_contradiction_can_explain_global_negative_but_never_confirms_the_full_set(setup, same_item):
    client, _, _, _ = setup
    record = partial_check(setup, visual=partial_assessment(same_item=same_item))
    result = phone_result(client, record)
    assert result["status"] == "mismatch"
    assert_subset(result, [0, 2, 3])
    assert result["publication_status"] == "ready"


@pytest.mark.parametrize("finding", ["contradicted", "not_established"])
def test_no_supported_photos_produces_no_verified_exports(setup, finding):
    client, _, _, _ = setup
    visual = assessment()
    for photo in visual.photos:
        photo.finding = finding
    record = partial_check(setup, visual=visual)
    result = phone_result(client, record)
    assert_subset(result, [])
    assert result["publication_status"] != "ready" and not result.get("publication")
    assert_no_publication(record)


def test_prior_all_photos_consent_requires_explicit_subset_consent_without_repeating_ai(setup):
    client, _, _, _ = setup
    comparisons = []
    record = check_video(setup, visual=partial_assessment(), auto_publish=True, comparison_calls=comparisons)
    result = phone_result(client, record)
    assert_subset(result, [0, 2, 3])
    assert result["publication_status"] == "consent_required" and not result.get("publication")
    assert_no_publication(record)
    path = BASE + f"/seller/{record['token']}/enable-matched-photos"
    for payload in ({}, {"publish_matched_photos": True},
                    {"publish_matched_photos": False, "consent": True},
                    {"publish_matched_photos": True, "consent": False}):
        assert client.post(path, json=payload).status_code == 422
    response = client.post(path, json={"publish_matched_photos": True, "consent": True})
    assert response.status_code in {200, 202}, response.text
    ready = phone_result(client, record)
    assert ready["status"] == "mismatch" and ready["publication_status"] == "ready"
    assert [photo["photo_index"] for photo in ready["publication"]["photos"]] == [0, 2, 3]
    assert comparisons == [ih.VisualAssessment]
    # Repeating this explicit opt-in is idempotent and grants no management key.
    repeated = client.post(path, json={"publish_matched_photos": True, "consent": True})
    assert repeated.status_code in {200, 202}
    assert phone_result(client, record)["publication"] == ready["publication"]
    assert record["manage_key"] not in repeated.text


@pytest.mark.parametrize("listing", [{}, {"auto_publish": False}])
def test_legacy_private_capture_cannot_be_silently_published_by_camera_link(setup, listing):
    client, _, _, _ = setup
    record = check_video(setup, visual=partial_assessment(), **listing)
    result = phone_result(client, record)
    assert_subset(result, [0, 2, 3])
    assert result.get("publication_status", "not_requested") == "not_requested"
    assert_no_publication(record)
    response = client.post(BASE + f"/seller/{record['token']}/enable-matched-photos",
                           json={"publish_matched_photos": True, "consent": True})
    assert response.status_code == 403
    assert_no_publication(record)
    # An authorized owner can explicitly choose the verified subset.
    response = client.post(BASE + f"/requests/{record['id']}/publish", headers=owner_headers(record),
                           json={"publish_selected_photos": True})
    assert response.status_code == 201, response.text
    public = client.get(BASE + "/public/" + response.json()["id"]).json()
    assert_subset(public, [0, 2, 3])
    assert not phone_result(client, record).get("publication")


def test_subset_publication_is_idempotent_and_withdrawal_cannot_be_revived(setup):
    client, _, _, _ = setup
    record = partial_check(setup)
    initial = phone_result(client, record)["publication"]
    for _ in range(3):
        ih.auto_publish_confirmed(record["id"])
        assert phone_result(client, record)["publication"] == initial
    manual = client.post(BASE + f"/requests/{record['id']}/publish", headers=owner_headers(record),
                         json={"publish_selected_photos": True})
    assert manual.status_code == 201 and manual.json()["id"] == initial["id"]
    with ih.database() as db:
        assert db.execute("SELECT COUNT(*) FROM ih_publications WHERE request_id=?", (record["id"],)).fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM ih_media WHERE request_id=? AND role='marked'", (record["id"],)).fetchone()[0] == 3
    assert client.delete(BASE + f"/requests/{record['id']}/publication", headers=owner_headers(record)).status_code == 200
    assert client.post(BASE + f"/seller/{record['token']}/enable-matched-photos",
                       json={"publish_matched_photos": True, "consent": True}).status_code == 409
    ih.auto_publish_confirmed(record["id"])
    assert phone_result(client, record)["publication_status"] == "withdrawn"
    assert client.get(BASE + "/public/" + initial["id"]).json()["status"] == "withdrawn"
    for photo in initial["photos"]:
        assert client.get(BASE + f"/public/{initial['id']}/photos/{photo['id']}").status_code == 404
    assert client.get(BASE + f"/seller/{record['token']}/marked-photos").status_code == 409


@pytest.mark.parametrize("partial", [False, True])
def test_unmapped_legacy_full_publications_remain_valid_without_expanding_partial_exports(setup, partial):
    client, _, _, _ = setup
    record = partial_check(setup, visual=partial_assessment() if partial else assessment())
    publication = phone_result(client, record)["publication"]
    # Simulate a database written before original-reference maps were introduced.
    with ih.database() as db:
        db.execute("DELETE FROM ih_publication_photos WHERE publication_id=?", (publication["id"],))
        db.execute("DELETE FROM ih_publication_scopes WHERE publication_id=?", (publication["id"],))
    response = client.get(BASE + "/public/" + publication["id"])
    if partial:
        assert response.status_code in {404, 410}
        assert phone_result(client, record)["publication_status"] != "ready"
        for photo in publication["photos"]:
            assert client.get(BASE + f"/public/{publication['id']}/photos/{photo['id']}").status_code == 404
    else:
        assert response.status_code == 200, response.text
        public = response.json()
        assert public["photo_count"] == 4
        assert_subset(public, [0, 1, 2, 3])
        assert [photo["photo_index"] for photo in public["photos"]] == [0, 1, 2, 3]


def test_incomplete_persisted_manifest_cannot_silently_shrink_a_verified_cohort(setup):
    client, _, _, _ = setup
    record = partial_check(setup)
    publication = phone_result(client, record)["publication"]
    with ih.database() as db:
        db.execute("DELETE FROM ih_publication_photos WHERE publication_id=? AND photo_index=2",
                   (publication["id"],))
    assert client.get(BASE + "/public/" + publication["id"]).status_code == 410
    result = phone_result(client, record)
    assert result["publication_status"] == "failed" and not result.get("publication")
    assert_subset(result, [0, 2, 3])  # The AI findings themselves are retained.
    for photo in publication["photos"]:
        assert client.get(BASE + f"/public/{publication['id']}/photos/{photo['id']}").status_code == 404
    assert client.get(BASE + f"/seller/{record['token']}/marked-photos").status_code == 409


@pytest.mark.parametrize("persistent", [False, True])
def test_subset_render_failure_is_atomic_and_never_repeats_the_comparison(setup, persistent):
    client, _, _, monkeypatch = setup
    original_renderer = ih.marked_photo
    renders, comparisons, active = [], [], Counter()
    lock = threading.Lock()
    # Reference 0 is approved in this fixture. A speculative render error on
    # rejected reference 1 must not accidentally make this retry test pass.
    target = ih.clean_photo(jpeg(0))
    failed_attempts = set()
    def fail_during_subset(content, publication_id, captured):
        with lock:
            assert not any(count and key != publication_id for key,count in active.items()), "Retry overlapped an unfinished render attempt"
            active[publication_id] += 1
            renders.append(publication_id)
            should_fail = content == target and (persistent or not failed_attempts)
            if should_fail:
                failed_attempts.add(publication_id)
        try:
            if should_fail:
                raise RuntimeError("private render error must not leak")
            return original_renderer(content, publication_id, captured)
        finally:
            with lock:
                active[publication_id] -= 1
    monkeypatch.setattr(ih, "marked_photo", fail_during_subset)
    record = partial_check(setup, comparison_calls=comparisons)
    result = phone_result(client, record)
    assert result["status"] == "mismatch" and result["analysis_status"] == "complete"
    assert_subset(result, [0, 2, 3])
    assert comparisons == [ih.VisualAssessment]
    assert "private render error" not in str(result)
    attempts = Counter(renders)
    assert len(attempts) == 2
    assert all(1 <= count <= 4 for count in attempts.values())
    assert list(attempts.values())[1] <= 3
    assert not any(active.values())
    if persistent:
        assert result["publication_status"] == "failed" and not result.get("publication")
        assert len(failed_attempts) == 2
        assert_no_publication(record)
        before_retry = list(renders)
        ih.auto_publish_confirmed(record["id"])
        assert renders == before_retry, "Persistent failure must stay within two attempts"
    else:
        assert result["publication_status"] == "ready"
        assert len(result["publication"]["photos"]) == 3
        assert len(failed_attempts) == 1
        assert list(attempts.values())[1] == 3
        with ih.database() as db:
            assert db.execute("SELECT COUNT(*) FROM ih_media WHERE request_id=? AND role='marked'", (record["id"],)).fetchone()[0] == 3
    private = owner_detail(client, record)
    assert private["analysis"]["result"] == "mismatch"
    assert len(private["analysis"]["visual"]["photos"]) == 4
    assert any(media["role"] == "video" for media in private["media"])
