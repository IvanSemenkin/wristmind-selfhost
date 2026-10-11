import json
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]

class ComposeTest(unittest.TestCase):
    def configuration(self, *args):
        env = {**os.environ, 'POSTGRES_PASSWORD': 'test-only',
               'WRISTMIND_BOOTSTRAP_SECRET': 'test-only', 'WRISTMIND_TOKEN_PEPPER': 'test-only'}
        result = subprocess.run(['docker', 'compose', '--env-file', '/dev/null', '-f', str(ROOT / 'compose.yaml'),
                                 *args, 'config', '--format', 'json'], cwd=ROOT, env=env,
                                text=True, capture_output=True, timeout=20, check=True)
        return json.loads(result.stdout)

    def test_three_default_services_and_single_panel_api_port(self):
        config = self.configuration()
        self.assertEqual(set(config['services']), {'db', 'api', 'worker'})
        api = config['services']['api']
        self.assertEqual(api['ports'][0]['target'], 8000)
        self.assertEqual(api['ports'][0]['host_ip'], '127.0.0.1')
        self.assertEqual(api['environment']['WRISTMIND_WEB_DIST'], '/app/web-dist')
        self.assertNotIn('ports', config['services']['db'])
        self.assertNotIn('ports', config['services']['worker'])

    def test_optional_profiles_do_not_change_default_worker_dependencies(self):
        config = self.configuration('--profile', 'search', '--profile', 'telegram')
        self.assertEqual(set(config['services']), {'db', 'api', 'worker', 'searxng', 'telegram-bot'})
        self.assertEqual(set(config['services']['worker']['depends_on']), {'db'})
        self.assertNotIn('ports', config['services']['searxng'])
        self.assertEqual(config['services']['telegram-bot']['image'], config['services']['api']['image'])

    def test_no_host_mounts_fixed_subnets_privileged_or_host_network(self):
        config = self.configuration('--profile', 'search', '--profile', 'telegram')
        for name, service in config['services'].items():
            self.assertNotEqual(service.get('network_mode'), 'host', name)
            self.assertFalse(service.get('privileged'), name)
            self.assertNotIn('NET_ADMIN', service.get('cap_add', []), name)
            for volume in service.get('volumes', []):
                if volume['type'] == 'bind':
                    self.assertTrue(Path(volume['source']).is_relative_to(ROOT / 'selfhost'), volume)
        self.assertFalse(config['networks']['default'].get('ipam', {}).get('config'))

    def test_requires_secrets_and_does_not_use_development_defaults(self):
        env = {key: value for key, value in os.environ.items()
               if key not in {'POSTGRES_PASSWORD','WRISTMIND_BOOTSTRAP_SECRET','WRISTMIND_TOKEN_PEPPER'}}
        result = subprocess.run(['docker','compose','--env-file','/dev/null','-f',str(ROOT / 'compose.yaml'),
                                 'config','--quiet'], cwd=ROOT, env=env, capture_output=True, timeout=20)
        self.assertNotEqual(result.returncode, 0)

    def test_build_excludes_old_app_links_and_private_context(self):
        dockerfile = (ROOT / 'selfhost/Dockerfile').read_text()
        self.assertIn('rm -rf public/.well-known', dockerfile)
        self.assertIn('wristmind_server.selfhost_app:app', dockerfile)
        self.assertNotIn('network: host', dockerfile)
        ignored = (ROOT / '.dockerignore').read_text()
        for entry in ['.git','**/.env','**/local.properties','**/*.keystore','**/*firebase-admin*.json','data']:
            self.assertIn(entry, ignored)

if __name__ == '__main__':
    unittest.main()
