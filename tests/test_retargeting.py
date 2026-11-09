"""Proportional motion transfer, missing controls and non-destructive baked constraints."""

from dataclasses import replace

import pytest

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.bone_animation import BoneAnimationService
from rigora.application_services.documents import DocumentService
from rigora.application_services.retargeting import RetargetService, suggest_mapping
from rigora.domain.entities import Bone, Constraint, Skeleton, Transform
from rigora.domain.geometry import transform_point
from rigora.domain.project import ProjectError


def documents():
    """Create proportionally different rigs with authored subframes and different frame rates."""
    source, target = DocumentService(), DocumentService()
    source.new()
    target.new()
    a = Bone(name="hips", length=100)
    b = Bone(name="arm.L", parent_id=a.id, length=60, transform=Transform(x=100))
    c = Bone(name="head", parent_id=a.id)
    x = Bone(name="pelvis", length=200, transform=Transform(x=400, rotation=10))
    y = Bone(name="upper_arm.L", parent_id=x.id, length=120, transform=Transform(x=200))
    sr, tr = Skeleton(bones=(a, b, c)), Skeleton(bones=(x, y))
    RetargetService(source).commit("Source rig", skeletons=(sr,))
    RetargetService(target).commit(
        "Target rig", skeletons=(tr,), settings=replace(target.project.scenes[0].settings, fps=48)
    )
    editor = AnimationEditingService(source)
    editor.key(a.id, "transform.x", 0, 0)
    editor.key(a.id, "transform.x", 12, 20)
    editor.key(b.id, "transform.rotation", 0, 0)
    editor.key(b.id, "transform.rotation", 6.5, 45)
    editor.key(b.id, "transform.rotation", 12, 90)
    editor.clip_settings(out_frame=12)
    return source, target, sr, tr


def test_retarget_preserves_seconds_subframes_proportions_corrections_and_undo(tmp_path):
    """A corrected motion remains scalar-editable and survives archive save with one undo."""
    source, target, sr, tr = documents()
    service = RetargetService(target)
    before, original = target.project, source.project
    mapping = suggest_mapping(sr, tr, "Human")
    result = service.apply(
        source,
        AnimationEditingService(source).clip.id,
        sr.id,
        tr.id,
        mapping,
        rotation_offsets={tr.bones[1].id: 5},
    )
    assert source.project is original and result.missing == ("head",)
    assert service.clip.out_frame == 24
    assert any(k.frame == 13 for t in service.timeline.tracks for k in t.keyframes)
    pose = target.animation.evaluate(24)
    assert pose.nodes[tr.bones[0].id].local.x == pytest.approx(440)
    assert pose.nodes[tr.bones[1].id].local.rotation == pytest.approx(95)
    assert service.scene.skeletons == before.scenes[0].skeletons
    target.save(tmp_path / "retarget.rigora")
    reopened = DocumentService()
    reopened.open(tmp_path / "retarget.rigora")
    assert reopened.animation.evaluate(24) == pose
    target.undo()
    assert target.project == before


def test_retarget_bakes_over_target_constraints_without_mutating_them(tmp_path):
    """FK overrides belong to a clip and remap alongside reusable action owners."""
    source, target, sr, tr = documents()
    service = RetargetService(target)
    constraint = Constraint(
        kind="rotation_limit", owner_id=tr.bones[1].id, parameters={"minimum": -5, "maximum": 5}
    )
    service.commit("Limit", constraints=(constraint,))
    service.apply(
        source,
        AnimationEditingService(source).clip.id,
        sr.id,
        tr.id,
        suggest_mapping(sr, tr, "Human"),
    )
    assert target.animation.evaluate(24).nodes[tr.bones[1].id].local.rotation == pytest.approx(90)
    assert service.scene.constraints == (constraint,)
    service.export_action(tmp_path / "motion.rigaction")
    service.import_action(tmp_path / "motion.rigaction")
    assert target.animation.evaluate(24).nodes[tr.bones[1].id].local.rotation == pytest.approx(90)
    target.animation.seek(24)
    node = target.animation.pose.nodes[tr.bones[1].id]
    end = transform_point(node.world_matrix, node.length, 0)
    patch, preview = BoneAnimationService(target).plan_drag(
        node.id, "pull", end[0] - 15, end[1] + 30
    )
    assert preview.frame == 24 and patch.after
    target.execute(patch)
    assert service.scene.constraints == (constraint,) and not target.animation.evaluator.rules


def test_retarget_rejects_duplicate_mapping_and_locked_targets_atomically():
    """Invalid transfers leave both documents and their history intact."""
    source, target, sr, tr = documents()
    service = RetargetService(target)
    before = target.project
    with pytest.raises(ProjectError, match="distinct"):
        service.apply(
            source,
            AnimationEditingService(source).clip.id,
            sr.id,
            tr.id,
            {b.id: tr.bones[0].id for b in sr.bones},
        )
    assert target.project is before
    service.commit(
        "Lock", skeletons=(replace(tr, bones=(replace(tr.bones[0], locked=True), tr.bones[1])),)
    )
    with pytest.raises(ProjectError, match="Unlock"):
        service.apply(
            source,
            AnimationEditingService(source).clip.id,
            sr.id,
            tr.id,
            suggest_mapping(sr, tr, "Human"),
        )


@pytest.mark.parametrize("profile", ["Human", "Quadruped", "Winged", "Flexible spine"])
def test_profiles_resolve_unique_explicit_roles(profile):
    """Every advertised anatomical profile maps explicit roles deterministically."""
    a, b = Bone(name="A", extra={"role": "root"}), Bone(name="B", extra={"role": "root"})
    assert suggest_mapping(Skeleton(bones=(a,)), Skeleton(bones=(b,)), profile) == {a.id: b.id}


@pytest.mark.gui
def test_retarget_dialog_previews_without_history_then_creates_clip(qtbot, tmp_path):
    """The desktop table drives the same corrected service and clears transient preview."""
    from rigora.app.application import ApplicationInfo
    from rigora.infrastructure.preferences import PreferencesStore
    from rigora.presentation.viewmodels.main_window import MainWindowViewModel
    from rigora.presentation.views.main_window import MainWindow
    from rigora.presentation.widgets.retargeting import RetargetDialog

    source, target, _, _ = documents()
    vm = MainWindowViewModel(ApplicationInfo(), preferences=PreferencesStore(tmp_path / "ui.json"))
    window = MainWindow(vm)
    window.confirm_discard = lambda: True
    qtbot.addWidget(window)
    vm.new_project()
    vm.content.pool.waitForDone(3000)
    # Adopt only test fixture records into the real tab's canonical document.
    RetargetService(vm.documents).commit("Target rig", skeletons=target.project.scenes[0].skeletons)
    vm.changed.emit()
    dialog = RetargetDialog(window)
    qtbot.addWidget(dialog)
    dialog.source = source
    dialog.fill_sources()
    dialog.populate()
    before = vm.documents.project
    window.rig_workspace.set_mode(True)
    dialog.preview()
    assert dialog.scratch is not None and vm.documents.project is before
    assert window.viewport.pose is vm.animation_editor.preview_pose
    dialog.slider.setValue(500)
    assert vm.animation_editor.preview_pose is not None
    dialog.apply()
    assert not vm.animation_editor.error and vm.documents.project.scenes[0].clips
    assert vm.animation_editor.preview_pose is None
