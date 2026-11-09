"""Master rig controls, deforming roots and consistent Object Editor gesture spaces."""

import pytest

from rigora.application_services.content_library import ContentService
from rigora.application_services.documents import DocumentService
from rigora.application_services.dynamics import DynamicsService
from rigora.application_services.rigging import RigService
from rigora.domain.entities import Bone, Skeleton, Transform
from rigora.domain.project import ProjectError
from rigora.infrastructure.effect_catalog import spring_presets


def specimen():
    """Drop the real flexible-chain template through the public placement service."""
    doc = DocumentService()
    doc.new()
    item = next(i for i in spring_presets() if i.name == "Long ponytail")
    rig_id = ContentService(doc).place(item, {}, position=(700, 450))
    rig = next(r for r in doc.scene.skeletons if r.id == rig_id)
    return doc, rig, str(rig.extra["object_id"])


def test_template_has_one_master_root_and_every_deforming_segment_can_spring():
    doc, rig, _ = specimen()
    masters = [b for b in rig.bones if b.extra.get("rig_root")]
    assert len(masters) == 1
    master = masters[0]
    assert master.parent_id is None and master.length == 0 and master.name == "Rig Root"
    segments = [b for b in rig.bones if not b.extra.get("rig_root")]
    assert segments[0].parent_id == master.id
    assert {c.owner_id for c in doc.scene.constraints if c.kind == "spring"} == {
        b.id for b in segments
    }
    with pytest.raises(ProjectError, match="Rig Root"):
        DynamicsService(doc).configure((master.id,))


@pytest.mark.parametrize("tool", ("selection_move", "chain_move"))
def test_object_editor_bone_move_uses_only_object_coordinates(tool):
    doc, rig, owner = specimen()
    from rigora.application_services.characters import CharacterService

    doc.set_animation_context(owner, frozenset(CharacterService(doc).members(owner)))
    service = RigService(doc)
    first = next(b for b in rig.bones if b.name == "chain.0")
    before = service.preview_pose().for_display()
    x, y = before.nodes[first.id].world_matrix[4:]
    _, after = service.plan_drag(first.id, tool, x + 25, y + 25, (first.id,))
    after = after.for_display()
    for bone in rig.bones:
        if bone.extra.get("rig_root"):
            continue
        delta = (25, 25) if bone.id == first.id or tool == "chain_move" else (0, 0)
        assert after.nodes[bone.id].world_matrix[4:] == pytest.approx(
            tuple(before.nodes[bone.id].world_matrix[i + 4] + delta[i] for i in (0, 1))
        )


def test_legacy_root_upgrade_preserves_existing_ids_world_geometry_and_undo(tmp_path):
    from rigora.domain.rig_roots import rooted_skeleton

    parent = Bone(name="First", transform=Transform(x=30, y=40, rotation=30))
    child = Bone(name="Child", parent_id=parent.id, transform=Transform(x=100))
    legacy = Skeleton(bones=(parent, child))
    rooted = rooted_skeleton(legacy)
    assert rooted_skeleton(rooted) is rooted
    assert {b.id for b in legacy.bones} < {b.id for b in rooted.bones}
    assert rooted.bones[1].transform == parent.transform
    assert rooted.bones[2] == child
    doc = DocumentService()
    doc.new()
    service = RigService(doc)
    service.commit("Legacy rig", skeletons=(legacy,))
    before = service.rest_pose()
    original = doc.project
    service.ensure_root(legacy.id)
    after = service.rest_pose()
    for bone in legacy.bones:
        assert after.nodes[bone.id].world_matrix == before.nodes[bone.id].world_matrix
    doc.save(tmp_path / "rooted.rigora")
    loaded = DocumentService()
    loaded.open(doc.path)
    assert loaded.project == doc.project
    doc.undo()
    assert doc.project == original


def test_general_spring_command_and_preset_share_first_segment_eligibility():
    doc, rig, _ = specimen()
    service = RigService(doc)
    first = next(b for b in rig.bones if b.name == "chain.0")
    service.commit("Remove test springs", constraints=())
    identity = service.add_constraint(first.id, "spring", frequency=2, damping=0.3)
    rule = next(c for c in doc.scene.constraints if c.id == identity)
    assert rule.owner_id == first.id and rule.kind == "spring"


def test_rig_root_scene_space_move_applies_object_placement_once():
    doc, rig, _ = specimen()
    service = RigService(doc)
    root = next(b for b in rig.bones if b.extra.get("rig_root"))
    before = service.preview_pose().for_display()
    x, y = before.nodes[root.id].world_matrix[4:]
    _, after = service.plan_drag(root.id, "chain_move", x + 25, y + 25, (root.id,))
    after = after.for_display()
    for bone in rig.bones:
        assert after.nodes[bone.id].world_matrix[4:] == pytest.approx(
            (before.nodes[bone.id].world_matrix[4] + 25, before.nodes[bone.id].world_matrix[5] + 25)
        )


def test_rig_root_keeps_child_local_transforms_and_carries_locked_children():
    from rigora.application_services.characters import CharacterService

    doc, rig, owner = specimen()
    doc.set_animation_context(owner, frozenset(CharacterService(doc).members(owner)))
    service = RigService(doc)
    root = next(b for b in rig.bones if b.extra.get("rig_root"))
    child = next(b for b in rig.bones if b.name == "chain.0")
    service.update(child.id, locked=True)
    before = doc.scene.skeletons[0]
    command, _ = service.plan_drag(root.id, "chain_move", 25, 40, (root.id,))
    doc.execute(command)
    after = doc.scene.skeletons[0]
    for bone in before.bones:
        if bone.id != root.id:
            assert next(b for b in after.bones if b.id == bone.id) == bone


