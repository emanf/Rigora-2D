"""Analytical IK, deterministic rule dependencies and safe invalid-setup diagnostics."""

from dataclasses import replace

import pytest

from rigora.domain.entities import Bone, Constraint, SceneObject, Skeleton, Transform
from rigora.domain.geometry import transform_point
from rigora.domain.project import Scene
from rigora.engine.evaluation import SceneEvaluator


def chain(target=(120, 80), **parameters):
    """Build a two-segment fixture with an independent end-effector control."""
    root = Bone(length=100)
    child = Bone(parent_id=root.id, length=100, transform=Transform(x=100))
    control = SceneObject(transform=Transform(x=target[0], y=target[1]))
    rule = Constraint(
        owner_id=root.id,
        target_id=control.id,
        kind="two_bone_ik",
        parameters={"end_bone_id": child.id, **parameters},
    )
    return (
        Scene(skeletons=(Skeleton(bones=(root, child)),), objects=(control,), constraints=(rule,)),
        root,
        child,
        control,
    )


@pytest.mark.parametrize("target", [(120, 80), (0, 0), (199.999999, 0), (400, 0), (0, -100)])
def test_ik_reachable_unreachable_and_singular_targets(target):
    scene, root, child, control = chain(target)
    evaluator = SceneEvaluator(scene)
    pose = evaluator.evaluate(0)
    assert not pose.warnings
    point = transform_point(pose.nodes[child.id].world_matrix, pose.nodes[child.id].length, 0)
    distance = (target[0] ** 2 + target[1] ** 2) ** 0.5
    expected = tuple(v * min(1, 200 / distance) for v in target) if distance else (0, 0)
    assert point == pytest.approx(expected, abs=1e-6)
    assert evaluator.evaluate(0) == pose
    assert root.transform.rotation == 0 and child.transform.rotation == 0


def test_bend_stretch_reach_and_fk_switch():
    scene, root, child, _ = chain((100, 100), bend=-1)
    pose = SceneEvaluator(scene).evaluate(0)
    assert pose.nodes[child.id].local.rotation < 0
    scene, root, child, _ = chain((250, 0), stretch=True, max_stretch=1.5)
    pose = SceneEvaluator(scene).evaluate(0)
    assert pose.nodes[root.id].length == 125
    assert transform_point(pose.nodes[child.id].world_matrix, 125, 0) == pytest.approx((250, 0))
    scene, root, child, _ = chain((180, 0), max_reach=80)
    pose = SceneEvaluator(scene).evaluate(0)
    assert transform_point(pose.nodes[child.id].world_matrix, 100, 0) == pytest.approx((80, 0))
    rule = replace(scene.constraints[0], parameters={"mode": "fk"})
    pose = SceneEvaluator(replace(scene, constraints=(rule,))).evaluate(0)
    assert transform_point(pose.nodes[child.id].world_matrix, 100, 0) == (200, 0)


def test_dependency_order_cycles_invalid_rules_and_injected_solver():
    one, two, three = SceneObject(), SceneObject(), SceneObject(transform=Transform(x=70))
    first = Constraint(owner_id=one.id, target_id=two.id, kind="copy_transform", order=-10)
    second = Constraint(owner_id=two.id, target_id=three.id, kind="track", order=10)
    scene = Scene(objects=(one, two, three), constraints=(first, second))
    assert SceneEvaluator(scene).evaluate(0).nodes[one.id].local.x == 70
    cyclic = replace(second, target_id=one.id)
    pose = SceneEvaluator(replace(scene, constraints=(first, cyclic))).evaluate(0)
    assert len(pose.warnings) == 2 and "cycle" in pose.warnings[0]
    bad = replace(first, kind="limits", target_id=None, parameters={"min_x": 5, "max_x": 1})
    pose = SceneEvaluator(replace(scene, constraints=(bad,))).evaluate(0)
    assert "min_x" in pose.warnings[0] and pose.nodes[one.id].local.x == 0
    custom = replace(first, kind="example.plugin", target_id=None)

    def solve(rule, context):
        """Exercise the public solver callable with a deterministic world-origin edit."""
        context.position(rule.owner_id, 42, 9)

    pose = SceneEvaluator(
        replace(scene, constraints=(custom,)), solvers={"example.plugin": solve}
    ).evaluate(0)
    assert pose.nodes[one.id].local.x == 42 and not pose.warnings


