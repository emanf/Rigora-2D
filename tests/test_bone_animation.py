"""Frame-aware bone posing, anchored chains, keyed IK targets and persistent playback caps."""

import pytest

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.bone_animation import BoneAnimationService
from rigora.application_services.documents import DocumentService
from rigora.application_services.rigging import RigService
from rigora.domain.geometry import transform_point


def rig_document():
    """Create an editable two-bone chain with a nonzero animated pose at frame twelve."""
    doc = DocumentService()
    doc.new()
    rig = RigService(doc)
    root = rig.create_bone((300, 300), (400, 300))
    tip = rig.create_bone((400, 300), (500, 300), root)
    editor = AnimationEditingService(doc)
    editor.key(root, "transform.rotation", 0, 0)
    editor.key(root, "transform.rotation", 24, 60)
    doc.animation.seek(12)
    return doc, rig, root, tip


def test_pose_drag_starts_from_displayed_frame_and_keys_without_changing_rest(tmp_path):
    """A solved chain is previewed live and committed once without changing binding geometry."""
    doc, rig, root, tip = rig_document()
    before, count = doc.project, len(doc.history.undo_stack)
    first = doc.animation.evaluate(0)
    rest = rig.scene.skeletons
    end = transform_point(doc.animation.pose.nodes[tip].world_matrix, 100, 0)
    command, preview = BoneAnimationService(doc).plan_drag(tip, "pull", end[0] - 20, end[1] + 40)
    assert doc.project is before and len(doc.history.undo_stack) == count
    assert (
        preview.frame == 12
        and preview.nodes[tip].world_matrix != doc.animation.pose.nodes[tip].world_matrix
    )
    assert transform_point(preview.nodes[root].world_matrix, 0, 0) == pytest.approx((300, 300))
    doc.execute(command)
    assert len(doc.history.undo_stack) == count + 1 and doc.animation.pose.frame == 12
    assert rig.scene.skeletons == rest
    assert doc.animation.evaluate(0).nodes == first.nodes
    assert doc.animation.pose.nodes == preview.nodes
    doc.save(tmp_path / "bone-motion.rigora")
    clone = DocumentService()
    clone.open(tmp_path / "bone-motion.rigora")
    assert clone.animation.evaluate(12) == preview
    doc.undo()
    assert doc.project == before


def test_playback_cap_clamps_transport_without_removing_future_keys(tmp_path):
    """Shortening a clip hides future playback, retains its keys, and survives save/undo."""
    doc, _, _, _ = rig_document()
    service = AnimationEditingService(doc)
    keys = service.timeline.tracks
    doc.animation.seek(24)
    before = doc.project
    service.set_end_frame(18)
    assert service.timeline.tracks == keys
    assert doc.animation.pose.frame == 18 and doc.animation.playback.range.end == 18
    doc.save(tmp_path / "cap.rigora")
    clone = DocumentService()
    clone.open(tmp_path / "cap.rigora")
    assert clone.animation.playback.range.end == 18
    doc.undo()
    assert doc.project == before
    doc.new()
    assert doc.animation.playback.range.end == 120
    service.set_end_frame(200)
    assert doc.animation.playback.range.end == 200


def test_ik_drag_keys_target_at_current_frame_and_preserves_root():
    """Animation gestures route constrained endpoints to keyed controls instead of rest edits."""
    doc, rig, root, tip = rig_document()
    rig.add_constraint(root, "two_bone_ik")
    rule = rig.scene.constraints[0]
    doc.animation.seek(12)
    rest = rig.scene.objects
    target = doc.animation.pose.nodes[rule.target_id].world_matrix[4:]
    command, preview = BoneAnimationService(doc).plan_drag(
        tip, "pull", target[0] - 25, target[1] + 30
    )
    assert preview.frame == 12
    assert preview.nodes[rule.target_id].world_matrix[4:] == pytest.approx(
        (target[0] - 25, target[1] + 30)
    )
    doc.execute(command)
    assert rig.scene.objects == rest
    assert any(t.owner_id == rule.target_id for t in AnimationEditingService(doc).timeline.tracks)
    assert transform_point(preview.nodes[root].world_matrix, 0, 0) == pytest.approx((300, 300))
