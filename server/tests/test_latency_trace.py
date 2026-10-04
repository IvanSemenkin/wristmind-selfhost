"""Tests for the diagnostic latency trace (a local JSONL file).

These cover the diagnostic contract only: safe JSONL lines, stable
trace_id/message_id linkage, rotation, and the guarantee that diagnostics never
influence a turn.
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
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


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

