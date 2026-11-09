"""Native file-dialog delegation without custom preview workers or directory scans."""

import pytest
from PySide6.QtWidgets import QFileDialog, QWidget

from rigora.presentation.widgets.file_dialogs import (
    choose_open_file,
    choose_open_files,
    choose_save_file,
)

pytestmark = pytest.mark.gui


@pytest.mark.parametrize("cancel", [False, True])
def test_native_selection_modes_and_cancel(qtbot, monkeypatch, tmp_path, cancel):
    """Keep open, multi-open and save contracts while leaving platform selection to Qt."""
    parent = QWidget()
    qtbot.addWidget(parent)
    chosen = str(tmp_path / "artwork with spaces.svg")
    other = str(tmp_path / "second.png")
    selected_filter = "Artwork (*.svg *.png)"
    calls = []

    def select_one(*args, **kwargs):
        calls.append((args, kwargs))
        return ("", "") if cancel else (chosen, selected_filter)

    def select_many(*args, **kwargs):
        calls.append((args, kwargs))
        return ([], "") if cancel else ([chosen, other], selected_filter)

    monkeypatch.setattr(QFileDialog, "getOpenFileName", select_one)
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", select_many)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", select_one)
    arguments = (parent, "Choose artwork", str(tmp_path), selected_filter)
    assert choose_open_file(*arguments) == (("", "") if cancel else (chosen, selected_filter))
    assert choose_open_files(*arguments) == ([] if cancel else [chosen, other])
    assert choose_save_file(*arguments) == (("", "") if cancel else (chosen, selected_filter))
    for args, kwargs in calls:
        assert args == arguments
        assert (
            not kwargs.get("options", QFileDialog.Option(0))
            & QFileDialog.Option.DontUseNativeDialog
        )
    assert calls[-1][1]["options"] & QFileDialog.Option.DontConfirmOverwrite
