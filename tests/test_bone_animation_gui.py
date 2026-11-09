"""Actual bone picking and timeline end dragging remain usable on the current animation frame."""

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from rigora.app.application import ApplicationInfo
from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.rigging import RigService
from rigora.domain.geometry import transform_point
from rigora.infrastructure.preferences import PreferencesStore
from rigora.presentation.viewmodels.main_window import MainWindowViewModel
from rigora.presentation.views.main_window import MainWindow

pytestmark = pytest.mark.gui


def move_held(widget, point):
    """Send a real Qt held-button move without depending on the desktop pointer position."""
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


@pytest.fixture
def window(qtbot, tmp_path):
    """Own an isolated editor with an animated two-bone chain and a visible timeline."""
    vm = MainWindowViewModel(ApplicationInfo(), preferences=PreferencesStore(tmp_path / "ui.json"))
    widget = MainWindow(vm)
    widget.confirm_discard = lambda: True
    qtbot.addWidget(widget)
    widget.resize(1600, 1000)
    widget.show()
    vm.new_project()
    rig = RigService(vm.documents)
    root = rig.create_bone((300, 300), (400, 300))
    tip = rig.create_bone((400, 300), (500, 300), root)
    editor = AnimationEditingService(vm.documents)
    editor.key(root, "transform.rotation", 0, 0)
    editor.key(root, "transform.rotation", 24, 60)
    vm.changed.emit()
    vm.playback.seek(12)
    qtbot.wait(20)
    return widget, root, tip


def test_bone_click_pose_scrub_and_play_do_not_freeze_or_reset_timeline(window, qtbot):
    """Replay selection, live chain posing and transport after creating an interpolated span."""
    widget, root, tip = window
    vm, viewport = widget.viewmodel, widget.viewport
    rest = vm.documents.project.scenes[0].skeletons
    baseline, count = vm.documents.project, len(vm.documents.history.undo_stack)
    point = transform_point(viewport.pose.nodes[tip].world_matrix, 70, 0)
    start = (viewport.offset + QPointF(*point) * viewport.zoom).toPoint()
    end = start + QPoint(-20, 40)
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
    assert widget.timeline.isEnabled() and widget.command_actions["play"].isEnabled()
    assert vm.playback.session.pose.frame == 12 and viewport.pose.frame == 12
    move_held(viewport, end)
    assert vm.documents.project is baseline and not vm.rig.error
    assert (
        viewport.pose.nodes[tip].world_matrix != vm.documents.animation.pose.nodes[tip].world_matrix
    )
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=end)
    assert not vm.rig.error and vm.playback.session.pose.frame == 12
    assert len(vm.documents.history.undo_stack) == count + 1
    assert vm.documents.project.scenes[0].skeletons == rest
    vm.playback.seek(20)
    expected = vm.documents.animation.evaluate(20)
    assert viewport.source_pose == expected
    for key in (root, tip):
        assert viewport.pose.nodes[key] == expected.for_display().nodes[key]
    assert widget.timeline.isEnabled()
    now = [0.0]
    vm.playback.clock = lambda: now[0]
    vm.playback.play_pause()
    now[0] = 1 / 24
    vm.playback.tick()
    assert vm.playback.session.playback.is_playing
    assert viewport.pose.frame == pytest.approx(21)
    vm.playback.pause()
    vm.undo()
    assert vm.documents.project == baseline


def test_ruler_end_flag_drag_and_numeric_cap_commit_once(window, qtbot):
    """Drag a cap live, then type another end without losing authored keys or disabling tools."""
    widget, root, _ = window
    vm, timeline = widget.viewmodel, widget.timeline
    widget.rig_workspace.set_mode(True)
    canvas, ruler = timeline.dope, timeline.dope.ruler
    canvas.pixels = 5
    timeline.expansion_changed()
    qtbot.wait(5)
    start = ruler.end_handle().center().toPoint()
    end = start + QPoint(-80 * 5, 0)
    before, count = vm.documents.project, len(vm.documents.history.undo_stack)
    QTest.mousePress(ruler, Qt.MouseButton.LeftButton, pos=start)
    move_held(ruler, end)
    assert canvas.end == 40 and vm.documents.project is before
    QTest.mouseRelease(ruler, Qt.MouseButton.LeftButton, pos=end)
    assert vm.playback.session.playback.range.end == 40
    assert len(vm.documents.history.undo_stack) == count + 1
    assert timeline.max_frame.value() == 40 and timeline.isEnabled()
    timeline.max_frame.setValue(80)
    timeline.max_frame.editingFinished.emit()
    assert vm.playback.session.playback.range.end == 80
    vm.undo()
    assert vm.playback.session.playback.range.end == 40
    vm.undo()
    assert vm.documents.project == before
