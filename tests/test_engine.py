"""Numerical contracts for stateless animation sampling and affine geometry."""

from dataclasses import replace
from uuid import uuid4

import pytest

from rigora.domain.entities import (
    AnimationClip,
    Bone,
    Constraint,
    Deformer,
    Group,
    Keyframe,
    Layer,
    SceneObject,
    Skeleton,
    Timeline,
    Track,
    Transform,
)
from rigora.domain.geometry import multiply, transform_point
from rigora.domain.project import Scene
from rigora.engine.evaluation import SceneEvaluator
from rigora.engine.sampling import CompiledTrack, EvaluationError
from rigora.engine.time import FrameRange


def test_affine_pivot_rotation_scale_and_parent_composition():
    local = Transform(x=10, y=20, rotation=90, scale_x=2, pivot_x=5).matrix()
    assert transform_point(local, 5, 0) == pytest.approx((15, 20))
    parent = Transform(x=100, rotation=90).matrix()
    assert transform_point(multiply(parent, local), 5, 0) == pytest.approx((80, 15))


@pytest.mark.parametrize(
    "interpolation,expected", [("step", 0), ("linear", 2.5), ("bezier", 1.5625)]
)
def test_sampling_endpoints_backward_seeks_and_default_easing(interpolation, expected):
    track = Track(
        owner_id="00000000-0000-0000-0000-000000000001",
        property_path="transform.x",
        keyframes=(
            Keyframe(frame=0, value=0, interpolation=interpolation),
            Keyframe(frame=10, value=10),
        ),
    )
    compiled = CompiledTrack(track)
    assert compiled.sample(-1) == 0
    assert compiled.sample(11) == 10
    assert compiled.sample(10) == 10
    assert compiled.sample(2.5) == pytest.approx(expected)
    assert compiled.sample(2.5) == compiled.sample(2.5)


def test_explicit_bezier_handles_invert_time_and_allow_value_overshoot():
    owner = "00000000-0000-0000-0000-000000000001"
    track = Track(
        owner_id=owner,
        property_path="transform.x",
        keyframes=(
            Keyframe(frame=0, value=0, interpolation="bezier", tangent_out=(2, 20)),
            Keyframe(frame=10, value=10, tangent_in=(-8, 20)),
        ),
    )
    compiled = CompiledTrack(track)
    assert compiled.sample(0) == 0
    assert compiled.sample(10) == 10
    # At cubic parameter 0.5: x = 2.75 and y = 20.
    assert compiled.sample(2.75) == pytest.approx(20, abs=1e-9)
    invalid = Track(
        owner_id=owner,
        property_path="transform.x",
        keyframes=(
            Keyframe(frame=0, value=0, interpolation="bezier", tangent_out=(9, 0)),
            Keyframe(frame=10, value=10, tangent_in=(-9, 0)),
        ),
    )
    with pytest.raises(EvaluationError, match="time"):
        CompiledTrack(invalid)


@pytest.mark.parametrize("value", [True, "hello", {}, 10**400])
def test_unsupported_key_values_fail_before_playback(value):
    track = Track(
        owner_id="00000000-0000-0000-0000-000000000001",
        property_path="transform.x",
        keyframes=(Keyframe(frame=0, value=value),),
    )
    with pytest.raises(EvaluationError):
        CompiledTrack(track)


def test_hierarchy_animation_blending_and_stateless_random_access():
    group = Group(transform=Transform(x=100, rotation=90))
    obj = SceneObject(parent_id=group.id, transform=Transform(x=10, scale_x=2))
    root = Bone(transform=Transform(x=300), length=50)
    child = Bone(parent_id=root.id, transform=Transform(x=50), length=30)
    timeline = Timeline(
        tracks=(
            Track(
                owner_id=obj.id,
                property_path="transform.x",
                weight=0.5,
                keyframes=(Keyframe(frame=0, value=10), Keyframe(frame=10, value=30)),
            ),
            Track(
                owner_id=obj.id,
                property_path="transform.x",
                blend_mode="additive",
                weight=0.5,
                keyframes=(Keyframe(frame=0, value=4),),
            ),
            Track(
                owner_id=obj.id,
                property_path="transform.scale_x",
                blend_mode="additive",
                weight=0.5,
                keyframes=(Keyframe(frame=0, value=3),),
            ),
            Track(
                owner_id=root.id,
                property_path="transform.rotation",
                keyframes=(Keyframe(frame=0, value=0), Keyframe(frame=10, value=180)),
            ),
            Track(
                owner_id=child.id, property_path="length", keyframes=(Keyframe(frame=0, value=40),)
            ),
        )
    )
    clip = AnimationClip(timeline_id=timeline.id, out_frame=10)
    scene = Scene(
        groups=(group,),
        objects=(obj,),
        skeletons=(Skeleton(bones=(child, root)),),
        timelines=(timeline,),
        clips=(clip,),
    )
    evaluator = SceneEvaluator(scene)
    at_five = evaluator.evaluate(5)
    assert at_five.nodes[obj.id].local.x == 17
    assert at_five.nodes[obj.id].local.scale_x == 4
    assert transform_point(at_five.nodes[obj.id].world_matrix, 0, 0) == pytest.approx((100, 17))
    assert transform_point(at_five.nodes[child.id].world_matrix, 0, 0) == pytest.approx((300, 50))
    assert at_five.nodes[child.id].length == 40
    for frame in (10, -5, 2.5, 0, 8, 5):
        evaluator.evaluate(frame)
    assert evaluator.evaluate(5) == at_five
    assert obj.transform.x == 10 and child.length == 30
    with pytest.raises(TypeError):
        at_five.nodes[obj.id] = at_five.nodes[child.id]


