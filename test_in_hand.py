import base64
import io
import json
import secrets
import time
import types
import zipfile

import cv2
import numpy as np
import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

import in_hand as ih

BASE = "/api/v1/in-hand"
ALICE = {"Authorization":"Bearer alice"}
BOB = {"Authorization":"Bearer bob"}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCKX_DATA_DIR",str(tmp_path))
    monkeypatch.setenv("LOCKX_PUBLIC_APP_ORIGIN","https://lockx.ai")
    for key in ("OPENAI_API_KEY","LOCKX_IN_HAND_VISION_MODEL"):
        monkeypatch.delenv(key,raising=False)
    clock = [time.time()]
    monkeypatch.setattr(ih,"time",types.SimpleNamespace(time=lambda:clock[0],gmtime=time.gmtime,strftime=time.strftime))
    def auth(authorization: str = Header(default="")):
        if not authorization.startswith("Bearer "):
            raise HTTPException(401)
        return authorization[7:]
    app=FastAPI()
    app.include_router(ih.create_router(auth))
    return TestClient(app),clock,tmp_path,monkeypatch


def jpeg(index=0, blank=False):
    image=Image.new("RGB",(320,240),"#c9d4bc")
    if not blank:
        draw=ImageDraw.Draw(image)
        for x in range(10,310,12):
            draw.line((x,10,320-x,230),fill="#254a3a",width=2)
        draw.rectangle((40+index*5,60,200,165),fill="#f5e9c2",outline="#31593c",width=4)
        draw.text((55,90),f"TEST ITEM {index}",fill="black")
    output=io.BytesIO();image.save(output,"JPEG")
    return output.getvalue()


def create(client, count=4, access_headers=ALICE, **changes):
    payload={"title":"Sample collectible","capture_mode":"handheld","consent":True,**changes}
    return client.post(BASE+"/requests",headers=access_headers,data={"payload":json.dumps(payload)},files=[("photos",(f"ref-{i}.jpg",jpeg(i),"image/jpeg")) for i in range(count)])


def test_no_login_creation_and_private_management_link(setup):
    client,*_=setup
    response=create(client,access_headers={})
    assert response.status_code==201,response.text
    r=response.json()
    assert len(r["manage_key"])==43 and r["manage_key"]!=r["token"]
    management={"X-LockX-Manage-Key":r["manage_key"]}
    assert client.get(BASE+"/requests/"+r["id"]).status_code==401
    assert client.get(BASE+"/requests/"+r["id"],headers=management).status_code==200
    assert client.get(BASE+"/media/"+r["media"][0]["id"],headers=management).status_code==200
    assert client.get(BASE+f"/requests/{r['id']}/evidence",headers=management).status_code==200
    assert "manage_key" not in client.get(BASE+"/seller/"+r["token"]).json()
    assert client.get(BASE+"/requests/"+r["id"],headers={"X-LockX-Manage-Key":r["token"]}).status_code==404
    with ih.database() as db:
        assert db.execute("SELECT digest FROM ih_access_keys WHERE request_id=?",(r["id"],)).fetchone()[0] != r["manage_key"]


def test_railway_volume_is_used_without_explicit_data_directory(setup):
    client,_,tmp,monkeypatch=setup
    monkeypatch.delenv("LOCKX_DATA_DIR")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID","production-test")
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH",str(tmp/"mounted-volume"))
    response=client.get(BASE+"/requests",headers={"X-LockX-Guest-Key":secrets.token_urlsafe(32)})
    assert response.status_code==200 and response.json()==[]
    assert (tmp/"mounted-volume"/"lockx"/"in-hand.sqlite3").exists()


def test_railway_without_persistent_storage_returns_service_error(setup):
    client,_,_,monkeypatch=setup
    monkeypatch.delenv("LOCKX_DATA_DIR")
    monkeypatch.delenv("RAILWAY_VOLUME_MOUNT_PATH",raising=False)
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID","production-test")
    response=client.get(BASE+"/requests",headers={"X-LockX-Guest-Key":secrets.token_urlsafe(32)})
    assert response.status_code==503 and "persistent storage" in response.json()["detail"]


