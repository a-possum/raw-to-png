from pathlib import Path
from threading import Event
import os
import time

import pytest

from raw_to_png.converter import Source
from raw_to_png.processing import (
    GIB, MIB, Resources, SpeedTuner, admits, estimate_memory, learn_memory, lower_priority, run_queue, worker_limit,
    receive_messages,
)


def simulated_child(source, target, bits, options, connection, cancel, mode='auto'):
    """Exercise real spawn/IPC/shutdown without expensive RAW decoding."""
    if source.path.name == 'crash.ARW':
        Path(target).with_suffix('.part').write_bytes(b'incomplete PNG')
        os._exit(7)
    connection.send(('ready', {'pixels': 24_000_000, 'priority': 5, 'threads': [1]}))
    if source.path.name == 'late-crash.ARW':
        Path(target).with_suffix('.part').write_bytes(b'incomplete PNG')
        os._exit(7)
    while not cancel.is_set():
        if connection.poll(.05):
            instruction = connection.recv()
            if instruction != 'run':
                connection.send(('done', {'state': 'Ошибка', 'detail': instruction}))
                connection.close()
                return
            break
    # Synchronize the first parallel wave instead of assuming spawn is faster
    # than a 0.4-second task (not true on Windows / cold Wine prefixes).
    stage = Path(target).parent
    (stage/'admitted').touch()
    root = stage.parent
    if mode != 'eco' and len(list(root.glob('*.png'))) == 1:
        deadline = time.monotonic() + 10
        while (not cancel.is_set() and time.monotonic() < deadline
               and len(list(root.glob('.arw-to-png-*/admitted'))) < 2):
            time.sleep(.02)
    deadline = time.monotonic() + .4
    while not cancel.is_set() and time.monotonic() < deadline:
        time.sleep(.02)
    if cancel.is_set():
        result = {'state': 'Отменено', 'detail': ''}
    elif source.path.name == 'broken.ARW':
        result = {'state': 'Ошибка', 'detail': 'bad raw'}
    else:
        Path(target).write_bytes(b'PNG test')
        result = {'state': 'Готово', 'detail': str(target)}
    connection.send(('done', result))
    connection.close()


def jobs(tmp_path, names):
    return [(Source(Path(name), Path(name)), tmp_path / f'{i}.png') for i, name in enumerate(names)]


def test_closed_windows_pipe_is_a_normal_end_of_messages():
    class Closed:
        def poll(self):
            raise BrokenPipeError(109, 'pipe closed')
    assert list(receive_messages(Closed())) == []


def test_queue_reports_estimates_after_successes_and_keeps_skips_out_of_work(tmp_path):
    estimates = []
    work = jobs(tmp_path, ['good.ARW']*8)
    work.append((Source(Path('already.ARW'), Path('already.ARW')), None))
    result = run_queue(work, 8, None, 'eco', Event(), lambda *args: None, lambda *args: None,
                       snapshot=lambda: Resources(16*GIB, 12*GIB, 8),
                       _target=simulated_child, on_estimate=estimates.append)
    assert result['ok'] == 8 and result['skipped'] == 1
    assert estimates[0] == {'seconds': None, 'waiting': False}
    assert any(row['seconds'] is not None and row['seconds'] > 0 for row in estimates)


def test_container_memory_does_not_count_reclaimable_file_cache_as_busy(monkeypatch):
    import raw_to_png.processing as module
    from types import SimpleNamespace
    monkeypatch.setattr(module.sys, 'platform', 'linux')
    monkeypatch.setattr(module.psutil, 'virtual_memory', lambda: SimpleNamespace(total=8*GIB, available=6*GIB))
    monkeypatch.setattr(module, '_read_limit', lambda name: {'memory.max':8*GIB,'memory.current':7*GIB}.get(name))
    original = Path.read_text
    def read(path, *args, **kwargs):
        if path.as_posix() == '/sys/fs/cgroup/memory.stat':
            return f'inactive_file {5*GIB}\n'
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path, 'read_text', read)
    assert module.resources().available == 6*GIB


