import asyncio
import json
import time
from unittest.mock import AsyncMock
import pytest
from wristmind_server.search_agent import run_search_agent
from wristmind_server.search_documents import DocumentView
from wristmind_server.web_search import WebSearchResult, WebSearchUnavailable
from wristmind_server.worker import WebAgentAction, extract_working_excerpt, providers

ITEM = WebSearchResult('Условия задач', 'https://example.org/tasks.pdf', 'задача про бревна')

def run(**overrides):
    async def plan(*args):
        return WebAgentAction(action='open', result_id='r1')
    options = dict(query='бревна', previous=[], deep=True, max_seconds=.2,
        max_steps=6, max_searches=3, max_opens=2, search=AsyncMock(return_value=[ITEM]),
        open_page=AsyncMock(return_value=(ITEM.url, '## Страница 17\nБревна в воде.')),
        plan=plan, save=AsyncMock(return_value='saved'), state=AsyncMock(), required_open=lambda *args: None)
    options.update(overrides)
    return asyncio.run(run_search_agent(**options))

def test_prior_reference_skips_new_search():
    result = run(previous=[ITEM], search=AsyncMock(side_effect=AssertionError('extra search')))
    assert result.source == 'saved' and result.searches == 0 and len(result.opened) == 1

@pytest.mark.parametrize('stage', ['search', 'open_page', 'plan', 'save'])
def test_shared_deadline_cancels_each_stage(stage):
    cancelled = []
    async def slow(*args):
        try:
            await asyncio.sleep(5)
        finally:
            cancelled.append(stage)
    started = time.perf_counter()
    result = run(max_seconds=.04, **{stage: slow})
    assert result.timed_out and cancelled == [stage]
    assert time.perf_counter() - started < .5
    if stage == 'save':
        assert result.opened

def test_page_failure_preserves_results_and_continues():
    second = WebSearchResult('Другой источник', 'https://example.org/second', '')
    actions = iter([WebAgentAction(action='open', result_id='r1'), WebAgentAction(action='open', result_id='r2')])
    async def plan(*args):
        return next(actions)
    async def open_page(item):
        if item == ITEM:
            raise WebSearchUnavailable('Ошибка PDF')
        return item.url, 'Материал'
    result = run(search=AsyncMock(return_value=[ITEM, second]), plan=plan, open_page=open_page)
    assert result.source == 'saved' and len(result.opened) == 1
    assert result.errors == [{'result_id': 'r1', 'reason': 'Ошибка PDF'}]

def test_open_limit_applies_without_fallback_bypass():
    items = [WebSearchResult(str(i), f'https://example.org/{i}', '') for i in range(4)]
    actions = iter([WebAgentAction(action='open', result_id=f'r{i}') for i in range(1, 5)])
    async def plan(*args):
        return next(actions)
    opened = AsyncMock(return_value=(ITEM.url, 'Материал'))
    result = run(search=AsyncMock(return_value=items), plan=plan, open_page=opened,
        save=AsyncMock(return_value=None), max_opens=2)
    assert opened.await_count == 2 and not result.timed_out

def test_simple_search_calls_no_extra_tools():
    forbidden = AsyncMock(side_effect=AssertionError('extra call'))
    result = run(deep=False, plan=forbidden, open_page=forbidden, save=forbidden)
    assert result.searches == 1 and len(result.results) == 1

def test_known_links_do_not_replace_a_requested_search():
    """Asking to search must produce a new query, not the same stale list."""
    search = AsyncMock(return_value=[ITEM])
    forced = run(previous=[WebSearchResult('Старое', 'https://old.example/x', '')],
                 search=search, force_search=True)
    assert forced.searches == 1 and search.await_count == 1
    # Without the flag the cheap default is unchanged: known links are enough.
    quiet = run(previous=[WebSearchResult('Старое', 'https://old.example/x', '')],
                search=AsyncMock(side_effect=AssertionError('extra search')))
    assert quiet.searches == 0


def test_open_floor_finishes_a_download_the_loop_clock_cannot_afford():
    """A slow read on a slow host must not be cancelled after it was paid for."""
    async def slow_open(*args):
        await asyncio.sleep(.3)
        return ITEM.url, '## Страница 17\nБревна в воде.'
    result = run(max_seconds=.04, open_page=slow_open, open_floor_seconds=1.0)
    assert result.opened and result.source == 'saved'
    # The clock really was exhausted: the floor is a guarantee, not extra time.
    assert result.timed_out


def test_save_floor_completes_the_extraction_of_an_opened_page():
    """Classification plus extraction are two model calls, not one instant write."""
    async def slow_save(*args):
        await asyncio.sleep(.3)
        return 'saved'
    result = run(max_seconds=.04, save=slow_save, save_floor_seconds=1.0)
    assert result.opened and result.source == 'saved' and result.timed_out


