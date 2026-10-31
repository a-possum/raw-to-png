"""Opt-in local reports. Only explicit numeric/status fields enter the report."""
from collections import deque
from dataclasses import asdict
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import tempfile
import time
import uuid

import psutil

VERSION = '0.2.0'
MAX_FILES = 2000
MAX_SAMPLES = 3600
MAX_REPORTS = 10


def build_channel(profile=None):
    profile = Path(profile) if profile is not None else Path(__file__).with_name('build-profile.json')
    try:
        value = json.loads(profile.read_text(encoding='utf-8-sig'))['channel']
        return value if value in ('test', 'release') else 'release'
    except (OSError, ValueError, KeyError, TypeError):
        return 'release'


def write_report(path, data):
    """Atomic local write; an interrupted checkpoint leaves the previous JSON intact."""
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.report-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class DiagnosticReport:
    def __init__(self, directory, *, channel, mode, bits, options, file_count):
        self.directory = Path(directory)
        self.path = self.directory / f'report-{uuid.uuid4().hex}.json'
        self.started = time.monotonic()
        self.parent = psutil.Process()
        self.cpu_seen = {}
        self.cpu_total = 0.0
        self.last_sample_cpu = 0.0
        self.last_sample = self.started
        self.last_checkpoint = self.started
        self.effective_cpus = float(psutil.cpu_count() or 1)
        self.samples = deque(maxlen=MAX_SAMPLES)
        self.files = []
        self.files_omitted = self.samples_omitted = 0
        self.peak_rss = self.peak_cpu_percent = 0
        self.waiting_since = None
        self.wait_seconds = 0.0
        self.save_error = None
        self.finished_at = None
        self.counts = {'ok': 0, 'failed': 0, 'skipped': 0, 'cancelled_files': 0}
        self.latest = {'active': 0, 'limit': 1, 'available_memory_bytes': None, 'waiting': False}
        versions = {}
        for name in ('rawpy', 'numpy', 'pypng', 'PySide6', 'psutil'):
            try:
                versions[name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                pass
        self.data = {
            'schema_version': 2, 'app_version': VERSION, 'channel': channel,
            'started_utc': datetime.now(timezone.utc).isoformat(), 'state': 'running',
            'system': {'os': platform.system(), 'os_release': platform.release(),
                       'os_version': platform.version(), 'python_version': platform.python_version(),
                       'cpu_model': platform.processor(), 'logical_cpus': psutil.cpu_count(),
                       'physical_cpus': psutil.cpu_count(logical=False),
                       'total_memory_bytes': psutil.virtual_memory().total},
            'versions': versions,
            'settings': {'mode': mode, 'bits': bits, 'conversion': asdict(options),
                         'file_count': file_count},
            'measurement': {'sample_interval_seconds': 1,
                            'cpu_percent_definition': '100% = all available logical CPUs',
                            'dimensions_definition': 'width/height = completed PNG; input_width/input_height = RAW metadata before orientation',
                            'ram_definition': 'Sampled sum of parent and child RSS; shared pages may be counted twice'},
        }
        for process in self._processes():
            try:
                self.cpu_seen[process.pid] = self._cpu(process)
            except psutil.Error:
                pass
        self.checkpoint()

    def _processes(self):
        try:
            return [self.parent] + self.parent.children(recursive=True)
        except psutil.Error:
            return [self.parent]

    @staticmethod
    def _cpu(process):
        values = process.cpu_times()
        return values.user + values.system

    def _account_cpu(self, pid, value):
        self.cpu_total += max(0, value - self.cpu_seen.get(pid, 0))
        self.cpu_seen[pid] = value

    def observe(self, active, limit, snapshot, waiting):
        now = time.monotonic()
        self.effective_cpus = snapshot.cpus
        self.data['system']['effective_cpus'] = snapshot.cpus
        self.data['system']['effective_memory_bytes'] = snapshot.total
        if waiting and self.waiting_since is None:
            self.waiting_since = now
        elif not waiting and self.waiting_since is not None:
            self.wait_seconds += now - self.waiting_since
            self.waiting_since = None
        self.latest = {'active': active, 'limit': limit,
                       'available_memory_bytes': snapshot.available, 'waiting': waiting}
        if now - self.last_sample >= 1:
            self.sample(now)
        if now - self.last_checkpoint >= 5:
            self.checkpoint()

    def sample(self, now=None):
        now = time.monotonic() if now is None else now
        rss = 0
        for process in self._processes():
            try:
                rss += process.memory_info().rss
                self._account_cpu(process.pid, self._cpu(process))
            except psutil.Error:
                pass
        interval = now - self.last_sample
        percent = (100 * (self.cpu_total - self.last_sample_cpu) /
                   (max(.001, interval) * max(.1, self.effective_cpus)))
        percent = min(100, max(0, percent))
        self.peak_rss = max(self.peak_rss, rss)
        self.peak_cpu_percent = max(self.peak_cpu_percent, percent)
        if len(self.samples) == MAX_SAMPLES:
            self.samples_omitted += 1
        self.samples.append({'seconds': round(now - self.started, 3),
                             'cpu_percent': round(percent, 2), 'rss_bytes': rss, **self.latest})
        self.last_sample, self.last_sample_cpu = now, self.cpu_total

    def job_finished(self, *, index, state, width=0, height=0, input_width=0, input_height=0, wall_seconds=0,
                     processing_seconds=0, peak_bytes=0, cpu_seconds=None, pid=None,
                     error_kind=None, error_code=None, exit_code=None):
        if cpu_seconds is not None and pid is not None:
            self._account_cpu(pid, cpu_seconds)
        if pid is not None:
            # The process is joined before this method is called.
            self.cpu_seen.pop(pid, None)
        key = {'Готово': 'ok', 'Ошибка': 'failed', 'Пропущено': 'skipped',
               'Отменено': 'cancelled_files'}[state]
        self.counts[key] += 1
        if len(self.files) < MAX_FILES:
            self.files.append({'file_id': index + 1, 'state': key, 'width': width, 'height': height,
                               'input_width': input_width, 'input_height': input_height,
                               'wall_seconds': round(wall_seconds, 3),
                               'processing_seconds': round(processing_seconds, 3),
                               'peak_worker_bytes': peak_bytes, 'cpu_seconds': cpu_seconds,
                               'error_kind': error_kind, 'error_code': error_code,
                               'worker_exit_code': exit_code})
        else:
            self.files_omitted += 1
        if key == 'failed':
            self.checkpoint()

    def snapshot(self):
        now = self.finished_at or time.monotonic()
        waiting = self.wait_seconds + (now - self.waiting_since if self.waiting_since is not None else 0)
        return {**self.data, 'totals': {**self.counts, 'elapsed_seconds': round(now - self.started, 3),
                                      'cpu_seconds': round(self.cpu_total, 3),
                                      'sampled_peak_rss_bytes': self.peak_rss,
                                      'sampled_peak_cpu_percent': round(self.peak_cpu_percent, 2),
                                      'memory_wait_seconds': round(waiting, 3)},
                'files': list(self.files), 'samples': list(self.samples),
                'files_omitted': self.files_omitted, 'samples_omitted': self.samples_omitted,
                'automatic_save_error': self.save_error}

    def checkpoint(self):
        self.last_checkpoint = time.monotonic()
        if self.save_error is not None:
            return
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            write_report(self.path, self.snapshot())
            # Only remove files owned by this report format, never arbitrary JSON.
            reports = sorted((p for p in self.directory.glob('report-*.json')
                              if len(p.stem) == 39 and all(c in '0123456789abcdef' for c in p.stem[7:])),
                             key=lambda p: p.stat().st_mtime, reverse=True)
            for report in reports[MAX_REPORTS:]:
                report.unlink(missing_ok=True)
        except OSError as error:
            # Preserve the in-memory report for Save As; conversion keeps running.
            self.save_error = type(error).__name__

    def finish(self, result=None, error_kind=None):
        now = time.monotonic()
        if self.waiting_since is not None:
            self.wait_seconds += now - self.waiting_since
            self.waiting_since = None
        self.latest = {**self.latest, 'active': 0, 'waiting': False}
        self.sample(now)
        self.finished_at = now
        self.data['state'] = ('error' if error_kind else 'cancelled' if result and result['cancelled']
                              else 'completed')
        self.data['fatal_error_kind'] = error_kind
        if result:
            # Explicit allowlist: never serialize error messages, paths or PIDs.
            self.data['queue'] = {key: result[key] for key in (
                'ok', 'failed', 'skipped', 'remaining', 'cancelled', 'elapsed', 'max_active')}
            for key in ('priorities', 'thread_counts', 'calibration',
                        'calibration_complete', 'selected_parallelism'):
                if key in result:
                    self.data['queue'][key] = result[key]
        self.data['completed_utc'] = datetime.now(timezone.utc).isoformat()
        self.checkpoint()
        return self.snapshot()
