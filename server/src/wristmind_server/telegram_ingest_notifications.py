"""Deliver durable terminal statuses for sources submitted through Telegram."""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import func, select

from .database import SessionFactory
from .db_models import Job, KnowledgeSource, Mode
from .telegram_bot import TelegramClient
from .telegram_photos import _bot_scope

logger = logging.getLogger(__name__)


async def deliver_ingest_notifications(session, client) -> int:
    jobs = list((await session.scalars(select(Job).where(
        Job.kind == "INGEST", Job.status.in_(("complete", "failed")),
        Job.payload["telegram_notify_processing"].as_boolean().is_(True),
        Job.payload["bot_scope"].as_string() == _bot_scope(client),
        func.coalesce(Job.result["telegram_ingest_notified"].as_boolean(), False).is_(False),
    ).order_by(Job.completed_at, Job.id).limit(20))).all())
    delivered = 0
    for job in jobs:
        chat_id = job.payload.get("telegram_chat_id")
        if not chat_id:
            continue
        source = await session.get(KnowledgeSource, job.payload.get("source_id"))
        mode = await session.get(Mode, source.mode_id) if source and source.mode_id else None
        title = source.title[:160] if source else "Источник из Telegram"
        destination = f" в режиме «{mode.name}»" if mode else ""
        text = (f"Источник «{title}» обработан{destination}. Теперь он доступен для ответов."
                if job.status == "complete" else
                f"Ошибка обработки источника «{title}»{destination}. "
                "Источник не готов для ответов. Попробуй повторить обработку в панели.")
        try:
            await client.send(str(chat_id), text)
        except Exception as error:
            # Transport errors can contain a bot token. Persist nothing until delivery succeeds.
            logger.warning("Telegram source status delivery failed: %s", type(error).__name__)
            continue
        job.result = {**(job.result or {}), "telegram_ingest_notified": True}
        await session.commit()
        delivered += 1
    return delivered


async def run_ingest_notifications(settings) -> None:
    client = TelegramClient(settings)
    while True:
        try:
            async with SessionFactory() as session:
                await deliver_ingest_notifications(session, client)
        except Exception as error:
            logger.warning("Telegram source status check failed: %s", type(error).__name__)
        await asyncio.sleep(3)
