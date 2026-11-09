"""Dependency-complete memoization for built-in deformers, independent of sampling order."""

from dataclasses import replace

from rigora.domain.entities import Bone, Deformer, SceneObject, Skeleton
from rigora.domain.mesh_geometry import grid_mesh
from rigora.domain.project import Scene
from rigora.engine.deformation import IDENTITY, DeformationPlan
from rigora.engine.evaluation import SceneEvaluator


def skinned_scene():
    """Build independent skinned parts sharing a bind set but using different bone weights."""
    bones = (Bone(), Bone(), Bone())
    objects = (SceneObject(), SceneObject())
    # Each mesh keeps its own vertex/triangle identity graph.
    parts = []
    for i, obj in enumerate(objects):
        mesh = grid_mesh(100, 100, 4, 4)
        parts.append(
            replace(
                mesh,
                object_id=obj.id,
                vertices=tuple(replace(v, weights={bones[i].id: 1}) for v in mesh.vertices),
            )
        )
    meshes = tuple(parts)
    stages = tuple(
        Deformer(
            owner_id=m.id,
            kind="skinning",
            parameters={"bind_matrices": {b.id: IDENTITY for b in bones}},
        )
        for m in meshes
    )
    return (
        Scene(objects=objects, skeletons=(Skeleton(bones=bones),), meshes=meshes, deformers=stages),
        meshes,
        bones,
    )


def test_only_changed_skin_dependencies_recompute_and_seek_order_matches_fresh_evaluators():
    """Unweighted bind motion reuses pixels; weighted bones and object inverses invalidate."""
    scene, meshes, bones = skinned_scene()
    evaluator = SceneEvaluator(scene)
    baseline = evaluator.evaluate(0)
    first, second = meshes[0].id, meshes[1].id
    moved = evaluator.evaluate(0, overrides={(bones[0].id, "transform.rotation"): 25})
    assert moved.meshes[first] is not baseline.meshes[first]
    assert moved.meshes[second] is baseline.meshes[second]
    for overrides in (
        {(bones[0].id, "transform.rotation"): 25},
        {(bones[2].id, "transform.x"): 55},
        {(scene.objects[0].id, "transform.scale_x"): 2},
        {},
    ):
        result = evaluator.evaluate(0, overrides=overrides)
        expected = SceneEvaluator(scene).evaluate(0, overrides=overrides)
        assert result.meshes == expected.meshes and result.warnings == expected.warnings
    assert len(evaluator.deformation._mesh_cache) == 2


def test_unused_binding_validity_and_image_area_pins_are_cache_dependencies():
    """A missing unused bind still diagnoses, and pins can depend on an otherwise unused bone."""
    scene, meshes, bones = skinned_scene()
    mesh = replace(
        meshes[0],
        extra={
            "area_pins": [
                {
                    "bone_id": bones[2].id,
                    "x": 50,
                    "y": 50,
                    "radius": 100,
                    "bone_bind": IDENTITY,
                    "object_bind": IDENTITY,
                }
            ]
        },
    )
    scene = replace(scene, meshes=(mesh, meshes[1]))
    evaluator = SceneEvaluator(scene)
    first = evaluator.evaluate(0)
    moved = evaluator.evaluate(0, overrides={(bones[2].id, "transform.x"): 30})
    assert moved.meshes[mesh.id].positions != first.meshes[mesh.id].positions
    assert (
        moved.meshes
        == SceneEvaluator(scene).evaluate(0, overrides={(bones[2].id, "transform.x"): 30}).meshes
    )
    nodes = dict(moved.nodes)
    del nodes[bones[2].id]
    result, warnings = evaluator.deformation.evaluate(nodes, {})
    expected, expected_warnings = DeformationPlan(scene).evaluate(nodes, {})
    assert warnings and warnings == expected_warnings and result == expected


def test_vertex_and_nested_deformer_values_invalidate_only_the_affected_mesh():
    """Memo keys include raw vertices and stage parameters without retaining a frame history."""
    obj = SceneObject()
    mesh = replace(grid_mesh(100, 100, 2, 2), object_id=obj.id)
    stage = Deformer(owner_id=mesh.id, kind="ffd")
    scene = Scene(objects=(obj,), meshes=(mesh,), deformers=(stage,))
    evaluator = SceneEvaluator(scene)
    nodes = evaluator.evaluate(0).nodes
    plan = evaluator.deformation
    baseline, _ = plan.evaluate(nodes, {})
    for values in (
        {(mesh.vertices[0].id, "x"): 20},
        {(stage.id, "parameters.controls.0.0"): 35},
        {},
    ):
        result = plan.evaluate(nodes, values)
        expected = DeformationPlan(scene).evaluate(nodes, values)
        assert result == expected
    assert baseline == plan.evaluate(nodes, {})[0]
    assert len(plan._mesh_cache) == 1


def test_custom_and_replaced_builtin_solvers_always_receive_the_full_context():
    """Plugins can observe unrelated nodes and are never incorrectly memoized as built-ins."""
    scene, meshes, bones = skinned_scene()
    calls = []

    def custom(context):
        calls.append(context.mesh.id)
        x = context.nodes[bones[2].id].world_matrix[4]
        return tuple((p[0] + x, p[1]) for p in context.points)

    evaluator = SceneEvaluator(scene, deformers={"skinning": custom})
    evaluator.evaluate(0)
    evaluator.evaluate(0)
    result = evaluator.evaluate(0, overrides={(bones[2].id, "transform.x"): 25})
    assert len(calls) == 6
    assert result.meshes[meshes[0].id].positions[0][0] == 25
    assert not evaluator.deformation._mesh_cache
