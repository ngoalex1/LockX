"""Explicit buyer email consent, durable deduplication, and offline provider failures."""
import asyncio
import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest

import in_hand as ih
import listing_import as importer
import seller_email as email
from test_buyer_proof import AUTH, BASE, app, create, funds
from test_in_hand import assessment, setup as vision_setup
from test_in_hand_identifiers import seed_pending, selected_labels


RECIPIENT = "seller@listing.example"
FROM = "LockX.ai <proof@verified.example>"


def path(record):
    return BASE + f"/requests/{record['id']}/seller-email"


def preview(app, record, headers=AUTH):
    response = app[0].get(path(record), headers=headers)
    assert response.status_code == 200, response.text
    assert response.headers.get("cache-control") == "no-store"
    return response.json()


def send(app, record, draft=None, headers=AUTH, **fields):
    draft = draft or preview(app, record)
    return app[0].post(path(record), headers=headers, json={
        "recipient": RECIPIENT, "draft_digest": draft["draft_digest"],
        "consent": True, **fields})


@pytest.fixture
def provider(app, monkeypatch):
    """No real address, key, or outgoing provider request is used by API tests."""
    monkeypatch.setenv("LOCKX_SELLER_EMAIL_ENABLED", "1")
    monkeypatch.setenv("LOCKX_SELLER_EMAIL_RESEND_KEY", "re_offline_test_value")
    monkeypatch.setenv("LOCKX_SELLER_EMAIL_FROM", FROM)
    monkeypatch.setenv("LOCKX_PUBLIC_APP_ORIGIN", "https://lockx.ai")
    monkeypatch.setattr(email, "time", SimpleNamespace(time=lambda: app[1][0]))
    state = {"calls": [], "result": {"status": "accepted", "provider_id": "mail-offline-1"}}

    async def deliver(payload, idempotency_key):
        state["calls"].append((copy.deepcopy(payload), idempotency_key))
        callback = state.get("callback")
        return await callback() if callback else copy.deepcopy(state["result"])

    monkeypatch.setattr(email, "deliver", deliver)
    return state


def ledger():
    with ih.database() as db:
        return [tuple(row) for row in db.execute("SELECT * FROM credit_ledger ORDER BY rowid")]


def test_preview_creation_poll_and_import_never_send_or_spend_another_credit(app, provider, monkeypatch):
    record = create(app).json()
    before = ledger()
    draft = preview(app, record)
    assert draft["status"] == "draft"
    assert draft["send_ready"] is True
    assert draft["recipient_locked"] is False
    assert record["token"] in draft["body"]
    assert "https://lockx.ai" in draft["body"]
    assert record["manage_key"] not in json.dumps(draft)
    assert "support@" not in draft["body"].lower()
    assert "buyer@" not in draft["body"].lower()
    assert "re_offline_test_value" not in json.dumps(draft)
    for _ in range(2):
        preview(app, record)
        assert app[0].get(BASE + "/requests", headers=AUTH).status_code == 200
        assert app[0].get(BASE + f"/requests/{record['id']}", headers=AUTH).status_code == 200
        assert app[0].get(BASE + f"/seller/{record['token']}").status_code == 200
    async def import_listing(_):
        return {"status": "unavailable", "contacts": [], "photos": []}
    monkeypatch.setattr(importer, "import_listing", import_listing)
    assert app[0].post(BASE + "/listing-import", json={"url": "https://market.example/items/123"}).status_code == 200
    assert not provider["calls"]
    assert ledger() == before and funds() == 2


