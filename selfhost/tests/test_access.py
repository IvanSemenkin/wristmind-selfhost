"""Local access contracts: DNS, real Compose parsing, recovery and credential preservation."""
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'selfhost'))
import access
import installer


class AccessTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.target = Path(self.temp.name) / 'install with spaces'
        self.data, self.values = installer.prepare(self.target, SimpleNamespace(port=8080, bind='0.0.0.0', demo=True))
        self.data['phase'] = 'ready'
        installer.write_manifest(self.target, self.data)
        self.before = (self.target / '.env').read_text()
        self.run = self.enterContext(patch.object(installer, 'run_step'))
        self.health = self.enterContext(patch.object(installer, 'health'))
        self.dns = self.enterContext(patch.object(access, 'dns_check', return_value=['203.0.113.10']))
        self.public = self.enterContext(patch.object(access, 'public_health', return_value=True))

    def domain(self):
        return access.configure(self.target, 'domain', 'ai.example.org', '203.0.113.10')

    def test_ip_detection_uses_server_side_of_ssh_connection(self):
        with patch.dict(os.environ, {'SSH_CONNECTION': '1.1.1.1 1234 8.8.8.8 22'}), patch.object(installer.subprocess, 'run') as run:
            self.assertEqual(access.detect_server_ip(), '8.8.8.8')
            run.assert_not_called()

    def test_ip_detection_queries_public_ip_for_private_ssh_destination(self):
        reply = subprocess.CompletedProcess([], 0, '9.9.9.9\n', '')
        with patch.dict(os.environ, {'SSH_CONNECTION': '1.1.1.1 1234 192.168.1.2 22'}), patch.object(installer.subprocess, 'run', return_value=reply):
            self.assertEqual(access.detect_server_ip(), '9.9.9.9')

    def test_ip_detection_failure_keeps_lan_destination_or_requires_manual_input(self):
        reply = subprocess.CompletedProcess([], 0, 'invalid-address', '')
        with patch.dict(os.environ, {'SSH_CONNECTION': '1.1.1.1 1234 192.168.1.2 22'}), patch.object(installer.subprocess, 'run', return_value=reply):
            self.assertEqual(access.detect_server_ip(), '192.168.1.2')
        with patch.dict(os.environ, {'SSH_CONNECTION': ''}), patch.object(installer.subprocess, 'run', side_effect=OSError):
            self.assertIsNone(access.detect_server_ip())

    def test_first_login_prints_full_activation_link_even_if_public_probe_is_pending(self):
        import io
        import contextlib
        access.configure(self.target, 'local')
        def configure_http(*args, **kwargs):
            self.public.return_value = False
            code = access.configure(self.target, 'http', expected_ip='203.0.113.10')
            return subprocess.CompletedProcess([], code)
        output = io.StringIO()
        with patch.object(sys, 'argv', ['installer', 'setup-link', '--install-dir', str(self.target)]), patch.object(sys.stdin, 'isatty', return_value=True), patch.object(installer.subprocess, 'run', side_effect=configure_http), contextlib.redirect_stdout(output):
            self.assertEqual(installer.main(), 0)
        self.assertIn('http://203.0.113.10:8080/setup#activate='+self.values['WRISTMIND_SELFHOST_SETUP_TOKEN'], output.getvalue())
        self.assertNotIn('http://localhost:8080/setup', output.getvalue())

    def test_http_ip_exposes_only_panel_port_and_preserves_secrets(self):
        self.domain()
        self.assertEqual(access.configure(self.target, 'http', expected_ip='203.0.113.10'), 0)
        values = installer.validate_saved(self.target, installer.manifest_at(self.target))
        self.assertEqual(values['WRISTMIND_PUBLIC_BASE_URL'], 'http://203.0.113.10:8080')
        self.assertEqual(values['WRISTMIND_BIND_ADDRESS'], '0.0.0.0')
        self.assertEqual(values['WRISTMIND_SELFHOST_SETUP_TOKEN'], self.values['WRISTMIND_SELFHOST_SETUP_TOKEN'])
        self.assertFalse((self.target / 'compose.access.yaml').exists())
        self.assertEqual(installer.manifest_at(self.target)['access']['mode'], 'http')

    def test_invalid_http_address_does_not_change_installation(self):
        for address in ('http://example.test', '127.0.0.1', '0.0.0.0', '224.0.0.1'):
            with self.assertRaises(ValueError):
                access.configure(self.target, 'http', expected_ip=address)
            self.assertEqual((self.target / '.env').read_text(), self.before)

    def test_domain_secure_origin_secrets_and_persisted_volumes(self):
        self.assertEqual(self.domain(), 0)
        values = installer.validate_saved(self.target, installer.manifest_at(self.target))
        for key in ('POSTGRES_PASSWORD', 'WRISTMIND_TOKEN_PEPPER', 'WRISTMIND_SELFHOST_SETUP_TOKEN', 'WRISTMIND_IMAGE'):
            self.assertEqual(values[key], self.values[key])
        self.assertEqual(values['WRISTMIND_BIND_ADDRESS'], '127.0.0.1')
        self.assertEqual(values['WRISTMIND_PUBLIC_BASE_URL'], 'https://ai.example.org')
        self.assertIn('flush_interval -1', (self.target / 'Caddyfile').read_text())
        overlay = json.loads((self.target / 'compose.access.yaml').read_text())
        self.assertEqual(set(overlay['volumes']), {'https_data', 'https_config'})
        self.assertEqual(installer.manifest_at(self.target)['access']['phase'], 'ready')
        for name in access.FILES:
            if (self.target / name).exists():
                self.assertEqual((self.target / name).stat().st_mode & 0o777, 0o600)

    def test_reconfigure_and_return_to_local_does_not_delete_data(self):
        self.domain()
        private = self.target / 'sentinel.db'
        private.write_text('preserve')
        self.assertEqual(access.configure(self.target, 'local'), 0)
        self.assertFalse((self.target / 'compose.access.yaml').exists())
        self.assertEqual(installer.read_env(self.target)['WRISTMIND_PUBLIC_BASE_URL'], 'http://localhost:8080')
        self.assertEqual(private.read_text(), 'preserve')
        self.assertTrue(any(call.args[0][-2:] == ['stop', 'gateway'] for call in self.run.call_args_list))
        self.domain()
        self.assertEqual(installer.manifest_at(self.target)['access']['phase'], 'ready')

    def test_tunnel_token_is_file_only_and_no_public_ports(self):
        token = Path(self.temp.name) / 'private-token'
        token.write_text('a' * 90)
        self.assertEqual(access.configure(self.target, 'tunnel', 'ai.example.org', token_file=token), 0)
        overlay = json.loads((self.target / 'compose.access.yaml').read_text())
        self.assertNotIn('ports', overlay['services']['gateway'])
        self.assertIn('--token-file', overlay['services']['gateway']['command'])
        self.assertNotIn('a' * 90, (self.target / 'compose.access.yaml').read_text())
        self.assertEqual((self.target / '.tunnel-token').stat().st_mode & 0o777, 0o600)
        for call in self.run.call_args_list:
            self.assertNotIn('a' * 90, ' '.join(call.args[0]))

    def test_pending_https_can_be_rechecked_without_restarting(self):
        self.public.side_effect = OSError('DNS not propagated')
        self.assertEqual(self.domain(), 1)
        self.assertEqual(installer.manifest_at(self.target)['access']['phase'], 'pending')
        self.run.reset_mock()
        self.public.side_effect = None
        self.public.return_value = True
        self.assertEqual(access.configure(self.target, 'check'), 0)
        self.run.assert_not_called()
        self.assertEqual(installer.manifest_at(self.target)['access']['phase'], 'ready')

    def test_failed_config_restores_credentials_and_old_access(self):
        self.domain()
        previous = {name: (self.target / name).read_bytes() if (self.target / name).exists() else None for name in access.FILES}
        self.run.side_effect = [RuntimeError('invalid compose'), None]
        with self.assertRaises(RuntimeError):
            access.configure(self.target, 'domain', 'other.example.org', '203.0.113.10')
        for name, content in previous.items():
            self.assertEqual((self.target / name).read_bytes() if (self.target / name).exists() else None, content)

    def test_failed_first_gateway_start_restores_local_and_stops_only_project_gateway(self):
        self.run.side_effect = [None, RuntimeError('start failed'), None, None]
        with patch.object(installer.subprocess, 'run', return_value=SimpleNamespace(stdout='aabbccddeeff\n')):
            with self.assertRaises(RuntimeError):
                self.domain()
        self.assertEqual((self.target / '.env').read_text(), self.before)
        self.assertFalse((self.target / 'compose.access.yaml').exists())
        self.assertTrue(any(call.args[0] == ['docker', 'stop', 'aabbccddeeff'] for call in self.run.call_args_list))

    def test_missing_ip_or_mismatched_dns_makes_no_changes(self):
        with self.assertRaises(ValueError):
            access.configure(self.target, 'domain', 'ai.example.org')
        self.dns.side_effect = ValueError('mismatch')
        with self.assertRaises(ValueError):
            self.domain()
        self.assertEqual((self.target / '.env').read_text(), self.before)
        self.run.assert_not_called()

    def test_symlinks_and_invalid_token_rejected(self):
        (self.target / 'Caddyfile').symlink_to('/dev/null')
        with self.assertRaises(ValueError):
            self.domain()
        (self.target / 'Caddyfile').unlink()
        token = Path(self.temp.name) / 'token'
        token.write_text('bad\ncommand')
        with self.assertRaises(ValueError):
            access.configure(self.target, 'tunnel', 'ai.example.org', token_file=token)
        self.assertEqual((self.target / '.env').read_text(), self.before)
        self.run.assert_not_called()

    def test_lock_prevents_parallel_install_or_access(self):
        key = hashlib.sha256(str(self.target.resolve()).encode()).hexdigest()[:16]
        with open(self.target.parent / ('.wristmind-lock-' + key), 'w') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(ValueError):
                self.domain()
        self.run.assert_not_called()

    def test_real_compose_configuration_for_both_gateways(self):
        self.domain()
        for mode in ('domain', 'tunnel'):
            access.atomic(self.target / 'compose.access.yaml', access.overlay(mode))
            result = subprocess.run(installer.compose(self.target, self.data, 'config', '--format', 'json'),
                cwd=self.target, env=installer.docker_environment(), capture_output=True, text=True, check=True, timeout=20)
            config = json.loads(result.stdout)
            self.assertEqual(set(config['services']), {'db', 'api', 'worker', 'gateway', 'searxng'})
            self.assertEqual(config['services']['api']['ports'][0]['host_ip'], '127.0.0.1')
            self.assertIn('--proxy-headers', config['services']['api']['command'])
            self.assertEqual(config['services']['gateway']['image'], 'caddy:2' if mode == 'domain' else 'cloudflare/cloudflared:latest')
            self.assertIn(self.data['project'], config['volumes']['postgres_data']['name'])

    def test_setup_link_uses_https_without_changing_secret(self):
        self.domain()
        result = subprocess.run([sys.executable, str(ROOT / 'selfhost/installer.py'), 'setup-link', '--install-dir', str(self.target)],
            capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), 'https://ai.example.org/setup#activate=' + self.values['WRISTMIND_SELFHOST_SETUP_TOKEN'])


