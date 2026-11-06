"""Lighting assistance is reserved for a quality-failed first capture."""

import json

import cv2
import numpy as np
import pytest

import in_hand as ih
from test_in_hand import BASE, assessment, create, model_ready, setup
from test_in_hand_auto_publish import owner_headers, phone_result
from test_in_hand_fast import chunk, finish
from test_in_hand_identifiers import encode, identifier, surface_photo
from test_in_hand_recovery import video_start


def quality_frames(kind):
    base=cv2.GaussianBlur(surface_photo(0),(41,41),12)
    positions={"shake":[0,32,-32,32,-32,32],"pan":[0,24,48,72,96,120],"defocus":[0]*6}
    if kind=="dark":
        return [(i,encode(np.full_like(base,8)),"Decoded dark frame") for i in range(6)]
    return [(i,encode(cv2.warpAffine(base,np.float32([[1,0,x],[0,1,0]]),(640,480),borderMode=cv2.BORDER_WRAP)),"Decoded frame")
            for i,x in enumerate(positions[kind])]


@pytest.mark.parametrize("kind,expected",[("dark","low_light"),("shake","motion_blur"),("pan",None),("defocus",None)])
def test_capture_quality_diagnostics_require_actual_darkness_or_blurred_direction_reversals(kind,expected):
    frames=quality_frames(kind)
    checks=[ih.frame_quality(frame[1]) for frame in frames]
    diagnostic=ih.capture_quality_diagnostics(frames,checks)
    assert diagnostic["retry_reason"]==expected
    assert diagnostic["sampled_frames"]==len(frames)
    if kind=="shake":
        assert diagnostic["blurred_frames"]==len(frames)
        assert diagnostic["motion_direction_reversals"]>=2
    if kind in {"pan","defocus"}:
        assert diagnostic["blurred_frames"]==len(frames),"Blur alone cannot be called a shaky capture"
        assert diagnostic["motion_direction_reversals"]==0


