"""External drag destinations and thumbnail file browsing through real Qt widgets."""

from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDrag, QDropEvent, QFontDatabase
from PySide6.QtTest import QTest
from test_workspace_redesign_gui import editor as editor

from rigora.application_services.scene_editing import SceneEditingService
from rigora.domain.geometry import transform_point

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def readable_offscreen_font(qapp):
    """Load the OS text font because Qt offscreen does not enumerate Windows fonts."""
    font = Path("C:/Windows/Fonts/segoeui.ttf")
    if font.is_file() and "Segoe UI" not in QFontDatabase.families():
        QFontDatabase.addApplicationFont(str(font))


def file_drop(widget, files, point):
    """Deliver the same local URL contract as an Explorer drop."""
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in files])
    event = QDropEvent(
        point,
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.dropEvent(event)
    assert event.isAccepted()


def test_external_drop_assets_stage_and_folder(editor, qtbot, tmp_path):
    """Each destination imports sources, placing instances only when requested."""
    window, vm = editor, editor.viewmodel
    files = []
    for name in ("one.svg", "two.svg", "three.svg"):
        path = tmp_path / name
        path.write_bytes(Path("assets/examples/prop.svg").read_bytes())
        files.append(path)
    file_drop(window.project_assets, files[:1], QPointF(20, 20))
    qtbot.waitUntil(lambda: not vm.media.busy, timeout=15000)
    assert not vm.media.error
    assert len(vm.documents.project.assets) == 1
    assert not vm.documents.project.scenes[0].objects
    before = vm.documents.project
    point = QPointF(300, 250)
    expected = QPointF(
        vm.documents.project.scenes[0].settings.width / 2,
        vm.documents.project.scenes[0].settings.height / 2,
    )
    file_drop(window.viewport, files[1:2], point)
    qtbot.waitUntil(lambda: not vm.media.busy, timeout=15000)
    assert not vm.media.error
    scene = vm.documents.project.scenes[0]
    assert len(scene.objects) == 1
    from rigora.domain.geometry import transform_point

    pose = vm.documents.animation.pose
    mesh = scene.meshes[0]
    points = [
        transform_point(pose.nodes[mesh.object_id].world_matrix, *p)
        for p in pose.meshes[mesh.id].positions
    ]
    assert (
        (min(p[0] for p in points) + max(p[0] for p in points)) / 2,
        (min(p[1] for p in points) + max(p[1] for p in points)) / 2,
    ) == pytest.approx((expected.x(), expected.y()))
    vm.documents.undo()
    assert vm.documents.project == before
    vm.documents.redo()
    folder = SceneEditingService(vm.documents).group(name="Costume")
    vm.changed.emit()
    tree = window.tree
    item = window.scene_workspace.items[folder]
    tree.scrollToItem(item)
    qtbot.wait(50)
    point = QPointF(tree.visualItemRect(item).center())
    file_drop(tree, files[2:], point)
    qtbot.waitUntil(lambda: not vm.media.busy, timeout=15000)
    assert not vm.media.error
    scene = vm.documents.project.scenes[0]
    added = next(o for o in scene.objects if o.parent_id == folder)
    assert added.id in vm.documents.animation.pose.nodes
    assert (
        window.scene_workspace.items[added.id].parent().data(0, Qt.ItemDataRole.UserRole) == folder
    )
    assert len(scene.objects) == 2


def test_internal_folder_move_keeps_rows_geometry_and_undo(editor, qtbot, monkeypatch):
    """Native drag completion cannot remove rows rebuilt by the canonical scene command."""
    from rigora.application_services.meshes import MeshService

    window, vm = editor, editor.viewmodel
    mesh_service = MeshService(vm.documents)
    source = mesh_service.register_image_bytes(
        "prop.svg", Path("assets/examples/prop.svg").read_bytes()
    )
    mesh_id = mesh_service.instantiate_asset(source)
    key = mesh_service.mesh(mesh_id).object_id
    service = SceneEditingService(vm.documents)
    folder = service.group(name="Folder")
    service.transform((folder,), dx=70, dy=35)
    vm.changed.emit()
    baseline = vm.documents.project
    geometry = vm.documents.animation.pose.meshes[mesh_id].positions
    tree = window.tree
    tree.clearSelection()
    window.scene_workspace.items[key].setSelected(True)

    def drag_completed(self, *args):
        window.scene_workspace.move_entries((key,), folder, None)
        return Qt.DropAction.MoveAction

    monkeypatch.setattr(QDrag, "exec", drag_completed)
    tree.startDrag(Qt.DropAction.MoveAction)
    assert window.scene_workspace.items[key].parent() is window.scene_workspace.items[folder]
    assert vm.documents.animation.pose.meshes[mesh_id].positions == geometry
    assert service.record(key).parent_id == folder
    vm.documents.undo()
    assert vm.documents.project == baseline


def test_modeless_composer_editors_pin_and_live_skinned_springs(editor, qtbot):
    """Moving a bound character produces transient follow-through on its real artwork mesh."""
    window, vm = editor, editor.viewmodel
    vm.documents.open(Path("examples/image-import-example.rigora"))
    vm.changed.emit()
    scene = vm.documents.project.scenes[0]
    root, child = scene.skeletons[0].bones
    mesh = scene.meshes[0]
    qtbot.waitUntil(lambda: mesh.asset_id in window.viewport.artwork.images, timeout=10000)
    vm.rig.select(child.id)
    window.show_bone_editor()
    assert vm.rig.selected == (child.id,)
    bone_editor = window.bone_editor
    qtbot.addWidget(bone_editor)
    bone_editor.add_pin()
    assert vm.mesh.tool == "area_pin"
    point = transform_point(
        window.viewport.pose.nodes[mesh.object_id].world_matrix,
        mesh.extra["image_width"] / 2,
        mesh.extra["image_height"] / 2,
    )
    screen = QPointF(*point) * window.viewport.zoom + window.viewport.offset
    QTest.mouseClick(window.viewport, Qt.MouseButton.LeftButton, pos=screen.toPoint())
    assert not vm.mesh.error
    pins = vm.documents.project.scenes[0].meshes[0].extra["area_pins"]
    assert len(pins) == 1 and pins[0]["bone_id"] == child.id
    bone_editor.release_pin()
    window.show_spring_editor()
    spring_editor = window.spring_editor
    qtbot.addWidget(spring_editor)
    spring_editor.preset("Rubbery")
    spring_editor.assign()
    assert not vm.animation_editor.error
    window.set_composer_target("part")
    vm.scene.select((mesh.object_id,))
    baseline = vm.documents.project
    steps = len(vm.documents.history.undo_stack)
    workspace = window.rig_workspace
    workspace.begin_springs()
    vm.scene.begin_preview()
    vm.scene.preview_transform(dx=100, dy=30)
    assert not vm.scene.error
    preview = vm.scene.preview
    workspace.spring_clock -= 1 / 60
    workspace.tick_springs()
    assert window.viewport.pose.meshes[mesh.id].positions != preview.meshes[mesh.id].positions
    assert vm.documents.project is baseline
    assert len(vm.documents.history.undo_stack) == steps
    window.grab().save(
        "C:/Users/eManF/Documents/Codex/2026-10-18/yo/outputs/Rigora-composer-workspace.png"
    )
    spring_editor.grab().save(
        "C:/Users/eManF/Documents/Codex/2026-10-18/yo/outputs/Rigora-spring-editor.png"
    )
    workspace.spring_timer.stop()
    vm.scene.cancel_preview()
    spring_editor.close()
    bone_editor.close()
