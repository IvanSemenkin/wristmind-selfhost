"""Optional local inference; CLI only, no Docker socket in the API container."""
import argparse
import access
from pathlib import Path
import sys
import installer
from resources import inspect_resources

PLANS = {'embedding': ('ollama', 'embeddinggemma', 'http://ollama:11434/v1', 4)}

def install(target, role, yes=False):
    if role not in PLANS: raise ValueError('Локально устанавливается только поиск по смыслу. Vision и голос подключаются через провайдера.')
    target = target.expanduser().absolute()
    data = installer.manifest_at(target)
    values = installer.validate_saved(target, data)
    if data['phase'] != 'ready': raise ValueError('Сначала завершите установку WristMind.')
    service, model, url, ram = PLANS[role]
    resources = inspect_resources(target)
    print(f"Локальная модель: {model}. Сервер: {resources['cpu']} CPU, {resources['ram_gib']} ГиБ RAM, {resources['disk_free_gib']} ГиБ свободно.")
    if resources['ram_gib'] < ram or resources['disk_free_gib'] < 6:
        raise ValueError(f'Нужно минимум {ram} ГиБ RAM и 6 ГиБ свободного диска. Используйте API или более мощный сервер.')
    if not yes:
        if not sys.stdin.isatty(): raise ValueError('Для запуска без терминала добавьте --yes после проверки ресурсов.')
        if input('Будут скачаны Docker-образ и модель. Продолжить? [д/Н] ').strip().lower() not in ('д','y','yes'): return
    # Same operation lock as install/update; no concurrent Compose mutations.
    with access.locked(target):
        data = installer.manifest_at(target)
        values = installer.validate_saved(target, data)
        if data['phase'] != 'ready': raise ValueError('Сначала завершите установку WristMind.')
        print('Запускаем локальный сервис; первый запуск и загрузка могут занять несколько минут. Подробности: install.log.')
        args = ('--profile', 'local-ai', 'up', '-d', '--wait', '--wait-timeout', '600', service)
        installer.run_step(installer.compose(target, data, *args), target, values)
        if service == 'ollama':
            print('Загружаем модель. Прогресс сохраняется в install.log; операция может занять несколько минут.')
            installer.run_step(installer.compose(target, data, 'exec', '-T', service, 'ollama', 'pull', model), target, values)
        print('Проверяем модель и назначаем её поиску по документам…')
        installer.run_step(installer.compose(target, data, 'exec', '-T', 'api', 'python', '-m', 'wristmind_server.local_model_setup'), target, values)
    print('Готово: локальный поиск установлен и назначен. Обновите панель; ключ, URL и выбор модели не нужны.')
    print('Ранее загруженные документы повторно обработайте для поиска по смыслу.')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install-dir', type=Path, required=True)
    parser.add_argument('--role', choices=PLANS, default='embedding')
    parser.add_argument('--yes', action='store_true')
    args = parser.parse_args()
    try: install(args.install_dir, args.role, args.yes)
    except (ValueError, RuntimeError, OSError) as error:
        print(str(error), file=sys.stderr); sys.exit(1)
