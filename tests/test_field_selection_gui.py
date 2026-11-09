"""Shared text selections are visible in standalone and embedded numeric/text editors."""

from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDateTimeEdit,
    QDoubleSpinBox,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from rigora.presentation.icons import IconProvider
from rigora.presentation.themes import ThemeManager

pytestmark = pytest.mark.gui


@pytest.mark.parametrize("theme", ("dark", "light"))
def test_common_fields_paint_visible_select_all(qapp, qtbot, theme):
    """Ctrl+A paints a contrasting selection without changing text, values or editor sizing."""
    ThemeManager(qapp, IconProvider()).apply(theme)
    host = QWidget()
    qtbot.addWidget(host)
    box = QVBoxLayout(host)
    fields = [
        QLineEdit("Selected words"),
        QSpinBox(),
        QDoubleSpinBox(),
        QDateTimeEdit(),
        QComboBox(),
        QPlainTextEdit("Selected words"),
        QTextEdit("Selected words"),
    ]
    fields[1].setValue(42)
    fields[2].setValue(42.25)
    fields[4].setEditable(True)
    fields[4].setEditText("Selected words")
    for widget in fields:
        box.addWidget(widget)
    host.resize(320, 620)
    host.show()
    output = Path("build/field-selection-review")
    output.mkdir(parents=True, exist_ok=True)
    for widget in fields:
        field = widget.lineEdit() if hasattr(widget, "lineEdit") else widget
        field.setFocus()
        if isinstance(field, QLineEdit):
            field.deselect()
        else:
            cursor = field.textCursor()
            cursor.clearSelection()
            field.setTextCursor(cursor)
        qtbot.wait(5)
        plain = field.grab().toImage()
        dimensions = widget.size()
        QApplication.sendEvent(
            field,
            QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier, "a"),
        )
        selected = field.grab().toImage()
        changed = sum(
            plain.pixel(x, y) != selected.pixel(x, y)
            for y in range(plain.height())
            for x in range(plain.width())
        )
        assert changed > 60, (theme, type(widget).__name__, changed)
        palette = field.palette()
        background = palette.color(QPalette.ColorRole.Base)
        highlight = palette.color(QPalette.ColorRole.Highlight)
        text = palette.color(QPalette.ColorRole.HighlightedText)
        assert abs(highlight.lightness() - background.lightness()) >= 60
        assert abs(text.lightness() - highlight.lightness()) >= 90
        assert widget.size() == dimensions
        selected.save(str(output / f"{theme}-{type(widget).__name__}.png"))
