"""Optional recording city/state stays session-bound, coarse and immutable."""

import json
import sqlite3
import threading

import pytest
from PIL import ImageDraw

import in_hand as ih
from test_in_hand import BASE, assessment, create, jpeg, setup
from test_in_hand_auto_publish import decode_marking, owner_headers, phone_result
from test_in_hand_recovery import video_start
from test_in_hand_speed import manual_publish

CITY = {"city": "San Francisco", "state": "CA", "country_code": "US", "source": "device_reported"}
COORDS = {"latitude": 37.77492951, "longitude": -122.41941551, "accuracy": 17.25}


def fresh_capture(setup, **listing):
    client, _, _, _ = setup
    response = create(client, access_headers={}, auto_publish=True, publish_matched_photos=True, **listing)
    assert response.status_code == 201, response.text
    record = response.json()
    stage = video_start(client, record)
    return record, stage


def location(client, record, stage, clock, **changes):
    payload = {"session_id": stage["session_id"], **COORDS, "timestamp": clock[0] * 1000, **changes}
    # Explicit JSON also exercises NaN/Infinity rejection rather than a client
    # encoder refusing the invalid number before the application sees it.
    return client.post(BASE + f"/seller/{record['token']}/location", content=json.dumps(payload),
                       headers={"content-type": "application/json"})


def finish_fixture(record, stage, clock, *, partial=False):
    """A complete evidence/session fixture; there is no simulated GPS in AI."""
    visual = assessment()
    if partial:
        visual.same_item = "contradicted"
        visual.photos[1].finding = "contradicted"
        visual.photos[1].evidence = "This reference has a different individual mark."
    clock[0] += 10.1
    with ih.database() as db:
        for i in range(4):
            ih.store_media(db, record["id"], "frame", "image/jpeg", jpeg(i), i * 2.5, f"Video view {i}")
        db.execute("UPDATE ih_sessions SET position=1,finished=?,observations=? WHERE id=?",
                   (clock[0], json.dumps([{"recording_end": True, "recording_seconds": 10, "partial_capture": False}]), stage["session_id"]))
        checks = {"duration_seconds": 10, "sampled_frames": 4, "notes": [], "capture_mode": "continuous_scan"}
        result = "mismatch" if partial else "confirmed"
        analysis = {"video": checks, "visual": visual.model_dump(), "result": result, "summary": "Generated evidence fixture."}
        db.execute("UPDATE ih_requests SET status=?,submitted=?,analysis_status='complete',analysis=? WHERE id=?",
                   (result, clock[0], json.dumps(analysis), record["id"]))


def stored_locations():
    with ih.database() as db:
        return [dict(row) for row in db.execute("SELECT * FROM ih_session_locations ORDER BY rowid")]


def assert_no_precise_location(value):
    if isinstance(value, dict):
        assert not {"latitude", "longitude", "accuracy", "timestamp", "lat", "lon", "lng"} & value.keys()
        for item in value.values():
            assert_no_precise_location(item)
    elif isinstance(value, list):
        for item in value:
            assert_no_precise_location(item)
    else:
        assert str(COORDS["latitude"]) not in str(value)
        assert str(COORDS["longitude"]) not in str(value)


def test_fresh_current_session_resolves_and_stores_only_city_state(setup, monkeypatch):
    client, clock, _, _ = setup
    record, stage = fresh_capture(setup)
    calls = []
    monkeypatch.setattr(ih, "resolve_video_location", lambda lat, lon: calls.append((lat, lon)) or CITY)
    response = location(client, record, stage, clock)
    assert response.status_code == 200, response.text
    assert calls == [(COORDS["latitude"], COORDS["longitude"])]
    rows = stored_locations()
    assert rows == [{"session_id": stage["session_id"], **CITY}]
    assert_no_precise_location(response.json())
    with ih.database() as db:
        for table in ("ih_session_locations", "ih_publication_locations"):
            columns = {row["name"] for row in db.execute("PRAGMA table_info(" + table + ")")}
            assert not {"latitude", "longitude", "accuracy", "timestamp", "lat", "lon", "lng"} & columns
        assert_no_precise_location([dict(row) for row in db.execute("SELECT * FROM ih_events")])


