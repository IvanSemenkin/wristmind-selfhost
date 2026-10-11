"""Prepare host dependencies for Ubuntu/Debian without removing existing runtimes."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

BASIC = {'curl': 'curl', 'timeout': 'coreutils', 'ss': 'iproute2', 'python3': 'python3'}


def probe(args):
    try:
        env = {key: value for key, value in os.environ.items() if not key.startswith(('WRISTMIND_', 'COMPOSE_')) and key not in {'POSTGRES_PASSWORD', 'SEARXNG_SECRET'}}
        return subprocess.run(args, capture_output=True, text=True, timeout=15, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return subprocess.CompletedProcess(args, 1, '', '')


def compose_ready():
    result = probe(['docker', 'compose', 'version', '--short'])
    match = re.match(r'v?(\d+)\.(\d+)', result.stdout.strip())
    return result.returncode == 0 and bool(match) and tuple(map(int, match.groups())) >= (2, 24)


def ready():
    return all(shutil.which(name) for name in BASIC) and compose_ready() and probe(['docker', 'buildx', 'version']).returncode == 0 and probe(['docker', 'info']).returncode == 0


def system(path=Path('/etc/os-release')):
    values = {}
    for line in path.read_text().splitlines():
        key, separator, value = line.partition('=')
        if separator and key in ('ID', 'VERSION_CODENAME', 'UBUNTU_CODENAME'):
            parts = shlex.split(value)
            if len(parts) != 1:
                raise ValueError('Некорректные сведения об ОС.')
            values[key] = parts[0]
    distro = values.get('ID', '')
    codename = values.get('UBUNTU_CODENAME') or values.get('VERSION_CODENAME', '')
    supported = {'ubuntu': {'jammy', 'noble', 'resolute'}, 'debian': {'bookworm', 'trixie'}}
    if codename not in supported.get(distro, set()):
        raise ValueError('Автоматическая установка зависимостей поддерживает Ubuntu 22.04/24.04/26.04 и Debian 12/13. На этой ОС нужны готовые Docker/Compose.')
    return distro, codename


def run(args):
    result = subprocess.run(args, env={**os.environ, 'DEBIAN_FRONTEND': 'noninteractive'}, timeout=1800)
    if result.returncode:
        raise RuntimeError('Не удалось подготовить зависимости. Проверьте сеть, свободное место и сообщение пакетного менеджера выше; данные WristMind сохранены.')


def repo_present(directory=Path('/etc/apt/sources.list.d'), main=Path('/etc/apt/sources.list')):
    paths = list(directory.glob('*.list')) + list(directory.glob('*.sources'))
    if main.is_file():
        paths.append(main)
    return any(re.search(r'^\s*(?!#).*https://download\.docker\.com/linux/', path.read_text(), re.M) for path in paths if path.is_file())


def repository(distro, codename):
    if repo_present():
        return
    arch = probe(['dpkg', '--print-architecture']).stdout.strip()
    if arch not in ('amd64', 'arm64'):
        raise ValueError('Автоматическая установка предназначена для amd64/arm64.')
    directory = Path('/etc/apt/keyrings')
    directory.mkdir(parents=True, exist_ok=True, mode=0o755)
    key = directory / 'wristmind-docker.asc'
    source = Path('/etc/apt/sources.list.d/wristmind-docker.sources')
    if key.is_symlink() or source.is_symlink():
        raise ValueError('Конфигурация репозитория содержит ссылку; автоматическая замена запрещена.')
    descriptor, name = tempfile.mkstemp(prefix='wristmind-docker-', dir=directory)
    os.close(descriptor)
    temporary = Path(name)
    try:
        run(['curl', '--fail', '--silent', '--show-error', '--location', '--proto', '=https', '--proto-redir', '=https', '--connect-timeout', '15', '--max-time', '120', f'https://download.docker.com/linux/{distro}/gpg', '-o', str(temporary)])
        if 'BEGIN PGP PUBLIC KEY BLOCK' not in temporary.read_text():
            raise ValueError('Ключ репозитория Docker не прошёл проверку формата.')
        temporary.chmod(0o644)
        temporary.replace(key)
        source.write_text(f'Types: deb\nURIs: https://download.docker.com/linux/{distro}\nSuites: {codename}\nComponents: stable\nArchitectures: {arch}\nSigned-By: {key}\n')
        source.chmod(0o644)
    finally:
        temporary.unlink(missing_ok=True)


def ensure():
    if ready():
        print('✓ Зависимости готовы: Docker и Compose доступны.')
        return
    if os.geteuid() != 0:
        raise ValueError('Для подготовки зависимостей нужны root-права. Меню запросит sudo; пароль не сохраняется.')
    distro, codename = system()
    if not shutil.which('apt-get'):
        raise ValueError('Для этой ОС не найден apt-get.')
    print('Подготавливаю системные зависимости…', flush=True)
    run(['apt-get', 'update'])
    run(['apt-get', 'install', '-y', '--no-remove', 'ca-certificates', 'curl', 'python3', 'coreutils', 'iproute2'])
    has_engine = shutil.which('docker') is not None
    if not compose_ready() or not has_engine or probe(['docker', 'buildx', 'version']).returncode != 0:
        if not has_engine:
            for package in ('docker.io', 'podman-docker', 'containerd', 'runc'):
                result = probe(['dpkg-query', '-W', '-f=${Status}', package])
                if result.returncode == 0 and 'install ok installed' in result.stdout:
                    raise ValueError('Найден существующий контейнерный runtime. Автоматическая замена запрещена; установите совместимый Docker без удаления своих данных.')
        repository(distro, codename)
        run(['apt-get', 'update'])
        packages = ['docker-compose-plugin', 'docker-buildx-plugin']
        if not has_engine:
            packages += ['docker-ce', 'docker-ce-cli', 'containerd.io']
        run(['apt-get', 'install', '-y', '--no-remove', *packages])
    if probe(['docker', 'info']).returncode != 0:
        if shutil.which('systemctl'):
            run(['systemctl', 'enable', '--now', 'docker'])
        elif shutil.which('service'):
            run(['service', 'docker', 'start'])
        else:
            raise ValueError('Docker установлен, но сервис не запущен; менеджер служб не найден.')
    if not ready():
        raise ValueError('После подготовки Docker/Compose недоступны. Проверьте службу Docker и версию Compose; установка WristMind ещё не начата.')
    print('✓ Зависимости установлены. Продолжаю установку WristMind.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    options = parser.parse_args()
    if options.check:
        sys.exit(0 if ready() else 1)
    try:
        ensure()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
