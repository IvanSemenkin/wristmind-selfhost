"""Serve the existing built panel alongside the API in self-hosted installs."""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.routing import APIRoute
from starlette.routing import Match
from starlette.types import Scope


_RESERVED = {'v1', 'health', 'docs', 'redoc', 'openapi.json', 'assets'}


class _PanelRoute(APIRoute):
    def matches(self, scope: Scope):
        # Leave API routing (including 405/Allow for wrong methods) untouched.
        path = scope.get('path', '').lstrip('/')
        if path.split('/')[0] in _RESERVED:
            return Match.NONE, {}
        return super().matches(scope)


def mount_panel(app: FastAPI, directory: Path) -> None:
    root = directory.resolve()
    if not (root / 'index.html').is_file() or not (root / 'assets').is_dir():
        raise RuntimeError('Web panel build is missing: build the self-hosting image first')
    # StaticFiles checks traversal and emits 404 for missing JS/CSS, never HTML.
    app.mount('/assets', StaticFiles(directory=root / 'assets'), name='panel-assets')

    async def panel(panel_path: str):
        parts = panel_path.split('/')
        if any(part.startswith('.') for part in parts if part):
            raise HTTPException(status_code=404, detail='Not found')
        target = (root / panel_path).resolve()
        if not target.is_relative_to(root):
            raise HTTPException(status_code=404, detail='Not found')
        if target.is_file():
            return FileResponse(target, headers={'Cache-Control': 'no-cache'})
        # A missing public file must not be a successful HTML response either.
        if Path(panel_path).suffix:
            raise HTTPException(status_code=404, detail='Not found')
        return FileResponse(root / 'index.html', headers={'Cache-Control': 'no-cache'})

    app.router.add_api_route('/{panel_path:path}', panel, methods=['GET', 'HEAD'],
                             include_in_schema=False, route_class_override=_PanelRoute)
