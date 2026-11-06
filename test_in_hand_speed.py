"""Faster delivery and rendering must preserve evidence and capability boundaries."""

import asyncio
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

import in_hand as ih
from test_in_hand import BASE, assessment, create, setup
from test_in_hand_auto_publish import decode_marking, owner_headers, phone_result
from test_in_hand_identifiers import (
    enable_model, evidence_fixture, private_detail, seed_pending, selected_labels,
)


def completed_record(setup, *, partial=False, auto_publish=True):
    """Retain a real finished session and evidence; only the model is a fixture."""
    client, _, _, _ = setup
    record, _, _, _ = seed_pending(setup)
    visual = assessment()
    if partial:
        visual.same_item = "contradicted"
        visual.photos[1].finding = "contradicted"
        visual.photos[1].evidence = "The individual mark differs on this reference."
    with ih.database() as db:
        row = db.execute("SELECT listing FROM ih_requests WHERE id=?", (record["id"],)).fetchone()
        listing = json.loads(row["listing"])
        listing.update(auto_publish=auto_publish, publish_matched_photos=True)
        checks = {"duration_seconds":10, "sampled_frames":20, "notes":[],
                  "capture_mode":"continuous_scan"}
        result = "mismatch" if partial else "confirmed"
        analysis = {"video":checks, "visual":visual.model_dump(),
                    "result":result, "summary":"Generated comparison fixture."}
        db.execute("UPDATE ih_requests SET listing=?,status=?,analysis_status='complete',analysis=? WHERE id=?",
                   (json.dumps(listing),result,json.dumps(analysis),record["id"]))
    return record


def manual_publish(client, record):
    return client.post(BASE+f"/requests/{record['id']}/publish", headers=owner_headers(record),
                       json={"publish_selected_photos":True})


def database_snapshot():
    with ih.database() as db:
        return {table:[tuple(row) for row in db.execute("SELECT * FROM "+table+" ORDER BY rowid")]
                for table in ("ih_requests", "ih_media", "ih_events", "ih_publications",
                              "ih_publication_jobs", "ih_scan_previews")}


def parse_events(content):
    events=[]
    for block in content.split("\n\n"):
        fields={}
        for line in block.splitlines():
            if ":" in line and not line.startswith(":"):
                name,value=line.split(":",1)
                fields[name]=value.strip()
        if fields.get("event") == "status":
            events.append(json.loads(fields["data"]))
    return events


class StreamRequest:
    async def is_disconnected(self):
        return False


def collect_stream(token):
    async def consume():
        chunks=[]
        async for chunk in ih.iter_seller_result_events(token, StreamRequest()):
            chunks.append(chunk.decode() if isinstance(chunk,bytes) else chunk)
        return "".join(chunks)
    return asyncio.run(consume())


def test_completed_event_stream_is_private_compact_and_read_only(setup, monkeypatch):
    client, _, _, _ = setup
    record=completed_record(setup, partial=True)
    response=manual_publish(client,record)
    assert response.status_code == 201,response.text
    before=database_snapshot()
    def forbidden(*args,**kwargs):
        pytest.fail("An event stream must never launch analysis, publish or clean capture data")
    for name in ("analyze", "schedule_publication", "auto_publish_confirmed", "cleanup_scan_media"):
        monkeypatch.setattr(ih,name,forbidden)
    response=client.get(BASE+f"/seller/{record['token']}/events")
    assert response.status_code == 200,response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "no-store" in response.headers["cache-control"]
    assert response.headers.get("x-accel-buffering") == "no"
    events=parse_events(response.text)
    assert len(events)==1
    event=events[0]
    assert set(event)=={"status","analysis_status","publication_status","revision"}
    assert event["status"]=="mismatch" and event["analysis_status"]=="complete"
    assert event["publication_status"]=="ready"
    assert isinstance(event["revision"],str) and len(event["revision"])==64
    for secret in (record["token"],record["manage_key"],record["id"]):
        assert secret not in response.text
    assert database_snapshot()==before


