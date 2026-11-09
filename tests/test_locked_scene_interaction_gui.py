"""Locked scene entries stay inspectable in the tree and inert beneath viewport pointers."""

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from test_roots_soft_drag_gui import drag
from test_roots_soft_drag_gui import editor as editor
from test_scene_artwork_picking_gui import layers

from rigora.application_services.scene_editing import SceneEditingService

pytestmark = pytest.mark.gui


@pytest.mark.parametrize("kind", ("camera", "artwork"))
def test_locked_entries_ignore_viewport_hover_and_drag_but_allow_tree_selection(
    editor, qtbot, kind
):
    """Even tree-selected locked entries have no viewport handles or pointer reactions."""
    vm, viewport, workspace = editor.viewmodel, editor.viewport, editor.scene_workspace
    if kind == "camera":
        key = vm.documents.scene.cameras[0].id
        viewport.zoom, viewport.offset = 0.2, QPointF(50, 50)
        point = QPointF(200, 50)
    else:
        (_, key), _ = layers(editor, qtbot)
        point = viewport.offset + QPointF(123, 144)
    SceneEditingService(vm.documents).flags((key,), locked=True)
    vm.changed.emit()
    if kind == "artwork":
        back = next(o.id for o in vm.documents.scene.objects if o.id != key)
        SceneEditingService(vm.documents).flags((back,), locked=True)
        vm.changed.emit()
    empty = QPointF(10, viewport.height() - 10)
    assert workspace.pick(point) == ""
    assert workspace.cursor_at(point).shape() == workspace.cursor_at(empty).shape()
    before, steps = vm.documents.project, len(vm.documents.history.undo_stack)
    drag(viewport, point, point + QPointF(20, 20))
    assert key not in vm.scene.selected
    assert vm.documents.project == before
    tree = editor.tree
    item = workspace.items[key]
    tree.scrollToItem(item)
    QTest.mouseClick(
        tree.viewport(), Qt.MouseButton.LeftButton, pos=tree.visualItemRect(item).center()
    )
    assert vm.scene.selected == (key,)
    assert workspace.transform_frame() is None
    viewport.refresh_cursor(point)
    assert viewport.cursor().shape() == workspace.cursor_at(empty).shape()
    drag(viewport, point, point + QPointF(20, 20))
    assert vm.documents.project == before and len(vm.documents.history.undo_stack) == steps
    item = workspace.items[key]
    tree.scrollToItem(item)
    lock = QPoint(
        tree.header().sectionViewportPosition(2) + tree.columnWidth(2) // 2,
        tree.visualItemRect(item).center().y(),
    )
    QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=lock)
    qtbot.waitUntil(lambda: not vm.scene.service.locked(key), timeout=3000)
    assert workspace.pick(point) == key
    assert len(vm.documents.history.undo_stack) == steps + 1


def test_locked_foreground_does_not_block_hover_or_selection_of_unlocked_artwork(editor, qtbot):
    """Pointer behavior passes through a locked foreground to an editable object behind it."""
    (back, front), _ = layers(editor, qtbot)
    vm, viewport, workspace = editor.viewmodel, editor.viewport, editor.scene_workspace
    SceneEditingService(vm.documents).flags((front,), locked=True)
    vm.changed.emit()
    point = viewport.offset + QPointF(123, 144)
    assert workspace.cursor_at(point).shape() == Qt.CursorShape.SizeAllCursor
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=point.toPoint())
    assert vm.scene.selected == (back,)
