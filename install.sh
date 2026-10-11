#!/usr/bin/env bash
# Download the self-host source into an isolated temporary directory and open its CLI.
set -euo pipefail
if [[ ${1:-} == --help || ${1:-} == -h ]]; then
  echo 'WristMind: запуск меню без клонирования репозитория.'
  echo 'bash install.sh [menu|check|status|install|...] [параметры wristmind]'
  echo 'Без параметров открывается меню. Docker устанавливается отдельно.'
  exit 0
fi
if [[ $(uname -s) != Linux ]]; then echo 'Установщик сервера требует Linux.' >&2; exit 1; fi
for WM_TOOL in curl python3 mktemp; do
  command -v "$WM_TOOL" >/dev/null || { echo "Для запуска нужен $WM_TOOL." >&2; exit 1; }
done
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || {
  echo 'Нужен Python 3.10 или новее.' >&2; exit 1;
}
WM_TEMP=$(mktemp -d "${TMPDIR:-/tmp}/wristmind-bootstrap.XXXXXXXX")
trap 'rm -rf -- "$WM_TEMP"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
WM_SOURCE_URL='https://codeload.github.com/IvanSemenkin/wristmind-selfhost/tar.gz/refs/heads/main'
if [[ -t 1 && ${TERM:-dumb} != dumb && ! ${NO_COLOR+x} ]]; then
  printf '\n\033[1;94mWristMind\033[0m  \033[90mSELFHOST\033[0m\n'
  printf '\033[90mЗагружаем меню установки и настройки…\033[0m\n\n'
else
  echo 'WristMind — загружаем меню установки и настройки…'
fi
if ! curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
  --connect-timeout 15 --max-time 180 --max-filesize 67108864 \
  "$WM_SOURCE_URL" --output "$WM_TEMP/source.tar.gz"; then
  echo 'Не удалось скачать WristMind. Проверьте интернет и доступ к репозиторию; установка не изменена.' >&2
  exit 1
fi
python3 - "$WM_TEMP/source.tar.gz" "$WM_TEMP/source" <<'PY'
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile

archive, destination = Path(sys.argv[1]), Path(sys.argv[2])
try:
    with tarfile.open(archive, 'r:gz') as source:
        members = []
        names = set()
        total = 0
        top = None
        for item in source:
            path = PurePosixPath(item.name)
            if path.is_absolute() or '..' in path.parts or not path.parts or not (item.isfile() or item.isdir()):
                raise ValueError('Небезопасный путь или ссылка в архиве.')
            if top is None:
                top = path.parts[0]
            if path.parts[0] != top or item.name in names:
                raise ValueError('Некорректная структура архива.')
            names.add(item.name)
            members.append((item, path))
            total += item.size
            if len(members) > 10000 or total > 256 * 1024**2:
                raise ValueError('Архив превышает допустимый размер.')
        for item, path in members:
            relative = Path(*path.parts[1:])
            target = destination / relative
            if item.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                if not path.parts[1:]:
                    raise ValueError('Некорректный корень архива.')
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(item) as reader, target.open('xb') as writer:
                    shutil.copyfileobj(reader, writer)
                target.chmod(0o755 if item.mode & 0o111 else 0o644)
    for name in ('wristmind', 'compose.yaml', 'selfhost/installer.py'):
        if not (destination / name).is_file():
            raise ValueError('В архиве отсутствуют файлы установщика.')
except (OSError, ValueError, tarfile.TarError) as error:
    print('Не удалось проверить исходники: ' + str(error), file=sys.stderr)
    sys.exit(1)
PY
if [[ $# -eq 0 ]]; then
  WM_DIRECTORY=${WRISTMIND_INSTALL_DIR:-}
  if [[ -z $WM_DIRECTORY ]]; then
    if [[ $EUID == 0 ]]; then WM_DIRECTORY=/opt/wristmind; else WM_DIRECTORY="$HOME/wristmind-server"; fi
    if [[ -t 0 ]]; then
      read -r -p "Каталог установки [$WM_DIRECTORY]: " WM_CHOICE
      WM_DIRECTORY=${WM_CHOICE:-$WM_DIRECTORY}
    fi
  fi
  bash "$WM_TEMP/source/wristmind" menu --install-dir "$WM_DIRECTORY"
else
  bash "$WM_TEMP/source/wristmind" "$@"
fi
