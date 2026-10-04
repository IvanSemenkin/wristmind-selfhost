import pytest
from unittest.mock import AsyncMock

from wristmind_server.config import get_settings
from wristmind_server.database import SessionFactory
from wristmind_server.db_models import KnowledgeChunk, KnowledgeSource, Mode
from wristmind_server.knowledge import ExtractedDocument, chunk_document_with_pages, knowledge_context
from wristmind_server.providers import ProviderRouter


def test_chunking_preserves_pdf_page_numbers():
    document = ExtractedDocument(
        text="Первая страница\n\nВторая страница",
        pages=2,
        kind="pdf",
        page_texts=("Первая страница", "Вторая страница"),
    )

    chunks = chunk_document_with_pages(document)

    assert chunks == [
        ("Первая страница", 1, 1),
        ("Вторая страница", 2, 2),
    ]


@pytest.mark.asyncio
async def test_small_knowledge_uses_full_context_and_large_knowledge_uses_budget():
    async with SessionFactory() as session:
        mode = Mode(
            name="Математика",
            color="#65F5C2",
            icon="calculate",
            system_prompt="",
            response_model_id="openrouter:google/gemini-2.5-flash-lite",
        )
        session.add(mode)
        await session.flush()
        source = KnowledgeSource(
            mode_id=mode.id,
            title="Конспект",
            filename="notes.pdf",
            media_type="application/pdf",
            processing_mode="OCR",
            storage_path="unused-in-this-test",
            status="ready",
            page_count=2,
            chunk_count=2,
            token_count=8,
        )
        session.add(source)
        await session.flush()
        session.add_all(
            [
                KnowledgeChunk(
                    source_id=source.id,
                    ordinal=0,
                    page_from=1,
                    page_to=1,
                    content="Теорема Пифагора для прямоугольного треугольника",
                    token_count=4,
                    embedding=None,
                ),
                KnowledgeChunk(
                    source_id=source.id,
                    ordinal=1,
                    page_from=2,
                    page_to=2,
                    content="Правила сложения обыкновенных дробей",
                    token_count=4,
                    embedding=None,
                ),
            ]
        )
        await session.commit()

        full_settings = get_settings().model_copy(
            update={"full_context_threshold_tokens": 8, "retrieval_context_budget_tokens": 4}
        )
        full, full_meta = await knowledge_context(
            session, mode.id, "теорема", ProviderRouter(full_settings), full_settings
        )
        assert full_meta["strategy"] == "full"
        assert "Пифагора" in full and "дробей" in full

        hybrid_settings = full_settings.model_copy(update={"full_context_threshold_tokens": 7})
        hybrid, hybrid_meta = await knowledge_context(
            session, mode.id, "теорема Пифагора", ProviderRouter(hybrid_settings), hybrid_settings
        )
        assert hybrid_meta == {"strategy": "hybrid", "source_tokens": 8, "context_tokens": 4}
        assert "Пифагора" in hybrid
        assert "дробей" not in hybrid


@pytest.mark.asyncio
async def test_chat_source_is_marked_as_the_default_conversation_material():
    async with SessionFactory() as session:
        mode = Mode(
            name="Литература",
            color="#65F5C2",
            icon="book",
            system_prompt="",
            response_model_id="openrouter:google/gemini-2.5-flash-lite",
        )
        session.add(mode)
        await session.flush()
        source = KnowledgeSource(
            mode_id=mode.id,
            chat_id="chat-with-saved-source",
            title="Месть фокусника",
            filename="source.txt",
            media_type="text/plain",
            processing_mode="WEB",
            storage_path="unused-in-this-test",
            status="ready",
            chunk_count=1,
            token_count=4,
        )
        session.add(source)
        await session.flush()
        session.add(
            KnowledgeChunk(
                source_id=source.id,
                ordinal=0,
                content="Полный текст сохранённого рассказа",
                token_count=4,
                embedding=None,
            )
        )
        await session.commit()

        settings = get_settings()
        context, meta = await knowledge_context(
            session,
            mode.id,
            "Напиши сочинение",
            ProviderRouter(settings),
            settings,
            chat_id="chat-with-saved-source",
        )

        assert "Полный текст" in context
        assert meta["chat_source_count"] == 1
        assert meta["chat_source_titles"] == ["Месть фокусника"]


async def _chat_working_source(session, mode, chat_id: str, chunks: list[tuple[str, int]]):
    source = KnowledgeSource(
        mode_id=mode.id,
        chat_id=chat_id,
        title="Колобок",
        filename="source.txt",
        media_type="text/plain",
        processing_mode="WEB",
        source_tier="working",
        origin_url="https://example.test/kolobok",
        storage_path="unused-in-this-test",
        status="ready",
        chunk_count=len(chunks),
        token_count=sum(tokens for _, tokens in chunks),
    )
    session.add(source)
    await session.flush()
    for ordinal, (content, tokens) in enumerate(chunks):
        session.add(
            KnowledgeChunk(
                source_id=source.id, ordinal=ordinal, content=content,
                token_count=tokens, embedding=None,
            )
        )
    await session.flush()
    return source


