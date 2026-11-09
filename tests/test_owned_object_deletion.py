"""Deleting an Object removes its metadata-owned rigs and actions as well as transform children."""

from dataclasses import replace

import pytest

from rigora.application_services.character_creation import CharacterCreationService, build_character
from rigora.application_services.characters import CharacterService
from rigora.application_services.content_library import ContentService
from rigora.application_services.documents import DocumentService
from rigora.application_services.dynamics import DynamicsService
from rigora.application_services.rigging import RigService
from rigora.application_services.scene_editing import SceneEditingService
from rigora.domain.character_recipe import character_preset


@pytest.mark.parametrize("selection", ("object", "empty_object", "character", "skeleton"))
def test_delete_owned_armature_and_private_motion_without_orphans(current_pack, selection):
    """Bones, spring rules, private clips and rows disappear together; one Undo restores them."""
    doc = DocumentService()
    doc.new()
    pack, files = current_pack("rigs-effects")
    item = next(i for i in pack.items if i.name == "Human · full body")
    rig_id = ContentService(doc).place(item, files, position=(320, 240))
    characters = CharacterService(doc)
    owner = characters.object_root(rig_id)
    other = characters.create_object(name="Keep me")
    rig = next(r for r in characters.scene.skeletons if r.id == rig_id)
    actor = next(c for c in characters.scene.characters if c.skeleton_id == rig_id)
    DynamicsService(doc).assign_group(
        (next(b.id for b in rig.bones if b.length > 0),), group="Follow through"
    )
    motion = characters.new_motion(owner.id, "Owned motion")
    timeline = next(c.timeline_id for c in characters.scene.clips if c.id == motion)
    if selection == "empty_object":
        RigService(doc).delete_many(tuple(b.id for b in rig.bones if not b.extra.get("rig_root")))
    key = actor.id if selection == "character" else rig_id if selection == "skeleton" else owner.id
    before, count = doc.project, len(doc.history.undo_stack)
    SceneEditingService(doc).delete_entries((key,))
    scene = characters.scene
    assert not scene.skeletons and not scene.characters and not scene.constraints
    assert other in characters.scene_objects()
    if selection != "skeleton":
        assert owner.id not in characters.records()
        assert motion not in {c.id for c in scene.clips}
        assert timeline not in {t.id for t in scene.timelines}
    assert not doc.animation.pose.warnings
    assert len(doc.history.undo_stack) == count + 1
    doc.undo()
    assert doc.project == before


def test_creator_object_deletion_cleans_feet_controls_and_all_owned_geometry():
    """A complete premade character uses the same cascade as a bare template armature."""
    doc = DocumentService()
    doc.new()
    root = CharacterCreationService(doc).create(
        build_character(replace(character_preset("Little"), motions=()))
    )
    before = doc.project
    assets = doc.project.assets
    service = SceneEditingService(doc)
    service.delete_entries((root,))
    assert not service.scene.groups and not service.scene.objects
    assert not service.scene.characters and not service.scene.skeletons
    assert (
        not service.scene.meshes and not service.scene.deformers and not service.scene.constraints
    )
    assert doc.project.assets == assets
    assert set(doc.animation.pose.nodes) == {camera.id for camera in service.scene.cameras}
    assert not doc.animation.pose.warnings
    doc.undo()
    assert doc.project == before
