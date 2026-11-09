"""Canonical transition graphs, span operations, auto-keying and persistence contracts."""

from dataclasses import replace

import pytest

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.documents import DocumentService
from rigora.application_services.rigging import RigService
from rigora.application_services.scene_editing import SceneEditingService
from rigora.domain.project import ProjectError
from rigora.engine.transition_curves import TransitionCurve, curve_presets


def animation():
    """Create one independently owned bone with two distinct keyed rotation poses."""
    doc = DocumentService()
    doc.new()
    bone = RigService(doc).create_bone((20, 30), (120, 30))
    service = AnimationEditingService(doc)
    service.key(bone, "transform.rotation", 0, 0)
    service.key(bone, "transform.rotation", 24, 90)
    refs = tuple(
        (service.timeline.tracks[0].id, k.id) for k in service.timeline.tracks[0].keyframes
    )
    return doc, service, bone, refs


def test_curve_drives_engine_retimes_reverses_copies_and_reopens(tmp_path):
    """Normalized graphs retain their shape under editing and use the real saved evaluator."""
    doc, service, bone, refs = animation()
    graph = TransitionCurve(((0, 0), (0.5, 0.2), (1, 1)), smooth=True)
    baseline = doc.project
    count = len(doc.history.undo_stack)
    service.set_transition(refs, graph)
    assert len(doc.history.undo_stack) == count + 1
    assert doc.animation.evaluate(12).nodes[bone].local.rotation == pytest.approx(18)
    service.edit_keys({refs[-1]: {"frame": 48}})
    assert doc.animation.evaluate(24).nodes[bone].local.rotation == pytest.approx(18)
    before = doc.project
    service.preview_keys({refs[-1]: {"value": 180}}, 24)
    assert doc.project is before
    samples = [doc.animation.evaluate(i).nodes[bone].local.rotation for i in range(49)]
    service.reverse_keys(refs)
    assert [
        doc.animation.evaluate(i).nodes[bone].local.rotation for i in range(49)
    ] == pytest.approx(samples[::-1])
    doc.undo()
    data = service.copy_keys(refs)
    pasted = service.paste_keys(data, 60)
    assert len(pasted) == 2
    assert doc.animation.evaluate(84).nodes[bone].local.rotation == pytest.approx(18)
    doc.save(tmp_path / "curves.rigora")
    loaded = DocumentService()
    loaded.open(doc.path)
    assert loaded.animation.evaluate(84) == doc.animation.evaluate(84)
    for _ in range(3):
        doc.undo()
    assert doc.project == baseline


def test_span_creation_hold_conversion_and_locks_are_atomic():
    """One command creates real endpoints; hold keys remain discrete and locked spans refuse."""
    doc = DocumentService()
    doc.new()
    bone = RigService(doc).create_bone((20, 30), (120, 30))
    service = AnimationEditingService(doc)
    before = doc.project
    count = len(doc.history.undo_stack)
    refs = service.create_tween(((bone, "transform.rotation"),), 12, 36)
    assert len(refs) == 2 and len(doc.history.undo_stack) == count + 1
    service.edit_keys({refs[-1]: {"value": 90}})
    assert doc.animation.evaluate(24).nodes[bone].local.rotation == pytest.approx(45)
    service.edit_keys({ref: {"interpolation": "step", "transition_curve": None} for ref in refs})
    assert doc.animation.evaluate(35).nodes[bone].local.rotation == 0
    assert doc.animation.evaluate(36).nodes[bone].local.rotation == 90
    service.set_transition(refs, curve_presets()["Quadratic ease in"])
    track = service.timeline.tracks[0]
    service.track_settings(track.id, locked=True, visible=True)
    locked = doc.project
    with pytest.raises(ProjectError, match="Unlock"):
        service.reverse_keys(refs)
    assert doc.project is locked
    for _ in range(5):
        doc.undo()
    assert doc.project == before


