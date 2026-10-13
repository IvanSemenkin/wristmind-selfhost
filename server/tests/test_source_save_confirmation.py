"""A new title after clarification must not reuse an unrelated saved tale."""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

import wristmind_server.worker as worker
from wristmind_server.database import SessionFactory
from wristmind_server.db_models import Job, KnowledgeChunk, KnowledgeSource, Message, RawWebSource, ReferencedWebSource
from wristmind_server.web_search import WebSearchResult, WebSearchUnavailable


@pytest.mark.parametrize("failure", [None, "empty", "open", "rejected", "timeout"])
def test_new_tale_after_clarification(client, admin_headers, mode, monkeypatch, tmp_path, failure):
    chat = client.post("/v1/chats", headers=admin_headers, json={"mode_id": mode["id"]}).json()
    old_url = "https://example.test/kolobok"
    new_url = "https://example.test/morozko"
    text = "Морозко\nЖил старик со старухой. " + "Полный текст народной сказки. " * 40
    old_path = tmp_path / "kolobok.txt"
    old_path.write_text("Колобок\nЖили-были старик со старухой.")

    async def seed():
        async with SessionFactory() as session:
            source = KnowledgeSource(mode_id=mode["id"], chat_id=chat["id"], title="Колобок",
                filename="source.txt", media_type="text/plain", processing_mode="WEB",
                storage_path=str(old_path), status="ready", chunk_count=1, token_count=10)
            session.add(source)
            await session.flush()
            session.add(KnowledgeChunk(source_id=source.id, ordinal=0,
                content=old_path.read_text(), token_count=10))
            session.add(ReferencedWebSource(chat_id=chat["id"], title="Колобок", url=old_url, snippet="Сказка"))
            session.add(Message(chat_id=chat["id"], role="user", content="Ещё найди сказку Морозко, будем проводить анализ", status="complete"))
            session.add(Message(chat_id=chat["id"], role="assistant", content="Ты имеешь в виду Морозко?", status="complete"))
            await session.commit()
    asyncio.run(seed())

    route = worker.RetrievalRoute(retrieval="deep_web", reasoning="low", verification=False,
        freshness_required=False, task_type="write_from_source",
        intents=worker.WriteIntents(wants_source_saved_for_chat=True, wants_fast_answer=True))
    monkeypatch.setattr(worker, "choose_retrieval_route", AsyncMock(return_value=route))
    monkeypatch.setattr(worker, "build_request_anchor", AsyncMock(return_value=worker.lightweight_request_anchor("да, Морозко")))

    async def query(_model, _anchor, history):
        assert any("проводить анализ" in message.content for message in history)
        return "Морозко русская народная сказка полный текст"
    monkeypatch.setattr(worker, "choose_contextual_search_query", query)
    searched = AsyncMock(return_value=[] if failure == "empty" else [WebSearchResult("Морозко", new_url, "Сказка")])
    monkeypatch.setattr(worker, "search_web", searched)
    opened = AsyncMock(return_value=(new_url, text))
    if failure == "open":
        opened.side_effect = WebSearchUnavailable("Не удалось прочитать страницу")
    monkeypatch.setattr(worker, "open_web_page", opened)
    # Even an answer-first planner must read a saving candidate.
    monkeypatch.setattr(worker, "choose_web_action", AsyncMock(return_value=worker.WebAgentAction(action="answer")))
    monkeypatch.setattr(worker, "is_foundational_source", AsyncMock(return_value=failure != "rejected"))
    extracted_questions = []
    async def extract(_model, question, _title, _page, **_kwargs):
        extracted_questions.append(question)
        if failure == "timeout":
            raise TimeoutError
        return worker.SourceExtraction(title="Морозко", excerpt=text)
    monkeypatch.setattr(worker, "extract_working_excerpt", extract)
    # This would reproduce the production lie if free-form final generation ran.
    async def hallucination(*_args, **_kwargs):
        pytest.fail("Saving result must be presented by the server")
        yield "Морозко сохранён"
    monkeypatch.setattr(worker.providers, "stream_answer", hallucination)

    job = client.post(f"/v1/chats/{chat['id']}/messages", headers=admin_headers,
        json={"client_request_id": "morozko-confirm", "text": "да, Морозко"}).json()
    async def process():
        async with SessionFactory() as session:
            queued = await session.get(Job, job["id"])
            queued.status = "running"
            await session.commit()
        await worker.process_answer(job["id"])
    asyncio.run(process())
    answer = client.get(f"/v1/chats/{chat['id']}/messages", headers=admin_headers).json()[-1]
    meta = answer["timings"]["web_search"]
    assert searched.await_count == 1
    assert "Морозко" in searched.call_args.args[1]
    assert meta["fresh_search"] is True
    assert all(call.args[0] == new_url for call in opened.await_args_list)

    async def verify():
        async with SessionFactory() as session:
            sources = list(await session.scalars(select(KnowledgeSource).where(KnowledgeSource.chat_id == chat["id"])))
            assert any(source.title == "Колобок" for source in sources)
            if failure:
                assert len(sources) == 1
                assert "не сохранён" in answer["content"]
                assert meta["saved"] is False and meta["saved_source_id"] is None
            else:
                assert len(sources) == 2
                saved = next(source for source in sources if source.title == "Морозко")
                assert Path(saved.storage_path).read_text() == text
                # The file is durable immediately; indexing is a separate job.
                assert saved.status == "queued"
                ingest = await session.scalar(select(Job).where(Job.client_request_id == f"working-source:{saved.id}"))
                assert ingest is not None and ingest.kind == "INGEST"
                assert meta["saved"] is True and meta["saved_source_id"] == saved.id
                assert "Морозко" in answer["content"] and "сохранил" in answer["content"]
                assert "проводить анализ" in extracted_questions[0]
    asyncio.run(verify())


