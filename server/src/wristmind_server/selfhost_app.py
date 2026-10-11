"""Self-hosting API, protected first-run wizard and existing panel delivery."""
import os
from pathlib import Path

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.exception_handlers import request_validation_exception_handler

from .config import get_settings
from .main import app
from .selfhost_setup import router
from .selfhost_maintenance import MaintenanceBoundary
from .web_host import mount_panel

get_settings().selfhost_enabled = True
app.include_router(router)
app.add_middleware(MaintenanceBoundary)


@app.middleware('http')
async def selfhost_boundary(request, call_next):
    path = request.url.path
    if path == '/v1/devices/admin/enroll':
        return JSONResponse({'detail': 'Для этой установки используйте вход с паролем'}, status_code=403)
    if request.method not in {'GET', 'HEAD', 'OPTIONS'} and (path.startswith('/v1/selfhost/') or request.cookies.get('wm_session')):
        origin = request.headers.get('origin')
        # Trust neither caller-supplied forwarded hosts nor cross-site form posts.
        allowed = {str(request.base_url).rstrip('/'), get_settings().public_base_url.rstrip('/')}
        if request.headers.get('x-wristmind-csrf') != '1' or (origin and origin not in allowed) or request.headers.get('sec-fetch-site') == 'cross-site':
            return JSONResponse({'detail': 'Проверка запроса не пройдена'}, status_code=403)
    response = await call_next(request)
    if path.startswith('/v1/selfhost/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.exception_handler(RequestValidationError)
async def safe_validation(request, exc):
    if request.url.path == '/v1/selfhost/features':
        return JSONResponse({'detail':'Проверьте переключатели функций'}, status_code=422)
    if request.url.path.startswith('/v1/selfhost/'):
        return JSONResponse({'detail': 'Проверьте поля формы. Пароль должен содержать от 12 до 256 символов; имя не должно быть пустым.'}, status_code=422)
    return await request_validation_exception_handler(request, exc)


mount_panel(app, Path(os.environ.get('WRISTMIND_WEB_DIST', '/app/web-dist')))
