"""Animation editing commands preserve engine behavior, persistence and atomic undo."""

import json
from dataclasses import replace

import pytest

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.commands import ScenePatch
from rigora.application_services.deformation import DeformationService, deformation_presets
from rigora.application_services.documents import DocumentService
from rigora.application_services.meshes import MeshService
from rigora.application_services.rigging import RigService
from rigora.domain.entities import Keyframe, Track
from rigora.domain.project import ProjectError
from rigora.engine.sampling import CompiledTrack


def editor():
    """Create an independent connected rig and return its shared editing service."""
    doc = DocumentService()
    doc.new("Animation editing")
    rig = RigService(doc)
    root = rig.create_bone((100, 100), (200, 100))
    tip = rig.create_bone((200, 100), (300, 100), root)
    return doc, AnimationEditingService(doc), root, tip


def test_key_edit_copy_collision_lock_delete_and_persistence(tmp_path):
    """Multi-key operations retain subframes, identity, clip bounds and one-step undo."""
    doc, service, root, tip = editor()
    service.key(root, "transform.rotation", 0, 0)
    service.key(root, "transform.rotation", 10.5, 90)
    service.key(tip, "transform.rotation", 0, 10)
    service.key(tip, "transform.rotation", 10.5, -30)
    doc.animation.seek(5.25)
    assert doc.animation.pose.nodes[root].local.rotation == pytest.approx(45)
    track = service.timeline.tracks[0]
    refs = tuple((track.id, k.id) for k in track.keyframes)
    original, count = doc.project, len(doc.history.undo_stack)
    service.edit_keys(
        {ref: {"frame": k.frame + 2.25} for ref, k in zip(refs, track.keyframes, strict=True)}
    )
    assert len(doc.history.undo_stack) == count + 1
    assert doc.animation.pose.frame == 5.25
    doc.undo()
    assert doc.project == original
    clipboard = service.copy_keys(refs)
    pasted = service.paste_keys(clipboard, 20.25)
    assert len(pasted) == 2
    assert [k.frame for k in service.timeline.tracks[0].keyframes] == [0, 10.5, 20.25, 30.75]
    before = doc.project
    with pytest.raises(ProjectError, match="overlap"):
        service.paste_keys(clipboard, 0)
    assert doc.project is before
    with pytest.raises(ProjectError, match="unique"):
        service.edit_keys({refs[1]: {"frame": 0}})
    assert doc.project is before
    service.track_settings(track.id, locked=True, visible=False)
    assert not service.timeline.tracks[0].visible
    assert doc.animation.evaluate(5.25).nodes[root].local.rotation == pytest.approx(0)
    with pytest.raises(ProjectError, match="Unlock"):
        service.edit_keys({refs[0]: {"value": 15}})
    with pytest.raises(ProjectError, match="Unlock"):
        service.key(root, "transform.rotation", 3, 10)
    doc.undo()
    service.edit_keys(dict.fromkeys(pasted, {}), delete=True)
    assert len(service.timeline.tracks[0].keyframes) == 2
    doc.undo()
    service.marker("Contact", 10.5, "Foot reaches ground")
    service.clip_settings(annotation="Reusable turn", loop=True)
    doc.save(tmp_path / "animation.rigora")
    loaded = DocumentService()
    loaded.open(doc.path)
    assert loaded.project == doc.project
    assert loaded.animation.evaluate(9.125) == doc.animation.evaluate(9.125)


def test_bezier_tangents_retime_reverse_offsets_and_duplicate():
    """Curve handles change sampled playback and preserve their shape under time scaling."""
    doc, service, root, _ = editor()
    service.key(root, "transform.x", 0, 100)
    service.key(root, "transform.x", 10, 200)
    service.clip_settings(out_frame=10)
    track = service.timeline.tracks[0]
    refs = tuple((track.id, k.id) for k in track.keyframes)
    linear = doc.animation.evaluate(3).nodes[root].local.x
    service.edit_keys(
        {
            refs[0]: {"interpolation": "bezier", "tangent_out": (2, 70)},
            refs[1]: {"tangent_in": (-2, -5)},
        }
    )
    curved = doc.animation.evaluate(3).nodes[root].local.x
    assert curved != pytest.approx(linear)
    source = service.timeline.tracks[0]
    original = doc.project
    service.retime(20, 40, reverse=True, offset_x=5)
    for frame in (0, 2.5, 8.25, 10):
        assert doc.animation.evaluate(40 - frame * 2).nodes[root].world_matrix[4] == pytest.approx(
            CompiledTrack(source).sample(frame) + 5, abs=1e-6
        )
    doc.undo()
    assert doc.project == original
    service.tangents(refs, "flat")
    assert service.timeline.tracks[0].keyframes[0].tangent_out[1] == 0
    source_timeline, source_clip = service.timeline, service.clip
    service.new_clip("Copy", duplicate=True)
    assert service.clip.id != source_clip.id
    assert service.timeline.id != source_timeline.id
    assert service.timeline.tracks[0].keyframes[0].id != source_timeline.tracks[0].keyframes[0].id
    doc.undo()
    assert len(service.scene.clips) == 1


