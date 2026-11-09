"""Deterministic follow-through, preserved source clips and volume-preserving cartoon helpers."""

import pytest

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.bone_animation import BoneAnimationService
from rigora.application_services.documents import DocumentService
from rigora.application_services.dynamics import BOUNCES, DynamicsService
from rigora.application_services.rigging import RigService
from rigora.domain.project import ProjectError


def animated_chain():
    """Build an accelerating anchored branch with bounded physical follow-through."""
    doc = DocumentService()
    doc.new()
    rig = RigService(doc)
    root = rig.create_bone((300, 300), (400, 300))
    tip = rig.create_bone((400, 300), (500, 300), root)
    editor = AnimationEditingService(doc)
    editor.key(root, "transform.rotation", 0, 0)
    editor.key(root, "transform.rotation", 12, 70)
    editor.key(root, "transform.rotation", 24, -20)
    editor.clip_settings(out_frame=48)
    DynamicsService(doc).configure((tip,), frequency=2, damping=0.4, gravity=100, inertia=0.8)
    return doc, root, tip


def test_spring_group_names_validate_and_preserve_legacy_rule_identity():
    """Legacy groups remain editable; invalid renames are atomic and generated names are unique."""
    doc, _, tip = animated_chain()
    service = DynamicsService(doc)
    service.configure((tip,), group="Group 1")
    rule = service.scene.constraints[0]
    assert service.group_names() == ("Default", "Group 1")
    assert service.create_group() == "Group 2"
    before = doc.project
    for old, new in (("Default", "Base"), ("Group 1", ""), ("Group 1", "Group 2")):
        with pytest.raises(ProjectError):
            service.rename_group(old, new)
        assert doc.project is before
    steps = len(doc.history.undo_stack)
    service.rename_group("Group 1", "Hair")
    assert len(doc.history.undo_stack) == steps + 1
    assert service.scene.constraints[0].id == rule.id
    assert service.scene.constraints[0].extra["spring_group"] == "Hair"
    doc.undo()
    assert doc.project == before


def test_root_membership_is_anchored_persistent_and_follows_group_commands(tmp_path):
    """Root grouping survives save/rename/removal without creating a simulated root constraint."""
    doc, _, tip = animated_chain()
    service = DynamicsService(doc)
    root = next(b.id for b in service.scene.skeletons[0].bones if b.extra.get("rig_root"))
    root_pose = doc.animation.evaluate(12).nodes[root]
    before, count = doc.project, len(doc.history.undo_stack)
    service.assign_group((root, tip), group="Chain", gravity=900)
    assert service.group_members("Chain") == (root, tip)
    assert all(c.owner_id != root for c in service.scene.constraints)
    assert doc.animation.evaluate(12).nodes[root].world_matrix == root_pose.world_matrix
    assert len(doc.history.undo_stack) == count + 1
    doc.undo()
    assert doc.project == before
    doc.redo()
    service.rename_group("Chain", "Hair")
    assert service.group_members("Hair") == (root, tip) and "Chain" not in service.group_names()
    destination = tmp_path / "anchored-group.rigora"
    doc.save(destination)
    reopened = DocumentService()
    reopened.open(destination)
    assert DynamicsService(reopened).group_members("Hair") == (root, tip)
    service.unassign_group((root,), {"Hair"})
    assert service.group_members("Hair") == (tip,)
    doc.undo()
    assert service.group_members("Hair") == (root, tip)
    service.remove_group("Hair")
    assert not service.group_members("Hair") and "Hair" not in service.group_names()
    doc.undo()
    assert service.group_members("Hair") == (root, tip)
    rig = RigService(doc)
    parent = rig.create_bone((300, 500), (300, 300))
    baseline = doc.project
    with pytest.raises(ProjectError, match="Rig Root"):
        rig.reparent(root, parent)
    assert doc.project is baseline
    assert service.group_members("Hair") == (root, tip)