@pytest.mark.asyncio
async def test_chat_working_source_is_passed_in_full_when_it_fits():
    """The whole saved text reaches the prompt, not a relevance sample of it."""
    async with SessionFactory() as session:
        mode = Mode(
            name="Литература", color="#65F5C2", icon="book", system_prompt="",
            response_model_id="openrouter:google/gemini-2.5-flash-lite",
        )
        session.add(mode)
        await session.flush()
        await _chat_working_source(session, mode, "chat-essay", [
            ("Начало сказки, которое совсем не похоже на запрос", 3),
            ("Концовка сказки, тоже без совпадений с запросом", 3),
        ])
        # Mode material competes for the same budget and must not win over the
        # chat's own material when that material fits.
        mode_source = KnowledgeSource(
            mode_id=mode.id, title="Конспект", filename="notes.txt",
            media_type="text/plain", processing_mode="OCR",
            storage_path="unused", status="ready", chunk_count=1, token_count=1,
        )
        session.add(mode_source)
        await session.flush()
        session.add(KnowledgeChunk(
            source_id=mode_source.id, ordinal=0,
            content="Совпадает с запросом сочинение", token_count=1, embedding=None,
        ))
        await session.commit()

        settings = get_settings().model_copy(update={
            "full_context_threshold_tokens": 1,
            "retrieval_context_budget_tokens": 6,
        })
        context, meta = await knowledge_context(
            session, mode.id, "сочинение", ProviderRouter(settings), settings,
            chat_id="chat-essay",
        )

        assert meta["strategy"] == "full_sources"
        assert meta["full_source_count"] == 1
        assert meta["full_source_tokens"] == 6
        assert meta["context_tokens"] == 6
        # Both ends of the saved text survive, in document order, even though
        # neither overlaps the query.
        assert "Начало сказки" in context and "Концовка сказки" in context
        assert context.index("Начало сказки") < context.index("Концовка сказки")
        # The budget is fully spent on the chat material, so nothing else leaks in.
        assert "Совпадает с запросом" not in context
        assert meta["chat_source_titles"] == ["Колобок"]


@pytest.mark.asyncio
async def test_only_working_source_needs_no_embedding_when_it_fits():
    async with SessionFactory() as session:
        mode = Mode(
            name="Литература", color="#65F5C2", icon="book", system_prompt="",
            response_model_id="openrouter:google/gemini-2.5-flash-lite",
        )
        session.add(mode)
        await session.flush()
        await _chat_working_source(session, mode, "chat-only-source", [
            ("Начало сказки", 3), ("Конец сказки", 3),
        ])
        await session.commit()

        settings = get_settings().model_copy(update={
            "full_context_threshold_tokens": 1,
            "retrieval_context_budget_tokens": 100,
        })
        provider = ProviderRouter(settings)
        provider.embed = AsyncMock(side_effect=AssertionError("embedding must not be called"))
        context, meta = await knowledge_context(
            session, mode.id, "что дальше", provider, settings, chat_id="chat-only-source",
        )

        provider.embed.assert_not_called()
        assert meta["strategy"] == "full_sources"
        assert meta["context_tokens"] == 6
        assert "Начало сказки" in context and "Конец сказки" in context


@pytest.mark.asyncio
async def test_chat_working_source_is_ranked_when_it_does_not_fit():
    async with SessionFactory() as session:
        mode = Mode(
            name="Литература", color="#65F5C2", icon="book", system_prompt="",
            response_model_id="openrouter:google/gemini-2.5-flash-lite",
        )
        session.add(mode)
        await session.flush()
        await _chat_working_source(session, mode, "chat-big", [
            ("Первая половина текста", 5),
            ("Вторая половина текста", 5),
        ])
        await session.commit()

        settings = get_settings().model_copy(update={
            "full_context_threshold_tokens": 1,
            "retrieval_context_budget_tokens": 4,
        })
        context, meta = await knowledge_context(
            session, mode.id, "текст", ProviderRouter(settings), settings, chat_id="chat-big",
        )

        # 10 tokens cannot be pinned into a 4 token budget: ranking is unchanged.
        assert meta["strategy"] == "hybrid"
        assert "full_source_count" not in meta
        # Only one half made it, so the material was not read whole.
        present = [text for text in ("Первая половина", "Вторая половина") if text in context]
        assert len(present) == 1, context
        assert meta["context_tokens"] < meta["source_tokens"]


@pytest.mark.asyncio
async def test_pinning_can_be_switched_off():
    async with SessionFactory() as session:
        mode = Mode(
            name="Литература", color="#65F5C2", icon="book", system_prompt="",
            response_model_id="openrouter:google/gemini-2.5-flash-lite",
        )
        session.add(mode)
        await session.flush()
        await _chat_working_source(session, mode, "chat-off", [("Единственный кусок", 2)])
        await session.commit()

        settings = get_settings().model_copy(update={
            "full_context_threshold_tokens": 1,
            "retrieval_context_budget_tokens": 8,
            "full_working_source_context": False,
        })
        _, meta = await knowledge_context(
            session, mode.id, "кусок", ProviderRouter(settings), settings, chat_id="chat-off",
        )

        assert meta["strategy"] == "hybrid"
        assert "full_source_count" not in meta
