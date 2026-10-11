"""Admin-managed connections and explicitly installed models, shared by both editions."""
import asyncio
import secrets
import hashlib
import time
from collections import OrderedDict
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from . import account_events
from .config import Settings, get_settings, ModelOption
from .database import get_session
from .db_models import AppSettings, Device, Mode
from .provider_connections import PRESETS, PRESET_MAP, ProviderConnection, CatalogError, discover_models, public_connection, safe_url
from .providers import ProviderRouter, ProviderError
from .model_capabilities import ROLES, probe_role
from .security import admin_device
from .selfhost_runtime import read_runtime, write_runtime, refresh_runtime

class PrivateInputRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def private_handler(request):
            try:
                return await handler(request)
            except RequestValidationError:
                raise HTTPException(422, 'Проверьте поля: провайдер, URL, название и ID модели. Недопустимые значения или слишком длинный текст.') from None
        return private_handler

router = APIRouter(tags=['Provider settings'], route_class=PrivateInputRoute)
_CATALOG_CACHE = OrderedDict()

async def cached_catalog(item, demo):
    fingerprint = hashlib.sha256((item.kind + item.base_url + item.api_key.get_secret_value() + str(demo)).encode()).hexdigest()
    cached = _CATALOG_CACHE.get(fingerprint)
    if cached and time.monotonic() - cached[0] < 60:
        return cached[1]
    rows = await discover(item, demo)
    _CATALOG_CACHE[fingerprint] = (time.monotonic(), rows)
    _CATALOG_CACHE.move_to_end(fingerprint)
    while len(_CATALOG_CACHE) > 32: _CATALOG_CACHE.popitem(last=False)
    return rows

async def discover(connection, demo):
    try:
        return await asyncio.wait_for(discover_models(connection, demo), 20)
    except TimeoutError:
        raise CatalogError('Каталог не ответил вовремя. Повторите или укажите ID вручную.', manual_allowed=True) from None

class ConnectionInput(BaseModel):
    kind: str = Field(max_length=30)
    label: str = Field(default='', max_length=80)
    api_key: SecretStr = Field(default=SecretStr(''), max_length=1000)
    base_url: str = Field(default='', max_length=300)
    allow_local: bool = False

class ConnectionUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=80)
    api_key: SecretStr | None = Field(default=None, max_length=1000)
    enabled: bool | None = None

class InstallModel(BaseModel):
    provider_id: str = Field(max_length=40)
    model_id: str = Field(pattern=r'^[A-Za-z0-9@][A-Za-z0-9._:/+@-]{0,119}$')
    label: str = Field(default='', max_length=80)
    use_default: bool = False
    roles: list[str] = Field(default=['text'], min_length=1, max_length=4)

class RoleAssignment(BaseModel):
    identity: str = Field(max_length=180)

class ModelUpdate(BaseModel):
    enabled: bool | None = None
    use_default: bool = False
    label: str | None = Field(default=None, min_length=1, max_length=80)


def snapshot(settings):
    values = read_runtime(settings)
    if 'providers' not in values:
        # Preserve the existing installation's configured IDs. Fresh self-host installs
        # have an empty allowed_models list and never automatically import a catalog.
        providers = []
        for kind in dict.fromkeys(m.provider for m in settings.allowed_models):
            if kind not in {'openrouter', 'deepseek', 'gigachat'}:
                continue
            key = getattr(settings, kind + ('_credentials' if kind == 'gigachat' else '_api_key'), None)
            providers.append({'id': kind, 'kind': kind, 'label': {'openrouter': 'OpenRouter', 'deepseek': 'DeepSeek', 'gigachat': 'GigaChat'}[kind],
                              'base_url': getattr(settings, kind + '_base_url'), 'api_key': key.get_secret_value() if key else '', 'enabled': True})
        values['providers'] = providers
        values['models'] = [{**m.model_dump(), 'enabled': True} for m in settings.allowed_models]
    return values