@pytest.mark.parametrize("changes", [
    {"latitude": 90.1}, {"latitude": -90.1}, {"longitude": 180.1}, {"longitude": -180.1},
    {"latitude": float("nan")}, {"latitude": float("inf")}, {"longitude": float("-inf")},
    {"accuracy": -1}, {"accuracy": 10000.1}, {"accuracy": float("nan")},
    {"latitude": "37.77"}, {"longitude": False}, {"accuracy": "10"}, {"timestamp": "123"},
    {"timestamp": float("inf")}, {"timestamp": None}, {"city": "Injected city"}, {"country_code": "US"},
])
def test_invalid_or_client_supplied_place_values_never_reach_resolver(setup, monkeypatch, changes):
    client, clock, _, _ = setup
    record, stage = fresh_capture(setup)
    monkeypatch.setattr(ih, "resolve_video_location", lambda *args: pytest.fail("Invalid GPS must never reach resolver"))
    response = location(client, record, stage, clock, **changes)
    assert response.status_code == 422, response.text
    assert_no_precise_location(response.json())
    assert stored_locations() == []


@pytest.mark.parametrize("offset", [-30.1, 10.1])
def test_old_or_future_location_fix_never_resolves(setup, monkeypatch, offset):
    client, clock, _, _ = setup
    record, stage = fresh_capture(setup)
    monkeypatch.setattr(ih, "resolve_video_location", lambda *args: pytest.fail("Stale GPS must never resolve"))
    response = location(client, record, stage, clock, timestamp=(clock[0] + offset) * 1000)
    assert response.status_code in {409, 422}, response.text
    assert stored_locations() == []


def test_fix_from_before_this_recording_is_rejected_even_within_global_freshness(setup, monkeypatch):
    client, clock, _, _ = setup
    record, stage = fresh_capture(setup)
    monkeypatch.setattr(ih, "resolve_video_location", lambda *args: pytest.fail("A prior-take fix cannot label this take"))
    response = location(client, record, stage, clock, timestamp=(clock[0] - 5.1) * 1000)
    assert response.status_code in {409, 422}, response.text
    assert stored_locations() == []


@pytest.mark.parametrize("token_kind", ["unknown", "management", "request_id", "other_capture"])
def test_location_write_requires_the_recording_link_and_its_own_session(setup, monkeypatch, token_kind):
    client, clock, _, _ = setup
    record, stage = fresh_capture(setup)
    other, _ = fresh_capture(setup)
    token = {"unknown": "not-a-token", "management": record["manage_key"], "request_id": record["id"],
             "other_capture": other["token"]}[token_kind]
    monkeypatch.setattr(ih, "resolve_video_location", lambda *args: pytest.fail("Wrong capability must not resolve"))
    response = location(client, {**record, "token": token}, stage, clock)
    assert response.status_code in {404, 409}, response.text
    assert stored_locations() == []


def test_new_take_never_inherits_prior_session_location(setup, monkeypatch):
    client, clock, _, _ = setup
    record, old_stage = fresh_capture(setup)
    monkeypatch.setattr(ih, "resolve_video_location", lambda *args: CITY)
    assert location(client, record, old_stage, clock).status_code == 200
    new_stage = video_start(client, record)
    assert new_stage["session_id"] != old_stage["session_id"]
    assert location(client, record, old_stage, clock).status_code == 409
    finish_fixture(record, new_stage, clock)
    response = manual_publish(client, record)
    assert response.status_code == 201, response.text
    publication = phone_result(client, record)["publication"]
    assert publication.get("location") is None
    assert client.get(BASE + "/public/" + publication["id"]).json().get("location") is None


