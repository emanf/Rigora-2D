"""Live property-strip edits and frame-grid/whole-track interactions through real Qt events."""

from uuid import uuid4

import pytest
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QContextMenuEvent,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPalette,
)
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QScrollArea, QToolButton, QWidget
from test_roots_soft_drag_gui import editor as root_editor

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.appearance import AppearanceService
from rigora.application_services.rigging import RigService
from rigora.domain.entities import Keyframe, Track
from rigora.presentation.widgets.key_canvas import KeyCanvas

pytestmark = pytest.mark.gui


@pytest.fixture
def editor(qtbot, tmp_path, monkeypatch):
    """Use the real document, painter and event routing with library-poster decoding isolated."""
    yield from root_editor.__wrapped__(qtbot, tmp_path, monkeypatch)


def shape(editor):
    """Select one vector image with deterministic dimensions and camera placement."""
    service = AppearanceService(editor.viewmodel.documents)
    mesh = service.create_shape("rectangle", 100, 150, 200, 120)
    key = str(service.mesh(mesh).object_id)
    editor.viewmodel.changed.emit()
    editor.scene_workspace.select_entries((key,))
    return key


def submit(field, value):
    """Commit a property value with the same signal emitted by Return or focus loss."""
    field.setValue(value)
    field.editingFinished.emit()


def test_toolbar_live_fields_ratio_visibility_flip_and_reset(editor, qtbot):
    vm = editor.viewmodel
    key = shape(editor)
    strip = editor.selection_properties
    assert strip.isEnabled()
    assert (strip.fields["x"].value(), strip.fields["y"].value()) == (200, 210)
    count = len(vm.documents.history.undo_stack)
    submit(strip.fields["width"], 400)
    assert strip.fields["height"].value() == 240
    assert len(vm.documents.history.undo_stack) == count + 1
    strip.ratio.setChecked(False)
    submit(strip.fields["height"], 180)
    assert strip.fields["width"].value() == 400
    submit(strip.fields["rotation"], 35)
    assert vm.documents.animation.pose.nodes[key].local.rotation == 35
    QTest.mouseClick(strip.horizontal, Qt.MouseButton.LeftButton)
    node = vm.documents.animation.pose.nodes[key]
    assert node.local.scale_x * node.local.scale_y < 0
    QTest.mouseClick(strip.visible, Qt.MouseButton.LeftButton)
    assert not vm.documents.animation.pose.nodes[key].visible
    QTest.mouseClick(strip.reset, Qt.MouseButton.LeftButton)
    assert strip.fields["width"].value() == 200
    assert strip.fields["height"].value() == 120
    assert strip.fields["rotation"].value() == 0
    assert strip.visible.isChecked()
    assert strip.fields["x"].value() == 960 and strip.fields["y"].value() == 540
    assert editor.main_tools.rect().contains(
        strip.reset.mapTo(editor.main_tools, strip.reset.rect().center())
    )
    editor.grab().save("build/selection-timeline-review.png")


def test_toolbar_follows_playback_drag_preview_and_tabs_without_authoring(editor):
    vm = editor.viewmodel
    key = shape(editor)
    strip = editor.selection_properties
    animation = AnimationEditingService(vm.documents)
    animation.key(key, "transform.x", 0, 100)
    animation.key(key, "transform.x", 20, 300)
    vm.changed.emit()
    count = len(vm.documents.history.undo_stack)
    vm.playback.seek(10)
    assert strip.fields["x"].value() == 300
    assert len(vm.documents.history.undo_stack) == count
    vm.scene.begin_preview()
    vm.scene.preview_transform(dx=60)
    assert strip.fields["x"].value() == 360
    assert len(vm.documents.history.undo_stack) == count
    vm.scene.cancel_preview()
    vm.changed.emit()
    assert strip.fields["x"].value() == 300
    vm.new_project()
    assert not strip.isEnabled()


def test_visibility_button_writes_real_hold_animation(editor):
    key = shape(editor)
    vm = editor.viewmodel
    vm.animation_editor.set_auto_key(True)
    vm.playback.seek(20)
    QTest.mouseClick(editor.selection_properties.visible, Qt.MouseButton.LeftButton)
    track = next(
        t for t in vm.animation_editor.service.timeline.tracks if t.property_path == "visibility"
    )
    assert [(k.frame, k.value) for k in track.keyframes] == [(0, 1), (20, 0)]
    assert vm.documents.animation.evaluate(19).nodes[key].visible
    assert not vm.documents.animation.evaluate(20).nodes[key].visible


