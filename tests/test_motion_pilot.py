"""Deterministic pointer mappings, isolated preview and native editable recording passes."""

import math
from dataclasses import replace

import pytest

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.documents import DocumentService
from rigora.application_services.motion_pilot import MotionPilotService, MotionPilotSession
from rigora.domain.entities import SceneObject, Timeline, Transform
from rigora.domain.motion_pilot import MotionPilotProfile
from rigora.domain.project import ProjectError


@pytest.fixture
def targets():
    """Create ordinary scene objects using the shared document commands without GUI state."""
    doc = DocumentService()
    doc.new()
    a = SceneObject(name="Leader", transform=Transform(x=100, y=100))
    b = SceneObject(name="Follower", transform=Transform(x=300, y=100))
    MotionPilotService(doc).commit("Add targets", objects=(a, b))
    return doc, a.id, b.id


def test_scene_switch_invalidates_recording_even_without_an_authoring_change(targets):
    """Capture ownership includes scene identity, since activation does not dirty the project."""
    doc, owner, _ = targets
    second = doc.add_scene()
    recording = MotionPilotSession(doc, (owner,), recording=True, pointer=(0, 0))
    recording.feed(6, (60, 30), final=True)
    source = doc.project
    doc.select_scene(second)
    assert doc.project is source
    with pytest.raises(ProjectError, match="changed"):
        recording.commit()
    assert doc.project is source and not doc.scene.objects


def test_position_preview_record_stop_edit_undo_and_reload(targets, tmp_path):
    """Preview is isolated; recordings retain their final fraction as ordinary editable keys."""
    doc, owner, _ = targets
    original = doc.project
    preview = MotionPilotSession(doc, (owner,), pointer=(0, 0))
    pose = preview.feed(6, (60, 30))
    assert pose.nodes[owner].local.x == pytest.approx(160)
    assert doc.project is original
    with pytest.raises(ProjectError, match="Preview"):
        preview.prepare_recording()
    record = MotionPilotSession(doc, (owner,), recording=True, pointer=(0, 0))
    record.feed(6, (60, 30))
    record.feed(12.5, (125, 50), final=True)
    before = len(doc.history.undo_stack)
    record.commit()
    assert len(doc.history.undo_stack) == before + 1
    assert doc.animation.evaluate(12.5).nodes[owner].local.x == pytest.approx(225)
    assert doc.animation.evaluate(50).nodes[owner].local.x == pytest.approx(225)
    service = AnimationEditingService(doc)
    track = next(t for t in service.timeline.tracks if t.property_path == "transform.x")
    final = next(k for k in track.keyframes if k.frame == 12.5)
    service.edit_keys({(track.id, final.id): {"frame": 13, "value": 240}})
    assert doc.animation.evaluate(13).nodes[owner].local.x == pytest.approx(240)
    doc.undo()
    destination = tmp_path / "pilot.rigora"
    doc.save(destination)
    other = DocumentService()
    other.open(destination)
    assert (
        other.animation.evaluate(12.5).nodes[owner].local
        == doc.animation.evaluate(12.5).nodes[owner].local
    )
    doc.undo()
    assert doc.project == original
    doc.redo()
    assert doc.animation.evaluate(12.5).nodes[owner].local.x == pytest.approx(225)


@pytest.mark.parametrize("uniform", (False, True))
def test_rotation_scale_mapping_and_face_modes(targets, uniform):
    """Signed axes, independent/uniform scale and mutually exclusive Turn use stable origins."""
    doc, owner, _ = targets
    profile = MotionPilotProfile(
        move=False,
        rotate=True,
        rotation_gain=1,
        scale=True,
        width_gain=0.01,
        height_gain=0.02,
        width_axis="-X",
        uniform=uniform,
    )
    session = MotionPilotSession(doc, (owner,), profile, pointer=(20, 20))
    initial = session.evaluator.evaluate(0).nodes[owner].local
    assert initial.scale_x == initial.scale_y == 1
    pose = session.feed(6, (70, 45)).nodes[owner].local
    assert pose.rotation == pytest.approx(50)
    assert pose.scale_x == pytest.approx(math.exp(-0.5))
    assert pose.scale_y == pytest.approx(pose.scale_x if uniform else math.exp(0.5))
    flip = MotionPilotSession(doc, (owner,), replace(profile, scale=False, face="Flip"))
    assert flip.feed(4, (-30, 0)).nodes[owner].local.scale_x < 0
    turn = MotionPilotSession(
        doc,
        (owner,),
        replace(
            profile, rotate=True, scale=False, face="Turn", forward_angle=90, turn_smoothness=0
        ),
    )
    assert turn.feed(4, (30, 0)).nodes[owner].local.rotation == pytest.approx(-90)


