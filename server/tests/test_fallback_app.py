import time

from fastapi.testclient import TestClient

from wristmind_server.fallback_app import app, settings
from wristmind_server.fallback_auth import issue_fallback_ticket


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