def test_aim_limits_space_switch_and_pin_point():
    owner, target = SceneObject(), SceneObject(transform=Transform(x=0, y=100))
    aim = Constraint(owner_id=owner.id, target_id=target.id, kind="aim")
    limit = Constraint(owner_id=owner.id, kind="limits", order=1, parameters={"max_rotation": 45})
    scene = Scene(objects=(owner, target), constraints=(aim, limit))
    assert SceneEvaluator(scene).evaluate(0).nodes[owner.id].local.rotation == pytest.approx(45)
    pin = Constraint(owner_id=owner.id, kind="pin", parameters={"point_x": 10, "x": 30, "y": 20})
    pose = SceneEvaluator(replace(scene, constraints=(pin,))).evaluate(0)
    assert transform_point(pose.nodes[owner.id].world_matrix, 10, 0) == (30, 20)
    space = Constraint(
        owner_id=owner.id,
        target_id=target.id,
        kind="space_switch",
        parameters={"offset": [1, 0, 0, 1, 20, 30]},
    )
    assert SceneEvaluator(replace(scene, constraints=(space,))).evaluate(0).nodes[
        owner.id
    ].world_matrix[4:] == (20, 130)


def test_reflected_ik_and_pivoted_aim_preserve_correct_world_directions():
    scene, root, child, target = chain((100, 100))
    reflected = replace(root, transform=Transform(scale_y=-1))
    scene = replace(scene, skeletons=(Skeleton(bones=(reflected, child)),))
    pose = SceneEvaluator(scene).evaluate(0)
    assert not pose.warnings
    assert transform_point(pose.nodes[child.id].world_matrix, 100, 0) == pytest.approx((100, 100))
    owner = SceneObject(transform=Transform(pivot_x=20, pivot_y=15, scale_x=2))
    aim = Constraint(owner_id=owner.id, target_id=target.id, kind="aim")
    pose = SceneEvaluator(Scene(objects=(owner, target), constraints=(aim,))).evaluate(0)
    node = pose.nodes[owner.id]
    ox, oy = node.world_matrix[4:]
    a, b = node.world_matrix[:2]
    assert a * (100 - oy) - b * (100 - ox) == pytest.approx(0, abs=1e-8)
    assert (ox, oy) == pytest.approx(owner.transform.matrix()[4:])
    bad_pin = Constraint(owner_id=owner.id, kind="pin")
    invalid = SceneEvaluator(Scene(objects=(owner,), constraints=(bad_pin,))).evaluate(0)
    assert "fixed scene X and Y" in invalid.warnings[0]


def test_injected_solver_is_shared_by_document_animation_and_rig_preview():
    from rigora.application_services.commands import ScenePatch
    from rigora.application_services.documents import DocumentService
    from rigora.application_services.rigging import RigService

    def solve(rule, context):
        """Move the driven origin through the same context used by built-in solvers."""
        context.position(rule.owner_id, 17, 23)

    document = DocumentService(constraint_solvers={"example.custom": solve})
    document.new()
    scene = document.project.scenes[0]
    obj = SceneObject()
    rule = Constraint(owner_id=obj.id, kind="example.custom")
    document.execute(
        ScenePatch(
            "Add custom solver fixture",
            scene.id,
            {"objects": (), "constraints": ()},
            {"objects": (obj,), "constraints": (rule,)},
        )
    )
    assert document.animation.pose.nodes[obj.id].world_matrix[4:] == (17, 23)
    assert RigService(document).preview_pose() == document.animation.pose
    with pytest.raises(TypeError):
        document.constraint_solvers["example.custom"] = solve
