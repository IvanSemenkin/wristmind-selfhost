"""Explicit model roles; catalog names never imply image/audio support."""
import asyncio
import base64
import io
import math
import wave
import httpx
from .provider_connections import ProviderConnection, headers, stream_connection
from .selfhost_runtime import read_runtime

ROLES = {'text', 'vision', 'speech', 'embedding'}

def selected(settings, role):
    values = read_runtime(settings)
    identity = values.get('model_roles', {}).get(role)
    if not identity: return None
    model = next((m for m in values.get('models', []) if m['id'] == identity and m.get('enabled', True) and role in m.get('roles', ['text'])), None)
    if not model: return None
    raw = next((p for p in values.get('providers', []) if p['id'] == model['provider'] and p.get('enabled', True)), None)
    if not raw: return None
    return ProviderConnection.model_validate(raw), identity.split(':', 1)[1]

async def image_text(connection, model, data, media_type):
    from .providers import ProviderError
    content = [{'type': 'text', 'text': 'Оцифруй источник в Markdown. Сохрани язык, формулы, таблицы и нумерацию. Ничего не решай.'},
               {'type': 'image_url', 'image_url': {'url': f'data:{media_type};base64,{base64.b64encode(data).decode()}'}}]
    try:
        async with asyncio.timeout(180):
            parts = [part async for part in stream_connection(connection, model, [{'role':'user','content':content}], thinking=False, max_tokens=4096)]
    except TimeoutError:
        raise ProviderError('Vision не ответил вовремя') from None
    text = ''.join(parts).strip()
    if not text: raise ProviderError('Vision вернул пустой результат')
    return text

async def request(connection, endpoint, **kwargs):
    from .providers import ProviderError
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(18 if endpoint == '/audio/transcriptions' else 120, connect=8), follow_redirects=False, trust_env=False) as client:
            response = await client.post(connection.base_url + endpoint, headers=headers(connection), **kwargs)
        if response.status_code >= 300: raise ProviderError(f'Сервис отклонил запрос (HTTP {response.status_code}). Проверьте назначение модели, ключ и баланс.')
        return response.json()
    except (httpx.HTTPError, ValueError):
        raise ProviderError('Сервис недоступен или вернул некорректный ответ') from None

async def embeddings(connection, model, texts):
    from .providers import ProviderError
    body = await request(connection, '/embeddings', json={'model':model, 'input':texts})
    try:
        rows = sorted(body['data'], key=lambda row: row['index'])
        vectors = [row['embedding'] for row in rows]
        assert len(vectors) == len(texts) and [row['index'] for row in rows] == list(range(len(texts)))
        assert vectors and 0 < len(vectors[0]) <= 16384
        assert all(len(v) == len(vectors[0]) and all(isinstance(n, (int,float)) and math.isfinite(n) for n in v) for v in vectors)
        return vectors
    except (KeyError, TypeError, AssertionError): raise ProviderError('Некорректные embeddings') from None

async def audio_text(connection, model, data, media_type='audio/wav'):
    from .providers import ProviderError
    if connection.kind == 'yandex':
        raise ProviderError('SpeechKit принимает PCM через потоковую диктовку')
    body = await request(connection, '/audio/transcriptions', data={'model':model,'language':'ru'}, files={'file':('recording.wav',data,media_type)})
    if not isinstance(body, dict): raise ProviderError('Некорректный ответ распознавания')
    text = body.get('text') or body.get('transcript') or ''
    if not isinstance(text, str): raise ProviderError('Некорректный ответ распознавания')
    return text.strip()

async def pcm_text(settings, pcm):
    from .providers import ProviderError
    item = selected(settings, 'speech')
    if not item: raise ProviderError('Добавьте модель распознавания голоса в настройках')
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000); wav.writeframes(pcm)
    return await audio_text(*item, stream.getvalue())

async def probe_role(settings, item, model, role):
    from .providers import ProviderError
    if settings.mock_providers: return
    if role == 'vision':
        # Tiny generated PNG, no user image leaves the server during the probe.
        from PIL import Image, ImageDraw
        output = io.BytesIO(); image = Image.new('RGB', (120, 60), 'white'); ImageDraw.Draw(image).text((12,20),'OK 2',fill='black'); image.save(output, 'PNG')
        await image_text(item, model, output.getvalue(), 'image/png')
    elif role == 'embedding': await embeddings(item, model, ['Проверка подключения'])
    elif role == 'speech':
        if item.kind == 'yandex':
            # REST validates the key; streaming uses the same SpeechKit credential.
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(18, connect=8), follow_redirects=False, trust_env=False) as client:
                    response = await client.post('https://stt.api.cloud.yandex.net/speech/v1/stt:recognize', headers={'Authorization': f'Api-Key {item.api_key.get_secret_value()}'}, params={'lang':'ru-RU','format':'lpcm','sampleRateHertz':'16000'}, content=bytes(16000))
                if response.status_code >= 400 or not isinstance(response.json(), dict):
                    raise ProviderError('SpeechKit не принял запрос. Проверьте ключ, права и баланс.')
            except (httpx.HTTPError, ValueError):
                raise ProviderError('SpeechKit временно недоступен или вернул некорректный ответ') from None
        else:
            stream = io.BytesIO()
            with wave.open(stream, 'wb') as wav:
                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000); wav.writeframes(bytes(16000))
            await audio_text(item, model, stream.getvalue())
