"""Real frame-ranking and conservative identifier comparison regressions."""

import json
import re
import cv2
import numpy as np
import pytest

import in_hand as ih
from test_in_hand import BASE, assessment, setup
from test_in_hand_recovery import video_start


def surface_photo(index):
    """Four different marked surfaces, with readable individual numbers."""
    image = np.full((480,640,3),225,dtype=np.uint8)
    cv2.rectangle(image,(50,40),(590,440),(40,60,50),5)
    rng = np.random.default_rng(300+index)
    for _ in range(90):
        x,y = (int(v) for v in rng.integers((80,80),(560,400)))
        cv2.circle(image,(x,y),int(rng.integers(2,8)),(int(rng.integers(30,170)),80,90),-1)
    cv2.rectangle(image,(75,175),(565,285),(245,245,245),-1)
    cv2.putText(image,f"SN 00{index}12345",(90,245),cv2.FONT_HERSHEY_SIMPLEX,1.25,(10,10,10),3,cv2.LINE_AA)
    cv2.putText(image,f"VIEW {index}",(195,360),cv2.FONT_HERSHEY_SIMPLEX,1.4,(20,20,20),3,cv2.LINE_AA)
    cv2.line(image,(90+index*100,80),(125+index*100,145),(5,5,5),5)
    return image


def encode(image):
    ok,jpeg = cv2.imencode(".jpg",image,[cv2.IMWRITE_JPEG_QUALITY,95])
    assert ok
    return jpeg.tobytes()


