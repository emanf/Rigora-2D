"""Project-source drags preview and place centered artwork at the cursor without duplicate icons."""

from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt
from PySide6.QtGui import QDrag, QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QApplication
from test_roots_soft_drag_gui import editor as editor

from rigora.application_services.characters import CharacterService
from rigora.application_services.image_rigging import ImageRigService
from rigora.application_services.meshes import MeshService
from rigora.application_services.scene_editing import SceneEditingService
from rigora.domain.geometry import transform_point

pytestmark = pytest.mark.gui


def source_asset(editor, qtbot):
    """Register a real SVG and wait for the regular shared artwork decoder."""
    doc = editor.viewmodel.documents
    key = MeshService(doc).register_image_bytes(
        "Prop.svg", Path("assets/examples/prop.svg").read_bytes()
    )
    editor.viewmodel.changed.emit()
    qtbot.waitUntil(lambda: key in editor.viewport.artwork.vectors, timeout=15000)
    return key


def mime(editor, key):
    """Use exactly the same project-source/session MIME contract as Project Assets."""
    data = QMimeData()
    data.setData("application/x-rigora-project-asset", key.encode())
    data.setData("application/x-rigora-session", editor.viewmodel.documents.session_id.encode())
    return data


def send(widget, event):
    """Deliver a widget event without moving the OS pointer or starting a native drag loop."""
    QApplication.sendEvent(widget, event)
    return event


def drag_event(kind, data, point):
    """Create native Qt drag event payloads for a copy operation."""
    return kind(
        point.toPoint(),
        Qt.DropAction.CopyAction,
        data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def bounds_center(pose, mesh_ids):
    """Read the visible world-space center from evaluated vertices rather than authored offsets."""
    points = [
        transform_point(pose.nodes[mesh.object_id].world_matrix, *point)
        for key, mesh in pose.meshes.items()
        if key in mesh_ids
        for point in mesh.positions
    ]
    return tuple((min(p[i] for p in points) + max(p[i] for p in points)) / 2 for i in (0, 1))


@pytest.mark.parametrize("context", ("scene", "object", "rigged"))
def test_project_source_ghost_follows_cursor_matches_drop_and_keeps_centered_pivot(
    editor, qtbot, context
):
    """Real drag enter/moves/drop honor pan, zoom and Object Editor adoption with one Undo."""
    vm, viewport = editor.viewmodel, editor.viewport
    key = source_asset(editor, qtbot)
    owner = None
    if context != "scene":
        mesh = MeshService(vm.documents).instantiate_asset(key)
        part = str(MeshService(vm.documents).mesh(mesh).object_id)
        if context == "rigged":
            images = ImageRigService(vm.documents)
            images.convert((mesh,), "Rig")
            images.draw_bone(mesh, (800, 450), (900, 450))
        owner = CharacterService(vm.documents).create_object((part,), "Editing")
        SceneEditingService(vm.documents).transform(
            (owner,), dx=100, dy=50, rotation=13, scale_x=1.2, scale_y=0.8
        )
        vm.changed.emit()
        editor.object_edit.enter(owner)
        qtbot.wait(30)
    viewport.zoom, viewport.offset = 0.65, QPointF(43, 57)
    data = mime(editor, key)
    first, target = QPointF(130, 160), QPointF(270, 215)
    before, count = vm.documents.project, len(vm.documents.history.undo_stack)
    old_meshes = {m.id for m in vm.documents.scene.meshes}
    assert send(viewport, drag_event(QDragEnterEvent, data, first)).isAccepted()
    ghost = viewport.drop_pose
    assert ghost is not None, viewport.drop_message
    assert send(viewport, drag_event(QDragMoveEvent, data, target)).isAccepted()
    assert viewport.drop_pose is ghost
    assert vm.documents.project is before and len(vm.documents.history.undo_stack) == count
    center = bounds_center(ghost, ghost.meshes)
    screen_center = viewport.offset + QPointF(*center) * viewport.zoom + viewport.drop_translation
    assert screen_center.toTuple() == pytest.approx(target.toTuple())
    event = QDropEvent(
        target,
        Qt.DropAction.CopyAction,
        data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    assert send(viewport, event).isAccepted()
    assert viewport.drop_pose is None and viewport.drop_translation.isNull()
    placed = {m.id for m in vm.documents.scene.meshes} - old_meshes
    assert len(placed) == 1
    pose = vm.documents.animation.pose
    assert bounds_center(pose, placed) == pytest.approx(viewport.scene_point(target).toTuple())
    mesh = pose.meshes[next(iter(placed))]
    node = pose.nodes[mesh.object_id]
    assert transform_point(
        node.world_matrix, node.local.pivot_x, node.local.pivot_y
    ) == pytest.approx(viewport.scene_point(target).toTuple())
    if owner:
        assert CharacterService(vm.documents).object_root(mesh.object_id).id == owner
        assert editor.object_edit.active and editor.object_edit.key == owner
    assert len(vm.documents.history.undo_stack) == count + 1
    vm.undo()
    assert vm.documents.project == before


def test_asset_drag_uses_only_cursor_and_scene_ghost_and_cleans_up_on_cancel(
    editor, qtbot, monkeypatch
):
    """Only the OS loop is substituted; real drag events keep all floating labels absent."""
    key = source_asset(editor, qtbot)
    assets, viewport = editor.project_assets, editor.viewport
    item = next(
        assets.item(i)
        for i in range(assets.count())
        if assets.item(i).data(Qt.ItemDataRole.UserRole) == key
    )
    assets.setCurrentItem(item)
    before = editor.viewmodel.documents.project
    completed = []

    def execute(drag, *args):
        assert drag.pixmap().size().width() == 1
        assert drag.pixmap().toImage().pixelColor(0, 0).alpha() == 0
        assert not hasattr(assets, "_drag_thumbnail")
        data = drag.mimeData()
        send(editor.tree.viewport(), drag_event(QDragEnterEvent, data, QPointF(25, 25)))
        send(viewport, drag_event(QDragEnterEvent, data, QPointF(180, 170)))
        assert viewport.drop_pose is not None
        send(viewport, drag_event(QDragMoveEvent, data, QPointF(230, 200)))
        assert viewport.drop_pose is not None
        send(viewport, QDragLeaveEvent())
        assert viewport.drop_pose is None
        send(editor.tree.viewport(), drag_event(QDragEnterEvent, data, QPointF(35, 35)))
        assert not hasattr(assets, "_drag_thumbnail")
        completed.append(True)
        return Qt.DropAction.IgnoreAction

    monkeypatch.setattr(QDrag, "exec", execute)
    assets.startDrag(Qt.DropAction.CopyAction)
    assert completed
    assert viewport.drop_pose is None and not assets._scene_preview_active
    assert editor.viewmodel.documents.project is before