@pytest.mark.parametrize("snap", (True, False))
def test_auto_keys_after_fractional_playback_match_clicked_frame_cells(editor, snap):
    """Automatic and inserted keys share frame centers; disabling Snap retains subframes."""
    key = shape(editor)
    vm, timeline = editor.viewmodel, editor.timeline
    timeline.snap.setChecked(snap)
    vm.animation_editor.set_auto_key(True)
    clock = [0.0]
    vm.playback.clock = lambda: clock[0]
    editor.command_actions["play"].trigger()
    clock[0] = 10.41 / vm.playback.session.scene.settings.fps
    vm.playback.tick()
    assert vm.documents.animation.pose.frame == pytest.approx(10.41)
    editor.command_actions["play"].trigger()
    expected = 10 if snap else pytest.approx(10.41)
    assert vm.documents.animation.pose.frame == expected
    assert not vm.playback.timer.isActive()
    submit(editor.selection_properties.fields["x"], 340)
    assert not vm.scene.error
    tracks = vm.animation_editor.service.timeline.tracks
    auto = next(t for t in tracks if t.owner_id == key and t.property_path == "transform.x")
    assert auto.keyframes[-1].frame == expected
    canvas = timeline.dope
    for track in tracks:
        for frame in track.keyframes:
            center = canvas.keys[track.id, frame.id].sceneBoundingRect().center().x()
            assert center == pytest.approx(frame.frame * canvas.pixels)
            if snap:
                assert center / canvas.pixels == round(center / canvas.pixels)

    # Inserting at the cursor uses the same frame policy as automatic authoring.
    lane = timeline._groups[key, "Transform"]
    lane.setSelected(True)
    vm.playback.seek(16.37)
    timeline.insert_key()
    assert not vm.animation_editor.error
    updated = next(t for t in vm.animation_editor.service.timeline.tracks if t.id == auto.id)
    assert updated.keyframes[-1].frame == (16 if snap else pytest.approx(16.37))

    def latest(owner, path):
        """Resolve actual recorded time rather than inferring it from the displayed cursor."""
        track = next(
            t
            for t in vm.animation_editor.service.timeline.tracks
            if t.owner_id == owner and t.property_path == path
        )
        return track.keyframes[-1].frame

    bone = RigService(vm.documents).create_bone((400, 300), (500, 300))
    vm.changed.emit()
    vm.rig.select(bone)
    vm.playback.seek(19.63)
    vm.rig.edit_pose({"transform.rotation": 25})
    assert not vm.rig.error
    assert latest(bone, "transform.rotation") == (20 if snap else pytest.approx(19.63))

    mesh = next(m for m in vm.documents.project.scenes[0].meshes if m.object_id == key)
    vm.mesh.select_mesh(mesh.id)
    vm.playback.seek(23.27)
    vm.mesh.key_pose()
    assert not vm.mesh.error
    assert latest(mesh.vertices[0].id, "x") == (23 if snap else pytest.approx(23.27))

    vm.playback.seek(26.7)
    vm.scene.run(lambda service: service.set_transform(key, x=390))
    assert not vm.scene.error
    assert latest(key, "transform.x") == (27 if snap else pytest.approx(26.7))


def test_scene_drag_stops_fractional_playback_before_automatic_key(editor, qtbot):
    """A direct object gesture captures its baseline on a whole frame, including during play."""
    from test_roots_soft_drag_gui import drag

    key = shape(editor)
    vm, viewport = editor.viewmodel, editor.viewport
    qtbot.waitUntil(
        lambda: all(
            mesh.asset_id in viewport.artwork.images
            for mesh in vm.documents.animation.pose.meshes.values()
        ),
        timeout=5000,
    )
    vm.animation_editor.set_auto_key(True)
    viewport.zoom, viewport.offset = 1, QPointF(20, 30)
    clock = [0.0]
    vm.playback.clock = lambda: clock[0]
    vm.playback.play_pause()
    clock[0] = 12.69 / vm.playback.session.scene.settings.fps
    vm.playback.tick()
    assert vm.documents.animation.pose.frame == pytest.approx(12.69)
    rect = editor.scene_workspace.transform_bounds()
    start = rect.topLeft() + QPointF(rect.width() * 0.3, rect.height() * 0.3)
    drag(viewport, start, start + QPointF(35, 20))
    assert not vm.scene.error
    assert vm.documents.animation.pose.frame == 13
    assert not vm.playback.timer.isActive()
    assert vm.documents.animation.pose.nodes[key].local.x == pytest.approx(135)
    assert all(
        frame.frame in (0, 13)
        for track in vm.animation_editor.service.timeline.tracks
        for frame in track.keyframes
    )


