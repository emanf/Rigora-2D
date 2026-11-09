"""Grounded support intervals, reversible targets, ordinary weight tracks and separate FK bakes."""

import math
from dataclasses import replace

import pytest

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.characters import CharacterService
from rigora.application_services.contact_editing import ContactEditingService
from rigora.application_services.documents import DocumentService
from rigora.application_services.rigging import RigService
from rigora.domain.geometry import transform_point


def contact_scene():
    """Build a movable two-segment leg with an optional articulated foot."""
    doc = DocumentService()
    doc.new()
    rig = RigService(doc)
    upper = rig.create_bone((100, 100), (200, 100))
    lower = rig.create_bone((200, 100), (300, 100), upper)
    foot = rig.create_bone((300, 100), (330, 100), lower)
    base = doc.animation.pose.nodes[upper].local
    edit = AnimationEditingService(doc)
    edit.key(upper, "transform.y", 0, base.y)
    edit.key(upper, "transform.y", 12, base.y + 80)
    return doc, upper, lower, foot


def test_foot_contact_holds_ankle_releases_and_preserves_rest_and_random_seek_order(tmp_path):
    """A support interval pins the foot while hips move, then releases at its last key."""
    doc, upper, lower, foot = contact_scene()
    original = doc.project
    service = ContactEditingService(doc)
    key = service.interval(upper, lower, 4, 20, foot=foot, space="world")
    rule = next(r for r in doc.scene.constraints if r.id == key)
    target = doc.animation.evaluate(8).nodes[rule.target_id].world_matrix[4:]
    for frame in (4, 8, 19, 6, 12, 4):
        pose = doc.animation.evaluate(frame)
        assert not pose.warnings
        ankle = transform_point(pose.nodes[lower].world_matrix, pose.nodes[lower].length, 0)
        assert math.dist(ankle, target) < 1e-5
    released = doc.animation.evaluate(20)
    assert (
        math.dist(
            transform_point(released.nodes[lower].world_matrix, released.nodes[lower].length, 0),
            target,
        )
        > 10
    )
    assert doc.scene.skeletons == original.scenes[0].skeletons
    channels = AnimationEditingService(doc).properties()
    assert any(o.id == key and p == "parameters.weight" for o, p, _ in channels)
    doc.save(tmp_path / "contact.rigora")
    loaded = DocumentService()
    loaded.open(doc.path)
    assert loaded.animation.evaluate(8) == doc.animation.evaluate(8)
    doc.undo()
    assert doc.project == original


def test_contact_bake_matches_evaluated_motion_and_removal_preserves_artwork():
    """Baking preserves the source; removal keeps bones and deletes the owned target."""
    doc, upper, lower, foot = contact_scene()
    service = ContactEditingService(doc)
    key = service.interval(upper, lower, 0, 20, foot=foot)
    source = doc.project
    expected = {f: doc.animation.evaluate(f).nodes[lower].world_matrix for f in range(20)}
    baked = service.bake_contacts(0, 19)
    assert doc.selected_clip_id == baked
    for frame, matrix in expected.items():
        assert doc.animation.evaluate(frame).nodes[lower].world_matrix == pytest.approx(matrix)
    doc.undo()
    assert doc.project == source
    target = next(r.target_id for r in doc.scene.constraints if r.id == key)
    bones = doc.scene.skeletons
    service.remove_contact(key)
    assert doc.scene.skeletons == bones
    assert target not in {o.id for o in doc.scene.objects}
    assert not any(t.owner_id in (key, target) for line in doc.scene.timelines for t in line.tracks)
    doc.undo()
    assert doc.project == source


def test_contacts_follow_object_space_and_compensate_near_unreachable_anchors():
    """Object placement carries its anchor; folded targets respect the knee's angle limit."""
    doc, upper, lower, foot = contact_scene()
    owner = CharacterService(doc).create_object(name="Walker")
    rig = RigService(doc)
    rig.commit(
        "Own rig",
        skeletons=tuple(
            replace(r, extra={**r.extra, "object_id": owner}) for r in doc.scene.skeletons
        ),
    )
    rig.set_minimum_joint_angle((lower,), 30)
    node = doc.animation.pose.nodes[upper]
    service = ContactEditingService(doc)
    key = service.interval(
        upper, lower, 0, 20, foot=foot, x=node.world_matrix[4], y=node.world_matrix[5]
    )
    rule = next(c for c in doc.scene.constraints if c.id == key)
    for offset in (0, 120):
        group = next(g for g in doc.scene.groups if g.id == owner)
        service.commit(
            "Place object",
            groups=tuple(
                replace(g, transform=replace(group.transform, x=group.transform.x + offset))
                if g.id == owner
                else g
                for g in doc.scene.groups
            ),
        )
        pose = doc.animation.evaluate(5)
        assert not pose.warnings
        ankle = transform_point(pose.nodes[lower].world_matrix, pose.nodes[lower].length, 0)
        assert math.dist(ankle, pose.nodes[rule.target_id].world_matrix[4:]) < 1e-5