def test_wave_independence_mouse_gate_lazy_mouse_and_flock_delays(targets):
    """Waves run independently, mouse waves pause and followers retain their delay state."""
    doc, a, b = targets
    wave = MotionPilotSession(
        doc,
        (a,),
        MotionPilotProfile(
            move=False, wave_move=True, wave_y=20, wave_rotate=True, wave_scale=True
        ),
    )
    pose = wave.feed(6, (0, 0)).nodes[a].local
    assert pose.y == pytest.approx(120)
    assert pose.rotation == pytest.approx(10)
    assert pose.scale_x == pytest.approx(1.05)
    mouse = MotionPilotSession(
        doc, (a,), MotionPilotProfile(move=False, wave_move=True, wave_mouse=True)
    )
    still = mouse.feed(12, (0, 0)).nodes[a].local.y
    assert still == 100
    assert mouse.feed(18, (25, 0)).nodes[a].local.y > 110
    flock = MotionPilotSession(
        doc, (a, b), MotionPilotProfile(delay_mode="Uniform", delay_frames=4)
    )
    pose = flock.feed(12, (120, 0))
    assert pose.nodes[a].local.x == pytest.approx(220)
    assert pose.nodes[b].local.x == pytest.approx(380)
    lazy = MotionPilotSession(doc, (a,), MotionPilotProfile(lazy_mouse=0.5))
    assert 100 < lazy.feed(6, (100, 0)).nodes[a].local.x < 200
    random_a = MotionPilotSession(doc, (a, b), MotionPilotProfile(delay_mode="Random", seed=4))
    random_b = MotionPilotSession(doc, (a, b), MotionPilotProfile(delay_mode="Random", seed=4))
    assert random_a.delays == random_b.delays


def test_blend_and_replace_passes_and_profile_roundtrip(targets, tmp_path):
    """New rotation passes preserve movement when blended and replace prior Pilot data when off."""
    doc, owner, follower = targets
    first = MotionPilotSession(doc, (owner,), recording=True)
    first.feed(12, (120, 0))
    first.commit()
    for blend in (True, False):
        profile = MotionPilotProfile(move=False, rotate=True, rotation_gain=1, blend=blend)
        session = MotionPilotSession(doc, (owner,), profile, recording=True)
        session.feed(12, (30, 0))
        session.commit()
        pose = doc.animation.evaluate(12).nodes[owner].local
        assert pose.rotation == pytest.approx(30)
        assert pose.x == pytest.approx(220 if blend else 100)
        if blend:
            doc.undo()
    service = MotionPilotService(doc)
    profile_path = tmp_path / "custom.rigpilot"
    service.export_profile(owner, profile_path)
    service.import_profile(follower, profile_path)
    assert service.profile(follower) == service.profile(owner)


def test_recorded_rotation_and_scale_keys_move_delete_and_undo(targets):
    """Recorded angular/scale output remains ordinary editable animation after capture."""
    doc, owner, _ = targets
    session = MotionPilotSession(
        doc, (owner,), MotionPilotProfile(move=False, rotate=True, scale=True), recording=True
    )
    session.feed(12.5, (40, 20), final=True)
    session.commit()
    editor = AnimationEditingService(doc)
    track = next(t for t in editor.timeline.tracks if t.property_path == "transform.rotation")
    key = next(k for k in track.keyframes if k.frame == 12.5)
    editor.edit_keys({(track.id, key.id): {"frame": 14.5, "value": 90}})
    assert doc.animation.evaluate(14.5).nodes[owner].local.rotation == 90
    before = doc.project
    editor.edit_keys({(track.id, key.id): {}}, delete=True)
    assert not any(k.id == key.id for t in editor.timeline.tracks for k in t.keyframes)
    doc.undo()
    assert doc.project == before
    assert doc.animation.evaluate(12.5).nodes[owner].local.scale_x == pytest.approx(math.exp(0.2))


def test_turn_smoothing_and_cursor_reference_preserve_initial_pose(targets):
    """Positive smoothing approaches the shortest angle and reference choices never warp startup."""
    doc, owner, _ = targets
    profile = MotionPilotProfile(move=False, face="Turn", turn_smoothness=0.5)
    smooth = MotionPilotSession(doc, (owner,), profile)
    instant = MotionPilotSession(doc, (owner,), replace(profile, turn_smoothness=0))
    assert smooth.feed(6, (0, 50)).nodes[owner].local.rotation < 90
    assert instant.feed(6, (0, 50)).nodes[owner].local.rotation == pytest.approx(90)
    center = MotionPilotSession(
        doc,
        (owner,),
        replace(profile, cursor_start="Viewport center"),
        pointer=(200, 200),
        viewport_center=(300, 300),
    )
    assert center.evaluator.evaluate(0).nodes[owner].local == doc.animation.pose.nodes[owner].local


