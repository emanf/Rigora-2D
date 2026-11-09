"""Cameras share deterministic scene transforms, cuts, persistence and render projection."""

import pytest

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.cameras import CameraService
from rigora.application_services.documents import DocumentService
from rigora.application_services.meshes import MeshService
from rigora.application_services.rendering import svg_frame
from rigora.application_services.scene_editing import SceneEditingService
from rigora.domain.entities import Transform
from rigora.domain.geometry import transform_point
from rigora.domain.project import ProjectError, SceneSettings
from rigora.engine.cameras import active_camera, camera_corners, camera_view


def test_cameras_default_scene_lifecycle_save_reopen_and_independent_transforms(tmp_path):
    """Each new scene owns one main camera; camera edits survive complete graph serialization."""
    doc = DocumentService()
    doc.new(settings=SceneSettings(width=640, height=360))
    first = doc.scene.cameras[0]
    assert first.name == "Main Camera" and first.active
    assert SceneEditingService(doc).locked(first.id)
    assert not doc.scene.groups and not doc.scene.objects
    assert camera_corners(first, doc.animation.pose, doc.scene.settings) == (
        (0, 0),
        (640, 0),
        (640, 360),
        (0, 360),
    )
    service = CameraService(doc)
    other = service.add()
    assert not SceneEditingService(doc).locked(other)
    SceneEditingService(doc).set_transform(
        other, x=100, y=50, rotation=30, scale_x=0.5, scale_y=0.5
    )
    service.update(
        other,
        background_mode="color",
        background_color="#12345680",
        match_scene=False,
        width=320.0,
        height=180.0,
    )
    service.activate(other)
    previous = doc.project
    service.duplicate(other)
    doc.undo()
    assert doc.project == previous
    second_scene = doc.add_scene()
    assert len(doc.project.scenes[1].cameras) == 1
    assert doc.project.scenes[1].cameras[0].extra["locked"]
    assert doc.project.scenes[1].cameras[0].id not in {first.id, other}
    path = tmp_path / "cameras.rigora"
    doc.save(path)
    loaded = DocumentService()
    loaded.open(path)
    assert loaded.project == doc.project
    assert CameraService(loaded).current().id == other
    loaded.select_scene(second_scene)
    assert CameraService(loaded).current().name == "Main Camera"


def test_keyed_cuts_are_exclusive_stepped_and_transform_animation_changes_projection():
    """Camera cuts retain the original view until the exact key, independent of seek history."""
    doc = DocumentService()
    doc.new()
    service = CameraService(doc)
    first = doc.scene.cameras[0].id
    second = service.add()
    service.activate(second, frame=20)
    service.activate(first, frame=40)
    edit = AnimationEditingService(doc)
    edit.key(second, "transform.x", 0, 0)
    edit.key(second, "transform.x", 40, 400)
    edit.key(second, "transform.rotation", 0, 0)
    edit.key(second, "transform.rotation", 40, 40)
    edit.key(second, "transform.scale_x", 0, 1)
    edit.key(second, "transform.scale_x", 40, 2)
    edit.key(second, "transform.scale_y", 0, 1)
    edit.key(second, "transform.scale_y", 40, 2)
    for frame, expected in (
        (45, first),
        (19.999, first),
        (20, second),
        (39.999, second),
        (0, first),
        (40, first),
    ):
        pose = doc.animation.evaluate(frame)
        assert active_camera(pose).id == expected
    pose = doc.animation.evaluate(30)
    camera_node = pose.nodes[second]
    projected = camera_view(pose)
    point = transform_point(camera_node.world_matrix, 200, 100)
    assert transform_point(projected.nodes[second].world_matrix, 200, 100) == pytest.approx(
        (200, 100)
    )
    from rigora.domain.geometry import inverse

    assert transform_point(inverse(camera_node.world_matrix), *point) == pytest.approx((200, 100))
    assert all(
        k.interpolation == "step"
        for t in edit.timeline.tracks
        if t.property_path == "camera.active"
        for k in t.keyframes
    )
    assert not pose.render_order
    from rigora.engine.camera_actions import EFFECT_PRESETS

    assert {p for owner, p, _ in edit.properties() if owner.id == second} == {
        "camera.active",
        *("camera.effect." + preset for preset in EFFECT_PRESETS),
        *("transform." + p for p in Transform.__dataclass_fields__ if p != "extra"),
    }


def test_scene_cuts_can_deactivate_locked_cameras_without_unlocking_transforms_or_tracks():
    """Output selection is scene-wide; owner transforms and explicit cut-track locks stay safe."""
    doc = DocumentService()
    doc.new()
    service = CameraService(doc)
    first = doc.scene.cameras[0].id
    second = service.add()
    service.activate(second, frame=20)
    assert SceneEditingService(doc).locked(first)
    editor = AnimationEditingService(doc)
    before = doc.project
    with pytest.raises(ProjectError, match="Unlock the animated owner"):
        editor.key(first, "transform.x", 5, 100)
    assert doc.project == before
    track = next(t for t in editor.timeline.tracks if t.owner_id == first)
    editor.track_settings(track.id, locked=True, visible=True)
    before = doc.project
    with pytest.raises(ProjectError, match="Unlock the track"):
        service.activate(first, frame=30)
    assert doc.project == before


