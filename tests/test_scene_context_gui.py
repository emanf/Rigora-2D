"""Actual scene activation, reference-only Object Editor rendering and grouped unbinding."""

from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from test_roots_soft_drag_gui import drag
from test_roots_soft_drag_gui import editor as editor

from rigora.application_services.appearance import AppearanceService
from rigora.application_services.bindings import BindingService
from rigora.application_services.characters import CharacterService

pytestmark = pytest.mark.gui


def object_shape(editor, name, x):
    """Create an ordinary multi-part Object using shared artwork commands."""
    doc = editor.viewmodel.documents
    mesh = AppearanceService(doc).create_shape("rectangle", x, 150, 80, 100)
    part = str(BindingService(doc).mesh(mesh).object_id)
    owner = CharacterService(doc).create_object((part,), name)
    return owner, part


def test_scene_headers_activate_only_one_scene_and_restore_selection_and_view(editor, qtbot):
    """The real Add button and inactive headers switch independent editor state."""
    vm, viewport = editor.viewmodel, editor.viewport
    first = vm.documents.scene.id
    owner, _ = object_shape(editor, "First Object", 100)
    vm.changed.emit()
    qtbot.wait(50)
    editor.scene_workspace.select_entries((owner,))
    viewport.zoom, viewport.offset = 0.8, QPointF(23, 45)
    QTest.mouseClick(editor.add_scene_button, Qt.MouseButton.LeftButton)
    qtbot.wait(50)
    second = vm.documents.scene.id
    assert second != first
    assert len(editor.scene_workspace.scene_items) == 2
    assert editor.scene_workspace.scene_items[first].childCount() == 0
    assert owner not in editor.scene_workspace.items
    other, _ = object_shape(editor, "Second Object", 300)
    vm.changed.emit()
    editor.scene_workspace.select_entries((other,))
    viewport.zoom, viewport.offset = 1.2, QPointF(67, 89)
    item = editor.scene_workspace.scene_items[first]
    QTest.mouseClick(
        editor.tree.viewport(),
        Qt.MouseButton.LeftButton,
        pos=editor.tree.visualItemRect(item).center(),
    )
    qtbot.wait(30)
    assert vm.documents.scene.id == first and vm.playback.session.scene.id == first
    assert vm.scene.selected == (owner,)
    assert viewport.zoom == 0.8 and viewport.offset == QPointF(23, 45)
    assert editor.scene_workspace.scene_items[second].childCount() == 0
    editor.scene_workspace.activate_scene(second)
    assert vm.scene.selected == (other,)
    assert viewport.zoom == 1.2 and viewport.offset == QPointF(67, 89)
    editor.scene_workspace.remove_scene(second)
    assert vm.documents.scene.id == first and len(editor.scene_workspace.scene_items) == 1
    vm.undo()
    assert len(editor.scene_workspace.scene_items) == 2


def test_scene_context_draws_other_objects_but_never_selects_or_moves_them(editor, qtbot):
    """The toolbar toggle changes pixels while every editing route retains isolation."""
    vm, viewport = editor.viewmodel, editor.viewport
    owner, part = object_shape(editor, "Editing", 100)
    other, other_part = object_shape(editor, "Reference", 320)
    vm.changed.emit()
    editor.object_edit.enter(owner)
    qtbot.wait(50)
    viewport.zoom, viewport.offset = 1, QPointF(20, 20)
    action = editor.command_actions["scene_context"]
    assert action.isVisible() and not action.isChecked()
    without = viewport.grab().toImage()
    action.trigger()
    assert viewport.reference_pose.nodes[other_part].visible
    assert not viewport.reference_pose.nodes[part].visible
    assert other_part not in viewport.pose.nodes or not viewport.pose.nodes[other_part].visible
    with_context = viewport.grab().toImage()
    assert with_context != without
    point = viewport.offset + QPointF(350, 180) * viewport.zoom
    assert editor.scene_workspace.pick(point) == ""
    before = vm.documents.project
    drag(viewport, point, point + QPointF(12, 8))
    assert vm.documents.project is before
    assert other not in vm.scene.selected and other_part not in vm.scene.selected
    output = Path("build/scenes-bindings-review")
    output.mkdir(parents=True, exist_ok=True)
    viewport.grab().save(str(output / "scene-context.png"))
    action.trigger()
    assert viewport.reference_pose is None and editor.object_edit._reference_pose is None
    editor.object_edit.exit()
    assert not action.isVisible()


def test_selecting_a_binding_folder_unbinds_connections_inside_the_object(editor, qtbot):
    """Group selection releases all its links in one Undo without extracting any artwork."""
    vm = editor.viewmodel
    owner, first = object_shape(editor, "Object", 100)
    mesh = AppearanceService(vm.documents).create_shape("ellipse", 210, 150, 80, 80)
    service = BindingService(vm.documents)
    second = str(service.mesh(mesh).object_id)
    service.move_entries((second,), owner)
    service.bind((first,), second)
    vm.changed.emit()
    editor.object_edit.enter(owner)
    editor.command_actions["bindings"].trigger()
    dialog = editor.bindings_dialog
    assert dialog.tree.topLevelItemCount() == 1
    folder = dialog.tree.topLevelItem(0)
    assert folder.childCount() == 1 and folder.isExpanded()
    dialog.hide()
    qtbot.wait(30)
    viewport = editor.viewport
    viewport.zoom, viewport.offset = 1, QPointF(20, 20)
    editor.scene_workspace.select_entries((first,))
    pose = vm.documents.animation.pose
    positions = {k: pose.nodes[k].world_matrix[4:] for k in (first, second)}
    screen = viewport.offset + QPointF(positions[first][0] + 25, positions[first][1] + 30)
    assert editor.scene_workspace.pick(screen) == first
    before_drag = vm.documents.project
    drag(viewport, screen, screen + QPointF(28, 17))
    assert not vm.scene.error
    for key, (x, y) in positions.items():
        assert vm.documents.animation.pose.nodes[key].world_matrix[4:] == pytest.approx(
            (x + 28, y + 17)
        )
    vm.undo()
    assert vm.documents.project == before_drag
    dialog.show()
    dialog.refresh(force=True)
    folder = dialog.tree.topLevelItem(0)
    folder.setSelected(True)
    before = vm.documents.project
    QTest.mouseClick(dialog.remove_button, Qt.MouseButton.LeftButton)
    assert not dialog.status.text() and not service.relationships()
    assert editor.object_edit.active and editor.object_edit.key == owner
    assert {CharacterService(vm.documents).object_root(k).id for k in (first, second)} == {owner}
    vm.undo()
    assert vm.documents.project == before
    dialog.close()
