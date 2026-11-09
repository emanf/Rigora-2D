"""Acceptance evidence for coupled Spring/Pilot motion, selective baking and legacy settings."""

import json
import math
import zipfile
from dataclasses import replace

import pytest
from test_dynamics import animated_chain
from test_editable_rig_export import check_geometry, decode_glb

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.character_creation import CharacterCreationService
from rigora.application_services.characters import CharacterService
from rigora.application_services.documents import DocumentService
from rigora.application_services.dynamics import DynamicsService
from rigora.application_services.motion_pilot import MotionPilotSession
from rigora.application_services.output import OutputService, OutputSettings
from rigora.application_services.rigging import RigService
from rigora.application_services.vector_creation import build_vector, vector_colors
from rigora.domain.motion_pilot import MotionPilotProfile
from rigora.domain.project import ProjectError
from rigora.domain.vector_catalog import VectorRecipe
from rigora.engine.springs import SpringSimulation


def test_baked_native_motion_bypasses_secondary_physics_and_action_import_remaps(tmp_path):
    """Loaded baked clips retain their simulated result without a second Spring pass."""
    doc, root, tip = animated_chain()
    service = DynamicsService(doc)
    baked = service.bake(tail_seconds=0)
    expected = doc.animation.evaluate(12).nodes[tip].world_matrix
    path = tmp_path / "spring-baked.rigaction"
    AnimationEditingService(doc).export_action(path)
    other, _, other_tip = animated_chain()
    imported = AnimationEditingService(other).import_action(path)
    assert (
        other_tip
        in next(c for c in DynamicsService(other).scene.clips if c.id == imported).extra[
            "spring_baked_bones"
        ]
    )
    assert other.animation.evaluate(12).nodes[other_tip].world_matrix == pytest.approx(expected)
    AnimationEditingService(doc).new_clip("Baked motion recording")
    session = MotionPilotSession(
        doc,
        (next(b.id for b in doc.scene.skeletons[0].bones if b.extra.get("rig_root")),),
        MotionPilotProfile(
            move=False, motion_enabled=True, motion_in_place=False, motion_clips=(baked,)
        ),
        recording=True,
    )
    actual = session.feed(12, (0, 0))
    assert actual.nodes[tip].world_matrix == pytest.approx(expected)
    assert not session.evaluator.active_springs(12)
    session.commit()
    assert not doc.animation.evaluator.active_springs(12)
    assert doc.animation.evaluate(12).nodes[tip].world_matrix == pytest.approx(expected)


def test_physical_controls_change_bounce_settling_gravity_and_rest_limits():
    """Compare actual release trajectories rather than inspecting the parameter mapping formula."""
    doc, _, tip = animated_chain()
    service = DynamicsService(doc)
    nodes = doc.animation.evaluator.sample_kinematic(0)

    def release(frequency, damping, gravity=0):
        service.configure((tip,), frequency=frequency, damping=damping, gravity=gravity)
        rule = service.scene.constraints[0]
        sim = SpringSimulation()
        sim.advance(nodes, (rule,), 1 / 60)
        if not gravity:
            sim.excite(nodes, (rule,))
        angles = []
        for _ in range(180):
            pose = sim.advance(nodes, (rule,), 1 / 60)
            angles.append(next(n.local.rotation for n in pose if n.id == tip))
        return angles

    bouncing, damped = release(2, 0.1), release(2, 1)
    assert min(bouncing) < -10 and min(damped) > -0.1
    slow, fast = release(0.8, 0.5), release(5, 0.5)
    assert max(abs(v) for v in fast[90:]) < max(abs(v) for v in slow[90:]) / 10
    assert release(2, 0.5, 1000)[-1] > 0
    assert release(2, 0.5, -1000)[-1] < 0
    service.configure((tip,), frequency=1, damping=0.1, clockwise=25, counterclockwise=10)
    for frame in range(49):
        angle = math.remainder(doc.animation.evaluate(frame).nodes[tip].local.rotation, 360)
        assert -10.00001 <= angle <= 25.00001


