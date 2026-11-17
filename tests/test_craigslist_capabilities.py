"""Report configured contact lookup availability without attempting a reveal."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import in_hand as ih


@pytest.mark.parametrize("mode,enabled", [
    (None, False),
    ("", False),
    ("local", False),
    (" LOCAL ", False),
    ("off", False),
    (" OFF ", False),
    ("unknown", False),
    ("remote-disabled", False),
    ("https://remote.example.test", False),
    ("remote", True),
    ("REMOTE", True),
    (" \tReMoTe\n", True),
])
def test_contact_capability_matches_explicit_remote_configuration_without_lookup(monkeypatch, mode, enabled):
    if mode is None:
        monkeypatch.delenv("LOCKX_CRAIGSLIST_CONTACT_MODE", raising=False)
    else:
        monkeypatch.setenv("LOCKX_CRAIGSLIST_CONTACT_MODE", mode)
    monkeypatch.setattr(ih, "visual_ready", lambda: False)
    monkeypatch.setattr(ih.seller_email, "configured", lambda: False)
    monkeypatch.setattr(ih.credits, "enabled", lambda: False)

    def unexpected(*args, **kwargs):
        raise AssertionError("Reading capabilities cannot authenticate or access stored evidence")

    monkeypatch.setattr(ih, "database", unexpected)
    application = FastAPI()
    application.include_router(ih.create_router(unexpected))
    with TestClient(application) as client:
        response = client.get("/api/v1/in-hand/capabilities")

    assert response.status_code == 200
    capabilities = response.json()
    assert capabilities["craigslist_reply_reveal"] is enabled
    assert capabilities["max_photos"] == 4
    assert capabilities["listing_photo_import"] is True
    assert capabilities["seller_email_drafts"] is True
    assert capabilities["seller_email_sending"] is False

