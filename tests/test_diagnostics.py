import json
from threading import Event

from raw_to_png.converter import ConversionOptions
from raw_to_png.diagnostics import DiagnosticReport, build_channel, write_report
from raw_to_png.processing import GIB, Resources, run_queue


def report(tmp_path, **kwargs):
    return DiagnosticReport(tmp_path, channel='test', mode='auto', bits=16,
                            options=ConversionOptions(), file_count=3, **kwargs)


def result():
    return {'ok':1, 'failed':1, 'skipped':1, 'remaining':0, 'cancelled':False,
            'elapsed':1, 'max_active':1, 'detail':'/private/path/must-not-appear'}


def test_missing_or_invalid_build_profile_defaults_to_release(tmp_path):
    profile = tmp_path/'build-profile.json'
    assert build_channel(profile) == 'release'
    for text, expected in [('not JSON', 'release'), ('{"channel":"test"}', 'test'),
                           ('{"channel":"release"}', 'release'), ('{"channel":"other"}', 'release')]:
        profile.write_text(text, encoding='utf-8-sig')
        assert build_channel(profile) == expected


def test_report_is_private_complete_and_atomic(tmp_path):
    recorder = report(tmp_path/'SECRET_PERSON'/'secret_photos')
    recorder.observe(1, 2, Resources(8*GIB, 5*GIB, 4), True)
    recorder.job_finished(index=0, state='Готово', width=6000, height=4000,
                          wall_seconds=.8, processing_seconds=.7, peak_bytes=100)
    recorder.job_finished(index=1, state='Ошибка', error_kind='PermissionError', error_code=13)
    recorder.job_finished(index=2, state='Пропущено')
    data = recorder.finish(result())
    assert data['state'] == 'completed'
    assert data['totals']['ok'] == data['totals']['failed'] == data['totals']['skipped'] == 1
    assert data['files'][1]['file_id'] == 2 and data['files'][1]['error_code'] == 13
    text = recorder.path.read_text()
    assert all(value not in text for value in ['SECRET_PERSON', 'secret_photos', '/private/path'])
    assert json.loads(text) == data
    assert not list(recorder.directory.glob('*.tmp'))
    assert recorder.snapshot()['totals']['elapsed_seconds'] == data['totals']['elapsed_seconds']


def test_reports_bound_size_and_preserve_unrelated_files(tmp_path, monkeypatch):
    import raw_to_png.diagnostics as module
    monkeypatch.setattr(module, 'MAX_FILES', 2)
    monkeypatch.setattr(module, 'MAX_SAMPLES', 2)
    monkeypatch.setattr(module, 'MAX_REPORTS', 2)
    unrelated = tmp_path/'my-notes.json'
    unrelated.write_text('keep')
    for _ in range(4):
        recorder = report(tmp_path)
        for index in range(4):
            recorder.job_finished(index=index, state='Пропущено')
            recorder.sample()
        data = recorder.finish()
    assert len(data['files']) == len(data['samples']) == 2
    assert data['files_omitted'] == 2 and data['samples_omitted'] == 3
    assert data['totals']['skipped'] == 4
    assert len(list(tmp_path.glob('report-*.json'))) == 2
    assert unrelated.read_text() == 'keep'


def test_failed_auto_save_retains_exportable_report(tmp_path, monkeypatch):
    import raw_to_png.diagnostics as module
    def denied(*args):
        raise PermissionError('/private/secret/path')
    monkeypatch.setattr(module, 'write_report', denied)
    recorder = report(tmp_path)
    recorder.job_finished(index=0, state='Пропущено')
    data = recorder.finish()
    assert data['automatic_save_error'] == 'PermissionError'
    output = tmp_path/'manual-export.json'
    write_report(output, data)
    assert 'secret' not in output.read_text()
    assert json.loads(output.read_text())['totals']['skipped'] == 1


def test_checkpoints_and_cancelled_fatal_outcomes(tmp_path, monkeypatch):
    import raw_to_png.diagnostics as module
    clock = [1000.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock[0])
    recorder = report(tmp_path)
    recorder.observe(1, 2, Resources(8*GIB, 5*GIB, 4), True)
    clock[0] += 6
    recorder.observe(1, 2, Resources(8*GIB, 5*GIB, 4), True)
    checkpoint = json.loads(recorder.path.read_text())
    assert checkpoint['state'] == 'running'
    assert checkpoint['samples'][0]['active'] == 1
    assert checkpoint['totals']['memory_wait_seconds'] == 6
    data = recorder.finish({**result(), 'cancelled':True})
    assert data['state'] == 'cancelled'
    assert data['totals']['memory_wait_seconds'] == 6
    second = report(tmp_path)
    assert second.finish(error_kind='RuntimeError')['state'] == 'error'


def test_actual_spawn_report_records_failures_without_private_paths(tmp_path):
    from raw_to_png.converter import Source
    from pathlib import Path
    source = tmp_path/'PRIVATE-NAME.ARW'
    source.write_bytes(b'invalid RAW')
    recorder = report(tmp_path/'logs')
    queue = run_queue([(Source(source, Path(source.name)), tmp_path/'PRIVATE-OUT.png')],
                      16, None, 'eco', Event(), lambda *args:None, lambda value:None,
                      diagnostics=recorder)
    data = recorder.finish(queue)
    assert queue['failed'] == data['totals']['failed'] == 1
    assert data['files'][0]['error_kind']
    assert 'PRIVATE-' not in recorder.path.read_text()
    assert str(tmp_path) not in recorder.path.read_text()
    assert data['totals']['cpu_seconds'] > 0
