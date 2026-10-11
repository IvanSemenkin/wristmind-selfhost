"""Tests for the diagnostic latency trace (JSONL + optional Telegram feed).

These cover the diagnostic contract only: safe JSONL lines, stable
trace_id/message_id linkage, rotation, and the guarantee that a broken Telegram
never affects the pipeline.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from wristmind_server import latency_trace
from wristmind_server.config import Settings

SAFE_KEYS = {
    "ts",
    "event",
    "trace_id",
    "message_id",
    "job_id",
    "since_send_ms",
    "duration_ms",
    "route",
    "model",
    "provider",
    "prompt_chars",
    "response_chars",
    "error_type",
    "delta_chars",
    "stream_chars",
    "stage",
    "search_count",
    "open_count",
    "fallback_used",
    "research_mode",
}


def _settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "storage_dir": tmp_path,
        "latency_trace_path": tmp_path / "latency-trace.jsonl",
        "latency_trace_enabled": True,
        "latency_telegram_enabled": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture(autouse=True)
def reset_telegram_globals():
    yield
    latency_trace._telegram_queue = None
    latency_trace._telegram_task = None
    latency_trace._dropped_telegram = 0


def _lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_record_writes_safe_jsonl_line(tmp_path: Path, monkeypatch) -> None:
    fake = _settings(tmp_path)
    monkeypatch.setattr(latency_trace, "get_settings", lambda: fake)

    latency_trace.record(
        latency_trace.PROVIDER_FIRST_TOKEN,
        trace_id="req-1",
        message_id="msg-1",
        job_id="job-1",
        since_send=4820,
        provider_ttft_ms=3710,
        route="web",
        model="deepseek:deepseek-flash",
        prompt_chars=1200,
        response_chars=340,
    )

    lines = _lines(fake.latency_trace_path)
    assert len(lines) == 1
    entry = lines[0]
    assert entry["event"] == "PROVIDER_FIRST_TOKEN"
    assert entry["trace_id"] == "req-1"
    assert entry["message_id"] == "msg-1"
    assert entry["job_id"] == "job-1"
    assert entry["since_send_ms"] == 4820
    assert entry["provider_ttft_ms"] == 3710
    assert entry["ts"].endswith("Z")
    # Only identifiers, timings and sizes: nothing else may be written.
    assert set(entry) <= SAFE_KEYS | {"provider_ttft_ms", "provider_headers_ms"}


def test_events_of_one_send_share_the_trace_id(tmp_path: Path, monkeypatch) -> None:
    fake = _settings(tmp_path)
    monkeypatch.setattr(latency_trace, "get_settings", lambda: fake)

    for event in (
        latency_trace.ROUTER_STARTED,
        latency_trace.ROUTER_FINISHED,
        latency_trace.SERVER_FIRST_DELTA,
    ):
        latency_trace.record(
            event,
            trace_id="trace-42",
            message_id="msg-42",
            job_id="job-42",
            duration_ms=10,
        )

    lines = _lines(fake.latency_trace_path)
    assert [line["event"] for line in lines] == [
        latency_trace.ROUTER_STARTED,
        latency_trace.ROUTER_FINISHED,
        latency_trace.SERVER_FIRST_DELTA,
    ]
    assert all(
        line["trace_id"] == "trace-42" and line["message_id"] == "msg-42" and line["job_id"] == "job-42"
        for line in lines
    )


def test_recording_is_disabled_without_losing_the_call(tmp_path: Path, monkeypatch) -> None:
    fake = _settings(tmp_path, latency_trace_enabled=False)
    monkeypatch.setattr(latency_trace, "get_settings", lambda: fake)

    entry = latency_trace.record(latency_trace.SEND_STARTED, trace_id="req-1")

    assert entry["event"] == latency_trace.SEND_STARTED
    assert not fake.latency_trace_path.exists()


def test_rotation_prunes_old_backups(tmp_path: Path, monkeypatch) -> None:
    fake = _settings(tmp_path, latency_trace_max_bytes=200, latency_trace_backup_count=2)
    monkeypatch.setattr(latency_trace, "get_settings", lambda: fake)

    path = fake.latency_trace_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x" * 10, encoding="utf-8")
    for index in range(5):
        backup = path.with_name(f"{path.stem}.2026010{index}T000000Z{path.suffix}")
        backup.write_text("y" * 10, encoding="utf-8")

    latency_trace._prune_backups(path, fake)

    backups = sorted(item.name for item in tmp_path.glob("latency-trace.*.jsonl"))
    assert len(backups) == 2
    assert path.exists()


def test_rotation_replaces_an_oversized_file(tmp_path: Path, monkeypatch) -> None:
    fake = _settings(tmp_path, latency_trace_max_bytes=64, latency_trace_backup_count=3)
    monkeypatch.setattr(latency_trace, "get_settings", lambda: fake)

    for index in range(6):
        latency_trace.record("OPEN_FINISHED", trace_id=f"req-{index}", duration_ms=index)

    path = fake.latency_trace_path
    assert path.exists()
    # The current file is never larger than the configured cap plus one line.
    assert path.stat().st_size < 64 + 200
    assert list(tmp_path.glob("latency-trace.*.jsonl"))


def test_telegram_failure_does_not_break_recording(tmp_path: Path, monkeypatch) -> None:
    fake = _settings(
        tmp_path,
        latency_telegram_enabled=True,
        telegram_bot_token="test-token",
        telegram_owner_id=1,
    )
    monkeypatch.setattr(latency_trace, "get_settings", lambda: fake)

    delivered: list[dict] = []

    async def broken_send(_token: str, _method: str, _payload: dict, **_kwargs):
        delivered.append(_payload)
        raise RuntimeError("telegram is down")

    monkeypatch.setattr(latency_trace, "telegram_call", broken_send)

    async def scenario() -> None:
        latency_trace.start_telegram_worker(fake)
        for index in range(3):
            latency_trace.record("SERVER_FIRST_DELTA", trace_id="req-1", duration_ms=index)
        # Give the consumer a chance to drain the queue.
        for _ in range(50):
            if latency_trace._telegram_queue is not None and latency_trace._telegram_queue.empty():
                break
            await asyncio.sleep(0.01)
        await latency_trace.stop_telegram_worker()

    asyncio.run(scenario())

    # Every event was still recorded locally despite every Telegram send failing.
    assert len(_lines(fake.latency_trace_path)) == 3
    assert len(delivered) == 3


def test_telegram_queue_never_blocks_the_caller(tmp_path: Path, monkeypatch) -> None:
    fake = _settings(
        tmp_path,
        latency_telegram_enabled=True,
        telegram_bot_token="test-token",
        telegram_owner_id=1,
    )
    monkeypatch.setattr(latency_trace, "get_settings", lambda: fake)

    async def never_sends(*_args, **_kwargs):
        await asyncio.sleep(3600)

    monkeypatch.setattr(latency_trace, "telegram_call", never_sends)

    async def scenario() -> None:
        latency_trace.start_telegram_worker(fake)
        # Queue capacity is 2000; record far fewer than that and require it to
        # stay non-blocking regardless of a stalled sender.
        for index in range(50):
            latency_trace.record(latency_trace.SERVER_FIRST_DELTA, trace_id="req-1", duration_ms=index)
        assert latency_trace._telegram_queue is not None
        await latency_trace.stop_telegram_worker()

    asyncio.run(scenario())


def test_format_event_is_compact_and_content_free(tmp_path: Path) -> None:
    text = latency_trace.format_event(
        {
            "event": latency_trace.PROVIDER_FIRST_TOKEN,
            "trace_id": "req-1",
            "message_id": "msg-1",
            "since_send_ms": 4820,
            "provider_ttft_ms": 3710,
            "route": "web",
            "model": "deepseek:deepseek-flash",
        }
    )

    assert text.splitlines()[0] == "⚡ PROVIDER_FIRST_TOKEN"
    assert "trace=req-1" in text
    assert "t=+4.82s" in text
    assert "ttft=3.71s" in text
    assert "route=web" in text
    assert "model=deepseek:deepseek-flash" in text


def test_log_status_and_reset(tmp_path: Path, monkeypatch) -> None:
    fake = _settings(tmp_path)
    monkeypatch.setattr(latency_trace, "get_settings", lambda: fake)

    empty = latency_trace.log_status(fake)
    assert empty["exists"] is False and empty["events"] == 0

    latency_trace.record("SEND_STARTED", trace_id="req-1")
    latency_trace.record("ANSWER_FINISHED", trace_id="req-1")

    status = latency_trace.log_status(fake)
    assert status["events"] == 2
    assert status["size_bytes"] > 0
    assert status["first_ts"] is not None and status["last_ts"] is not None

    result = latency_trace.reset_log(fake)
    assert result["rotated"] is True
    assert latency_trace.log_status(fake)["events"] == 0
    assert Path(result["rotated_to"]).exists()


def test_watch_diagnostics_endpoint_records_event(client, admin_headers, tmp_path, monkeypatch) -> None:
    fake = _settings(tmp_path)
    monkeypatch.setattr(latency_trace, "get_settings", lambda: fake)

    response = client.post(
        "/v1/diagnostics/latency",
        headers=admin_headers,
        json={
            "event": "WATCH_FIRST_VISIBLE_TEXT",
            "trace_id": "req-watch-1",
            "elapsed_ms": 2410,
            "stream_chars": 12,
        },
    )

    assert response.status_code == 204
    lines = _lines(fake.latency_trace_path)
    assert any(
        line["event"] == "WATCH_FIRST_VISIBLE_TEXT" and line["trace_id"] == "req-watch-1"
        for line in lines
    )


def test_watch_diagnostics_endpoint_rejects_anonymous_call(client, tmp_path, monkeypatch) -> None:
    fake = _settings(tmp_path)
    monkeypatch.setattr(latency_trace, "get_settings", lambda: fake)

    response = client.post("/v1/diagnostics/latency", json={"event": "SEND_STARTED"})

    assert response.status_code in {401, 403}


def test_full_answer_chain_shares_one_trace_id(
    client, admin_headers, mode, tmp_path, monkeypatch
) -> None:
    """One send must produce a single, joinable chain of trace events."""
    from wristmind_server.worker import process_next_job

    fake = _settings(tmp_path)
    monkeypatch.setattr(latency_trace, "get_settings", lambda: fake)

    chat = client.post("/v1/chats", headers=admin_headers, json={"mode_id": mode["id"]}).json()
    job = client.post(
        f"/v1/chats/{chat['id']}/messages",
        headers=admin_headers,
        json={"client_request_id": "trace-chain-1", "text": "Объясни теорему Пифагора"},
    ).json()

    assert asyncio.run(process_next_job()) is True

    lines = _lines(fake.latency_trace_path)
    chain = [line for line in lines if line["trace_id"] == "trace-chain-1"]
    events = [line["event"] for line in chain]
    assert events[0] == latency_trace.SERVER_RECEIVED
    assert latency_trace.ROUTER_FINISHED in events
    assert latency_trace.ANSWER_FINISHED in events
    assert all(line["job_id"] == job["id"] for line in chain if line["job_id"])
    # Every server-side event of this send carries the assistant message id.
    message_ids = {line["message_id"] for line in chain if line["message_id"]}
    assert len(message_ids) == 1

    messages = client.get(f"/v1/chats/{chat['id']}/messages", headers=admin_headers).json()
    timings = messages[-1]["timings"]
    for key in (
        "job_id",
        "message_id",
        "request_id",
        "request_received_ms",
        "queue_ms",
        "local_retrieval_ms",
        "router_ms",
        "web_ms",
        "open_ms",
        "provider_request_start",
        "provider_ttft_ms",
        "server_first_delta_ms",
        "total_ms",
        "prompt_chars",
        "response_chars",
        "first_token_ms",
    ):
        assert key in timings, key
    assert timings["total_ms"] >= 0
    assert timings["prompt_chars"] > 0
    assert timings["response_chars"] > 0
    # The answer text never leaks into the trace.
    assert not any("Пифагор" in json.dumps(line, ensure_ascii=False) for line in chain)


def test_telegram_feed_only_carries_key_stages(tmp_path: Path, monkeypatch) -> None:
    fake = _settings(tmp_path)
    monkeypatch.setattr(latency_trace, "get_settings", lambda: fake)

    sent: list[str] = []

    async def scenario() -> None:
        latency_trace._telegram_queue = asyncio.Queue()
        for event in ("SSE_SUBSCRIBE_START", "ROUTER_FINISHED", "WATCH_FIRST_DELTA_RECEIVED"):
            latency_trace.record(event, trace_id="req-1")
        while not latency_trace._telegram_queue.empty():
            sent.append(str(latency_trace._telegram_queue.get_nowait()))

    asyncio.run(scenario())

    # Technical events stay JSONL-only; the allowlisted one reaches Telegram.
    assert len(sent) == 1
    assert latency_trace.WATCH_FIRST_DELTA_RECEIVED in sent[0]
    assert len(_lines(fake.latency_trace_path)) == 3
    assert "SSE_SUBSCRIBE_START" not in latency_trace.TELEGRAM_EVENTS
    assert "ROUTER_FINISHED" not in latency_trace.TELEGRAM_EVENTS
    assert latency_trace.SEND_STARTED in latency_trace.TELEGRAM_EVENTS
    assert latency_trace.WATCH_FIRST_VISIBLE_TEXT in latency_trace.TELEGRAM_EVENTS
    assert latency_trace.ERROR in latency_trace.TELEGRAM_EVENTS
    assert latency_trace.FALLBACK in latency_trace.TELEGRAM_EVENTS


def test_telegram_feed_passes_allowlisted_events(tmp_path: Path, monkeypatch) -> None:
    fake = _settings(tmp_path)
    monkeypatch.setattr(latency_trace, "get_settings", lambda: fake)

    async def scenario() -> list[dict]:
        latency_trace._telegram_queue = asyncio.Queue()
        for event in latency_trace.TELEGRAM_EVENTS:
            latency_trace.record(event, trace_id="req-1")
        queued = []
        while not latency_trace._telegram_queue.empty():
            queued.append(latency_trace._telegram_queue.get_nowait())
        return queued

    queued = asyncio.run(scenario())
    assert len(queued) == len(latency_trace.TELEGRAM_EVENTS)
    assert all(item["event"] in latency_trace.TELEGRAM_EVENTS for item in queued)


def test_summary_omits_unknown_values_and_shortens_ids(tmp_path: Path, monkeypatch) -> None:
    fake = _settings(tmp_path)
    monkeypatch.setattr(latency_trace, "get_settings", lambda: fake)

    latency_trace.record(
        latency_trace.ANSWER_FINISHED,
        trace_id="1234567890abcdef",
        route="web",
        total_ms=13_400,
        provider_ttft_ms=3_710,
        server_first_delta_ms=4_820,
    )

    metrics = latency_trace._read_trace_metrics("1234567890abcdef", fake)
    text = latency_trace.format_summary("1234567890abcdef", metrics)

    assert text.startswith("🏁 REQUEST FINISHED")
    assert "Trace: 12345678" in text
    assert "1234567890abcdef" not in text
    assert "Route: web" in text
    assert "First visible: 4.82s" in text
    assert "Provider TTFT: 3.71s" in text
    assert "Total: 13.40s" in text


def test_summary_prefers_watch_first_visible_and_hides_missing(tmp_path: Path, monkeypatch) -> None:
    fake = _settings(tmp_path)
    monkeypatch.setattr(latency_trace, "get_settings", lambda: fake)

    latency_trace.record(
        latency_trace.WATCH_FIRST_VISIBLE_TEXT,
        trace_id="trace-watch",
        first_visible_text_rendered_ms=2_410,
    )

    metrics = latency_trace._read_trace_metrics("trace-watch", fake)
    text = latency_trace.format_summary("trace-watch", metrics)

    assert "First visible: 2.41s" in text
    assert "Route:" not in text
    assert "Provider TTFT:" not in text
    assert "Total:" not in text


def test_request_summary_is_scheduled_once(tmp_path: Path, monkeypatch) -> None:
    fake = _settings(
        tmp_path,
        latency_telegram_enabled=True,
        telegram_bot_token="test-token",
        telegram_owner_id=1,
    )
    monkeypatch.setattr(latency_trace, "get_settings", lambda: fake)

    scheduled: list[str] = []

    async def scenario() -> None:
        latency_trace.start_telegram_worker(fake)
        monkeypatch.setattr(
            latency_trace, "_emit_summary_later", lambda tid, delay: scheduled.append(tid) or asyncio.sleep(0)
        )
        latency_trace.schedule_request_summary("trace-1")
        latency_trace.schedule_request_summary("trace-1")
        await asyncio.sleep(0.05)
        await latency_trace.stop_telegram_worker()

    asyncio.run(scenario())
    assert scheduled == ["trace-1"]
