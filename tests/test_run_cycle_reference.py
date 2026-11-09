"""A running gait has recovery, flight and fixed limbs without changing the approved walk."""

import math

import pytest

from rigora.application_services.character_creation import build_character
from rigora.application_services.documents import DocumentService
from rigora.domain.character_recipe import CharacterRecipe
from rigora.domain.illustration_catalog import CREATOR_DESIGNS, TEMPLATE_DESIGNS, design_by_id
from rigora.infrastructure.illustration_motion import duration, world_joints


@pytest.mark.parametrize(
    "design",
    [d for d in (*TEMPLATE_DESIGNS, *CREATOR_DESIGNS) if d.anatomy in ("human", "robot")],
    ids=lambda d: d.id,
)
def test_run_has_clear_flight_and_folded_recovery_instead_of_a_fast_walk(design):
    poses = [world_joints(design, "Side", "Run", i / 120) for i in range(120)]
    assert (
        max(min(-12 - p[f"foot.{s}"].root[1] for s in ("R", "L")) for p in poses)
        > design.leg * 0.15
    )
    assert max(abs((p["thigh.R"].angle - p["shin.R"].angle + 180) % 360 - 180) for p in poses) > 95
    assert any(
        p["foot.R"].root[0] < p["hips"].root[0] and p["foot.R"].root[1] < -12 - design.leg * 0.6
        for p in poses
    )
    for pose in poses:
        assert abs(pose["spine"].angle + 90) <= 3.2
        for side in ("R", "L"):
            assert pose["thigh." + side].length == pytest.approx(design.leg)
            assert pose["shin." + side].length == pytest.approx(design.leg)
            assert pose["upper_arm." + side].length == pytest.approx(design.arm)
            assert pose["forearm." + side].length == pytest.approx(design.arm * 0.88)


def test_run_pose_and_velocity_repeat_without_a_loop_pop():
    design = design_by_id("dot")
    epsilon = 1e-5
    before, seam, after = [
        world_joints(design, "Side", "Run", t) for t in (1 - epsilon, 0, epsilon)
    ]
    end = world_joints(design, "Side", "Run", 1)
    for name, joint in seam.items():
        assert end[name].root == pytest.approx(joint.root)
        assert end[name].tip == pytest.approx(joint.tip)
        incoming = tuple((joint.tip[i] - before[name].tip[i]) / epsilon for i in (0, 1))
        outgoing = tuple((after[name].tip[i] - joint.tip[i]) / epsilon for i in (0, 1))
        assert math.dist(incoming, outgoing) < 1


@pytest.mark.parametrize("design_id", ("nova", "dot", "orbit"))
def test_baked_run_keeps_reference_trajectories_and_smooth_loop(design_id):
    """Editable engine keys preserve wrist/ankle trajectories and the periodic boundary."""
    document = DocumentService()
    build_character(
        CharacterRecipe(design_id=design_id, view="Side", motions=("Run",)), scratch=document
    )
    design = design_by_id(design_id)
    length = duration(design, "Run")
    bones = [
        bone
        for bone in document.scene.skeletons[0].bones
        if bone.name in ("hand.R", "hand.L", "foot.R", "foot.L")
    ]
    previous = {}
    start = document.animation.evaluate(0, loop=True)
    end = document.animation.evaluate(length, loop=True)
    for bone in bones:
        assert start.nodes[bone.id].world_matrix == pytest.approx(end.nodes[bone.id].world_matrix)
    for i in range(121):
        phase = i / 120
        pose = document.animation.evaluate(phase * length, loop=True)
        source = world_joints(design, "Side", "Run", phase)
        for bone in bones:
            point = pose.nodes[bone.id].world_matrix[4:]
            assert math.dist(point, source[bone.name].root) < design.leg * 0.06
            assert math.dist(point, previous.get(bone.id, point)) < design.leg * 0.15
            previous[bone.id] = point
