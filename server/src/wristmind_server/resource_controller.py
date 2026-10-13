"""Worker-wide bounded admission; Linux probes only while operations are active."""
from __future__ import annotations

import asyncio
from collections import Counter, deque
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass
from functools import wraps
import os
from pathlib import Path
import time

from . import search_trace

MB = 1024 * 1024
KINDS = ('search', 'http', 'html', 'pdf', 'ocr', 'planner', 'index')
HEAVY = {'html', 'pdf', 'ocr', 'index'}


class ResourceUnavailable(RuntimeError):
    """Bounded admission failed; never evidence that a source does not exist."""


@dataclass(frozen=True)
class ResourceSample:
    available_bytes: int | None = None
    cpu_load: float | None = None  # one-minute load / effective CPU capacity


def linux_sample(proc=Path('/proc'), cgroup=Path('/sys/fs/cgroup')) -> ResourceSample:
    available = None
    cpu = float(os.cpu_count() or 1)
    load = None
    try:
        for line in (proc / 'meminfo').read_text().splitlines():
            if line.startswith('MemAvailable:'):
                available = int(line.split()[1]) * 1024
                break
    except (OSError, ValueError, IndexError):
        pass
    # Look at the container leaf AND parents: a parent can impose a smaller cap.
    paths = {cgroup}
    try:
        for line in (proc / 'self/cgroup').read_text().splitlines():
            _, controllers, path = line.split(':', 2)
            if not controllers:
                leaf = cgroup / path.lstrip('/')
            elif 'memory' in controllers.split(','):
                leaf = cgroup / 'memory' / path.lstrip('/')
            else:
                continue
            if '..' not in leaf.parts:
                paths.add(leaf)
                paths.update(p for p in leaf.parents if p == cgroup or cgroup in p.parents)
    except (OSError, ValueError):
        pass
    for path in paths:
        for limit_name, used_name in [('memory.max', 'memory.current'),
                                       ('memory.limit_in_bytes', 'memory.usage_in_bytes')]:
            try:
                limit = int((path / limit_name).read_text().strip())
                used = int((path / used_name).read_text().strip())
                if 0 < limit < 1 << 60:
                    free = max(0, limit - used)
                    available = free if available is None else min(available, free)
            except (OSError, ValueError):
                pass
        try:
            quota, period = (path / 'cpu.max').read_text().split()
            if quota != 'max' and int(period) > 0:
                cpu = min(cpu, max(.01, int(quota) / int(period)))
        except (OSError, ValueError):
            pass
    try:
        load = float((proc / 'loadavg').read_text().split()[0]) / cpu
    except (OSError, ValueError, IndexError):
        pass
    return ResourceSample(available, load)


class Lease:
    def __init__(self, controller, kind):
        self.controller, self.kind, self.released = controller, kind, False

    def release(self):
        if self.released:
            return
        self.released = True
        self.controller.active[self.kind] -= 1
        self.controller.changed.set()
        self.controller.record('released', self.kind)


