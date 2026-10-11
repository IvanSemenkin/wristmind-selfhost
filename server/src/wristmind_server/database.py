from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from .config import get_settings
from .assistant_prompt import DEFAULT_GLOBAL_PROMPT
from .source_prompts import DEFAULT_SOURCE_CANDIDATE_PROMPT, DEFAULT_SOURCE_INTENT_PROMPT


LEGACY_DEFAULT_GLOBAL_PROMPT = (
    "Ты — WristMind. Отвечай на языке пользователя кратко, точно и по делу: сначала "
    "прямой ответ, без вступлений и воды. Подробности добавляй только по просьбе или "
    "если без них ответ будет неточным. Проверяй факты и вычисления, не выдумывай "
    "источники; отмечай неопределённость."
)
MINIMAL_DEFAULT_GLOBAL_PROMPT = "Ты — WristMind. Отвечай на языке пользователя кратко и по делу. Не выдумывай факты; если не уверен — скажи."


class Base(DeclarativeBase):
    pass


settings = get_settings()
# SQLite is the test/local engine only, and it is driven from several event
# loops (the test suite calls `asyncio.run` per case). A pooled aiosqlite
# connection stays bound to the loop that created it, so reusing one from
# another loop both leaks state and produces `database is locked` failures
# between concurrent writers. A pool-less engine with a real busy timeout
# removes that whole class of failure. PostgreSQL keeps the normal pool.
if settings.database_url.startswith("sqlite"):
    engine = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        poolclass=NullPool,
        connect_args={"timeout": 30},
    )
else:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session


