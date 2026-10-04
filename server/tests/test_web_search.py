import asyncio

import httpx
import pytest

from wristmind_server.web_search import (
    WebSearchUnavailable,
    _validate_public_web_url,
    open_web_page,
    search_snippets_are_sufficient,
    search_web,
    web_search_prompt,
    web_search_sources,
)


def test_search_keeps_only_public_http_results_and_limits_them():
    async def scenario():
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "results": [
                        {"title": "Официальный источник", "url": "https://example.org/a", "content": "Короткий факт"},
                        {"title": "Локальный адрес", "url": "file:///private", "content": "skip"},
                        {"title": "Второй", "url": "http://example.org/b", "content": "Ещё факт"},
                    ]
                },
            )
        )
        original = httpx.AsyncClient

        class Client(httpx.AsyncClient):
            def __init__(self, *args, **kwargs):
                kwargs["transport"] = transport
                super().__init__(*args, **kwargs)

        httpx.AsyncClient = Client
        try:
            return await search_web("http://searxng:8080", "проверка", timeout_seconds=1, result_limit=1)
        finally:
            httpx.AsyncClient = original

    results = asyncio.run(scenario())

    assert [result.title for result in results] == ["Официальный источник"]
    assert "[1]" in web_search_prompt(results)
    assert "https://example.org/a" in web_search_sources(results)


def test_sufficient_snippets_use_the_fast_answer_path():
    rich_results = [
        type("Result", (), {"snippet": "факт " * 100})(),
        type("Result", (), {"snippet": "данные " * 100})(),
        type("Result", (), {"snippet": "пример " * 100})(),
    ]
    assert search_snippets_are_sufficient(rich_results)
    assert not search_snippets_are_sufficient(rich_results[:2])


def test_open_rejects_private_and_local_addresses():
    async def scenario():
        for url in (
            "http://127.0.0.1/secret",
            "http://192.168.0.1/secret",
            "http://10.0.0.1/secret",
            "http://172.20.0.1/secret",
            "http://localhost/secret",
        ):
            with pytest.raises(WebSearchUnavailable):
                await _validate_public_web_url(url)

    asyncio.run(scenario())


def test_open_checks_redirect_target_and_download_size(monkeypatch):
    async def public_host(*_args):
        return None

    monkeypatch.setattr("wristmind_server.web_search._resolve_public_host", public_host)
    redirect_transport = httpx.MockTransport(
        lambda request: httpx.Response(302, headers={"location": "http://127.0.0.1/private"})
    )
    original = httpx.AsyncClient

    class Client(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = redirect_transport
            super().__init__(*args, **kwargs)

    async def redirect_scenario():
        httpx.AsyncClient = Client
        try:
            with pytest.raises(WebSearchUnavailable):
                await open_web_page(
                    "https://example.org/a", timeout_seconds=1, max_download_bytes=100, max_redirects=3
                )
        finally:
            httpx.AsyncClient = original

    asyncio.run(redirect_scenario())

    large_transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * 101))

    class LargeClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = large_transport
            super().__init__(*args, **kwargs)

    async def size_scenario():
        httpx.AsyncClient = LargeClient
        try:
            with pytest.raises(WebSearchUnavailable):
                await open_web_page(
                    "https://example.org/a", timeout_seconds=1, max_download_bytes=100, max_redirects=3
                )
        finally:
            httpx.AsyncClient = original

    asyncio.run(size_scenario())
