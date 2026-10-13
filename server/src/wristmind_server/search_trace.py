"""Content-free search telemetry in the existing rotating latency JSONL.

No message/title/URL, provider credentials, file path, or exception body is accepted.
Context variables isolate requests and propagate into asyncio.to_thread work.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
import hashlib
import os
from pathlib import Path
import time


_current = ContextVar('search_trace', default=None)
_purpose = ContextVar('search_llm_purpose', default='final_answer')
_call = ContextVar('search_llm_call', default=None)
_STRING_FIELDS = {'stage', 'status', 'purpose', 'reason', 'completion', 'stop_reason', 'route', 'kind', 'mode'}
_NUMERIC_FIELDS = {'duration_ms', 'response_ms', 'worker_ms', 'llm_calls', 'network_attempts',
                  'searches', 'opens', 'successful_opens', 'cache_hits', 'cache_misses', 'cache_skipped',
                  'chars_in', 'chars_out', 'bytes_in', 'rss_bytes', 'peak_rss_bytes', 'child_peak_rss_bytes',
                  'trafilatura_ms', 'cache_bytes', 'score', 'call_id', 'pages', 'verified_sources',
                  'prompt_tokens', 'completion_tokens', 'total_tokens', 'http_status',
                  'active_operations', 'kind_active', 'peak_concurrency', 'waiting_operations',
                  'slot_wait_ms', 'available_bytes', 'cpu_load', 'cancellations', 'first_source_ms', 'kind_peak'}


def fingerprint(value):
    return hashlib.sha256(str(value).encode()).hexdigest()[:20]


def memory():
    try:
        values = {}
        for line in Path('/proc/self/status').read_text().splitlines():
            if line.startswith(('VmRSS:', 'VmHWM:')):
                key = 'rss_bytes' if line.startswith('VmRSS:') else 'peak_rss_bytes'
                values[key] = int(line.split()[1]) * 1024
        return values
    except (OSError, ValueError, IndexError):
        return {}  # Unsupported platforms report unavailable, never zero.


@dataclass
class SearchTrace:
    job_id: str
    started: float = field(default_factory=time.perf_counter)
    received_ms: int | None = None
    route: str = 'none'
    completion: str = 'unverified'
    stop_reason: str = 'no_search'
    searches: int = 0
    opens: int = 0
    successful_opens: int = 0
    verified_sources: int = 0
    llm_calls: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    cache_skipped: int = 0
    tokens: dict = field(default_factory=dict)

    def event(self, event, **fields):
        # Strong allowlist: unknown data is dropped even if a caller passes it.
        safe = {}
        for key, value in fields.items():
            if key in _NUMERIC_FIELDS and isinstance(value, (int, float)) and not isinstance(value, bool):
                safe[key] = value
            elif key in _STRING_FIELDS and isinstance(value, str):
                # Only code-owned short identifiers, no natural-language reasons.
                if len(value) <= 64 and all(c.isascii() and (c.isalnum() or c in '_-.') for c in value):
                    safe[key] = value
            elif key == 'url_hash' and isinstance(value, str) and len(value) == 20 and all(c in '0123456789abcdef' for c in value):
                safe[key] = value
        try:
            from . import latency_trace
            latency_trace.record('SEARCH_' + event, job_id=self.job_id, **safe)
        except Exception:
            pass  # Diagnostics must never fail a request.


@contextmanager
def scope(job_id):
    # Hash non-UUID test/client identifiers; content supplied as an ID cannot leak.
    import uuid
    try:
        safe_id = str(uuid.UUID(str(job_id)))
    except (ValueError, TypeError, AttributeError):
        safe_id = fingerprint(job_id)
    trace = SearchTrace(safe_id)
    token = _current.set(trace)
    try:
        yield trace
    finally:
        _current.reset(token)


def current():
    return _current.get()


def event(name, **fields):
    trace = current()
    if trace is not None:
        trace.event(name, **fields)


@contextmanager
def stage(name, **fields):
    start = time.perf_counter()
    status = 'success'
    try:
        yield fields
    except BaseException as exc:
        status = 'cancelled' if isinstance(exc, (asyncio.CancelledError, GeneratorExit)) else 'error'
        fields['reason'] = type(exc).__name__
        raise
    finally:
        event('STAGE', stage=name, status=status, duration_ms=round((time.perf_counter()-start)*1000, 3),
              **fields, **memory())


def purpose(name):
    def decorate(function):
        @wraps(function)
        async def wrapped(*args, **kwargs):
            token = _purpose.set(name)
            try:
                return await function(*args, **kwargs)
            finally:
                _purpose.reset(token)
        return wrapped
    return decorate


@contextmanager
def llm_call(name=None):
    trace = current()
    if trace is None or _call.get() is not None:
        yield
        return
    trace.llm_calls += 1
    info = {'call_id': trace.llm_calls, 'network_attempts': 1}
    token = _call.set(info)
    started = time.perf_counter()
    status = 'success'
    try:
        yield
    except BaseException as exc:
        status = 'cancelled' if isinstance(exc, (asyncio.CancelledError, GeneratorExit)) else 'error'
        raise
    finally:
        trace.event('LLM', purpose=name or _purpose.get(), status=status,
                    duration_ms=round((time.perf_counter()-started)*1000, 3), **info)
        for key in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
            if key in info:
                trace.tokens[key] = trace.tokens.get(key, 0) + info[key]
        _call.reset(token)


def observed_stream(function):
    @wraps(function)
    async def wrapped(*args, **kwargs):
        with llm_call():
            stream = function(*args, **kwargs)
            try:
                async for chunk in stream:
                    yield chunk
            finally:
                await stream.aclose()
    return wrapped


def observed_call(name):
    def decorate(function):
        @wraps(function)
        async def wrapped(*args, **kwargs):
            with llm_call(name):
                return await function(*args, **kwargs)
        return wrapped
    return decorate


def usage(value):
    info = _call.get()
    if info is None or not isinstance(value, dict):
        return
    for target, keys in (('prompt_tokens', ('prompt_tokens', 'input_tokens')),
                         ('completion_tokens', ('completion_tokens', 'output_tokens')),
                         ('total_tokens', ('total_tokens',))):
        for key in keys:
            number = value.get(key)
            if isinstance(number, int) and not isinstance(number, bool) and 0 <= number < 10**10:
                info[target] = max(info.get(target, 0), number)
                break
    if 'total_tokens' not in info and 'prompt_tokens' in info and 'completion_tokens' in info:
        info['total_tokens'] = info['prompt_tokens'] + info['completion_tokens']
    elif 'prompt_tokens' in info and 'completion_tokens' in info:
        info['total_tokens'] = max(info['total_tokens'], info['prompt_tokens'] + info['completion_tokens'])


def network_attempt(attempt):
    info = _call.get()
    if info is not None:
        info['network_attempts'] = max(info['network_attempts'], attempt)


def traced_answer(function):
    @wraps(function)
    async def wrapped(job_id, *args, **kwargs):
        with scope(job_id) as trace:
            status = 'complete'
            try:
                return await function(job_id, *args, **kwargs)
            except asyncio.CancelledError:
                status = 'cancelled'
                trace.stop_reason = 'cancelled'
                raise
            except BaseException:
                status = 'error'
                raise
            finally:
                if trace.received_ms is not None:
                    trace.event('SUMMARY', status=status, route=trace.route, completion=trace.completion,
                        stop_reason=trace.stop_reason, response_ms=max(0, round(time.time()*1000)-trace.received_ms),
                        worker_ms=round((time.perf_counter()-trace.started)*1000, 3),
                        llm_calls=trace.llm_calls, searches=trace.searches, opens=trace.opens,
                        successful_opens=trace.successful_opens, verified_sources=trace.verified_sources,
                        cache_hits=trace.cache_hits, cache_misses=trace.cache_misses, cache_skipped=trace.cache_skipped,
                        **trace.tokens, **memory())
    return wrapped
