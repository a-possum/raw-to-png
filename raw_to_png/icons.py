"""Shared identity for the application window, Windows taskbar and dialogs."""
from pathlib import Path
import sys

from PySide6.QtGui import QIcon


def application_icon():
    return QIcon(str(Path(__file__).with_name('assets')/'app.ico'))


def configure_application(app):
    if sys.platform == 'win32':
        import ctypes
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('RawToPng.Desktop')
        except (AttributeError, OSError):
            pass
    app.setWindowIcon(application_icon())
