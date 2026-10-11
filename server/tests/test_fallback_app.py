import time

from fastapi.testclient import TestClient

from wristmind_server.fallback_app import app, settings
from wristmind_server.fallback_auth import issue_fallback_ticket


def test_status_reports_main_and_fallback_without_ticket(monkeypatch):
    import wristmind_server.fallback_app as fallback_app

    async def main_up():
        return True

    monkeypatch.setattr(fallback_app, "_main_available", main_up)
    with TestClient(app) as client:
        response = client.get("/fallback/status")
    assert response.status_code == 200
    assert response.json()["main"] == "up"
    assert response.json()["fallback"] == "ok"
    assert response.json()["updated_at"]

    async def main_down():
        return False

    monkeypatch.setattr(fallback_app, "_main_available", main_down)
    with TestClient(app) as client:
        response = client.get("/fallback/status")
    assert response.json()["main"] == "down"


def test_fallback_response_is_authenticated_and_idempotent(tmp_path):
    settings.fallback_database_path = tmp_path / "fallback.sqlite3"
    ticket = issue_fallback_ticket(
        "watch-test",
        "user-test",
        int(time.time()) + 300,
        settings.fallback_ticket_secret.get_secret_value(),
    )
    payload = {
        "request_id": "fallback-request-1",
        "chat_id": "chat-test",
        "mode_name": "История",
        "system_prompt": "Отвечай как учитель истории.",
        "history": [{"role": "user", "content": "Расскажи о реформах"}],
        "text": "А что изменилось затем?",
        "requested_web_search": True,
    }

    with TestClient(app) as client:
        unauthorized = client.post("/fallback/v1/respond", json=payload)
        first = client.post(
            "/fallback/v1/respond",
            headers={"Authorization": f"Bearer {ticket}"},
            json=payload,
        )
        repeated = client.post(
            "/fallback/v1/respond",
            headers={"Authorization": f"Bearer {ticket}"},
            json=payload,
        )

    assert unauthorized.status_code == 401
    assert first.status_code == 200, first.text
    assert repeated.json() == first.json()
    assert first.json()["degraded"] is True
    assert first.json()["sources_available"] is False
