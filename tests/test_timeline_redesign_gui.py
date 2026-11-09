"""Real grouped timeline scrolling, channel drops, aggregate key drags and compact layout."""

import json
from dataclasses import replace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QTreeWidgetItemIterator

from rigora.app.application import ApplicationInfo
from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.appearance import AppearanceService
from rigora.application_services.commands import ScenePatch
from rigora.application_services.deformation import DeformationPreset, DeformationService
from rigora.application_services.meshes import MeshService
from rigora.application_services.rigging import RigService
from rigora.application_services.scene_editing import SceneEditingService
from rigora.domain.entities import (
    AnimationClip,
    Bone,
    Character,
    Keyframe,
    Skeleton,
    Timeline,
    Track,
)
from rigora.engine.transition_curves import TransitionCurve, curve_presets
from rigora.infrastructure.preferences import PreferencesStore
from rigora.presentation.viewmodels.main_window import MainWindowViewModel
from rigora.presentation.views.main_window import MainWindow
from rigora.presentation.widgets.curve_editor import CURVE_MIME
from rigora.presentation.widgets.timeline_tracks import CHANNEL_MIME, decode_channels, row_channels
from rigora.resources import asset_path

pytestmark = pytest.mark.gui


@pytest.fixture
def window(qtbot, tmp_path):
    """Own an isolated native editor; teardown never prompts about disposable authored data."""
    vm = MainWindowViewModel(ApplicationInfo(), preferences=PreferencesStore(tmp_path / "ui.json"))
    widget = MainWindow(vm)
    widget.confirm_discard = lambda: True
    qtbot.addWidget(widget)
    widget.resize(1500, 950)
    widget.show()
    vm.new_project()
    widget.resizeDocks([widget.docks["timeline"]], [380], Qt.Orientation.Vertical)
    return widget