def test_auto_key_records_scene_gesture_with_initial_pose_and_one_undo():
    """Recording moves sampled transforms rather than overwriting their authored rest pose."""
    doc = DocumentService()
    doc.new()
    bone = RigService(doc).create_bone((20, 30), (120, 30))
    service = SceneEditingService(doc)
    service.auto_key = True
    doc.animation.seek(24)
    before, count = doc.project, len(doc.history.undo_stack)
    service.transform((bone,), dx=100, rotation=45)
    assert len(doc.history.undo_stack) == count + 1
    assert service.record(bone).transform.x == 20
    assert doc.animation.evaluate(0).nodes[bone].local.x == 20
    assert doc.animation.evaluate(12).nodes[bone].local.x == 70
    assert doc.animation.evaluate(24).nodes[bone].local.rotation == 45
    doc.animation.seek(48)
    service.transform((bone,), dx=20)
    assert doc.animation.evaluate(48).nodes[bone].local.x == 140
    doc.undo()
    doc.undo()
    assert doc.project == before


def test_presets_repeat_and_graph_validation():
    """Every bundled preset is usable, endpoints are exact and malformed curves are rejected."""
    presets = curve_presets()
    assert len(presets) == 24
    for graph in presets.values():
        assert graph.sample(0) == 0 and graph.sample(1) == 1
        assert TransitionCurve.from_data(graph.to_data()) == graph
    curve = presets["Quadratic ease in"].repeated(3)
    assert curve.sample(1 / 3) == pytest.approx(1 / 3)
    with pytest.raises(ProjectError):
        curve.repeated(8)
    for points in (((0, 0), (0.5, 1), (0.5, 0), (1, 1)), ((0, 0), (0.5, float("nan")), (1, 1))):
        with pytest.raises(ProjectError):
            TransitionCurve(points)
    doc, service, _, refs = animation()
    baseline = doc.project
    with pytest.raises(ProjectError):
        service.edit_keys({refs[0]: {"transition_curve": {"points": [[0, 0]], "smooth": False}}})
    assert doc.project is baseline


def test_legacy_bezier_endpoint_stretch_preserves_normalized_shape():
    """Frame-unit tangent controls scale with their adjoining endpoint intervals."""
    doc, service, bone, refs = animation()
    service.edit_keys(
        {
            refs[0]: {"interpolation": "bezier", "tangent_out": (8, 0)},
            refs[1]: {"tangent_in": (-8, 0)},
        }
    )
    sample = doc.animation.evaluate(6).nodes[bone].local.rotation
    service.edit_keys({refs[1]: {"frame": 48}})
    assert doc.animation.evaluate(12).nodes[bone].local.rotation == pytest.approx(sample)


def test_weighted_auto_key_matches_the_displayed_transform():
    """Recording solves raw weighted values instead of applying the blend weight twice."""
    doc, editor, bone, _ = animation()
    track = editor.timeline.tracks[0]
    editor.publish(
        "Weighted channel",
        replace(editor.timeline, tracks=(replace(track, weight=0.5),)),
        editor.clip,
    )
    doc.animation.seek(12)
    before = doc.animation.pose.nodes[bone].local.rotation
    service = SceneEditingService(doc)
    service.auto_key = True
    service.transform((bone,), rotation=10)
    assert doc.animation.evaluate(12).nodes[bone].local.rotation == pytest.approx(before + 10)


def test_complete_clip_reverse_keeps_its_transition_graph():
    """Clip-level reversal preserves easing rather than reverting a span to linear timing."""
    doc, service, bone, refs = animation()
    service.set_transition(refs, curve_presets()["Back ease out"])
    end = service.clip.out_frame
    times = (0, 5, 18, 24, 95, 100, 112, end)
    expected = [doc.animation.evaluate(end - t).nodes[bone].local.rotation for t in times]
    service.retime(0, end, reverse=True)
    assert [doc.animation.evaluate(t).nodes[bone].local.rotation for t in times] == pytest.approx(
        expected
    )
