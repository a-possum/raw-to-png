import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope='session')
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr('raw_to_png.ui.QSettings', lambda *args: QSettings(
        str(tmp_path / 'settings.ini'), QSettings.IniFormat))
    monkeypatch.setattr('raw_to_png.ui.default_diagnostics_directory', lambda: tmp_path/'diagnostics')
