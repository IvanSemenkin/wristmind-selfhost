"""Shared private-volume pause for self-host API and worker during CLI maintenance."""
from .config import get_settings
from fastapi.responses import JSONResponse


def maintenance_active(settings=None):
    settings = settings or get_settings()
    return settings.selfhost_enabled and (settings.storage_dir / '.wristmind-maintenance').exists()


class MaintenanceBoundary:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] in {'http', 'websocket'} and scope.get('path') != '/health' and maintenance_active():
            if scope['type'] == 'websocket':
                await send({'type': 'websocket.close', 'code': 1013})
            else:
                response = JSONResponse({'detail': 'Система временно обслуживается. Повторите запрос после завершения обновления.'},
                                        status_code=503, headers={'Retry-After': '30', 'Cache-Control': 'no-store'})
                await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
