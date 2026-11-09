"""Complete pointer selection, editable vertex transforms and centered source drop feedback."""

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from test_workspace_redesign_gui import editor as editor

from rigora.application_services.meshes import MeshService
from rigora.application_services.rigging import RigService
from rigora.application_services.skinning import SkinService
from rigora.domain.geometry import transform_point

pytestmark = pytest.mark.gui


def setup_art(editor):
    """Create a source, independent image and two bones in a view with ample empty margins."""
    vm = editor.viewmodel
    service = MeshService(vm.documents)
    source = service.register_image_bytes("prop.svg", Path("assets/examples/prop.svg").read_bytes())
    mesh_id = service.instantiate_asset(source)
    root = RigService(vm.documents).create_bone((100, 100), (190, 100))
    child = RigService(vm.documents).create_bone((190, 100), (250, 120), root)
    SkinService(vm.documents).bind(mesh_id, (root, child))
    vm.changed.emit()
    editor.viewport.zoom, editor.viewport.offset = 0.3, QPointF(30, 30)
    return source, mesh_id, root, child


def marquee(window):
    """Drag across the entire visible preview through actual widget mouse events."""
    viewport = window.viewport
    start, end = QPoint(4, 4), QPoint(viewport.width() - 4, viewport.height() - 4)
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(viewport, end)
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=end)


def test_marquee_selects_mixed_types_and_checkbox_filters(editor, qtbot):
    source, mesh_id, root, child = setup_art(editor)
    vm = editor.viewmodel
    owner = vm.mesh.service.mesh(mesh_id).object_id
    master = next(b.id for b in vm.documents.scene.skeletons[0].bones if b.extra.get("rig_root"))
    editor.rig_workspace.set_mode(True)
    vm.rig.set_tool("select")
    marquee(editor)
    assert {owner, root, child} <= set(vm.scene.selected)
    assert set(vm.rig.selected) == {master, root, child}
    editor.rig_workspace.set_mode(True)
    vm.rig.set_tool("draw")
    editor.selection_filters["images"].setChecked(False)
    assert not vm.rig.active
    editor.selection_filters["images"].setChecked(True)
    editor.selection_filters["bones"].setChecked(False)
    marquee(editor)
    assert vm.scene.selected == (owner,)
    assert not vm.rig.selected
    before = vm.documents.project
    bones_before = before.scenes[0].skeletons
    pose_before = vm.documents.animation.pose
    world_before = transform_point(
        pose_before.nodes[owner].world_matrix, *pose_before.meshes[mesh_id].positions[0]
    )
    vm.scene.begin_preview()
    vm.scene.preview_transform(dx=20)
    vm.scene.finish_preview()
    assert vm.documents.project.scenes[0].skeletons == bones_before
    pose_after = vm.documents.animation.pose
    world_after = transform_point(
        pose_after.nodes[owner].world_matrix, *pose_after.meshes[mesh_id].positions[0]
    )
    assert world_after == pytest.approx((world_before[0] + 20, world_before[1]))
    vm.undo()
    editor.selection_filters["images"].setChecked(False)
    editor.selection_filters["bones"].setChecked(True)
    marquee(editor)
    assert set(vm.scene.selected) == {master, root, child}
    vm.scene.select((root, child))
    QTest.keyClick(editor.viewport, Qt.Key.Key_Delete)
    assert [b.id for b in vm.documents.scene.skeletons[0].bones] == [master]
    assert vm.documents.project.scenes[0].objects
    vm.undo()
    assert len(vm.documents.project.scenes[0].skeletons[0].bones) == 3


def test_vertex_resize_handles_change_selected_geometry_once_and_undo(editor, qtbot):
    source, mesh_id, root, child = setup_art(editor)
    vm = editor.viewmodel
    vm.mesh.select_mesh(mesh_id)
    editor.mesh_workspace.activate_tool("vertex")
    mesh = vm.mesh.mesh
    vm.mesh.select(tuple(v.id for v in mesh.vertices))
    baseline = vm.documents.project
    original = vm.mesh.pose.meshes[mesh_id].positions
    steps = len(vm.documents.history.undo_stack)
    editor.command_actions["scale"].trigger()
    assert vm.mesh.active and vm.mesh.tool == "vertex" and vm.mesh.transform_mode == "scale"
    interaction = editor.mesh_workspace.interaction
    frame = interaction.vertex_box()
    start = frame[1][4][0].toPoint()
    QTest.mousePress(editor.viewport, Qt.MouseButton.LeftButton, pos=start)
    assert interaction.scale is not None
    QTest.mouseMove(editor.viewport, start + QPoint(24, 18))
    assert vm.documents.project is baseline
    assert vm.mesh.pose.meshes[mesh_id].positions != original
    QTest.mouseRelease(editor.viewport, Qt.MouseButton.LeftButton, pos=start + QPoint(24, 18))
    assert not vm.mesh.error
    assert len(vm.documents.history.undo_stack) == steps + 1
    vm.undo()
    assert vm.documents.project == baseline
    assert vm.mesh.pose.meshes[mesh_id].positions == original


