"""Older world-space contact targets remain owned and follow the selected bone-editing scope."""

from dataclasses import replace

import pytest

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.characters import CharacterService
from rigora.application_services.documents import DocumentService
from rigora.application_services.object_library import object_fragment
from rigora.application_services.rigging import RigService
from rigora.domain.entities import Bone, Constraint, Group, Skeleton, Transform
from rigora.domain.rig_roots import rooted_skeleton


def contact_document():
    doc = DocumentService()
    doc.new()
    owner = Group(name="Actor", extra={"object_container": True})
    hip = Bone(name="hips", length=60, transform=Transform(x=20, y=30))
    foot = Bone(name="foot.L", parent_id=hip.id, length=20, transform=Transform(x=60))
    rig = rooted_skeleton(
        Skeleton(bones=(hip, foot), extra={"object_id": owner.id}), position=(20, 30)
    )
    target = Group(
        name="Support",
        transform=Transform(x=80, y=30),
        extra={"studio_floor_plant": True, "object_id": owner.id},
    )
    rule = Constraint(owner_id=foot.id, target_id=target.id, kind="copy_transform")
    doc.add_entities(
        doc.scene.id, {"groups": (owner, target), "skeletons": (rig,), "constraints": (rule,)}
    )
    doc.set_animation_context(owner.id, frozenset(CharacterService(doc).members(owner.id)))
    return doc, owner, foot, target


@pytest.mark.parametrize("recording", (False, True))
@pytest.mark.parametrize("inherit", (False, True))
def test_legacy_support_follows_fk_and_preserves_bone_mode_and_undo(recording, inherit):
    doc, _, foot, _ = contact_document()
    rig = doc.scene.skeletons[0]
    root = next(b for b in rig.bones if b.extra.get("rig_root"))
    before = doc.animation.pose
    source = doc.project
    if recording:
        changes = {(root.id, "transform.x"): before.nodes[root.id].local.x + 80}
        if not inherit:
            changes.update(
                {
                    (b.id, "transform.x"): before.nodes[b.id].local.x - 80
                    for b in rig.bones
                    if b.parent_id == root.id
                }
            )
        AnimationEditingService(doc).auto_key_values(changes, 0)
    else:
        RigService(doc).transform_selection(
            (root.id,),
            root.id,
            "selection_move",
            before.nodes[root.id].world_matrix[4] + 80,
            before.nodes[root.id].world_matrix[5],
            include_descendants=inherit,
        )
    pose = doc.animation.pose
    assert not pose.warnings
    assert pose.nodes[foot.id].world_matrix[4:] == pytest.approx((80 + (80 if inherit else 0), 30))
    doc.undo()
    assert doc.project == source


def test_legacy_contact_without_owner_metadata_stays_inside_fragment():
    doc, owner, _, target = contact_document()
    scene = replace(
        doc.scene,
        groups=tuple(
            replace(g, extra={"studio_floor_plant": True}) if g.id == target.id else g
            for g in doc.scene.groups
        ),
    )
    fragment = object_fragment(scene, (owner.id,))
    assert fragment.constraints == scene.constraints
    assert {g.id for g in fragment.groups} == {g.id for g in scene.groups}
