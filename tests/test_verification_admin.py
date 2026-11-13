"""Queue operations are protected by the existing verified-UUID admin gate."""
import sys
from types import SimpleNamespace

from test_credit_admin import AUTH, client


def test_queue_stats_cannot_be_read_by_anonymous_or_member(client):
    route = "/api/v1/credits/admin/queue"
    assert client.get(route).status_code == 401
    assert client.get(route, headers={"Authorization": "Bearer member"}).status_code == 403


def test_admin_queue_stats_are_private_and_do_not_change_wallet(client, monkeypatch):
    calls = []
    def snapshot():
        calls.append(True)
        return {"counts": {"queued": 2, "running": 1},
                "budget": {"limit_usd": 100, "actual_recorded_usd": .05}}
    monkeypatch.setitem(sys.modules, "verification_queue", SimpleNamespace(admin_status=snapshot))
    response = client.get("/api/v1/credits/admin/queue", headers=AUTH)
    assert response.status_code == 200 and calls == [True]
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["budget"]["limit_usd"] == 100
    assert "email" not in response.text and "token" not in response.text
