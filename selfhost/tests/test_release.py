"""Publisher contracts: exact public allowlist, immutable artifacts and dependency pins."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'selfhost'))
import release
import installer


class ReleaseBuildTest(unittest.TestCase):
    def test_public_builder_never_packages_private_state_or_git_history(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'source'
            source.mkdir()
            for name in release.RUNTIME:
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / name, path)
            (source / '.env').write_text('SECRET=publisher-private-test-value')
            (source / '.tunnel-token').write_text('private-tunnel-value')
            (source / '.git').mkdir()
            (source / '.git/history').write_text('private history')
            calls = []
            def docker(args, **kwargs):
                calls.append(args)
                if 'save' in args:
                    Path(args[args.index('-o') + 1]).write_bytes(b'test-image')
                return SimpleNamespace(returncode=0)
            def inspect(image):
                return {'Id': 'sha256:' + 'a' * 64, 'Architecture': 'amd64', 'Os': 'linux',
                        'RepoDigests': ['example/pinned@sha256:' + 'b' * 64]}
            package = root / 'outputs/release.tar.gz'
            with patch.object(installer, 'ROOT', source), patch.object(release.subprocess, 'run', side_effect=docker), patch.object(release, 'inspect_image', side_effect=inspect):
                release.build('1.0.1', 'amd64', package)
            checksum = release.digest(package)
            self.assertTrue((package.parent / (package.name + '.sha256')).read_text().startswith(checksum))
            unpacked = root / 'unpacked'
            unpacked.mkdir()
            info = release.unpack(package, checksum, unpacked)
            self.assertEqual(set(info['files']), set(release.RUNTIME) | {'image.tar'})
            self.assertNotIn('.env', info['files'])
            self.assertNotIn('.git/history', info['files'])
            self.assertEqual(info['image'], 'wristmind-selfhost:1.0.1-amd64')
            self.assertEqual(len([args for args in calls if 'pull' in args]), 4)
            with self.assertRaises(ValueError):
                release.build('1.0.1', 'amd64', package)

    def test_version_and_image_name_cannot_overwrite_an_existing_legacy_image(self):
        data = {'format': 1, 'kind': 'release', 'version': '1.0.1', 'arch': 'amd64', 'schema': 1,
                'postgres_major': 16, 'image': 'wristmind-selfhost:wristmind-0123456789ab',
                'image_id': 'sha256:' + 'a' * 64, 'files': {name: 'a' * 64 for name in (*release.RUNTIME, 'image.tar')}}
        with self.assertRaises(ValueError):
            release.metadata(data)

    def test_tag_version_validation_rejects_shell_and_prerelease_values_before_build(self):
        for version in ('v1.0.1', '1.0.1;touch /tmp/x', '1.0.1-rc1', '01.0.1'):
            with self.assertRaises(ValueError):
                release.build(version, 'amd64', Path('/unused-test-output'))

if __name__ == '__main__':
    unittest.main()
