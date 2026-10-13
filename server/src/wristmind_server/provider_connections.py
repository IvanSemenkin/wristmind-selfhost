"""Provider presets, catalog discovery and text-stream adapters for added models."""
import json
from . import search_trace
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field, SecretStr

PRESETS = [
    {'id': 'yandex', 'label': 'Yandex · SpeechKit', 'url': 'https://stt.api.cloud.yandex.net', 'protocol': 'speechkit'},
    {'id': 'openai', 'label': 'OpenAI · GPT', 'url': 'https://api.openai.com/v1', 'protocol': 'openai'},
    {'id': 'anthropic', 'label': 'Anthropic · Claude', 'url': 'https://api.anthropic.com/v1', 'protocol': 'anthropic'},
    {'id': 'deepseek', 'label': 'DeepSeek', 'url': 'https://api.deepseek.com', 'protocol': 'openai'},
    {'id': 'openrouter', 'label': 'OpenRouter', 'url': 'https://openrouter.ai/api/v1', 'protocol': 'openai'},
    {'id': 'gemini', 'label': 'Google · Gemini', 'url': 'https://generativelanguage.googleapis.com/v1beta/openai', 'protocol': 'openai'},
    {'id': 'groq', 'label': 'Groq', 'url': 'https://api.groq.com/openai/v1', 'protocol': 'openai'},
    {'id': 'mistral', 'label': 'Mistral AI', 'url': 'https://api.mistral.ai/v1', 'protocol': 'openai'},
    {'id': 'xai', 'label': 'xAI · Grok', 'url': 'https://api.x.ai/v1', 'protocol': 'openai'},
    {'id': 'together', 'label': 'Together AI', 'url': 'https://api.together.xyz/v1', 'protocol': 'openai'},
    {'id': 'compatible', 'label': 'OpenAI-совместимый · свой URL', 'url': '', 'protocol': 'openai'},
]
PRESET_MAP = {p['id']: p for p in PRESETS}


class ProviderConnection(BaseModel):
    id: str = Field(pattern=r'^(?:p_[0-9a-f]{12}|openrouter|deepseek|gigachat)$')
    kind: str
    label: str = Field(min_length=1, max_length=80)
    base_url: str = Field(max_length=300)
    api_key: SecretStr = SecretStr('')
    enabled: bool = True
    allow_local: bool = False


def safe_url(value, allow_local=False):
    parsed = urlsplit(value.strip())
    try:
        parsed.port
    except ValueError:
        raise ValueError('Некорректный порт URL') from None
    if parsed.scheme not in {'https', 'http'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Укажите адрес API без ключа, логина, параметров и фрагмента')
    if parsed.scheme == 'http' and not allow_local:
        raise ValueError('Для HTTP включите разрешение локального подключения')
    if any(p in {'.', '..'} for p in parsed.path.split('/')):
        raise ValueError('Некорректный путь API')
    return value.strip().rstrip('/')


def headers(connection):
    key = connection.api_key.get_secret_value()
    if connection.kind == 'anthropic':
        return {'x-api-key': key, 'anthropic-version': '2023-06-01'}
    return {'Authorization': f'Bearer {key}'} if key else {}


def public_connection(connection):
    return {'id': connection.id, 'kind': connection.kind, 'label': connection.label, 'base_url': connection.base_url,
            'enabled': connection.enabled, 'allow_local': connection.allow_local,
            'has_key': bool(connection.api_key.get_secret_value())}


class CatalogError(Exception):
    def __init__(self, message, authentication=False, manual_allowed=False):
        super().__init__(message)
        self.authentication = authentication
        self.manual_allowed = manual_allowed


async def discover_models(connection, demo=False):
    if connection.kind == 'yandex':
        return [{'id': 'general', 'label': 'SpeechKit · русский голос'}]
    if demo:
        return [{'id': 'demo-assistant', 'label': 'Тестовая модель (без платных запросов)'}]
    result = []
    cursor = None
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False, trust_env=False) as client:
            for _ in range(10):
                params = {'after_id': cursor, 'limit': 1000} if cursor else None
                async with client.stream('GET', connection.base_url + '/models', headers=headers(connection), params=params) as response:
                    if response.status_code in {401, 403}:
                        raise CatalogError('Ключ отклонён провайдером. Проверьте ключ и доступ.', authentication=True)
                    if response.status_code in {404, 405}:
                        raise CatalogError('Провайдер не отдаёт список моделей. Укажите ID вручную.', manual_allowed=True)
                    if response.status_code >= 300:
                        raise CatalogError('Каталог провайдера недоступен. Повторите или укажите ID вручную.', manual_allowed=True)
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 8_000_000:
                            raise CatalogError('Список моделей слишком большой. Укажите ID вручную.', manual_allowed=True)
                    data = json.loads(raw)
                rows = data.get('data', [])
                if not isinstance(rows, list):
                    raise CatalogError('Неподдерживаемый каталог. Укажите ID вручную.', manual_allowed=True)
                for item in rows:
                    if not isinstance(item, dict):
                        continue
                    identity = item.get('id')
                    if isinstance(identity, str) and 0 < len(identity) <= 120 and not any(c.isspace() for c in identity):
                        result.append({'id': identity, 'label': str(item.get('name') or item.get('display_name') or identity)[:160]})
                if not data.get('has_more') or not data.get('last_id') or data['last_id'] == cursor:
                    break
                cursor = data['last_id']
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise CatalogError('Не удалось получить список моделей. Повторите или введите ID вручную.', manual_allowed=True) from None
    return sorted({item['id']: item for item in result}.values(), key=lambda v: v['label'].casefold())[:5000]


