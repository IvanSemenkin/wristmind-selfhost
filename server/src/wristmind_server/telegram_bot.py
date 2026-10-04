"""Small Telegram control surface for WristMind."""
from __future__ import annotations

import logging
import json
import secrets
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings
from .database import SessionFactory
from .db_models import Chat, Device, Job, JobEvent, KnowledgeSource, Message, Mode, PairingCode, TelegramAccount, TelegramEmojiDraft, User, utcnow
from .security import hash_secret

logger = logging.getLogger(__name__)
QUICK_CHAT_MODE_NAME = "Быстрый чат"


class TelegramClient:
    def __init__(self, settings: Settings):
        self.token = settings.telegram_bot_token.get_secret_value() if settings.telegram_bot_token else ""
        self.api_base = f"https://api.telegram.org/bot{self.token}"
        self.file_base = f"https://api.telegram.org/file/bot{self.token}"

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    async def request(
        self,
        method: str,
        payload: dict[str, object],
        *,
        timeout: float = 12,
    ) -> Any:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(f"{self.api_base}/{method}", json=payload)
            response.raise_for_status()
            body = response.json()
        if not body.get("ok"):
            raise RuntimeError(f"Telegram {method} failed")
        return body.get("result", {})

    async def get_updates(self, offset: int) -> list[dict[str, object]]:
        result = await self.request(
            "getUpdates",
            {
                "offset": offset,
                "timeout": 25,
                "allowed_updates": ["message", "callback_query"],
            },
            timeout=35,
        )
        if not isinstance(result, list):
            return []
        return [item for item in result if isinstance(item, dict)]

    async def send(self, chat_id: str, text: str, keyboard: list[list[dict[str, str]]] | None = None) -> None:
        payload: dict[str, object] = {"chat_id": chat_id, "text": text[:4096]}
        if keyboard:
            payload["reply_markup"] = {"inline_keyboard": keyboard}
        await self.request("sendMessage", payload)

    async def answer_callback(self, callback_id: str, text: str = "") -> None:
        await self.request("answerCallbackQuery", {"callback_query_id": callback_id, "text": text[:200]})

    async def download(self, file_id: str) -> tuple[str, bytes]:
        file_meta = await self.request("getFile", {"file_id": file_id})
        file_path = str(file_meta.get("file_path", ""))
        if not file_path or ".." in Path(file_path).parts:
            raise RuntimeError("Telegram returned an invalid file path")
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(f"{self.file_base}/{file_path}")
            response.raise_for_status()
            return file_path, response.content


def bot_is_enabled(settings: Settings) -> bool:
    return settings.telegram_bot_token is not None and settings.telegram_owner_id is not None


async def _account_for_update(
    session: AsyncSession, telegram_user_id: str, chat_id: str, settings: Settings
) -> TelegramAccount | None:
    if settings.telegram_owner_id is None or telegram_user_id != str(settings.telegram_owner_id):
        return None
    account = await session.scalar(select(TelegramAccount).where(TelegramAccount.telegram_user_id == telegram_user_id))
    if account:
        if account.chat_id != chat_id:
            account.chat_id = chat_id
            await session.commit()
        return account
    owner = await session.scalar(select(User).where(User.role == "ADMIN", User.deleted_at.is_(None)).order_by(User.created_at))
    if owner is None:
        owner = User(name="Владелец", role="ADMIN")
        session.add(owner)
        await session.flush()
    device = Device(
        name="WristMind Telegram",
        kind="TELEGRAM",
        is_admin=True,
        user_id=owner.id,
        token_hash=hash_secret(f"telegram:{telegram_user_id}:{secrets.token_urlsafe(24)}", settings),
    )
    session.add(device)
    await session.flush()
    account = TelegramAccount(
        telegram_user_id=telegram_user_id,
        chat_id=chat_id,
        user_id=owner.id,
        device_id=device.id,
    )
    session.add(account)
    await session.commit()
    return account


async def _active_modes(session: AsyncSession) -> list[Mode]:
    return list((await session.scalars(select(Mode).where(Mode.deleted_at.is_(None), Mode.name != QUICK_CHAT_MODE_NAME).order_by(Mode.name))).all())


def _mode_keyboard(modes: list[Mode]) -> list[list[dict[str, str]]]:
    rows = [[{"text": f"{mode.icon} {mode.name}", "callback_data": f"mode:{mode.id}"}] for mode in modes]
    rows.append([{"text": "➕ Новый чат", "callback_data": "new"}, {"text": "🩺 Статус", "callback_data": "status"}])
    return rows


