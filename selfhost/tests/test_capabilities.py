"""Feature switches, role isolation and portable speech in real isolated API."""
import asyncio
import io
import wave
from pathlib import Path
from unittest.mock import patch
import httpx
import pytest
import test_setup
from wristmind_server.resource_estimate import estimate, inspect_resources
from wristmind_server.model_capabilities import audio_text, embeddings, image_text
from wristmind_server.provider_connections import ProviderConnection
from wristmind_server.providers import ProviderError
from pydantic import SecretStr

import unittest
class TestCapabilityApi(unittest.TestCase):
    run_case = test_setup.SetupTest.run_case

    def test_models_roles_switches_and_device_contract(self):
        self.run_case('''
create()
configure()
assert client.get('/v1/capabilities').json()['speech_mode'] == 'system'
assert not client.get('/v1/capabilities').json()['vision']
p = client.post('/v1/providers', json={'kind':'groq'}).json()['provider']['id']
voice = client.post('/v1/models/installed', json={'provider_id':p,'model_id':'whisper','roles':['speech']})
assert voice.status_code == 200, voice.text
identity = voice.json()['id']
assert identity not in [m['id'] for m in client.get('/v1/models').json()]
assert client.get('/v1/capabilities').json()['speech_mode'] == 'buffered'
assert client.patch('/v1/models/installed/' + identity, json={'use_default':True}).status_code == 422
from uuid import uuid4
session_id = str(uuid4())
assert client.post('/v1/stt/stream', json={'action':'start','session_id':session_id}).status_code == 200
assert client.post('/v1/stt/stream', json={'action':'finish','session_id':session_id}).status_code == 200
features = {'web_search':False,'digitization':False,'rag':False,'voice':False}
assert client.put('/v1/selfhost/features', json=features).status_code == 200
assert client.get('/v1/capabilities').json()['speech_mode'] == 'system'
assert client.post('/v1/stt/stream', json={'action':'start','session_id':str(uuid4())}).status_code == 409
assert client.post('/v1/stt/stream', json={'action':'capabilities','session_id':str(uuid4())}).json()['selfhost']
assert client.put('/v1/selfhost/features',json={**features,'unknown':True}).status_code == 422
assert client.get('/v1/selfhost/features').json()['features']['voice']['enabled'] is False
from wristmind_server.selfhost_runtime import refresh_runtime
other = get_settings().model_copy(deep=True)
refresh_runtime(other)
assert other.selfhost_features == features
assert client.put('/v1/model-roles/vision', json={'identity':identity}).status_code == 422
assert client.put('/v1/model-roles/speech',json={'identity':''}).status_code == 200
assert not client.get('/v1/provider-settings').json()['model_roles'].get('speech')
''')

    def test_delete_provider_preserves_data_and_guards_active_model(self):
        self.run_case('''create(); identity = configure(); mode_id = mode()
registry = client.get('/v1/provider-settings').json()
active = registry['models'][0]['provider']
assert client.delete('/v1/providers/' + active).status_code == 409
p = client.post('/v1/providers', json={'kind':'groq'}).json()['provider']['id']
m = client.post('/v1/models/installed', json={'provider_id':p,'model_id':'whisper','roles':['speech']}).json()['id']
assert client.delete('/v1/providers/' + p).status_code == 200
registry = client.get('/v1/provider-settings').json()
assert p not in [row['id'] for row in registry['providers']]
assert m not in [row['id'] for row in registry['models']]
assert not registry['model_roles'].get('speech')
assert client.get('/v1/providers/' + p + '/catalog').status_code == 404
assert client.patch('/v1/providers/' + p, json={'enabled':True}).status_code == 404
assert registry['default_model_id'] == identity
assert any(row['id'] == mode_id for row in client.get('/v1/modes').json())
values = read_runtime(get_settings())
assert next(row for row in values['providers'] if row['id'] == p)['api_key'] == ''
''')

    def test_ocr_rag_guard_and_legacy_untouched(self):
        self.run_case('''
create(); configure()
client.put('/v1/selfhost/features',json={'web_search':False,'digitization':False,'rag':False,'voice':False})
from wristmind_server.knowledge import extract_document, knowledge_context
async def test():
    settings = get_settings()
    assert not (await knowledge_context(None, 'missing', 'query', None, settings))[0]
    try: await extract_document(Path('nonexistent'), 'image/png', 'OCR', None, settings)
    except ValueError as error: assert 'отключена' in str(error)
    else: raise AssertionError('OCR bypassed switch')
    from wristmind_server.feature_capabilities import enabled
    original = settings.model_copy(deep=True); original.selfhost_enabled = False
    assert enabled(original,'voice') and enabled(original,'rag')
asyncio.run(test())
''')