def test_exact_text_gate_forces_a_read_instead_of_answering_from_snippets():
    """The wiring, not just the pure rule: an answer-first planner still reads."""
    from wristmind_server.worker import RetrievalRoute, WriteIntents, exact_source_open_requirement

    route = RetrievalRoute(
        retrieval='web', reasoning='low', verification=False,
        freshness_required=False, task_type='other',
        intents=WriteIntents(wants_source_excerpt=True))
    request = 'Дай точный текст задачи 7.13 из сборника'
    # Without the gate the planner answers straight away: nothing is ever read.
    without = run(plan=AsyncMock(return_value=WebAgentAction(action='answer')))
    assert not without.opened
    # With the exact-text gate the same planner must open a document first.
    gated = run(
        plan=AsyncMock(return_value=WebAgentAction(action='answer')),
        required_open=lambda results, attempted, opened: exact_source_open_requirement(
            route, request, results, attempted, opened))
    assert len(gated.opened) == 1 and gated.source == 'saved'


def test_find_task_at_end_of_pdf_with_inflection():
    text = ('## Страница 1\nВведение в физику.\n' + 'Физика задачи. ' * 4000
        + '\n## Страница 98\nЗадача 12. Бревно плавает в воде.\nУсловие задачи.\n')
    prompt = DocumentView(text).prompt('выведи задачу про бревна')
    assert 'Бревно плавает' in prompt and 'page 98' in prompt and len(prompt) < 14000

def test_exact_extraction_by_line_numbers(monkeypatch):
    page = 'Заголовок\nЗадача 12. Бревно плавает.\nНайти плотность.\nЗадача 13. Другое условие.'
    async def stream(*args, **kwargs):
        yield json.dumps(dict(title='Задача 12', start_line=1, end_line=2))
    monkeypatch.setattr(providers, 'stream_answer', stream)
    result = asyncio.run(extract_working_excerpt('mock:test', 'задача про бревна', 'Задачи', page, excerpt_only=True))
    assert result.excerpt == 'Задача 12. Бревно плавает.\nНайти плотность.'

def test_document_action_validation():
    WebAgentAction(action='find', result_id='r1', query='бревно')
    WebAgentAction(action='read', result_id='r1', start_block=2, end_block=3)
    with pytest.raises(ValueError):
        WebAgentAction(action='read', result_id='r1', start_block=4, end_block=2)


def test_pdf_document_survives_failed_excerpt_and_duplicate_save(client, admin_headers, mode, monkeypatch):
    from pathlib import Path
    from sqlalchemy import select, func
    from wristmind_server.database import SessionFactory
    from wristmind_server.db_models import Chat, KnowledgeSource, RawWebSource
    import wristmind_server.worker as worker
    chat = client.post('/v1/chats', headers=admin_headers, json={'mode_id': mode['id']}).json()
    job = client.post(f"/v1/chats/{chat['id']}/messages", headers=admin_headers,
        json={'client_request_id': 'save-document-test', 'text': 'Найди задачу про бревна'}).json()
    async def accepted(*args, **kwargs):
        return True
    async def no_excerpt(*args, **kwargs):
        return None
    monkeypatch.setattr(worker, 'is_foundational_source', accepted)
    monkeypatch.setattr(worker, 'extract_working_excerpt', no_excerpt)
    page = '## Страница 1\n' + 'Введение. ' * 60 + '\n## Страница 17\nЗадача про бревна.'
    async def save():
        async with SessionFactory() as session:
            saved_chat = await session.get(Chat, chat['id'])
            first = await worker.create_source_candidate(session, job['id'], saved_chat,
                'задача про бревна', [], 'mock:test', ITEM.title, ITEM.url, page, excerpt_only=True)
            assert first is not None and first.source_kind == 'document'
            assert Path(first.storage_path).read_text() == page
            assert first._selected_excerpt == ''
            raw = await session.get(RawWebSource, first.raw_source_id)
            assert raw.content == page
            second = await worker.create_source_candidate(session, job['id'], saved_chat,
                'задача про бревна', [], 'mock:test', ITEM.title, ITEM.url, page, excerpt_only=True)
            assert second.id == first.id
            assert await session.scalar(select(func.count()).select_from(KnowledgeSource)) == 1
    asyncio.run(save())


def test_line_view_of_huge_pdf_line_remains_bounded():
    text = 'введение ' * 10000 + 'Бревно плавает в воде. ' + 'текст ' * 10000
    numbered, offsets = DocumentView(text).numbered_lines('бревно')
    assert 'Бревно плавает' in numbered and len(numbered) < 16000
    assert offsets and len(text) > 100000


