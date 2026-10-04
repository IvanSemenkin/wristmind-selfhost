"""Latency diagnostics: JSONL trace file plus an optional live Telegram feed.

Diagnostic-only by construction:

* Nothing here influences routing, retrieval, provider requests, retries,
  timeouts, the streaming protocol or the produced answer.
* Only identifiers, timestamps, durations and sizes are recorded. Prompts,
  answers, chain-of-thought, credentials, tokens and personal data never are.
* Recording a JSONL line is a local append and a non-blocking queue push, so it
  can never delay an answer. Telegram delivery happens on a background task; a
  Telegram error is logged and swallowed.

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

# Live Telegram feed shows only the stages that explain the wait until the first
# visible token. Every event is still written to JSONL in full; this set only
# decides what is worth a chat message.
TELEGRAM_EVENTS = frozenset(
    {
        SEND_STARTED,
        SERVER_RECEIVED,
        JOB_ACCEPTED,
        PROVIDER_REQUEST_STARTED,
        PROVIDER_FIRST_TOKEN,
        SERVER_FIRST_DELTA,
        WATCH_FIRST_DELTA_RECEIVED,
        WATCH_FIRST_VISIBLE_TEXT,
        ANSWER_FINISHED,
        # Router attempt lines are short and content-free, and they are exactly
        # what explains a multi-second router: a slow first call or a retry.
        ROUTER_ATTEMPT_STARTED,
        ROUTER_ATTEMPT_FINISHED,
        ERROR,
        TIMEOUT,
        FALLBACK,
    }
)

EVENT_EMOJI: dict[str, str] = {
    SEND_STARTED: "📱",
    SERVER_RECEIVED: "📥",
    JOB_ACCEPTED: "🎫",
    ROUTER_STARTED: "🔀",
    ROUTER_ATTEMPT_STARTED: "🔁",
    ROUTER_ATTEMPT_FINISHED: "🔁",
    ROUTER_FINISHED: "🔀",
    LOCAL_RETRIEVAL_STARTED: "📚",
    LOCAL_RETRIEVAL_FINISHED: "📚",
    WEB_SEARCH_STARTED: "🔎",
    WEB_SEARCH_FINISHED: "🔎",
    OPEN_STARTED: "📄",
    OPEN_FINISHED: "📄",
    PROVIDER_REQUEST_STARTED: "🚀",
    PROVIDER_FIRST_TOKEN: "⚡",
    SERVER_FIRST_DELTA: "📤",
    WATCH_FIRST_DELTA_RECEIVED: "📲",
    WATCH_FIRST_VISIBLE_TEXT: "👁",
    ANSWER_FINISHED: "✅",
    REQUEST_FINISHED: "🏁",
    ERROR: "❌",
    TIMEOUT: "⏱",
    FALLBACK: "🛟",
}

# Only these extra keys may reach the Telegram message (values are short and
# content-free). Anything else stays in JSONL, where it is still safe but not
# worth a chat line.
TELEGRAM_FIELDS = (
    "route",
    "research_mode",
    "provider",
    "model",
    "search_count",
    "open_count",
    "prompt_chars",
    "response_chars",
    "fallback_used",
    "error_type",
    "duration_ms",
    "provider_ttft_ms",
    "provider_headers_ms",
    "delta_chars",
    "stream_chars",
    "stage",
    # Router attempt diagnostics: identifiers and counters only, never content.
    "router_source",
    "attempt",
    "attempts_count",
    "received_chars",
    "result_status",
    "retry_reason",
    "provider_attempt",
    "network_retry",
    "total_router_ms",
)

# Human-readable labels for the few values worth showing in chat.
TELEGRAM_LABELS = {
    "provider_ttft_ms": "ttft",
    "provider_headers_ms": "headers",
    "research_mode": "research",
    "search_count": "searches",
    "open_count": "opens",
    "received_chars": "chars",
    "result_status": "status",
    "retry_reason": "retry",
    "router_source": "source",
}

# Router keys whose value already reads as milliseconds but must not be shown
# with the generic ``_ms`` seconds formatting.
TELEGRAM_MILLISECOND_LABELS = {
    "total_router_ms": "total_router",
}

_file_lock = threading.Lock()
_telegram_queue: asyncio.Queue[dict[str, Any]] | None = None
_telegram_task: asyncio.Task[None] | None = None
_dropped_telegram = 0
# Traces whose final summary has already been scheduled or sent, so one request
# produces exactly one REQUEST FINISHED message.
_summarized: set[str] = set()
SUMMARY_DELAY_SECONDS = 2.5


# --- configuration -----------------------------------------------------------


def trace_path(settings: Settings | None = None) -> Path:
    """JSONL location. Defaults to the shared private volume."""
    config = settings or get_settings()
    return config.latency_trace_path or (config.storage_dir / "latency-trace.jsonl")


def trace_enabled(settings: Settings | None = None) -> bool:
    config = settings or get_settings()
    return bool(config.latency_trace_enabled)


def telegram_enabled(settings: Settings | None = None) -> bool:
    config = settings or get_settings()
    if not config.latency_telegram_enabled:
        return False
    return bool(latency_bot_token(config) and latency_chat_id(config))


def latency_bot_token(settings: Settings | None = None) -> str:
    """Dedicated diagnostics bot token when set, otherwise the main bot token."""
    config = settings or get_settings()
    if config.latency_telegram_bot_token is not None:
        value = config.latency_telegram_bot_token.get_secret_value()
        if value:
            return value
    if config.telegram_bot_token is not None:
        return config.telegram_bot_token.get_secret_value()
    return ""


def latency_chat_id(settings: Settings | None = None) -> str:
    config = settings or get_settings()
    if config.latency_telegram_chat_id:
        return str(config.latency_telegram_chat_id)
    if config.telegram_owner_id is not None:
        return str(config.telegram_owner_id)
    return ""


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
    """Append one safe event to JSONL and offer it to the Telegram feed.

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
    _enqueue_telegram(entry)
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