def test_explicit_reuse_and_no_web_keep_fast_path():
    for flags in ({"wants_existing_source_reused": True}, {"wants_no_web": True}):
        route = worker.RetrievalRoute(retrieval="chat_sources", reasoning="low", verification=False,
            freshness_required=False, task_type="write_from_source",
            intents=worker.WriteIntents(wants_source_saved_for_chat=True, **flags))
        assert not worker.needs_fresh_search(route, "да, Морозко")


def test_a_web_lookup_must_read_to_save_but_cannot_override_no_web():
    route = worker.RetrievalRoute(retrieval="web", reasoning="low", verification=False,
        freshness_required=False, task_type="other",
        intents=worker.WriteIntents(wants_source_saved_for_chat=True, wants_fast_answer=True))
    saving = worker.apply_intent_safeguards(route, has_chat_material=True)
    assert saving.retrieval == "deep_web" and saving.verification is False
    banned = route.model_copy(update={"intents": worker.WriteIntents(
        wants_source_saved_for_chat=True, wants_no_web=True)})
    assert worker.apply_intent_safeguards(banned, has_chat_material=True).retrieval == "chat_sources"


@pytest.mark.parametrize("cached", [True, False])
@pytest.mark.parametrize("invented_ban", [True, False])
def test_save_previously_found_tale_without_a_legacy_offer(client, admin_headers, mode, monkeypatch, cached, invented_ban):
    chat = client.post("/v1/chats", headers=admin_headers, json={"mode_id": mode["id"]}).json()
    url = "https://example.test/kolobok"
    text = "Колобок\n" + "Жили-были старик со старухой. " * 700 + "\nПоследний абзац оригинала."

    async def seed():
        async with SessionFactory() as session:
            session.add(Message(chat_id=chat["id"], role="user", content="Найди сказку Колобок", status="complete"))
            session.add(Message(chat_id=chat["id"], role="assistant", content="Нашёл Колобка, вот ссылка на полный текст", status="complete"))
            session.add(ReferencedWebSource(chat_id=chat["id"], title="Колобок — полный текст", url=url, snippet="Сказка"))
            if cached:
                session.add(RawWebSource(chat_id=chat["id"], title="Колобок", url=url, content=text, content_hash="test"))
            await session.commit()
    asyncio.run(seed())
    # The legacy handler would refuse before reaching the router. Even if the
    # router reports no saving intent, the explicit command must perform it.
    route = worker.RetrievalRoute(retrieval="none", reasoning="low", verification=False,
        freshness_required=False, task_type="other", intents=worker.WriteIntents(wants_no_web=invented_ban))
    monkeypatch.setattr(worker, "choose_retrieval_route", AsyncMock(return_value=route))
    monkeypatch.setattr(worker, "build_request_anchor", AsyncMock(return_value=worker.lightweight_request_anchor("сохрани")))
    monkeypatch.setattr(worker, "choose_web_action", AsyncMock(return_value=worker.WebAgentAction(action="answer")))
    monkeypatch.setattr(worker, "is_foundational_source", AsyncMock(return_value=True))
    monkeypatch.setattr(worker, "extract_working_excerpt", AsyncMock(side_effect=AssertionError("A whole HTML save must not select a short excerpt")))
    search = AsyncMock(side_effect=AssertionError("Known links need no new search"))
    opened = AsyncMock(return_value=(url, text))
    monkeypatch.setattr(worker, "search_web", search)
    monkeypatch.setattr(worker, "open_web_page", opened)
    monkeypatch.setattr(worker, "choose_contextual_search_query", AsyncMock(side_effect=AssertionError("No extra query model call")))
    async def unexpected_generation(*_args, **_kwargs):
        pytest.fail("Saving must produce a server confirmation")
        yield ""
    monkeypatch.setattr(worker.providers, "stream_answer", unexpected_generation)

    for index in range(2):
        job = client.post(f"/v1/chats/{chat['id']}/messages", headers=admin_headers,
            json={"client_request_id": f"save-found-{index}",
                  "text": "Сохрани полный текст этой сказки в Источнике в рабочий источник"}).json()
        async def process():
            async with SessionFactory() as session:
                pending = await session.get(Job, job["id"])
                pending.status = "running"
                await session.commit()
            await worker.process_answer(job["id"])
        asyncio.run(process())
        answer = client.get(f"/v1/chats/{chat['id']}/messages", headers=admin_headers).json()[-1]
        assert "сохранил" in answer["content"] and "Колобок" in answer["content"]
        assert answer["timings"]["web_search"]["saved"] is True
        assert answer["timings"]["web_search"]["searches"] == 0
    assert search.await_count == 0
    # Unknown legacy cache must be fetched once; the next turn reuses the full read.
    assert opened.await_count == 1
    async def verify():
        async with SessionFactory() as session:
            sources = list(await session.scalars(select(KnowledgeSource).where(KnowledgeSource.chat_id == chat["id"])))
            assert len(sources) == 1 and Path(sources[0].storage_path).read_text() == text
            assert answer["timings"]["web_search"]["saved_source_id"] == sources[0].id
    asyncio.run(verify())