def held_move(widget, point):
    """Deliver a held-button move independent of the physical desktop cursor."""
    QApplication.sendEvent(
        widget,
        QMouseEvent(
            QMouseEvent.Type.MouseMove,
            QPointF(point),
            widget.mapToGlobal(point),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )


def test_object_picker_inline_add_and_dense_mesh_property_hide_internal_channels(window, qtbot):
    """Whole properties add once from scene objects, including meshes beyond 512 scalar channels."""
    vm = window.viewmodel
    meshes = MeshService(vm.documents)
    mesh_id = meshes.import_image(asset_path("examples/prop.svg"), 16, 16)
    body = meshes.mesh(mesh_id)
    meshes.set_flags(mesh_id, {body.vertices[0].id}, protected=True)
    other = meshes.import_image(asset_path("examples/torso.svg"), 2, 2)
    background = meshes.mesh(other).object_id
    scene = SceneEditingService(vm.documents)
    scene.rename(body.object_id, "Character body")
    scene.rename(background, "Background")
    folder = scene.group((body.object_id,), "Character parts")
    look = AppearanceService(vm.documents).ensure(mesh_id)
    stage = DeformationService(vm.documents).add(mesh_id, DeformationPreset("FFD", "ffd", {}))
    vm.changed.emit()
    window.object_edit.enter(folder)
    animation = AnimationEditingService(vm.documents)
    animation.add_channels(((body.object_id, "transform.x"),))
    vm.changed.emit()
    vm.scene.select((background,))
    window.timeline.open_picker()
    picker = window.timeline.picker
    picker.objects.setCurrentItem(picker.object_rows[body.object_id])
    assert picker.object_rows[body.object_id].parent() is picker.object_rows[folder]
    assert look not in picker.object_rows and stage not in picker.object_rows
    assert all(vertex.id not in picker.object_rows for vertex in body.vertices)

    def property_row(label):
        return next(
            picker.tree.topLevelItem(i)
            for i in range(picker.tree.topLevelItemCount())
            if picker.tree.topLevelItem(i).text(0) == label
        )

    assert [picker.tree.topLevelItem(i).text(0) for i in range(4)] == [
        "Transform",
        "Visible",
        "Opacity",
        "Mesh Deformation",
    ]
    assert property_row("Transform").text(1) == "Partly added"
    assert property_row("Color") and property_row("Outline")
    ffd = property_row("Deformation · FFD")
    assert any(path.startswith("parameters.controls.") for _, path in row_channels(ffd))
    assert not any(path.startswith("parameters.bounds") for _, path in row_channels(ffd))
    assert all(
        picker.tree.topLevelItem(i).childCount() == 0
        for i in range(picker.tree.topLevelItemCount())
    )
    count = len(vm.documents.history.undo_stack)
    QTest.mouseClick(
        picker.tree.itemWidget(property_row("Transform"), 2), Qt.MouseButton.LeftButton
    )
    assert not vm.animation_editor.error
    assert len(animation.timeline.tracks) == 7
    assert len(vm.documents.history.undo_stack) == count + 1
    assert picker.objects.currentItem().data(0, Qt.ItemDataRole.UserRole) == body.object_id
    assert property_row("Transform").text(1) == "Added"
    assert not picker.tree.itemWidget(property_row("Transform"), 2).isEnabled()

    deformation = property_row("Mesh Deformation")
    channels = row_channels(deformation)
    assert len(channels) == (len(body.vertices) - 1) * 2 > 512
    mime = picker.tree.mimeData((deformation,))
    assert decode_channels(mime, vm.documents.session_id) == channels
    QTest.mouseClick(picker.tree.itemWidget(deformation, 2), Qt.MouseButton.LeftButton)
    assert not vm.animation_editor.error
    assert len(animation.timeline.tracks) == 7 + len(channels)
    assert not any(track.keyframes for track in animation.timeline.tracks)
    lane = window.timeline._groups["", "Mesh deformation"]
    assert len(window.timeline.row_tracks(lane)) == len(channels)
    window.timeline.drop_channels(mime, 12)
    assert not vm.animation_editor.error
    assert all(
        [(key.frame) for key in track.keyframes] == [12]
        for track in animation.timeline.tracks
        if track.owner_id in {vertex.id for vertex in body.vertices}
    )
    picker.grab().save("build/simple-track-picker-review.png")
    vm.undo()
    vm.undo()
    assert len(animation.timeline.tracks) == 7
    assert property_row("Mesh Deformation").text(1) == "Available"
    assert background not in picker.object_rows
    window.object_edit.exit()
    picker.refresh()
    picker.search.setText("background")
    assert picker.object_rows[body.object_id].isHidden()
    assert not picker.object_rows[background].isHidden()
    assert picker.tree.topLevelItemCount() == 0 and not picker.add_button.isEnabled()
    picker.objects.setCurrentItem(picker.object_rows[background])
    assert property_row("Transform").text(1) == "Available"
    vm.new_project()
    assert set(picker.records) == {camera.id for camera in vm.documents.scene.cameras}
    assert picker.objects.topLevelItemCount() == 1 and picker.tree.topLevelItemCount() == 0
    assert not picker.add_button.isEnabled()


def test_color_and_deformation_choices_remain_single_timeline_properties(window):
    """Color and each built-in effect add complete, flat property lanes."""
    vm = window.viewmodel
    looks = AppearanceService(vm.documents)
    mesh = looks.create_shape("ellipse", 100, 100, 100, 100)
    look = looks.ensure(mesh)
    effect = looks.add(mesh, DeformationPreset("Flexible shape", "ffd", {}))
    vm.changed.emit()
    window.object_edit.enter(str(looks.mesh(mesh).object_id))
    vm.scene.select((looks.mesh(mesh).object_id,))
    window.timeline.open_picker()
    picker = window.timeline.picker
    for label, _owner, lane in (
        ("Color", look, "Color"),
        ("Deformation · Flexible shape", effect, "Deformation"),
    ):
        row = next(
            picker.tree.topLevelItem(i)
            for i in range(picker.tree.topLevelItemCount())
            if picker.tree.topLevelItem(i).text(0) == label
        )
        members = row_channels(row)
        QTest.mouseClick(picker.tree.itemWidget(row, 2), Qt.MouseButton.LeftButton)
        assert not vm.animation_editor.error
        timeline_row = window.timeline._groups["", lane]
        assert len(window.timeline.row_tracks(timeline_row)) == len(members)
        assert timeline_row.childCount() == 0


def test_scroll_replay_keeps_ruler_separate_and_track_rows_aligned(window, qtbot):
    """Replay fractional row scrolling and verify fixed-header pixels and actual lane geometry."""
    vm = window.viewmodel
    doc = vm.documents
    scene = doc.project.scenes[0]
    bones = tuple(Bone(name=f"Joint {i:02}") for i in range(35))
    data = Timeline(
        tracks=tuple(
            Track(
                owner_id=b.id,
                property_path="transform.rotation",
                keyframes=(Keyframe(frame=4, value=0), Keyframe(frame=40, value=30)),
            )
            for b in bones
        )
    )
    clip = AnimationClip(timeline_id=data.id, out_frame=100)
    rig = Skeleton(bones=bones)
    actor = Character(name="Test rig", skeleton_id=rig.id)
    doc.execute(
        ScenePatch(
            "Many timeline rows",
            scene.id,
            {"skeletons": (), "characters": (), "timelines": (), "clips": ()},
            {"skeletons": (rig,), "characters": (actor,), "timelines": (data,), "clips": (clip,)},
        )
    )
    vm.changed.emit()
    window.object_edit.enter(actor.id)
    window.timeline.group_properties.setChecked(False)
    qtbot.wait(20)
    timeline = window.timeline
    canvas = timeline.dope
    assert canvas.ruler.geometry().bottom() < canvas.viewport().geometry().top()
    assert canvas.ruler.width() == canvas.viewport().width()
    assert timeline.pages.geometry().bottom() >= timeline.height() - 2
    assert (
        not timeline.key_controls.isVisible() and timeline.key_controls.window() is timeline.details
    )
    header = canvas.ruler.grab().toImage()
    assert canvas.verticalScrollBar().maximum() > 200
    assert canvas.verticalScrollBar().maximum() == timeline.tracks.verticalScrollBar().maximum()
    rows = {}
    iterator = QTreeWidgetItemIterator(timeline.tracks)
    while item := iterator.value():
        if not item.childCount():
            rows.update((key, item) for key in timeline.row_tracks(item))
        iterator += 1
    for value in (17, 29, canvas.verticalScrollBar().maximum(), 53, 0, 137, 0):
        canvas.verticalScrollBar().setValue(value)
        qtbot.wait(2)
        assert timeline.tracks.verticalScrollBar().value() == value
        visible = 0
        for track in data.tracks:
            row = rows[track.id]
            rect = timeline.tracks.visualItemRect(row)
            if rect.intersects(timeline.tracks.viewport().rect()):
                visible += 1
                ref = (track.id, track.keyframes[0].id)
                y = canvas.mapFromScene(canvas.keys[ref].pos()).y()
                assert abs(rect.center().y() - y) <= 1
        assert visible
        assert canvas.ruler.grab().toImage() == header
    vm.documents.animation.seek(0)
    vm.scene.select((bones[0].id,))
    timeline.only_selected.setChecked(True)
    assert set(canvas.keys) == {(data.tracks[0].id, k.id) for k in data.tracks[0].keyframes}
    timeline.search.setText("no matching channel")
    assert not canvas.keys
    timeline.search.clear()
    vm.scene.select((bones[1].id,))
    assert set(canvas.keys) == {(data.tracks[1].id, k.id) for k in data.tracks[1].keyframes}
    vm.scene.select((doc.project.scenes[0].skeletons[0].id,))
    assert len(canvas.keys) == 70


def test_picker_add_group_double_click_and_channel_drop_are_real_undoable_edits(window, qtbot):
    """Add a compound Transform lane, capture all components, and drag it to a frame."""
    vm = window.viewmodel
    bone = RigService(vm.documents).create_bone((50, 30), (150, 30))
    vm.changed.emit()
    vm.scene.select((bone,))
    timeline = window.timeline
    timeline.group_properties.setChecked(False)
    timeline.open_picker()
    picker = timeline.picker
    assert picker.objects.currentItem().data(0, Qt.ItemDataRole.UserRole) == bone
    scale = next(
        picker.tree.topLevelItem(i)
        for i in range(picker.tree.topLevelItemCount())
        if picker.tree.topLevelItem(i).text(0) == "Transform"
    )
    before = len(vm.documents.history.undo_stack)
    picker.add((scale,))
    assert len(vm.documents.history.undo_stack) == before + 1
    service = vm.animation_editor.service
    assert len(service.timeline.tracks) == 7 and not any(
        t.keyframes for t in service.timeline.tracks
    )
    group = timeline._groups[bone, "Transform"]
    qtbot.wait(10)
    rect = timeline.tracks.visualItemRect(group)
    QTest.mouseDClick(
        timeline.dope.viewport(),
        Qt.MouseButton.LeftButton,
        pos=timeline.dope.mapFromScene(QPointF(12 * timeline.dope.pixels, rect.center().y())),
    )
    assert all(t.keyframes[0].frame == 12 for t in service.timeline.tracks)
    assert len(vm.documents.history.undo_stack) == before + 2
    vm.undo()
    assert not any(t.keyframes for t in service.timeline.tracks)
    position = next(
        picker.tree.topLevelItem(i)
        for i in range(picker.tree.topLevelItemCount())
        if picker.tree.topLevelItem(i).text(0) == "Transform"
    )
    mime = picker.tree.mimeData((position,))
    target = timeline.dope.viewport()
    point = timeline.dope.mapFromScene(QPointF(18 * timeline.dope.pixels, 60))
    baseline = vm.documents.project
    enter = QDragEnterEvent(
        point,
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(target, enter)
    move = QDragMoveEvent(
        point,
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(target, move)
    assert enter.isAccepted() and vm.documents.project is baseline
    assert timeline.dope._drop_position is not None
    drop = QDropEvent(
        QPointF(point),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(target, drop)
    assert drop.isAccepted() and timeline.dope._drop_position is None
    position_tracks = [
        t for t in service.timeline.tracks if t.property_path in ("transform.x", "transform.y")
    ]
    assert [(t.keyframes[0].frame, t.keyframes[0].value) for t in position_tracks] == [
        (18, 50),
        (18, 30),
    ]
    assert len(service.timeline.tracks) == 7
    assert len(vm.documents.history.undo_stack) == before + 2
    stale = QMimeData()
    stale.setData(
        CHANNEL_MIME,
        json.dumps({"session": "other", "channels": [[bone, "transform.rotation"]]}).encode(),
    )
    baseline = vm.documents.project
    timeline.drop_channels(stale, 20)
    assert vm.documents.project is baseline and "active project" in vm.animation_editor.error
    vm.scene.select(())
    timeline.inspect_owner(timeline.tracks.topLevelItem(0), 0)
    assert vm.scene.selected == ()
    timeline.inspect_owner(timeline._groups[bone, "Transform"], 0)
    assert vm.scene.selected == (bone,) and window.viewport.selected_nodes == (bone,)


@pytest.mark.parametrize("double_click_drag", [False, True])
@pytest.mark.parametrize("snap", [False, True])
def test_double_clicked_rotation_key_stays_in_lane_and_commits_time(
    window, qtbot, double_click_drag, snap
):
    """New Rotation keys retain their lane during ordinary and double-click-held drags."""
    vm = window.viewmodel
    bone = RigService(vm.documents).create_bone((20, 30), (120, 30))
    service = AnimationEditingService(vm.documents)
    service.add_channels(((bone, "transform.rotation"),))
    vm.changed.emit()
    qtbot.wait(10)
    canvas = window.timeline.dope
    track = service.timeline.tracks[0]
    start = canvas.mapFromScene(QPointF(12 * canvas.pixels, 12 + canvas.rows.index(track.id) * 24))
    QTest.mouseDClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
    ref = track.id, service.timeline.tracks[0].keyframes[0].id
    original = QPointF(canvas.keys[ref].pos())
    canvas.snap = snap
    before = len(vm.documents.history.undo_stack)
    press = QTest.mouseDClick if double_click_drag else QTest.mousePress
    press(canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
    target = start + QPoint(49, 35)
    held_move(canvas.viewport(), target)
    assert canvas.keys[ref].pos().y() == original.y()
    frame = 18 if snap else 18.125
    assert canvas.keys[ref].pos().x() == frame * canvas.pixels
    assert len(vm.documents.history.undo_stack) == before
    QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, pos=target)
    key = service.timeline.tracks[0].keyframes[0]
    assert key.frame == frame and key.value == 0
    assert len(vm.documents.history.undo_stack) == before + 1
    vm.undo()
    assert service.timeline.tracks[0].keyframes[0].frame == 12
    assert canvas.keys[ref].pos() == original


def test_insert_during_double_click_discards_deleted_drag_items(window, qtbot):
    """Inserting beside an existing key ends its old graphics gesture before rebuilding."""
    vm = window.viewmodel
    bone = RigService(vm.documents).create_bone((20, 30), (120, 30))
    service = AnimationEditingService(vm.documents)
    service.add_channels(((bone, "transform.rotation"),), frame=4)
    vm.changed.emit()
    qtbot.wait(10)
    canvas = window.timeline.dope
    track = service.timeline.tracks[0]
    start = canvas.mapFromScene(QPointF(12 * canvas.pixels, 12 + canvas.rows.index(track.id) * 24))
    before = len(vm.documents.history.undo_stack)
    QTest.mouseClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseDClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
    held_move(canvas.viewport(), start + QPoint(49, 35))
    QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, pos=start + QPoint(49, 35))
    assert [k.frame for k in service.timeline.tracks[0].keyframes] == [4, 12]
    assert len(vm.documents.history.undo_stack) == before + 1
    assert not canvas._pressed
    vm.undo()
    assert [k.frame for k in service.timeline.tracks[0].keyframes] == [4]


def test_collapsed_group_drags_both_scale_axes_as_one_command(window, qtbot):
    """Aggregate keys move horizontally together and preserve spacing and undo ownership."""
    vm = window.viewmodel
    bone = RigService(vm.documents).create_bone((20, 30), (120, 30))
    service = AnimationEditingService(vm.documents)
    channels = ((bone, "transform.scale_x"), (bone, "transform.scale_y"))
    service.add_channels(channels, frame=0)
    service.add_channels(channels, frame=10)
    vm.changed.emit()
    qtbot.wait(10)
    canvas = window.timeline.dope
    refs = tuple((t.id, t.keyframes[0].id) for t in service.timeline.tracks)
    assert canvas.keys[refs[0]] is canvas.keys[refs[1]]
    start = canvas.mapFromScene(canvas.keys[refs[0]].pos())
    before = len(vm.documents.history.undo_stack)
    QTest.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
    held_move(canvas.viewport(), start + QPoint(48, 35))
    assert len(vm.documents.history.undo_stack) == before
    assert canvas.keys[refs[0]].pos().y() == canvas.mapToScene(start).y()
    QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, pos=start + QPoint(48, 35))
    assert not vm.animation_editor.error
    assert [[k.frame for k in t.keyframes] for t in service.timeline.tracks] == [[6, 10], [6, 10]]
    assert len(vm.documents.history.undo_stack) == before + 1
    vm.undo()
    assert [[k.frame for k in t.keyframes] for t in service.timeline.tracks] == [[0, 10], [0, 10]]
    window.timeline.show_details()
    qtbot.wait(1)
    assert window.timeline.details.height() < 400
    assert window.timeline.pages.count() == 3
    assert all(window.timeline.pages.tabText(i) != "Graph editor" for i in range(2))


@pytest.fixture
def tween(window, qtbot):
    """Expose a real 24-frame rotation span with an independently owned editor window."""
    vm = window.viewmodel
    bone = RigService(vm.documents).create_bone((20, 30), (120, 30))
    service = AnimationEditingService(vm.documents)
    service.key(bone, "transform.rotation", 0, 0)
    service.key(bone, "transform.rotation", 24, 90)
    vm.changed.emit()
    qtbot.wait(10)
    track = service.timeline.tracks[0]
    refs = tuple((track.id, k.id) for k in track.keyframes)
    return window, service, bone, refs


def test_tween_body_moves_both_keys_live_and_endpoint_stretches_only_duration(tween):
    """Body drags preserve duration; a subsequent endpoint drag resizes just that endpoint."""
    window, service, bone, refs = tween
    vm, canvas = window.viewmodel, window.timeline.dope
    assert len(canvas.spans) == 1
    row = canvas.keys[refs[0]].pos().y()
    start = canvas.mapFromScene(QPointF(12 * canvas.pixels, row))
    target = start + QPoint(32, 25)
    baseline, count = vm.documents.project, len(vm.documents.history.undo_stack)
    QTest.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
    held_move(canvas.viewport(), target)
    assert vm.documents.project is baseline
    assert vm.animation_editor.preview_pose.frame == 4
    assert window.viewport.pose.nodes[bone].local.rotation == 0
    QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, pos=target)
    assert [k.frame for k in service.timeline.tracks[0].keyframes] == [4, 28]
    assert len(vm.documents.history.undo_stack) == count + 1
    start = canvas.mapFromScene(canvas.keys[refs[1]].pos())
    target = start + QPoint(80, -25)
    QTest.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
    held_move(canvas.viewport(), target)
    assert canvas.keys[refs[1]].pos().y() == row
    QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, pos=target)
    assert [k.frame for k in service.timeline.tracks[0].keyframes] == [4, 38]
    assert vm.documents.animation.evaluate(21).nodes[bone].local.rotation == pytest.approx(45)
    vm.undo()
    vm.undo()
    assert vm.documents.project == baseline


