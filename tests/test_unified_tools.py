"""Selected-only bone transforms and shared scene gizmo pivots preserve untouched geometry."""

import math
from dataclasses import replace
from pathlib import Path

import pytest

from rigora.application_services.bone_animation import BoneAnimationService
from rigora.application_services.documents import DocumentService
from rigora.application_services.meshes import MeshService
from rigora.application_services.rigging import RigService
from rigora.application_services.scene_editing import SceneEditingService
from rigora.domain.geometry import transform_point
from rigora.domain.project import ProjectError


def chain():
    """Return a branch and an independent root to detect unintended rig-wide motion."""
    document = DocumentService()
    document.new()
    rig = RigService(document)
    root = rig.create_bone((100, 150), (200, 150))
    middle = rig.create_bone((200, 150), (280, 150), root)
    tip = rig.create_bone((280, 150), (340, 150), middle)
    other = rig.create_bone((100, 300), (180, 300), new_skeleton=True)
    return document, rig, root, middle, tip, other


@pytest.mark.parametrize("rotation", [-175, 175])
@pytest.mark.parametrize("scale_x,scale_y", [(1, 1), (-2, 0.5), (0.5, 2)])
def test_joint_limit_uses_direct_parent_world_angle(rotation, scale_x, scale_y, tmp_path):
    """Both bend sides and mirrored/nonuniform parents honor each connected joint's limit."""
    doc, rig, root, middle, tip, other = chain()
    rig.update(
        root,
        transform=replace(rig.bone(root).transform, rotation=23, scale_x=scale_x, scale_y=scale_y),
    )
    rig.set_minimum_joint_angle((middle, tip), 90)
    for key in (middle, tip):
        rig.update(key, transform=replace(rig.bone(key).transform, rotation=rotation))
    pose = rig.preview_pose()
    assert not pose.warnings
    for parent, child in ((root, middle), (middle, tip)):
        a, b = pose.nodes[parent].world_matrix[:2]
        c, d = pose.nodes[child].world_matrix[:2]
        interior = 180 - math.degrees(
            math.acos(max(-1, min(1, (a * c + b * d) / math.hypot(a, b) / math.hypot(c, d))))
        )
        assert interior == pytest.approx(90)
        assert pose.nodes[child].world_matrix[4:] == pytest.approx(
            transform_point(pose.nodes[parent].world_matrix, rig.bone(parent).length, 0)
        )
    path = tmp_path / "joint-limit.rigora"
    doc.save(path)
    loaded = DocumentService()
    loaded.open(path)
    assert loaded.animation.pose.nodes[tip].world_matrix == pytest.approx(
        pose.nodes[tip].world_matrix
    )
    baseline = doc.project
    rig.set_minimum_joint_angle((middle, tip), 0)
    assert rig.preview_pose().nodes[middle].world_matrix != pose.nodes[middle].world_matrix
    doc.undo()
    assert doc.project == baseline


def test_whole_rig_drag_moves_only_connected_root_and_descendants():
    """An independent skeleton stays fixed, and one undo restores the selected rig."""
    doc, rig, root, middle, tip, other = chain()
    before, project = rig.preview_pose(), doc.project
    command, preview = rig.plan_drag(middle, "rig_move", 230, 190, (middle,))
    for key in (root, middle, tip):
        origin = before.nodes[key].world_matrix[4:]
        assert preview.nodes[key].world_matrix[4:] == pytest.approx(
            (origin[0] + 30, origin[1] + 40)
        )
    assert preview.nodes[other].world_matrix == before.nodes[other].world_matrix
    doc.execute(command)
    doc.undo()
    assert doc.project == project


@pytest.mark.parametrize("scope", ["selection_rotate", "chain_rotate"])
def test_rotation_anchors_joint_and_fk_inherits_without_double_rotation(scope):
    """Single-joint transforms anchor the root; FK moves descendants exactly once."""
    doc, rig, root, middle, tip, other = chain()
    before, baseline = rig.preview_pose(), doc.project
    command, pose = rig.plan_drag(middle, scope, 90, 0, (middle,))
    assert pose.nodes[middle].world_matrix[4:] == pytest.approx((200, 150))
    assert transform_point(pose.nodes[middle].world_matrix, 80, 0) == pytest.approx((200, 230))
    for key in (root, other):
        assert pose.nodes[key].world_matrix == pytest.approx(before.nodes[key].world_matrix)
    if scope == "chain_rotate":
        assert pose.nodes[tip].world_matrix[4:] == pytest.approx((200, 230))
        assert pose.nodes[tip].local == pytest.approx(before.nodes[tip].local)
    else:
        assert pose.nodes[tip].world_matrix == pytest.approx(before.nodes[tip].world_matrix)
    doc.execute(command)
    doc.undo()
    assert doc.project == baseline


