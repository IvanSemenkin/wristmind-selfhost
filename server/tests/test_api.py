import asyncio
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from wristmind_server.database import SessionFactory
from wristmind_server.db_models import (
    Device,
    KnowledgeChunk,
    KnowledgeSource,
    Job,
    Message,
    PushRegistration,
    ReferencedWebSource,
    RawWebSource,
)


def test_web_panel_can_enroll_and_use_cors(client: TestClient):
    preflight = client.options(
        "/v1/modes",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://localhost:3000"

    enrolled = client.post(
        "/v1/devices/admin/enroll",
        headers={"X-WristMind-Bootstrap": "test-bootstrap"},
        json={"name": "WristMind Web", "kind": "WEB"},
    )
    assert enrolled.status_code == 200, enrolled.text
    assert enrolled.json()["is_admin"] is True


def test_dashboard_stats_counts_only_ai_answer_requests(
    client: TestClient, admin_headers: dict, mode: dict
):
    chat = client.post(
        "/v1/chats", headers=admin_headers, json={"mode_id": mode["id"]}
    ).json()
    for request_id, text in (("dashboard-count-1", "Первый вопрос"), ("dashboard-count-2", "Второй вопрос")):
        assert client.post(
            f"/v1/chats/{chat['id']}/messages",
            headers=admin_headers,
            json={"client_request_id": request_id, "text": text},
        ).status_code == 202

    stats = client.get("/v1/dashboard/stats", headers=admin_headers)
    assert stats.status_code == 200
    assert stats.json()["total_ai_requests"] == 2
    assert stats.json()["requests_today"] == 2
    assert stats.json()["requests_yesterday"] == 0
    assert stats.json()["error_rate_today"] == 0
    assert len(stats.json()["activity"]) == 14
    assert stats.json()["activity"][-1]["requests"] == 2
    assert stats.json()["usage"] == [{"mode_id": mode["id"], "requests": 2, "tokens": 0}]


def test_answer_cancel_is_idempotent_and_keeps_partial_text(client: TestClient, admin_headers: dict, mode: dict):
    chat = client.post("/v1/chats", headers=admin_headers, json={"mode_id": mode["id"]}).json()
    job = client.post(
        f"/v1/chats/{chat['id']}/messages", headers=admin_headers,
        json={"client_request_id": "cancel-partial-1", "text": "Расскажи историю"},
    ).json()

    async def set_partial() -> None:
        async with SessionFactory() as session:
            saved = await session.get(Job, job["id"])
            saved.status = "running"
            assistant = await session.get(Message, saved.payload["assistant_message_id"])
            assistant.content = "Уже полученный фрагмент"
            await session.commit()

    asyncio.run(set_partial())
    first = client.post(f"/v1/jobs/{job['id']}/cancel", headers=admin_headers)
    repeated = client.post(f"/v1/jobs/{job['id']}/cancel", headers=admin_headers)
    assert first.status_code == repeated.status_code == 200
    assert first.json()["status"] == repeated.json()["status"] == "cancelled"
    messages = client.get(f"/v1/chats/{chat['id']}/messages", headers=admin_headers).json()
    assert messages[-1]["content"] == "Уже полученный фрагмент"
    assert messages[-1]["status"] == "cancelled"
    events = client.get(f"/v1/jobs/{job['id']}/events", headers=admin_headers)
    assert events.text.count("event: cancelled") == 1


def test_cancelled_queued_answer_is_not_claimed(client: TestClient, admin_headers: dict, mode: dict):
    chat = client.post("/v1/chats", headers=admin_headers, json={"mode_id": mode["id"]}).json()
    job = client.post(
        f"/v1/chats/{chat['id']}/messages", headers=admin_headers,
        json={"client_request_id": "cancel-queued-1", "text": "Расскажи историю"},
    ).json()
    assert client.post(f"/v1/jobs/{job['id']}/cancel", headers=admin_headers).json()["status"] == "cancelled"

    from wristmind_server.worker import claim_job

    assert asyncio.run(claim_job()) != job["id"]


def test_dashboard_stats_groups_days_errors_and_timezone(
    client: TestClient, admin_headers: dict, mode: dict
):
    chat = client.post(
        "/v1/chats", headers=admin_headers, json={"mode_id": mode["id"]}
    ).json()
    for request_id in ("dashboard-day-1", "dashboard-day-2"):
        response = client.post(
            f"/v1/chats/{chat['id']}/messages",
            headers=admin_headers,
            json={"client_request_id": request_id, "text": request_id},
        )
        assert response.status_code == 202

    async def place_jobs() -> None:
        async with SessionFactory() as session:
            jobs = (await session.scalars(select(Job).where(Job.kind == "ANSWER"))).all()
            today = datetime.now(timezone.utc).date()
            jobs[0].created_at = datetime.combine(today - timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
            jobs[1].created_at = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
            jobs[1].status = "failed"
            await session.commit()

    asyncio.run(place_jobs())
    response = client.get("/v1/dashboard/stats?utc_offset_minutes=0", headers=admin_headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total_ai_requests"] == 2
    assert data["requests_yesterday"] == 1
    assert data["requests_today"] == 1
    assert data["error_rate_today"] == 100
    assert data["activity"][-2]["requests"] == 1
    assert data["activity"][-1]["errors"] == 1
    assert data["usage"][0]["requests"] == 2

    shifted = client.get("/v1/dashboard/stats?utc_offset_minutes=-60", headers=admin_headers)
    assert shifted.status_code == 200, shifted.text
    assert shifted.json()["requests_yesterday"] == 1
    assert shifted.json()["requests_today"] == 0


def test_model_catalog_keeps_existing_models_and_adds_cheap_openrouter_options(
    client: TestClient, admin_headers: dict
):
    response = client.get("/v1/models", headers=admin_headers)
    assert response.status_code == 200, response.text
    model_ids = {item["id"] for item in response.json()}
    assert "openrouter:google/gemini-2.5-flash-lite" in model_ids
    assert "gigachat:GigaChat-2" in model_ids
    assert "deepseek:deepseek-flash" in model_ids
    assert "openrouter:deepseek/deepseek-v4-flash-0731" not in model_ids
    assert "openrouter:qwen/qwen3.8-flash" in model_ids


def test_legacy_deepseek_mode_id_is_presented_as_official(client: TestClient, admin_headers: dict):
    created = client.post(
        "/v1/modes",
        headers=admin_headers,
        json={"name": "Legacy DeepSeek", "response_model_id": "openrouter:deepseek/deepseek-v4-flash-0731"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["response_model_id"] == "deepseek:deepseek-flash"
    listed = client.get("/v1/modes", headers=admin_headers).json()
    assert [item["response_model_id"] for item in listed if item["name"] == "Legacy DeepSeek"] == [
        "deepseek:deepseek-flash"
    ]


def test_chat_creation_is_idempotent_for_a_client_request(client: TestClient, admin_headers: dict, mode: dict):
    request = {"mode_id": mode["id"], "client_request_id": "same-chat-request"}

    first = client.post("/v1/chats", headers=admin_headers, json=request)
    repeated = client.post("/v1/chats", headers=admin_headers, json=request)

    assert first.status_code == 201, first.text
    assert repeated.status_code == 201, repeated.text
    assert first.json()["id"] == repeated.json()["id"]
    chats = client.get("/v1/chats", headers=admin_headers).json()
    assert [chat["id"] for chat in chats] == [first.json()["id"]]


def test_quick_chat_creation_is_idempotent_for_a_client_request(client: TestClient, admin_headers: dict):
    request = {"client_request_id": "same-quick-request"}

    first = client.post("/v1/chats/quick", headers=admin_headers, json=request)
    repeated = client.post("/v1/chats/quick", headers=admin_headers, json=request)

    assert first.status_code == 201, first.text
    assert repeated.status_code == 201, repeated.text
    assert first.json()["id"] == repeated.json()["id"]


def test_fallback_ticket_and_message_sync_are_idempotent(
    client: TestClient, admin_headers: dict, mode: dict
):
    ticket = client.get("/v1/devices/self/fallback-ticket", headers=admin_headers)
    assert ticket.status_code == 200, ticket.text
    assert ticket.json()["ticket"]

    chat = client.post(
        "/v1/chats",
        headers=admin_headers,
        json={"mode_id": mode["id"], "client_request_id": "fallback-chat"},
    ).json()
    payload = {
        "request_id": "fallback-turn-1",
        "user_text": "Продолжи объяснение",
        "assistant_text": "Резервный ответ",
    }
    first = client.post(f"/v1/chats/{chat['id']}/fallback-messages", headers=admin_headers, json=payload)
    repeated = client.post(f"/v1/chats/{chat['id']}/fallback-messages", headers=admin_headers, json=payload)

    assert first.json() == {"status": "synced"}
    assert repeated.json() == {"status": "already_synced"}
    messages = client.get(f"/v1/chats/{chat['id']}/messages", headers=admin_headers).json()
    assert [(item["role"], item["content"]) for item in messages] == [
        ("user", "Продолжи объяснение"),
        ("assistant", "Резервный ответ"),
    ]


def test_admin_pairing_and_revocation(client: TestClient, admin: dict, admin_headers: dict):
    pairing = client.post("/v1/devices/pairing-codes", headers=admin_headers)
    assert pairing.status_code == 201, pairing.text

    watch = client.post(
        "/v1/devices/enroll",
        json={"name": "Xiaomi Watch 2", "kind": "WATCH", "code": pairing.json()["code"]},
    )
    assert watch.status_code == 200, watch.text
    watch_token = watch.json()["token"]

    devices = client.get("/v1/devices", headers=admin_headers)
    assert devices.status_code == 200
    assert {item["kind"] for item in devices.json()} == {"PHONE", "WATCH"}

    revoked = client.delete(f"/v1/devices/{watch.json()['device_id']}", headers=admin_headers)
    assert revoked.status_code == 204
    assert client.get(
        "/v1/modes", headers={"Authorization": f"Bearer {watch_token}"}
    ).status_code == 401


def test_device_address_and_removed_record_keep_audit_row(
    client: TestClient, admin: dict, admin_headers: dict,
):
    code = client.post("/v1/devices/pairing-codes", headers=admin_headers).json()["code"]
    enrolled = client.post(
        "/v1/devices/enroll",
        json={"name": "Xiaomi Watch 2", "kind": "WATCH", "code": code},
        headers={
            "X-Forwarded-For": "1.1.1.1, 8.8.8.8, 10.0.0.2",
            "User-Agent": "WristMind-Wear/1",
        },
    )
    assert enrolled.status_code == 200, enrolled.text
    device_id = enrolled.json()["device_id"]
    devices = client.get("/v1/devices", headers=admin_headers).json()
    watch = next(item for item in devices if item["id"] == device_id)
    assert watch["enrolled_ip"] == "8.8.8.8"
    assert watch["last_ip"] == "8.8.8.8"
    assert watch["user_agent"] == "WristMind-Wear/1"

    endpoint = f"/v1/devices/{device_id}/record"
    assert client.delete(endpoint, headers=admin_headers).status_code == 409
    assert client.delete(f"/v1/devices/{device_id}", headers=admin_headers).status_code == 204
    assert all(item["id"] != device_id for item in client.get("/v1/devices", headers=admin_headers).json())
    assert client.delete(endpoint, headers=admin_headers).status_code == 404
    assert client.delete(f"/v1/devices/{admin['device_id']}/record", headers=admin_headers).status_code == 409

    async def audit_row_exists() -> bool:
        async with SessionFactory() as session:
            row = await session.get(Device, device_id)
            return row is not None and row.revoked_at is not None and row.removed_at is not None

    assert asyncio.run(audit_row_exists())


def test_pairing_code_request_is_idempotent_after_lost_response(
    client: TestClient, admin_headers: dict
):
    request = {"client_request_id": "pairing-request-after-lost-response"}

    first = client.post("/v1/devices/pairing-codes", headers=admin_headers, json=request)
    repeated = client.post("/v1/devices/pairing-codes", headers=admin_headers, json=request)

    assert first.status_code == 201, first.text
    assert repeated.status_code == 201, repeated.text
    assert repeated.json() == first.json()


def test_watch_can_revoke_its_own_token(client: TestClient, admin_headers: dict):
    pairing = client.post("/v1/devices/pairing-codes", headers=admin_headers)
    watch = client.post(
        "/v1/devices/enroll",
        json={"name": "Xiaomi Watch 2", "kind": "WATCH", "code": pairing.json()["code"]},
    )
    token = watch.json()["token"]

    revoked = client.delete("/v1/devices/self", headers={"Authorization": f"Bearer {token}"})
    assert revoked.status_code == 204
    assert client.get("/v1/modes", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_watch_can_register_and_replace_its_push_token(client: TestClient, admin_headers: dict):
    pairing = client.post("/v1/devices/pairing-codes", headers=admin_headers)
    watch = client.post(
        "/v1/devices/enroll",
        json={"name": "Xiaomi Watch 2", "kind": "WATCH", "code": pairing.json()["code"]},
    )
    headers = {"Authorization": f"Bearer {watch.json()['token']}"}
    first = "a" * 32
    second = "b" * 32

    assert client.put("/v1/devices/self/push-token", headers=headers, json={"token": first}).status_code == 204
    assert client.put("/v1/devices/self/push-token", headers=headers, json={"token": second}).status_code == 204

    async def registered_token() -> str:
        async with SessionFactory() as session:
            value = await session.get(PushRegistration, watch.json()["device_id"])
            assert value is not None
            return value.token

    assert asyncio.run(registered_token()) == second


def test_web_panel_can_enroll_with_one_time_pairing_code(
    client: TestClient, admin_headers: dict
):
    pairing = client.post("/v1/devices/pairing-codes", headers=admin_headers)
    assert pairing.status_code == 201, pairing.text

    panel = client.post(
        "/v1/devices/admin/enroll-by-code",
        json={"name": "WristMind Web", "kind": "WEB", "code": pairing.json()["code"]},
    )
    assert panel.status_code == 200, panel.text
    assert panel.json()["is_admin"] is True

    reused = client.post(
        "/v1/devices/admin/enroll-by-code",
        json={"name": "WristMind Web 2", "kind": "WEB", "code": pairing.json()["code"]},
    )
    assert reused.status_code == 401


def test_only_single_owner_can_enroll_devices(client: TestClient, admin_headers: dict):
    assert client.get("/v1/users", headers=admin_headers).status_code == 404
    pairing = client.post("/v1/devices/pairing-codes", headers=admin_headers)
    assert pairing.status_code == 201, pairing.text
    watch = client.post("/v1/devices/enroll", json={"name": "Owner Watch", "kind": "WATCH", "code": pairing.json()["code"]})
    assert watch.status_code == 200, watch.text
    assert watch.json()["is_admin"] is False


def test_generic_enrollment_cannot_create_web_or_user_sessions(client: TestClient, admin_headers: dict):
    pairing = client.post("/v1/devices/pairing-codes", headers=admin_headers)
    assert pairing.status_code == 201
    rejected = client.post("/v1/devices/enroll", json={"name": "Panel", "kind": "WEB", "code": pairing.json()["code"]})
    assert rejected.status_code == 400
    assert client.post("/v1/users", headers=admin_headers, json={"name": "Another"}).status_code == 404


def test_chat_keeps_immutable_mode_and_survives_mode_delete(
    client: TestClient, admin_headers: dict, mode: dict
):
    chat = client.post(
        "/v1/chats",
        headers=admin_headers,
        json={"mode_id": mode["id"], "title": "Дроби"},
    )
    assert chat.status_code == 201, chat.text
    assert chat.json()["mode_id"] == mode["id"]

    switched = client.patch(
        f"/v1/chats/{chat.json()['id']}",
        headers=admin_headers,
        json={"title": "Новая тема", "mode_id": "forbidden"},
    )
    assert switched.status_code == 200
    assert switched.json()["mode_id"] == mode["id"]

    assert client.delete(f"/v1/modes/{mode['id']}", headers=admin_headers).status_code == 204
    chats = client.get("/v1/chats", headers=admin_headers)
    assert chats.status_code == 200
    assert chats.json()[0]["mode_id"] == mode["id"]
    assert chats.json()[0]["mode_deleted"] is True


def test_quick_chat_uses_built_in_universal_mode_and_can_be_deleted(
    client: TestClient, admin_headers: dict
):
    created = client.post("/v1/chats/quick", headers=admin_headers)
    assert created.status_code == 201, created.text
    chat = created.json()
    assert chat["title"] == "Быстрый чат"
    assert chat["mode_name"] == "Быстрый чат"

    modes = client.get("/v1/modes", headers=admin_headers)
    assert modes.status_code == 200
    assert all(item["name"] != "Быстрый чат" for item in modes.json())

    deleted = client.delete(f"/v1/chats/{chat['id']}", headers=admin_headers)
    assert deleted.status_code == 204
    assert all(item["id"] != chat["id"] for item in client.get("/v1/chats", headers=admin_headers).json())


def test_paired_watch_can_soft_delete_a_chat(client: TestClient, admin_headers: dict, mode: dict):
    chat = client.post(
        "/v1/chats",
        headers=admin_headers,
        json={"mode_id": mode["id"], "title": "Удалить с часов"},
    ).json()
    pairing = client.post("/v1/devices/pairing-codes", headers=admin_headers)
    watch = client.post(
        "/v1/devices/enroll",
        json={"name": "Xiaomi Watch 2", "kind": "WATCH", "code": pairing.json()["code"]},
    )
    headers = {"Authorization": f"Bearer {watch.json()['token']}"}

    assert client.delete(f"/v1/chats/{chat['id']}", headers=headers).status_code == 204
    assert all(item["id"] != chat["id"] for item in client.get("/v1/chats", headers=admin_headers).json())


def test_message_request_is_idempotent(
    client: TestClient, admin_headers: dict, mode: dict
):
    chat = client.post(
        "/v1/chats", headers=admin_headers, json={"mode_id": mode["id"]}
    ).json()
    body = {"client_request_id": "request-1", "text": "Сколько будет 2 + 2?"}
    first = client.post(f"/v1/chats/{chat['id']}/messages", headers=admin_headers, json=body)
    second = client.post(f"/v1/chats/{chat['id']}/messages", headers=admin_headers, json=body)
    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text
    assert first.json()["id"] == second.json()["id"]

    messages = client.get(f"/v1/chats/{chat['id']}/messages", headers=admin_headers)
    assert [item["role"] for item in messages.json()] == ["user", "assistant"]


def test_message_request_is_idempotent_across_watch_and_companion_tokens(
    client: TestClient, admin_headers: dict, mode: dict
):
    chat = client.post(
        "/v1/chats", headers=admin_headers, json={"mode_id": mode["id"]}
    ).json()
    companion = client.post(
        "/v1/devices/admin/enroll",
        headers={"X-WristMind-Bootstrap": "test-bootstrap"},
        json={"name": "Test companion", "kind": "PHONE"},
    )
    assert companion.status_code == 200, companion.text
    companion_headers = {"Authorization": f"Bearer {companion.json()['token']}"}
    body = {"client_request_id": "cross-device-request", "text": "Повторный вопрос"}

    first = client.post(f"/v1/chats/{chat['id']}/messages", headers=admin_headers, json=body)
    second = client.post(f"/v1/chats/{chat['id']}/messages", headers=companion_headers, json=body)

    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text
    assert first.json()["id"] == second.json()["id"]
    messages = client.get(f"/v1/chats/{chat['id']}/messages", headers=admin_headers)
    assert [item["role"] for item in messages.json()] == ["user", "assistant"]


def test_message_history_limit_returns_the_newest_messages_in_chat_order(
    client: TestClient, admin_headers: dict, mode: dict
):
    chat = client.post(
        "/v1/chats", headers=admin_headers, json={"mode_id": mode["id"]}
    ).json()
    for index in range(3):
        response = client.post(
            f"/v1/chats/{chat['id']}/messages",
            headers=admin_headers,
            json={"client_request_id": f"history-limit-{index}", "text": f"Вопрос {index}"},
        )
        assert response.status_code == 202, response.text

    messages = client.get(
        f"/v1/chats/{chat['id']}/messages?limit=4", headers=admin_headers
    )
    assert messages.status_code == 200, messages.text
    assert [item["role"] for item in messages.json()] == ["user", "assistant", "user", "assistant"]
    assert [item["content"] for item in messages.json() if item["role"] == "user"] == [
        "Вопрос 1",
        "Вопрос 2",
    ]


def test_fallback_stt_does_not_keep_audio(
    client: TestClient, admin_headers: dict
):
    response = client.post(
        "/v1/stt",
        headers=admin_headers,
        files={"file": ("question.webm", b"test-audio", "audio/webm")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["text"] == "Тестовая расшифровка WristMind"
    assert response.json()["language"] == "ru"


def test_mode_description_and_settings_can_be_updated(
    client: TestClient, admin_headers: dict, mode: dict
):
    response = client.patch(
        f"/v1/modes/{mode['id']}",
        headers=admin_headers,
        json={
            "name": "Алгебра",
            "description": "Решение школьных задач и проверка вычислений.",
            "response_model_id": "openrouter:google/gemini-2.5-flash-lite",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Алгебра"
    assert response.json()["description"] == "Решение школьных задач и проверка вычислений."


def test_default_model_and_response_settings_are_persisted(
    client: TestClient, admin_headers: dict[str, str]
):
    blocked = client.put(
        "/v1/settings", headers=admin_headers,
        json={"source_intent_prompt": "Тестовый промпт определения намерения пользователя."},
    )
    assert blocked.status_code == 403
    enabled = client.put("/v1/settings", headers=admin_headers, json={"developer_mode": True})
    assert enabled.status_code == 200
    assert enabled.json()["developer_mode"] is True
    updated = client.put(
        "/v1/settings",
        headers=admin_headers,
        json={
            "default_model_id": "gigachat:GigaChat-2",
            "stream_responses": False,
            "retention_days": 30,
            "source_intent_prompt": "Тестовый промпт определения намерения пользователя.",
            "source_candidate_prompt": "Тестовый промпт проверки найденного материала на соответствие.",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["default_model_id"] == "gigachat:GigaChat-2"
    assert updated.json()["stream_responses"] is False
    assert updated.json()["retention_days"] == 30
    assert updated.json()["source_intent_prompt"].startswith("Тестовый промпт")
    assert updated.json()["source_candidate_prompt"].startswith("Тестовый промпт")

    reread = client.get("/v1/settings", headers=admin_headers)
    assert reread.status_code == 200, reread.text
    assert reread.json()["default_model_id"] == "gigachat:GigaChat-2"
    assert reread.json()["stream_responses"] is False
    assert reread.json()["retention_days"] == 30
    assert reread.json()["source_intent_prompt"] == updated.json()["source_intent_prompt"]
    assert reread.json()["source_candidate_prompt"] == updated.json()["source_candidate_prompt"]


def test_internal_prompts_require_developer_mode_but_mode_prompts_do_not(
    client: TestClient, admin_headers: dict[str, str], mode: dict,
):
    assert client.get("/v1/prompts", headers=admin_headers).status_code == 403
    assert client.put(
        "/v1/prompts/chat_title", headers=admin_headers, json={"text": "Новое название"},
    ).status_code == 403
    mode_update = client.patch(
        f"/v1/modes/{mode['id']}", headers=admin_headers,
        json={"system_prompt": "Промпт режима доступен всегда."},
    )
    assert mode_update.status_code == 200, mode_update.text
    assert mode_update.json()["system_prompt"] == "Промпт режима доступен всегда."

    assert client.put(
        "/v1/settings", headers=admin_headers, json={"developer_mode": True},
    ).status_code == 200
    records = client.get("/v1/prompts", headers=admin_headers)
    assert records.status_code == 200, records.text
    title = next(item for item in records.json() if item["key"] == "chat_title")
    assert title["text"] == title["default_text"]
    changed = client.put(
        "/v1/prompts/chat_title", headers=admin_headers, json={"text": "Новая тема чата"},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["customized"] is True
    router = next(item for item in records.json() if item["key"] == "choose_retrieval_route")
    assert client.put(
        "/v1/prompts/choose_retrieval_route", headers=admin_headers,
        json={"text": router["text"].replace("{{original_request}}", "")},
    ).status_code == 422
    assert client.put(
        "/v1/settings", headers=admin_headers, json={"developer_mode": False},
    ).status_code == 200
    assert client.get("/v1/prompts", headers=admin_headers).status_code == 403
    assert client.patch(
        f"/v1/modes/{mode['id']}", headers=admin_headers,
        json={"system_prompt": "Другой промпт режима."},
    ).status_code == 200


def test_mode_watch_visibility_is_reversible_without_deleting_chats(
    client: TestClient, admin_headers: dict, mode: dict
):
    chat = client.post(
        "/v1/chats", headers=admin_headers, json={"mode_id": mode["id"]}
    )
    assert chat.status_code == 201, chat.text
    assert mode["hidden_on_watch"] is False

    hidden = client.patch(
        f"/v1/modes/{mode['id']}", headers=admin_headers, json={"hidden_on_watch": True}
    )
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["hidden_on_watch"] is True
    web = client.post(
        "/v1/devices/admin/enroll",
        headers={"X-WristMind-Bootstrap": "test-bootstrap"},
        json={"name": "WristMind Web", "kind": "WEB"},
    )
    assert web.status_code == 200, web.text
    web_headers = {"Authorization": f"Bearer {web.json()['token']}"}
    listed = client.get("/v1/modes", headers=web_headers).json()
    assert next(item for item in listed if item["id"] == mode["id"])["hidden_on_watch"] is True
    pairing = client.post("/v1/devices/pairing-codes", headers=admin_headers)
    watch = client.post(
        "/v1/devices/enroll",
        json={"name": "watch", "kind": "WATCH", "code": pairing.json()["code"]},
    )
    watch_headers = {"Authorization": f"Bearer {watch.json()['token']}"}
    assert all(item["id"] != mode["id"] for item in client.get("/v1/modes", headers=watch_headers).json())
    assert all(item["id"] != mode["id"] for item in client.get("/v1/modes", headers=admin_headers).json())
    chats = client.get("/v1/chats", headers=admin_headers).json()
    assert next(item for item in chats if item["id"] == chat.json()["id"])["mode_deleted"] is False

    shown = client.patch(
        f"/v1/modes/{mode['id']}", headers=admin_headers, json={"hidden_on_watch": False}
    )
    assert shown.status_code == 200, shown.text
    assert shown.json()["hidden_on_watch"] is False
    assert any(item["id"] == mode["id"] for item in client.get("/v1/modes", headers=watch_headers).json())


def test_source_detail_and_reprocess_clear_previous_chunks(
    client: TestClient, admin_headers: dict, mode: dict
):
    uploaded = client.post(
        "/v1/knowledge",
        headers=admin_headers,
        data={
            "mode_id": mode["id"],
            "processing_mode": "VISION",
            "client_request_id": "upload-source-detail",
            "title": "Задача с фотографии",
        },
        files={"file": ("task.png", b"fake-image-content", "image/png")},
    )
    assert uploaded.status_code == 202, uploaded.text
    source = client.get("/v1/knowledge", headers=admin_headers).json()[0]

    async def prepare_ready_source() -> None:
        async with SessionFactory() as session:
            stored = await session.scalar(
                select(KnowledgeSource).where(KnowledgeSource.id == source["id"])
            )
            assert stored is not None
            stored.status = "ready"
            stored.page_count = 1
            stored.chunk_count = 1
            stored.token_count = 12
            session.add(
                KnowledgeChunk(
                    source_id=stored.id,
                    ordinal=0,
                    kind="vision",
                    content="На изображении показано уравнение: 2x + 4 = 10.",
                    token_count=12,
                    embedding=None,
                )
            )
            await session.commit()

    asyncio.run(prepare_ready_source())

    detail = client.get(f"/v1/knowledge/{source['id']}", headers=admin_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["chunks"][0]["kind"] == "vision"
    assert "2x + 4" in detail.json()["chunks"][0]["content"]
    # Sources created before page ranges were stored still open on the
    # correct page when they have exactly one chunk for each page.
    assert detail.json()["chunks"][0]["page_from"] == 1
    assert detail.json()["chunks"][0]["page_to"] == 1

    reprocessed = client.post(
        f"/v1/knowledge/{source['id']}/reprocess",
        headers=admin_headers,
        json={"client_request_id": "reprocess-source-detail"},
    )
    assert reprocessed.status_code == 202, reprocessed.text
    refreshed = client.get(f"/v1/knowledge/{source['id']}", headers=admin_headers).json()
    assert refreshed["status"] == "queued"
    assert refreshed["chunks"] == []
    assert refreshed["chunk_count"] == 0


def test_messages_expose_referenced_web_sources_for_diagnostics(
    client: TestClient, admin_headers: dict, mode: dict
):
    """The console reads this read-only audit trail; it never feeds retrieval."""
    chat = client.post(
        "/v1/chats", headers=admin_headers, json={"mode_id": mode["id"]}
    ).json()
    client.post(
        f"/v1/chats/{chat['id']}/messages",
        headers=admin_headers,
        json={"client_request_id": "ref-source-1", "text": "Найди текст", "web_search": True},
    )

    initial = client.get(f"/v1/chats/{chat['id']}/messages", headers=admin_headers).json()
    assistant_id = next(item["id"] for item in initial if item["role"] == "assistant")
    assert initial[0]["sources"] == []
    assert isinstance(initial[-1]["timings"], dict)

    async def seed() -> None:
        async with SessionFactory() as session:
            session.add(ReferencedWebSource(
                chat_id=chat["id"],
                message_id=assistant_id,
                url="https://example.test/text",
                title="Текст",
                snippet="фрагмент",
            ))
            await session.commit()

    asyncio.run(seed())

    refreshed = client.get(f"/v1/chats/{chat['id']}/messages", headers=admin_headers).json()
    assistant = next(item for item in refreshed if item["role"] == "assistant")
    assert [item["url"] for item in assistant["sources"]] == ["https://example.test/text"]
    assert assistant["sources"][0]["title"] == "Текст"
    # Only the message that actually used the page carries it.
    assert refreshed[0]["sources"] == []


def _chat(client: TestClient, admin_headers: dict, mode: dict) -> dict:
    return client.post("/v1/chats", headers=admin_headers, json={"mode_id": mode["id"]}).json()


def test_chat_sources_are_empty_for_a_new_chat(client: TestClient, admin_headers: dict, mode: dict):
    chat = _chat(client, admin_headers, mode)

    response = client.get(f"/v1/chats/{chat['id']}/sources", headers=admin_headers)

    assert response.status_code == 200, response.text
    assert response.json() == {"working": [], "referenced": []}


def test_working_source_text_is_full_and_scoped_to_its_chat(
    client: TestClient, admin_headers: dict, mode: dict, tmp_path,
):
    chat = _chat(client, admin_headers, mode)
    other_chat = _chat(client, admin_headers, mode)
    content = "Начало сказки.\n" + "Полный сохранённый текст. " * 100
    target = tmp_path / "saved-source.txt"
    target.write_text(content, encoding="utf-8")

    async def seed() -> str:
        async with SessionFactory() as session:
            source = KnowledgeSource(
                mode_id=mode["id"], chat_id=chat["id"], title="Колобок",
                filename="source.txt", media_type="text/plain", processing_mode="WEB",
                source_tier="working", status="ready", storage_path=str(target),
            )
            session.add(source)
            await session.commit()
            return source.id

    source_id = asyncio.run(seed())
    response = client.get(
        f"/v1/chats/{chat['id']}/sources/{source_id}/text", headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["content"] == content
    assert response.json()["character_count"] == len(content)
    assert client.get(
        f"/v1/chats/{other_chat['id']}/sources/{source_id}/text", headers=admin_headers,
    ).status_code == 404


def test_chat_sources_list_referenced_web_pages(client: TestClient, admin_headers: dict, mode: dict):
    chat = _chat(client, admin_headers, mode)

    async def seed() -> None:
        async with SessionFactory() as session:
            session.add(ReferencedWebSource(
                chat_id=chat["id"],
                url="https://example.test/kolobok",
                title="Колобок",
                snippet="фрагмент текста",
            ))
            await session.commit()

    asyncio.run(seed())

    payload = client.get(f"/v1/chats/{chat['id']}/sources", headers=admin_headers).json()
    assert payload["working"] == []
    assert [item["url"] for item in payload["referenced"]] == ["https://example.test/kolobok"]
    assert payload["referenced"][0]["title"] == "Колобок"


def test_working_source_is_not_repeated_among_the_web_finds(
    client: TestClient, admin_headers: dict, mode: dict
):
    chat = _chat(client, admin_headers, mode)
    shared_url = "https://example.test/kolobok"

    async def seed() -> None:
        async with SessionFactory() as session:
            session.add(KnowledgeSource(
                mode_id=mode["id"],
                chat_id=chat["id"],
                title="Колобок",
                filename="source.txt",
                media_type="text/plain",
                processing_mode="WEB",
                source_tier="working",
                source_kind="passage",
                origin_url=shared_url,
                origin_title="Колобок — Викитека",
                storage_path="/tmp/wm-test-source.txt",
                status="ready",
            ))
            session.add(ReferencedWebSource(
                chat_id=chat["id"], url=shared_url, title="Колобок", snippet="то же самое",
            ))
            session.add(ReferencedWebSource(
                chat_id=chat["id"], url="https://other.test/page", title="Другое", snippet="иное",
            ))
            await session.commit()

    asyncio.run(seed())

    payload = client.get(f"/v1/chats/{chat['id']}/sources", headers=admin_headers).json()
    assert [item["title"] for item in payload["working"]] == ["Колобок"]
    assert payload["working"][0]["origin_title"] == "Колобок — Викитека"
    # The promoted page is chat material, so it is not listed again as a find.
    assert [item["url"] for item in payload["referenced"]] == ["https://other.test/page"]


def test_chat_sources_never_leak_another_chats_material(
    client: TestClient, admin_headers: dict, mode: dict
):
    mine = _chat(client, admin_headers, mode)
    other = _chat(client, admin_headers, mode)

    async def seed() -> None:
        async with SessionFactory() as session:
            session.add(ReferencedWebSource(
                chat_id=other["id"], url="https://other.test/secret", title="Чужое", snippet="",
            ))
            await session.commit()

    asyncio.run(seed())

    payload = client.get(f"/v1/chats/{mine['id']}/sources", headers=admin_headers).json()
    assert payload == {"working": [], "referenced": []}


def test_chat_sources_distinguish_found_read_and_saved_without_duplicate_or_leak(
    client: TestClient, admin_headers: dict, mode: dict,
):
    chat = _chat(client, admin_headers, mode)
    other = _chat(client, admin_headers, mode)
    base = "https://example.test/"

    async def seed_found():
        async with SessionFactory() as session:
            for name in ("found", "read", "saved", "empty"):
                session.add(ReferencedWebSource(chat_id=chat["id"], url=base + name,
                                               title=name, snippet="Поисковый фрагмент"))
            # A read in a different chat must never upgrade this chat's link.
            session.add(RawWebSource(chat_id=other["id"], url=base + "found", title="Private",
                                     content="Чужой текст", content_hash="a" * 64))
            await session.commit()

    asyncio.run(seed_found())
    initial = client.get(f"/v1/chats/{chat['id']}/sources", headers=admin_headers).json()
    assert all(row["read_at"] is None and row["character_count"] == 0 for row in initial["referenced"])

    async def seed_reads():
        async with SessionFactory() as session:
            for name, content in (("read", "Полный текст страницы"), ("saved", "Сохранённый текст"),
                                  ("direct", "Текст после редиректа"), ("empty", "   ")):
                session.add(RawWebSource(chat_id=chat["id"], url=base + name, title=name,
                                         content=content, content_hash="b" * 64))
            session.add(KnowledgeSource(
                mode_id=mode["id"], chat_id=chat["id"], title="saved", filename="source.txt",
                media_type="text/plain", processing_mode="WEB", source_tier="working",
                origin_url=base + "saved", storage_path="/tmp/wm-test-source.txt", status="ready",
            ))
            await session.commit()

    asyncio.run(seed_reads())
    updated = client.get(f"/v1/chats/{chat['id']}/sources", headers=admin_headers).json()
    entries = {row["url"]: row for row in updated["referenced"]}
    assert entries[base + "found"]["read_at"] is None
    assert entries[base + "empty"]["read_at"] is None
    assert entries[base + "read"]["read_at"] is not None
    assert entries[base + "read"]["character_count"] == len("Полный текст страницы")
    assert entries[base + "direct"]["read_at"] is not None
    assert base + "saved" not in entries
    assert len(updated["working"]) == 1
    assert all("content" not in row for row in updated["referenced"])


def test_chat_pinning_is_persisted_without_renaming(client, admin_headers, mode):
    chat = client.post('/v1/chats', headers=admin_headers, json={'mode_id': mode['id'], 'title': 'Моя задача'}).json()
    path = f"/v1/chats/{chat['id']}"
    pinned = client.patch(path, headers=admin_headers, json={'pinned': True})
    assert pinned.status_code == 200, pinned.text
    assert pinned.json()['pinned'] is True
    assert pinned.json()['title'] == 'Моя задача'
    listed = next(c for c in client.get('/v1/chats', headers=admin_headers).json() if c['id'] == chat['id'])
    assert listed['pinned'] is True
    renamed = client.patch(path, headers=admin_headers, json={'title': ' Новое название '})
    assert renamed.json()['title'] == 'Новое название'
    assert renamed.json()['pinned'] is True
    unpinned = client.patch(path, headers=admin_headers, json={'pinned': False})
    assert unpinned.json()['pinned'] is False
    assert unpinned.json()['title'] == 'Новое название'
    assert client.patch(path, headers=admin_headers, json={'title': '   '}).status_code == 422


def test_existing_chat_survives_pinned_column_migration(client, admin_headers, mode):
    from sqlalchemy import text
    from wristmind_server import database

    chat = client.post('/v1/chats', headers=admin_headers, json={'mode_id': mode['id'], 'title': 'Старый чат'}).json()

    async def migrate_legacy_table():
        async with database.engine.begin() as connection:
            await connection.execute(text('ALTER TABLE chats DROP COLUMN pinned'))
        await database.init_database()
        await database.init_database()  # Startup migration is repeatable.

    asyncio.run(migrate_legacy_table())
    chats = client.get('/v1/chats', headers=admin_headers).json()
    restored = next(c for c in chats if c['id'] == chat['id'])
    assert restored['title'] == 'Старый чат'
    assert restored['pinned'] is False
