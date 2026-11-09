"""Posed pins and legacy ownership remain valid independently of built-in character catalogs."""

from dataclasses import replace
from pathlib import Path

import pytest

from rigora.application_services.characters import CharacterService
from rigora.application_services.documents import DocumentService
from rigora.application_services.rigging import RigService
from rigora.application_services.skinning import SkinService
from rigora.domain.geometry import transform_point


def test_pin_on_posed_artwork_uses_displayed_point_and_does_not_jump():
    """Click inversion follows evaluated triangles rather than undeformed source coordinates."""
    doc = DocumentService()
    doc.open(Path("examples/image-import-example.rigora"))
    skin = SkinService(doc)
    mesh = skin.scene.meshes[0]
    root, child = skin.scene.skeletons[0].bones
    rig = RigService(doc)
    rig.update(child.id, transform=replace(child.transform, rotation=45))
    pose = doc.animation.pose
    face = mesh.triangles[-1]
    positions = dict(
        zip((v.id for v in mesh.vertices), pose.meshes[mesh.id].positions, strict=True)
    )
    local = tuple(sum(positions[k][i] for k in face) / 3 for i in (0, 1))
    world = transform_point(pose.nodes[mesh.object_id].world_matrix, *local)
    baseline = doc.project
    key = skin.area_pin_at(mesh.id, world, root.id, radius=80)
    index = next(i for i, v in enumerate(skin.mesh(mesh.id).vertices) if v.id == key)
    assert doc.animation.pose.meshes[mesh.id].positions[index] == pytest.approx(local)
    rig.update(child.id, transform=replace(child.transform, rotation=70))
    assert doc.animation.pose.meshes[mesh.id].positions[index] == pytest.approx(local)
    doc.undo()
    doc.undo()
    assert doc.project == baseline


def test_legacy_bone_membership_keeps_bound_artwork_evaluable_in_object_editor():
    """Older actors with empty explicit image lists still own their bone-bound artwork."""
    doc = DocumentService()
    doc.open(Path("examples/image-import-example.rigora"))
    actor = doc.project.scenes[0].characters[0]
    mesh = doc.project.scenes[0].meshes[0]
    service = CharacterService(doc)
    members = frozenset(service.members(actor.id))
    assert mesh.id in members and mesh.object_id in members
    assert service.owner(mesh.id) == actor
    doc.set_animation_context(actor.id, members)
    assert mesh.id in doc.animation.pose.meshes
