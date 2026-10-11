"""Read-only installer contract: no Docker services or real installation data."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

class CliTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.install = self.root / 'install dir'
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.env = {**os.environ, 'PATH': str(self.bin) + ':' + os.environ['PATH']}

    def tool(self, name, body):
        path = self.bin / name
        path.write_text('#!/bin/sh\n' + body + '\n')
        path.chmod(0o755)

    def run_cli(self, command='status', *extra, stdin=''):
        return subprocess.run([str(ROOT / 'wristmind'), command, '--install-dir', str(self.install), *extra],
                              env=self.env, input=stdin, text=True, capture_output=True, timeout=15)

    def test_clean_status_is_read_only_and_repeatable(self):
        for _ in range(2):
            result = self.run_cli()
            self.assertEqual(result.returncode, 0)
            self.assertIn('ещё не установлен', result.stdout)
            self.assertFalse(self.install.exists())

    def test_partial_install_preserves_secrets_without_executing_env(self):
        self.install.mkdir()
        secret = f'TOKEN=private-test-value\ntouch "{self.root / "executed"}"\n'
        (self.install / '.env').write_text(secret)
        result = self.run_cli()
        self.assertIn('незавершённая', result.stdout)
        self.assertNotIn('private-test-value', result.stdout + result.stderr)
        self.assertEqual((self.install / '.env').read_text(), secret)
        self.assertFalse((self.root / 'executed').exists())

    def test_marker_and_files_detect_existing_install(self):
        self.install.mkdir()
        for name in ['.wristmind-install', '.env', 'compose.yaml']:
            (self.install / name).write_text('unchanged')
        (self.install / '.wristmind-install').write_text(json.dumps({'format': 1, 'project': 'wristmind-0123456789ab', 'phase': 'ready'}))
        before = {p.name: p.read_bytes() for p in self.install.iterdir()}
        result = self.run_cli()
        self.assertIn('Установка обнаружена', result.stdout)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.install.iterdir()})

    def test_occupied_directory_not_treated_as_new(self):
        self.install.mkdir()
        (self.install / 'other.txt').write_text('keep')
        self.assertIn('занят', self.run_cli().stdout)
        self.assertEqual((self.install / 'other.txt').read_text(), 'keep')

    def test_invalid_arguments_fail_before_mutation(self):
        for args in [('check', '--domain', 'https://bad.test/x'), ('check', '--domain'), ('unknown',)]:
            self.assertEqual(self.run_cli(*args).returncode, 2)
        self.assertFalse(self.install.exists())

    def test_install_failed_preflight_is_not_reported_as_success(self):
        self.tool('docker', 'exit 1')
        result = self.run_cli('install')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Docker Compose', result.stderr)
        self.assertFalse(self.install.exists())

    def test_interactive_install_collects_port_and_demo_without_shell_flags(self):
        import pty
        copy = self.root / 'source'
        (copy / 'selfhost').mkdir(parents=True)
        import shutil
        shutil.copy2(ROOT / 'wristmind', copy / 'wristmind')
        calls = self.root / 'arguments'
        (copy / 'selfhost/installer.py').write_text(
            "import json,sys\nfrom pathlib import Path\n"
            "if sys.argv[1] == 'state': print('new')\n"
            "elif sys.argv[1] == 'install': Path(" + repr(str(calls)) + ").write_text(json.dumps(sys.argv[1:]))\n")
        master, slave = pty.openpty()
        try:
            process = subprocess.Popen(['bash', str(copy / 'wristmind'), 'menu', '--install-dir', str(self.install)],
                env=self.env, stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            os.close(slave)
            os.write(master, b'3\n9090\n2\nn\n0\n')
            out, err = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0, err.decode())
            import json
            args = json.loads(calls.read_text())
            self.assertEqual(args[args.index('--port')+1], '9090')
            self.assertIn('--demo', args)
            self.assertFalse(self.install.exists())
        finally:
            os.close(master)

    def test_noninteractive_menu_never_hangs(self):
        result = self.run_cli('menu')
        self.assertEqual(result.returncode, 0)
        self.assertIn('Для меню', result.stdout)

    def requirements_tools(self):
        self.tool('docker', 'exit 0')
        self.tool('getconf', 'echo 4')
        self.tool('df', "printf 'Filesystem 1024-blocks Used Available Capacity Mounted\\nfs 20000000 0 20000000 0%% /\\n'")
        self.tool('ss', 'exit 0')
        self.tool('getent', 'exit 0')

    def test_requirements_and_dns_use_read_only_commands(self):
        self.requirements_tools()
        result = self.run_cli('check', '--domain', 'example.test')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('совпадение с IP сервера ещё не проверено', result.stdout)
        self.assertFalse(self.install.exists())

    def test_requirements_report_docker_and_port_failures(self):
        self.requirements_tools()
        self.tool('docker', 'exit 1')
        self.tool('ss', 'echo LISTEN')
        result = self.run_cli('check')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Docker не запущен', result.stdout)
        self.assertIn('Порт 8080 занят', result.stdout)
        self.assertFalse(self.install.exists())

if __name__ == '__main__':
    unittest.main()
