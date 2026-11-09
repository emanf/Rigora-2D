"""Elapsed-time transport and shared-service state remain independent of authoring data."""

from dataclasses import replace

import pytest
from animation_fixtures import animation_example

from rigora.application_services.animation import AnimationSession
from rigora.application_services.commands import ProjectPatch
from rigora.application_services.documents import DocumentService
from rigora.domain.entities import AnimationClip, Keyframe, SceneObject, Timeline, Track
from rigora.domain.project import Scene, SceneSettings
from rigora.engine.playback import PlaybackController
from rigora.engine.sampling import EvaluationError
from rigora.engine.time import FrameRange


def test_transport_pause_stop_seek_loop_and_inclusive_duration():
    controller = PlaybackController(FrameRange(10, 19, 10))
    controller.play()
    assert controller.advance(0.5) == 15
    controller.pause()
    assert controller.advance(100) == 15
    controller.seek(12)
    controller.play()
    assert controller.advance(0.75) == pytest.approx(19.5)
    assert controller.is_playing
    assert controller.advance(0.05) == 19 and controller.state == "stopped"
    controller.play()
    assert controller.frame == 10
    controller.loop = True
    assert controller.advance(123.5) == 15
    controller.stop()
    assert controller.frame == 10 and controller.state == "stopped"
    controller.seek(-100)
    assert controller.frame == 10
    controller.seek(100)
    assert controller.frame == 19
    with pytest.raises(EvaluationError):
        controller.advance(-0.1)


def test_animation_session_arbitrary_evaluation_does_not_mutate_saved_model():
    obj = SceneObject()
    timeline = Timeline(
        tracks=(
            Track(
                owner_id=obj.id,
                property_path="transform.x",
                keyframes=(Keyframe(frame=0, value=0), Keyframe(frame=10, value=100)),
            ),
        )
    )
    clip = AnimationClip(timeline_id=timeline.id, out_frame=10, loop=True)
    other = replace(clip, id="00000000-0000-0000-0000-000000000099", name="Other", in_frame=5)
    scene = Scene(
        objects=(obj,), timelines=(timeline,), clips=(clip, other), settings=SceneSettings(fps=10)
    )
    before = scene.to_dict()
    session = AnimationSession(scene)
    direct = session.evaluate(5)
    assert session.playback.frame == 0 and direct.nodes[obj.id].local.x == 50
    session.play()
    assert session.advance(0.5) == direct
    session.seek(2)
    session.seek(5)
    assert session.pose == direct
    session.select_clip(other.id)
    assert session.playback.frame == 5 and session.pose.nodes[obj.id].local.x == 50
    assert scene.to_dict() == before


def test_single_frame_clip_stops_after_one_frame_and_rejects_nonfinite_time():
    playback = PlaybackController(FrameRange(7, 7, 24))
    playback.play()
    playback.advance(1 / 24)
    assert playback.frame == 7 and not playback.is_playing
    with pytest.raises(EvaluationError):
        playback.advance(float("inf"))


def test_saved_reopened_animation_matches_and_transport_never_dirties_project(tmp_path):
    sample = animation_example()
    doc = DocumentService()
    doc.new(sample.name)
    doc.execute(
        ProjectPatch("Load sample", {"scenes": doc.project.scenes}, {"scenes": sample.scenes})
    )
    path = tmp_path / "animation.rigora"
    doc.save(path)
    session = doc.animation
    expected = session.evaluate(23.5)
    session.play()
    session.advance(0.5)
    session.seek(23.5)
    assert session.pose == expected and not doc.dirty
    reopened = DocumentService()
    reopened.open(path)
    assert reopened.animation.evaluate(23.5) == expected
    assert reopened.animation is not session and reopened.animation.playback.frame == 0
    doc.update_settings(sample.name, "Edited scene", replace(sample.scenes[0].settings, fps=60))
    updated = doc.animation
    assert updated is not session and updated.playback.frame == 23.5
    assert updated.playback.range.fps == 60
    doc.undo()
    assert doc.animation.evaluate(23.5) == expected and not doc.dirty


def test_failed_seek_advance_and_clip_selection_retain_last_valid_runtime():
    from rigora.domain.entities import Bone, Skeleton

    bone = Bone(length=10)
    timeline = Timeline(
        tracks=(
            Track(
                owner_id=bone.id,
                property_path="length",
                keyframes=(Keyframe(frame=0, value=10), Keyframe(frame=10, value=-10)),
            ),
        )
    )
    clip = AnimationClip(timeline_id=timeline.id, out_frame=10)
    session = AnimationSession(
        Scene(skeletons=(Skeleton(bones=(bone,)),), timelines=(timeline,), clips=(clip,))
    )
    initial = session.pose
    with pytest.raises(EvaluationError, match="negative"):
        session.seek(10)
    assert session.pose is initial and session.playback.frame == 0
    session.play()
    with pytest.raises(EvaluationError, match="negative"):
        session.advance(10 / session.playback.range.fps)
    assert session.pose == initial and session.playback.frame == 0
    assert session.playback.state == "paused"
    with pytest.raises(EvaluationError, match="not part"):
        session.select_clip("00000000-0000-0000-0000-000000000001")
    assert session.pose == initial and session.evaluator.clip is clip
