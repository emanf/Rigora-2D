"""Reusable source instances, scene protection and normalized editable FFD motion workflows."""

from dataclasses import replace
from pathlib import Path

import pytest

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.content_library import ContentLibrary, ContentService
from rigora.application_services.documents import DocumentService
from rigora.application_services.ffd_motion import FfdMotionService
from rigora.application_services.meshes import MeshService
from rigora.application_services.rigging import RigService
from rigora.application_services.scene_editing import SceneEditingService
from rigora.domain.project import ProjectError
from rigora.engine.ffd_controls import edit_controls
from rigora.infrastructure.content_packs import read_pack
from rigora.infrastructure.preferences import PreferencesStore


def test_scene_bone_parenting_cycles_and_sibling_order_are_atomic():
    """Scene moves share rig validation and keep branch world poses, including undo."""
    doc = DocumentService()
    doc.new()
    rig, scene = RigService(doc), SceneEditingService(doc)
    root = rig.create_bone((100, 100), (200, 100))
    a = rig.create_bone((200, 100), (260, 100), root)
    b = rig.create_bone((200, 100), (200, 160), root)
    child = rig.create_bone((260, 100), (300, 100), a)
    baseline, before = doc.project, rig.rest_pose()
    count = len(doc.history.undo_stack)
    scene.move_entries((a, child), b)
    assert rig.bone(a).parent_id == b and rig.bone(child).parent_id == a
    assert rig.rest_pose().nodes[child].world_matrix == pytest.approx(
        before.nodes[child].world_matrix
    )
    assert len(doc.history.undo_stack) == count + 1
    doc.undo()
    assert doc.project == baseline
    with pytest.raises(ProjectError):
        scene.move_entries((root,), child)
    assert doc.project == baseline and len(doc.history.undo_stack) == count
    scene.move_entries((b,), root, a)
    siblings = [bone.id for bone in rig.scene.skeletons[0].bones if bone.parent_id == root]
    assert siblings == [b, a]
    rig.update(b, locked=True)
    with pytest.raises(ProjectError, match="unlocked"):
        scene.move_entries((a,), b)


def test_scene_artwork_can_attach_reattach_and_move_back_into_folder():
    """Visual bone parenting is an explicit keep-world attachment and can be undone or detached."""
    doc = DocumentService()
    doc.new()
    rig, scene = RigService(doc), SceneEditingService(doc)
    a = rig.create_bone((100, 100), (200, 100))
    b = rig.create_bone((400, 200), (480, 200))
    mesh = scene.import_image(Path("assets/examples/prop.svg"), 3, 3)
    owner = scene.mesh(mesh).object_id
    folder = scene.group()
    world = doc.animation.pose.nodes[owner].world_matrix
    scene.move_entries((owner,), a)
    assert doc.animation.pose.nodes[owner].world_matrix == pytest.approx(world)
    rule = next(c for c in scene.scene.constraints if c.owner_id == owner)
    scene.move_entries((owner,), b)
    assert len(scene.scene.constraints) == 1
    assert scene.scene.constraints[0].id == rule.id and scene.scene.constraints[0].target_id == b
    assert doc.animation.pose.nodes[owner].world_matrix == pytest.approx(world)
    baseline = doc.project
    scene.move_entries((owner,), folder)
    assert not scene.scene.constraints and scene.record(owner).parent_id == folder
    assert doc.animation.pose.nodes[owner].world_matrix == pytest.approx(world)
    doc.undo()
    assert doc.project == baseline