def test_missing_motion_and_overlapping_flock_are_rejected_atomically(targets):
    """Deleted native references report errors and nested targets cannot receive double movement."""
    from uuid import uuid4

    doc, owner, follower = targets
    before = doc.project
    with pytest.raises(ValueError, match="clip"):
        MotionPilotSession(doc, (owner,), MotionPilotProfile(motion_clips=(str(uuid4()),)))
    assert doc.project is before
    service = MotionPilotService(doc)
    a, b = service.scene.objects
    service.commit("Parent follower", objects=(a, replace(b, parent_id=owner)))
    before = doc.project
    with pytest.raises(ProjectError, match="parent"):
        MotionPilotSession(doc, (owner, follower))
    assert doc.project is before


def test_key_optimization_keeps_turns_and_stale_recording_is_rejected(targets):
    """Key reduction preserves turns within tolerance and rejects concurrent edits."""
    doc, owner, _ = targets
    session = MotionPilotSession(doc, (owner,), recording=True)
    session.feed(10, (100, 0))
    session.feed(20, (0, 0))
    optimized = session.prepare_recording()[0]
    session.profile = replace(session.profile, optimize=False)
    full = session.prepare_recording()[0]
    assert sum(len(t.keyframes) for t in optimized.tracks) < sum(
        len(t.keyframes) for t in full.tracks
    )
    assert any(k.frame == 10 for t in optimized.tracks for k in t.keyframes)
    MotionPilotService(doc).set_profile(owner, MotionPilotProfile(rotate=True))
    with pytest.raises(ProjectError, match="changed"):
        session.commit()


@pytest.mark.parametrize(
    "data",
    [
        {"followers": [{}]},
        {"motion_speed": float("nan")},
        {"move": 1},
        {"move_x_axis": "Z"},
        {"unknown": 1},
        {"followers": "bad"},
    ],
)
def test_malformed_profiles_fail_with_project_errors(data):
    """Profile files reject malformed inert data at the shared service boundary."""
    with pytest.raises(ProjectError):
        MotionPilotProfile.from_dict(data)


def test_long_capture_isolated_bounded_and_editable_after_background_preparation(targets):
    """A one-minute capture keeps editable output and enforces pointer/scalar budgets."""
    doc, owner, follower = targets
    AnimationEditingService(doc).key(owner, "transform.x", 0, 100)
    AnimationEditingService(doc).clip_settings(out_frame=2000)
    original = doc.project
    session = MotionPilotSession(doc, (owner, follower), recording=True)
    session.feed(1440, (500, 300), final=True)
    assert len(session.times) == 1441 and doc.project is original
    cache = session.evaluator.sample_kinematic.cache_info()
    assert cache.currsize <= cache.maxsize <= 512
    timeline, clip = session.prepare_recording()
    assert len(timeline.tracks) < 10
    assert all(len(t.keyframes) < 10 for t in timeline.tracks if t.extra.get("motion_pilot"))
    session.commit((timeline, clip))
    assert doc.animation.evaluate(1440).nodes[owner].local.x == pytest.approx(600)
    before = len(session.times)
    session.end = 100001
    with pytest.raises(ProjectError, match="100,000"):
        session.feed(100001, (0, 0))
    assert len(session.times) == before


@pytest.mark.parametrize("mode", ("Automatic", "Mouse movement", "Click to play", "Click to loop"))
def test_native_motion_triggers_reverse_speed_in_place_and_followers(targets, mode):
    """Native clips drive compatible flock objects with explicit, deterministic trigger clocks."""
    doc, a, b = targets
    editor = AnimationEditingService(doc)
    editor.key(a, "transform.rotation", 0, 0)
    editor.key(a, "transform.rotation", 24, 90)
    editor.key(a, "transform.x", 0, 100)
    editor.key(a, "transform.x", 24, 200)
    editor.clip_settings(out_frame=24)
    source = editor.clip.id
    timeline = Timeline(name="Scene capture")
    editor.publish("Choose recording timeline", timeline, editor.blank_clip(timeline))
    profile = MotionPilotProfile(
        move=False, motion_enabled=True, motion_clips=(source,), motion_speed=2, motion_trigger=mode
    )
    session = MotionPilotSession(doc, (a, b), profile, recording=True)
    if mode.startswith("Click"):
        assert session.feed(3, (0, 0)).nodes[a].local.rotation == 0
        assert session.feed(4, (0, 0), clicked=True).nodes[a].local.rotation == 0
        pose = session.feed(7, (0, 0))
        assert pose.nodes[a].local.rotation == pytest.approx(22.5)
    else:
        pose = session.feed(3, (30, 0))
        assert pose.nodes[a].local.rotation == pytest.approx(22.5)
    assert pose.nodes[b].local.rotation == pytest.approx(pose.nodes[a].local.rotation)
    assert pose.nodes[a].local.x == 100 and pose.nodes[b].local.x == 300
    session.commit()
    assert doc.animation.evaluate(session.frame).nodes[b].local.rotation == pytest.approx(
        pose.nodes[b].local.rotation
    )
    reverse = MotionPilotSession(
        doc, (a,), replace(profile, motion_reverse=True, motion_trigger="Automatic", blend=False)
    )
    assert reverse.feed(3, (0, 0)).nodes[a].local.rotation == pytest.approx(67.5)
