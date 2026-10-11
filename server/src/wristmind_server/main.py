from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError

from .speech_stream import router as speech_stream_router
from .config import Settings, get_settings, resolve_model_id
from .database import SessionFactory, close_database, get_session, init_database
from .db_models import (
    AccountEvent,
    AppSettings,
    Chat,
    ChatSourceCandidate,
    Device,
    Job,
    JobEvent,
    KnowledgeChunk,
    KnowledgeSource,
    Message,
    Mode,
    PairingCode,
    PushRegistration,
    PromptOverride,
    ReferencedWebSource,
    RawWebSource,
    TelegramAccount,
    TelegramEmojiDraft,
    User,
    utcnow,
)
from .schemas import (
    ChatCreate,
    ChatReferencedSourceResponse,
    ChatSourceCandidateResponse,
    ChatSourceSaveRequest,
    ChatResponse,
    ChatSourcesResponse,
    ChatUpdate,
    ChatWorkingSourceResponse,
    ChatWorkingSourceTextResponse,
    DashboardActivityPoint,
    DashboardStatsResponse,
    DashboardUsageBreakdown,
    DeviceEnrollRequest,
    DeviceResponse,
    DeviceTokenResponse,
    FallbackMessageSync,
    FallbackTicketResponse,
    GlobalSettingsResponse,
    GlobalSettingsUpdate,
    JobResponse,
    KnowledgeReprocessRequest,
    KnowledgeSourceDetailResponse,
    KnowledgeSourceResponse,
    MessageCreate,
    MessageResponse,
    ModeCreate,
    ModeResponse,
    ModeUpdate,
    ReferencedSourceResponse,
    ModelOptionResponse,
    PairDeviceRequest,
    PairingCodeCreate,
    PairingCodeResponse,
    PushTokenUpdate,
    PromptRecord,
    PromptUpdate,
    WearDiagnosticsUpload,
    QuickChatCreate,
    TranscriptionResponse,
    CurrentUserResponse,
)
from .fallback_auth import issue_fallback_ticket
from . import account_events, latency_trace
from .providers import ProviderError, ProviderRouter
from .prompt_registry import DEFAULT_TEMPLATES, PROMPT_LABELS, required_markers
from .push import schedule_watch_state_changed
from .security import admin_device, client_ip, current_device, hash_secret, issue_device_token, issue_pairing_code
from .telegram_bot import bot_is_enabled, handle_update


logger = logging.getLogger("uvicorn.error")

