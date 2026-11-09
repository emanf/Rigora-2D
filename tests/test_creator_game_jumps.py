"""Game jumps anticipate, leave the floor, recover and bake into ordinary editable actions."""

import math

import pytest

from rigora.application_services.character_creation import build_character
from rigora.application_services.documents import DocumentService
from rigora.domain.character_recipe import CharacterRecipe
from rigora.domain.illustration_catalog import CREATOR_DESIGNS
from rigora.infrastructure.illustration_motion import duration, world_joints


@pytest.mark.parametrize("design", CREATOR_DESIGNS, ids=lambda d: d.id)
@pytest.mark.parametrize("action", ("Jump", "Hop", "High jump", "Crouch", "Stretch"))
def test_new_actions_move_preserve_lengths_and_return_to_initial_pose(design, action):
    first = world_joints(design, "Side", action, 0)
    last = world_joints(design, "Side", action, 1)
    changed = False
    for i in range(41):
        pose = world_joints(design, "Side", action, i / 40)
        for name, joint in pose.items():
            assert joint.length == pytest.approx(first[name].length)
            assert all(math.isfinite(v) for v in (*joint.root, *joint.tip))
            changed |= math.dist(joint.tip, first[name].tip) > 1
    assert changed
    for name in first:
        assert first[name].root == pytest.approx(last[name].root)
        assert first[name].tip == pytest.approx(last[name].tip)


@pytest.mark.parametrize("action", ("Jump", "Hop", "High jump"))
def test_human_jump_has_grounded_anticipation_flight_and_a_soft_landing(action):
    design = CREATOR_DESIGNS[0]
    poses = [world_joints(design, "Side", action, i / 100) for i in range(101)]
    initial = poses[0]["hips"].root[1]
    anticipation = max(poses[:35], key=lambda p: p["hips"].root[1])
    assert anticipation["hips"].root[1] > initial + design.leg * 0.15
    assert max(p["hips"].root[1] for p in poses[70:]) > initial + design.leg * 0.1
    assert (
        max(min(-12 - p["foot." + s].root[1] for s in ("R", "L")) for p in poses) > design.leg * 0.3
    )
    assert max(abs(anticipation["foot." + s].root[1] + 12) for s in ("R", "L")) < design.leg * 0.06
    assert all(p["foot." + s].root[1] <= -11 for p in poses for s in ("R", "L"))


def test_new_actions_are_editable_clips_with_real_engine_motion():
    document = DocumentService()
    actions = ("Jump", "Hop", "High jump", "Crouch", "Stretch")
    build_character(CharacterRecipe(motions=actions), scratch=document)
    for clip in document.scene.clips:
        assert not clip.loop
        document.select_animation_clip(clip.id)
        first = document.animation.evaluate(0)
        middle = document.animation.evaluate(duration(CREATOR_DESIGNS[0], clip.name) * 0.45)
        assert not middle.warnings
        assert any(
            first.nodes[b.id].world_matrix != middle.nodes[b.id].world_matrix
            for b in document.scene.skeletons[0].bones
        )
