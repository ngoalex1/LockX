"""Actual pixel geometry gates optional highlights; it never supplies a verdict."""
import copy
import hashlib

import cv2
import numpy as np
import pytest

import evidence_regions as regions
import in_hand as ih
from test_in_hand import assessment


def encoded(image):
    ok, data = cv2.imencode(".png", image)
    assert ok
    return {"content": data.tobytes()}


def texture(seed=7):
    rng = np.random.default_rng(seed)
    image = rng.integers(0, 256, (480, 480), dtype=np.uint8)
    image = cv2.GaussianBlur(image, (3, 3), 0)
    # Unique local features at multiple scales support a real transform.
    for _ in range(50):
        x, y = rng.integers(20, 460, size=2)
        radius = int(rng.integers(3, 10))
        cv2.circle(image, (int(x), int(y)), radius, int(rng.integers(0, 256)), 2)
    return image


def candidate(**fields):
    return {"photo_index": 0, "frame_index": 0, "label": "Unique seam wear",
            "evidence": "The small interrupted seam matches both views.",
            "reference_box": {"x": .15, "y": .15, "width": .4, "height": .4},
            "frame_box": {"x": .19, "y": .175, "width": .4, "height": .4}, **fields}


@pytest.fixture
def pair():
    original = texture()
    transform = np.array([[1, 0, 19.2], [0, 1, 12], [0, 0, 1]], dtype=np.float64)
    translated = cv2.warpPerspective(original, transform, (480, 480))
    return [encoded(original)], [encoded(translated)]


def validate(pair, proposals=None, *, allowed=None, eligible=None):
    refs, frames = pair
    return regions.validate_regions(proposals if proposals is not None else [candidate()], refs, frames,
        allowed_frame_indices=[0] if allowed is None else allowed, eligible_photo_indices=eligible)


def test_translated_individual_texture_produces_a_grounded_pair_with_actual_media_hashes(pair):
    result = validate(pair)
    assert len(result) == 1
    found = result[0]
    assert found["reference_box"] == candidate()["reference_box"]
    assert found["frame_box"] == candidate()["frame_box"]
    assert found["provenance"] == "ai_highlight_geometrically_supported"
    assert found["reference_sha256"] == hashlib.sha256(pair[0][0]["content"]).hexdigest()
    assert found["frame_sha256"] == hashlib.sha256(pair[1][0]["content"]).hexdigest()
    assert not {"finding", "same_item", "confidence", "authentic", "verdict"} & found.keys()


def test_rotated_view_can_ground_a_small_detail_using_real_feature_correspondences():
    original = texture(12)
    rotation = cv2.getRotationMatrix2D((240, 240), 4, .98)
    transformed = cv2.warpAffine(original, rotation, (480, 480))
    proposal = candidate(reference_box={"x": .2, "y": .2, "width": .3, "height": .3},
                         frame_box={"x": .17, "y": .2, "width": .37, "height": .37})
    assert len(validate(([encoded(original)], [encoded(transformed)]), [proposal])) == 1


def test_matching_whole_images_do_not_validate_a_wrong_proposed_detail(pair):
    proposal = candidate(frame_box={"x": .6, "y": .6, "width": .3, "height": .3})
    assert validate(pair, [proposal]) == []


@pytest.mark.parametrize("kind", ["unrelated", "blank", "repeating", "corrupt", "tiny"])
def test_no_actual_unique_correspondence_means_no_highlight(kind):
    if kind == "unrelated":
        refs, frames = [encoded(texture(7))], [encoded(texture(8))]
    elif kind == "blank":
        refs = frames = [encoded(np.full((480, 480), 127, np.uint8))]
    elif kind == "repeating":
        grid = ((np.indices((480, 480)).sum(axis=0) // 8) % 2 * 255).astype(np.uint8)
        refs = frames = [encoded(grid)]
    elif kind == "corrupt":
        refs, frames = [{"content": b"not an image"}], [encoded(texture())]
    else:
        refs = frames = [encoded(np.zeros((20, 20), np.uint8))]
    assert validate((refs, frames)) == []


@pytest.mark.parametrize("box", [
    {"x": -.01, "y": .2, "width": .2, "height": .2},
    {"x": .9, "y": .2, "width": .2, "height": .2},
    {"x": .2, "y": .9, "width": .2, "height": .2},
    {"x": .2, "y": .2, "width": 0, "height": .2},
    {"x": .2, "y": .2, "width": .02, "height": .2},
    {"x": .2, "y": .2, "width": .7, "height": .7},
    {"x": float("nan"), "y": .2, "width": .2, "height": .2},
    {"x": .2, "y": float("inf"), "width": .2, "height": .2},
])
def test_invalid_unbounded_or_whole_item_boxes_are_omitted(pair, box):
    assert validate(pair, [candidate(reference_box=box)]) == []
    assert validate(pair, [candidate(frame_box=box)]) == []


@pytest.mark.parametrize("fields", [
    {"photo_index": -1}, {"photo_index": 7}, {"frame_index": -1}, {"frame_index": 5},
    {"frame_index": 1.5}, {"photo_index": 1.5},
    {"label": "QR redemption code"}, {"evidence": "The password is legible"},
    {"label": "   "},
])
def test_invalid_indices_and_sensitive_semantic_annotations_do_not_survive(pair, fields):
    assert validate(pair, [candidate(**fields)]) == []


def test_allowed_frame_indices_preserve_original_gaps_and_eligible_photo_subset(pair):
    refs, frames = pair
    sparse = (refs * 3, frames * 6)
    proposals = [candidate(photo_index=0, frame_index=1),
                 candidate(photo_index=0, frame_index=4),
                 candidate(photo_index=0, frame_index=0),  # zero is not selected
                 candidate(photo_index=1, frame_index=4),  # reference failed
                 candidate(photo_index=2, frame_index=4)]
    result = validate(sparse, proposals, allowed=[1, 4], eligible=[0, 2])
    assert [(item["photo_index"], item["frame_index"]) for item in result] == [(0, 1), (0, 4), (2, 4)]


def test_duplicate_regions_and_per_photo_limit_bound_public_annotations(pair):
    refs, frames = pair
    proposals = [candidate(frame_index=index) for index in range(6)] * 2
    result = validate((refs, frames * 6), proposals, allowed=list(range(6)))
    assert len(result) == 3
    assert [r["frame_index"] for r in result] == [0, 1, 2]


@pytest.mark.parametrize("malformed", [None, "bad", {"label": "oops"}, [None, 1, {}, {"unexpected": True}],
    [candidate(reference_box=None)], [candidate(extra="not allowed")]])
def test_malformed_optional_regions_leave_existing_assessment_and_recommendation_intact(malformed):
    visual = assessment()
    before = visual.model_dump()
    baseline = ih.recommendation(visual, 4, {})
    parsed = ih.VisualAssessment.model_validate({**before, "supporting_regions": malformed})
    assert parsed.supporting_regions == []
    assert parsed.photos == visual.photos
    assert parsed.same_item == visual.same_item
    assert ih.recommendation(parsed, 4, {}) == baseline


def test_geometry_does_not_modify_caller_photos_or_its_semantic_finding(pair):
    proposals = [candidate()]
    untouched = copy.deepcopy(proposals)
    before = assessment()
    before.photos[0].finding = "contradicted"
    verdict = ih.recommendation(before, 4, {})
    assert validate(pair, proposals)
    assert proposals == untouched
    assert before.photos[0].finding == "contradicted"
    assert ih.recommendation(before, 4, {}) == verdict