async def locked_config(session, settings):
    # Lock one durable row across API processes; SQLite's insert obtains a write lock.
    if session.bind.dialect.name == 'postgresql':
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    await session.execute(insert(AppSettings).values(id=1, default_model_id=settings.default_model_id).on_conflict_do_nothing(index_elements=['id']))
    return await session.scalar(select(AppSettings).where(AppSettings.id == 1).with_for_update())

async def persist(session, settings, values):
    write_runtime(settings, values)
    account_events.record_account_event(session, account_events.SETTINGS_UPDATED, {})
    await session.commit()
    refresh_runtime(settings)


def connection(values, identity):
    row = next((p for p in values['providers'] if p['id'] == identity and not p.get('deleted')), None)
    if row is None:
        raise HTTPException(404, 'Провайдер не найден')
    return ProviderConnection.model_validate(row)

async def guard_disable(session, identities, config):
    used = await session.scalar(select(Mode.id).where(Mode.deleted_at.is_(None), Mode.response_model_id.in_(identities)).limit(1))
    if config.default_model_id in identities or used:
        raise HTTPException(409, 'Модель используется по умолчанию или в режиме. Сначала выберите другую модель в настройках и режимах.')

async def choose_default(session, settings, values, config, identity):
    config.default_model_id = identity
    for field in ('default_model_id', 'quick_chat_model_id', 'router_model_id', 'title_model_id'):
        values[field] = identity
    # Only the self-host wizard owns this row; imported legacy chats/modes remain intact.
    if getattr(settings, 'selfhost_enabled', False):
        from .db_models import SelfHostAdmin
        admin = await session.get(SelfHostAdmin, 1)
        if admin:
            admin.probe_passed = False

async def probe(settings, identity, candidate=None):
    async def collect():
        router = ProviderRouter(candidate or settings)
        try:
            parts = []
            async for part in router.stream_answer(identity, [{'role': 'user', 'content': 'Ответь кратко: ОК'}], thinking=False, max_tokens=256):
                parts.append(part)
                if sum(map(len, parts)) > 8000:
                    break
            if not ''.join(parts).strip():
                raise ProviderError('Empty answer')
        finally:
            await router.aclose()
    try:
        await asyncio.wait_for(collect(), 30)
    except (ProviderError, TimeoutError, OSError):
        raise HTTPException(502, 'Модель не ответила. Проверьте ID, ключ, баланс и доступность провайдера; повторите.') from None

@router.get('/v1/provider-settings')
async def read_settings(response: Response, _: Device = Depends(admin_device), session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)):
    response.headers['Cache-Control'] = 'no-store'
    values = snapshot(settings)
    config = await session.get(AppSettings, 1)
    return {'presets': PRESETS, 'providers': [public_connection(ProviderConnection.model_validate(p)) for p in values['providers'] if not p.get('deleted')],
            'models': [m for m in values['models'] if not m.get('deleted')], 'default_model_id': config.default_model_id if config else settings.default_model_id, 'demo': settings.mock_providers, 'model_roles': values.get('model_roles', {}), 'selfhost': settings.selfhost_enabled}

@router.post('/v1/providers')
async def add_provider(payload: ConnectionInput, _: Device = Depends(admin_device), session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)):
    preset = PRESET_MAP.get(payload.kind)
    if not preset:
        raise HTTPException(422, 'Выберите провайдера из списка')
    try:
        url = safe_url(payload.base_url if payload.kind == 'compatible' else preset['url'], payload.allow_local)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    key = payload.api_key.get_secret_value().strip()
    if not key and not settings.mock_providers and not (payload.kind == 'compatible' and payload.allow_local):
        raise HTTPException(422, 'Введите ключ провайдера')
    await locked_config(session, settings)
    values = snapshot(settings)
    if sum(not p.get('deleted') for p in values['providers']) >= 32:
        raise HTTPException(409, 'Достигнут предел: 32 подключения')
    item = ProviderConnection(id='p_' + secrets.token_hex(6), kind=payload.kind, label=payload.label.strip() or preset['label'], base_url=url, api_key=SecretStr(key), allow_local=payload.allow_local)
    warning = ''
    try:
        await discover(item, settings.mock_providers)
    except CatalogError as error:
        if error.authentication:
            raise HTTPException(422, str(error)) from None
        warning = str(error)
    values['providers'].append({**item.model_dump(exclude={'api_key'}), 'api_key': key})
    await persist(session, settings, values)
    return {'provider': public_connection(item), 'warning': warning}