def test_guest_browser_access_is_private_and_management_keys_are_per_inspection(setup):
    client,*_=setup
    browser={"X-LockX-Guest-Key":secrets.token_urlsafe(32)}
    r=create(client,access_headers=browser).json()
    other=create(client,access_headers=browser).json()
    assert len(client.get(BASE+"/requests",headers=browser).json())==2
    stranger={"X-LockX-Guest-Key":secrets.token_urlsafe(32)}
    assert client.get(BASE+"/requests",headers=stranger).json()==[]
    assert client.get(BASE+"/requests/"+r["id"],headers=stranger).status_code==404
    management={"X-LockX-Manage-Key":r["manage_key"]}
    assert [row["id"] for row in client.get(BASE+"/requests",headers=management).json()]==[r["id"]]
    for path in ("/requests/"+other["id"],"/requests/"+other["id"]+"/evidence","/media/"+other["media"][0]["id"]):
        assert client.get(BASE+path,headers=management).status_code==404
    assert client.delete(BASE+f"/requests/{other['id']}/publication",headers=management).status_code==404
    assert client.post(BASE+f"/requests/{other['id']}/publish",headers=management,json={"publish_selected_photos":True}).status_code==404
    assert client.get(BASE+"/requests",headers={"X-LockX-Guest-Key":"short"}).status_code==401


def start(client, record):
    response=client.post(BASE+f"/seller/{record['token']}/start")
    assert response.status_code==200,response.text
    return response.json()


def progress(client, record, stage, **changes):
    return client.post(BASE+f"/seller/{record['token']}/progress",json={"session_id":stage["session_id"],"stage_id":stage["stage"]["id"],"image":"data:image/jpeg;base64,"+base64.b64encode(jpeg()).decode(),**changes})


def complete(client, record, clock):
    stage=start(client,record)
    while not stage["complete"]:
        clock[0]+=ih.STAGE_SECONDS+.1
        response=progress(client,record,stage)
        assert response.status_code==200,response.text
        stage=response.json()
        assert not stage.get("retry"),stage
    return stage


def video(tmp_path, seconds, variant=0):
    path=tmp_path/f"capture-{variant}.mp4"
    writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*"mp4v"),5,(320,240))
    assert writer.isOpened()
    frame=cv2.imdecode(np.frombuffer(jpeg(variant),np.uint8),cv2.IMREAD_COLOR)
    for i in range(round(seconds*5)):
        picture=frame.copy()
        cv2.circle(picture,(20+(i*3)%280,20+(i*2)%200),7,(40,80,100),-1)
        writer.write(picture)
    writer.release()
    return path.read_bytes()


def submit(client,record,stage,content):
    return client.post(BASE+f"/seller/{record['token']}/submit",data={"payload":json.dumps({"session_id":stage["session_id"],"consent":True,"source":"browser_camera"})},files={"video":("capture.mp4",content,"video/mp4")})


def assessment(count=4, **changes):
    return ih.VisualAssessment.model_validate({"same_item":"supported","distinguishing_details":["Small scratch at lower left","Uneven mark beside serial label"],"challenge_actions":"followed","continuity":"consistent","photos":[{"photo_index":i,"finding":"supported","evidence":"The same specific marks appear in this view.","frame_indices":[i]} for i in range(count)],"claims":[],"concerns":[],"summary":"Selected photos correspond to the individual item shown.",**changes})


def model_ready(monkeypatch,result):
    monkeypatch.setenv("OPENAI_API_KEY","test-placeholder")
    monkeypatch.setenv("LOCKX_IN_HAND_VISION_MODEL","test-model")
    monkeypatch.setattr(ih,"vision_call",lambda *args,**kwargs:result)


def test_owner_boundaries_and_private_capture_view(setup):
    client,_,_,_=setup
    response=create(client)
    assert response.status_code==201,response.text
    r=response.json()
    assert len(r["media"])==4
    assert client.get(BASE+"/requests").status_code==401
    assert client.get(BASE+"/requests/"+r["id"],headers=BOB).status_code==404
    assert client.get(BASE+"/requests",headers=BOB).json()==[]
    media_id=r["media"][0]["id"]
    assert client.get(BASE+"/media/"+media_id,headers=BOB).status_code==404
    assert client.get(BASE+"/media/"+media_id).status_code==401
    public=client.get(BASE+"/seller/"+r["token"]).json()
    assert not {"token","owner_id","analysis","events","session_id"}&public.keys()
    assert client.get(BASE+f"/seller/{r['token']}/photos/{media_id}").status_code==200
    other=create(client).json()
    assert client.get(BASE+f"/seller/{other['token']}/photos/{media_id}").status_code==404


def test_private_record_requires_valid_images_and_permission(setup):
    client,*_=setup
    assert create(client,count=0).status_code in (400,422)
    assert create(client,count=7).status_code in (400,422)
    assert create(client,consent=False).status_code==422
    bad=client.post(BASE+"/requests",headers=ALICE,data={"payload":json.dumps({"title":"Item","consent":True})},files={"photos":("fake.jpg",b"not a photo","image/jpeg")})
    assert bad.status_code==415


