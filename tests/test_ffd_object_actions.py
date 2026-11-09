"""Reusable FFD sources retain Scene timing and use canonical linked action tracks."""

from dataclasses import replace

import pytest

from rigora.application_services.animation_editing import AnimationEditingService, motion_source_end
from rigora.application_services.characters import CharacterService
from rigora.application_services.content_library import ContentService
from rigora.application_services.documents import DocumentService
from rigora.domain.project import SceneSettings
from rigora.infrastructure.effect_catalog import ffd_presets

MOTIONS = tuple(item for item in ffd_presets() if "motion" in item.payload)


@pytest.mark.parametrize("item", MOTIONS, ids=lambda item: item.name)
def test_each_scene_ffd_retains_a_named_editable_source_and_atomic_undo(item):
    """Every built-in motion is available to Object Editor without losing its placed animation."""
    doc = DocumentService()
    doc.new()
    doc.set_animation_context(None)
    original = doc.project
    stage = ContentService(doc).place(item, {}, position=(320, 240))
    characters = CharacterService(doc)
    owner = characters.scene_objects()[0]
    (source,) = characters.motions(owner)
    assert source.name == item.name and source.extra["object_id"] == owner
    source_timeline = next(t for t in doc.scene.timelines if t.id == source.timeline_id)
    assert source_timeline.tracks and all(t.owner_id == stage for t in source_timeline.tracks)
    assert all(not t.locked for t in source_timeline.tracks)
    placed = AnimationEditingService(doc).timeline
    assert all(t.extra["motion_window"]["source"] == source.id for t in placed.tracks)
    assert all(t.extra["motion_window"]["name"] == item.name for t in placed.tracks)
    assert len(doc.history.undo_stack) == 1
    doc.undo()
    assert doc.project == original


@pytest.mark.parametrize("fps", (24, 30, 60))
def test_ffd_source_starts_at_zero_while_scene_placement_preserves_offset_and_period(fps, tmp_path):
    """Retained actions have a complete loop at each FPS, speed and repeat setting."""
    item = replace(
        MOTIONS[0],
        payload={**MOTIONS[0].payload, "speed": 1.7, "repeats": 2, "snap_to_frames": False},
    )
    doc = DocumentService()
    doc.new(settings=SceneSettings(fps=fps))
    doc.set_animation_context(None)
    doc.animation.seek(17)
    stage = ContentService(doc).place(item, {})
    characters = CharacterService(doc)
    owner = characters.scene_objects()[0]
    (source,) = characters.motions(owner)
    period = item.payload["motion"]["duration"] * fps / item.payload["motion"]["fps"] / 1.7 * 2
    assert motion_source_end(source) == pytest.approx(period)
    timeline = next(t for t in doc.scene.timelines if t.id == source.timeline_id)
    assert min(k.frame for t in timeline.tracks for k in t.keyframes) == 0
    assert max(k.frame for t in timeline.tracks for k in t.keyframes) == pytest.approx(period)
    arranged = AnimationEditingService(doc).timeline
    for track in arranged.tracks:
        assert track.owner_id == stage
        assert track.extra["motion_window"]["start"] == 17
        assert track.extra["motion_window"]["end"] == pytest.approx(17 + period)
        assert track.extra["motion_window"]["source_end"] == pytest.approx(period)
    path = tmp_path / "ffd-source.rigora"
    doc.save(path)
    clone = DocumentService()
    clone.open(path)
    assert CharacterService(clone).motions(owner) == (source,)


@pytest.mark.parametrize("fps", (24, 30, 60))
@pytest.mark.parametrize("speed", (1, 1.7, 20))
@pytest.mark.parametrize("loop", (False, True))
def test_new_ffd_presets_use_project_frames_and_keep_loop_closure(fps, speed, loop):
    """Preset timing lands on frame centers while one closing loop sample preserves continuity."""
    item = next(item for item in MOTIONS if item.payload["motion"]["loop"] == loop)
    item = replace(item, payload={**item.payload, "speed": speed, "repeats": 2})
    doc = DocumentService()
    doc.new(settings=SceneSettings(fps=fps))
    doc.set_animation_context(None)
    doc.animation.seek(17)
    stage = ContentService(doc).place(item, {})
    characters = CharacterService(doc)
    owner = characters.scene_objects()[0]
    (source,) = characters.motions(owner)
    exact = item.payload["motion"]["duration"] * fps / item.payload["motion"]["fps"] / speed * 2
    period = max(1, round(exact))
    assert motion_source_end(source) == period
    timeline = next(t for t in doc.scene.timelines if t.id == source.timeline_id)
    for track in timeline.tracks:
        times = [key.frame for key in track.keyframes]
        assert all(time == round(time) for time in times)
        assert times[0] == 0 and times[-1] == period
        assert all(a < b for a, b in zip(times, times[1:], strict=False))
        if loop:
            assert track.keyframes[0].value == track.keyframes[-1].value
    placed = AnimationEditingService(doc).timeline
    assert all(t.owner_id == stage for t in placed.tracks)
    assert all(t.extra["motion_window"]["end"] == 17 + period for t in placed.tracks)
