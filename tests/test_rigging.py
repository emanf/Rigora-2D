"""Rest-space topology edits, mirroring and immutable rig command history."""

import math
from dataclasses import replace
from pathlib import Path

import pytest

from rigora.application_services.documents import DocumentService
from rigora.application_services.rigging import RigService
from rigora.domain.entities import Transform
from rigora.domain.geometry import transform_point
from rigora.domain.project import ProjectError
from rigora.engine.chain_pull import pull_chain


@pytest.mark.parametrize("target", [(150, 0), (120, 130), (500, 100), (0, 0)])
def test_anchored_chain_projection_preserves_root_and_lengths(target):
    """Straight, folded and unreachable pulls must remain finite and keep every joint connected."""
    original = ((0, 0), (100, 0), (200, 0), (300, 0))
    solved = pull_chain(original, target)
    assert solved[0] == original[0]
    for start, end in zip(solved[:-1], solved[1:], strict=True):
        assert math.dist(start, end) == pytest.approx(100)
    if math.dist(original[0], target) <= 300:
        assert math.dist(solved[-1], target) < 1e-3
    else:
        assert math.dist(original[0], solved[-1]) == pytest.approx(300)


def test_pull_plan_updates_connected_chain_without_mutating_document(tmp_path):
    """Preview and commit share one command with complete undo and persistence."""
    doc = DocumentService()
    doc.new()
    service = RigService(doc)
    root = service.create_bone((100, 100), (200, 100))
    middle = service.create_bone((200, 100), (300, 100), root)
    tip = service.create_bone((300, 100), (400, 100), middle)
    original = doc.project
    history = len(doc.history.undo_stack)
    command, pose = service.plan_drag(tip, "pull", 310, 200)
    assert doc.project is original and len(doc.history.undo_stack) == history
    assert transform_point(pose.nodes[root].world_matrix, 0, 0) == pytest.approx((100, 100))
    assert transform_point(pose.nodes[tip].world_matrix, 100, 0) == pytest.approx(
        (310, 200), abs=1e-3
    )
    for parent, child in ((root, middle), (middle, tip)):
        assert transform_point(pose.nodes[parent].world_matrix, 100, 0) == pytest.approx(
            transform_point(pose.nodes[child].world_matrix, 0, 0)
        )
    doc.execute(command)
    assert len(doc.history.undo_stack) == history + 1
    doc.save(tmp_path / "pulled.rigora")
    reopened = DocumentService()
    reopened.open(tmp_path / "pulled.rigora")
    assert reopened.project == doc.project
    doc.undo()
    assert doc.project == original
    doc.redo()
    assert doc.project == reopened.project


def test_root_attached_pull_and_group_move_preserve_topology():
    """Root-attached branches remain anchored and group moves never double-translate children."""
    doc = DocumentService()
    doc.new()
    service = RigService(doc)
    root = service.create_bone((100, 100), (200, 100))
    branch = service.create_bone((100, 100), (100, 200), root)
    leaf = service.create_bone((100, 200), (100, 300), branch)
    service.pull(leaf, 200, 200)
    pose = service.preview_pose()
    for key in (root, branch):
        assert transform_point(pose.nodes[key].world_matrix, 0, 0) == pytest.approx((100, 100))
    assert transform_point(pose.nodes[leaf].world_matrix, 100, 0) == pytest.approx(
        (200, 200), abs=1e-3
    )
    before = pose.nodes[leaf].world_matrix
    service.move_selection((root, branch, leaf), root, 130, 120)
    after = service.preview_pose().nodes[leaf].world_matrix
    assert after[:4] == pytest.approx(before[:4])
    assert after[4:] == pytest.approx((before[4] + 30, before[5] + 20))


def test_pull_preview_deforms_bound_art_and_preserves_source_document():
    """Preview real skinning while leaving stored bones, asset bytes and history intact."""
    doc = DocumentService()
    doc.open(Path("examples/image-import-example.rigora"))
    service = RigService(doc)
    original = doc.project
    rig = service.scene.skeletons[0]
    mesh = service.scene.meshes[0]
    before = service.preview_pose().meshes[mesh.id].positions
    _, pose = service.plan_drag(rig.bones[-1].id, "pull", 470, 400)
    assert pose.meshes[mesh.id].positions != before
    assert doc.project is original and not doc.can_undo


