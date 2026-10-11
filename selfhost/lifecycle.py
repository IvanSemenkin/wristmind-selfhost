"""Terminal-only maintenance. Full snapshots; no volume deletion or silent data reset."""
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
import tempfile
import tarfile
import time
from types import SimpleNamespace

import access
import installer
import release

JOURNAL = '.wristmind-operation'
LAST = '.wristmind-last-update'
WRITERS = {'api', 'worker', 'telegram-bot', 'gateway'}
BACKUP_CODE = """import pathlib,sys,tarfile
root=pathlib.Path('/data/private')
if any(p.is_symlink() for p in root.rglob('*')): raise ValueError('symlink')
with tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz') as t: t.add(root,arcname='private')
"""
# Validate the complete inner archive before replacing any private file. SQL and files
# are restored while API/worker/gateway are stopped. Never follow archive links.
RESTORE_CODE = """import pathlib,sys,tarfile,tempfile,shutil,pwd,os
root=pathlib.Path('/data/private')
with tempfile.TemporaryFile() as f:
 shutil.copyfileobj(sys.stdin.buffer,f); f.seek(0)
 with tarfile.open(fileobj=f,mode='r:gz') as t:
  members=t.getmembers()
  names=[m.name for m in members]
  if len(members)>100000 or len(names)!=len(set(names)) or sum(m.size for m in members)>32*1024**3: raise ValueError('size')
  for m in members:
   p=pathlib.PurePosixPath(m.name)
   if p.is_absolute() or '..' in p.parts or not p.parts or p.parts[0]!='private' or not (m.isfile() or m.isdir()): raise ValueError('unsafe')
  if any(p.is_symlink() for p in root.rglob('*')): raise ValueError('existing symlink')
  for p in root.iterdir():
   if p.is_dir(): shutil.rmtree(p)
   else: p.unlink()
  for m in members:
   p=root.joinpath(*pathlib.PurePosixPath(m.name).parts[1:])
   if m.isdir(): p.mkdir(parents=True,exist_ok=True)
   else:
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('wb') as out,t.extractfile(m) as src: shutil.copyfileobj(src,out)
    p.chmod(0o600)
  owner=pwd.getpwnam('wristmind')
  os.chown(root,owner.pw_uid,owner.pw_gid)
  root.chmod(0o700)
  for p in root.rglob('*'):
   os.chown(p,owner.pw_uid,owner.pw_gid)
   if p.is_dir(): p.chmod(0o700)
"""


def operation_label(command, target, source=None, destination=None):
    if destination:
        return {'database.dump': 'Сохраняю базу данных', 'private.tar.gz': 'Сохраняю пользовательские файлы',
                'image.tar': 'Сохраняю прежний Docker-образ'}.get(destination.name, 'Создаю резервную копию')
    if command[:3] == ['docker', 'image', 'load']:
        return 'Загружаю Docker-образ из пакета'
    if command[:3] == ['docker', 'image', 'pull']:
        return 'Скачиваю образ зависимости'
    if 'up' in command:
        return 'Запускаю сервисы и ожидаю их готовности'
    if 'stop' in command or 'down' in command:
        return 'Останавливаю сервисы'
    if 'pg_restore' in command:
        return 'Восстанавливаю базу данных'
    return 'Выполняю операцию Docker'


@installer.with_status(operation_label)
def run(command, target, source=None, destination=None):
    # Binary database/file/image streams never enter logs or terminal output.
    with (source.open('rb') if source else open(os.devnull, 'rb')) as input_stream:
        with (destination.open('xb') if destination else open(os.devnull, 'wb')) as output:
            if destination:
                os.chmod(destination, 0o600)
            result = subprocess.run(command, cwd=target, env=installer.docker_environment(), stdin=input_stream,
                                    stdout=output, stderr=subprocess.DEVNULL, timeout=1800)
    if result.returncode:
        raise RuntimeError('Операция Docker не завершилась; приватный вывод скрыт.')


def command(target, data, *args):
    return installer.compose(target, data, *args)


def state(target, require_ready=True):
    if target.is_symlink():
        raise ValueError('Каталог установки не должен быть ссылкой.')
    data = installer.manifest_at(target)
    values = installer.validate_saved(target, data)
    if require_ready and data['phase'] != 'ready':
        raise ValueError('Установка не завершена.')
    return data, values


