"""Original vector controls and pivot-based paths evaluated by ordinary scalar channels."""

import pytest

from rigora.application_services.documents import DocumentService
from rigora.application_services.path_editing import PathEditingService
from rigora.domain.geometry import transform_point


def test_bezier_artwork_revisions_and_camera_pivot_path_survive_undo_and_storage(tmp_path):
    """A camera follows the actual cubic at midpoint; editing artwork retains its geometry."""
    doc = DocumentService()
    doc.new()
    service = PathEditingService(doc)
    points = ((0, 0), (0, 100), (100, 100), (100, 0))
    key = service.artwork(points)
    mesh = service.mesh(key)
    before = doc.read_asset(mesh.asset_id)
    service.artwork(((0, 0), (10, 100), (90, 100), (100, 0)), mesh_id=key, stroke="#ff0000")
    assert service.mesh(key).vertices == mesh.vertices
    assert doc.read_asset(mesh.asset_id) != before
    doc.undo()
    assert doc.read_asset(mesh.asset_id) == before
    camera = doc.scene.cameras[0]
    service.motion(camera.id, points, 0, 20, orient=True)
    pose = doc.animation.evaluate(10)
    assert not pose.warnings
    node = pose.nodes[camera.id]
    assert transform_point(
        node.world_matrix, node.local.pivot_x, node.local.pivot_y
    ) == pytest.approx((50, 75))
    assert node.local.rotation == pytest.approx(0)
    doc.save(tmp_path / "curves.rigora")
    doc.open(doc.path)
    assert doc.animation.evaluate(10).nodes[camera.id] == node


def test_scene_path_edit_adds_manual_progress_without_rewriting_placed_action():
    """Editing scene path timing preserves reusable action keys and its arranged segment."""
    from test_object_scene_actions import composition

    doc, chars, _, root, _, _ = composition()
    doc.set_animation_context(root, frozenset(chars.members(root)))
    clip = chars.new_motion(root, "Path action")
    points = ((0, 0), (0, 100), (100, 100), (100, 0))
    paths = PathEditingService(doc)
    rule = paths.motion(root, points, 0, 10)
    doc.set_animation_context(None)
    chars.place_motion(root, clip, 0, 2)
    old = tuple(t for t in doc.animation.evaluator.timeline.tracks if t.extra.get("motion_window"))
    paths.motion(root, points, 30, 40)
    tracks = doc.animation.evaluator.timeline.tracks
    assert tuple(t for t in tracks if t.extra.get("motion_window")) == old
    manual = next(t for t in tracks if t.owner_id == rule and not t.extra.get("motion_window"))
    assert [k.frame for k in manual.keyframes] == [30, 40]