@router.delete('/v1/providers/{identity}')
async def delete_provider(identity: str, _: Device = Depends(admin_device), session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)):
    config = await locked_config(session, settings)
    values = snapshot(settings)
    connection(values, identity)
    identities = [m['id'] for m in values['models'] if m['provider'] == identity]
    await guard_disable(session, identities, config)
    for row in values['providers']:
        if row['id'] == identity:
            row.update(deleted=True, enabled=False, api_key='')
    for row in values['models']:
        if row['provider'] == identity:
            row.update(deleted=True, enabled=False)
    values['model_roles'] = {role: model for role, model in values.get('model_roles', {}).items() if model not in identities}
    await persist(session, settings, values)
    return {'ok': True}

@router.patch('/v1/providers/{identity}')
async def update_provider(identity: str, payload: ConnectionUpdate, _: Device = Depends(admin_device), session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)):
    config = await locked_config(session, settings)
    values = snapshot(settings); item = connection(values, identity)
    if payload.enabled is False:
        await guard_disable(session, [m['id'] for m in values['models'] if m['provider'] == identity], config)
    if payload.api_key and payload.api_key.get_secret_value().strip():
        if item.kind == 'gigachat':
            raise HTTPException(422, 'Ключ GigaChat этой установки задаётся в конфигурации сервера')
        item.api_key = SecretStr(payload.api_key.get_secret_value().strip())
        try:
            await discover(item, settings.mock_providers)
        except CatalogError as error:
            if error.authentication:
                raise HTTPException(422, str(error)) from None
    if payload.enabled is not None: item.enabled = payload.enabled
    if payload.label is not None:
        if not payload.label.strip(): raise HTTPException(422, 'Введите название')
        item.label = payload.label.strip()
    values['providers'] = [{**item.model_dump(exclude={'api_key'}), 'api_key': item.api_key.get_secret_value()} if p['id'] == identity else p for p in values['providers']]
    await persist(session, settings, values)
    return public_connection(item)

@router.get('/v1/providers/{identity}/catalog')
async def catalog(identity: str, response: Response, query: str = '', _: Device = Depends(admin_device), settings: Settings = Depends(get_settings)):
    response.headers['Cache-Control'] = 'no-store'
    item = connection(snapshot(settings), identity)
    if not item.enabled: raise HTTPException(409, 'Провайдер выключен')
    try:
        rows = await cached_catalog(item, settings.mock_providers)
    except CatalogError as error:
        if error.authentication: raise HTTPException(422, str(error)) from None
        return {'models': [], 'total': 0, 'warning': str(error)}
    filtered = [m for m in rows if query[:120].casefold() in (m['id'] + ' ' + m['label']).casefold()]
    return {'models': filtered[:200], 'total': len(filtered), 'warning': ''}