@pytest.mark.parametrize('mode,cpus,successes,expected', [
    ('eco', 32, 100, 1), ('auto', 32, 0, 1), ('auto', 32, 1, 2),
    ('auto', 32, 2, 3), ('auto', 32, 10, 4), ('auto', 4, 10, 3),
    ('auto', 2, 10, 1), ('auto', .5, 10, 1),
])
def test_cpu_and_calibration_limits(mode, cpus, successes, expected):
    assert worker_limit(mode, Resources(16*GIB, 12*GIB, cpus), successes) == expected


def test_maximum_can_use_all_cpus_but_only_at_learned_target():
    state = Resources(16*GIB, 12*GIB, 8)
    assert worker_limit('maximum', state, 100) == 1
    assert worker_limit('maximum', state, 100, 4) == 4
    assert worker_limit('maximum', state, 100, 32) == 8
    assert worker_limit('maximum', Resources(16*GIB, 12*GIB, 1), 100, 32) == 1


def test_speed_tuner_scales_when_throughput_improves_and_backs_off():
    tuner = SpeedTuner(ceiling=8)
    phase = tuner.generation
    tuner.completed(phase, 24_000_000, 10, 10)
    assert tuner.target == 2
    phase = tuner.generation
    tuner.completed(phase, 24_000_000, 9, 9)
    tuner.completed(phase, 24_000_000, 10, 10)
    assert tuner.target == 4
    phase = tuner.generation
    # Four jobs now take too long: throughput falls below the two-worker level.
    for _ in range(4):
        tuner.completed(phase, 24_000_000, 40, 40)
    assert tuner.target == 2 and tuner.settled
    tuner.completed(phase, 100_000_000, 1, 1)
    assert tuner.target == 2


def test_tuner_ignores_previous_phase_and_handles_memory_failure():
    tuner = SpeedTuner(ceiling=4)
    phase = tuner.generation
    tuner.completed(phase, 24_000_000, 10, 10)
    assert tuner.target == 2
    tuner.completed(phase, 24_000_000, 11, 11)
    assert tuner.rates == []
    tuner.memory_failure()
    assert tuner.target == 1 and tuner.settled


def test_tuner_compares_fully_loaded_rates_without_transition_wave_bias():
    # An eight-worker wave can take two batches to fill while old jobs exit.
    # Completed jobs still have a 14-second service time, so choosing four
    # because the entire transition took 28 seconds would discard real speed.
    tuner = SpeedTuner(ceiling=12)
    for target, seconds in [(1, 10), (2, 10), (4, 12), (8, 14), (12, 21)]:
        assert tuner.target == target
        phase = tuner.generation
        for _ in range(min(target, 4)):
            tuner.completed(phase, 24_000_000, seconds, seconds)
    assert tuner.target == 8 and tuner.settled
    assert [row['parallelism'] for row in tuner.history] == [1, 2, 4, 8, 12]
    assert tuner.history[3]['accepted'] and not tuner.history[4]['accepted']


def test_tuner_excludes_unfilled_memory_limited_and_tail_jobs():
    tuner = SpeedTuner(target=8, ceiling=12, best_target=4, best_rate=8_000_000)
    for _ in range(20):
        tuner.completed(tuner.generation, 24_000_000, 12, 5)
    assert tuner.target == 8 and not tuner.settled and not tuner.history
    assert not tuner.rates


def test_tuner_normalizes_resolution_and_resists_one_slow_file():
    tuner = SpeedTuner(target=4, ceiling=8, best_target=2, best_rate=4_800_000)
    for pixels, seconds in [(24_000_000, 12), (48_000_000, 24),
                            (12_000_000, 6), (24_000_000, 120)]:
        tuner.completed(tuner.generation, pixels, seconds, seconds)
    assert tuner.target == 8
    assert tuner.history[0]['pixels_per_second'] == 8_000_000


def test_budget_reserves_system_and_unallocated_running_buffers():
    state = Resources(8*GIB, 3*GIB, 8)
    assert state.reserve == 2*GIB
    assert admits(state, 800*MIB)
    assert not admits(state, 800*MIB, headroom=400*MIB)
    assert admits(state, 800*MIB, current_rss=400*MIB, headroom=400*MIB)
    assert estimate_memory(100_000_000) > estimate_memory(24_000_000)
    assert estimate_memory(1_000) >= 384*MIB
    assert learn_memory(32, 1000, 60*MIB) == 32
    assert learn_memory(32, 1_000_000, 400*MIB) > 32


