import asyncio
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'server/src'))
from wristmind_server import selfhost_maintenance as maintenance


class MaintenanceTest(unittest.TestCase):
    def test_api_and_websocket_pause_but_health_still_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            settings = SimpleNamespace(selfhost_enabled=True, storage_dir=Path(temp))
            (settings.storage_dir / '.wristmind-maintenance').touch()
            app = AsyncMock()
            wrapped = maintenance.MaintenanceBoundary(app)
            send = AsyncMock()
            with patch.object(maintenance, 'get_settings', return_value=settings):
                asyncio.run(wrapped({'type': 'http', 'method': 'POST', 'path': '/v1/chats'}, AsyncMock(), send))
                self.assertEqual(send.call_args_list[0].args[0]['status'], 503)
                app.assert_not_called()
                send.reset_mock()
                asyncio.run(wrapped({'type': 'websocket', 'path': '/v1/events'}, AsyncMock(), send))
                self.assertEqual(send.call_args.args[0]['code'], 1013)
                asyncio.run(wrapped({'type': 'http', 'path': '/health'}, AsyncMock(), send))
                self.assertEqual(app.call_count, 1)
                (settings.storage_dir / '.wristmind-maintenance').unlink()
                asyncio.run(wrapped({'type': 'http', 'path': '/v1/chats'}, AsyncMock(), send))
                self.assertEqual(app.call_count, 2)

    def test_original_non_selfhost_runtime_is_unaffected_even_if_marker_exists(self):
        with tempfile.TemporaryDirectory() as temp:
            settings = SimpleNamespace(selfhost_enabled=False, storage_dir=Path(temp))
            (settings.storage_dir / '.wristmind-maintenance').touch()
            self.assertFalse(maintenance.maintenance_active(settings))

    def test_worker_does_not_claim_or_send_jobs_during_maintenance(self):
        from wristmind_server import worker
        with tempfile.TemporaryDirectory() as temp:
            settings = SimpleNamespace(selfhost_enabled=True, storage_dir=Path(temp))
            (settings.storage_dir / '.wristmind-maintenance').touch()
            with patch.object(worker, 'settings', settings), patch.object(worker, 'claim_job', new_callable=AsyncMock) as claim:
                self.assertFalse(asyncio.run(worker.process_next_job()))
                claim.assert_not_called()

if __name__ == '__main__':
    unittest.main()
