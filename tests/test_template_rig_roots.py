"""Template masters sit at authored attachments without shifting geometry or source actions."""

from dataclasses import replace

import pytest

from rigora.application_services.character_creation import build_character
from rigora.application_services.content_library import content_project
from rigora.application_services.illustration_cache import recipe_for
from rigora.domain.entities import Skeleton
from rigora.domain.geometry import affine, transform_point
from rigora.domain.illustration_catalog import CREATOR_DESIGNS, TEMPLATE_DESIGNS
from rigora.domain.project import Scene
from rigora.domain.validation import json_copy
from rigora.engine.evaluation import SceneEvaluator
from rigora.infrastructure.illustration_motion import world_joints
from rigora.infrastructure.motion_catalog import skeletons


@pytest.mark.parametrize("item", skeletons(), ids=lambda item: item.name)
def test_bare_template_master_matches_primary_attachment_and_retains_authored_endpoints(item):
    """Serialized rigs include the same visible master as the placed and previewed resource."""
    rig = Skeleton.from_dict(json_copy(item.payload["skeleton"]))
    masters = [b for b in rig.bones if b.extra.get("rig_root")]
    assert len(masters) == 1
    master = masters[0]
    primary = next(b for b in rig.bones if not b.extra.get("rig_root"))
    pose = SceneEvaluator(Scene(skeletons=(rig,))).evaluate(0)
    assert master.length == 0 and master.parent_id is None
    assert pose.nodes[master.id].world_matrix[4:] == pytest.approx(
        pose.nodes[primary.id].world_matrix[4:]
    )
    assert master.id not in rig.extra["semantic_mapping"].values()
    endpoints = [
        transform_point(pose.nodes[b.id].world_matrix, x, 0)
        for b in rig.bones
        if b.id != master.id
        for x in (0, b.length)
    ]
    assert (
        min(p[0] for p in endpoints),
        min(p[1] for p in endpoints),
        max(p[0] for p in endpoints),
        max(p[1] for p in endpoints),
    ) == pytest.approx(item.payload["rig_bounds"])


@pytest.mark.parametrize("design", (*TEMPLATE_DESIGNS, *CREATOR_DESIGNS), ids=lambda d: d.id)
def test_character_template_root_and_every_action_retain_authored_world_poses(design):
    """Root rebasing preserves absolute animation keys, bind poses and every anatomical joint."""
    recipe = recipe_for(design)
    built = build_character(recipe)
    scene = content_project(built.item, built.files).scenes[0]
    rig = scene.skeletons[0]
    master = next(b for b in rig.bones if b.extra.get("rig_root"))
    rest_joints = world_joints(design, recipe.view, rest=True)
    primary = next(j for j in rest_joints.values() if j.parent is None)
    assert (master.transform.x, master.transform.y) == pytest.approx(primary.root)
    rest = SceneEvaluator(replace(scene, clips=(), timelines=())).evaluate(0)
    for bone in rig.bones:
        if bone.id != master.id:
            joint = rest_joints[bone.name]
            assert rest.nodes[bone.id].world_matrix == pytest.approx(
                affine(*joint.root, joint.angle, 1, 1, 0, 0)
            )
    for clip in scene.clips:
        evaluator = SceneEvaluator(scene, clip.id)
        frame = 8
        from rigora.infrastructure.illustration_motion import duration

        expected = world_joints(design, recipe.view, clip.name, frame / duration(design, clip.name))
        pose = evaluator.evaluate(frame)
        assert not pose.warnings
        assert pose.nodes[master.id].world_matrix == rest.nodes[master.id].world_matrix
        for bone in rig.bones:
            if bone.id == master.id:
                continue
            joint = expected[bone.name]
            assert pose.nodes[bone.id].world_matrix == pytest.approx(
                affine(*joint.root, joint.angle, 1, 1, 0, 0), abs=1e-7
            )