def test_result_events_reject_bad_and_expired_capture_capabilities(setup):
    client,clock,_,_=setup
    record=create(client,access_headers={}).json()
    for token in ("not-a-capture-token",record["manage_key"],record["id"]):
        response=client.get(BASE+f"/seller/{token}/events")
        assert response.status_code == 404,response.text
        assert not response.headers.get("content-type","").startswith("text/event-stream")
    clock[0]+=8*86400
    response=client.get(BASE+f"/seller/{record['token']}/events")
    assert response.status_code == 410,response.text


def test_result_events_deliver_completion_without_a_poll_or_background_job(setup, monkeypatch):
    client,_,_,_=setup
    record=create(client,access_headers={},auto_publish=True).json()
    before=database_snapshot()
    tick=[0.0]
    sleeps=[]
    monkeypatch.setattr(ih,"perf_counter",lambda:tick[0])
    async def sleep(seconds):
        sleeps.append(seconds)
        tick[0]+=seconds
        with ih.database() as db:
            if len(sleeps)==1:
                db.execute("UPDATE ih_requests SET status='processing',analysis_status='processing' WHERE id=?",(record["id"],))
            else:
                db.execute("UPDATE ih_requests SET status='inconclusive',analysis_status='complete',analysis=? WHERE id=?",
                           (json.dumps({"result":"inconclusive","summary":"No individual marks established."}),record["id"]))
    monkeypatch.setattr(ih.asyncio,"sleep",sleep)
    content=collect_stream(record["token"])
    events=parse_events(content)
    assert [event["status"] for event in events]==["waiting","processing","inconclusive"]
    assert len({event["revision"] for event in events})==3
    assert events[-1]["publication_status"]=="unavailable"
    after=database_snapshot()
    assert after["ih_publication_jobs"]==before["ih_publication_jobs"]==[]
    assert after["ih_publications"]==before["ih_publications"]==[]
    for name in ("ih_media","ih_events","ih_scan_previews"):
        assert after[name]==before[name]


def test_waiting_stream_has_a_bounded_lifetime_and_never_approves_at_two_seconds(setup, monkeypatch):
    client,_,_,_=setup
    record=create(client,access_headers={},auto_publish=True).json()
    before=database_snapshot()
    tick=[0.0]
    monkeypatch.setattr(ih,"perf_counter",lambda:tick[0])
    monkeypatch.setattr(ih,"RESULT_STREAM_MAX_SECONDS",3.0)
    monkeypatch.setattr(ih,"RESULT_STREAM_POLL_SECONDS",.25)
    async def sleep(seconds):
        tick[0]+=seconds
    monkeypatch.setattr(ih.asyncio,"sleep",sleep)
    events=parse_events(collect_stream(record["token"]))
    assert tick[0]>=3 and tick[0]<3.5
    assert len(events)==1 and events[0]["status"]=="waiting"
    assert events[0]["publication_status"]=="pending"
    assert database_snapshot()==before


def test_disconnected_stream_closes_without_waiting_or_starting_work(setup, monkeypatch):
    client,_,_,_=setup
    record=create(client,access_headers={},auto_publish=True).json()
    before=database_snapshot()
    class Disconnected:
        async def is_disconnected(self):
            return True
    async def forbidden_sleep(*args):
        pytest.fail("A disconnected stream must release its worker immediately")
    monkeypatch.setattr(ih.asyncio,"sleep",forbidden_sleep)
    async def consume():
        return [chunk async for chunk in ih.iter_seller_result_events(record["token"],Disconnected())]
    chunks=asyncio.run(consume())
    # Sending the immediate snapshot before checking disconnection is harmless;
    # continuing to wait after a disconnected client is not.
    assert len(chunks)<=1
    assert database_snapshot()==before


def test_withdrawal_is_reported_without_restarting_publication(setup,monkeypatch):
    client,_,_,_=setup
    record=completed_record(setup,partial=True)
    response=manual_publish(client,record)
    assert response.status_code==201,response.text
    publication_id=response.json()["id"]
    response=client.delete(BASE+f"/requests/{record['id']}/publication",headers=owner_headers(record))
    assert response.status_code==200,response.text
    before=database_snapshot()
    events=parse_events(collect_stream(record["token"]))
    assert len(events)==1 and events[0]["publication_status"]=="withdrawn"
    assert publication_id not in json.dumps(events)
    assert database_snapshot()==before


