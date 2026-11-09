"""Object roots anchor spring bases without consuming the first deforming bone."""

from dataclasses import replace

import pytest

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.character_creation import CharacterCreationService, build_character
from rigora.application_services.documents import DocumentService
from rigora.application_services.dynamics import DynamicsService
from rigora.application_services.rigging import RigService
from rigora.domain.character_recipe import CharacterRecipe
from rigora.domain.geometry import transform_point
from rigora.engine.springs import SpringSimulation


def test_first_object_bone_springs_around_its_base_and_bakes_without_double_placement(tmp_path):
    """A premade object's real root stays fixed while its first bone deforms and exports keys."""
    doc = DocumentService()
    doc.new()
    owner = CharacterCreationService(doc).create(
        build_character(CharacterRecipe(design_id="sumi", name="Sumi", motions=()))
    )
    doc.set_animation_context(None)
    service = DynamicsService(doc)
    root = next(b.id for b in service.scene.skeletons[0].bones if not b.extra.get("rig_root"))
    service.assign_group((root,), group="Body", frequency=2, damping=0.3, gravity=900)
    rule = next(r for r in service.scene.constraints if r.owner_id == root and r.kind == "spring")
    assert rule.extra["spring_object_root"] and service.group_members("Body") == (root,)
    edit = AnimationEditingService(doc)
    edit.key(owner, "transform.x", 0, 0)
    edit.key(owner, "transform.x", 8, 120)
    edit.key(owner, "transform.y", 0, 0)
    edit.key(owner, "transform.y", 8, 100)
    edit.clip_settings(out_frame=24)
    evaluator = doc.animation.evaluator
    pose = evaluator.evaluate(12)
    primary_pose = {n.id: n for n in evaluator.sample_kinematic(12)}
    assert not pose.warnings
    assert pose.nodes[owner] == primary_pose[owner]
    assert pose.nodes[root].world_matrix[4:] == pytest.approx(primary_pose[root].world_matrix[4:])
    assert pose.nodes[root].local.rotation != pytest.approx(primary_pose[root].local.rotation)
    reference = pose.nodes[root].world_matrix
    evaluator.evaluate(24)
    assert evaluator.evaluate(12).nodes[root].world_matrix == pytest.approx(reference)
    service.bake("Body", tail_seconds=0)
    baked = doc.animation.evaluate(12)
    assert baked.nodes[root].world_matrix == pytest.approx(reference)
    for key, mesh in pose.meshes.items():
        for expected, actual in zip(mesh.positions, baked.meshes[key].positions, strict=True):
            assert actual == pytest.approx(expected)
    path = tmp_path / "root-spring.rigora"
    doc.save(path)
    other = DocumentService()
    other.open(path)
    other.select_animation_clip(service.clip.id)
    assert other.animation.evaluate(12).nodes[root].world_matrix == pytest.approx(reference)


def test_object_first_bone_release_respects_pivots_and_carries_descendants():
    """Object-anchor spring state can be excited without inserting or moving a root bone."""
    from test_dynamics import animated_chain

    doc, root, tip = animated_chain()
    rig = RigService(doc)
    rig.update(
        root,
        transform=replace(
            rig.bone(root).transform,
            pivot_x=12,
            pivot_y=7,
            scale_x=1.2,
            scale_y=0.7,
        ),
    )
    service = DynamicsService(doc)
    actor = service.scene.characters[0]
    doc.set_animation_context(
        actor.id, frozenset({actor.id, service.scene.skeletons[0].id, root, tip})
    )
    service.assign_group((root, tip), group="Branch", frequency=2, gravity=0)
    rules = tuple(c for c in service.scene.constraints if c.kind == "spring")
    assert {r.owner_id for r in rules} == {root, tip}
    nodes = list(doc.animation.evaluator.sample_kinematic(0))
    sim = SpringSimulation()
    sim.advance(nodes, rules, 1 / 60)
    sim.excite(nodes, rules)
    result = {n.id: n for n in sim.advance(nodes, rules, 1 / 60)}
    original = next(n for n in nodes if n.id == root)
    assert result[root].local.rotation != original.local.rotation
    assert result[root].world_matrix[4:] == pytest.approx(original.world_matrix[4:])
    assert result[tip].world_matrix[4:] == pytest.approx(
        transform_point(
            result[root].world_matrix,
            result[root].length,
            0,
        )
    )
