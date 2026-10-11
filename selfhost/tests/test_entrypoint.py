"""Smoke test the real self-hosting application in a disposable SQLite install."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

class EntrypointTest(unittest.TestCase):
    def test_actual_api_lifespan_and_built_panel_share_the_origin(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            env = {key: value for key, value in os.environ.items() if not key.startswith('WRISTMIND_')}
            env.update({
                'PYTHONPATH': str(ROOT / 'server/src'),
                'WRISTMIND_DATABASE_URL': f'sqlite+aiosqlite:///{runtime / "test.db"}',
                'WRISTMIND_STORAGE_DIR': str(runtime / 'private'),
                'WRISTMIND_BOOTSTRAP_SECRET': 'test-only-bootstrap',
                'WRISTMIND_TOKEN_PEPPER': 'test-only-pepper',
                'WRISTMIND_MOCK_PROVIDERS': 'true',
                'WRISTMIND_SELFHOST_SETUP_TOKEN': 'test-only-activation',
                'WRISTMIND_LATENCY_TRACE_ENABLED': 'false',
                'WRISTMIND_WEB_DIST': str(ROOT / 'web/dist'),
            })
            script = '''
from fastapi.testclient import TestClient
from wristmind_server.selfhost_app import app
with TestClient(app) as client:
    assert client.get('/health').json()['status'] == 'ok'
    assert client.get('/talk').status_code == 200
    assert client.get('/v1/nonexistent').status_code == 404
    assert client.get('/v1/chats').status_code == 401
    client.headers['X-WristMind-CSRF'] = '1'
    enrolled = client.post('/v1/selfhost/admin', headers={'X-WristMind-Setup':'test-only-activation'}, json={'login':'owner','password':'test-only-password-strong'})
    assert enrolled.status_code == 201, enrolled.text
    headers = {'X-WristMind-CSRF':'1'}
    provider = client.post('/v1/providers', headers=headers, json={'kind':'openai'}).json()['provider']['id']
    installed = client.post('/v1/models/installed', headers=headers, json={'provider_id':provider,'model_id':'demo-assistant','use_default':True})
    assert installed.status_code == 200, installed.text
    chat = client.post('/v1/chats/quick', headers=headers, json={'client_request_id':'selfhost-smoke-chat'})
    assert chat.status_code == 201
    chat_id = chat.json()['id']
    assert client.get('/talk/' + chat_id).status_code == 200
    assert client.get('/v1/chats', headers=headers).json()[0]['id'] == chat_id
    job = client.post('/v1/chats/' + chat_id + '/messages', headers=headers, json={'text':'Hello','client_request_id':'selfhost-smoke-message'})
    assert job.status_code == 202
    assert client.get('/v1/chats/' + chat_id + '/messages', headers=headers).status_code == 200
'''
            result = subprocess.run([sys.executable, '-c', script], cwd=runtime, env=env,
                                    capture_output=True, text=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((runtime / 'test.db').exists())

if __name__ == '__main__':
    unittest.main()
