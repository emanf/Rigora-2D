"""Delete and Select All in Object Editor retain an empty, reusable owning Object."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from test_roots_soft_drag_gui import editor as editor

from rigora.application_services.appearance import AppearanceService
from rigora.application_services.characters import CharacterService
from rigora.application_services.content_library import ContentService
from rigora.application_services.image_rigging import ImageRigService
from rigora.application_services.scene_editing import SceneEditingService
from rigora.domain.entities import Character, Group

pytestmark = pytest.mark.gui


@pytest.mark.parametrize("kind", ("solid", "group", "character", "template"))
def test_delete_all_contents_keeps_editor_and_empty_owner_with_atomic_undo(
    current_pack, editor, qtbot, kind
):
    """Actual Ctrl+A/Delete retains the owner for shapes, compound art and both rig formats."""
    vm, viewport = editor.viewmodel, editor.viewport
    doc = vm.documents
    service = CharacterService(doc)
    if kind == "template":
        pack, files = current_pack("rigs-effects")
        item = next(i for i in pack.items if i.name == "Human · full body")
        rig = ContentService(doc).place(item, files, position=(300, 200))
        root = service.object_root(rig).id
    else:
        mesh = AppearanceService(doc).create_shape("rectangle", 100, 100, 80, 100)
        part = str(service.mesh(mesh).object_id)
        if kind == "solid":
            root = part
        elif kind == "character":
            images = ImageRigService(doc)
            root = images.convert((mesh,), "Character")
            images.draw_bone(mesh, (120, 130), (170, 130))
        else:
            second = AppearanceService(doc).create_shape("ellipse", 210, 100, 80, 100)
            root = service.create_object((part, str(service.mesh(second).object_id)), "Object")
    folder = service.group((root,), "Scene folder") if kind == "group" else None
    other = service.create_object(name="Keep outside")
    name = service.record(root).name
    vm.changed.emit()
    editor.object_edit.enter(root)
    qtbot.wait(30)
    before, count = doc.project, len(doc.history.undo_stack)
    viewport.setFocus()
    QTest.keyClick(viewport, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    assert vm.scene.selected
    if isinstance(service.record(root), (Group, Character)):
        assert root not in vm.scene.selected
    assert other not in vm.scene.selected and folder not in vm.scene.selected
    QTest.keyClick(viewport, Qt.Key.Key_Delete)
    assert not vm.scene.error
    assert editor.object_edit.active and editor.object_edit.key == root
    assert service.record(root).name == name and other in service.records()
    assert not service.meshes_for((root,))
    assert not service.scene.objects
    assert all(b.extra.get("rig_root") for r in service.scene.skeletons for b in r.bones)
    assert len(doc.history.undo_stack) == count + 1
    emptied = doc.project
    QTest.keyClick(viewport, Qt.Key.Key_Delete)
    assert doc.project is emptied and len(doc.history.undo_stack) == count + 1
    vm.undo()
    assert doc.project == before and editor.object_edit.active
    vm.redo()
    assert doc.project == emptied and editor.object_edit.active
    editor.object_edit.exit()
    assert root in editor.scene_workspace.items
    editor.scene_workspace.select_entries((root,))
    assert editor.scene_workspace.items[root].isSelected()
    editor.scene_workspace.delete_selection()
    assert root not in service.records() and other in service.records()


def test_explicit_container_delete_in_object_context_clears_contents_instead(editor):
    """Tree/menu selection of the owner uses the same protection as keyboard deletion."""
    doc = editor.viewmodel.documents
    characters = CharacterService(doc)
    mesh = AppearanceService(doc).create_shape("rectangle", 100, 100, 80, 100)
    root = characters.create_object((str(characters.mesh(mesh).object_id),), "Object")
    editor.viewmodel.changed.emit()
    editor.object_edit.enter(root)
    before = doc.project
    SceneEditingService(doc).delete_entries((root,))
    editor.viewmodel.changed.emit()
    assert characters.record(root).name == "Object"
    assert not characters.meshes_for((root,)) and editor.object_edit.active
    doc.undo()
    assert doc.project == before
