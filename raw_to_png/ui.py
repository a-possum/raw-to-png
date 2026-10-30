from pathlib import Path
import sys
from threading import Event
import tempfile

from PySide6.QtCore import QSettings, QThread, QUrl, Signal, Qt, QStandardPaths
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QAbstractItemView,
    QGroupBox, QFormLayout, QDoubleSpinBox, QStackedWidget,
    QScrollArea, QFrame, QLayout, QSizePolicy,
)

from .converter import ConversionOptions, discover, plan
from .processing import run_queue
from .diagnostics import DiagnosticReport, build_channel, write_report


def default_diagnostics_directory():
    return Path(QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation)) / 'RawToPng' / 'diagnostics'


class Worker(QThread):
    row = Signal(int, str, str)
    progress = Signal(int)
    summary = Signal(str)
    activity = Signal(str)

    def __init__(self, jobs, bits, options=None, mode='auto', *, diagnostics_enabled=False,
                 diagnostics_dir=None, channel='release'):
        super().__init__()
        self.jobs, self.bits, self.options, self.mode = jobs, bits, options, mode
        self.cancel = Event()
        self.result = None
        self.diagnostics_enabled = diagnostics_enabled
        self.diagnostics_dir = diagnostics_dir or default_diagnostics_directory()
        self.channel = channel
        self.report_data = None
        self.report_error = None

    def run(self):
        report = None
        fatal_kind = None
        if self.diagnostics_enabled:
            try:
                report = DiagnosticReport(self.diagnostics_dir, channel=self.channel, mode=self.mode,
                                          bits=self.bits, options=self.options or ConversionOptions(),
                                          file_count=len(self.jobs))
            except Exception as error:
                self.report_error = type(error).__name__
        try:
            kwargs = {'diagnostics': report} if report else {}
            self.result = run_queue(self.jobs, self.bits, self.options, self.mode, self.cancel,
                                    self.row.emit, self.progress.emit, self.activity.emit, **kwargs)
        except Exception as error:
            fatal_kind = type(error).__name__
            self.summary.emit(f'Не удалось продолжить очередь: {error}')
            self.activity.emit('Обработка остановлена')
            return
        finally:
            if report:
                try:
                    self.report_data = report.finish(self.result, fatal_kind)
                    self.report_error = report.save_error
                except Exception as error:
                    self.report_error = type(error).__name__
        result = self.result
        state = 'Остановлено' if result['cancelled'] else 'Завершено'
        self.summary.emit(f"{state}. Готово: {result['ok']}, ошибок: {result['failed']}, "
                          f"пропущено: {result['skipped']}, не обработано: {result['remaining']}. "
                          f"Время: {result['elapsed']:.0f} с.")
        self.activity.emit(f"{state} · одновременно обрабатывалось до {result['max_active']} фотографий")


