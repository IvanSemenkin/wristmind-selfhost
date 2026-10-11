"""Durable account-level event log for the control panel.

The panel used to learn about changes only through the one-shot bootstrap it
performed on load, so anything produced elsewhere (a watch question, a worker
that finished an answer, a background title, a finished ingestion) stayed
invisible until a full page reload. `account_events` is the smallest durable
thing that fixes that: one append-only row per user-visible mutation, carrying a
monotonic cursor, a type and identifiers only.

Two rules keep it honest:

* a row is added with the mutation's own session and committed with it, so the
  stream can never report a change that rolled back, or skip one that committed;
* the payload never carries the entity itself. The panel owns the mapping from
  API payloads to its own types, so duplicating serialization here would drift.
  A reader refetches exactly the slice named by the event.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db_models import AccountEvent, utcnow

logger = logging.getLogger("uvicorn.error")

# How long the log is kept. A client whose cursor is older than what survives
# gets `resync` and reloads once instead of silently missing changes.
RETENTION_DAYS = 7

RESYNC = "resync"

CHAT_CREATED = "chat.created"
CHAT_UPDATED = "chat.updated"
CHAT_DELETED = "chat.deleted"
MESSAGE_CREATED = "message.created"
MESSAGE_UPDATED = "message.updated"
MODE_UPDATED = "mode.updated"
MODE_REMOVED = "mode.removed"
SOURCE_UPDATED = "source.updated"
SOURCE_REMOVED = "source.removed"
DEVICE_UPDATED = "device.updated"
DEVICE_REMOVED = "device.removed"
SETTINGS_UPDATED = "settings.updated"
PAIRING_UPDATED = "pairing.updated"


def record_account_event(
    session: AsyncSession,
    event_type: str,
    data: dict[str, Any] | None = None,
    owner_id: str | None = None,
) -> None:
    """Queue one event in the caller's transaction. Never commits on its own."""
    session.add(AccountEvent(owner_id=owner_id, type=event_type, data=dict(data or {})))


async def prune_account_events(session: AsyncSession, retention_days: int = RETENTION_DAYS) -> int:
    """Drop events older than the retention window. Commits its own transaction."""
    cutoff = utcnow() - timedelta(days=retention_days)
    result = await session.execute(delete(AccountEvent).where(AccountEvent.created_at < cutoff))
    await session.commit()
    return int(result.rowcount or 0)


async def resolve_cursor(
    session: AsyncSession,
    after: int,
    last_event_id: str | None = None,
) -> tuple[int, bool]:
    """Decide where a reader starts.

    Returns `(cursor, needs_resync)`. A zero cursor means a client that has just
    loaded current state, so it starts at the tail instead of replaying history.
    A cursor older than the retention window cannot be served correctly, so the
    reader is told to reload rather than being handed a silent gap.

    This is separate from the streaming loop because it is the only part with
    real decisions in it, and it is worth testing without a live connection.
    """
    cursor = max(after, int(last_event_id or 0))
    newest = await session.scalar(select(func.max(AccountEvent.id))) or 0
    oldest = await session.scalar(select(func.min(AccountEvent.id)))
    if cursor == 0:
        return newest, False
    if oldest is not None and cursor < oldest - 1:
        return newest, True
    return cursor, False
