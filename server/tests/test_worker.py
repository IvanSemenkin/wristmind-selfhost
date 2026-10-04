import asyncio

from fastapi.testclient import TestClient
from sqlalchemy import select, update

import wristmind_server.worker as worker
from wristmind_server.database import SessionFactory
from wristmind_server.db_models import Chat, Job, JobEvent
from wristmind_server.web_search import WebSearchResult
from wristmind_server.worker import process_next_job
from wristmind_server.identity import CORE_IDENTITY_PROMPT


def test_running_answer_task_stops_after_cancel_status(client: TestClient, admin_headers: dict, mode: dict):
    chat = client.post("/v1/chats", headers=admin_headers, json={"mode_id": mode["id"]}).json()
    job = client.post(
        f"/v1/chats/{chat['id']}/messages", headers=admin_headers,
        json={"client_request_id": "cancel-worker-1", "text": "Длинный ответ"},
    ).json()

    async def verify() -> None:
        async with SessionFactory() as session:
            await session.execute(update(Job).where(Job.id == job["id"]).values(status="running"))
            await session.commit()
        task = asyncio.create_task(asyncio.sleep(10))
        watcher = asyncio.create_task(worker._watch_answer_cancellation(job["id"], task))
        async with SessionFactory() as session:
            await session.execute(update(Job).where(Job.id == job["id"]).values(status="cancelled"))
            await session.commit()
        try:
            await asyncio.wait_for(task, timeout=2)
            assert False, "cancelled answer task continued"
        except asyncio.CancelledError:
            pass
        await watcher

    asyncio.run(verify())


def test_answer_job_streams_and_persists_result(
    client: TestClient, admin_headers: dict, mode: dict, monkeypatch,
):
    answer_system_messages: list[str] = []
    original_stream_answer = worker.providers.stream_answer

    async def record_stream(model_id, messages, **kwargs):
        for item in messages:
            if item["role"] == "system" and CORE_IDENTITY_PROMPT in item["content"]:
                answer_system_messages.append(item["content"])
        async for chunk in original_stream_answer(model_id, messages, **kwargs):
            yield chunk

    monkeypatch.setattr(worker.providers, "stream_answer", record_stream)
    chat = client.post(
        "/v1/chats", headers=admin_headers, json={"mode_id": mode["id"]}
    ).json()
    job = client.post(
        f"/v1/chats/{chat['id']}/messages",
        headers=admin_headers,
        json={"client_request_id": "worker-1", "text": "Объясни теорему Пифагора"},
    ).json()

    assert asyncio.run(process_next_job()) is True

    status = client.get(f"/v1/jobs/{job['id']}", headers=admin_headers)
    assert status.status_code == 200
    assert status.json()["status"] == "complete"
    assert answer_system_messages
    assert all(message.endswith(CORE_IDENTITY_PROMPT) for message in answer_system_messages)

    messages = client.get(f"/v1/chats/{chat['id']}/messages", headers=admin_headers).json()
    assert messages[-1]["status"] == "complete"
    assert messages[-1]["content"]
    assert messages[-1]["timings"]["total_ms"] >= 0

    events = client.get(f"/v1/jobs/{job['id']}/events?after=0", headers=admin_headers)
    assert events.status_code == 200
    assert events.headers["cache-control"] == "no-cache, no-transform"
    assert events.headers["x-accel-buffering"] == "no"
    assert "event: delta" in events.text
    assert "event: complete" in events.text

    async def progress_states() -> list[str]:
        async with SessionFactory() as session:
            rows = (await session.scalars(
                select(JobEvent)
                .where(JobEvent.job_id == job["id"], JobEvent.event == "state")
                .order_by(JobEvent.id)
            )).all()
            return [row.data["state"] for row in rows]

    states = asyncio.run(progress_states())
    assert states.index("context") < states.index("routing") < states.index("generating")
    assert "searching" not in states


