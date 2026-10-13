"""Real SQLite/API contracts, isolated from legacy API enrollment tests."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

PRELUDE = '''
import asyncio, json, os
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import select
from fastapi.testclient import TestClient
from wristmind_server.selfhost_app import app
from wristmind_server.config import get_settings
from wristmind_server.database import SessionFactory
from wristmind_server.db_models import Device, SelfHostAdmin, SelfHostWebSession, Mode, utcnow
from wristmind_server.selfhost_runtime import read_runtime, refresh_runtime
from wristmind_server.providers import ProviderError, ProviderRouter

client = TestClient(app)
client.__enter__()
client.headers['X-WristMind-CSRF'] = '1'
def create():
    response = client.post('/v1/selfhost/admin', headers={'X-WristMind-Setup':'test-activation'}, json={'login':'owner','password':'test-password-strong'})
    assert response.status_code == 201, response.text
    assert response.json()['token'] == ''
    return response

def configure():
    response = client.post('/v1/providers', json={'kind':'deepseek'})
    assert response.status_code == 200, response.text
    provider_id = response.json()['provider']['id']
    response = client.post('/v1/models/installed', json={'provider_id': provider_id, 'model_id':'demo-assistant','use_default':True})
    assert response.status_code == 200, response.text
    return response.json()['id']

def mode():
    response = client.post('/v1/selfhost/mode', json={'name':'Мой помощник','prompt':'Объясняй ясно.'})
    assert response.status_code == 200, response.text
    return response.json()['id']
'''

class SetupTest(unittest.TestCase):
    def run_case(self, script):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            env = {k: v for k, v in os.environ.items() if not k.startswith('WRISTMIND_')}
            env.update(PYTHONPATH=str(ROOT / 'server/src'), WRISTMIND_DATABASE_URL=f'sqlite+aiosqlite:///{runtime / "test.db"}',
                       WRISTMIND_STORAGE_DIR=str(runtime / 'private'), WRISTMIND_SELFHOST_ENABLED='true',
                       WRISTMIND_SELFHOST_SETUP_TOKEN='test-activation', WRISTMIND_BOOTSTRAP_SECRET='test-bootstrap',
                       WRISTMIND_TOKEN_PEPPER='test-pepper', WRISTMIND_MOCK_PROVIDERS='true',
                       WRISTMIND_WEB_DIST=str(ROOT / 'web/dist'), WRISTMIND_LATENCY_TRACE_ENABLED='false')
            result = subprocess.run([sys.executable, '-c', PRELUDE + script + '\nclient.__exit__(None,None,None)'],
                                    cwd=runtime, env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_activation_cookie_single_owner_and_validation_privacy(self):
        self.run_case('''
assert not client.get('/v1/selfhost/status').json()['admin_created']
assert client.post('/v1/devices/admin/enroll', headers={'X-WristMind-Bootstrap':'test-bootstrap'}, json={'name':'panel','kind':'WEB'}).status_code == 403
payload = {'login':'owner','password':'test-password-strong'}
assert client.post('/v1/selfhost/admin', json=payload).status_code == 403
invalid = client.post('/v1/selfhost/admin', headers={'X-WristMind-Setup':'test-activation'}, json={'login':'x','password':'secret'})
assert invalid.status_code == 422 and 'secret' not in invalid.text
response = create()
cookie = response.headers['set-cookie'].lower()
assert 'httponly' in cookie and 'samesite=strict' in cookie and 'max-age=2592000' in cookie
assert client.get('/v1/selfhost/session').status_code == 200
assert client.get('/v1/me').json()['is_admin']
assert client.post('/v1/selfhost/admin', headers={'X-WristMind-Setup':'test-activation'}, json=payload).status_code == 409
async def check():
    async with SessionFactory() as s:
        admin = await s.get(SelfHostAdmin, 1)
        assert admin.password_hash.startswith('scrypt-v1$') and 'test-password-strong' not in admin.password_hash
asyncio.run(check())
''')

    def test_login_logout_expiration_and_persistent_lockout(self):
        self.run_case('''
create()
assert client.post('/v1/selfhost/logout', json={}).status_code == 204
assert client.get('/v1/selfhost/session').status_code == 401
payload = {'login':'owner','password':'test-password-strong'}
for i in range(8):
    assert client.post('/v1/selfhost/login', json={**payload,'password':'wrong-password'}).status_code == 401
assert client.post('/v1/selfhost/login', json=payload).status_code == 429
async def unlock():
    async with SessionFactory() as s:
        admin = await s.get(SelfHostAdmin, 1)
        admin.locked_until = utcnow() - timedelta(seconds=1)
        await s.commit()
asyncio.run(unlock())
assert client.post('/v1/selfhost/login', json=payload).status_code == 200
cookie = client.cookies.get('wm_session')
assert client.post('/v1/selfhost/login', json=payload).status_code == 200
assert client.cookies.get('wm_session') != cookie
assert client.get('/v1/me', headers={'Authorization':'Bearer ' + cookie}).status_code == 401
async def expire():
    async with SessionFactory() as s:
        web = (await s.scalars(select(SelfHostWebSession).order_by(SelfHostWebSession.expires_at.desc()))).first()
        web.expires_at = utcnow() - timedelta(seconds=1)
        await s.commit()
asyncio.run(expire())
assert client.get('/v1/selfhost/session').status_code == 401
''')

    def test_browser_identity_reuses_device_after_logout_and_cookie_expiry(self):
        self.run_case("""
