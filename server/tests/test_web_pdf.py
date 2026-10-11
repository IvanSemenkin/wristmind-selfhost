import asyncio
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from sqlalchemy import select

from wristmind_server.config import get_settings
from wristmind_server.providers import ProviderRouter
from wristmind_server.web_search import WebSearchUnavailable, extract_web_pdf, open_web_page


def make_pdf(*texts):
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=600, height=800)
        if text:
            font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                     NameObject('/Subtype'): NameObject('/Type1'),
                                     NameObject('/BaseFont'): NameObject('/Helvetica')})
            page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({
                NameObject('/F1'): writer._add_object(font),
            })})
            stream = DecodedStreamObject()
            stream.set_data(f'BT /F1 12 Tf 50 750 Td ({text}) Tj ET'.encode())
            page[NameObject('/Contents')] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def mock_download(monkeypatch, response):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(
        transport=httpx.MockTransport(response), **kw,
    ))
    async def public_host(*args):
        pass
    monkeypatch.setattr('wristmind_server.web_search._resolve_public_host', public_host)


@pytest.mark.parametrize('content_type,url', [
    ('application/pdf', 'https://example.org/download'),
    ('application/octet-stream', 'https://example.org/download'),
    ('application/octet-stream', 'https://example.org/tasks.pdf'),
])
def test_download_reads_pdf_text_and_uses_document_limit(monkeypatch, content_type, url):
    data = make_pdf('Task 11. Find the pressure on the ice.', 'Task 12. Find the acceleration.')
    mock_download(monkeypatch, lambda r: httpx.Response(200, content=data, headers={'content-type': content_type}))
    async def no_vision(*args):
        pytest.fail('PDF text layer must not call Vision')
    monkeypatch.setattr(ProviderRouter, 'analyze_file', no_vision)
    final_url, text = asyncio.run(open_web_page(url, timeout_seconds=1, max_download_bytes=100,
                                               max_pdf_download_bytes=10_000, max_redirects=3))
    assert final_url == url
    assert '## Страница 1' in text and 'Task 11.' in text
    assert '## Страница 2' in text and 'Task 12.' in text
    assert text.index('Task 11.') < text.index('Task 12.')


def test_pdf_text_after_the_old_html_limit_is_preserved():
    text = asyncio.run(extract_web_pdf(make_pdf('Introduction ' * 1200, 'Task 12. The required task at the end.')))
    assert len(text) > 12_000
    assert text.endswith('Task 12. The required task at the end.')


def test_scanned_pdf_uses_vision_and_removes_temporary_file(monkeypatch):
    seen = []
    async def vision(self, path, media_type):
        seen.append(path)
        assert path.exists() and path.read_bytes().startswith(b'%PDF-')
        assert media_type == 'application/pdf'
        return '## Страница 1\n\nРаспознанное условие задачи 12.'
    monkeypatch.setattr(ProviderRouter, 'analyze_file', vision)
    text = asyncio.run(extract_web_pdf(make_pdf(None)))
    assert 'условие задачи 12' in text
    assert len(seen) == 1 and not seen[0].exists()


def test_pdf_limits_and_invalid_document_are_source_errors(monkeypatch):
    monkeypatch.setattr(get_settings(), 'max_pdf_pages', 1)
    with pytest.raises(WebSearchUnavailable, match='число страниц'):
        asyncio.run(extract_web_pdf(make_pdf(None, None)))
    with pytest.raises(WebSearchUnavailable, match='PDF'):
        asyncio.run(extract_web_pdf(b'%PDF-invalid'))
    data = make_pdf('Task 12. The required text layer.')
    mock_download(monkeypatch, lambda r: httpx.Response(200, content=data, headers={'content-type': 'application/pdf'}))
    with pytest.raises(WebSearchUnavailable, match='большая'):
        asyncio.run(open_web_page('https://example.org/tasks.pdf', timeout_seconds=1,
                                 max_download_bytes=100, max_pdf_download_bytes=100, max_redirects=3))


def test_html_keeps_its_original_download_limit(monkeypatch):
    mock_download(monkeypatch, lambda r: httpx.Response(200, content=b'x' * 101, headers={'content-type': 'text/html'}))
    with pytest.raises(WebSearchUnavailable, match='большая'):
        asyncio.run(open_web_page('https://example.org/page', timeout_seconds=1,
                                 max_download_bytes=100, max_pdf_download_bytes=10_000, max_redirects=3))


