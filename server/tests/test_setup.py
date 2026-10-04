"""First-run setup endpoints: honest installation state and key handling."""

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from sqlalchemy import select

from wristmind_server import main as main_module
from wristmind_server.database import SessionFactory
from wristmind_server.db_models import Job


def test_fresh_install_requires_setup(client: TestClient):
    response = client.get("/v1/setup/status")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["database_ok"] is True
    assert body["first_run_completed"] is False
    assert body["instance_claimed"] is False
    assert body["setup_required"] is True
    assert body["admin_devices"] == 0
    assert body["active_modes"] == 0
    assert body["knowledge_sources"] == 0
    # The test environment runs with mock providers, so it can answer at once.
    assert body["provider_mode"] == "mock"
    assert body["provider_ready"] is True
    # Nothing secret may leak through an unauthenticated route.
    assert set(body) == {
        "first_run_completed",
        "instance_claimed",
        "admin_devices",
        "active_modes",
        "knowledge_sources",
        "database_ok",
        "provider_mode",
        "provider_ready",
        "providers_with_keys",
        "setup_required",
        "first_mode_id",
    }


def test_setup_status_flips_after_enrollment_and_work(
    client: TestClient, admin_headers: dict, mode: dict
):
    claimed = client.get("/v1/setup/status").json()
    assert claimed["instance_claimed"] is True
    assert claimed["setup_required"] is False
    assert claimed["admin_devices"] == 1
    assert claimed["active_modes"] == 1


def test_provider_check_validates_input(client: TestClient):
    assert (
        client.post(
            "/v1/setup/provider/check", json={"provider": "unknown", "api_key": "x" * 20}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/v1/setup/provider/check", json={"provider": "openrouter", "api_key": "short"}
        ).status_code
        == 422
    )


def test_provider_check_reports_rejection_without_network(
    client: TestClient, monkeypatch
):
    """A rejected key is reported as rejected; the candidate key is never stored."""
    import httpx

    from wristmind_server import providers as providers_module

    async def fake_stream(self, model_id, messages, **kwargs):  # noqa: ANN001
        request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
        response = httpx.Response(401, request=request)
        raise providers_module.ProviderError("rejected") from httpx.HTTPStatusError(
            "rejected", request=request, response=response
        )
        yield  # keeps this an async generator, like the real implementation

    monkeypatch.setattr(providers_module.ProviderRouter, "stream_answer", fake_stream)

    response = client.post(
        "/v1/setup/provider/check",
        json={"provider": "openrouter", "api_key": "sk-or-v1-not-a-real-key"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is False
    assert body["provider"] == "openrouter"
    assert "отклонён" in body["message"]


def test_provider_check_reports_success(client: TestClient, monkeypatch):
    from wristmind_server import providers as providers_module

    async def fake_stream(self, model_id, messages, **kwargs):  # noqa: ANN001
        yield "pong"

    monkeypatch.setattr(providers_module.ProviderRouter, "stream_answer", fake_stream)

    body = client.post(
        "/v1/setup/provider/check",
        json={"provider": "deepseek", "api_key": "sk-deepseek-candidate"},
    ).json()
    assert body["ok"] is True
    assert body["latency_ms"] is not None


def test_provider_save_writes_env_and_keeps_comments(client: TestClient, tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# keep me\nPOSTGRES_PASSWORD=secret\nWRISTMIND_MOCK_PROVIDERS=true\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(main_module, "_ENV_FILE_PATH", env_file)
    # No Docker socket in tests: the route must degrade, not fail.
    monkeypatch.setattr(
        main_module, "_restart_self_container", lambda: _false_awaitable()
    )

    response = client.post(
        "/v1/setup/provider",
        json={"provider": "deepseek", "api_key": "sk-deepseek-value"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["restart_required"] is True
    assert body["env_file"] == str(env_file)

    text = env_file.read_text(encoding="utf-8")
    assert "# keep me" in text
    assert "POSTGRES_PASSWORD=secret" in text
    assert "WRISTMIND_DEEPSEEK_API_KEY=sk-deepseek-value" in text
    # Saving a key must also make sure a real provider is used.
    assert "WRISTMIND_MOCK_PROVIDERS=false" in text
    assert text.count("WRISTMIND_DEEPSEEK_API_KEY") == 1


def test_provider_save_is_idempotent_for_existing_line(client: TestClient, tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("WRISTMIND_OPENROUTER_API_KEY=old\n", encoding="utf-8")
    monkeypatch.setattr(main_module, "_ENV_FILE_PATH", env_file)
    monkeypatch.setattr(
        main_module, "_restart_self_container", lambda: _false_awaitable()
    )

    client.post(
        "/v1/setup/provider",
        json={"provider": "openrouter", "api_key": "sk-or-v1-new"},
    )
    client.post(
        "/v1/setup/provider",
        json={"provider": "openrouter", "api_key": "sk-or-v1-new"},
    )
    text = env_file.read_text(encoding="utf-8")
    assert text.count("WRISTMIND_OPENROUTER_API_KEY") == 1
    assert "old" not in text


async def _false_awaitable() -> bool:
    return False


def test_setup_complete_requires_auth_and_is_idempotent(client: TestClient, admin_headers: dict):
    assert client.post("/v1/setup/complete").status_code in {401, 403}

    assert client.post("/v1/setup/complete", headers=admin_headers).status_code == 204
    assert client.get("/v1/setup/status").json()["first_run_completed"] is True

    # Running the wizard again must not fail.
    assert client.post("/v1/setup/complete", headers=admin_headers).status_code == 204
    assert client.get("/v1/setup/status").json()["first_run_completed"] is True


def test_setup_first_chat_is_idempotent(client: TestClient, admin_headers: dict):
    first = client.post("/v1/setup/first-chat", headers=admin_headers)
    assert first.status_code == 202, first.text
    second = client.post("/v1/setup/first-chat", headers=admin_headers)
    assert second.status_code == 202, second.text

    # Reusing the same mode and chat is what keeps the wizard free of duplicates.
    assert first.json()["mode_id"] == second.json()["mode_id"]
    assert first.json()["chat_id"] == second.json()["chat_id"]

    status = client.get("/v1/setup/status").json()
    assert status["active_modes"] == 1
    assert status["first_mode_id"] == first.json()["mode_id"]


def test_setup_first_chat_requires_auth(client: TestClient):
    assert client.post("/v1/setup/first-chat").status_code in {401, 403}


def test_first_question_flows_through_the_created_chat(
    client: TestClient, admin_headers: dict
):
    """The created chat is a real one: a question is accepted and answered."""
    created = client.post("/v1/setup/first-chat", headers=admin_headers).json()
    queued = client.post(
        f"/v1/chats/{created['chat_id']}/messages",
        headers=admin_headers,
        json={"client_request_id": "setup-first-question", "text": "Скажи привет"},
    )
    assert queued.status_code == 202, queued.text
    job_id = queued.json()["id"]

    asyncio.run(_run_worker_until(job_id))

    messages = client.get(
        f"/v1/chats/{created['chat_id']}/messages", headers=admin_headers
    ).json()
    assistant = [item for item in messages if item["role"] == "assistant"]
    assert assistant, messages
    assert assistant[-1]["content"].strip()


async def _run_worker_until(job_id: str) -> None:
    """Drive the real worker once, the way the worker test module does."""
    import wristmind_server.worker as worker_module

    async with SessionFactory() as session:
        job = await session.get(Job, job_id)
        assert job is not None
    await worker_module.process_next_job()
