"""Template placement produces whole movable objects and scene captions support renaming."""

import pytest
from PySide6.QtCore import QEvent, QMimeData, QPointF, Qt, QTimer
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QKeyEvent
from PySide6.QtWidgets import QApplication, QLineEdit, QMenu
from test_roots_soft_drag_gui import drag
from test_roots_soft_drag_gui import editor as editor

from rigora.application_services.appearance import AppearanceService
from rigora.application_services.characters import CharacterService
from rigora.domain.geometry import transform_point

pytestmark = pytest.mark.gui


@pytest.mark.parametrize("destination", ("empty_scene", "miss", "empty_object", "artwork"))
def test_dropped_landmarks_become_one_selectable_movable_object(editor, qtbot, destination):
    """Real template drops preserve target artwork and keep whole-object movement undoable."""
    vm, viewport = editor.viewmodel, editor.viewport
    characters = CharacterService(vm.documents)
    target = ""
    artwork = ""
    if destination in ("miss", "empty_object"):
        target = characters.create_object(name="Existing object")
        characters.set_transform(target, x=150, y=160)
    elif destination == "artwork":
        artwork = AppearanceService(vm.documents).create_shape("rectangle", 100, 100, 160, 180)
        target = str(characters.mesh(artwork).object_id)
    vm.changed.emit()
    if target:
        editor.scene_workspace.select_entries((target,))
    qtbot.wait(30)
    viewport.zoom, viewport.offset = 1, QPointF(20, 20)
    baseline, count = vm.documents.project, len(vm.documents.history.undo_stack)
    old_art = vm.documents.animation.pose.meshes.get(artwork)
    old_points = (
        tuple(
            transform_point(vm.documents.animation.pose.nodes[old_art.object_id].world_matrix, *p)
            for p in old_art.positions
        )
        if old_art
        else ()
    )
    entry = next(e for e in vm.content.entries if e.item.name == "Human · full body")
    mime = QMimeData()
    mime.setData("application/x-rigora-content", entry.key.encode())
    point = QPointF(150, 160) if destination in ("empty_object", "artwork") else QPointF(460, 270)
    screen = viewport.offset + point
    for event in (
        QDragEnterEvent(
            screen.toPoint(),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
        QDropEvent(
            screen,
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    ):
        QApplication.sendEvent(viewport, event)
        assert event.isAccepted()
    qtbot.waitUntil(lambda: bool(characters.scene.skeletons) and not vm.content.busy, timeout=15000)
    assert not vm.content.error
    assert not editor.object_edit.active and not vm.rig.active
    rig = characters.scene.skeletons[0]
    owner = characters.object_root(rig.id)
    assert owner is not None and owner.extra.get("object_container")
    assert owner.id in editor.scene_workspace.items
    assert len(characters.scene_objects()) == (2 if destination == "miss" else 1)
    if destination in ("empty_object", "artwork"):
        assert owner.id == target
    else:
        assert owner.id != target
    assert vm.scene.selected == (owner.id,)
    assert len(vm.documents.history.undo_stack) == count + 1
    if artwork:
        mesh = vm.documents.animation.pose.meshes[artwork]
        for p, original_point in zip(mesh.positions, old_points, strict=True):
            assert transform_point(
                vm.documents.animation.pose.nodes[mesh.object_id].world_matrix, *p
            ) == pytest.approx(original_point)
    before = vm.documents.animation.pose
    bone = max(rig.bones, key=lambda b: b.length)
    body = viewport.offset + QPointF(
        *transform_point(before.nodes[bone.id].world_matrix, bone.length * 0.37, 0)
    )
    if destination in ("empty_scene", "miss", "empty_object"):
        assert editor.scene_workspace.pick(body) == owner.id
        drag(viewport, body, body + QPointF(32, 24))
    else:
        vm.scene.begin_preview()
        vm.scene.preview_transform(dx=32, dy=24)
        vm.scene.finish_preview()
    assert not vm.scene.error
    after = vm.documents.animation.pose
    for b in rig.bones:
        assert after.nodes[b.id].world_matrix[4:] == pytest.approx(
            (before.nodes[b.id].world_matrix[4] + 32, before.nodes[b.id].world_matrix[5] + 24)
        )
    assert len(vm.documents.history.undo_stack) == count + 2
    vm.undo()
    vm.undo()
    assert vm.documents.project == baseline


def test_scene_caption_context_menu_renames_with_undo(editor, qtbot):
    """Rename Scene invokes the real inline editor and preserves scene identity and settings."""
    tree = editor.tree
    scene = editor.viewmodel.documents.project.scenes[0]
    row = tree.topLevelItem(0)
    actions = []

    def choose():
        """Close the offscreen native menu before starting its inline editor."""
        menu = QApplication.activePopupWidget()
        assert isinstance(menu, QMenu)
        actions.append(next(a for a in menu.actions() if a.text() == "Rename scene"))
        menu.close()

    QTimer.singleShot(0, choose)
    editor.scene_workspace.context_menu(tree.visualItemRect(row).center())
    count = len(editor.viewmodel.documents.history.undo_stack)
    actions[0].trigger()
    field = next(w for w in tree.findChildren(QLineEdit) if w.isVisible())
    field.setText("Animation room")
    QApplication.sendEvent(
        field, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
    )
    qtbot.waitUntil(lambda: editor.viewmodel.documents.project.scenes[0].name == "Animation room")
    renamed = editor.viewmodel.documents.project.scenes[0]
    assert renamed.id == scene.id and renamed.settings == scene.settings
    assert len(editor.viewmodel.documents.history.undo_stack) == count + 1
    editor.viewmodel.undo()
    assert editor.viewmodel.documents.project.scenes[0] == scene
