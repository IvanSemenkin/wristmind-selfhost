"""Read-only estimates, not a benchmark or a promise of throughput."""
import json
import os
import shutil
from pathlib import Path


def estimate(cpu, ram, available, disk):
    tier = 'comfortable' if cpu >= 4 and ram >= 8 else 'standard' if cpu >= 2 and ram >= 4 else 'limited'
    return {'cpu': round(cpu, 2), 'ram_gib': round(ram, 1), 'available_gib': round(available, 1),
            'disk_free_gib': round(disk, 1), 'tier': tier,
            'recommendations': {'web_search': cpu >= 2 and ram >= 4, 'digitization': cpu >= 2 and ram >= 4,
                                'rag': ram >= 4, 'voice': True},
            'notice': 'Ориентировочная оценка для одного активного пользователя. Модели работают у провайдера; PDF/OCR и поиск нагружают сервер. Скорость диска, сеть и одновременные запросы не измеряются.'}


def inspect_resources(path=Path('.'), proc=Path('/proc'), cgroup=Path('/sys/fs/cgroup')):
    def read(file):
        try: return file.read_text().strip()
        except OSError: return ''
    memory = {}
    for line in read(proc / 'meminfo').splitlines():
        key, _, value = line.partition(':')
        try: memory[key] = int(value.split()[0]) * 1024
        except (ValueError, IndexError): pass
    cpu = float(len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else os.cpu_count() or 1)
    ram = memory.get('MemTotal', 0); available = memory.get('MemAvailable', ram)
    quota = read(cgroup / 'cpu.max').split()
    if len(quota) == 2 and quota[0] != 'max':
        try: cpu = min(cpu, int(quota[0]) / int(quota[1]))
        except (ValueError, ZeroDivisionError): pass
    limit = read(cgroup / 'memory.max'); current = read(cgroup / 'memory.current')
    if limit.isdigit():
        ram = min(ram, int(limit))
        if current.isdigit(): available = min(available, max(0, int(limit) - int(current)))
    target = Path(path).resolve()
    while not target.exists(): target = target.parent
    disk = shutil.disk_usage(target).free
    return estimate(cpu, ram / 2**30, available / 2**30, disk / 2**30)


if __name__ == '__main__':
    import sys
    import textwrap
    colours = sys.stdout.isatty() and os.environ.get('TERM', 'dumb') != 'dumb' and 'NO_COLOR' not in os.environ
    def emit(text, colour='90'):
        prefix = '\033[' + colour + 'm' if colours else ''
        suffix = '\033[0m' if colours else ''
        width = max(28, min(76, shutil.get_terminal_size().columns))
        for line in textwrap.wrap(text, width=width):
            print(prefix + line + suffix)
    result = inspect_resources(Path(sys.argv[1]) if len(sys.argv) > 1 else Path('.'))
    emit(f"Оценка ресурсов: {result['cpu']} CPU · {result['ram_gib']} ГиБ RAM (свободно {result['available_gib']}) · {result['disk_free_gib']} ГиБ диска")
    emit('Профиль: ' + {'limited':'ограниченный', 'standard':'базовый', 'comfortable':'с запасом'}[result['tier']], '93' if result['tier'] == 'limited' else '92')
    emit(result['notice'])
    for key, label in [('web_search','Веб-поиск'), ('digitization','Оцифровка'), ('rag','RAG'), ('voice','Голос через API')]:
        emit(label + ': ' + ('доступен после подключения провайдера; локальная модель не нужна' if key == 'voice' else 'рекомендуется' if result['recommendations'][key] else 'может работать медленно; включайте по необходимости'))