QUICK_CHAT_MODE_NAME = "Быстрый чат"
QUICK_CHAT_MODE_DESCRIPTION = "Школа, быт, готовка и любые общие вопросы."
QUICK_CHAT_MODE_PROMPT = (
    "Ты — универсальный помощник WristMind. Помогай с любыми вопросами: школьные "
    "предметы, быт, готовка и другое. Отвечай на языке пользователя кратко и точно; "
    "объясняй подробнее, когда это нужно для задачи или об этом просят. Не выдумывай "
    "факты; если данных не хватает, уточни."
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_database()
    async with SessionFactory() as session:
        owner = await session.scalar(select(User).where(User.role == "ADMIN", User.deleted_at.is_(None)).order_by(User.created_at))
        if owner is None:
            owner = User(name="Владелец", role="ADMIN")
            session.add(owner)
            await session.flush()
        # The product has one owner. Collapse legacy user rows into that owner
        # so removing the old multi-user UI cannot orphan existing data.
        legacy_users = select(User.id).where(User.id != owner.id)
        await session.execute(update(Device).where(Device.user_id.is_(None)).values(user_id=owner.id))
        await session.execute(update(Device).where(Device.user_id.in_(legacy_users)).values(user_id=owner.id))
        await session.execute(update(PairingCode).where(PairingCode.user_id.is_(None)).values(user_id=owner.id))
        await session.execute(update(PairingCode).where(PairingCode.user_id.in_(legacy_users)).values(user_id=owner.id))
        await session.execute(update(Chat).where(Chat.user_id.is_(None)).values(user_id=owner.id))
        await session.execute(update(Chat).where(Chat.user_id.in_(legacy_users)).values(user_id=owner.id))
        await session.execute(update(KnowledgeSource).where(KnowledgeSource.user_id.is_(None)).values(user_id=owner.id))
        await session.execute(update(KnowledgeSource).where(KnowledgeSource.user_id.in_(legacy_users)).values(user_id=owner.id))
        await session.execute(update(TelegramAccount).where(TelegramAccount.user_id.in_(legacy_users)).values(user_id=owner.id))
        await session.execute(update(TelegramEmojiDraft).where(TelegramEmojiDraft.user_id.in_(legacy_users)).values(user_id=owner.id))
        await session.execute(update(User).where(User.id != owner.id, User.deleted_at.is_(None)).values(deleted_at=utcnow()))
        await session.commit()
    # The panel's live stream is resumable within this window; older rows are
    # dropped and a lagging cursor gets `resync` instead of a silent gap.
    async with SessionFactory() as session:
        try:
            await account_events.prune_account_events(session)
        except Exception:  # pragma: no cover - retention must never block startup
            logger.warning("Could not prune account events", exc_info=True)
    # Diagnostic-only live latency feed; a no-op unless explicitly enabled.
    latency_trace.start_telegram_worker(get_settings())
    yield
    await latency_trace.stop_telegram_worker()
    await close_database()


app = FastAPI(title="WristMind API", version="1.0.0", lifespan=lifespan)
app.include_router(speech_stream_router)
from .feature_capabilities import router as capabilities_router
app.include_router(capabilities_router)
from .provider_registry import router as provider_registry_router
app.include_router(provider_registry_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def valid_wear_diagnostic_line(line: str) -> bool:
    parts = line.split(" ", 2)
    if len(parts) != 3 or len(parts[0]) != 13 or not parts[0].isdigit() or len(line) > 700:
        return False
    prefixes = {
        "answer": ("answer_trace ",),
        "latency": ("latency_trace ",),
        "transport": ("wear_transport ",),
        "route": ("send_route ", "create_route ", "source_save "),
        "send": ("send_timing ", "answer_total_ms="),
        "speech": ("speech_transport ",),
    }
    return all(32 <= ord(char) < 127 for char in line) and parts[2].startswith(
        prefixes.get(parts[1], ())
    )


@app.post("/v1/diagnostics/wear")
async def upload_wear_diagnostics(
    request: WearDiagnosticsUpload,
    device: Device = Depends(current_device),
) -> dict[str, int]:
    if device.kind != "WATCH":
        raise HTTPException(status_code=403, detail="Watch device required")
    if not latency_trace.manual_wear_diagnostics_available():
        raise HTTPException(status_code=503, detail="Diagnostics Telegram is unavailable")
    if any(not valid_wear_diagnostic_line(line) for line in request.lines):
        raise HTTPException(status_code=422, detail="Invalid diagnostic line")
    try:
        await latency_trace.send_wear_diagnostics(request.lines, device.id)
    except Exception as error:
        logger.warning("Wear diagnostic export failed: %s", type(error).__name__)
        raise HTTPException(status_code=502, detail="Diagnostic delivery failed") from None
    return {"sent": len(request.lines)}


def chat_response(chat: Chat) -> ChatResponse:
    return ChatResponse(
        id=chat.id,
        mode_id=chat.mode_id,
        mode_name=chat.mode_name_snapshot,
        mode_deleted=chat.mode.deleted_at is not None,
        title=chat.title,
        pinned=chat.pinned,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
    )


def ensure_model(model_id: str, settings: Settings) -> None:
    if settings.model_option(resolve_model_id(model_id)) is None:
        raise HTTPException(status_code=422, detail="Model is not allowed")


async def owner_for_device(device: Device, session: AsyncSession) -> User:
    if device.user_id is None:
        raise HTTPException(status_code=403, detail="Device has no owner")
    owner = await session.get(User, device.user_id)
    if owner is None or owner.deleted_at is not None:
        raise HTTPException(status_code=403, detail="Device owner not found")
    return owner


async def admin_owner(session: AsyncSession) -> User:
    owner = await session.scalar(select(User).where(User.role == "ADMIN", User.deleted_at.is_(None)).order_by(User.created_at))
    if owner is None or owner.deleted_at is not None:
        owner = User(name="Владелец", role="ADMIN")
        session.add(owner)
        await session.flush()
    return owner


async def job_belongs_to_user(job: Job, user_id: str, session: AsyncSession) -> bool:
    chat_id = job.payload.get("chat_id")
    if isinstance(chat_id, str):
        return await session.scalar(select(Chat.id).where(Chat.id == chat_id, Chat.user_id == user_id)) is not None
    source_id = job.payload.get("source_id")
    if isinstance(source_id, str):
        return await session.scalar(select(KnowledgeSource.id).where(KnowledgeSource.id == source_id, KnowledgeSource.user_id == user_id)) is not None
    return False


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "1.0.0"}


@app.post("/v1/telegram/webhook", status_code=204)
async def telegram_webhook(
    update: dict[str, object],
    secret: str | None = Header(None, alias="X-Telegram-Bot-Api-Secret-Token"),
    settings: Settings = Depends(get_settings),
) -> None:
    """Accept a Telegram update quickly; Bot API processing continues in background."""
    if not bot_is_enabled(settings):
        raise HTTPException(status_code=404, detail="Telegram bot is disabled")
    expected = settings.telegram_webhook_secret.get_secret_value() if settings.telegram_webhook_secret else ""
    if expected and not secret or expected and not secrets.compare_digest(secret, expected):
        raise HTTPException(status_code=401, detail="Invalid Telegram webhook secret")
    asyncio.create_task(handle_update(update, settings))


@app.get("/v1/dashboard/stats", response_model=DashboardStatsResponse)
async def dashboard_stats(
    utc_offset_minutes: int = Query(default=0, ge=-720, le=840),
    _: Device = Depends(admin_device),
    session: AsyncSession = Depends(get_session),
) -> DashboardStatsResponse:
    total_ai_requests = await session.scalar(
        select(func.count(Job.id)).where(Job.kind == "ANSWER")
    )
    display_timezone = timezone(timedelta(minutes=utc_offset_minutes))
    today = datetime.now(display_timezone).date()
    first_day = today - timedelta(days=13)
    since = datetime.combine(
        first_day, datetime.min.time(), tzinfo=display_timezone
    ).astimezone(timezone.utc)
    recent_jobs = (
        await session.execute(
            select(Job.created_at, Job.status, Job.payload)
            .where(Job.kind == "ANSWER", Job.created_at >= since)
        )
    ).all()

    daily = {
        first_day + timedelta(days=offset): {"requests": 0, "errors": 0}
        for offset in range(14)
    }
    chat_ids: set[str] = set()
    message_ids: set[str] = set()
    for created_at, status, payload in recent_jobs:
        # SQLite stores naive timestamps in tests; production PostgreSQL returns
        # aware timestamps. Both represent UTC in this application.
        created_utc = (
            created_at.replace(tzinfo=timezone.utc)
            if created_at.tzinfo is None
            else created_at.astimezone(timezone.utc)
        )
        day = created_utc.astimezone(display_timezone).date()
        if day not in daily:
            continue
        daily[day]["requests"] += 1
        if status == "failed":
            daily[day]["errors"] += 1
        if isinstance(payload, dict):
            if isinstance(payload.get("chat_id"), str):
                chat_ids.add(payload["chat_id"])
            if isinstance(payload.get("assistant_message_id"), str):
                message_ids.add(payload["assistant_message_id"])

    mode_by_chat = dict(
        (await session.execute(select(Chat.id, Chat.mode_id).where(Chat.id.in_(chat_ids)))).all()
    ) if chat_ids else {}
    token_by_message: dict[str, int] = {}
    if message_ids:
        for message_id, usage in (
            await session.execute(select(Message.id, Message.usage).where(Message.id.in_(message_ids)))
        ).all():
            raw_tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
            if isinstance(raw_tokens, (int, float)) and not isinstance(raw_tokens, bool):
                token_by_message[message_id] = max(0, int(raw_tokens))

    usage_by_mode: dict[str, dict[str, int]] = {}
    for _, _, payload in recent_jobs:
        if not isinstance(payload, dict):
            continue
        chat_id = payload.get("chat_id")
        mode_id = mode_by_chat.get(chat_id) if isinstance(chat_id, str) else None
        if not mode_id:
            continue
        item = usage_by_mode.setdefault(mode_id, {"requests": 0, "tokens": 0})
        item["requests"] += 1
        message_id = payload.get("assistant_message_id")
        if isinstance(message_id, str):
            item["tokens"] += token_by_message.get(message_id, 0)

    activity = [
        DashboardActivityPoint(
            bucket=datetime.combine(day, datetime.min.time(), tzinfo=display_timezone),
            requests=counts["requests"],
            errors=counts["errors"],
        )
        for day, counts in daily.items()
    ]
    today_counts = daily[today]
    yesterday_counts = daily[today - timedelta(days=1)]
    return DashboardStatsResponse(
        total_ai_requests=total_ai_requests or 0,
        requests_today=today_counts["requests"],
        requests_yesterday=yesterday_counts["requests"],
        error_rate_today=(
            today_counts["errors"] / today_counts["requests"] * 100
            if today_counts["requests"] else 0
        ),
        activity=activity,
        usage=[
            DashboardUsageBreakdown(mode_id=mode_id, **counts)
            for mode_id, counts in sorted(
                usage_by_mode.items(), key=lambda entry: entry[1]["requests"], reverse=True
            )
        ],
    )


@app.post("/v1/stt/yandex", response_model=TranscriptionResponse)
async def transcribe_panel_audio(
    file: UploadFile = File(...),
    _: Device = Depends(admin_device),
    settings: Settings = Depends(get_settings),
) -> TranscriptionResponse:
    from .feature_capabilities import require
    require(settings, 'voice')
    # Mono signed 16-bit PCM, 16 kHz, at most 30 seconds. Never persist audio.
    content = await file.read(960_001)
    await file.close()
    if len(content) > 960_000:
        raise HTTPException(status_code=413, detail="Запись должна быть не длиннее 30 секунд")
    if not content or len(content) % 2:
        raise HTTPException(status_code=422, detail="Некорректная аудиозапись")
    started = time.perf_counter()
    try:
        text = await ProviderRouter(settings).transcribe_yandex(content)
    except ProviderError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    if not text:
        raise HTTPException(status_code=422, detail="Речь не распознана. Попробуйте ещё раз.")
    return TranscriptionResponse(text=text, duration_ms=round((time.perf_counter() - started) * 1000), provider="yandex")


@app.post("/v1/stt", response_model=TranscriptionResponse)
async def transcribe_audio(
    file: UploadFile = File(...),
    _: Device = Depends(current_device),
    settings: Settings = Depends(get_settings),
) -> TranscriptionResponse:
    content = await file.read(settings.max_upload_bytes + 1)
    await file.close()
    if not content:
        raise HTTPException(status_code=422, detail="Audio file is empty")
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="Audio file is too large")
    from .feature_capabilities import require
    require(settings, 'voice')
    media_type = file.content_type or "application/octet-stream"
    suffix = Path(file.filename or "audio.webm").suffix[:12] or ".bin"
    temp_dir = settings.storage_dir / "stt-temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"{uuid4()}{suffix}"
    temp_path.write_bytes(content)
    started = time.perf_counter()
    provider = ProviderRouter(settings)
    try:
        text = await provider.transcribe(temp_path, media_type)
    except ProviderError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    finally:
        temp_path.unlink(missing_ok=True)
    return TranscriptionResponse(
        text=text,
        duration_ms=round((time.perf_counter() - started) * 1000),
        provider="mock" if settings.mock_providers else "openrouter",
    )