class AdaptiveResourceController:
    def __init__(self, *, sampler=linux_sample, clock=time.monotonic, interval=2.0,
                 busy_mb=900, critical_mb=500, hysteresis_mb=150,
                 free_mb=1400, wait_seconds=10.0, max_waiters=32):
        self.sampler, self.clock = sampler, clock
        self.interval, self.wait_seconds, self.max_waiters = interval, wait_seconds, max_waiters
        self.busy_mb, self.critical_mb = busy_mb, critical_mb
        self.hysteresis_mb, self.free_mb = hysteresis_mb, free_mb
        self.mode = 'NORMAL'
        self.sample = ResourceSample()
        self.last_sample = float('-inf')
        self.active, self.peak = Counter(), Counter()
        self.total_peak = 0
        self.waiters = deque()
        self.changed = asyncio.Event()
        self.recovery_samples = 0
        self.detached = set()  # bounded by acquired slots; retain physical thread ownership
        self.executor = None

    def refresh(self):
        now = self.clock()
        if now - self.last_sample < self.interval:
            return
        self.last_sample = now
        try:
            self.sample = self.sampler()
        except (OSError, ValueError):
            self.sample = ResourceSample()
        mem = self.sample.available_bytes
        load = self.sample.cpu_load
        old = self.mode
        if mem is None:
            self.mode = 'NORMAL'  # safe fixed fallback, no free-resource boost
            self.recovery_samples = 0
        else:
            mb = mem / MB
            target = 'CRITICAL' if mb < self.critical_mb or (load is not None and load >= 1.5) else (
                'BUSY' if mb <= self.busy_mb or (load is not None and load >= .9) else 'NORMAL')
            order = {'NORMAL': 0, 'BUSY': 1, 'CRITICAL': 2}
            if order[target] >= order[old]:
                self.mode, self.recovery_samples = target, 0
            else:
                threshold = (self.critical_mb if old == 'CRITICAL' else self.busy_mb) + self.hysteresis_mb
                recovered = mb > threshold and (load is None or load < (1.2 if old == 'CRITICAL' else .75))
                self.recovery_samples = self.recovery_samples + 1 if recovered else 0
                if self.recovery_samples >= 2:
                    self.mode = 'BUSY' if old == 'CRITICAL' else 'NORMAL'
                    self.recovery_samples = 0
        if self.mode != old:
            search_trace.event('RESOURCE_MODE', mode=self.mode, reason='pressure_sample',
                               available_bytes=mem, cpu_load=load)
            self.changed.set()

    def limit(self, kind):
        if kind not in KINDS:
            raise ValueError('Unknown resource operation')
        if self.mode == 'CRITICAL' and kind in HEAVY:
            return 0
        if self.mode != 'NORMAL':
            return 0 if kind == 'index' else 1
        free = (self.sample.available_bytes is not None and self.sample.cpu_load is not None
                and self.sample.available_bytes > self.free_mb * MB and self.sample.cpu_load < .6
                and not any(self.active[key] for key in HEAVY) and len(self.waiters) < 4)
        return {'search': 2 if free else 1, 'http': 3 if free else 2}.get(kind, 1)

    def record(self, status, kind, **fields):
        search_trace.event('RESOURCE_SLOT', kind=kind, mode=self.mode, status=status,
            active_operations=sum(self.active.values()), kind_active=self.active[kind],
            peak_concurrency=self.total_peak, kind_peak=self.peak[kind], waiting_operations=len(self.waiters), **fields)

    async def acquire(self, kind, *, timeout=None):
        self.limit(kind)
        if len(self.waiters) >= self.max_waiters:
            self.record('rejected', kind, reason='queue_full')
            raise ResourceUnavailable('Сервер занят: очередь операций заполнена. Попробуйте позже.')
        ticket = (object(), kind)
        self.waiters.append(ticket)
        started = self.clock()
        lease = None
        deadline = started + (self.wait_seconds if timeout is None else min(timeout, self.wait_seconds))
        try:
            while True:
                self.changed.clear()
                self.refresh()
                first = next(item for item in self.waiters if item[1] == kind)
                if first is ticket and self.active[kind] < self.limit(kind):
                    self.active[kind] += 1
                    self.peak[kind] = max(self.peak[kind], self.active[kind])
                    self.total_peak = max(self.total_peak, sum(self.active.values()))
                    lease = Lease(self, kind)
                    return lease
                remaining = deadline - self.clock()
                if remaining <= 0:
                    self.record('timeout', kind, reason='resource_wait_timeout')
                    raise ResourceUnavailable('Сервер занят: не удалось дождаться свободных ресурсов. Попробуйте позже.')
                try:
                    await asyncio.wait_for(self.changed.wait(), min(self.interval, remaining))
                except TimeoutError:
                    pass
        except asyncio.CancelledError:
            self.record('cancelled', kind, cancellations=1)
            raise
        finally:
            self.waiters.remove(ticket)
            self.changed.set()
            if lease is not None:
                self.record('acquired', kind, slot_wait_ms=(self.clock() - started) * 1000)

    @asynccontextmanager
    async def slot(self, kind, *, timeout=None):
        lease = await self.acquire(kind, timeout=timeout)
        try:
            yield
        except asyncio.CancelledError:
            self.record('cancelled', kind, cancellations=1)
            raise
        finally:
            lease.release()

    async def thread(self, kind, function, *args):
        """Cancellation releases ownership only AFTER the physical thread finishes."""
        lease = await self.acquire(kind)
        loop = asyncio.get_running_loop()
        if self.executor is None:
            self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='wristmind-document')
        try:
            physical = self.executor.submit(copy_context().run, function, *args)
        except BaseException:
            lease.release()
            raise
        self.detached.add(physical)
        def finished(done):
            def settle():
                self.detached.discard(done)
                lease.release()
                if not done.cancelled():
                    done.exception()  # observe exceptions after caller cancellation
            if not loop.is_closed():
                try:
                    loop.call_soon_threadsafe(settle)
                except RuntimeError:
                    pass  # loop closed during process shutdown; no new admissions
        physical.add_done_callback(finished)
        try:
            return await asyncio.shield(asyncio.wrap_future(physical))
        except asyncio.CancelledError:
            self.record('cancelled', kind, cancellations=1)
            raise

    def close(self):
        if self.executor is not None:
            self.executor.shutdown(wait=False, cancel_futures=True)


def resources():
    loop = asyncio.get_running_loop()
    if not hasattr(loop, '_wristmind_resources'):
        from .config import get_settings
        s = get_settings()
        loop._wristmind_resources = AdaptiveResourceController(sampler=linux_sample,
            busy_mb=s.resource_busy_memory_mb, critical_mb=s.resource_critical_memory_mb,
            hysteresis_mb=s.resource_hysteresis_memory_mb, free_mb=s.resource_free_memory_mb,
            wait_seconds=s.resource_wait_seconds, max_waiters=s.resource_max_waiters)
    return loop._wristmind_resources


def resource_operation(kind):
    def decorate(function):
        @wraps(function)
        async def wrapped(*args, **kwargs):
            async with resources().slot(kind):
                return await function(*args, **kwargs)
        return wrapped
    return decorate
