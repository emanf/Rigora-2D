"""Real Templates shelf placement for the new layered scenes and background Objects."""

import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication
from test_roots_soft_drag_gui import editor as editor

from rigora.domain.geometry import transform_point

pytestmark = pytest.mark.gui


@pytest.mark.parametrize("name,category", (("Pine tree", "Environment"), ("Torch", "Fire & smoke")))
def test_templates_shelf_scenery_drag_previews_at_cursor_and_commits_once(
    editor, qtbot, name, category
):
    """Discover only useful categories, then position complete scenery via real viewport events."""
    vm, viewport, shelf = editor.viewmodel, editor.viewport, editor.content_shelf
    qtbot.waitUntil(lambda: not vm.content.busy and bool(vm.content.entries), timeout=15000)
    categories = [shelf.collection.itemText(i) for i in range(shelf.collection.count())]
    assert category in categories
    shelf.collection.setCurrentText(category)
    row = next(
        shelf.results.item(i)
        for i in range(shelf.results.count())
        if shelf.results.item(i).text() == name
    )
    entry = row.data(Qt.ItemDataRole.UserRole)
    baseline = vm.documents.project
    viewport.zoom, viewport.offset = 0.5, QPointF(30, 40)
    point = QPointF(310, 230)
    mime = QMimeData()
    mime.setData("application/x-rigora-content", entry.key.encode())
    enter = QDragEnterEvent(
        point.toPoint(),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(viewport, enter)
    assert enter.isAccepted()
    qtbot.waitUntil(lambda: viewport.drop_pose is not None, timeout=15000)
    ghost = viewport.drop_pose
    parts = len(ghost.meshes)
    assert parts > 0
    assert vm.documents.project is baseline
    owner = next(n for n in ghost.nodes.values() if n.kind == "group" and n.parent_id is None)
    expected = viewport.scene_point(point)
    anchor = QPointF(*transform_point(owner.world_matrix, owner.local.pivot_x, owner.local.pivot_y))
    painted = viewport.offset + anchor * viewport.zoom + viewport.drop_translation
    assert (painted - point).manhattanLength() < 1e-6
    drop = QDropEvent(
        point,
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(viewport, drop)
    qtbot.waitUntil(lambda: vm.documents.project is not baseline, timeout=15000)
    assert drop.isAccepted() and viewport.drop_pose is None
    if editor.object_edit.active:
        editor.object_edit.exit()
    doc = vm.documents
    assert len(doc.scene.meshes) == parts and len(doc.history.undo_stack) == 1
    assert not doc.animation.pose.warnings
    owner = next(g for g in doc.scene.groups if g.extra.get("object_container"))
    assert transform_point(
        doc.animation.pose.nodes[owner.id].world_matrix,
        owner.transform.pivot_x,
        owner.transform.pivot_y,
    ) == pytest.approx(expected.toTuple())
    vm.undo()
    assert doc.project == baseline