@installer.with_status('Проверяю запущенные сервисы')
def running(target, data):
    result = subprocess.run(command(target, data, 'ps', '--status', 'running', '--services'),
        capture_output=True, text=True, check=True, timeout=20, env=installer.docker_environment())
    names = result.stdout.split()
    if set(names) - {'db', 'api', 'worker', 'gateway', 'telegram-bot', 'searxng', 'ollama', 'local-speech'}:
        raise ValueError('Обнаружены неизвестные сервисы; обслуживание остановлено.')
    return names


def start(target, data, names=None):
    timeout = '600' if names and set(names) & {'ollama', 'local-speech'} else '120'
    args = ['up', '-d', '--no-build', '--wait', '--wait-timeout', timeout]
    run(command(target, data, *args, *(names or [])), target)


def write_journal(target, **data):
    access.atomic(target / JOURNAL, json.dumps(data) + '\n')


def read_journal(target):
    path = target / JOURNAL
    if path.is_symlink():
        raise ValueError('Журнал операции не должен быть ссылкой.')
    return json.loads(path.read_text()) if path.exists() else {}


def pause(target, data, enabled):
    code = "from pathlib import Path; p=Path('/data/private/.wristmind-maintenance'); " + (
        "p.touch(exist_ok=True)" if enabled else "p.unlink(missing_ok=True)")
    run(command(target, data, 'run', '--rm', '--no-deps', '-T', '--user', '0', '--entrypoint', 'python', 'api', '-c', code), target)