def test_explicit_send_uses_fixed_template_and_only_capture_link_then_deduplicates(app, provider):
    record = create(app).json()
    draft = preview(app, record)
    before = ledger()
    response = send(app, record, draft)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "accepted"
    assert response.json()["sent_to"] == RECIPIENT
    assert response.json()["recipient_locked"] is True
    assert response.json()["send_ready"] is False
    payload, key = provider["calls"][0]
    assert payload["from"] == FROM
    assert payload["to"] == [RECIPIENT]
    assert payload["subject"] == draft["subject"]
    assert payload["text"] == draft["body"]
    assert record["token"] in payload["text"]
    assert record["manage_key"] not in json.dumps(payload)
    assert "Bearer buyer" not in json.dumps(payload)
    assert not ({"cc", "bcc", "reply_to", "headers"} & payload.keys())
    assert key and len(key) <= 256
    assert send(app, record, draft).status_code == 200
    assert len(provider["calls"]) == 1
    assert ledger() == before and funds() == 2


@pytest.mark.parametrize("consent", [None, False, "true", 1, [], {}])
def test_send_requires_strict_explicit_true_consent(app, provider, consent):
    record = create(app).json()
    response = send(app, record, consent=consent)
    assert response.status_code == 422, response.text
    assert not provider["calls"] and funds() == 2


@pytest.mark.parametrize("recipient", ["", "seller@listing.example\r\nBcc: victim@example.com", "seller@listing.example\n", "a@example.com,b@example.com", "Name <seller@example.com>", "seller@example.com?bcc=victim@example.com", "a@localhost", "a b@example.com", "a@example.com\x00"])
def test_recipient_rejects_multiple_addresses_and_header_injection(app, provider, recipient):
    record = create(app).json()
    response = send(app, record, recipient=recipient)
    assert response.status_code == 422, response.text
    assert not provider["calls"] and funds() == 2


def test_send_requires_current_exact_draft_and_ignores_no_client_message_fields(app, provider):
    record = create(app).json()
    assert send(app, record, draft_digest="forged").status_code in {409, 422}
    assert not provider["calls"]
    response = send(app, record, subject="Client injection", body="Unrelated text", sender="spoof@example.com")
    assert response.status_code == 422, response.text
    assert not provider["calls"]


def test_only_exact_signed_in_owner_can_send_capture_and_management_keys_cannot(app, provider):
    record = create(app).json()
    draft = preview(app, record)
    assert preview(app, record, {"X-LockX-Manage-Key": record["manage_key"]})["draft_digest"] == draft["draft_digest"]
    for headers, status in [({}, 401), ({"Authorization": "Bearer capturer"}, 404),
                            ({"Authorization": "Bearer capturer", "X-LockX-Manage-Key": record["manage_key"]}, 404),
                            ({"X-LockX-Manage-Key": record["manage_key"]}, 401),
                            ({"X-LockX-Manage-Key": record["token"]}, 401)]:
        response = send(app, record, draft, headers=headers)
        assert response.status_code == status, response.text
    assert app[0].get(path(record), headers={"Authorization": "Bearer capturer"}).status_code == 404
    assert not provider["calls"] and funds() == 2


@pytest.mark.parametrize("count", [1, 2])
def test_signed_listing_contacts_survive_manual_photos_and_draft_requires_buyer_choice(app, provider, monkeypatch, count):
    monkeypatch.setattr(importer, "time", SimpleNamespace(time=lambda: app[1][0]))
    contacts = [f"seller{index}@boutique.example" for index in range(count)]
    html = ('<title>A listed watch</title><section class="seller-contact">' + ''.join(
        f'<a href="mailto:{address}">Email listing seller {index}</a>' for index, address in enumerate(contacts))
        + '</section><footer><a href="mailto:support@market.example">Contact seller</a></footer>')
    async def fetch(url, *, kind="html"):
        assert kind == "html"
        return html.encode(), url, "text/html"
    monkeypatch.setattr(importer, "fetch_public", fetch)
    response = app[0].post(BASE + "/listing-import", json={"url": "https://market.example/items/123?variant=green"})
    assert response.status_code == 200, response.text
    source = response.json()
    assert source["status"] == "unavailable" and source["photos"] == []
    assert source["import_token"]
    result = create(app, contact_import_token=source["import_token"])
    assert result.status_code == 201, result.text
    record = result.json()
    draft = preview(app, record)
    assert [entry["email"] for entry in draft["contacts"]] == contacts
    assert draft["recipient"] == (contacts[0] if count == 1 else "")
    assert "support@market.example" not in json.dumps(draft)
    assert not provider["calls"] and funds() == 2
    with ih.database() as db:
        listing = json.loads(db.execute("SELECT listing FROM ih_requests WHERE id=?", (record["id"],)).fetchone()[0])
        assert "contact_import_token" not in listing
        assert listing["listing_import"]["seller_contact"] == source["seller_contact"]
    assert send(app, record, draft, recipient=contacts[-1]).json()["status"] == "accepted"
    assert provider["calls"][0][0]["to"] == [contacts[-1]]


