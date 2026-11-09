"""Selectable run styles have distinct choreography, fixed limbs and seamless editable loops."""

import math

import pytest

from rigora.application_services.character_creation import build_character
from rigora.application_services.documents import DocumentService
from rigora.domain.character_recipe import MOTION_CHOICES, RUN_ACTIONS, CharacterRecipe
from rigora.domain.illustration_catalog import CREATOR_DESIGNS, design_by_id
from rigora.infrastructure.illustration_motion import duration, world_joints


@pytest.mark.parametrize("design", CREATOR_DESIGNS, ids=lambda d: d.id)
def test_run_choices_have_distinct_poses_at_normalized_time_and_fixed_lengths(design):
    signatures = []
    baseline = world_joints(design, "Side", rest=True)
    for action in RUN_ACTIONS:
        assert action in MOTION_CHOICES
        assert 16 <= duration(design, action) <= 48
        poses = [world_joints(design, "Side", action, i / 32) for i in range(33)]
        signatures.append(
            tuple(
                round(v, 3)
                for pose in poses[:-1]
                for name in ("foot.R", "hand.R", "hips")
                for v in pose[name].root
            )
        )
        for pose in poses:
            for name, joint in pose.items():
                # The preserved animal Run has an authored flexible torso.
                # New run variants keep the torso as well as the limbs rigid.
                if design.anatomy not in ("human", "robot") and action == "Run" and name == "spine":
                    continue
                assert joint.length == pytest.approx(baseline[name].length)
                assert all(math.isfinite(v) for v in (*joint.root, *joint.tip))
        for name in poses[0]:
            assert poses[0][name].root == pytest.approx(poses[-1][name].root)
            assert poses[0][name].tip == pytest.approx(poses[-1][name].tip)
    assert len(set(signatures)) == len(RUN_ACTIONS) == 7


def test_all_run_choices_bake_as_separately_selectable_repeating_actions():
    doc = DocumentService()
    build_character(CharacterRecipe(design_id="dot", motions=RUN_ACTIONS), scratch=doc)
    assert tuple(c.name for c in doc.scene.clips) == RUN_ACTIONS
    for clip in doc.scene.clips:
        assert clip.loop
        doc.select_animation_clip(clip.id)
        first = doc.animation.evaluate(0, loop=True)
        last = doc.animation.evaluate(clip.out_frame + 1, loop=True)
        middle = doc.animation.evaluate((clip.out_frame + 1) * 0.37, loop=True)
        assert not middle.warnings
        assert any(
            first.nodes[b.id].world_matrix != middle.nodes[b.id].world_matrix
            for b in doc.scene.skeletons[0].bones
        )
        for bone in doc.scene.skeletons[0].bones:
            assert first.nodes[bone.id].world_matrix == pytest.approx(
                last.nodes[bone.id].world_matrix
            )


@pytest.mark.parametrize("action", RUN_ACTIONS)
def test_run_styles_match_baked_trajectories_and_have_no_velocity_pop(action):
    design = design_by_id("dot")
    epsilon = 1e-5
    before, seam, after = [
        world_joints(design, "Side", action, t) for t in (1 - epsilon, 0, epsilon)
    ]
    for name in seam:
        incoming = tuple((seam[name].tip[i] - before[name].tip[i]) / epsilon for i in (0, 1))
        outgoing = tuple((after[name].tip[i] - seam[name].tip[i]) / epsilon for i in (0, 1))
        assert math.dist(incoming, outgoing) < 1
    doc = DocumentService()
    build_character(CharacterRecipe(design_id="dot", view="Side", motions=(action,)), scratch=doc)
    length = duration(design, action)
    bones = [
        b
        for b in doc.scene.skeletons[0].bones
        if b.name in ("hand.R", "hand.L", "foot.R", "foot.L")
    ]
    previous = {}
    for i in range(121):
        phase = i / 120
        pose = doc.animation.evaluate(phase * length, loop=True)
        expected = world_joints(design, "Side", action, phase)
        for bone in bones:
            point = pose.nodes[bone.id].world_matrix[4:]
            assert math.dist(point, expected[bone.name].root) < design.leg * 0.07
            assert math.dist(point, previous.get(bone.id, point)) < design.leg * 0.18
            previous[bone.id] = point
