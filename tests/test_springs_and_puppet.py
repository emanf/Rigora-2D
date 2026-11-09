"""Deterministic and interactive secondary dynamics plus portable motion-card performance
recording.
"""

import math
from dataclasses import replace

import pytest

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.content_library import ContentLibrary, ContentService
from rigora.application_services.documents import DocumentService
from rigora.application_services.puppet import MotionCard, PuppetService, PuppetSession
from rigora.application_services.rigging import RigService
from rigora.domain.geometry import affine, transform_point
from rigora.domain.project import ProjectError
from rigora.engine.constraints import ConstraintContext
from rigora.engine.springs import SpringSimulation
from rigora.infrastructure.preferences import PreferencesStore


@pytest.mark.parametrize("translate", [False, True])
@pytest.mark.parametrize("scale", [(1, 1), (-1.3, 0.8), (0.7, 1.4)])
def test_spring_chain_keeps_joints_attached_with_pivots_and_scaled_parents(translate, scale):
    """Strong live motion deforms connected bone lengths without introducing any joint gaps."""
    from rigora.application_services.dynamics import DynamicsService

    doc = DocumentService()
    doc.new()
    rig = RigService(doc)
    root = rig.create_bone((100, 100), (200, 100))
    child = rig.create_bone((200, 100), (280, 100), root)
    tip = rig.create_bone((280, 100), (340, 100), child)
    DynamicsService(doc).configure(
        (child, tip),
        translate=translate,
        stretch=40,
        squash=100,
        gravity=900,
        inertia=1.2,
        clockwise=35,
        counterclockwise=20,
    )
    context = ConstraintContext(list(doc.animation.pose.nodes.values()))
    for key in (child, tip):
        node = context.node(key)
        local = node.local._replace(pivot_x=13, pivot_y=7)
        matrix = affine(*local)
        context.local(
            key,
            local._replace(
                x=local.x + node.local_matrix[4] - matrix[4],
                y=local.y + node.local_matrix[5] - matrix[5],
            ),
        )
    node = context.node(root)
    context.local(root, node.local._replace(scale_x=scale[0], scale_y=scale[1]))
    rest = list(context.nodes.values())
    root_node = context.node(root)
    simulation = SpringSimulation()
    rules = doc.animation.evaluator.springs
    simulation.advance(rest, rules, 1 / 60)
    strained = False
    for frame in range(1, 151):
        context = ConstraintContext(rest)
        context.local(
            root,
            root_node.local._replace(
                x=100 + 80 * math.sin(frame / 9),
                y=100 + 45 * math.cos(frame / 13),
                rotation=45 * math.sin(frame / 17),
            ),
        )
        target = context.nodes
        result = {n.id: n for n in simulation.advance(list(target.values()), rules, 1 / 60)}
        assert result[root].world_matrix == target[root].world_matrix
        for key in (child, tip):
            current = result[key]
            parent = result[current.parent_id]
            assert current.world_matrix[4:] == pytest.approx(
                transform_point(parent.world_matrix, parent.length, 0), abs=1e-7
            )
            ratio = math.hypot(*current.world_matrix[:2]) / math.hypot(
                *target[key].world_matrix[:2]
            )
            assert 0.001 - 1e-10 <= ratio <= 1.4 + 1e-10
            strained |= abs(ratio - 1) > 1e-4
            assert all(math.isfinite(v) for v in current.world_matrix)
    assert strained is translate


def test_deep_spring_chain_does_not_compound_squash_into_singular_parent_spaces():
    """Full squash and strong acceleration remain bounded across a long attached chain."""
    from rigora.application_services.dynamics import DynamicsService

    doc = DocumentService()
    doc.new()
    rig, keys = RigService(doc), []
    for i in range(12):
        keys.append(rig.create_bone((i * 50, 100), ((i + 1) * 50, 100), keys[-1] if keys else None))
    DynamicsService(doc).configure(
        tuple(keys[1:]),
        translate=True,
        rotate=False,
        squash=100,
        stretch=100,
        frequency=0.5,
        damping=0.05,
        inertia=3,
    )
    rest = list(doc.animation.pose.nodes.values())
    rules, simulation = doc.animation.evaluator.springs, SpringSimulation()
    simulation.advance(rest, rules, 1 / 60)
    for frame in range(30):
        context = ConstraintContext(rest)
        root = context.node(keys[0])
        context.local(root.id, root.local._replace(x=400 * (frame % 2)))
        result = {n.id: n for n in simulation.advance(list(context.nodes.values()), rules, 0.1)}
        for key in keys[1:]:
            node = result[key]
            parent = result[node.parent_id]
            assert node.world_matrix[4:] == pytest.approx(
                transform_point(parent.world_matrix, parent.length, 0)
            )
            assert 0.001 - 1e-10 <= math.hypot(*node.world_matrix[:2]) <= 2 + 1e-10


def test_flat_bone_does_not_divide_by_zero_during_spring_length_compensation():
    """A zero-scale leaf stays flat rather than crashing the interactive physics timer."""
    doc = DocumentService()
    doc.new()
    rig = RigService(doc)
    root = rig.create_bone((100, 100), (200, 100))
    child = rig.create_bone((200, 100), (280, 100), root)
    rule = rig.add_constraint(child, "spring")
    context = ConstraintContext(list(doc.animation.pose.nodes.values()))
    node = context.node(child)
    context.local(child, node.local._replace(scale_x=0))
    simulation = SpringSimulation()
    result = simulation.advance(
        list(context.nodes.values()),
        tuple(c for c in rig.scene.constraints if c.id == rule),
        1 / 60,
    )
    assert next(n for n in result if n.id == child).world_matrix[:2] == (0, 0)


