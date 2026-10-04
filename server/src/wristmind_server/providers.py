from __future__ import annotations

import base64
import asyncio
import hashlib
import json
import math
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import httpx
from curl_cffi.requests import AsyncSession, RequestsError

from .config import Settings, resolve_model_id


class ProviderError(RuntimeError):
    pass


CHAT_STREAM_TIMEOUT = httpx.Timeout(connect=10.0, read=45.0, write=30.0, pool=10.0)
EMBEDDING_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=10.0)


@dataclass
class StreamTiming:
    """Diagnostic-only marks for one provider streaming call.

    The caller passes an empty instance and reads the fields afterwards. The
    values are ``time.perf_counter()`` readings and never influence control
    flow, retries, timeouts, model selection or the streaming protocol.
    """

    # Set immediately before the provider request is dispatched: everything the
    # caller spends up to this point (prompt build, queueing) is excluded.
    request_started_at: float | None = None
    # Set once the response headers have been read back, i.e. the request really
    # reached the provider and the model started producing.
    headers_at: float | None = None
    # Set on the first non-empty content chunk actually yielded to the caller.
    first_chunk_at: float | None = None


# Diagnostic-only observation channel. A caller that wants to know whether one
# provider call was internally retried activates it with
# :func:`provider_attempt_diagnostics`; everything is written by the provider
# into the caller's own dict. It never replaces a value the caller already put
# there, so a failed attempt cannot overwrite the real ``network_retry`` flag.
_provider_attempt_info: ContextVar[dict[str, object] | None] = ContextVar(
    "provider_attempt_info", default=None
)


@contextmanager
def provider_attempt_diagnostics(info: dict[str, object]) -> Iterator[dict[str, object]]:
    """Observe provider network attempts for the duration of one call.

    Purely observational: the provider's retry loop, sleep, error handling and
    streaming are unaffected, and a caller that does not use this context is
    never touched by it.
    """
    token = _provider_attempt_info.set(info)
    try:
        yield info
    finally:
        _provider_attempt_info.reset(token)


def _note_provider_attempt(attempt: int) -> None:
    """Record attempt progress. Never raises and never mutates the stream."""
    info = _provider_attempt_info.get()
    if info is None:
        return
    info["provider_attempt"] = attempt
    if attempt > 1:
        info["network_retry"] = True


def _observed_timing(timing: StreamTiming | None) -> StreamTiming:
    """The caller's timing object, or a private one for a diagnostic observer.

    The private object is used only to publish marks to an observing caller
    that did not pass its own instance. Nothing reads it back.
    """
    return timing if timing is not None else StreamTiming()


def _mark_provider_timing(mark: str, timing: StreamTiming | None) -> None:
    """Publish one provider mark to an observing caller, when there is one.

    The production caller that owns ``timing`` keeps reading it directly; this
    only mirrors the last attempt's request/TTFT marks for a caller that did
    not pass its own instance. Timing values are never read back by the
    provider, so control flow cannot depend on them.
    """
    info = _provider_attempt_info.get()
    if info is None:
        return
    if mark == "request":
        info["provider_ttft_ms"] = None
        info["provider_headers_ms"] = None
    elif timing is None or timing.request_started_at is None:
        return
    elif mark == "headers" and timing.headers_at is not None:
        info["provider_headers_ms"] = round((timing.headers_at - timing.request_started_at) * 1000)
    elif mark == "first_chunk" and timing.first_chunk_at is not None:
        info["provider_ttft_ms"] = round((timing.first_chunk_at - timing.request_started_at) * 1000)


def deterministic_embedding(text: str, dimensions: int = 1536) -> list[float]:
    values = [0.0] * dimensions
    for token in text.lower().split():
        digest = hashlib.sha256(token.encode()).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        values[index] += -1.0 if digest[4] & 1 else 1.0
    norm = math.sqrt(sum(item * item for item in values)) or 1.0
    return [item / norm for item in values]