def test_parallel_qr_rendering_releases_writer_and_publishes_only_approved_indices(setup,monkeypatch):
    client,_,tmp,_=setup
    record=completed_record(setup,partial=True)
    original=ih.marked_photo
    verified_threads=set()
    lock=threading.Lock()
    def renderer(content,publication_id,captured):
        # An independent writer must be able to proceed while image processing
        # runs. A held BEGIN IMMEDIATE here recreates the old bottleneck.
        with sqlite3.connect(tmp/"in-hand.sqlite3",timeout=.2) as db:
            db.execute("BEGIN IMMEDIATE")
            assert db.execute("SELECT status FROM ih_requests WHERE id=?",(record["id"],)).fetchone()[0]=="mismatch"
        with lock:
            verified_threads.add(threading.get_ident())
        return original(content,publication_id,captured)
    monkeypatch.setattr(ih,"marked_photo",renderer)
    response=manual_publish(client,record)
    assert response.status_code==201,response.text
    result=phone_result(client,record)
    publication=result["publication"]
    assert [photo["photo_index"] for photo in publication["photos"]]==[0,2,3]
    assert 1<=len(verified_threads)<=3
    for photo in publication["photos"]:
        content=client.get(BASE+f"/public/{publication['id']}/photos/{photo['id']}").content
        assert decode_marking(content)=="https://lockx.ai/#in-hand/verify/"+publication["id"]


def test_cohort_change_during_qr_render_cannot_commit_stale_verified_images(setup,monkeypatch):
    client,_,tmp,_=setup
    record=completed_record(setup,partial=True,auto_publish=False)
    original=ih.marked_photo
    changed=threading.Event()
    lock=threading.Lock()
    def renderer(content,publication_id,captured):
        with lock:
            if not changed.is_set():
                with sqlite3.connect(tmp/"in-hand.sqlite3",timeout=.2) as db:
                    raw=db.execute("SELECT analysis FROM ih_requests WHERE id=?",(record["id"],)).fetchone()[0]
                    analysis=json.loads(raw)
                    analysis["visual"]["photos"][2]["finding"]="not_established"
                    db.execute("UPDATE ih_requests SET analysis=? WHERE id=?",(json.dumps(analysis),record["id"]))
                changed.set()
        return original(content,publication_id,captured)
    monkeypatch.setattr(ih,"marked_photo",renderer)
    response=manual_publish(client,record)
    assert response.status_code==409,response.text
    assert changed.is_set()
    with ih.database() as db:
        assert db.execute("SELECT COUNT(*) FROM ih_publications WHERE request_id=?",(record["id"],)).fetchone()[0]==0
        assert db.execute("SELECT COUNT(*) FROM ih_media WHERE request_id=? AND role='marked'",(record["id"],)).fetchone()[0]==0
        assert db.execute("SELECT COUNT(*) FROM ih_publication_photos").fetchone()[0]==0


def test_concurrent_withdrawn_record_cannot_be_replaced_after_rendering(setup,monkeypatch):
    client,clock,tmp,_=setup
    record=completed_record(setup,auto_publish=False)
    original=ih.marked_photo
    changed=threading.Event()
    lock=threading.Lock()
    withdrawn_id="concurrentlywithdrawn"
    def renderer(content,publication_id,captured):
        with lock:
            if not changed.is_set():
                with sqlite3.connect(tmp/"in-hand.sqlite3",timeout=.2) as db:
                    db.execute("INSERT INTO ih_publications VALUES (?,?,?,?)",
                               (withdrawn_id,record["id"],clock[0],clock[0]))
                changed.set()
        return original(content,publication_id,captured)
    monkeypatch.setattr(ih,"marked_photo",renderer)
    response=manual_publish(client,record)
    assert response.status_code==409,response.text
    with ih.database() as db:
        pubs=db.execute("SELECT id,revoked FROM ih_publications WHERE request_id=?",(record["id"],)).fetchall()
        assert [dict(pub) for pub in pubs]==[{"id":withdrawn_id,"revoked":clock[0]}]
        assert db.execute("SELECT COUNT(*) FROM ih_media WHERE request_id=? AND role='marked'",(record["id"],)).fetchone()[0]==0
    assert client.get(BASE+"/public/"+withdrawn_id).json()["status"]=="withdrawn"


