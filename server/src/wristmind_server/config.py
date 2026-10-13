from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .provider_connections import ProviderConnection


class ModelOption(BaseModel):
    id: str
    label: str
    provider: str


# DeepSeek is served by its own API, not through OpenRouter. The former
# OpenRouter catalog id is kept as an alias so already-saved modes, chats and
# `WRISTMIND_DEFAULT_MODEL_ID` / `WRISTMIND_QUICK_CHAT_MODEL_ID` keep working
# and are routed to the official API without touching stored data.
DEEPSEEK_MODEL_ID = "deepseek:deepseek-flash"
LEGACY_DEEPSEEK_MODEL_ID = "openrouter:deepseek/deepseek-v4-flash-0731"
LEGACY_MODEL_ALIASES = {LEGACY_DEEPSEEK_MODEL_ID: DEEPSEEK_MODEL_ID}


def resolve_model_id(model_id: str) -> str:
    return LEGACY_MODEL_ALIASES.get(model_id, model_id)


def default_models() -> list[ModelOption]:
    return [
        ModelOption(
            id="openrouter:google/gemini-2.5-flash-lite",
            label="Gemini 2.5 Flash Lite",
            provider="openrouter",
        ),
        ModelOption(
            id=DEEPSEEK_MODEL_ID,
            label="DeepSeek V4 Flash",
            provider="deepseek",
        ),
        ModelOption(
            id="openrouter:qwen/qwen3.8-flash",
            label="Qwen3.8 Flash",
            provider="openrouter",
        ),
        ModelOption(
            id="gigachat:GigaChat-2",
            label="GigaChat",
            provider="gigachat",
        ),
    ]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="WRISTMIND_",
        extra="ignore",
    )

    selfhost_features: dict[str, bool] = {}
    model_roles: dict[str, str] = {}
    selfhost_enabled: bool = False
    selfhost_setup_token: SecretStr | None = None

    environment: str = "development"
    database_url: str = "sqlite+aiosqlite:///./data/wristmind.db"
    storage_dir: Path = Path("data/private")
    firebase_credentials_path: Path | None = None
    bootstrap_secret: SecretStr = SecretStr("change-me-before-production")
    token_pepper: SecretStr = SecretStr("development-only-pepper")
    public_base_url: str = "http://127.0.0.1:8000"
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    provider_connections: list[ProviderConnection] = []
    allowed_models: list[ModelOption] = default_models()
    default_model_id: str = "openrouter:google/gemini-2.5-flash-lite"
    quick_chat_model_id: str = "openrouter:qwen/qwen3.8-flash"
    # A title is a tiny background task, so it never uses the mode's answer model.
    title_model_id: str = "openrouter:google/gemini-2.5-flash-lite"
    # AUTO routing is independent of title generation and final answer models.
    router_model_id: str = DEEPSEEK_MODEL_ID

    openrouter_api_key: SecretStr | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    # DeepSeek defaults to thinking mode with effort `high`; `low` keeps the
    # reasoning benefit without making the first visible token wait too long.
    deepseek_reasoning_effort: str = "low"
    vision_model: str = "deepseek-flash"
    stt_model: str = "openai/gpt-4o-mini-transcribe"
    yandex_speechkit_api_key: SecretStr | None = None
    embedding_model: str = "openai/text-embedding-3-small"

    gigachat_credentials: SecretStr | None = None
    gigachat_scope: str = "GIGACHAT_API_PERS"
    gigachat_auth_url: str = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    gigachat_base_url: str = "https://api.giga.chat/v1"
    # The legacy OAuth gateway presents a self-signed chain. Keep this explicit
    # and configurable so deployments can turn verification on when they have
    # installed the Sber CA certificate.
    gigachat_verify_ssl: bool = False

    full_context_threshold_tokens: int = 12_000
    retrieval_context_budget_tokens: int = 6_000
    # A chat's Working Sources are its own durable material. When they all fit
    # in the retrieval budget they are passed in full instead of competing with
    # the mode knowledge base for ranked chunks, so an answer can really read the
    # whole saved text. The prompt never grows: the pinned material is taken out
    # of the same budget.
    full_working_source_context: bool = True
    max_upload_bytes: int = 50_000_000
    max_pdf_pages: int = 300
    worker_poll_seconds: float = 0.5
    searxng_url: str | None = None
    search_provider: str = "searxng"
    search_api_key: SecretStr | None = None
    search_folder_id: str = ""
    web_search_timeout_seconds: float = 12.0
    web_search_results_limit: int = 5
    web_open_timeout_seconds: float = 8.0
    web_open_max_download_bytes: int = Field(default=2_000_000, ge=1, le=8_000_000)
    web_html_max_document_chars: int = Field(default=1_000_000, ge=12_000, le=4_000_000)
    web_model_fragment_chars: int = Field(default=12_000, ge=2_048, le=32_000)
    web_html_memory_mb: int = Field(default=256, ge=128, le=512)
    web_html_extract_seconds: float = Field(default=12.0, gt=0, le=60)
    resource_busy_memory_mb: int = Field(default=900, ge=256, le=8192)
    resource_critical_memory_mb: int = Field(default=500, ge=128, le=4096)
    resource_hysteresis_memory_mb: int = Field(default=150, ge=32, le=1024)
    resource_free_memory_mb: int = Field(default=1400, ge=512, le=16384)
    resource_wait_seconds: float = Field(default=10.0, gt=0, le=30)
    resource_max_waiters: int = Field(default=32, ge=1, le=128)
    web_comparison_parallel_read: bool = True
    web_cache_news_ttl_seconds: int = Field(default=3600, ge=0)
    web_cache_page_ttl_seconds: int = Field(default=86400, ge=0)
    web_cache_document_ttl_seconds: int = Field(default=604800, ge=0)
    web_cache_static_ttl_seconds: int = Field(default=7776000, ge=0)
    web_cache_max_entries: int = Field(default=512, ge=0)
    web_cache_max_bytes: int = Field(default=64_000_000, ge=0)
    web_open_max_redirects: int = 3
    web_agent_max_steps: int = 6
    web_agent_max_searches: int = 3
    web_agent_max_opened_pages: int = Field(default=2, ge=1, le=4)
    # The loop's own budget covers planning, searching and opening. It is
    # measured from before request framing, so framing time is already taken out
    # of it. 30 s was too small for one save-source turn: two planner calls, a
    # search, a page read and the extraction call do not fit even when the
    # network itself takes under 7 s.
    web_agent_max_seconds: float = 60.0
    # Work that is already paid for keeps a floor, so an exhausted loop clock
    # cannot cancel a download that has already happened. One open call is a
    # download plus trafilatura/PDF text extraction (or vision OCR) on the Pi.
    web_open_extract_seconds: float = 30.0
    # Classification plus excerpt extraction for a candidate source: two model
    # calls that decide whether the read page becomes a Working Source.
    web_source_save_seconds: float = 20.0
    research_max_seconds: float = 75.0
    research_review_rounds: int = 2
    # A saved document is often far larger than the retrieval budget, and chunk
    # ranking does not always surface a specific task or clause. For tasks that
    # need a document's own text, the stored full text is searched directly and
    # one bounded window is added to the prompt.
    saved_source_excerpt_chars: int = 6_000
    # How many saved documents one turn may scan before giving up. The scan stops
    # early at a strong match, so a chat with many saved sources stays cheap.
    saved_source_scan_limit: int = 5
    # Block score that counts as a strong lexical hit and ends the scan.
    saved_source_strong_score: float = 40.0
    # Chat-scoped material gets its own ceiling so a large saved document is not
    # starved by the shared mode knowledge base. It applies only when the chat
    # has working sources; other turns keep the smaller retrieval budget.
    chat_source_context_budget_tokens: int = 12_000
    # Shared only by the main API and the small public-VPS fallback service.
    # It signs short-lived offline-verifiable tickets; it is never sent to a client.
    fallback_ticket_secret: SecretStr | None = None
    fallback_ticket_ttl_days: int = 30
    fallback_database_path: Path = Path("data/fallback.sqlite3")
    fallback_history_messages: int = 6
    fallback_global_prompt: str = (
        "Ты — WristMind. Отвечай на языке пользователя точно и по существу. "
        "Не выдумывай факты; если данных недостаточно, честно скажи об этом."
    )
    # Disabled until both values are set in the ignored server .env.
    telegram_bot_token: SecretStr | None = None
    telegram_owner_id: int | None = None
    telegram_webhook_secret: SecretStr | None = None
    mock_providers: bool = True

    # --- Latency diagnostics -------------------------------------------------
    # Diagnostic-only. Recording never changes routing, retrieval, provider
    # calls, retries, timeouts or output, and never touches the answer text.
    # The JSONL trace is local and safe; the live Telegram feed is opt-in and
    # off by default so a production deployment stays quiet.
    latency_trace_enabled: bool = True
    # Defaults to <storage_dir>/latency-trace.jsonl, i.e. the private volume
    # shared by the API and worker containers.
    latency_trace_path: Path | None = None
    latency_trace_max_bytes: int = 8_000_000
    latency_trace_backup_count: int = 5
    # Both WRISTMIND_LATENCY_TELEGRAM_ENABLED and the unprefixed
    # LATENCY_TELEGRAM_ENABLED are accepted.
    latency_telegram_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "WRISTMIND_LATENCY_TELEGRAM_ENABLED", "LATENCY_TELEGRAM_ENABLED"
        ),
    )
    # Optional dedicated diagnostics bot. When unset, the main bot token is used.
    latency_telegram_bot_token: SecretStr | None = None
    # Optional explicit chat id. When unset, telegram_owner_id is used.
    latency_telegram_chat_id: str | None = None

    @model_validator(mode='after')
    def validate_resource_thresholds(self):
        if not self.resource_critical_memory_mb < self.resource_busy_memory_mb < self.resource_free_memory_mb:
            raise ValueError('Resource thresholds must satisfy critical < busy < free')
        return self

    @field_validator("allowed_models", "cors_origins", mode="before")
    @classmethod
    def parse_json_lists(cls, value: object) -> object:
        return json.loads(value) if isinstance(value, str) else value

    def model_option(self, model_id: str) -> ModelOption | None:
        return next((item for item in self.allowed_models if item.id == model_id), None)


@lru_cache
def _environment_settings() -> Settings:
    return Settings()


def get_settings() -> Settings:
    from .selfhost_runtime import refresh_runtime
    return refresh_runtime(_environment_settings())


get_settings.cache_clear = _environment_settings.cache_clear
