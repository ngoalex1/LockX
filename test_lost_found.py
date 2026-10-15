import io
import json
from datetime import datetime, timezone

import httpx
import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from PIL import Image
from twilio.request_validator import RequestValidator

import lost_found as lf


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCKX_DATA_DIR", str(tmp_path))
    for key in ("OPENAI_API_KEY", "LOCKX_VISION_MODEL", "TWILIO_AUTH_TOKEN", "TWILIO_ACCOUNT_SID", "LOCKX_MMS_NUMBER", "LOCKX_MMS_WEBHOOK_URL"):
        monkeypatch.delenv(key, raising=False)
    def identity(authorization: str = Header(default="")):
        if not authorization.startswith("Bearer "):
            raise HTTPException(401)
        return authorization[7:]
    app = FastAPI()
    app.include_router(lf.create_router(identity))
    return TestClient(app)


def jpeg():
    buffer = io.BytesIO()
    Image.new("RGB", (40, 40), "green").save(buffer, "JPEG")
    return buffer.getvalue()


def report(**updates):
    return {"title":"Rolex Submariner", "category":"Watch", "incident":"lost", "brand":"Rolex", "model":"Submariner", "color":"Black", "serial":"AB-1234", "location":"San Francisco", "incident_date":"2026-01-01", "details":"Steel bracelet with a small scratch near the clasp.", "private_details":"Secret engraving 1985", "police_reference":"PRIVATE-POLICE", "value":1000000, **updates}


def post_report(client, owner="alice", **updates):
    return client.post("/api/v1/lost-found/reports", headers={"Authorization":"Bearer " + owner}, data={"payload":json.dumps(report(**updates))}, files=[("photos", ("item.jpg", jpeg(), "image/jpeg"))])


def finder(client, **updates):
    return client.post("/api/v1/lost-found/sightings", data={"payload":json.dumps({"consent":True,"category":"Watch","serial":"AB1234","location":"Nearby cafe","contact":"finder@example.test", **updates})}, files=[("photos", ("found.jpg", jpeg(), "image/jpeg"))])


def matches(client, owner="alice"):
    return client.get("/api/v1/lost-found/matches", headers={"Authorization":"Bearer " + owner}).json()


def update(client, match_id, status, note="", owner="alice"):
    return client.patch("/api/v1/lost-found/matches/" + match_id, headers={"Authorization":"Bearer " + owner}, json={"status":status,"verification_note":note})


def test_private_evidence_and_photos_are_scoped(client):
    created = post_report(client)
    assert created.status_code == 201, created.text
    private = created.json()
    assert private["reward"] == 300000
    public = client.get("/api/v1/lost-found/public").json()[0]
    assert not ({"serial","private_details","police_reference","owner_id"} & public.keys())
    assert "1985" not in json.dumps(public)
    photo = private["photos"][0]
    assert client.get("/api/v1/lost-found/public/photos/" + photo).status_code == 200
    assert client.get("/api/v1/lost-found/photos/" + photo).status_code == 401
    assert client.get("/api/v1/lost-found/photos/" + photo, headers={"Authorization":"Bearer bob"}).status_code == 404
    assert client.get("/api/v1/lost-found/reports", headers={"Authorization":"Bearer bob"}).json() == []


def test_unpublished_reports_and_photos_never_go_public(client):
    private = post_report(client, publish=False).json()
    assert client.get("/api/v1/lost-found/public").json() == []
    assert client.get("/api/v1/lost-found/public/photos/" + private["photos"][0]).status_code == 404


def test_anonymous_intake_matches_and_contact_is_gated(client):
    post_report(client)
    submission = finder(client)
    assert submission.status_code == 201, submission.text
    assert set(submission.json()) == {"id","status","message"}
    lead = matches(client)[0]
    assert lead["score"] == 98
    assert lead["analysis_status"] == "manual_review"
    assert "contact" not in lead["sighting"]
    assert matches(client, "bob") == []
    assert client.get("/api/v1/lost-found/public/photos/" + lead["photos"][0]).status_code == 404
    assert client.get("/api/v1/lost-found/photos/" + lead["photos"][0], headers={"Authorization":"Bearer bob"}).status_code == 404
    assert client.get("/api/v1/lost-found/photos/" + lead["photos"][0], headers={"Authorization":"Bearer alice"}).status_code == 200