def test_slower_model_completion_preserves_checks_instead_of_forcing_a_two_second_verdict(setup,monkeypatch):
    client,_,_,_=setup
    record,_,_,_=seed_pending(setup)
    tick=[100.0]
    monkeypatch.setattr(ih,"perf_counter",lambda:tick[0])
    compared=[]
    def compare(schema,instructions,content,**kwargs):
        compared.append(schema)
        assert len([entry for entry in content if entry.get("type")=="input_text" and entry.get("text","").startswith("reference index ")])==4
        indices=selected_labels(content)
        assert len(indices)<=12 and max(indices)>=18
        # Simulates a model taking longer than the delivery target. There must
        # be no auto-approval, skipped photo or lower-quality deadline branch.
        with ih.database() as db:
            row=db.execute("SELECT * FROM ih_requests WHERE id=?",(record["id"],)).fetchone()
            assert row["analysis_status"]=="processing"
            assert ih.photo_eligibility(db,row)["verified_count"]==0
            assert db.execute("SELECT COUNT(*) FROM ih_publications WHERE request_id=?",(record["id"],)).fetchone()[0]==0
        tick[0]+=3.1
        return assessment(photos=[{"photo_index":i,"finding":"supported","evidence":"Distinct individual marks correspond.","frame_indices":[indices[-1]]} for i in range(4)])
    enable_model(monkeypatch,compare)
    ih.analyze(record["id"])
    final=private_detail(client,record)
    assert compared==[ih.VisualAssessment]
    assert final["analysis_status"]=="complete" and final["status"]=="confirmed"
    assert len(final["analysis"]["visual"]["photos"])==4
    assert final["analysis"]["video"]["vision_ms"]>=3100


def test_concurrent_publishers_commit_one_immutable_photo_set(setup,monkeypatch):
    client,_,_,_=setup
    record=completed_record(setup,auto_publish=False)
    original=ih.marked_photo
    first_render=threading.Barrier(2,timeout=15)
    seen=set()
    lock=threading.Lock()
    def renderer(content,publication_id,captured):
        with lock:
            first=publication_id not in seen
            seen.add(publication_id)
        if first:
            first_render.wait()
        return original(content,publication_id,captured)
    monkeypatch.setattr(ih,"marked_photo",renderer)
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures=[workers.submit(manual_publish,client,record) for _ in range(2)]
        responses=[future.result(timeout=30) for future in futures]
    assert all(response.status_code==201 for response in responses),[response.text for response in responses]
    assert len(seen)==2,"Both requests rendered before either could publish"
    assert responses[0].json()["id"]==responses[1].json()["id"]
    publication_id=responses[0].json()["id"]
    with ih.database() as db:
        assert db.execute("SELECT COUNT(*) FROM ih_publications WHERE request_id=?",(record["id"],)).fetchone()[0]==1
        assert db.execute("SELECT COUNT(*) FROM ih_media WHERE request_id=? AND role='marked'",(record["id"],)).fetchone()[0]==4
        mapped=db.execute("SELECT photo_index FROM ih_publication_photos WHERE publication_id=? ORDER BY photo_index",(publication_id,)).fetchall()
        assert [row[0] for row in mapped]==[0,1,2,3]