class Scanner(QThread):
    found = Signal(object)
    error = Signal(str)

    def __init__(self, paths, recursive):
        super().__init__()
        self.paths, self.recursive = paths, recursive

    def run(self):
        try:
            self.found.emit(discover(self.paths, self.recursive))
        except Exception as error:
            self.error.emit(str(error))


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('ARW → PNG · Конвертер фотографий')
        self.resize(1220, 820)
        self.setMinimumSize(1000, 720)
        self.setAcceptDrops(True)
        self.sources = []
        self.worker = self.scanner = None
        self.settings = QSettings('RawToPng', 'RawToPng')
        self.channel = build_channel()
        self.last_report = None
        if self.channel == 'test':
            self.setWindowTitle(self.windowTitle() + ' · тестовая сборка')
        self.applying_preset = False
        root = QWidget()
        root.setObjectName('root')
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)
        header = QHBoxLayout()
        heading = QVBoxLayout()
        title = QLabel('Ваши RAW. Готовые PNG.')
        title.setObjectName('title')
        heading.addWidget(title)
        subtitle = QLabel('Добавьте фотографии, выберите папку и запустите конвертацию.')
        subtitle.setObjectName('muted')
        heading.addWidget(subtitle)
        header.addLayout(heading)
        header.addStretch()
        badge = QLabel('SONY ARW  →  PNG')
        badge.setObjectName('badge')
        header.addWidget(badge)
        layout.addLayout(header)
        body = QHBoxLayout()
        body.setSpacing(18)
        files = QGroupBox('1  Фотографии')
        files_layout = QVBoxLayout(files)
        files_layout.setSpacing(12)
        tools = QHBoxLayout()
        self.add_files = QPushButton('+ Файлы')
        self.add_folder = QPushButton('+ Папка')
        self.remove = QPushButton('Убрать выбранные')
        self.clear = QPushButton('Очистить')
        for control in (self.add_files, self.add_folder, self.remove, self.clear):
            tools.addWidget(control)
        tools.addStretch()
        files_layout.addLayout(tools)
        self.recursive = QCheckBox('Искать ARW во вложенных папках')
        self.recursive.setChecked(True)
        files_layout.addWidget(self.recursive)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['Фотография', 'Статус', 'Результат / ошибка'])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setColumnWidth(1, 115)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        self.stack = QStackedWidget()
        empty = QLabel('Перетащите фотографии сюда\n\nФайлы .ARW или целую папку\n\nЛибо нажмите «+ Файлы» / «+ Папка» выше')
        empty.setAlignment(Qt.AlignCenter)
        empty.setObjectName('dropzone')
        self.stack.addWidget(empty)
        self.stack.addWidget(self.table)
        files_layout.addWidget(self.stack, 1)
        self.count = QLabel('Очередь пуста · оригиналы остаются без изменений')
        self.count.setObjectName('muted')
        files_layout.addWidget(self.count)
        body.addWidget(files, 1)
        side_panel = QWidget()
        side = QVBoxLayout(side_panel)
        side.setSizeConstraint(QLayout.SetMinimumSize)
        side.setContentsMargins(0, 0, 8, 0)
        side.setSpacing(14)
        save = QGroupBox('2  Куда сохранить')
        save.setFixedWidth(355)
        save_layout = QVBoxLayout(save)
        self.destination = QLineEdit(self.settings.value('destination', ''))
        self.destination.setPlaceholderText('Папка для готовых PNG')
        self.destination.setToolTip('Можно вставить полный путь или выбрать папку кнопкой ниже')
        save_layout.addWidget(self.destination)
        self.browse = QPushButton('Выбрать папку сохранения…')
        save_layout.addWidget(self.browse)
        self.preserve = QCheckBox('Сохранять структуру подпапок')
        self.preserve.setChecked(self.settings.value('preserve', True, type=bool))
        save_layout.addWidget(self.preserve)
        save_layout.addWidget(QLabel('Если PNG с таким именем уже есть:'))
        self.collision = QComboBox()
        self.collision.addItem('Создать копию с новым именем', 'rename')
        self.collision.addItem('Пропустить этот файл', 'skip')
        self.collision.setCurrentIndex(max(0, self.collision.findData(self.settings.value('collision', 'rename'))))
        save_layout.addWidget(self.collision)
        side.addWidget(save)
        options = QGroupBox('3  Как конвертировать')
        self.options_group = options
        options.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        options.setFixedWidth(355)
        options_layout = QVBoxLayout(options)
        self.preset = QComboBox()
        self.preset.addItem('Для обработки · PNG 16 бит', 'editing')
        self.preset.addItem('Для просмотра · PNG 8 бит', 'viewing')
        self.preset.addItem('Быстро · 8 бит, половина размера', 'quick')
        self.preset.addItem('Свои настройки', 'custom')
        options_layout.addWidget(self.preset)
        self.preset_help = QLabel()
        self.preset_help.setWordWrap(True)
        self.preset_help.setObjectName('muted')
        options_layout.addWidget(self.preset_help)
        options_layout.addWidget(QLabel('Производительность'))
        self.performance = QComboBox()
        self.performance.addItem('Авто · баланс скорости и нагрузки', 'auto')
        self.performance.addItem('Экономный · одна фотография', 'eco')
        self.performance.addItem('Максимальная скорость', 'maximum')
        self.performance.setCurrentIndex(max(0, self.performance.findData(
            self.settings.value('performance', 'auto'))))
        self.performance.setToolTip('Выберите баланс скорости и нагрузки на компьютер.')
        options_layout.addWidget(self.performance)
        self.maximum_warning = QLabel('Пока идёт конвертация на максимальной скорости, '
                                      'не используйте другие тяжёлые приложения.')
        self.maximum_warning.setWordWrap(True)
        self.maximum_notice = QWidget()
        self.maximum_notice.setFixedHeight(80)
        self.maximum_notice.setStyleSheet('background: #fff4da; border-radius: 6px;')
        notice_layout = QVBoxLayout(self.maximum_notice)
        notice_layout.setContentsMargins(10, 10, 10, 10)
        self.maximum_warning.setStyleSheet('color: #78531b;')
        notice_layout.addWidget(self.maximum_warning)
        options_layout.addWidget(self.maximum_notice)
        self.activity_label = QLabel()
        self.activity_label.setWordWrap(True)
        self.activity_label.setObjectName('muted')
        options_layout.addWidget(self.activity_label)
        self.performance.currentIndexChanged.connect(self.performance_changed)
        self.performance_changed()
        self.advanced_toggle = QCheckBox('Дополнительные настройки')
        options_layout.addWidget(self.advanced_toggle)
        self.advanced = QWidget()
        form = QFormLayout(self.advanced)
        form.setContentsMargins(0, 4, 0, 4)
        self.bits = QComboBox()
        self.bits.addItem('16 бит на канал', 16)
        self.bits.addItem('8 бит на канал', 8)
        form.addRow('Глубина цвета', self.bits)
        self.white_balance = QComboBox()
        self.white_balance.addItem('Как в камере', 'camera')
        self.white_balance.addItem('Автоматический', 'auto')
        self.white_balance.addItem('Дневной свет', 'daylight')
        form.addRow('Баланс белого', self.white_balance)
        self.brightness = QDoubleSpinBox()
        self.brightness.setRange(-2, 2)
        self.brightness.setSingleStep(0.25)
        self.brightness.setSuffix(' EV')
        self.brightness.setToolTip('Множитель яркости 2^EV; 0 — без коррекции')
        form.addRow('Яркость', self.brightness)
        self.auto_bright = QCheckBox('Автоматически осветлять')
        self.half_size = QCheckBox('½ ширины и высоты')
        form.addRow(self.auto_bright)
        form.addRow(self.half_size)
        self.diagnostics = QCheckBox('Записывать отчёт проверки')
        self.diagnostics.setChecked(self.channel == 'test')
        self.diagnostics.setToolTip('Отчёт хранится только на этом компьютере. '
                                    'Без фотографий, EXIF и полных путей. Никуда не отправляется.')
        form.addRow(self.diagnostics)
        options_layout.addWidget(self.advanced)
        self.advanced.setVisible(False)
        side.addWidget(options)
        note = QLabel('Все варианты сохраняются в PNG / sRGB.\nОригиналы и существующие файлы не перезаписываются.')
        note.setWordWrap(True)
        note.setObjectName('muted')
        note.setMaximumWidth(355)
        side.addWidget(note)
        side.addStretch()
        scroll = QScrollArea()
        scroll.setWidget(side_panel)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setFixedWidth(385)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet('QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }')
        body.addWidget(scroll)
        layout.addLayout(body, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setFormat('%v из %m файлов · %p%')
        layout.addWidget(self.progress)
        self.diagnostics_status = QLabel('Отчёт проверки будет сохранён только на этом компьютере.')
        self.diagnostics_status.setObjectName('muted')
        self.diagnostics_status.setVisible(self.diagnostics.isChecked())
        self.diagnostics.toggled.connect(self.diagnostics_status.setVisible)
        layout.addWidget(self.diagnostics_status)
        footer = QHBoxLayout()
        self.status = QLabel('Добавьте фотографии для начала')
        self.status.setWordWrap(True)
        self.stop = QPushButton('Остановить')
        self.stop.setEnabled(False)
        self.open_output = QPushButton('Открыть папку')
        self.save_report = QPushButton('Сохранить отчёт')
        self.save_report.setEnabled(False)
        self.save_report.setVisible(self.diagnostics.isChecked())
        self.diagnostics.toggled.connect(self.save_report.setVisible)
        self.start = QPushButton('Конвертировать')
        self.start.setObjectName('primary')
        footer.addWidget(self.status, 1)
        for control in (self.save_report, self.open_output, self.stop, self.start):
            footer.addWidget(control)
        layout.addLayout(footer)
        self.add_files.clicked.connect(self.pick_files)
        self.add_folder.clicked.connect(self.pick_folder)
        self.browse.clicked.connect(self.pick_destination)
        self.clear.clicked.connect(self.clear_queue)
        self.table.itemSelectionChanged.connect(self.refresh_actions)
        self.remove.clicked.connect(self.remove_selected)
        self.start.clicked.connect(self.begin)
        self.stop.clicked.connect(self.cancel)
        self.open_output.clicked.connect(self.open_folder)
        self.save_report.clicked.connect(self.export_report)
        self.destination.textChanged.connect(self.refresh_actions)
        self.advanced_toggle.toggled.connect(self.advanced.setVisible)
        self.advanced_toggle.toggled.connect(self.fit_options_height)
        self.preset.currentIndexChanged.connect(self.apply_preset)
        for control in (self.bits, self.white_balance):
            control.currentIndexChanged.connect(self.custom_settings)
        self.brightness.valueChanged.connect(self.custom_settings)
        self.auto_bright.toggled.connect(self.custom_settings)
        self.half_size.toggled.connect(self.custom_settings)
        self.apply_preset()
        self.restore_options()
        self.refresh_actions()
        self.setStyleSheet('''
            QWidget { font-family: "Segoe UI", sans-serif; font-size: 13px; color: #24324a; }
            QWidget#root { background: #f2f5fa; }
            QLabel#title { font-size: 27px; font-weight: 700; color: #15223b; }
            QLabel#muted { color: #65738b; }
            QLabel#badge { background: #e2eafa; color: #315dba; border-radius: 12px; padding: 10px; font-weight: 600; }
            QGroupBox { background: white; border: 1px solid #dce3ef; border-radius: 12px; margin-top: 12px; padding: 18px 12px 12px; font-weight: 600; }
            QGroupBox::title { subcontrol-origin: margin; left: 16px; padding: 0 6px; }
            QPushButton { background: #f7f9fc; border: 1px solid #d5deec; border-radius: 7px; padding: 9px 10px; }
            QPushButton:hover { background: #eaf0fc; border-color: #799be2; }
            QPushButton#primary { background: #315ed5; color: white; border: none; padding: 12px 22px; font-weight: 600; }
            QPushButton#primary:hover { background: #244bb1; }
            QPushButton#primary:disabled { color: #98a4b7; background: #e0e6f0; }
            QPushButton:disabled { color: #98a4b7; background: #edf0f5; border-color: #e0e5ed; }
            QLineEdit, QComboBox, QDoubleSpinBox { background: white; color: #24324a; border: 1px solid #d5deec; border-radius: 6px; padding: 7px; }
            QComboBox QAbstractItemView { background: white; color: #24324a; selection-background-color: #dce7ff; selection-color: #183a80; }
            QTableWidget { background: white; alternate-background-color: #f6f8fc; border: 1px solid #e0e6ef; gridline-color: #edf0f5; selection-background-color: #dce7ff; selection-color: #183a80; }
            QHeaderView::section { background: #f6f8fc; color: #65738b; border: none; padding: 10px; }
            QLabel#dropzone { background: #f7f9fd; color: #65738b; border: 2px dashed #cbd7eb; border-radius: 12px; font-size: 16px; }
            QProgressBar { background: #e5eaf3; border: none; border-radius: 6px; min-height: 20px; text-align: center; }
            QProgressBar::chunk { background: #8aacef; border-radius: 6px; }
            QCheckBox { spacing: 7px; }
        ''')
        self.fit_options_height()

    def fit_options_height(self):
        # Scroll the sidebar instead of squeezing wrapped labels into each other.
        margins = self.options_group.layout().contentsMargins()
        width = self.options_group.contentsRect().width() - margins.left() - margins.right() - 20
        notice_height = max(80, self.maximum_warning.heightForWidth(max(1, width)) + 20)
        self.maximum_notice.setFixedHeight(notice_height)
        self.options_group.layout().invalidate()
        height = self.options_group.heightForWidth(self.options_group.width())
        if height > 0:
            self.options_group.setMinimumHeight(height)

    def set_activity(self, text):
        self.activity_label.setText(text)
        self.fit_options_height()

    def performance_changed(self):
        self.maximum_notice.setVisible(self.performance.currentData() == 'maximum')
        label = {'auto': 'Авто', 'eco': 'Экономный', 'maximum': 'Максимальная скорость'}
        self.set_activity(f'{label[self.performance.currentData()]} · ожидание запуска')

    def refresh_actions(self):
        busy = self.busy()
        self.start.setEnabled(bool(self.sources) and not busy)
        self.remove.setEnabled(bool(self.table.selectedItems()) and not busy)
        self.open_output.setEnabled(bool(self.destination.text().strip()) and Path(self.destination.text().strip()).expanduser().is_dir())
        self.start.setText(f'Конвертировать {len(self.sources)} файлов' if self.sources else 'Конвертировать')
        self.count.setText(f'В очереди: {len(self.sources)} · оригиналы не изменяются' if self.sources else 'Очередь пуста · оригиналы остаются без изменений')
        self.stack.setCurrentIndex(1 if self.sources else 0)
        if not self.sources:
            self.progress.setFormat('Ожидание файлов')

    def apply_preset(self):
        mode = self.preset.currentData()
        help_text = {
            'editing': 'Полный размер и 16 бит на канал — больше данных для дальнейшей обработки.',
            'viewing': 'Полный размер, 8 бит и автоматическое осветление — для обычного просмотра.',
            'quick': 'Половина ширины и высоты, 8 бит — быстрее и меньше места на диске.',
            'custom': 'Выбраны ваши настройки. Результат сохраняется в PNG / sRGB.',
        }
        self.preset_help.setText(help_text[mode])
        self.fit_options_height()
        if mode == 'custom':
            self.advanced_toggle.setChecked(True)
            return
        self.applying_preset = True
        self.bits.setCurrentIndex(0 if mode == 'editing' else 1)
        self.white_balance.setCurrentIndex(0)
        self.brightness.setValue(0)
        self.auto_bright.setChecked(mode != 'editing')
        self.half_size.setChecked(mode == 'quick')
        self.applying_preset = False

    def custom_settings(self):
        if not self.applying_preset:
            self.preset.setCurrentIndex(self.preset.findData('custom'))

    def restore_options(self):
        mode = self.settings.value('preset', 'editing')
        self.preset.setCurrentIndex(max(0, self.preset.findData(mode)))
        if mode == 'custom':
            self.applying_preset = True
            self.bits.setCurrentIndex(1 if self.settings.value('bits', 16, type=int) == 8 else 0)
            self.white_balance.setCurrentIndex(max(0, self.white_balance.findData(self.settings.value('white_balance', 'camera'))))
            self.brightness.setValue(self.settings.value('brightness', 0.0, type=float))
            self.auto_bright.setChecked(self.settings.value('auto_bright', False, type=bool))
            self.half_size.setChecked(self.settings.value('half_size', False, type=bool))
            self.applying_preset = False

    def remove_selected(self):
        for row in sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True):
            del self.sources[row]
            self.table.removeRow(row)
        self.refresh_actions()
        self.status.setText(f'В очереди: {len(self.sources)} файлов')

    def busy(self):
        return any(worker is not None and worker.isRunning() for worker in (self.worker, self.scanner))

    def lock(self, busy):
        for control in (self.add_files, self.add_folder, self.clear, self.recursive,
                        self.destination, self.browse, self.bits, self.start, self.remove,
                        self.preserve, self.collision, self.preset, self.advanced, self.performance):
            control.setEnabled(not busy)
        if not busy:
            self.refresh_actions()

    def pick_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Выберите Sony RAW', '', 'Sony RAW (*.arw *.ARW)')
        self.add(paths)

    def pick_folder(self):
        path = QFileDialog.getExistingDirectory(self, 'Добавить папку с ARW')
        if path:
            self.add([path])

    def pick_destination(self):
        path = QFileDialog.getExistingDirectory(self, 'Папка для PNG', self.destination.text())
        if path:
            self.destination.setText(path)

    def add(self, paths):
        if not paths or self.busy():
            return
        self.lock(True)
        self.status.setText('Поиск ARW…')
        self.scanner = Scanner(paths, self.recursive.isChecked())
        self.scanner.found.connect(self.imported)
        self.scanner.error.connect(lambda error: self.status.setText(f'Ошибка чтения папки: {error}'))
        self.scanner.finished.connect(lambda: self.lock(False))
        self.scanner.start()

    def imported(self, sources):
        seen = {source.path for source in self.sources}
        for source in sources:
            if source.path not in seen:
                self.sources.append(source)
                seen.add(source.path)
                row = self.table.rowCount()
                self.table.insertRow(row)
                for column, value in enumerate((str(source.relative), 'В очереди', '')):
                    item = QTableWidgetItem(value)
                    item.setToolTip(value)
                    self.table.setItem(row, column, item)
                self.table.item(row, 0).setToolTip(str(source.path))
        self.progress.setRange(0, max(1, len(self.sources)))
        self.progress.setValue(0)
        self.progress.setFormat('%v из %m файлов · %p%')
        self.status.setText(f'В очереди: {len(self.sources)} файлов')
        self.refresh_actions()

    def clear_queue(self):
        self.sources.clear()
        self.table.setRowCount(0)
        self.progress.setValue(0)
        self.status.setText('Очередь очищена')
        self.refresh_actions()

    def begin(self):
        if not self.sources:
            QMessageBox.information(self, 'Очередь пуста', 'Добавьте файлы .ARW или папку.')
            return
        if not self.destination.text().strip():
            self.pick_destination()
            if not self.destination.text().strip():
                return
        try:
            destination = Path(self.destination.text().strip()).expanduser().resolve()
            destination.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryFile(dir=destination):
                pass
            jobs = plan(self.sources, destination, preserve_folders=self.preserve.isChecked(),
                        collision=self.collision.currentData())
        except Exception as error:
            QMessageBox.warning(self, 'Папка назначения недоступна', str(error))
            return
        self.settings.setValue('destination', str(destination))
        self.settings.setValue('bits', self.bits.currentData())
        for key, value in {
            'preset': self.preset.currentData(), 'preserve': self.preserve.isChecked(),
            'collision': self.collision.currentData(), 'white_balance': self.white_balance.currentData(),
            'brightness': self.brightness.value(), 'auto_bright': self.auto_bright.isChecked(),
            'half_size': self.half_size.isChecked(),
            'performance': self.performance.currentData(),
        }.items():
            self.settings.setValue(key, value)
        for index, (_, target) in enumerate(jobs):
            self.update_row(index, 'В очереди', str(target) if target else 'Будет пропущено: совпадение имени')
        self.progress.setRange(0, len(jobs))
        self.progress.setValue(0)
        self.lock(True)
        self.stop.setEnabled(True)
        self.status.setText('Конвертация…')
        self.last_report = None
        self.save_report.setEnabled(False)
        self.diagnostics_status.setText('Отчёт проверки записывается только на этом компьютере.')
        options = ConversionOptions(white_balance=self.white_balance.currentData(),
                                    auto_bright=self.auto_bright.isChecked(),
                                    half_size=self.half_size.isChecked(),
                                    brightness_ev=self.brightness.value())
        self.worker = Worker(jobs, self.bits.currentData(), options, self.performance.currentData(),
                             diagnostics_enabled=self.diagnostics.isChecked(),
                             diagnostics_dir=default_diagnostics_directory(), channel=self.channel)
        self.worker.row.connect(self.update_row)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.summary.connect(self.status.setText)
        self.worker.activity.connect(self.set_activity)
        self.worker.finished.connect(self.finished)
        self.worker.start()
        self.open_output.setEnabled(True)

    def update_row(self, index, state, detail):
        for column, text in ((1, state), (2, detail)):
            self.table.item(index, column).setText(text)
            self.table.item(index, column).setToolTip(text)

    def finished(self):
        self.lock(False)
        self.stop.setEnabled(False)
        if self.worker:
            self.last_report = self.worker.report_data
            self.save_report.setEnabled(self.last_report is not None)
            if self.worker.report_error:
                self.diagnostics_status.setText('Не удалось автоматически сохранить отчёт. '
                                                'Попробуйте кнопку «Сохранить отчёт».'
                                                if self.last_report is not None else
                                                'Не удалось создать отчёт проверки.')
            elif self.last_report is not None:
                self.diagnostics_status.setText('Отчёт проверки готов. Его можно сохранить и передать для проверки.')
        for row in range(self.table.rowCount()):
            if self.table.item(row, 1).text() in ('В очереди', 'Подготовка…', 'Обработка…'):
                self.update_row(row, 'Не обработано', self.table.item(row, 2).text())

    def cancel(self):
        if self.worker:
            self.worker.cancel.set()
            self.stop.setEnabled(False)
            self.status.setText('Остановка… Дождитесь завершения текущего этапа обработки RAW.')

    def export_report(self):
        if self.last_report is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Сохранить отчёт проверки',
                                             'ARW-to-PNG-report.json', 'Отчёт JSON (*.json)')
        if path:
            try:
                write_report(Path(path), self.last_report)
            except OSError:
                QMessageBox.warning(self, 'Не удалось сохранить отчёт', 'Выберите другую папку для отчёта.')

    def open_folder(self):
        path = Path(self.destination.text().strip()).expanduser()
        if self.destination.text().strip() and path.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and not self.busy():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.add([url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()])

    def closeEvent(self, event):
        if self.busy():
            self.cancel()
            event.ignore()
            QMessageBox.information(self, 'Дождитесь остановки',
                                    'Идёт обработка. Дождитесь её остановки и закройте окно ещё раз.')
        else:
            event.accept()


def main():
    if sys.argv[1:2] == ['--packaging-check']:
        from .packaging_check import run
        sys.exit(run(sys.argv[2:]))
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = Window()
    window.show()
    sys.exit(app.exec())