def test_fk_multi_selection_and_animated_rotation_share_solver():
    """Selected joints each rotate while animation retains authored rest data."""
    doc, rig, root, middle, tip, other = chain()
    baseline = doc.project
    _, pose = rig.plan_drag(middle, "chain_rotate", 30, 0, (middle, tip))
    assert pose.nodes[middle].local.rotation == pytest.approx(30)
    assert pose.nodes[tip].local.rotation == pytest.approx(30)
    command, pose = BoneAnimationService(doc).plan_drag(middle, "chain_rotate", 90, 0, (middle,))
    doc.execute(command)
    assert doc.project.scenes[0].skeletons == baseline.scenes[0].skeletons
    assert doc.animation.pose.nodes[tip].world_matrix[4:] == pytest.approx((200, 230))
    doc.undo()
    assert doc.project == baseline


@pytest.mark.parametrize("reverse", [False, True])
def test_fk_multi_rotation_anchors_highest_selected_joint_in_rest_and_animation(reverse):
    """Selected joints bend independently in rest and animation, regardless of selection order."""
    doc, rig, root, middle, tip, _ = chain()
    selected = (tip, middle) if reverse else (middle, tip)
    before = rig.preview_pose()
    for service in (rig, BoneAnimationService(doc)):
        command, pose = service.plan_drag(tip, "chain_rotate", 90, 0, selected)
        assert pose.nodes[middle].world_matrix[4:] == pytest.approx((200, 150))
        assert pose.nodes[tip].world_matrix[4:] == pytest.approx((200, 230))
        assert pose.nodes[root].world_matrix == before.nodes[root].world_matrix
        assert pose.nodes[middle].local.rotation == pytest.approx(90)
        assert pose.nodes[tip].local.rotation == pytest.approx(90)
        assert transform_point(pose.nodes[tip].world_matrix, 60, 0) == pytest.approx((140, 230))
        doc.execute(command)
        doc.undo()


def test_fk_respects_locked_descendants_and_rig_scope_covers_selected_roots_once():
    """Locked branches reject FK atomically; overlapping rig selections move only once."""
    doc, rig, root, middle, tip, other = chain()
    rig.update(tip, locked=True)
    baseline = doc.project
    with pytest.raises(ProjectError, match="locked"):
        rig.plan_drag(middle, "chain_rotate", 40, 0, (middle,))
    assert doc.project == baseline
    rig.update(tip, locked=False)
    before = rig.preview_pose()
    _, pose = rig.plan_drag(middle, "rig_move", 230, 190, (middle, tip, other))
    for key in (root, middle, tip, other):
        x, y = before.nodes[key].world_matrix[4:]
        assert pose.nodes[key].world_matrix[4:] == pytest.approx((x + 30, y + 40))


@pytest.mark.parametrize("indices", [(0, 1), (0, 2), (1, 2)])
@pytest.mark.parametrize("angle", [-20, 30])
def test_fk_each_selected_joint_keys_once_and_unselected_locals_stay_intact(indices, angle):
    """Adjacent or separated selected joints bend in either direction through the shared solver."""
    doc, rig, root, middle, tip, other = chain()
    keys = (root, middle, tip)
    selected = tuple(keys[i] for i in indices)
    baseline, before = doc.project, rig.preview_pose()
    for service in (rig, BoneAnimationService(doc)):
        command, preview = service.plan_drag(selected[-1], "chain_rotate", angle, 0, selected)
        for identity in (*keys, other):
            assert preview.nodes[identity].local.rotation == pytest.approx(
                before.nodes[identity].local.rotation + (angle if identity in selected else 0)
            )
            assert preview.nodes[identity].local.x == pytest.approx(before.nodes[identity].local.x)
            assert preview.nodes[identity].local.y == pytest.approx(before.nodes[identity].local.y)
        doc.execute(command)
        for identity in selected:
            assert doc.animation.pose.nodes[identity].local.rotation == pytest.approx(angle)
        doc.undo()
        assert doc.project == baseline


