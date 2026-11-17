"""Recovery identifiers are validated before any owner-scoped storage request."""
from unittest.mock import Mock
from urllib.parse import quote

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import main

CASE = "6a63a14c-e60e-4b29-94ef-68c0c6099dc8"
PHOTO = "6b462051-ae7d-45cc-822d-6033690b38d8"
OWNER = "ff2581a8-a31a-4fb9-8aba-fc8515780182"
INVALID_IDS = ["invalid", CASE + "#", CASE + "&x=y", CASE + "?x=y"]


@pytest.fixture
def client(monkeypatch):
    saved = dict(main.app.dependency_overrides)
    main.app.dependency_overrides[main.current_user] = lambda: OWNER
    storage = Mock()
    monkeypatch.setattr(main, "supabase_request", storage)
    try:
        yield TestClient(main.app), storage
    finally:
        main.app.dependency_overrides.clear()
        main.app.dependency_overrides.update(saved)


@pytest.mark.parametrize("identifier", INVALID_IDS)
@pytest.mark.parametrize("operation", ["scans", "photos", "update", "scan", "delete", "upload", "delete_photo"])
def test_invalid_case_identifier_never_reaches_storage(client, identifier, operation):
    browser, storage = client
    base = "/api/v1/cases/" + quote(identifier, safe="")
    if operation in {"scans", "photos"}:
        response = browser.get(base + "/" + operation)
    elif operation == "update":
        response = browser.patch(base, json={"brand": "Test", "model": "Test"})
    elif operation == "upload":
        response = browser.post(base + "/photos", files={"photo": ("test.jpg", b"test", "image/jpeg")})
    elif operation == "delete_photo":
        response = browser.post(base + "/photos/" + PHOTO + "/delete")
    else:
        response = browser.post(base + "/" + operation)
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid recovery identifier"}
    storage.assert_not_called()


@pytest.mark.parametrize("identifier", INVALID_IDS)
def test_invalid_photo_identifier_never_reaches_storage(client, identifier):
    browser, storage = client
    response = browser.post("/api/v1/cases/" + CASE + "/photos/" + quote(identifier, safe="") + "/delete")
    assert response.status_code == 422
    storage.assert_not_called()


@pytest.mark.parametrize("lookup", [main.assert_case_owner, main.owned_case_row])
def test_valid_case_keeps_exact_owner_filter(client, lookup):
    _, storage = client
    storage.return_value.json.return_value = [{"id": CASE}]
    lookup(CASE, OWNER)
    assert storage.call_count == 1
    method, path = storage.call_args.args
    assert method == "GET"
    assert path.startswith("watch_cases?id=eq." + CASE + "&owner_id=eq." + OWNER + "&select=")


@pytest.mark.parametrize("lookup", [main.assert_case_owner, main.owned_case_row])
def test_missing_owned_case_remains_not_found(client, lookup):
    _, storage = client
    storage.return_value.json.return_value = []
    with pytest.raises(HTTPException) as error:
        lookup(CASE, OWNER)
    assert error.value.status_code == 404