@pytest.mark.parametrize('mode,expected', [('auto', 16384), ('eco', 16384), ('maximum', 32)])
def test_windows_priority_never_exceeds_normal(monkeypatch, mode, expected):
    import raw_to_png.processing as module
    calls = []
    class Process:
        def nice(self, value=None):
            if value is not None:
                calls.append(value)
            return calls[-1]
    monkeypatch.setattr(module.sys, 'platform', 'win32')
    monkeypatch.setattr(module.psutil, 'BELOW_NORMAL_PRIORITY_CLASS', 16384, raising=False)
    monkeypatch.setattr(module.psutil, 'NORMAL_PRIORITY_CLASS', 32, raising=False)
    monkeypatch.setattr(module.psutil, 'Process', Process)
    assert lower_priority(mode) == expected and calls == [expected]


@pytest.mark.parametrize('mode,max_count', [('eco', 1), ('auto', 4), ('maximum', 8)])
def test_spawned_queue_bounded_and_continues_after_native_crash(tmp_path, mode, max_count):
    rows, progress = [], []
    work = jobs(tmp_path, ['good.ARW']*5 + ['crash.ARW', 'late-crash.ARW', 'broken.ARW', 'last.ARW'])
    result = run_queue(work, 16, None, mode, Event(), lambda *args: rows.append(args),
                       progress.append, snapshot=lambda: Resources(16*GIB, 12*GIB, 8),
                       _target=simulated_child)
    assert result['ok'] == 6 and result['failed'] == 3 and result['remaining'] == 0
    assert result['max_active'] <= max_count
    if mode in ('auto', 'maximum'):
        assert result['max_active'] > 1
    assert (tmp_path/'8.png').exists()
    assert progress[-1] == 9
    assert any('код 7' in detail for _, _, detail in rows)
    assert not list(tmp_path.glob('.arw-to-png-*'))
    assert not (tmp_path/'5.png').exists()
    assert not (tmp_path/'6.png').exists()


@pytest.mark.parametrize('mode', ['auto', 'maximum'])
def test_memory_pause_resumes_without_starting_more_tasks(tmp_path, mode):
    statuses = []
    low_checks = 0
    def snapshot():
        nonlocal low_checks
        low_checks += 1
        return Resources(8*GIB, 500*MIB if low_checks <= 3 else 6*GIB, 8)
    result = run_queue(jobs(tmp_path, ['good.ARW']), 16, None, mode, Event(),
                       lambda *args: None, lambda value: None, statuses.append,
                       snapshot=snapshot, _target=simulated_child)
    assert result['ok'] == 1
    assert any('ожидание свободной памяти' in text for text in statuses)


def test_cancel_while_waiting_for_memory_launches_nothing(tmp_path):
    cancel = Event()
    def activity(text):
        if 'ожидание' in text:
            cancel.set()
    result = run_queue(jobs(tmp_path, ['good.ARW']), 16, None, 'auto', cancel,
                       lambda *args: None, lambda value: None, activity,
                       snapshot=lambda: Resources(8*GIB, 500*MIB, 8), _target=simulated_child)
    assert result['cancelled'] and result['remaining'] == 1
    assert not list(tmp_path.glob('*.png'))


@pytest.mark.parametrize('mode', ['auto', 'maximum'])
def test_cancel_running_process_joins_children(tmp_path, mode):
    import multiprocessing
    cancel = Event()
    rows = []
    def row(index, state, detail):
        rows.append(state)
        if state == 'Обработка…':
            cancel.set()
    before = {child.pid for child in multiprocessing.active_children()}
    result = run_queue(jobs(tmp_path, ['good.ARW']*3), 16, None, mode, cancel,
                       row, lambda value: None, snapshot=lambda: Resources(8*GIB, 6*GIB, 8),
                       _target=simulated_child)
    assert result['cancelled'] and result['remaining'] == 3
    assert 'Отменено' in rows
    assert {child.pid for child in multiprocessing.active_children()} == before
    assert not list(tmp_path.glob('*.png'))