def test_reference_feature_cache_keeps_original_frame_selection_and_citations(monkeypatch):
    refs,frames,useful=evidence_fixture()
    refs=[{**reference,"request_id":"cache-equivalence","id":f"reference-{i}"}
          for i,reference in enumerate(refs)]
    with ih._reference_lock:
        ih._reference_cache.clear()
    original=ih.media_features
    computed=[]
    def features(media):
        if media.get("request_id")=="cache-equivalence":
            computed.append(media["id"])
        return original(media)
    monkeypatch.setattr(ih,"media_features",features)
    import cv2
    cv2.setRNGSeed(343)
    first,first_metadata=ih.select_evidence_frames(refs,frames)
    assert sorted(computed)==[f"reference-{i}" for i in range(4)]
    cv2.setRNGSeed(343)
    second,second_metadata=ih.select_evidence_frames(refs,frames)
    assert computed==list(dict.fromkeys(computed)),"Cached references must not be decoded a second time"
    assert first==second and set(useful)<=set(second)
    for key in ("selected_frame_indices","reference_best_frames","method","total_frames","selected_frames"):
        assert first_metadata[key]==second_metadata[key]
    assert "result" not in second_metadata and "confirmed" not in second_metadata


def test_reference_feature_cache_uses_actual_content_and_separates_private_requests(monkeypatch):
    refs,_,_=evidence_fixture()
    with ih._reference_lock:
        ih._reference_cache.clear()
    original=ih.media_features
    computed=[]
    def features(media):
        computed.append((media["request_id"],media["id"],media["content"]))
        return original(media)
    monkeypatch.setattr(ih,"media_features",features)
    media={**refs[0],"request_id":"private-request-A","id":"same-id","sha256":"untrusted-claimed-hash"}
    ih.reference_features(media)
    ih.reference_features(media)
    changed={**media,"content":refs[1]["content"]}
    ih.reference_features(changed)
    ih.reference_features(changed)
    other_request={**changed,"request_id":"private-request-B"}
    ih.reference_features(other_request)
    ih.reference_features(other_request)
    assert len(computed)==3
    assert computed[0][2]!=computed[1][2]
    assert computed[1][0]!=computed[2][0]


def test_private_export_preparation_overlaps_ai_without_releasing_unapproved_photos(setup,monkeypatch):
    client,_,_,_=setup
    record,_,_,_=seed_pending(setup)
    with ih.database() as db:
        listing=json.loads(db.execute("SELECT listing FROM ih_requests WHERE id=?",(record["id"],)).fetchone()[0])
        listing.update(auto_publish=True,publish_matched_photos=True)
        db.execute("UPDATE ih_requests SET listing=? WHERE id=?",(json.dumps(listing),record["id"]))
    original=ih.marked_photo
    started=threading.Event()
    release=threading.Event()
    renders=[]
    lock=threading.Lock()
    def renderer(content,publication_id,captured):
        with lock:
            renders.append(publication_id)
        started.set()
        assert release.wait(timeout=10),"Private preparation was never released by the fixture"
        return original(content,publication_id,captured)
    monkeypatch.setattr(ih,"marked_photo",renderer)
    compared=[]
    def compare(schema,instructions,content,**kwargs):
        compared.append(schema)
        try:
            assert started.wait(timeout=5),"QR preparation should run concurrently with visual comparison"
            with ih.database() as db:
                row=db.execute("SELECT * FROM ih_requests WHERE id=?",(record["id"],)).fetchone()
                assert row["analysis_status"]=="processing"
                assert ih.photo_eligibility(db,row)["verified_count"]==0
                assert db.execute("SELECT COUNT(*) FROM ih_publications WHERE request_id=?",(record["id"],)).fetchone()[0]==0
                assert db.execute("SELECT COUNT(*) FROM ih_media WHERE request_id=? AND role='marked'",(record["id"],)).fetchone()[0]==0
                assert db.execute("SELECT COUNT(*) FROM ih_publication_jobs WHERE request_id=?",(record["id"],)).fetchone()[0]==0
            with lock:
                reserved=list(set(renders))
            assert len(reserved)==1
            assert client.get(BASE+"/public/"+reserved[0]).status_code==404
            pending=phone_result(client,record)
            assert pending["verified_count"]==0 and not pending.get("publication")
            indices=selected_labels(content)
            visual=assessment(same_item="contradicted",photos=[
                {"photo_index":i,"finding":"contradicted" if i==1 else "supported",
                 "evidence":"Different individual mark." if i==1 else "Individual marks correspond.",
                 "frame_indices":[indices[-1]]} for i in range(4)])
            return visual
        finally:
            release.set()
    enable_model(monkeypatch,compare)
    ih.analyze(record["id"])
    result=phone_result(client,record)
    assert compared==[ih.VisualAssessment]
    assert result["status"]=="mismatch" and result["publication_status"]=="ready"
    publication=result["publication"]
    assert [photo["photo_index"] for photo in publication["photos"]]==[0,2,3]
    assert len(renders)==4 and set(renders)=={publication["id"]},"Approved prepared JPEGs should be reused"
    for photo in publication["photos"]:
        response=client.get(BASE+f"/public/{publication['id']}/photos/{photo['id']}")
        assert response.status_code==200
        assert decode_marking(response.content)=="https://lockx.ai/#in-hand/verify/"+publication["id"]


