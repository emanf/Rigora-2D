"""Shared theme and background-worker recovery checks using actual Qt controls."""

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDoubleSpinBox, QPlainTextEdit, QVBoxLayout

from rigora.presentation.icons import IconProvider
from rigora.presentation.themes import PALETTES, ThemeManager
from rigora.presentation.viewmodels.content_library import LibraryJob

pytestmark = pytest.mark.gui


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_numeric_and_multiline_fields_share_palette_and_keyboard_focus(qapp, qtbot, theme):
    """Decimal and multiline controls retain readable surfaces and a working Tab chain."""
    manager = ThemeManager(qapp, IconProvider())
    manager.apply(theme)
    dialog = QDialog()
    qtbot.addWidget(dialog)
    layout = QVBoxLayout(dialog)
    numeric, multiline = QDoubleSpinBox(), QPlainTextEdit()
    numeric.setAccessibleName("Export start frame")
    multiline.setAccessibleName("Media source paths")
    layout.addWidget(numeric)
    layout.addWidget(multiline)
    dialog.show()
    numeric.setFocus()
    qtbot.waitUntil(numeric.hasFocus)
    qtbot.keyClick(numeric, Qt.Key.Key_Tab)
    assert multiline.hasFocus()
    assert numeric.grab().toImage().pixelColor(4, 4).name() == PALETTES[theme]["raised"]
    assert multiline.grab().toImage().pixelColor(4, 4).name() == PALETTES[theme]["raised"]
    manager.apply("dark")


def test_unexpected_decoder_failure_emits_recoverable_result(qtbot):
    """A codec RuntimeError must release import controls instead of stranding a busy worker."""

    def failing():
        """Represent a third-party decoder failure outside normal validation exceptions."""
        raise RuntimeError("Codec unavailable")

    job = LibraryJob(failing)
    with qtbot.waitSignal(job.signals.failed) as signal:
        job.run()
    assert signal.args == ["Codec unavailable"]
