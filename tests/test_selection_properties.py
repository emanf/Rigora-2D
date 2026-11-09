"""Selection-strip sizing, appearance animation, reset, locks and track clipboard contracts."""

import pytest

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.appearance import AppearanceService
from rigora.application_services.documents import DocumentService
from rigora.application_services.scene_editing import SceneEditingService
from rigora.application_services.selection_properties import SelectionPropertyService
from rigora.domain.geometry import transform_point
from rigora.domain.project import ProjectError


@pytest.fixture
def artwork():
    """Own one sharp vector rectangle with known original dimensions."""
    doc = DocumentService()
    doc.new()
    shapes = AppearanceService(doc)
    mesh = shapes.create_shape("rectangle", 100, 150, 200, 120)
    key = str(shapes.mesh(mesh).object_id)
    return doc, SelectionPropertyService(doc), key


def test_dimensions_ignore_rotation_and_ratio_lock_preserves_pivot(artwork):
    doc, service, key = artwork
    service.set_transform(key, rotation=37)
    state = service.metrics((key,))
    assert (state.width, state.height) == pytest.approx((200, 120))
    assert (state.x, state.y) == (200, 210)
    service.edit((key,), "width", 400)
    changed = service.metrics((key,))
    assert (changed.width, changed.height) == pytest.approx((400, 240))
    assert (changed.x, changed.y, changed.rotation) == pytest.approx((200, 210, 37))
    service.edit((key,), "height", 180, ratio=False)
    assert service.metrics((key,)).width == pytest.approx(400)
    service.edit((key,), "x", 350)
    assert service.metrics((key,)).x == 350
    assert doc.animation.pose.nodes[key].local.x == 250


def test_reset_restores_native_size_pivot_opacity_facing_and_camera_center_in_one_undo(artwork):
    doc, service, key = artwork
    service.set_transform(key, x=40, y=20, rotation=80, scale_x=-2, scale_y=3)
    service.move_pivot(key, 45, 70)
    service.appearance((key,), opacity=20, visible=False)
    baseline = doc.project
    before = len(doc.history.undo_stack)
    service.reset((key,))
    node = doc.animation.pose.nodes[key]
    assert node.local.rotation == 0 and node.local.scale_x == node.local.scale_y == 1
    assert (node.local.pivot_x, node.local.pivot_y) == pytest.approx((100, 60))
    assert transform_point(node.world_matrix, 100, 60) == pytest.approx((960, 540))
    state = service.metrics((key,))
    assert (state.width, state.height, state.opacity, state.visible) == (200, 120, 100, True)
    assert len(doc.history.undo_stack) == before + 1
    doc.undo()
    assert doc.project == baseline


def test_group_reset_keeps_parts_separate_and_recenters_folder(artwork):
    doc, service, key = artwork
    shapes = AppearanceService(doc)
    other = str(shapes.mesh(shapes.create_shape("ellipse", 500, 200, 100, 100)).object_id)
    group = service.group((key, other))
    service.set_transform(group, rotation=40, scale_x=-2, scale_y=2)
    child_transforms = tuple(o.transform for o in service.scene.objects)
    service.reset((group,))
    assert tuple(o.transform for o in service.scene.objects) == child_transforms
    center = service.metrics((group,))
    assert center.x == pytest.approx(960)
    assert center.y == pytest.approx(540)
    assert service.metrics((group,)).width > 400


def test_multi_resize_scales_placement_and_width_together(artwork):
    doc, service, key = artwork
    shapes = AppearanceService(doc)
    other = str(shapes.mesh(shapes.create_shape("ellipse", 500, 200, 100, 100)).object_id)
    before = service.metrics((key, other))
    service.edit((key, other), "width", before.width * 2)
    after = service.metrics((key, other))
    assert after.width == pytest.approx(before.width * 2)
    assert after.height == pytest.approx(before.height * 2)
    assert after.x + after.width / 2 == pytest.approx(before.x + before.width / 2)


def test_visibility_keys_seed_hidden_state_and_use_holds(artwork):
    doc, service, key = artwork
    service.appearance((key,), visible=False)
    service.auto_key = True
    doc.animation.seek(20)
    service.appearance((key,), visible=True, opacity=30)
    editor = AnimationEditingService(doc)
    visibility = next(t for t in editor.timeline.tracks if t.property_path == "visibility")
    assert [(k.frame, k.value, k.interpolation) for k in visibility.keyframes] == [
        (0, 0, "step"),
        (20, 1, "step"),
    ]
    assert not doc.animation.evaluate(19).nodes[key].visible
    assert doc.animation.evaluate(20).nodes[key].visible
    assert doc.animation.evaluate(20).nodes[key].opacity == pytest.approx(0.3)
    service.auto_key = False
    doc.animation.seek(30)
    service.appearance((key,), visible=False)
    visibility = next(t for t in editor.timeline.tracks if t.property_path == "visibility")
    assert [k.frame for k in visibility.keyframes] == [0, 20, 30]


def test_locked_selection_rejects_reset_without_partial_changes(artwork):
    doc, service, key = artwork
    service.flags((key,), locked=True)
    baseline, count = doc.project, len(doc.history.undo_stack)
    with pytest.raises(ProjectError, match="unlocked"):
        service.reset((key,))
    assert doc.project is baseline and len(doc.history.undo_stack) == count


