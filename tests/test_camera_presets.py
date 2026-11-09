"""Portable camera presets produce deterministic movement and matching output overlays."""

import xml.etree.ElementTree as ET
from dataclasses import replace

import pytest

from rigora.application_services.cameras import CameraService
from rigora.application_services.documents import DocumentService
from rigora.application_services.rendering import svg_frame
from rigora.application_services.scene_editing import SceneEditingService
from rigora.engine.camera_actions import EFFECT_PRESETS, MOTION_PRESETS


@pytest.mark.parametrize("preset", MOTION_PRESETS)
def test_camera_motion_presets_are_real_portable_and_reversible(preset, tmp_path):
    """Every move changes the evaluated camera, preserves base transforms, and survives reload."""
    doc = DocumentService()
    doc.new()
    service = CameraService(doc)
    camera = doc.scene.cameras[0]
    SceneEditingService(doc).flags((camera.id,), locked=False)
    baseline = doc.project
    identity = service.action(camera.id, preset, "camera_motion", 0, 48)
    assert service.camera(camera.id).transform == camera.transform
    matrices = {
        doc.animation.evaluate(frame).nodes[camera.id].world_matrix for frame in (0, 7, 13, 25, 47)
    }
    assert len(matrices) > 1
    doc.save(tmp_path / "camera.rigora")
    loaded = DocumentService()
    loaded.open(doc.path)
    assert (
        loaded.animation.evaluate(13).nodes[camera.id]
        == doc.animation.evaluate(13).nodes[camera.id]
    )
    doc.undo()
    assert doc.project == baseline
    doc.redo()
    service.remove_action(identity)
    assert doc.animation.evaluate(13).nodes[camera.id].world_matrix == camera.transform.matrix()


@pytest.mark.parametrize("preset", EFFECT_PRESETS)
def test_camera_effects_render_in_camera_coordinates_and_expire(preset):
    """Each overlay is valid SVG, changes output only inside its interval, and is deterministic."""
    doc = DocumentService()
    doc.new()
    camera = doc.scene.cameras[0]
    before = svg_frame(doc, 12)
    CameraService(doc).action(camera.id, preset, "camera_effect", 0, 24)
    output = svg_frame(doc, 12)
    assert output != before and ET.fromstring(output) is not None
    assert output == svg_frame(doc, 12)
    assert doc.animation.evaluate(12).cameras[0].extra["lens_effects"][preset] > 0
    assert doc.animation.evaluate(25).cameras[0].extra["lens_effects"][preset] == 0


def test_camera_cut_keeps_the_previous_camera_until_the_cut():
    """One exclusive cut chooses the next main view without modifying camera placement."""
    doc = DocumentService()
    doc.new()
    service = CameraService(doc)
    original = service.current().id
    second = service.add()
    service.activate(second, frame=20)
    from rigora.engine.cameras import active_camera

    assert active_camera(doc.animation.evaluate(19)).id == original
    assert active_camera(doc.animation.evaluate(20)).id == second


def test_overlapping_lens_actions_keep_the_strongest_weighted_effect():
    """Later inactive or weaker intervals cannot mask an existing effect's intensity/speed."""
    doc = DocumentService()
    doc.new()
    service = CameraService(doc)
    camera = doc.scene.cameras[0].id
    service.action(camera, "rain", "camera_effect", 0, 80, amount=0.6, speed=2)
    weaker = service.action(camera, "rain", "camera_effect", 0, 80, amount=1, speed=3)
    timeline = doc.scene.timelines[0]
    service.commit(
        "Weight lens action",
        timelines=tuple(
            replace(
                item,
                tracks=tuple(
                    replace(track, weight=0.2)
                    if track.extra.get("camera_action", {}).get("id") == weaker
                    else track
                    for track in item.tracks
                ),
            )
            if item.id == timeline.id
            else item
            for item in doc.scene.timelines
        ),
    )
    service.action(camera, "rain", "camera_effect", 50, 70, speed=4)
    evaluated = doc.animation.evaluate(20).cameras[0].extra
    assert evaluated["lens_effects"]["rain"] == pytest.approx(0.6)
    assert evaluated["lens_speeds"]["rain"] == 2


def test_camera_effect_eye_mutes_output_and_lock_rejects_new_actions():
    """Camera actions use the same evaluation mute and insertion lock as ordinary keys."""
    from rigora.application_services.animation_editing import AnimationEditingService
    from rigora.domain.project import ProjectError

    doc = DocumentService()
    doc.new()
    camera = doc.scene.cameras[0].id
    service = CameraService(doc)
    identity = service.action(camera, "rain", "camera_effect", 0, 24)
    editor = AnimationEditingService(doc)
    track = editor.timeline.tracks[0]
    before = svg_frame(doc, 12)
    editor.track_settings(track.id, locked=True, visible=False)
    assert svg_frame(doc, 12) != before
    assert not doc.animation.evaluate(12).cameras[0].extra.get("lens_effects", {}).get("rain")
    revision = doc.project
    with pytest.raises(ProjectError, match="Unlock"):
        service.action(camera, "rain", "camera_effect", 30, 48)
    with pytest.raises(ProjectError, match="Unlock"):
        service.remove_action(identity)
    assert doc.project is revision
