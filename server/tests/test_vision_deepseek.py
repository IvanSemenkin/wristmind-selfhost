import asyncio
import base64
import json

import httpx
import pytest
from pypdf import PdfWriter

from wristmind_server.config import Settings
from wristmind_server.providers import ProviderError, ProviderRouter


def setup_transport(monkeypatch, seen, status=200):
    original_client = httpx.AsyncClient
    def handle(request):
        seen.append((request, json.loads(request.content)))
        return httpx.Response(status, json={'choices': [{'message': {'content': 'Оцифрованный текст'}}]})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original_client(transport=httpx.MockTransport(handle), **kwargs))


def test_image_uses_existing_official_key_and_disables_thinking(tmp_path, monkeypatch):
    seen = []
    setup_transport(monkeypatch, seen)
    path = tmp_path / 'image.png'
    path.write_bytes(b'image-data')
    router = ProviderRouter(Settings(mock_providers=False, deepseek_api_key='test-key', openrouter_api_key=None))
    assert asyncio.run(router.analyze_file(path, 'image/png')) == 'Оцифрованный текст'
    request, payload = seen[0]
    assert str(request.url) == 'https://api.deepseek.com/chat/completions'
    assert request.headers['Authorization'] == 'Bearer test-key'
    assert payload['model'] == 'deepseek-flash'
    assert payload['thinking'] == {'type': 'disabled'}
    image = payload['messages'][0]['content'][1]
    assert image['type'] == 'image_url'
    assert image['image_url']['url'].endswith(base64.b64encode(b'image-data').decode())


def test_pdf_is_rendered_page_by_page_and_preserves_order(tmp_path, monkeypatch):
    seen = []
    setup_transport(monkeypatch, seen)
    path = tmp_path / 'document.pdf'
    pdf = PdfWriter()
    pdf.add_blank_page(width=100, height=100)
    pdf.add_blank_page(width=100, height=100)
    pdf.write(path)
    rendered = []
    def render(path, page):
        rendered.append(page)
        return f'page-{page}'.encode()
    monkeypatch.setattr(ProviderRouter, '_vision_pdf_page', staticmethod(render))
    router = ProviderRouter(Settings(mock_providers=False, deepseek_api_key='test-key'))
    answer = asyncio.run(router.analyze_file(path, 'application/pdf'))
    assert rendered == [1, 2]
    assert len(seen) == 2
    assert answer == '## Страница 1\n\nОцифрованный текст\n\n## Страница 2\n\nОцифрованный текст'
    assert all(payload['messages'][0]['content'][1]['type'] == 'image_url' for _, payload in seen)
    router.settings.max_pdf_pages = 1
    with pytest.raises(ProviderError):
        asyncio.run(router.analyze_file(path, 'application/pdf'))
    assert len(seen) == 2


def test_rendered_pdf_is_png_and_provider_failure_is_reported(tmp_path, monkeypatch):
    path = tmp_path / 'page.pdf'
    pdf = PdfWriter()
    pdf.add_blank_page(width=100, height=100)
    pdf.write(path)
    assert ProviderRouter._vision_pdf_page(path, 1).startswith(b'\x89PNG')
    seen = []
    setup_transport(monkeypatch, seen, status=503)
    image = tmp_path / 'image.png'
    image.write_bytes(b'image')
    router = ProviderRouter(Settings(mock_providers=False, deepseek_api_key='test-key'))
    with pytest.raises(ProviderError, match='HTTP 503'):
        asyncio.run(router.analyze_file(image, 'image/png'))
