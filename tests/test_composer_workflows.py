"""Scene organization, reversible deletion and spring translation as complete authoring flows."""

from dataclasses import replace
from pathlib import Path

import pytest

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.documents import DocumentService
from rigora.application_services.dynamics import DynamicsService
from rigora.application_services.meshes import MeshService
from rigora.application_services.object_library import ObjectLibraryService
from rigora.application_services.rigging import RigService
from rigora.application_services.scene_editing import SceneEditingService
from rigora.domain.geometry import transform_point
from rigora.domain.project import ProjectError
from rigora.engine.springs import SpringSimulation


def artwork():
    """Create two independent editable instances sharing one original vector source."""
    doc = DocumentService()
    doc.new()
    meshes = MeshService(doc)
    source = meshes.register_image_bytes("prop.svg", Path("assets/examples/prop.svg").read_bytes())
    ids = tuple(meshes.mesh(meshes.instantiate_asset(source)).object_id for _ in range(2))
    return doc, source, ids


def test_scene_folders_reorder_preserve_world_pose_and_roundtrip(tmp_path):
    """Nested grouping and front/back moves preserve geometry and serialize through normal saves."""
    doc, _, (a, b) = artwork()
    service = SceneEditingService(doc)
    before = doc.animation.pose.nodes[a].world_matrix
    folder = service.group((a,), "Character")
    assert service.record(a).parent_id == folder
    assert doc.animation.pose.nodes[a].world_matrix == before
    inner = service.group((b,), "Hands")
    service.move_entries((inner,), folder)
    with pytest.raises(ProjectError, match="descendants"):
        service.move_entries((folder,), inner)
    service.move_entries((a,), folder, b)
    assert doc.animation.pose.render_order.index(a) < doc.animation.pose.render_order.index(b)
    service.move_entries((a,), folder)
    assert doc.animation.pose.render_order[-1] == a
    doc.save(tmp_path / "folders.rigora")
    loaded = DocumentService()
    loaded.open(tmp_path / "folders.rigora")
    assert loaded.animation.pose.render_order == doc.animation.pose.render_order
    service.flags((folder,), locked=True)
    with pytest.raises(ProjectError, match="unlocked"):
        service.move_entries((a,), None)


def test_delete_scene_dependencies_source_protection_and_undo(tmp_path):
    """Deletion removes mesh/deformer keys while preserving sources and exact undo recovery."""
    doc, source, (a, b) = artwork()
    service = SceneEditingService(doc)
    AnimationEditingService(doc).key(a, "transform.x", 12, 200)
    folder = service.group((a, b))
    original = doc.project
    with pytest.raises(ProjectError, match="in use|saved Object"):
        service.remove_asset(source)
    service.delete_entries((folder,))
    assert not service.scene.objects and not service.scene.meshes and not service.scene.groups
    assert not any(t.tracks for t in service.scene.timelines)
    assert len(doc.project.assets) == 1
    doc.undo()
    assert doc.project == original
    doc.redo()
    with pytest.raises(ProjectError, match="saved Object"):
        service.remove_asset(source)
    library = ObjectLibraryService(doc)
    library.remove(tuple(library.entries()))
    service.remove_asset(source)
    assert not doc.project.assets
    doc.undo()
    assert len(doc.project.assets) == 1
    doc.save(tmp_path / "deleted.rigora")


def test_rigid_group_attachment_keeps_world_pose_and_follows_bone():
    """Attaching an imported folder preserves placement and carries its actual child mesh."""
    doc, _, (a, _) = artwork()
    rig = RigService(doc)
    root = rig.template("Chain")
    service = SceneEditingService(doc)
    folder = service.group((a,))
    before = doc.animation.pose.nodes[a].world_matrix
    service.attach((folder,), root)
    assert doc.animation.pose.nodes[a].world_matrix == pytest.approx(before)
    rig.update(root, transform=replace(rig.bone(root).transform, x=rig.bone(root).transform.x + 25))
    assert doc.animation.pose.nodes[a].world_matrix[4] == pytest.approx(before[4] + 25)


def test_spring_translate_bounds_direction_limits_and_saved_group(tmp_path):
    """Acceleration stretches a bone within bounds while its parent joint remains attached."""
    doc = DocumentService()
    doc.new()
    rig = RigService(doc)
    root = rig.template("Chain")
    child = next(b.id for s in rig.scene.skeletons for b in s.bones if b.parent_id == root)
    service = DynamicsService(doc)
    service.configure(
        (child,),
        translate=True,
        stretch=40,
        squash=20,
        clockwise=15,
        counterclockwise=5,
        group="Hair",
    )
    rule = next(c for c in service.scene.constraints if c.kind == "spring")
    assert rule.extra["spring_group"] == "Hair"
    nodes = tuple(doc.animation.pose.nodes.values())
    simulation = SpringSimulation()
    simulation.advance(nodes, (rule,), 1 / 60)
    shifted = tuple(
        replace(n, world_matrix=(*n.world_matrix[:4], n.world_matrix[4] + 30, n.world_matrix[5]))
        for n in nodes
    )
    result = simulation.advance(shifted, (rule,), 1 / 60)
    value = next(n for n in result if n.id == child)
    original = next(n for n in nodes if n.id == child)
    assert 0.8 * original.local.scale_x <= value.local.scale_x <= 1.4 * original.local.scale_x
    assert value.local.scale_x != pytest.approx(original.local.scale_x)
    assert value.local.x == pytest.approx(original.local.x)
    parent = next(n for n in result if n.id == root)
    assert value.world_matrix[4:] == pytest.approx(
        transform_point(parent.world_matrix, parent.length, 0)
    )
    assert not doc.animation.pose.warnings
    doc.save(tmp_path / "spring.rigora")
    loaded = DocumentService()
    loaded.open(tmp_path / "spring.rigora")
    assert loaded.project.scenes[0].constraints[0].extra["spring_group"] == "Hair"
    with pytest.raises(ProjectError, match="ranges"):
        service.configure((child,), squash=101)