def test_flat_property_rows_inert_headers_hover_ticks_seek_and_zoom(editor, qtbot):
    vm = editor.viewmodel
    key = shape(editor)
    animation = AnimationEditingService(vm.documents)
    animation.add_channels(
        tuple(
            (key, p)
            for p in ("transform.x", "transform.y", "transform.rotation", "visibility", "opacity")
        )
    )
    vm.changed.emit()
    timeline, canvas = editor.timeline, editor.timeline.dope
    owner = timeline.tracks.topLevelItem(0)
    assert not owner.flags() & Qt.ItemFlag.ItemIsSelectable
    assert [owner.child(i).text(0) for i in range(owner.childCount())] == [
        "TRANSFORM",
        "OPACITY",
        "VISIBILITY",
    ]
    assert all(owner.child(i).childCount() == 0 for i in range(owner.childCount()))
    assert 0 not in canvas.summary_rows
    lane = timeline._groups[key, "Transform"]
    y = timeline.tracks.visualItemRect(lane).center().y()
    point = canvas.mapFromScene(QPointF(6 * canvas.pixels, y))
    QApplication.sendEvent(
        canvas.viewport(),
        QMouseEvent(
            QMouseEvent.Type.MouseMove,
            QPointF(point),
            QPointF(point),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    assert canvas._hover_slot is not None and canvas._hover_slot.x() == 6 * canvas.pixels
    QTest.mouseClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert vm.playback.session.pose.frame == 6
    assert not any(t.keyframes for t in animation.timeline.tracks)
    canvas.context_requested.disconnect(timeline.context_menu)
    menu = []
    canvas.context_requested.connect(menu.append)
    other = canvas.mapFromScene(QPointF(17 * canvas.pixels, y))
    event = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse, other, canvas.viewport().mapToGlobal(other)
    )
    QApplication.sendEvent(canvas.viewport(), event)
    assert menu and vm.playback.session.pose.frame == 17
    before = canvas.pixels
    zoom = next(
        b for b in timeline.findChildren(QToolButton) if b.accessibleName() == "Zoom in timeline"
    )
    QTest.mouseClick(zoom, Qt.MouseButton.LeftButton)
    assert canvas.pixels > before and vm.playback.session.pose.frame == 17
    assert len(canvas.summary_rows) == 1
    image = canvas.viewport().grab().toImage()

    # Only the tenth frame's cell is darker; neighboring ten-frame intervals match.
    def cell_color(frame):
        x = canvas.mapFromScene(QPointF(frame * canvas.pixels, 0)).x()
        return image.pixelColor(x, y + 7)

    assert cell_color(5) == cell_color(15)
    assert cell_color(10) == cell_color(20)
    assert cell_color(10).lightness() < cell_color(15).lightness()
    animation.add_channels(
        tuple((t.owner_id, t.property_path) for t in animation.timeline.tracks), frame=0
    )
    animation.add_channels(
        tuple((t.owner_id, t.property_path) for t in animation.timeline.tracks), frame=30
    )
    vm.changed.emit()
    qtbot.waitUntil(lambda: bool(editor.viewport.artwork.vectors), timeout=10000)
    editor.grab().save("build/selection-timeline-grid-review.png")
    timeline.open_picker()
    assert [
        timeline.picker.tree.topLevelItem(i).text(0)
        for i in range(timeline.picker.tree.topLevelItemCount())
    ][:3] == ["Transform", "Visible", "Opacity"]


def test_track_shortcuts_remove_whole_lanes_and_canvas_delete_only_keys(editor, qtbot):
    key = shape(editor)
    vm = editor.viewmodel
    animation = AnimationEditingService(vm.documents)
    channels = ((key, "transform.x"), (key, "transform.y"))
    animation.add_channels(channels, frame=4)
    animation.add_channels(channels, frame=14)
    vm.changed.emit()
    timeline, canvas = editor.timeline, editor.timeline.dope
    lane = timeline._groups[key, "Transform"]
    lane.setSelected(True)
    timeline.tracks.setFocus()
    QTest.keyClick(timeline.tracks, Qt.Key.Key_X, Qt.KeyboardModifier.ControlModifier)
    assert not animation.timeline.tracks and not vm.animation_editor.error
    vm.playback.seek(20)
    QTest.keyClick(timeline.tracks, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert len(animation.timeline.tracks) == 2

    assert [k.frame for k in animation.timeline.tracks[0].keyframes] == [20, 30]
    vm.animation_editor.select((t.id, t.keyframes[0].id) for t in animation.timeline.tracks)
    canvas.setFocus()
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    assert len(animation.timeline.tracks) == 2
    assert all(len(t.keyframes) == 1 for t in animation.timeline.tracks)
    timeline._groups[key, "Transform"].setSelected(True)
    timeline.tracks.setFocus()
    QTest.keyClick(timeline.tracks, Qt.Key.Key_Delete)
    assert not animation.timeline.tracks
    vm.undo()
    assert len(animation.timeline.tracks) == 2


def test_frame_cells_center_keys_and_picking_at_multiple_zoom_levels(qtbot):
    """Painted borders surround key centers; both halves of each cell pick the same frame."""
    parent = QWidget()
    qtbot.addWidget(parent)
    canvas = KeyCanvas(parent)
    canvas.resize(720, 140)
    palette = canvas.palette()
    palette.setColor(QPalette.ColorRole.Base, QColor(80, 80, 80))
    palette.setColor(canvas.foregroundRole(), QColor(240, 240, 240))
    canvas.setPalette(palette)
    track = Track(
        owner_id=str(uuid4()),
        property_path="transform.x",
        keyframes=tuple(Keyframe(frame=f, value=0) for f in (0, 2, 10)),
    )
    for pixels in (8, 24, 160, 200):
        canvas.pixels = pixels
        canvas.rebuild((track,), [track.id], (), (), 20)
        canvas.horizontalScrollBar().setValue(canvas.horizontalScrollBar().minimum())
        gutter = round(-canvas.sceneRect().left())
        image = QImage(24 * pixels + 2 * gutter, 24, QImage.Format.Format_RGB32)
        painter = QPainter(image)
        painter.translate(gutter, 0)
        canvas.drawBackground(painter, QRectF(-gutter, 0, image.width(), 24))
        painter.end()

        for key in track.keyframes:
            center = canvas.keys[track.id, key.id].sceneBoundingRect().center().x()
            assert center == key.frame * pixels
            x = round(gutter + center)
            fill = image.pixelColor(x, 12)
            assert image.pixelColor(x - pixels // 4, 12) == fill
            assert image.pixelColor(x + pixels // 4, 12) == fill
            assert image.pixelColor(x - pixels // 2, 12) != fill
            assert image.pixelColor(x + pixels // 2, 12) != fill
            for offset in (-0.35, 0, 0.35):
                point = canvas.mapFromScene(QPointF((key.frame + offset) * pixels, 12))
                assert canvas.frame_at(point) == key.frame
        assert (
            image.pixelColor(gutter + 10 * pixels, 12).lightness()
            < image.pixelColor(gutter + 11 * pixels, 12).lightness()
        )
        assert canvas.mapFromScene(QPointF(-pixels / 2, 12)).x() >= 8


def test_frame_zero_is_fully_visible_and_easy_to_key_after_rebuild_and_zoom(editor, qtbot):
    """The first key and ruler handle have a stable gutter without changing stored time."""
    key = shape(editor)
    vm = editor.viewmodel
    animation = AnimationEditingService(vm.documents)
    animation.add_channels(((key, "transform.x"),))
    vm.changed.emit()
    canvas = editor.timeline.dope
    track = animation.timeline.tracks[0]
    y = canvas.rows.index(track.id) * 24 + 12
    point = canvas.mapFromScene(QPointF(0, y))
    assert point.x() >= 12
    assert canvas.frame_at(point) == 0
    QTest.mouseDClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert not vm.animation_editor.error
    assert [k.frame for k in animation.timeline.tracks[0].keyframes] == [0]

    for factor in (0.5, 4, 0.5):
        canvas.zoom(factor)
        canvas.horizontalScrollBar().setValue(canvas.horizontalScrollBar().minimum())
        canvas.rebuild(canvas.tracks, canvas.rows, canvas.markers, (), canvas.end)
        point = canvas.mapFromScene(QPointF(0, y))
        item = next(iter(canvas.keys.values()))
        bounds = canvas.mapFromScene(item.sceneBoundingRect()).boundingRect()
        assert canvas.viewport().rect().contains(bounds)
        assert point.x() >= 12
        vm.playback.seek(20)
        QTest.mouseClick(canvas.ruler, Qt.MouseButton.LeftButton, pos=QPoint(point.x(), 10))
        assert vm.playback.session.pose.frame == 0
        QTest.mouseClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=point - QPoint(3, 0))
        assert vm.animation_editor.selected
        assert all(k.frame == 0 for k in animation.timeline.tracks[0].keyframes)


@pytest.mark.parametrize("object_editor", [False, True])
def test_ruler_focus_steps_frames_with_arrow_keys_without_editing_keys(
    editor, qtbot, object_editor
):
    """Scene/Object rulers own arrow stepping after a click; fields keep caret navigation."""
    key = shape(editor)
    if object_editor:
        editor.object_edit.enter(key)
        assert editor.object_edit.active
    vm, timeline = editor.viewmodel, editor.timeline
    AnimationEditingService(vm.documents).add_channels(((key, "transform.x"),))
    vm.changed.emit()
    canvas, ruler = timeline.dope, timeline.dope.ruler
    before, steps = vm.documents.project, len(vm.documents.history.undo_stack)
    for button in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
        timeline.frame.setFocus()
        point = canvas.mapFromScene(QPointF(12 * canvas.pixels, 0))
        QTest.mouseClick(ruler, button, pos=QPoint(point.x(), 10))
        assert ruler.hasFocus() and vm.documents.animation.pose.frame == 12
        QTest.keyClick(ruler, Qt.Key.Key_Right)
        assert vm.documents.animation.pose.frame == 13 and timeline.frame.value() == 13
        QTest.keyClick(ruler, Qt.Key.Key_Left)
        assert vm.documents.animation.pose.frame == 12
        for _ in range(3):
            QApplication.sendEvent(
                ruler,
                QKeyEvent(
                    QKeyEvent.Type.KeyPress,
                    Qt.Key.Key_Right,
                    Qt.KeyboardModifier.NoModifier,
                    "",
                    True,
                    1,
                ),
            )
        assert vm.documents.animation.pose.frame == 15
        QTest.keyClick(ruler, Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier)
        assert vm.documents.animation.pose.frame == 15
    vm.playback.seek_start()
    QTest.keyClick(ruler, Qt.Key.Key_Left)
    assert vm.documents.animation.pose.frame == vm.playback.session.playback.range.start
    vm.playback.seek_end()
    QTest.keyClick(ruler, Qt.Key.Key_Right)
    assert vm.documents.animation.pose.frame == vm.playback.session.playback.range.end
    vm.playback.seek(12)
    canvas.setFocus()
    QTest.keyClick(canvas, Qt.Key.Key_Right)
    assert vm.documents.animation.pose.frame == 13
    field = timeline.frame.lineEdit()
    field.setFocus()
    field.setCursorPosition(1)
    QTest.keyClick(field, Qt.Key.Key_Right)
    assert field.cursorPosition() == 2 and vm.documents.animation.pose.frame == 13
    assert vm.documents.project is before and len(vm.documents.history.undo_stack) == steps


def test_property_groups_wrap_on_narrow_windows_without_losing_controls(editor, qtbot):
    """Related fields remain intact and visible on extra rows without a scrolling strip."""
    shape(editor)
    editor.resize(1800, 1000)
    qtbot.wait(10)
    assert not editor.main_tools.findChildren(QScrollArea)
    strip = editor.selection_properties
    labels = {
        label.text().rstrip(":"): label
        for group in strip.groups.values()
        for label in group.findChildren(QLabel)
    }
    for name in ("X", "Y", "W", "H"):
        label = labels[name]
        assert label.width() <= label.sizeHint().width() + 1
        field = strip.fields[{"X": "x", "Y": "y", "W": "width", "H": "height"}[name]]
        assert 0 <= field.x() - label.geometry().right() <= 6
    assert 8 <= labels["Y"].x() - strip.fields["x"].geometry().right() <= 16
    editor.resize(1200, 850)
    qtbot.wait(10)
    assert editor.width() <= 1200
    reset = editor.selection_properties.reset
    point = reset.mapTo(editor.main_tools, reset.rect().center())
    assert editor.main_tools.rect().contains(point) and reset.isVisible()
    assert len({g.y() for g in editor.main_tools.groups.values()}) > 1


def test_main_titlebar_keeps_logo_and_menus_without_brand_text(editor):
    """Removing the wordmark leaves the shared caption's controls and application icon intact."""
    assert "RIGORA" not in [label.text() for label in editor.titlebar.findChildren(QLabel)]
    assert editor.titlebar.logo.isVisible() and not editor.titlebar.logo.icon().isNull()
    assert editor.menu_bar.x() <= 60


def test_keyed_object_can_move_rotate_and_scale_with_auto_key_off(editor, qtbot):
    """All three real canvas gestures update the current keyed pose and retain earlier frames."""
    from test_roots_soft_drag_gui import drag, pointer

    from rigora.presentation import transform_gizmo

    key = shape(editor)
    vm, viewport, work = editor.viewmodel, editor.viewport, editor.scene_workspace
    qtbot.waitUntil(
        lambda: all(
            mesh.asset_id in viewport.artwork.images
            for mesh in vm.documents.animation.pose.meshes.values()
        ),
        timeout=5000,
    )
    editor.selection_properties.ratio.setChecked(True)
    animation = AnimationEditingService(vm.documents)
    channels = tuple((key, f"transform.{p}") for p in ("x", "y", "rotation", "scale_x", "scale_y"))
    animation.add_channels(channels, frame=0)
    animation.add_channels(channels, frame=20)
    vm.changed.emit()
    vm.playback.seek(10)
    assert not vm.scene.auto_key and not vm.animation_editor.auto_key
    original = vm.documents.animation.evaluate(0).nodes[key]
    viewport.zoom, viewport.offset = 1, QPointF(20, 30)
    count = len(vm.documents.history.undo_stack)
    rect = work.transform_bounds()
    start = rect.topLeft() + QPointF(rect.width() * 0.25, rect.height() * 0.3)
    before = vm.documents.animation.pose.nodes[key]
    pointer(viewport, QMouseEvent.Type.MouseButtonPress, start)
    pointer(viewport, QMouseEvent.Type.MouseMove, start + QPointF(35, 20))
    assert vm.scene.preview.nodes[key].local.x == pytest.approx(before.local.x + 35)
    assert len(vm.documents.history.undo_stack) == count
    pointer(viewport, QMouseEvent.Type.MouseButtonRelease, start + QPointF(35, 20))
    moved = vm.documents.animation.pose.nodes[key]
    assert moved.local.x == pytest.approx(before.local.x + 35)
    assert moved.local.y == pytest.approx(before.local.y + 20)
    rect, mapping, _ = work.transform_frame()
    pivot = work.pivot_point(work.transform_frame())
    start = transform_gizmo.handles(rect, mapping)[8]
    vector = start - pivot
    drag(viewport, start, pivot + QPointF(-vector.y(), vector.x()))
    assert vm.documents.animation.pose.nodes[key].local.rotation == pytest.approx(90)
    rect, mapping, _ = work.transform_frame()
    local = transform_gizmo.handles(rect)[3]
    drag(viewport, mapping.map(local), mapping.map(local + QPointF(40, 15)))
    scaled = vm.documents.animation.pose.nodes[key]
    assert scaled.local.scale_x == pytest.approx(1.2)
    assert scaled.local.scale_y == pytest.approx(1.2)
    assert not vm.scene.error
    assert len(vm.documents.history.undo_stack) == count + 3
    assert vm.documents.animation.evaluate(0).nodes[key] == original
    assert not vm.scene.auto_key and not vm.animation_editor.auto_key
    vm.undo()
    assert vm.documents.animation.pose.nodes[key].local.scale_x == pytest.approx(1)
