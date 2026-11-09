"""Real offscreen camera picking, numeric controls, settings, timeline and preview flows."""

import pytest
from PySide6.QtCore import QPointF, Qt
from test_roots_soft_drag_gui import drag
from test_roots_soft_drag_gui import editor as editor

from rigora.application_services.cameras import CameraService
from rigora.application_services.scene_editing import SceneEditingService
from rigora.application_services.selection_properties import SelectionPropertyService
from rigora.presentation.camera_workspace import CameraSettingsDialog

pytestmark = pytest.mark.gui


def test_camera_tree_frame_drag_transform_fields_and_timeline_picker(editor, qtbot):
    """The same camera is selectable, movable and keyable without entering Object Editor."""
    vm, viewport = editor.viewmodel, editor.viewport
    camera = vm.documents.scene.cameras[0]
    SceneEditingService(vm.documents).flags((camera.id,), locked=False)
    vm.changed.emit()
    assert camera.id in editor.scene_workspace.items
    assert list(editor.selection_properties.fields)[:3] == ["x", "y", "depth"]
    viewport.zoom, viewport.offset = 0.2, QPointF(100, 100)
    assert editor.scene_workspace.pick(QPointF(200, 100)) == camera.id
    assert editor.scene_workspace.pick(QPointF(200, 180)) == ""
    editor.scene_workspace.select_entries((camera.id,))
    metrics = SelectionPropertyService(vm.documents).metrics((camera.id,))
    assert metrics.width == 1920 and metrics.height == 1080
    assert not editor.selection_properties.fields["depth"].isEnabled()
    drag(viewport, QPointF(200, 100), QPointF(230, 120))
    assert not vm.scene.error
    assert vm.documents.animation.pose.nodes[camera.id].local.x == pytest.approx(150)
    assert vm.documents.animation.pose.nodes[camera.id].local.y == pytest.approx(100)
    assert not editor.object_edit.active
    strip = editor.selection_properties
    strip.fields["rotation"].setValue(25)
    strip.fields["rotation"].editingFinished.emit()
    strip.fields["width"].setValue(960)
    strip.fields["width"].editingFinished.emit()
    assert vm.documents.animation.pose.nodes[camera.id].local.rotation == pytest.approx(25)
    assert vm.documents.animation.pose.nodes[camera.id].local.scale_x == pytest.approx(0.5)
    editor.camera_workspace.key_transform(camera.id)
    assert not vm.scene.error
    timeline = vm.animation_editor.service.timeline
    assert {t.property_path for t in timeline.tracks if t.owner_id == camera.id} == {
        "transform.x",
        "transform.y",
        "transform.rotation",
        "transform.scale_x",
        "transform.scale_y",
    }
    from rigora.presentation.widgets.timeline_tracks import TrackPicker, row_channels

    picker = TrackPicker(editor.timeline)
    qtbot.addWidget(picker)
    picker.refresh()
    assert camera.id in picker.object_rows
    picker.objects.setCurrentItem(picker.object_rows[camera.id])
    channels = {
        key
        for i in range(picker.tree.topLevelItemCount())
        for key in row_channels(picker.tree.topLevelItem(i))
    }
    assert (camera.id, "transform.x") in channels
    assert any(
        picker.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole + 6)
        == (camera.id, "camera_cut")
        for i in range(picker.tree.topLevelItemCount())
    )
    assert any(owner == "__cameras__" for owner, _ in editor.timeline._groups)
    picker.close()
    editor.camera_workspace.add()
    assert len(vm.documents.scene.cameras) == 2
    other = vm.documents.scene.cameras[-1]
    assert vm.scene.selected == (other.id,)
    editor.camera_workspace.cut(other.id, 20)
    assert not vm.scene.error
    assert any(
        t.property_path == "camera.active" for t in vm.animation_editor.service.timeline.tracks
    )


def test_camera_settings_preview_cancel_apply_and_scene_bound_guard(editor, qtbot):
    """Settings are reversible; preview follows cuts, uses vector sources and clips output."""
    workspace, vm = editor.camera_workspace, editor.viewmodel
    camera = vm.documents.scene.cameras[0]
    dialog = CameraSettingsDialog(workspace, camera.id)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.background.setCurrentIndex(dialog.background.findData("color"))
    dialog.color.setText("#345678")
    dialog.name.setText("Wide shot")
    before = vm.documents.project
    dialog.reject()
    assert vm.documents.project is before
    dialog = CameraSettingsDialog(workspace, camera.id)
    qtbot.addWidget(dialog)
    dialog.background.setCurrentIndex(dialog.background.findData("color"))
    dialog.color.setText("#345678")
    dialog.match.setChecked(False)
    dialog.frame_width.setValue(640)
    dialog.frame_height.setValue(360)
    dialog.apply()
    assert not dialog.error.text()
    assert CameraService(vm.documents).camera(camera.id).background_color == "#345678"
    workspace.show_preview()
    qtbot.addWidget(workspace.preview)
    qtbot.wait(20)
    assert workspace.preview.viewport.camera_frame_only
    assert workspace.preview.viewport.pose.nodes[camera.id].world_matrix == pytest.approx(
        (1, 0, 0, 1, 0, 0)
    )
    image = workspace.preview.viewport.grab().toImage()
    center = workspace.preview.viewport.offset + QPointF(320, 180) * workspace.preview.viewport.zoom
    assert image.pixelColor(center.toPoint()).name() == "#345678"
    assert editor.viewport.camera_backdrop is not None
    vm.undo()
    assert CameraService(vm.documents).camera(camera.id).background_mode == "transparent"
    workspace.preview.close()