@app.post("/v1/devices/admin/enroll", response_model=DeviceTokenResponse)
async def enroll_admin(
    request: DeviceEnrollRequest,
    http_request: Request,
    bootstrap: str | None = Header(None, alias="X-WristMind-Bootstrap"),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> DeviceTokenResponse:
    expected = settings.bootstrap_secret.get_secret_value()
    if not bootstrap or not secrets.compare_digest(bootstrap, expected):
        raise HTTPException(status_code=401, detail="Invalid bootstrap secret")
    if request.kind not in {"PHONE", "WEB"}:
        raise HTTPException(status_code=422, detail="The admin device must be a phone or web panel")
    owner = await admin_owner(session)
    address = client_ip(http_request)
    device = Device(
        name=request.name, kind=request.kind, is_admin=True, user_id=owner.id, token_hash="pending",
        enrolled_ip=address, last_ip=address,
        user_agent=http_request.headers.get("user-agent", "")[:300] or None,
    )
    session.add(device)
    await session.flush()
    token = issue_device_token(device.id)
    device.token_hash = hash_secret(token, settings)
    await session.commit()
    return DeviceTokenResponse(device_id=device.id, token=token, is_admin=True, user_id=owner.id)


@app.post("/v1/devices/pairing-codes", response_model=PairingCodeResponse, status_code=201)
async def create_pairing_code(
    request: PairingCodeCreate | None = None,
    device: Device = Depends(current_device),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> PairingCodeResponse:
    owner = await owner_for_device(device, session)
    # Owner watches can issue a code without acquiring other admin permissions.
    if not device.is_admin and not (device.kind == "WATCH" and owner.role == "ADMIN"):
        raise HTTPException(status_code=403, detail="Admin device or owner watch required")
    client_request_id = request.client_request_id if request else None
    if client_request_id:
        existing = await session.scalar(
            select(PairingCode).where(
                PairingCode.created_by_id == device.id,
                PairingCode.client_request_id == client_request_id,
            )
        )
        if existing is not None:
            return PairingCodeResponse(
                code=issue_pairing_code(client_request_id, device.id, existing.derivation_counter, settings),
                expires_at=existing.expires_at.replace(tzinfo=timezone.utc)
                if existing.expires_at.tzinfo is None
                else existing.expires_at,
            )

    # A retry with the same request ID reconstructs the same raw code from the
    # server-side pepper. Only its hash is persisted. The counter handles the
    # unlikely case where another six-digit code already has the same hash.
    for derivation_counter in range(10):
        code = (
            issue_pairing_code(client_request_id, device.id, derivation_counter, settings)
            if client_request_id
            else f"{secrets.randbelow(1_000_000):06d}"
        )
        expires_at = utcnow() + timedelta(minutes=10)
        session.add(
            PairingCode(
                code_hash=hash_secret(code, settings),
                expires_at=expires_at,
                created_by_id=device.id,
                user_id=owner.id,
                client_request_id=client_request_id,
                derivation_counter=derivation_counter,
            )
        )
        try:
            account_events.record_account_event(
                session,
                account_events.PAIRING_UPDATED,
                {},
                owner_id=owner.id,
            )
            await session.commit()
            return PairingCodeResponse(code=code, expires_at=expires_at)
        except IntegrityError:
            await session.rollback()
            if client_request_id:
                existing = await session.scalar(
                    select(PairingCode).where(
                        PairingCode.created_by_id == device.id,
                        PairingCode.client_request_id == client_request_id,
                    )
                )
                if existing is not None:
                    return PairingCodeResponse(
                        code=issue_pairing_code(
                            client_request_id,
                            device.id,
                            existing.derivation_counter,
                            settings,
                        ),
                        expires_at=existing.expires_at.replace(tzinfo=timezone.utc)
                        if existing.expires_at.tzinfo is None
                        else existing.expires_at,
                    )
    raise HTTPException(status_code=503, detail="Не удалось выпустить уникальный код. Повторите попытку")


@app.post("/v1/devices/enroll", response_model=DeviceTokenResponse)
async def enroll_device(
    request: PairDeviceRequest,
    http_request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> DeviceTokenResponse:
    pairing = await session.scalar(
        select(PairingCode).where(PairingCode.code_hash == hash_secret(request.code, settings))
    )
    now = utcnow()
    if pairing is None or pairing.used_at is not None:
        raise HTTPException(status_code=401, detail="Invalid pairing code")
    expiry = pairing.expires_at
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    if expiry < now:
        raise HTTPException(status_code=401, detail="Pairing code expired")
    if request.kind not in {"PHONE", "WATCH"}:
        raise HTTPException(status_code=400, detail="This code can enroll only a phone or watch")
    owner = await admin_owner(session)
    address = client_ip(http_request)
    device = Device(
        name=request.name, kind=request.kind, is_admin=False, user_id=owner.id, token_hash="pending",
        enrolled_ip=address, last_ip=address,
        user_agent=http_request.headers.get("user-agent", "")[:300] or None,
    )
    session.add(device)
    await session.flush()
    token = issue_device_token(device.id)
    device.token_hash = hash_secret(token, settings)
    pairing.used_at = now
    account_events.record_account_event(
        session,
        account_events.DEVICE_UPDATED,
        {"device_id": device.id},
        owner_id=owner.id,
    )
    await session.commit()
    return DeviceTokenResponse(device_id=device.id, token=token, is_admin=False, user_id=owner.id)


@app.post("/v1/devices/admin/enroll-by-code", response_model=DeviceTokenResponse)
async def enroll_admin_by_code(
    request: PairDeviceRequest,
    http_request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> DeviceTokenResponse:
    """Create an additional web admin session using a short one-time code.

    The existing device enrollment endpoint remains non-admin and is used by
    watches/phones. Keeping this as a separate route prevents a client from
    accidentally receiving admin access just by changing its kind field.
    """
    if request.kind != "WEB":
        raise HTTPException(status_code=400, detail="Admin code can enroll only a web panel")

    pairing = await session.scalar(
        select(PairingCode).where(PairingCode.code_hash == hash_secret(request.code, settings))
    )
    now = utcnow()
    if pairing is None or pairing.used_at is not None:
        raise HTTPException(status_code=401, detail="Invalid pairing code")
    expiry = pairing.expires_at
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    if expiry < now:
        raise HTTPException(status_code=401, detail="Pairing code expired")

    owner = await admin_owner(session)
    address = client_ip(http_request)
    device = Device(
        name=request.name, kind="WEB", is_admin=True, user_id=owner.id, token_hash="pending",
        enrolled_ip=address, last_ip=address,
        user_agent=http_request.headers.get("user-agent", "")[:300] or None,
    )
    session.add(device)
    await session.flush()
    token = issue_device_token(device.id)
    device.token_hash = hash_secret(token, settings)
    pairing.used_at = now
    account_events.record_account_event(
        session,
        account_events.DEVICE_UPDATED,
        {"device_id": device.id},
        owner_id=owner.id,
    )
    await session.commit()
    return DeviceTokenResponse(device_id=device.id, token=token, is_admin=True, user_id=owner.id)


@app.get("/v1/me", response_model=CurrentUserResponse)
async def current_user(
    device: Device = Depends(current_device),
    session: AsyncSession = Depends(get_session),
) -> CurrentUserResponse:
    owner = await owner_for_device(device, session)
    return CurrentUserResponse(id=owner.id, name=owner.name, role=owner.role, created_at=owner.created_at, is_admin=device.is_admin)


@app.delete("/v1/devices/self", status_code=204)
async def revoke_current_device(
    current: Device = Depends(current_device),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Allow a non-admin client to revoke its own device token."""
    current.revoked_at = utcnow()
    current.removed_at = current.revoked_at
    await session.execute(delete(PushRegistration).where(PushRegistration.device_id == current.id))
    account_events.record_account_event(
        session,
        account_events.DEVICE_REMOVED,
        {"device_id": current.id},
        owner_id=current.user_id,
    )
    await session.commit()


@app.get("/v1/devices/self/fallback-ticket", response_model=FallbackTicketResponse)
async def fallback_ticket(
    device: Device = Depends(current_device),
    settings: Settings = Depends(get_settings),
) -> FallbackTicketResponse:
    if not settings.fallback_ticket_secret or not device.user_id:
        raise HTTPException(status_code=503, detail="Fallback mode is not configured")
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.fallback_ticket_ttl_days)
    ticket = issue_fallback_ticket(
        device.id,
        device.user_id,
        int(expires_at.timestamp()),
        settings.fallback_ticket_secret.get_secret_value(),
    )
    return FallbackTicketResponse(ticket=ticket, expires_at=expires_at)


@app.put("/v1/devices/self/push-token", status_code=204)
async def register_push_token(
    request: PushTokenUpdate,
    current: Device = Depends(current_device),
    session: AsyncSession = Depends(get_session),
) -> None:
    if current.kind != "WATCH":
        raise HTTPException(status_code=403, detail="Only watches can register push tokens")
    await session.execute(delete(PushRegistration).where(PushRegistration.token == request.token))
    registration = await session.get(PushRegistration, current.id)
    if registration is None:
        session.add(PushRegistration(device_id=current.id, token=request.token))
    else:
        registration.token = request.token
    await session.commit()


@app.get("/v1/devices", response_model=list[DeviceResponse])
async def list_devices(
    _: Device = Depends(admin_device),
    session: AsyncSession = Depends(get_session),
) -> list[Device]:
    return list((await session.scalars(select(Device).where(Device.removed_at.is_(None), Device.revoked_at.is_(None)).order_by(Device.created_at))).all())


@app.delete("/v1/devices/{device_id}", status_code=204)
async def revoke_device(
    device_id: str,
    current: Device = Depends(admin_device),
    session: AsyncSession = Depends(get_session),
) -> None:
    if current.id == device_id:
        raise HTTPException(status_code=409, detail="Cannot revoke the current admin device")
    device = await session.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    device.revoked_at = utcnow()
    device.removed_at = device.revoked_at
    account_events.record_account_event(
        session,
        account_events.DEVICE_REMOVED,
        {"device_id": device.id},
        owner_id=device.user_id,
    )
    await session.commit()


@app.delete("/v1/devices/{device_id}/record", status_code=204)
async def remove_revoked_device_record(
    device_id: str,
    current: Device = Depends(admin_device),
    session: AsyncSession = Depends(get_session),
) -> None:
    if current.id == device_id:
        raise HTTPException(status_code=409, detail="Cannot remove the current admin device")
    device = await session.get(Device, device_id)
    if device is None or device.removed_at is not None:
        raise HTTPException(status_code=404, detail="Device not found")
    if device.revoked_at is None:
        raise HTTPException(status_code=409, detail="Revoke device access before removing it")
    device.removed_at = utcnow()
    account_events.record_account_event(
        session,
        account_events.DEVICE_REMOVED,
        {"device_id": device.id},
        owner_id=device.user_id,
    )
    await session.commit()


@app.get("/v1/models", response_model=list[ModelOptionResponse])
async def list_models(
    _: Device = Depends(current_device),
    settings: Settings = Depends(get_settings),
) -> list[ModelOptionResponse]:
    names = {p.id: p.label for p in settings.provider_connections if p.id.startswith('p_')}
    return [ModelOptionResponse(**{**item.model_dump(), 'provider': names.get(item.provider, item.provider)}) for item in settings.allowed_models]


async def app_settings(session: AsyncSession, settings: Settings) -> AppSettings:
    value = await session.get(AppSettings, 1)
    if value is None:
        value = AppSettings(id=1, default_model_id=resolve_model_id(settings.default_model_id))
        session.add(value)
        await session.commit()
        await session.refresh(value)
    return value


@app.get("/v1/settings", response_model=GlobalSettingsResponse)
async def read_settings(
    _: Device = Depends(admin_device),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> GlobalSettingsResponse:
    value = await app_settings(session, settings)
    return GlobalSettingsResponse(
        developer_mode=value.developer_mode,
        global_system_prompt=value.global_system_prompt,
        source_intent_prompt=value.source_intent_prompt,
        source_candidate_prompt=value.source_candidate_prompt,
        history_message_limit=value.history_message_limit,
        default_model_id=resolve_model_id(value.default_model_id),
        stream_responses=value.stream_responses,
        retention_days=value.retention_days,
    )


@app.put("/v1/settings", response_model=GlobalSettingsResponse)
async def update_settings(
    request: GlobalSettingsUpdate,
    _: Device = Depends(admin_device),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> GlobalSettingsResponse:
    value = await app_settings(session, settings)
    if not value.developer_mode and any(
        prompt is not None for prompt in (
            request.global_system_prompt,
            request.source_intent_prompt,
            request.source_candidate_prompt,
        )
    ):
        raise HTTPException(status_code=403, detail="Включите режим разработчика для изменения системных промптов")
    if request.developer_mode is not None:
        value.developer_mode = request.developer_mode
    if request.global_system_prompt is not None:
        value.global_system_prompt = request.global_system_prompt.strip()
    if request.source_intent_prompt is not None:
        value.source_intent_prompt = request.source_intent_prompt.strip()
    if request.source_candidate_prompt is not None:
        value.source_candidate_prompt = request.source_candidate_prompt.strip()
    if request.history_message_limit is not None:
        value.history_message_limit = request.history_message_limit
    if request.default_model_id is not None:
        model_id = resolve_model_id(request.default_model_id)
        ensure_model(model_id, settings)
        value.default_model_id = model_id
        from .selfhost_runtime import read_runtime, write_runtime, refresh_runtime
        runtime = read_runtime(settings)
        if 'providers' in runtime:
            for field in ('default_model_id', 'quick_chat_model_id', 'router_model_id', 'title_model_id'):
                runtime[field] = model_id
            write_runtime(settings, runtime)
            refresh_runtime(settings)
    if request.stream_responses is not None:
        value.stream_responses = request.stream_responses
    if request.retention_days is not None:
        value.retention_days = request.retention_days
    account_events.record_account_event(session, account_events.SETTINGS_UPDATED, {})
    await session.commit()
    schedule_watch_state_changed(get_settings())
    return GlobalSettingsResponse(
        developer_mode=value.developer_mode,
        global_system_prompt=value.global_system_prompt,
        source_intent_prompt=value.source_intent_prompt,
        source_candidate_prompt=value.source_candidate_prompt,
        history_message_limit=value.history_message_limit,
        default_model_id=resolve_model_id(value.default_model_id),
        stream_responses=value.stream_responses,
        retention_days=value.retention_days,
    )


@app.get("/v1/prompts", response_model=list[PromptRecord])
async def list_internal_prompts(
    _: Device = Depends(admin_device),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> list[PromptRecord]:
    config = await app_settings(session, settings)
    if not config.developer_mode:
        raise HTTPException(status_code=403, detail="Режим разработчика выключен")
    overrides = {item.key: item.text for item in (await session.scalars(select(PromptOverride))).all()}
    return [
        PromptRecord(
            key=key, label=PROMPT_LABELS[key], text=overrides.get(key, default),
            default_text=default, customized=key in overrides,
        )
        for key, default in sorted(DEFAULT_TEMPLATES.items(), key=lambda item: PROMPT_LABELS[item[0]])
    ]


@app.put("/v1/prompts/{key}", response_model=PromptRecord)
async def update_internal_prompt(
    key: str,
    request: PromptUpdate,
    _: Device = Depends(admin_device),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> PromptRecord:
    config = await app_settings(session, settings)
    if not config.developer_mode:
        raise HTTPException(status_code=403, detail="Режим разработчика выключен")
    if key not in DEFAULT_TEMPLATES:
        raise HTTPException(status_code=404, detail="Промпт не найден")
    value = request.text.strip()
    default = DEFAULT_TEMPLATES[key]
    if value and required_markers(key) != set(re.findall(r"\{\{([^{}]+)\}\}", value)):
        raise HTTPException(status_code=422, detail="Сохраните все динамические поля промпта")
    record = await session.get(PromptOverride, key)
    if value and value != default:
        if record is None:
            session.add(PromptOverride(key=key, text=value))
        else:
            record.text = value
    elif record is not None:
        await session.delete(record)
    if key == "quick_chat_mode":
        quick_mode = await session.scalar(select(Mode).where(Mode.name == QUICK_CHAT_MODE_NAME))
        if quick_mode is not None:
            quick_mode.system_prompt = value or default
    account_events.record_account_event(session, account_events.SETTINGS_UPDATED, {"prompt": key})
    await session.commit()
    return PromptRecord(
        key=key, label=PROMPT_LABELS[key], text=value or default,
        default_text=default, customized=bool(value and value != default),
    )


@app.get("/v1/modes", response_model=list[ModeResponse])
async def list_modes(
    device: Device = Depends(current_device),
    session: AsyncSession = Depends(get_session),
) -> list[Mode]:
    filters = [Mode.deleted_at.is_(None), Mode.name != QUICK_CHAT_MODE_NAME]
    if device.kind in {"WATCH", "PHONE"}:
        filters.append(Mode.hidden_on_watch.is_(False))
    return list(
        (
            await session.scalars(
                select(Mode)
                .where(*filters)
                .order_by(Mode.name)
            )
        ).all()
    )


@app.post("/v1/modes", response_model=ModeResponse, status_code=201)
async def create_mode(
    request: ModeCreate,
    _: Device = Depends(admin_device),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Mode:
    ensure_model(request.response_model_id, settings)
    mode = Mode(**request.model_dump())
    session.add(mode)
    await session.flush()
    account_events.record_account_event(session, account_events.MODE_UPDATED, {"mode_id": mode.id})
    await session.commit()
    await session.refresh(mode)
    schedule_watch_state_changed(get_settings())
    return mode


@app.patch("/v1/modes/{mode_id}", response_model=ModeResponse)
async def update_mode(
    mode_id: str,
    request: ModeUpdate,
    _: Device = Depends(admin_device),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Mode:
    mode = await session.get(Mode, mode_id)
    if mode is None or mode.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Mode not found")
    values = request.model_dump(exclude_unset=True)
    if "response_model_id" in values:
        ensure_model(values["response_model_id"], settings)
    for key, value in values.items():
        setattr(mode, key, value)
    mode.updated_at = utcnow()
    account_events.record_account_event(session, account_events.MODE_UPDATED, {"mode_id": mode.id})
    await session.commit()
    await session.refresh(mode)
    schedule_watch_state_changed(get_settings())
    return mode


@app.delete("/v1/modes/{mode_id}", status_code=204)
async def delete_mode(
    mode_id: str,
    _: Device = Depends(admin_device),
    session: AsyncSession = Depends(get_session),
) -> None:
    mode = await session.get(Mode, mode_id)
    if mode is None or mode.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Mode not found")
    mode.deleted_at = utcnow()
    sources = await session.scalars(
        select(KnowledgeSource).where(
            KnowledgeSource.mode_id == mode_id,
            KnowledgeSource.deleted_at.is_(None),
        )
    )
    for source in sources:
        source.deleted_at = utcnow()
    account_events.record_account_event(session, account_events.MODE_REMOVED, {"mode_id": mode.id})
    await session.commit()
    schedule_watch_state_changed(get_settings())


@app.get("/v1/chats", response_model=list[ChatResponse])
async def list_chats(
    device: Device = Depends(current_device),
    session: AsyncSession = Depends(get_session),
) -> list[ChatResponse]:
    owner = await owner_for_device(device, session)
    chats = (
        await session.scalars(
            select(Chat)
            .options(selectinload(Chat.mode))
            .where(Chat.deleted_at.is_(None), Chat.user_id == owner.id)
            .order_by(Chat.updated_at.desc())
        )
    ).all()
    return [chat_response(item) for item in chats]


@app.post("/v1/chats", response_model=ChatResponse, status_code=201)
async def create_chat(
    request: ChatCreate,
    device: Device = Depends(current_device),
    session: AsyncSession = Depends(get_session),
) -> ChatResponse:
    owner = await owner_for_device(device, session)
    existing = await existing_chat_for_request(owner.id, request.client_request_id, session)
    if existing is not None:
        return chat_response(existing)
    mode = await session.get(Mode, request.mode_id)
    if mode is None or mode.deleted_at is not None:
        raise HTTPException(status_code=422, detail="An active mode is required")
    chat = Chat(
        mode_id=mode.id,
        user_id=owner.id,
        mode_name_snapshot=mode.name,
        title=request.title.strip(),
        client_request_id=request.client_request_id,
    )
    session.add(chat)
    chat = await commit_new_chat(chat, owner.id, request.client_request_id, session)
    if chat.mode is None:
        chat.mode = mode
    schedule_watch_state_changed(get_settings())
    return chat_response(chat)


@app.post("/v1/chats/quick", response_model=ChatResponse, status_code=201)
async def create_quick_chat(
    request: QuickChatCreate = QuickChatCreate(),
    device: Device = Depends(current_device),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ChatResponse:
    owner = await owner_for_device(device, session)
    existing = await existing_chat_for_request(owner.id, request.client_request_id, session)
    if existing is not None:
        return chat_response(existing)
    app_config = await app_settings(session, settings)
    quick_model_id = app_config.default_model_id or settings.quick_chat_model_id
    ensure_model(quick_model_id, settings)
    quick_override = await session.get(PromptOverride, "quick_chat_mode")
    quick_prompt = quick_override.text if quick_override is not None else QUICK_CHAT_MODE_PROMPT
    mode = await session.scalar(select(Mode).where(Mode.name == QUICK_CHAT_MODE_NAME))
    if mode is None:
        mode = Mode(
            name=QUICK_CHAT_MODE_NAME,
            description=QUICK_CHAT_MODE_DESCRIPTION,
            color="#65F5C2",
            icon="spark",
            system_prompt=quick_prompt,
            response_model_id=quick_model_id,
        )
        session.add(mode)
        await session.flush()
    elif mode.deleted_at is not None:
        mode.deleted_at = None
        mode.description = QUICK_CHAT_MODE_DESCRIPTION
        mode.system_prompt = quick_prompt
    elif mode.system_prompt != quick_prompt:
        mode.system_prompt = quick_prompt
    mode.response_model_id = quick_model_id

    chat = Chat(
        mode_id=mode.id,
        user_id=owner.id,
        mode_name_snapshot=mode.name,
        title=QUICK_CHAT_MODE_NAME,
        client_request_id=request.client_request_id,
    )
    session.add(chat)
    chat = await commit_new_chat(chat, owner.id, request.client_request_id, session)
    if chat.mode is None:
        chat.mode = mode
    schedule_watch_state_changed(get_settings())
    return chat_response(chat)


async def existing_chat_for_request(
    user_id: str,
    client_request_id: str | None,
    session: AsyncSession,
) -> Chat | None:
    if client_request_id is None:
        return None
    return await session.scalar(
        select(Chat)
        .options(selectinload(Chat.mode))
        .where(Chat.user_id == user_id, Chat.client_request_id == client_request_id)
    )


async def commit_new_chat(
    chat: Chat,
    user_id: str,
    client_request_id: str | None,
    session: AsyncSession,
) -> Chat:
    try:
        # Flush first: `Chat.id` is assigned by a Python-side default during
        # flush, and the event must name the chat it announces.
        await session.flush()
        account_events.record_account_event(
            session,
            account_events.CHAT_CREATED,
            {"chat_id": chat.id},
            owner_id=user_id,
        )
        await session.commit()
        await session.refresh(chat)
        return chat
    except IntegrityError:
        await session.rollback()
        existing = await existing_chat_for_request(user_id, client_request_id, session)
        if existing is None:
            raise
        return existing


@app.patch("/v1/chats/{chat_id}", response_model=ChatResponse)
async def update_chat(
    chat_id: str,
    request: ChatUpdate,
    device: Device = Depends(current_device),
    session: AsyncSession = Depends(get_session),
) -> ChatResponse:
    owner = await owner_for_device(device, session)
    chat = await session.scalar(select(Chat).options(selectinload(Chat.mode)).where(Chat.id == chat_id, Chat.user_id == owner.id))
    if chat is None or chat.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Chat not found")
    if request.title is not None:
        chat.title = request.title
        chat.title_generation_state = "manual"
    if request.pinned is not None:
        chat.pinned = request.pinned
    chat.updated_at = utcnow()
    account_events.record_account_event(
        session, account_events.CHAT_UPDATED, {"chat_id": chat.id}, owner_id=owner.id
    )
    await session.commit()
    schedule_watch_state_changed(get_settings())
    return chat_response(chat)


@app.delete("/v1/chats/{chat_id}", status_code=204)
async def delete_chat(
    chat_id: str,
    device: Device = Depends(current_device),
    session: AsyncSession = Depends(get_session),
) -> None:
    owner = await owner_for_device(device, session)
    chat = await session.scalar(select(Chat).where(Chat.id == chat_id, Chat.user_id == owner.id))
    if chat is None or chat.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Chat not found")
    chat.deleted_at = utcnow()
    account_events.record_account_event(
        session, account_events.CHAT_DELETED, {"chat_id": chat.id}, owner_id=owner.id
    )
    await session.commit()
    schedule_watch_state_changed(get_settings())


async def _with_referenced_sources(
    session: AsyncSession, messages: list[Message]
) -> list[MessageResponse]:
    """Attach the web sources each answer actually used, in one extra query.

    This is a read-only projection for the console's diagnostics panel; it does
    not touch retrieval, and messages without an audit trail stay empty.
    """
    responses = [MessageResponse.model_validate(message) for message in messages]
    assistant_ids = [message.id for message in messages if message.role == "assistant"]
    if not assistant_ids:
        return responses
    rows = (
        await session.scalars(
            select(ReferencedWebSource)
            .where(ReferencedWebSource.message_id.in_(assistant_ids))
            .order_by(ReferencedWebSource.retrieved_at)
        )
    ).all()
    by_message = {response.id: response for response in responses}
    for row in rows:
        target = by_message.get(row.message_id or "")
        if target is not None:
            target.sources.append(ReferencedSourceResponse.model_validate(row))
    return responses


@app.get("/v1/chats/{chat_id}/messages", response_model=list[MessageResponse])
async def list_messages(
    chat_id: str,
    limit: int | None = Query(default=None, ge=1, le=100),
    device: Device = Depends(current_device),
    session: AsyncSession = Depends(get_session),
) -> list[MessageResponse]:
    owner = await owner_for_device(device, session)
    chat = await session.scalar(select(Chat).where(Chat.id == chat_id, Chat.user_id == owner.id))
    if chat is None or chat.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Chat not found")
    statement = select(Message).where(Message.chat_id == chat_id)
    if limit is None:
        messages = list((await session.scalars(statement.order_by(Message.created_at))).all())
        return await _with_referenced_sources(session, messages)

    newest_first = list(
        (await session.scalars(statement.order_by(Message.created_at.desc()).limit(limit))).all()
    )
    return await _with_referenced_sources(session, list(reversed(newest_first)))


@app.get("/v1/chats/{chat_id}/sources", response_model=ChatSourcesResponse)
async def list_chat_sources(
    chat_id: str,
    device: Device = Depends(current_device),
    session: AsyncSession = Depends(get_session),
) -> ChatSourcesResponse:
    """Chat-scoped sources only: its Working Sources and its web references.

    This is a read-only projection for the console. It deliberately does not
    touch the mode knowledge base, which is a separate system, and it never
    creates a source.
    """
    owner = await owner_for_device(device, session)
    chat = await session.scalar(select(Chat).where(Chat.id == chat_id, Chat.user_id == owner.id))
    if chat is None or chat.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Chat not found")

    working_rows = (
        await session.scalars(
            select(KnowledgeSource)
            .where(
                KnowledgeSource.chat_id == chat_id,
                KnowledgeSource.source_tier == "working",
                KnowledgeSource.deleted_at.is_(None),
            )
            .order_by(KnowledgeSource.created_at)
        )
    ).all()
    referenced_rows = (
        await session.scalars(
            select(ReferencedWebSource)
            .where(ReferencedWebSource.chat_id == chat_id)
            .order_by(ReferencedWebSource.retrieved_at)
        )
    ).all()

    # Select metadata only: full cached documents must not travel with the index.
    reads = (await session.execute(
        select(RawWebSource.id, RawWebSource.url, RawWebSource.title,
               RawWebSource.retrieved_at, func.length(RawWebSource.content).label("character_count"))
        .where(RawWebSource.chat_id == chat_id, func.length(func.trim(RawWebSource.content)) > 0)
        .order_by(RawWebSource.retrieved_at)
    )).all()
    read_by_url = {row.url: row for row in reads}
    working_urls = {row.origin_url for row in working_rows if row.origin_url}
    references = []
    seen_urls = set(working_urls)
    for row in referenced_rows:
        if row.url in seen_urls:
            continue
        seen_urls.add(row.url)
        entry = ChatReferencedSourceResponse.model_validate(row)
        read = read_by_url.get(row.url)
        if read is not None:
            entry.read_at = read.retrieved_at
            entry.character_count = read.character_count
        references.append(entry)
    # Reads reached through redirects/direct URLs may have no search result.
    for row in reads:
        if row.url in seen_urls:
            continue
        seen_urls.add(row.url)
        references.append(ChatReferencedSourceResponse(
            id=row.id, title=row.title, url=row.url, snippet="",
            retrieved_at=row.retrieved_at, message_id=None,
            read_at=row.retrieved_at, character_count=row.character_count,
        ))
    return ChatSourcesResponse(
        working=[ChatWorkingSourceResponse.model_validate(row) for row in working_rows],
        referenced=references,
    )


@app.get("/v1/chats/{chat_id}/sources/{source_id}/text", response_model=ChatWorkingSourceTextResponse)
async def get_chat_working_source_text(
    chat_id: str,
    source_id: str,
    device: Device = Depends(current_device),
    session: AsyncSession = Depends(get_session),
) -> ChatWorkingSourceTextResponse:
    """Return the saved text only to the owner of this chat and source."""
    owner = await owner_for_device(device, session)
    source = await session.scalar(
        select(KnowledgeSource)
        .join(Chat, KnowledgeSource.chat_id == Chat.id)
        .where(
            Chat.id == chat_id,
            Chat.user_id == owner.id,
            Chat.deleted_at.is_(None),
            KnowledgeSource.id == source_id,
            KnowledgeSource.chat_id == chat_id,
            KnowledgeSource.source_tier == "working",
            KnowledgeSource.deleted_at.is_(None),
        )
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Working source not found")
    try:
        content = Path(source.storage_path).read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=503, detail="Saved source text is unavailable") from exc
    return ChatWorkingSourceTextResponse(
        id=source.id,
        title=source.title,
        status=source.status,
        content=content,
        character_count=len(content),
    )


@app.post("/v1/chats/{chat_id}/messages", response_model=JobResponse, status_code=202)
async def create_message(
    chat_id: str,
    request: MessageCreate,
    device: Device = Depends(current_device),
    client_sent_ms: str | None = Header(None, alias="X-WristMind-Client-Sent-Ms"),
    session: AsyncSession = Depends(get_session),
) -> Job:
    received_ms = round(time.time() * 1000)
    client_delay_ms = None
    client_sent_epoch_ms: int | None = None
    if client_sent_ms:
        try:
            client_sent_epoch_ms = int(client_sent_ms)
            client_delay_ms = max(0, received_ms - client_sent_epoch_ms)
        except ValueError:
            client_sent_epoch_ms = None
    logger.info(
        "wm_send_server_received request_id=%s chat_id=%s received_unix_ms=%s client_to_server_ms=%s",
        request.client_request_id,
        chat_id,
        received_ms,
        client_delay_ms,
    )
    chat = await session.scalar(select(Chat).options(selectinload(Chat.mode)).where(Chat.id == chat_id))
    owner = await owner_for_device(device, session)
    if chat is None or chat.user_id != owner.id or chat.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Chat not found")
    existing = await session.scalar(
        select(Job).where(
            Job.kind == "ANSWER",
            Job.client_request_id == request.client_request_id,
        )
    )
    if existing:
        if existing.payload.get("chat_id") != chat.id:
            raise HTTPException(status_code=409, detail="Request ID is already used by another chat")
        logger.info(
            "wm_send_job_reused request_id=%s job_id=%s elapsed_ms=%s",
            request.client_request_id,
            existing.id,
            round(time.time() * 1000) - received_ms,
        )
        return existing
    has_user_message = await session.scalar(
        select(Message.id).where(Message.chat_id == chat.id, Message.role == "user").limit(1)
    )
    user_message = Message(chat_id=chat.id, role="user", content=request.text.strip())
    assistant_message = Message(chat_id=chat.id, role="assistant", content="", status="streaming")
    session.add_all([user_message, assistant_message])
    await session.flush()
    job = Job(
        kind="ANSWER",
        status="queued",
        device_id=device.id,
        client_request_id=request.client_request_id,
        payload={
            "chat_id": chat.id,
            "user_message_id": user_message.id,
            "assistant_message_id": assistant_message.id,
            # Research is a response-quality pass. The local-first router,
            # not this API boundary, decides whether the turn needs internet.
            "web_search": request.web_search,
            "web_research": request.web_research,
            "research_mode": request.research_mode,
            # Diagnostic-only: lets the worker report "since send" for the
            # latency trace. No pipeline logic reads this key.
            "client_sent_ms": client_sent_epoch_ms,
        },
    )
    session.add(job)
    if has_user_message is None and chat.title_generation_state == "idle":
        # The worker always claims ANSWER jobs before this low-priority title job, so
        # naming can never postpone the first streamed response.
        chat.title_generation_state = "queued"
        session.add(
            Job(
                kind="CHAT_TITLE",
                status="queued",
                device_id=device.id,
                client_request_id=f"chat-title:{chat.id}",
                payload={"chat_id": chat.id, "first_message": user_message.content[:1000]},
            )
        )
    await session.flush()
    session.add(JobEvent(job_id=job.id, event="state", data={"state": "queued"}))
    chat.updated_at = utcnow()
    account_events.record_account_event(
        session,
        account_events.MESSAGE_CREATED,
        {"chat_id": chat.id, "message_id": user_message.id},
        owner_id=owner.id,
    )
    account_events.record_account_event(
        session, account_events.CHAT_UPDATED, {"chat_id": chat.id}, owner_id=owner.id
    )
    await session.commit()
    await session.refresh(job)
    # Diagnostic-only trace. Recording is a local append plus a non-blocking
    # queue push; it never delays the 202 response.
    latency_trace.record(
        latency_trace.SERVER_RECEIVED,
        trace_id=request.client_request_id,
        message_id=assistant_message.id,
        job_id=job.id,
        since_send=0 if client_delay_ms is not None else None,
        duration_ms=client_delay_ms,
        client_to_server_ms=client_delay_ms,
        question_chars=len(request.text.strip()),
        research_mode=bool(request.research_mode),
    )
    logger.info(
        "wm_send_job_created request_id=%s job_id=%s elapsed_ms=%s",
        request.client_request_id,
        job.id,
        round(time.time() * 1000) - received_ms,
    )
    schedule_watch_state_changed(get_settings())
    return job


@app.post("/v1/chats/{chat_id}/fallback-messages")
async def sync_fallback_message(
    chat_id: str,
    request: FallbackMessageSync,
    device: Device = Depends(current_device),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """Commit one answer produced by the VPS fallback without generating it again."""
    owner = await owner_for_device(device, session)
    chat = await session.scalar(select(Chat).where(Chat.id == chat_id, Chat.user_id == owner.id))
    if chat is None or chat.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Chat not found")

    # A timed-out normal POST may have reached the main server before the watch
    # switched to fallback. Prefer that authoritative job instead of duplicating
    # the user's turn during reconciliation.
    existing_answer = await session.scalar(
        select(Job).where(Job.kind == "ANSWER", Job.client_request_id == request.request_id)
    )
    if existing_answer is not None:
        return {"status": "main_answer_exists"}
    existing_sync = await session.scalar(
        select(Job).where(Job.kind == "FALLBACK_SYNC", Job.client_request_id == request.request_id)
    )
    if existing_sync is not None:
        return {"status": "already_synced"}

    had_user_message = await session.scalar(
        select(Message.id).where(Message.chat_id == chat.id, Message.role == "user").limit(1)
    )
    user_message = Message(
        chat_id=chat.id,
        role="user",
        content=request.user_text.strip(),
        timings={"fallback": True},
    )
    assistant_message = Message(
        chat_id=chat.id,
        role="assistant",
        content=request.assistant_text.strip(),
        status="complete",
        provider="deepseek",
        model_id="deepseek:deepseek-flash",
        timings={"fallback": True, "sources_available": False},
    )
    session.add_all([user_message, assistant_message])
    await session.flush()
    completed_at = utcnow()
    session.add(Job(
        kind="FALLBACK_SYNC",
        status="complete",
        device_id=device.id,
        client_request_id=request.request_id,
        payload={
            "chat_id": chat.id,
            "user_message_id": user_message.id,
            "assistant_message_id": assistant_message.id,
        },
        result={"message_id": assistant_message.id, "fallback": True},
        started_at=completed_at,
        completed_at=completed_at,
    ))
    if not had_user_message and chat.title == "Новый чат":
        chat.title = request.user_text.strip()[:120]
        chat.title_generation_state = "complete"
    chat.updated_at = completed_at
    account_events.record_account_event(
        session,
        account_events.MESSAGE_CREATED,
        {"chat_id": chat.id, "message_id": user_message.id},
        owner_id=owner.id,
    )
    account_events.record_account_event(
        session, account_events.CHAT_UPDATED, {"chat_id": chat.id}, owner_id=owner.id
    )
    await session.commit()
    # Diagnostic-only: one marker that this turn was served by the VPS fallback.
    latency_trace.record(
        latency_trace.FALLBACK,
        trace_id=request.request_id,
        message_id=assistant_message.id,
        job_id=None,
        fallback_used=True,
        provider="deepseek",
        model="deepseek:deepseek-flash",
        response_chars=len(assistant_message.content),
        stage="vps_fallback_sync",
    )
    latency_trace.schedule_request_summary(request.request_id)
    schedule_watch_state_changed(get_settings())
    return {"status": "synced"}


@app.post("/v1/diagnostics/latency", status_code=204)
async def record_watch_latency(
    request: dict,
    device: Device = Depends(current_device),
) -> None:
    """Diagnostic-only sink for watch-side latency events.

    Additive endpoint: it records one safe event (identifiers, timings, sizes)
    into the latency trace and its optional Telegram feed. It never reads or
    writes pipeline state, always answers 204, and swallows all failures so a
    watch can fire it without any chance of affecting the answer.
    """
    try:
        event = str(request.get("event") or "")[:64]
        if not event:
            return
        trace_id = request.get("trace_id") or request.get("request_id")
        # Bounded numeric metric pass-through: exact watch metric names plus the
        # generic durations. Non-numeric or unknown keys are ignored.
        metrics = {
            key: request[key]
            for key in (
                "send_started_ms",
                "first_sse_delta_received_ms",
                "first_visible_text_rendered_ms",
                "since_send_ms",
                "elapsed_ms",
                "duration_ms",
                "delta_chars",
                "stream_chars",
                "payload_chars",
                "question_chars",
            )
            if isinstance(request.get(key), (int, float))
        }
        latency_trace.record(
            event,
            trace_id=str(trace_id)[:100] if trace_id else None,
            message_id=str(request["message_id"])[:64] if request.get("message_id") else None,
            job_id=str(request["job_id"])[:64] if request.get("job_id") else None,
            since_send=metrics.get("since_send_ms"),
            duration_ms=metrics.get("duration_ms"),
            route=str(request["route"])[:32] if request.get("route") else None,
            model=str(request["model"])[:160] if request.get("model") else None,
            stage=str(request["stage"])[:32] if request.get("stage") else None,
            error_type=str(request["error_type"])[:64] if request.get("error_type") else None,
            source="watch",
            **{key: value for key, value in metrics.items() if key not in {"since_send_ms", "duration_ms"}},
        )
    except Exception:  # pragma: no cover - diagnostics must never fail
        logger.debug("Unable to record watch latency event", exc_info=True)


@app.get("/v1/jobs/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str,
    device: Device = Depends(current_device),
    session: AsyncSession = Depends(get_session),
) -> Job:
    job = await session.get(Job, job_id)
    owner = await owner_for_device(device, session)
    if job is None or not await job_belongs_to_user(job, owner.id, session):
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/v1/jobs/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(
    job_id: str,
    device: Device = Depends(current_device),
    session: AsyncSession = Depends(get_session),
) -> Job:
    job = await session.get(Job, job_id)
    owner = await owner_for_device(device, session)
    if job is None or not await job_belongs_to_user(job, owner.id, session):
        raise HTTPException(status_code=404, detail="Job not found")
    if job.kind != "ANSWER":
        raise HTTPException(status_code=409, detail="Only answer jobs can be cancelled")
    changed = await session.execute(
        update(Job)
        .where(Job.id == job_id, Job.status.in_(("queued", "running")))
        .values(status="cancelled", completed_at=utcnow())
    )
    if changed.rowcount:
        await session.execute(
            update(Message)
            .where(Message.id == job.payload["assistant_message_id"])
            .values(status="cancelled")
        )
        session.add(JobEvent(job_id=job_id, event="cancelled", data={}))
        await session.commit()
        schedule_watch_state_changed(get_settings())
    await session.refresh(job)
    return job


@app.get("/v1/jobs/{job_id}/events")
async def job_events(
    job_id: str,
    after: int = 0,
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
    device: Device = Depends(current_device),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    cursor = max(after, int(last_event_id or 0))
    owner = await owner_for_device(device, session)
    initial_job = await session.get(Job, job_id)
    if initial_job is None or not await job_belongs_to_user(initial_job, owner.id, session):
        raise HTTPException(status_code=404, detail="Job not found")

    async def stream():
        nonlocal cursor
        while True:
            async with SessionFactory() as session:
                job = await session.get(Job, job_id)
                if job is None:
                    yield "event: error\ndata: {\"detail\":\"Job not found\"}\n\n"
                    return
                events = (
                    await session.scalars(
                        select(JobEvent)
                        .where(JobEvent.job_id == job_id, JobEvent.id > cursor)
                        .order_by(JobEvent.id)
                    )
                ).all()
                for item in events:
                    cursor = item.id
                    yield f"id: {item.id}\nevent: {item.event}\ndata: {json.dumps(item.data, ensure_ascii=False)}\n\n"
                if job.status in {"complete", "failed", "cancelled"} and not events:
                    return
            if not events:
                yield ": keepalive\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/v1/events")
async def account_events_stream(
    after: int = 0,
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
    device: Device = Depends(current_device),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """Live account-level stream for the control panel.

    `after=0` means a client that has just bootstrapped and already holds current
    state: it starts at the tail, because replaying history would only cause
    redundant refetches. Any non-zero cursor resumes exactly where it stopped,
    including the browser's own reconnect through `Last-Event-ID`. A cursor that
    fell behind the retention window gets one `resync` event instead of a silent
    gap.

    Identifier-only payloads are deliberate: the reader refetches the slice the
    event names, so this stream can never serve stale entity bodies as if they
    were current.
    """
    owner = await owner_for_device(device, session)
    cursor, resynced = await account_events.resolve_cursor(session, after, last_event_id)

    async def stream():
        nonlocal cursor
        if resynced:
            yield f"event: {account_events.RESYNC}\ndata: {{}}\n\n"
        while True:
            async with SessionFactory() as session:
                events = (
                    await session.scalars(
                        select(AccountEvent)
                        .where(
                            or_(
                                AccountEvent.owner_id == owner.id,
                                AccountEvent.owner_id.is_(None),
                            ),
                            AccountEvent.id > cursor,
                        )
                        .order_by(AccountEvent.id)
                        .limit(200)
                    )
                ).all()
                for item in events:
                    cursor = item.id
                    yield (
                        f"id: {item.id}\nevent: {item.type}\n"
                        f"data: {json.dumps(item.data, ensure_ascii=False)}\n\n"
                    )
            if not events:
                yield ": keepalive\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/v1/knowledge", response_model=list[KnowledgeSourceResponse])
async def list_knowledge(
    mode_id: str | None = None,
    device: Device = Depends(current_device),
    session: AsyncSession = Depends(get_session),
) -> list[KnowledgeSource]:
    owner = await owner_for_device(device, session)
    query = select(KnowledgeSource).where(
        KnowledgeSource.deleted_at.is_(None), KnowledgeSource.user_id == owner.id,
        KnowledgeSource.chat_id.is_(None),
    )
    if mode_id:
        query = query.where(KnowledgeSource.mode_id == mode_id)
    return list((await session.scalars(query.order_by(KnowledgeSource.created_at.desc()))).all())


@app.get("/v1/chats/{chat_id}/source-candidates", response_model=list[ChatSourceCandidateResponse])
async def list_chat_source_candidates(
    chat_id: str,
    device: Device = Depends(current_device),
    session: AsyncSession = Depends(get_session),
) -> list[ChatSourceCandidateResponse]:
    owner = await owner_for_device(device, session)
    chat = await session.scalar(select(Chat).where(Chat.id == chat_id, Chat.user_id == owner.id, Chat.deleted_at.is_(None)))
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    candidates = (await session.scalars(
        select(ChatSourceCandidate).where(
            ChatSourceCandidate.chat_id == chat.id,
            ChatSourceCandidate.saved_source_id.is_(None),
            ChatSourceCandidate.dismissed_at.is_(None),
        ).order_by(ChatSourceCandidate.created_at)
    )).all()
    return [ChatSourceCandidateResponse(
        id=item.id, title=item.title, url=item.url,
        preview=" ".join(item.content.split())[:180],
        content=(item.content[:18_000].rsplit(" ", 1)[0] if len(item.content) > 18_000 else item.content),
        truncated=len(item.content) > 18_000,
    ) for item in candidates]


@app.post("/v1/chats/{chat_id}/source-candidates/{candidate_id}/save", response_model=JobResponse, status_code=202)
async def save_chat_source_candidate(
    chat_id: str,
    candidate_id: str,
    request: ChatSourceSaveRequest,
    device: Device = Depends(current_device),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Job:
    owner = await owner_for_device(device, session)
    chat = await session.scalar(select(Chat).where(Chat.id == chat_id, Chat.user_id == owner.id, Chat.deleted_at.is_(None)))
    candidate = await session.get(ChatSourceCandidate, candidate_id)
    if chat is None or candidate is None or candidate.chat_id != chat_id:
        raise HTTPException(status_code=404, detail="Source suggestion not found")
    existing = await session.scalar(select(Job).where(Job.device_id == device.id, Job.client_request_id == request.client_request_id))
    if existing:
        return existing
    if candidate.saved_source_id:
        raise HTTPException(status_code=409, detail="Source is already saved")
    from .feature_capabilities import require
    require(settings, 'digitization')
    source_id = str(uuid4())
    target_dir = settings.storage_dir / "sources" / source_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "source.txt"
    target.write_text(candidate.content, encoding="utf-8")
    source = KnowledgeSource(
        id=source_id, mode_id=chat.mode_id, chat_id=None, user_id=owner.id,
        title=candidate.title[:160], filename="source.txt", media_type="text/plain",
        # Legacy explicit action: keep using the existing mode-level source
        # mechanism, outside the new Referenced → Working pipeline.
        processing_mode="WEB", origin_url=candidate.url, storage_path=str(target),
    )
    session.add(source)
    # Flush the source first: PostgreSQL otherwise sees the candidate's foreign
    # key update before the referenced row exists.
    await session.flush()
    candidate.saved_source_id = source.id
    job = Job(kind="INGEST", status="queued", device_id=device.id, client_request_id=request.client_request_id, payload={"source_id": source.id})
    session.add(job)
    await session.flush()
    session.add(JobEvent(job_id=job.id, event="state", data={"state": "queued"}))
    account_events.record_account_event(
        session,
        account_events.SOURCE_UPDATED,
        {"source_id": source.id, "chat_id": None, "mode_id": source.mode_id},
        owner_id=owner.id,
    )
    await session.commit()
    await session.refresh(job)
    return job


@app.delete("/v1/chats/{chat_id}/source-candidates/{candidate_id}", status_code=204)
async def dismiss_chat_source_candidate(
    chat_id: str, candidate_id: str, device: Device = Depends(current_device), session: AsyncSession = Depends(get_session),
) -> None:
    owner = await owner_for_device(device, session)
    candidate = await session.scalar(
        select(ChatSourceCandidate).join(Chat).where(
            ChatSourceCandidate.id == candidate_id, ChatSourceCandidate.chat_id == chat_id,
            Chat.user_id == owner.id, Chat.deleted_at.is_(None),
        )
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="Source suggestion not found")
    candidate.dismissed_at = utcnow()
    account_events.record_account_event(
        session,
        account_events.SOURCE_UPDATED,
        {"chat_id": chat_id},
        owner_id=owner.id,
    )
    await session.commit()


@app.get("/v1/knowledge/{source_id}", response_model=KnowledgeSourceDetailResponse)
async def get_knowledge_source(
    source_id: str,
    chunk_offset: int = Query(default=0, ge=0),
    chunk_limit: int = Query(default=50, ge=1, le=100),
    device: Device = Depends(current_device),
    session: AsyncSession = Depends(get_session),
) -> KnowledgeSourceDetailResponse:
    owner = await owner_for_device(device, session)
    source = await session.scalar(
        select(KnowledgeSource).where(
            KnowledgeSource.id == source_id,
            KnowledgeSource.deleted_at.is_(None),
            KnowledgeSource.user_id == owner.id,
        )
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Knowledge source not found")
    chunks = list(
        (
            await session.scalars(
                select(KnowledgeChunk)
                .where(KnowledgeChunk.source_id == source.id)
                .order_by(KnowledgeChunk.ordinal)
                .offset(chunk_offset)
                .limit(chunk_limit)
            )
        ).all()
    )
    # Older OCR sources were created before page ranges were stored.  If there
    # is exactly one chunk per page, ordinal is a reliable, lossless fallback.
    # New sources receive explicit ranges from the ingestion worker.
    if source.page_count == source.chunk_count and source.page_count > 0:
        for chunk in chunks:
            if chunk.page_from is None:
                page_number = chunk.ordinal + 1
                chunk.page_from = page_number
                chunk.page_to = page_number
    return KnowledgeSourceDetailResponse(
        **KnowledgeSourceResponse.model_validate(source).model_dump(),
        chunks=chunks,
        chunk_offset=chunk_offset,
        chunk_limit=chunk_limit,
        has_more=source.chunk_count > chunk_offset + len(chunks),
    )


@app.post("/v1/knowledge", response_model=JobResponse, status_code=202)
async def upload_knowledge(
    mode_id: str = Form(...),
    processing_mode: str = Form(..., pattern="^(OCR|VISION)$"),
    client_request_id: str = Form(..., min_length=1, max_length=100),
    title: str = Form(..., min_length=1, max_length=160),
    file: UploadFile = File(...),
    device: Device = Depends(current_device),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Job:
    owner = await owner_for_device(device, session)
    existing = await session.scalar(
        select(Job).where(
            Job.device_id == device.id,
            Job.client_request_id == client_request_id,
        )
    )
    if existing:
        await file.close()
        return existing
    mode = await session.get(Mode, mode_id)
    if mode is None or mode.deleted_at is not None:
        await file.close()
        raise HTTPException(status_code=422, detail="An active mode is required")
    from .feature_capabilities import require
    require(settings, 'digitization')
    if processing_mode == 'VISION' and settings.selfhost_enabled:
        from .model_capabilities import selected
        if not selected(settings, 'vision'): raise HTTPException(409, 'Добавьте Vision-модель или выберите OCR')
    filename = Path(file.filename or "source.bin").name
    suffix = Path(filename).suffix.lower()
    if suffix not in {".pdf", ".jpg", ".jpeg", ".png", ".webp"}:
        await file.close()
        raise HTTPException(status_code=415, detail="Only PDF and images are supported")
    source_id = str(uuid4())
    target_dir = settings.storage_dir / "sources" / source_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"original{suffix}"
    size = 0
    try:
        with target.open("wb") as output:
            while chunk := await file.read(64 * 1024):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise HTTPException(status_code=413, detail="File is too large")
                output.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
    source = KnowledgeSource(
        id=source_id,
        mode_id=mode_id,
        user_id=owner.id,
        title=title.strip(),
        filename=filename,
        media_type=file.content_type or "application/octet-stream",
        processing_mode=processing_mode,
        storage_path=str(target),
    )
    session.add(source)
    job = Job(
        kind="INGEST",
        status="queued",
        device_id=device.id,
        client_request_id=client_request_id,
        payload={"source_id": source.id},
    )
    session.add(job)
    await session.flush()
    session.add(JobEvent(job_id=job.id, event="state", data={"state": "queued"}))
    account_events.record_account_event(
        session,
        account_events.SOURCE_UPDATED,
        {"source_id": source.id, "mode_id": source.mode_id},
        owner_id=owner.id,
    )
    await session.commit()
    await session.refresh(job)
    return job


@app.post(
    "/v1/knowledge/{source_id}/reprocess",
    response_model=JobResponse,
    status_code=202,
)
async def reprocess_knowledge(
    source_id: str,
    request: KnowledgeReprocessRequest,
    device: Device = Depends(current_device),
    session: AsyncSession = Depends(get_session),
) -> Job:
    owner = await owner_for_device(device, session)
    existing = await session.scalar(
        select(Job).where(
            Job.device_id == device.id,
            Job.client_request_id == request.client_request_id,
        )
    )
    if existing:
        return existing
    source = await session.scalar(select(KnowledgeSource).where(KnowledgeSource.id == source_id, KnowledgeSource.user_id == owner.id))
    if source is None or source.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Knowledge source not found")
    if source.status in {"queued", "processing"}:
        raise HTTPException(status_code=409, detail="Knowledge source is already processing")
    if not Path(source.storage_path).is_file():
        raise HTTPException(status_code=409, detail="Original source file is missing")

    await session.execute(delete(KnowledgeChunk).where(KnowledgeChunk.source_id == source.id))
    source.status = "queued"
    source.error = None
    source.page_count = 0
    source.chunk_count = 0
    source.token_count = 0
    job = Job(
        kind="INGEST",
        status="queued",
        device_id=device.id,
        client_request_id=request.client_request_id,
        payload={"source_id": source.id},
    )
    session.add(job)
    await session.flush()
    session.add(JobEvent(job_id=job.id, event="state", data={"state": "queued"}))
    account_events.record_account_event(
        session,
        account_events.SOURCE_UPDATED,
        {"source_id": source.id, "mode_id": source.mode_id},
        owner_id=owner.id,
    )
    await session.commit()
    await session.refresh(job)
    return job


@app.delete("/v1/knowledge/{source_id}", status_code=204)
async def delete_knowledge(
    source_id: str,
    device: Device = Depends(current_device),
    session: AsyncSession = Depends(get_session),
) -> None:
    owner = await owner_for_device(device, session)
    source = await session.scalar(select(KnowledgeSource).where(KnowledgeSource.id == source_id, KnowledgeSource.user_id == owner.id))
    if source is None or source.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Knowledge source not found")
    source.deleted_at = utcnow()
    account_events.record_account_event(
        session,
        account_events.SOURCE_REMOVED,
        {"source_id": source.id, "mode_id": source.mode_id},
        owner_id=owner.id,
    )
    await session.commit()
