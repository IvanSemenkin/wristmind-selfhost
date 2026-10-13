from __future__ import annotations

import base64
import asyncio
import hashlib
import json
import math
import time
import subprocess
from tempfile import TemporaryDirectory
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import httpx
from pypdf import PdfReader
from curl_cffi.requests import AsyncSession, RequestsError

from . import search_trace
from .resource_controller import resources, resource_operation
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
    search_trace.network_attempt(attempt)
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

    @search_trace.observed_stream
    async def stream_answer(
        self,
        model_id: str,
        messages: list[dict[str, str]],
        *,
        session_id: str | None = None,
        timing: StreamTiming | None = None,
        thinking: bool = True,
        reuse_connection: bool = False,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        model_id = resolve_model_id(model_id)
        provider, _, remote_model = model_id.partition(":")
        connection = next((p for p in self.settings.provider_connections if p.id == provider), None)
        if connection and not connection.enabled:
            raise ProviderError('Этот провайдер выключен. Включите его в настройках.')
        if provider.startswith('p_') and connection is None:
            raise ProviderError('Провайдер модели больше не доступен. Проверьте настройки.')
        if provider.startswith('p_') and not self.settings.model_option(model_id):
            raise ProviderError('Модель выключена или не добавлена. Проверьте настройки.')
        if self.settings.mock_providers:
            question = next(
                (item["content"] for item in reversed(messages) if item["role"] == "user"),
                "",
            )
            answer = f"Тестовый ответ WristMind: {question}"
            for part in answer.split(" "):
                yield part + " "
            return
        if connection and provider.startswith('p_') and connection.kind not in {'gigachat', 'openrouter'}:
            from .provider_connections import stream_connection
            async for chunk in stream_connection(connection, remote_model, messages, max_tokens=max_tokens, timing=timing, thinking=thinking, reasoning_effort=self.settings.deepseek_reasoning_effort):
                yield chunk
            return
        if provider.startswith('p_') and not (connection and connection.kind == 'openrouter'):
            raise ProviderError('Провайдер модели больше не доступен. Проверьте настройки.')
        if provider == "openrouter" or (connection and connection.kind == "openrouter"):
            headers = self._openrouter_headers() if not connection else {"Authorization": "Bearer " + connection.api_key.get_secret_value()}
            openrouter_url = connection.base_url if connection else self.settings.openrouter_base_url
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
                        f"{openrouter_url.rstrip('/')}/chat/completions",
                        headers,
                        remote_model,
                        messages,
                        timing=timing,
                        **({"max_tokens": max_tokens} if max_tokens is not None else {}),
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
            if max_tokens is not None:
                extra_payload["max_tokens"] = max_tokens
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
        max_tokens: int | None = None,
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
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
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
                            search_trace.usage(body.get("usage") if isinstance(body, dict) else None)
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
                            search_trace.usage(body.get("usage") if isinstance(body, dict) else None)
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
        from .model_capabilities import selected, embeddings
        choice = selected(self.settings, 'embedding')
        if choice and texts and not self.settings.mock_providers:
            return await embeddings(*choice, texts)
        if self.settings.selfhost_enabled and not choice:
            # Explicit lexical fallback; never masquerade as a remote semantic embedding.
            return [[] for _ in texts]
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

    @search_trace.observed_call("vision_ocr")
    @resource_operation('ocr')
    async def analyze_file(self, path: Path, media_type: str) -> str:
        from .model_capabilities import selected, image_text
        choice = selected(self.settings, 'vision')
        if choice:
            is_pdf = media_type == 'application/pdf' or path.suffix.lower() == '.pdf'
            pages = await resources().thread('pdf', lambda: len(PdfReader(str(path)).pages)) if is_pdf else 1
            if not 1 <= pages <= self.settings.max_pdf_pages: raise ProviderError('Превышен предел страниц PDF')
            answers = []
            for page in range(1, pages + 1):
                data = await resources().thread('pdf', self._vision_pdf_page, path, page) if is_pdf else await resources().thread('pdf', path.read_bytes)
                text = 'Тестовый источник' if self.settings.mock_providers else await image_text(*choice, data, 'image/png' if is_pdf else media_type)
                answers.append(f'## Страница {page}\n\n{text}' if is_pdf else text)
            return '\n\n'.join(answers)
        if self.settings.selfhost_enabled: raise ProviderError('Добавьте Vision-модель в настройках для оцифровки изображений')
        if self.settings.mock_providers or not self.settings.deepseek_api_key:
            raise ProviderError("Vision provider is not configured")
        is_pdf = media_type == "application/pdf" or path.suffix.lower() == ".pdf"
        pages = await resources().thread('pdf', lambda: len(PdfReader(str(path)).pages)) if is_pdf else 1
        if pages < 1 or pages > self.settings.max_pdf_pages:
            raise ProviderError("PDF exceeds the supported page limit")
        answers = []
        # One session for all pages; PDFs are rendered locally, never sent as unsupported file blocks.
        async with httpx.AsyncClient(timeout=180) as client:
            for page in range(1, pages + 1):
                data = await resources().thread('pdf', self._vision_pdf_page, path, page) if is_pdf else await resources().thread('pdf', path.read_bytes)
                image_type = "image/png" if is_pdf else media_type
                encoded = base64.b64encode(data).decode("ascii")
                payload = {
                    "model": self.settings.vision_model,
                    "thinking": {"type": "disabled"},
                    "messages": [{"role": "user", "content": [
                        {"type": "text", "text": (
                            "Оцифруй источник в структурированный Markdown. Сохрани язык, "
                            "нумерацию заданий, формулы, таблицы и подписи. Для схем и "
                            "изображений добавь точное смысловое описание. Ничего не решай."
                        )},
                        {"type": "image_url", "image_url": {
                            "url": f"data:{image_type};base64,{encoded}", "detail": "original",
                        }},
                    ]}],
                    "temperature": 0,
                }
                try:
                    response = await client.post(
                        f"{self.settings.deepseek_base_url.rstrip('/')}/chat/completions",
                        headers=self._deepseek_headers(), json=payload,
                    )
                except httpx.HTTPError as exc:
                    raise ProviderError("Не удалось подключиться к DeepSeek Vision") from exc
                if response.status_code >= 400:
                    raise ProviderError(f"DeepSeek Vision HTTP {response.status_code}")
                search_trace.usage(response.json().get("usage"))
                text = response.json()["choices"][0]["message"]["content"].strip()
                if not text:
                    raise ProviderError("DeepSeek Vision вернул пустой результат")
                answers.append(f"## Страница {page}\n\n{text}" if is_pdf else text)
        return "\n\n".join(answers)

    @staticmethod
    def _vision_pdf_page(path: Path, page: int) -> bytes:
        with TemporaryDirectory(prefix="wristmind-vision-") as directory:
            prefix = Path(directory) / "page"
            try:
                subprocess.run(
                    ["pdftoppm", "-f", str(page), "-l", str(page), "-singlefile",
                     "-scale-to", "2000", "-png", str(path), str(prefix)],
                    check=True, timeout=60, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                return prefix.with_suffix(".png").read_bytes()
            except (OSError, subprocess.SubprocessError) as exc:
                raise ProviderError("Не удалось подготовить страницу PDF для Vision") from exc

    async def transcribe_yandex(self, audio: bytes) -> str:
        from .model_capabilities import selected, pcm_text
        choice = selected(self.settings, 'speech')
        if choice and choice[0].kind != 'yandex':
            return 'Тестовая расшифровка WristMind' if self.settings.mock_providers else await pcm_text(self.settings, audio)
        if self.settings.mock_providers:
            return "Тестовая расшифровка WristMind"
        if not self.settings.yandex_speechkit_api_key:
            raise ProviderError("SpeechKit не настроен")
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(25, connect=8)) as client:
                response = await client.post(
                    "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize",
                    headers={"Authorization": f"Api-Key {self.settings.yandex_speechkit_api_key.get_secret_value()}"},
                    params={"lang": "ru-RU", "format": "lpcm", "sampleRateHertz": "16000", "rawResults": "false", "profanityFilter": "false"},
                    content=audio,
                )
        except httpx.HTTPError as error:
            raise ProviderError("Сервис распознавания временно недоступен. Попробуйте ещё раз.") from error
        if response.status_code >= 400:
            raise ProviderError(f"SpeechKit не принял запрос (HTTP {response.status_code}). Проверьте ключ, права и баланс.")
        try:
            return str(response.json().get("result") or "").strip()
        except ValueError as error:
            raise ProviderError("Сервис распознавания вернул некорректный ответ") from error

    async def transcribe(self, path: Path, media_type: str) -> str:
        from .model_capabilities import selected, audio_text
        choice = selected(self.settings, 'speech')
        if choice:
            return 'Тестовая расшифровка WristMind' if self.settings.mock_providers else await audio_text(*choice, await asyncio.to_thread(path.read_bytes), media_type)
        if self.settings.selfhost_enabled: raise ProviderError('Добавьте модель распознавания голоса в настройках')
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
