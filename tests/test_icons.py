import struct
from pathlib import Path

from PySide6.QtCore import QSize

from raw_to_png.icons import application_icon, configure_application
from raw_to_png.ui import Window


def test_icon_contains_small_and_large_windows_sizes(app):
    path = Path(__file__).resolve().parents[1]/'raw_to_png/assets/app.ico'
    data = path.read_bytes()
    assert struct.unpack_from('<HHH', data) == (0, 1, 7)
    sizes = set()
    for index in range(7):
        width, height, _, _, _, bits, length, offset = struct.unpack_from('<BBBBHHII', data, 6+16*index)
        assert bits == 32 and offset+length <= len(data)
        sizes.add((width or 256, height or 256))
    assert sizes == {(n, n) for n in (16, 24, 32, 48, 64, 128, 256)}
    icon = application_icon()
    for size in (16, 32, 256):
        assert not icon.pixmap(QSize(size, size)).isNull()
    window = Window()
    assert not window.windowIcon().isNull()
    window.close()


def test_windows_taskbar_identity_uses_app_icon(app, monkeypatch):
    from types import SimpleNamespace
    import ctypes
    import raw_to_png.icons as module
    called = []
    monkeypatch.setattr(module.sys, 'platform', 'win32')
    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(shell32=SimpleNamespace(
        SetCurrentProcessExplicitAppUserModelID=called.append)), raising=False)
    configure_application(app)
    assert called == ['RawToPng.Desktop']
    assert not app.windowIcon().isNull()
