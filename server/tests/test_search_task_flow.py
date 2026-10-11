"""Two turns in one chat: a saved material is rejected, and the task survives.

This drives the real API/worker path with mock providers. It checks the two
things the state exists for: the follow-up is still a source-search task, and
the document the user called wrong is recorded by the server — not by the model.

Local note: in a combined local run this test can hit the known SQLite
"database is locked" contention (production uses PostgreSQL). It belongs to the
focused set, where it runs clean.
"""
import asyncio
import json

from fastapi.testclient import TestClient

import wristmind_server.worker as worker
from wristmind_server.database import SessionFactory
from wristmind_server.db_models import Chat, ChatSearchTask, KnowledgeChunk, KnowledgeSource
from wristmind_server.search_task import rejected_source_ids
from wristmind_server.web_search import WebSearchResult
from wristmind_server.worker import process_next_job

ROUTE_REPLY = json.dumps({
    "retrieval": "deep_web",
    "reasoning": "high",
    "verification": True,
    "freshness_required": False,
    "task_type": "write_from_source",
    "intents": {"rejects_previous_material": True},
})

EXCERPT_ROUTE_REPLY = json.dumps({
    "retrieval": "chat_sources",
    "reasoning": "low",
    "verification": False,
    "freshness_required": False,
    "task_type": "write_from_source",
    "intents": {"wants_source_excerpt": True},
})


def _install_stubs(monkeypatch, seen: list[str], route_reply: str = ROUTE_REPLY,
                   answers: list[str] | None = None):
    async def stream(_model_id, messages, **_kwargs):
        prompt = messages[0]["content"]
        if "Задача поиска материала в этом чате" in prompt:
            seen.append(prompt)
        if answers is not None and "Точный поиск внутри сохранённого источника" in prompt:
            answers.append(prompt)
        if "Ты — маршрутизатор ответа" in prompt:
            yield route_reply
        elif "цельный материал" in prompt:
            yield '{"requested":true}'
        else:
            yield "Короткий ответ."

    async def search(_url, _query, **_kwargs):
        return [WebSearchResult("Сборник задач", "https://example.test/sbornik", "задача 11")]

    async def open_page(url, **_kwargs):
        return url, "## Страница 1\nЗадача 11 про сани. Условие полностью."

    monkeypatch.setattr(worker.providers, "stream_answer", stream)
    monkeypatch.setattr(worker, "search_web", search)
    monkeypatch.setattr(worker, "open_web_page", open_page)


def _saved_source(chat_id: str, mode_id: str, title: str) -> str:
    async def create() -> str:
        async with SessionFactory() as session:
            source = KnowledgeSource(
                mode_id=mode_id, chat_id=chat_id, title=title, filename="source.txt",
                media_type="text/plain", processing_mode="WEB", source_tier="working",
                storage_path="unused-in-this-test", status="ready",
                chunk_count=1, token_count=4,
            )
            session.add(source)
            await session.flush()
            session.add(KnowledgeChunk(
                source_id=source.id, ordinal=0,
                content="Задача 7.13 про бревно", token_count=4, embedding=None,
            ))
            await session.commit()
            return source.id

    return asyncio.run(create())


def _task_state(chat_id: str):
    async def read():
        async with SessionFactory() as session:
            return await session.get(ChatSearchTask, chat_id)

    return asyncio.run(read())


def test_a_rejection_is_recorded_and_the_task_keeps_going(
    client: TestClient, admin_headers: dict, mode: dict, monkeypatch,
):
    chat = client.post("/v1/chats", headers=admin_headers, json={"mode_id": mode["id"]}).json()
    rejected_id = _saved_source(chat["id"], mode["id"], "Стратегии")

    async def seed() -> None:
        async with SessionFactory() as session:
            session.add(ChatSearchTask(
                chat_id=chat["id"],
                statement="Найди сборник задач, где была задача про санки",
                confirmed_source_id=rejected_id,
                rejected=[],
                idle_turns=3,
            ))
            await session.commit()

    asyncio.run(seed())

    seen: list[str] = []
    _install_stubs(monkeypatch, seen)

    client.post(
        f"/v1/chats/{chat['id']}/messages",
        headers=admin_headers,
        json={"client_request_id": "reject-1", "text": "Это не тот сборник", "web_research": True},
    )
    # Drain whatever this turn queued (ANSWER first, then the title job) without
    # depending on how many jobs the path creates.
    for _ in range(4):
        if asyncio.run(process_next_job()) is False:
            break

    task = _task_state(chat["id"])
    # The server stored the rejection itself and kept the task alive.
    assert rejected_id in rejected_source_ids(task)
    assert task.idle_turns == 0
    assert task.confirmed_source_id == rejected_id

    # The router was told what is being looked for and that a task is unfinished.
    assert seen, "the router never saw the search task"
    assert "Найди сборник задач, где была задача про санки" in seen[0]
    assert "Стратегии" in seen[0]


def test_an_exact_question_searches_inside_the_saved_document(
    client: TestClient, admin_headers: dict, mode: dict, monkeypatch, tmp_path,
):
    """A huge saved text must be usable on a later turn, not only via ranking."""
    chat = client.post("/v1/chats", headers=admin_headers, json={"mode_id": mode["id"]}).json()

    stored = tmp_path / "sbornik.txt"
    stored.write_text(
        "## Страница 1\n" + ("общие сведения о климате и природе. " * 400)
        + "\n## Страница 12\nЗадача 12. Бревно плавает в воде. Найти плотность.\n",
        encoding="utf-8",
    )

    async def seed() -> None:
        async with SessionFactory() as session:
            chat_row = await session.get(Chat, chat["id"])
            source = KnowledgeSource(
                user_id=chat_row.user_id,
                mode_id=mode["id"], chat_id=chat["id"], title="Сборник задач",
                filename="sbornik.txt", media_type="text/plain", processing_mode="WEB",
                source_tier="working", storage_path=str(stored), status="ready",
                chunk_count=1, token_count=4,
            )
            session.add(source)
            await session.flush()
            session.add(KnowledgeChunk(
                source_id=source.id, ordinal=0,
                content="общие сведения о климате", token_count=4, embedding=None,
            ))
            await session.commit()

    asyncio.run(seed())

    seen: list[str] = []
    answers: list[str] = []
    _install_stubs(monkeypatch, seen, route_reply=EXCERPT_ROUTE_REPLY, answers=answers)

    client.post(
        f"/v1/chats/{chat['id']}/messages",
        headers=admin_headers,
        json={"client_request_id": "excerpt-1", "text": "Дай точный текст задачи 12", "web_research": False},
    )
    for _ in range(4):
        if asyncio.run(process_next_job()) is False:
            break

    assert answers, "the answer prompt never got the direct document search"
    assert "Задача 12. Бревно плавает в воде" in answers[0]
    assert "Сборник задач" in answers[0]
