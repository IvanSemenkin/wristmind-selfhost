import asyncio
from unittest.mock import patch
import httpx
import pytest
from fastapi import HTTPException
from pydantic import SecretStr
from wristmind_server.config import Settings, get_settings, ModelOption
from wristmind_server.main import app
from wristmind_server.provider_connections import CatalogError, ProviderConnection, discover_models, stream_connection
from wristmind_server.providers import ProviderError, ProviderRouter
from wristmind_server.selfhost_runtime import refresh_runtime

@pytest.fixture
def registry(client, admin_headers, tmp_path):
    settings = get_settings().model_copy(deep=True)
    settings.storage_dir = tmp_path / 'private'
    settings.openrouter_api_key = SecretStr('test-openrouter-key')
    settings.deepseek_api_key = SecretStr('test-deepseek-key')
    settings.gigachat_credentials = SecretStr('test-giga-key')
    app.dependency_overrides[get_settings] = lambda: settings
    yield client, admin_headers, settings
    app.dependency_overrides.pop(get_settings, None)


def add(client, headers, kind='openai'):
    response = client.post('/v1/providers', headers=headers, json={'kind':kind})
    assert response.status_code == 200, response.text
    return response.json()['provider']['id']


def install(client, headers, provider, identity='manual-model', **fields):
    return client.post('/v1/models/installed', headers=headers, json={'provider_id':provider,'model_id':identity, **fields})


def test_catalog_is_separate_from_added_models_and_legacy_ids_preserved(registry):
    client, headers, settings = registry
    before = client.get('/v1/models', headers=headers).json()
    provider = add(client, headers)
    assert client.get('/v1/models', headers=headers).json() == before
    catalog = client.get(f'/v1/providers/{provider}/catalog', headers=headers).json()
    assert catalog['models'][0]['id'] == 'demo-assistant'
    assert not client.get(f'/v1/providers/{provider}/catalog?query=missing', headers=headers).json()['models']
    response = install(client, headers, provider)
    assert response.status_code == 200, response.text
    identity = response.json()['id']
    assert identity == provider + ':manual-model'
    assert len(client.get('/v1/models', headers=headers).json()) == len(before) + 1
    assert install(client, headers, provider).json()['id'] == identity
    assert len(client.get('/v1/models', headers=headers).json()) == len(before) + 1
    other = settings.model_copy(deep=True); other.provider_connections = []
    refresh_runtime(other)
    assert other.model_option(identity)


def test_default_and_modes_protected_from_disabling(registry):
    client, headers, settings = registry
    provider = add(client, headers)
    identity = install(client, headers, provider, use_default=True).json()['id']
    assert client.patch('/v1/models/installed/' + identity, headers=headers, json={'enabled':False}).status_code == 409
    assert client.patch('/v1/providers/' + provider, headers=headers, json={'enabled':False}).status_code == 409
    assert client.get('/v1/settings', headers=headers).json()['default_model_id'] == identity
    alternate = install(client, headers, provider, 'second-model', use_default=True).json()['id']
    mode = client.post('/v1/modes', headers=headers, json={'name':'Provider test','system_prompt':'Help','response_model_id':identity})
    assert mode.status_code == 201, mode.text
    assert client.patch('/v1/models/installed/' + identity, headers=headers, json={'enabled':False}).status_code == 409
    # No references: a third model can be disabled and re-enabled without erasing it.
    third = install(client, headers, provider, 'third-model').json()['id']
    assert client.patch('/v1/models/installed/' + third, headers=headers, json={'enabled':False}).status_code == 200
    assert not any(m['id'] == third for m in client.get('/v1/models', headers=headers).json())
    assert any(m['id'] == third for m in client.get('/v1/provider-settings', headers=headers).json()['models'])
    assert client.patch('/v1/models/installed/' + third, headers=headers, json={'enabled':True}).status_code == 200
    assert settings.default_model_id == alternate


def test_keys_validation_probe_and_encryption(registry):
    client, headers, settings = registry
    settings.mock_providers = False
    async def discovery(*args): return [{'id':'manual-model','label':'Manual'}]
    async def answer(self, *args, **kwargs):
        assert self.settings.provider_connections[-1].api_key.get_secret_value() == 'private-test-key'
        assert kwargs['max_tokens'] == 256
        yield 'OK'
    assert client.post('/v1/providers', headers=headers, json={'kind':'openai','api_key':'x' * 1001}).status_code == 422
    assert 'x' * 1001 not in client.post('/v1/providers', headers=headers, json={'kind':'openai','api_key':'x' * 1001}).text
    with patch('wristmind_server.provider_registry.discover_models', discovery):
        response = client.post('/v1/providers', headers=headers, json={'kind':'openai','api_key':'private-test-key'})
    assert response.status_code == 200, response.text
    provider = response.json()['provider']['id']
    with patch.object(ProviderRouter, 'stream_answer', answer):
        assert install(client, headers, provider).status_code == 200
    public = client.get('/v1/provider-settings', headers=headers)
    assert 'private-test-key' not in public.text and public.headers['cache-control'] == 'no-store'
    path = settings.storage_dir / 'selfhost-settings.enc'
    assert b'private-test-key' not in path.read_bytes() and path.stat().st_mode & 0o777 == 0o600
    async def rejected(self, *args, **kwargs):
        raise ProviderError('private-test-key in response')
        yield ''
    with patch.object(ProviderRouter, 'stream_answer', rejected):
        result = install(client, headers, provider, 'bad-model')
        assert result.status_code == 502 and 'private-test-key' not in result.text
    assert not settings.model_option(provider + ':bad-model')