first = create().json()['deviceId']
browser = client.cookies.get('wm_browser')
assert browser and browser != client.cookies.get('wm_session')
payload = {'login':'owner','password':'test-password-strong'}
assert client.post('/v1/selfhost/login', json=payload).json()['deviceId'] == first
assert client.post('/v1/selfhost/logout', json={}).status_code == 204
assert client.get('/v1/me').status_code == 401
assert client.cookies.get('wm_browser') == browser
assert client.post('/v1/selfhost/login', json=payload).json()['deviceId'] == first
client.cookies.delete('wm_session')  # Browser has expired its authentication cookie.
assert client.get('/v1/me').status_code == 401  # Identity cookie cannot authenticate.
assert client.post('/v1/selfhost/login', json=payload).json()['deviceId'] == first
async def count():
    async with SessionFactory() as s:
        assert len((await s.scalars(select(Device))).all()) == 1
asyncio.run(count())
# A genuinely separate browser creates its own panel, even with the same user agent/IP.
client.cookies.clear()
second = client.post('/v1/selfhost/login', json=payload).json()['deviceId']
assert second != first
client.cookies.clear()
client.cookies.set('wm_browser', browser + 'tampered')
third = client.post('/v1/selfhost/login', json=payload).json()['deviceId']
assert third not in {first, second}
""")

    def test_active_session_renewal_and_old_browser_upgrade(self):
        self.run_case("""
first = create().json()['deviceId']
old_token = client.cookies.get('wm_session')
client.cookies.delete('wm_browser')
async def shorten():
    async with SessionFactory() as s:
        web = await s.get(SelfHostWebSession, first)
        web.expires_at = utcnow() + timedelta(hours=1)
        await s.commit()
asyncio.run(shorten())
response = client.get('/v1/selfhost/session')
assert response.status_code == 200 and response.json()['deviceId'] == first
assert 'max-age=2592000' in response.headers['set-cookie'].lower()
assert client.cookies.get('wm_session') == old_token
assert client.cookies.get('wm_browser')
async def verify():
    async with SessionFactory() as s:
        web = await s.get(SelfHostWebSession, first)
        assert web.expires_at.replace(tzinfo=__import__('datetime').timezone.utc) > utcnow() + timedelta(days=29)
