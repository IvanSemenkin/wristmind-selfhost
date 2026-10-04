import asyncio

import httpx

from wristmind_server.config import Settings
from wristmind_server.providers import (
    ProviderError,
    ProviderRouter,
    StreamTiming,
    provider_attempt_diagnostics,
)


def test_provider_diagnostics_report_a_network_retry_without_changing_it() -> None:
    router = ProviderRouter(Settings(mock_providers=False, openrouter_api_key="test-key"))
    attempts = 0
    info: dict[str, object] = {}

    async def flaky_stream(*_args, **kwargs):
        nonlocal attempts
        attempts += 1
        timing = kwargs.get("timing")
        if isinstance(timing, StreamTiming):
            timing.request_started_at = 0.0
            timing.headers_at = 0.2
            timing.first_chunk_at = 0.5
        if attempts == 1:
            raise ProviderError("Не удалось подключиться к провайдеру") from httpx.ConnectError(
                "connection reset"
            )
        yield "готово"

    router._stream_openrouter = flaky_stream  # type: ignore[method-assign]

    async def collect() -> list[str]:
        with provider_attempt_diagnostics(info):
            return [
                chunk
                async for chunk in router.stream_answer(
                    "openrouter:qwen/qwen3.8-flash",
                    [{"role": "user", "content": "Проверка"}],
                )
            ]

    assert asyncio.run(collect()) == ["готово"]
    # The retry itself is unchanged: still exactly two network attempts.
    assert attempts == 2
    assert info["provider_attempt"] == 2
    assert info["network_retry"] is True


def test_provider_diagnostics_stay_silent_without_an_observer() -> None:
    router = ProviderRouter(Settings(mock_providers=False, openrouter_api_key="test-key"))
    seen: list[StreamTiming | None] = []

    async def stream(*_args, **kwargs):
        seen.append(kwargs.get("timing"))
        yield "готово"

    router._stream_openrouter = stream  # type: ignore[method-assign]

    async def collect() -> list[str]:
        return [
            chunk
            async for chunk in router.stream_answer(
                "openrouter:qwen/qwen3.8-flash",
                [{"role": "user", "content": "Проверка"}],
            )
        ]

    assert asyncio.run(collect()) == ["готово"]
    # Nothing is observed, nothing is created, nothing is recorded.
    assert seen == [None]


