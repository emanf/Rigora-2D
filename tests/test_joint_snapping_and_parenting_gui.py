"""Joint magnets and Scene drops use stable geometry and undoable application commands."""

import json
from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from test_rigging_gui import move_pointer
from test_unified_tools_gui import bones, drag
from test_workspace_redesign_gui import editor as editor

from rigora.application_services.characters import CharacterService
from rigora.application_services.meshes import MeshService
from rigora.application_services.rigging import RigService
from rigora.application_services.scene_editing import SceneEditingService

pytestmark = pytest.mark.gui


@pytest.mark.parametrize("scope", ["selection_move", "rig_move"])
@pytest.mark.parametrize("zoom", [1, 2])
@pytest.mark.parametrize("free", [False, True])
def test_group_move_snaps_joints_in_pixels_and_alt_preserves_raw_drag(editor, scope, zoom, free):
    """Align a multi-bone group without reparenting; Alt bypasses at any zoom."""
    window, vm = editor, editor.viewmodel
    _, middle, tip = bones(window)
    RigService(vm.documents).create_bone((420, 220), (460, 220), new_skeleton=True)
    vm.changed.emit()
    vm.rig.select_many((middle, tip))
    window.bone_mode_buttons[scope].click()
    viewport = window.viewport
    viewport.zoom = zoom
    viewport.offset = QPointF(20, 20)
    start = viewport.offset + QPointF(240, 160) * zoom
    end = start + QPointF(220 - 9 / zoom, 60) * zoom
    baseline = vm.documents.project
    parents = {b.id: b.parent_id for r in baseline.scenes[0].skeletons for b in r.bones}
    count = len(vm.documents.history.undo_stack)
    drag(
        viewport,
        start.toPoint(),
        end.toPoint(),
        Qt.KeyboardModifier.AltModifier if free else Qt.KeyboardModifier.NoModifier,
    )
    assert not vm.rig.error
    expected = (420 - 9 / zoom, 220) if free else (420, 220)
    assert vm.documents.animation.pose.nodes[middle].world_matrix[4:] == pytest.approx(expected)
    assert {
        b.id: b.parent_id for r in vm.documents.project.scenes[0].skeletons for b in r.bones
    } == parents
    assert len(vm.documents.history.undo_stack) == count + 1
    vm.undo()
    assert vm.documents.project == baseline


def test_alt_toggles_group_snap_without_pointer_motion(editor):
    """A held modifier immediately releases/restores the magnet during the same gesture."""
    window, vm = editor, editor.viewmodel
    _, middle, tip = bones(window)
    RigService(vm.documents).create_bone((420, 220), (460, 220))
    vm.changed.emit()
    vm.rig.select_many((middle, tip))
    viewport = window.viewport
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=QPoint(260, 180))
    move_pointer(viewport, QPoint(471, 240))
    assert vm.rig.pose.nodes[middle].world_matrix[4:] == pytest.approx((420, 220))
    assert viewport._movement_snap == QPointF(420, 220)
    QTest.keyPress(viewport, Qt.Key.Key_Alt)
    assert vm.rig.pose.nodes[middle].world_matrix[4:] == pytest.approx((411, 220))
    assert viewport._movement_snap is None
    QTest.keyRelease(viewport, Qt.Key.Key_Alt)
    assert vm.rig.pose.nodes[middle].world_matrix[4:] == pytest.approx((420, 220))
    QTest.keyClick(viewport, Qt.Key.Key_Escape)
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=QPoint(471, 240))
    assert viewport._movement_snap is None