def test_group_bake_preserves_other_springs_tail_undo_and_custom_legacy_reload(tmp_path):
    """Bake one group faithfully; preserve its live source and migrate old named groups."""
    doc, root, tip = animated_chain()
    ear = RigService(doc).create_bone((400, 300), (400, 360), root)
    service = DynamicsService(doc)
    service.configure((tip,), group="Hair", frequency=1, damping=0.2)
    service.configure((ear,), group="Ear", frequency=3, damping=0.5)
    service.group_color("Hair", "#987abc")
    service.save_custom_preset("Soft custom", "Hair")
    assert service.scene.extra["spring_presets"]["Soft custom"]["frequency"] == 1
    source = service.clip
    reference = {frame: doc.animation.evaluate(frame) for frame in (0, 6, 12, 36, 48)}
    before = doc.project
    service.bake("Hair", tail_seconds=0)
    assert service.clip.out_frame > source.out_frame + 24
    assert set(service.clip.extra["spring_baked_bones"]) == {tip}
    assert {r.owner_id for r in doc.animation.evaluator.springs} == {ear}
    assert next(c for c in service.scene.clips if c.id == source.id) == source
    for frame, expected in reference.items():
        pose = doc.animation.evaluate(frame)
        for key in (tip, ear):
            assert pose.nodes[key].world_matrix == pytest.approx(
                expected.nodes[key].world_matrix, abs=1e-6
            )
    with pytest.raises(ProjectError, match="no live"):
        service.bake("Hair")
    doc.undo()
    assert doc.project == before
    identity = service.group_metadata("Hair")["id"]
    service.commit(
        "Legacy fixture",
        extra={
            key: value
            for key, value in service.scene.extra.items()
            if key != "spring_group_metadata"
        },
    )
    legacy = tmp_path / "legacy-springs.rigora"
    doc.save(legacy)
    contents = legacy.read_bytes()
    expected = doc.animation.evaluate(36).nodes
    other = DocumentService()
    other.open(legacy)
    assert legacy.read_bytes() == contents
    assert DynamicsService(other).group_metadata("Hair")["id"] == identity
    assert other.animation.evaluate(36).nodes == expected
    assert DynamicsService(other).scene.extra["spring_presets"]["Soft custom"]["frequency"] == 1


def test_native_walk_pointer_motion_and_springs_preview_record_bake_and_seek_match(tmp_path):
    """A premade Panda walks under pointer motion with independent live secondary motion."""
    doc = DocumentService()
    doc.new()
    primary, accent = vector_colors("Animals", "bean")
    owner = CharacterCreationService(doc).create(
        build_vector(VectorRecipe(design_id="bean", name="bean", primary=primary, accent=accent))
    )
    doc.set_animation_context(None)
    service = DynamicsService(doc)
    tail = next(b.id for r in service.scene.skeletons for b in r.bones if b.name == "tail")
    service.configure((tail,), group="Tail", frequency=2, damping=0.4)
    walk = next(c for c in CharacterService(doc).motions(owner) if c.name == "Walk")
    bones = tuple(b.id for rig in service.scene.skeletons for b in rig.bones)
    leg = next(
        b.id for rig in service.scene.skeletons for b in rig.bones if b.name == "upper_arm.L"
    )
    RigService(doc).add_constraint(leg, "pin")
    service.commit(
        "Authored FK motion fixture",
        clips=tuple(
            replace(c, extra={**c.extra, "fk_bones": bones}) if c.id == walk.id else c
            for c in service.scene.clips
        ),
    )
    profile = MotionPilotProfile(motion_enabled=True, motion_clips=(walk.id,), optimize=False)
    session = MotionPilotSession(doc, (owner,), profile, recording=True)
    preview = session.feed(12, (60, 150))
    assert session.evaluator._frame_fk(12)
    assert tail in {r.owner_id for r in session.evaluator.active_springs(12)}
    session.commit()
    recorded = doc.animation.evaluate(12)
    assert recorded.nodes[tail].world_matrix == pytest.approx(
        preview.nodes[tail].world_matrix, abs=1e-6
    )
    for key in recorded.meshes:
        for point, expected in zip(
            recorded.meshes[key].positions, preview.meshes[key].positions, strict=True
        ):
            assert point == pytest.approx(expected)
    doc.animation.evaluate(80)
    assert doc.animation.evaluate(12).nodes[tail].world_matrix == pytest.approx(
        recorded.nodes[tail].world_matrix
    )
    service.bake("Tail", tail_seconds=0)
    baked = doc.animation.evaluate(12)
    assert tail not in {r.owner_id for r in doc.animation.evaluator.springs}
    assert baked.nodes[tail].world_matrix == pytest.approx(
        recorded.nodes[tail].world_matrix, abs=1e-6
    )
    destination = tmp_path / "combined.rigora"
    doc.save(destination)
    other = DocumentService()
    other.open(destination)
    other.select_animation_clip(service.clip.id)
    assert other.animation.evaluate(12).nodes == baked.nodes
    output = tmp_path / "combined-godot.zip"
    result = OutputService(lambda _: output).export(
        other,
        str(output),
        OutputSettings(format="godot-rig", frames=(0, 12), width=128, height=128),
    )
    assert result["status"] == "completed"
    with zipfile.ZipFile(output) as archive:
        gltf, binary = decode_glb(archive.read("character.glb"))
        runtime = json.loads(archive.read("rig.json"))
        check_geometry(other, gltf, binary, runtime, (0, 12))