async def _show_modes(client: TelegramClient, account: TelegramAccount, session: AsyncSession) -> None:
    modes = await _active_modes(session)
    if not modes:
        await client.send(account.chat_id, "Нет активных режимов. Создай режим в панели WristMind.")
        return
    selected = await session.get(Mode, account.selected_mode_id) if account.selected_mode_id else None
    selected_text = f"Сейчас выбран: {selected.name}\n\n" if selected else ""
    await client.send(account.chat_id, selected_text + "Выбери режим для фото и новых вопросов:", _mode_keyboard(modes))


async def _new_pairing_code(account: TelegramAccount, session: AsyncSession, settings: Settings) -> str:
    code = f"{secrets.randbelow(1_000_000):06d}"
    session.add(PairingCode(
        code_hash=hash_secret(code, settings),
        expires_at=utcnow() + timedelta(minutes=10),
        created_by_id=account.device_id,
        user_id=account.user_id,
    ))
    await session.commit()
    return code


async def _queue_text(account: TelegramAccount, text: str, session: AsyncSession) -> Job | None:
    mode = await session.get(Mode, account.selected_mode_id) if account.selected_mode_id else None
    if mode is None or mode.deleted_at is not None:
        return None
    chat = await session.get(Chat, account.active_chat_id) if account.active_chat_id else None
    if chat is None or chat.deleted_at is not None or chat.mode_id != mode.id:
        chat = Chat(mode_id=mode.id, user_id=account.user_id, mode_name_snapshot=mode.name, title="Новый чат")
        session.add(chat)
        await session.flush()
        account.active_chat_id = chat.id
    request_id = f"telegram:{uuid4()}"
    user_message = Message(chat_id=chat.id, role="user", content=text.strip())
    assistant_message = Message(chat_id=chat.id, role="assistant", content="", status="streaming")
    session.add_all([user_message, assistant_message])
    await session.flush()
    job = Job(
        kind="ANSWER",
        status="queued",
        device_id=account.device_id,
        client_request_id=request_id,
        payload={
            "chat_id": chat.id,
            "user_message_id": user_message.id,
            "assistant_message_id": assistant_message.id,
            "web_search": False,
            "web_research": False,
            "telegram_chat_id": account.chat_id,
        },
    )
    session.add(job)
    await session.flush()
    session.add(JobEvent(job_id=job.id, event="state", data={"state": "queued"}))
    chat.updated_at = utcnow()
    await session.commit()
    return job


async def _store_photo(account: TelegramAccount, file_id: str, caption: str, client: TelegramClient, session: AsyncSession, settings: Settings) -> str:
    mode = await session.get(Mode, account.selected_mode_id) if account.selected_mode_id else None
    if mode is None or mode.deleted_at is not None:
        return "Сначала выбери режим командой /modes."
    file_path, content = await client.download(file_id)
    if not content or len(content) > settings.max_upload_bytes:
        return "Файл слишком большой или пустой."
    source_id = str(uuid4())
    suffix = Path(file_path).suffix.lower() or ".jpg"
    target_dir = settings.storage_dir / "sources" / source_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"original{suffix}"
    target.write_bytes(content)
    source = KnowledgeSource(
        id=source_id,
        mode_id=mode.id,
        user_id=account.user_id,
        title=(caption.strip() or f"Фото из Telegram {utcnow():%d.%m.%Y %H:%M}")[:160],
        filename=Path(file_path).name,
        media_type="image/jpeg",
        processing_mode="VISION",
        storage_path=str(target),
    )
    session.add(source)
    job = Job(
        kind="INGEST",
        status="queued",
        device_id=account.device_id,
        client_request_id=f"telegram-photo:{source_id}",
        payload={"source_id": source.id, "telegram_chat_id": account.chat_id},
    )
    session.add(job)
    await session.flush()
    session.add(JobEvent(job_id=job.id, event="state", data={"state": "queued"}))
    await session.commit()
    return f"Фото добавлено в режим «{mode.name}». Когда обработка завершится, оно будет учитываться в будущих ответах."


async def _status_text(session: AsyncSession) -> str:
    queued = await session.scalar(select(func.count(Job.id)).where(Job.status.in_(("queued", "running")))) or 0
    return "WristMind работает. " + ("Есть задачи в обработке: " + str(queued) + "." if queued else "Очередь пуста.")


async def _emoji_slots(session: AsyncSession) -> tuple[list[list[dict[str, str]]], dict[str, tuple[str, str]]]:
    slots: dict[str, tuple[str, str]] = {
        "bot": ("Главная иконка WristMind Link", "Показывается рядом с приветствием и справкой."),
        "status": ("Проверка состояния", "Кнопка «Статус»: сервер работает или нужна проверка."),
        "pair": ("Подключение часов", "Кнопка или команда для нового кода привязки."),
        "photo": ("Фото в знания", "Подтверждение, что фото добавлено в выбранный режим."),
    }
    rows = [[{"text": purpose, "callback_data": f"emoji:{slot}"}] for slot, (purpose, _) in slots.items()]
    for mode in await _active_modes(session):
        slot = f"mode:{mode.id}"
        slots[slot] = (f"Режим «{mode.name}»", f"Будет иконкой режима «{mode.name}» в Telegram.")
        rows.append([{"text": f"Режим: {mode.name}", "callback_data": f"emoji:{slot}"}])
    return rows, slots


