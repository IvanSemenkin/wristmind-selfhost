"""Latency diagnostics: a local JSONL trace file.

Diagnostic-only by construction:

* Nothing here influences routing, retrieval, provider requests, retries,
  timeouts, the streaming protocol or the produced answer.
* Only identifiers, timestamps, durations and sizes are recorded. Prompts,
  answers, chain-of-thought, credentials, tokens and personal data never are.
* Recording a JSONL line is a local append, so it can never delay an answer.

Trace identity: ``trace_id`` is the client request id (the watch-generated
request id, stored server-side as ``Job.client_request_id``). It is known to the
watch before the POST and to the server after it, so it is the single key that
joins watch-side and server-side events of one send. ``job_id`` and
``message_id`` are attached as soon as they exist.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from .config import Settings, get_settings

logger = logging.getLogger(__name__)


# Event names. Kept as constants so call sites cannot drift from the contract.
SEND_STARTED = "SEND_STARTED"
SERVER_RECEIVED = "SERVER_RECEIVED"
JOB_ACCEPTED = "JOB_ACCEPTED"
ROUTER_STARTED = "ROUTER_STARTED"
# Per-attempt router diagnostics. One pair is recorded for every router model
# call, so a slow router can be attributed either to one slow provider attempt
# or to a second (retry) call. Diagnostic only: the router retry loop, its
# prompt and its parser are unchanged.
ROUTER_ATTEMPT_STARTED = "ROUTER_ATTEMPT_STARTED"
ROUTER_ATTEMPT_FINISHED = "ROUTER_ATTEMPT_FINISHED"
ROUTER_FINISHED = "ROUTER_FINISHED"
LOCAL_RETRIEVAL_STARTED = "LOCAL_RETRIEVAL_STARTED"
LOCAL_RETRIEVAL_FINISHED = "LOCAL_RETRIEVAL_FINISHED"
WEB_SEARCH_STARTED = "WEB_SEARCH_STARTED"
WEB_SEARCH_FINISHED = "WEB_SEARCH_FINISHED"
OPEN_STARTED = "OPEN_STARTED"
OPEN_FINISHED = "OPEN_FINISHED"
PROVIDER_REQUEST_STARTED = "PROVIDER_REQUEST_STARTED"
PROVIDER_FIRST_TOKEN = "PROVIDER_FIRST_TOKEN"
SERVER_FIRST_DELTA = "SERVER_FIRST_DELTA"
WATCH_FIRST_DELTA_RECEIVED = "WATCH_FIRST_DELTA_RECEIVED"
WATCH_FIRST_VISIBLE_TEXT = "WATCH_FIRST_VISIBLE_TEXT"
ANSWER_FINISHED = "ANSWER_FINISHED"
REQUEST_FINISHED = "REQUEST_FINISHED"
ERROR = "ERROR"
TIMEOUT = "TIMEOUT"
FALLBACK = "FALLBACK"

_file_lock = threading.Lock()

# --- configuration -----------------------------------------------------------


def trace_path(settings: Settings | None = None) -> Path:
    """JSONL location. Defaults to the shared private volume."""
    config = settings or get_settings()
    return config.latency_trace_path or (config.storage_dir / "latency-trace.jsonl")


def trace_enabled(settings: Settings | None = None) -> bool:
    config = settings or get_settings()
    return bool(config.latency_trace_enabled)


# --- time helpers ------------------------------------------------------------


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def epoch_ms() -> int:
    return round(datetime.now(timezone.utc).timestamp() * 1000)


def since_send_ms(send_epoch_ms: int | None) -> int | None:
    """Milliseconds elapsed since the watch tapped send, when that is known."""
    if not send_epoch_ms:
        return None
    return max(0, epoch_ms() - int(send_epoch_ms))


# --- recording ---------------------------------------------------------------


def record(
    event: str,
    *,
    trace_id: str | None = None,
    message_id: str | None = None,
    job_id: str | None = None,
    since_send: int | None = None,
    duration_ms: int | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """Append one safe event to the JSONL trace.

    Never raises and never blocks on I/O other than the local append.
    """
    entry: dict[str, Any] = {
        "ts": now_iso(),
        "event": event,
        "trace_id": trace_id,
        "message_id": message_id,
        "job_id": job_id,
    }
    if since_send is not None:
        entry["since_send_ms"] = since_send
    if duration_ms is not None:
        entry["duration_ms"] = duration_ms
    for key, value in fields.items():
        if value is None:
            continue
        entry[key] = value
    try:
        _append(entry)
    except Exception:  # pragma: no cover - diagnostics must never break a turn
        logger.debug("Unable to append latency trace record", exc_info=True)
    return entry


def _append(entry: dict[str, Any]) -> None:
    settings = get_settings()
    if not trace_enabled(settings):
        return
    path = trace_path(settings)
    line = json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n"
    with _file_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        _rotate_if_needed(path, settings)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line)


def _rotate_if_needed(path: Path, settings: Settings) -> None:
    """Size-based rotation; the newest ``latency_trace_backup_count`` files stay."""
    try:
        size = path.stat().st_size
    except OSError:
        return
    if size < settings.latency_trace_max_bytes:
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rotated = path.with_name(f"{path.stem}.{stamp}{path.suffix}")
    try:
        os.replace(path, rotated)
    except OSError:
        return
    _prune_backups(path, settings)


def _prune_backups(path: Path, settings: Settings) -> None:
    pattern = f"{path.stem}.*{path.suffix}"
    try:
        backups = sorted(
            (item for item in path.parent.glob(pattern) if item.name != path.name),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return
    for stale in backups[max(0, settings.latency_trace_backup_count):]:
        try:
            stale.unlink()
        except OSError:
            pass




# --- per-request summary -----------------------------------------------------


# --- commands ----------------------------------------------------------------


def log_status(settings: Settings | None = None) -> dict[str, Any]:
    """Size, event count and time span of the current trace file."""
    config = settings or get_settings()
    path = trace_path(config)
    info: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": 0,
        "events": 0,
        "first_ts": None,
        "last_ts": None,
    }
    if not path.exists():
        return info
    try:
        info["size_bytes"] = path.stat().st_size
        with open(path, "rb") as handle:
            for raw in handle:
                if not raw.strip():
                    continue
                info["events"] += 1
                try:
                    parsed = json.loads(raw.decode("utf-8", errors="replace"))
                except ValueError:
                    continue
                stamp = parsed.get("ts")
                if isinstance(stamp, str):
                    if info["first_ts"] is None:
                        info["first_ts"] = stamp
                    info["last_ts"] = stamp
    except OSError:
        logger.debug("Unable to stat latency trace", exc_info=True)
    return info


def reset_log(settings: Settings | None = None) -> dict[str, Any]:
    """Rotate the current trace file away so the next event starts a fresh one."""
    config = settings or get_settings()
    path = trace_path(config)
    if not path.exists():
        return {"rotated": False, "path": str(path)}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rotated = path.with_name(f"{path.stem}.{stamp}{path.suffix}")
    with _file_lock:
        try:
            os.replace(path, rotated)
        except OSError:
            return {"rotated": False, "path": str(path)}
        _prune_backups(path, config)
    return {"rotated": True, "path": str(path), "rotated_to": str(rotated)}
