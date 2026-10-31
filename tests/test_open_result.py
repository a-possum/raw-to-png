from pathlib import Path

from raw_to_png.converter import Source
from raw_to_png.ui import Window


def test_double_click_opens_completed_png_in_any_language(app, tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr('raw_to_png.ui.QDesktopServices.openUrl', lambda url: opened.append(url) or True)
    window = Window()
    window.imported([Source(tmp_path/'фото.ARW', Path('фото.ARW'))])
    output = tmp_path/'Фото с пробелами.png'
    output.write_bytes(b'test PNG')
    window.update_row(0, 'Готово', str(output))
    for language in ('ru', 'en'):
        window.language.setCurrentIndex(window.language.findData(language))
        window.table.cellDoubleClicked.emit(0, 0)
        assert Path(opened[-1].toLocalFile()) == output
    assert len(opened) == 2
    window.close()


def test_ignores_unfinished_rows_errors_and_non_png_targets(app, tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr('raw_to_png.ui.QDesktopServices.openUrl', lambda url: opened.append(url))
    window = Window()
    window.imported([Source(tmp_path/'photo.ARW', Path('photo.ARW'))])
    for state in ('В очереди', 'Обработка…', 'Ошибка', 'Отменено', 'Пропущено'):
        window.update_row(0, state, 'https://example.invalid/')
        window.open_result(0)
    window.update_row(0, 'Готово', str(tmp_path/'not-an-image.exe'))
    window.open_result(0)
    assert not opened
    window.close()


def test_missing_output_is_reported_without_opening_it(app, tmp_path, monkeypatch):
    messages = []
    monkeypatch.setattr('raw_to_png.ui.QMessageBox.information', lambda *args: messages.append(args))
    window = Window()
    window.language.setCurrentIndex(window.language.findData('en'))
    window.imported([Source(tmp_path/'photo.ARW', Path('photo.ARW'))])
    window.update_row(0, 'Готово', str(tmp_path/'missing.png'))
    window.open_result(0)
    assert messages[-1][1:] == ('File unavailable', 'The PNG was moved or deleted.')
    window.close()


def test_eta_waiting_cancel_and_completion_do_not_leave_stale_time(app):
    window = Window()
    window.eta_active = True
    window.eta.setVisible(True)
    window.update_estimate({'seconds': 100, 'waiting': False})
    assert window.eta.text() == 'Осталось примерно 2 мин'
    window.language.setCurrentIndex(window.language.findData('en'))
    assert window.eta.text() == 'About 2 min remaining'
    window.update_estimate({'seconds': None, 'waiting': True})
    assert 'paused' in window.eta.text()
    window.cancel()
    assert window.eta.isHidden() and not window.eta_active
    window.update_estimate({'seconds': 20, 'waiting': False})
    assert window.eta.isHidden()
    window.finished()
    assert window.eta.isHidden()
    window.close()


def test_background_worker_updates_eta_and_hides_it_when_finished(app, tmp_path, monkeypatch):
    from threading import Event
    from PySide6.QtCore import QObject, Slot, QEventLoop, QTimer
    start, release = Event(), Event()
    def queue(jobs, bits, options, mode, cancel, on_row, on_progress, on_activity, **kwargs):
        start.wait(5)
        for value in ({'seconds': None, 'waiting': False}, {'seconds': 90, 'waiting': False},
                      {'seconds': None, 'waiting': True}):
            kwargs['on_estimate'](value)
        release.wait(5)
        return {'ok': 0, 'failed': 0, 'skipped': 0, 'remaining': 1,
                'cancelled': False, 'elapsed': 1, 'max_active': 1}
    monkeypatch.setattr('raw_to_png.ui.run_queue', queue)
    window = Window()
    window.language.setCurrentIndex(window.language.findData('en'))
    window.destination.setText(str(tmp_path/'out'))
    window.imported([Source(tmp_path/'photo.ARW', Path('photo.ARW'))])
    window.begin()
    seen = []
    class Recorder(QObject):
        @Slot(object)
        def record(self, value):
            seen.append(window.eta.text())
            if value['waiting']:
                release.set()
    recorder = Recorder()
    window.worker.estimate.connect(recorder.record)
    loop = QEventLoop()
    window.worker.finished.connect(loop.quit)
    QTimer.singleShot(5000, loop.quit)
    start.set()
    loop.exec()
    assert seen == ['Updating the time estimate…', 'About 1 min 30 s remaining',
                    'Waiting for free memory · time estimate paused']
    assert not window.worker.isRunning() and window.eta.isHidden()
    window.close()
