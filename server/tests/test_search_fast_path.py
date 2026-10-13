import asyncio
from unittest.mock import AsyncMock
from sqlalchemy import select, func

from wristmind_server.database import SessionFactory
from wristmind_server.db_models import Job, RawWebSource, KnowledgeSource, KnowledgeChunk
from wristmind_server.web_search import WebSearchResult
import wristmind_server.worker as worker


def test_worker_wires_fast_search_and_completion_without_rewrite_or_planner(client, admin_headers, mode, monkeypatch):
    request = 'Найди полный оригинальный текст А. С. Пушкина "Капитанская дочка" и проверь наличие всех 14 глав'
    item = WebSearchResult('Пушкин — Капитанская дочка, полный текст', 'https://library.example/book', 'Оригинал')
    text = 'Капитанская дочка\n' + '\n'.join(f'Глава {n}\n' + 'Текст главы. ' * 100 for n in range(1, 15))
    chat = client.post('/v1/chats', headers=admin_headers, json={'mode_id': mode['id']}).json()
    job = client.post(f"/v1/chats/{chat['id']}/messages", headers=admin_headers,
                      json={'client_request_id': 'fast-primary-1', 'text': request}).json()
    route = worker.RetrievalRoute(retrieval='deep_web', reasoning='low', verification=False,
                                   freshness_required=False, task_type='other',
                                   intents=worker.WriteIntents(wants_primary_source=True))
    monkeypatch.setattr(worker, 'choose_retrieval_route', AsyncMock(return_value=route))
    monkeypatch.setattr(worker, 'build_request_anchor', AsyncMock(return_value=worker.RequestAnchor(
        original_request=request, main_subject=request, task_type='other')))
    for name in ('choose_contextual_search_query', 'choose_web_action'):
        monkeypatch.setattr(worker, name, AsyncMock(side_effect=AssertionError(f'unnecessary {name}')))
    monkeypatch.setattr(worker, 'create_source_candidate', AsyncMock(return_value=None))
    search = AsyncMock(return_value=[item])
    monkeypatch.setattr(worker, 'search_web', search)
    monkeypatch.setattr(worker, 'open_web_page', AsyncMock(return_value=(item.url, text)))
    monkeypatch.setattr(worker.settings, 'searxng_url', 'http://searxng:8080')
    async def answer(*args, **kwargs):
        yield 'Заголовки и текст всех 14 глав присутствуют; подлинность этим не установлена.'
    monkeypatch.setattr(worker.providers, 'stream_answer', answer)
    async def process():
        async with SessionFactory() as session:
            pending = await session.get(Job, job['id'])
            pending.status = 'running'
            await session.commit()
        await worker.process_answer(job['id'])
        async with SessionFactory() as session:
            raw = await session.scalar(select(RawWebSource).where(RawWebSource.chat_id == chat['id']))
            assert raw is not None and (raw.full_content or raw.content) == text
            assert await session.scalar(select(func.count()).select_from(KnowledgeSource)) == 0
            assert await session.scalar(select(func.count()).select_from(KnowledgeChunk)) == 0
    asyncio.run(process())
    messages = client.get(f"/v1/chats/{chat['id']}/messages", headers=admin_headers).json()
    meta = messages[-1]['timings']['web_search']
    assert meta['completion'] == 'success' and meta['planner_calls'] == 0
    assert meta['explicit_query'] and meta['checks']['r1']['verified']
    assert meta['opened_pages'] == 1 and search.await_count == 1
