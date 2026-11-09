"""Independent spring-release transport, paused solver state and timeline/tab ownership."""

import math
import time

import pytest
from test_editor_tool_lifecycle_gui import make_chain
from test_roots_soft_drag_gui import editor as editor

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.domain.geometry import transform_point

pytestmark = pytest.mark.gui


def assert_restored_pose(displayed, canonical):
    """Compare restored physics while honoring Object Editor's hidden camera outlines."""
    assert displayed.nodes.keys() == canonical.nodes.keys()
    for key, node in canonical.nodes.items():
        actual = displayed.nodes[key]
        if node.kind == "camera":
            assert not actual.visible
            assert actual.world_matrix == node.world_matrix
        else:
            assert actual == node


@pytest.mark.parametrize("preset", ("Rubbery", "Stretchy", "Squashy"))
def test_spring_play_pause_and_repeat_leave_timeline_and_keys_untouched(editor, qtbot, preset):
    """Angular and axial previews move real bones, resume held physics and retain the clip frame."""
    vm, workspace = editor.viewmodel, editor.rig_workspace
    root, child, tip = make_chain(editor)
    animation = AnimationEditingService(vm.documents)
    animation.key(root, "transform.x", 0, 100)
    animation.key(root, "transform.x", 20, 300)
    vm.changed.emit()
    vm.playback.seek(10)
    if vm.playback.session.playback.loop:
        vm.playback.toggle_loop()
    editor.show_spring_editor()
    dialog = editor.spring_editor
    vm.rig.select(root)
    assert not vm.playback.session.playback.loop
    assert dialog.play_button.defaultAction() is None and dialog.loop_button.defaultAction() is None
    dialog.preset(preset)
    assert dialog.group_members(), (
        dialog.status.text(),
        vm.animation_editor.error,
        vm.rig.selected,
    )
    workspace.stop_springs()
    held = workspace.spring_pose()
    baseline, steps = vm.documents.project, len(vm.documents.history.undo_stack)
    clip_id = animation.clip.id
    vm.animation_editor.set_auto_key(True)
    dialog.play_button.click()
    assert dialog.play_button.isChecked() and dialog.preview_timer.isActive()
    assert workspace.spring_timer.isActive() and not vm.playback.session.playback.is_playing
    actual = editor.viewport.pose

    def point(pose):
        """Read the displayed tip position, including angular or axial spring displacement."""
        return transform_point(pose.nodes[tip].world_matrix, pose.nodes[tip].length, 0)

    assert math.dist(point(actual), point(held)) > 10
    assert actual.nodes[root].world_matrix[4:] == pytest.approx(held.nodes[root].world_matrix[4:])
    for key in (child, tip):
        node = actual.nodes[key]
        parent = actual.nodes[node.parent_id]
        assert node.world_matrix[4:] == pytest.approx(
            transform_point(parent.world_matrix, parent.length, 0)
        )
    for _ in range(8):
        workspace.spring_clock = time.monotonic() - 1 / 60
        workspace.tick_springs()
    assert editor.viewport.pose.nodes[child].world_matrix != actual.nodes[child].world_matrix
    dialog.play_button.click()
    frozen, solver = editor.viewport.pose, workspace.spring
    assert dialog.preview_paused and not dialog.preview_timer.isActive()
    assert not workspace.spring_timer.isActive()
    qtbot.wait(50)
    assert editor.viewport.pose is frozen
    dialog.play_button.click()
    assert workspace.spring is solver and workspace.spring_timer.isActive()
    dialog.loop_button.click()
    assert not dialog.loop_button.isChecked() and not vm.playback.session.playback.loop
    dialog.preview_timer.timeout.emit()
    assert not dialog.play_button.isChecked() and not dialog.preview_timer.isActive()
    assert not workspace.spring_timer.isActive()
    assert_restored_pose(editor.viewport.pose, held)
    assert vm.playback.session.playback.frame == 10 and animation.clip.id == clip_id
    assert editor.timeline.frame.value() == 10
    assert vm.documents.project is baseline and len(vm.documents.history.undo_stack) == steps


