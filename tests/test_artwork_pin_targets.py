"""Object-relative image anchors remain independent of skeletal posing and preserve undo."""

from dataclasses import replace
from pathlib import Path

import pytest

from rigora.application_services.documents import DocumentService
from rigora.application_services.rigging import RigService
from rigora.application_services.skinning import SkinService
from rigora.domain.geometry import transform_point


def setup_pin(bone=False):
    """Use a real skinned image with two joints and no generated catalog dependency."""
    doc = DocumentService()
    doc.open(Path("examples/image-import-example.rigora"))
    skin = SkinService(doc)
    mesh = doc.scene.meshes[0]
    root, child = doc.scene.skeletons[0].bones
    vertex = mesh.vertices[-1]
    key = skin.add_area_pin(mesh.id, (vertex.x, vertex.y), root.id if bone else None, 100)
    return doc, skin, mesh.id, key, root, child


def location(doc, mesh_id, vertex_id):
    """Read actual displayed pin geometry rather than its undeformed setup coordinates."""
    mesh = next(m for m in doc.scene.meshes if m.id == mesh_id)
    pose = doc.animation.pose
    index = next(i for i, v in enumerate(mesh.vertices) if v.id == vertex_id)
    return transform_point(
        pose.nodes[mesh.object_id].world_matrix, *pose.meshes[mesh_id].positions[index]
    )


def test_default_pin_resists_all_bone_motion_and_follows_artwork_transform():
    doc, skin, mesh_id, key, root, child = setup_pin()
    pin = skin.mesh(mesh_id).extra["area_pins"][0]
    assert pin["target_kind"] == "object"
    before = location(doc, mesh_id, key)
    rig = RigService(doc)
    for bone in (child, root):
        rig.update(
            bone.id, transform=replace(bone.transform, rotation=bone.transform.rotation + 45)
        )
        assert location(doc, mesh_id, key) == pytest.approx(before)
    obj = next(o for o in doc.scene.objects if o.id == skin.mesh(mesh_id).object_id)
    rig.commit(
        "Move artwork",
        objects=(replace(obj, transform=replace(obj.transform, x=obj.transform.x + 75)),),
    )
    assert location(doc, mesh_id, key) == pytest.approx((before[0] + 75, before[1]))


def test_selected_bone_pin_keeps_legacy_attachment_behavior():
    doc, skin, mesh_id, key, root, _ = setup_pin(True)
    before = location(doc, mesh_id, key)
    RigService(doc).update(root.id, transform=replace(root.transform, x=root.transform.x + 40))
    assert location(doc, mesh_id, key) == pytest.approx((before[0] + 40, before[1]))


@pytest.mark.parametrize("bone_target", (False, True))
def test_pin_targets_and_properties_survive_save_load(tmp_path, bone_target):
    """Persistent anchors use the same services and evaluation after reopening a project."""
    doc, skin, mesh_id, key, _, _ = setup_pin(bone_target)
    skin.update_area_pins(mesh_id, (key,), radius=75, strength=0.8)
    before = location(doc, mesh_id, key)
    doc.save(tmp_path / "pins.rigora")
    loaded = DocumentService()
    loaded.open(doc.path)
    assert loaded.project == doc.project
    assert location(loaded, mesh_id, key) == pytest.approx(before)


def test_saved_legacy_bone_pins_keep_attachment_without_new_metadata():
    """Older packs omit target kind and strength; evaluation retains bone anchoring."""
    doc, skin, mesh_id, key, root, _ = setup_pin(True)
    mesh = skin.mesh(mesh_id)
    pin = {
        k: v for k, v in mesh.extra["area_pins"][0].items() if k not in ("target_kind", "strength")
    }
    skin.replace_mesh(replace(mesh, extra={**mesh.extra, "area_pins": [pin]}))
    before = location(doc, mesh_id, key)
    RigService(doc).update(root.id, transform=replace(root.transform, x=root.transform.x + 20))
    assert location(doc, mesh_id, key) == pytest.approx((before[0] + 20, before[1]))


def test_selected_pin_properties_are_undoable_and_target_changes_capture_current_pose():
    doc, skin, mesh_id, key, root, _ = setup_pin()
    before = location(doc, mesh_id, key)
    original, count = doc.project, len(doc.history.undo_stack)
    skin.update_area_pins(mesh_id, (key,), radius=80, strength=0.6, bone_id=root.id)
    pin = skin.mesh(mesh_id).extra["area_pins"][0]
    assert pin["radius"] == 80 and pin["strength"] == 0.6 and pin["bone_id"] == root.id
    assert location(doc, mesh_id, key) == pytest.approx(before)
    assert len(doc.history.undo_stack) == count + 1
    doc.undo()
    assert doc.project == original


