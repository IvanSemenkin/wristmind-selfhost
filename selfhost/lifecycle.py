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
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
            access.atomic(output.with_name(output.name + ".sha256"), checksum + "  " + output.name + "\n")
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


def update(target, package, checksum, nightly=False):
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
        if nightly:
            # Close admission before the final check; existing work is never intentionally stopped.
            pause(target, old_data, True)
            try:
                is_idle = auto_idle(target)
            except BaseException:
                pause(target, old_data, False)
                raise
            if not is_idle:
                pause(target, old_data, False)
                print('Появились активные задания. Обновление отложено до следующей ночи.')
                return
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


def choose_backup(target):
    directory = target / 'backups'
    if directory.is_symlink():
        raise ValueError('Каталог резервных копий не должен быть ссылкой.')
    copies = sorted((p for p in directory.glob('*.tar.gz') if not p.is_symlink() and p.is_file()),
                    key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)
    if not copies:
        print('Резервных копий пока нет. Создайте бэкап в пункте 3.')
        return None
    print('\nВосстановление из резервной копии')
    for number, path in enumerate(copies, 1):
        date = time.strftime('%d.%m.%Y %H:%M', time.localtime(path.stat().st_mtime))
        name = ''.join(c if c.isprintable() else '?' for c in path.name)
        print(f'{number}) {date} · {path.stat().st_size / 1024**2:.1f} МБ · {name}')
    print('0) Назад')
    while True:
        try:
            value = input('Выберите бэкап: ').strip()
        except EOFError:
            return None
        if value == '0':
            return None
        if value.isascii() and value.isdigit() and len(value) <= 6 and 1 <= int(value) <= len(copies):
            package = copies[int(value) - 1]
            break
        print('Введите номер из списка или 0 для возврата.')
    if package.is_symlink():
        raise ValueError('Бэкап не должен быть ссылкой.')
    with installer.wait_status('Проверяю выбранную резервную копию'):
        # Read only the small metadata; do not extract database/private files.
        with tarfile.open(package, 'r|*') as archive:
            info = None
            for count, member in enumerate(archive):
                if count > len(release.RUNTIME) + len(release.PRIVATE) + 4:
                    raise ValueError('Некорректный состав бэкапа.')
                if member.name == 'manifest.json':
                    if not member.isfile() or member.size > 65536:
                        raise ValueError('Некорректный манифест бэкапа.')
                    info = release.metadata(json.load(archive.extractfile(member)))
                    break
        if not info or info['kind'] != 'backup':
            raise ValueError('Выбранный архив не является резервной копией.')
        saved = installer.manifest_at(target)
        if saved and saved['project'] != info['project']:
            raise ValueError('Это резервная копия другого проекта.')
        checksum = release.digest(package)
        sidecar = package.with_name(package.name + '.sha256')
        if sidecar.is_symlink():
            raise ValueError('Файл контрольной суммы не должен быть ссылкой.')
        if sidecar.exists():
            with sidecar.open() as stream:
                expected = stream.read(256).split()
            if expected != [checksum, package.name]:
                raise ValueError('Контрольная сумма бэкапа не совпадает. Восстановление отменено.')
    print(f"Выбрана копия: {package.name}\nВерсия: {info['version']} · проект: {info['project']}")
    print('Восстановление заменит текущие данные выбранной копией. Перед этим будет создан бэкап нынешнего состояния.')
    try:
        answer = input('Восстановить? Введите «да» для подтверждения: ').strip().lower()
    except EOFError:
        answer = ''
    if answer != 'да':
        print('Восстановление отменено.')
        return None
    return package, checksum, info['project']


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
    parser.add_argument('command', choices=['backup', 'update', 'restore-menu', 'restore', 'rollback', 'remove', 'install-release', 'version'])
    parser.add_argument('--install-dir', type=Path, required=True)
    parser.add_argument('--package', type=Path)
    parser.add_argument('--url')
    parser.add_argument('--latest', action='store_true')
    parser.add_argument('--nightly', action='store_true')
    parser.add_argument('--sha256')
    parser.add_argument('--confirm-project')
    parser.add_argument('--no-safety-backup', action='store_true', help='Явное аварийное восстановление без копирования текущего повреждённого состояния')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--demo', action='store_true')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    target = args.install_dir
    if args.nightly and (args.command != 'update' or not args.latest):
        parser.error('--nightly доступен только для update --latest.')
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
            if args.command == 'restore-menu':
                selected = choose_backup(target)
                if selected is None:
                    return 0
                args.package, args.sha256, args.confirm_project = selected
                args.command = 'restore'
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
                if args.nightly:
                    if not auto_idle(target):
                        print('Во время скачивания появились активные задания. Обновление отложено до следующей ночи.')
                        return 0
                if args.nightly:
                    update(target, args.package, args.sha256, nightly=True)
                else:
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