def test_track_cut_paste_retains_empty_lanes_key_curves_and_undo(artwork):
    doc, _, key = artwork
    editor = AnimationEditingService(doc)
    editor.add_channels(((key, "transform.x"), (key, "transform.y")))
    editor.key(key, "transform.x", 4, 10)
    editor.key(key, "transform.x", 14, 20)
    source = editor.timeline
    data = editor.copy_tracks(t.id for t in source.tracks)
    editor.remove_tracks(t.id for t in source.tracks)
    assert not editor.timeline.tracks
    before = len(doc.history.undo_stack)
    refs = editor.paste_tracks(data, 20)
    assert len(refs) == 2 and len(editor.timeline.tracks) == 2
    assert [k.frame for k in editor.timeline.tracks[0].keyframes] == [20, 30]
    assert not editor.timeline.tracks[1].keyframes
    assert len(doc.history.undo_stack) == before + 1
    doc.undo()
    assert not editor.timeline.tracks


def test_track_paste_collision_missing_owner_and_lock_fail_atomically(artwork):
    doc, _, key = artwork
    editor = AnimationEditingService(doc)
    editor.add_channels(((key, "transform.x"), (key, "transform.y")))
    editor.key(key, "transform.x", 4, 10)
    data = editor.copy_tracks(t.id for t in editor.timeline.tracks)
    baseline, count = doc.project, len(doc.history.undo_stack)
    with pytest.raises(ProjectError, match="overlap"):
        editor.paste_tracks(data, 4)
    assert doc.project is baseline and len(doc.history.undo_stack) == count
    track = editor.timeline.tracks[1]
    editor.track_settings(track.id, locked=True, visible=True)
    baseline = doc.project
    with pytest.raises(ProjectError, match="Unlock"):
        editor.remove_tracks(t.id for t in editor.timeline.tracks)
    with pytest.raises(ProjectError, match="Unlock"):
        editor.paste_tracks(data, 20)
    assert doc.project is baseline
    data["tracks"][0]["owner_id"] = "missing"
    with pytest.raises(ProjectError):
        editor.paste_tracks(data, 20)
    assert doc.project is baseline


def test_invalid_track_payload_is_rejected(artwork):
    doc, _, _ = artwork
    editor = AnimationEditingService(doc)
    for data in ({}, {"format": "rigora.tracks", "version": 1, "tracks": []}):
        with pytest.raises(ProjectError):
            editor.paste_tracks(data, 0)


def test_empty_track_clipboard_preserves_editor_and_blend_settings(artwork):
    doc, _, key = artwork
    editor = AnimationEditingService(doc)
    editor.add_channels(((key, "transform.x"),))
    track = editor.timeline.tracks[0]
    from dataclasses import replace

    editor.publish(
        "Layered lane",
        replace(
            editor.timeline,
            tracks=(replace(track, blend_mode="additive", weight=0.4, visible=False),),
        ),
        editor.clip,
    )
    data = editor.copy_tracks((track.id,))
    editor.remove_tracks((track.id,))
    refs = editor.paste_tracks(data, 20)
    restored = editor.timeline.tracks[0]
    assert not refs and not restored.keyframes
    assert restored.blend_mode == "additive" and restored.weight == 0.4 and not restored.visible


def test_existing_transform_edits_and_reset_record_current_frame(artwork):
    doc, service, key = artwork
    editor = AnimationEditingService(doc)
    editor.key(key, "transform.x", 0, 100)
    editor.key(key, "transform.x", 20, 300)
    doc.animation.seek(10)
    service.edit((key,), "x", 500)
    assert service.metrics((key,)).x == 500
    assert doc.animation.evaluate(0).nodes[key].local.x == 100

    before = len(doc.history.undo_stack)
    service.reset((key,))
    assert len(doc.history.undo_stack) == before + 1
    assert service.metrics((key,)).x == 960
    assert service.metrics((key,)).y == 540
    assert doc.animation.evaluate(0).nodes[key].local.x == 100


@pytest.mark.parametrize(
    "changes", ({"dx": 35, "dy": 20}, {"rotation": 25}, {"scale_x": 1.5, "scale_y": 1.5})
)
def test_shared_scene_transforms_record_existing_keys_without_auto_key(artwork, changes):
    """Headless and canvas edits share current-pose recording without mutating rest transforms."""
    doc, _, key = artwork
    editor = AnimationEditingService(doc)
    channels = tuple((key, f"transform.{p}") for p in ("x", "y", "rotation", "scale_x", "scale_y"))
    editor.add_channels(channels, frame=0)
    editor.add_channels(channels, frame=20)
    doc.animation.seek(10)
    service = SceneEditingService(doc)
    before, count = doc.project, len(doc.history.undo_stack)
    original = doc.animation.evaluate(0).nodes[key]
    source = doc.animation.pose.nodes[key]
    service.transform((key,), **changes)
    node = doc.animation.pose.nodes[key]
    assert node.local.x == pytest.approx(source.local.x + changes.get("dx", 0))
    assert node.local.y == pytest.approx(source.local.y + changes.get("dy", 0))
    assert node.local.rotation == pytest.approx(source.local.rotation + changes.get("rotation", 0))
    assert node.local.scale_x == pytest.approx(source.local.scale_x * changes.get("scale_x", 1))
    assert node.local.scale_y == pytest.approx(source.local.scale_y * changes.get("scale_y", 1))
    assert doc.animation.evaluate(0).nodes[key] == original
    assert service.scene.objects == before.scenes[0].objects
    assert not service.auto_key and len(doc.history.undo_stack) == count + 1
    doc.undo()
    assert doc.project == before


def test_empty_transform_lanes_remain_editable_without_creating_keys(artwork):
    doc, _, key = artwork
    editor = AnimationEditingService(doc)
    editor.add_channels(((key, "transform.x"),))
    service = SceneEditingService(doc)
    original = doc.animation.pose.nodes[key]
    service.transform((key,), dx=35)
    assert doc.animation.pose.nodes[key].local.x == original.local.x + 35
    assert not editor.timeline.tracks[0].keyframes
