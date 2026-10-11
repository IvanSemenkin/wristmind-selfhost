"""State of a material search: recognition, rejection and context exclusion.

The state is what keeps a follow-up question a source-search task and keeps a
document the user rejected out of that task's candidates. It must never start a
search by itself, so the "not alive" cases carry as much weight as the alive one.
"""
from types import SimpleNamespace

import pytest

from wristmind_server.config import get_settings
from wristmind_server.database import SessionFactory
from wristmind_server.db_models import ChatSearchTask, KnowledgeChunk, KnowledgeSource, Mode
from wristmind_server.knowledge import knowledge_context
from wristmind_server.providers import ProviderRouter
from wristmind_server.search_task import (
    SEARCH_TASK_IDLE_LIMIT,
    rejected_source_ids,
    search_task_block,
    task_is_alive,
    with_rejection,
)


def _task(**overrides):
    values = {"statement": "Найди сборник задач по математике", "rejected": [], "idle_turns": 0}
    values.update(overrides)
    return SimpleNamespace(**values)


def test_a_task_without_a_statement_or_too_idle_is_not_used():
    assert task_is_alive(None) is False
    assert task_is_alive(_task(statement="")) is False
    assert task_is_alive(_task(statement="   ")) is False
    assert task_is_alive(_task(idle_turns=SEARCH_TASK_IDLE_LIMIT)) is True
    # A conversation that moved on must not drag a stale task back onto the web.
    assert task_is_alive(_task(idle_turns=SEARCH_TASK_IDLE_LIMIT + 1)) is False


def test_the_router_sees_the_task_and_what_was_rejected():
    block = search_task_block(
        _task(rejected=["src-1", "src-2"]),
        {"src-1": "Стратегии", "src-2": "Другой сборник"},
    )

    assert "Найди сборник задач по математике" in block
    assert "Стратегии" in block and "Другой сборник" in block
    assert "уже отклонил" in block


def test_an_ordinary_question_gets_no_reason_to_search():
    assert search_task_block(None) == ""
    assert search_task_block(_task(idle_turns=SEARCH_TASK_IDLE_LIMIT + 1)) == ""
    # A task with nothing rejected still describes what is being looked for.
    assert "уже отклонил" not in search_task_block(_task())


def test_rejections_are_a_plain_set_and_never_duplicated():
    assert rejected_source_ids(None) == set()
    assert rejected_source_ids(_task(rejected=None)) == set()
    assert rejected_source_ids(_task(rejected=["a", "b", "a"])) == {"a", "b"}
    assert with_rejection(["a"], "b") == ["a", "b"]
    assert with_rejection(["a"], "a") == ["a"]
    assert with_rejection(None, "a") == ["a"]
    assert with_rejection(["a"], None) == ["a"]


@pytest.mark.asyncio
async def test_the_state_is_stored_and_read_back():
    async with SessionFactory() as session:
        session.add(ChatSearchTask(
            chat_id="chat-with-task",
            statement="Найди сборник «Стратегии»",
            statement_message_id="m-1",
            rejected=["src-old"],
            idle_turns=2,
        ))
        await session.commit()

    async with SessionFactory() as session:
        stored = await session.get(ChatSearchTask, "chat-with-task")

    assert stored is not None
    assert stored.statement == "Найди сборник «Стратегии»"
    assert rejected_source_ids(stored) == {"src-old"}
    assert task_is_alive(stored) is True


async def _working_source(session, mode, chat_id: str, title: str, text: str):
    source = KnowledgeSource(
        mode_id=mode.id, chat_id=chat_id, title=title, filename="source.txt",
        media_type="text/plain", processing_mode="WEB", source_tier="working",
        storage_path="unused-in-this-test", status="ready",
        chunk_count=1, token_count=4,
    )
    session.add(source)
    await session.flush()
    session.add(KnowledgeChunk(
        source_id=source.id, ordinal=0, content=text, token_count=4, embedding=None,
    ))
    await session.flush()
    return source


@pytest.mark.asyncio
async def test_a_rejected_document_leaves_the_candidates_of_this_task():
    """Exclusion is per task: the row stays stored and readable."""
    settings = get_settings()
    async with SessionFactory() as session:
        mode = Mode(
            name="Математика", color="#65F5C2", icon="book", system_prompt="",
            response_model_id="openrouter:google/gemini-2.5-flash-lite",
        )
        session.add(mode)
        await session.flush()
        rejected = await _working_source(
            session, mode, "chat-exclusion", "Стратегии", "Условие задачи 7.13 про бревно",
        )
        kept = await _working_source(
            session, mode, "chat-exclusion", "Нужный сборник", "Условие задачи 11 про сани",
        )
        await session.commit()

        without_exclusion, _ = await knowledge_context(
            session, mode.id, "задача про сани", ProviderRouter(settings), settings,
            chat_id="chat-exclusion",
        )
        assert "бревно" in without_exclusion and "сани" in without_exclusion

        filtered, meta = await knowledge_context(
            session, mode.id, "задача про сани", ProviderRouter(settings), settings,
            chat_id="chat-exclusion", exclude_source_ids={rejected.id},
        )

        assert "сани" in filtered
        assert "бревно" not in filtered
        assert meta["chat_source_titles"] == [kept.title]
        # The excluded document is still stored: nothing was deleted.
        assert (await session.get(KnowledgeSource, rejected.id)) is not None