async def _export_emoji_drafts(session: AsyncSession, settings: Settings, user_id: str) -> None:
    drafts = list((await session.scalars(select(TelegramEmojiDraft).where(TelegramEmojiDraft.user_id == user_id).order_by(TelegramEmojiDraft.slot))).all())
    target = settings.storage_dir / "telegram-emoji-drafts.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps([
        {"slot": item.slot, "custom_emoji_id": item.custom_emoji_id, "purpose": item.purpose, "example": item.example}
        for item in drafts
    ], ensure_ascii=False, indent=2), encoding="utf-8")


async def _save_custom_emoji(account: TelegramAccount, entities: object, client: TelegramClient, session: AsyncSession, settings: Settings) -> bool:
    if not account.emoji_target or not isinstance(entities, list):
        return False
    entity = next((item for item in entities if isinstance(item, dict) and item.get("type") == "custom_emoji"), None)
    custom_emoji_id = str(entity.get("custom_emoji_id", "")) if entity else ""
    if not custom_emoji_id:
        return False
    _, slots = await _emoji_slots(session)
    purpose, example = slots.get(account.emoji_target, ("Пользовательская иконка", "Используется в интерфейсе Telegram-бота."))
    draft = await session.scalar(select(TelegramEmojiDraft).where(
        TelegramEmojiDraft.user_id == account.user_id,
        TelegramEmojiDraft.slot == account.emoji_target,
    ))
    if draft is None:
        draft = TelegramEmojiDraft(user_id=account.user_id, slot=account.emoji_target, custom_emoji_id=custom_emoji_id, purpose=purpose, example=example)
        session.add(draft)
    else:
        draft.custom_emoji_id, draft.purpose, draft.example = custom_emoji_id, purpose, example
    slot = account.emoji_target
    account.emoji_target = None
    await session.commit()
    await _export_emoji_drafts(session, settings, account.user_id)
    await client.send(account.chat_id, f"Emoji сохранён для пункта: {purpose}. Его ID записан в приватный файл настроек.")
    return True


async def handle_update(update: dict[str, object], settings: Settings) -> None:
    if not bot_is_enabled(settings):
        return
    client = TelegramClient(settings)
    message = update.get("message")
    callback = update.get("callback_query")
    raw = callback.get("message") if isinstance(callback, dict) else message
    sender = (callback or message).get("from") if isinstance((callback or message), dict) else None
    chat = raw.get("chat") if isinstance(raw, dict) else None
    if not isinstance(sender, dict) or not isinstance(chat, dict) or chat.get("type") != "private":
        return
    telegram_user_id, chat_id = str(sender.get("id", "")), str(chat.get("id", ""))
    # Diagnostic commands are owner-only and need no WristMind account binding,
    # so a dedicated latency bot works without pairing.
    if isinstance(message, dict) and not isinstance(callback, dict):
        candidate_text = str(message.get("text", "")).strip()
        if is_latency_owner(telegram_user_id, settings) and await handle_latency_command(
            candidate_text, chat_id, client, settings
        ):
            return
    async with SessionFactory() as session:
        account = await _account_for_update(session, telegram_user_id, chat_id, settings)
        if account is None:
            await client.send(chat_id, "Этот бот пока не привязан к вашему WristMind.")
            return
        if isinstance(callback, dict):
            data = str(callback.get("data", ""))
            await client.answer_callback(str(callback.get("id", "")))
            if data.startswith("mode:"):
                mode = await session.get(Mode, data.removeprefix("mode:"))
                if mode and mode.deleted_at is None:
                    account.selected_mode_id = mode.id
                    account.active_chat_id = None
                    await session.commit()
                    await client.send(chat_id, f"Выбран режим «{mode.name}». Теперь можно отправить фото или короткий вопрос.")
            elif data == "new":
                account.active_chat_id = None
                await session.commit()
                await client.send(chat_id, "Новый чат начнётся со следующего вопроса.")
            elif data == "status":
                await client.send(chat_id, await _status_text(session))
            elif data.startswith("emoji:"):
                _, slots = await _emoji_slots(session)
                target = data.removeprefix("emoji:")
                if target in slots:
                    account.emoji_target = target
                    await session.commit()
                    purpose, example = slots[target]
                    await client.send(chat_id, f"Нужен emoji для: {purpose}.\nПример: {example}\n\nОтправь следующим сообщением один Premium emoji.")
            return
        if not isinstance(message, dict):
            return
        text = str(message.get("text", "")).strip()
        if await _save_custom_emoji(account, message.get("entities"), client, session, settings):
            return
        if text in {"/start", "/help"}:
            await client.send(chat_id, "WristMind Link\n\n/modes — выбрать режим\n/pair — код подключения часов\n/status — состояние сервера\n/new — новый чат\n\nФото добавляется в базу знаний выбранного режима.\n\n/latency — файл latency-логов\n/latency_status — состояние лога\n/latency_clear — ротация лога")
        elif text == "/modes":
            await _show_modes(client, account, session)
        elif text == "/pair":
            await client.send(chat_id, f"Код подключения часов: {await _new_pairing_code(account, session, settings)}\nОн действует 10 минут.")
        elif text == "/status":
            await client.send(chat_id, await _status_text(session))
        elif text == "/new":
            account.active_chat_id = None
            await session.commit()
            await client.send(chat_id, "Новый чат начнётся со следующего вопроса.")
        elif text == "/emoji":
            keyboard, _ = await _emoji_slots(session)
            await client.send(chat_id, "Выбери, для чего нужен Premium emoji. Потом пришли сам emoji отдельным сообщением.", keyboard)
        elif isinstance(message.get("photo"), list) and message["photo"]:
            photo = message["photo"][-1]
            if isinstance(photo, dict):
                await client.send(chat_id, await _store_photo(account, str(photo.get("file_id", "")), str(message.get("caption", "")), client, session, settings))
        elif text and not text.startswith("/"):
            job = await _queue_text(account, text, session)
            await client.send(chat_id, "Сначала выбери режим: /modes" if job is None else "Запрос принят. Пришлю готовый ответ сюда.")


