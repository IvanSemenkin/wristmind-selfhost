"""Short authenticated Wear dictation sessions; audio stays in bounded memory."""
from __future__ import annotations

import asyncio
import base64
import binascii
import zlib
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

import grpc
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from yandex.cloud.ai.stt.v3 import stt_pb2 as stt, stt_service_pb2_grpc as service

from .config import Settings, get_settings
from .db_models import Device
from .security import current_device

router = APIRouter()


class SpeechRequest(BaseModel):
    session_id: UUID
    action: Literal['start', 'chunk', 'finish', 'cancel', 'capabilities']
    seq: int = Field(default=0, ge=0, le=300)
    data: str = Field(default='', max_length=86_000)
    encoding: Literal['pcm', 'pcm_zlib'] = 'pcm'


@dataclass
class Session:
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=32))
    task: asyncio.Task | None = None
    seq: int = 0
    audio_bytes: int = 0
    finishing: bool = False
    cancelled: bool = False


_sessions: dict[tuple[str, str], Session] = {}


async def recognize(session: Session, settings: Settings) -> str:
    if settings.mock_providers:
        while await session.queue.get() is not None:
            pass
        return 'Тестовая расшифровка WristMind'
    if settings.selfhost_enabled and not settings.yandex_speechkit_api_key:
        from .model_capabilities import pcm_text
        from .providers import ProviderError
        audio = bytearray()
        while True:
            chunk = await session.queue.get()
            if chunk is None: break
            audio.extend(chunk)
        try: return await pcm_text(settings, bytes(audio))
        except ProviderError as error: raise HTTPException(502, str(error)) from None
    key = settings.yandex_speechkit_api_key
    if not key:
        raise HTTPException(503, 'SpeechKit не настроен')

    async def requests():
        yield stt.StreamingRequest(session_options=stt.StreamingOptions(
            recognition_model=stt.RecognitionModelOptions(
                audio_format=stt.AudioFormatOptions(raw_audio=stt.RawAudio(
                    audio_encoding=stt.RawAudio.LINEAR16_PCM,
                    sample_rate_hertz=16000, audio_channel_count=1)),
                text_normalization=stt.TextNormalizationOptions(
                    text_normalization=stt.TextNormalizationOptions.TEXT_NORMALIZATION_ENABLED,
                    profanity_filter=False, literature_text=True),
                language_restriction=stt.LanguageRestrictionOptions(
                    restriction_type=stt.LanguageRestrictionOptions.WHITELIST,
                    language_code=['ru-RU']),
                audio_processing_type=stt.RecognitionModelOptions.REAL_TIME)))
        while True:
            try:
                audio = await asyncio.wait_for(session.queue.get(), 2)
            except TimeoutError:
                # Keep the provider session alive while a waking/weak watch link catches up.
                yield stt.StreamingRequest(silence_chunk=stt.SilenceChunk(duration_ms=100))
                continue
            if audio is None:
                return
            yield stt.StreamingRequest(chunk=stt.AudioChunk(data=audio))

    finals: dict[int, str] = {}
    partial = ''
    async with grpc.aio.secure_channel('stt.api.cloud.yandex.net:443', grpc.ssl_channel_credentials()) as channel:
        call = service.RecognizerStub(channel).RecognizeStreaming(
            requests(), metadata=(('authorization', f'Api-Key {key.get_secret_value()}'),), timeout=115)
        try:
            async for event in call:
                kind = event.WhichOneof('Event')
                if kind == 'partial' and event.partial.alternatives:
                    partial = event.partial.alternatives[0].text
                elif kind == 'final' and event.final.alternatives:
                    finals[len(finals)] = event.final.alternatives[0].text
                    partial = ''
                elif kind == 'final_refinement' and event.final_refinement.normalized_text.alternatives:
                    finals[int(event.final_refinement.final_index)] = event.final_refinement.normalized_text.alternatives[0].text
            return ' '.join([finals[index] for index in sorted(finals)] + ([partial] if partial else [])).strip()
        except grpc.aio.AioRpcError as error:
            raise HTTPException(502, 'Сервис распознавания временно недоступен') from error
        finally:
            call.cancel()