def test_link_expiration_and_nonexistent_tokens(setup):
    client,clock,_,_=setup
    r=create(client).json()
    assert client.get(BASE+"/seller/incorrect").status_code==404
    clock[0]+=86401
    assert client.get(BASE+"/seller/"+r["token"]).status_code==410
    assert client.post(BASE+f"/seller/{r['token']}/start").status_code==410
    assert client.get(BASE+"/requests/"+r["id"],headers=ALICE).json()["status"]=="expired"


def test_order_minimum_time_and_restart_session_binding(setup):
    client,clock,_,_=setup
    r=create(client).json();stage=start(client,r)
    assert "stages" not in stage and "plan" not in stage
    assert progress(client,r,stage).status_code==425
    clock[0]+=4.1
    assert progress(client,r,stage,stage_id="photo-3").status_code==409
    next_stage=progress(client,r,stage).json()
    assert next_stage["position"]==1
    assert progress(client,r,stage).status_code==409
    fresh=start(client,r)
    assert fresh["session_id"]!=stage["session_id"]
    clock[0]+=4.1
    assert progress(client,r,next_stage).status_code==409
    assert progress(client,r,fresh).status_code==200


def test_quality_followup_and_recorded_override(setup):
    client,clock,_,_=setup
    r=create(client,count=1).json();stage=start(client,r);clock[0]+=4.1
    image="data:image/jpeg;base64,"+base64.b64encode(jpeg(blank=True)).decode()
    response=progress(client,r,stage,image=image)
    assert response.json()["retry"] and response.json()["position"]==0
    assert progress(client,r,stage,image=image,continue_with_quality_issue=True).json()["position"]==1
    with ih.database() as db:
        observations=json.loads(db.execute("SELECT observations FROM ih_sessions WHERE id=?",(stage["session_id"],)).fetchone()[0])
    assert observations[0]["quality_override"] is True


def test_interactive_reference_followup_does_not_approve_photo(setup):
    client,clock,_,monkeypatch=setup
    r=create(client,count=1).json();stage=start(client,r)
    while stage["stage"]["id"]!="photo-0":
        clock[0]+=4.1;stage=progress(client,r,stage).json()
    model_ready(monkeypatch,ih.ViewCheck(view="needs_another_view",instruction="Bring the lower left scratch closer."))
    clock[0]+=4.1
    result=progress(client,r,stage).json()
    assert result["retry"] and "scratch" in result["feedback"]
    assert result["position"]==stage["position"]
    assert progress(client,r,stage,continue_with_quality_issue=True).json()["complete"]
    detail=client.get(BASE+"/requests/"+r["id"],headers=ALICE).json()
    assert detail["status"]=="capturing" and detail["analysis"] is None


def test_incomplete_and_invalid_recordings_cannot_submit(setup):
    client,clock,tmp,_=setup
    r=create(client,count=1).json();stage=start(client,r)
    assert submit(client,r,stage,video(tmp,2,9)).status_code==409
    stage=complete(client,r,clock)
    assert submit(client,r,stage,b"not a video").status_code==415
    assert submit(client,r,stage,video(tmp,2)).status_code==422


def test_real_recording_without_analysis_is_inconclusive_not_verified(setup):
    client,clock,tmp,_=setup
    r=create(client).json();stage=complete(client,r,clock)
    response=submit(client,r,stage,video(tmp,stage["total"]*4+1))
    assert response.status_code==202,response.text
    detail=client.get(BASE+"/requests/"+r["id"],headers=ALICE).json()
    assert detail["status"]=="inconclusive" and detail["analysis_status"]=="unavailable"
    assert detail["analysis"]["video"]["sampled_frames"]==stage["total"]+4
    assert len([m for m in detail["media"] if m["role"]=="video"])==1
    assert submit(client,r,stage,b"another").status_code==202
    assert client.post(BASE+f"/requests/{r['id']}/publish",headers=ALICE,json={"publish_selected_photos":True}).status_code==409
    exported=client.get(BASE+f"/requests/{r['id']}/evidence",headers=ALICE).json()
    assert "token" not in exported["verification"]
    assert exported["verification"]["sessions"]


def test_one_recording_cannot_be_reused_in_another_request(setup):
    client,clock,tmp,_=setup
    r=create(client,count=1).json();stage=complete(client,r,clock);content=video(tmp,21)
    assert submit(client,r,stage,content).status_code==202
    other=create(client,count=1).json();other_stage=complete(client,other,clock)
    assert submit(client,other,other_stage,content).status_code==409