def test_web_progress_marks_the_actual_search_pass(
    client: TestClient, admin_headers: dict, mode: dict, monkeypatch
):
    async def route(*_args, **_kwargs):
        return worker.RetrievalRoute(
            retrieval="web", reasoning="low", verification=False,
            freshness_required=True, task_type="current_fact",
        )

    async def search(*_args, **_kwargs):
        return [WebSearchResult("Официальная документация", "https://example.org/python", "Версия")]

    monkeypatch.setattr(worker, "choose_retrieval_route", route)
    monkeypatch.setattr(worker, "search_web", search)
    chat = client.post("/v1/chats", headers=admin_headers, json={"mode_id": mode["id"]}).json()
    job = client.post(
        f"/v1/chats/{chat['id']}/messages", headers=admin_headers,
        json={"client_request_id": "progress-web-1", "text": "Какая сейчас версия Python?"},
    ).json()

    assert asyncio.run(process_next_job()) is True

    async def states() -> list[dict]:
        async with SessionFactory() as session:
            rows = (await session.scalars(
                select(JobEvent)
                .where(JobEvent.job_id == job["id"], JobEvent.event == "state")
                .order_by(JobEvent.id)
            )).all()
            return [row.data for row in rows]

    progress = asyncio.run(states())
    assert any(item.get("state") == "searching" and item.get("pass") == 1 for item in progress)
    assert not any(item.get("state") == "reviewing_sources" for item in progress)


def test_first_message_generates_one_background_chat_title(
    client: TestClient, admin_headers: dict, mode: dict
):
    chat = client.post("/v1/chats", headers=admin_headers, json={"mode_id": mode["id"]}).json()
    client.post(
        f"/v1/chats/{chat['id']}/messages",
        headers=admin_headers,
        json={"client_request_id": "title-1", "text": "Реши квадратное уравнение"},
    )

    # ANSWER has priority over CHAT_TITLE, so naming cannot postpone the response.
    assert asyncio.run(process_next_job()) is True
    assert asyncio.run(process_next_job()) is True

    async def title_state() -> tuple[str, list[str]]:
        async with SessionFactory() as session:
            saved_chat = await session.get(Chat, chat["id"])
            jobs = list(await session.scalars(select(Job.kind).where(Job.payload["chat_id"].as_string() == chat["id"])))
            return saved_chat.title if saved_chat else "", jobs

    title, job_kinds = asyncio.run(title_state())
    assert title != "Новый чат"
    assert job_kinds.count("CHAT_TITLE") == 1

    client.post(
        f"/v1/chats/{chat['id']}/messages",
        headers=admin_headers,
        json={"client_request_id": "title-2", "text": "А теперь проверь ответ"},
    )
    _, job_kinds = asyncio.run(title_state())
    assert job_kinds.count("CHAT_TITLE") == 1


def test_requested_web_search_is_saved_in_answer_job(client: TestClient, admin_headers: dict, mode: dict):
    chat = client.post("/v1/chats", headers=admin_headers, json={"mode_id": mode["id"]}).json()
    job = client.post(
        f"/v1/chats/{chat['id']}/messages",
        headers=admin_headers,
        json={"client_request_id": "web-search-1", "text": "Что нового?", "web_search": True},
    ).json()

    async def payload() -> dict:
        async with SessionFactory() as session:
            saved = await session.get(Job, job["id"])
            return saved.payload if saved else {}

    assert asyncio.run(payload())["web_search"] is True


def test_research_mode_does_not_force_web_in_answer_job(client: TestClient, admin_headers: dict, mode: dict):
    chat = client.post("/v1/chats", headers=admin_headers, json={"mode_id": mode["id"]}).json()
    job = client.post(
        f"/v1/chats/{chat['id']}/messages",
        headers=admin_headers,
        json={"client_request_id": "research-1", "text": "Сравни две теории", "research_mode": True},
    ).json()

    async def payload() -> dict:
        async with SessionFactory() as session:
            saved = await session.get(Job, job["id"])
            return saved.payload if saved else {}

    saved = asyncio.run(payload())
    assert saved["web_search"] is False
    assert saved["web_research"] is False
    assert saved["research_mode"] is True


def _web_route(retrieval: str, task_type: str) -> "worker.RetrievalRoute":
    return worker.RetrievalRoute(
        retrieval=retrieval, reasoning="low", verification=False,
        freshness_required=True, task_type=task_type,
    )