# --- Telegram feed -----------------------------------------------------------


def start_telegram_worker(settings: Settings | None = None) -> None:
    """Start the background sender. Safe to call repeatedly."""
    global _telegram_queue, _telegram_task
    config = settings or get_settings()
    if not telegram_enabled(config):
        return
    if _telegram_task is not None and not _telegram_task.done():
        return
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    _telegram_queue = asyncio.Queue(maxsize=2000)
    _telegram_task = asyncio.create_task(_telegram_consumer())
    logger.info("Latency Telegram feed enabled")


async def stop_telegram_worker() -> None:
    global _telegram_task
    task = _telegram_task
    _telegram_task = None
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: B014 - diagnostics only
            pass


def _enqueue_telegram(entry: dict[str, Any]) -> None:
    """Non-blocking hand-off; a full queue drops the message, never the answer.

    Only the key stages reach Telegram. Everything else stays JSONL-only.
    """
    global _dropped_telegram
    queue = _telegram_queue
    if queue is None:
        return
    if entry.get("event") not in TELEGRAM_EVENTS:
        return
    try:
        queue.put_nowait(entry)
    except asyncio.QueueFull:
        _dropped_telegram += 1


def _enqueue_text(text: str) -> None:
    """Enqueue a pre-rendered message (the request summary) on the same sender."""
    global _dropped_telegram
    queue = _telegram_queue
    if queue is None:
        return
    try:
        queue.put_nowait({"_render": text})
    except asyncio.QueueFull:
        _dropped_telegram += 1


async def _telegram_consumer() -> None:
    queue = _telegram_queue
    if queue is None:  # pragma: no cover - defensive
        return
    while True:
        entry = await queue.get()
        try:
            await _send_entry(entry)
        except Exception as error:
            # Never log the exception body: a Bot API URL contains the token.
            # A missing or broken Telegram must never surface anywhere else.
            logger.debug("Latency Telegram delivery failed: %s", type(error).__name__)
        finally:
            queue.task_done()


async def _send_entry(entry: dict[str, Any]) -> None:
    settings = get_settings()
    token = latency_bot_token(settings)
    chat_id = latency_chat_id(settings)
    if not token or not chat_id:
        return
    text = entry.get("_render") or format_event(entry)
    await telegram_call(token, "sendMessage", {"chat_id": chat_id, "text": text})


def _short(value: object) -> str:
    """Short id for chat; the full value stays in JSONL."""
    return str(value)[:8]


def format_event(entry: dict[str, Any]) -> str:
    """Short, readable, content-free Telegram rendering of one event."""
    event = str(entry.get("event") or "?")
    lines = [f"{EVENT_EMOJI.get(event, '•')} {event}"]
    if entry.get("trace_id"):
        lines.append(f"trace={_short(entry['trace_id'])}")
    if entry.get("message_id"):
        lines.append(f"msg={_short(entry['message_id'])}")
    if entry.get("job_id"):
        lines.append(f"job={_short(entry['job_id'])}")
    if entry.get("since_send_ms") is not None:
        lines.append(f"t=+{int(entry['since_send_ms']) / 1000:.2f}s")
    if entry.get("duration_ms") is not None:
        lines.append(f"duration={int(entry['duration_ms']) / 1000:.2f}s")
    for key in TELEGRAM_FIELDS:
        value = entry.get(key)
        if value is None or key == "duration_ms":
            continue
        if key in TELEGRAM_MILLISECOND_LABELS:
            lines.append(f"{TELEGRAM_MILLISECOND_LABELS[key]}={int(value) / 1000:.2f}s")
            continue
        label = TELEGRAM_LABELS.get(key, key)
        if key.endswith("_ms"):
            value = f"{int(value) / 1000:.2f}s"
        lines.append(f"{label}={value}")
    return "\n".join(lines)


# --- per-request summary -----------------------------------------------------


