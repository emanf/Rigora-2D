"""Creator feet remain directly editable while automatic standing contacts stay available."""

from dataclasses import replace

import pytest

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.bone_animation import BoneAnimationService
from rigora.application_services.character_creation import CharacterCreationService, build_character
from rigora.application_services.documents import DocumentService
from rigora.application_services.rigging import RigService
from rigora.domain.character_recipe import character_preset
from rigora.domain.geometry import affine, multiply, transform_point


@pytest.fixture(scope="module", params=("Little", "Ribbon", "Orbit"))
def premade(request):
    """Use complete production creator rigs with their ordinary standing and walking actions."""
    return build_character(character_preset(request.param))


def foot_context(premade):
    """Insert a premade and enter the same action context selected by Object Editor."""
    doc = DocumentService()
    doc.new()
    root = CharacterCreationService(doc).create(premade)
    doc.set_animation_context(root)
    foot = next(b for r in doc.project.scenes[0].skeletons for b in r.bones if b.name == "foot.L")
    return doc, foot


@pytest.mark.parametrize("tool", ("chain_rotate", "selection_move"))
def test_foot_pose_drag_updates_contact_and_visible_artwork(premade, tool, tmp_path):
    """Preview, keyed release and Undo must change the constrained foot, not just its raw keys."""
    doc, foot = foot_context(premade)
    doc.animation.seek(7)
    before, source = doc.animation.pose, doc.project
    count = len(doc.history.undo_stack)
    matrix = before.nodes[foot.id].world_matrix
    other = next(b.id for r in source.scenes[0].skeletons for b in r.bones if b.name == "foot.R")
    x, y = (30, 0) if tool == "chain_rotate" else (matrix[4] + 25, matrix[5] - 16)
    delta = (
        multiply(
            affine(matrix[4], matrix[5], 30, 1, 1, 0, 0),
            affine(-matrix[4], -matrix[5], 0, 1, 1, 0, 0),
        )
        if tool == "chain_rotate"
        else affine(25, -16, 0, 1, 1, 0, 0)
    )
    command, preview = BoneAnimationService(doc).plan_drag(foot.id, tool, x, y, (foot.id,))
    assert doc.project is source
    assert preview.nodes[foot.id].world_matrix == pytest.approx(multiply(delta, matrix))
    assert preview.meshes != before.meshes and not preview.warnings
    assert preview.nodes[other].world_matrix == pytest.approx(before.nodes[other].world_matrix)
    doc.execute(command)
    assert doc.animation.pose.nodes[foot.id].world_matrix == pytest.approx(multiply(delta, matrix))
    assert doc.project.scenes[0].skeletons == source.scenes[0].skeletons
    assert doc.project.scenes[0].constraints == source.scenes[0].constraints
    assert len(doc.history.undo_stack) == count + 1
    root = next(g.id for g in source.scenes[0].groups if g.extra.get("object_container"))
    doc.save(tmp_path / "edited-foot.rigora")
    clone = DocumentService()
    clone.open(tmp_path / "edited-foot.rigora")
    clone.set_animation_context(root)
    assert clone.animation.evaluate(7).nodes[foot.id].world_matrix == pytest.approx(
        multiply(delta, matrix)
    )
    walking = next(c.id for c in source.scenes[0].clips if c.name.startswith("Walk"))
    doc.select_animation_clip(walking)
    original = DocumentService()
    original.project = source
    original.set_animation_context(root)
    original.select_animation_clip(walking)
    assert doc.animation.evaluate(7) == original.animation.evaluate(7)
    doc.undo()
    assert doc.project == source


def test_numeric_foot_pose_and_rest_edit_follow_contacts(premade):
    """Inspector keys and rest authoring both carry automatic contacts in one reversible edit."""
    doc, foot = foot_context(premade)
    before, source = doc.animation.pose, doc.project
    local = before.nodes[foot.id].local
    AnimationEditingService(doc).auto_key_values(
        {(foot.id, "transform.rotation"): local.rotation + 20}, 0
    )
    assert doc.animation.pose.nodes[foot.id].world_matrix != pytest.approx(
        before.nodes[foot.id].world_matrix
    )
    doc.undo()
    assert doc.project == source
    doc.set_animation_context(None)
    before = doc.animation.pose
    RigService(doc).update(
        foot.id, transform=replace(foot.transform, rotation=foot.transform.rotation + 20)
    )
    assert doc.animation.pose.nodes[foot.id].world_matrix != pytest.approx(
        before.nodes[foot.id].world_matrix
    )


def test_foot_rest_drag_without_actions_keeps_preview_in_object_space():
    """An unanimated creator rig previews the same local artwork that release will publish."""
    premade = build_character(replace(character_preset("Little"), motions=()))
    doc, foot = foot_context(premade)
    before, source = doc.animation.pose, doc.project
    count = len(doc.history.undo_stack)
    command, preview = RigService(doc).plan_drag(foot.id, "chain_rotate", 30, 0, (foot.id,))
    assert preview.meshes != before.meshes and doc.project is source
    doc.execute(command)
    assert doc.animation.pose.meshes == preview.meshes
    assert doc.animation.pose.nodes == preview.nodes
    assert len(doc.history.undo_stack) == count + 1
    doc.undo()
    assert doc.project == source


