"""Exact frame reuse, clip invalidation, memory bounds and isolated animation forks."""

from dataclasses import replace

from rigora.application_services.animation import AnimationSession
from rigora.domain.entities import AnimationClip, Keyframe, SceneObject, Timeline, Track
from rigora.domain.project import Scene


def animated_session():
    """Build two clips that deliberately produce different values at the same sample frame."""
    obj = SceneObject()
    first = Timeline(
        tracks=(
            Track(
                owner_id=obj.id,
                property_path="transform.x",
                keyframes=(
                    Keyframe(frame=0, value=0),
                    Keyframe(frame=24, value=24),
                ),
            ),
        )
    )
    second = Timeline(
        tracks=(
            replace(
                first.tracks[0],
                id=SceneObject().id,
                keyframes=(
                    Keyframe(frame=0, value=100),
                    Keyframe(frame=24, value=124),
                ),
            ),
        )
    )
    clips = (AnimationClip(timeline_id=first.id), AnimationClip(timeline_id=second.id))
    scene = Scene(objects=(obj,), timelines=(first, second), clips=clips)
    return AnimationSession(scene, clips[0].id), obj.id, clips[1].id


def test_exact_frames_reuse_without_quantizing_and_clip_switch_discards_old_results():
    """Fractional samples remain exact, while a new clip cannot reuse another clip's values."""
    session, obj, clip = animated_session()
    session.cache_enabled = True
    one = session.evaluate(12.25)
    assert session.evaluate(12.25) is one
    assert session.pose_cache.hits == 1
    assert session.evaluate(12.5).nodes[obj].local.x == 12.5
    session.select_clip(clip)
    assert not session.pose_cache.entries
    assert session.evaluate(12.25).nodes[obj].local.x == 112.25


def test_pose_cache_is_bounded_and_forks_do_not_share_mutable_cache_state():
    """Eviction preserves evaluation correctness and independent render workers."""
    session, obj, _ = animated_session()
    session.cache_enabled = True
    session.pose_cache.limit = 2048
    for frame in range(10):
        assert session.evaluate(frame).nodes[obj].local.x == frame
        assert session.pose_cache.bytes <= 2048
    assert len(session.pose_cache.entries) <= 2
    before = tuple(session.pose_cache.entries)
    scratch = session.fork()
    assert scratch.pose_cache is not session.pose_cache and not scratch.pose_cache.entries
    assert not scratch.cache_enabled
    scratch.evaluate(2)
    assert tuple(session.pose_cache.entries) == before
