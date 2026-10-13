"""Export reviewed source paths without inherited Git history or private state.

This is a release preparation tool, not a substitute for a human security review.
"""
from __future__ import annotations
import argparse
import fnmatch
import os
from pathlib import Path
import re
import shutil
import tempfile

FILES = ('.gitignore', '.dockerignore', '.env.example', 'README.md', 'SETUP.md', 'DESIGN_SYSTEM.md',
         'RELEASE_NOTES.md', 'compose.yaml', 'wristmind', 'install.sh')
TREES = ('selfhost', 'server/src', 'server/tests', 'web/src', 'web/public',
         'android/core', 'android/phone', 'android/wear', 'android/panel',
         'android/gradle', 'assets/branding', '.github/workflows')
EXTRA = ('server/pyproject.toml', 'web/package.json', 'web/package-lock.json',
         'web/tsconfig.json', 'web/vite.config.ts', 'web/vinext.config.ts',
         'web/index.html', 'web/tsconfig.app.json', 'web/tsconfig.node.json', 'android/build.gradle.kts', 'android/settings.gradle.kts',
         'android/gradle.properties', 'android/gradlew', 'android/gradlew.bat',
         'docs/ADAPTIVE_WEB_SEARCH_BENCHMARK.json')
DOCS = ('SELF_HOSTING_INSTALL', 'SELF_HOSTING_ACCESS', 'SELF_HOSTING_RELEASES',
        'SELF_HOSTING_RUNTIME', 'SELF_HOSTING_CAPABILITIES', 'LOCAL_MODELS',
        'COMPANION_SETUP', 'PUBLIC_RELEASE_CHECKLIST', 'PROMPT_PARITY', 'ASSISTANT_SYSTEM_PROMPT', 'LONG_WEB_DOCUMENTS', 'DEEP_WEB_SEARCH',
        'ADAPTIVE_WEB_SEARCH', 'SEARCH_PRIMARY_SOURCE_FIX', 'SEARCH_OBSERVABILITY')
BLOCKED = ('build', 'node_modules', '__pycache__', '.pytest_cache', '.gradle',
           '.kotlin', 'data', 'data-v2', '.runtime', '.git', '.well-known')
PATTERNS = ('.env*', '*.db', '*.sqlite*', '*.jks', '*.keystore', '*.pem', '*.key',
            '*firebase*json', 'google-services.json', 'local.properties', '*.apk',
            '*.p12', '*.pfx', '*.tsbuildinfo', '*.pyc', '.tunnel-token', '.access-*', 'private-config.js')
SECRETS = re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|'
                     r'\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{24,}|'
                     r'\b(?:ghp|github_pat)_[A-Za-z0-9_]{30,}')


def allowed(path: Path) -> bool:
    return not any(part in BLOCKED or part.startswith('.venv') for part in path.parts) and not any(
        fnmatch.fnmatch(path.name, pattern) for pattern in PATTERNS)


def selected(root: Path) -> list[Path]:
    candidates = [root / name for name in FILES + EXTRA]
    candidates += [root / 'docs' / (name + '.md') for name in DOCS]
    for name in TREES:
        folder = root / name
        if folder.is_symlink():
            raise ValueError('Символические ссылки в исходниках запрещены.')
        if folder.is_dir():
            for current, folders, files in os.walk(folder, followlinks=False):
                base = Path(current)
                folders[:] = [name for name in folders if allowed((base / name).relative_to(root))]
                for name in folders:
                    if (base / name).is_symlink():
                        raise ValueError('Символическая ссылка: ' + (base / name).relative_to(root).as_posix())
                candidates.extend(base / name for name in files)
    result = []
    for path in sorted(set(candidates)):
        relative = path.relative_to(root)
        if relative.as_posix() == '.env.example':
            permit = True
        else:
            permit = allowed(relative)
        if not permit:
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('Символическая ссылка: ' + relative.as_posix())
        if path.is_file():
            if path.suffix != '.jar' and SECRETS.search(path.read_bytes().decode('utf-8', errors='ignore')):
                raise ValueError('Возможный секрет; проверьте файл: ' + relative.as_posix())
            result.append(path)
    for name in FILES:
        if root / name not in result:
            raise ValueError('Нет обязательного файла: ' + name)
    return result


def export(root: Path, target: Path) -> int:
    root = root.resolve()
    target = target.absolute()
    if target.exists() or target.is_symlink():
        raise ValueError('Каталог назначения уже существует; перезапись запрещена.')
    if target.resolve().is_relative_to(root):
        raise ValueError('Экспорт должен находиться вне рабочего проекта.')
    paths = selected(root)  # Validate before creating an output directory.
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.wristmind-export-', dir=target.parent) as temp:
        staging = Path(temp) / 'source'
        staging.mkdir()
        for path in paths:
            destination = staging / path.relative_to(root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
        staging.rename(target)
    return len(paths)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Чистый экспорт исходников без Git-истории и приватных файлов.')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        count = export(Path(__file__).resolve().parents[1], args.output)
        print(f'Экспортировано файлов: {count}. Публикация не выполнялась; ручной аудит обязателен.')
    except (ValueError, OSError) as error:
        parser.exit(1, str(error) + '\n')