@pytest.mark.parametrize("provider_result", [None, "exception"])
def test_unavailable_or_denied_location_does_not_block_verification_or_exports(setup, monkeypatch, provider_result):
    client, clock, _, _ = setup
    record, stage = fresh_capture(setup)
    def resolve(*args):
        if provider_result == "exception":
            raise RuntimeError("Lookup unavailable")
        return None
    monkeypatch.setattr(ih, "resolve_video_location", resolve)
    response = location(client, record, stage, clock)
    assert response.status_code == 200, response.text
    assert stored_locations() == []
    finish_fixture(record, stage, clock)
    response = manual_publish(client, record)
    assert response.status_code == 201, response.text
    result = phone_result(client, record)
    assert result["publication_status"] == "ready" and result["verified_count"] == 4
    assert result["publication"].get("location") is None


def test_slow_location_result_is_ignored_after_recording_ends(setup, monkeypatch):
    client, clock, _, _ = setup
    record, stage = fresh_capture(setup)
    def resolve(*args):
        finish_fixture(record, stage, clock)
        return CITY
    monkeypatch.setattr(ih, "resolve_video_location", resolve)
    response = location(client, record, stage, clock)
    assert response.status_code in {200, 409}, response.text
    assert stored_locations() == []
    assert manual_publish(client, record).status_code == 201
    assert phone_result(client, record)["publication"].get("location") is None


def test_resolver_cannot_write_a_late_result_into_a_restarted_take(setup, monkeypatch):
    client, clock, _, _ = setup
    record, stage = fresh_capture(setup)
    new_stages = []
    def resolve(*args):
        new_stages.append(video_start(client, record))
        return CITY
    monkeypatch.setattr(ih, "resolve_video_location", resolve)
    response = location(client, record, stage, clock)
    assert response.status_code in {200, 409}, response.text
    assert stored_locations() == []
    finish_fixture(record, new_stages[0], clock)
    assert manual_publish(client, record).status_code == 201
    assert phone_result(client, record)["publication"].get("location") is None


def test_only_matched_photos_get_location_footer_readable_qr_and_coarse_public_metadata(setup, monkeypatch):
    client, clock, _, _ = setup
    record, stage = fresh_capture(setup)
    monkeypatch.setattr(ih, "resolve_video_location", lambda *args: CITY)
    assert location(client, record, stage, clock).status_code == 200
    finish_fixture(record, stage, clock, partial=True)
    observed_text = []
    original_text = ImageDraw.ImageDraw.text
    def text(draw, xy, value, *args, **kwargs):
        observed_text.append(value)
        return original_text(draw, xy, value, *args, **kwargs)
    monkeypatch.setattr(ImageDraw.ImageDraw, "text", text)
    response = manual_publish(client, record)
    assert response.status_code == 201, response.text
    result = phone_result(client, record)
    publication = result["publication"]
    assert publication["location"] == CITY
    assert [photo["photo_index"] for photo in publication["photos"]] == [0, 2, 3]
    assert any("San Francisco" in value and "CA" in value for value in observed_text)
    assert not any(str(COORDS["latitude"]) in value or str(COORDS["longitude"]) in value for value in observed_text)
    public = client.get(BASE + "/public/" + publication["id"]).json()
    assert public["location"] == CITY and public["verified_count"] == 3 and public["total_count"] == 4
    for photo in public["photos"]:
        response = client.get(BASE + f"/public/{publication['id']}/photos/{photo['id']}")
        assert response.status_code == 200
        assert decode_marking(response.content) == "https://lockx.ai/#in-hand/verify/" + publication["id"]
    private = client.get(BASE + "/requests/" + record["id"], headers=owner_headers(record)).json()
    for payload in [result, publication, public, private]:
        assert_no_precise_location(payload)
    with ih.database() as db:
        frozen = dict(db.execute("SELECT * FROM ih_publication_locations WHERE publication_id=?", (publication["id"],)).fetchone())
        assert frozen == {"publication_id": publication["id"], "session_id": stage["session_id"], **CITY}
        assert db.execute("SELECT COUNT(*) FROM ih_media WHERE request_id=? AND role='marked'", (record["id"],)).fetchone()[0] == 3


