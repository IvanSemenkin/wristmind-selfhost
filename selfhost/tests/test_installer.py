"""Installer end-to-end contracts with isolated fake Docker; no real containers."""
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('installer', ROOT / 'selfhost/installer.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallerTest(unittest.TestCase):
    def test_build_status_and_log_do_not_expose_secrets(self):
        import io
        import contextlib
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            secret = 'private-provider-test-token'
            command = ['python3', '-c', 'print("npm ci '+secret+'")']
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                installer.run_step(command, target, {'API_KEY': secret}, label='Сборка API и панели')
            self.assertIn('Сборка API и панели', output.getvalue())
            self.assertIn('готово', output.getvalue())
            self.assertNotIn(secret, output.getvalue())
            self.assertNotIn(secret, (target / 'install.log').read_text())

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / 'installation with spaces'
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.calls = self.root / 'calls'
        self.env = {**os.environ, 'PATH': str(self.bin) + ':' + os.environ['PATH'],
                    'TEST_CALLS': str(self.calls), 'TEST_FAIL': '', 'TEST_VERSION': '5.5.1',
                    'POSTGRES_PASSWORD': 'parent-secret', 'COMPOSE_PROFILES': 'telegram',
                    'WRISTMIND_IMAGE': 'wrong-parent-image'}
        self.tool('docker', '''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
with open(os.environ['TEST_CALLS'], 'a') as f:
    f.write(json.dumps(args) + '\\n')
if args[:2] == ['compose', 'version']:
    print(os.environ['TEST_VERSION']); sys.exit(0)
if args == ['info']:
    sys.exit(1 if os.environ['TEST_FAIL'] == 'info' else 0)
if args == ['buildx', 'version']:
    print('github.com/docker/buildx v0.17.0'); sys.exit(0)
step = next((v for v in args if v in {'config', 'build', 'up', 'exec'}), '')
if step == 'build':
    env = pathlib.Path(args[args.index('--env-file') + 1]).read_text()
    print(next(line.split('=', 1)[1] for line in env.splitlines() if line.startswith('POSTGRES_PASSWORD=')))
if os.environ['TEST_FAIL'] == step:
    sys.exit(1)
assert not any(k.startswith(('COMPOSE_', 'WRISTMIND_')) or k == 'POSTGRES_PASSWORD' for k in os.environ)
''')
        self.tool('getconf', '#!/bin/sh\necho 4\n')
        self.tool('df', "#!/bin/sh\nprintf 'Filesystem 1024-blocks Used Available Capacity Mounted\\nfs 20000000 0 20000000 0%% /\\n'\n")
        self.tool('ss', '#!/bin/sh\nexit 0\n')
        # Dependency repair must never escalate to the host's real sudo in tests.
        self.tool('sudo', '#!/bin/sh\nexit 1\n')

    def tool(self, name, text):
        path = self.bin / name
        path.write_text(text)
        path.chmod(0o755)

    def run_install(self, *args):
        return subprocess.run([str(ROOT / 'wristmind'), 'install', '--install-dir', str(self.target), *args],
                              env=self.env, capture_output=True, text=True, timeout=30)

    def successful(self, *args):
        result = self.run_install(*args)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_first_install_payload_secrets_permissions_and_health(self):
        result = self.successful('--demo', '--port', '18080')
        values = installer.read_env(self.target)
        data = installer.manifest_at(self.target)
        self.assertEqual(data['phase'], 'ready')
        self.assertEqual(values['WRISTMIND_HTTP_PORT'], '18080')
        self.assertEqual(values['WRISTMIND_MOCK_PROVIDERS'], 'true')
        self.assertEqual(values['COMPOSE_PROFILES'], 'search')
        self.assertEqual(values['WRISTMIND_SEARXNG_URL'], 'http://searxng:8080')
        self.assertEqual(len(values['SEARXNG_SECRET']), 64)
        self.assertNotEqual(values['POSTGRES_PASSWORD'], 'parent-secret')
        self.assertEqual(len({values[k] for k in ('POSTGRES_PASSWORD', 'WRISTMIND_BOOTSTRAP_SECRET', 'WRISTMIND_TOKEN_PEPPER')}), 3)
        for name in ('.env', '.wristmind-install', 'install.log'):
            self.assertEqual((self.target / name).stat().st_mode & 0o777, 0o600)
        self.assertFalse((self.target / '.git').exists())
        self.assertFalse((self.target / 'web/node_modules').exists())
        self.assertFalse((self.target / 'server/.env').exists())
        log = (self.target / 'install.log').read_text()
        self.assertNotIn(values['POSTGRES_PASSWORD'], log + result.stdout + result.stderr)
        self.assertIn('[скрыто]', log)
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertTrue(any('exec' in call and '/health' in call[-1] for call in calls))
        self.assertTrue(all(data['project'] in call for call in calls if 'config' in call or 'up' in call))

    def test_setup_link_uses_activation_only_without_regenerating_secrets(self):
        self.successful('--demo', '--port', '18080')
        saved = (self.target / '.env').read_bytes()
        values = installer.read_env(self.target)
        result = subprocess.run([str(ROOT / 'wristmind'), 'setup-link', '--install-dir', str(self.target)], env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('/setup#activate=' + values['WRISTMIND_SELFHOST_SETUP_TOKEN'], result.stdout)
        self.assertNotIn(values['WRISTMIND_BOOTSTRAP_SECRET'], result.stdout)
        self.assertEqual(saved, (self.target / '.env').read_bytes())
        self.assertNotIn(values['WRISTMIND_SELFHOST_SETUP_TOKEN'], (self.target / 'install.log').read_text())

    def test_materialized_payload_passes_real_compose_config(self):
        installer.prepare(self.target, SimpleNamespace(port=18080, bind=None, demo=False))
        data = installer.manifest_at(self.target)
        command = installer.compose(self.target, data, 'config', '--format', 'json')
        command[0] = shutil.which('docker', path=os.environ['PATH'])
        result = subprocess.run(command, env=installer.docker_environment(), capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, 'Compose configuration failed')
        config = json.loads(result.stdout)
        self.assertEqual(set(config['services']), {'db', 'api', 'worker', 'searxng'})
        self.assertNotIn('ports', config['services']['searxng'])
        self.assertEqual(config['name'], data['project'])
        self.assertEqual(config['services']['api']['ports'][0]['published'], '18080')
        self.assertEqual(config['services']['api']['build']['context'], str(self.target))
        self.assertTrue(all(v['name'].startswith(data['project'] + '_') for v in config['volumes'].values()))

    def test_separate_installs_have_distinct_secrets_and_volume_names(self):
        options = SimpleNamespace(port=None, bind=None, demo=False)
        first, values = installer.prepare(self.target, options)
        second, other = installer.prepare(self.root / 'second', options)
        self.assertNotEqual(first['project'], second['project'])
        for key in ('POSTGRES_PASSWORD', 'WRISTMIND_BOOTSTRAP_SECRET', 'WRISTMIND_TOKEN_PEPPER'):
            self.assertNotEqual(values[key], other[key])

    def test_repeat_is_noop_preserving_secrets_and_data(self):
        self.successful()
        before = (self.target / '.env').read_bytes()
        calls = self.calls.read_bytes()
        (self.target / 'precious-user-file').write_text('preserve')
        self.env['TEST_FAIL'] = 'info'
        self.successful()
        self.assertEqual(before, (self.target / '.env').read_bytes())
        self.assertEqual(calls, self.calls.read_bytes())
        self.assertEqual((self.target / 'precious-user-file').read_text(), 'preserve')

    def test_failed_steps_resume_without_regenerating_secrets(self):
        for step in ('config', 'build', 'up', 'exec'):
            with self.subTest(step=step):
                self.target = self.root / step
                self.env['TEST_FAIL'] = step
                result = self.run_install('--demo')
                self.assertEqual(result.returncode, 1)
                self.assertEqual(installer.manifest_at(self.target)['phase'], 'failed')
                saved = (self.target / '.env').read_bytes()
                self.assertIn('--resume', self.run_install().stderr)
                self.env['TEST_FAIL'] = ''
                self.successful('--resume')
                self.assertEqual(saved, (self.target / '.env').read_bytes())
                self.assertEqual(installer.manifest_at(self.target)['phase'], 'ready')
        self.assertNotIn('down', self.calls.read_text())

    def test_unmanaged_directory_and_env_never_overwritten(self):
        self.target.mkdir()
        (self.target / '.env').write_text('PRIVATE=do-not-change\n')
        self.assertEqual(self.run_install('--resume').returncode, 1)
        self.assertEqual((self.target / '.env').read_text(), 'PRIVATE=do-not-change\n')
        self.assertFalse(self.calls.exists())

    def test_changed_parameters_and_corrupted_secrets_refused(self):
        self.successful('--demo')
        saved = (self.target / '.env').read_bytes()
        for args in (('--port', '18081'), ('--bind', '0.0.0.0')):
            self.assertEqual(self.run_install(*args).returncode, 1)
            self.assertEqual(saved, (self.target / '.env').read_bytes())
        values = installer.read_env(self.target)
        (self.target / '.env').write_text(saved.decode().replace(values['POSTGRES_PASSWORD'], 'broken'))
        self.assertEqual(self.run_install('--resume').returncode, 1)
        self.assertIn('broken', (self.target / '.env').read_text())

    def test_preflight_failure_creates_no_installation(self):
        for fail, version in (('info', '5.5.1'), ('', '2.23.0')):
            self.env.update(TEST_FAIL=fail, TEST_VERSION=version)
            self.assertEqual(self.run_install().returncode, 1)
            self.assertFalse(self.target.exists())

    def test_busy_selected_port_creates_no_installation(self):
        self.tool('ss', '#!/bin/sh\necho LISTEN\n')
        result = self.run_install('--port', '18080')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Порт 18080 занят', result.stdout)
        self.assertFalse(self.target.exists())

    def test_domain_and_invalid_port_refused_before_mutation(self):
        for args in (('--domain', 'example.test'), ('--port', '0'), ('--port', '999999'), ('--timeout', '0')):
            self.assertNotEqual(self.run_install(*args).returncode, 0)
        self.assertFalse(self.target.exists())
        self.assertFalse(self.calls.exists())

    def test_concurrent_install_refused(self):
        path = self.root / ('.wristmind-lock-' + hashlib.sha256(str(self.target.resolve()).encode()).hexdigest()[:16])
        with path.open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertIn('другая установка', self.run_install().stderr)
            self.assertFalse(self.target.exists())

    def test_symlinks_and_source_directory_refused(self):
        elsewhere = self.root / 'other'
        elsewhere.mkdir()
        self.target.symlink_to(elsewhere)
        self.assertEqual(self.run_install().returncode, 1)
        self.assertEqual(list(elsewhere.iterdir()), [])
        self.target = ROOT
        self.assertIn('вне исходников', self.run_install().stderr)

    def test_atomic_manifest_write_tolerates_leftover_and_parse_failure(self):
        self.target.mkdir()
        (self.target / '.wristmind-install.next').write_text('interrupted')
        installer.write_manifest(self.target, {'format': 1, 'project': 'wristmind-0123456789ab', 'phase': 'failed'})
        self.assertEqual(installer.manifest_at(self.target)['phase'], 'failed')
        (self.target / '.wristmind-install').write_text('not json')
        self.assertIsNone(installer.manifest_at(self.target))

    def test_failed_payload_leaves_no_target_or_staging(self):
        with patch.object(installer, 'payload', side_effect=ValueError('invalid payload')):
            with self.assertRaises(ValueError):
                installer.prepare(self.target, SimpleNamespace(port=None, bind=None, demo=False))
        self.assertFalse(self.target.exists())
        self.assertEqual(list(self.root.glob('.wristmind-staging-*')), [])

    def test_source_symlink_rejected(self):
        source = self.root / 'source'
        staging = self.root / 'staging'
        source.mkdir(); staging.mkdir()
        (source / 'compose.yaml').symlink_to(ROOT / 'compose.yaml')
        with patch.object(installer, 'ROOT', source):
            with self.assertRaisesRegex(ValueError, 'символическую'):
                installer.payload(staging)


if __name__ == '__main__':
    unittest.main()
