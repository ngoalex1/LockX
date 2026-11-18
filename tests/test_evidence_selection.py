"""Real synthetic pixel/geometry regressions; no model or provider is called."""
import cv2
import numpy as np
import pytest

import evidence_selection as selection
import in_hand as ih
from test_in_hand_identifiers import surface_photo, encode, evidence_fixture


def test_half_second_window_retains_real_sharp_detail_between_old_two_fps_samples():
    sharp=surface_photo(0)
    blurred=cv2.GaussianBlur(sharp,(41,41),12)
    sampler=selection.SharpWindowSampler()
    for index in range(300):
        # Briefly legible at .267s; old samples at0/.5 miss this original frame.
        sampler.consider(sharp if index==8 else blurred,index/30)
    frames=sampler.finish()
    assert len(frames)==20 and sampler.examined==80
    assert frames[0][0]==8/30
    assert frames[0][1]==encode_jpeg88(sharp)
    assert [round(seconds*2) for seconds,_ in frames[1:]]==list(range(1,20))
    assert sampler.finish()==frames


def encode_jpeg88(frame):
    okay,data=cv2.imencode('.jpg',frame,[cv2.IMWRITE_JPEG_QUALITY,88])
    assert okay
    return data.tobytes()


@pytest.mark.parametrize('fps',[1,5,24,29.97,60,120])
def test_variable_fps_has_bounded_candidate_and_storage_counts_and_actual_timestamps(fps):
    frame=surface_photo(0)
    sampler=selection.SharpWindowSampler()
    count=round(fps*10)
    original_times={index/fps for index in range(count)}
    for index in range(count):sampler.consider(frame,index/fps)
    candidates=sampler.finish()
    assert sampler.examined<=81
    assert 1<=len(candidates)<=20
    assert all(seconds in original_times for seconds,_ in candidates)
    assert [seconds for seconds,_ in candidates]==sorted({seconds for seconds,_ in candidates})
    assert len({int(seconds*2+1e-6) for seconds,_ in candidates})==len(candidates)


def test_dark_clipped_and_sensor_grain_are_not_preferred_as_sharp_detail():
    rng=np.random.default_rng(73)
    real=surface_photo(0)
    dark=np.full_like(real,5)
    clipped=np.full_like(real,254)
    grain=np.clip(rng.normal(128,42,real.shape),0,255).astype(np.uint8)
    assert selection.capture_focus(real)>0
    assert selection.capture_focus(dark)==0
    assert selection.capture_focus(clipped)==0
    assert selection.capture_focus(grain)==0
    blurred=cv2.GaussianBlur(real,(31,31),10)
    assert selection.capture_focus(real)>selection.capture_focus(blurred)


def diversity_fixture():
    ref=surface_photo(0)
    blur=cv2.GaussianBlur(ref,(41,41),12)
    matrix=cv2.getPerspectiveTransform(np.float32([[0,0],[639,0],[639,479],[0,479]]),
                                      np.float32([[30,18],[615,8],[630,455],[12,468]]))
    angled=cv2.warpPerspective(ref,matrix,(640,480),borderValue=(225,225,225))
    frames=[{'content':encode(ref if index in {3,4,5} else angled if index==15 else blur),
             'seconds':index*.5,'label':str(index)} for index in range(20)]
    return [{'content':encode(ref)}],frames


def test_temporally_separated_coherent_angle_is_kept_instead_of_only_near_duplicates():
    refs,frames=diversity_fixture()
    before=[(frame['content'],frame['seconds']) for frame in frames]
    selected,metadata=ih.select_evidence_frames(refs,frames)
    assert len(selected)<=12
    assert {0,10,19,15}<=set(selected)
    assert metadata['reference_best_frames'][0]['feature_matches']>0
    assert before==[(frame['content'],frame['seconds']) for frame in frames]
    assert selected==sorted(set(selected))


def test_four_references_keep_real_geometrically_supported_views_under_same_twelve_image_budget(monkeypatch):
    refs,frames,useful=evidence_fixture()
    def no_model(*args,**kwargs):raise AssertionError('Pixel ranking cannot verify an item')
    monkeypatch.setattr(ih,'vision_call',no_model)
    selected,metadata=ih.select_evidence_frames(refs,frames)
    assert set(useful)<=set(selected)
    assert len(selected)<=12 and all(0<=index<len(frames) for index in selected)
    assert metadata['total_frames']==20
    assert all('result' not in entry and 'match_percentage' not in entry for entry in metadata['reference_best_frames'])


def test_unrelated_texture_cannot_create_a_coherent_feature_correspondence():
    a=surface_photo(0)
    unrelated=np.random.default_rng(997).integers(0,256,a.shape,dtype=np.uint8)
    result=selection.correspondence(ih.media_features({'content':encode(a)}),ih.media_features({'content':encode(unrelated)}))
    assert result['score']==0 and result['inliers']==0
