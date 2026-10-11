from pathlib import Path
import sys
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'server/src'))
from wristmind_server.web_host import mount_panel

class WebHostTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'web'
        self.root.mkdir()
        (self.root / 'assets').mkdir()
        (self.root / 'index.html').write_text('<html>WristMind</html>')
        (self.root / 'assets/app.js').write_text('console.log("public")')
        (self.root / 'manifest.webmanifest').write_text('{}')
        (self.root / 'sw.js').write_text('/* public service worker */')
        (self.root / '.env').write_text('NEVER_SEND_THIS')
        (self.root.parent / 'private.txt').write_text('NEVER_SEND_THIS')
        (self.root / 'leaked.txt').symlink_to(self.root.parent / 'private.txt')
        (self.root / 'assets/leaked.txt').symlink_to(self.root.parent / 'private.txt')
        app = FastAPI()
        @app.get('/health')
        def health(): return {'status':'ok'}
        @app.get('/v1/example')
        def api(): return {'api': True}
        @app.post('/v1/post-only')
        def post_only(): return {'api':True}
        mount_panel(app, self.root)
        self.client = TestClient(app)

    def test_spa_routes_and_api_coexist(self):
        for path in ['/', '/main', '/talk', '/talk/chat-id', '/chats/chat-id', '/setup']:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertIn('WristMind', response.text)
            self.assertEqual(response.headers['cache-control'], 'no-cache')
        self.assertEqual(self.client.get('/health').json(), {'status':'ok'})
        self.assertEqual(self.client.get('/v1/example').json(), {'api':True})
        self.assertEqual(self.client.get('/v1/missing').status_code, 404)
        self.assertEqual(self.client.post('/talk').status_code, 405)
        response = self.client.get('/v1/post-only')
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.headers['allow'], 'POST')
        self.assertEqual(self.client.head('/talk').status_code, 200)

    def test_missing_assets_and_public_files_never_return_spa_html(self):
        for path in ['/assets/no.js', '/no.js', '/favicon.png', '/.well-known/assetlinks.json']:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 404, path)
            self.assertNotIn('<html>', response.text)
        response = self.client.get('/assets/app.js')
        self.assertEqual(response.status_code, 200)
        self.assertIn('javascript', response.headers['content-type'])
        self.assertEqual(self.client.get('/manifest.webmanifest').status_code, 200)
        self.assertEqual(self.client.get('/sw.js').headers['cache-control'], 'no-cache')

    def test_traversal_hidden_files_and_external_symlinks_are_not_served(self):
        for path in ['/.env', '/%2e%2e/private.txt', '/leaked.txt', '/assets/leaked.txt', '/assets/%2e%2e/%2e%2e/private.txt']:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 404, path)
            self.assertNotIn('NEVER_SEND_THIS', response.text)

    def test_startup_fails_clearly_if_panel_build_is_missing(self):
        with self.assertRaisesRegex(RuntimeError, 'Web panel build is missing'):
            mount_panel(FastAPI(), self.root / 'missing')

if __name__ == '__main__':
    unittest.main()
