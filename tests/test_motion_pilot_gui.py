"""Offscreen end-to-end Motion Pilot tool, input scoping and asynchronous recorded key adoption."""

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from test_character_objects_gui import editor as editor
from test_object_scene_actions_gui import readable_offscreen_fonts as readable_offscreen_fonts

from rigora.application_services.appearance import AppearanceService
from rigora.application_services.motion_pilot import MotionPilotService

pytestmark = pytest.mark.gui


def target(editor):
    """Create ordinary vector artwork and select its actual scene identity."""
    service = AppearanceService(editor.viewmodel.documents)
    mesh = service.create_shape("ellipse", 120, 120, 80, 120)
    owner = service.mesh(mesh).object_id
    editor.viewmodel.changed.emit()
    editor.viewmodel.scene.select((owner,))
    return owner


def test_menu_space_preview_record_keys_cancel_and_offscreen_capture(editor, qtbot):
    """Use real menu/Space/pointer events; text entry and canceled previews never record keys."""
    owner = target(editor)
    action = editor.command_actions["motion_pilot"]
    assert action in editor.menus["Animation"].actions()
    action.trigger()
    tool = editor.motion_pilot
    assert tool.leader.currentData() == owner
    before = editor.viewmodel.documents.project
    tool.preview_button.click()
    assert tool.model.state == "Preview armed"
    editor.filter.setFocus()
    QTest.keyClick(editor.filter, Qt.Key.Key_Space)
    assert tool.model.state == "Preview armed" and editor.filter.text().endswith(" ")
    tool.pointer = (0, 0)
    QTest.keyClick(editor.viewport, Qt.Key.Key_Space)
    assert tool.model.state == "Previewing"
    tool.timer.stop()
    QTest.mouseMove(editor.viewport, QPoint(300, 230))
    assert tool.pointer != (0, 0)
    tool.model.capture(6, (60, 30))
    assert editor.viewmodel.animation_editor.preview_pose.nodes[owner].local.x == pytest.approx(180)
    QTest.keyClick(editor.viewport, Qt.Key.Key_Escape)
    assert tool.model.state == "Idle"
    assert editor.viewmodel.documents.project is before
    tool.pointer = (0, 0)
    tool.record_button.click()
    QTest.keyClick(editor.viewport, Qt.Key.Key_Space)
    assert tool.model.state == "Recording"
    tool.timer.stop()
    tool.model.capture(6, (60, 30))
    tool.model.pause()
    tool.model.capture(9, (500, 500))
    assert tool.model.session.frame == 6
    tool.model.pause()
    tool.timer.stop()
    tool.model.stop(12.5, (125, 60))
    qtbot.waitUntil(lambda: tool.model.state == "Idle", timeout=15000)
    assert not editor.viewmodel.animation_editor.error
    assert editor.viewmodel.documents.animation.evaluate(12.5).nodes[
        owner
    ].local.x == pytest.approx(245)
    assert any(lane == "Transform" for _, lane in editor.timeline._groups)
    output = Path("build/prompt-17-review")
    output.mkdir(parents=True, exist_ok=True)
    tool.grab().save(str(output / "motion-pilot.png"))
    editor.viewmodel.undo()
    assert editor.viewmodel.documents.project == before
    tool.close()
    assert tool.model.session is None and not tool.timer.isActive()


def test_profile_edits_survive_fast_target_changes_and_closed_tool_releases_input(editor, qtbot):
    """Queued profile edits keep captured target IDs rather than mutating the next selection."""
    first = target(editor)
    second = target(editor)
    editor.viewmodel.scene.select((first,))
    editor.show_motion_pilot()
    tool = editor.motion_pilot
    tool.controls["wave_y"].setValue(77)
    tool.leader.setCurrentIndex(tool.leader.findData(second))
    qtbot.wait(180)
    service = MotionPilotService(editor.viewmodel.documents)
    assert service.profile(first).wave_y == 77
    assert service.profile(second).wave_y == 25
    tool.arm(False)
    tool.model.start((0, 0), (0, 0))
    tool.timer.stop()
    tool.close()
    assert tool.model.state == "Idle"
    before = editor.viewmodel.documents.project
    QTest.keyClick(editor.filter, Qt.Key.Key_Space)
    assert editor.viewmodel.documents.project is before


def test_closing_tool_flushes_pending_profile_without_recording(editor):
    """Closing after a setting edit retains settings without creating motion keys."""
    owner = target(editor)
    editor.show_motion_pilot()
    tool = editor.motion_pilot
    tool.controls["lazy_mouse"].setValue(0.42)
    assert tool.save_timer.isActive()
    tool.close()
    service = MotionPilotService(editor.viewmodel.documents)
    assert service.profile(owner).lazy_mouse == 0.42
    assert service.timeline is None or not any(
        t.extra.get("motion_pilot") for t in service.timeline.tracks
    )


def test_record_arming_keeps_viewport_usable_and_visible_start_records_real_mouse_input(
    editor, qtbot
):
    """Record actual pointer events against the live capture clock without manual frame samples."""
    owner = target(editor)
    editor.show_motion_pilot()
    tool = editor.motion_pilot
    editor.viewport.zoom = 1
    editor.viewport.offset.setX(0)
    editor.viewport.offset.setY(0)
    tool.record_button.click()
    assert tool.model.state == "Record armed" and tool.start_button.isVisible()
    assert editor.isEnabled() and editor.viewport.isEnabled()
    QTest.mouseMove(editor.viewport, QPoint(100, 100))
    assert tool.pointer == (100, 100)
    tool.start_button.click()
    assert tool.model.state == "Recording" and not tool.start_button.isVisible()
    qtbot.wait(60)
    QTest.mouseMove(editor.viewport, QPoint(160, 130))
    qtbot.waitUntil(
        lambda: editor.viewmodel.animation_editor.preview_pose.nodes[owner].local.x > 170
    )
    tool.stop_button.click()
    qtbot.waitUntil(lambda: tool.model.state == "Idle", timeout=15000)
    assert not editor.viewmodel.animation_editor.error
    assert editor.viewmodel.documents.animation.evaluate(tool.last_frame).nodes[owner].local.x > 170
    tool.close()