def test_accepted_invitation_cannot_change_recipient(app, provider):
    record = create(app).json()
    draft = preview(app, record)
    assert send(app, record, draft).json()["status"] == "accepted"
    assert send(app, record, draft, recipient="different@listing.example").status_code == 409
    assert len(provider["calls"]) == 1


@pytest.mark.parametrize("state", ["cancelled", "declined", "expired", "submitted", "capturing"])
def test_only_pending_unsubmitted_waiting_buyer_request_can_send(app, provider, state):
    record = create(app).json()
    draft = preview(app, record)
    if state in {"cancelled", "declined"}:
        suffix = f"/requests/{record['id']}/cancel" if state == "cancelled" else f"/seller/{record['token']}/decline"
        assert app[0].post(BASE + suffix, headers=AUTH, json={"consent": True}).status_code == 200
    elif state == "expired":
        app[1][0] += 86401
    else:
        with ih.database() as db:
            if state == "submitted":
                db.execute("UPDATE ih_requests SET status='processing',submitted=? WHERE id=?", (app[1][0], record["id"]))
            else:
                db.execute("UPDATE ih_requests SET status='capturing' WHERE id=?", (record["id"],))
    assert send(app, record, draft).status_code in {409, 410}
    assert not provider["calls"]


def test_seller_created_inspection_cannot_send_buyer_invitation(app, provider):
    record = create(app, request_kind="seller", request_key="").json()
    response = app[0].get(path(record), headers=AUTH)
    assert response.status_code in {404, 409}
    assert app[0].post(path(record), headers=AUTH, json={"recipient": RECIPIENT, "draft_digest": "a"*64, "consent": True}).status_code in {404, 409}
    assert not provider["calls"]


def test_disabled_sender_configuration_cannot_claim_or_call_provider(app, provider, monkeypatch):
    record = create(app).json()
    draft = preview(app, record)
    monkeypatch.setenv("LOCKX_SELLER_EMAIL_ENABLED", "0")
    assert preview(app, record)["send_ready"] is False
    assert send(app, record, draft).status_code == 503
    assert not provider["calls"]


def test_concurrent_send_clicks_make_one_outbound_request(app, provider):
    record = create(app).json()
    draft = preview(app, record)
    entered, release = threading.Event(), threading.Event()
    async def blocked():
        entered.set()
        assert await asyncio.to_thread(release.wait, 5)
        return {"status": "accepted", "provider_id": "mail-offline-race"}
    provider["callback"] = blocked
    with ThreadPoolExecutor(max_workers=4) as pool:
        first = pool.submit(send, app, record, draft)
        try:
            assert entered.wait(5)
            others = list(pool.map(lambda _: send(app, record, draft), range(3)))
            assert all(r.status_code == 200 and r.json()["status"] == "sending" for r in others)
            assert len(provider["calls"]) == 1
        finally:
            release.set()
        assert first.result().json()["status"] == "accepted"
    assert send(app, record, draft).json()["status"] == "accepted"
    assert len(provider["calls"]) == 1 and funds() == 2


