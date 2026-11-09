"""Numerical deformation, ordered composition and sampled geometry contracts."""

from dataclasses import replace

import pytest

from rigora.domain.entities import (
    AnimationClip,
    Bone,
    Constraint,
    Deformer,
    Group,
    Keyframe,
    SceneObject,
    Skeleton,
    Timeline,
    Track,
    Transform,
)
from rigora.domain.mesh_geometry import grid_mesh
from rigora.domain.project import Scene
from rigora.engine.evaluation import SceneEvaluator


def scene_with(kind="ffd", **parameters):
    """Build a small fixed-size quad field with one editable stage."""
    obj = SceneObject()
    mesh = replace(grid_mesh(100, 100, 2, 2), object_id=obj.id)
    stage = Deformer(owner_id=mesh.id, kind=kind, parameters=parameters)
    return Scene(objects=(obj,), meshes=(mesh,), deformers=(stage,)), mesh, stage


def test_ffd_and_lattice_have_distinct_basis_and_identity():
    scene, mesh, stage = scene_with()
    assert SceneEvaluator(scene).evaluate(0).meshes[mesh.id].positions[4] == (50, 50)
    controls = [[0, 0] for _ in range(9)]
    controls[4] = [40, 20]
    stage = replace(stage, parameters={"controls": controls})
    scene = replace(scene, deformers=(stage,))
    assert SceneEvaluator(scene).evaluate(0).meshes[mesh.id].positions[4] == (60, 55)
    scene = replace(scene, deformers=(replace(stage, kind="lattice"),))
    assert SceneEvaluator(scene).evaluate(0).meshes[mesh.id].positions[4] == (90, 70)


def test_order_mask_intensity_pin_and_invalid_stage_rollback():
    scene, mesh, stage = scene_with("transform", x=20, intensity=0.5)
    vertex = mesh.vertices[0]
    stage = replace(stage, parameters={**stage.parameters, "weights": {vertex.id: 0.5}})
    broken = Deformer(owner_id=mesh.id, kind="ffd", parameters={"columns": 1}, order=1)
    scale = Deformer(
        owner_id=mesh.id, kind="transform", parameters={"scale_x": 2, "pivot_x": 0}, order=2
    )
    mesh = replace(mesh, vertices=(*mesh.vertices[:-1], replace(mesh.vertices[-1], pinned=True)))
    scene = replace(scene, meshes=(mesh,), deformers=(stage, broken, scale))
    pose = SceneEvaluator(scene).evaluate(0)
    assert pose.meshes[mesh.id].positions[0] == (10, 0)
    assert pose.meshes[mesh.id].positions[1] == (100, 0)
    assert pose.meshes[mesh.id].positions[-1] == (100, 100)
    assert len(pose.warnings) == 1


def test_skin_binding_uses_explicit_world_matrices_and_current_object_inverse():
    scene, mesh, _ = scene_with()
    obj = replace(scene.objects[0], transform=Transform(x=100))
    bone = Bone(transform=Transform(x=200))
    mesh = replace(mesh, vertices=tuple(replace(v, weights={bone.id: 1}) for v in mesh.vertices))
    skin = Deformer(
        owner_id=mesh.id,
        kind="skinning",
        parameters={
            "object_bind": obj.transform.matrix(),
            "bind_matrices": {bone.id: bone.transform.matrix()},
        },
    )
    scene = replace(
        scene,
        objects=(obj,),
        meshes=(mesh,),
        skeletons=(Skeleton(bones=(bone,)),),
        deformers=(skin,),
    )
    assert SceneEvaluator(scene).evaluate(0).meshes[mesh.id].positions[0] == (0, 0)
    bone = replace(bone, transform=Transform(x=230, rotation=90))
    scene = replace(scene, skeletons=(replace(scene.skeletons[0], bones=(bone,)),))
    assert SceneEvaluator(scene).evaluate(0).meshes[mesh.id].positions[0] == pytest.approx(
        (130, -100)
    )


def test_object_space_skin_cache_reuses_placement_but_invalidates_relative_edits():
    """Cached local geometry follows placement; bone and individual artwork changes reskin."""
    group = Group(transform=Transform(x=500))
    obj = SceneObject(parent_id=group.id, transform=Transform(x=100))
    bone = Bone(transform=Transform(x=200))
    mesh = replace(grid_mesh(100, 100, 2, 2), object_id=obj.id)
    mesh = replace(mesh, vertices=tuple(replace(v, weights={bone.id: 1}) for v in mesh.vertices))
    skin = Deformer(
        owner_id=mesh.id,
        kind="skinning",
        parameters={
            "object_bind": Transform(x=600).matrix(),
            "object_group": group.id,
            "object_group_bind": group.transform.matrix(),
            "bind_matrices": {bone.id: bone.transform.matrix()},
        },
    )
    evaluator = SceneEvaluator(
        Scene(
            groups=(group,),
            objects=(obj,),
            meshes=(mesh,),
            skeletons=(Skeleton(bones=(bone,)),),
            deformers=(skin,),
        )
    )
    original = evaluator.evaluate(0)
    placed = evaluator.evaluate(0, overrides={(group.id, "transform.x"): 550})
    assert placed.meshes[mesh.id] is original.meshes[mesh.id]
    artwork = evaluator.evaluate(0, overrides={(obj.id, "transform.x"): 120})
    assert artwork.meshes[mesh.id] is not original.meshes[mesh.id]
    assert artwork.meshes[mesh.id].positions[0] == (-20, 0)
    posed = evaluator.evaluate(0, overrides={(bone.id, "transform.x"): 230})
    assert posed.meshes[mesh.id].positions[0] == (30, 0)


