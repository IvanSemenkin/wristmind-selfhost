from __future__ import annotations

import asyncio
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import uvicorn
import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .config import get_settings
from .identity import CORE_IDENTITY_PROMPT
from .fallback_auth import FallbackIdentity, FallbackTicketError, verify_fallback_ticket


settings = get_settings()


class FallbackHistoryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20_000)


class FallbackAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=100)
    chat_id: str = Field(min_length=1, max_length=100)
    mode_name: str = Field(default="WristMind", max_length=80)
    system_prompt: str = Field(default="", max_length=20_000)
    history: list[FallbackHistoryMessage] = Field(default_factory=list, max_length=50)
    text: str = Field(min_length=1, max_length=20_000)
    requested_web_search: bool = False


class FallbackAnswerResponse(BaseModel):
    request_id: str
    answer: str
    degraded: bool = True
    sources_available: bool = False


def _database_path() -> Path:
    path = settings.fallback_database_path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _initialize_database() -> None:
    with sqlite3.connect(_database_path()) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS fallback_responses (
                request_id TEXT PRIMARY KEY,
                device_id TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                answer TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )


def _cached_answer(identity: FallbackIdentity, request: FallbackAnswerRequest) -> str | None:
    with sqlite3.connect(_database_path()) as connection:
        row = connection.execute(
            "SELECT device_id, chat_id, answer FROM fallback_responses WHERE request_id = ?",
            (request.request_id,),
        ).fetchone()
    if row is None:
        return None
    if row[0] != identity.device_id or row[1] != request.chat_id:
        raise HTTPException(status_code=409, detail="Request ID is already used")
    return str(row[2])


def _save_answer(identity: FallbackIdentity, request: FallbackAnswerRequest, answer: str) -> str:
    with sqlite3.connect(_database_path()) as connection:
        connection.execute(
            "INSERT OR IGNORE INTO fallback_responses(request_id, device_id, chat_id, answer, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                request.request_id,
                identity.device_id,
                request.chat_id,
                answer,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        row = connection.execute(
            "SELECT device_id, chat_id, answer FROM fallback_responses WHERE request_id = ?",
            (request.request_id,),
        ).fetchone()
    if row is None or row[0] != identity.device_id or row[1] != request.chat_id:
        raise HTTPException(status_code=409, detail="Request ID is already used")
    return str(row[2])


def _identity(authorization: str | None) -> FallbackIdentity:
    if not settings.fallback_ticket_secret:
        raise HTTPException(status_code=503, detail="Fallback mode is not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Fallback ticket required")
    try:
        return verify_fallback_ticket(
            authorization.removeprefix("Bearer ").strip(),
            settings.fallback_ticket_secret.get_secret_value(),
        )
    except FallbackTicketError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@asynccontextmanager
async def lifespan(_: FastAPI):
    await asyncio.to_thread(_initialize_database)
    yield


app = FastAPI(title="WristMind fallback", version="1.0.0", lifespan=lifespan)


async def _deepseek_answer(messages: list[dict[str, str]]) -> str:
    if settings.mock_providers:
        question = next(item["content"] for item in reversed(messages) if item["role"] == "user")
        return f"Тестовый ответ WristMind: {question}"
    headers = {
        "Authorization": f"Bearer {settings.deepseek_api_key.get_secret_value()}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "deepseek-flash",
        "messages": messages,
        "temperature": 0.15,
        "stream": False,
        "thinking": {"type": "enabled"},
        "reasoning_effort": settings.deepseek_reasoning_effort,
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=10)) as client:
        response = await client.post(
            f"{settings.deepseek_base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json=payload,
        )
    if response.status_code >= 400:
        raise RuntimeError(f"DeepSeek HTTP {response.status_code}")
    return response.json()["choices"][0]["message"]["content"].strip()


@app.get("/fallback/health")
async def health() -> dict[str, str]:
    configured = bool(settings.fallback_ticket_secret and settings.deepseek_api_key)
    return {"status": "ok" if configured else "unconfigured", "mode": "fallback"}


async def _main_available() -> bool:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(2.0, connect=1.0), trust_env=False) as client:
            response = await client.get("http://127.0.0.1:18080/health")
        return response.status_code == 200 and response.json().get("status") == "ok"
    except (httpx.HTTPError, ValueError):
        return False


@app.get("/fallback/status")
async def server_status() -> dict[str, str]:
    main_up = await _main_available()
    fallback_ready = bool(settings.fallback_ticket_secret and settings.deepseek_api_key)
    return {
        "main": "up" if main_up else "down",
        "fallback": "ok" if fallback_ready else "unconfigured",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/fallback/v1/respond", response_model=FallbackAnswerResponse)
async def respond(
    request: FallbackAnswerRequest,
    authorization: str | None = Header(None),
) -> FallbackAnswerResponse:
    identity = _identity(authorization)
    cached = await asyncio.to_thread(_cached_answer, identity, request)
    if cached is not None:
        return FallbackAnswerResponse(request_id=request.request_id, answer=cached)
    if not settings.deepseek_api_key:
        raise HTTPException(status_code=503, detail="DeepSeek is not configured")

    system_parts = [settings.fallback_global_prompt]
    if request.system_prompt.strip():
        system_parts.append(request.system_prompt.strip())
    system_parts.append(
        "Сейчас работает резервный режим. Сохранённые источники, RAG и веб-поиск недоступны. "
        "Используй только системный промпт и переданную историю диалога. Не утверждай, что проверял интернет "
        "или использовал источники. Если без них нельзя ответить надёжно, прямо обозначь ограничение."
    )
    system_parts.append(CORE_IDENTITY_PROMPT)
    history = request.history[-settings.fallback_history_messages :]
    messages = [{"role": "system", "content": "\n\n".join(system_parts)}]
    messages.extend({"role": item.role, "content": item.content} for item in history)
    messages.append({"role": "user", "content": request.text})
    try:
        async with asyncio.timeout(90):
            answer = await _deepseek_answer(messages)
    except (httpx.HTTPError, RuntimeError, KeyError, IndexError, TimeoutError) as exc:
        raise HTTPException(status_code=502, detail="Fallback model is temporarily unavailable") from exc
    if not answer:
        raise HTTPException(status_code=502, detail="Fallback model returned an empty answer")
    answer = await asyncio.to_thread(_save_answer, identity, request, answer)
    return FallbackAnswerResponse(request_id=request.request_id, answer=answer)


if __name__ == "__main__":
    uvicorn.run("wristmind_server.fallback_app:app", host="127.0.0.1", port=18081)
