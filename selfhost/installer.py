"""Local-source self-host installer. No shell execution of configuration files."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from functools import wraps
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import threading

ROOT = Path(__file__).resolve().parents[1]
MARKER = '.wristmind-install'


_status_state = threading.local()


@contextmanager
def wait_status(label, detail=None, interval=None):
    """Heartbeat for real work, without subprocess output or private arguments."""
    if getattr(_status_state, 'active', False):
        yield
        return
    _status_state.active = True
    stream = sys.stderr
    terminal = stream.isatty()
    delay = interval if interval is not None else (1 if terminal else 5)
    stopped = threading.Event()
    started = time.monotonic()
    frames = ('◐', '◓', '◑', '◒')
    frame = 0
    def render(final=None):
        nonlocal frame
        elapsed = int(time.monotonic() - started)
        suffix = detail() if detail is not None else ''
        line = f"{final or frames[frame % 4]} {label} · {elapsed // 60:02d}:{elapsed % 60:02d}"
        if suffix:
            line += ' · ' + suffix
        print(('\r\033[K' if terminal else '') + line,
              end='\n' if final or not terminal else '', file=stream, flush=True)
        frame += 1
    def heartbeat():
        while not stopped.wait(delay):
            render()
    worker = threading.Thread(target=heartbeat, daemon=True)
    failed = False
    try:
        render()
        worker.start()
        yield
    except BaseException:
        failed = True
        raise
    finally:
        stopped.set()
        if worker.ident is not None:
            worker.join()
        try:
            render('✕' if failed else '✓')
        finally:
            _status_state.active = False


def with_status(label):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            title = label(*args, **kwargs) if callable(label) else label
            with wait_status(title):
                return function(*args, **kwargs)
        return wrapped
    return decorate


def manifest_at(target):
    marker = target / MARKER
    if marker.is_symlink():
        return None
    try:
        data = json.loads(marker.read_text())
        if data.get('format') == 1 and re.fullmatch(r'wristmind-[0-9a-f]{12}', data.get('project', '')):
            return data
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    return None


def state(target):
    if target.is_symlink():
        return 'occupied'
    data = manifest_at(target)
    if data and (target / '.env').is_file() and (target / 'compose.yaml').is_file():
        return 'installed' if data.get('phase') == 'ready' else 'incomplete'
    if any((target / name).exists() for name in (MARKER, '.env', 'compose.yaml')):
        return 'incomplete'
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        return 'occupied'
    return 'new'


def write_manifest(target, data):
    descriptor, name = tempfile.mkstemp(prefix='.wristmind-install-', dir=target)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
            json.dump(data, output, ensure_ascii=False, indent=2)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target / MARKER)
    finally:
        temporary.unlink(missing_ok=True)


def read_env(target):
    path = target / '.env'
    if path.is_symlink():
        raise ValueError('Конфигурация не должна быть символической ссылкой.')
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, separator, value = line.partition('=')
        if not separator or not re.fullmatch(r'[A-Z][A-Z0-9_]*', key) or key in values:
            raise ValueError('Неверный формат конфигурации; файл сохранён без изменений.')
        values[key] = value.strip().strip('"').strip("'")
    return values


def docker_environment():
    # Parent .env/Compose settings must never select another installation's
    # project, profiles or database credentials.
    return {key: value for key, value in os.environ.items()
            if not key.startswith(('WRISTMIND_', 'COMPOSE_'))
            and key not in {'POSTGRES_PASSWORD', 'SEARXNG_SECRET'}}


def compose(target, data, *arguments):
    extra = target / 'compose.access.yaml'
    if extra.is_symlink():
        raise ValueError('Конфигурация доступа не должна быть ссылкой.')
    overrides = ['-f', str(extra)] if extra.is_file() else []
    return ['docker', 'compose', '--project-directory', str(target), '--env-file', str(target / '.env'),
            '-p', data['project'], '-f', str(target / 'compose.yaml'), *overrides, *arguments]


def run_step(command, target, values, label=None):
    hidden = [value for key, value in values.items() if value and
              any(part in key for part in ('SECRET', 'PASSWORD', 'PEPPER', 'TOKEN', 'API_KEY', 'CREDENTIALS'))]
    log_path = target / 'install.log'
    descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'a', encoding='utf-8') as log:
        os.chmod(log_path, 0o600)
        process = subprocess.Popen(command, cwd=target, env=docker_environment(),
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace')
        stopped = threading.Event()
        started = time.monotonic()
        stage = [label]
        interactive = sys.stdout.isatty()
        colours = interactive and os.environ.get('TERM', 'dumb') != 'dumb' and 'NO_COLOR' not in os.environ
        def show_status(final=None):
            elapsed = int(time.monotonic() - started)
            text = f"{stage[0]} · {elapsed // 60:02d}:{elapsed % 60:02d} · {final or 'ожидание Docker'}"
            if interactive:
                width = max(20, shutil.get_terminal_size().columns - 1)
                text = text[:width]
                prefix = '\033[94m' if colours else ''
                suffix = '\033[0m' if colours else ''
                print('\r' + prefix + text.ljust(width) + suffix, end='\n' if final else '', flush=True)
            else:
                print(text, flush=True)
        def heartbeat():
            while not stopped.wait(1 if interactive else 15):
                show_status()
        worker = None
        if label:
            show_status()
            worker = threading.Thread(target=heartbeat, daemon=True)
            worker.start()
        code = None
        try:
            for line in process.stdout:
                for value in hidden:
                    line = line.replace(value, '[скрыто]')
                log.write(line)
                log.flush()
                # Only fixed labels reach the terminal, never raw Docker output.
                if label and 'build' in command:
                    lower = line.lower()
                    if 'npm ci' in lower: stage[0] = 'Установка зависимостей панели'
                    elif 'npm run build' in lower or 'vite v' in lower: stage[0] = 'Сборка веб-панели'
                    elif 'pip install' in lower: stage[0] = 'Установка зависимостей API'
                    elif 'exporting' in lower: stage[0] = 'Сохранение Docker-образа'
            code = process.wait()
        except BaseException:
            process.terminate()
            process.wait(timeout=10)
            raise
        finally:
            stopped.set()
            if worker:
                worker.join(timeout=2)
                show_status('готово' if code == 0 else 'остановлено')
    if code:
        raise RuntimeError('Операция Docker не завершилась. Подробности в защищённом install.log.')


def validate_saved(target, data):
    if not data or data.get('phase') not in {'prepared', 'starting', 'ready', 'failed'}:
        raise ValueError('Нет корректного состояния этой установки. Автоматическая перезапись запрещена.')
    if (target / 'compose.yaml').is_symlink():
        raise ValueError('compose.yaml не должен быть символической ссылкой.')
    if type(data.get('port')) is not int or not 1 <= data['port'] <= 65535 or data.get('bind') not in {'127.0.0.1', '0.0.0.0'} or type(data.get('demo')) is not bool:
        raise ValueError('Повреждены параметры установки; автоматический запуск запрещён.')
    values = read_env(target)
    if values.get('WRISTMIND_PROJECT_NAME') != data['project']:
        raise ValueError('Имя проекта в конфигурации изменено; автоматический запуск запрещён.')
    for key in ('POSTGRES_PASSWORD', 'WRISTMIND_BOOTSTRAP_SECRET', 'WRISTMIND_TOKEN_PEPPER'):
        if not re.fullmatch(r'[0-9a-f]{48,64}', values.get(key, '')):
            raise ValueError('Секреты установки отсутствуют или повреждены; новые не генерируются поверх прежних.')
    if values.get('WRISTMIND_HTTP_PORT') != str(data.get('port')) or values.get('WRISTMIND_BIND_ADDRESS') != data.get('bind'):
        raise ValueError('Порт или адрес изменены. Этот запуск не заменяет настройку установки.')
    if values.get('WRISTMIND_MOCK_PROVIDERS') != ('true' if data['demo'] else 'false'):
        raise ValueError('Режим провайдеров изменён; автоматический запуск запрещён.')
    expected_image = data.get('release', {}).get('image', 'wristmind-selfhost:' + data['project'])
    if not re.fullmatch(r'wristmind-selfhost:[a-zA-Z0-9_.-]+', expected_image) or values.get('WRISTMIND_IMAGE') != expected_image:
        raise ValueError('Образ установки изменён вне механизма обновлений.')
    return values


def payload(staging):
    files = ['compose.yaml', '.dockerignore', '.env.example', 'wristmind', 'selfhost/installer.py',
             'selfhost/Dockerfile', 'selfhost/dependencies.py', 'selfhost/access.py', 'selfhost/lifecycle.py', 'selfhost/release.py', 'selfhost/resources.py', 'selfhost/local_models.py', 'selfhost/web_search.py', 'selfhost/search/settings.yml', 'server/pyproject.toml',
             'web/package.json', 'web/package-lock.json', 'web/index.html', 'web/tsconfig.json',
             'web/tsconfig.app.json', 'web/tsconfig.node.json', 'web/vite.config.ts']
    for name in files:
        destination = staging / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if (ROOT / name).is_symlink():
            raise ValueError('Исходники содержат символическую ссылку; сборка остановлена.')
        shutil.copy2(ROOT / name, destination)
    for name in ['server/src', 'web/src', 'web/public']:
        source = ROOT / name
        if source.is_symlink() or any(path.is_symlink() for path in source.rglob('*')):
            raise ValueError('Исходники содержат символическую ссылку; сборка остановлена.')
        shutil.copytree(ROOT / name, staging / name,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.env', '.env.*', 'node_modules'))


def prepare(target, options, files=None):
    staging = Path(tempfile.mkdtemp(prefix='.wristmind-staging-', dir=target.parent))
    try:
        if files is None:
            payload(staging)
        else:
            import release
            for name in release.RUNTIME:
                destination = staging / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(files / name, destination)
            (staging / 'wristmind').chmod(0o700)
        project = 'wristmind-' + secrets.token_hex(6)
        port = options.port or 8080
        bind = options.bind or '127.0.0.1'
        values = {
            'WRISTMIND_SELFHOST_SETUP_TOKEN': secrets.token_hex(32),
            'POSTGRES_PASSWORD': secrets.token_hex(24),
            'WRISTMIND_BOOTSTRAP_SECRET': secrets.token_hex(32),
            'WRISTMIND_TOKEN_PEPPER': secrets.token_hex(32),
            'WRISTMIND_PROJECT_NAME': project,
            'WRISTMIND_IMAGE': 'wristmind-selfhost:' + project,
            'WRISTMIND_HTTP_PORT': str(port), 'WRISTMIND_BIND_ADDRESS': bind,
            'WRISTMIND_PUBLIC_BASE_URL': f'http://localhost:{port}',
            'WRISTMIND_CORS_ORIGINS': '[]',
            'WRISTMIND_MOCK_PROVIDERS': 'true' if options.demo else 'false',
            'COMPOSE_PROFILES': 'search',
            'SEARXNG_SECRET': secrets.token_hex(32),
            'WRISTMIND_SEARXNG_URL': 'http://searxng:8080',
        }
        descriptor = os.open(staging / '.env', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
            output.write(''.join(f'{key}={value}\n' for key, value in values.items()))
        data = {'format': 1, 'project': project, 'phase': 'prepared', 'port': port, 'bind': bind,
                'demo': bool(options.demo), 'source': 'local-development', 'created_at': int(time.time())}
        write_manifest(staging, data)
        os.replace(staging, target)  # Refuses to replace a non-empty directory.
        return data, values
    finally:
        if staging.exists():
            shutil.rmtree(staging)  # Only our freshly allocated staging directory.


@with_status('Проверяю требования и доступность Docker')
def preflight(target, options, fresh):
    version = subprocess.run(['docker', 'compose', 'version', '--short'], capture_output=True,
                             text=True, timeout=10, env=docker_environment())
    match = re.match(r'v?(\d+)\.(\d+)', version.stdout.strip())
    if version.returncode or not match or tuple(map(int, match.groups())) < (2, 24):
        raise ValueError('Нужен Docker Compose plugin версии 2.24 или новее.')
    if fresh:
        command = [str(ROOT / 'wristmind'), 'check', '--install-dir', str(target), '--port', str(options.port or 8080)]
        if subprocess.run(command, env=docker_environment()).returncode:
            raise ValueError('Проверка требований не пройдена. Установка не изменена.')
    else:
        if subprocess.run(['docker', 'info'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          timeout=10, env=docker_environment()).returncode:
            raise ValueError('Docker недоступен. Конфигурация сохранена без изменений.')


@with_status('Проверяю готовность API и поиска')
def health(target, data, timeout):
    # Check inside the API container: no dependency on externally open ports,
    # IPv6, proxy environment, or a different service returning /health.
    probe = "import json,urllib.request; r=json.load(urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3)); assert r.get('status')=='ok'"
    result = subprocess.run(compose(target, data, 'exec', '-T', 'api', 'python', '-c', probe),
                            env=docker_environment(), cwd=target, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, timeout=timeout)
    if result.returncode:
        raise RuntimeError('API не прошёл проверку здоровья. Данные и конфигурация сохранены.')

    if read_env(target).get('WRISTMIND_SEARXNG_URL'):
        search_health(target, data, timeout)


def search_health(target, data, timeout=60):
    probe = "import os,json,urllib.request; u=os.environ['WRISTMIND_SEARXNG_URL'].rstrip('/')+'/search?q=wristmind&format=json'; r=json.load(urllib.request.urlopen(u,timeout=15)); assert isinstance(r.get('results'),list)"
    result = subprocess.run(compose(target, data, 'exec', '-T', 'api', 'python', '-c', probe),
                            env=docker_environment(), cwd=target, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, timeout=timeout)
    if result.returncode:
        raise RuntimeError('Веб-поиск не прошёл проверку. Повторите команду; данные сохранены.')


def validate_install(target, options):
    if options.domain:
        raise ValueError('Сначала установите систему, затем выберите настройку HTTPS в меню.')
    resolved = target.resolve()
    if target.is_symlink() or resolved.is_relative_to(ROOT) or ROOT.is_relative_to(resolved):
        raise ValueError('Выберите отдельный каталог вне исходников. Символическая ссылка не допускается.')
    if state(target) != 'new':
        data = manifest_at(target)
        validate_saved(target, data)
        for key in ('port', 'bind', 'demo'):
            requested = getattr(options, key)
            if requested is not None and requested != data.get(key):
                raise ValueError('Повторная установка не меняет параметры. Конфигурация сохранена.')
        if data['phase'] != 'ready' and not options.resume:
            raise ValueError('Есть незавершённая установка. Продолжите её через меню или повторите с --resume; прежние секреты будут сохранены.')


def install(target, options):
    validate_install(target, options)
    if options.domain:
        raise ValueError('Сначала выполните install без --domain, затем access --mode domain --domain ИМЯ --expected-ip IP.')
    resolved = target.resolve()
    if target.is_symlink() or resolved.is_relative_to(ROOT) or ROOT.is_relative_to(resolved):
        raise ValueError('Выберите отдельный каталог вне исходников. Символическая ссылка не допускается.')
    fresh = state(target) == 'new'
    if not fresh:
        data = manifest_at(target)
        values = validate_saved(target, data)
        for key in ('port', 'bind', 'demo'):
            requested = getattr(options, key)
            if requested is not None and requested != data.get(key):
                raise ValueError('Повторная установка не меняет параметры. Конфигурация сохранена.')
        if data['phase'] == 'ready':
            print('Установка уже завершена. Повторный запуск не пересобирает сервисы и не меняет секреты.')
            print(f"Панель: {values['WRISTMIND_PUBLIC_BASE_URL']}/talk")
            return 0
        if not options.resume:
            raise ValueError('Есть незавершённая установка. Повторите с --resume; прежние секреты будут сохранены.')
    print('1/5 Проверяю требования', flush=True)
    preflight(target, options, fresh)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.parent / ('.wristmind-lock-' + hashlib.sha256(str(resolved).encode()).hexdigest()[:16])
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('В этом каталоге уже выполняется другая установка.') from None
        if fresh:
            if state(target) != 'new':
                raise ValueError('Каталог изменился во время проверки. Перезапись запрещена.')
            print('2/5 Готовлю файлы и новые секреты', flush=True)
            data, values = prepare(target, options)
        else:
            data = manifest_at(target)
            values = validate_saved(target, data)
            if data['phase'] == 'ready':
                print('Установка уже завершена; конфигурация сохранена.')
                return 0
            print('2/5 Использую сохранённую конфигурацию', flush=True)
        try:
            run_step(compose(target, data, 'config', '--quiet'), target, values)
            print('3/5 Собираю API и панель. Первая сборка может занять несколько минут', flush=True)
            if data.get('release'):
                import release
                if release.inspect_image(values['WRISTMIND_IMAGE'])['Id'] != data['release']['image_id']:
                    raise ValueError('Нет точного образа релиза. Повторите install-release --resume с исходным пакетом.')
            else:
                run_step(compose(target, data, 'build', 'api'), target, values, label='Сборка API и панели')
            data['phase'] = 'starting'
            write_manifest(target, data)
            print('4/5 Запускаю базу, API и обработчик', flush=True)
            run_step(compose(target, data, 'up', '-d', '--no-build', '--wait', '--wait-timeout', str(options.timeout)), target, values, label='Запуск сервисов')
            print('5/5 Проверяю API', flush=True)
            health(target, data, options.timeout)
            data['phase'] = 'ready'
            write_manifest(target, data)
        except (Exception, KeyboardInterrupt):
            data['phase'] = 'failed'
            write_manifest(target, data)
            raise
    print(f"Сервисы установлены. Настройка: http://localhost:{data['port']}/setup")
    print('Для первого входа откройте ссылку из команды ./wristmind setup-link с тем же каталогом. Для домена / HTTPS / NAT используйте ./wristmind access с тем же каталогом.')
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['install', 'validate', 'state', 'setup-link'])
    parser.add_argument('--install-dir', required=True, type=Path)
    parser.add_argument('--port', type=int)
    parser.add_argument('--bind', choices=['127.0.0.1', '0.0.0.0'])
    parser.add_argument('--demo', action='store_true', default=None)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--domain')
    parser.add_argument('--timeout', type=int, default=120)
    options = parser.parse_args()
    target = options.install_dir
    if not target.is_absolute() or target == Path('/') or (options.port is not None and not 1 <= options.port <= 65535) or not 1 <= options.timeout <= 600:
        parser.error('Неверный каталог, порт или время ожидания (1–600 секунд).')
    try:
        if options.command == 'validate':
            validate_install(target, options)
            return 0
        if options.command == 'state':
            print(state(target))
            return 0
        if options.command == 'setup-link':
            values = validate_saved(target, manifest_at(target))
            if values['WRISTMIND_PUBLIC_BASE_URL'].startswith('http://localhost:') and sys.stdin.isatty():
                print('Настроим HTTP-доступ по IP для входа с другого устройства.', flush=True)
                result = subprocess.run([sys.executable, str(ROOT / 'selfhost/access.py'), '--install-dir', str(target), '--mode', 'http'])
                updated = manifest_at(target)
                values = validate_saved(target, updated)
                # External reachability can fail behind NAT while HTTP configuration
                # is already applied. Still give the usable activation URL.
                http_pending = (updated.get('access', {}).get('mode') == 'http'
                                and updated['access'].get('phase') == 'pending'
                                and not values['WRISTMIND_PUBLIC_BASE_URL'].startswith('http://localhost:'))
                if result.returncode and not (result.returncode == 1 and http_pending):
                    return result.returncode
            token = values.get('WRISTMIND_SELFHOST_SETUP_TOKEN', '')
            if not re.fullmatch(r'[0-9a-f]{64}', token):
                raise ValueError('Код активации отсутствует. Эта установка создана до этапа 4; автоматическая замена запрещена.')
            if sys.stdout.isatty():
                print("\nСсылка первого входа — скопируйте целиком:")
            print(f"{values['WRISTMIND_PUBLIC_BASE_URL']}/setup#activate={token}")
            return 0
        return install(target, options)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        # Do not include captured Docker output/configuration in terminal errors.
        print(str(error) if isinstance(error, (ValueError, RuntimeError)) else 'Операция прервана. Проверьте права и Docker; файлы и данные сохранены.', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('Установка прервана. Возобновление: install --resume с тем же каталогом.', file=sys.stderr)
        return 130

if __name__ == '__main__':
    sys.exit(main())