@pytest.mark.parametrize("radius,strength", ((0, 1), (50, -0.1), (50, 1.1)))
def test_invalid_pin_properties_do_not_mutate_document(radius, strength):
    doc, skin, mesh_id, key, _, _ = setup_pin()
    before = doc.project
    with pytest.raises(ValueError):
        skin.update_area_pins(mesh_id, (key,), radius=radius, strength=strength)
    assert doc.project is before


def test_pin_strength_blends_with_skinning_instead_of_forcing_its_center():
    """A half-strength Object pin retains half of the ordinary skeletal displacement."""
    doc, skin, mesh_id, key, root, _ = setup_pin()
    before = location(doc, mesh_id, key)
    skin.update_area_pins(mesh_id, (key,), strength=0.5)
    RigService(doc).update(root.id, transform=replace(root.transform, x=root.transform.x + 40))
    assert location(doc, mesh_id, key) == pytest.approx((before[0] + 20, before[1]))


def test_pin_move_collision_rolls_back_without_overwriting_another_pin():
    doc, skin, mesh_id, key, _, _ = setup_pin()
    mesh = skin.mesh(mesh_id)
    other = mesh.vertices[0]
    second = skin.add_area_pin(mesh_id, (other.x, other.y))
    before, count = doc.project, len(doc.history.undo_stack)
    with pytest.raises(ValueError, match="existing anchor"):
        skin.move_area_pin(mesh_id, key, location(doc, mesh_id, second))
    assert doc.project == before and len(doc.history.undo_stack) == count


def test_locked_artwork_rejects_pin_edits_without_mutation():
    from rigora.application_services.scene_editing import SceneEditingService

    doc, skin, mesh_id, key, _, _ = setup_pin()
    scene = SceneEditingService(doc)
    owner = skin.mesh(mesh_id).object_id
    record = scene.record(owner)
    scene.update_records(
        {owner: replace(record, extra={**record.extra, "locked": True})}, "Lock artwork"
    )
    before = doc.project
    for edit in (
        lambda: skin.update_area_pins(mesh_id, (key,), radius=75),
        lambda: skin.remove_area_pins(mesh_id, (key,)),
        lambda: skin.move_area_pin(mesh_id, key, (220, 240)),
    ):
        with pytest.raises(ValueError, match="Unlock"):
            edit()
        assert doc.project is before


def test_pin_matrix_work_is_bounded_by_attachments_not_vertex_count(monkeypatch):
    """Matrix inverses are prepared once per pin, rather than once per affected vertex."""
    from rigora.engine import deformation
    from rigora.engine.evaluation import SceneEvaluator

    doc, _, _, _, root, _ = setup_pin()
    calls = 0
    original = deformation.inverse

    def inverse(matrix):
        nonlocal calls
        calls += 1
        return original(matrix)

    monkeypatch.setattr(deformation, "inverse", inverse)
    SceneEvaluator(doc.scene).evaluate(0, overrides={(root.id, "transform.rotation"): 35})
    assert calls <= 5


@pytest.mark.parametrize("bone_target", (False, True))
def test_pin_on_placed_character_captures_current_pose_and_follows_outer_transform(bone_target):
    """Object placement is applied once for both target types, including retargeting in Scene."""
    from rigora.application_services.character_creation import (
        CharacterCreationService,
        build_character,
    )
    from rigora.application_services.scene_editing import SceneEditingService
    from rigora.domain.character_recipe import CharacterRecipe
    from rigora.domain.geometry import inverse, multiply

    doc = DocumentService()
    doc.new()
    owner = CharacterCreationService(doc).create(build_character(CharacterRecipe(motions=())))
    scene = SceneEditingService(doc)
    group = scene.record(owner)
    scene.update_records(
        {owner: replace(group, transform=replace(group.transform, x=500, y=300))}, "Place character"
    )
    skin = SkinService(doc)
    mesh = doc.scene.meshes[0]
    target = next(b for b in doc.scene.skeletons[0].bones if b.name == "hips")
    original = mesh.vertices[-1]
    pose = doc.animation.pose
    original_point = transform_point(
        pose.nodes[mesh.object_id].world_matrix, original.x, original.y
    )
    key = skin.area_pin_at(mesh.id, original_point, target.id if bone_target else None)
    assert location(doc, mesh.id, key) == pytest.approx(original_point)
    before = doc.animation.pose.nodes[owner].world_matrix
    group = scene.record(owner)
    scene.update_records(
        {
            owner: replace(
                group, transform=replace(group.transform, x=550, rotation=20, scale_x=1.2)
            )
        },
        "Move character",
    )
    after = doc.animation.pose.nodes[owner].world_matrix
    assert location(doc, mesh.id, key) == pytest.approx(
        transform_point(multiply(after, inverse(before)), *original_point)
    )
    skin.update_area_pins(mesh.id, (key,), bone_id=target.id if not bone_target else None)
    assert location(doc, mesh.id, key) == pytest.approx(
        transform_point(multiply(after, inverse(before)), *original_point)
    )
