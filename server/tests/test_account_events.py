"""The panel's live account feed.

`GET /v1/events` is what lets the console show what the watch, the worker and
other sessions do without a page reload. These checks cover the parts that can
silently break: authentication, the cursor rules (a fresh client starts at the
tail, a resume continues, a cursor behind retention asks for a resync), and the
fact that API mutations actually land in the log with an owner.

The streaming loop itself is not exercised here: it never ends by design, so a
test would have to race it. It shares its shape with the existing job-events
stream, and is verified against a running server instead.
"""

import asyncio

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from wristmind_server import account_events
from wristmind_server.database import SessionFactory
from wristmind_server.db_models import AccountEvent


def _record(event_types: list[str], owner_id: str | None = None) -> list[int]:
    """Append events and return their assigned ids, oldest first."""

    async def run() -> list[int]:
        async with SessionFactory() as session:
            for event_type in event_types:
                account_events.record_account_event(
                    session, event_type, {"chat_id": "chat-under-test"}, owner_id=owner_id
                )
            await session.commit()
            rows = (await session.scalars(select(AccountEvent).order_by(AccountEvent.id))).all()
            return [row.id for row in rows]

    return asyncio.run(run())


def _stored() -> list[tuple[int, str, dict, str | None]]:
    async def run() -> list[tuple[int, str, dict, str | None]]:
        async with SessionFactory() as session:
            rows = (await session.scalars(select(AccountEvent).order_by(AccountEvent.id))).all()
            return [(row.id, row.type, row.data, row.owner_id) for row in rows]

    return asyncio.run(run())


def _resolve(after: int, last_event_id: str | None = None) -> tuple[int, bool]:
    async def run() -> tuple[int, bool]:
        async with SessionFactory() as session:
            return await account_events.resolve_cursor(session, after, last_event_id)

    return asyncio.run(run())


def test_events_require_a_device_token(client: TestClient):
    assert client.get("/v1/events").status_code in {401, 403}


def test_a_fresh_cursor_starts_at_the_tail_and_a_resume_continues():
    ids = _record(["chat.created", "chat.updated"])
    assert len(ids) == 2

    # after=0 is a client that has just loaded current state: tail, no replay.
    assert _resolve(0) == (ids[-1], False)
    # A real cursor continues exactly where it stopped, without a resync.
    assert _resolve(ids[0]) == (ids[0], False)
    # The browser's own reconnect sends Last-Event-ID instead of the query arg.
    assert _resolve(0, str(ids[0])) == (ids[0], False)


def test_a_cursor_behind_retention_asks_for_a_resync():
    ids = _record(["chat.created", "chat.updated", "chat.created"])

    async def prune_everything_but_the_last() -> None:
        async with SessionFactory() as session:
            await session.execute(delete(AccountEvent).where(AccountEvent.id < ids[-1]))
            await session.commit()

    asyncio.run(prune_everything_but_the_last())

    # The client has seen id 1, but ids 1 and 2 are gone: event 2 was missed,
    # so a partial cache cannot be trusted and a full reload is required.
    cursor, resynced = _resolve(ids[0])
    assert resynced is True
    assert cursor == ids[-1]
    # A cursor that only just fell behind the window is still served normally.
    assert _resolve(ids[-1] - 1) == (ids[-1] - 1, False)


def test_creating_a_chat_records_one_owned_event(
    client: TestClient, admin_headers: dict, admin: dict, mode: dict
):
    chat = client.post("/v1/chats", headers=admin_headers, json={"mode_id": mode["id"]}).json()

    stored = _stored()
    # The `mode` fixture already logged its own creation; the chat's event is
    # the newest one, and it must name the chat and its owner.
    _, event_type, data, owner_id = stored[-1]
    assert event_type == "chat.created"
    assert data["chat_id"] == chat["id"]
    assert owner_id == admin["user_id"]


def test_pruning_drops_only_events_past_the_window():
    _record(["chat.created"])

    async def prune_with_no_retention() -> int:
        async with SessionFactory() as session:
            return await account_events.prune_account_events(session, retention_days=0)

    # Everything is older than "now", so the window clears the log completely.
    assert asyncio.run(prune_with_no_retention()) == 1
    assert _stored() == []
    # An empty log cannot produce a gap, and ids are never reused, so a stale
    # cursor simply waits for the next event instead of forcing a reload.
    assert _resolve(5) == (5, False)