def test_camera_image_backdrop_and_projected_artwork_reach_preview_and_export(editor, qtbot):
    """Compare actual vector pixels after camera translation and preserve editing outside frame."""
    from PySide6.QtCore import QByteArray
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    from rigora.application_services.meshes import MeshService
    from rigora.application_services.rendering import svg_frame
    from rigora.application_services.scene_editing import SceneEditingService

    vm = editor.viewmodel
    doc = vm.documents
    cameras = CameraService(doc)
    key = doc.scene.cameras[0].id
    SceneEditingService(doc).flags((key,), locked=False)
    source = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40">'
        b'<rect width="40" height="40" fill="#ff0000"/></svg>'
    )
    mesh_service = MeshService(doc)
    mesh = mesh_service.import_image_bytes("Red.svg", source, 1, 1)
    part = str(mesh_service.mesh(mesh).object_id)
    SceneEditingService(doc).set_transform(part, x=120, y=30)
    cameras.update(
        key,
        match_scene=False,
        width=200.0,
        height=100.0,
        background_mode="color",
        background_color="#ffffff",
    )
    SceneEditingService(doc).set_transform(key, x=100, y=10)
    vm.changed.emit()
    data = svg_frame(doc, 0, width=200, height=100)
    image = QImage(200, 100, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    renderer = QSvgRenderer(QByteArray(data))
    renderer.render(painter)
    painter.end()
    assert image.pixelColor(30, 30).name() == "#ff0000"
    assert image.pixelColor(130, 30).name() == "#ffffff"
    cameras.update(
        key,
        background_mode="image",
        asset_id=mesh_service.mesh(mesh).asset_id,
        background_fit="cover",
    )
    vm.changed.emit()
    editor.camera_workspace.show_preview()
    qtbot.addWidget(editor.camera_workspace.preview)
    preview = editor.camera_workspace.preview.viewport
    qtbot.wait(20)
    output = preview.grab().toImage()
    center = preview.offset + QPointF(150, 50) * preview.zoom
    assert output.pixelColor(center.toPoint()).name() == "#ff0000"
    editor.camera_workspace.preview.close()


def test_camera_frame_highlight_follows_scrubbing_and_playback_without_changing_selection(
    editor, qtbot
):
    """Actual viewport pixels show one white output frame and dim other frames at each cut."""
    from rigora.application_services.scene_editing import SceneEditingService
    from rigora.engine.cameras import active_camera

    vm, viewport = editor.viewmodel, editor.viewport
    doc = vm.documents
    service = CameraService(doc)
    first = doc.scene.cameras[0].id
    second = service.add("Close shot")
    for key in (first, second):
        service.update(key, match_scene=False, width=200.0, height=120.0)
    SceneEditingService(doc).set_transform(second, x=90, y=50)
    service.activate(second, frame=20)
    vm.changed.emit()
    editor.scene_workspace.select_entries((first,))
    viewport.zoom, viewport.offset = 1, QPointF(50, 70)
    viewport.grid_visible = viewport.checker_visible = False
    original = doc.project
    history = len(doc.history.undo_stack)

    def brightness(x, y):
        """Sample the strongest border pixel in a device-independent viewport neighborhood."""
        image = viewport.grab().toImage()
        scale = image.devicePixelRatio()
        return max(
            image.pixelColor(round((x + dx) * scale), round((y + dy) * scale)).red()
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
        )

    vm.playback.seek(19)
    assert active_camera(viewport.pose).id == first
    assert brightness(100, 70) == 255
    assert brightness(300, 120) < 160
    vm.playback.seek(20)
    assert active_camera(viewport.pose).id == second
    assert brightness(100, 70) < 180
    assert brightness(300, 120) == 255
    assert vm.scene.selected == (first,)
    viewport.grab().save("build/camera-frame-highlights.png")

    vm.playback.seek(19)
    elapsed = [0.0]
    vm.playback.clock = lambda: elapsed[0]
    vm.playback.play_pause()
    vm.playback.timer.stop()
    elapsed[0] = 2 / doc.scene.settings.fps
    vm.playback.tick()
    assert vm.playback.session.playback.is_playing
    assert active_camera(viewport.pose).id == second
    assert brightness(100, 70) < 180 and brightness(300, 120) == 255
    vm.playback.pause()

    SceneEditingService(doc).set_transform(second, x=0, y=0)
    vm.changed.emit()
    vm.playback.seek(19)
    assert active_camera(viewport.pose).id == first
    assert brightness(100, 70) == 255
    doc.undo()
    assert doc.project == original and len(doc.history.undo_stack) == history
    assert vm.scene.selected == (first,)