def test_return_requires_review_and_evidence(client):
    post_report(client)
    finder(client)
    mid = matches(client)[0]["id"]
    assert update(client, mid, "returned", "I have received the watch").status_code == 409
    assert update(client, mid, "reviewing", owner="bob").status_code == 404
    assert update(client, mid, "reviewing").status_code == 200
    assert update(client, mid, "verified", "yes").status_code == 422
    assert update(client, mid, "verified", "Private engraving matches my receipt").status_code == 200
    assert matches(client)[0]["sighting"]["contact"] == "finder@example.test"
    assert update(client, mid, "returned", "Returned at the agreed location").status_code == 200
    assert client.get("/api/v1/lost-found/public").json() == []
    assert client.get("/api/v1/lost-found/reports", headers={"Authorization":"Bearer alice"}).json()[0]["status"] == "recovered"


def test_finder_before_report_is_rematched(client):
    finder(client)
    assert matches(client) == []
    post_report(client)
    assert len(matches(client)) == 1
    lf.rematch_all()
    assert len(matches(client)) == 1


def test_description_only_brand_model_can_match_without_vision(client):
    post_report(client, serial="")
    finder(client, serial="", description="I found a Rolex Submariner with a steel bracelet.")
    lead = matches(client)[0]
    assert lead["score"] >= 70
    assert any("Description mentions brand" in reason for reason in lead["reasons"])


def test_provider_failure_retains_photo_and_manual_match(client, monkeypatch):
    post_report(client)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("LOCKX_VISION_MODEL", "test-model")
    def unavailable(*args, **kwargs):
        raise httpx.ConnectError("Provider unavailable")
    monkeypatch.setattr(httpx, "post", unavailable)
    assert finder(client).status_code == 201
    lead = matches(client)[0]
    assert lead["analysis_status"] == "analysis_failed"
    assert lead["photos"] and lead["score"] == 98
    lf.rematch_all()
    assert len(matches(client)) == 1


def test_serial_conflict_beats_similar_attributes(client):
    post_report(client)
    finder(client, serial="DIFFERENT", brand="Rolex", model="Submariner", color="Black")
    assert matches(client) == []
    score, reasons = lf.rank(report(serial=""), {"category":"Watch","brand":"Rolex"})
    assert score == 40


@pytest.mark.parametrize("updates", [{"value":0},{"value":-1},{"reward_percent":101},{"incident_date":"2099-01-01"},{"category":"Not valid"}])
def test_invalid_report_rejected_atomically(client, updates):
    assert post_report(client, **updates).status_code == 422
    assert client.get("/api/v1/lost-found/public").json() == []


def test_invalid_image_and_missing_consent_rejected(client):
    response = client.post("/api/v1/lost-found/sightings", data={"payload":json.dumps({"consent":True})}, files={"photos":("bad.jpg", b"<script>bad</script>", "image/jpeg")})
    assert response.status_code == 415
    assert finder(client, consent=False).status_code == 422
    assert len(lf.clean_photo(jpeg())) > 0


def test_limits_and_no_fabricated_integration_status(client):
    caps = client.get("/api/v1/lost-found/capabilities").json()
    assert caps["sms_ready"] is False and caps["vision_ready"] is False
    assert caps["reward_payments_ready"] is False
    for _ in range(15):
        assert finder(client).status_code == 201
    assert finder(client).status_code == 429


def sms_config(monkeypatch):
    config = {"TWILIO_ACCOUNT_SID":"AC" + "a" * 32,"TWILIO_AUTH_TOKEN":"test-token","LOCKX_MMS_NUMBER":"+15555550100","LOCKX_MMS_WEBHOOK_URL":"https://api.example.test/api/v1/lost-found/webhooks/twilio"}
    for key, value in config.items():
        monkeypatch.setenv(key, value)
    return config


def sms(client, config, fields, valid=True):
    data = {"AccountSid":config["TWILIO_ACCOUNT_SID"],"To":config["LOCKX_MMS_NUMBER"],"From":"+15555550101", "MessageSid":"SM" + "b" * 32,"NumMedia":"0", **fields}
    signature = RequestValidator(config["TWILIO_AUTH_TOKEN"]).compute_signature(config["LOCKX_MMS_WEBHOOK_URL"], data)
    return client.post("/api/v1/lost-found/webhooks/twilio", data=data, headers={"X-Twilio-Signature": signature if valid else "forged"})


