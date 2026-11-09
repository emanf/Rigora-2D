"""Default asset columns and the Object Editor's side-by-side property docks."""

import pytest
from PySide6.QtCore import Qt
from test_character_objects_gui import editor as editor
from test_character_objects_gui import scene_objects

pytestmark = pytest.mark.gui


@pytest.mark.parametrize("width", (1280, 1600, 1920))
def test_default_content_has_two_columns(editor, qtbot, width):
    """Reset establishes two complete cards per row at common application sizes."""
    editor.resize(width, 900)
    editor.restore_layout()
    editor.library_tabs.setCurrentWidget(editor.content_shelf)
    grid = editor.content_shelf.results
    qtbot.waitUntil(lambda: grid.count() >= 3)
    qtbot.wait(30)
    first, second, third = [grid.visualItemRect(grid.item(i)) for i in range(3)]
    assert first.top() == second.top()
    assert third.top() > second.top()
    assert second.right() < grid.viewport().width()


def test_object_editor_keeps_inspector_closed_and_opens_it_to_the_right(editor, qtbot):
    """Inspector starts closed and opens beside Assets without changing Scene visibility."""
    _, actor, *_ = scene_objects(editor)
    assets, inspector = editor.docks["assets"], editor.docks["inspector"]
    assert inspector.isHidden()
    editor.object_edit.enter(actor)
    assert inspector.isHidden()
    inspector.toggleViewAction().trigger()
    qtbot.wait(30)
    assert not inspector.isHidden()
    assert editor.dockWidgetArea(inspector) == Qt.DockWidgetArea.RightDockWidgetArea
    assert inspector.x() >= assets.x() + assets.width()
    assert abs(inspector.y() - assets.y()) <= 1
    assert abs(inspector.height() - assets.height()) <= 1
    editor.object_edit.exit()
    assert inspector.isHidden() and not assets.isHidden()
