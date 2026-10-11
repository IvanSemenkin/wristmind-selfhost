"""Versioned offline release packages: allowlisted files, hashes, no private state."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

import installer

RUNTIME = ('compose.yaml', '.env.example', 'wristmind', 'selfhost/installer.py',
           'selfhost/access.py', 'selfhost/lifecycle.py', 'selfhost/release.py', 'selfhost/resources.py', 'selfhost/local_models.py', 'selfhost/web_search.py',
           'selfhost/Dockerfile', 'selfhost/search/settings.yml')
PRIVATE = ('.env', '.wristmind-install', 'compose.access.yaml', 'Caddyfile', '.tunnel-token')
VERSION = r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)'
MAX_BYTES = 32 * 1024**3


def digest(path):
    hasher = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            hasher.update(block)
    return hasher.hexdigest()


def metadata(data):
    if not isinstance(data, dict):
        raise ValueError('Манифест должен быть объектом.')
    if data.get('format') != 1 or data.get('kind') not in ('release', 'backup'):
        raise ValueError('Неизвестный формат пакета.')
    if not re.fullmatch(VERSION, str(data.get('version', ''))) or data.get('arch') not in ('amd64', 'arm64'):
        raise ValueError('Неверная версия или архитектура пакета.')
    if data.get('schema') != 1 or data.get('postgres_major') != 16:
        raise ValueError('Изменение поколения базы требует отдельной миграции; этот пакет не применяется автоматически.')
    if not re.fullmatch(r'wristmind-selfhost:[a-zA-Z0-9_.-]+', str(data.get('image', ''))):
        raise ValueError('Неверное имя образа.')
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', str(data.get('image_id', ''))):
        raise ValueError('Неверный идентификатор образа.')
    hashes = data.get('files')
    allowed = set(RUNTIME) | {'image.tar'}
    required = set(RUNTIME) | {'image.tar'}
    if data['kind'] == 'backup':
        allowed |= set(PRIVATE) | {'database.dump', 'private.tar.gz'}
        required = {'.env', '.wristmind-install', 'compose.yaml', 'image.tar', 'database.dump', 'private.tar.gz'}
        if not re.fullmatch(r'wristmind-[0-9a-f]{12}', str(data.get('project', ''))):
            raise ValueError('Неверный проект резервной копии.')
        if not isinstance(data.get('running'), list) or set(data['running']) - {'db', 'api', 'worker', 'gateway', 'telegram-bot', 'searxng', 'ollama', 'local-speech'}:
            raise ValueError('Неверные сервисы резервной копии.')
    if not isinstance(hashes, dict) or not required.issubset(hashes) or set(hashes) - allowed or any(
        not re.fullmatch(r'[0-9a-f]{64}', str(value)) for value in hashes.values()
    ):
        raise ValueError('Неверный список или контрольные суммы файлов.')
    if data['kind'] == 'release':
        if data['image'] != f"wristmind-selfhost:{data['version']}-{data['arch']}":
            raise ValueError('Имя образа должно соответствовать версии и архитектуре релиза.')
        images = data.get('dependencies', {})
        if set(images) != {'db', 'caddy', 'tunnel', 'search'} or any(
            not re.fullmatch(r'[a-z0-9./_-]+@sha256:[0-9a-f]{64}', str(value)) for value in images.values()
        ):
            raise ValueError('Зависимости релиза должны иметь фиксированные digest.')
    return data


def unpack(package, checksum, destination):
    if package.is_symlink() or not re.fullmatch(r'[0-9a-f]{64}', checksum or '') or digest(package) != checksum:
        raise ValueError('SHA256 не совпадает. Установка не изменена.')
    with tarfile.open(package, 'r:*') as archive:
        allowed = set(RUNTIME) | set(PRIVATE) | {'manifest.json', 'image.tar', 'database.dump', 'private.tar.gz'}
        members = []
        for member in archive:
            if len(members) >= len(allowed):
                raise ValueError('Слишком много файлов в пакете.')
            members.append(member)
        names = [member.name for member in members]
        if len(names) != len(set(names)) or set(names) - allowed or 'manifest.json' not in names or any(
            not member.isfile() or member.size < 0 for member in members
        ) or sum(member.size for member in members) > MAX_BYTES:
            raise ValueError('Пакет содержит небезопасные пути, ссылки или слишком большой объём.')
        info = archive.getmember('manifest.json')
        if info.size > 65536:
            raise ValueError('Слишком большой манифест.')
        data = metadata(json.load(archive.extractfile(info)))
        if set(names) != set(data['files']) | {'manifest.json'}:
            raise ValueError('Состав пакета не совпадает с манифестом.')
        for member in members:
            path = destination / member.name
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with path.open('xb') as output, archive.extractfile(member) as source:
                os.chmod(path, 0o600)
                shutil.copyfileobj(source, output)
            if member.name != 'manifest.json' and digest(path) != data['files'][member.name]:
                raise ValueError('Повреждён файл внутри пакета.')
    return data


def pack(directory, data, output):
    if output.exists() or output.is_symlink():
        raise ValueError('Файл результата уже существует; перезапись запрещена.')
    data['files'] = {path.relative_to(directory).as_posix(): digest(path) for path in directory.rglob('*') if path.is_file()}
    metadata(data)
    if sum(path.stat().st_size for path in directory.rglob('*') if path.is_file()) > MAX_BYTES:
        raise ValueError('Слишком большой пакет.')
    (directory / 'manifest.json').write_text(json.dumps(data, indent=2) + '\n')
    descriptor = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            with tarfile.open(fileobj=stream, mode='w:gz', compresslevel=1) as archive:
                for path in sorted(directory.rglob('*')):
                    if path.is_symlink():
                        raise ValueError('Ссылка в пакете запрещена.')
                    if path.is_file():
                        archive.add(path, arcname=path.relative_to(directory).as_posix(), recursive=False)
            stream.flush()
            os.fsync(stream.fileno())
        directory_fd = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    return digest(output)


def inspect_image(image):
    result = subprocess.run(['docker', 'image', 'inspect', image], capture_output=True, text=True,
                            check=True, timeout=30, env=installer.docker_environment())
    return json.loads(result.stdout)[0]


def fetch(url, output, checksum):
    from urllib.parse import urlsplit
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.fragment:
        raise ValueError('Ссылка пакета должна быть HTTPS без учётных данных.')
    if output.exists() or output.is_symlink():
        raise ValueError('Файл уже существует.')
    class HTTPSOnly(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, message, headers, redirected):
            if urlsplit(redirected).scheme != 'https':
                raise ValueError('Переход с HTTPS на HTTP запрещён.')
            return super().redirect_request(request, fp, code, message, headers, redirected)
    try:
        with urllib.request.build_opener(HTTPSOnly()).open(url, timeout=30) as source, output.open('xb') as stream:
            os.chmod(output, 0o600)
            count = 0
            while block := source.read(1024 * 1024):
                count += len(block)
                if count > MAX_BYTES:
                    raise ValueError('Слишком большой пакет.')
                stream.write(block)
        if digest(output) != checksum:
            raise ValueError('SHA256 загруженного пакета не совпадает.')
    except BaseException:
        output.unlink(missing_ok=True)
        raise


def build(version, arch, output):
    if not re.fullmatch(VERSION, version) or arch not in ('amd64', 'arm64'):
        raise ValueError('Нужна версия X.Y.Z и архитектура amd64/arm64.')
    if output.exists():
        raise ValueError('Пакет уже существует.')
    output.parent.mkdir(parents=True, exist_ok=True)
    image = f'wristmind-selfhost:{version}-{arch}'
    def docker(*args):
        subprocess.run(['docker', *args], cwd=installer.ROOT, check=True, env=installer.docker_environment())
    docker('build', '--platform', 'linux/' + arch, '-f', 'selfhost/Dockerfile', '-t', image, '.')
    actual = inspect_image(image)
    if actual['Architecture'] != arch or actual['Os'] != 'linux':
        raise ValueError('Архитектура собранного образа не совпадает.')
    dependencies = {}
    for name, tag in {'db': 'pgvector/pgvector:pg16', 'caddy': 'caddy:2',
                      'tunnel': 'cloudflare/cloudflared:latest', 'search': 'searxng/searxng:latest'}.items():
        docker('pull', '--platform', 'linux/' + arch, tag)
        dependencies[name] = inspect_image(tag)['RepoDigests'][0]
    with tempfile.TemporaryDirectory(prefix='wristmind-release-') as temp:
        staging = Path(temp)
        for name in RUNTIME:
            source = installer.ROOT / name
            if source.is_symlink():
                raise ValueError('Ссылки в исходниках релиза запрещены.')
            destination = staging / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        # Dependency images are pinned by digest and pulled by Compose on the server.
        docker('image', 'save', '-o', str(staging / 'image.tar'), image)
        data = {'format': 1, 'kind': 'release', 'version': version, 'arch': arch, 'schema': 1,
                'postgres_major': 16, 'image': image, 'image_id': actual['Id'], 'dependencies': dependencies}
        checksum = pack(staging, data, output)
    if output.stat().st_size >= 2 * 1024**3:
        output.unlink()
        raise ValueError('Пакет превышает лимит отдельного файла GitHub Releases (2 GiB).')
    (output.parent / (output.name + '.sha256')).write_text(checksum + '  ' + output.name + '\n')
    print(f'Релиз: {output.name}\nSHA256: {checksum}')


def main():
    parser = argparse.ArgumentParser(description='Сборка публичного релиза без приватных данных')
    parser.add_argument('--version', required=True)
    parser.add_argument('--arch', choices=['amd64', 'arm64'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        build(args.version, args.arch, args.output)
        return 0
    except (OSError, ValueError, subprocess.SubprocessError):
        print('Сборка релиза не завершена. Проверьте Docker, версию и каталог результата.', file=sys.stderr)
        return 1

if __name__ == '__main__':
    sys.exit(main())