def drop_rows(tree, keys, target, below=False):
    """Deliver the same MIME and source contract as a native Scene row drag."""

    class RowDrop(QDropEvent):
        def source(self):
            """Identify the source tree for its internal-only move contract."""
            return tree

    tree.expandAll()
    tree.scrollToItem(target)
    data = QMimeData()
    data.setData("application/x-rigora-scene", json.dumps(keys).encode())
    rect = tree.visualItemRect(target)
    point = rect.center()
    if below:
        point.setY(rect.bottom() - 1)
    enter = QDragEnterEvent(
        point,
        Qt.DropAction.MoveAction,
        data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(tree.viewport(), enter)
    move = QDragMoveEvent(
        point,
        Qt.DropAction.MoveAction,
        data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(tree.viewport(), move)
    event = RowDrop(
        QPointF(point),
        Qt.DropAction.MoveAction,
        data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(tree.viewport(), event)


def test_scene_drop_reparents_bone_branch_and_skeleton_drop_detaches(editor):
    """Bone rows support real drops, preserving branch geometry and one-step undo."""
    window, vm = editor, editor.viewmodel
    root, middle, tip = bones(window)
    target = RigService(vm.documents).create_bone((400, 350), (470, 350))
    vm.changed.emit()
    baseline = vm.documents.project
    before = RigService(vm.documents).rest_pose()
    count = len(vm.documents.history.undo_stack)
    assert window.scene_workspace.items[middle].flags() & Qt.ItemFlag.ItemIsDragEnabled
    drop_rows(window.tree, (middle, tip), window.scene_workspace.items[target])
    assert not vm.scene.error
    rig = RigService(vm.documents)
    assert rig.bone(middle).parent_id == target and rig.bone(tip).parent_id == middle
    for key in (root, middle, tip):
        assert rig.rest_pose().nodes[key].world_matrix == pytest.approx(
            before.nodes[key].world_matrix
        )
    assert window.scene_workspace.items[middle].parent() == window.scene_workspace.items[target]
    assert len(vm.documents.history.undo_stack) == count + 1
    vm.undo()
    assert vm.documents.project == baseline
    skeleton = vm.documents.project.scenes[0].skeletons[0]
    drop_rows(window.tree, (middle,), window.scene_workspace.items[skeleton.id])
    master = next(b.id for b in skeleton.bones if b.extra.get("rig_root"))
    assert not vm.scene.error and rig.bone(middle).parent_id == master


def test_fk_rotation_snaps_only_reachable_joint_and_keeps_base_fixed(editor):
    """FK magnets align a reachable joint by angle without translating or stretching a chain."""
    window, vm = editor, editor.viewmodel
    _, middle, tip = bones(window)
    RigService(vm.documents).create_bone((200, 240), (240, 240))
    vm.changed.emit()
    vm.rig.select_many((middle, tip))
    window.bone_mode_buttons["chain_move"].click()
    drag(window.viewport, QPoint(260, 180), QPoint(225, 220))
    assert not vm.rig.error
    pose = vm.documents.animation.pose
    assert pose.nodes[middle].world_matrix[4:] == pytest.approx((200, 160))
    assert pose.nodes[tip].world_matrix[4:] == pytest.approx((200, 240))


def test_scene_drop_artwork_onto_bones_and_back_into_folder(editor):
    """Attachment rows follow keep-world reattachment and detachment."""
    window, vm = editor, editor.viewmodel
    root, _, tip = bones(window)
    mesh_service = MeshService(vm.documents)
    mesh = mesh_service.import_image(Path("assets/examples/prop.svg"), 3, 3)
    CharacterService(vm.documents).add_object_parts(window.object_edit.key, (mesh,))
    owner = mesh_service.mesh(mesh).object_id
    service = SceneEditingService(vm.documents)
    folder = service.group()
    service.move_entries((folder,), window.object_edit.key)
    vm.changed.emit()
    world = vm.documents.animation.pose.nodes[owner].world_matrix
    for target in (root, tip, folder):
        drop_rows(window.tree, (owner,), window.scene_workspace.items[target])
        assert not vm.scene.error
        assert window.scene_workspace.items[owner].parent() == window.scene_workspace.items[target]
        assert vm.documents.animation.pose.nodes[owner].world_matrix == pytest.approx(world)


def test_scene_drop_below_bone_reorders_siblings_in_visual_order(editor):
    """A below-row drop places bones after their sibling in visual order."""
    window, vm = editor, editor.viewmodel
    root, middle, _ = bones(window)
    sibling = RigService(vm.documents).create_bone((200, 160), (200, 250), root)
    vm.changed.emit()
    drop_rows(window.tree, (middle,), window.scene_workspace.items[sibling], below=True)
    assert not vm.scene.error
    row = window.scene_workspace.items[root]
    assert row.indexOfChild(window.scene_workspace.items[sibling]) < row.indexOfChild(
        window.scene_workspace.items[middle]
    )