class ValidationTest(unittest.TestCase):
    def test_domain_validation_idna_and_injection(self):
        self.assertEqual(access.domain_name('AI.Example.org.'), 'ai.example.org')
        self.assertEqual(access.domain_name('пример.рф'), 'xn--e1afmkfd.xn--p1ai')
        for value in ['https://a.example.org', 'a.example.org/path', 'a.example.org:443', '127.0.0.1', '*.example.org', 'a..org', 'a.example.org {\n evil }', '-a.example.org']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                access.domain_name(value)

    def test_dns_checks_all_a_and_aaaa(self):
        with patch.object(access.socket, 'getaddrinfo', return_value=[(0, 0, 0, '', ('203.0.113.10', 443)), (0, 0, 0, '', ('2001:db8::1', 443))]):
            self.assertEqual(len(access.dns_check('ai.example.org', '203.0.113.10,2001:db8::1')), 2)
            with self.assertRaises(ValueError):
                access.dns_check('ai.example.org', '203.0.113.10')
        with patch.object(access.socket, 'getaddrinfo', side_effect=access.socket.gaierror()):
            with self.assertRaises(ValueError):
                access.dns_check('ai.example.org')

    def test_dotenv_preserves_other_credentials_and_does_not_execute(self):
        text = "A_SECRET='literal$neverexecute'\nWRISTMIND_PUBLIC_BASE_URL=http://localhost\nOTHER=stay\n"
        updated = access.update_env(text, {'WRISTMIND_PUBLIC_BASE_URL': 'https://ai.example.org'})
        self.assertIn("A_SECRET='literal$neverexecute'", updated)
        self.assertIn('OTHER=stay', updated)
        self.assertEqual(updated.count('WRISTMIND_PUBLIC_BASE_URL='), 1)

if __name__ == '__main__':
    unittest.main()
