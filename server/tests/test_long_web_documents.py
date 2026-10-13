"""Local fixtures only: no external search/model calls or production data."""
import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select
from wristmind_server.web_search import extract_web_html, open_web_page, WebSearchUnavailable
from wristmind_server.search_documents import DocumentView
from wristmind_server.search_agent import run_search_agent
from wristmind_server.web_search import WebSearchResult
from wristmind_server.worker import WebAgentAction
from wristmind_server.web_cache import cache_document, reusable_document
from wristmind_server.db_models import RawWebSource, KnowledgeChunk
from wristmind_server.database import SessionFactory


def book_html():
    return '<html><body><article><h1>Оригинальная книга</h1>' + ''.join(
        f'<h2>Глава {i}</h2><p>' + (f'В главе {i} описаны события, путешествия и встречи героев. ' * 70)
        + f'</p><p>Последний абзац раздела {i}.</p>' for i in range(1, 15)) + '</article></body></html>'


_HTTP_CLIENT = httpx.AsyncClient

def download(monkeypatch, body):
    original = _HTTP_CLIENT
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body,
              headers={'content-type': 'text/html'})), **kw))
    monkeypatch.setattr('wristmind_server.web_search._resolve_public_host', AsyncMock())


def test_long_html_preserves_tail_headings_paragraphs_and_arbitrary_reads(monkeypatch):
    download(monkeypatch, book_html().encode())
    url, text = asyncio.run(open_web_page('https://example.org/book', timeout_seconds=1,
                              max_download_bytes=2_000_000, max_redirects=3))
    assert len(text) > 12_000
    assert '## Глава 14' in text and '\n\n' in text
    view = DocumentView(text)
    found = view.prompt('глава 14', max_chars=6000)
    assert 'Глава 14' in found and len(found) <= 6000
    index = next(b.id for b in view.blocks if 'Глава 14' in view.read(b.id, b.id))
    assert 'Глава 14' in view.read(index, index, max_chars=2000)
    with pytest.raises(ValueError, match='smaller'):
        view.read(0, len(view.blocks) - 1, max_chars=2000)
    assert 'Глава 14' not in view.prompt('глава 99')
    assert 'совпадений' in view.prompt('глава 99')


def test_short_html_and_empty_corrupt_documents(monkeypatch):
    html = '<html><article><h1>Короткая история</h1><p>' + ('Герой отправился домой и рассказал друзьям о путешествии. ' * 12) + '</p></article></html>'
    download(monkeypatch, html.encode())
    _, text = asyncio.run(open_web_page('https://example.org/short', timeout_seconds=1,
                             max_download_bytes=20000, max_redirects=3))
    assert 'Герой отправился' in text and len(text) < 12000
    download(monkeypatch, b'\x00\x01<script>nothing()</script>')
    with pytest.raises(WebSearchUnavailable, match='извлечь'):
        asyncio.run(open_web_page('https://example.org/broken', timeout_seconds=1,
                                 max_download_bytes=20000, max_redirects=3))


def test_extraction_rejects_oversized_text_instead_of_truncating():
    with pytest.raises(WebSearchUnavailable, match='не сохранён частично'):
        asyncio.run(extract_web_html(book_html(), max_chars=12000, memory_mb=256, timeout_seconds=5))


