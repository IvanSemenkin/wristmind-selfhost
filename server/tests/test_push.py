import asyncio

from wristmind_server.config import Settings
from wristmind_server import push


async def test_state_change_push_is_scheduled_without_waiting(monkeypatch) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_notify(_: Settings) -> None:
        started.set()
        await release.wait()

    monkeypatch.setattr(push, "notify_watch_state_changed", slow_notify)

    push.schedule_watch_state_changed(Settings())
    await asyncio.wait_for(started.wait(), timeout=0.1)
    assert not release.is_set()
    release.set()
    await asyncio.sleep(0)
