"""Recovery and package security contracts. Docker streams are isolated fakes."""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'selfhost'))
import installer
import access
import lifecycle
import release


def private_archive(path, malicious=False):
    with tarfile.open(path, 'w:gz') as archive:
        directory = tarfile.TarInfo('private')
        directory.type = tarfile.DIRTYPE
        archive.addfile(directory)
        file = tarfile.TarInfo('../escape' if malicious else 'private/source.txt')
        value = b'private test content'
        file.size = len(value)
        archive.addfile(file, io.BytesIO(value))


class LifecycleTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / 'installation'
        self.data, self.values = installer.prepare(self.target, SimpleNamespace(port=8080, bind=None, demo=True))
        self.data['phase'] = 'ready'
        installer.write_manifest(self.target, self.data)
        self.before = (self.target / '.env').read_bytes()
        self.calls = []
        self.fail = None
        self.enterContext(patch.object(lifecycle, 'run', side_effect=self.fake_run))
        self.enterContext(patch.object(lifecycle, 'running', return_value=['db', 'api', 'worker']))
        self.enterContext(patch.object(release, 'inspect_image', side_effect=self.inspect))
        self.enterContext(patch.object(lifecycle, 'project_available'))
        self.enterContext(patch.object(lifecycle, 'daemon_arch', return_value='amd64'))
        self.health = self.enterContext(patch.object(installer, 'health'))

    def inspect(self, image):
        return {'Id': 'sha256:' + ('b' if image.endswith('1.0.1-amd64') else 'a') * 64,
                'Architecture': 'amd64', 'Os': 'linux'}

    def fake_run(self, command, target, source=None, destination=None):
        self.calls.append((command, source, destination))
        if self.fail and self.fail(command, target):
            self.fail = None
            raise RuntimeError('simulated failure')
        if destination:
            if destination.name == 'private.tar.gz':
                private_archive(destination)
            elif destination.name == 'database.dump':
                destination.write_bytes(b'PGDMP-dummy-test-stream')
            else:
                destination.write_bytes(b'image test stream')
            destination.chmod(0o600)

    def package(self, version='1.0.1', arch='amd64'):
        directory = self.root / ('stage-' + version + arch)
        directory.mkdir()
        for name in release.RUNTIME:
            path = directory / name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, path)
        (directory / 'image.tar').write_bytes(b'image test stream')
        info = {'format': 1, 'kind': 'release', 'version': version, 'arch': arch, 'schema': 1,
            'postgres_major': 16, 'image': f'wristmind-selfhost:{version}-{arch}',
            'image_id': self.inspect(f'wristmind-selfhost:{version}-{arch}')['Id'],
            'dependencies': {key: 'example/' + key + '@sha256:' + 'c' * 64 for key in ('db', 'caddy', 'tunnel', 'search')}}
        output = self.root / (version + arch + '.tar.gz')
        checksum = release.pack(directory, info, output)
        return output, checksum

    def test_backup_has_database_private_config_and_old_image_without_changing_secrets(self):
        package, checksum = lifecycle.backup(self.target)
        unpacked = self.root / 'unpack'
        unpacked.mkdir()
        info = release.unpack(package, checksum, unpacked)
        self.assertEqual(info['kind'], 'backup')
        self.assertEqual((unpacked / '.env').read_bytes(), self.before)
        self.assertEqual((self.target / '.env').read_bytes(), self.before)
        self.assertEqual(package.stat().st_mode & 0o777, 0o600)
        self.assertEqual(package.parent.stat().st_mode & 0o777, 0o700)
        commands = [call[0] for call in self.calls]
        self.assertTrue(any('pg_dump' in cmd and '-Fc' in cmd for cmd in commands))
        self.assertTrue(any('stop' in cmd for cmd in commands))
        self.assertIn('up', commands[-1])

    def test_backup_failure_restarts_original_services_and_does_not_leave_ready_archive(self):
        self.fail = lambda cmd, target: 'pg_dump' in cmd
        with self.assertRaises(RuntimeError):
            lifecycle.backup(self.target)
        self.assertIn('up', self.calls[-1][0])
        self.assertEqual(list((self.target / 'backups').glob('*.tar.gz')), [])
        self.assertEqual((self.target / '.env').read_bytes(), self.before)

    def test_update_preserves_identity_secrets_changes_only_managed_version_and_pins(self):
        package, checksum = self.package()
        lifecycle.update(self.target, package, checksum)
        values = installer.read_env(self.target)
        for key in ('POSTGRES_PASSWORD', 'WRISTMIND_TOKEN_PEPPER', 'WRISTMIND_SELFHOST_SETUP_TOKEN', 'WRISTMIND_PROJECT_NAME'):
            self.assertEqual(values[key], self.values[key])
        self.assertEqual(values['WRISTMIND_IMAGE'], 'wristmind-selfhost:1.0.1-amd64')
        self.assertIn('@sha256:', values['WRISTMIND_DATABASE_IMAGE'])
        saved = installer.manifest_at(self.target)
        installer.validate_saved(self.target, saved)
        self.assertEqual(saved['release']['version'], '1.0.1')
        self.assertEqual(lifecycle.read_journal(self.target)['phase'], 'ready')
        self.assertEqual(len(list((self.target / 'backups').glob('*.tar.gz'))), 1)

    def test_nightly_final_busy_check_unpauses_without_stopping_writers(self):
        package, checksum = self.package()
        with patch.object(lifecycle, 'auto_idle', return_value=False), patch.object(lifecycle, 'pause') as pause:
            lifecycle.update(self.target, package, checksum, nightly=True)
            self.assertEqual([call.args[-1] for call in pause.call_args_list], [True, False])
        self.assertEqual((self.target / '.env').read_bytes(), self.before)
        self.assertFalse(any('stop' in call[0] for call in self.calls))
        self.assertFalse((self.target / 'backups').exists())

    def test_nightly_final_probe_error_unpauses_without_changing_data(self):
        package, checksum = self.package()
        with patch.object(lifecycle, 'auto_idle', side_effect=RuntimeError('probe failed')), patch.object(lifecycle, 'pause') as pause:
            with self.assertRaises(RuntimeError):
                lifecycle.update(self.target, package, checksum, nightly=True)
            self.assertEqual([call.args[-1] for call in pause.call_args_list], [True, False])
        self.assertEqual((self.target / '.env').read_bytes(), self.before)
        self.assertFalse(any('stop' in call[0] for call in self.calls))

    def test_health_failure_automatically_restores_old_configuration_and_database(self):
        package, checksum = self.package()
        self.health.side_effect = [RuntimeError('bad new API'), None]
        with self.assertRaises(RuntimeError):
            lifecycle.update(self.target, package, checksum)
        self.assertEqual((self.target / '.env').read_bytes(), self.before)
        self.assertNotIn('release', installer.manifest_at(self.target))
        self.assertEqual(lifecycle.read_journal(self.target)['phase'], 'rolled-back')
        commands = [call[0] for call in self.calls]
        self.assertTrue(any('pg_restore' in cmd and '--list' in cmd for cmd in commands))
        self.assertTrue(any('pg_restore' in cmd and '--exit-on-error' in cmd for cmd in commands))
        self.assertTrue(any('dropdb' in cmd and '--force' in cmd for cmd in commands))
        self.assertTrue(any(source and source.name == 'private.tar.gz' for _, source, _ in self.calls))

    def test_failure_of_rollback_retains_recovery_pointer_and_blocks_more_updates(self):
        package, checksum = self.package()
        self.health.side_effect = RuntimeError('unavailable API')
        with self.assertRaises(RuntimeError):
            lifecycle.update(self.target, package, checksum)
        journal = lifecycle.read_journal(self.target)
        self.assertEqual(journal['phase'], 'failed')
        self.assertTrue(Path(journal['recovery']).is_file())
        with self.assertRaises(ValueError):
            lifecycle.update(self.target, package, checksum)
        self.health.side_effect = None
        lifecycle.rollback(self.target, self.data['project'])
        self.assertEqual(lifecycle.read_journal(self.target)['phase'], 'ready')
        self.assertEqual((self.target / '.env').read_bytes(), self.before)

    def test_architecture_and_repeated_version_rejected_before_backup(self):
        package, checksum = self.package(arch='arm64')
        with self.assertRaises(ValueError):
            lifecycle.update(self.target, package, checksum)
        self.assertFalse((self.target / 'backups').exists())
        package, checksum = self.package()
        lifecycle.update(self.target, package, checksum)
        count = len(self.calls)
        with self.assertRaises(ValueError):
            lifecycle.update(self.target, package, checksum)
        self.assertEqual(len(self.calls), count)

    def test_restore_needs_project_confirmation_and_takes_safety_backup(self):
        package, checksum = lifecycle.backup(self.target)
        count = len(self.calls)
        with self.assertRaises(ValueError):
            lifecycle.restore(self.target, package, checksum, 'wrong-project')
        self.assertEqual(len(self.calls), count)
        lifecycle.restore(self.target, package, checksum, self.data['project'])
        self.assertEqual(len(list((self.target / 'backups').glob('*.tar.gz'))), 2)
        self.assertEqual((self.target / '.env').read_bytes(), self.before)

    def test_restore_into_empty_directory_preserves_project_and_encryption_keys(self):
        package, checksum = lifecycle.backup(self.target)
        fresh = self.root / 'recovered'
        lifecycle.restore(fresh, package, checksum, self.data['project'])
        self.assertEqual((fresh / '.env').read_bytes(), self.before)
        self.assertEqual(installer.manifest_at(fresh)['project'], self.data['project'])
        self.assertEqual(lifecycle.read_journal(fresh)['phase'], 'ready')

    def test_interrupted_snapshot_can_restart_without_replacing_data(self):
        lifecycle.write_journal(self.target, phase='backing-up', running=['api', 'worker'], previous={})
        lifecycle.rollback(self.target, self.data['project'])
        self.assertEqual(lifecycle.read_journal(self.target), {})
        self.assertEqual((self.target / '.env').read_bytes(), self.before)
        self.assertEqual(len(self.calls), 2)

    def test_install_release_materializes_cli_without_building_sources(self):
        package, checksum = self.package()
        target = self.root / 'fresh'
        lifecycle.install_release(target, package, checksum, 18080, True)
        data = installer.manifest_at(target)
        self.assertEqual(data['phase'], 'ready')
        installer.validate_saved(target, data)
        self.assertTrue((target / 'selfhost/lifecycle.py').is_file())
        self.assertFalse((target / 'server/src').exists())
        self.assertFalse(any('build' in cmd for cmd, _, _ in self.calls))
        self.assertTrue((target / 'wristmind').stat().st_mode & 0o100)

    def test_cli_routes_package_checksum_and_confirmation_without_shell_execution(self):
        result = subprocess.run([str(ROOT / 'wristmind'), 'restore', '--install-dir', str(self.target),
            '--package', str(self.root / 'missing'), '--sha256', 'a' * 64, '--confirm-project', self.data['project']],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('Укажите --package', result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        self.assertEqual((self.target / '.env').read_bytes(), self.before)


class ArchiveSecurityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def unsafe(self, name, kind=tarfile.REGTYPE):
        package = self.root / 'unsafe.tar.gz'
        with tarfile.open(package, 'w:gz') as archive:
            item = tarfile.TarInfo(name)
            item.type = kind
            item.linkname = '/etc/passwd'
            archive.addfile(item, io.BytesIO(b''))
        output = self.root / 'output'
        output.mkdir()
        with self.assertRaises(ValueError):
            release.unpack(package, release.digest(package), output)
        self.assertEqual(list(output.iterdir()), [])

    def test_traversal_rejected_before_extraction(self):
        self.unsafe('../escape')

    def test_links_rejected_before_extraction(self):
        self.unsafe('compose.yaml', tarfile.SYMTYPE)

    def test_private_archive_checked_before_any_restore(self):
        package = self.root / 'private.tar.gz'
        private_archive(package, True)
        with self.assertRaises(ValueError):
            lifecycle.validate_private(package)

    def test_unknown_schema_is_explicitly_blocked(self):
        with self.assertRaises(ValueError):
            release.metadata({'format': 1, 'kind': 'release', 'version': '1.0.1', 'arch': 'amd64', 'schema': 2})

    def test_download_rejects_cleartext_and_credentials_before_network(self):
        for url in ('http://example.org/package', 'https://user:password@example.org/file'):
            with self.assertRaises(ValueError):
                release.fetch(url, self.root / 'download', 'a' * 64)
        self.assertFalse((self.root / 'download').exists())

    def test_restore_helper_replaces_private_files_and_corrects_owner(self):
        root = self.root / 'private'
        root.mkdir()
        (root / 'obsolete.txt').write_text('old')
        package = self.root / 'private.tar.gz'
        private_archive(package)
        code = lifecycle.RESTORE_CODE.replace("pathlib.Path('/data/private')", f'pathlib.Path({str(root)!r})').replace("pwd.getpwnam('wristmind')", 'pwd.getpwuid(os.getuid())')
        with package.open('rb') as stream:
            result = subprocess.run([sys.executable, '-c', code], stdin=stream, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((root / 'obsolete.txt').exists())
        self.assertEqual((root / 'source.txt').read_bytes(), b'private test content')
        self.assertEqual((root / 'source.txt').stat().st_mode & 0o777, 0o600)

    def test_restore_helper_unsafe_archive_preserves_current_files(self):
        root = self.root / 'private'
        root.mkdir()
        sentinel = root / 'sentinel'
        sentinel.write_text('stay')
        package = self.root / 'private.tar.gz'
        private_archive(package, True)
        code = lifecycle.RESTORE_CODE.replace("pathlib.Path('/data/private')", f'pathlib.Path({str(root)!r})')
        with package.open('rb') as stream:
            result = subprocess.run([sys.executable, '-c', code], stdin=stream, capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sentinel.read_text(), 'stay')

class AdditionalRecoveryTest(unittest.TestCase):
    setUp = LifecycleTest.setUp
    inspect = LifecycleTest.inspect
    fake_run = LifecycleTest.fake_run
    package = LifecycleTest.package

    def test_failed_fresh_install_can_resume_same_artifact_without_regenerating_credentials(self):
        package, checksum = self.package()
        target = self.root / 'resumable'
        self.health.side_effect = RuntimeError('API not ready')
        with self.assertRaises(RuntimeError):
            lifecycle.install_release(target, package, checksum, 18080, True)
        before = (target / '.env').read_bytes()
        self.assertEqual(installer.manifest_at(target)['phase'], 'failed')
        self.health.side_effect = None
        lifecycle.install_release(target, package, checksum, 18080, True, resume=True)
        self.assertEqual((target / '.env').read_bytes(), before)
        self.assertEqual(installer.manifest_at(target)['phase'], 'ready')

    def test_restore_refuses_a_different_existing_project_without_modification(self):
        package, checksum = lifecycle.backup(self.target)
        other = self.root / 'other'
        installer.prepare(other, SimpleNamespace(port=8080, bind=None, demo=True))
        before = (other / '.env').read_bytes()
        with self.assertRaises(ValueError):
            lifecycle.restore(other, package, checksum, self.data['project'])
        self.assertEqual((other / '.env').read_bytes(), before)

    def test_outer_checksum_failure_does_not_run_docker_or_create_backup(self):
        package, _ = self.package()
        with self.assertRaises(ValueError):
            lifecycle.update(self.target, package, '0' * 64)
        self.assertEqual(self.calls, [])
        self.assertFalse((self.target / 'backups').exists())

    def test_remove_cli_requires_confirmation_before_docker(self):
        result = subprocess.run([str(ROOT / 'wristmind'), 'remove', '--install-dir', str(self.target)],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertIn('--confirm-project', result.stderr)
        self.assertEqual((self.target / '.env').read_bytes(), self.before)

    def test_version_cli_exposes_no_keys_and_displays_project(self):
        result = subprocess.run([str(ROOT / 'wristmind'), 'version', '--install-dir', str(self.target)],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertIn(self.data['project'], result.stdout)
        self.assertNotIn(self.values['WRISTMIND_TOKEN_PEPPER'], result.stdout + result.stderr)
        self.assertNotIn(self.values['WRISTMIND_SELFHOST_SETUP_TOKEN'], result.stdout + result.stderr)

if __name__ == '__main__':
    unittest.main()

    def test_backup_selection_confirmation_and_sidecar_integrity(self):
        package, checksum = lifecycle.backup(self.target)
        self.assertEqual(package.with_name(package.name + '.sha256').read_text().split(), [checksum, package.name])
        calls = len(self.calls)
        with patch('builtins.input', side_effect=['wrong', '1', 'нет']):
            self.assertIsNone(lifecycle.choose_backup(self.target))
        self.assertEqual(len(self.calls), calls)
        with patch('builtins.input', side_effect=['1', 'да']):
            self.assertEqual(lifecycle.choose_backup(self.target), (package, checksum, self.data['project']))
        self.assertEqual(len(self.calls), calls)
        package.with_name(package.name + '.sha256').write_text('f' * 64 + '  ' + package.name)
        with patch('builtins.input', side_effect=['1']):
            with self.assertRaises(ValueError):
                lifecycle.choose_backup(self.target)

    def test_legacy_backups_without_sidecar_and_empty_list(self):
        self.assertIsNone(lifecycle.choose_backup(self.target))
        package, checksum = lifecycle.backup(self.target)
        package.with_name(package.name + '.sha256').unlink()
        with patch('builtins.input', side_effect=['1', 'да']):
            self.assertEqual(lifecycle.choose_backup(self.target), (package, checksum, self.data['project']))
        with patch('builtins.input', return_value='0'):
            self.assertIsNone(lifecycle.choose_backup(self.target))


class OciIdentityTest(unittest.TestCase):
    def test_config_and_oci_identity_are_linked_not_merely_accepted(self):
        import hashlib
        config = 'sha256:' + 'a' * 64
        blob = json.dumps({'schemaVersion': 2, 'config': {'digest': config}}).encode()
        oci = 'sha256:' + hashlib.sha256(blob).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            image = target / 'image.tar'
            with tarfile.open(image, 'w') as archive:
                member = tarfile.TarInfo('blobs/sha256/' + oci[7:])
                member.size = len(blob)
                archive.addfile(member, io.BytesIO(blob))
            manifest = {'image': 'test', 'image_id': config, 'arch': 'amd64'}
            with patch.object(release, 'inspect_image', return_value={'Id': oci, 'Architecture': 'amd64', 'Os': 'linux'}):
                lifecycle.check_image(target, manifest, image)
                with self.assertRaises(ValueError):
                    lifecycle.check_image(target, {**manifest, 'image_id': 'sha256:' + 'b' * 64}, image)
                with self.assertRaises(ValueError):
                    lifecycle.check_image(target, {**manifest, 'arch': 'arm64'}, image)
            with patch.object(release, 'inspect_image', return_value={'Id': config, 'Architecture': 'amd64', 'Os': 'linux'}):
                lifecycle.check_image(target, {**manifest, 'image_id': oci}, image)
