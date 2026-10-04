from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from sqlalchemy import select

from .config import Settings
from .database import SessionFactory
from .db_models import Device, PushRegistration

logger = logging.getLogger(__name__)


async def notify_watch_state_changed(settings: Settings) -> None:
    credentials_path = settings.firebase_credentials_path
    if credentials_path is None or not credentials_path.is_file():
        return
    async with SessionFactory() as session:
        tokens = list(
            (
                await session.scalars(
                    select(PushRegistration.token)
                    .join(Device, PushRegistration.device_id == Device.id)
                    .where(Device.kind == "WATCH", Device.revoked_at.is_(None))
                )
            ).all()
        )
    if not tokens:
        return
    await asyncio.to_thread(_send_state_changed, credentials_path, tokens)


def schedule_watch_state_changed(settings: Settings) -> None:
    """Notify watches without making an already-committed API mutation wait."""
    task = asyncio.create_task(notify_watch_state_changed(settings))

    def report_failure(completed: asyncio.Task[None]) -> None:
        if completed.cancelled():
            return
        error = completed.exception()
        if error is not None:
            logger.error("Unable to schedule WristMind state-change push", exc_info=error)

    task.add_done_callback(report_failure)


def _send_state_changed(credentials_path: Path, tokens: list[str]) -> None:
    try:
        import firebase_admin
        from firebase_admin import credentials, messaging

        try:
            app = firebase_admin.get_app("wristmind-sync")
        except ValueError:
            app = firebase_admin.initialize_app(credentials.Certificate(str(credentials_path)), name="wristmind-sync")
        for token in tokens:
            try:
                messaging.send(
                    messaging.Message(
                        data={"event": "state_changed"},
                        token=token,
                        # A watch needs to fetch the new list immediately when a chat is
                        # renamed or removed. Normal-priority FCM messages may wait for
                        # Wear OS to leave Doze, which left stale chats on screen for minutes.
                        android=messaging.AndroidConfig(collapse_key="wristmind-sync", priority="high"),
                    ),
                    app=app,
                )
            except Exception:
                # One stale FCM registration must not prevent the other active watches
                # from receiving the state-change signal.
                logger.exception("Unable to deliver WristMind state-change push to a watch")
    except Exception:
        logger.exception("Unable to deliver WristMind state-change push")