def test_pdf_is_saved_as_chat_source_after_another_page_fails(client, admin_headers, mode, monkeypatch):
    import wristmind_server.worker as worker
    from wristmind_server.database import SessionFactory
    from wristmind_server.db_models import KnowledgeSource, RawWebSource, KnowledgeChunk
    from wristmind_server.web_search import WebSearchResult

    pdf_text = 'Task 12. Find the acceleration of the sled on ice. ' * 10
    data = make_pdf(pdf_text)
    mock_download(monkeypatch, lambda r: (
        httpx.Response(413) if r.url.path == '/broken' else
        httpx.Response(200, content=data, headers={'content-type': 'application/pdf'})
    ))
    async def route(*a, **kw):
        return worker.RetrievalRoute(retrieval='deep_web', reasoning='low', verification=False,
            freshness_required=False, task_type='other',
            intents=worker.WriteIntents(wants_source_saved_for_chat=True))
    async def search(*a, **kw):
        return [WebSearchResult('Недоступная страница', 'https://example.org/broken', 'задачи'),
                WebSearchResult('Условия олимпиады', 'https://example.org/tasks.pdf', 'задача 12')]
    async def query(*a, **kw):
        return 'задача 12'
    async def anchor(model_id, question):
        return worker.lightweight_request_anchor(question)
    actions = iter([worker.WebAgentAction(action='open', result_id='r1'),
                    worker.WebAgentAction(action='open', result_id='r2'), worker.WebAgentAction(action='answer')])
    async def action(*a, **kw):
        return next(actions)
    async def foundation(*a, **kw):
        return True
    async def excerpt(model_id, question, title, page, **kw):
        assert 'Task 12.' in page
        return worker.SourceExtraction(title='Условия олимпиады', excerpt=page)
    for name, fn in [('choose_retrieval_route', route), ('search_web', search),
                     ('choose_contextual_search_query', query), ('build_request_anchor', anchor),
                     ('choose_web_action', action), ('is_foundational_source', foundation),
                     ('extract_working_excerpt', excerpt)]:
        monkeypatch.setattr(worker, name, fn)
    chat = client.post('/v1/chats', headers=admin_headers, json={'mode_id': mode['id']}).json()
    job = client.post(f"/v1/chats/{chat['id']}/messages", headers=admin_headers,
                     json={'client_request_id': 'pdf-source-test', 'text': 'Найди и сохрани PDF с задачами.'}).json()
    # Run the answer itself: cancelling the polling watcher across separate
    # asyncio.run loops leaves SQLite readers open in this test harness.
    async def answer():
        assert await worker.claim_job() == job['id']
        await worker.process_answer(job['id'])
    asyncio.run(answer())
    status = client.get(f"/v1/jobs/{job['id']}", headers=admin_headers).json()
    assert status['status'] == 'complete', status.get('error')
    messages = client.get(f"/v1/chats/{chat['id']}/messages", headers=admin_headers).json()
    assert 'Поиск источников временно недоступен' not in messages[-1]['content']
    assert 'сохранил' in messages[-1]['content']
    assert messages[-1]['timings']['web_search']['page_errors'][0]['result_id'] == 'r1'
    assert client.get(f"/v1/jobs/{job['id']}", headers=admin_headers).json()['status'] == 'complete'
    async def source():
        async with SessionFactory() as s:
            item = await s.scalar(select(KnowledgeSource).where(KnowledgeSource.chat_id == chat['id']))
            raw = await s.get(RawWebSource, item.raw_source_id)
            assert item.origin_url == 'https://example.org/tasks.pdf'
            assert item.source_tier == 'working'
            assert 'Task 12.' in Path(item.storage_path).read_text()
            assert raw.content == Path(item.storage_path).read_text()
            return item.id
    source_id = asyncio.run(source())
    from wristmind_server.db_models import Job
    async def ingest():
        async with SessionFactory() as s:
            pending = await s.scalar(select(Job).where(Job.kind == 'INGEST'))
            ingest_id = pending.id
        await worker.process_ingest(ingest_id)
    asyncio.run(ingest())
    async def ready():
        async with SessionFactory() as s:
            item = await s.get(KnowledgeSource, source_id)
            assert item.status == 'ready'
            assert await s.scalar(select(KnowledgeChunk.id).where(KnowledgeChunk.source_id == source_id))
    asyncio.run(ready())


def test_mixed_pdf_sends_only_scanned_pages_to_vision(monkeypatch):
    from pypdf import PdfReader
    writer = PdfWriter()
    writer.append(BytesIO(make_pdf('Task 11. This text layer needs no recognition.', None)))
    writer.pages[1][NameObject('/Resources')] = DictionaryObject({NameObject('/XObject'): DictionaryObject({
        NameObject('/Image'): DictionaryObject({NameObject('/Subtype'): NameObject('/Image')}),
    })})
    buffer = BytesIO()
    writer.write(buffer)
    async def vision(self, path, media_type):
        assert len(PdfReader(path).pages) == 1
        return '## Страница 1\n\nTask 12. Recognized from the scanned second page.'
    monkeypatch.setattr(ProviderRouter, 'analyze_file', vision)
    text = asyncio.run(extract_web_pdf(buffer.getvalue()))
    assert '## Страница 1\n\nTask 11.' in text
    assert '## Страница 2\n\nTask 12.' in text