class ProviderRouter:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._gigachat_token: str | None = None
        self._gigachat_token_expires_at = 0.0
        self._router_deepseek_client: httpx.AsyncClient | None = None

    async def aclose(self) -> None:
        if self._router_deepseek_client is not None:
            await self._router_deepseek_client.aclose()
            self._router_deepseek_client = None

    async def stream_answer(
        self,
        model_id: str,
        messages: list[dict[str, str]],
        *,
        session_id: str | None = None,
        timing: StreamTiming | None = None,
        thinking: bool = True,
        reuse_connection: bool = False,
    ) -> AsyncIterator[str]:
        model_id = resolve_model_id(model_id)
        provider, _, remote_model = model_id.partition(":")
        if self.settings.mock_providers:
            question = next(
                (item["content"] for item in reversed(messages) if item["role"] == "user"),
                "",
            )
            answer = f"Тестовый ответ WristMind: {question}"
            for part in answer.split(" "):
                yield part + " "
            return
        if provider == "openrouter":
            headers = self._openrouter_headers()
            # A stable session keeps a chat on the same provider route. This
            # allows OpenRouter/provider prompt caches to reuse the unchanged
            # system prompt and preceding chat history on later turns.
            if session_id:
                headers["X-Session-Id"] = session_id
            # OpenRouter occasionally drops a connection before it sends the
            # first SSE chunk. Retrying only in that narrow window is safe:
            # no partial answer has reached the user, so it cannot duplicate
            # text or repeat an already-visible response.
            delivered_content = False
            for attempt in range(2):
                # Diagnostic-only observation of which network attempt this is.
                # The loop, the sleep and the error handling are unchanged.
                _note_provider_attempt(attempt + 1)
                try:
                    async for chunk in self._stream_openrouter(
                        f"{self.settings.openrouter_base_url.rstrip('/')}/chat/completions",
                        headers,
                        remote_model,
                        messages,
                        timing=timing,
                    ):
                        delivered_content = True
                        yield chunk
                    return
                except ProviderError as exc:
                    transient_network_error = isinstance(
                        exc.__cause__,
                        (httpx.TimeoutException, httpx.NetworkError, RequestsError),
                    )
                    if delivered_content or attempt == 1 or not transient_network_error:
                        raise
                    await asyncio.sleep(0.35)
            return
        if provider == "deepseek":
            # The official DeepSeek API is OpenAI-compatible, so it uses the
            # plain httpx path rather than OpenRouter's browser TLS profile.
            # Reasoning stays on by default at a lower effort than the API
            # default. The router and final answer opt out explicitly; other
            # callers keep their existing behaviour.
            if thinking:
                extra_payload: dict[str, object] = {
                    "thinking": {"type": "enabled"},
                    "reasoning_effort": self.settings.deepseek_reasoning_effort,
                }
            else:
                extra_payload = {"thinking": {"type": "disabled"}}
            headers = self._deepseek_headers()
            if reuse_connection and self._router_deepseek_client is None:
                self._router_deepseek_client = httpx.AsyncClient(timeout=CHAT_STREAM_TIMEOUT)
            async for chunk in self._stream_openai_compatible(
                f"{self.settings.deepseek_base_url.rstrip('/')}/chat/completions",
                headers,
                remote_model,
                messages,
                extra_payload=extra_payload,
                timing=timing,
                client=self._router_deepseek_client if reuse_connection else None,
            ):
                yield chunk
            return
        if provider == "gigachat":
            token = await self._get_gigachat_token()
            request = self._stream_openai_compatible(
                f"{self.settings.gigachat_base_url.rstrip('/')}/chat/completions",
                {"Authorization": f"Bearer {token}"},
                remote_model,
                messages,
                verify=self.settings.gigachat_verify_ssl,
                timing=timing,
            )
            try:
                async for chunk in request:
                    yield chunk
            except ProviderError as exc:
                if "Token has expired" not in str(exc):
                    raise
                # A token can expire between the cache check and the request.
                # Refresh once, then let the original provider error surface.
                self._gigachat_token = None
                self._gigachat_token_expires_at = 0.0
                token = await self._get_gigachat_token()
                async for chunk in self._stream_openai_compatible(
                    f"{self.settings.gigachat_base_url.rstrip('/')}/chat/completions",
                    {"Authorization": f"Bearer {token}"},
                    remote_model,
                    messages,
                    verify=self.settings.gigachat_verify_ssl,
                    timing=timing,
                ):
                    yield chunk
            return
        raise ProviderError(f"Unsupported provider: {provider}")

    async def _stream_openrouter(
        self,
        url: str,
        headers: dict[str, str],
        model: str,
        messages: list[dict[str, str]],
        *,
        timing: StreamTiming | None = None,
    ) -> AsyncIterator[str]:
        """Stream through OpenRouter with a regular browser TLS profile.

        OpenRouter's edge security can reject the default TLS fingerprint of
        automated HTTP clients even when the same account and VPN succeed in a
        browser or curl. curl_cffi keeps the API request identical while using
        Chrome's network fingerprint for this provider only.
        """
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.15,
            "stream": True,
        }
        try:
            async with AsyncSession(impersonate="chrome") as client:
                # Diagnostic mirror for a caller that observes this call through
                # provider_attempt_diagnostics; it never feeds back into control.
                observed_timing = _observed_timing(timing)
                timing = observed_timing
                timing.request_started_at = time.perf_counter()
                _mark_provider_timing("request", timing)
                async with client.stream(
                    "POST",
                    url,
                    headers=headers,
                    json=payload,
                    timeout=45,
                ) as response:
                    timing.headers_at = time.perf_counter()
                    _mark_provider_timing("headers", timing)
                    if response.status_code >= 400:
                        raise ProviderError(
                            f"Provider HTTP {response.status_code}: {(await response.acontent())[:500]!r}"
                        )
                    async for raw_line in response.aiter_lines():
                        line = raw_line.decode("utf-8", errors="replace")
                        if not line.startswith("data:"):
                            continue
                        data = line.removeprefix("data:").strip()
                        if not data or data == "[DONE]":
                            continue
                        try:
                            body = json.loads(data)
                            chunk = body["choices"][0]["delta"].get("content")
                        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
                            continue
                        if chunk:
                            if timing.first_chunk_at is None:
                                timing.first_chunk_at = time.perf_counter()
                            _mark_provider_timing("first_chunk", timing)
                            yield chunk
        except RequestsError as exc:
            raise ProviderError("Не удалось подключиться к провайдеру") from exc

    async def _stream_openai_compatible(
        self,
        url: str,
        headers: dict[str, str],
        model: str,
        messages: list[dict[str, str]],
        *,
        verify: bool = True,
        extra_payload: dict[str, object] | None = None,
        timing: StreamTiming | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> AsyncIterator[str]:
        payload: dict[str, object] = {
            "model": model,
            "messages": messages,
            "temperature": 0.15,
            "stream": True,
        }
        if extra_payload:
            payload.update(extra_payload)
        owns_client = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=CHAT_STREAM_TIMEOUT, verify=verify)
        try:
            try:
                timing = _observed_timing(timing)
                timing.request_started_at = time.perf_counter()
                _mark_provider_timing("request", timing)
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    timing.headers_at = time.perf_counter()
                    _mark_provider_timing("headers", timing)
                    if response.status_code >= 400:
                        raise ProviderError(f"Provider HTTP {response.status_code}: {(await response.aread())[:500]!r}")
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line.removeprefix("data:").strip()
                        if not data or data == "[DONE]":
                            continue
                        try:
                            body = json.loads(data)
                            chunk = body["choices"][0]["delta"].get("content")
                        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
                            continue
                        if chunk:
                            if timing.first_chunk_at is None:
                                timing.first_chunk_at = time.perf_counter()
                            _mark_provider_timing("first_chunk", timing)
                            yield chunk
            finally:
                if owns_client:
                    await client.aclose()
        except httpx.TimeoutException as exc:
            raise ProviderError("Провайдер не ответил в течение 45 секунд") from exc
        except httpx.HTTPError as exc:
            raise ProviderError("Не удалось подключиться к провайдеру") from exc

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self.settings.mock_providers or not self.settings.openrouter_api_key:
            return [deterministic_embedding(item) for item in texts]
        payload = {"model": self.settings.embedding_model, "input": texts}
        try:
            async with httpx.AsyncClient(timeout=EMBEDDING_TIMEOUT) as client:
                response = await client.post(
                    f"{self.settings.openrouter_base_url.rstrip('/')}/embeddings",
                    headers=self._openrouter_headers(),
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise ProviderError("Не удалось создать embeddings: провайдер недоступен") from exc
        except httpx.HTTPError as exc:
            raise ProviderError("Не удалось подключиться к провайдеру embeddings") from exc
        if response.status_code >= 400:
            raise ProviderError(f"Embedding HTTP {response.status_code}: {response.text[:500]}")
        data = sorted(response.json()["data"], key=lambda item: item["index"])
        return [item["embedding"] for item in data]

    async def analyze_file(self, path: Path, media_type: str) -> str:
        if self.settings.mock_providers or not self.settings.openrouter_api_key:
            raise ProviderError("Vision provider is not configured")
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        content_type = "file" if media_type == "application/pdf" else "image_url"
        file_value = f"data:{media_type};base64,{encoded}"
        attachment = (
            {"type": "file", "file": {"filename": path.name, "file_data": file_value}}
            if content_type == "file"
            else {"type": "image_url", "image_url": {"url": file_value}}
        )
        payload = {
            "model": self.settings.vision_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Оцифруй источник в структурированный Markdown. Сохрани язык, "
                                "нумерацию заданий, формулы, таблицы и подписи. Для схем и "
                                "изображений добавь точное смысловое описание. Ничего не решай."
                            ),
                        },
                        attachment,
                    ],
                }
            ],
            "temperature": 0,
        }
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(
                f"{self.settings.openrouter_base_url.rstrip('/')}/chat/completions",
                headers=self._openrouter_headers(),
                json=payload,
            )
        if response.status_code >= 400:
            raise ProviderError(f"Vision HTTP {response.status_code}: {response.text[:500]}")
        return response.json()["choices"][0]["message"]["content"].strip()

    async def transcribe(self, path: Path, media_type: str) -> str:
        if self.settings.mock_providers or not self.settings.openrouter_api_key:
            return "Тестовая расшифровка WristMind"
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{self.settings.openrouter_base_url.rstrip('/')}/audio/transcriptions",
                headers=self._openrouter_headers(),
                data={"model": self.settings.stt_model, "language": "ru"},
                files={"file": (path.name, path.read_bytes(), media_type)},
            )
        if response.status_code >= 400:
            raise ProviderError(f"STT HTTP {response.status_code}: {response.text[:500]}")
        body = response.json()
        return str(body.get("text") or body.get("transcript") or "").strip()

    def _openrouter_headers(self) -> dict[str, str]:
        if not self.settings.openrouter_api_key:
            raise ProviderError("OpenRouter API key is missing")
        return {
            "Authorization": f"Bearer {self.settings.openrouter_api_key.get_secret_value()}",
            "HTTP-Referer": self.settings.public_base_url,
            "X-Title": "WristMind",
        }

    def _deepseek_headers(self) -> dict[str, str]:
        if not self.settings.deepseek_api_key:
            raise ProviderError("DeepSeek API key is missing")
        return {"Authorization": f"Bearer {self.settings.deepseek_api_key.get_secret_value()}"}

    async def _get_gigachat_token(self) -> str:
        now = time.time()
        if self._gigachat_token and now < self._gigachat_token_expires_at - 30:
            return self._gigachat_token
        if not self.settings.gigachat_credentials:
            raise ProviderError("GigaChat credentials are missing")
        headers = {
            "Authorization": f"Basic {self.settings.gigachat_credentials.get_secret_value()}",
            "RqUID": str(uuid4()),
            "Content-Type": "application/x-www-form-urlencoded",
        }
        async with httpx.AsyncClient(
            timeout=30,
            verify=self.settings.gigachat_verify_ssl,
        ) as client:
            response = await client.post(
                self.settings.gigachat_auth_url,
                headers=headers,
                data={"scope": self.settings.gigachat_scope},
            )
        if response.status_code >= 400:
            raise ProviderError(f"GigaChat auth HTTP {response.status_code}")
        try:
            body = response.json()
            token = body["access_token"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderError("GigaChat auth response has no access token") from exc
        self._gigachat_token = str(token)
        try:
            expires_at = float(body.get("expires_at", now + 1500))
            # GigaChat returns an epoch timestamp in milliseconds. Accept
            # seconds as well so older/proxy responses remain compatible.
            if expires_at > 10_000_000_000:
                expires_at /= 1000
            self._gigachat_token_expires_at = expires_at
        except (TypeError, ValueError):
            self._gigachat_token_expires_at = now + 1500
        return self._gigachat_token