def test_asset_hover_matches_centered_drop_and_does_not_dirty_source(editor, qtbot):
    source, mesh_id, root, child = setup_art(editor)
    vm = editor.viewmodel
    qtbot.waitUntil(lambda: not editor.mesh_workspace.jobs, timeout=10000)
    before = vm.documents.project
    steps = len(vm.documents.history.undo_stack)
    editor.preview_project_asset(source, vm.documents.session_id)
    ghost = editor.viewport.drop_pose
    assert ghost is not None and len(ghost.meshes) == 1
    assert vm.documents.project is before
    assert len(vm.documents.history.undo_stack) == steps
    ghost_mesh = next(iter(ghost.meshes.values()))
    points = tuple(
        transform_point(ghost.nodes[ghost_mesh.object_id].world_matrix, *p)
        for p in ghost_mesh.positions
    )
    existing = vm.documents.animation.pose
    original = existing.meshes[mesh_id]
    original_points = tuple(
        transform_point(existing.nodes[owner].world_matrix, *p)
        for owner in (original.object_id,)
        for p in original.positions
    )
    center = tuple(
        (min(p[i] for p in original_points) + max(p[i] for p in original_points)) / 2
        for i in (0, 1)
    )
    assert (
        (min(p[0] for p in points) + max(p[0] for p in points)) / 2,
        (min(p[1] for p in points) + max(p[1] for p in points)) / 2,
    ) == pytest.approx(center)
    editor.drop_project_asset(source, vm.documents.session_id)
    assert editor.viewport.drop_pose is None
    scene = vm.documents.project.scenes[0]
    new_mesh = scene.meshes[-1]
    pose = vm.documents.animation.pose
    actual = tuple(
        transform_point(pose.nodes[new_mesh.object_id].world_matrix, *p)
        for p in pose.meshes[new_mesh.id].positions
    )
    assert actual == points
    assert len(vm.documents.history.undo_stack) == steps + 1
    font = Path("C:/Windows/Fonts/segoeui.ttf")
    if font.is_file():
        QFontDatabase.addApplicationFont(str(font))
    editor.grab().save("build/selection-and-drop-workspace.png")
    vm.undo()
    assert vm.documents.project == before


def test_bone_editor_delete_button_handles_pins_and_bound_artwork(editor, qtbot):
    """The actual modeless Delete button works on constrained skinned bones and restores undo."""
    vm = editor.viewmodel
    vm.documents.open(Path("examples/image-import-example.rigora"))
    vm.changed.emit()
    root, child = vm.documents.project.scenes[0].skeletons[0].bones
    editor.scene_workspace.select_entries((child.id,))
    editor.show_bone_editor()
    dialog = editor.bone_editor
    qtbot.addWidget(dialog)
    dialog.bone_buttons["Add pin"].click()
    assert not vm.rig.error
    baseline = vm.documents.project
    button = dialog.bone_buttons["Delete bones"]
    assert button.isEnabled()
    button.click()
    assert not vm.rig.error
    assert child.id not in {b.id for b in vm.documents.project.scenes[0].skeletons[0].bones}
    assert vm.documents.project.scenes[0].meshes
    assert not button.isEnabled()
    vm.undo()
    assert vm.documents.project == baseline
    vm.documents.project.validate_references()
    dialog.close()


def test_scene_folder_drag_shows_full_preview_and_places_at_camera_center(editor, qtbot):
    """Project-source MIME hover/drop uses the same centered geometry inside a Scene folder."""
    from PySide6.QtGui import QDragLeaveEvent, QDragMoveEvent, QDropEvent

    from rigora.application_services.scene_editing import SceneEditingService

    source, mesh_id, root, child = setup_art(editor)
    vm = editor.viewmodel
    qtbot.waitUntil(lambda: not editor.mesh_workspace.jobs, timeout=10000)
    editor.object_edit.exit()
    folder = SceneEditingService(vm.documents).group(name="Costume")
    vm.changed.emit()
    item = next(
        editor.project_assets.item(i)
        for i in range(editor.project_assets.count())
        if editor.project_assets.item(i).data(Qt.ItemDataRole.UserRole) == source
    )
    mime = editor.project_assets.mimeData([item])
    tree = editor.tree
    tree.scrollToItem(editor.scene_workspace.items[folder])
    point = tree.visualItemRect(editor.scene_workspace.items[folder]).center()
    baseline = vm.documents.project
    hover = QDragMoveEvent(
        point,
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    tree.dragMoveEvent(hover)
    assert hover.isAccepted()
    assert editor.viewport.drop_pose is not None
    assert vm.documents.project is baseline
    ghost = editor.viewport.drop_pose
    ghost_mesh = next(iter(ghost.meshes.values()))
    expected = tuple(
        transform_point(ghost.nodes[ghost_mesh.object_id].world_matrix, *p)
        for p in ghost_mesh.positions
    )
    tree.dragLeaveEvent(QDragLeaveEvent())
    assert editor.viewport.drop_pose is None
    tree.dragMoveEvent(hover)
    assert editor.viewport.drop_pose is not None
    drop = QDropEvent(
        QPointF(point),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    tree.dropEvent(drop)
    assert drop.isAccepted() and editor.viewport.drop_pose is None
    scene = vm.documents.project.scenes[0]
    mesh = scene.meshes[-1]
    owner = next(o for o in scene.objects if o.id == mesh.object_id)
    assert owner.parent_id == folder
    pose = vm.documents.animation.pose
    actual = tuple(
        transform_point(pose.nodes[owner.id].world_matrix, *p)
        for p in pose.meshes[mesh.id].positions
    )
    assert actual == expected
    vm.undo()
    assert vm.documents.project == baseline