@pytest.mark.parametrize("changes,expected",[
    ({},"confirmed"),
    ({"same_item":"contradicted"},"mismatch"),
    ({"distinguishing_details":["Same model only"]},"inconclusive"),
    ({"distinguishing_details":["Same visible scratch","Same visible scratch"]},"inconclusive"),
    ({"challenge_actions":"unclear"},"inconclusive"),
    ({"continuity":"suspicious"},"inconclusive"),
    ({"concerns":["Unreadable identifying label"]},"inconclusive"),
    ({"photos":[]},"inconclusive"),
    ({"claims":[{"subject":"Genuine card","finding":"not_established","evidence":"Cannot establish authenticity visually.","frame_indices":[]}]},"inconclusive"),
    ({"claims":[{"subject":"No scratches","finding":"contradicted","evidence":"Scratch visible.","frame_indices":[0]}]},"mismatch"),
])
def test_approval_requires_specific_complete_uncontradicted_evidence(changes,expected):
    assert ih.recommendation(assessment(**changes),4,{"notes":[]})==expected
    assert ih.recommendation(assessment(),4,{"notes":["Focus problem"]})=="inconclusive"


@pytest.mark.parametrize("guest",[False,True])
def test_public_record_marked_photos_zip_and_withdrawal(setup,guest):
    client,clock,tmp,monkeypatch=setup
    r=create(client,access_headers={} if guest else ALICE).json();stage=complete(client,r,clock)
    owner_headers={"X-LockX-Manage-Key":r["manage_key"]} if guest else ALICE
    model_ready(monkeypatch,assessment())
    assert submit(client,r,stage,video(tmp,33)).status_code==202
    assert client.get(BASE+"/requests/"+r["id"],headers=owner_headers).json()["status"]=="confirmed"
    path=BASE+f"/requests/{r['id']}/publish"
    assert client.post(path,headers=BOB,json={"publish_selected_photos":True}).status_code==404
    assert client.post(path,headers=owner_headers,json={"publish_selected_photos":False}).status_code==422
    response=client.post(path,headers=owner_headers,json={"publish_selected_photos":True})
    assert response.status_code==201,response.text
    publication=response.json()["id"]
    assert client.post(path,headers=owner_headers,json={"publish_selected_photos":True}).json()["id"]==publication
    public=client.get(BASE+"/public/"+publication).json()
    assert public["photo_count"]==4 and public["status"]=="verified"
    assert public["captured"]==clock[0]
    assert not {"token","owner_id","description","details","analysis","session_id","media"}&public.keys()
    p=public["photos"][0]["id"]
    image_response=client.get(BASE+f"/public/{publication}/photos/{p}")
    assert image_response.status_code==200 and image_response.headers["cache-control"]=="no-store"
    marked=cv2.imdecode(np.frombuffer(image_response.content,np.uint8),cv2.IMREAD_COLOR)
    qr,_,_=cv2.QRCodeDetector().detectAndDecode(marked)
    assert qr=="https://lockx.ai/#in-hand/verify/"+publication
    original=r["media"][0]["id"]
    assert client.get(BASE+f"/public/{publication}/photos/{original}").status_code==404
    zipped=client.get(BASE+f"/requests/{r['id']}/marked-photos",headers=owner_headers)
    assert zipped.status_code==200
    assert len(zipfile.ZipFile(io.BytesIO(zipped.content)).namelist())==4
    assert client.delete(BASE+f"/requests/{r['id']}/publication",headers=BOB).status_code==404
    assert client.delete(BASE+f"/requests/{r['id']}/publication",headers=owner_headers).status_code==200
    assert client.get(BASE+"/public/"+publication).json()["status"]=="withdrawn"
    assert client.get(BASE+f"/public/{publication}/photos/{p}").status_code==404
    assert client.post(path,headers=owner_headers,json={"publish_selected_photos":True}).status_code==409


@pytest.mark.parametrize("mode,description,changes,expected",[
    ("digital","",{},"inconclusive"),
    ("handheld","Guaranteed genuine",{},"inconclusive"),
    ("handheld","",{"photos":[{"photo_index":0,"finding":"supported","evidence":"Missing other photos","frame_indices":[0]}]},"inconclusive"),
    ("handheld","",{"photos":[{"photo_index":i,"finding":"supported","evidence":"Invalid index","frame_indices":[999]} for i in range(4)]},"inconclusive"),
])
def test_full_analysis_cannot_confirm_digital_missing_claims_or_invalid_citations(setup,mode,description,changes,expected):
    client,clock,tmp,monkeypatch=setup
    r=create(client,capture_mode=mode,description=description).json();stage=complete(client,r,clock)
    model_ready(monkeypatch,assessment(**changes))
    assert submit(client,r,stage,video(tmp,33)).status_code==202
    assert client.get(BASE+"/requests/"+r["id"],headers=ALICE).json()["status"]==expected