@pytest.mark.parametrize("tool,value", (("chain_rotate", 30), ("chain_scale", 1.5)))
def test_master_rotation_and_scale_carry_each_chain_about_the_master(tool, value):
    """Master transforms inherit once without rewriting deforming-bone local poses."""
    from rigora.application_services.characters import CharacterService
    from rigora.domain.geometry import affine, multiply

    doc, rig, owner = specimen()
    doc.set_animation_context(owner, frozenset(CharacterService(doc).members(owner)))
    service = RigService(doc)
    root = next(b for b in rig.bones if b.extra.get("rig_root"))
    before = service.preview_pose().for_display()
    command, after = service.plan_drag(root.id, tool, value, 0, (root.id,))
    after = after.for_display()
    x, y = before.nodes[root.id].world_matrix[4:]
    angle, scale = (value, 1) if tool.endswith("rotate") else (0, value)
    delta = multiply(affine(x, y, angle, scale, scale, 0, 0), affine(-x, -y, 0, 1, 1, 0, 0))
    for bone in rig.bones:
        assert after.nodes[bone.id].world_matrix == pytest.approx(
            multiply(delta, before.nodes[bone.id].world_matrix)
        )
    doc.execute(command)
    assert [b for b in doc.scene.skeletons[0].bones if b.id != root.id] == [
        b for b in rig.bones if b.id != root.id
    ]


@pytest.mark.parametrize(
    "tool,value", (("selection_move", 30), ("selection_rotate", 30), ("selection_scale", 1.5))
)
def test_bone_mode_repositions_master_without_moving_deforming_bones(tool, value):
    """Root-only edits compensate direct children, preserving every chain's world pose."""
    from rigora.application_services.characters import CharacterService

    doc, rig, owner = specimen()
    doc.set_animation_context(owner, frozenset(CharacterService(doc).members(owner)))
    service = RigService(doc)
    root = next(b for b in rig.bones if b.extra.get("rig_root"))
    before = service.preview_pose().for_display()
    _, after = service.plan_drag(
        root.id, tool, value, 20 if tool.endswith("move") else 0, (root.id,)
    )
    after = after.for_display()
    assert after.nodes[root.id].world_matrix != before.nodes[root.id].world_matrix
    for bone in rig.bones:
        if bone.id != root.id:
            assert after.nodes[bone.id].world_matrix == pytest.approx(
                before.nodes[bone.id].world_matrix
            )


def test_empty_object_rig_root_is_idempotent_protected_and_owned():
    """Preparing a skeleton creates one protected control, removable with its Object."""
    from rigora.application_services.characters import CharacterService
    from rigora.application_services.scene_editing import SceneEditingService

    doc = DocumentService()
    doc.new()
    owner = CharacterService(doc).create_object()
    doc.set_animation_context(owner, frozenset({owner}))
    service = RigService(doc)
    root_id = service.prepare_object_rig(owner)
    rig = next(r for r in doc.scene.skeletons if r.extra.get("object_id") == owner)
    assert len(rig.bones) == 1 and rig.bones[0].id == root_id
    baseline = doc.project
    assert service.prepare_object_rig(owner) == root_id and doc.project is baseline
    with pytest.raises(ProjectError, match="protected"):
        service.delete(root_id)
    with pytest.raises(ProjectError, match="protected"):
        SceneEditingService(doc).delete_entries((rig.id,))
    service.create_bone((20, 30), (80, 30))
    assert service.scene.skeletons[0].bones[-1].parent_id == root_id
    doc.set_animation_context(None)
    SceneEditingService(doc).delete_entries((owner,))
    assert not doc.scene.skeletons


def test_master_root_keys_move_skin_and_remain_linked_in_scene(tmp_path):
    from rigora.application_services.animation_editing import AnimationEditingService
    from rigora.application_services.character_creation import (
        CharacterCreationService,
        build_character,
    )
    from rigora.application_services.characters import CharacterService
    from rigora.domain.character_recipe import CharacterRecipe

    doc = DocumentService()
    doc.new()
    owner = CharacterCreationService(doc).create(
        build_character(CharacterRecipe(design_id="sumi", name="Sumi", motions=()))
    )
    chars = CharacterService(doc)
    doc.set_animation_context(owner, frozenset(chars.members(owner)))
    clip = chars.new_motion(owner, "Root movement")
    master = next(b for b in doc.scene.skeletons[0].bones if b.extra.get("rig_root"))
    edit = AnimationEditingService(doc)
    edit.key(master.id, "transform.x", 0, 0)
    edit.key(master.id, "transform.x", 12, 30)
    source_before, source_after = doc.animation.evaluate(0), doc.animation.evaluate(12)
    for key, mesh in source_before.meshes.items():
        for original, moved in zip(mesh.positions, source_after.meshes[key].positions, strict=True):
            assert moved == pytest.approx((original[0] + 30, original[1]))
    doc.set_animation_context(None)
    chars.place_motion(owner, clip, 0, 1, repeat=False)
    scene_clip = doc.selected_clip_id
    a, b = doc.animation.evaluate(0), doc.animation.evaluate(12)
    assert a.nodes[owner] == b.nodes[owner]
    for key, mesh in a.meshes.items():
        for original, moved in zip(mesh.positions, b.meshes[key].positions, strict=True):
            assert moved == pytest.approx((original[0] + 30, original[1]))
    doc.save(tmp_path / "root-animation.rigora")
    loaded = DocumentService()
    loaded.open(doc.path)
    loaded.set_animation_context(None)
    loaded.select_animation_clip(scene_clip)
    assert loaded.animation.evaluate(12).meshes == b.meshes