def evidence_fixture():
    references = [surface_photo(index) for index in range(4)]
    useful = [3,8,13,18]
    frames = []
    for index in range(20):
        surface = useful.index(index) if index in useful else min(index//5,3)
        picture = references[surface].copy()
        if index in {1,6,11,16}:
            # Sharp texture alone is not relevant evidence of a reference view.
            picture = np.random.default_rng(index).integers(0,256,picture.shape,dtype=np.uint8)
        elif index not in useful:
            picture = cv2.GaussianBlur(picture,(41,41),12)
        frames.append({"content":encode(picture),"seconds":index*.5,"label":f"Actual video frame {index}"})
    return [{"content":encode(image)} for image in references],frames,useful


def seed_pending(setup,capture_mode="handheld"):
    client,clock,_,_ = setup
    refs,frames,useful = evidence_fixture()
    payload = {"title":"Four numbered surfaces","capture_mode":capture_mode,"consent":True}
    response = client.post(BASE+"/requests",data={"payload":json.dumps(payload)},
                           files=[("photos",(f"reference-{index}.jpg",photo["content"],"image/jpeg")) for index,photo in enumerate(refs)])
    assert response.status_code == 201,response.text
    record = response.json()
    stage = video_start(client,record)
    clock[0] += 10.1
    with ih.database() as db:
        for frame in frames:
            ih.store_media(db,record["id"],"frame","image/jpeg",frame["content"],frame["seconds"],frame["label"])
        observations = [{"label":"Recording end","seconds":10.1,"recording_seconds":10,"recording_end":True,"partial_capture":False}]
        db.execute("UPDATE ih_sessions SET position=1,finished=?,observations=? WHERE id=?",(clock[0],json.dumps(observations),stage["session_id"]))
        checks = {"duration_seconds":10,"sampled_frames":20,"notes":[],"capture_mode":"continuous_scan"}
        db.execute("UPDATE ih_requests SET status='processing',submitted=?,analysis_status='pending',analysis=? WHERE id=?",
                   (clock[0],json.dumps({"video":checks,"result":"inconclusive"}),record["id"]))
    return record,refs,frames,useful


def enable_model(monkeypatch,callback):
    monkeypatch.setenv("OPENAI_API_KEY","test-placeholder")
    monkeypatch.setenv("LOCKX_IN_HAND_VISION_MODEL","test-model")
    monkeypatch.setattr(ih,"vision_call",callback)


def private_detail(client,record):
    return client.get(BASE+"/requests/"+record["id"],headers={"X-LockX-Manage-Key":record["manage_key"]}).json()


def identifier(**changes):
    return {"photo_index":0,"label":"Serial number","reference_text":"0012345","video_text":"0012345",
            "readability":"both_readable","finding":"supported","evidence":"The serial numbers are legible in both views.",
            "frame_indices":[3],**changes}


def selected_labels(content):
    return [int(match.group(1)) for item in content if item.get("type")=="input_text"
            for match in [re.search(r"video_frame index (\d+)",item.get("text",""))] if match]


def test_frame_selection_keeps_the_sharp_relevant_view_for_all_four_photos():
    refs,frames,useful = evidence_fixture()
    selected,metadata = ih.select_evidence_frames(refs,frames)
    assert 4 <= len(selected) <= 12 < len(frames)
    assert selected == sorted(set(selected))
    assert set(useful) <= set(selected)
    assert metadata["total_frames"] == 20 and metadata["selected_frames"] == len(selected)
    assert metadata["selected_frame_indices"] == selected
    per_photo = {item["photo_index"]:item for item in metadata["reference_best_frames"]}
    assert set(per_photo) == {0,1,2,3}
    for index,good_frame in enumerate(useful):
        assert good_frame in per_photo[index]["frame_indices"]
        assert per_photo[index]["feature_matches"] > 0


def test_selection_is_only_preparation_and_never_calls_a_verifier(monkeypatch):
    refs,frames,_ = evidence_fixture()
    def unexpected(*args,**kwargs):
        pytest.fail("Feature ranking cannot issue a visual verification verdict")
    monkeypatch.setattr(ih,"vision_call",unexpected)
    selected,metadata = ih.select_evidence_frames(refs,frames)
    assert selected and "confirmed" not in metadata and "result" not in metadata


def test_strong_feature_matches_cannot_override_an_inconclusive_visual_assessment(setup):
    client,_,_,monkeypatch = setup
    record,_,_,_ = seed_pending(setup)
    def compare(schema,instructions,content,**kwargs):
        indices = selected_labels(content)
        return assessment(same_item="inconclusive",distinguishing_details=["Same model only"],
                          photos=[{"photo_index":i,"finding":"not_established","evidence":"Individual marks are not established.",
                                   "frame_indices":[indices[-1]]} for i in range(4)])
    enable_model(monkeypatch,compare)
    ih.analyze(record["id"])
    final = private_detail(client,record)
    assert final["status"] == "inconclusive" and final["analysis_status"] == "complete"
    assert client.post(BASE+f"/requests/{record['id']}/publish",headers={"X-LockX-Manage-Key":record["manage_key"]},
                       json={"publish_selected_photos":True}).status_code == 409


def test_all_references_reach_comparison_with_original_selected_citation_indices(setup):
    client,_,_,monkeypatch = setup
    record,_,_,_ = seed_pending(setup)
    observed = {}
    def compare(schema,instructions,content,**kwargs):
        observed["indices"] = selected_labels(content)
        references = [item["text"] for item in content if item.get("type")=="input_text" and item.get("text","").startswith("reference index ")]
        assert len(references) == 4
        assert len(observed["indices"]) <= 12
        assert max(observed["indices"]) >= 18
        assert set(observed["indices"]) != set(range(len(observed["indices"])))
        photos = [{"photo_index":index,"finding":"supported","evidence":"Corresponding distinct marks are visible.",
                   "frame_indices":[observed["indices"][-1]]} for index in range(4)]
        return assessment(photos=photos)
    enable_model(monkeypatch,compare)
    ih.analyze(record["id"])
    final = private_detail(client,record)
    assert final["status"] == "confirmed"
    assert final["analysis"]["video"]["frame_selection"]["selected_frame_indices"] == observed["indices"]
    assert final["analysis"]["visual"]["photos"][0]["frame_indices"] == [observed["indices"][-1]]


@pytest.mark.parametrize("reference_text,video_text", [
    ("SN123456","SN123457"),("0012345","12345"),("ABO123","AB0123"),
])
def test_legible_identifier_characters_override_a_claimed_visual_match(reference_text,video_text):
    visual = assessment(identifier_checks=[identifier(reference_text=reference_text,video_text=video_text)])
    assert ih.recommendation(visual,4,{"notes":[]}) == "mismatch"


@pytest.mark.parametrize("changes", [
    {"readability":"unclear","video_text":"00?2345"},
    {"reference_text":""},{"video_text":""},{"frame_indices":[]},
])
def test_unclear_identifier_never_approves_even_if_model_labels_it_supported(changes):
    visual = assessment(identifier_checks=[identifier(**changes)])
    assert ih.recommendation(visual,4,{"notes":[]}) == "inconclusive"


def test_exact_legible_identifier_is_compatible_with_existing_photo_requirements():
    visual = assessment(identifier_checks=[identifier()])
    assert ih.recommendation(visual,4,{"notes":[]}) == "confirmed"
    assert ih.recommendation(assessment(photos=[],identifier_checks=[identifier()]),4,{"notes":[]}) == "inconclusive"
    assert assessment().identifier_checks == []


def test_optional_identifier_default_remains_compatible_with_strict_model_api_schema():
    schema = ih.strict_vision_schema(ih.VisualAssessment)
    assert "identifier_checks" in schema["required"]
    assert "identifier_checks" not in ih.VisualAssessment.model_json_schema()["required"]
    assert schema["$defs"]["IdentifierCheck"]["additionalProperties"] is False
    assert set(schema["$defs"]["IdentifierCheck"]["required"]) == {
        "photo_index","label","reference_text","video_text","readability","finding","evidence","frame_indices"}


@pytest.mark.parametrize("case", ["photo", "identifier", "identifier_photo_index"])
def test_analyze_rejects_citations_to_frames_not_sent_to_the_model(setup,case):
    client,_,_,monkeypatch = setup
    record,_,_,_ = seed_pending(setup)
    def compare(schema,instructions,content,**kwargs):
        transmitted = selected_labels(content)
        omitted = next(index for index in range(20) if index not in transmitted)
        good = transmitted[-1]
        photos = [{"photo_index":index,"finding":"supported","evidence":"Visible details correspond.",
                   "frame_indices":[omitted if case=="photo" and index==0 else good]} for index in range(4)]
        checks = [identifier(frame_indices=[omitted if case=="identifier" else good],
                             photo_index=10 if case=="identifier_photo_index" else 0)]
        return assessment(photos=photos,identifier_checks=checks)
    enable_model(monkeypatch,compare)
    ih.analyze(record["id"])
    final = private_detail(client,record)
    assert final["status"] == "inconclusive" and final["analysis_status"] == "failed"


def test_phone_identifier_results_never_grant_management_access(setup):
    client,_,_,monkeypatch = setup
    record,_,_,_ = seed_pending(setup)
    def compare(schema,instructions,content,**kwargs):
        indices = selected_labels(content)
        return assessment(photos=[{"photo_index":i,"finding":"supported","evidence":"Same distinct marks.","frame_indices":[indices[-1]]} for i in range(4)],
                          identifier_checks=[identifier(frame_indices=[indices[-1]])])
    enable_model(monkeypatch,compare)
    ih.analyze(record["id"])
    response = client.get(BASE+f"/seller/{record['token']}/result")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "confirmed"
    assert not {"token","owner_id","manage_key","events","media","session_id","publication"}&body.keys()
    assert record["manage_key"] not in response.text and record["token"] not in response.text
    assert client.get(BASE+"/requests/"+record["id"]).status_code == 401
    assert client.get(BASE+"/requests/"+record["id"],headers={"X-LockX-Manage-Key":record["token"]}).status_code == 404
    assert client.post(BASE+f"/requests/{record['id']}/publish",headers={"X-LockX-Manage-Key":record["token"]},
                       json={"publish_selected_photos":True}).status_code == 404


@pytest.mark.parametrize("changes,expected_status,expected_finding", [
    ({"video_text":"0012346"},"mismatch","contradicted"),
    ({"readability":"unclear","video_text":"001?345"},"inconclusive","not_established"),
])
def test_phone_identifier_finding_agrees_with_deterministic_number_comparison(setup,changes,expected_status,expected_finding):
    client,_,_,monkeypatch = setup
    record,_,_,_ = seed_pending(setup)
    def compare(schema,instructions,content,**kwargs):
        indices = selected_labels(content)
        return assessment(photos=[{"photo_index":i,"finding":"supported","evidence":"Same visible marks.","frame_indices":[indices[-1]]} for i in range(4)],
                          identifier_checks=[identifier(frame_indices=[indices[-1]],**changes)])
    enable_model(monkeypatch,compare)
    ih.analyze(record["id"])
    phone = client.get(BASE+f"/seller/{record['token']}/result").json()
    assert phone["status"] == expected_status
    assert phone["identifier_checks"][0]["finding"] == expected_finding
    assert phone["photos"][0]["finding"] == expected_finding


def test_digital_results_do_not_echo_usable_ticket_identifiers(setup):
    client,_,_,monkeypatch = setup
    record,_,_,_ = seed_pending(setup,capture_mode="digital")
    barcode = "00981234567890456789"
    def compare(schema,instructions,content,**kwargs):
        indices = selected_labels(content)
        return assessment(photos=[{"photo_index":i,"finding":"supported","evidence":"Visible screen details correspond.","frame_indices":[indices[-1]]} for i in range(4)],
                          identifier_checks=[identifier(label="Ticket barcode",reference_text=barcode,video_text=barcode,
                                                        evidence="Both barcode numbers are visible.",frame_indices=[indices[-1]])])
    enable_model(monkeypatch,compare)
    ih.analyze(record["id"])
    final = private_detail(client,record)
    assert final["status"] == "inconclusive"
    response = client.get(BASE+f"/seller/{record['token']}/result")
    assert response.status_code == 200 and barcode not in response.text
    assert record["manage_key"] not in response.text


def test_actual_provider_payload_constrains_original_citations_and_four_photo_findings(setup):
    client,_,_,monkeypatch = setup
    record,_,_,_ = seed_pending(setup)
    captured = {}
    def fake_post(url,**kwargs):
        assert url == "https://api.openai.com/v1/responses"
        payload = kwargs["json"]
        captured["schema"] = payload["text"]["format"]["schema"]
        captured["strict"] = payload["text"]["format"]["strict"]
        selected = selected_labels(payload["input"][0]["content"])
        captured["indices"] = selected
        photos = [{"photo_index":index,"finding":"supported","evidence":"Corresponding distinctive marks.",
                   "frame_indices":[selected[-1]]} for index in range(4)]
        visual = assessment(photos=photos,identifier_checks=[identifier(frame_indices=[selected[-1]])])
        class Response:
            def raise_for_status(self):
                pass
            def json(self):
                return {"output":[{"content":[{"type":"output_text","text":visual.model_dump_json()}]}]}
        return Response()
    monkeypatch.setenv("OPENAI_API_KEY","test-placeholder")
    monkeypatch.setenv("LOCKX_IN_HAND_VISION_MODEL","test-model")
    monkeypatch.setattr(ih.httpx,"post",fake_post)
    ih.analyze(record["id"])
    final = private_detail(client,record)
    assert final["status"] == "confirmed", final["analysis"]
    schema,selected = captured["schema"],captured["indices"]
    assert captured["strict"] is True
    assert len(selected) <= 12 and max(selected) >= 18
    assert set(selected) != set(range(len(selected)))
    assert schema["properties"]["photos"]["minItems"] == 4
    assert schema["properties"]["photos"]["maxItems"] == 4
    for name in ("PhotoFinding","Finding","IdentifierCheck"):
        properties = schema["$defs"][name]["properties"]
        assert properties["frame_indices"]["items"]["enum"] == selected
    for name in ("PhotoFinding","IdentifierCheck"):
        assert schema["$defs"][name]["properties"]["photo_index"]["enum"] == [0,1,2,3]
    def verify_required(node):
        if isinstance(node,dict):
            if node.get("type") == "object" and "properties" in node:
                assert set(node["required"]) == set(node["properties"])
                assert node["additionalProperties"] is False
            assert "default" not in node
            for value in node.values():
                verify_required(value)
        elif isinstance(node,list):
            for value in node:
                verify_required(value)
    verify_required(schema)
    assert final["analysis"]["visual"]["photos"][0]["frame_indices"] == [selected[-1]]