def test_common_timeline_animates_vertices_controls_and_pin_leaves_statelessly():
    scene, mesh, stage = scene_with("ffd", controls=[[0, 0] for _ in range(9)])
    timeline = Timeline(
        tracks=(
            Track(
                owner_id=stage.id,
                property_path="parameters.controls.4.0",
                keyframes=(Keyframe(frame=0, value=0), Keyframe(frame=10, value=40)),
            ),
            Track(
                owner_id=mesh.vertices[0].id,
                property_path="y",
                keyframes=(Keyframe(frame=0, value=0), Keyframe(frame=10, value=10)),
            ),
        )
    )
    scene = replace(
        scene, timelines=(timeline,), clips=(AnimationClip(timeline_id=timeline.id, out_frame=10),)
    )
    evaluator = SceneEvaluator(scene)
    assert evaluator.evaluate(10).meshes[mesh.id].positions[4] == (60, 50)
    assert evaluator.evaluate(5).meshes[mesh.id].positions[4] == (55, 50)
    assert evaluator.evaluate(0).meshes[mesh.id].positions[0] == (0, 0)
    assert mesh.vertices[0].y == 0


@pytest.mark.parametrize(
    "kind", ["bend", "bulge", "twist", "squash_stretch", "pin", "vertex_offset", "lattice"]
)
def test_builtin_neutral_parameters_are_identity(kind):
    scene, mesh, _ = scene_with(kind)
    pose = SceneEvaluator(scene).evaluate(0)
    assert not pose.warnings
    for vertex, point in zip(mesh.vertices, pose.meshes[mesh.id].positions, strict=True):
        assert point == pytest.approx((vertex.x, vertex.y))


def test_pins_are_animatable_and_constraints_run_before_skinning():
    scene, mesh, stage = scene_with("pin")
    vertex = mesh.vertices[4]
    stage = replace(
        stage, parameters={"pins": {vertex.id: {"x": 70, "y": 50, "strength": 1}}, "radius": 100}
    )
    timeline = Timeline(
        tracks=(
            Track(
                owner_id=stage.id,
                property_path=f"parameters.pins.{vertex.id}.y",
                keyframes=(Keyframe(frame=0, value=50), Keyframe(frame=10, value=80)),
            ),
        )
    )
    scene = replace(
        scene,
        deformers=(stage,),
        timelines=(timeline,),
        clips=(AnimationClip(timeline_id=timeline.id, out_frame=10),),
    )
    assert SceneEvaluator(scene).evaluate(5).meshes[mesh.id].positions[4] == (70, 65)
    bone, target = Bone(), SceneObject(transform=Transform(x=25))
    mesh = replace(mesh, vertices=tuple(replace(v, weights={bone.id: 1}) for v in mesh.vertices))
    skin = Deformer(
        owner_id=mesh.id,
        kind="skinning",
        parameters={"bind_matrices": {bone.id: (1, 0, 0, 1, 0, 0)}},
    )
    rule = Constraint(owner_id=bone.id, target_id=target.id, kind="copy_transform")
    scene = replace(
        scene,
        objects=(*scene.objects, target),
        meshes=(mesh,),
        deformers=(skin,),
        constraints=(rule,),
        skeletons=(Skeleton(bones=(bone,)),),
        timelines=(),
        clips=(),
    )
    pose = SceneEvaluator(scene).evaluate(0)
    assert not pose.warnings
    assert pose.meshes[mesh.id].positions[4] == (75, 50)


def test_injected_deformer_cannot_mutate_parameter_inputs():
    scene, mesh, stage = scene_with("custom", controls=[[1, 2]])
    observed = []

    def solver(context):
        """Check nested ownership while returning a valid custom displacement field."""
        with pytest.raises(TypeError):
            context.parameters["controls"][0][0] = 55
        observed.append(context.parameters["controls"][0][0])
        return tuple((x + 5, y) for x, y in context.points)

    evaluator = SceneEvaluator(scene, deformers={"custom": solver})
    assert evaluator.evaluate(0).meshes[mesh.id].positions[4] == (55, 50)
    evaluator.evaluate(0)
    assert observed == [1, 1] and stage.parameters["controls"][0][0] == 1


def test_overlapping_pin_falloff_keeps_explicit_anchor_targets():
    scene, mesh, stage = scene_with("pin")
    left, right = mesh.vertices[0], mesh.vertices[1]
    stage = replace(
        stage,
        parameters={
            "radius": 300,
            "pins": {left.id: {"x": 10, "y": 20}, right.id: {"x": 70, "y": 30}},
        },
    )
    pose = SceneEvaluator(replace(scene, deformers=(stage,))).evaluate(0)
    assert pose.meshes[mesh.id].positions[0] == (10, 20)
    assert pose.meshes[mesh.id].positions[1] == (70, 30)