def test_completed_and_published_record_location_is_immutable(setup, monkeypatch):
    client, clock, _, _ = setup
    record, stage = fresh_capture(setup)
    monkeypatch.setattr(ih, "resolve_video_location", lambda *args: CITY)
    assert location(client, record, stage, clock).status_code == 200
    finish_fixture(record, stage, clock)
    assert location(client, record, stage, clock).status_code == 409
    assert manual_publish(client, record).status_code == 201
    publication = phone_result(client, record)["publication"]
    before = client.get(BASE + "/public/" + publication["id"]).json()
    monkeypatch.setattr(ih, "resolve_video_location", lambda *args: pytest.fail("Published records cannot resolve a new location"))
    assert location(client, record, stage, clock).status_code == 409
    assert client.get(BASE + "/public/" + publication["id"]).json() == before
    assert stored_locations() == [{"session_id": stage["session_id"], **CITY}]


def test_old_no_location_record_keeps_three_argument_renderer_compatibility(setup, monkeypatch):
    client, clock, _, _ = setup
    record, stage = fresh_capture(setup)
    finish_fixture(record, stage, clock)
    original = ih.marked_photo
    calls = []
    def renderer(content, publication_id, captured):
        calls.append(publication_id)
        return original(content, publication_id, captured)
    monkeypatch.setattr(ih, "marked_photo", renderer)
    assert manual_publish(client, record).status_code == 201
    assert len(calls) == 4
    publication = phone_result(client, record)["publication"]
    assert publication.get("location") is None
    assert client.get(BASE + "/public/" + publication["id"]).json().get("location") is None


def test_location_changes_invalidate_both_approval_fingerprint_and_prepared_exports(setup, monkeypatch):
    client, clock, _, _ = setup
    record, stage = fresh_capture(setup)
    monkeypatch.setattr(ih, "resolve_video_location", lambda *args: CITY)
    assert location(client, record, stage, clock).status_code == 200
    finish_fixture(record, stage, clock)
    with ih.database() as db:
        row = db.execute("SELECT * FROM ih_requests WHERE id=?", (record["id"],)).fetchone()
        before = ih.publication_snapshot(db, row)
        refs = db.execute("SELECT * FROM ih_media WHERE request_id=? AND role='listing' ORDER BY rowid", (record["id"],)).fetchall()
        session = db.execute("SELECT * FROM ih_sessions WHERE id=?", (stage["session_id"],)).fetchone()
        preparation = ih.prepare_exports(row, refs, session)
    assert preparation is not None
    try:
        assert preparation.matches(before)
        with ih.database() as db:
            db.execute("UPDATE ih_session_locations SET city='Oakland' WHERE session_id=?", (stage["session_id"],))
            row = db.execute("SELECT * FROM ih_requests WHERE id=?", (record["id"],)).fetchone()
            after = ih.publication_snapshot(db, row)
        assert after["fingerprint"] != before["fingerprint"]
        assert not preparation.matches(after)
    finally:
        preparation.close()


def test_location_change_during_render_cannot_commit_wrong_city_images(setup, monkeypatch):
    client, clock, tmp, _ = setup
    record, stage = fresh_capture(setup)
    monkeypatch.setattr(ih, "resolve_video_location", lambda *args: CITY)
    assert location(client, record, stage, clock).status_code == 200
    finish_fixture(record, stage, clock)
    changed = threading.Event()
    lock = threading.Lock()
    original = ih.marked_photo
    def renderer(*args, **kwargs):
        with lock:
            if not changed.is_set():
                with sqlite3.connect(tmp / "in-hand.sqlite3", timeout=.2) as db:
                    db.execute("UPDATE ih_session_locations SET city='Oakland' WHERE session_id=?", (stage["session_id"],))
                changed.set()
        return original(*args, **kwargs)
    monkeypatch.setattr(ih, "marked_photo", renderer)
    response = manual_publish(client, record)
    assert response.status_code == 409, response.text
    assert changed.is_set()
    with ih.database() as db:
        assert db.execute("SELECT COUNT(*) FROM ih_publications WHERE request_id=?", (record["id"],)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM ih_publication_locations").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM ih_media WHERE request_id=? AND role='marked'", (record["id"],)).fetchone()[0] == 0