def test_inclusive_time_conversion_loop_and_single_frame():
    span = FrameRange(10, 19, 10)
    assert span.duration_frames == 10 and span.duration_seconds == 1
    assert span.seconds_to_frame(0.5) == 15 and span.frame_to_seconds(15) == 0.5
    assert span.normalize(20, loop=True) == 10
    assert span.normalize(9, loop=True) == 19
    assert span.normalize(19.5, loop=True) == 19.5
    assert span.normalize(20) == 19
    assert FrameRange(4, 4, 24).normalize(100, loop=True) == 4
    with pytest.raises(EvaluationError):
        span.normalize(float("nan"))


def test_deep_hierarchy_cycles_missing_parents_and_numeric_overflow():
    groups = []
    for _ in range(1200):
        groups.append(Group(parent_id=groups[-1].id if groups else None, transform=Transform(x=1)))
    pose = SceneEvaluator(Scene(groups=tuple(reversed(groups)))).evaluate(0)
    assert pose.nodes[groups[-1].id].world_matrix[4] == 1200
    with pytest.raises(EvaluationError, match="cycle"):
        SceneEvaluator(Scene(groups=(replace(groups[0], parent_id=groups[0].id),)))
    with pytest.raises(EvaluationError, match="missing"):
        SceneEvaluator(Scene(objects=(SceneObject(parent_id=str(uuid4())),)))
    huge = Group(transform=Transform(x=1e308))
    with pytest.raises(EvaluationError, match="finite"):
        SceneEvaluator(
            Scene(
                groups=(huge,),
                objects=(SceneObject(parent_id=huge.id, transform=Transform(x=1e308)),),
            )
        ).evaluate(0)


def test_visibility_render_order_and_deferred_stages_are_explicit():
    layer = Layer(visible=False)
    hidden = Group(layer_id=layer.id)
    one = SceneObject(parent_id=hidden.id)
    two = SceneObject()
    scene = Scene(
        layers=(layer,),
        groups=(hidden,),
        objects=(one, two),
        draw_order=(one.id,),
        constraints=(Constraint(owner_id=one.id, kind="ik"),),
        deformers=(Deformer(owner_id=one.id, kind="lattice"),),
    )
    pose = SceneEvaluator(scene).evaluate(0)
    assert not pose.nodes[one.id].visible and pose.nodes[two.id].visible
    assert pose.render_order == (two.id, one.id)
    assert len(pose.warnings) == 2 and "not evaluated" in pose.warnings[0]


def test_bone_endpoint_overflow_and_incompatible_parent_are_rejected():
    bone = Bone(length=1e308, transform=Transform(scale_x=1e308))
    with pytest.raises(EvaluationError, match="endpoint"):
        SceneEvaluator(Scene(skeletons=(Skeleton(bones=(bone,)),))).evaluate(0)
    other = Bone(parent_id=bone.id)
    with pytest.raises(EvaluationError, match="skeleton"):
        SceneEvaluator(Scene(skeletons=(Skeleton(bones=(bone,)), Skeleton(bones=(other,)))))


def test_unsupported_properties_and_negative_animated_bone_length():
    bone = Bone()
    track = Track(
        owner_id=bone.id, property_path="length", keyframes=(Keyframe(frame=0, value=-1),)
    )
    timeline = Timeline(tracks=(track,))
    scene = Scene(
        skeletons=(Skeleton(bones=(bone,)),),
        timelines=(timeline,),
        clips=(AnimationClip(timeline_id=timeline.id),),
    )
    with pytest.raises(EvaluationError, match="negative"):
        SceneEvaluator(scene).evaluate(0)
    unsupported = replace(track, property_path="future.unknown")
    with pytest.raises(EvaluationError, match="unsupported"):
        SceneEvaluator(replace(scene, timelines=(replace(timeline, tracks=(unsupported,)),)))