def test_last_bone_with_interior_or_offset_parent_attachment_can_be_pulled():
    """Template shoulders and hips preserve their attachment offsets while ancestors pose live."""
    doc = DocumentService()
    doc.new()
    service = RigService(doc)
    root = service.create_bone((100, 100), (250, 100))
    arm = service.create_bone((175, 110), (245, 110), root)
    leaf = service.create_bone((245, 110), (315, 110), arm)
    original_offset = service.bone(arm).transform.x, service.bone(arm).transform.y
    original = doc.project
    command, pose = service.plan_drag(leaf, "pull", 240, 190)
    assert doc.project is original
    assert transform_point(pose.nodes[root].world_matrix, 0, 0) == pytest.approx((100, 100))
    assert transform_point(pose.nodes[leaf].world_matrix, 70, 0) == pytest.approx(
        (240, 190), abs=1e-3
    )
    doc.execute(command)
    assert (service.bone(arm).transform.x, service.bone(arm).transform.y) == pytest.approx(
        original_offset
    )
    assert service.bone(root).length == 150
    doc.undo()
    assert doc.project == original


def test_constrained_last_bone_pull_moves_ik_target_live_and_undoes():
    """Dragging an IK endpoint edits its control, preserving the anchored root and constraint."""
    doc = DocumentService()
    doc.new()
    service = RigService(doc)
    root = service.create_bone((100, 100), (200, 100))
    child = service.create_bone((200, 100), (300, 100), root)
    rule_id = service.add_constraint(root, "two_bone_ik")
    rule = next(c for c in service.scene.constraints if c.id == rule_id)
    original = doc.project
    count = len(doc.history.undo_stack)
    command, pose = service.plan_drag(child, "pull", 250, 150)
    assert transform_point(pose.nodes[child].world_matrix, 100, 0) == pytest.approx((250, 150))
    assert transform_point(pose.nodes[root].world_matrix, 0, 0) == pytest.approx((100, 100))
    assert doc.project is original and len(doc.history.undo_stack) == count
    doc.execute(command)
    assert service.preview_pose().nodes[rule.target_id].world_matrix[4:] == (250, 150)
    assert service.scene.constraints[0] == rule
    assert len(doc.history.undo_stack) == count + 1
    doc.undo()
    assert doc.project == original


def test_create_reparent_insert_delete_and_undo_preserve_child_world():
    doc = DocumentService()
    doc.new()
    rig = RigService(doc)
    root = rig.create_bone((100, 100), (200, 100))
    child = rig.create_bone((200, 100), (250, 150), root)
    before = rig.rest_pose().nodes[child].world_matrix
    rig.reparent(child, None)
    assert rig.rest_pose().nodes[child].world_matrix == pytest.approx(before)
    rig.reparent(child, root)
    inserted = rig.insert(root)
    assert rig.bone(child).parent_id == inserted
    assert rig.rest_pose().nodes[child].world_matrix == pytest.approx(before)
    rig.delete(inserted)
    assert rig.bone(child).parent_id == root
    assert rig.rest_pose().nodes[child].world_matrix == pytest.approx(before)
    doc.undo()
    assert rig.bone(child).parent_id == inserted
    with pytest.raises(ProjectError):
        rig.reparent(root, child)


