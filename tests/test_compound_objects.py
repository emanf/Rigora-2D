"""Solid object containers, independent editable parts and blank reusable animation clips."""

from pathlib import Path

import pytest

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.appearance import AppearanceService
from rigora.application_services.characters import CharacterService
from rigora.application_services.documents import DocumentService
from rigora.domain.geometry import transform_point


def test_empty_object_parts_motion_transform_and_roundtrip(tmp_path: Path):
    """An empty object can own an empty clip, gain parts later and retain independent transforms."""
    document = DocumentService()
    document.new()
    objects = CharacterService(document)
    root = objects.create_object(name="My object")
    clip = objects.new_motion(root, "Idle")
    animation = AnimationEditingService(document)
    assert animation.clip.id == clip and not animation.timeline.tracks
    assert not objects.scene.skeletons and not objects.scene.characters
    look = AppearanceService(document)
    a = look.create_shape("ellipse", 100, 150, 60, 90)
    b = look.create_shape("rectangle", 180, 190, 80, 30)
    before = document.animation.pose
    objects.add_object_parts(root, (a, b))
    for key in (a, b):
        owner = str(objects.mesh(key).object_id)
        assert document.animation.pose.nodes[owner].world_matrix == pytest.approx(
            before.nodes[owner].world_matrix
        )
        assert objects.object_root(key).id == root
    local = {o.id: o.transform for o in objects.scene.objects}
    objects.transform((root,), dx=35, dy=20, rotation=25)
    assert {o.id: o.transform for o in objects.scene.objects} == local
    animation.auto_key_values({(root, "transform.rotation"): 0}, 0)
    animation.auto_key_values({(root, "transform.rotation"): 90}, 20)
    assert document.animation.evaluate(0).nodes[root].local.rotation == 0
    assert document.animation.evaluate(20).nodes[root].local.rotation == 90
    assert len(objects.motions(root)) == 1
    document.save(tmp_path / "object.rigora")
    loaded = DocumentService()
    loaded.open(tmp_path / "object.rigora")
    assert loaded.project == document.project
    assert CharacterService(loaded).object_root(a).id == root


def test_adopting_import_folders_preserves_their_structure_and_undo():
    """PSD-like imported folders remain nested parts rather than being flattened on adoption."""
    document = DocumentService()
    document.new()
    objects = CharacterService(document)
    root = objects.create_object()
    look = AppearanceService(document)
    a = look.create_shape("ellipse", 100, 100, 40, 60)
    b = look.create_shape("rectangle", 120, 130, 50, 70)
    owners = tuple(str(objects.mesh(k).object_id) for k in (a, b))
    folder = objects.group(owners, "Imported layers")
    before = document.project
    count = len(document.history.undo_stack)
    points = {
        key: transform_point(document.animation.pose.nodes[key].world_matrix, 0, 0)
        for key in owners
    }
    objects.add_object_parts(root, (a, b))
    assert objects.record(folder).parent_id == root
    assert all(objects.record(key).parent_id == folder for key in owners)
    assert len(document.history.undo_stack) == count + 1
    for key in owners:
        assert transform_point(
            document.animation.pose.nodes[key].world_matrix, 0, 0
        ) == pytest.approx(points[key])
    document.undo()
    assert document.project == before


def test_animated_single_image_gains_parts_without_reparenting_its_keys():
    """Promoting a one-part object retains its identity, exact poses and existing blank actions."""
    document = DocumentService()
    document.new()
    objects, look = CharacterService(document), AppearanceService(document)
    mesh = look.create_shape("ellipse", 120, 150, 80, 100)
    key = str(objects.mesh(mesh).object_id)
    clip = objects.new_motion(key, "Later")
    editor = AnimationEditingService(document)
    editor.auto_key_values({(key, "transform.rotation"): 10, (key, "transform.x"): 120}, 0)
    editor.auto_key_values({(key, "transform.rotation"): 90, (key, "transform.x"): 240}, 20)
    poses = {
        frame: document.animation.evaluate(frame).nodes[key].world_matrix for frame in (0, 10, 20)
    }
    tracks = editor.timeline.tracks
    root = objects.promote_object(key)
    assert root == key and objects.motions(root)[0].id == clip
    assert editor.timeline.tracks == tracks
    owner = str(objects.mesh(mesh).object_id)
    assert owner != key and objects.record(owner).parent_id == root
    for frame, matrix in poses.items():
        assert document.animation.evaluate(frame).nodes[owner].world_matrix == pytest.approx(matrix)
    other = look.create_shape("rectangle", 250, 200, 40, 60)
    objects.add_object_parts(root, (other,))
    assert objects.object_root(other).id == root