def test_openrouter_retries_initial_network_disconnect_once() -> None:
    router = ProviderRouter(Settings(mock_providers=False, openrouter_api_key="test-key"))
    attempts = 0

    async def flaky_stream(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ProviderError("Не удалось подключиться к провайдеру") from httpx.ConnectError(
                "connection reset"
            )
        yield "готово"

    router._stream_openrouter = flaky_stream  # type: ignore[method-assign]

    async def collect() -> list[str]:
        return [
            chunk
            async for chunk in router.stream_answer(
                "openrouter:qwen/qwen3.8-flash",
                [{"role": "user", "content": "Проверка"}],
            )
        ]

    assert asyncio.run(collect()) == ["готово"]
    assert attempts == 2


def test_openrouter_uses_stable_chat_session_for_prompt_cache_routing() -> None:
    router = ProviderRouter(Settings(mock_providers=False, openrouter_api_key="test-key"))
    seen: dict = {}
    router._stream_openrouter = _capture_stream(seen)  # type: ignore[method-assign]

    async def collect() -> list[str]:
        return [
            chunk
            async for chunk in router.stream_answer(
                "openrouter:qwen/qwen3.8-flash",
                [{"role": "user", "content": "Проверка"}],
                session_id="chat:4a4d2d72-546e-4e43-bb55-efc9c1225ab6",
            )
        ]

    assert asyncio.run(collect()) == ["готово"]
    assert seen["headers"]["X-Session-Id"] == "chat:4a4d2d72-546e-4e43-bb55-efc9c1225ab6"


def _capture_stream(seen: dict) -> object:
    async def capture(url, headers, model, messages, **kwargs):
        seen["url"] = url
        seen["headers"] = headers
        seen["model"] = model
        seen["extra_payload"] = kwargs.get("extra_payload")
        yield "готово"

    return capture


def test_deepseek_uses_official_api() -> None:
    router = ProviderRouter(Settings(mock_providers=False, deepseek_api_key="ds-key"))
    seen: dict = {}
    router._stream_openai_compatible = _capture_stream(seen)  # type: ignore[method-assign]

    async def collect(model_id: str) -> list[str]:
        return [
            chunk
            async for chunk in router.stream_answer(model_id, [{"role": "user", "content": "Привет"}])
        ]

    assert asyncio.run(collect("deepseek:deepseek-flash")) == ["готово"]
    assert seen["url"] == "https://api.deepseek.com/chat/completions"
    assert seen["headers"] == {"Authorization": "Bearer ds-key"}
    assert seen["model"] == "deepseek-flash"
    assert seen["extra_payload"] == {"thinking": {"type": "enabled"}, "reasoning_effort": "low"}


def test_deepseek_reasoning_effort_is_configurable() -> None:
    router = ProviderRouter(
        Settings(mock_providers=False, deepseek_api_key="ds-key", deepseek_reasoning_effort="max")
    )
    seen: dict = {}
    router._stream_openai_compatible = _capture_stream(seen)  # type: ignore[method-assign]

    async def collect() -> list[str]:
        return [
            chunk
            async for chunk in router.stream_answer(
                "deepseek:deepseek-flash", [{"role": "user", "content": "Привет"}]
            )
        ]

    assert asyncio.run(collect()) == ["готово"]
    assert seen["extra_payload"] == {"thinking": {"type": "enabled"}, "reasoning_effort": "max"}


def test_legacy_openrouter_deepseek_id_routes_to_official_api() -> None:
    router = ProviderRouter(Settings(mock_providers=False, deepseek_api_key="ds-key"))
    seen: dict = {}
    router._stream_openai_compatible = _capture_stream(seen)  # type: ignore[method-assign]

    async def openrouter_should_not_run(*_args, **_kwargs):
        raise AssertionError("legacy DeepSeek id must not reach OpenRouter")
        yield  # pragma: no cover

    router._stream_openrouter = openrouter_should_not_run  # type: ignore[method-assign]

    async def collect() -> list[str]:
        return [
            chunk
            async for chunk in router.stream_answer(
                "openrouter:deepseek/deepseek-v4-flash-0731",
                [{"role": "user", "content": "Привет"}],
            )
        ]

    assert asyncio.run(collect()) == ["готово"]
    assert seen["url"] == "https://api.deepseek.com/chat/completions"


def test_deepseek_final_answer_call_can_disable_thinking() -> None:
    router = ProviderRouter(Settings(mock_providers=False, deepseek_api_key="ds-key"))
    seen: dict = {}
    router._stream_openai_compatible = _capture_stream(seen)  # type: ignore[method-assign]

    async def collect() -> list[str]:
        return [
            chunk
            async for chunk in router.stream_answer(
                "deepseek:deepseek-flash",
                [{"role": "user", "content": "Проверка"}],
                thinking=False,
            )
        ]

    assert asyncio.run(collect()) == ["готово"]
    assert seen["extra_payload"] == {"thinking": {"type": "disabled"}}


def test_deepseek_thinking_stays_on_by_default() -> None:
    router = ProviderRouter(Settings(mock_providers=False, deepseek_api_key="ds-key"))
    seen: dict = {}
    router._stream_openai_compatible = _capture_stream(seen)  # type: ignore[method-assign]

    async def collect() -> list[str]:
        return [
            chunk
            async for chunk in router.stream_answer(
                "deepseek:deepseek-flash",
                [{"role": "user", "content": "Проверка"}],
            )
        ]

    assert asyncio.run(collect()) == ["готово"]
    assert seen["extra_payload"] == {"thinking": {"type": "enabled"}, "reasoning_effort": "low"}