def test_resource_limits_and_advisory(tmp_path):
    proc = tmp_path / 'proc'; proc.mkdir()
    (proc/'meminfo').write_text('MemTotal: 16000000 kB\nMemAvailable: 8000000 kB\n')
    cgroup = tmp_path/'cgroup'; cgroup.mkdir()
    (cgroup/'cpu.max').write_text('100000 100000')
    (cgroup/'memory.max').write_text(str(2 * 2**30))
    (cgroup/'memory.current').write_text(str(2**30))
    result=inspect_resources(tmp_path,proc,cgroup)
    assert result['cpu'] <= 1 and result['ram_gib'] == 2 and result['available_gib'] == 1
    assert not result['recommendations']['web_search']
    assert estimate(4,8,4,20)['tier'] == 'comfortable'


def connection(kind='groq'):
    return ProviderConnection(id='p_123456789abc',kind=kind,label='Test',base_url='https://example.test/v1',api_key=SecretStr('test-key'))

@pytest.mark.asyncio
async def test_portable_audio_and_embedding_are_not_chat_requests():
    paths=[]
    def handler(request):
        paths.append(request.url.path)
        assert request.headers['authorization'] == 'Bearer test-key'
        if request.url.path.endswith('audio/transcriptions'):
            assert b'whisper' in request.content and b'RIFF' in request.content
            return httpx.Response(200,json={'text':'Привет'})
        return httpx.Response(200,json={'data':[{'index':0,'embedding':[1,2]}]})
    client=httpx.AsyncClient
    def factory(**kwargs): return client(transport=httpx.MockTransport(handler),**kwargs)
    stream=io.BytesIO()
    with wave.open(stream,'wb') as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000); wav.writeframes(bytes(3200))
    with patch('httpx.AsyncClient',factory):
        assert await audio_text(connection(),'whisper',stream.getvalue()) == 'Привет'
        assert await embeddings(connection(),'embedding',['hello']) == [[1,2]]
    assert paths == ['/v1/audio/transcriptions','/v1/embeddings']

@pytest.mark.asyncio
async def test_unsupported_provider_response_is_safe():
    client=httpx.AsyncClient
    def factory(**kwargs): return client(transport=httpx.MockTransport(lambda _: httpx.Response(404,text='private-key-do-not-show')),**kwargs)
    with patch('httpx.AsyncClient',factory):
        with pytest.raises(ProviderError) as error: await audio_text(connection(),'bad',b'audio')
    assert 'private-key' not in str(error.value)


@pytest.mark.asyncio
async def test_buffered_voice_consumes_pcm_without_speechkit(tmp_path):
    from wristmind_server.config import Settings
    from wristmind_server.selfhost_runtime import write_runtime, refresh_runtime
    from wristmind_server.speech_stream import Session, recognize
    settings = Settings(selfhost_enabled=True, storage_dir=tmp_path, mock_providers=False)
    provider = connection()
    identity = provider.id + ':whisper'
    write_runtime(settings, {'providers':[{**provider.model_dump(exclude={'api_key'}), 'api_key':'test-key'}],
                            'models':[{'id':identity,'provider':provider.id,'label':'Voice','roles':['speech'],'enabled':True}],
                            'model_roles':{'speech':identity}})
    refresh_runtime(settings)
    session = Session()
    await session.queue.put(bytes(3200)); await session.queue.put(None)
    client = httpx.AsyncClient
    def factory(**kwargs):
        return client(transport=httpx.MockTransport(lambda request: httpx.Response(200,json={'text':'Распознано'})), **kwargs)
    with patch('httpx.AsyncClient',factory): assert await recognize(session,settings) == 'Распознано'
    assert not settings.yandex_speechkit_api_key