def test_deformer_channels_use_same_key_editor_and_respect_protection():
    """FFD dots and mesh vertices share scalar curves rather than another animation model."""
    from pathlib import Path

    doc, service, _, _ = editor()
    mesh_id = MeshService(doc).import_image(Path("assets/examples/torso.svg"), 2, 2)
    deform = DeformationService(doc)
    stage = deform.add(mesh_id, deformation_presets()[0])
    assert any(
        owner.id == stage and path == "parameters.controls.0.0"
        for owner, path, _ in service.properties()
    )
    service.key(stage, "parameters.controls.0.0", 0, 0)
    service.key(stage, "parameters.controls.0.0", 10, 50)
    before = doc.animation.evaluate(0).meshes[mesh_id].positions
    after = doc.animation.evaluate(10).meshes[mesh_id].positions
    assert before != after
    track = service.timeline.tracks[0]
    service.track_settings(track.id, locked=True, visible=True)
    from rigora.application_services.deformation_motion import DeformationMotionService

    with pytest.raises(ProjectError, match="Unlock"):
        DeformationMotionService(doc).key(stage, "parameters.controls.0.0", 5, 30)


def test_reverse_step_events_and_unkeyed_root_offsets():
    """Reversed holds switch immediately after events and offsets work without position tracks."""
    doc, service, root, _ = editor()
    service.key(root, "transform.rotation", 0, 0, interpolation="step")
    service.key(root, "transform.rotation", 10, 90)
    service.clip_settings(out_frame=10)
    service.retime(0, 10, reverse=True, offset_x=30)
    assert doc.animation.evaluate(0).nodes[root].local.rotation == 90
    assert doc.animation.evaluate(0.01).nodes[root].local.rotation == 0
    assert doc.animation.evaluate(9).nodes[root].local.rotation == 0
    assert doc.animation.evaluate(5).nodes[root].world_matrix[4] == 130
    assert doc.animation.evaluate(5).nodes[root].local.x == 100


def test_blend_preserves_layered_sampling_and_action_exchange(tmp_path):
    """Blend outputs use actual ordered track policies and action exchange retains motion data."""
    doc, service, root, _ = editor()
    service.key(root, "transform.x", 0, 100)
    service.key(root, "transform.x", 10, 200)
    service.clip_settings(out_frame=10)
    scene, timeline = service.scene, service.timeline
    extra = Track(
        name="Additive offset",
        owner_id=root,
        property_path="transform.x",
        blend_mode="additive",
        weight=0.5,
        keyframes=(Keyframe(frame=0, value=20),),
    )
    changed = replace(timeline, tracks=(*timeline.tracks, extra))
    doc.execute(
        ScenePatch("Add layer", scene.id, {"timelines": scene.timelines}, {"timelines": (changed,)})
    )
    first_id = service.clip.id
    service.new_clip("Second")
    service.key(root, "transform.x", 0, 300)
    service.key(root, "transform.x", 10, 400)
    service.clip_settings(out_frame=10)
    second_id = service.clip.id
    doc.select_animation_clip(first_id)
    service.blend(second_id, weight=0.5)
    assert doc.animation.evaluate(5).nodes[root].local.x == pytest.approx(255)
    assert len(service.scene.clips) == 3
    doc.undo()
    doc.select_animation_clip(first_id)
    service.blend(second_id, weight=1, transition=5)
    assert doc.animation.evaluate(0).nodes[root].local.x == pytest.approx(110)
    assert doc.animation.evaluate(10).nodes[root].local.x == pytest.approx(400)
    service.marker("End", 10, "Transition complete")
    path = tmp_path / "turn.rigaction"
    service.export_action(path)
    with pytest.raises(FileExistsError):
        service.export_action(path)
    expected = doc.animation.evaluate(5).nodes[root].local.x
    service.import_action(path)
    assert doc.animation.evaluate(5).nodes[root].local.x == pytest.approx(expected)
    assert service.timeline.markers[0].annotation == "Transition complete"
    before = doc.project
    raw = json.loads(path.read_text())
    raw["owners"] = {}
    path.write_text(json.dumps(raw))
    with pytest.raises(ProjectError, match="Invalid reusable"):
        service.import_action(path)
    assert doc.project is before


def test_locked_transform_lane_rejects_new_channels():
    """A grouped Transform lock protects channels that have not yet been keyed."""
    doc, service, root, _ = editor()
    service.key(root, "transform.x", 0, 100)
    service.track_settings(service.timeline.tracks[0].id, locked=True, visible=True)
    before = doc.project
    with pytest.raises(ProjectError, match="Unlock"):
        service.key(root, "transform.y", 5, 200)
    with pytest.raises(ProjectError, match="Unlock"):
        service.add_channels(((root, "transform.rotation"),), frame=5)
    assert doc.project is before


def test_eye_mutes_evaluation_and_survives_save_and_undo(tmp_path):
    """A hidden track contributes nothing; restoring it resumes the unchanged animation."""
    doc, service, root, _ = editor()
    service.key(root, "transform.rotation", 0, 70)
    track = service.timeline.tracks[0]
    before = doc.project
    service.track_settings(track.id, locked=False, visible=False)
    assert doc.animation.evaluate(0).nodes[root].local.rotation == 0
    doc.save(tmp_path / "muted.rigora")
    loaded = DocumentService()
    loaded.open(doc.path)
    assert loaded.animation.evaluate(0).nodes[root].local.rotation == 0
    doc.undo()
    assert doc.project == before
    assert doc.animation.evaluate(0).nodes[root].local.rotation == 70