@pytest.mark.parametrize("status", ["uncertain", "rejected"])
def test_failed_or_unknown_attempt_retries_only_exact_recipient_frozen_payload_and_key(app, provider, monkeypatch, status):
    record = create(app).json()
    draft = preview(app, record)
    provider["result"] = {"status": status}
    first = send(app, record, draft)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == ("uncertain" if status == "uncertain" else "draft")
    assert first.json()["recipient_locked"] is True
    original = copy.deepcopy(provider["calls"][0])
    assert send(app, record, draft, recipient="different@listing.example").status_code == 409
    assert len(provider["calls"]) == 1
    monkeypatch.setenv("LOCKX_SELLER_EMAIL_FROM", "Changed <changed@verified.example>")
    monkeypatch.setenv("LOCKX_PUBLIC_APP_ORIGIN", "https://changed.example")
    assert preview(app, record)["body"] == draft["body"]
    provider["result"] = {"status": "accepted", "provider_id": "mail-offline-recovered"}
    app[1][0] += 61
    retry = send(app, record, draft)
    assert retry.status_code == 200 and retry.json()["status"] == "accepted", retry.text
    assert provider["calls"][1] == original
    assert funds() == 2


def test_unknown_result_cannot_be_retried_after_provider_idempotency_window(app, provider):
    record = create(app).json()
    draft = preview(app, record)
    provider["result"] = {"status": "uncertain"}
    assert send(app, record, draft).json()["status"] == "uncertain"
    app[1][0] += 23 * 3600 + 1
    assert preview(app, record)["send_ready"] is False
    assert send(app, record, draft).status_code in {409, 410}
    assert len(provider["calls"]) == 1 and funds() == 2


def test_provider_throttling_prevents_immediate_repeated_outbound_attempts(app, provider):
    record = create(app).json()
    draft = preview(app, record)
    provider["result"] = {"status": "rejected", "retry_after": 60}
    first = send(app, record, draft)
    assert first.status_code == 200 and first.json()["status"] == "draft"
    assert first.json()["send_ready"] is False
    second = send(app, record, draft)
    assert second.status_code in {200, 429}
    assert len(provider["calls"]) == 1
    app[1][0] += 61
    assert preview(app, record)["send_ready"] is True
    provider["result"] = {"status": "accepted", "provider_id": "mail-offline-after-throttle"}
    assert send(app, record, draft).json()["status"] == "accepted"
    assert provider["calls"][0] == provider["calls"][1]


def test_late_completion_cannot_overwrite_more_recent_claim(app, provider):
    record = create(app).json()
    draft = preview(app, record)
    with ih.database() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM ih_requests WHERE id=?", (record["id"],)).fetchone()
        _, first, _ = email.claim(db, row, RECIPIENT, draft["draft_digest"])
        first_claim = db.execute("SELECT claim_id FROM ih_seller_emails WHERE request_id=?", (record["id"],)).fetchone()[0]
    assert first
    app[1][0] += 31
    with ih.database() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM ih_requests WHERE id=?", (record["id"],)).fetchone()
        email.claim(db, row, RECIPIENT, draft["draft_digest"])
        second_claim = db.execute("SELECT claim_id FROM ih_seller_emails WHERE request_id=?", (record["id"],)).fetchone()[0]
        email.complete(db, record["id"], second_claim, {"status": "accepted", "provider_id": "newer-accepted"})
    with ih.database() as db:
        email.complete(db, record["id"], first_claim, {"status": "rejected"})
    assert preview(app, record)["status"] == "accepted"
    assert not provider["calls"]