CONFIG = '.wristmind-auto-update.json'
UNITS = Path('/etc/systemd/system')
BUSY_CODE = """import asyncio
from sqlalchemy import select, func
from wristmind_server.database import SessionFactory
from wristmind_server.db_models import Job
async def check():
 async with SessionFactory() as session:
  count = await session.scalar(select(func.count()).select_from(Job).where(Job.status.in_(['queued','running'])))
  print('BUSY' if count else 'IDLE')
asyncio.run(check())
"""


def auto_validate_schedule(clock, zone):
    if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', clock):
        raise ValueError('Время должно быть в формате ЧЧ:ММ, например 04:00.')
    if not re.fullmatch(r'[A-Za-z0-9_+/-]+', zone) or zone.startswith('/') or '..' in zone:
        raise ValueError('Укажите часовой пояс, например Europe/Moscow.')
    try:
        ZoneInfo(zone)
    except (ValueError, ZoneInfoNotFoundError):
        raise ValueError('Неизвестный часовой пояс. Используйте имя из timedatectl list-timezones.') from None
    return f'*-*-* {clock}:00 {zone}'


def auto_unit_name(target):
    return 'wristmind-update-' + hashlib.sha256(str(target.resolve()).encode()).hexdigest()[:12]


def auto_quote_unit(value):
    if any(char in str(value) for char in '\n\r\x00'):
        raise ValueError('Недопустимый путь.')
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'


def auto_unit_files(target, clock, zone):
    calendar = auto_validate_schedule(clock, zone)
    script = target / 'selfhost/lifecycle.py'
    service = f'''[Unit]
Description=WristMind nightly verified update
Wants=network-online.target
After=network-online.target docker.service
ConditionPathExists={auto_quote_unit(target / '.wristmind-install')[1:-1]}

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 {auto_quote_unit(script)} --auto-update run --install-dir {auto_quote_unit(target)}
WorkingDirectory={auto_quote_unit(target)[1:-1]}
TimeoutStartSec=2h
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
'''
    timer = f'''[Unit]
Description=WristMind nightly update at {clock} ({zone})

[Timer]
OnCalendar={calendar}
Persistent=false
AccuracySec=1min
Unit={auto_unit_name(target)}.service

[Install]
WantedBy=timers.target
'''
    return service, timer


def auto_settings(target):
    path = target / CONFIG
    if path.is_symlink():
        raise ValueError('Настройки автообновления не должны быть ссылкой.')
    return json.loads(path.read_text()) if path.exists() else {'enabled': False, 'time': '04:00', 'timezone': 'Europe/Moscow'}


def auto_default_zone():
    path = Path('/etc/timezone')
    if path.exists():
        candidate = path.read_text().strip()
        try:
            auto_validate_schedule('04:00', candidate)
            return candidate
        except ValueError:
            pass
    try:
        candidate = str(Path('/etc/localtime').resolve()).split('/zoneinfo/', 1)[1]
        auto_validate_schedule('04:00', candidate)
        return candidate
    except (IndexError, ValueError):
        return 'Etc/UTC'


def auto_systemctl(*args):
    subprocess.run(['systemctl', *args], check=True, timeout=30)


def auto_configure(target, enabled, clock='04:00', zone='Europe/Moscow'):
    state(target, False)  # Reject an absent/foreign/partial installation before touching systemd.
    service, timer = auto_unit_files(target, clock, zone)
    if os.geteuid() != 0:
        args = [sys.executable, str(Path(__file__).resolve()), '--auto-update', 'enable' if enabled else 'disable',
                '--install-dir', str(target), '--time', clock, '--timezone', zone]
        subprocess.run(['sudo', *args], check=True)
        return
    if not Path('/run/systemd/system').exists():
        raise ValueError('Для ночного автообновления нужен сервер с systemd.')
    name = auto_unit_name(target)
    with access.locked(target):
        if enabled:
            runtime = target / 'selfhost/lifecycle.py'
            if runtime.is_symlink() or not runtime.is_file() or 'def auto_main(' not in runtime.read_text():
                raise ValueError('Сначала обновите установку через меню 5 → 2, затем включите расписание.')
            access.atomic(UNITS / (name + '.service'), service)
            access.atomic(UNITS / (name + '.timer'), timer)
            auto_systemctl('daemon-reload')
            auto_systemctl('enable', '--now', name + '.timer')
            auto_systemctl('restart', name + '.timer')
        else:
            auto_systemctl('disable', '--now', name + '.timer')
        access.atomic(target / CONFIG, json.dumps({'enabled': enabled, 'time': clock, 'timezone': zone}, indent=2) + '\n')
    auto_show(target)