async def init_database() -> None:
    from . import db_models  # noqa: F401

    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    async with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            # Fresh installs have no tables to ALTER. Create the extension first
            # (Vector columns require it), then create absent tables, then migrate.
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await connection.run_sync(Base.metadata.create_all)
            await connection.execute(text("ALTER TABLE devices ADD COLUMN IF NOT EXISTS user_id VARCHAR(36)"))
            await connection.execute(text("ALTER TABLE devices ADD COLUMN IF NOT EXISTS removed_at TIMESTAMP WITH TIME ZONE"))
            await connection.execute(text("ALTER TABLE devices ADD COLUMN IF NOT EXISTS enrolled_ip VARCHAR(45)"))
            await connection.execute(text("ALTER TABLE devices ADD COLUMN IF NOT EXISTS last_ip VARCHAR(45)"))
            await connection.execute(text("ALTER TABLE devices ADD COLUMN IF NOT EXISTS user_agent VARCHAR(300)"))
            await connection.execute(text("ALTER TABLE pairing_codes ADD COLUMN IF NOT EXISTS user_id VARCHAR(36)"))
            await connection.execute(text("ALTER TABLE pairing_codes ADD COLUMN IF NOT EXISTS client_request_id VARCHAR(100)"))
            await connection.execute(
                text("ALTER TABLE pairing_codes ADD COLUMN IF NOT EXISTS derivation_counter INTEGER NOT NULL DEFAULT 0")
            )
            await connection.execute(text("ALTER TABLE chats ADD COLUMN IF NOT EXISTS user_id VARCHAR(36)"))
            await connection.execute(text("ALTER TABLE chats ADD COLUMN IF NOT EXISTS client_request_id VARCHAR(100)"))
            await connection.execute(text("ALTER TABLE knowledge_sources ADD COLUMN IF NOT EXISTS user_id VARCHAR(36)"))
            await connection.execute(text("ALTER TABLE knowledge_sources ADD COLUMN IF NOT EXISTS chat_id VARCHAR(36)"))
            await connection.execute(text("ALTER TABLE knowledge_sources ADD COLUMN IF NOT EXISTS origin_url VARCHAR(1500)"))
            await connection.execute(
                text("ALTER TABLE knowledge_sources ADD COLUMN IF NOT EXISTS source_tier VARCHAR(20) NOT NULL DEFAULT 'legacy'")
            )
            await connection.execute(text("ALTER TABLE knowledge_sources ADD COLUMN IF NOT EXISTS source_kind VARCHAR(30) NOT NULL DEFAULT 'document'"))
            await connection.execute(text("ALTER TABLE knowledge_sources ADD COLUMN IF NOT EXISTS origin_title VARCHAR(240)"))
            await connection.execute(text("ALTER TABLE knowledge_sources ADD COLUMN IF NOT EXISTS raw_source_id VARCHAR(36)"))
            await connection.execute(text("ALTER TABLE knowledge_sources ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)"))
            await connection.execute(text("ALTER TABLE knowledge_sources ADD COLUMN IF NOT EXISTS extraction_start INTEGER"))
            await connection.execute(text("ALTER TABLE knowledge_sources ADD COLUMN IF NOT EXISTS extraction_end INTEGER"))
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await connection.run_sync(Base.metadata.create_all)
        if connection.dialect.name == "postgresql":
            await connection.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP WITH TIME ZONE"))
            await connection.execute(
                text("ALTER TABLE modes ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT ''")
            )
            await connection.execute(
                text("ALTER TABLE modes ADD COLUMN IF NOT EXISTS hidden_on_watch BOOLEAN NOT NULL DEFAULT FALSE")
            )
            await connection.execute(text("ALTER TABLE modes ADD COLUMN IF NOT EXISTS telegram_emoji_id VARCHAR(80)"))
            await connection.execute(text("ALTER TABLE telegram_accounts ADD COLUMN IF NOT EXISTS emoji_target VARCHAR(120)"))
            await connection.execute(
                text("ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS history_message_limit INTEGER NOT NULL DEFAULT 12")
            )
            await connection.execute(
                text("ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS default_model_id VARCHAR(160) NOT NULL DEFAULT 'openrouter:google/gemini-2.5-flash-lite'")
            )
            await connection.execute(
                text("ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS stream_responses BOOLEAN NOT NULL DEFAULT TRUE")
            )
            await connection.execute(
                text("ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS retention_days INTEGER NOT NULL DEFAULT 90")
            )
            await connection.execute(
                text("ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS developer_mode BOOLEAN NOT NULL DEFAULT FALSE")
            )
            await connection.execute(
                text("ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS source_intent_prompt TEXT")
            )
            await connection.execute(
                text("ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS source_candidate_prompt TEXT")
            )
            await connection.execute(
                text(
                    "UPDATE app_settings SET source_intent_prompt = :prompt "
                    "WHERE source_intent_prompt IS NULL OR BTRIM(source_intent_prompt) = ''"
                ),
                {"prompt": DEFAULT_SOURCE_INTENT_PROMPT},
            )
            await connection.execute(
                text(
                    "UPDATE app_settings SET source_candidate_prompt = :prompt "
                    "WHERE source_candidate_prompt IS NULL OR BTRIM(source_candidate_prompt) = ''"
                ),
                {"prompt": DEFAULT_SOURCE_CANDIDATE_PROMPT},
            )
            await connection.execute(
                text("ALTER TABLE chats ADD COLUMN IF NOT EXISTS title_generation_state VARCHAR(20) NOT NULL DEFAULT 'idle'")
            )
            await connection.execute(text("ALTER TABLE chats ADD COLUMN IF NOT EXISTS pinned BOOLEAN NOT NULL DEFAULT FALSE"))
            await connection.execute(text("ALTER TABLE chats ADD COLUMN IF NOT EXISTS memory_summary TEXT NOT NULL DEFAULT ''"))
            await connection.execute(text("ALTER TABLE chats ADD COLUMN IF NOT EXISTS memory_turn_count INTEGER NOT NULL DEFAULT 0"))
            await connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_chats_user_client_request_id "
                    "ON chats (user_id, client_request_id) WHERE client_request_id IS NOT NULL"
                )
            )
            await connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_pairing_codes_creator_client_request_id "
                    "ON pairing_codes (created_by_id, client_request_id) WHERE client_request_id IS NOT NULL"
                )
            )
        elif connection.dialect.name == "sqlite":
            user_columns = (await connection.execute(text("PRAGMA table_info(users)"))).mappings().all()
            if not any(column["name"] == "deleted_at" for column in user_columns):
                await connection.execute(text("ALTER TABLE users ADD COLUMN deleted_at DATETIME"))
            for table in ("devices", "pairing_codes", "chats", "knowledge_sources"):
                columns = (await connection.execute(text(f"PRAGMA table_info({table})"))).mappings().all()
                if not any(column["name"] == "user_id" for column in columns):
                    await connection.execute(text(f"ALTER TABLE {table} ADD COLUMN user_id TEXT"))
            pairing_columns = (await connection.execute(text("PRAGMA table_info(pairing_codes)"))).mappings().all()
            if not any(column["name"] == "client_request_id" for column in pairing_columns):
                await connection.execute(text("ALTER TABLE pairing_codes ADD COLUMN client_request_id TEXT"))
            if not any(column["name"] == "derivation_counter" for column in pairing_columns):
                await connection.execute(
                    text("ALTER TABLE pairing_codes ADD COLUMN derivation_counter INTEGER NOT NULL DEFAULT 0")
                )
            await connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_pairing_codes_creator_client_request_id "
                    "ON pairing_codes (created_by_id, client_request_id) WHERE client_request_id IS NOT NULL"
                )
            )
            source_columns = (await connection.execute(text("PRAGMA table_info(knowledge_sources)"))).mappings().all()
            if not any(column["name"] == "chat_id" for column in source_columns):
                await connection.execute(text("ALTER TABLE knowledge_sources ADD COLUMN chat_id TEXT"))
            if not any(column["name"] == "origin_url" for column in source_columns):
                await connection.execute(text("ALTER TABLE knowledge_sources ADD COLUMN origin_url TEXT"))
            if not any(column["name"] == "source_tier" for column in source_columns):
                await connection.execute(
                    text("ALTER TABLE knowledge_sources ADD COLUMN source_tier TEXT NOT NULL DEFAULT 'legacy'")
                )
            for column, definition in (
                ("source_kind", "TEXT NOT NULL DEFAULT 'document'"),
                ("origin_title", "TEXT"),
                ("raw_source_id", "TEXT"),
                ("content_hash", "TEXT"),
                ("extraction_start", "INTEGER"),
                ("extraction_end", "INTEGER"),
            ):
                if not any(item["name"] == column for item in source_columns):
                    await connection.execute(text(f"ALTER TABLE knowledge_sources ADD COLUMN {column} {definition}"))
            columns = (await connection.execute(text("PRAGMA table_info(modes)"))).mappings().all()
            if not any(column["name"] == "description" for column in columns):
                await connection.execute(
                    text("ALTER TABLE modes ADD COLUMN description TEXT NOT NULL DEFAULT ''")
                )
            if not any(column["name"] == "hidden_on_watch" for column in columns):
                await connection.execute(
                    text("ALTER TABLE modes ADD COLUMN hidden_on_watch BOOLEAN NOT NULL DEFAULT 0")
                )
            if not any(column["name"] == "telegram_emoji_id" for column in columns):
                await connection.execute(text("ALTER TABLE modes ADD COLUMN telegram_emoji_id TEXT"))
            telegram_columns = (await connection.execute(text("PRAGMA table_info(telegram_accounts)"))).mappings().all()
            if telegram_columns and not any(column["name"] == "emoji_target" for column in telegram_columns):
                await connection.execute(text("ALTER TABLE telegram_accounts ADD COLUMN emoji_target TEXT"))
            settings_columns = (await connection.execute(text("PRAGMA table_info(app_settings)"))).mappings().all()
            if not any(column["name"] == "history_message_limit" for column in settings_columns):
                await connection.execute(
                    text("ALTER TABLE app_settings ADD COLUMN history_message_limit INTEGER NOT NULL DEFAULT 12")
                )
            if not any(column["name"] == "default_model_id" for column in settings_columns):
                await connection.execute(
                    text("ALTER TABLE app_settings ADD COLUMN default_model_id TEXT NOT NULL DEFAULT 'openrouter:google/gemini-2.5-flash-lite'")
                )
            if not any(column["name"] == "stream_responses" for column in settings_columns):
                await connection.execute(text("ALTER TABLE app_settings ADD COLUMN stream_responses BOOLEAN NOT NULL DEFAULT 1"))
            if not any(column["name"] == "retention_days" for column in settings_columns):
                await connection.execute(text("ALTER TABLE app_settings ADD COLUMN retention_days INTEGER NOT NULL DEFAULT 90"))
            if not any(column["name"] == "developer_mode" for column in settings_columns):
                await connection.execute(text("ALTER TABLE app_settings ADD COLUMN developer_mode BOOLEAN NOT NULL DEFAULT 0"))
            if not any(column["name"] == "source_intent_prompt" for column in settings_columns):
                await connection.execute(text("ALTER TABLE app_settings ADD COLUMN source_intent_prompt TEXT"))
            if not any(column["name"] == "source_candidate_prompt" for column in settings_columns):
                await connection.execute(text("ALTER TABLE app_settings ADD COLUMN source_candidate_prompt TEXT"))
            await connection.execute(
                text(
                    "UPDATE app_settings SET source_intent_prompt = :prompt "
                    "WHERE source_intent_prompt IS NULL OR TRIM(source_intent_prompt) = ''"
                ),
                {"prompt": DEFAULT_SOURCE_INTENT_PROMPT},
            )
            await connection.execute(
                text(
                    "UPDATE app_settings SET source_candidate_prompt = :prompt "
                    "WHERE source_candidate_prompt IS NULL OR TRIM(source_candidate_prompt) = ''"
                ),
                {"prompt": DEFAULT_SOURCE_CANDIDATE_PROMPT},
            )
            chat_columns = (await connection.execute(text("PRAGMA table_info(chats)"))).mappings().all()
            if not any(column["name"] == "title_generation_state" for column in chat_columns):
                await connection.execute(
                    text("ALTER TABLE chats ADD COLUMN title_generation_state TEXT NOT NULL DEFAULT 'idle'")
                )
            if not any(column["name"] == "pinned" for column in chat_columns):
                await connection.execute(text("ALTER TABLE chats ADD COLUMN pinned BOOLEAN NOT NULL DEFAULT FALSE"))
            if not any(column["name"] == "memory_summary" for column in chat_columns):
                await connection.execute(text("ALTER TABLE chats ADD COLUMN memory_summary TEXT NOT NULL DEFAULT ''"))
            if not any(column["name"] == "memory_turn_count" for column in chat_columns):
                await connection.execute(text("ALTER TABLE chats ADD COLUMN memory_turn_count INTEGER NOT NULL DEFAULT 0"))
            if not any(column["name"] == "client_request_id" for column in chat_columns):
                await connection.execute(text("ALTER TABLE chats ADD COLUMN client_request_id TEXT"))
            await connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_chats_user_client_request_id "
                    "ON chats (user_id, client_request_id) WHERE client_request_id IS NOT NULL"
                )
            )
        # Upgrade only known factory defaults; never overwrite user instructions.
        await connection.execute(
            text("UPDATE app_settings SET global_system_prompt = :current "
                 "WHERE global_system_prompt IN (:legacy, :minimal)"),
            {"current": DEFAULT_GLOBAL_PROMPT, "legacy": LEGACY_DEFAULT_GLOBAL_PROMPT,
             "minimal": MINIMAL_DEFAULT_GLOBAL_PROMPT},
        )



async def close_database() -> None:
    await engine.dispose()
