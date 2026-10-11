"""Terminal-only setup of the fixed local search model. No HTTP admin endpoint."""
import asyncio
from .config import get_settings
from .database import SessionFactory, engine
from .model_capabilities import embeddings
from .provider_connections import ProviderConnection
from .provider_registry import locked_config, snapshot, persist

MODEL = 'embeddinggemma'
URL = 'http://ollama:11434/v1'
PROVIDER = 'p_6c6f63616c00'

def configure(values):
    """Preserve existing providers/models and assign only semantic search."""
    providers = values.setdefault('providers', [])
    row = next((p for p in providers if p['id'] == PROVIDER), None)
    if row and (row.get('base_url') != URL or row.get('kind') != 'compatible'):
        raise ValueError('ID local-search занят другим подключением. Настройки не изменены.')
    if row is None:
        row = {'id': PROVIDER, 'kind': 'compatible', 'label': 'Локальный поиск', 'base_url': URL, 'api_key': '', 'allow_local': True, 'enabled': True}
        providers.append(row)
    elif row.get('api_key'):
        raise ValueError('Локальное подключение защищено ключом. Настройки не изменены.')
    row.update(enabled=True, allow_local=True)
    row.pop('deleted', None)
    identity = PROVIDER + ':' + MODEL
    models = values.setdefault('models', [])
    model = next((m for m in models if m['id'] == identity), None)
    if model is None:
        models.append({'id': identity, 'provider': PROVIDER, 'label': 'Поиск по смыслу · локально', 'roles': ['embedding'], 'enabled': True})
    else:
        if model.get('provider') != PROVIDER:
            raise ValueError('ID модели занят другой моделью. Настройки не изменены.')
        model['enabled'] = True
        model['roles'] = list(dict.fromkeys(model.get('roles', []) + ['embedding']))
    values.setdefault('model_roles', {})['embedding'] = identity
    return values

async def setup(settings, session):
    if not settings.selfhost_enabled or settings.mock_providers:
        raise ValueError('Автонастройка доступна только в рабочей SelfHost-установке.')
    connection = ProviderConnection(id=PROVIDER, kind='compatible', label='Локальный поиск', base_url=URL, allow_local=True)
    # Verify actual inference before changing persistent configuration.
    await asyncio.wait_for(embeddings(connection, MODEL, ['Проверка локального поиска']), timeout=180)
    await locked_config(session, settings)
    values = configure(snapshot(settings))
    await persist(session, settings, values)

async def main():
    try:
        async with SessionFactory() as session:
            await setup(get_settings(), session)
    finally:
        await engine.dispose()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception:
        # Transport/config errors must never expose credentials in terminal logs.
        print('Не удалось проверить и назначить локальный поиск. Повторите команду после проверки сервиса; подробности в install.log.')
        raise SystemExit(1) from None
    print('Локальный поиск установлен, проверен и назначен автоматически. Обновите панель.')