@pytest.mark.parametrize("translate", [False, True])
def test_dynamics_bake_matches_evaluation_and_preserves_source_undo_save(tmp_path, translate):
    """Fixed integration preserves visible poses, editable channels and original rig constraints."""
    doc, root, tip = animated_chain()
    service = DynamicsService(doc)
    if translate:
        service.configure(
            (tip,),
            frequency=2,
            damping=0.4,
            gravity=100,
            inertia=0.8,
            translate=True,
            stretch=40,
            squash=20,
        )
    before, count, original = doc.project, len(doc.history.undo_stack), service.clip
    reference = {f: doc.animation.evaluate(f) for f in (0, 3, 12, 25, 48)}
    key = service.bake()
    assert key != original.id and len(doc.history.undo_stack) == count + 1
    assert service.scene.skeletons == before.scenes[0].skeletons
    assert service.scene.constraints == before.scenes[0].constraints
    assert not doc.animation.evaluator.springs
    for frame, pose in reference.items():
        assert doc.animation.evaluate(frame).nodes[tip].local == pytest.approx(
            pose.nodes[tip].local, abs=1e-6
        )
        assert doc.animation.evaluate(frame).nodes[root].world_matrix[4:] == pytest.approx(
            (300, 300)
        )
    first = service.timeline.tracks
    doc.undo()
    assert doc.project == before
    service.bake()
    assert [
        (t.owner_id, t.property_path, [(k.frame, k.value) for k in t.keyframes])
        for t in service.timeline.tracks
    ] == [(t.owner_id, t.property_path, [(k.frame, k.value) for k in t.keyframes]) for t in first]
    doc.save(tmp_path / "physics.rigora")
    clone = DocumentService()
    clone.open(tmp_path / "physics.rigora")
    clone.select_animation_clip(service.clip.id)
    assert clone.animation.evaluate(25).nodes == doc.animation.evaluate(25).nodes
    doc.animation.seek(25)
    patch, preview = BoneAnimationService(doc).plan_drag(tip, "rotate", 400, 450)
    assert patch.after and preview.frame == 25 and not doc.animation.evaluator.springs


def test_invalid_spring_and_root_selection_leave_rig_unchanged():
    """Rejected root or out-of-range spring settings never enter the command history."""
    doc, root, tip = animated_chain()
    before = doc.project
    master = next(b.id for b in doc.scene.skeletons[0].bones if b.extra.get("rig_root"))
    with pytest.raises(ProjectError, match="Rig Root"):
        DynamicsService(doc).configure((master,))
    with pytest.raises(ProjectError, match="ranges"):
        DynamicsService(doc).configure((tip,), damping=-1)
    assert doc.project is before


@pytest.mark.parametrize("preset", list(BOUNCES))
def test_bounce_presets_and_squash_preserve_area_and_are_editable(preset):
    """Bounce arcs move the control and squash keys maintain the authored scale product."""
    doc, root, _ = animated_chain()
    service = DynamicsService(doc)
    service.bounce(root, preset=preset, duration=48, height=60)
    assert any(
        k.value < 300
        for t in service.timeline.tracks
        if t.property_path == "transform.y"
        for k in t.keyframes
    )
    for frame in (0, 4, 12, 24, 48):
        node = doc.animation.evaluate(frame).nodes[root]
        assert node.local.scale_x * node.local.scale_y == pytest.approx(1, abs=0.015)
    service.squash(root, 10, 0.5, 8)
    node = doc.animation.evaluate(14).nodes[root]
    assert node.local.scale_x * node.local.scale_y == pytest.approx(1)


@pytest.mark.gui
def test_dynamics_dialog_preview_and_background_bake(qtbot, tmp_path):
    """Desktop simulation previews remain transient and background results publish once."""
    pytest.importorskip("PySide6")
    from rigora.app.application import ApplicationInfo
    from rigora.infrastructure.preferences import PreferencesStore
    from rigora.presentation.viewmodels.main_window import MainWindowViewModel
    from rigora.presentation.views.main_window import MainWindow
    from rigora.presentation.widgets.dynamics import DynamicsDialog

    doc, _, _ = animated_chain()
    vm = MainWindowViewModel(ApplicationInfo(), preferences=PreferencesStore(tmp_path / "ui.json"))
    window = MainWindow(vm)
    window.confirm_discard = lambda: True
    qtbot.addWidget(window)
    vm.new_project()
    vm.content.pool.waitForDone(3000)
    scene = doc.project.scenes[0]
    DynamicsService(vm.documents).commit(
        "Animated fixture",
        skeletons=scene.skeletons,
        timelines=scene.timelines,
        clips=scene.clips,
        constraints=scene.constraints,
    )
    vm.changed.emit()
    dialog = DynamicsDialog(window)
    qtbot.addWidget(dialog)
    dialog.show()
    before = vm.documents.project
    window.rig_workspace.set_mode(True)
    dialog.preview()
    qtbot.waitUntil(lambda: vm.animation_editor.preview_pose is not None)
    assert vm.documents.project is before
    assert window.viewport.pose is vm.animation_editor.preview_pose
    dialog.stop()
    dialog.bake()
    qtbot.waitUntil(lambda: dialog.bake_job is None, timeout=10000)
    assert not vm.animation_editor.error and len(vm.documents.project.scenes[0].clips) == 2
    assert dialog.grab().save(str(tmp_path / "dynamics-dialog.png"))
    dialog.close()