@pytest.fixture
def wire(monkeypatch):
    """Exercise the actual deliver adapter through an offline HTTPX transport."""
    monkeypatch.setenv("LOCKX_SELLER_EMAIL_RESEND_KEY", "re_offline_test_value")
    state = {"calls": [], "options": [], "status": 200, "body": {"id": "offline-provider-id"}, "headers": {}}
    original = httpx.AsyncClient
    async def respond(request):
        state["calls"].append(request)
        if state.get("error"):
            raise state["error"]
        return httpx.Response(state["status"], json=state["body"], headers=state["headers"], request=request)
    def client(**kwargs):
        state["options"].append(kwargs)
        return original(**kwargs, transport=httpx.MockTransport(respond))
    monkeypatch.setattr(httpx, "AsyncClient", client)
    return state


def deliver():
    return asyncio.run(email.deliver({"from": FROM, "to": [RECIPIENT], "subject": "Fixed", "text": "Fixed body"}, "stable-offline-key"))


def test_provider_uses_fixed_resend_https_without_environment_proxy_or_redirects(wire):
    assert deliver() == {"status": "accepted", "provider_id": "offline-provider-id"}
    request, = wire["calls"]
    assert str(request.url) == "https://api.resend.com/emails" and request.method == "POST"
    assert request.headers["Idempotency-Key"] == "stable-offline-key"
    assert request.headers["Authorization"] == "Bearer re_offline_test_value"
    assert json.loads(request.content)["to"] == [RECIPIENT]
    options, = wire["options"]
    assert options["trust_env"] is False and options["follow_redirects"] is False
    assert 0 < options["timeout"] <= 10


@pytest.mark.parametrize("body", [{}, {"id": ""}, {"id": None}, {"id": "x"*101}, [], None])
def test_success_without_bounded_provider_receipt_is_uncertain(wire, body):
    wire["body"] = body
    assert deliver()["status"] == "uncertain"


@pytest.mark.parametrize("status", [301, 307, 409, 500, 502, 503])
def test_redirect_conflict_and_server_failures_preserve_unknown_outcome(wire, status):
    wire.update(status=status, body={"message": "re_secret_not_for_browser"}, headers={"location": "https://attacker.example"})
    result = deliver()
    assert result["status"] == "uncertain"
    assert "re_secret_not_for_browser" not in json.dumps(result)
    assert len(wire["calls"]) == 1


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 429])
def test_rejected_provider_response_is_definitive_and_details_are_not_leaked(wire, status):
    wire.update(status=status, body={"message": "re_secret_not_for_browser"})
    result = deliver()
    assert result["status"] == "rejected"
    assert "re_secret_not_for_browser" not in json.dumps(result)


@pytest.mark.parametrize("error", [httpx.ConnectTimeout("offline"), httpx.ReadTimeout("offline"), httpx.WriteError("offline")])
def test_network_error_cannot_claim_definitive_delivery_failure(wire, error):
    wire["error"] = error
    assert deliver()["status"] == "uncertain"


def test_provider_rate_limit_preserves_retry_after(wire):
    wire.update(status=429, body={"name": "rate_limit_exceeded"}, headers={"Retry-After": "60"})
    result = deliver()
    assert result["status"] == "rejected"
    assert result["retry_after"] >= 60