def test_impossible_memory_requirement_fails_instead_of_waiting_forever(tmp_path):
    rows = []
    result = run_queue(jobs(tmp_path, ['good.ARW']), 16, None, 'auto', Event(),
                       lambda *args: rows.append(args), lambda value: None,
                       snapshot=lambda: Resources(1700*MIB, 1600*MIB, 4), _target=simulated_child)
    assert result['failed'] == 1 and result['remaining'] == 0
    assert any('недостаточно' in detail.lower() for _, _, detail in rows)


def test_publishing_never_overwrites_and_supports_fat(tmp_path, monkeypatch):
    from raw_to_png.processing import publish
    source, target = tmp_path/'stage.png', tmp_path/'final.png'
    source.write_bytes(b'complete PNG')
    target.write_bytes(b'existing')
    with pytest.raises(FileExistsError):
        publish(source, target)
    assert target.read_bytes() == b'existing'
    def no_links(*args):
        raise OSError('hard links unsupported')
    monkeypatch.setattr('raw_to_png.processing.os.link', no_links)
    with pytest.raises(FileExistsError):
        publish(source, target)
    assert target.read_bytes() == b'existing'
    target.unlink()
    publish(source, target)
    assert target.read_bytes() == b'complete PNG'


def test_publish_copy_failure_removes_partial_final(tmp_path, monkeypatch):
    from raw_to_png.processing import publish
    source, target = tmp_path/'stage.png', tmp_path/'final.png'
    source.write_bytes(b'complete PNG')
    def no_links(*args):
        raise OSError('unsupported')
    def disk_full(source, output):
        output.write(b'partial')
        raise OSError('disk full')
    monkeypatch.setattr('raw_to_png.processing.os.link', no_links)
    monkeypatch.setattr('raw_to_png.processing.shutil.copyfileobj', disk_full)
    with pytest.raises(OSError, match='disk full'):
        publish(source, target)
    assert not target.exists()


@pytest.mark.skipif(not os.environ.get('RAW_TO_PNG_SAMPLE'), reason='External RAW sample not provided')
def test_real_spawned_conversion_and_cancellation(tmp_path):
    from threading import Timer
    import png
    from raw_to_png.converter import ConversionOptions
    from raw_to_png.diagnostics import DiagnosticReport
    source = Path(os.environ['RAW_TO_PNG_SAMPLE'])
    work = [(Source(source, Path(source.name)), tmp_path/'real.png')]
    report = DiagnosticReport(tmp_path/'logs', channel='test', mode='auto', bits=8,
                              options=ConversionOptions(half_size=True), file_count=1)
    result = run_queue(work, 8, ConversionOptions(half_size=True), 'auto', Event(),
                       lambda *args: None, lambda value: None, diagnostics=report)
    assert result['ok'] == 1 and result['thread_counts'] == [1]
    import sys
    if sys.platform == 'win32':
        import psutil
        assert result['priorities'] == [int(psutil.BELOW_NORMAL_PRIORITY_CLASS)]
    else:
        assert all(priority >= 5 for priority in result['priorities'])
    width, height, rows, info = png.Reader(filename=str(tmp_path/'real.png')).read()
    assert width > 100 and height > 100 and info['bitdepth'] == 8
    assert sum(1 for _ in rows) == height
    data = report.finish(result)
    assert data['schema_version'] == 2
    assert (data['files'][0]['width'], data['files'][0]['height']) == (width, height)
    assert data['files'][0]['input_width'] * data['files'][0]['input_height'] > width * height
    assert data['queue']['thread_counts'] == [1]
    cancel = Event()
    timers = []
    def on_row(index, state, detail):
        if state == 'Обработка…':
            timer = Timer(.2, cancel.set)
            timers.append(timer)
            timer.start()
    second = [(Source(source, Path(source.name)), tmp_path/'cancelled.png')]
    result = run_queue(second, 16, None, 'auto', cancel, on_row, lambda value: None)
    for timer in timers:
        timer.join()
    assert result['cancelled'] and result['ok'] == 0
    assert not (tmp_path/'cancelled.png').exists()
    assert not list(tmp_path.glob('.arw-to-png-*'))