def quality_video(tmp,kind):
    path=tmp/f"quality-{kind}.mp4"
    writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*"mp4v"),8,(320,240))
    assert writer.isOpened()
    base=cv2.GaussianBlur(cv2.resize(surface_photo(0),(320,240)),(31,31),10)
    for index in range(80):
        if kind=="dark":
            picture=np.full((240,320,3),8,dtype=np.uint8)
        else:
            offset=20 if (index//4)%2 else -20
            picture=cv2.warpAffine(base,np.float32([[1,0,offset],[0,1,0]]),(320,240),borderMode=cv2.BORDER_WRAP)
        writer.write(picture)
    writer.release()
    return path.read_bytes()


def quality_assessment(reason="low_light",**changes):
    return assessment(same_item="inconclusive",distinguishing_details=[],
                      photos=[{"photo_index":i,"finding":"not_established","evidence":"Video capture quality prevents matching this attempted view.","frame_indices":[0]} for i in range(4)],
                      capture_failure_reason=reason,**changes)


def quality_capture(setup,reason="low_light",*,visual=None,**listing):
    client,clock,tmp,monkeypatch=setup
    response=create(client,access_headers={},auto_publish=True,publish_matched_photos=True,**listing)
    assert response.status_code==201,response.text
    record=response.json()
    stage=video_start(client,record)
    assert chunk(client,record,stage,0,quality_video(tmp,"dark" if reason=="low_light" else "shake")).status_code==200
    clock[0]+=10.1
    model_ready(monkeypatch,visual or quality_assessment(reason))
    response=finish(client,record,stage,recording_seconds=10)
    assert response.status_code==202,response.text
    return record


def retry(client,record,**payload):
    return client.post(BASE+f"/seller/{record['token']}/retry-capture",json={"consent":True,**payload})


def stored_record(record_id):
    with ih.database() as db:
        row=dict(db.execute("SELECT * FROM ih_requests WHERE id=?",(record_id,)).fetchone())
        media=[dict(media) for media in db.execute("SELECT * FROM ih_media WHERE request_id=? ORDER BY rowid",(record_id,))]
        events=[tuple(event) for event in db.execute("SELECT * FROM ih_events WHERE request_id=? ORDER BY rowid",(record_id,))]
    return row,media,events


@pytest.mark.parametrize("reason",["low_light","motion_blur"])
def test_quality_failed_first_capture_creates_one_new_inspection_with_identical_references_and_consent(setup,reason):
    client,_,_,_=setup
    record=quality_capture(setup,reason)
    result=phone_result(client,record)
    assert result["status"]=="inconclusive" and result["analysis_status"]=="complete"
    assert result["verified_count"]==0 and result["capture_retry_reason"]==reason
    before=stored_record(record["id"])
    with ih.database() as db:
        diagnostic=json.loads(before[0]["analysis"])["video"]["quality_diagnostics"]
        assert diagnostic["retry_reason"]==reason
        assert db.execute("SELECT COUNT(*) FROM ih_publications WHERE request_id=?",(record["id"],)).fetchone()[0]==0
    response=retry(client,record)
    assert response.status_code in {200,201},response.text
    child=response.json()
    assert child["id"]!=record["id"] and child["token"]!=record["token"]
    assert child["capture_retry_reason"]==reason
    assert "manage_key" not in child
    parent_after=stored_record(record["id"])
    assert parent_after[0]==before[0] and parent_after[1]==before[1],"The failed inspection and its evidence must be immutable"
    child_row,child_media,_=stored_record(child["id"])
    assert child_row["owner_id"]==before[0]["owner_id"]
    assert json.loads(child_row["listing"])==json.loads(before[0]["listing"])
    assert child_row["status"]=="waiting" and not child_row["session_id"]
    original_refs=[media for media in before[1] if media["role"]=="listing"]
    assert len(child_media)==len(original_refs)==4
    assert all(media["role"]=="listing" for media in child_media)
    for source,cloned in zip(original_refs,child_media):
        assert source["content"]==cloned["content"] and source["sha256"]==cloned["sha256"]
        assert source["id"]!=cloned["id"]
    detail=client.get(BASE+f"/seller/{child['token']}")
    assert detail.status_code==200 and detail.json()["capture_retry_reason"]==reason
    assert "capture_retry_reason" not in client.get(BASE+f"/seller/{record['token']}").json(),"Only a retry capture enables lighting assistance"
    again=retry(client,record)
    assert again.status_code in {200,201} and again.json()==child
    assert client.get(BASE+f"/requests/{child['id']}").status_code==401
    assert client.get(BASE+f"/requests/{child['id']}",headers={"X-LockX-Manage-Key":child["token"]}).status_code==404
    assert client.delete(BASE+f"/requests/{child['id']}/publication",headers={"X-LockX-Manage-Key":child["token"]}).status_code==404
    assert retry(client,child).status_code==409,"A child cannot create an unlimited chain of new inspections"


@pytest.mark.parametrize("case",[
    "missing_views","other","legacy_reason_absent","number_mismatch","reference_unreadable",
    "identity_contradicted","continuity_suspicious","challenge_not_followed","global_concern",
    "partial_capture","quality_override","replay_note","wrong_diagnostic","digital","matched_subset",
])
def test_non_quality_or_integrity_failures_cannot_enable_lighting_retry(setup,case):
    client,_,_,_=setup
    record=quality_capture(setup)
    with ih.database() as db:
        row=db.execute("SELECT * FROM ih_requests WHERE id=?",(record["id"],)).fetchone()
        analysis=json.loads(row["analysis"])
        listing=json.loads(row["listing"])
        visual=analysis["visual"]
        if case in {"missing_views","other"}:
            visual["capture_failure_reason"]=case
        elif case=="legacy_reason_absent":
            visual.pop("capture_failure_reason",None)
        elif case=="number_mismatch":
            visual["identifier_checks"]=[identifier(reference_text="0012345",video_text="0012346",frame_indices=[0],finding="contradicted")]
        elif case=="reference_unreadable":
            visual["identifier_checks"]=[identifier(reference_text="",video_text="0012345",readability="unclear",frame_indices=[0],finding="not_established")]
        elif case=="identity_contradicted":
            visual["same_item"]="contradicted"
        elif case=="continuity_suspicious":
            visual["continuity"]="suspicious"
        elif case=="challenge_not_followed":
            visual["challenge_actions"]="not_followed"
        elif case=="global_concern":
            visual["concerns"]=["A different item appears during the recording."]
        elif case in {"partial_capture","quality_override"}:
            observations=[{"label":"Unsafe inherited capture","seconds":10,"recording_end":True,case:True}]
            db.execute("UPDATE ih_sessions SET observations=? WHERE id=?",(json.dumps(observations),row["session_id"]))
        elif case=="replay_note":
            analysis["video"]["notes"].append("Recording was reused from a previous inspection.")
        elif case=="wrong_diagnostic":
            analysis["video"]["quality_diagnostics"]["retry_reason"]="motion_blur"
        elif case=="digital":
            listing["capture_mode"]="digital"
        elif case=="matched_subset":
            analysis["video"]["notes"]=[]
            visual["same_item"]="supported"
            visual["challenge_actions"]="followed"
            visual["continuity"]="consistent"
            visual["distinguishing_details"]=["Distinct cut beside lower left mark","Uneven corner scratch on the same edge"]
            visual["photos"][0]["finding"]="supported"
        db.execute("UPDATE ih_requests SET analysis=?,listing=? WHERE id=?",(json.dumps(analysis),json.dumps(listing),record["id"]))
    before=stored_record(record["id"])
    response=retry(client,record)
    assert response.status_code==409,response.text
    assert stored_record(record["id"])[0:2]==before[0:2]
    assert "capture_retry_reason" not in phone_result(client,record)
    with ih.database() as db:
        assert db.execute("SELECT COUNT(*) FROM ih_capture_retries WHERE parent_request_id=?",(record["id"],)).fetchone()[0]==0


def test_quality_retry_requires_explicit_consent_and_the_original_capture_capability(setup):
    client,_,_,_=setup
    record=quality_capture(setup)
    for payload in ({},{"consent":False},{"consent":"true"}):
        response=client.post(BASE+f"/seller/{record['token']}/retry-capture",json=payload)
        assert response.status_code==422,response.text
    for token in ("unknown",record["manage_key"],record["id"]):
        response=client.post(BASE+f"/seller/{token}/retry-capture",json={"consent":True})
        assert response.status_code==404,response.text
    response=client.post(BASE+f"/seller/{record['token']}/retry-capture",json={"consent":True,"owner_id":"other"})
    assert response.status_code==422,response.text