@pytest.mark.parametrize("operation", ["scan_plan", "coverage_review", "capture_targets", "comparison"])
def test_visual_calls_keep_item_claims_but_exclude_contact_and_request_metadata(vision_setup, monkeypatch, operation):
    """Inspect the real model HTTP payload at every listing-bearing call site."""
    monkeypatch.setenv("LOCKX_CREDITS_ENABLED", "0")
    monkeypatch.setenv("LOCKX_VERIFICATION_QUEUE_ENABLED", "0")
    record, _, _, _ = seed_pending(vision_setup)
    expected = {"title": "Visible blue ceramic bowl", "category": "Ceramics", "capture_mode": "handheld",
                "description": "Two photographed hairline marks", "details": "Stamped 00127 on base",
                "photo_notes": ["Show the base stamp", "Show the rim", "Show the left mark", "Show the right mark"]}
    private_values = ["private-seller@boutique.example", "private-buyer-request-reference",
                      "https://market.example/private-listing", "private-cdn-source", "private-contact-page"]
    with ih.database() as db:
        row = db.execute("SELECT * FROM ih_requests WHERE id=?", (record["id"],)).fetchone()
        session_id = row["session_id"]
        listing = json.loads(row["listing"])
        listing.update(expected, request_key=private_values[1], listing_url=private_values[2],
                       listing_import={"listing_url": private_values[2], "imported_at": 123,
                           "photos": [{"source_url": "https://images.example/private-cdn-source"}],
                           "seller_contact": {"candidates": [{"email": private_values[0], "source": "listing_mailto"}],
                                              "contact_url": "https://market.example/private-contact-page"}})
        db.execute("UPDATE ih_requests SET listing=? WHERE id=?", (json.dumps(listing), record["id"]))
        if operation in {"scan_plan", "capture_targets"}:
            db.execute("UPDATE ih_requests SET status='waiting',submitted=NULL WHERE id=?", (record["id"],))
        elif operation == "coverage_review":
            db.execute("UPDATE ih_requests SET status='capturing',submitted=NULL WHERE id=?", (record["id"],))
            db.execute("UPDATE ih_sessions SET finished=NULL WHERE id=?", (session_id,))
            db.execute("UPDATE ih_scan_sessions SET review_status='pending' WHERE session_id=?", (session_id,))
    captured = []
    def model_post(url, **kwargs):
        assert url == "https://api.openai.com/v1/responses"
        payload = kwargs["json"]
        captured.append(payload)
        content = payload["input"][0]["content"]
        item = json.loads(content[0]["text"])
        assert item.get("listing", item) == expected
        assert not any(value in json.dumps(payload) for value in private_values)
        assert record["manage_key"] not in json.dumps(payload)
        assert record["token"] not in json.dumps(payload)
        assert payload["store"] is False
        if operation == "scan_plan":
            output = ih.ScanPlan(groups=[ih.ScanGroup(photo_indices=[i], label=f"View {i}", instruction="Show this photographed surface") for i in range(4)])
        elif operation == "coverage_review":
            output = ih.CoverageReview(follow_ups=[])
        elif operation == "capture_targets":
            output = ih.Targets(photo_targets=["Show the photographed marks"] * 4)
        else:
            selected = selected_labels(content)
            output = assessment(photos=[{"photo_index": i, "finding": "supported", "evidence": "The photographed marks correspond.",
                                        "frame_indices": [selected[-1]]} for i in range(4)],
                                claims=[{"subject": "Stamped 00127 on base", "finding": "supported",
                                         "evidence": "The base stamp is visible.", "frame_indices": [selected[-1]]}])
        class Response:
            def raise_for_status(self):
                pass
            def json(self):
                return {"output": [{"content": [{"type": "output_text", "text": output.model_dump_json()}]}]}
        return Response()
    monkeypatch.setenv("OPENAI_API_KEY", "offline-model-test")
    monkeypatch.setenv("LOCKX_IN_HAND_VISION_MODEL", "offline-model-test")
    monkeypatch.setattr(ih.httpx, "post", model_post)
    if operation == "scan_plan":
        ih.prepare_scan(record["id"])
    elif operation == "coverage_review":
        ih.review_scan(session_id)
    elif operation == "capture_targets":
        ih.prepare(record["id"])
    else:
        ih.analyze(record["id"])
    assert len(captured) == 1, "The intended visual call must actually execute"
    with ih.database() as db:
        if operation == "scan_plan":
            assert db.execute("SELECT plan FROM ih_scan_plans WHERE request_id=?", (record["id"],)).fetchone()
        elif operation == "coverage_review":
            assert db.execute("SELECT review_status FROM ih_scan_sessions WHERE session_id=?", (session_id,)).fetchone()[0] == "complete"
        elif operation == "comparison":
            assert db.execute("SELECT analysis_status FROM ih_requests WHERE id=?", (record["id"],)).fetchone()[0] == "complete"