def test_import_library_instances_scene_flags_and_transforms(tmp_path):
    """Import does not place, repeated placement shares bytes but owns independent editable
    geometry.
    """
    doc = DocumentService()
    doc.new()
    service = MeshService(doc)
    key = service.register_image_bytes("prop.svg", Path("assets/examples/prop.svg").read_bytes())
    assert len(doc.project.assets) == 1 and not doc.project.scenes[0].objects
    first, second = service.instantiate_asset(key), service.instantiate_asset(key)
    a, b = service.mesh(first), service.mesh(second)
    assert a.id != b.id and a.object_id != b.object_id and a.vertices[0].id != b.vertices[0].id
    assert a.asset_id == b.asset_id == key and len(doc.project.assets) == 1
    scene = SceneEditingService(doc)
    scene.flags((a.object_id,), visible=False, locked=True)
    assert scene.locked(a.object_id) and not doc.animation.pose.nodes[a.object_id].visible
    with pytest.raises(ProjectError, match="Unlock"):
        scene.transform((a.object_id,), dx=30)
    scene.flags((a.object_id,), visible=True, locked=False)
    baseline = scene.record(a.object_id).transform
    scene.transform((a.object_id,), dx=40, scale_x=2)
    assert scene.record(a.object_id).transform.x == baseline.x + 40
    assert scene.record(b.object_id).transform == baseline
    doc.undo()
    assert scene.record(a.object_id).transform == baseline
    doc.save(tmp_path / "instances.rigora")
    reopened = DocumentService()
    reopened.open(tmp_path / "instances.rigora")
    assert len(reopened.project.assets) == 1 and len(reopened.project.scenes[0].objects) == 2


def test_ffd_selected_scale_rotate_average_reset_and_untouched_points():
    """Transforms act around selected dots while Average reconstructs a bilinear corner surface."""
    params = {"columns": 3, "rows": 3, "bounds": [0, 0, 100, 100], "controls": [[0, 0]] * 9}
    changed = edit_controls(params, (0, 1, 3, 4), scale_x=2, scale_y=2)
    assert set(changed) == {0, 1, 3, 4}
    assert changed[0] == (-25, -25) and changed[4] == (25, 25)
    rotated = edit_controls(params, (0, 2), rotation=90)
    assert rotated[0] == pytest.approx((50, -50))
    params["controls"] = [[0, 0] for _ in range(9)]
    params["controls"][2] = [40, 20]
    redistributed = edit_controls(params, (), operation="average")
    assert redistributed[4] == pytest.approx((10, 5))
    assert redistributed[2] == (40, 20)
    assert edit_controls(params, (2,), operation="reset") == {2: (0, 0)}


def test_normalized_ffd_motions_layer_strength_roundtrip_share_and_undo(tmp_path):
    """One-click motion retains existing tracks, adapts size, multiplies strengths and shares
    keys.
    """
    doc = DocumentService()
    doc.new()
    mesh_id = MeshService(doc).import_image(Path("assets/examples/prop.svg"), 4, 4)
    owner = MeshService(doc).mesh(mesh_id).object_id
    editor = AnimationEditingService(doc)
    editor.key(owner, "transform.x", 0, 200)
    editor.key(owner, "transform.x", 48, 260)
    original = doc.project
    original_tracks = editor.timeline.tracks
    item = next(
        e.item
        for e in ContentLibrary(PreferencesStore(tmp_path / "ui.json")).entries()
        if e.item.name == "Soft breathing"
    )
    item = replace(item, payload={**item.payload, "repeats": 2, "speed": 2, "strength": 0.5})
    count = len(doc.history.undo_stack)
    stage = ContentService(doc).apply(item, {}, mesh_id=mesh_id)
    assert len(doc.history.undo_stack) == count + 1
    assert all(track in editor.timeline.tracks for track in original_tracks)
    first = doc.animation.evaluate(0).meshes[mesh_id].positions
    peak = doc.animation.evaluate(6).meshes[mesh_id].positions
    assert first != peak
    assert doc.animation.evaluate(6).nodes[owner].local.x == pytest.approx(207.5)
    service = FfdMotionService(doc)
    service.object_strength(mesh_id, 0)
    assert doc.animation.evaluate(6).meshes[mesh_id].positions == first
    service.object_strength(mesh_id, 1)
    shared = tmp_path / "original-ffd.rigpack"
    service.export(shared, stage, "My FFD", "eManF", "CC0-1.0")
    pack, files = read_pack(shared)
    assert "motion" in pack.items[0].payload and pack.items[0].author == "eManF"
    other = DocumentService()
    other.new()
    target = MeshService(other).import_image(Path("assets/examples/torso.svg"), 3, 3)
    ContentService(other).apply(pack.items[0], files, mesh_id=target)
    assert (
        other.animation.evaluate(6).meshes[target].positions
        != other.animation.evaluate(0).meshes[target].positions
    )
    doc.undo()
    doc.undo()
    doc.undo()
    assert doc.project == original