def expire(key: tuple[str, str], session: Session) -> None:
    if _sessions.get(key) is session:
        _sessions.pop(key)
        if session.task and not session.task.done():
            session.task.cancel()
        while not session.queue.empty():
            session.queue.get_nowait()


@router.post('/v1/stt/stream')
async def speech_stream(
    body: SpeechRequest,
    device: Device = Depends(current_device),
    settings: Settings = Depends(get_settings),
) -> dict:
    if body.action == 'capabilities':
        from .feature_capabilities import capabilities
        from .selfhost_runtime import refresh_runtime
        refresh_runtime(settings)
        return capabilities(settings)
    # The companion may carry the request with the paired user's other device token.
    key = (str(device.user_id or device.id), str(body.session_id))
    session = _sessions.get(key)
    if body.action == 'start':
        from .feature_capabilities import require
        from .selfhost_runtime import refresh_runtime
        refresh_runtime(settings)
        require(settings, 'voice')
        if session is None:
            if not settings.selfhost_enabled and not settings.mock_providers and not settings.yandex_speechkit_api_key:
                raise HTTPException(503, 'SpeechKit не настроен')
            active = [s for (owner, _), s in _sessions.items() if owner == key[0] and s.task and not s.task.done()]
            if len(active) >= 2 or len(_sessions) >= 64:
                raise HTTPException(429, 'Слишком много записей')
            session = Session()
            _sessions[key] = session
            session.task = asyncio.create_task(recognize(session, settings))
            # Retrieve failures even when a watch disconnects without a finish request.
            session.task.add_done_callback(lambda task: None if task.cancelled() else task.exception())
            asyncio.get_running_loop().call_later(120, expire, key, session)
        if session.cancelled:
            raise HTTPException(409, 'Запись отменена')
        return {'status': 'ready', 'seq': session.seq}
    if body.action == 'cancel':
        if session:
            session.cancelled = True
            if session.task:
                session.task.cancel()
            while not session.queue.empty():
                session.queue.get_nowait()
        return {'status': 'cancelled'}
    if session is None:
        raise HTTPException(404, 'Запись завершена. Начните заново')
    if session.cancelled:
        raise HTTPException(409, 'Запись отменена')
    if body.action == 'chunk':
        if body.seq < session.seq:
            return {'status': 'accepted', 'seq': session.seq}
        if body.seq != session.seq or session.finishing:
            raise HTTPException(409, 'Нарушен порядок аудиофрагментов')
        try:
            audio = base64.b64decode(body.data, validate=True)
            if body.encoding == 'pcm_zlib':
                decoder = zlib.decompressobj()
                audio = decoder.decompress(audio, 64_001)
                if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                    raise ValueError('Invalid or oversized compressed audio')
        except (ValueError, binascii.Error, zlib.error) as error:
            raise HTTPException(422, 'Некорректный аудиофрагмент') from error
        if not audio or len(audio) % 2 or len(audio) > 64_000:
            raise HTTPException(422, 'Некорректный аудиофрагмент')
        if session.audio_bytes + len(audio) > 960_000:
            raise HTTPException(413, 'Запись должна быть не длиннее 30 секунд')
        if session.task.done():
            await session.task
            raise HTTPException(409, 'Распознавание уже завершено')
        try:
            session.queue.put_nowait(audio)
        except asyncio.QueueFull as error:
            raise HTTPException(429, 'Распознавание не успевает за записью') from error
        session.seq += 1
        session.audio_bytes += len(audio)
        return {'status': 'accepted', 'seq': session.seq}
    if not session.finishing:
        session.finishing = True
        try:
            await asyncio.wait_for(session.queue.put(None), 5)
        except TimeoutError as error:
            raise HTTPException(504, 'Сервис распознавания не отвечает') from error
    try:
        text = await asyncio.wait_for(asyncio.shield(session.task), 20)
    except TimeoutError as error:
        raise HTTPException(504, 'Сервис распознавания не отвечает') from error
    return {'status': 'complete', 'text': text}
