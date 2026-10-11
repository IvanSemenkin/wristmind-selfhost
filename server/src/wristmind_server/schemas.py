from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import resolve_model_id


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class DeviceEnrollRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["PHONE", "WATCH", "WEB"]


class PairDeviceRequest(DeviceEnrollRequest):
    code: str = Field(min_length=6, max_length=12)


class DeviceTokenResponse(BaseModel):
    device_id: str
    token: str
    is_admin: bool
    user_id: str | None = None


class PushTokenUpdate(BaseModel):
    token: str = Field(min_length=20, max_length=512)


class WearDiagnosticsUpload(BaseModel):
    lines: list[str] = Field(min_length=1, max_length=240)


class FallbackTicketResponse(BaseModel):
    ticket: str
    expires_at: datetime


class DeviceResponse(ApiModel):
    id: str
    name: str
    kind: str
    is_admin: bool
    user_id: str | None
    created_at: datetime
    last_seen_at: datetime
    revoked_at: datetime | None
    enrolled_ip: str | None = None
    last_ip: str | None = None
    user_agent: str | None = None


class PairingCodeResponse(BaseModel):
    code: str
    expires_at: datetime


class PairingCodeCreate(BaseModel):
    client_request_id: str | None = Field(default=None, min_length=1, max_length=100)


class UserResponse(ApiModel):
    id: str
    name: str
    role: str
    created_at: datetime


class CurrentUserResponse(UserResponse):
    is_admin: bool


class GlobalSettingsResponse(BaseModel):
    developer_mode: bool
    global_system_prompt: str
    source_intent_prompt: str
    source_candidate_prompt: str
    history_message_limit: int
    default_model_id: str
    stream_responses: bool
    retention_days: int


class GlobalSettingsUpdate(BaseModel):
    developer_mode: bool | None = None
    global_system_prompt: str | None = Field(default=None, min_length=1, max_length=20_000)
    source_intent_prompt: str | None = Field(default=None, min_length=20, max_length=20_000)
    source_candidate_prompt: str | None = Field(default=None, min_length=20, max_length=20_000)
    history_message_limit: int | None = Field(default=None, ge=2, le=50)
    default_model_id: str | None = Field(default=None, min_length=1, max_length=160)
    stream_responses: bool | None = None
    retention_days: int | None = Field(default=None, ge=0, le=3650)


class PromptRecord(BaseModel):
    key: str
    label: str
    text: str
    default_text: str
    customized: bool


class PromptUpdate(BaseModel):
    text: str = Field(max_length=20_000)


class DashboardActivityPoint(BaseModel):
    bucket: datetime
    requests: int
    errors: int


class DashboardUsageBreakdown(BaseModel):
    mode_id: str
    requests: int
    tokens: int


class DashboardStatsResponse(ApiModel):
    total_ai_requests: int
    requests_today: int
    requests_yesterday: int
    error_rate_today: float
    activity: list[DashboardActivityPoint]
    usage: list[DashboardUsageBreakdown]


class ModelOptionResponse(BaseModel):
    id: str
    label: str
    provider: str


class ModeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    color: str = Field(default="#65F5C2", pattern=r"^#[0-9A-Fa-f]{6}$")
    icon: str = Field(default="spark", max_length=40)
    telegram_emoji_id: str | None = Field(default=None, max_length=80)
    system_prompt: str = Field(default="", max_length=20_000)
    response_model_id: str = Field(max_length=160)
    hidden_on_watch: bool = False


class ModeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    icon: str | None = Field(default=None, max_length=40)
    telegram_emoji_id: str | None = Field(default=None, max_length=80)
    system_prompt: str | None = Field(default=None, max_length=20_000)
    response_model_id: str | None = Field(default=None, max_length=160)
    hidden_on_watch: bool = False


class ModeResponse(ApiModel):
    id: str
    name: str
    description: str
    color: str
    icon: str
    telegram_emoji_id: str | None
    system_prompt: str
    response_model_id: str
    hidden_on_watch: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None

    @field_validator("response_model_id")
    @classmethod
    def canonical_model_id(cls, value: str) -> str:
        """Present migrated provider ids in their current form without rewriting stored rows."""
        return resolve_model_id(value)