def test_bone_origin_pin_survives_parent_motion():
    """Pins enforce world-space anchors through the same solver used by playback and export."""
    doc = DocumentService()
    doc.new()
    rig = RigService(doc)
    root = rig.template("Chain")
    child = next(b.id for s in rig.scene.skeletons for b in s.bones if b.parent_id == root)
    point = transform_point(doc.animation.pose.nodes[child].world_matrix, 0, 0)
    rig.add_constraint(child, "pin")
    rig.update(root, transform=replace(rig.bone(root).transform, x=550))
    assert transform_point(doc.animation.pose.nodes[child].world_matrix, 0, 0) == pytest.approx(
        point
    )


def test_composer_part_and_sprite_transforms_preserve_distinct_skin_behavior():
    """Part editing moves a bound rig; sprite editing shifts artwork without moving the bones."""

    doc = DocumentService()
    doc.open(Path("examples/image-import-example.rigora"))
    scene = doc.project.scenes[0]
    mesh, root = scene.meshes[0], scene.skeletons[0].bones[0]
    owner = mesh.object_id

    def world_points():
        pose = doc.animation.pose
        return tuple(
            transform_point(pose.nodes[owner].world_matrix, *p)
            for p in pose.meshes[mesh.id].positions
        )

    baseline = doc.project
    before = world_points()
    service = SceneEditingService(doc)
    service.sprite_edit = True
    service.transform((owner,), dx=40, dy=20)
    assert service.record(root.id) == root
    for old, changed in zip(before, world_points(), strict=True):
        assert changed == pytest.approx((old[0] + 40, old[1] + 20))
    doc.undo()
    assert doc.project == baseline
    service.sprite_edit = False
    service.part_edit = True
    service.transform((owner,), dx=40, dy=20)
    assert doc.animation.pose.nodes[root.id].world_matrix[4:] == pytest.approx(
        (root.transform.x + 40, root.transform.y + 20)
    )
    for old, changed in zip(before, world_points(), strict=True):
        assert changed == pytest.approx((old[0] + 40, old[1] + 20))
    doc.undo()
    assert doc.project == baseline


def test_duplicate_branch_has_independent_ids_and_keeps_parent_topology():
    """Duplicating a subtree leaves the source rig intact and is one reversible edit."""
    doc = DocumentService()
    doc.new()
    service = RigService(doc)
    root = service.create_bone((20, 20), (100, 20))
    child = service.create_bone((100, 20), (150, 40), root)
    baseline = doc.project
    pose = doc.animation.pose
    copies = service.duplicate(root)
    assert len(copies) == 2 and not set(copies).intersection((root, child))
    copied_root, copied_child = (service.bone(k) for k in copies)
    assert copied_child.parent_id == copied_root.id
    assert doc.animation.pose.nodes[copied_child.id].world_matrix == pytest.approx(
        pose.nodes[child].world_matrix
    )
    assert service.bone(root).name == "Bone"
    doc.undo()
    assert doc.project == baseline


def test_delete_bound_bones_repairs_weights_constraints_keys_and_restores_undo(tmp_path):
    """Deleting a used bone cleans every live dependency without losing source artwork."""
    doc = DocumentService()
    doc.open(Path("examples/image-import-example.rigora"))
    rig = RigService(doc)
    root, child = rig.scene.skeletons[0].bones
    DynamicsService(doc).configure((child.id,))
    AnimationEditingService(doc).key(child.id, "transform.rotation", 8, 25)
    baseline = doc.project
    mesh = rig.scene.meshes[0]
    original_bytes = doc.read_asset(mesh.asset_id)
    rig.delete(child.id)
    assert all(child.id not in v.weights for v in rig.scene.meshes[0].vertices)
    assert all(c.owner_id != child.id for c in rig.scene.constraints)
    assert all(t.owner_id != child.id for timeline in rig.scene.timelines for t in timeline.tracks)
    assert all(child.id not in d.parameters.get("bind_matrices", {}) for d in rig.scene.deformers)
    assert len(rig.scene.objects) == len(baseline.scenes[0].objects)
    assert doc.read_asset(mesh.asset_id) == original_bytes
    doc.project.validate_references()
    doc.save(tmp_path / "deleted-bone.rigora")
    doc.undo()
    assert doc.project == baseline
    rig.delete_many((root.id, child.id))
    assert not rig.scene.skeletons[0].bones
    assert not any(d.kind == "skinning" for d in rig.scene.deformers)
    assert all(not v.weights for m in rig.scene.meshes for v in m.vertices)
    doc.project.validate_references()
    doc.undo()
    assert doc.project == baseline
