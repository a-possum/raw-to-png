import os
import pytest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication
from raw_to_png.converter import Source
from raw_to_png.ui import Window, Worker


def test_window_and_worker_continue_after_bad_raw(app, tmp_path):
    from pathlib import Path
    window = Window()
    source = tmp_path / 'broken.ARW'
    source.write_bytes(b'invalid')
    window.imported([Source(source, Path(source.name))])
    assert window.table.rowCount() == 1
    assert window.bits.itemData(0) == 16
    outcomes, completed = [], []
    worker = Worker([(Source(source, Path(source.name)), tmp_path / 'out.png'),
                     (Source(source, Path(source.name)), tmp_path / 'second.png'),
                     (Source(source, Path(source.name)), None)], 16)
    worker.row.connect(lambda *args: outcomes.append(args))
    worker.summary.connect(completed.append)
    worker.run()
    assert any(state == 'Пропущено' for _, state, _ in outcomes)
    assert worker.result['failed'] == 2 and worker.result['skipped'] == 1
    assert 'ошибок: 2' in completed[-1]
    window.close()
    app.processEvents()


def test_presets_and_custom_controls(app, tmp_path):
    from pathlib import Path
    window = Window()
    assert window.bits.currentData() == 16
    assert not window.start.isEnabled()
    window.preset.setCurrentIndex(window.preset.findData('viewing'))
    assert window.bits.currentData() == 8
    assert window.auto_bright.isChecked()
    assert not window.half_size.isChecked()
    window.preset.setCurrentIndex(window.preset.findData('quick'))
    assert window.half_size.isChecked()
    window.brightness.setValue(0.5)
    assert window.preset.currentData() == 'custom'
    assert window.advanced_toggle.isChecked()
    window.imported([Source(tmp_path / 'a.ARW', Path('a.ARW')),
                     Source(tmp_path / 'b.ARW', Path('b.ARW'))])
    window.table.selectRow(0)
    assert window.remove.isEnabled()
    window.remove_selected()
    assert len(window.sources) == 1 and window.sources[0].path.name == 'b.ARW'
    window.clear_queue()
    assert window.stack.currentIndex() == 0 and not window.start.isEnabled()
    window.close()


@pytest.mark.parametrize('mode', ['eco', 'maximum'])
def test_choose_destination_and_background_conversion_options(app, tmp_path, monkeypatch, mode):
    from pathlib import Path
    from PySide6.QtCore import QEventLoop, QTimer
    destination = tmp_path / 'chosen-output'
    monkeypatch.setattr('raw_to_png.ui.QFileDialog.getExistingDirectory', lambda *args: str(destination))
    calls = []
    def fake_queue(jobs, bits, options, mode, cancel, on_row, on_progress, on_activity, **kwargs):
        for index, (source, target) in enumerate(jobs):
            calls.append((target, bits, options, mode))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'test')
            on_row(index, 'Готово', str(target))
            on_progress(index+1)
        return {'ok':len(jobs), 'failed':0, 'skipped':0, 'remaining':0,
                'cancelled':False, 'elapsed':.1, 'max_active':1}
    monkeypatch.setattr('raw_to_png.ui.run_queue', fake_queue)
    window = Window()
    window.pick_destination()
    assert window.destination.text() == str(destination)
    window.preset.setCurrentIndex(window.preset.findData('quick'))
    window.preserve.setChecked(False)
    window.performance.setCurrentIndex(window.performance.findData(mode))
    window.imported([Source(tmp_path / 'photo.ARW', Path('sub/photo.ARW'))])
    window.begin()
    loop = QEventLoop()
    window.worker.finished.connect(loop.quit)
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    app.processEvents()
    assert not window.worker.isRunning()
    assert calls[0][0] == destination / 'photo.png'
    assert calls[0][1] == 8 and calls[0][3] == mode
    assert calls[0][2].half_size and calls[0][2].auto_bright
    assert window.table.item(0, 1).text() == 'Готово'
    assert window.start.isEnabled()
    window.close()
    restored = Window()
    assert restored.destination.text() == str(destination)
    assert restored.preset.currentData() == 'quick'
    assert restored.half_size.isChecked()
    assert not restored.preserve.isChecked()
    assert restored.performance.currentData() == mode
    assert restored.maximum_notice.isHidden() == (mode != 'maximum')
    restored.close()


def test_maximum_warning_only_shown_in_maximum_mode(app):
    window = Window()
    window.show()
    assert window.performance.currentData() == 'auto'
    assert window.maximum_notice.isHidden()
    window.performance.setCurrentIndex(window.performance.findData('maximum'))
    app.processEvents()
    app.processEvents()
    assert not window.maximum_notice.isHidden()
    assert window.maximum_warning.height() >= window.maximum_warning.heightForWidth(window.maximum_warning.width())
    assert window.activity_label.y() >= window.maximum_notice.geometry().bottom()
    assert window.maximum_warning.text() == ('Пока идёт конвертация на максимальной скорости, '
                                             'не используйте другие тяжёлые приложения.')
    window.performance.setCurrentIndex(window.performance.findData('eco'))
    assert window.maximum_notice.isHidden()
    window.close()


def test_worker_skip_counts_as_progress_without_converting(app, tmp_path, monkeypatch):
    from pathlib import Path
    worker = Worker([(Source(tmp_path / 'exists.ARW', Path('exists.ARW')), None)], 16)
    summaries, progress, rows = [], [], []
    worker.summary.connect(summaries.append)
    worker.progress.connect(progress.append)
    worker.row.connect(lambda *args: rows.append(args))
    worker.run()
    assert 'пропущено: 1, не обработано: 0' in summaries[0]
    assert progress == [1] and rows[0][1] == 'Пропущено'


@pytest.mark.parametrize('channel,enabled', [('test', True), ('release', False)])
def test_diagnostics_build_defaults_and_report_export(app, tmp_path, monkeypatch, channel, enabled):
    import json
    from pathlib import Path
    monkeypatch.setattr('raw_to_png.ui.build_channel', lambda: channel)
    window = Window()
    assert window.diagnostics.isChecked() == enabled
    assert not window.save_report.isEnabled()
    # A skip-only queue exercises the actual report lifecycle without mocking it.
    source = Source(tmp_path/'private-filename.ARW', Path('private-filename.ARW'))
    worker = Worker([(source, None)], 16, diagnostics_enabled=enabled,
                    diagnostics_dir=tmp_path/'logs', channel=channel)
    worker.run()
    window.worker = worker
    window.finished()
    assert window.save_report.isEnabled() == enabled
    if enabled:
        output = tmp_path/'export.json'
        monkeypatch.setattr('raw_to_png.ui.QFileDialog.getSaveFileName', lambda *args: (str(output), ''))
        window.export_report()
        data = json.loads(output.read_text())
        assert data['totals']['skipped'] == 1
        assert 'private-filename' not in output.read_text()
        assert len(list((tmp_path/'logs').glob('report-*.json'))) == 1
    else:
        assert not (tmp_path/'logs').exists()
    window.close()
