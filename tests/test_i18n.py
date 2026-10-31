import pickle
import re
from pathlib import Path
from string import Formatter

import pytest
from PySide6.QtWidgets import QAbstractButton, QLabel, QGroupBox

from raw_to_png.converter import Source
from raw_to_png.i18n import ENGLISH, exception_text, message, render
from raw_to_png.ui import Window, Worker


def english(window):
    window.language.setCurrentIndex(window.language.findData('en'))


def test_messages_survive_ipc_without_translating_paths():
    path = 'C:/Фотографии/{не шаблон}/Готово.png'
    value = message('Не удалось продолжить очередь: {error}', error=path)
    restored = pickle.loads(pickle.dumps(value))
    assert render(restored, 'en') == f'Could not continue the queue: {path}'
    assert render(restored, 'ru') == f'Не удалось продолжить очередь: {path}'
    assert render(path, 'en') == path
    error = ValueError(message('Недопустимый путь назначения'))
    assert render(exception_text(error), 'en') == 'Invalid output path'


def test_catalog_preserves_format_fields():
    def fields(text):
        return sorted((field, spec, conversion) for _, field, spec, conversion
                      in Formatter().parse(text) if field is not None)
    for source, translation in ENGLISH.items():
        assert fields(source) == fields(translation), source
        assert not re.search('[А-Яа-яЁё]', translation), source


@pytest.mark.parametrize('channel', ['test', 'release'])
def test_language_switch_translates_controls_and_preserves_queue_and_options(app, tmp_path, monkeypatch, channel):
    monkeypatch.setattr('raw_to_png.ui.build_channel', lambda: channel)
    window = Window()
    try:
        window.preset.setCurrentIndex(window.preset.findData('quick'))
        window.brightness.setValue(.75)
        window.performance.setCurrentIndex(window.performance.findData('maximum'))
        path = tmp_path/'Готово {оригинал}.ARW'
        window.imported([Source(path, Path(path.name))])
        output = str(tmp_path/'Обработка… {выход}.png')
        window.update_row(0, 'Готово', output)
        window.progress.setValue(1)
        english(window)
        assert window.start.text() == 'Convert (1)'
        assert window.language.accessibleName() == 'Language'
        assert window.table.item(0, 0).text() == path.name
        assert window.table.item(0, 1).text() == 'Done'
        assert window.table.item(0, 2).text() == output
        assert window.preset.currentData() == 'custom'
        assert window.bits.currentData() == 8 and window.half_size.isChecked()
        assert window.brightness.value() == .75
        assert window.performance.currentData() == 'maximum'
        assert window.progress.value() == 1
        assert window.progress.format() == '%v of %m files · %p%'
        assert window.diagnostics.isChecked() == (channel == 'test')
        assert window.maximum_warning.text() == 'Avoid using other demanding apps while converting at maximum speed.'
        assert window.destination.placeholderText() == 'Folder for converted PNG files'
        assert window.bits.currentText() == '8 bits per channel'
        # Check the actual visible text and tooltips, including form labels.
        values = [window.windowTitle()]
        for kind in (QLabel, QAbstractButton):
            values.extend(widget.text() for widget in window.findChildren(kind))
        values.extend(group.title() for group in window.findChildren(QGroupBox))
        values.extend(render(value, 'en') for _, value in window._attributes)
        assert all(not re.search('[А-Яа-яЁё]', value) for value in values), values
        assert window.findChild(QLabel, 'badge').text() == 'ARW  →  PNG'
        window.language.setCurrentIndex(window.language.findData('ru'))
        assert window.table.item(0, 1).text() == 'Готово'
        assert window.table.item(0, 2).text() == output
        assert window.progress.format() == '%v из %m файлов · %p%'
    finally:
        window.close()


def test_language_is_restored_and_invalid_setting_falls_back(app):
    window = Window()
    english(window)
    window.close()
    restored = Window()
    assert restored.language.currentData() == 'en'
    assert restored.start.text() == 'Convert'
    restored.settings.setValue('language', 'unsupported')
    restored.close()
    fallback = Window()
    assert fallback.language.currentData() == 'ru'
    assert fallback.start.text() == 'Конвертировать'
    fallback.close()


def test_english_file_dialogs_and_validation_messages(app, tmp_path, monkeypatch):
    window = Window()
    english(window)
    calls = []
    monkeypatch.setattr('raw_to_png.ui.QFileDialog.getOpenFileNames',
                        lambda *args: (calls.append(args) or ([], '')))
    window.pick_files()
    assert calls[-1][1] == 'Select ARW files'
    assert calls[-1][-1] == 'ARW files (*.arw *.ARW)'
    monkeypatch.setattr('raw_to_png.ui.QMessageBox.information', lambda *args: calls.append(args))
    window.begin()
    assert calls[-1][1:] == ('Queue empty', 'Add .ARW files or a folder.')
    monkeypatch.setattr('raw_to_png.ui.QFileDialog.getSaveFileName',
                        lambda *args: (calls.append(args) or ('', '')))
    window.last_report = {'state': 'completed'}
    window.export_report()
    assert calls[-1][1] == 'Save diagnostic report'
    assert calls[-1][-1] == 'JSON report (*.json)'
    window.close()


def test_english_summary_and_skip_status_can_switch_back_after_processing(app, tmp_path):
    window = Window()
    english(window)
    source = Source(tmp_path/'Снимок.ARW', Path('Снимок.ARW'))
    window.imported([source])
    worker = Worker([(source, None)], 16)
    worker.row.connect(window.update_row)
    worker.activity.connect(window.set_activity)
    worker.summary.connect(lambda value: window.set_text(window.status, value))
    worker.run()
    window.worker = worker
    window.finished()
    assert window.table.item(0, 1).text() == 'Skipped'
    assert window.table.item(0, 2).text() == 'A PNG with this name already exists or is queued'
    assert 'Completed. Done: 0, errors: 0, skipped: 1, not processed: 0.' in window.status.text()
    assert window.activity_label.text() == 'Completed · up to 0 photos processed at a time'
    window.language.setCurrentIndex(window.language.findData('ru'))
    assert 'Завершено. Готово: 0, ошибок: 0, пропущено: 1' in window.status.text()
    assert window.table.item(0, 1).text() == 'Пропущено'
    window.close()


def test_worker_activity_localizes_memory_wait_and_stop(app, tmp_path):
    from raw_to_png.processing import GIB, MIB, Resources, run_queue
    from threading import Event
    cancel = Event()
    values = []
    def activity(value):
        values.append(render(value, 'en'))
        if 'waiting for free memory' in values[-1]:
            cancel.set()
    source = Source(tmp_path/'photo.ARW', Path('photo.ARW'))
    result = run_queue([(source, tmp_path/'photo.png')], 16, None, 'auto', cancel,
                       lambda *args: None, lambda *args: None, activity,
                       snapshot=lambda: Resources(8*GIB, 500*MIB, 8))
    assert result['cancelled']
    assert values == ['Auto · waiting for free memory, active tasks: 0']
