"""First-run wizard and password sessions; mounted only by selfhost_app."""
import asyncio
import hashlib
import hmac
import secrets
import threading
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings, get_settings
from .database import get_session
from .db_models import Device, Mode, SelfHostAdmin, SelfHostWebSession, User, utcnow
from .providers import ProviderError, ProviderRouter
from .security import admin_device, current_device, hash_secret, issue_device_token
from .selfhost_runtime import read_runtime

router = APIRouter(prefix='/v1/selfhost', tags=['Self hosting'])
SESSION_SECONDS = 12 * 60 * 60
_PASSWORD_SLOTS = threading.Semaphore(2)


class CreateAdmin(BaseModel):
    login: str = Field(min_length=1, max_length=80)
    password: SecretStr = Field(min_length=12, max_length=256)


class Login(BaseModel):
    login: str = Field(min_length=1, max_length=80)
    password: SecretStr = Field(min_length=1, max_length=256)


class FirstMode(BaseModel):
    name: str = Field(default='Помощник', min_length=1, max_length=80)
    prompt: str = Field(default='Помогай понятно и по делу. Объясняй решение, когда это полезно.', max_length=8000)


class ProbeQuestion(BaseModel):
    text: str = Field(default='Сколько будет 2 + 2?', min_length=1, max_length=500)


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    with _PASSWORD_SLOTS:
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**17, r=8, p=1, maxmem=192*1024*1024).hex()
    return f'scrypt-v1${salt}${digest}'


def password_matches(password, stored):
    try:
        version, salt, _ = stored.split('$')
        return version == 'scrypt-v1' and hmac.compare_digest(password_hash(password, salt), stored)
    except (ValueError, TypeError):
        return False


def session_info(device):
    return {'baseUrl': '', 'token': '', 'deviceId': device.id, 'isAdmin': True}


async def new_session(session, owner_id, request, response, settings):
    device = Device(name='Веб-панель', kind='WEB', is_admin=True, user_id=owner_id, token_hash='pending',
                    user_agent=request.headers.get('user-agent', '')[:300] or None)
    session.add(device)
    await session.flush()
    token = issue_device_token(device.id)
    device.token_hash = hash_secret(token, settings)
    session.add(SelfHostWebSession(device_id=device.id, expires_at=utcnow() + timedelta(seconds=SESSION_SECONDS)))
    response.set_cookie('wm_session', token, max_age=SESSION_SECONDS, httponly=True, samesite='strict',
                        secure=request.url.scheme == 'https' or settings.public_base_url.startswith('https://'), path='/')
    response.headers['Cache-Control'] = 'no-store'
    return session_info(device)


@router.get('/status')
async def setup_status(session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)):
    admin = await session.get(SelfHostAdmin, 1)
    return {'selfhost': True, 'admin_created': admin is not None, 'completed': bool(admin and admin.completed),
            'demo': settings.mock_providers, 'https': settings.public_base_url.startswith('https://')}


@router.post('/admin', status_code=201)
async def create_admin(payload: CreateAdmin, request: Request, response: Response,
                       activation: str | None = Header(None, alias='X-WristMind-Setup'),
                       session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)):
    if await session.get(SelfHostAdmin, 1):
        raise HTTPException(409, 'Администратор уже создан. Войдите с паролем.')
    expected = settings.selfhost_setup_token.get_secret_value() if settings.selfhost_setup_token else ''
    if not expected or not activation or not secrets.compare_digest(expected, activation):
        raise HTTPException(403, 'Откройте ссылку активации, выданную установщиком.')
    login = payload.login.strip()
    if not login:
        raise HTTPException(422, 'Укажите имя администратора')
    hashed = await asyncio.to_thread(password_hash, payload.password.get_secret_value())
    owner = await session.scalar(select(User).where(User.role == 'ADMIN', User.deleted_at.is_(None)).order_by(User.created_at))
    if owner is None:
        owner = User(name='Владелец', role='ADMIN'); session.add(owner); await session.flush()
    record = SelfHostAdmin(id=1, user_id=owner.id, login=login, password_hash=hashed)
    session.add(record)
    try:
        await session.flush()  # Singleton key makes concurrent first-run requests safe.
        info = await new_session(session, owner.id, request, response, settings)
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, 'Администратор уже создан. Войдите с паролем.') from None
    return info


@router.post('/login')
async def login(payload: Login, request: Request, response: Response,
                session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)):
    admin = await session.scalar(select(SelfHostAdmin).where(SelfHostAdmin.id == 1).with_for_update())
    if not admin:
        raise HTTPException(409, 'Сначала завершите создание администратора')
    locked = admin.locked_until
    if locked and locked.replace(tzinfo=timezone.utc) > utcnow():
        raise HTTPException(429, 'Слишком много попыток входа. Повторите через 10 минут.')
    valid = await asyncio.to_thread(password_matches, payload.password.get_secret_value(), admin.password_hash)
    if not valid or not hmac.compare_digest(payload.login.strip().encode(), admin.login.encode()):
        admin.failed_attempts += 1
        if admin.failed_attempts >= 8:
            admin.locked_until = utcnow() + timedelta(minutes=10)
        await session.commit()
        raise HTTPException(401, 'Неверное имя или пароль')
    owner = await session.get(User, admin.user_id)
    if not owner or owner.deleted_at is not None:
        raise HTTPException(403, 'Доступ владельца отключён')
    admin.failed_attempts = 0; admin.locked_until = None
    # Revoke the browser's previous login on replacement, never its paired watches.
    old = request.cookies.get('wm_session')
    if old:
        previous = await session.scalar(select(Device).where(Device.token_hash == hash_secret(old, settings)))
        if previous and await session.get(SelfHostWebSession, previous.id):
            previous.revoked_at = utcnow()
    info = await new_session(session, admin.user_id, request, response, settings)
    await session.commit()
    return info


