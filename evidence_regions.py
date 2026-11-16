"""Optional explanatory regions. Geometry never determines an item verdict."""
import hashlib
import math
import re

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, ValidationError


class EvidenceBox(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    x: float
    y: float
    width: float
    height: float


class EvidenceRegion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    photo_index: int
    frame_index: int
    label: str
    evidence: str
    reference_box: EvidenceBox
    frame_box: EvidenceBox


def parse_region_candidates(value):
    """Bad optional annotations do not invalidate the existing assessment."""
    output = []
    for item in value[:18] if isinstance(value, list) else []:
        try:
            output.append(EvidenceRegion.model_validate(item))
        except (ValidationError, TypeError, ValueError):
            continue
    return output


def _image(media):
    image = cv2.imdecode(np.frombuffer(media["content"], np.uint8), cv2.IMREAD_GRAYSCALE)
    if image is None or min(image.shape) < 32:
        return None
    height, width = image.shape
    scale = min(1, 800 / max(width, height))
    if scale < 1:
        image = cv2.resize(image, (round(width * scale), round(height * scale)))
    return image


def _box(box, image):
    values = [box.x, box.y, box.width, box.height]
    if (not all(math.isfinite(v) for v in values) or min(box.x, box.y) < 0
            or min(box.width, box.height) < .025 or box.x + box.width > 1
            or box.y + box.height > 1 or not .001 <= box.width * box.height <= .25):
        return None
    h, w = image.shape
    if min(box.width * w, box.height * h) < 12:
        return None
    return np.array([box.x*w, box.y*h, (box.x+box.width)*w, (box.y+box.height)*h])


def _inside(points, box):
    return ((points[:, 0] >= box[0]) & (points[:, 0] <= box[2])
            & (points[:, 1] >= box[1]) & (points[:, 1] <= box[3]))


def _unambiguous_patch(image,box):
    """Withhold highlights on repeated texture that can align in many places."""
    scale=min(1,320/max(image.shape))
    small=cv2.resize(image,None,fx=scale,fy=scale) if scale<1 else image
    x0,y0,x1,y1=np.round(box*scale).astype(int)
    patch=small[y0:y1,x0:x1]
    if min(patch.shape,default=0)<8 or float(patch.std())<10:
        return False
    correlations=cv2.matchTemplate(small,patch,cv2.TM_CCOEFF_NORMED)
    h,w=patch.shape
    # Adjacent shifts of the same detail are expected; separated near-identical
    # matches indicate a repeated pattern rather than a locatable detail.
    correlations[max(0,y0-h//2):y0+h//2+1,max(0,x0-w//2):x0+w//2+1]=-1
    return not np.any(correlations>.94)


def _matches(a, b):
    orb = cv2.ORB_create(nfeatures=1200, nlevels=6, fastThreshold=10)
    ka, da = orb.detectAndCompute(a, None)
    kb, db = orb.detectAndCompute(b, None)
    if da is None or db is None:
        return None
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    pairs = matcher.knnMatch(da, db, k=2)
    reverse={p[0].queryIdx:p[0].trainIdx for p in matcher.knnMatch(db,da,k=2)
             if len(p)==2 and p[0].distance<.72*p[1].distance}
    good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < .72*p[1].distance
            and reverse.get(p[0].trainIdx)==p[0].queryIdx]
    if len(good) < 8:
        return None
    src = np.float32([ka[m.queryIdx].pt for m in good])
    dst = np.float32([kb[m.trainIdx].pt for m in good])
    homography, mask = cv2.findHomography(src, dst, cv2.RANSAC, 3, maxIters=500)
    if homography is None or mask is None or not np.isfinite(homography).all():
        return None
    inliers = mask.ravel().astype(bool)
    if inliers.sum() < 8:
        return None
    return src[inliers], dst[inliers], homography


def validate_regions(candidates, refs, frames, *, allowed_frame_indices, eligible_photo_indices=None):
    """Keep bounded, pixel-grounded pairs; return [] when grounding is unclear.

    The model proposes the semantic label. Local geometric support checks the
    proposed locations, not whether a label is true or an item is authentic.
    """
    allowed = set(allowed_frame_indices)
    eligible = set(range(len(refs))) if eligible_photo_indices is None else set(eligible_photo_indices)
    images, correspondences, counts, seen, output = {}, {}, {}, set(), []
    for region in parse_region_candidates(candidates):
        pi, fi = region.photo_index, region.frame_index
        if pi not in eligible or not 0 <= pi < len(refs) or fi not in allowed or not 0 <= fi < len(frames) or counts.get(pi, 0) >= 3:
            continue
        label = " ".join(region.label.split())[:80]
        evidence = " ".join(region.evidence.split())[:240]
        if not label or re.search(r"barcode|\bqr\b|password|credential|redemption|access.?code", label + " " + evidence, re.I):
            continue
        for key, media in ((('r',pi), refs[pi]), (('f',fi), frames[fi])):
            if key not in images:
                images[key] = _image(media)
        a, b = images[('r',pi)], images[('f',fi)]
        if a is None or b is None:
            continue
        ab, bb = _box(region.reference_box, a), _box(region.frame_box, b)
        if ab is None or bb is None:
            continue
        if not _unambiguous_patch(a,ab) or not _unambiguous_patch(b,bb):
            continue
        pair = (pi,fi)
        if pair not in correspondences:
            correspondences[pair] = _matches(a,b)
        matches = correspondences[pair]
        if matches is None:
            continue
        source, target, homography = matches
        supported = _inside(source,ab) & _inside(target,bb)
        if int(supported.sum()) < 4:
            continue
        center = np.float32([[[float((ab[0]+ab[2])/2),float((ab[1]+ab[3])/2)]]])
        projected = cv2.perspectiveTransform(center,homography).reshape(2)
        if not np.isfinite(projected).all() or not _inside(projected.reshape(1,2),bb)[0]:
            continue
        key = (pi,fi,*[round(v,2) for v in region.reference_box.model_dump().values()])
        if key in seen:
            continue
        seen.add(key)
        counts[pi] = counts.get(pi,0)+1
        output.append({**region.model_dump(),"label":label,"evidence":evidence,
                       "provenance":"ai_highlight_geometrically_supported",
                       "reference_sha256":hashlib.sha256(refs[pi]["content"]).hexdigest(),
                       "frame_sha256":hashlib.sha256(frames[fi]["content"]).hexdigest()})
    return output
