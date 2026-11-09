"""Main toolbar wrapping, group arrangement and persistent authoring controls."""

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QScrollArea
from test_roots_soft_drag_gui import editor as editor
from test_roots_soft_drag_gui import pointer

pytestmark = pytest.mark.gui


@pytest.mark.parametrize("width", (900, 1200, 1800))
def test_main_toolbar_wraps_without_scrollbars_or_overlapping_groups(editor, qtbot, width):
    """Resizing keeps every group visible and gives the document the remaining height."""
    editor.resize(width, 900)
    qtbot.wait(20)
    bar = editor.main_tools
    assert not bar.findChildren(QScrollArea)
    boxes = [group.geometry() for group in bar.groups.values()]
    assert all(bar.rect().contains(box) for box in boxes)
    assert all(not a.intersects(b) for i, a in enumerate(boxes) for b in boxes[i + 1 :])
    if width == 900:
        assert len({box.top() for box in boxes}) > 1
    assert editor.menuWidget().height() == editor.titlebar.height() + bar.height()


def test_group_grip_reorders_without_changing_document_and_saves_preferences(editor, qtbot):
    """A real grip drag and keyboard reorder persist without adding project undo steps."""
    editor.resize(1200, 900)
    qtbot.wait(20)
    bar, doc = editor.main_tools, editor.viewmodel.documents
    before, steps = doc.project, len(doc.history.undo_stack)
    order = bar.order()
    source, target = bar.grips[order[-1]], bar.groups[order[0]]
    destination = source.mapFrom(bar, target.geometry().topLeft()).toPointF()
    pointer(source, QMouseEvent.Type.MouseButtonPress, QPointF(source.rect().center()))
    pointer(source, QMouseEvent.Type.MouseMove, destination)
    pointer(source, QMouseEvent.Type.MouseButtonRelease, destination)
    assert bar.order()[0] == order[-1]
    saved = editor.viewmodel.preferences.data["main_toolbar_order"]
    assert saved == bar.order()
    assert doc.project is before and len(doc.history.undo_stack) == steps
    QTest.keyClick(source, Qt.Key.Key_End)
    assert bar.order() == order
    assert editor.viewmodel.preferences.path.exists()


def test_toolbar_restores_known_groups_and_reset_restores_default_order(editor):
    """Stale, duplicate and unknown preference entries cannot lose toolbar controls."""
    bar = editor.main_tools
    original = bar.order()
    bar.restore_order([original[-1], "unknown", original[-1], original[0]])
    assert bar.order()[0] == original[-1]
    assert len(bar.order()) == len(set(bar.order())) == len(original)
    editor.restore_layout()
    assert bar.order() == original