def test_extraction_timeout_terminates_child(monkeypatch):
    original = asyncio.create_subprocess_exec
    children = []
    async def spawn(*args, **kwargs):
        child = await original(*args, **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    with pytest.raises(WebSearchUnavailable, match='время'):
        asyncio.run(extract_web_html(book_html(), max_chars=1000000, memory_mb=256, timeout_seconds=.001))
    assert children and all(child.returncode is not None for child in children)


def test_full_document_cache_keeps_legacy_snapshot_and_does_not_ingest(client, admin_headers, mode):
    chat = client.post('/v1/chats', headers=admin_headers, json={'mode_id':mode['id']}).json()
    async def scenario():
        async with SessionFactory() as session:
            old = RawWebSource(chat_id=chat['id'], url='https://example.org/book', title='Book',
                               content='legacy truncated text', content_hash='old')
            session.add(old); await session.commit()
            assert reusable_document(old, fresh=False, max_html_chars=1000000) is None
            full = '## Глава 1\n' + 'Текст. ' * 3000 + '\n## Глава 14\nКонец.'
            updated = await cache_document(session, chat['id'], 'Book', old.url, full)
            await session.commit()
            assert updated.id == old.id and updated.content == 'legacy truncated text'
            assert updated.content_hash == 'old'
            assert reusable_document(updated, fresh=False, max_html_chars=1000000) == full
            assert reusable_document(updated, fresh=True, max_html_chars=1000000) is None
            assert (await session.scalars(select(KnowledgeChunk))).all() == []
            updated = await cache_document(session, chat['id'], 'Book', old.url, full+'\nFresh')
            assert updated.full_content.endswith('Fresh') and updated.content == 'legacy truncated text'
            await session.commit()
            return updated.full_content
    latest = asyncio.run(scenario())
    listing = client.get(f"/v1/chats/{chat['id']}/sources", headers=admin_headers).json()
    assert listing['referenced'][0]['character_count'] == len(latest)
    assert 'content' not in listing['referenced'][0] and 'full_content' not in listing['referenced'][0]
    assert listing['working'] == []


def test_agent_can_find_and_read_far_tail_with_bounded_model_context():
    text = 'Вступительный материал. ' * 3000 + '\n## Глава 14\nФинал оригинального произведения.'
    view = DocumentView(text)
    index = next(b.id for b in view.blocks if 'Глава 14' in view.read(b.id,b.id))
    actions = iter([WebAgentAction(action='open', result_id='r1'),
                    WebAgentAction(action='find', result_id='r1', query='глава 14'),
                    WebAgentAction(action='read', result_id='r1', start_block=index, end_block=index),
                    WebAgentAction(action='answer')])
    seen = []
    async def plan(query, results, inspected, evidence):
        seen.extend(value[2] for value in inspected.values())
        return next(actions)
    result = asyncio.run(run_search_agent(query='глава 14', previous=[], deep=True,
        max_seconds=5, max_steps=6, max_searches=1, max_opens=1, model_fragment_chars=6000,
        search=AsyncMock(return_value=[WebSearchResult('Book','https://example.org/book','')]),
        open_page=AsyncMock(return_value=('https://example.org/book',text)), plan=plan,
        save=AsyncMock(return_value=None), state=AsyncMock(), required_open=lambda *a:None))
    assert result.opened['r1'][2] == text
    assert 'Глава 14' in result.inspected['r1'][2]
    assert seen and all(len(value)<=6000 for value in seen)


def test_html_memory_failure_is_reported_without_partial_text():
    # Intentionally below the supported settings minimum to exercise child failure.
    with pytest.raises(WebSearchUnavailable, match='памяти'):
        asyncio.run(extract_web_html(book_html(), max_chars=1000000, memory_mb=8, timeout_seconds=5))


def test_old_sqlite_cache_schema_migrates_without_losing_text(client):
    from sqlalchemy import text
    from wristmind_server.database import engine, init_database
    async def scenario():
        async with engine.begin() as connection:
            # Simulate exactly the old schema in the isolated test database.
            await connection.execute(text('DROP TABLE raw_web_sources'))
            await connection.execute(text('''CREATE TABLE raw_web_sources (
                id VARCHAR(36) PRIMARY KEY, chat_id VARCHAR(36), url VARCHAR(1500),
                title VARCHAR(240), content TEXT, content_hash VARCHAR(64), retrieved_at DATETIME,
                UNIQUE(chat_id, url))'''))
            await connection.execute(text("INSERT INTO raw_web_sources VALUES ('old','chat','https://example.org/old','Old','original truncated text','hash',CURRENT_TIMESTAMP)"))
        await init_database()
        await init_database()  # Idempotent migration.
        async with SessionFactory() as session:
            row = await session.get(RawWebSource, 'old')
            assert row.content == 'original truncated text'
            assert row.extraction_version == 0 and row.full_content is None
            assert row.last_checked_at is None and row.last_accessed_at is None
            assert row.cache_bytes is None and row.cache_kind is None
            assert reusable_document(row, fresh=False, max_html_chars=1000000) is None
    asyncio.run(scenario())


def test_only_one_html_parser_runs_at_a_time(monkeypatch):
    active = 0
    peak = 0
    class Child:
        returncode = None
        async def communicate(self, data=None):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(.01)
            active -= 1
            self.returncode = 0
            return b'Complete text', b''
    async def spawn(*args, **kwargs):
        return Child()
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    async def scenario():
        return await asyncio.gather(*(extract_web_html('html', max_chars=1000000,
                          memory_mb=256, timeout_seconds=1) for _ in range(3)))
    assert asyncio.run(scenario()) == ['Complete text'] * 3
    assert peak == 1


def test_streamed_gzip_expansion_respects_download_limit(monkeypatch):
    import gzip
    original = _HTTP_CLIENT
    compressed = gzip.compress(b'<html>' + b'x' * 200_000 + b'</html>')
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, stream=httpx.ByteStream(compressed),
            headers={'content-type':'text/html', 'content-encoding':'gzip'})), **kw))
    monkeypatch.setattr('wristmind_server.web_search._resolve_public_host', AsyncMock())
    with pytest.raises(WebSearchUnavailable, match='большая'):
        asyncio.run(open_web_page('https://example.org/compressed', timeout_seconds=1,
                                 max_download_bytes=1000, max_redirects=3))


def test_roman_chapter_at_tail_and_missing_chapter():
    text = 'Предисловие. ' * 3000 + '\n## Глава XIV\nЗаключительная глава книги.'
    view = DocumentView(text)
    assert 'Глава XIV' in view.prompt('глава 14', max_chars=6000)
    assert 'совпадений' in view.prompt('глава 15')


def test_streamed_gzip_pdf_keeps_pdf_download_limit_and_text_layer(monkeypatch):
    import gzip
    from test_web_pdf import make_pdf
    data = make_pdf('Chapter 14. The complete final chapter.')
    original = _HTTP_CLIENT
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, stream=httpx.ByteStream(gzip.compress(data)),
            headers={'content-type':'application/pdf', 'content-encoding':'gzip'})), **kw))
    monkeypatch.setattr('wristmind_server.web_search._resolve_public_host', AsyncMock())
    _, text = asyncio.run(open_web_page('https://example.org/book.pdf', timeout_seconds=1,
                            max_download_bytes=100, max_pdf_download_bytes=10000, max_redirects=3))
    assert 'Chapter 14' in text and '## Страница 1' in text
