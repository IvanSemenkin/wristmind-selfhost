"""One-command private SearXNG setup, with preserved credentials and rollback."""
import argparse
from pathlib import Path
import secrets
import sys
import subprocess
import access
import installer


def install(target):
    target = target.expanduser().absolute()
    with access.locked(target):
        data = installer.manifest_at(target)
        values = installer.validate_saved(target, data)
        if data['phase'] != 'ready': raise ValueError('Сначала завершите установку WristMind.')
        original = (target / '.env').read_text()
        old_url = values.get('WRISTMIND_SEARXNG_URL', '')
        if old_url and old_url.rstrip('/') != 'http://searxng:8080':
            raise ValueError('Уже настроен другой поисковый сервис. Он сохранён без изменений.')
        profiles = list(dict.fromkeys([p for p in values.get('COMPOSE_PROFILES', '').split(',') if p] + ['search']))
        changes = {'COMPOSE_PROFILES': ','.join(profiles), 'WRISTMIND_SEARXNG_URL': 'http://searxng:8080',
                   'SEARXNG_SECRET': values.get('SEARXNG_SECRET') or secrets.token_hex(32)}
        active = {**values, **changes}
        print('Настраиваем веб-поиск. Первый запуск может занять несколько минут.')
        access.atomic(target / '.env', access.update_env(original, changes))
        try:
            installer.run_step(installer.compose(target, data, 'up', '-d', '--no-build', '--wait', '--wait-timeout', '180', 'searxng', 'api', 'worker'), target, active)
            installer.search_health(target, data)
            installer.run_step(installer.compose(target, data, 'exec', '-T', 'api', 'python', '-m', 'wristmind_server.web_search_setup'), target, active)
        except BaseException:
            access.atomic(target / '.env', original)
            try:
                installer.run_step(installer.compose(target, data, 'up', '-d', '--no-build', 'api', 'worker'), target, active)
            except Exception:
                print('Конфигурация восстановлена; повторно запустите API/worker через меню обслуживания.', file=sys.stderr)
            raise
    print('Готово: веб-поиск подключён. Обновите панель. Ключ и URL вводить не нужно.')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install-dir', required=True, type=Path)
    args = parser.parse_args()
    try: install(args.install_dir)
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr); sys.exit(1)