def test_custom_url_and_auth_boundaries(registry):
    client, headers, settings = registry
    assert client.get('/v1/provider-settings').status_code == 401
    for url in ['https://name:key@example.com/v1','https://example.com/v1?key=secret','http://localhost:11434/v1']:
        assert client.post('/v1/providers', headers=headers, json={'kind':'compatible','base_url':url}).status_code == 422
    response = client.post('/v1/providers', headers=headers, json={'kind':'compatible','base_url':'http://localhost:11434/v1','allow_local':True})
    assert response.status_code == 200, response.text
    provider = response.json()['provider']['id']
    identity = install(client, headers, provider).json()['id']
    assert client.patch('/v1/providers/' + provider, headers=headers, json={'enabled':False}).status_code == 200
    assert not settings.model_option(identity)
    async def collect():
        with pytest.raises(ProviderError):
            async for _ in ProviderRouter(settings).stream_answer(identity, [{'role':'user','content':'x'}]): pass
    asyncio.run(collect())


@pytest.mark.parametrize('kind', ['openai', 'anthropic', 'deepseek', 'gemini'])
def test_registered_adapter_protocols_and_stream(kind):
    conn = ProviderConnection(id='p_123456abcdef', kind=kind, label='Test', base_url='https://provider.test/v1', api_key=SecretStr('test-key'))
    original = httpx.AsyncClient
    def respond(request):
        import json
        payload = json.loads(request.content)
        assert payload['model'] == 'manual-model' and payload['stream']
        if kind == 'anthropic':
            assert request.url.path == '/v1/messages' and request.headers['x-api-key'] == 'test-key'
            assert payload['system'] == 'Help' and payload['max_tokens'] == 256
            stream = 'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"OK"}}\n\n'
        else:
            assert request.url.path == '/v1/chat/completions' and request.headers['authorization'] == 'Bearer test-key'
            assert payload['max_completion_tokens' if kind == 'openai' else 'max_tokens'] == 256
            if kind == 'deepseek': assert payload['thinking'] == {'type':'disabled'}
            stream = 'data: {"choices":[{"delta":{"content":"OK"}}]}\n\ndata: [DONE]\n\n'
        return httpx.Response(200, text=stream)
    def fake_client(**kwargs): return original(transport=httpx.MockTransport(respond), **kwargs)
    async def collect():
        settings = Settings(mock_providers=False, provider_connections=[conn], allowed_models=[ModelOption(id=conn.id + ':' + 'manual-model', label='Test', provider=conn.id)])
        return ''.join([part async for part in ProviderRouter(settings).stream_answer(conn.id + ':manual-model', [{'role':'system','content':'Help'},{'role':'user','content':'Question'}], thinking=False, max_tokens=256)])
    with patch('wristmind_server.provider_connections.httpx.AsyncClient', fake_client):
        assert asyncio.run(collect()) == 'OK'


def test_anthropic_catalog_pagination_and_safe_auth_error():
    conn = ProviderConnection(id='p_123456abcdef', kind='anthropic', label='Test', base_url='https://provider.test/v1', api_key=SecretStr('test-key'))
    original = httpx.AsyncClient
    seen = []
    def respond(request):
        seen.append(request)
        return httpx.Response(200, json={'data':[{'id':'model-a' if len(seen) == 1 else 'model-b'}], 'has_more':len(seen)==1, 'last_id':'model-a'})
    with patch('wristmind_server.provider_connections.httpx.AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs)):
        assert len(asyncio.run(discover_models(conn))) == 2
    assert seen[1].url.params['after_id'] == 'model-a'
    with patch('wristmind_server.provider_connections.httpx.AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(lambda request: httpx.Response(401,text='test-key')), **kwargs)):
        with pytest.raises(CatalogError) as caught: asyncio.run(discover_models(conn))
        assert caught.value.authentication and 'test-key' not in str(caught.value)


def test_openrouter_reuses_existing_tls_adapter():
    conn = ProviderConnection(id='p_123456abcdef', kind='openrouter', label='Test', base_url='https://openrouter.ai/api/v1', api_key=SecretStr('test-key'))
    router = ProviderRouter(Settings(mock_providers=False, provider_connections=[conn], allowed_models=[ModelOption(id=conn.id + ':vendor/model', label='Test', provider=conn.id)]))
    async def stream(url, headers, model, messages, **kwargs):
        assert url == conn.base_url + '/chat/completions' and headers['Authorization'] == 'Bearer test-key'
        assert model == 'vendor/model' and kwargs['max_tokens'] == 256
        yield 'OK'
    router._stream_openrouter = stream
    async def collect(): return ''.join([s async for s in router.stream_answer(conn.id + ':vendor/model', [{'role':'user','content':'Hi'}], max_tokens=256)])
    assert asyncio.run(collect()) == 'OK'


def test_standard_default_selector_updates_registered_runtime(registry):
    client, headers, settings = registry
    provider = add(client, headers)
    first = install(client, headers, provider, 'first', use_default=True).json()['id']
    second = install(client, headers, provider, 'second').json()['id']
    response = client.put('/v1/settings', headers=headers, json={'default_model_id':second})
    assert response.status_code == 200, response.text
    assert settings.default_model_id == settings.router_model_id == settings.title_model_id == settings.quick_chat_model_id == second
    assert client.patch('/v1/models/installed/' + first, headers=headers, json={'enabled':False}).status_code == 200
    async def collect():
        with pytest.raises(ProviderError):
            async for _ in ProviderRouter(settings).stream_answer(first, [{'role':'user','content':'x'}]): pass
    asyncio.run(collect())
