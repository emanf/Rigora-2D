"""Canonical lane creation, safe evaluated-key capture and plugin numeric catalog contracts."""

from dataclasses import replace
from pathlib import Path

import pytest

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.deformation import DeformationPreset, DeformationService
from rigora.application_services.documents import DocumentService
from rigora.application_services.meshes import MeshService
from rigora.application_services.plugins import PluginManager
from rigora.application_services.rigging import RigService
from rigora.domain.project import ProjectError
from rigora.infrastructure.preferences import PreferencesStore
from rigora.sdk.scaffold import generate_plugin


def test_empty_group_lanes_capture_evaluate_undo_and_reopen(tmp_path):
    """Adding Position/Scale never changes a pose or duplicates lanes; capture is one undo step."""
    doc = DocumentService()
    doc.new()
    bone = RigService(doc).create_bone((10, 20), (110, 20))
    service = AnimationEditingService(doc)
    channels = tuple((bone, f"transform.{p}") for p in ("x", "y", "scale_x", "scale_y"))
    baseline = doc.animation.evaluate(0)
    count = len(doc.history.undo_stack)
    service.add_channels(channels)
    assert len(doc.history.undo_stack) == count + 1
    assert len(service.timeline.tracks) == 4 and not any(
        t.keyframes for t in service.timeline.tracks
    )
    assert doc.animation.evaluate(0).nodes == baseline.nodes
    service.add_channels(channels)
    assert len(doc.history.undo_stack) == count + 1
    service.add_channels(channels, frame=12)
    assert len(doc.history.undo_stack) == count + 2
    assert [t.keyframes[0].value for t in service.timeline.tracks] == [10, 20, 1, 1]
    doc.undo()
    assert not any(t.keyframes for t in service.timeline.tracks)
    doc.redo()
    doc.save(tmp_path / "channels.rigora")
    clone = DocumentService()
    clone.open(tmp_path / "channels.rigora")
    assert clone.animation.evaluate(12) == doc.animation.evaluate(12)
    assert {c.group for c in service.channels()} >= {"Position", "Scale", "Rotation", "Opacity"}


def test_weighted_key_capture_and_failed_group_are_atomic():
    """Weighted samples retain blend semantics and a locked member prevents the whole edit."""
    doc = DocumentService()
    doc.new()
    bone = RigService(doc).create_bone((10, 0), (110, 0))
    service = AnimationEditingService(doc)
    service.key(bone, "transform.x", 0, 20)
    service.key(bone, "transform.x", 20, 60)
    timeline = service.timeline
    service.publish(
        "Weighted track",
        replace(timeline, tracks=(replace(timeline.tracks[0], weight=0.5),)),
        service.clip,
    )
    before = doc.animation.evaluate(10)
    service.add_channels(((bone, "transform.x"),), frame=10)
    assert doc.animation.evaluate(10) == before
    assert service.timeline.tracks[0].keyframes[1].value == 40
    track = service.timeline.tracks[0]
    service.track_settings(track.id, locked=True, visible=True)
    baseline, count = doc.project, len(doc.history.undo_stack)
    with pytest.raises(ProjectError, match="Unlock"):
        service.add_channels(((bone, "transform.y"), (bone, "transform.x")), frame=12)
    assert doc.project is baseline and len(doc.history.undo_stack) == count
    with pytest.raises(ProjectError, match="supported"):
        service.add_channels(((bone, "future.path"),))
    assert doc.project is baseline


def test_registered_plugin_nested_parameters_have_real_labeled_tracks(tmp_path):
    """A deformer can expose arbitrary nested numeric leaves and readable groups without Qt code."""
    package = generate_plugin(tmp_path / "plugin", "org.timeline.wave", "deformer")
    (package / "__init__.py").write_text(
        '''"""Original nested-parameter example."""
def solve(context):
    """Apply a numeric vertical displacement from a nested parameter."""
    return tuple((x,y+context.parameters['wave']['amplitude']) for x,y in context.points)
def register(context):
    """Publish a solver and optional channel presentation metadata."""
    context.register('deformers','org.timeline.wave.solve','Wave',solve,
        parameters={'wave':{'amplitude':12,'phase':0}},
        animation_channels={
            'parameters.wave.amplitude':{'group':'Secondary motion','label':'Wave height'}})
''',
        encoding="utf-8",
    )
    manager = PluginManager(PreferencesStore(tmp_path / "profile.json"))
    manager.discover((package,), installed=False)
    manager.trust("org.timeline.wave")
    manager.enable("org.timeline.wave")
    try:
        doc = DocumentService()
        doc.new()
        manager.attach(doc)
        mesh = MeshService(doc).import_image(Path("assets/examples/prop.svg"), 2, 2)
        stage = DeformationService(doc).add(
            mesh,
            DeformationPreset(
                "Wave", "org.timeline.wave.solve", {"wave": {"amplitude": 12, "phase": 0}}
            ),
        )
        service = AnimationEditingService(doc)
        channel = next(
            c for c in service.channels() if c.key == (stage, "parameters.wave.amplitude")
        )
        assert (channel.group, channel.label) == ("Secondary motion", "Wave height")
        service.add_channels((channel.key,), frame=0)
        service.key(stage, channel.path, 24, 32)
        assert (
            doc.animation.evaluate(24).meshes[mesh].positions[0][1]
            - doc.animation.evaluate(0).meshes[mesh].positions[0][1]
            == 20
        )
        assert doc.fork().channel_metadata == doc.channel_metadata
        manager.disable("org.timeline.wave")
        manager.attach(doc)
        assert doc.animation.evaluate(0).warnings
        assert service.timeline.tracks[0].property_path == channel.path
    finally:
        manager.shutdown()