@router.post('/v1/models/installed')
async def install_model(payload: InstallModel, _: Device = Depends(admin_device), session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)):
    config = await locked_config(session, settings)
    values = snapshot(settings); item = connection(values, payload.provider_id)
    if not item.enabled: raise HTTPException(409, 'Сначала включите провайдера')
    if len(values['models']) >= 200: raise HTTPException(409, 'Достигнут предел: 200 добавленных моделей')
    identity = item.id + ':' + payload.model_id
    candidate = settings.model_copy(deep=True)
    candidate.provider_connections = [ProviderConnection.model_validate(p) for p in values['providers']]
    candidate.allowed_models.append(ModelOption(id=identity, provider=item.id, label=payload.label.strip() or payload.model_id))
    roles = list(dict.fromkeys(payload.roles))
    if set(roles) - ROLES or (payload.use_default and 'text' not in roles):
        raise HTTPException(422, 'Выберите допустимое назначение модели; по умолчанию нужна текстовая модель')
    if item.kind == 'deepseek' and roles != ['text']:
        raise HTTPException(422, 'DeepSeek поддерживает только текстовые ответы. Для Vision, голоса или embeddings выберите другого провайдера.')
    if item.kind == 'yandex' and roles != ['speech']:
        raise HTTPException(422, 'SpeechKit поддерживает только распознавание голоса')
    if 'text' in roles: await probe(settings, identity, candidate)
    for role in roles:
        if role != 'text':
            try: await asyncio.wait_for(probe_role(settings, item, payload.model_id, role), 35)
            except (ProviderError, TimeoutError, OSError):
                raise HTTPException(502, 'Модель не поддерживает выбранную функцию или не ответила. Проверьте ID, ключ и баланс.') from None
    model = next((m for m in values['models'] if m['id'] == identity), None)
    if model is None:
        model = {'id': identity, 'provider': item.id, 'label': payload.label.strip() or payload.model_id, 'enabled': True, 'roles': roles}
        values['models'].append(model)
    else:
        model['enabled'] = True
        model['roles'] = list(dict.fromkeys(model.get('roles', ['text']) + roles))
    for role in roles:
        if role != 'text': values.setdefault('model_roles', {}).setdefault(role, identity)
    if 'text' in roles and (payload.use_default or not settings.allowed_models):
        await choose_default(session, settings, values, config, identity)
    await persist(session, settings, values)
    return model

@router.patch('/v1/models/installed/{identity:path}')
async def update_model(identity: str, payload: ModelUpdate, _: Device = Depends(admin_device), session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)):
    config = await locked_config(session, settings)
    values = snapshot(settings); model = next((m for m in values['models'] if m['id'] == identity), None)
    if model is None: raise HTTPException(404, 'Добавленная модель не найдена')
    item = connection(values, model['provider'])
    if payload.enabled is False: await guard_disable(session, [identity], config)
    if payload.use_default and 'text' not in model.get('roles', ['text']):
        raise HTTPException(422, 'Для ответов нужна текстовая модель')
    if payload.use_default and (not item.enabled or payload.enabled is False or (not model.get('enabled', True) and payload.enabled is not True)):
        raise HTTPException(409, 'Сначала включите модель и провайдера')
    if payload.enabled is not None: model['enabled'] = payload.enabled
    if payload.label is not None:
        if not payload.label.strip(): raise HTTPException(422, 'Введите название')
        model['label'] = payload.label.strip()
    if payload.use_default: await choose_default(session, settings, values, config, identity)
    await persist(session, settings, values)
    return model


@router.put('/v1/model-roles/{role}')
async def assign_role(role: str, payload: RoleAssignment, _: Device = Depends(admin_device), session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)):
    if role not in ROLES - {'text'}: raise HTTPException(422, 'Недопустимое назначение')
    await locked_config(session, settings)
    values = snapshot(settings)
    if payload.identity:
        model = next((m for m in values['models'] if m['id'] == payload.identity and m.get('enabled', True) and role in m.get('roles', ['text'])), None)
        if not model or not connection(values, model['provider']).enabled:
            raise HTTPException(422, 'Сначала добавьте и проверьте модель с нужным назначением')
        values.setdefault('model_roles', {})[role] = payload.identity
    else: values.setdefault('model_roles', {}).pop(role, None)
    await persist(session, settings, values)
    return {'model_roles': values['model_roles']}
