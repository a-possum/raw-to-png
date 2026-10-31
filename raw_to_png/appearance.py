"""Window colours only; conversion settings and image pixels are independent."""
from string import Template

from PySide6.QtGui import QColor, QPalette


COLOURS = {
    'dark': {
        'background': '#15191f', 'panel': '#1c222b', 'field': '#222a35',
        'text': '#e6eaf1', 'muted': '#a9b5c7', 'border': '#354154',
        'alternate': '#202733', 'hover': '#2c3b53', 'selected': '#36598b',
        'selected_text': '#ffffff', 'primary': '#3865cf', 'primary_hover': '#4775e0',
        'disabled': '#8190a6', 'disabled_background': '#252e3c',
        'badge': '#243653', 'badge_text': '#b4ccff',
        'warning': '#3b301f', 'warning_text': '#f1d191', 'progress': '#467ad1',
    },
    'light': {
        'background': '#f2f5fa', 'panel': '#ffffff', 'field': '#f7f9fc',
        'text': '#24324a', 'muted': '#65738b', 'border': '#d5deec',
        'alternate': '#f6f8fc', 'hover': '#eaf0fc', 'selected': '#dce7ff',
        'selected_text': '#183a80', 'primary': '#315ed5', 'primary_hover': '#244bb1',
        'disabled': '#78859a', 'disabled_background': '#e0e6f0',
        'badge': '#e2eafa', 'badge_text': '#315dba',
        'warning': '#fff4da', 'warning_text': '#78531b', 'progress': '#8aacef',
    },
}


def theme_code(value):
    return value if value in COLOURS else 'dark'


def palette(theme):
    c = COLOURS[theme_code(theme)]
    result = QPalette()
    for role, key in ((QPalette.Window, 'background'), (QPalette.WindowText, 'text'),
                      (QPalette.Base, 'panel'), (QPalette.AlternateBase, 'alternate'),
                      (QPalette.Text, 'text'), (QPalette.Button, 'field'),
                      (QPalette.ButtonText, 'text'), (QPalette.Highlight, 'selected'),
                      (QPalette.HighlightedText, 'selected_text'),
                      (QPalette.ToolTipBase, 'field'), (QPalette.ToolTipText, 'text'),
                      (QPalette.Link, 'badge_text'), (QPalette.BrightText, 'selected_text')):
        result.setColor(role, QColor(c[key]))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        result.setColor(QPalette.Disabled, role, QColor(c['disabled']))
    return result


def stylesheet(theme):
    c = COLOURS[theme_code(theme)]
    return Template('''
        QWidget { font-family: "Segoe UI", sans-serif; font-size: 13px; color: $text; }
        QWidget#root { background: $background; }
        QLabel { background: transparent; }
        QLabel#title { font-size: 27px; font-weight: 700; color: $text; }
        QLabel#muted { color: $muted; }
        QLabel#badge { background: $badge; color: $badge_text; border-radius: 12px; padding: 10px; font-weight: 600; }
        QGroupBox { background: $panel; border: 1px solid $border; border-radius: 12px; margin-top: 12px; padding: 18px 12px 12px; font-weight: 600; }
        QGroupBox::title { subcontrol-origin: margin; left: 16px; padding: 0 6px; }
        QPushButton { background: $field; border: 1px solid $border; border-radius: 7px; padding: 9px 10px; }
        QPushButton:hover { background: $hover; border-color: $progress; }
        QPushButton#primary { background: $primary; color: white; border: none; padding: 12px 22px; font-weight: 600; }
        QPushButton#primary:hover { background: $primary_hover; }
        QPushButton:disabled, QPushButton#primary:disabled { color: $disabled; background: $disabled_background; border-color: $border; }
        QLineEdit, QComboBox, QDoubleSpinBox { background: $field; color: $text; border: 1px solid $border; border-radius: 6px; padding: 7px; selection-background-color: $selected; selection-color: $selected_text; }
        QComboBox QAbstractItemView { background: $field; color: $text; selection-background-color: $selected; selection-color: $selected_text; }
        QComboBox:disabled, QLineEdit:disabled, QDoubleSpinBox:disabled { color: $disabled; background: $disabled_background; }
        QCheckBox:disabled { color: $disabled; }
        QTableWidget { background: $panel; alternate-background-color: $alternate; border: 1px solid $border; gridline-color: $border; selection-background-color: $selected; selection-color: $selected_text; }
        QHeaderView::section { background: $alternate; color: $muted; border: none; padding: 10px; }
        QLabel#dropzone { background: $field; color: $muted; border: 2px dashed $border; border-radius: 12px; font-size: 16px; }
        QWidget#maximumNotice { background: $warning; border-radius: 6px; }
        QLabel#maximumWarning { color: $warning_text; }
        QProgressBar { background: $disabled_background; border: none; border-radius: 6px; min-height: 20px; text-align: center; }
        QProgressBar::chunk { background: $progress; border-radius: 6px; }
        QCheckBox { spacing: 7px; }
        QCheckBox::indicator:unchecked { border: 1px solid $muted; background: $field; border-radius: 2px; }
        QToolTip { background: $field; color: $text; border: 1px solid $border; padding: 5px; }
        QScrollBar:vertical { background: $background; width: 12px; margin: 0; }
        QScrollBar::handle:vertical { background: $border; min-height: 24px; border-radius: 5px; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
    ''').substitute(c)