@pytest.mark.parametrize(
    "tool,x,y",
    [("selection_move", 220, 190), ("selection_rotate", 35, 0), ("selection_scale", 1.5, 0)],
)
def test_single_bone_keeps_parent_children_and_other_rigs_fixed(tool, x, y):
    """Only the selected world bone changes; child compensation and undo are atomic."""
    doc, rig, root, middle, tip, other = chain()
    baseline, before = doc.project, doc.animation.pose
    count = len(doc.history.undo_stack)
    command, preview = rig.plan_drag(middle, tool, x, y, (middle,))
    assert doc.project is baseline
    for key in (root, tip, other):
        assert preview.nodes[key].world_matrix == pytest.approx(before.nodes[key].world_matrix)
    assert preview.nodes[middle].world_matrix != before.nodes[middle].world_matrix
    doc.execute(command)
    assert len(doc.history.undo_stack) == count + 1
    doc.undo()
    assert doc.project == baseline


def test_multiple_selected_bones_move_together_and_ctrl_solver_stays_available():
    """Explicit selection transforms preserve untouched roots; pull remains a distinct solve."""
    doc, rig, root, middle, tip, other = chain()
    before = doc.animation.pose
    _, selected = rig.plan_drag(middle, "selection_move", 230, 170, (middle, tip))
    for key in (middle, tip):
        original = before.nodes[key].world_matrix
        assert selected.nodes[key].world_matrix[4:] == pytest.approx(
            (original[4] + 30, original[5] + 20)
        )
    assert selected.nodes[root].world_matrix == before.nodes[root].world_matrix
    assert selected.nodes[other].world_matrix == before.nodes[other].world_matrix
    _, pulled = rig.plan_drag(tip, "pull", 250, 230, (tip,))
    assert pulled.nodes[root].world_matrix[4:] == pytest.approx(before.nodes[root].world_matrix[4:])
    assert pulled.nodes[middle].world_matrix != before.nodes[middle].world_matrix


def test_selected_pose_keys_child_compensation_and_keeps_rest_data():
    """The animated entry point uses the same selected-only solver and remains undoable."""
    doc, rig, root, middle, tip, _ = chain()
    baseline = doc.project
    command, preview = BoneAnimationService(doc).plan_drag(
        middle, "selection_move", 230, 180, (middle,)
    )
    assert preview.nodes[root].world_matrix == pytest.approx(
        doc.animation.pose.nodes[root].world_matrix
    )
    assert preview.nodes[tip].world_matrix == pytest.approx(
        doc.animation.pose.nodes[tip].world_matrix
    )
    doc.execute(command)
    assert rig.scene.skeletons == baseline.scenes[0].skeletons
    assert doc.animation.pose.nodes[middle].world_matrix[4:] == pytest.approx((230, 180))
    doc.undo()
    assert doc.project == baseline


@pytest.mark.parametrize("auto_key", [False, True])
def test_scene_scale_uses_opposite_handle_pivot_and_records_translation(auto_key):
    """Resizing about a fixed corner also keys the necessary translation when auto-key is on."""
    doc = DocumentService()
    doc.new()
    meshes = MeshService(doc)
    mesh_id = meshes.import_image_bytes("prop.svg", Path("assets/examples/prop.svg").read_bytes())
    owner = meshes.mesh(mesh_id).object_id
    before = doc.animation.pose.nodes[owner].world_matrix
    pivot = transform_point(before, 100, 100)
    old_tip = transform_point(before, 0, 0)
    service = SceneEditingService(doc)
    service.auto_key = auto_key
    service.transform((owner,), scale_x=2, scale_y=2, center_x=pivot[0], center_y=pivot[1])
    after = doc.animation.pose.nodes[owner].world_matrix
    assert transform_point(after, 100, 100) == pytest.approx(pivot)
    assert transform_point(after, 0, 0) == pytest.approx(
        (pivot[0] + 2 * (old_tip[0] - pivot[0]), pivot[1] + 2 * (old_tip[1] - pivot[1]))
    )
