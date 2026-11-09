"""Independent editable view slots retain canonical records and can be stepped in Scene."""

from rigora.application_services.appearance import AppearanceService
from rigora.application_services.characters import CharacterService
from rigora.application_services.documents import DocumentService
from rigora.application_services.object_views import ObjectViewsService


def test_view_slots_keep_original_artwork_empty_slots_and_keyed_switches(tmp_path):
    """Slot changes retain all part IDs; held view keys survive save/reopen and Undo."""
    doc = DocumentService()
    doc.new()
    art, characters = AppearanceService(doc), CharacterService(doc)
    original = art.create_shape("rectangle", 20, 30, 40, 60)
    part = characters.mesh(original).object_id
    root = characters.create_object((part,))
    views = ObjectViewsService(doc)
    views.switch(root, "Side")
    assert views.edited_view(root) == "Side"
    assert views.edit_members(root) == {root}
    assert not doc.animation.pose.nodes[part].visible
    side = art.create_shape("ellipse", 40, 50, 20, 60)
    side_part = characters.mesh(side).object_id
    characters.add_object_parts(root, (side,))
    assert doc.animation.pose.nodes[side_part].visible
    views.switch(root, "Default")
    assert part in views.edit_members(root) and side_part not in views.edit_members(root)
    assert doc.animation.pose.nodes[part].visible
    assert not doc.animation.pose.nodes[side_part].visible
    assert {m.id for m in doc.scene.meshes} == {original, side}
    views.key_view(root, "Default", 0)
    views.key_view(root, "Side", 20)
    views.key_view(root, "Default", 40)
    for frame, first in ((0, True), (19, True), (20, False), (39, False), (40, True)):
        pose = doc.animation.evaluate(frame)
        assert pose.nodes[part].visible == first
        assert pose.nodes[side_part].visible != first
    doc.save(tmp_path / "views.rigora")
    loaded = DocumentService()
    loaded.open(doc.path)
    assert loaded.animation.evaluate(25).meshes == doc.animation.evaluate(25).meshes
    assert loaded.animation.evaluate(25).nodes == doc.animation.evaluate(25).nodes
    doc.undo()
    assert doc.animation.evaluate(40).nodes[side_part].visible


def test_saved_legacy_turnaround_loads_into_an_editable_slot_without_replacing_default():
    """Compressed authored sides from earlier projects remain available after slot migration."""
    from rigora.application_services.character_creation import (
        CharacterCreationService,
        build_character,
    )
    from rigora.domain.character_recipe import CharacterRecipe

    doc = DocumentService()
    doc.new()
    root = CharacterCreationService(doc).create(build_character(CharacterRecipe(motions=())))
    views = ObjectViewsService(doc)
    views.apply(root, views.prepare(root, "Back"))
    original = {m.asset_id for m in doc.scene.meshes}
    views.switch(root, "Front 3/4")
    assert len(CharacterService(doc).scene_objects()) == 1
    assert not doc.animation.pose.warnings
    front = {m.asset_id for m in doc.animation.pose.meshes.values()}
    assert front and front != original
    views.switch(root, "Default")
    assert {m.asset_id for m in doc.animation.pose.meshes.values()} == original
