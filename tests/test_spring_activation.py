"""Editable activation keys gate canonical fixed-step dynamics without seek-order state leaks."""

import pytest
from test_dynamics import animated_chain

from rigora.application_services.documents import DocumentService
from rigora.application_services.dynamics import DynamicsService


def test_object_motion_drives_springs_in_scene_space_without_double_transform():
    """A premade animal's container motion excites its tail while the root stays in bind space."""
    from rigora.application_services.animation_editing import AnimationEditingService
    from rigora.application_services.character_creation import (
        CharacterCreationService,
        build_character,
    )
    from rigora.domain.character_recipe import CharacterRecipe

    doc = DocumentService()
    doc.new()
    owner = CharacterCreationService(doc).create(
        build_character(CharacterRecipe(design_id="sumi", name="Sumi", motions=()))
    )
    doc.set_animation_context(None)
    editor = AnimationEditingService(doc)
    editor.key(owner, "transform.y", 0, 0)
    editor.key(owner, "transform.y", 8, 150)
    editor.key(owner, "transform.y", 16, -100)
    service = DynamicsService(doc)
    rig = service.scene.skeletons[0]
    tail = next(b.id for b in rig.bones if b.name == "tail")
    root = next(b.id for b in rig.bones if not b.parent_id)
    service.configure((tail,), gravity=0, frequency=2, damping=0.3)
    evaluator = doc.animation.evaluator
    pose = evaluator.evaluate(12)
    kinematic = {n.id: n for n in evaluator.sample_kinematic(12)}
    assert pose.nodes[root].world_matrix == pytest.approx(kinematic[root].world_matrix)
    assert pose.nodes[tail].world_matrix != pytest.approx(kinematic[tail].world_matrix)
    assert not pose.warnings
    evaluator.evaluate(35)
    assert evaluator.evaluate(12).nodes[tail].world_matrix == pytest.approx(
        pose.nodes[tail].world_matrix
    )


def test_group_and_master_activation_scrub_edit_undo_and_reload(tmp_path):
    """Group keys and master keys stop procedural motion while retaining authored transforms."""
    doc, root, tip = animated_chain()
    service = DynamicsService(doc)
    service.configure((tip,), group="Hair", gravity=600)
    service.group_color("Hair", "#987abc")
    identity = service.group_metadata("Hair")["id"]
    service.activation("Hair", False, 18)
    service.activation("Hair", True, 30)
    evaluator = doc.animation.evaluator
    assert evaluator.active_springs(17) and not evaluator.active_springs(18)
    assert evaluator.active_springs(30)
    at_off = evaluator.evaluate(24).nodes[tip]
    assert (
        at_off.world_matrix
        == next(n for n in evaluator.sample_kinematic(24) if n.id == tip).world_matrix
    )
    continuous = [evaluator.evaluate(f).nodes[tip].world_matrix for f in range(41)][-1]
    evaluator.evaluate(48)
    assert evaluator.evaluate(40).nodes[tip].world_matrix == pytest.approx(continuous)
    service.activation("Hair", False, 36, master=True)
    assert not doc.animation.evaluator.active_springs(40)
    doc.undo()
    assert doc.animation.evaluator.active_springs(40)
    service.rename_group("Hair", "Ears")
    assert service.group_metadata("Ears")["id"] == identity
    assert service.group_metadata("Ears")["color"] == "#987abc"
    assert all(
        t.extra["spring_group"] == "Ears"
        for t in service.timeline.tracks
        if t.extra.get("spring_activation")
    )
    target = tmp_path / "springs.rigora"
    doc.save(target)
    other = DocumentService()
    other.open(target)
    assert other.animation.evaluate(40).nodes[tip].world_matrix == pytest.approx(continuous)
    assert DynamicsService(other).group_metadata("Ears")["id"] == identity
    service.remove_group("Ears")
    assert not any(t.extra.get("spring_activation") for t in service.timeline.tracks)
    assert not service.scene.constraints
    assert root in doc.animation.pose.nodes


def test_reassignment_adopts_destination_activation_and_unassign_removes_old_gate():
    """A bone follows its new group's keyed state without retaining contradictory old gates."""
    from rigora.application_services.rigging import RigService

    doc, root, tip = animated_chain()
    ear = RigService(doc).create_bone((400, 300), (400, 350), root)
    service = DynamicsService(doc)
    service.configure((tip,), group="Hair")
    service.configure((ear,), group="Ears")
    service.activation("Hair", False, 10)
    service.activation("Ears", False, 20)
    before = doc.project
    service.configure((tip,), group="Ears")
    assert service.group_members("Hair") == ()
    assert {r.owner_id for r in doc.animation.evaluator.active_springs(15)} == {tip, ear}
    assert not doc.animation.evaluator.active_springs(20)
    gates = [t for t in service.timeline.tracks if t.owner_id == tip]
    assert len(gates) == 1 and gates[0].extra["spring_group"] == "Ears"
    doc.undo()
    assert doc.project == before
    service.unassign_group((tip,), {"Hair"})
    assert not any(t.owner_id == tip for t in service.timeline.tracks)


def test_long_seek_reconstructs_full_history_and_reuses_bounded_checkpoints(monkeypatch):
    """A cold seek beyond six seconds matches replay; nearby rewinds reuse retained ticks."""
    from rigora.application_services.animation_editing import AnimationEditingService
    from rigora.engine.evaluation import SceneEvaluator
    from rigora.engine.springs import SpringSimulation

    doc, _, tip = animated_chain()
    AnimationEditingService(doc).clip_settings(out_frame=2000)
    DynamicsService(doc).configure((tip,), frequency=0.5, damping=0.05)
    evaluator = doc.animation.evaluator
    for frame in range(241):
        expected = evaluator.evaluate(frame).nodes[tip].world_matrix
    cold = SceneEvaluator(evaluator.scene, evaluator.clip.id)
    assert cold.evaluate(240).nodes[tip].world_matrix == pytest.approx(expected, abs=1e-10)
    calls = []
    original = SpringSimulation.advance

    def counted(self, nodes, rules, dt):
        """Measure replay work independently of host CPU speed."""
        calls.append(dt)
        return original(self, nodes, rules, dt)

    monkeypatch.setattr(SpringSimulation, "advance", counted)
    evaluator.evaluate(216)
    assert len(calls) <= 61
    evaluator.evaluate(2000)
    assert len(evaluator.spring_cursor.checkpoints) <= 65
    assert 0 in evaluator.spring_cursor.checkpoints


def test_spring_row_lock_protects_new_master_channel():
    """A new master switch cannot bypass a locked grouped Spring row."""
    from rigora.domain.project import ProjectError

    doc, _, _ = animated_chain()
    service = DynamicsService(doc)
    service.activation("Default", True, 0)
    track = next(t for t in service.timeline.tracks if t.property_path == "spring.enabled")
    service.track_settings(track.id, locked=True, visible=True)
    before = doc.project
    with pytest.raises(ProjectError, match="Unlock"):
        service.activation("Default", False, 5, master=True)
    assert doc.project is before