def test_dragging_during_explicit_spring_preview_never_commits_authored_pose(editor):
    """Release a real viewport drag signal during Preview without writing rest data or keys."""
    root, _, _ = make_chain(editor)
    editor.show_spring_editor()
    dialog = editor.spring_editor
    dialog.preset("Rubbery")
    dialog.play_button.click()
    before = editor.viewmodel.documents.project
    count = len(editor.viewmodel.documents.history.undo_stack)
    editor.viewport.bone_drag_started.emit()
    editor.viewport.bone_drag_preview.emit(root, "move", 40, 25)
    editor.viewport.bone_dragged.emit(root, "move", 40, 25)
    assert editor.viewmodel.documents.project is before
    assert len(editor.viewmodel.documents.history.undo_stack) == count
    assert editor.viewmodel.rig._preview_source is None
    dialog.stop_preview()
    assert_restored_pose(editor.viewport.pose, editor.viewmodel.documents.animation.pose)


def test_local_repeat_timeline_takeover_and_tab_switch_release_preview(editor, monkeypatch):
    """Repeat is local; timeline actions and tab switches release the preview."""
    vm, workspace = editor.viewmodel, editor.rig_workspace
    _, child, tip = make_chain(editor)
    editor.show_spring_editor()
    dialog = editor.spring_editor
    dialog.preset("Rubbery")
    baseline, steps = vm.documents.project, len(vm.documents.history.undo_stack)
    loop = vm.playback.session.playback.loop
    releases = []
    original = workspace.excite_springs

    def excite(members, **kwargs):
        releases.append(members)
        return original(members, **kwargs)

    monkeypatch.setattr(workspace, "excite_springs", excite)
    dialog.play_button.click()
    dialog.preview_timer.timeout.emit()
    assert releases == [dialog.group_members(), dialog.group_members()]
    assert dialog.play_button.isChecked() and dialog.preview_timer.isActive()
    assert not vm.playback.session.playback.is_playing
    assert not vm.documents.project.scenes[0].timelines
    assert vm.playback.session.playback.loop == loop
    assert vm.documents.project is baseline and len(vm.documents.history.undo_stack) == steps
    editor.command_actions["play"].trigger()
    assert vm.playback.session.playback.is_playing
    assert not dialog.preview_timer.isActive() and not dialog.play_button.isChecked()
    assert not workspace.spring_timer.isActive()
    vm.playback.pause()
    dialog.play_button.click()
    vm.playback.seek(12)
    assert not dialog.play_button.isChecked() and not dialog.preview_timer.isActive()
    dialog.play_button.click()
    old_document = vm.documents
    vm.new_project()
    assert not dialog.isVisible() and not dialog.preview_timer.isActive()
    assert not dialog.play_button.isChecked()
    assert vm.documents is not old_document and old_document.project is baseline


def test_local_spring_play_holds_fractional_timeline_without_snapping(editor):
    """Starting a physics-only test can pause main playback without moving its precise cursor."""
    vm = editor.viewmodel
    make_chain(editor)
    editor.show_spring_editor()
    dialog = editor.spring_editor
    vm.playback.seek(10.41)
    dialog.preset("Rubbery")
    assert vm.playback.session.pose.frame == pytest.approx(10.41)
    vm.playback.play_pause()
    baseline = vm.documents.project
    steps = len(vm.documents.history.undo_stack)
    dialog.play_button.click()
    assert vm.playback.session.pose.frame == pytest.approx(10.41)
    assert not vm.playback.session.playback.is_playing
    assert dialog.play_button.isChecked() and dialog.preview_timer.isActive()
    assert editor.rig_workspace.spring_timer.isActive()
    assert vm.documents.project is baseline and len(vm.documents.history.undo_stack) == steps
