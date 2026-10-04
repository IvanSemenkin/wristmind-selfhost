from unittest.mock import AsyncMock

from wristmind_server import latency_trace


def test_watch_can_export_bounded_diagnostics(client, admin_headers, monkeypatch):
    pairing = client.post("/v1/devices/pairing-codes", headers=admin_headers)
    watch = client.post(
        "/v1/devices/enroll",
        json={"name": "Xiaomi Watch 2", "kind": "WATCH", "code": pairing.json()["code"]},
    ).json()
    sent = AsyncMock()
    monkeypatch.setattr(latency_trace, "telegram_enabled", lambda: True)
    monkeypatch.setattr(latency_trace, "send_wear_diagnostics", sent)
    lines = [
        "1791111111111 latency latency_trace event=WATCH_FIRST_DELTA_RECEIVED elapsed_ms=81000",
        "1791111111112 answer answer_trace event=stream_interrupted cursor=17",
    ]

    response = client.post(
        "/v1/diagnostics/wear",
        headers={"Authorization": f"Bearer {watch['token']}"},
        json={"lines": lines},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"sent": 2}
    sent.assert_awaited_once_with(lines, watch["device_id"])


def test_wear_diagnostics_rejects_other_devices_and_arbitrary_text(client, admin_headers, monkeypatch):
    sent = AsyncMock()
    monkeypatch.setattr(latency_trace, "telegram_enabled", lambda: True)
    monkeypatch.setattr(latency_trace, "send_wear_diagnostics", sent)
    line = "1791111111111 latency latency_trace event=SEND_STARTED elapsed_ms=0"
    assert client.post("/v1/diagnostics/wear", json={"lines": [line]}).status_code == 401
    assert client.post(
        "/v1/diagnostics/wear", headers=admin_headers, json={"lines": [line]},
    ).status_code == 403

    pairing = client.post("/v1/devices/pairing-codes", headers=admin_headers)
    watch = client.post(
        "/v1/devices/enroll",
        json={"name": "Xiaomi Watch 2", "kind": "WATCH", "code": pairing.json()["code"]},
    ).json()
    response = client.post(
        "/v1/diagnostics/wear",
        headers={"Authorization": f"Bearer {watch['token']}"},
        json={"lines": ["1791111111111 answer private message text"]},
    )
    assert response.status_code == 422
    sent.assert_not_awaited()