def test_web_route_never_calls_the_model_request_anchor(
    client: TestClient, admin_headers: dict, mode: dict, monkeypatch
):
    """route=web must use the deterministic anchor, even for a non-trivial ask."""
    anchor_calls: list[str] = []

    async def route(*_args, **_kwargs):
        return _web_route("web", "current_fact")

    async def search(*_args, **_kwargs):
        return [WebSearchResult("Документация", "https://example.org/doc", "Версия")]

    async def anchor(_model_id, text):
        anchor_calls.append(text)
        return worker.lightweight_request_anchor(text)

    monkeypatch.setattr(worker, "choose_retrieval_route", route)
    monkeypatch.setattr(worker, "search_web", search)
    monkeypatch.setattr(worker, "build_request_anchor", anchor)

    chat = client.post("/v1/chats", headers=admin_headers, json={"mode_id": mode["id"]}).json()
    # "или" keeps this out of is_simple_fresh_fact, so it used to need the model.
    client.post(
        f"/v1/chats/{chat['id']}/messages", headers=admin_headers,
        json={"client_request_id": "anchor-web-1", "text": "Версия Python или Node сейчас?"},
    )
    assert asyncio.run(process_next_job()) is True

    messages = client.get(f"/v1/chats/{chat['id']}/messages", headers=admin_headers).json()
    assert anchor_calls == []
    assert messages[-1]["timings"]["request_anchor"]["mode"] == "deterministic"


def test_deep_web_route_still_builds_the_model_request_anchor(
    client: TestClient, admin_headers: dict, mode: dict, monkeypatch
):
    """The deep_web agent loop keeps its model-built frame."""
    anchor_calls: list[str] = []

    async def route(*_args, **_kwargs):
        return _web_route("deep_web", "write_from_source")

    async def search(*_args, **_kwargs):
        return [WebSearchResult("Документация", "https://example.org/doc", "Версия")]

    async def query(*_args, **_kwargs):
        return "python version"

    async def action(*_args, **_kwargs):
        return worker.WebAgentAction(action="answer")

    async def anchor(_model_id, text):
        anchor_calls.append(text)
        return worker.lightweight_request_anchor(text)

    monkeypatch.setattr(worker, "choose_retrieval_route", route)
    monkeypatch.setattr(worker, "search_web", search)
    monkeypatch.setattr(worker, "choose_contextual_search_query", query)
    monkeypatch.setattr(worker, "choose_web_action", action)
    monkeypatch.setattr(worker, "build_request_anchor", anchor)

    chat = client.post("/v1/chats", headers=admin_headers, json={"mode_id": mode["id"]}).json()
    client.post(
        f"/v1/chats/{chat['id']}/messages", headers=admin_headers,
        json={"client_request_id": "anchor-deep-1", "text": "Расскажи подробнее про документ"},
    )
    assert asyncio.run(process_next_job()) is True

    messages = client.get(f"/v1/chats/{chat['id']}/messages", headers=admin_headers).json()
    assert anchor_calls == ["Расскажи подробнее про документ"]
    assert messages[-1]["timings"]["request_anchor"]["mode"] == "model"


def test_final_answer_call_disables_thinking_on_fast_routes(
    client: TestClient, admin_headers: dict, mode: dict, monkeypatch
):
    """none/web/chat_sources formulate the answer with thinking off.

    Internal analytical steps keep it: only the final answer call is asserted
    here, and the default stays True for every other caller.
    """
    seen: list[dict] = []

    async def fake_stream(model_id, messages, **kwargs):
        seen.append(kwargs)
        for part in ("Ответ", " готов"):
            yield part

    async def search(*_args, **_kwargs):
        return [WebSearchResult("Документация", "https://example.org/doc", "Версия")]

    monkeypatch.setattr(worker.providers, "stream_answer", fake_stream)
    monkeypatch.setattr(worker, "search_web", search)

    for idx, retrieval in ((1, "none"), (2, "web")):
        async def route(*_args, _r=retrieval, **_kwargs):
            return _web_route(_r, "current_fact" if _r == "web" else "definition")

        monkeypatch.setattr(worker, "choose_retrieval_route", route)
        chat = client.post("/v1/chats", headers=admin_headers, json={"mode_id": mode["id"]}).json()
        client.post(
            f"/v1/chats/{chat['id']}/messages", headers=admin_headers,
            json={"client_request_id": f"thinking-{idx}", "text": "Что такое HTTP?"},
        )
        assert asyncio.run(process_next_job()) is True

    assert seen, "the final answer call must have happened"
    assert all(item.get("thinking") is False for item in seen)