def auto_show(target):
    data = auto_settings(target)
    print('Ночное автообновление: ' + ('включено' if data['enabled'] else 'выключено'))
    if data['enabled']:
        print(f"Ежедневно в {data['time']} · {data['timezone']}")
        print('Активные задания: обновление пропускается до следующей ночи.')
        print('Пропущенное время не догоняется при дневном запуске сервера.')
        name = auto_unit_name(target)
        subprocess.run(['systemctl', 'list-timers', name + '.timer', '--no-pager'], check=False, timeout=10)
        print('Логи: journalctl -u ' + name + '.service --no-pager')


def auto_idle(target):
    data, _ = state(target, False)
    result = subprocess.run(command(target, data, 'exec', '-T', 'api', 'python', '-c', BUSY_CODE),
        cwd=target, env=installer.docker_environment(), capture_output=True, text=True, timeout=20, check=True)
    if result.stdout.strip() not in {'BUSY', 'IDLE'}:
        raise ValueError('Не удалось проверить активные задания; обновление пропущено.')
    return result.stdout.strip() == 'IDLE'


def auto_run(target):
    config = auto_settings(target)
    if not config['enabled']:
        print('Ночное автообновление выключено.')
        return 0
    # No downloads, backups or maintenance if a search/answer/ingestion is currently running.
    with access.locked(target):
        ensure_idle(target)
        if not auto_idle(target):
            print('Есть активные задания. Обновление отложено до следующей ночи.')
            return 0
    # The normal updater owns its own exclusive lock, checksum, mandatory backup and rollback.
    return subprocess.run([sys.executable, str(target / 'selfhost/lifecycle.py'), 'update', '--latest',
                           '--nightly', '--install-dir', str(target)], check=False).returncode


def auto_menu(target):
    while True:
        print('\nНочные обновления WristMind')
        auto_show(target)
        print('1) Включить / изменить время\n2) Выключить\n0) Назад')
        answer = input('Выберите пункт: ').strip()
        if answer == '0':
            return
        if answer == '1':
            data = auto_settings(target)
            clock = input(f"Время [{data.get('time', '04:00')}]: ").strip() or data.get('time', '04:00')
            zone = input(f"Ваш часовой пояс [{auto_default_zone()}], например Europe/Moscow: ").strip() or auto_default_zone()
            auto_validate_schedule(clock, zone)
            print(f'Каждую ночь в {clock} ({zone}): проверка выпуска, бэкап, обновление и проверка запуска.')
            print('При ошибке — откат к прежней версии; при активных заданиях — пропуск до следующей ночи.')
            if input('Включить? [y/N]: ').strip().lower() in {'y', 'yes', 'д', 'да'}:
                auto_configure(target, True, clock, zone)
        elif answer == '2':
            data = auto_settings(target)
            if data['enabled']:
                auto_configure(target, False, data['time'], data['timezone'])
            else:
                print('Уже выключено.')


def auto_main():
    parser = argparse.ArgumentParser(description='Ночное автообновление только через терминал')
    parser.add_argument('action', choices=['menu', 'enable', 'disable', 'status', 'run'])
    parser.add_argument('--install-dir', type=Path, required=True)
    parser.add_argument('--time', default='04:00')
    parser.add_argument('--timezone', default='Europe/Moscow')
    args = parser.parse_args(sys.argv[2:])
    target = args.install_dir
    if not target.is_absolute() or target == Path('/') or target.is_symlink():
        parser.error('Неверный каталог установки.')
    try:
        if args.action == 'menu':
            auto_menu(target)
        elif args.action == 'status':
            auto_show(target)
        elif args.action == 'run':
            return auto_run(target)
        else:
            auto_configure(target, args.action == 'enable', args.time, args.timezone)
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(str(error) if isinstance(error, ValueError) else 'Не удалось настроить/выполнить ночное обновление. Проверьте systemd и права.', file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        return 0


if __name__ == '__main__':
    sys.exit(auto_main() if sys.argv[1:2] == ['--auto-update'] else main())
