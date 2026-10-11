import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class BootstrapTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.bin = self.folder / 'bin'
        self.bin.mkdir()
        curl = self.bin / 'curl'
        curl.write_text('''#!/usr/bin/env python3
import os, shutil, sys
if os.environ.get('WM_TEST_FAIL'): sys.exit(22)
shutil.copyfile(os.environ['WM_TEST_ARCHIVE'], sys.argv[sys.argv.index('--output') + 1])
''')
        curl.chmod(0o755)
        self.archive = self.folder / 'archive.tar.gz'
        self.env = {**os.environ, 'PATH': str(self.bin) + ':' + os.environ['PATH'],
                    'TMPDIR': str(self.folder), 'WM_TEST_ARCHIVE': str(self.archive)}

    def archive_with(self, invalid=None):
        with tarfile.open(self.archive, 'w:gz') as archive:
            for name in ('wristmind', 'compose.yaml', 'selfhost/installer.py'):
                content = (ROOT / name).read_bytes()
                entry = tarfile.TarInfo('wristmind-main/' + name)
                entry.size = len(content)
                entry.mode = 0o755 if name == 'wristmind' else 0o644
                archive.addfile(entry, io.BytesIO(content))
            if invalid:
                entry = tarfile.TarInfo(invalid)
                entry.type = tarfile.SYMTYPE
                entry.linkname = '/etc/passwd'
                archive.addfile(entry)

    def run_bootstrap(self, *args):
        result = subprocess.run(['bash', str(ROOT / 'install.sh'), *args], env=self.env,
                                input='', capture_output=True, text=True, timeout=15)
        self.assertFalse(list(self.folder.glob('wristmind-bootstrap.*')))
        return result

    def test_download_and_status_forwarding(self):
        self.archive_with()
        install = self.folder / 'not installed'
        result = self.run_bootstrap('status', '--install-dir', str(install))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('ещё не установлен', result.stdout)
        self.assertFalse(install.exists())

    def test_menu_does_not_install_when_noninteractive(self):
        self.archive_with()
        result = self.run_bootstrap()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Для меню', result.stdout)

    def test_network_failure_is_not_success(self):
        self.env['WM_TEST_FAIL'] = '1'
        result = self.run_bootstrap()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Не удалось скачать', result.stderr)

    def test_symlink_and_path_traversal_rejected(self):
        for name in ('wristmind-main/link', 'wristmind-main/../../escaped'):
            self.archive_with(name)
            result = self.run_bootstrap('status')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Не удалось проверить', result.stderr)
        self.assertFalse((self.folder / 'escaped').exists())


class MaintenanceMenuTest(unittest.TestCase):
    def test_empty_invalid_and_crlf_input_keep_submenu_open(self):
        code = (ROOT / 'wristmind').read_text().rsplit('case $WM_COMMAND in', 1)[0]
        code += '\nmaintenance() { printf "OPERATION:%s\\n" "$*"; }\nmaintenance_menu\necho FINISHED\n'
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'menu.sh'
            script.write_text(code)
            result = subprocess.run(['bash', str(script)], input='\r\nwrong\r\n1\r\n0\r\n',
                                    text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('OPERATION:version', result.stdout)
        self.assertIn('FINISHED', result.stdout)
        self.assertGreaterEqual(result.stdout.count('Обновления и резервные копии'), 3)
