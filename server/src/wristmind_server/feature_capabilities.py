"""Self-host switches enforce server boundaries; clients receive no credentials."""
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from typing import Literal
from .provider_registry import PrivateInputRoute
from sqlalchemy.ext.asyncio import AsyncSession
from .config import Settings, get_settings
from .db_models import Device
from .database import get_session
from .security import admin_device, current_device
from .selfhost_runtime import refresh_runtime
from .model_capabilities import selected
from .resource_estimate import inspect_resources

router = APIRouter(route_class=PrivateInputRoute)
LABELS = {'web_search':'Веб-поиск', 'digitization':'Оцифровка', 'rag':'Поиск по источникам (RAG)', 'voice':'Голосовой ввод'}


def enabled(settings, feature):
    return not settings.selfhost_enabled or settings.selfhost_features.get(feature, True)


def capabilities(settings):
    rows = {}
    for name in LABELS:
        on = enabled(settings, name)
        ready = True; reason = 'Готово'
        if name == 'web_search' and not (settings.searxng_url if settings.search_provider == 'searxng' else settings.search_api_key):
            ready = False; reason = 'Веб-поиск ещё не настроен. Выполните команду автоматической настройки.'
        if name == 'digitization':
            reason = 'Чтение печатного текста доступно. Для понимания изображений и сложных страниц добавьте модель для изображений' if settings.selfhost_enabled and not selected(settings, 'vision') else 'Чтение текста и понимание изображений доступны'
        if name == 'voice' and settings.selfhost_enabled and not selected(settings, 'speech'):
            ready = False; reason = 'Добавьте модель распознавания голоса. На часах доступна системная диктовка'
        if name == 'rag' and settings.selfhost_enabled and not selected(settings, 'embedding'):
            reason = 'Поиск по словам доступен. Чтобы находить похожие по смыслу фрагменты, добавьте модель поиска по смыслу'
        rows[name] = {'enabled':on, 'available':on and ready, 'reason':reason if on else 'Отключено в настройках сервера'}
    return {'selfhost':settings.selfhost_enabled, 'features':rows, 'search_provider':settings.search_provider,
            'vision': bool(selected(settings, 'vision')) if settings.selfhost_enabled else bool(settings.deepseek_api_key),
            'speech_mode':'system' if not rows['voice']['available'] else 'streaming' if settings.yandex_speechkit_api_key else 'buffered'}


def resource_view(settings):
    resources = inspect_resources(settings.storage_dir)
    if settings.search_provider != 'searxng':
        resources['recommendations']['web_search'] = True
    return resources


def require(settings, feature):
    row = capabilities(settings)['features'][feature]
    if not row['available']: raise HTTPException(409, row['reason'])

class Features(BaseModel):
    model_config = ConfigDict(extra='forbid')
    web_search: bool
    digitization: bool
    rag: bool
    voice: bool

@router.get('/v1/capabilities')
async def read_capabilities(response: Response, _: Device = Depends(current_device), settings: Settings = Depends(get_settings)):
    refresh_runtime(settings)
    response.headers['Cache-Control'] = 'no-store'
    return capabilities(settings)

@router.get('/v1/selfhost/features')
async def read_features(_: Device = Depends(admin_device), settings: Settings = Depends(get_settings)):
    if not settings.selfhost_enabled: raise HTTPException(404)
    refresh_runtime(settings)
    return {**capabilities(settings), 'resources': resource_view(settings)}

@router.put('/v1/selfhost/features')
async def update_features(body: Features, _: Device = Depends(admin_device), session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)):
    if not settings.selfhost_enabled: raise HTTPException(404)
    from .provider_registry import locked_config, snapshot, persist
    await locked_config(session, settings)
    values = snapshot(settings)
    values['selfhost_features'] = body.model_dump()
    await persist(session, settings, values)
    return {**capabilities(settings), 'resources': resource_view(settings)}


class SearchConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    provider: Literal['searxng', 'yandex', 'brave', 'tavily']
    api_key: SecretStr | None = Field(default=None, max_length=1000)
    folder_id: str = Field(default='', max_length=50, pattern=r'^[A-Za-z0-9_-]*$')


def public_search_config(settings):
    return {'provider': settings.search_provider, 'has_key': bool(settings.search_api_key), 'folder_id': settings.search_folder_id}

@router.get('/v1/selfhost/search')
async def read_search(_: Device = Depends(admin_device), settings: Settings = Depends(get_settings)):
    if not settings.selfhost_enabled: raise HTTPException(404)
    refresh_runtime(settings)
    return public_search_config(settings)

@router.put('/v1/selfhost/search')
async def update_search(body: SearchConfig, _: Device = Depends(admin_device), session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)):
    if not settings.selfhost_enabled: raise HTTPException(404)
    from .provider_registry import locked_config, snapshot, persist
    await locked_config(session, settings)
    refresh_runtime(settings)
    values = snapshot(settings)
    key = body.api_key.get_secret_value().strip() if body.api_key else ''
    if not key and body.provider == settings.search_provider and settings.search_api_key:
        key = settings.search_api_key.get_secret_value()
    if body.provider != 'searxng' and not key:
        raise HTTPException(422, 'Введите ключ выбранного поискового API.')
    if body.provider == 'yandex' and not body.folder_id:
        raise HTTPException(422, 'Для Yandex Search API нужен ID каталога (folder ID).')
    values.update(search_provider=body.provider, search_api_key=key if body.provider != 'searxng' else '', search_folder_id=body.folder_id if body.provider == 'yandex' else '')
    await persist(session, settings, values)
    return public_search_config(settings)