async def notify_answer(chat_id: str, answer: str, settings: Settings) -> None:
    if not bot_is_enabled(settings):
        return
    try:
        client = TelegramClient(settings)
        for index in range(0, len(answer), 4096):
            await client.send(chat_id, answer[index:index + 4096])
    except Exception:
        logger.exception("Unable to deliver WristMind Telegram answer")


# --- Latency diagnostics commands -------------------------------------------
# Diagnostic-only surface: reads/rotates the latency trace and reports its size.
# It never touches chats, modes, jobs or answers.

LATENCY_COMMANDS = ("/latency", "/latency_clear", "/latency_status")


def _format_status(status: dict[str, Any]) -> str:
    if not status.get("exists"):
        return f"Лог ещё не создан.\n{status['path']}"
    size_mb = int(status["size_bytes"]) / 1_048_576
    lines = [
        f"Файл: {status['path']}",
        f"Размер: {size_mb:.2f} MB",
        f"Событий: {status['events']}",
        f"Первое: {status['first_ts'] or '—'}",
        f"Последнее: {status['last_ts'] or '—'}",
        f"Telegram: {'вкл' if status['telegram_enabled'] else 'выкл'}",
    ]
    if status.get("dropped_telegram"):
        lines.append(f"Потеряно в Telegram: {status['dropped_telegram']}")
    return "\n".join(lines)


async def handle_latency_command(text: str, chat_id: str, client: TelegramClient, settings: Settings) -> bool:
    """Handle /latency* commands. Returns True when the text was one of them."""
    command = text.strip().split()[0] if text.strip() else ""
    if command not in LATENCY_COMMANDS:
        return False
    from . import latency_trace

    if command == "/latency_status":
        await client.send(chat_id, _format_status(latency_trace.log_status(settings)))
        return True
    if command == "/latency_clear":
        result = latency_trace.reset_log(settings)
        if result.get("rotated"):
            await client.send(chat_id, f"Лог ротирован.\nНовый файл: {result['path']}\nСтарый: {result['rotated_to']}")
        else:
            await client.send(chat_id, f"Ротировать нечего.\n{result['path']}")
        return True
    path = latency_trace.trace_path(settings)
    if not path.exists():
        await client.send(chat_id, f"Лог ещё не создан.\n{path}")
        return True
    status = latency_trace.log_status(settings)
    token = latency_trace.latency_bot_token(settings)
    try:
        await latency_trace.send_document(
            token, chat_id, path, caption=f"latency events={status['events']} size={status['size_bytes']}b"
        )
    except Exception as error:
        # Type only: a Bot API URL contains the token.
        logger.warning("Unable to send latency trace document: %s", type(error).__name__)
        await client.send(chat_id, "Не удалось отправить файл. Смотрите /latency_status.")
    return True


def is_latency_owner(sender_id: str, settings: Settings) -> bool:
    """Only the configured owner may read or clear diagnostics."""
    return settings.telegram_owner_id is not None and str(settings.telegram_owner_id) == sender_id
