"""Small local SQLite fixtures; no network or user-data deletion."""
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from sqlalchemy import select, func
from wristmind_server.config import Settings
from wristmind_server.database import SessionFactory
from wristmind_server.db_models import RawWebSource, KnowledgeSource
from wristmind_server.web_cache import cache_document, cache_decision, reusable_document, document_text, material_kind

NOW = datetime(2026, 10, 12, tzinfo=timezone.utc)

def row(kind='page', age=0):
    return RawWebSource(chat_id='chat', title='Document', url='https://example.org/document',
        content='Original', content_hash='hash', extraction_version=1, cache_kind=kind,
        retrieved_at=NOW-timedelta(seconds=age))

@pytest.mark.parametrize('kind,ttl', [('news',3600), ('page',86400), ('document',604800), ('static',7776000)])
def test_type_ttl_and_legacy_compatibility(kind, ttl):
    item = row(kind, ttl-1)
    assert cache_decision(item, now=NOW) == 'hit'
    item.retrieved_at = (NOW-timedelta(seconds=ttl)).replace(tzinfo=None)
    assert cache_decision(item, now=NOW) == 'expired'
    item.extraction_version = 0
    assert cache_decision(item, now=NOW) == 'legacy_extraction'
    assert cache_decision(item, fresh=True, now=NOW) == 'fresh_required'


def test_reads_are_read_only_and_do_not_slide_ttl():
    item = row(age=100)
    assert reusable_document(item, fresh=False, max_html_chars=100, now=NOW) == 'Original'
    assert item.last_checked_at is None and item.last_accessed_at is None
    assert cache_decision(item, now=NOW+timedelta(days=1)) == 'expired'
    assert cache_decision(row(age=-400), now=NOW) == 'expired'
    assert cache_decision(row(), now=NOW, settings=Settings(web_cache_page_ttl_seconds=0)) == 'expired'
    assert material_kind('Новости сегодня', 'https://example.org/news', 'text') == 'news'
    assert material_kind('Полный текст повести', 'https://example.org/book', ('Глава 1\n'+ 'text '*1800+'\nГлава 2\nГлава 3\n')) == 'static'


def test_cache_refresh_quota_and_provenance(client, admin_headers, mode, tmp_path):
    chat = client.post('/v1/chats', headers=admin_headers, json={'mode_id':mode['id']}).json()
    config = Settings(web_cache_max_entries=1, web_cache_max_bytes=100)
    async def check():
        async with SessionFactory() as session:
            first = await cache_document(session, chat['id'], 'Original', 'https://example.org/a', 'original', now=NOW, settings=config)
            original_id, original_hash = first.id, first.content_hash
            await session.commit()
            assert await cache_document(session, chat['id'], 'Other', 'https://example.org/b', 'second', now=NOW, settings=config) is None
            refreshed = await cache_document(session, chat['id'], 'Updated', first.url, 'updated', now=NOW+timedelta(days=2), settings=config)
            assert refreshed.id == original_id and refreshed.content_hash == original_hash
            assert refreshed.content == 'original' and document_text(refreshed) == 'updated'
            await cache_document(session, chat['id'], 'Updated', first.url, 'updated', refreshed=False, now=NOW+timedelta(days=3), settings=config)
            assert first.last_checked_at == NOW+timedelta(days=2)
            assert first.last_accessed_at == NOW+timedelta(days=3)
            await cache_document(session, chat['id'], 'Too large', first.url, 'x'*101, now=NOW+timedelta(days=4), settings=config)
            assert document_text(first) == 'updated' and first.last_checked_at == NOW+timedelta(days=2)
            path = tmp_path/'source.txt'; path.write_text('User working original')
            source = KnowledgeSource(mode_id=mode['id'], chat_id=chat['id'], title='User original', filename='source.txt',
                media_type='text/plain', processing_mode='WEB', raw_source_id=first.id, storage_path=str(path), status='ready')
            session.add(source); await session.commit()
            await cache_document(session, chat['id'], 'Updated', first.url, 'x'*101, now=NOW+timedelta(days=4), settings=config)
            assert first.content == 'original' and first.content_hash == original_hash
            assert source.status == 'ready' and path.read_text() == 'User working original'
            assert source.raw_source_id == original_id
            assert await session.scalar(select(func.count(RawWebSource.id))) == 1
            protected = await cache_document(session, chat['id'], 'Explicit working source', 'https://example.org/c', 'z'*200,
                                             protect=True, settings=Settings(web_cache_max_entries=0, web_cache_max_bytes=0))
            assert protected is not None
    asyncio.run(check())


def test_user_api_cancel_interrupts_deep_open_and_preserves_sources(client, admin_headers, mode, monkeypatch):
    from unittest.mock import AsyncMock
    import wristmind_server.worker as worker
    from wristmind_server import latency_trace
    from wristmind_server.db_models import Job
    from wristmind_server.web_search import WebSearchResult
    request='Найди полный оригинальный текст А. С. Пушкина "Капитанская дочка" и проверь наличие всех 14 глав'
    item=WebSearchResult('Пушкин — Капитанская дочка, полный текст','https://library.example/book','Оригинал')
    chat=client.post('/v1/chats',headers=admin_headers,json={'mode_id':mode['id']}).json()
    job=client.post(f"/v1/chats/{chat['id']}/messages",headers=admin_headers,json={'client_request_id':'cancel-deep-open','text':request}).json()
    route=worker.RetrievalRoute(retrieval='deep_web',reasoning='low',verification=False,freshness_required=False,
                               task_type='other',intents=worker.WriteIntents(wants_primary_source=True))
    monkeypatch.setattr(worker,'choose_retrieval_route',AsyncMock(return_value=route))
    monkeypatch.setattr(worker,'build_request_anchor',AsyncMock(return_value=worker.lightweight_request_anchor(request)))
    monkeypatch.setattr(worker,'search_web',AsyncMock(return_value=[item]))
    monkeypatch.setattr(worker.settings,'searxng_url','http://searxng:8080')
    save=AsyncMock(side_effect=AssertionError('cancelled source must not be saved'))
    monkeypatch.setattr(worker,'create_source_candidate',save)
    records=[]
    monkeypatch.setattr(latency_trace,'record',lambda event,**fields:records.append(dict(event=event,**fields)))
    async def check():
        entered=asyncio.Event();interrupted=asyncio.Event()
        async def open_page(*a,**kw):
            entered.set()
            try:await asyncio.sleep(60)
            except asyncio.CancelledError:interrupted.set();raise
        monkeypatch.setattr(worker,'open_web_page',open_page)
        task=asyncio.create_task(worker.process_next_job())
        await asyncio.wait_for(entered.wait(),2)
        result=await asyncio.to_thread(client.post,f"/v1/jobs/{job['id']}/cancel",headers=admin_headers)
        assert result.status_code==200
        assert await asyncio.wait_for(task,3) is True
        assert interrupted.is_set() and save.await_count==0
        async with SessionFactory() as session:
            assert (await session.get(Job,job['id'])).status=='cancelled'
            assert await session.scalar(select(func.count(KnowledgeSource.id)))==0
            assert await session.scalar(select(func.count(RawWebSource.id)))==0
        summary=next(x for x in records if x['event']=='SEARCH_SUMMARY')
        assert summary['status']=='cancelled' and summary['stop_reason']=='cancelled'
        assert summary['searches']==1 and summary['opens']==1
    asyncio.run(check())