class ChatCreate(BaseModel):
    mode_id: str
    title: str = Field(default="Новый чат", min_length=1, max_length=120)
    client_request_id: str | None = Field(default=None, min_length=1, max_length=100)


class QuickChatCreate(BaseModel):
    client_request_id: str | None = Field(default=None, min_length=1, max_length=100)


class ChatUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    pinned: bool | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Chat title must not be blank")
        return value


class ChatResponse(BaseModel):
    pinned: bool = False
    id: str
    mode_id: str
    mode_name: str
    mode_deleted: bool
    title: str
    created_at: datetime
    updated_at: datetime


class ReferencedSourceResponse(ApiModel):
    """A web page actually supplied to an answer, kept as a read-only audit row."""

    id: str
    title: str
    url: str
    retrieved_at: datetime


class MessageResponse(ApiModel):
    id: str
    chat_id: str
    role: str
    content: str
    status: str
    provider: str | None
    model_id: str | None
    usage: dict[str, Any]
    timings: dict[str, Any]
    created_at: datetime
    # Referenced web sources for this answer. Populated for assistant messages
    # that consulted the web; empty for anything older than the audit trail.
    sources: list[ReferencedSourceResponse] = Field(default_factory=list)


class ChatWorkingSourceResponse(ApiModel):
    """A Working Source owned by one chat.

    Working Sources are chat material, never part of the shared knowledge base,
    so they are read back only through the chat that owns them.
    """

    id: str
    title: str
    origin_url: str | None
    origin_title: str | None
    status: str
    created_at: datetime


class ChatWorkingSourceTextResponse(BaseModel):
    id: str
    title: str
    status: str
    content: str
    character_count: int


class ChatReferencedSourceResponse(ApiModel):
    """A web page this chat saw. Read-only; it is evidence, not RAG content."""

    id: str
    title: str
    url: str
    snippet: str
    retrieved_at: datetime
    message_id: str | None
    # A successful text read, not a search snippet or a model claim.
    read_at: datetime | None = None
    character_count: int = 0


class ChatSourcesResponse(ApiModel):
    """Everything the chat itself found: its Working Sources and web references.

    Referenced entries whose URL already backs a Working Source are omitted, so
    the same page is never listed twice.
    """

    working: list[ChatWorkingSourceResponse] = Field(default_factory=list)
    referenced: list[ChatReferencedSourceResponse] = Field(default_factory=list)


class MessageCreate(BaseModel):
    client_request_id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=20_000)
    web_search: bool = False
    web_research: bool = False
    research_mode: bool = False


class FallbackMessageSync(BaseModel):
    request_id: str = Field(min_length=1, max_length=100)
    user_text: str = Field(min_length=1, max_length=20_000)
    assistant_text: str = Field(min_length=1, max_length=100_000)


class TranscriptionResponse(BaseModel):
    text: str
    language: str = "ru"
    duration_ms: int
    provider: str


class JobResponse(ApiModel):
    id: str
    kind: str
    status: str
    client_request_id: str
    result: dict[str, Any]
    error: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class KnowledgeSourceResponse(ApiModel):
    id: str
    mode_id: str
    title: str
    filename: str
    media_type: str
    processing_mode: str
    source_tier: str
    status: str
    page_count: int
    chunk_count: int
    token_count: int
    error: str | None
    created_at: datetime


class ChatSourceCandidateResponse(BaseModel):
    id: str
    title: str
    url: str
    preview: str
    content: str = ""
    truncated: bool = False


class ChatSourceSaveRequest(BaseModel):
    client_request_id: str = Field(min_length=1, max_length=100)


class KnowledgeChunkResponse(ApiModel):
    id: str
    ordinal: int
    page_from: int | None
    page_to: int | None
    kind: str
    content: str
    token_count: int


class KnowledgeSourceDetailResponse(KnowledgeSourceResponse):
    chunks: list[KnowledgeChunkResponse]
    chunk_offset: int
    chunk_limit: int
    has_more: bool


class KnowledgeReprocessRequest(BaseModel):
    client_request_id: str = Field(min_length=1, max_length=100)
