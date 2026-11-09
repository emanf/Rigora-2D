"""Compact dock captions and overlapping resize targets keep the workspace contiguous."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QSplitter
from test_character_objects_gui import editor as editor

pytestmark = pytest.mark.gui


def test_docked_and_floating_panels_have_only_title_and_close(editor, qtbot):
    """All shared panels keep a single close control in either placement mode."""
    for key in ("hierarchy", "assets", "inspector", "timeline"):
        dock = editor.docks[key]
        dock.show()
        for floating in (False, True):
            dock.setFloating(floating)
            qtbot.wait(10)
            assert not hasattr(dock, "detach_button")
            assert dock.titlebar.minimize_button.isHidden()
            assert dock.titlebar.maximize_button.isHidden()
            assert dock.titlebar.close_button.isVisible()
            assert dock.titlebar.height() == 32
        dock.titlebar.close_button.click()
        assert dock.isHidden()
        dock.setFloating(False)
        dock.toggleViewAction().trigger()
        assert not dock.isHidden()


def test_caption_double_click_redocks_and_plugin_removal_retires_resize_target(editor, qtbot):
    """A panel remains recoverable without float buttons and leaves no stale input overlay."""
    from shiboken6 import isValid

    from rigora.presentation.widgets.window_frame import DockPanel

    panel = DockPanel("Temporary plugin panel", editor, editor.icons)
    editor.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, panel)
    panel.show()
    qtbot.wait(10)
    QTest.mouseDClick(panel.titlebar, Qt.MouseButton.LeftButton)
    assert panel.isFloating()
    QTest.mouseDClick(panel.titlebar, Qt.MouseButton.LeftButton)
    assert not panel.isFloating()
    grip = panel.resize_grip
    panel.deleteLater()
    qtbot.waitUntil(lambda: not isValid(panel))
    qtbot.waitUntil(lambda: not isValid(grip))


def test_dividers_reserve_one_pixel_and_resize_targets_overlap(editor, qtbot):
    """Hairline boundaries leave room for data while resize handles overlap adjacent pixels."""
    for splitter in editor.findChildren(QSplitter):
        assert splitter.handleWidth() == 1
    qtbot.wait(20)
    center, assets = editor.centralWidget(), editor.docks["assets"]
    assert assets.x() - (center.x() + center.width()) == 1
    handle = assets.resize_grip
    assert handle.parentWidget() is editor and handle.width() == 7
    assert handle.isVisible()
    assert handle.geometry().contains(assets.pos())
    assert handle.cursor().shape() == Qt.CursorShape.SizeHorCursor
    timeline = editor.docks["timeline"]
    assert timeline.titleBarWidget() is timeline.titlebar
    assert timeline.resize_grip.height() == 7
    assert timeline.resize_grip.geometry().contains(timeline.pos())
    editor.docks["assets"].setFloating(True)
    qtbot.wait(20)
    assert handle.isHidden()
