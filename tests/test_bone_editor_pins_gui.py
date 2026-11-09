"""Bone Editor pins target painted parts independently of bone selection filters."""

from dataclasses import replace

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from test_roots_soft_drag_gui import editor as editor

from rigora.application_services.appearance import AppearanceService
from rigora.application_services.character_creation import CharacterCreationService, build_character
from rigora.application_services.image_rigging import ImageRigService
from rigora.application_services.rigging import RigService
from rigora.domain.character_recipe import CharacterRecipe
from rigora.domain.geometry import transform_point

pytestmark = pytest.mark.gui


def test_pin_without_artwork_explains_requirement_without_arming_empty_tool(editor):
    """Bare rigs receive useful feedback instead of an active tool that ignores every click."""
    vm = editor.viewmodel
    root = RigService(vm.documents).create_bone((100, 100), (200, 100))
    vm.changed.emit()
    vm.rig.select(root)
    editor.show_bone_editor()
    dialog = editor.bone_editor
    before = vm.documents.project
    dialog.bone_buttons["Add pin"].click()
    assert not vm.mesh.active
    assert not dialog.bone_buttons["Add pin"].isChecked()
    assert "Pins anchor artwork" in dialog.status.text()
    assert vm.documents.project == before


@pytest.mark.parametrize("select_bone", (False, True))
def test_pin_click_targets_artwork_under_bones_and_preserves_other_parts(
    editor, qtbot, select_bone
):
    """Click another part with bones-only selection, then release and undo real anchors."""
    vm, viewport = editor.viewmodel, editor.viewport
    shapes = AppearanceService(vm.documents)
    first = shapes.create_shape("rectangle", 100, 100, 120, 160)
    second = shapes.create_shape("rectangle", 300, 100, 120, 160)
    images = ImageRigService(vm.documents)
    actor = images.convert((first, second), "Pinned character")
    rig = RigService(vm.documents)
    root = rig.create_bone((120, 180), (180, 180), skeleton_id=images.scene.skeletons[0].id)
    child = rig.create_bone((180, 180), (400, 180), root)
    for key in (first, second):
        images.bind_image(key, root)
    vm.changed.emit()
    editor.object_edit.enter(actor)
    qtbot.waitUntil(lambda: not editor.mesh_workspace.jobs, timeout=10000)
    vm.rig.select(root if select_bone else "")
    vm.mesh.select_mesh(first)
    editor.show_bone_editor()
    dialog = editor.bone_editor
    vm.scene.selection_types = {"bones"}
    viewport.zoom, viewport.offset = 1, QPointF(10, 10)
    dialog.bone_buttons["Add pin"].click()
    before, steps = vm.documents.project, len(vm.documents.history.undo_stack)
    point = QPointF(360, 180) * viewport.zoom + viewport.offset
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=point.toPoint())
    assert not vm.mesh.error, dialog.status.text()
    assert vm.mesh.mesh_id == second
    assert not images.mesh(first).extra.get("area_pins")
    pins = images.mesh(second).extra["area_pins"]
    assert len(pins) == 1
    if select_bone:
        assert pins[0]["bone_id"] == root
    else:
        assert pins[0]["target_kind"] == "object"
    assert len(vm.documents.history.undo_stack) == steps + 1
    anchor = pins[0]["vertex_id"]
    index = next(i for i, v in enumerate(images.mesh(second).vertices) if v.id == anchor)
    pose = vm.documents.animation.pose
    position = transform_point(
        pose.nodes[images.mesh(second).object_id].world_matrix,
        *pose.meshes[second].positions[index],
    )
    assert position == pytest.approx((360, 180))
    rig.update(child, transform=replace(rig.bone(child).transform, rotation=35))
    pose = vm.documents.animation.pose
    assert transform_point(
        pose.nodes[images.mesh(second).object_id].world_matrix,
        *pose.meshes[second].positions[index],
    ) == pytest.approx(position)
    vm.undo()
    dialog.bone_buttons["Release pin"].click()
    assert not images.mesh(second).extra["area_pins"]
    vm.undo()
    assert images.mesh(second).extra["area_pins"]
    vm.undo()
    assert vm.documents.project == before
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=(point + QPointF(0, 150)).toPoint())
    assert "Click visible, unlocked artwork" in dialog.status.text()
    assert vm.documents.project == before


def test_creator_character_accepts_pin_on_clicked_part(editor, qtbot):
    """The creator's placed and linked multi-part artwork uses the same pointer pin tool."""
    vm, viewport = editor.viewmodel, editor.viewport
    root = CharacterCreationService(vm.documents).create(
        build_character(CharacterRecipe(motions=("Stand",)))
    )
    vm.changed.emit()
    editor.object_edit.enter(root)
    qtbot.waitUntil(lambda: not editor.mesh_workspace.jobs, timeout=15000)
    editor.show_bone_editor()
    dialog = editor.bone_editor
    viewport.fit_canvas()
    dialog.bone_buttons["Add pin"].click()
    images = ImageRigService(vm.documents)
    bound = {d.owner_id for d in images.scene.deformers if d.kind == "skinning"}
    target = None
    for mesh in reversed(images.scene.meshes):
        if mesh.id not in bound or mesh.id == vm.mesh.mesh_id:
            continue
        evaluated = viewport.pose.meshes.get(mesh.id)
        if evaluated is None:
            continue
        positions = dict(zip((v.id for v in mesh.vertices), evaluated.positions, strict=True))
        for face in mesh.triangles:
            local = tuple(sum(positions[k][axis] for k in face) / 3 for axis in (0, 1))
            world = transform_point(viewport.pose.nodes[mesh.object_id].world_matrix, *local)
            screen = viewport.offset + QPointF(*world) * viewport.zoom
            if (
                viewport.rect().contains(screen.toPoint())
                and editor.scene_workspace.mesh_at(QPointF(screen.toPoint())) == mesh.id
            ):
                target = mesh.id, screen.toPoint()
                break
        if target:
            break
    assert target is not None, "The created character needs visible bound artwork."
    before, steps = vm.documents.project, len(vm.documents.history.undo_stack)
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=target[1])
    assert not vm.mesh.error, dialog.status.text()
    assert len(images.mesh(target[0]).extra["area_pins"]) == 1
    assert len(vm.documents.history.undo_stack) == steps + 1
    assert viewport.grab().save("build/bone-editor-pin-character.png")
    vm.undo()
    assert vm.documents.project == before