def test_signed_mms_deduplicates_and_saves_followup(client, monkeypatch):
    config = sms_config(monkeypatch)
    monkeypatch.setattr(lf, "process_sighting", lambda _: None)
    fields = {"NumMedia":"1","MediaUrl0":"https://api.twilio.com/2010-04-01/Accounts/" + config["TWILIO_ACCOUNT_SID"] + "/Messages/SM" + "b"*32 + "/Media/ME" + "c"*32}
    assert sms(client, config, fields, valid=False).status_code == 403
    first = sms(client, config, fields)
    assert first.status_code == 200 and "Photos received" in first.text
    assert sms(client, config, fields).text == first.text
    with lf.database() as db:
        assert db.execute("SELECT count(*) FROM sightings").fetchone()[0] == 1
    followup = sms(client, config, {"MessageSid":"SM"+"d"*32,"Body":"Found at the library"})
    assert "update was added" in followup.text
    with lf.database() as db:
        row = db.execute("SELECT * FROM sightings").fetchone()
        assert json.loads(row["data"])["location"] == "Found at the library"
        assert "+15555550101" not in json.dumps(dict(row))


def test_mms_media_rejects_arbitrary_urls_without_network(client, monkeypatch):
    sms_config(monkeypatch)
    with lf.database() as db:
        db.execute("INSERT INTO sightings(id,data,source,created_at) VALUES (?,?,?,?)", ("ssrf",json.dumps({"media_urls":["http://169.254.169.254/latest/meta-data/"]}),"mms",lf.now()))
    def fail_network(*args, **kwargs):
        pytest.fail("Untrusted media URL must not be fetched")
    monkeypatch.setattr(httpx.Client, "stream", fail_network)
    lf.fetch_mms("ssrf")
    with lf.database() as db:
        assert db.execute("SELECT analysis_status FROM sightings WHERE id='ssrf'").fetchone()[0] == "media_failed"


def test_photo_analysis_adapter_and_claimed_job(client, monkeypatch):
    post_report(client)
    # Create without credentials, then retry after configuring the provider.
    sighting = finder(client, serial="").json()["id"]
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("LOCKX_VISION_MODEL", "test-vision-model")
    calls = []
    def provider(url, **kwargs):
        calls.append(kwargs["json"])
        return httpx.Response(200, request=httpx.Request("POST", url), json={"output":[{"content":[{"type":"output_text","text":json.dumps({"category":"Watch","serial":"AB1234"})}]}]})
    monkeypatch.setattr(httpx, "post", provider)
    lf.process_sighting(sighting)
    lf.process_sighting(sighting)
    assert len(calls) == 1
    assert calls[0]["store"] is False
    assert calls[0]["input"][0]["content"][1]["image_url"].startswith("data:image/jpeg;base64,")
    assert matches(client)[0]["score"] == 98
    assert matches(client)[0]["analysis_status"] == "analyzed"


