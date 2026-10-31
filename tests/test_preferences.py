from pathlib import Path

import pytest
from PySide6.QtGui import QPalette

from raw_to_png.converter import Source
from raw_to_png.ui import Window


def test_fresh_start_is_full_size_8bit_dark_and_no_auto_brightness(app):
    window = Window()
    window.show()
    app.processEvents()
    assert window.preset.currentData() == 'viewing'
    assert window.bits.currentData() == 8
    assert not window.half_size.isChecked()
    assert not window.auto_bright.isChecked()
    assert window.auto_bright.isVisible() and not window.advanced.isVisible()
    assert window.theme.currentData() == 'dark'
    assert window.palette().color(QPalette.Window).lightness() < 64
    window.close()


def test_presets_and_bit_depth_never_enable_or_clear_manual_brightness(app):
    window = Window()
    for manual in (False, True):
        window.auto_bright.setChecked(manual)
        for preset, bits, half in [('editing', 16, False), ('quick', 8, True), ('viewing', 8, False)]:
            window.preset.setCurrentIndex(window.preset.findData(preset))
            assert window.bits.currentData() == bits
            assert window.half_size.isChecked() == half
            assert window.auto_bright.isChecked() == manual
        window.bits.setCurrentIndex(window.bits.findData(16))
        assert window.auto_bright.isChecked() == manual
    window.close()


@pytest.mark.parametrize('old_preset,old_bits,old_auto,expected_preset,expected_bits,expected_auto', [
    ('viewing', 8, True, 'viewing', 8, False),
    ('quick', 8, True, 'quick', 8, False),
    ('editing', 16, False, 'viewing', 8, False),
    ('custom', 16, True, 'custom', 16, True),
])
def test_old_preferences_migrate_once(app, old_preset, old_bits, old_auto,
                                      expected_preset, expected_bits, expected_auto):
    from raw_to_png.ui import QSettings
    settings = QSettings('RawToPng', 'RawToPng')
    settings.setValue('preset', old_preset)
    settings.setValue('bits', old_bits)
    settings.setValue('auto_bright', old_auto)
    window = Window()
    assert window.preset.currentData() == expected_preset
    assert window.bits.currentData() == expected_bits
    assert window.auto_bright.isChecked() == expected_auto
    # A later explicit 16-bit choice must survive the next launch.
    window.settings.setValue('preset', 'editing')
    window.settings.setValue('bits', 16)
    window.settings.setValue('auto_bright', True)
    window.close()
    restored = Window()
    assert restored.preset.currentData() == 'editing'
    assert restored.bits.currentData() == 16
    assert restored.auto_bright.isChecked()
    restored.close()


def test_theme_and_language_preserve_queue_options_and_selection(app, tmp_path):
    window = Window()
    window.imported([Source(tmp_path/'a.ARW', Path('a.ARW'))])
    window.table.selectRow(0)
    window.preset.setCurrentIndex(window.preset.findData('editing'))
    window.auto_bright.setChecked(True)
    for theme in ('light', 'dark'):
        window.theme.setCurrentIndex(window.theme.findData(theme))
        for language in ('en', 'ru'):
            window.language.setCurrentIndex(window.language.findData(language))
            assert window.theme.currentData() == theme
            assert window.preset.currentData() == 'editing'
            assert window.bits.currentData() == 16
            assert window.auto_bright.isChecked()
            assert window.table.item(0, 0).text() == 'a.ARW'
            assert window.table.selectedItems()
        assert (window.palette().color(QPalette.Window).lightness() < 64) == (theme == 'dark')
    window.theme.setCurrentIndex(window.theme.findData('light'))
    window.close()
    restored = Window()
    assert restored.theme.currentData() == 'light'
    restored.settings.setValue('theme', 'invalid')
    restored.close()
    fallback = Window()
    assert fallback.theme.currentData() == 'dark'
    fallback.close()


def test_visible_brightness_is_locked_during_conversion(app):
    window = Window()
    window.lock(True)
    assert not window.auto_bright.isEnabled()
    assert not window.theme.isEnabled()
    window.lock(False)
    assert window.auto_bright.isEnabled() and window.theme.isEnabled()
    window.close()


def test_maximum_warning_is_visible_in_a_small_dark_window(app):
    window = Window()
    window.resize(1000, 720)
    window.show()
    window.performance.setCurrentIndex(window.performance.findData('maximum'))
    app.processEvents()
    app.processEvents()
    assert not window.maximum_notice.visibleRegion().isEmpty()
    window.close()