async def stream_connection(connection, model, messages, *, max_tokens=None, timing=None, thinking=True, reasoning_effort="low"):
    """Native Anthropic SSE or the existing OpenAI-shaped chat stream protocol."""
    from .providers import ProviderError, StreamTiming, _mark_provider_timing
    import time
    timing = timing or StreamTiming()
    native = connection.kind == 'anthropic'
    if native:
        system = '\n'.join(str(m['content']) for m in messages if m['role'] == 'system')
        conversation = [dict(m) for m in messages if m['role'] in {'user', 'assistant'}]
        for message in conversation:
            if isinstance(message['content'], list):
                converted = []
                for block in message['content']:
                    if block['type'] == 'image_url':
                        prefix, data = block['image_url']['url'].split(',', 1)
                        converted.append({'type':'image', 'source':{'type':'base64', 'media_type':prefix[5:].split(';')[0], 'data':data}})
                    else: converted.append(block)
                message['content'] = converted
        if not conversation:
            conversation = [{'role': 'user', 'content': system or 'Ответь ОК'}]
            system = ''
        payload = {'model': model, 'messages': conversation, 'max_tokens': max_tokens or 4096, 'stream': True}
        if system:
            payload['system'] = system
        path = '/messages'
    else:
        payload = {'model': model, 'messages': messages, 'stream': True}
        if max_tokens is not None:
            payload['max_completion_tokens' if connection.kind == 'openai' else 'max_tokens'] = max_tokens
        if connection.kind == 'deepseek':
            payload['thinking'] = {'type': 'enabled' if thinking else 'disabled'}
            if thinking: payload['reasoning_effort'] = reasoning_effort
        path = '/chat/completions'
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(45, connect=10), follow_redirects=False, trust_env=False) as client:
            timing.request_started_at = time.perf_counter(); _mark_provider_timing('request', timing)
            async with client.stream('POST', connection.base_url + path, headers=headers(connection), json=payload) as response:
                timing.headers_at = time.perf_counter(); _mark_provider_timing('headers', timing)
                if response.status_code >= 300:
                    raise ProviderError(f'Провайдер отклонил запрос (HTTP {response.status_code}). Проверьте ключ, ID модели и баланс.')
                async for line in response.aiter_lines():
                    if not line.startswith('data:'):
                        continue
                    data = line[5:].strip()
                    if not data or data == '[DONE]':
                        continue
                    try:
                        event = json.loads(data)
                        search_trace.usage(event.get("usage"))
                        if isinstance(event.get("message"), dict):
                            search_trace.usage(event["message"].get("usage"))
                        if event.get('type') == 'error' or event.get('error'):
                            raise ProviderError('Провайдер прервал ответ. Повторите запрос.')
                        if native:
                            delta = event.get('delta', {})
                            chunk = delta.get('text') if event.get('type') == 'content_block_delta' and delta.get('type') == 'text_delta' else None
                        else:
                            chunk = event['choices'][0]['delta'].get('content')
                    except (ValueError, KeyError, IndexError, TypeError):
                        continue
                    if isinstance(chunk, str) and chunk:
                        if timing.first_chunk_at is None:
                            timing.first_chunk_at = time.perf_counter(); _mark_provider_timing('first_chunk', timing)
                        yield chunk
    except httpx.HTTPError as error:
        raise ProviderError('Не удалось получить ответ от провайдера. Проверьте соединение и URL.') from error
