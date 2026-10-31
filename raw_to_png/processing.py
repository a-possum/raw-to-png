"""Bounded, spawn-based conversion queue. Qt stays in the parent process."""
from dataclasses import dataclass, field
from pathlib import Path
import math
import multiprocessing as mp
import os
import shutil
import statistics
import sys
import tempfile
import time

import psutil

from .i18n import exception_text, message

MIB = 1024 ** 2
GIB = 1024 ** 3
BOOTSTRAP_BYTES = 256 * MIB
MODES = ('auto', 'eco', 'maximum')


@dataclass(frozen=True)
class Resources:
    total: int
    available: int
    cpus: float

    @property
    def reserve(self):
        return max(GIB, self.total // 4)


def _read_limit(name):
    try:
        value = (Path('/sys/fs/cgroup') / name).read_text().strip()
        return None if value == 'max' else int(value)
    except (OSError, ValueError):
        return None


def resources():
    memory = psutil.virtual_memory()
    total, available = memory.total, memory.available
    cpus = float(psutil.cpu_count() or 1)
    try:
        cpus = min(cpus, len(psutil.Process().cpu_affinity()))
    except (AttributeError, psutil.Error):
        pass
    if sys.platform.startswith('linux'):
        limit = _read_limit('memory.max')
        current = _read_limit('memory.current')
        if limit is not None:
            total = min(total, limit)
            if current is not None:
                # Reclaimable inactive file cache is not resident application RAM.
                # Counting it as used can pause queues after copying large RAW files.
                try:
                    stats = dict(line.split() for line in Path('/sys/fs/cgroup/memory.stat').read_text().splitlines())
                    reclaimable = int(stats.get('inactive_file', 0))
                except (OSError, ValueError):
                    reclaimable = 0
                available = min(available, max(0, limit - current + min(current, reclaimable)))
        try:
            quota, period = (Path('/sys/fs/cgroup/cpu.max').read_text().split())
            if quota != 'max':
                cpus = min(cpus, int(quota) / int(period))
        except (OSError, ValueError, ZeroDivisionError):
            pass
    return Resources(total, min(total, available), max(0.1, cpus))


def worker_limit(mode, snapshot, successes, speed_target=1):
    if mode not in MODES:
        raise ValueError(message('Неизвестный режим производительности'))
    if mode == 'eco':
        return 1
    if mode == 'maximum':
        return min(max(1, math.floor(snapshot.cpus)), max(1, speed_target))
    # Leave one effective CPU free, including container quotas and affinity.
    return min(4, max(1, math.floor(snapshot.cpus) - 1), successes + 1)


@dataclass
class SpeedTuner:
    """Compare service rates under load without charging queue fill time.

    Only jobs spent mostly at the requested concurrency qualify. A median of
    per-job pixel rates resists outliers; multiplying by concurrency estimates
    steady throughput independently of how long the previous wave takes to exit.
    """
    target: int = 1
    ceiling: int = 1
    best_target: int = 1
    best_rate: float = 0
    generation: int = 0
    rates: list = field(default_factory=list)
    history: list = field(default_factory=list)
    settled: bool = False

    def completed(self, generation, pixels, seconds, full_load_seconds):
        if (self.settled or generation != self.generation or seconds <= 0
                or pixels <= 0 or full_load_seconds / seconds < .8):
            return
        self.rates.append(pixels / seconds)
        if len(self.rates) < min(self.target, 4):
            return
        rate = self.target * statistics.median(self.rates)
        accepted = self.best_rate == 0 or rate >= self.best_rate * 1.05
        measured_target = self.target
        if accepted:
            self.best_rate, self.best_target = rate, self.target
            next_target = min(self.ceiling, self.target * 2)
            self.settled = next_target == self.target
            self.target = next_target
        else:
            self.target = self.best_target
            self.settled = True
        self.history.append({'parallelism': measured_target, 'samples': len(self.rates),
                             'pixels_per_second': round(rate, 3), 'accepted': accepted,
                             'next_parallelism': self.target})
        self.generation += 1
        self.rates.clear()

    def memory_failure(self):
        self.target = self.best_target = 1
        self.settled = True
        self.generation += 1
        self.rates.clear()


def estimate_memory(pixels, bytes_per_pixel=32):
    # Covers full-resolution RAW buffers even for 8-bit / half-size export.
    return max(384 * MIB, 128 * MIB + math.ceil(pixels * bytes_per_pixel))


def learn_memory(current, pixels, peak):
    # Do not extrapolate fixed interpreter/library overhead per sensor pixel.
    return max(current, max(0, peak - 128 * MIB) * 1.5 / max(1, pixels))


def admits(snapshot, estimate, current_rss=0, headroom=0):
    return snapshot.available - snapshot.reserve - headroom >= max(0, estimate - current_rss)


def lower_priority(mode='auto'):
    if mode not in MODES:
        raise ValueError(message('Неизвестный режим производительности'))
    process = psutil.Process()
    if sys.platform == 'win32':
        process.nice(psutil.NORMAL_PRIORITY_CLASS if mode == 'maximum'
                     else psutil.BELOW_NORMAL_PRIORITY_CLASS)
    else:
        process.nice(max(0 if mode == 'maximum' else 5, process.nice()))
    return int(process.nice())


def _peak_memory():
    info = psutil.Process().memory_info()
    if hasattr(info, 'peak_wset'):
        return info.peak_wset
    if sys.platform.startswith('linux'):
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    return info.rss


def _child(source, target, bits, options, connection, cancel, mode='auto'):
    """Only paths/options cross IPC; decoded images never enter the GUI process."""
    for variable in ('OMP_NUM_THREADS', 'OMP_THREAD_LIMIT', 'OPENBLAS_NUM_THREADS',
                     'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        os.environ[variable] = '1'
    os.environ['OMP_DYNAMIC'] = 'FALSE'
    priority = None
    cancelled_type = ()
    try:
        priority = lower_priority(mode)
        from .converter import Cancelled, convert
        cancelled_type = Cancelled
        import rawpy
        from threadpoolctl import threadpool_limits, threadpool_info
        with threadpool_limits(limits=1):
            if cancel.is_set():
                raise Cancelled()
            # Header inspection does not unpack the entire sensor buffer.
            with rawpy.RawPy() as raw:
                raw.open_file(str(source.path))
                sizes = raw.sizes
                pixels = sizes.raw_width * sizes.raw_height
            connection.send(('ready', {
                'pixels': pixels, 'priority': priority,
                'width': sizes.width, 'height': sizes.height,
                'threads': [pool['num_threads'] for pool in threadpool_info()],
            }))
            while not cancel.is_set():
                if connection.poll(0.1):
                    instruction = connection.recv()
                    if instruction != 'run':
                        raise ValueError(instruction)
                    break
            if cancel.is_set():
                raise Cancelled()
            width, height = convert(source.path, target, bits, cancel, options)
            result = {'state': 'Готово', 'detail': str(target),
                      'output_width': width, 'output_height': height}
    except Exception as error:
        # Import failure is also a job failure and must not strand the queue.
        result = {'state': 'Отменено' if isinstance(error, cancelled_type) else 'Ошибка',
                  'detail': '' if isinstance(error, cancelled_type) else exception_text(error),
                  'memory_error': isinstance(error, MemoryError),
                  'error_kind': type(error).__name__, 'error_code': getattr(error, 'errno', None)}
    try:
        result.update(peak_bytes=_peak_memory(), priority=priority, cpu_seconds=time.process_time())
        connection.send(('done', result))
    finally:
        connection.close()


@dataclass
class Running:
    index: int
    process: object
    pipe: object
    target: Path
    staging: object
    ready: bool = False
    admitted: bool = False
    decided: bool = False
    estimate: int = BOOTSTRAP_BYTES
    pixels: int = 0
    rss: int = 0
    peak: int = 0
    result: object = None
    speed_generation: int = 0
    input_width: int = 0
    input_height: int = 0
    started_at: float = 0
    admitted_at: object = None
    calibration_target: int = 1
    full_load_seconds: float = 0
    accounted_at: float = 0


def receive_messages(pipe):
    """Windows can raise BrokenPipeError in poll(), as well as in recv()."""
    while True:
        try:
            if not pipe.poll():
                return
            message = pipe.recv()
        except (EOFError, OSError):
            return
        yield message


def publish(staged, target):
    """A native decoder only sees its private directory, never a final PNG."""
    try:
        # Same-volume hard links publish a completed file atomically on NTFS.
        os.link(staged, target)
        return
    except FileExistsError:
        raise
    except OSError:
        # FAT/exFAT and other filesystems may not support hard links.
        pass
    created = False
    try:
        with open(staged, 'rb') as source:
            with open(target, 'xb') as output:
                created = True
                shutil.copyfileobj(source, output)
    except BaseException:
        if created:
            Path(target).unlink(missing_ok=True)
        raise


def run_queue(jobs, bits, options, mode, cancel, on_row, on_progress,
              on_activity=lambda text: None, *, snapshot=resources, _target=None, diagnostics=None):
    """Launch one metadata probe at a time; admit decoding against live RAM."""
    if mode not in MODES:
        raise ValueError(message('Неизвестный режим производительности'))
    context = mp.get_context('spawn')
    shared_cancel = context.Event()
    active = []
    cursor = ok = failed = skipped = successes = 0
    bytes_per_pixel = 32
    peak_worker = max_active = 0
    priorities, thread_counts = set(), set()
    last_activity = None
    label = {'auto': 'Авто', 'eco': 'Экономный', 'maximum': 'Максимальная скорость'}[mode]
    tuner = SpeedTuner()
    started = time.monotonic()

    def activity(text):
        nonlocal last_activity
        if text != last_activity:
            on_activity(text)
            last_activity = text

    try:
        while active or (cursor < len(jobs) and not cancel.is_set()):
            if cancel.is_set():
                shared_cancel.set()
            now = time.monotonic()
            admitted = sum(job.admitted for job in active)
            for job in active:
                if job.admitted:
                    if admitted >= job.calibration_target:
                        job.full_load_seconds += now - job.accounted_at
                    job.accounted_at = now
            for job in list(active):
                try:
                    job.rss = psutil.Process(job.process.pid).memory_info().rss
                    job.peak = max(job.peak, job.rss)
                except psutil.Error:
                    job.rss = 0
                for kind, payload in receive_messages(job.pipe):
                    if kind == 'ready':
                        job.ready = True
                        job.pixels = payload['pixels']
                        job.input_width = payload.get('width', 0)
                        job.input_height = payload.get('height', 0)
                        job.estimate = estimate_memory(job.pixels, bytes_per_pixel)
                        priorities.add(payload['priority'])
                        thread_counts.update(payload['threads'])
                    elif kind == 'done':
                        job.result = payload
                if job.process.is_alive():
                    continue
                job.process.join()
                # Drain a final message that arrived between poll() and exit.
                for kind, payload in receive_messages(job.pipe):
                    if kind == 'done':
                        job.result = payload
                result = job.result or {'state': 'Ошибка', 'error_kind': 'WorkerExit',
                                        'exit_code': job.process.exitcode,
                                        'detail': message('Рабочий процесс завершился (код {code})', code=job.process.exitcode)}
                cpu_seconds = result.get('cpu_seconds')
                if result['state'] == 'Готово':
                    if cancel.is_set():
                        result = {'state': 'Отменено', 'detail': ''}
                    else:
                        try:
                            publish(Path(job.staging.name) / 'image.png', job.target)
                            result['detail'] = str(job.target)
                        except OSError as error:
                            result = {'state': 'Ошибка', 'detail': exception_text(error),
                                      'error_kind': type(error).__name__, 'error_code': error.errno}
                job.peak = max(job.peak, result.get('peak_bytes', 0))
                peak_worker = max(peak_worker, job.peak)
                if result['state'] == 'Готово':
                    ok += 1
                    successes += 1
                    if job.pixels:
                        bytes_per_pixel = learn_memory(bytes_per_pixel, job.pixels, job.peak)
                        if mode == 'maximum':
                            tuner.completed(job.speed_generation, job.pixels,
                                            time.monotonic() - job.admitted_at,
                                            job.full_load_seconds)
                elif result['state'] == 'Ошибка':
                    failed += 1
                    if result.get('memory_error'):
                        successes = 0
                        bytes_per_pixel *= 1.5
                        tuner.memory_failure()
                on_row(job.index, result['state'], result['detail'])
                on_progress(ok + failed + skipped)
                if diagnostics:
                    now = time.monotonic()
                    diagnostics.job_finished(index=job.index, state=result['state'],
                                             width=result.get('output_width', 0),
                                             height=result.get('output_height', 0),
                                             input_width=job.input_width, input_height=job.input_height,
                                             wall_seconds=now - job.started_at,
                                             processing_seconds=now - job.admitted_at if job.admitted_at else 0,
                                             peak_bytes=job.peak, cpu_seconds=cpu_seconds, pid=job.process.pid,
                                             error_kind=result.get('error_kind'),
                                             error_code=result.get('error_code'), exit_code=result.get('exit_code'))
                job.pipe.close()
                job.process.close()
                job.staging.cleanup()
                active.remove(job)

            if cancel.is_set():
                activity(message('{mode} · остановка, активных задач: {count}', mode=message(label), count=len(active)))
                if active:
                    time.sleep(0.1)
                continue
            state = snapshot()
            tuner.ceiling = max(1, math.floor(state.cpus))
            limit = (worker_limit(mode, state, successes, tuner.target) if mode == 'maximum'
                     else worker_limit(mode, state, successes))
            waiting = False
            for job in active:
                if not job.ready or job.decided:
                    continue
                headroom = sum(max(0, other.estimate - other.rss)
                               for other in active if other is not job and other.admitted)
                try:
                    if job.estimate + state.reserve > state.total:
                        job.pipe.send(message('Для этого RAW недостаточно оперативной памяти с учётом запаса системе'))
                        job.decided = True
                    elif admits(state, job.estimate, job.rss, headroom):
                        job.pipe.send('run')
                        job.decided = job.admitted = True
                        job.admitted_at = time.monotonic()
                        job.accounted_at = job.admitted_at
                        if mode == 'maximum':
                            job.speed_generation = tuner.generation
                            job.calibration_target = limit
                        on_row(job.index, 'Обработка…', str(job.target))
                    else:
                        waiting = True
                except (OSError, EOFError) as error:
                    job.decided = True
                    job.result = {'state': 'Ошибка', 'error_kind': type(error).__name__,
                                  'detail': message('Потеряна связь с рабочим процессом: {error}', error=exception_text(error))}

            while cursor < len(jobs) and jobs[cursor][1] is None:
                on_row(cursor, 'Пропущено', message('PNG с таким именем уже существует или есть в очереди'))
                if diagnostics:
                    diagnostics.job_finished(index=cursor, state='Пропущено')
                cursor += 1
                skipped += 1
                on_progress(ok + failed + skipped)
            if (not cancel.is_set() and cursor < len(jobs) and len(active) < limit
                    and not any(not job.decided for job in active)):
                headroom = sum(max(0, job.estimate - job.rss) for job in active if job.admitted)
                if BOOTSTRAP_BYTES + state.reserve > state.total:
                    on_row(cursor, 'Ошибка', message('Недостаточно памяти для безопасного запуска обработки'))
                    if diagnostics:
                        diagnostics.job_finished(index=cursor, state='Ошибка', error_kind='MemoryBudget')
                    cursor += 1
                    failed += 1
                    on_progress(ok + failed + skipped)
                elif admits(state, BOOTSTRAP_BYTES, headroom=headroom):
                    source, target = jobs[cursor]
                    try:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        staging = tempfile.TemporaryDirectory(prefix='.arw-to-png-', dir=target.parent)
                    except OSError as error:
                        on_row(cursor, 'Ошибка', exception_text(error))
                        if diagnostics:
                            diagnostics.job_finished(index=cursor, state='Ошибка',
                                                     error_kind=type(error).__name__, error_code=error.errno)
                        cursor += 1
                        failed += 1
                        on_progress(ok + failed + skipped)
                        continue
                    parent, child = context.Pipe()
                    process = context.Process(target=_target or _child,
                                              args=(source, Path(staging.name) / 'image.png', bits,
                                                    options, child, shared_cancel, mode),
                                              daemon=True)
                    try:
                        process.start()
                    except BaseException:
                        parent.close()
                        child.close()
                        staging.cleanup()
                        raise
                    child.close()
                    active.append(Running(cursor, process, parent, target, staging,
                                          started_at=time.monotonic()))
                    on_row(cursor, 'Подготовка…', str(target))
                    cursor += 1
                else:
                    waiting = True
            count = sum(job.admitted for job in active)
            max_active = max(max_active, count)
            if diagnostics:
                diagnostics.observe(count, limit, state, waiting)
            activity(message('{mode} · обрабатывается фотографий: {count}' if not waiting else
                             '{mode} · ожидание свободной памяти, активных задач: {count}',
                             mode=message(label), count=count))
            cancel.wait(0.1)
    finally:
        # Cooperative shutdown: never terminate a process in the middle of writing.
        shared_cancel.set()
        for job in active:
            job.process.join()
            job.pipe.close()
            job.process.close()
            job.staging.cleanup()
    return {'ok': ok, 'failed': failed, 'skipped': skipped,
            'remaining': len(jobs) - ok - failed - skipped,
            'cancelled': cancel.is_set(), 'elapsed': time.monotonic() - started,
            'peak_worker_bytes': peak_worker, 'max_active': max_active,
            'priorities': sorted(priorities), 'thread_counts': sorted(thread_counts),
            'calibration': tuner.history if mode == 'maximum' else [],
            'calibration_complete': tuner.settled if mode == 'maximum' else None,
            'selected_parallelism': tuner.best_target if mode == 'maximum' else None}
