"""Terminal-only feature activation after SearXNG has passed its health probe."""
import asyncio
from .config import get_settings
from .database import SessionFactory, engine
from .provider_registry import locked_config, snapshot, persist

async def setup(settings, session):
    if not settings.selfhost_enabled or settings.searxng_url.rstrip('/') != 'http://searxng:8080':
        raise ValueError('Настройте внутренний поисковый сервис.')
    await locked_config(session, settings)
    values = snapshot(settings)
    values.setdefault('selfhost_features', {})['web_search'] = True
    await persist(session, settings, values)

async def main():
    try:
        async with SessionFactory() as session:
            await setup(get_settings(), session)
    finally: await engine.dispose()

if __name__ == '__main__':
    try: asyncio.run(main())
    except Exception:
        print('Не удалось сохранить включение веб-поиска. Повторите команду.')
        raise SystemExit(1) from None