@pytest.mark.gui
@pytest.mark.parametrize("operation", ("part_move", "bone_move", "bone_rotate"))
def test_creator_window_object_editor_foot_pointer_gestures(editor, qtbot, operation):
    """Create through the wizard, enter Object Editor and manipulate the displayed shoe or bone."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent
    from test_character_wizard_gui import creator, select_design
    from test_roots_soft_drag_gui import pointer

    wizard = creator(editor, qtbot)
    select_design(wizard, "Little")
    wizard.create_character()
    qtbot.waitUntil(lambda: not wizard.isVisible() or bool(wizard.model.error), timeout=90000)
    assert not wizard.model.error
    vm, viewport = editor.viewmodel, editor.viewport
    doc = vm.documents
    root = next(g.id for g in doc.project.scenes[0].groups if g.extra.get("object_container"))
    editor.object_edit.enter(root)
    qtbot.waitUntil(
        lambda: {a.id for a in doc.project.assets} <= viewport.artwork.vectors.keys(),
        timeout=15000,
    )
    foot = next(b for r in doc.project.scenes[0].skeletons for b in r.bones if b.name == "foot.L")
    editor.set_composer_target("part" if operation == "part_move" else "bone_only")
    viewport.zoom, viewport.offset = 2, QPointF(-1600, -1250)
    before, source = doc.animation.pose, doc.project
    count = len(doc.history.undo_stack)
    if operation == "part_move":
        feet = {
            b.id
            for r in doc.project.scenes[0].skeletons
            for b in r.bones
            if b.name.startswith("foot.")
        }
        bound = {
            d.owner_id
            for d in doc.project.scenes[0].deformers
            if d.kind == "skinning" and feet.intersection(d.parameters.get("bind_matrices", {}))
        }
        mesh = next(
            m
            for owner in reversed(before.render_order)
            for m in before.meshes.values()
            if m.object_id == owner and m.id in bound and before.nodes[owner].visible
        )
        points = [
            transform_point(before.nodes[mesh.object_id].world_matrix, *p) for p in mesh.positions
        ]
        center = tuple((min(p[i] for p in points) + max(p[i] for p in points)) / 2 for i in (0, 1))
        viewport.offset = (
            QPointF(viewport.width() / 2, viewport.height() / 2) - QPointF(*center) * viewport.zoom
        )
        start = QPointF(*center) * viewport.zoom + viewport.offset
        end = start + QPointF(60, -40)
        # A selected whole-object gizmo has priority over a coincident part;
        # begin this independent part-selection gesture without that overlay.
        vm.scene.select(())
    else:
        vm.rig.select(foot.id)
        editor.bone_mode_buttons[
            "selection_move" if operation == "bone_move" else "chain_move"
        ].click()
        matrix = before.nodes[foot.id].world_matrix
        start = (
            QPointF(
                *transform_point(matrix, foot.length * (0.5 if operation == "bone_move" else 1), 0)
            )
            * viewport.zoom
            + viewport.offset
        )
        end = (
            start + QPointF(50, -35)
            if operation == "bone_move"
            else QPointF(*transform_point(matrix, 0, foot.length)) * viewport.zoom + viewport.offset
        )
    pointer(viewport, QMouseEvent.Type.MouseButtonPress, start)
    if operation == "part_move":
        assert vm.scene.selected == (mesh.object_id,), [
            before.nodes[k].name for k in vm.scene.selected
        ]
    pointer(viewport, QMouseEvent.Type.MouseMove, end)
    preview = vm.scene.preview if operation == "part_move" else vm.rig.pose
    assert preview is not None and preview.meshes != before.meshes
    if operation != "part_move":
        assert vm.rig.selected == (foot.id,)
        assert preview.nodes[foot.id].world_matrix != pytest.approx(
            before.nodes[foot.id].world_matrix
        )
    assert doc.project is source
    pointer(viewport, QMouseEvent.Type.MouseButtonRelease, end)
    assert not vm.scene.error and not vm.rig.error
    assert doc.animation.pose.meshes != before.meshes
    assert len(doc.history.undo_stack) == count + 1
    if operation == "part_move":
        pose = doc.animation.pose
        actual = [
            transform_point(pose.nodes[mesh.object_id].world_matrix, *p)
            for p in pose.meshes[mesh.id].positions
        ]
        for point, old in zip(actual, points, strict=True):
            assert point == pytest.approx((old[0] + 30, old[1] - 20))
    doc.undo()
    vm.changed.emit()
    assert doc.project == source


@pytest.fixture
def editor(qtbot, tmp_path, monkeypatch):
    """Use the isolated real workspace with unrelated shelf thumbnail workers suppressed."""
    from test_roots_soft_drag_gui import editor as existing

    yield from existing.__wrapped__(qtbot, tmp_path, monkeypatch)