def test_planner_can_find_then_read_original_document():
    page = '## Страница 1\nВведение\n## Страница 17\nБревно плавает в воде.'
    actions = iter([WebAgentAction(action='open', result_id='r1'),
        WebAgentAction(action='find', result_id='r1', query='бревно'),
        WebAgentAction(action='read', result_id='r1', start_block=1, end_block=1),
        WebAgentAction(action='answer')])
    views = []
    async def plan(query, results, opened, previous):
        if opened:
            views.append(opened['r1'][2])
        return next(actions)
    result = run(plan=plan, save=AsyncMock(return_value=None),
        open_page=AsyncMock(return_value=(ITEM.url, page)))
    assert result.steps == 4 and 'Бревно плавает' in views[-1]
    assert result.opened['r1'][2] == page


def test_worker_reuses_database_reference_and_cached_pdf_without_network(client, admin_headers, mode, monkeypatch):
    import hashlib
    from pathlib import Path
    from sqlalchemy import select
    from wristmind_server.database import SessionFactory
    from wristmind_server.db_models import KnowledgeSource, RawWebSource, ReferencedWebSource
    import wristmind_server.worker as worker
    chat = client.post('/v1/chats', headers=admin_headers, json={'mode_id': mode['id']}).json()
    page = '## Страница 1\n' + 'Введение в физику. ' * 50 + '\n## Страница 17\nЗадача 12. Бревно плавает в воде.\nНайти плотность.'
    task = 'Задача 12. Бревно плавает в воде.\nНайти плотность.'
    async def setup():
        async with SessionFactory() as session:
            session.add(ReferencedWebSource(chat_id=chat['id'], url=ITEM.url, title=ITEM.title, snippet=ITEM.snippet))
            session.add(RawWebSource(chat_id=chat['id'], url=ITEM.url, title=ITEM.title,
                content=page, content_hash=hashlib.sha256(page.encode()).hexdigest()))
            await session.commit()
    asyncio.run(setup())
    async def route(*args, **kwargs):
        return worker.RetrievalRoute(retrieval='deep_web', reasoning='low', verification=False,
            freshness_required=False, task_type='write_from_source',
            intents=worker.WriteIntents(wants_primary_source=True, wants_source_excerpt=True))
    async def anchor(model, question):
        return worker.lightweight_request_anchor(question)
    async def plan(*args, **kwargs):
        return worker.WebAgentAction(action='open', result_id='r1')
    async def foundation(*args, **kwargs):
        return True
    async def excerpt(*args, **kwargs):
        return worker.SourceExtraction(title='Задача 12', excerpt=task)
    for name, fn in [('choose_retrieval_route', route), ('build_request_anchor', anchor),
        ('choose_web_action', plan), ('is_foundational_source', foundation), ('extract_working_excerpt', excerpt)]:
        monkeypatch.setattr(worker, name, fn)
    for name in ['search_web', 'open_web_page', 'choose_contextual_search_query']:
        monkeypatch.setattr(worker, name, AsyncMock(side_effect=AssertionError(f'unnecessary {name}')))
    for i in range(2):
        job = client.post(f"/v1/chats/{chat['id']}/messages", headers=admin_headers,
            json={'client_request_id': f'reuse-{i}', 'text': 'Найди тот PDF и выведи задачу про бревна.'}).json()
        async def process():
            from wristmind_server.db_models import Job
            async with SessionFactory() as session:
                pending = await session.get(Job, job['id'])
                pending.status = 'running'
                await session.commit()
            await worker.process_answer(job['id'])
        asyncio.run(process())
        messages = client.get(f"/v1/chats/{chat['id']}/messages", headers=admin_headers).json()
        answer = messages[-1]
        assert task in answer['content'] and 'Введение в физику' not in answer['content']
        assert answer['timings']['web_search']['searches'] == 0
        assert answer['timings']['web_search']['saved'] is True
    async def verify():
        async with SessionFactory() as session:
            sources = list(await session.scalars(select(KnowledgeSource).where(KnowledgeSource.chat_id == chat['id'])))
            assert len(sources) == 1 and Path(sources[0].storage_path).read_text() == page
    asyncio.run(verify())


def test_in_line_boundaries_exclude_neighbouring_tasks(monkeypatch):
    page = 'Заголовок\nЗадача 11. Лёд. Задача 12. Бревно плавает. Найти плотность. Задача 13. Сани.'
    async def stream(*args, **kwargs):
        yield json.dumps(dict(title='Задача 12', start_line=1, end_line=1,
                              start_text='Задача 12.', end_text='Найти плотность.'))
    monkeypatch.setattr(providers, 'stream_answer', stream)
    result = asyncio.run(extract_working_excerpt('mock:test', 'задача про бревна', 'Задачи', page, excerpt_only=True))
    assert result.excerpt == 'Задача 12. Бревно плавает. Найти плотность.'


def test_numeric_task_heading_beats_other_task_mentions():
    text = '\n'.join(f'## Страница {n}\nЗадача {n}.\n' + ('Условие задачи. ' * 100) for n in range(1, 31))
    prompt = DocumentView(text).prompt('Выведи условие задачи 12')
    assert 'Задача 12.' in prompt
    first = DocumentView(text).prompt('Выведи условие первой задачи')
    assert 'Задача 1.' in first