def test_popup_add_drag_delete_repeat_and_cancel_preserve_source(tween, qtbot):
    """Graph dots preview through the engine, and cancelling restores the source pose/history."""
    window, service, bone, refs = tween
    vm, canvas = window.viewmodel, window.timeline.dope
    center = canvas.mapFromScene((canvas.keys[refs[0]].pos() + canvas.keys[refs[1]].pos()) / 2)
    baseline, count = vm.documents.project, len(vm.documents.history.undo_stack)
    QTest.mouseDClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=center)
    dialog = window.timeline.curve_editor
    assert dialog.isVisible() and dialog.play.isChecked() and dialog.timer.isActive()
    dialog.play.setChecked(False)
    chart = dialog.chart
    point = chart.point_at(0.5, 0.25).toPoint()
    QTest.mouseDClick(chart, Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseRelease(chart, Qt.MouseButton.LeftButton, pos=point)
    assert len(chart.curve.points) == 3
    dialog.progress.setValue(500)
    assert window.viewport.pose.nodes[bone].local.rotation == pytest.approx(22.5, abs=1)
    point = chart.point_at(*chart.curve.points[1]).toPoint()
    QTest.mousePress(chart, Qt.MouseButton.LeftButton, pos=point)
    held_move(chart, point + QPoint(0, -25))
    QTest.mouseRelease(chart, Qt.MouseButton.LeftButton, pos=point + QPoint(0, -25))
    assert window.viewport.pose.nodes[bone].local.rotation > 22.5
    QTest.keyClick(chart, Qt.Key.Key_Delete)
    assert len(chart.curve.points) == 2
    QTest.keyClick(chart, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert len(chart.curve.points) == 3 and vm.documents.project is baseline
    QTest.keyClick(
        chart, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
    )
    assert len(chart.curve.points) == 2 and vm.documents.project is baseline
    chart.set_curve(TransitionCurve(((0, 0), (0.5, 0.2), (1, 1))))
    dialog.repeat_count.setValue(3)
    dialog.repeat_curve()
    assert len(chart.curve.points) == 7
    assert vm.documents.project is baseline and len(vm.documents.history.undo_stack) == count
    dialog.reject()
    assert vm.animation_editor.preview_pose is None and not dialog.timer.isActive()
    canonical = vm.documents.animation.pose
    assert window.viewport.pose == replace(
        canonical,
        nodes={
            key: replace(node, visible=False) if node.kind == "camera" else node
            for key, node in canonical.nodes.items()
        },
    )
    assert vm.documents.project is baseline


def test_preset_drop_graph_apply_clipboard_and_reverse_are_real(tween, qtbot):
    """Drop a preset, edit/apply it, then duplicate/cut/paste whole spans with their graphs."""
    window, service, bone, refs = tween
    vm, timeline = window.viewmodel, window.timeline
    canvas = timeline.dope
    before = len(vm.documents.history.undo_stack)
    mime = QMimeData()
    mime.setData(CURVE_MIME, b"Quadratic ease in")
    point = canvas.mapFromScene((canvas.keys[refs[0]].pos() + canvas.keys[refs[1]].pos()) / 2)
    enter = QDragEnterEvent(
        point,
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(canvas.viewport(), enter)
    drop = QDropEvent(
        QPointF(point),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(canvas.viewport(), drop)
    assert drop.isAccepted() and len(vm.documents.history.undo_stack) == before + 1
    assert vm.documents.animation.evaluate(12).nodes[bone].local.rotation == pytest.approx(22.5)
    assert any(item.data(2) for item in canvas.scene().items())
    timeline.open_curve(refs)
    dialog = timeline.curve_editor
    dialog.play.setChecked(False)
    dialog.chart.set_curve(curve_presets()["Cubic ease out"])
    QTest.mouseClick(dialog.apply, Qt.MouseButton.LeftButton)
    assert not dialog.isVisible() and not vm.animation_editor.error
    assert vm.documents.animation.evaluate(12).nodes[bone].local.rotation == pytest.approx(78.75)
    vm.animation_editor.select(refs)
    vm.animation_editor.paste(duplicate=True)
    assert [k.frame for k in service.timeline.tracks[0].keyframes] == [0, 24, 25, 49]
    vm.animation_editor.cut()
    assert [k.frame for k in service.timeline.tracks[0].keyframes] == [0, 24]
    vm.playback.seek(60)
    vm.animation_editor.paste()
    assert [k.frame for k in service.timeline.tracks[0].keyframes] == [0, 24, 60, 84]
    samples = [vm.documents.animation.evaluate(i).nodes[bone].local.rotation for i in range(60, 85)]
    timeline.edit_actions["reverse"].trigger()
    assert [
        vm.documents.animation.evaluate(i).nodes[bone].local.rotation for i in range(60, 85)
    ] == pytest.approx(samples[::-1])


def test_auto_key_stage_drag_and_toolbar_are_inside_dope_sheet(window, qtbot):
    """Scene drag recording seeds the first pose and shares the mesh auto-key preference."""
    vm = window.viewmodel
    bone = RigService(vm.documents).create_bone((20, 30), (120, 30))
    vm.changed.emit()
    vm.scene.select((bone,))
    vm.playback.seek(24)
    window.timeline.auto_key.setChecked(True)
    assert vm.scene.auto_key and vm.mesh.auto_key
    assert window.timeline.pages.widget(0).isAncestorOf(window.timeline.auto_key)
    baseline, count = vm.documents.project, len(vm.documents.history.undo_stack)
    vm.scene.begin_preview()
    vm.scene.preview_transform(dx=100)
    assert vm.documents.project is baseline
    assert vm.scene.preview.nodes[bone].local.x == 120
    vm.scene.finish_preview()
    assert len(vm.documents.history.undo_stack) == count + 1
    assert vm.documents.animation.evaluate(12).nodes[bone].local.x == 70
    vm.undo()
    assert vm.documents.project == baseline


def test_graph_popup_closes_on_clip_switch_and_palette_updates_presets(tween, qtbot):
    """Scratch edits never leak into another clip, and cached thumbnails follow theme changes."""
    window, service, _, refs = tween
    vm, timeline = window.viewmodel, window.timeline
    original_clip = service.clip.id
    vm.animation_editor.run(lambda s: s.new_clip("Other clip"))
    timeline.clips.setCurrentIndex(timeline.clips.findData(original_clip))
    timeline.open_curve(refs)
    dialog = timeline.curve_editor
    icon_key = dialog.presets.item(0).icon().cacheKey()
    vm.set_theme("light")
    qtbot.waitUntil(lambda: dialog.presets.item(0).icon().cacheKey() != icon_key)
    image = dialog.presets.item(0).icon().pixmap(100, 56).toImage()
    assert any(image.pixelColor(x, y).alpha() > 0 for x in range(100) for y in range(56))
    baseline = vm.documents.project
    timeline.clips.setCurrentIndex(1 - timeline.clips.currentIndex())
    assert not dialog.isVisible() and not dialog.timer.isActive()
    assert vm.animation_editor.preview_pose is None and vm.documents.project is baseline
