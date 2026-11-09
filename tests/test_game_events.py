"""Typed markers follow reusable action timing and deterministic interval delivery."""

import pytest
from test_object_scene_actions import composition

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.documents import DocumentService
from rigora.domain.project import ProjectError


def test_events_arranged_speed_repeat_mute_and_non_executing_seek(tmp_path):
    """Source event timing survives placement and does not fire merely from scrubbing/export."""
    doc, chars, _, root, a, _ = composition()
    doc.set_animation_context(root, frozenset(chars.members(root)))
    source = chars.new_motion(root, "Walk")
    edit = AnimationEditingService(doc)
    edit.clip_settings(in_frame=0, out_frame=10)
    edit.key(chars.mesh(a).object_id, "transform.rotation", 0, 10)
    edit.marker("Left foot", 2, event_type="footstep", payload={"surface": "stone", "gain": 0.7})
    revision = doc.project
    with pytest.raises(ProjectError):
        edit.marker("Invalid", 4, event_type="run_python", payload={})
    assert doc.project is revision
    doc.set_animation_context(None)
    key = chars.place_motion(root, source, 5, 20 / doc.scene.settings.fps, speed=2)
    events = doc.animation.runtime_events
    assert [e.frame for e in events] == [6, 11, 16, 21]
    session = doc.animation
    session.seek(5)
    assert not session.last_events
    session.play()
    session.advance(12 / doc.scene.settings.fps)
    assert [e.frame for e in session.last_events] == [6, 11, 16]
    session.seek(5)
    session.advance(1 / doc.scene.settings.fps)
    assert [e.frame for e in session.last_events] == [6]
    chars.edit_segment(key, muted=True)
    assert not doc.animation.runtime_events
    doc.undo()
    assert len(doc.animation.runtime_events) == 4
    doc.save(tmp_path / "events.rigora")
    selected = doc.selected_clip_id
    doc.open(doc.path)
    doc.select_animation_clip(selected)
    assert doc.animation.runtime_events[0].payload["surface"] == "stone"


def test_start_events_fire_once_on_play_and_loop_but_never_on_seek_or_stop():
    """Initial-frame gameplay cues match native runtime delivery without scrub side effects."""
    doc = DocumentService()
    doc.new()
    edit = AnimationEditingService(doc)
    edit.new_clip("Event clock")
    edit.marker("Begin", 0, event_type="signal", payload={"state": "begin"})
    edit.clip_settings(in_frame=0, out_frame=4)
    session = doc.animation
    session.play()
    session.advance(0)
    assert not session.last_events
    session.advance(1 / 24)
    assert [e.name for e in session.last_events] == ["Begin"]
    session.advance(1 / 24)
    assert not session.last_events
    session.set_loop(True)
    session.advance(4 / 24)
    assert [e.name for e in session.last_events] == ["Begin"]
    session.seek(0)
    assert not session.last_events
    session.advance(1 / 24)
    assert not session.last_events
    session.stop()
    assert not session.last_events
