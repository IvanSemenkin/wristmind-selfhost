"""Optional HTTPS entry point for an existing installation; never deletes volumes."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import sys
import tempfile
import urllib.request

import installer

FILES = ('.env', '.wristmind-install', 'compose.access.yaml', 'Caddyfile', '.tunnel-token')


def detect_server_ip():
    """Prefer the public SSH destination; do not confuse it with the client IP."""
    def address(value):
        try:
            ip = ipaddress.IPv4Address(value)
            return ip if not (ip.is_loopback or ip.is_unspecified or ip.is_multicast or ip.is_link_local) else None
        except ValueError:
            return None
    connection = os.environ.get('SSH_CONNECTION', '').split()
    ssh_ip = address(connection[2]) if len(connection) == 4 else None
    if ssh_ip and ssh_ip.is_global:
        return str(ssh_ip)
    try:
        result = installer.subprocess.run(
            ['curl', '--ipv4', '--fail', '--silent', '--show-error', '--proto', '=https',
             '--connect-timeout', '3', '--max-time', '5', 'https://api.ipify.org'],
            capture_output=True, text=True, timeout=7, env=installer.docker_environment())
        public = address(result.stdout.strip()) if result.returncode == 0 else None
        if public and public.is_global:
            return str(public)
    except (OSError, installer.subprocess.SubprocessError):
        pass
    return str(ssh_ip) if ssh_ip else None


def domain_name(value):
    try:
        host = value.strip().rstrip('.').encode('idna').decode('ascii').lower()
    except UnicodeError:
        raise ValueError('Некорректный домен.') from None
    labels = host.split('.')
    if len(host) > 253 or len(labels) < 2 or any(
        not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in labels
    ):
        raise ValueError('Нужен домен без протокола, порта и пути.')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return host
    raise ValueError('Для HTTPS укажите доменное имя, а не IP.')


def dns_check(host, expected=None):
    try:
        addresses = {ipaddress.ip_address(row[4][0]) for row in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    except socket.gaierror:
        raise ValueError('Домен пока не разрешается в DNS. Настройте DNS и повторите команду.') from None
    if expected:
        try:
            wanted = {ipaddress.ip_address(item.strip()) for item in expected.split(',')}
        except ValueError:
            raise ValueError('Ожидаемый IP: адрес или список IPv4/IPv6 через запятую.') from None
        if not addresses or not addresses.issubset(wanted):
            raise ValueError('DNS не совпадает с указанными IP сервера. Проверьте все записи A и AAAA; файлы не изменены.')
    return sorted(str(item) for item in addresses)


def atomic(path, content):
    if path.is_symlink():
        raise ValueError('Файл настройки не должен быть символической ссылкой.')
    descriptor, temporary = tempfile.mkstemp(prefix='.access-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(content if isinstance(content, bytes) else content.encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def update_env(text, changes):
    # Preserve unrelated options and credentials exactly, never execute dotenv.
    for key, value in changes.items():
        line = f'{key}={value}'
        pattern = rf'(?m)^{re.escape(key)}=.*$'
        if re.search(pattern, text):
            text = re.sub(pattern, lambda _: line, text)
        else:
            text = text.rstrip('\n') + '\n' + line + '\n'
    return text


def overlay(mode):
    gateway = {'restart': 'unless-stopped', 'depends_on': {'api': {'condition': 'service_healthy'}},
               'security_opt': ['no-new-privileges:true']}
    config = {'services': {'api': {'command': ['uvicorn', 'wristmind_server.selfhost_app:app',
              '--host', '0.0.0.0', '--port', '8000', '--proxy-headers', '--forwarded-allow-ips', '*']},
              'gateway': gateway}}
    # API is forced to loopback. Only this installation's gateway is publicly reachable.
    if mode == 'domain':
        gateway.update(image='${WRISTMIND_CADDY_IMAGE:-caddy:2}', ports=['80:80', '443:443'], volumes=[
            './Caddyfile:/etc/caddy/Caddyfile:ro', 'https_data:/data', 'https_config:/config'])
        config['volumes'] = {'https_data': {}, 'https_config': {}}
    else:
        gateway.update(image='${WRISTMIND_TUNNEL_IMAGE:-cloudflare/cloudflared:latest}', user='0:0', read_only=True, cap_drop=['ALL'],
                       volumes=['./.tunnel-token:/run/secrets/tunnel-token:ro'],
                       command=['tunnel', '--no-autoupdate', 'run', '--token-file', '/run/secrets/tunnel-token'])
    return json.dumps(config, indent=2) + '\n'  # JSON is also valid YAML / Compose.


@contextmanager
def locked(target):
    name = '.wristmind-lock-' + hashlib.sha256(str(target.resolve()).encode()).hexdigest()[:16]
    descriptor = os.open(target.parent / name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Другая операция уже выполняется для этой установки.') from None
        yield


def public_health(url):
    # No redirects: a login page or another host is not a successful API probe.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(url + '/health', timeout=10) as response:
        return json.load(response).get('status') == 'ok'


def check(target):
    data = installer.manifest_at(target)
    values = installer.validate_saved(target, data)
    access = data.get('access', {'mode': 'local'})
    url = values['WRISTMIND_PUBLIC_BASE_URL']
    if access['mode'] == 'local':
        print(f'Локальный доступ: {url}/talk. Публичный HTTPS не настроен.')
        return 0
    try:
        installer.health(target, data, 20)
        if not public_health(url):
            raise ValueError('API ответил без подтверждения здоровья.')
    except (OSError, ValueError, RuntimeError) as error:
        access['phase'] = 'pending'
        installer.write_manifest(target, data)
        print(f'Внешний доступ ещё не подтверждён: {url}. Проверьте DNS, порты или маршрут туннеля; повторите access --mode check.')
        return 1
    access['phase'] = 'ready'
    installer.write_manifest(target, data)
    print(f"{'HTTP-доступ проверен' if access['mode'] == 'http' else 'HTTPS проверен'}. Панель: {url}/talk")
    return 0


def configure(target, mode, domain='', expected_ip=None, token_file=None):
    if mode not in {'local', 'http', 'domain', 'tunnel', 'check'}:
        raise ValueError('Неизвестный режим доступа.')
    if target.is_symlink():
        raise ValueError('Каталог установки не должен быть ссылкой.')
    with locked(target):
        journal = target / '.wristmind-operation'
        if journal.is_symlink():
            raise ValueError('Журнал обслуживания не должен быть ссылкой.')
        if mode != 'check' and journal.exists() and json.loads(journal.read_text()).get('phase') in {'backing-up', 'updating', 'restoring', 'failed'}:
            raise ValueError('Сначала завершите обслуживание: rollback или restore.')
        data = installer.manifest_at(target)
        values = installer.validate_saved(target, data)
        if data['phase'] != 'ready':
            raise ValueError('Сначала завершите установку: install --resume.')
        if mode == 'check':
            return check(target)
        host = domain_name(domain) if mode in {'domain', 'tunnel'} else ''
        address = None
        if mode == 'http':
            try:
                address = ipaddress.ip_address(expected_ip or '')
            except ValueError:
                raise ValueError('Укажите IP сервера без протокола и порта.') from None
            if address.is_loopback or address.is_unspecified or address.is_multicast:
                raise ValueError('Укажите адрес сервера, доступный с вашего устройства.')
        if mode == 'domain' and not expected_ip:
            raise ValueError('Укажите --expected-ip с публичным IP сервера для проверки A/AAAA.')
        if host:
            dns_check(host, expected_ip if mode == 'domain' else None)
        token = ''
        if mode == 'tunnel':
            if not token_file or token_file.is_symlink() or not token_file.is_file():
                raise ValueError('Укажите обычный файл токена: --tunnel-token-file. Не передавайте токен в командной строке.')
            if token_file.stat().st_size > 8192:
                raise ValueError('Неверный файл токена туннеля.')
            token = token_file.read_text().strip()
            if not re.fullmatch(r'[A-Za-z0-9_+/=-]{20,8192}', token):
                raise ValueError('Неверный формат токена туннеля.')
        for name in FILES:
            if (target / name).is_symlink():
                raise ValueError('Файлы установки не должны быть ссылками.')
        snapshots = {name: (target / name).read_bytes() if (target / name).exists() else None for name in FILES}
        old_data = json.loads(json.dumps(data))
        url = f'https://{host}' if host else f"http://localhost:{data['port']}"
        if address:
            http_host = f'[{address}]' if address.version == 6 else str(address)
            url = f"http://{http_host}:{data['port']}"
        bind = '0.0.0.0' if mode == 'http' else '127.0.0.1'
        changes = {'WRISTMIND_PUBLIC_BASE_URL': url, 'WRISTMIND_BIND_ADDRESS': bind}
        new_values = {**values, **changes, 'TUNNEL_TOKEN': token}
        try:
            # Stop only our managed entry point when explicitly returning to local mode.
            if mode in {'local', 'http'} and snapshots['compose.access.yaml']:
                installer.run_step(installer.compose(target, data, 'stop', 'gateway'), target, new_values)
            atomic(target / '.env', update_env(snapshots['.env'].decode(), changes))
            if mode in {'local', 'http'}:
                (target / 'compose.access.yaml').unlink(missing_ok=True)
            else:
                atomic(target / 'compose.access.yaml', overlay(mode))
                if mode == 'domain':
                    atomic(target / 'Caddyfile', f'{host} {{\n    reverse_proxy api:8000 {{\n        flush_interval -1\n    }}\n}}\n')
                else:
                    atomic(target / '.tunnel-token', token + '\n')
            data['bind'] = bind
            data['access'] = {'mode': mode, 'domain': host, 'phase': 'pending' if host or address else 'local'}
            installer.write_manifest(target, data)
            installer.run_step(installer.compose(target, data, 'config', '--quiet'), target, new_values)
            installer.run_step(installer.compose(target, data, 'up', '-d', '--no-build', '--wait', '--wait-timeout', '120'), target, new_values)
            installer.health(target, data, 20)
        except BaseException:
            for name, content in snapshots.items():
                if content is None:
                    (target / name).unlink(missing_ok=True)
                else:
                    atomic(target / name, content)
            # Restored files and credentials; try to restore running services as well.
            try:
                if not snapshots['compose.access.yaml'] and mode in {'domain', 'tunnel'}:
                    # New gateway is now an orphan; stop by project/service label, never touch volumes.
                    result = installer.subprocess.run(['docker', 'ps', '-q', '--filter', f"label=com.docker.compose.project={data['project']}",
                        '--filter', 'label=com.docker.compose.service=gateway'], capture_output=True, text=True, timeout=10,
                        env=installer.docker_environment())
                    ids = result.stdout.split()
                    if ids and all(re.fullmatch(r'[0-9a-f]{12,64}', item) for item in ids):
                        installer.run_step(['docker', 'stop', *ids], target, new_values)
                installer.run_step(installer.compose(target, old_data, 'up', '-d', '--no-build', '--wait', '--wait-timeout', '120'), target, new_values)
            except (OSError, RuntimeError, installer.subprocess.SubprocessError):
                print('Конфигурация восстановлена. Перезапуск не подтверждён; проверьте Docker.', file=sys.stderr)
            raise
        return check(target)


def main():
    parser = argparse.ArgumentParser(description='Домен / HTTPS / туннель WristMind')
    parser.add_argument('--install-dir', required=True, type=Path)
    parser.add_argument('--mode', choices=['local', 'http', 'domain', 'tunnel', 'check'])
    parser.add_argument('--domain', default='')
    parser.add_argument('--expected-ip')
    parser.add_argument('--tunnel-token-file', type=Path)
    options = parser.parse_args()
    if not options.install_dir.is_absolute() or options.install_dir == Path('/'):
        parser.error('Нужен абсолютный каталог установки, отличный от /.')
    if options.mode is None:
        if not sys.stdin.isatty():
            parser.error('Для автоматического запуска укажите --mode.')
        print('1) Свой домен + HTTPS  2) Cloudflare Tunnel за NAT  3) Оставить локально  4) Проверить доступ  5) HTTP по IP')
        choice = input('> ').strip()
        options.mode = {'1': 'domain', '2': 'tunnel', '3': 'local', '4': 'check', '5': 'http'}.get(choice)
        if not options.mode:
            parser.error('Выберите 1–5.')
        if options.mode in ('domain', 'tunnel'):
            options.domain = input('Домен (без https://): ').strip()
        if options.mode == 'domain':
            options.expected_ip = input('Публичные IP сервера (A/AAAA, через запятую): ').strip()
        elif options.mode == 'tunnel':
            print('В Cloudflare создайте Tunnel и маршрут домена → http://api:8000. Сохраните токен в закрытый файл.')
            options.tunnel_token_file = Path(input('Путь к файлу токена: ').strip()).expanduser()
    if options.mode == 'http':
        print('HTTP по IP: микрофон браузера недоступен, соединение не шифруется.')
        if not options.expected_ip:
            print('Определяю IP сервера…', flush=True)
            options.expected_ip = detect_server_ip()
            if options.expected_ip:
                print(f'Адрес найден: http://{options.expected_ip}. Использую выбранный порт установки.', flush=True)
            elif sys.stdin.isatty():
                options.expected_ip = input('Не удалось определить адрес. IP сервера: ').strip()
    try:
        return configure(options.install_dir, options.mode, options.domain, options.expected_ip, options.tunnel_token_file)
    except (OSError, ValueError, RuntimeError, installer.subprocess.SubprocessError) as error:
        print(str(error) if isinstance(error, (ValueError, RuntimeError)) else 'Не удалось настроить доступ. Проверьте Docker, DNS и права файлов.', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('Настройка отменена.', file=sys.stderr)
        return 130


if __name__ == '__main__':
    sys.exit(main())
