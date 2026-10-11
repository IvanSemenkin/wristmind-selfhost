"""Durable photo-to-mode selection; ingestion uses the existing Vision worker."""
from __future__ import annotations

import hashlib
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import httpx
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select

from .db_models import Job, JobEvent, KnowledgeSource, Mode, utcnow


async def watch_modes(session):
    return list((await session.scalars(select(Mode).where(
        Mode.deleted_at.is_(None), Mode.hidden_on_watch.is_(False),
        Mode.name != "Быстрый чат",
    ).order_by(Mode.name))).all())


def _bot_scope(client):
    # Bind file IDs and buttons to their bot without persisting credentials.
    return hashlib.sha256(client.token.encode()).hexdigest()


async def handle_photo(update, account, client, session, settings):
    """Return True only for an image upload or our image-selection callback."""
    callback = update.get("callback_query")
    if isinstance(callback, dict):
        data = str(callback.get("data", ""))
        if not data.startswith("photo:"):
            return False
        try:
            await client.answer_callback(str(callback.get("id", "")))
        except httpx.HTTPStatusError as error:
            # A delayed update can outlive Telegram's callback acknowledgement.
            # The durable, owner-bound selection still needs to be processed.
            if error.response.status_code != 400:
                raise
        try:
            _, job_id, index_text = data.split(":")
            index = int(index_text)
        except (ValueError, TypeError):
            return True
        job = await session.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if (job is None or job.device_id != account.device_id
                or job.payload.get("telegram_chat_id") != account.chat_id
                or job.payload.get("bot_scope") != _bot_scope(client)):
            await client.send(account.chat_id, "Эта кнопка загрузки недоступна. Отправь картинку заново.")
            return True
        if job.status != "awaiting_mode":
            await client.send(account.chat_id, "Эта картинка уже передана на обработку.")
            return True
        created = job.created_at.replace(tzinfo=utcnow().tzinfo) if job.created_at.tzinfo is None else job.created_at
        if utcnow() - created > timedelta(hours=24):
            await client.send(account.chat_id, "Выбор режима устарел. Отправь картинку заново.")
            return True
        mode_ids = job.payload.get("mode_ids", [])
        if not 0 <= index < len(mode_ids):
            return True
        mode = await session.get(Mode, mode_ids[index])
        if (mode is None or mode.deleted_at is not None or mode.hidden_on_watch
                or mode.name == "Быстрый чат"):
            await client.send(account.chat_id, "Этот режим больше не доступен на часах. Отправь картинку заново.")
            return True
        try:
            file_path, content = await client.download(job.payload["file_id"])
        except Exception:
            # Telegram exceptions can include a URL containing the bot token.
            await client.send(account.chat_id, "Не удалось скачать картинку. Попробуй нажать кнопку ещё раз.")
            return True
        if not content or len(content) > settings.max_upload_bytes:
            await client.send(account.chat_id, "Картинка пустая или слишком большая.")
            return True
        try:
            with Image.open(BytesIO(content)) as image:
                image_format = image.format
                image.verify()
            media_type, suffix = {
                "JPEG": ("image/jpeg", ".jpg"), "PNG": ("image/png", ".png"),
                "WEBP": ("image/webp", ".webp"), "GIF": ("image/gif", ".gif"),
            }[image_format]
        except (UnidentifiedImageError, OSError, ValueError, KeyError, Image.DecompressionBombError):
            await client.send(account.chat_id, "Не удалось прочитать картинку. Отправь фото, PNG, JPEG или WebP.")
            return True
        source_id = str(uuid4())
        target = settings.storage_dir / "sources" / source_id / f"original{suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        source = KnowledgeSource(
            id=source_id, mode_id=mode.id, user_id=account.user_id,
            title=(job.payload.get("caption", "").strip() or f"Фото из Telegram {utcnow():%d.%m.%Y %H:%M}")[:160],
            filename=Path(file_path).name[:240], media_type=media_type,
            processing_mode="VISION", storage_path=str(target),
        )
        session.add(source)
        job.kind, job.status = "INGEST", "queued"
        job.payload = {**job.payload, "source_id": source.id, "telegram_notify_processing": True}
        session.add(JobEvent(job_id=job.id, event="state", data={"state": "queued"}))
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            target.unlink(missing_ok=True)
            raise
        await client.send(account.chat_id, f"Картинка добавлена в источники режима «{mode.name}». "
                          "Источник поставлен в очередь. Пришлю сообщение, когда обработка завершится или возникнет ошибка.")
        return True

    message = update.get("message")
    if not isinstance(message, dict):
        return False
    photos = message.get("photo")
    document = message.get("document")
    if isinstance(photos, list) and photos:
        file = photos[-1]
    elif isinstance(document, dict) and str(document.get("mime_type", "")).startswith("image/"):
        file = document
    else:
        return False
    if not isinstance(file, dict) or not file.get("file_id"):
        return True
    if int(file.get("file_size") or 0) > settings.max_upload_bytes:
        await client.send(account.chat_id, "Картинка слишком большая.")
        return True
    modes = await watch_modes(session)
    if not modes:
        await client.send(account.chat_id, "Нет режимов, доступных на часах. Включи нужный режим в панели и отправь картинку снова.")
        return True
    request_id = "telegram-image:" + hashlib.sha256(
        f"{_bot_scope(client)}:{account.chat_id}:{message.get('message_id')}".encode()
    ).hexdigest()
    job = await session.scalar(select(Job).where(
        Job.device_id == account.device_id, Job.client_request_id == request_id,
    ))
    if job is None:
        job = Job(
            kind="TELEGRAM_PHOTO", status="awaiting_mode", device_id=account.device_id,
            client_request_id=request_id, payload={
                "file_id": file["file_id"], "caption": str(message.get("caption", ""))[:160],
                "telegram_chat_id": account.chat_id, "bot_scope": _bot_scope(client),
                "mode_ids": [mode.id for mode in modes],
            },
        )
        session.add(job)
        await session.commit()
    if job.status != "awaiting_mode":
        return True
    mode_names = {mode.id: mode.name for mode in modes}
    keyboard = [[{"text": mode_names[mode_id], "callback_data": f"photo:{job.id}:{index}"}]
                for index, mode_id in enumerate(job.payload["mode_ids"]) if mode_id in mode_names]
    await client.send(account.chat_id, "В какой режим добавить эту картинку? После выбора запущу Vision.", keyboard)
    return True