def census_response(*, incorporated=True, cdp=False):
    place = {"BASENAME": "San Francisco", "NAME": "San Francisco city", "STATE": "06",
             "CENTLAT": "37.77492951", "CENTLON": "-122.41941551", "GEOID": "0667000"}
    return {"result": {"geographies": {
        "States": [{"NAME": "California", "STUSAB": "CA", "STATE": "06"}],
        "Incorporated Places": [place] if incorporated else [],
        "Census Designated Places": [{**place, "BASENAME": "Test CDP"}] if cdp else [],
        "Counties": [{"NAME": "San Francisco County"}],
    }, "input": {"location": {"x": COORDS["longitude"], "y": COORDS["latitude"]}}}}


def stub_census(monkeypatch, payload, calls=None):
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, limit):
            assert limit == 262145
            return raw[:limit]
    def urlopen(request, timeout):
        if calls is not None:
            calls.append((request.full_url, timeout))
        return Response()
    monkeypatch.setattr(ih, "urlopen", urlopen)


@pytest.mark.parametrize("incorporated,cdp,city", [(True, True, "San Francisco"), (False, True, "Test CDP")])
def test_census_resolver_uses_actual_city_or_cdp_with_matching_state_not_raw_provider_fields(monkeypatch, incorporated, cdp, city):
    from urllib.parse import parse_qs, urlparse
    calls = []
    stub_census(monkeypatch, census_response(incorporated=incorporated, cdp=cdp), calls)
    resolved = ih.resolve_video_location(COORDS["latitude"], COORDS["longitude"])
    assert resolved == {**CITY, "city": city}
    assert_no_precise_location(resolved)
    url, timeout = calls[0]
    assert urlparse(url).hostname == "geocoding.geo.census.gov" and timeout == 3.5
    query = parse_qs(urlparse(url).query)
    assert query["x"] == ["-122.419"] and query["y"] == ["37.775"]
    assert query["benchmark"] == ["Public_AR_Current"] and query["vintage"] == ["Current_Current"]


@pytest.mark.parametrize("case", ["county_only", "wrong_state", "invalid_state", "missing_state", "invalid_city", "invalid_json", "oversized", "unexpected_shape", "timeout"])
def test_reverse_geocoder_failure_or_unreliable_place_omits_location_without_inventing_a_city(monkeypatch, caplog, case):
    payload = census_response()
    geographies = payload["result"]["geographies"]
    if case == "county_only":
        geographies["Incorporated Places"] = []
    elif case == "wrong_state":
        geographies["Incorporated Places"][0]["STATE"] = "36"
    elif case == "invalid_state":
        geographies["States"][0]["STUSAB"] = "California"
    elif case == "missing_state":
        geographies["States"] = []
    elif case == "invalid_city":
        geographies["Incorporated Places"][0]["BASENAME"] = "City\nInjected text"
    elif case == "invalid_json":
        payload = b"not JSON"
    elif case == "oversized":
        payload = b" " * 262145
    elif case == "unexpected_shape":
        payload = {"result": {"geographies": ["bad"]}}
    if case == "timeout":
        def unavailable(*args, **kwargs):
            raise TimeoutError(f"Sensitive provider URL?x={COORDS['longitude']}&y={COORDS['latitude']}")
        monkeypatch.setattr(ih, "urlopen", unavailable)
    else:
        stub_census(monkeypatch, payload)
    assert ih.resolve_video_location(COORDS["latitude"], COORDS["longitude"]) is None
    assert str(COORDS["latitude"]) not in caplog.text and str(COORDS["longitude"]) not in caplog.text


