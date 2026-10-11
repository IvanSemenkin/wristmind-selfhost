"""Encrypted, atomic settings shared by the self-hosted API and worker."""
import base64
import hashlib
import json
import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet
from pydantic import SecretStr


FIELDS = {'openrouter_api_key', 'deepseek_api_key', 'default_model_id', 'quick_chat_model_id',
          'router_model_id', 'title_model_id', 'providers', 'models', 'model_roles', 'selfhost_features'}


def cipher(settings):
    key = hashlib.sha256(b'wristmind-runtime-v1:' + settings.token_pepper.get_secret_value().encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def read_runtime(settings):
    path = settings.storage_dir / 'selfhost-settings.enc'
    if not path.exists():
        return {}
    if path.is_symlink() or path.stat().st_size > 512_000:
        raise RuntimeError('Повреждена конфигурация модели')
    values = json.loads(cipher(settings).decrypt(path.read_bytes()))
    if not isinstance(values, dict) or set(values) - FIELDS or any(not isinstance(v, list if k in {'providers', 'models'} else dict if k in {'model_roles', 'selfhost_features'} else str) for k, v in values.items()):
        raise RuntimeError('Повреждена конфигурация модели')
    return values


def write_runtime(settings, values):
    if set(values) - FIELDS:
        raise ValueError('Unknown runtime setting')
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix='.selfhost-settings-', dir=settings.storage_dir)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(cipher(settings).encrypt(json.dumps(values).encode()))
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, settings.storage_dir / 'selfhost-settings.enc')
    finally:
        Path(name).unlink(missing_ok=True)


def refresh_runtime(settings):
    from .config import ModelOption
    from .provider_connections import ProviderConnection
    values = read_runtime(settings)
    for key, value in values.items():
        if key not in {'providers', 'models'}:
            setattr(settings, key, SecretStr(value) if key.endswith('_api_key') else value)
    if 'providers' in values:
        settings.provider_connections = [ProviderConnection.model_validate(p) for p in values['providers']]
        for item in settings.provider_connections:
            if item.id in {'openrouter', 'deepseek'}:
                setattr(settings, item.id + '_api_key', item.api_key)
    if 'models' in values:
        enabled = {p.id for p in settings.provider_connections if p.enabled}
        settings.allowed_models = [ModelOption.model_validate(m) for m in values['models']
                                   if m.get('enabled', True) and m['provider'] in enabled and 'text' in m.get('roles', ['text'])]
    elif getattr(settings, 'selfhost_enabled', False):
        settings.allowed_models = []
    if settings.selfhost_enabled or values.get('model_roles', {}).get('speech'):
        from .provider_connections import ProviderConnection
        identity = values.get('model_roles', {}).get('speech')
        model = next((m for m in values.get('models', []) if m['id'] == identity and m.get('enabled', True) and 'speech' in m.get('roles', ['text'])), None)
        provider = next((p for p in settings.provider_connections if model and p.id == model['provider'] and p.enabled and p.kind == 'yandex'), None)
        if provider: settings.yandex_speechkit_api_key = provider.api_key
        elif settings.selfhost_enabled: settings.yandex_speechkit_api_key = None
    return settings