def test_result_events_signal_publication_readiness_even_when_aggregate_result_is_unchanged(setup,monkeypatch):
    _,_,_,_=setup
    record=completed_record(setup,partial=True)
    tick=[0.0]
    monkeypatch.setattr(ih,"perf_counter",lambda:tick[0])
    calls=[]
    async def sleep(seconds):
        tick[0]+=seconds
        calls.append(seconds)
        with ih.database() as db:
            row=db.execute("SELECT * FROM ih_requests WHERE id=?",(record["id"],)).fetchone()
            ih.publish_confirmed_photos(db,row)
    monkeypatch.setattr(ih.asyncio,"sleep",sleep)
    events=parse_events(collect_stream(record["token"]))
    assert [event["status"] for event in events]==["mismatch","mismatch"]
    assert [event["publication_status"] for event in events]==["pending","ready"]
    assert events[0]["revision"]!=events[1]["revision"]
    assert len(calls)==1


def test_expiring_capture_link_closes_stream_and_releases_admission(setup,monkeypatch):
    client,clock,_,_=setup
    record=create(client,access_headers={},auto_publish=True).json()
    tick=[0.0]
    monkeypatch.setattr(ih,"perf_counter",lambda:tick[0])
    async def sleep(seconds):
        tick[0]+=seconds
        clock[0]+=2*86400
    monkeypatch.setattr(ih.asyncio,"sleep",sleep)
    ih.admit_result_stream(record["id"])
    async def consume():
        return "".join([chunk async for chunk in ih.iter_seller_result_events(record["token"],StreamRequest(),admission=record["id"])])
    content=asyncio.run(consume())
    assert len(parse_events(content))==1
    assert 'event: unavailable\ndata: {"status":"unavailable"}' in content
    with ih._stream_lock:
        assert record["id"] not in ih._active_streams
    with ih.database() as db:
        assert db.execute("SELECT COUNT(*) FROM ih_publication_jobs").fetchone()[0]==0


def test_result_stream_limits_are_bounded_per_capture_and_globally():
    with ih._stream_lock:
        saved=dict(ih._active_streams)
        ih._active_streams.clear()
    try:
        for _ in range(ih.RESULT_STREAM_MAX_PER_REQUEST):
            ih.admit_result_stream("same-capture")
        with pytest.raises(ih.HTTPException) as limited:
            ih.admit_result_stream("same-capture")
        assert limited.value.status_code==429 and limited.value.headers["Retry-After"]=="5"
        for _ in range(ih.RESULT_STREAM_MAX_PER_REQUEST):
            ih.release_result_stream("same-capture")
        for index in range(ih.RESULT_STREAM_MAX_ACTIVE):
            ih.admit_result_stream(f"capture-{index}")
        with pytest.raises(ih.HTTPException) as limited:
            ih.admit_result_stream("overflow-capture")
        assert limited.value.status_code==429
        for index in range(ih.RESULT_STREAM_MAX_ACTIVE):
            ih.release_result_stream(f"capture-{index}")
        with ih._stream_lock:
            assert not ih._active_streams
    finally:
        with ih._stream_lock:
            ih._active_streams.clear()
            ih._active_streams.update(saved)