def test_mirror_templates_groups_and_save_reload(tmp_path):
    doc = DocumentService()
    doc.new()
    rig = RigService(doc)
    root = rig.create_bone((100, 100), (180, 150))
    rig.update(root, name="arm.L", group="Arms", color="#dddddd")
    mirrored = rig.mirror(root, 300)[0]
    original = rig.rest_pose().nodes[root]
    reflected = rig.rest_pose().nodes[mirrored]
    point = transform_point(original.world_matrix, original.length, 0)
    assert transform_point(reflected.world_matrix, reflected.length, 0) == pytest.approx(
        (600 - point[0], point[1])
    )
    assert rig.bone(mirrored).name == "arm.R"
    rig.set_group("Arms", locked=True)
    with pytest.raises(ProjectError, match="locked"):
        rig.update(root, name="Locked")
    rig.set_group("Arms", locked=False, visible=False)
    assert not rig.rest_pose().nodes[root].visible
    rig.template("Biped")
    rig.template("Quadruped")
    doc.save(tmp_path / "rig.rigora")
    expected = rig.rest_pose().to_dict()
    doc.open(tmp_path / "rig.rigora")
    assert rig.rest_pose().to_dict() == expected


def test_topology_rejects_shear_without_changing_history():
    doc = DocumentService()
    doc.new()
    rig = RigService(doc)
    parent = rig.create_bone((100, 100), (200, 100))
    child = rig.create_bone((250, 200), (300, 240))
    rig.update(parent, transform=Transform(rotation=40, scale_x=2))
    previous = doc.project
    with pytest.raises(ProjectError, match="shear"):
        rig.reparent(child, parent)
    assert doc.project is previous
    rig.update(child, transform=replace(rig.bone(child).transform, pivot_x=10))


def test_example_targets_animate_symmetrically_and_roundtrip(tmp_path):
    from animation_fixtures import rigging_example

    from rigora.engine.evaluation import SceneEvaluator
    from rigora.infrastructure.project_storage import ProjectStorage

    sample = rigging_example()
    path = tmp_path / "symmetric.rigora"
    storage = ProjectStorage()
    storage.save(path, sample, {})
    reopened = storage.load_document(path).project
    evaluator = SceneEvaluator(sample.scenes[0])
    for frame in (0, 23.5, 55, 5, 30, 0):
        pose = evaluator.evaluate(frame)
        assert not pose.warnings
        assert pose == SceneEvaluator(reopened.scenes[0]).evaluate(frame)
        tips = []
        for rig in sample.scenes[0].skeletons:
            for bone in rig.bones:
                if bone.parent_id:
                    node = pose.nodes[bone.id]
                    point = transform_point(node.world_matrix, node.length, 0)
                    target = next(
                        obj for obj in sample.scenes[0].objects if obj.name.endswith(bone.name[-2:])
                    )
                    assert point == pytest.approx(pose.nodes[target.id].world_matrix[4:])
                    tips.append(point)
        assert tips[0][0] + tips[1][0] == pytest.approx(900)
        assert tips[0][1] == pytest.approx(tips[1][1])


def test_pivoted_endpoint_edit_and_space_switch_keep_world_pose():
    from rigora.application_services.commands import ScenePatch
    from rigora.domain.entities import SceneObject

    doc = DocumentService()
    doc.new()
    service = RigService(doc)
    root = service.create_bone((100, 100), (200, 100))
    service.update(root, transform=Transform(x=100, y=100, pivot_x=15, pivot_y=10))
    service.drag(root, "length", 240, 170)
    node = service.rest_pose().nodes[root]
    assert transform_point(node.world_matrix, node.length, 0) == pytest.approx((240, 170))
    pin = service.add_constraint(root, "pin", point_x=10, point_y=5)
    assert service.preview_pose().nodes[root].world_matrix == pytest.approx(node.world_matrix)
    service.remove_constraint(pin)
    one = SceneObject(transform=Transform(x=40, y=50))
    two = SceneObject(transform=Transform(x=300, y=200))
    scene = service.scene
    doc.execute(
        ScenePatch("Add control spaces", scene.id, {"objects": ()}, {"objects": (one, two)})
    )
    rule = service.add_constraint(root, "space_switch", one.id)
    before = doc.animation.pose.nodes[root].world_matrix
    service.update_constraint(rule, target_id=two.id, keep_world=True)
    assert doc.animation.pose.nodes[root].world_matrix == pytest.approx(before)
    original = doc.project
    service.delete(root)
    assert all(b.extra.get("rig_root") for b in service.scene.skeletons[0].bones)
    assert all(c.id != rule for c in service.scene.constraints)
    doc.undo()
    assert doc.project == original
