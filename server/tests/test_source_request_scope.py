import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from wristmind_server.worker import (
    delete_requested_chat_sources, extract_working_excerpt, providers,
)


def test_requested_excerpt_is_exact_and_does_not_expand_to_page(monkeypatch):
    excerpt = 'Нужный абзац из восьмой главы.'
    page = 'Заголовок\n' + excerpt + '\nДругая часть главы.'

    async def stream(*args, **kwargs):
        yield json.dumps({'title': 'Отрывок VIII', 'excerpt': excerpt})

    monkeypatch.setattr(providers, 'stream_answer', stream)
    result = asyncio.run(extract_working_excerpt('mock:test', 'Найди отрывок', 'Глава VIII', page, excerpt_only=True))
    assert result.excerpt == excerpt


def test_failed_or_whole_page_excerpt_never_falls_back_to_full_page(monkeypatch):
    page = 'Полная глава. ' * 200
    for reply in ('bad JSON', json.dumps({'title': 'Глава', 'excerpt': page})):
        async def stream(*args, **kwargs):
            yield reply
        monkeypatch.setattr(providers, 'stream_answer', stream)
        assert asyncio.run(extract_working_excerpt('mock:test', 'Отрывок', 'Глава', page, excerpt_only=True)) is None


def test_source_delete_is_soft_and_rejects_unknown_or_other_chat_ids():
    source = SimpleNamespace(id='current-source', title='Глава VII', deleted_at=None)
    class Result:
        def all(self):
            return [source]
    session = SimpleNamespace(scalars=AsyncMock(return_value=Result()))
    chat = SimpleNamespace(id='current-chat', user_id='owner')
    async def run():
        answer = await delete_requested_chat_sources(session, chat, ['other-source'])
        assert 'Уточни' in answer
        assert source.deleted_at is None
        answer = await delete_requested_chat_sources(session, chat, [])
        assert 'Уточни' in answer
        assert source.deleted_at is None
        answer = await delete_requested_chat_sources(session, chat, [source.id])
        assert 'Удалены' in answer
        assert source.deleted_at is not None
    asyncio.run(run())
    query = str(session.scalars.call_args.args[0])
    assert 'knowledge_sources.chat_id =' in query
    assert 'knowledge_sources.user_id =' in query
    assert 'knowledge_sources.deleted_at IS NULL' in query