@router.get('/session')
async def read_session(device: Device = Depends(admin_device)):
    return session_info(device)


@router.post('/logout', status_code=204)
async def logout(response: Response, device: Device = Depends(current_device), session: AsyncSession = Depends(get_session)):
    device.revoked_at = utcnow()
    await session.commit()
    response.delete_cookie('wm_session', path='/')


async def wizard_owner(session):
    admin = await session.get(SelfHostAdmin, 1)
    if not admin:
        raise HTTPException(409, 'Создайте администратора')
    return admin


@router.get('/wizard')
async def wizard_state(_: Device = Depends(admin_device), session: AsyncSession = Depends(get_session),
                       settings: Settings = Depends(get_settings)):
    admin = await wizard_owner(session)
    values = read_runtime(settings)
    mode = await session.get(Mode, admin.first_mode_id) if admin.first_mode_id else None
    return {'mode_name': mode.name if mode else '', 'mode_prompt': mode.system_prompt if mode else '',
            'model_configured': bool(values.get('default_model_id')), 'model_id': values.get('default_model_id', ''),
            'models': [m.model_dump() for m in settings.allowed_models],
            'mode_created': bool(admin.first_mode_id), 'probe_passed': admin.probe_passed,
            'completed': admin.completed, 'demo': settings.mock_providers}


async def limited_answer(settings, model_id, text, prompt=''):
    async def collect():
        parts = []
        async for part in ProviderRouter(settings).stream_answer(
            model_id, [{'role': 'system', 'content': prompt + '\nОтветь кратко, максимум два предложения.'},
                       {'role': 'user', 'content': text}], thinking=False, max_tokens=256):
            parts.append(part)
        result = ''.join(parts).strip()
        if not result:
            raise ProviderError('Empty answer')
        return result[:8000]
    try:
        return await asyncio.wait_for(collect(), timeout=30)
    except (ProviderError, TimeoutError, OSError):
        # Provider bodies may echo credentials; never send those bodies to clients.
        raise HTTPException(502, 'Модель не ответила. Проверьте ключ, баланс и доступность сервера провайдера; повторите.') from None


@router.post('/mode')
async def first_mode(payload: FirstMode, _: Device = Depends(admin_device),
                     session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)):
    admin = await wizard_owner(session)
    values = read_runtime(settings)
    if not values.get('default_model_id'):
        raise HTTPException(409, 'Сначала проверьте модель')
    name = payload.name.strip()
    if not name or name == 'Быстрый чат':
        raise HTTPException(422, 'Укажите собственное название режима')
    mode = await session.get(Mode, admin.first_mode_id) if admin.first_mode_id else None
    if mode is None:
        mode = Mode(name=name, system_prompt=payload.prompt, response_model_id=values['default_model_id'],
                    color='#3D8BFD', icon='message'); session.add(mode)
    elif mode.deleted_at is not None:
        raise HTTPException(409, 'Первый режим удалён. Создайте режим в панели.')
    else:
        mode.name = name; mode.system_prompt = payload.prompt
        mode.response_model_id = values['default_model_id']
    admin.probe_passed = False
    try:
        await session.flush()
        admin.first_mode_id = mode.id
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, 'Режим с таким названием уже существует') from None
    return {'id': mode.id, 'name': mode.name}


@router.post('/question')
async def question(payload: ProbeQuestion, _: Device = Depends(admin_device),
                   session: AsyncSession = Depends(get_session), settings: Settings = Depends(get_settings)):
    admin = await wizard_owner(session)
    if not admin.first_mode_id:
        raise HTTPException(409, 'Сначала создайте режим')
    mode = await session.get(Mode, admin.first_mode_id)
    if not mode or mode.deleted_at is not None:
        raise HTTPException(409, 'Режим недоступен; создайте режим в панели')
    answer = await limited_answer(settings, mode.response_model_id, payload.text, mode.system_prompt)
    admin.probe_passed = True
    await session.commit()
    return {'answer': answer, 'demo': settings.mock_providers}


@router.post('/complete')
async def complete(_: Device = Depends(admin_device), session: AsyncSession = Depends(get_session),
                   settings: Settings = Depends(get_settings)):
    admin = await wizard_owner(session)
    if not admin.first_mode_id or not admin.probe_passed or not read_runtime(settings).get('default_model_id'):
        raise HTTPException(409, 'Завершите проверку модели, режим и пробный вопрос')
    admin.completed = True
    await session.commit()
    return {'ok': True, 'panel': '/talk', 'api': '/v1'}
