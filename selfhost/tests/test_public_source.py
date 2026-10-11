import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('public_source', Path(__file__).resolve().parents[1] / 'public_source.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PublicSourceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'working'
        self.root.mkdir()
        for name in module.FILES:
            self.write(name, 'public example')

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def test_no_history_private_files_or_build_outputs(self):
        self.write('.git/config', 'private history')
        self.write('server/src/app.py', 'print("ok")')
        self.write('web/tsconfig.app.json', '{}')
        self.write('android/gradle/wrapper/gradle-wrapper.jar', 'wrapper')
        for name in ('server/src/.env', 'server/src/key.pem', 'android/phone/local.properties',
                     'android/phone/build/outputs/app.apk', 'android/phone/signing.p12',
                     'web/public/.well-known/assetlinks.json', 'deploy/private.conf', 'watch/app.js'):
            self.write(name, 'private')
        out = self.base / 'public'
        module.export(self.root, out)
        files = {p.relative_to(out).as_posix() for p in out.rglob('*') if p.is_file()}
        self.assertEqual(files, set(module.FILES) | {'server/src/app.py', 'web/tsconfig.app.json', 'android/gradle/wrapper/gradle-wrapper.jar'})

    def test_secret_rejected_without_echo_and_output_not_created(self):
        self.write('server/src/bad.py', '-----BEGIN ' + 'PRIVATE KEY-----')
        out = self.base / 'public'
        with self.assertRaisesRegex(ValueError, 'server/src/bad.py') as caught:
            module.export(self.root, out)
        self.assertNotIn('BEGIN PRIVATE KEY', str(caught.exception))
        self.assertFalse(out.exists())

    def test_symlink_rejected(self):
        path = self.write('server/src/ok.py', 'ok')
        (path.parent / 'linked.py').symlink_to(path)
        with self.assertRaisesRegex(ValueError, 'Символическая ссылка'):
            module.export(self.root, self.base / 'public')

    def test_existing_and_nested_output_rejected(self):
        for out in (self.root, self.root / 'nested'):
            with self.assertRaises(ValueError):
                module.export(self.root, out)
        self.assertFalse((self.root / 'nested').exists())