asyncio.run(verify())
# Routine requests within the same day don't keep rewriting the cookie.
assert 'set-cookie' not in client.get('/v1/me').headers
""")

    def test_csrf_and_foreign_origin_fail_without_mutating(self):
        self.run_case('''
create()
client.headers.pop('X-WristMind-CSRF')
assert client.post('/v1/providers', json={'kind':'deepseek'}).status_code == 403
assert client.post('/v1/chats/quick', json={}).status_code == 403
client.headers['X-WristMind-CSRF'] = '1'
assert client.post('/v1/providers', json={'kind':'deepseek'}, headers={'Origin':'https://attacker.test'}).status_code == 403
assert not client.get('/v1/selfhost/wizard').json()['model_configured']
configure()
''')

    def test_full_wizard_resume_idempotent_mode_and_chat(self):
        self.run_case('''
create()
assert client.post('/v1/selfhost/complete', json={}).status_code == 409
assert client.post('/v1/selfhost/mode', json={'name':'Assistant'}).status_code == 409
configure()
mode_id = mode()
assert mode() == mode_id
state = client.get('/v1/selfhost/wizard').json()
assert state['mode_name'] == 'Мой помощник' and state['model_configured'] and not state['probe_passed']
result = client.post('/v1/selfhost/question', json={'text':'2 + 2?'})
assert result.status_code == 200 and result.json()['demo']
assert 'Тестовый ответ' in result.json()['answer']
assert client.post('/v1/selfhost/complete', json={}).status_code == 200
assert client.get('/v1/selfhost/status').json()['completed']
assert client.post('/v1/selfhost/complete', json={}).status_code == 200
chat = client.post('/v1/chats/quick', json={'client_request_id':'wizard-chat'})
assert chat.status_code == 201, chat.text
assert client.get('/v1/chats').json()[0]['id'] == chat.json()['id']
packet = client.post('/v1/chats/' + chat.json()['id'] + '/messages', json={'text':'Hello','client_request_id':'wizard-message'})
assert packet.status_code == 202, packet.text
async def run_worker():
    from wristmind_server.worker import process_next_job
    for _ in range(3):
        await process_next_job()
asyncio.run(run_worker())
job = client.get('/v1/jobs/' + packet.json()['id'])
assert job.status_code == 200 and job.json()['status'] == 'complete', job.text
assert any(m['role'] == 'assistant' and 'Тестовый ответ' in m['content'] for m in client.get('/v1/chats/' + chat.json()['id'] + '/messages').json())
assert client.get('/v1/selfhost/status').headers['cache-control'] == 'no-store'
''')

    def test_keys_encrypted_provider_errors_hidden_and_worker_reload(self):
        self.run_case('''
create()
settings = get_settings()
settings.mock_providers = False
assert client.post('/v1/providers', json={'kind':'deepseek'}).status_code == 422
async def discovery(*args, **kwargs):
    return [{'id':'manual-model','label':'Manual'}]
with patch('wristmind_server.provider_registry.discover_models', discovery):
    result = client.post('/v1/providers', json={'kind':'deepseek','api_key':'private-test-key'})
    assert result.status_code == 200, result.text
provider_id = result.json()['provider']['id']
async def broken(self, *args, **kwargs):
    raise ProviderError('private-test-key in provider body')
    yield ''
with patch.object(ProviderRouter, 'stream_answer', broken):
    result = client.post('/v1/models/installed', json={'provider_id':provider_id,'model_id':'manual-model'})
    assert result.status_code == 502 and 'private-test-key' not in result.text
assert not client.get('/v1/models').json()
async def working(self, model_id, messages, **kwargs):
    assert kwargs['thinking'] is False and kwargs['max_tokens'] == 256
    assert self.settings.provider_connections[0].api_key.get_secret_value() == 'private-test-key'
    yield 'ОК'
with patch.object(ProviderRouter, 'stream_answer', working):
    result = client.post('/v1/models/installed', json={'provider_id':provider_id,'model_id':'manual-model','use_default':True})
    assert result.status_code == 200, result.text
stored = settings.storage_dir / 'selfhost-settings.enc'
assert b'private-test-key' not in stored.read_bytes() and stored.stat().st_mode & 0o777 == 0o600
assert 'private-test-key' not in client.get('/v1/provider-settings').text
get_settings.cache_clear()
new = get_settings()
assert new.provider_connections[0].api_key.get_secret_value() == 'private-test-key'
assert new.quick_chat_model_id == new.router_model_id == new.title_model_id == provider_id + ':manual-model'
from wristmind_server.config import Settings
other = Settings()
refresh_runtime(other)
assert other.provider_connections[0].api_key.get_secret_value() == 'private-test-key'
''')

    def test_existing_bearer_device_and_speech_contract_remain_usable(self):
        self.run_case('''
create()
code = client.post('/v1/devices/pairing-codes', json={})
assert code.status_code in {200,201}, code.text
# Dictation requires an explicitly installed voice model; cookie auth still works.
p = client.post('/v1/providers', json={'kind':'groq'}).json()['provider']['id']
assert client.post('/v1/models/installed', json={'provider_id':p,'model_id':'demo-voice','roles':['speech']}).status_code == 200
from uuid import uuid4
session_id = str(uuid4())
response = client.post('/v1/stt/stream', json={'session_id':session_id,'action':'start'})
assert response.status_code == 200, response.text
assert client.post('/v1/stt/stream', json={'session_id':session_id,'action':'cancel'}).status_code == 200
''')

if __name__ == '__main__':
    unittest.main()
