"""Offscreen checks of the actual Bind/Unbind actions and modeless relationship inspector."""

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from test_roots_soft_drag_gui import editor as editor

from rigora.application_services.appearance import AppearanceService
from rigora.application_services.bindings import BindingService
from rigora.application_services.dynamics import DynamicsService
from rigora.application_services.image_rigging import ImageRigService
from rigora.application_services.rigging import RigService

pytestmark = pytest.mark.gui


def make_character(editor):
    """Use real shapes and automatic bone drawing, with the actual Object Editor context."""
    vm = editor.viewmodel
    shapes = AppearanceService(vm.documents)
    first = shapes.create_shape("rectangle", 100, 100, 100, 150)
    second = shapes.create_shape("ellipse", 200, 150, 100, 100)
    images = ImageRigService(vm.documents)
    actor = images.convert((first, second), "Binding test")
    root = images.draw_bone(first, (120, 130), (180, 130))
    child = images.draw_bone(first, (180, 130), (240, 150), root)
    vm.changed.emit()
    editor.object_edit.enter(actor)
    return images, actor, first, second, root, child


def test_toolbar_unbind_keeps_bones_visible_and_cleans_springs(editor, qtbot):
    """The reported draw/unbind path preserves hierarchy rows, isolation and undo."""
    images, actor, first, _, root, child = make_character(editor)
    vm = editor.viewmodel
    DynamicsService(vm.documents).configure((root, child), group="Hair")
    vm.changed.emit()
    editor.character_panel.show_page("bones")
    editor.scene_workspace.select_entries((str(images.mesh(first).object_id),))
    before, count = vm.documents.project, len(vm.documents.history.undo_stack)
    editor.command_actions["unbind_parts"].trigger()
    assert not vm.scene.error
    assert len(vm.documents.history.undo_stack) == count + 1
    assert not any(d.kind == "skinning" and d.owner_id == first for d in images.scene.deformers)
    assert actor == editor.object_edit.key
    assert {root, child} <= editor.object_edit.ids
    for key in (root, child):
        assert key in editor.scene_workspace.items
        assert not editor.scene_workspace.items[key].isHidden()
    vm.undo()
    assert vm.documents.project == before
    editor.scene_workspace.select_entries((child,))
    editor.command_actions["unbind_parts"].trigger()
    assert not vm.scene.error
    master = next(b for b in images.scene.skeletons[0].bones if b.extra.get("rig_root"))
    assert RigService(vm.documents).bone(child).parent_id == master.id
    assert not any(c.kind == "spring" and c.owner_id == child for c in images.scene.constraints)
    assert any(c.kind == "spring" and c.owner_id == root for c in images.scene.constraints)
    qtbot.wait(30)


def test_bind_window_links_shapes_filters_rows_and_removes_only_selected_connection(editor, qtbot):
    """A real UI-created shape link moves with its target; selected-row release is undoable."""
    images, _, first, second, _, _ = make_character(editor)
    vm = editor.viewmodel
    source, target = str(images.mesh(first).object_id), str(images.mesh(second).object_id)
    editor.scene_workspace.select_entries((source,))
    editor.command_actions["bind_parts"].trigger()
    dialog = editor.bindings_dialog
    assert dialog.isVisible() and dialog.sources == (source,)
    dialog.target.setCurrentIndex(dialog.target.findData(target))
    QTest.mouseClick(dialog.bind_button, Qt.MouseButton.LeftButton)
    assert not dialog.status.text()
    service = BindingService(vm.documents)
    rule = next(c for c in service.scene.constraints if c.owner_id == source)
    assert rule.kind == "parent" and rule.target_id == target
    dialog.search.setText("Parent")
    matches = []
    for i in range(dialog.tree.topLevelItemCount()):
        folder = dialog.tree.topLevelItem(i)
        assert folder.childCount() > 0
        assert folder.isHidden() == all(
            folder.child(j).isHidden() for j in range(folder.childCount())
        )
        for j in range(folder.childCount()):
            item = folder.child(j)
            assert item.isHidden() == (item.text(1) != "Parent")
            if item.data(0, Qt.ItemDataRole.UserRole) == f"constraint:{rule.id}":
                matches.append(item)
    assert len(matches) == 1
    matches[0].setSelected(True)
    before, count = vm.documents.project, len(vm.documents.history.undo_stack)
    QTest.mouseClick(dialog.remove_button, Qt.MouseButton.LeftButton)
    assert not dialog.status.text()
    assert not any(c.id == rule.id for c in service.scene.constraints)
    assert len(vm.documents.history.undo_stack) == count + 1
    vm.undo()
    assert vm.documents.project == before
    assert dialog.search.text() == "Parent"
    dialog.search.clear()
    qtbot.wait(20)
    output = Path("build/bindings-review")
    output.mkdir(parents=True, exist_ok=True)
    dialog.grab().save(str(output / "bindings.png"))
    dialog.close()


def test_bone_binding_window_uses_explicit_target_and_global_auto_bind_switch(editor):
    """Bone-to-bone parenting and drawing policy are available without hidden dropdown state."""
    _, _, _, _, root, child = make_character(editor)
    vm = editor.viewmodel
    service = BindingService(vm.documents)
    service.unbind((child,))
    vm.changed.emit()
    editor.scene_workspace.select_entries((child,))
    editor.command_actions["bindings"].trigger()
    dialog = editor.bindings_dialog
    dialog.source.setCurrentIndex(dialog.source.findData(child))
    dialog.target.setCurrentIndex(dialog.target.findData(root))
    QTest.mouseClick(dialog.bind_button, Qt.MouseButton.LeftButton)
    assert not dialog.status.text()
    assert RigService(vm.documents).bone(child).parent_id == root
    dialog.auto_bind.setFocus()
    QTest.keyClick(dialog.auto_bind, Qt.Key.Key_Space)
    assert not vm.rig.auto_bind_artwork
    dialog.close()
