from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .source_prompts import DEFAULT_SOURCE_CANDIDATE_PROMPT, DEFAULT_SOURCE_INTENT_PROMPT

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(20))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enrolled_ip: Mapped[str | None] = mapped_column(String(45))
    last_ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(300))


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    role: Mapped[str] = mapped_column(String(20), default="USER")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PairingCode(Base):
    __tablename__ = "pairing_codes"
    __table_args__ = (UniqueConstraint("created_by_id", "client_request_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[str] = mapped_column(ForeignKey("devices.id"))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    client_request_id: Mapped[str | None] = mapped_column(String(100))
    derivation_counter: Mapped[int] = mapped_column(Integer, default=0)


class PushRegistration(Base):
    __tablename__ = "push_registrations"

    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"), primary_key=True)
    token: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AppSettings(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    global_system_prompt: Mapped[str] = mapped_column(
        Text,
        default="Ты — WristMind. Отвечай на языке пользователя кратко и по делу. Не выдумывай факты; если не уверен — скажи.",
    )
    source_intent_prompt: Mapped[str] = mapped_column(Text, default=DEFAULT_SOURCE_INTENT_PROMPT)
    source_candidate_prompt: Mapped[str] = mapped_column(Text, default=DEFAULT_SOURCE_CANDIDATE_PROMPT)
    developer_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    history_message_limit: Mapped[int] = mapped_column(Integer, default=12)
    default_model_id: Mapped[str] = mapped_column(String(160), default="openrouter:google/gemini-2.5-flash-lite")
    stream_responses: Mapped[bool] = mapped_column(Boolean, default=True)
    retention_days: Mapped[int] = mapped_column(Integer, default=90)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class PromptOverride(Base):
    __tablename__ = "prompt_overrides"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Mode(Base):
    __tablename__ = "modes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    color: Mapped[str] = mapped_column(String(16), default="#65F5C2")
    icon: Mapped[str] = mapped_column(String(40), default="spark")
    # Telegram custom emoji are opaque IDs. Keep `icon` for the web and Wear UI.
    telegram_emoji_id: Mapped[str | None] = mapped_column(String(80))
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    response_model_id: Mapped[str] = mapped_column(String(160))
    hidden_on_watch: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    chats: Mapped[list["Chat"]] = relationship(back_populates="mode")
    sources: Mapped[list["KnowledgeSource"]] = relationship(back_populates="mode")


class Chat(Base):
    __tablename__ = "chats"
    __table_args__ = (
        Index(
            "uq_chats_user_client_request_id",
            "user_id",
            "client_request_id",
            unique=True,
            postgresql_where=text("client_request_id IS NOT NULL"),
            sqlite_where=text("client_request_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    mode_id: Mapped[str] = mapped_column(ForeignKey("modes.id"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    client_request_id: Mapped[str | None] = mapped_column(String(100))
    mode_name_snapshot: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(120), default="Новый чат")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    # `idle` → `queued` → `complete` is deliberately durable: a title is generated
    # at most once and a manual rename can always stop a queued generation.
    title_generation_state: Mapped[str] = mapped_column(String(20), default="idle")
    memory_summary: Mapped[str] = mapped_column(Text, default="")
    memory_turn_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    mode: Mapped[Mode] = relationship(back_populates="chats")
    messages: Mapped[list["Message"]] = relationship(back_populates="chat", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    chat_id: Mapped[str] = mapped_column(ForeignKey("chats.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="complete")
    provider: Mapped[str | None] = mapped_column(String(40))
    model_id: Mapped[str | None] = mapped_column(String(160))
    usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    timings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    chat: Mapped[Chat] = relationship(back_populates="messages")


class TelegramAccount(Base):
    """One approved Telegram private chat attached to one WristMind user."""

    __tablename__ = "telegram_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    telegram_user_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    chat_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"), unique=True, index=True)
    selected_mode_id: Mapped[str | None] = mapped_column(ForeignKey("modes.id"))
    active_chat_id: Mapped[str | None] = mapped_column(ForeignKey("chats.id"))
    emoji_target: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class TelegramEmojiDraft(Base):
    """A collected custom emoji and the UI slot it is intended for."""

    __tablename__ = "telegram_emoji_drafts"
    __table_args__ = (UniqueConstraint("user_id", "slot"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    slot: Mapped[str] = mapped_column(String(120))
    custom_emoji_id: Mapped[str] = mapped_column(String(80))
    purpose: Mapped[str] = mapped_column(String(240))
    example: Mapped[str] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class KnowledgeSource(Base):
    __tablename__ = "knowledge_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    mode_id: Mapped[str] = mapped_column(ForeignKey("modes.id"), index=True)
    # A source saved from search belongs to one conversation, never to every
    # chat that happens to use the same mode.
    chat_id: Mapped[str | None] = mapped_column(ForeignKey("chats.id"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    filename: Mapped[str] = mapped_column(String(240))
    media_type: Mapped[str] = mapped_column(String(100))
    processing_mode: Mapped[str] = mapped_column(String(20))
    # Only Working Sources belong to the new search pipeline. Existing global
    # sources retain the neutral legacy value and remain a separate feature.
    source_tier: Mapped[str] = mapped_column(String(20), default="legacy")
    source_kind: Mapped[str] = mapped_column(String(30), default="document")
    origin_url: Mapped[str | None] = mapped_column(String(1_500))
    origin_title: Mapped[str | None] = mapped_column(String(240))
    raw_source_id: Mapped[str | None] = mapped_column(ForeignKey("raw_web_sources.id"), index=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    extraction_start: Mapped[int | None] = mapped_column(Integer)
    extraction_end: Mapped[int | None] = mapped_column(Integer)
    storage_path: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    mode: Mapped[Mode] = relationship(back_populates="sources")
    chunks: Mapped[list["KnowledgeChunk"]] = relationship(
        back_populates="source", cascade="all, delete-orphan", order_by="KnowledgeChunk.ordinal"
    )


class ChatSourceCandidate(Base):
    """A fetched page awaiting an explicit save decision in one chat."""

    __tablename__ = "chat_source_candidates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    chat_id: Mapped[str] = mapped_column(ForeignKey("chats.id"), index=True)
    title: Mapped[str] = mapped_column(String(240))
    url: Mapped[str] = mapped_column(String(1_500))
    content: Mapped[str] = mapped_column(Text)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    saved_source_id: Mapped[str | None] = mapped_column(ForeignKey("knowledge_sources.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChatSearchTask(Base):
    """Durable state of the material search in one chat.

    Written by the server only. A model may describe what the user is looking
    for, but "the user rejected this document" is a fact about the conversation,
    and the next turn has to be able to rely on it. The row keeps a follow-up
    question a source-search task and keeps a rejected document out of that
    task's candidates. It never starts a search by itself: the router decides
    every turn, and a task that has been idle for several turns is ignored.
    """

    __tablename__ = "chat_search_tasks"

    chat_id: Mapped[str] = mapped_column(ForeignKey("chats.id"), primary_key=True)
    # The request that opened the task, as the server recorded it.
    statement: Mapped[str] = mapped_column(Text, default="")
    statement_message_id: Mapped[str | None] = mapped_column(String(36))
    # The saved source this task currently rests on, if any.
    confirmed_source_id: Mapped[str | None] = mapped_column(String(36))
    # Source ids the user rejected for this task. Stored, never deleted.
    rejected: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Turns without material activity; the task stops being shown to the router
    # once the conversation has clearly moved on.
    idle_turns: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ReferencedWebSource(Base):
    """A lightweight audit trail for web evidence; it is not RAG content."""

    __tablename__ = "referenced_web_sources"
    __table_args__ = (UniqueConstraint("chat_id", "url"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    chat_id: Mapped[str] = mapped_column(ForeignKey("chats.id"), index=True)
    message_id: Mapped[str | None] = mapped_column(ForeignKey("messages.id"), index=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id"), index=True)
    url: Mapped[str] = mapped_column(String(1_500))
    title: Mapped[str] = mapped_column(String(240))
    snippet: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str | None] = mapped_column(Text)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RawWebSource(Base):
    """Cleaned, immutable page text used to prove a Working Source's origin."""

    __tablename__ = "raw_web_sources"
    __table_args__ = (UniqueConstraint("chat_id", "url"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    chat_id: Mapped[str] = mapped_column(ForeignKey("chats.id"), index=True)
    url: Mapped[str] = mapped_column(String(1_500))
    title: Mapped[str] = mapped_column(String(240))
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (UniqueConstraint("source_id", "ordinal"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(ForeignKey("knowledge_sources.id"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    page_from: Mapped[int | None] = mapped_column(Integer)
    page_to: Mapped[int | None] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(30), default="text")
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))

    source: Mapped[KnowledgeSource] = relationship(back_populates="chunks")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("device_id", "client_request_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(30), index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"), index=True)
    client_request_id: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    events: Mapped[list["JobEvent"]] = relationship(back_populates="job", cascade="all, delete-orphan")


class JobEvent(Base):
    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    event: Mapped[str] = mapped_column(String(40))
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    job: Mapped[Job] = relationship(back_populates="events")


class AccountEvent(Base):
    """Durable account-level event log for the control panel.

    Mirrors `job_events`, but for whole-surface changes instead of one job: the
    panel resumes from a numeric cursor over `GET /v1/events` instead of polling
    every list endpoint. A row is written in the same transaction as the mutation
    it describes, so a stream reader can never observe a change that was rolled
    back, or miss one that was committed.

    `owner_id` is NULL for admin-managed shared data (modes, global settings,
    prompts) that every owner is allowed to see; per-surface data carries its
    owner so one account's stream never exposes another's rows.
    """

    __tablename__ = "account_events"
    __table_args__ = (Index("ix_account_events_owner_id_id", "owner_id", "id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[str | None] = mapped_column(String(36), index=True)
    type: Mapped[str] = mapped_column(String(60))
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class SelfHostAdmin(Base):
    """Single installation owner; password login is independent of device pairing."""
    __tablename__ = "selfhost_admin"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    login: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    first_mode_id: Mapped[str | None] = mapped_column(ForeignKey("modes.id"))
    probe_passed: Mapped[bool] = mapped_column(Boolean, default=False)


class SelfHostWebSession(Base):
    __tablename__ = "selfhost_web_sessions"
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