def test_production_cors_allows_match_review():
    from main import app
    response = TestClient(app).options("/api/v1/lost-found/matches/example", headers={
        "Origin":"https://lockx.ai", "Access-Control-Request-Method":"PATCH",
        "Access-Control-Request-Headers":"authorization,content-type"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://lockx.ai"


def edit_report(client, created, owner="alice", **changes):
    fields = lf.ReportInput.model_fields
    payload = {k: v for k, v in created.items() if k in fields}
    payload.update(changes)
    return client.patch("/api/v1/lost-found/reports/" + created["id"], headers={"Authorization":"Bearer " + owner}, json={"report":payload,"expected_revision":created["revision"]})


def status_report(client, created, status, owner="alice"):
    return client.patch("/api/v1/lost-found/reports/" + created["id"] + "/status", headers={"Authorization":"Bearer " + owner}, json={"status":status,"expected_revision":created["revision"]})


def test_edit_is_owner_scoped_and_guards_stale_changes(client):
    created = post_report(client).json()
    assert created["revision"] == 1
    assert edit_report(client, created, owner="bob", title="Stolen edit").status_code == 404
    changed = edit_report(client, created, title="Updated Rolex", reward_percent=20)
    assert changed.status_code == 200, changed.text
    assert changed.json()["revision"] == 2 and changed.json()["reward"] == 200000
    assert changed.json()["photos"] == created["photos"]
    assert edit_report(client, created, title="Old window edit").status_code == 409


def test_archive_restore_and_public_photo_visibility(client):
    created = post_report(client).json()
    archived = status_report(client, created, "archived")
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    assert client.get("/api/v1/lost-found/public").json() == []
    assert client.get("/api/v1/lost-found/public/reports/" + created["id"]).status_code == 404
    assert client.get("/api/v1/lost-found/public/photos/" + created["photos"][0]).status_code == 404
    assert status_report(client, created, "active").status_code == 409
    restored = status_report(client, archived.json(), "active")
    assert restored.status_code == 200 and restored.json()["revision"] == 3
    assert client.get("/api/v1/lost-found/public/reports/" + created["id"]).status_code == 200


def test_targeted_photo_only_lead_reaches_selected_owner(client):
    created = post_report(client).json()
    submission = finder(client, serial="", category=None, target_report_id=created["id"])
    assert submission.status_code == 201
    lead = matches(client)[0]
    assert lead["report_id"] == created["id"] and lead["score"] == 20
    assert "Finder selected" in lead["reasons"][0]
    assert "contact" not in lead["sighting"]


def test_targeted_reports_cannot_point_to_private_or_archived_reports(client):
    created = post_report(client, publish=False).json()
    assert finder(client, target_report_id=created["id"]).status_code == 404
    published = post_report(client, title="Another item").json()
    status_report(client, published, "archived")
    assert finder(client, target_report_id=published["id"]).status_code == 404
    assert finder(client, target_report_id="nonexistent").status_code == 404


def test_report_edit_revokes_stale_match_photos_and_contact(client):
    created = post_report(client).json()
    finder(client)
    lead = matches(client)[0]
    photo = lead["photos"][0]
    update(client, lead["id"], "reviewing")
    update(client, lead["id"], "verified", "Receipt and private engraving agree")
    changed = edit_report(client, created, serial="CHANGED-IDENTIFIER")
    assert changed.status_code == 200
    stale = matches(client)[0]
    assert stale["status"] == "withdrawn" and stale["photos"] == []
    assert "contact" not in stale["sighting"]
    assert client.get("/api/v1/lost-found/photos/" + photo, headers={"Authorization":"Bearer alice"}).status_code == 404
    assert update(client, lead["id"], "returned", "Trying an outdated match").status_code == 409


def test_archive_blocks_match_transitions_until_restore(client):
    created = post_report(client).json()
    finder(client)
    mid = matches(client)[0]["id"]
    archived = status_report(client, created, "archived").json()
    assert update(client, mid, "reviewing").status_code == 409
    status_report(client, archived, "active")
    assert update(client, mid, "reviewing").status_code == 200


def test_export_and_history_are_private_and_do_not_leak_unverified_contact(client):
    created = post_report(client).json()
    finder(client)
    edit_report(client, created, details="The steel bracelet has a scratch near its clasp.")
    path = "/api/v1/lost-found/reports/" + created["id"]
    assert client.get(path + "/evidence").status_code == 401
    assert client.get(path + "/activity", headers={"Authorization":"Bearer bob"}).status_code == 404
    assert client.get(path + "/evidence", headers={"Authorization":"Bearer bob"}).status_code == 404
    result = client.get(path + "/evidence", headers={"Authorization":"Bearer alice"})
    assert result.status_code == 200 and "attachment" in result.headers["content-disposition"]
    evidence = result.json()
    assert evidence["report"]["serial"] == "AB-1234"
    assert evidence["reference_photo_manifest"][0]["sha256"]
    assert "finder@example.test" not in result.text
    assert [e["event"] for e in evidence["activity"]] == ["created", "edited"]
    assert client.get(path + "/activity", headers={"Authorization":"Bearer alice"}).json()[0]["event"] == "edited"


def test_public_single_report_is_redacted(client):
    created = post_report(client).json()
    result = client.get("/api/v1/lost-found/public/reports/" + created["id"])
    assert result.status_code == 200
    assert not ({"serial", "private_details", "police_reference", "revision", "_revision"} & result.json().keys())


def test_railway_requires_persistent_storage(client, monkeypatch):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "test-environment")
    monkeypatch.delenv("LOCKX_DATA_DIR")
    monkeypatch.delenv("RAILWAY_VOLUME_MOUNT_PATH", raising=False)
    result = client.get("/api/v1/lost-found/public")
    assert result.status_code == 503
    assert "persistent storage" in result.json()["detail"]


def test_railway_volume_is_used_automatically(client, monkeypatch, tmp_path):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "test-environment")
    monkeypatch.delenv("LOCKX_DATA_DIR")
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", str(tmp_path / "volume"))
    assert post_report(client).status_code == 201
    assert (tmp_path / "volume" / "lockx" / "lost-found.sqlite3").exists()
