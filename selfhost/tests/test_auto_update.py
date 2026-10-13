"""Nightly update contracts; no real systemd, Docker, downloads or server mutation."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'selfhost'))
import lifecycle


class AutoUpdateTest(unittest.TestCase):
    def test_default_disabled_and_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'missing'
            with patch.object(lifecycle.subprocess, 'run') as run:
                self.assertEqual(lifecycle.auto_run(target), 0)
                run.assert_not_called()
                self.assertFalse(target.exists())

    def test_calendar_is_in_users_timezone_and_does_not_catch_up_during_day(self):
        target = Path('/opt/wristmind')
        service, timer = lifecycle.auto_unit_files(target, '04:00', 'Europe/Moscow')
        self.assertIn('OnCalendar=*-*-* 04:00:00 Europe/Moscow', timer)
        self.assertIn('Persistent=false', timer)
        self.assertIn('--auto-update run --install-dir "/opt/wristmind"', service)
        self.assertIn('TimeoutStartSec=2h', service)
        self.assertNotEqual(lifecycle.auto_unit_name(target), lifecycle.auto_unit_name(Path('/opt/another')))
        for time, zone in [('25:00','UTC'),('4:00','UTC'),('04:00','../UTC'),('04:00','No/SuchZone'),('04:00\nExecStart=x','UTC')]:
            with self.assertRaises(ValueError):
                lifecycle.auto_validate_schedule(time, zone)
        with self.assertRaises(ValueError):
            lifecycle.auto_quote_unit('/tmp/x\nExecStart=x')
        self.assertEqual(lifecycle.auto_quote_unit('/opt/a %i'), '"/opt/a %%i"')

    def test_busy_jobs_skip_without_download_or_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            with patch.object(lifecycle, 'auto_settings', return_value={'enabled':True}), \
                 patch.object(lifecycle, 'ensure_idle'), patch.object(lifecycle, 'auto_idle', return_value=False), \
                 patch.object(lifecycle.subprocess, 'run') as run:
                self.assertEqual(lifecycle.auto_run(target), 0)
                run.assert_not_called()

    def test_existing_updater_owns_hash_backup_and_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            with patch.object(lifecycle, 'auto_settings', return_value={'enabled':True}), \
                 patch.object(lifecycle, 'ensure_idle'), patch.object(lifecycle, 'auto_idle', return_value=True), \
                 patch.object(lifecycle.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
                self.assertEqual(lifecycle.auto_run(target), 0)
                args = run.call_args.args[0]
                self.assertIn(str(target / 'selfhost/lifecycle.py'), args)
                self.assertIn('--latest', args)
                self.assertIn('--nightly', args)

    def test_failed_or_unknown_probe_never_means_idle(self):
        with patch.object(lifecycle, 'state', return_value=({'project':'wristmind-0123456789ab'}, {})), \
             patch.object(lifecycle, 'command', return_value=['docker']), \
             patch.object(lifecycle.subprocess, 'run', return_value=subprocess.CompletedProcess([],0,stdout='unexpected')):
            with self.assertRaises(ValueError):
                lifecycle.auto_idle(Path('/opt/wristmind'))

    def test_configuration_units_enable_disable_without_real_systemd(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'installation'; target.mkdir()
            (target / 'selfhost').mkdir(); (target / 'selfhost/lifecycle.py').write_text('def auto_main(): pass')
            units = Path(tmp) / 'units'; units.mkdir()
            original = Path.exists
            with patch.object(lifecycle, 'state'), patch.object(lifecycle, 'UNITS', units), \
                 patch.object(lifecycle.os, 'geteuid', return_value=0), patch.object(lifecycle, 'auto_show'), \
                 patch.object(Path, 'exists', lambda p: True if str(p) == '/run/systemd/system' else original(p)), \
                 patch.object(lifecycle, 'auto_systemctl') as systemctl:
                lifecycle.auto_configure(target, True, '04:00', 'Europe/Moscow')
                config = lifecycle.auto_settings(target)
                self.assertTrue(config['enabled'])
                timer = units / (lifecycle.auto_unit_name(target) + '.timer')
                self.assertIn('Europe/Moscow', timer.read_text())
                systemctl.assert_any_call('enable','--now', timer.name)
                lifecycle.auto_configure(target, False, '04:00', 'Europe/Moscow')
                self.assertFalse(lifecycle.auto_settings(target)['enabled'])
                systemctl.assert_any_call('disable','--now', timer.name)

if __name__ == '__main__':
    unittest.main()