def test_spring_sampling_seek_order_fixed_root_and_live_settling():
    """A child lags parent motion, preserves the anchor, and produces repeatable random seeks."""
    document = DocumentService()
    document.new()
    rig = RigService(document)
    root = rig.create_bone((100, 100), (200, 100))
    child = rig.create_bone((200, 100), (300, 100), root)
    master = rig.bone(root).parent_id
    assert master is not None and rig.bone(master).extra.get("rig_root")
    with pytest.raises(ProjectError, match="kinematic anchor"):
        rig.add_constraint(master, "spring")
    rule = rig.add_constraint(child, "spring", frequency=3, damping=0.5, inertia=0.6)
    editor = AnimationEditingService(document)
    editor.key(root, "transform.rotation", 0, 0)
    editor.key(root, "transform.rotation", 12, 90)
    assert not document.animation.pose.warnings
    pose = document.animation.evaluate(6)
    assert pose.nodes[root].world_matrix[4:] == (100, 100)
    assert abs(pose.nodes[child].local.rotation) > 1
    first = document.animation.evaluate(8)
    document.animation.evaluate(2)
    assert document.animation.evaluate(8) == first
    simulation = SpringSimulation()
    rest = tuple(document.animation.evaluate(0).nodes.values())
    rules = (next(c for c in rig.scene.constraints if c.id == rule),)
    simulation.advance(rest, rules, 1 / 60)
    target = list(rest)
    root_index = next(i for i, node in enumerate(target) if node.id == root)
    child_index = next(i for i, node in enumerate(target) if node.id == child)
    source = target[root_index]
    from rigora.domain.geometry import affine, multiply

    local = source.local._replace(rotation=40)
    target[root_index] = replace(
        source, local=local, local_matrix=affine(*local), world_matrix=affine(*local)
    )
    target[child_index] = replace(
        target[child_index],
        world_matrix=multiply(target[root_index].world_matrix, target[child_index].local_matrix),
    )
    initial = simulation.advance(target, rules, 1 / 60)
    for _ in range(180):
        settled = simulation.advance(target, rules, 1 / 60)
    assert initial[root_index].world_matrix == target[root_index].world_matrix
    assert abs(initial[child_index].local.rotation) > abs(settled[child_index].local.rotation)
    assert all(math.isfinite(v) for n in settled for v in n.world_matrix)


def test_puppet_preview_looping_recording_profiles_and_undo(tmp_path):
    """Card previews stay isolated; loops record ordinary keys as one undoable scene command."""
    doc = DocumentService()
    doc.new()
    entries = ContentLibrary(PreferencesStore(tmp_path / "ui.json")).entries()
    service = PuppetService(doc)
    template = next(e.item for e in entries if e.item.name == "Human · full body")
    rig = ContentService(doc).apply(template, {})
    walk = next(e.item for e in entries if e.item.name == "Natural · Walk")
    key = service.add(rig, walk, hotkey="W")
    card = service.cards()[0]
    assert card.id == key
    source = doc.project
    preview = PuppetSession(doc)
    preview.trigger(card, 0)
    a = preview.pose(3)
    period = walk.payload["duration"] * doc.project.scenes[0].settings.fps / walk.payload["fps"]
    b = preview.pose(3 + period)
    assert doc.project is source and a.nodes.keys() == b.nodes.keys()
    for node_id, node in a.nodes.items():
        assert b.nodes[node_id].world_matrix == pytest.approx(node.world_matrix, abs=1e-8)
        assert b.nodes[node_id].visible == node.visible
        assert b.nodes[node_id].opacity == pytest.approx(node.opacity)
    recording = PuppetSession(doc, recording=True)
    recording.trigger(card, 0)
    recording.pose(55)
    count = len(doc.history.undo_stack)
    recording.commit()
    assert doc.project is not source and len(doc.history.undo_stack) == count + 1
    assert doc.project.scenes[0].clips
    assert all(
        "cycle" not in track.extra
        for timeline in doc.project.scenes[0].timelines
        for track in timeline.tracks
    )
    assert doc.animation.evaluate(3).nodes != doc.animation.evaluate(15).nodes
    doc.undo()
    assert doc.project == source
    profile = tmp_path / "motions.rigpuppet"
    service.export_profile(profile)
    service.set_cards(())
    service.import_profile(profile, rig)
    assert service.cards()[0].name == "Natural · Walk"
    with pytest.raises(ProjectError, match="preserved"):
        service.export_profile(profile)


def test_puppet_effect_keys_and_changed_source_are_safe():
    """Visibility, flip and opacity are actual evaluated channels; stale recordings never
    publish.
    """
    doc = DocumentService()
    doc.new()
    from rigora.application_services.commands import ScenePatch
    from rigora.domain.entities import SceneObject

    obj = SceneObject()
    scene = doc.project.scenes[0]
    doc.execute(ScenePatch("Object", scene.id, {"objects": ()}, {"objects": (obj,)}))
    source = doc.project
    session = PuppetSession(doc, recording=True)
    session.trigger(MotionCard(target_id=obj.id, kind="visibility"), 4)
    assert session.pose(0).nodes[obj.id].visible
    assert not session.pose(5).nodes[obj.id].visible
    session.trigger(MotionCard(target_id=obj.id, kind="visibility"), 6)
    session.trigger(MotionCard(target_id=obj.id, kind="flip_x"), 7)
    session.trigger(MotionCard(target_id=obj.id, kind="opacity"), 8)
    pose = session.pose(9)
    assert pose.nodes[obj.id].visible and pose.nodes[obj.id].local.scale_x == -1
    assert pose.nodes[obj.id].opacity == 0.25 and doc.project is source
    doc.new()
    with pytest.raises(ProjectError, match="changed"):
        session.commit()