def _read_trace_metrics(trace_id: str, settings: Settings) -> dict[str, Any]:
    """Last known value of each metric for one trace, read from the shared file.

    The watch's events are recorded by the API process while the summary is
    produced by the worker, so the shared JSONL is the only place that holds the
    whole chain. The read is bounded to the tail of the file.
    """
    path = trace_path(settings)
    metrics: dict[str, Any] = {}
    try:
        size = path.stat().st_size
    except OSError:
        return metrics
    window = min(size, 2_000_000)
    try:
        with open(path, "rb") as handle:
            if window < size:
                handle.seek(size - window)
                handle.readline()  # drop the partial first line
            for raw in handle:
                try:
                    entry = json.loads(raw.decode("utf-8", errors="replace"))
                except ValueError:
                    continue
                if entry.get("trace_id") != trace_id:
                    continue
                for key in (
                    "route",
                    "model",
                    "provider",
                    "total_ms",
                    "duration_ms",
                    "provider_ttft_ms",
                    "server_first_delta_ms",
                    "first_sse_delta_received_ms",
                    "first_visible_text_rendered_ms",
                    "response_chars",
                    "router_source",
                    "attempts_count",
                    "total_router_ms",
                    "result_status",
                ):
                    if entry.get(key) is not None:
                        metrics[key] = entry[key]
    except OSError:
        logger.debug("Unable to read latency trace metrics")
    return metrics


def format_summary(trace_id: str, metrics: dict[str, Any]) -> str:
    """One final message per request; missing values are omitted entirely."""
    lines = [f"{EVENT_EMOJI[REQUEST_FINISHED]} REQUEST FINISHED", "", f"Trace: {_short(trace_id)}"]
    if metrics.get("route"):
        lines.append(f"Route: {metrics['route']}")
    if metrics.get("total_router_ms") is not None:
        router_line = f"Router: {int(metrics['total_router_ms']) / 1000:.2f}s"
        attempts = metrics.get("attempts_count")
        if attempts:
            router_line += f" ({int(attempts)} attempt{'s' if int(attempts) != 1 else ''}"
            if metrics.get("router_source"):
                router_line += f", {metrics['router_source']}"
            router_line += ")"
        lines.append(router_line)
    first_visible = (
        metrics.get("first_visible_text_rendered_ms")
        or metrics.get("first_sse_delta_received_ms")
        or metrics.get("server_first_delta_ms")
    )
    if first_visible is not None:
        lines.append(f"First visible: {int(first_visible) / 1000:.2f}s")
    if metrics.get("provider_ttft_ms") is not None:
        lines.append(f"Provider TTFT: {int(metrics['provider_ttft_ms']) / 1000:.2f}s")
    total = metrics.get("total_ms") or metrics.get("duration_ms")
    if total is not None:
        lines.append(f"Total: {int(total) / 1000:.2f}s")
    return "\n".join(lines)


def schedule_request_summary(trace_id: str | None, delay_seconds: float = SUMMARY_DELAY_SECONDS) -> None:
    """Schedule exactly one REQUEST FINISHED message for a finished turn.

    The short delay lets the watch's last event land in the shared file first.
    The task is fire-and-forget: it never blocks or delays the answer.
    """
    if not trace_id:
        return
    settings = get_settings()
    if not telegram_enabled(settings) or _telegram_queue is None:
        return
    if trace_id in _summarized:
        return
    if len(_summarized) > 1000:
        _summarized.clear()
    _summarized.add(trace_id)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    asyncio.create_task(_emit_summary_later(trace_id, delay_seconds))


async def _emit_summary_later(trace_id: str, delay_seconds: float) -> None:
    try:
        await asyncio.sleep(delay_seconds)
        settings = get_settings()
        metrics = await asyncio.to_thread(_read_trace_metrics, trace_id, settings)
        _enqueue_text(format_summary(trace_id, metrics))
    except Exception as error:  # pragma: no cover - diagnostics must never raise
        logger.debug("Unable to build latency summary: %s", type(error).__name__)


async def telegram_call(token: str, method: str, payload: dict[str, Any], *, timeout: float = 6.0) -> Any:
    """Minimal Bot API call. The token is never logged."""
    url = f"https://api.telegram.org/bot{token}/{method}"
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        return response.json()


async def send_document(token: str, chat_id: str, path: Path, caption: str = "") -> None:
    if not token or not chat_id or not path.exists():
        return
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    with open(path, "rb") as handle:
        files = {"document": (path.name, handle, "application/jsonl")}
        data = {"chat_id": chat_id}
        if caption:
            data["caption"] = caption[:1024]
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(url, data=data, files=files)
            response.raise_for_status()


async def send_wear_diagnostics(lines: list[str], device_id: str) -> None:
    """Send an explicit watch export through the existing diagnostics bot."""
    settings = get_settings()
    token = latency_bot_token(settings)
    chat_id = latency_chat_id(settings)
    payload = ("\n".join(lines) + "\n").encode("utf-8")
    caption = f"Wear diagnostics · {device_id[:8]} · {now_iso()}"
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.post(
            f"https://api.telegram.org/bot{token}/sendDocument",
            data={"chat_id": chat_id, "caption": caption},
            files={"document": ("wear-diagnostics.txt", payload, "text/plain")},
        )
        response.raise_for_status()


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
        "telegram_enabled": telegram_enabled(config),
        "dropped_telegram": _dropped_telegram,
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
