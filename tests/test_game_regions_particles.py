"""Deterministic particle birth transforms and separately exported gameplay region activation."""

import json

import pytest

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.documents import DocumentService
from rigora.application_services.game_authoring import GameAuthoringService
from rigora.application_services.output import OutputService, OutputSettings
from rigora.application_services.rendering import svg_frame
from rigora.domain.project import ProjectError
from rigora.engine.game_regions import game_regions


def test_particles_leave_moving_emitter_and_reproduce_seeks_and_rendered_output(tmp_path):
    """World particles retain birth origins while local particles follow the current emitter."""
    doc = DocumentService()
    doc.new()
    game, edit = GameAuthoringService(doc), AnimationEditingService(doc)
    settings = dict(rate=2, lifetime=2, speed=0, gravity=0, start=0, end=24, size=4, seed=31)
    key = game.emitter(x=10, y=30, settings=settings)
    edit.key(key, "transform.x", 0, 10)
    edit.key(key, "transform.x", 24, 110)
    expected = doc.animation.evaluate(12).particles[key]
    assert [p.matrix[4] for p in expected] == pytest.approx([10, 60])
    for frame in (4, 20, 12, 1, 12):
        pose = doc.animation.evaluate(frame)
        if frame == 12:
            assert pose.particles[key] == expected
    source = svg_frame(doc, 12)
    assert b'<circle r="1"/>' in source
    game.emitter(identity=key, settings={**settings, "world_space": False})
    assert [p.matrix[4] for p in doc.animation.evaluate(12).particles[key]] == pytest.approx(
        [60, 60]
    )
    before = doc.project
    with pytest.raises(ProjectError):
        game.emitter(settings=dict(rate=1000, lifetime=60))
    assert doc.project is before
    doc.undo()
    assert doc.animation.evaluate(12).particles[key] == expected
    doc.save(tmp_path / "particles.rigora")
    doc.open(doc.path)
    assert svg_frame(doc, 12) == source


def test_hitbox_visibility_transform_and_runtime_metadata_without_rendered_artwork(tmp_path):
    """Collision shapes follow ordinary keys, remain out of rendered SVG and survive export."""
    doc = DocumentService()
    doc.new()
    service = GameAuthoringService(doc)
    key = service.region(name="Sword damage", width=60, height=20, x=100, y=80)
    edit = AnimationEditingService(doc)
    edit.key(key, "visibility", 0, 0, interpolation="step")
    edit.key(key, "visibility", 5, 1, interpolation="step")
    edit.key(key, "transform.rotation", 5, 90)
    assert not game_regions(doc.scene, doc.animation.evaluate(4))[0]["enabled"]
    shape = game_regions(doc.scene, doc.animation.evaluate(5))[0]
    assert shape["enabled"]
    assert shape["points"][0] == pytest.approx((110, 50))
    assert b"Sword damage" not in svg_frame(doc, 5)
    output = OutputService(lambda path: tmp_path / path)
    output.export(
        doc,
        "regions.json",
        OutputSettings(format="runtime-json", frames=(4, 5), width=64, height=64),
    )
    payload = json.loads((tmp_path / "regions.json").read_text())
    assert not payload["samples"][0]["regions"][0]["enabled"]
    assert payload["samples"][1]["regions"][0]["enabled"]


def test_object_scope_keeps_other_regions_out_of_authoring_and_export():
    """Entering an Object exposes only its owned regions, including after empty-view selection."""
    from rigora.application_services.characters import CharacterService

    doc = DocumentService()
    doc.new()
    chars, game = CharacterService(doc), GameAuthoringService(doc)
    root = chars.create_object(name="Owned regions")
    outside = game.region(name="Scene region")
    doc.set_animation_context(root, frozenset(chars.members(root)))
    inside = game.region(name="Object region")
    doc.set_animation_context(root, frozenset(chars.members(root)))
    pose = doc.animation.evaluate(0)
    assert pose.region_owners == frozenset((inside,))
    assert [r["id"] for r in game_regions(doc.scene, pose)] == [inside]
    doc.set_animation_context(None)
    assert {r["id"] for r in game_regions(doc.scene, doc.animation.evaluate(0))} == {
        inside,
        outside,
    }


def test_ground_and_magnet_physics_are_bounded_and_seek_order_independent(tmp_path):
    """Original particles bounce without penetrating their radius and magnets attract/repel."""
    doc = DocumentService()
    doc.new()
    service = GameAuthoringService(doc)
    settings = dict(
        rate=0,
        burst=1,
        lifetime=4,
        speed=0,
        gravity=300,
        size=5,
        ground_enabled=True,
        ground_y=100,
        bounce=0.7,
        friction=0.2,
    )
    key = service.emitter(x=0, y=0, settings=settings)
    samples = {frame: doc.animation.evaluate(frame).particles[key] for frame in (0, 12, 24, 36, 48)}
    assert all(parts[0].matrix[5] <= 95 for parts in samples.values())
    assert samples[36][0].matrix[5] < 95
    for frame in (48, 12, 36, 0, 24):
        assert doc.animation.evaluate(frame).particles[key] == samples[frame]
    settings.update(
        gravity=0,
        ground_enabled=False,
        magnet_enabled=True,
        magnet_x=100,
        magnet_y=0,
        magnet_radius=300,
        magnet_strength=200,
    )
    service.emitter(identity=key, settings=settings)
    attracted = doc.animation.evaluate(24).particles[key][0].matrix
    assert attracted[4] > 10 and attracted[5] == 0
    service.emitter(identity=key, settings={**settings, "magnet_strength": -200})
    assert doc.animation.evaluate(24).particles[key][0].matrix[4] < -10
    before = doc.project
    with pytest.raises(ProjectError, match="World space"):
        service.emitter(identity=key, settings={**settings, "world_space": False})
    assert doc.project is before
    source = svg_frame(doc, 24)
    doc.save(tmp_path / "physics.rigora")
    doc.open(doc.path)
    assert svg_frame(doc, 24) == source