def test_camera_background_image_export_projection_and_deletion_cleanup():
    """Embedded backgrounds reach output; deleting a camera repairs dependent tracks."""
    doc = DocumentService()
    doc.new()
    service = CameraService(doc)
    key = doc.scene.cameras[0].id
    SceneEditingService(doc).flags((key,), locked=False)
    source = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="80" height="40">'
        b'<rect width="80" height="40" fill="#ffffff"/></svg>'
    )
    asset = MeshService(doc).register_image_bytes("Background.svg", source)
    service.update(
        key,
        match_scene=False,
        width=400.0,
        height=200.0,
        background_mode="image",
        background_color="#12345680",
        asset_id=asset,
        background_fit="contain",
        background_opacity=0.5,
    )
    data = svg_frame(doc, 0).decode()
    assert 'viewBox="0 0 400 200"' in data
    assert 'fill="#123456"' in data and "xMidYMid meet" in data
    assert "data:image/svg+xml;base64," in data and 'opacity="0.5"' in data
    assert "bone-source" not in data
    service.activate(key, frame=10)
    SceneEditingService(doc).delete_entries((key,))
    assert not doc.scene.cameras
    assert not doc.animation.pose.nodes
    assert all(t.owner_id != key for timeline in doc.scene.timelines for t in timeline.tracks)
    assert active_camera(doc.animation.pose) is None
    doc.undo()
    assert CameraService(doc).current().id == key
    service.update(key, enabled=False)
    assert active_camera(doc.animation.pose) is None


@pytest.mark.parametrize(
    "fields",
    (
        {"width": 0},
        {"background_color": "red"},
        {"background_opacity": 2},
        {"transform": Transform(scale_x=0)},
    ),
)
def test_invalid_camera_data_never_enters_history(fields):
    """Headless and GUI clients share bounded frame/color/transform validation."""
    doc = DocumentService()
    doc.new()
    before = doc.project
    with pytest.raises(ProjectError):
        CameraService(doc).update(doc.scene.cameras[0].id, **fields)
    assert doc.project is before


def test_camera_automation_and_scene_copy_share_the_same_validated_services(tmp_path):
    """Public Python/CLI/MCP operations retain cuts and remap camera IDs on scene duplication."""
    from rigora.api import RigoraAPI
    from rigora.application_services.object_library import ObjectLibraryService

    api = RigoraAPI(tmp_path)
    api.execute("project_create")
    first = api.execute("camera_list").data["active_camera_id"]
    second = api.execute("camera_create", {"name": "Closeup"}).data["camera_id"]
    api.execute(
        "camera_edit",
        {
            "camera_id": second,
            "settings": {
                "transform": {"x": 120, "rotation": 15},
                "background_mode": "color",
                "background_color": "#556677",
            },
        },
    )
    api.execute("camera_activate", {"camera_id": second, "frame": 24})
    assert active_camera(api.document.animation.evaluate(23)).id == first
    assert active_camera(api.document.animation.evaluate(24)).id == second
    copies = ObjectLibraryService(api.document)
    copied = copies.copy_scene(api.document.scene.id)
    scene_id = copies.paste(copied)[0]
    api.execute("scene_select", {"scene_id": scene_id})
    cameras = api.execute("camera_list").data["cameras"]
    assert len(cameras) == 2 and all(c["id"] not in (first, second) for c in cameras)
    assert active_camera(api.document.animation.evaluate(24)).name == "Closeup"
    api.execute("camera_delete", {"camera_id": cameras[1]["id"]})
    assert len(api.document.scene.cameras) == 1
    api.execute("undo")
    assert len(api.document.scene.cameras) == 2


def test_camera_reset_preserves_cuts_and_appearance_and_can_record_transform_only():
    """Reset never turns an inactive camera on or creates artwork visibility/opacity lanes."""
    from rigora.application_services.selection_properties import SelectionPropertyService

    doc = DocumentService()
    doc.new()
    service = CameraService(doc)
    key = service.add()
    service.update(
        key,
        match_scene=False,
        width=640.0,
        height=360.0,
        background_mode="color",
        background_color="#aabbcc",
    )
    SceneEditingService(doc).set_transform(key, x=100, y=50, rotation=20, scale_x=2, scale_y=2)
    SelectionPropertyService(doc).reset((key,))
    assert doc.animation.pose.nodes[key].world_matrix == pytest.approx((1, 0, 0, 1, 0, 0))
    assert not service.camera(key).active and service.camera(key).background_color == "#aabbcc"
    reset = SelectionPropertyService(doc)
    reset.auto_key = True
    reset.reset((key,))
    assert all(
        t.property_path.startswith("transform.")
        for t in AnimationEditingService(doc).timeline.tracks
    )