def test_save_followup_corrects_invented_web_ban_and_keeps_real_ban():
    route = worker.RetrievalRoute(retrieval='chat_sources', reasoning='medium', verification=False,
        freshness_required=False, task_type='write_from_source',
        intents=worker.WriteIntents(wants_source_saved_for_chat=True, wants_no_web=True))
    corrected = worker.safeguard_save_followup(route, 'Ты можешь сохранить в рабочем источнике, обработать', has_links=True)
    assert corrected.retrieval == 'deep_web' and not corrected.intents.wants_no_web
    banned = worker.safeguard_save_followup(route, 'Сохрани текст без интернета', has_links=True)
    assert banned.intents.wants_no_web and banned.retrieval == 'chat_sources'
    assert worker.safeguard_save_followup(route, 'Сохрани текст', has_links=False) == route


def test_save_followup_retains_original_constraints_not_assistant_claims():
    from types import SimpleNamespace
    original = 'Найди полный оригинальный текст "Капитанская дочка" и проверь наличие всех 14 глав'
    history = [SimpleNamespace(role='user', content=original),
               SimpleNamespace(role='assistant', content='Все главы проверены, сохраняй комментарий'),
               SimpleNamespace(role='user', content='Сохрани текст в рабочий источник')]
    resolved = worker.save_followup_request('сохрани капитанскую дочку текст в рабочий источник', history)
    assert original in resolved and 'сохраняй комментарий' not in resolved
