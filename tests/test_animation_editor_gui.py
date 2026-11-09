"""Real Qt key, curve, clipboard, preview and constrained endpoint interactions."""

import pytest
from animation_fixtures import open_animation_fixture

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from rigora.app.application import ApplicationInfo
from rigora.domain.geometry import transform_point
from rigora.engine.transition_curves import TransitionCurve
from rigora.infrastructure.preferences import PreferencesStore
from rigora.presentation.viewmodels.main_window import MainWindowViewModel
from rigora.presentation.views.main_window import MainWindow


@pytest.fixture
def editor_window(qtbot, tmp_path):
    """Create an isolated animation shell with no interaction with the owner's open windows."""
    model = MainWindowViewModel(
        ApplicationInfo(), preferences=PreferencesStore(tmp_path / "ui.json")
    )
    window = MainWindow(model)
    qtbot.addWidget(window, before_close_func=lambda w: setattr(w, "confirm_discard", lambda: True))
    window.resize(1600, 1000)
    window.show()
    open_animation_fixture(model)
    window.resizeDocks([window.docks["timeline"]], [420], Qt.Orientation.Vertical)
    qtbot.wait(10)
    return window


def move_mouse(widget, point):
    """Deliver a held-button move without relying on the desktop's synthetic pointer state."""
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


def test_dope_sheet_drag_numeric_clipboard_lock_range_and_undo(editor_window, qtbot):
    """Native key movement edits the real timeline; clipboard and locking remain reversible."""
    window = editor_window
    vm, timeline = window.viewmodel, window.timeline
    editor, service = vm.animation_editor, vm.animation_editor.service
    track = next(t for t in service.timeline.tracks if t.name == "Root rotation")
    key = track.keyframes[1]
    ref = track.id, key.id
    canvas = timeline.dope
    item = canvas.keys[ref]
    canvas.ensureVisible(item)
    qtbot.wait(1)
    start = canvas.mapFromScene(item.pos())
    count = len(vm.documents.history.undo_stack)
    QTest.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
    move_mouse(canvas.viewport(), start + QPoint(16, 0))
    assert len(vm.documents.history.undo_stack) == count
    QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, pos=start + QPoint(16, 0))
    assert not editor.error
    current = next(t for t in service.timeline.tracks if t.id == track.id)
    assert current.keyframes[1].frame == 32
    assert len(vm.documents.history.undo_stack) == count + 1
    vm.undo()
    assert next(t for t in service.timeline.tracks if t.id == track.id).keyframes[1].frame == 30
    editor.select((ref,))
    timeline.key_value.setValue(70)
    timeline.apply_numeric()
    vm.playback.seek(30)
    assert vm.documents.animation.pose.nodes[track.owner_id].local.rotation == 70
    editor.copy()
    vm.playback.seek(40)
    editor.paste()
    assert not editor.error
    assert any(k.frame == 40 for t, k in editor.key_records() if t.id == track.id)
    editor.delete()
    assert not any(k.frame == 40 for t, k in editor.key_records() if t.id == track.id)
    editor.run(lambda s: s.track_settings(track.id, locked=True, visible=True))
    editor.select((ref,))
    baseline = vm.documents.project
    timeline.key_value.setValue(25)
    timeline.apply_numeric()
    assert "Unlock" in editor.error and vm.documents.project is baseline
    vm.undo()
    timeline.select_range(25, 35)
    assert ref in editor.selected
    assert timeline.clip_editor.start.value() == 25
    assert timeline.clip_editor.end.value() == 35


def test_popup_graph_changes_playback_and_preview_tools_preserve_document(editor_window, qtbot):
    """Dragging a Bézier handle changes actual engine samples; overlays remain transient."""
    window = editor_window
    vm, timeline = window.viewmodel, window.timeline
    editor, service = vm.animation_editor, vm.animation_editor.service
    track = next(t for t in service.timeline.tracks if t.name == "Root rotation")
    ref = track.id, track.keyframes[0].id
    editor.select((ref,))
    original = vm.documents.animation.evaluate(10).nodes[track.owner_id].local.rotation
    timeline.open_curve()
    dialog = timeline.curve_editor
    dialog.play.setChecked(False)
    baseline = vm.documents.project
    chart = dialog.chart
    chart.set_curve(TransitionCurve(((0, 0), (0.5, 0.2), (1, 1))))
    start = chart.point_at(0.5, 0.2).toPoint()
    target = start + QPoint(0, -30)
    QTest.mousePress(chart, Qt.MouseButton.LeftButton, pos=start)
    move_mouse(chart, target)
    QTest.mouseRelease(chart, Qt.MouseButton.LeftButton, pos=target)
    assert vm.documents.project is baseline
    assert editor.preview_pose is not None
    QTest.mouseClick(dialog.apply, Qt.MouseButton.LeftButton)
    assert not editor.error
    assert vm.documents.animation.evaluate(10).nodes[
        track.owner_id
    ].local.rotation != pytest.approx(original)
    vm.undo()
    assert vm.documents.animation.evaluate(10).nodes[
        track.owner_id
    ].local.rotation == pytest.approx(original)
    baseline = vm.documents.project
    vm.playback.seek(10)
    timeline.compare.setChecked(True)
    timeline.onion.setChecked(True)
    timeline.trails.setChecked(True)
    vm.playback.seek(15)
    assert len(window.viewport.ghost_poses) == 3
    assert window.viewport.motion_trails
    assert vm.documents.project is baseline
    assert vm.documents.animation.pose.frame == 15
    timeline.clip_editor.start.setValue(5)
    timeline.clip_editor.end.setValue(20)
    timeline.clip_editor.preview_range()
    assert vm.playback.session.playback.range.start == 5
    assert vm.playback.session.playback.range.end == 20


def test_last_ik_bone_can_be_dragged_live_without_selecting_control(editor_window):
    """A bone-body drag routes an active IK endpoint to its target and keeps the root fixed."""
    window = editor_window
    vm = window.viewmodel
    vm.new_project("IK drag")
    window.rig_workspace.set_mode(True)
    vm.rig.run(lambda s: s.create_bone((300, 200), (450, 200)))
    root = vm.rig.bone.id
    vm.rig.run(lambda s: s.create_bone((450, 200), (600, 200), root))
    tip = vm.rig.bone.id
    vm.rig.run(lambda s: s.add_constraint(root, "two_bone_ik"))
    vm.rig.set_tool("select")
    window.rig_workspace.frame_rig()
    viewport = window.viewport
    node = vm.rig.pose.nodes[tip]
    start = (
        viewport.offset + QPointF(*transform_point(node.world_matrix, 90, 0)) * viewport.zoom
    ).toPoint()
    end = start + QPoint(-30, 45)
    baseline = vm.documents.project
    before = node.world_matrix
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
    move_mouse(viewport, end)
    assert vm.rig.selected == (tip,)
    assert not vm.rig.error
    assert vm.rig.pose.nodes[tip].world_matrix != before
    assert transform_point(vm.rig.pose.nodes[root].world_matrix, 0, 0) == pytest.approx((300, 200))
    assert vm.documents.project is baseline
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=end)
    assert vm.documents.project != baseline
    vm.undo()
    assert vm.documents.project == baseline