def test_first_valid_session_fix_cannot_be_replaced_by_a_second_city(setup, monkeypatch):
    client, clock, _, _ = setup
    record, stage = fresh_capture(setup)
    monkeypatch.setattr(ih, "resolve_video_location", lambda *args: CITY)
    assert location(client, record, stage, clock).status_code == 200
    monkeypatch.setattr(ih, "resolve_video_location", lambda *args: pytest.fail("The first resolved location is immutable"))
    response = location(client, record, stage, clock, latitude=38.1234, longitude=-121.1234)
    assert response.status_code == 200 and response.json()["location"] == CITY
    assert stored_locations() == [{"session_id": stage["session_id"], **CITY}]


def test_published_location_is_frozen_independently_of_private_session_metadata(setup, monkeypatch):
    client, clock, _, _ = setup
    record, stage = fresh_capture(setup)
    monkeypatch.setattr(ih, "resolve_video_location", lambda *args: CITY)
    assert location(client, record, stage, clock).status_code == 200
    finish_fixture(record, stage, clock)
    assert manual_publish(client, record).status_code == 201
    publication = phone_result(client, record)["publication"]
    before = client.get(BASE + "/public/" + publication["id"]).json()
    with ih.database() as db:
        db.execute("UPDATE ih_session_locations SET city='Oakland' WHERE session_id=?", (stage["session_id"],))
    assert client.get(BASE + "/public/" + publication["id"]).json() == before
    assert phone_result(client, record)["publication"]["location"] == CITY


def test_quality_retry_requires_its_own_fresh_recording_location(setup, monkeypatch):
    from test_in_hand_quality_retry import quality_assessment, retry
    client, clock, _, _ = setup
    record, stage = fresh_capture(setup)
    monkeypatch.setattr(ih, "resolve_video_location", lambda *args: CITY)
    assert location(client, record, stage, clock).status_code == 200
    finish_fixture(record, stage, clock)
    with ih.database() as db:
        row = db.execute("SELECT analysis FROM ih_requests WHERE id=?", (record["id"],)).fetchone()
        analysis = json.loads(row["analysis"])
        analysis["visual"] = quality_assessment().model_dump()
        analysis["result"] = "inconclusive"
        analysis["video"].update(notes=["Most sampled views have lighting or focus issues."],
                                  quality_diagnostics={"retry_reason": "low_light", "sampled_frames": 4, "low_light_frames": 4})
        db.execute("UPDATE ih_requests SET status='inconclusive',analysis=? WHERE id=?", (json.dumps(analysis), record["id"]))
    response = retry(client, record)
    assert response.status_code == 201, response.text
    child = response.json()
    child_stage = video_start(client, child)
    finish_fixture(child, child_stage, clock)
    ih.auto_publish_confirmed(child["id"])
    publication = phone_result(client, child)["publication"]
    assert publication.get("location") is None
    assert client.get(BASE + "/public/" + publication["id"]).json().get("location") is None
    assert stored_locations() == [{"session_id": stage["session_id"], **CITY}]


@pytest.mark.parametrize("raw,status", [(b"", 422), (b"not-json", 422), (b"[]", 422), (b" " * 2049, 413)])
def test_invalid_and_oversized_location_bodies_are_bounded_without_resolver_calls(setup, monkeypatch, raw, status):
    client, _, _, _ = setup
    record, _ = fresh_capture(setup)
    monkeypatch.setattr(ih, "resolve_video_location", lambda *args: pytest.fail("Rejected bodies must never reach the provider"))
    response = client.post(BASE + f"/seller/{record['token']}/location", content=raw,
                           headers={"content-type": "application/json"})
    assert response.status_code == status, response.text
    assert stored_locations() == []


def test_abandoned_capture_session_cannot_add_location_after_thirty_seconds(setup, monkeypatch):
    client, clock, _, _ = setup
    record, stage = fresh_capture(setup)
    clock[0] += 30.1
    monkeypatch.setattr(ih, "resolve_video_location", lambda *args: pytest.fail("An abandoned recording must never resolve GPS"))
    response = location(client, record, stage, clock)
    assert response.status_code == 409, response.text
    assert stored_locations() == []
