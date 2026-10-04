from __future__ import annotations

import asyncio
import logging

from . import latency_trace
from .config import get_settings
from .database import close_database, init_database
from .telegram_bot import TelegramClient, bot_is_enabled, handle_update


logger = logging.getLogger(__name__)


async def _poll(settings) -> None:
    client = TelegramClient(settings)
    offset = 0
    while True:
        try:
            for update in await client.get_updates(offset):
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    offset = max(offset, update_id + 1)
                try:
                    await handle_update(update, settings)
                except Exception:
                    logger.exception("Unable to process Telegram update %s", update_id)
        except Exception:
            logger.exception("Telegram polling failed; retrying")
            await asyncio.sleep(3)


def _diagnostics_token(settings) -> str:
    if settings.latency_telegram_bot_token is None:
        return ""
    return settings.latency_telegram_bot_token.get_secret_value()


def _diagnostics_settings(settings):
    """A Settings copy whose bot token is the dedicated diagnostics bot.

    Only the token differs; every other value (owner id, trace path, flags) is
    the same, so the dedicated bot answers with the same authorisation rules.
    """
    token = _diagnostics_token(settings)
    if not token:
        return None
    if settings.telegram_bot_token is not None and settings.telegram_bot_token.get_secret_value() == token:
        return None
    return settings.model_copy(update={"telegram_bot_token": settings.latency_telegram_bot_token})


async def run() -> None:
    settings = get_settings()
    diagnostic = _diagnostics_settings(settings)
    if not bot_is_enabled(settings) and diagnostic is None:
        raise RuntimeError("Telegram bot is not configured")
    await init_database()
    # Live event delivery is owned by the API and worker processes; this service
    # only handles commands, so no Telegram sender is started here.
    tasks: list[asyncio.Task[None]] = []
    if bot_is_enabled(settings):
        tasks.append(asyncio.create_task(_poll(settings)))
    if diagnostic is not None:
        logger.info("Latency diagnostics bot polling enabled")
        tasks.append(asyncio.create_task(_poll(diagnostic)))
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await latency_trace.stop_telegram_worker()
        await close_database()


if __name__ == "__main__":
    asyncio.run(run())