def backup(target, paused=False):
    data, values = state(target)
    names = running(target, data)
    if not {'db', 'api', 'worker'}.issubset(names):
        raise ValueError('Для согласованного бэкапа нужны работающие db/api/worker. Сначала восстановите запуск.')
    directory = target / 'backups'
    if directory.is_symlink():
        raise ValueError('Каталог резервных копий не должен быть ссылкой.')
    directory.mkdir(mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    output = directory / (time.strftime('%Y%m%d-%H%M%S') + '-' + os.urandom(4).hex() + '.tar.gz')
    writers = sorted(set(names) & WRITERS)
    old = read_journal(target)
    write_journal(target, phase='backing-up', running=writers, previous=old)
    completed = False
    try:
        run(command(target, data, 'stop', *writers), target)
        pause(target, data, True)
        with tempfile.TemporaryDirectory(prefix='.backup-', dir=directory) as temp:
            staging = Path(temp)
            for name in (*release.RUNTIME, *release.PRIVATE):
                source = target / name
                if source.is_symlink():
                    raise ValueError('Ссылки в конфигурации запрещены.')
                if source.exists():
                    destination = staging / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
                    os.chmod(destination, 0o600)
            run(command(target, data, 'exec', '-T', 'db', 'pg_dump', '-U', 'wristmind', '-d', 'wristmind', '-Fc'),
                target, destination=staging / 'database.dump')
            run(command(target, data, 'run', '--rm', '--no-deps', '-T', '--user', '0', '--entrypoint', 'python', 'api', '-c', BACKUP_CODE),
                target, destination=staging / 'private.tar.gz')
            info = release.inspect_image(values['WRISTMIND_IMAGE'])
            run(['docker', 'image', 'save', values['WRISTMIND_IMAGE']], target, destination=staging / 'image.tar')
            manifest = {'format': 1, 'kind': 'backup', 'version': data.get('release', {}).get('version', '0.0.0'),
                'arch': info['Architecture'], 'schema': 1, 'postgres_major': 16, 'image': values['WRISTMIND_IMAGE'],
                'image_id': info['Id'], 'project': data['project'], 'running': names}
            checksum = release.pack(staging, manifest, output)
        completed = True
    finally:
        if not paused or not completed:
            pause(target, data, False)
            start(target, data, writers)
            access.atomic(target / JOURNAL, json.dumps(old) + '\n')
    if paused:
        write_journal(target, phase='updating', recovery=str(output), sha256=checksum, running=names)
    print(f'Резервная копия: {output}\nSHA256: {checksum}')
    return output, checksum


def daemon_arch():
    result = subprocess.run(['docker', 'version', '--format', '{{.Server.Arch}}'], capture_output=True,
        text=True, check=True, timeout=20, env=installer.docker_environment())
    arch = result.stdout.strip()
    if arch not in {'amd64', 'arm64'}:
        raise ValueError('Поддерживаются Linux amd64 и arm64.')
    return arch


@installer.with_status('Проверяю идентификатор и архитектуру образа')
def check_image(target, manifest, image_archive=None):
    actual = release.inspect_image(manifest['image'])
    matches = actual['Id'] == manifest['image_id']
    # Classic Docker reports the config digest; containerd reports the OCI
    # manifest digest. Accept only a cryptographically verified link in the
    # image archive whose checksum was already checked by release.unpack.
    if not matches and image_archive is not None:
        with tarfile.open(image_archive, 'r:*') as archive:
            for manifest_id, config_id in ((actual['Id'], manifest['image_id']),
                                           (manifest['image_id'], actual['Id'])):
                if not re.fullmatch(r'sha256:[0-9a-f]{64}', manifest_id):
                    continue
                try:
                    member = archive.getmember('blobs/sha256/' + manifest_id[7:])
                except KeyError:
                    continue
                if not member.isfile() or member.size > 65536:
                    continue
                blob = archive.extractfile(member).read()
                if 'sha256:' + hashlib.sha256(blob).hexdigest() != manifest_id:
                    continue
                try:
                    document = json.loads(blob)
                    matches = document.get('schemaVersion') == 2 and document.get('config', {}).get('digest') == config_id
                except (ValueError, AttributeError):
                    continue
                if matches:
                    break
    if not matches or actual['Architecture'] != manifest['arch'] or actual['Os'] != 'linux':
        raise ValueError('Загруженный образ не совпадает с манифестом.')


def stage_files(target, staging, names):
    for name in names:
        path = target / name
        if path.is_symlink():
            raise ValueError('Ссылка в настройках запрещена.')
        path.parent.mkdir(parents=True, exist_ok=True)
        if (staging / name).exists():
            access.atomic(path, (staging / name).read_bytes())
            if name == 'wristmind':
                path.chmod(0o700)
        else:
            path.unlink(missing_ok=True)


def helper(target, data, code, source):
    run(command(target, data, 'run', '--rm', '--no-deps', '-T', '--user', '0', '--entrypoint', 'python', 'api', '-c', code), target, source=source)


def validate_private(path):
    with tarfile.open(path, 'r:gz') as archive:
        members = archive.getmembers()
        files = {member.name for member in members if member.isfile()}
        names = [member.name for member in members]
        if len(members) > 100000 or len(names) != len(set(names)) or sum(m.size for m in members) > release.MAX_BYTES:
            raise ValueError('Слишком большой архив приватных файлов.')
        for member in members:
            p = Path(member.name)
            if p.is_absolute() or '..' in p.parts or not p.parts or p.parts[0] != 'private' or p.as_posix() != member.name or not (member.isfile() or member.isdir()):
                raise ValueError('Небезопасный архив приватных файлов.')
            if member.name == 'private' and not member.isdir():
                raise ValueError('Корень приватных файлов должен быть каталогом.')
            if any(parent.as_posix() in files for parent in p.parents):
                raise ValueError('Файл используется как родительский каталог.')


def apply_backup(target, staging, info):
    saved = installer.manifest_at(staging)
    values = installer.validate_saved(staging, saved)
    if values['WRISTMIND_IMAGE'] != info['image'] or saved['project'] != info['project']:
        raise ValueError('Бэкап не соответствует собственной конфигурации.')
    validate_private(staging / 'private.tar.gz')
    with (staging / 'database.dump').open('rb') as dump:
        if dump.read(5) != b'PGDMP':
            raise ValueError('Повреждён архив базы данных.')
    run(['docker', 'image', 'load'], target, source=staging / 'image.tar')
    check_image(target, info, staging / 'image.tar')
    # Also stop possibly half-started new services, using current valid configuration.
    if installer.manifest_at(target):
        current, _ = state(target, False)
        active = sorted(set(running(target, current)) & WRITERS)
        if active:
            run(command(target, current, 'stop', *active), target)
    stage_files(target, staging, (*release.RUNTIME, *release.PRIVATE))
    run(command(target, saved, 'config', '--quiet'), target)
    start(target, saved, ['db'])
    run(command(target, saved, 'exec', '-T', 'db', 'pg_restore', '--list'), target, source=staging / 'database.dump')
    run(command(target, saved, 'exec', '-T', 'db', 'dropdb', '-U', 'wristmind', '--force', '--if-exists', 'wristmind'), target)
    run(command(target, saved, 'exec', '-T', 'db', 'createdb', '-U', 'wristmind', 'wristmind'), target)
    run(command(target, saved, 'exec', '-T', 'db', 'pg_restore', '-U', 'wristmind', '-d', 'wristmind',
                '--exit-on-error', '--no-owner', '--no-privileges'), target, source=staging / 'database.dump')
    helper(target, saved, RESTORE_CODE, staging / 'private.tar.gz')
    pause(target, saved, True)
    start(target, saved, info['running'])
    installer.health(target, saved, 20)


def ensure_idle(target):
    if read_journal(target).get('phase') in {'backing-up', 'updating', 'restoring', 'failed'}:
        raise ValueError('Предыдущая операция не завершена. Используйте rollback или restore, прежде чем обновляться.')


def update(target, package, checksum):
    ensure_idle(target)
    old_data, _ = state(target)
    with tempfile.TemporaryDirectory(prefix='wristmind-update-') as temp:
        staging = Path(temp)
        info = release.unpack(package, checksum, staging)
        if info['kind'] != 'release':
            raise ValueError('Для update нужен релиз, а не бэкап.')
        arch = release.inspect_image(installer.read_env(target)['WRISTMIND_IMAGE'])['Architecture']
        if info['arch'] != arch:
            raise ValueError('Архитектура релиза не подходит серверу.')
        current = old_data.get('release', {}).get('version', '0.0.0')
        if tuple(map(int, info['version'].split('.'))) <= tuple(map(int, current.split('.'))):
            raise ValueError('Версия не новее текущей. Для возврата используйте rollback.')
        # Image/dependencies are obtained before the maintenance pause, so a network
        # failure cannot take an otherwise healthy installation offline.
        run(['docker', 'image', 'load'], target, source=staging / 'image.tar')
        check_image(target, info, staging / 'image.tar')
        active = {'db'}
        mode = old_data.get('access', {}).get('mode')
        if mode in {'domain', 'tunnel'}:
            active.add('caddy' if mode == 'domain' else 'tunnel')
        if 'searxng' in running(target, old_data):
            active.add('search')
        for name in sorted(active):
            run(['docker', 'image', 'pull', info['dependencies'][name]], target)
        recovery, recovery_hash = backup(target, paused=True)
        try:
            stage_files(target, staging, release.RUNTIME)
            changes = {'WRISTMIND_IMAGE': info['image'], 'WRISTMIND_DATABASE_IMAGE': info['dependencies']['db'],
                'WRISTMIND_CADDY_IMAGE': info['dependencies']['caddy'], 'WRISTMIND_TUNNEL_IMAGE': info['dependencies']['tunnel'],
                'WRISTMIND_SEARCH_IMAGE': info['dependencies']['search']}
            access.atomic(target / '.env', access.update_env((target / '.env').read_text(), changes))
            old_data['release'] = {key: info[key] for key in ('version', 'image', 'image_id', 'arch', 'schema')}
            installer.write_manifest(target, old_data)
            run(command(target, old_data, 'config', '--quiet'), target)
            start(target, old_data, ['db', 'api', 'worker'])
            installer.health(target, old_data, 20)
            # Open the external gateway only after the new API passes health.
            names = read_journal(target)['running']
            start(target, old_data, names)
            installer.health(target, old_data, 20)
            access.atomic(target / LAST, json.dumps({'recovery': str(recovery), 'sha256': recovery_hash}) + '\n')
            write_journal(target, phase='ready')
            pause(target, old_data, False)
        except BaseException:
            try:
                with tempfile.TemporaryDirectory(prefix='wristmind-rollback-') as restore_temp:
                    restored = Path(restore_temp)
                    snapshot = release.unpack(recovery, recovery_hash, restored)
                    apply_backup(target, restored, snapshot)
                write_journal(target, phase='rolled-back', recovery=str(recovery), sha256=recovery_hash)
                pause(target, installer.manifest_at(target), False)
                print('Обновление не завершилось. Прежняя версия и данные восстановлены.', file=sys.stderr)
            except BaseException:
                write_journal(target, phase='failed', recovery=str(recovery), sha256=recovery_hash)
                print('Автоматический откат не завершён. Бэкап сохранён; выполните rollback после восстановления Docker.', file=sys.stderr)
            raise
        print(f"Обновлено до {info['version']}. Возврат: wristmind rollback с подтверждением проекта.")


@installer.with_status('Проверяю доступность проекта')
def project_available(project):
    result = subprocess.run(['docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project=' + project],
        capture_output=True, text=True, check=True, timeout=20, env=installer.docker_environment())
    if result.stdout.strip():
        raise ValueError('Проект уже существует в Docker. Не восстанавливайте второй экземпляр с тем же именем; сначала удалите старые контейнеры, сохранив томы.')


def restore(target, package, checksum, confirmation, safety=True):
    with tempfile.TemporaryDirectory(prefix='wristmind-restore-') as temp:
        staging = Path(temp)
        info = release.unpack(package, checksum, staging)
        if info['kind'] != 'backup' or confirmation != info['project']:
            raise ValueError('Нужен бэкап и --confirm-project с точным именем его проекта.')
        fresh = installer.state(target) == 'new'
        if not fresh:
            current, _ = state(target, False)
            if current['project'] != info['project']:
                raise ValueError('Бэкап другого проекта не применяется поверх этой установки.')
        saved = installer.manifest_at(staging)
        installer.validate_saved(staging, saved)
        validate_private(staging / 'private.tar.gz')
        if fresh:
            project_available(info['project'])
            target.mkdir(mode=0o700, exist_ok=True)
        recovery = None
        if not fresh and safety:
            recovery = backup(target, paused=True)
        write_journal(target, phase='restoring', recovery=str(recovery[0]) if recovery else str(package),
                      sha256=recovery[1] if recovery else checksum)
        try:
            apply_backup(target, staging, info)
            write_journal(target, phase='ready')
            pause(target, installer.manifest_at(target), False)
        except BaseException:
            write_journal(target, phase='failed', recovery=str(recovery[0]) if recovery else str(package),
                          sha256=recovery[1] if recovery else checksum)
            raise
        print('Состояние из резервной копии восстановлено. Более новые данные заменены.')


def rollback(target, confirmation):
    record = read_journal(target)
    if record.get('phase') == 'backing-up':
        data, _ = state(target, False)
        if confirmation != data['project']:
            raise ValueError('Подтвердите имя проекта через --confirm-project.')
        names = record.get('running', [])
        if set(names) - WRITERS:
            raise ValueError('Повреждён журнал обслуживания.')
        pause(target, data, False)
        start(target, data, names)
        access.atomic(target / JOURNAL, json.dumps(record.get('previous', {})) + '\n')
        print('Прерванный бэкап отменён; прежние сервисы запущены.')
        return
    if not record.get('recovery'):
        path = target / LAST
        if path.is_symlink() or not path.exists():
            raise ValueError('Нет сохранённой точки отката.')
        record = json.loads(path.read_text())
    package = Path(record['recovery'])
    # Only a local, protected recovery point; never execute a path from the journal.
    restore(target, package, record['sha256'], confirmation, safety=False)


def install_release(target, package, checksum, port, demo, resume=False):
    with tempfile.TemporaryDirectory(prefix='wristmind-install-release-') as temp:
        staging = Path(temp)
        info = release.unpack(package, checksum, staging)
        if info['kind'] != 'release':
            raise ValueError('install-release требует релиз.')
        if info['arch'] != daemon_arch():
            raise ValueError('Архитектура пакета не совпадает с Docker-сервером.')
        fresh = installer.state(target) == 'new'
        if not fresh:
            data, values = state(target, False)
            if not resume or data['phase'] == 'ready' or data.get('release', {}).get('image_id') != info['image_id'] or data['port'] != port or data['demo'] != demo:
                raise ValueError('Каталог занят. Для своего незавершённого релиза повторите с --resume и прежними параметрами.')
        if target.resolve().is_relative_to(installer.ROOT) or installer.ROOT.is_relative_to(target.resolve()):
            raise ValueError('Каталог установки должен находиться вне исходников.')
        target.parent.mkdir(parents=True, exist_ok=True)
        if fresh:
            data, values = installer.prepare(target, SimpleNamespace(port=port, bind='127.0.0.1', demo=demo), files=staging)
        changes = {'WRISTMIND_IMAGE': info['image'], 'WRISTMIND_DATABASE_IMAGE': info['dependencies']['db'],
            'WRISTMIND_CADDY_IMAGE': info['dependencies']['caddy'], 'WRISTMIND_TUNNEL_IMAGE': info['dependencies']['tunnel'],
            'WRISTMIND_SEARCH_IMAGE': info['dependencies']['search']}
        access.atomic(target / '.env', access.update_env((target / '.env').read_text(), changes))
        data['release'] = {key: info[key] for key in ('version', 'image', 'image_id', 'arch', 'schema')}
        installer.write_manifest(target, data)
        try:
            run(['docker', 'image', 'load'], target, source=staging / 'image.tar')
            check_image(target, info, staging / 'image.tar')
            run(command(target, data, 'config', '--quiet'), target)
            start(target, data)
            installer.health(target, data, 20)
            data['phase'] = 'ready'
        except BaseException:
            data['phase'] = 'failed'
            installer.write_manifest(target, data)
            raise
        installer.write_manifest(target, data)
        print(f'Релиз {info["version"]} установлен. Первый вход: wristmind setup-link с тем же каталогом.')


def main():
    parser = argparse.ArgumentParser(description='Терминальное обслуживание WristMind')
    parser.add_argument('command', choices=['backup', 'update', 'restore', 'rollback', 'remove', 'install-release', 'version'])
    parser.add_argument('--install-dir', type=Path, required=True)
    parser.add_argument('--package', type=Path)
    parser.add_argument('--url')
    parser.add_argument('--latest', action='store_true')
    parser.add_argument('--sha256')
    parser.add_argument('--confirm-project')
    parser.add_argument('--no-safety-backup', action='store_true', help='Явное аварийное восстановление без копирования текущего повреждённого состояния')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--demo', action='store_true')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    target = args.install_dir
    if not target.is_absolute() or target == Path('/') or target.is_symlink() or not 1 <= args.port <= 65535:
        parser.error('Неверный каталог или порт.')
    if args.latest:
        if args.command != 'update' or args.package or args.url or args.sha256:
            parser.error('--latest доступен только для автоматического update.')
        try:
            print('Проверяю новые выпуски WristMind…', flush=True)
            latest_version, args.url, args.sha256 = release.latest_release()
        except (OSError, ValueError, KeyError, TypeError):
            print('Не удалось получить выпуск с GitHub. Повторите позже.', file=sys.stderr)
            return 1
    if args.command in ('update', 'restore', 'install-release') and (bool(args.package) == bool(args.url) or not re.fullmatch(r'[0-9a-f]{64}', args.sha256 or '')):
        parser.error('Укажите --package либо --url, а также доверенный --sha256.')
    if args.no_safety_backup and args.command != 'restore':
        parser.error('--no-safety-backup разрешён только для аварийного restore; бэкап перед update обязателен.')
    if not target.parent.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with access.locked(target), tempfile.TemporaryDirectory(prefix='wristmind-download-') as downloaded:
            if args.latest:
                data, _ = state(target, False)
                current = data.get('release', {}).get('version', '0.0.0')
                if tuple(map(int, current.split('.'))) >= tuple(map(int, latest_version.split('.'))):
                    print('Уже установлена актуальная версия: ' + current)
                    return 0
                print('Скачиваю обновление ' + latest_version + '…', flush=True)
            if args.url:
                args.package = Path(downloaded) / 'package.tar.gz'
                release.fetch(args.url, args.package, args.sha256)
            if args.command == 'version':
                data, _ = state(target, False)
                print(f"Версия: {data.get('release', {}).get('version', 'local-development')}\nПроект: {data['project']}\nОперация: {read_journal(target).get('phase', 'нет')}")
            elif args.command == 'backup':
                ensure_idle(target); backup(target)
            elif args.command == 'update':
                update(target, args.package, args.sha256)
            elif args.command == 'restore':
                restore(target, args.package, args.sha256, args.confirm_project, not args.no_safety_backup)
            elif args.command == 'rollback':
                rollback(target, args.confirm_project)
            elif args.command == 'install-release':
                install_release(target, args.package, args.sha256, args.port, args.demo, args.resume)
            else:
                ensure_idle(target)
                data, _ = state(target, False)
                if args.confirm_project != data['project']:
                    raise ValueError('Для удаления контейнеров укажите --confirm-project. Томы и данные будут сохранены.')
                run(command(target, data, 'down'), target)
                print('Контейнеры удалены. Конфигурация, резервные копии и все томы сохранены.')
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, tarfile.TarError) as error:
        print(str(error) if isinstance(error, (ValueError, RuntimeError)) else 'Операция не завершена. Проверьте Docker, файлы и состояние обслуживания.', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('Операция прервана. Проверьте version; при незавершённой операции используйте rollback.', file=sys.stderr)
        return 130

if __name__ == '__main__':
    sys.exit(main())
