"""Centered imports, stable pivot edits and local-axis resizing through Qt-free services."""

import pytest

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.appearance import AppearanceService
from rigora.application_services.characters import CharacterService
from rigora.application_services.documents import DocumentService
from rigora.application_services.scene_editing import SceneEditingService
from rigora.domain.geometry import transform_point


def artwork():
    """Create one generated shape with original vectors and its normal scene transform."""
    doc = DocumentService()
    doc.new()
    shapes = AppearanceService(doc)
    mesh = shapes.create_shape("rectangle", 120, 100, 200, 120)
    return doc, shapes.mesh(mesh).object_id, SceneEditingService(doc)


def test_large_import_has_center_pivot_and_unchanged_camera_fit():
    """Pivot defaults cannot offset the fitted artwork or alter reusable source bytes."""
    doc = DocumentService()
    doc.new()
    shapes = AppearanceService(doc)
    source = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="4000" height="2000">'
        b'<rect width="4000" height="2000"/></svg>'
    )
    mesh = shapes.import_image_bytes("Large.svg", source)
    node = doc.animation.pose.nodes[shapes.mesh(mesh).object_id]
    assert (node.local.pivot_x, node.local.pivot_y) == (2000, 1000)
    assert transform_point(node.world_matrix, 2000, 1000) == pytest.approx((960, 540))
    assert transform_point(node.world_matrix, 0, 0) == pytest.approx((192, 156))
    assert doc.read_asset(shapes.mesh(mesh).asset_id) == source


def test_relocating_pivot_keeps_transformed_artwork_and_folder_children_fixed(tmp_path):
    """A moved pivot persists through save/Undo and remains the center of later rotation."""
    doc, owner, service = artwork()
    group = service.group((owner,))
    service.set_transform(group, rotation=27, scale_x=1.4, scale_y=0.7)
    service.set_transform(owner, rotation=-31, scale_x=1.5, scale_y=0.8)
    before = doc.project
    matrix = doc.animation.pose.nodes[owner].world_matrix
    point = transform_point(matrix, 40, 75)
    service.move_pivot(owner, *point)
    node = doc.animation.pose.nodes[owner]
    assert node.world_matrix == pytest.approx(matrix)
    assert (node.local.pivot_x, node.local.pivot_y) == pytest.approx((40, 75))
    doc.save(tmp_path / "pivot.rigora")
    clone = DocumentService()
    clone.open(tmp_path / "pivot.rigora")
    assert clone.animation.pose.nodes[owner].world_matrix == pytest.approx(matrix)
    assert clone.project.scenes[0].objects[0].extra["pivot_edited"]
    doc.undo()
    assert doc.project == before
    before = doc.animation.pose.nodes[owner].world_matrix
    service.move_pivot(group, 350, 280)
    assert doc.animation.pose.nodes[owner].world_matrix == pytest.approx(before)
    service.transform((group,), rotation=35)
    node = doc.animation.pose.nodes[group]
    assert transform_point(
        node.world_matrix, node.local.pivot_x, node.local.pivot_y
    ) == pytest.approx((350, 280))


def test_keyed_pivot_and_following_rotation_preserve_current_position():
    """Animated edits sample compensated translation and pivot together, preserving frame zero."""
    doc, owner, service = artwork()
    editor = AnimationEditingService(doc)
    editor.key(owner, "transform.rotation", 0, 0)
    editor.key(owner, "transform.rotation", 40, 60)
    initial = doc.animation.evaluate(0).nodes[owner].world_matrix
    doc.animation.seek(20)
    before = doc.animation.pose.nodes[owner].world_matrix
    point = transform_point(before, 20, 30)
    service.move_pivot(owner, *point)
    assert not service.auto_key
    assert doc.animation.pose.nodes[owner].world_matrix == pytest.approx(before)
    assert doc.animation.evaluate(0).nodes[owner].world_matrix == pytest.approx(initial)
    service.transform((owner,), rotation=15, center_x=point[0], center_y=point[1])
    node = doc.animation.pose.nodes[owner]
    assert transform_point(
        node.world_matrix, node.local.pivot_x, node.local.pivot_y
    ) == pytest.approx(point)


def test_scene_pivot_is_not_blocked_by_transform_keys_in_private_object_actions():
    """An Object's inactive actions cannot prevent editing its independent scene placement pivot."""
    doc, owner, service = artwork()
    root = CharacterService(doc).create_object((owner,), "Animated Object")
    CharacterService(doc).new_motion(root, "Private turn")
    editor = AnimationEditingService(doc)
    editor.key(root, "transform.rotation", 0, 0)
    editor.key(root, "transform.rotation", 20, 45)
    doc.set_animation_context(None)
    timelines, before = doc.scene.timelines, doc.animation.pose.nodes[root].world_matrix
    service.move_pivot(root, 350, 280)
    assert doc.scene.timelines == timelines
    node = doc.animation.pose.nodes[root]
    assert node.world_matrix == pytest.approx(before)
    assert transform_point(
        node.world_matrix, node.local.pivot_x, node.local.pivot_y
    ) == pytest.approx((350, 280))


def test_local_axis_resize_under_scaled_rotated_parent_keeps_opposite_edge():
    """Nonuniform scaling follows object axes, including under a nonuniform parent."""
    doc, owner, service = artwork()
    group = service.group((owner,))
    service.set_transform(group, rotation=27, scale_x=1.4, scale_y=0.7)
    service.set_transform(owner, rotation=37)
    before = doc.animation.pose.nodes[owner]
    anchor = transform_point(before.world_matrix, 0, 60)
    service.transform(
        (owner,), scale_x=1.6, scale_y=1, center_x=anchor[0], center_y=anchor[1], space_id=owner
    )
    after = doc.animation.pose.nodes[owner]
    assert transform_point(after.world_matrix, 0, 60) == pytest.approx(anchor)
    assert after.local.scale_x == pytest.approx(before.local.scale_x * 1.6)
    assert after.local.scale_y == pytest.approx(before.local.scale_y)
