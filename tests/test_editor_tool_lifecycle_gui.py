"""Exercise toolbox toggles, modeless editor ownership and applied spring controls."""

from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton
from test_workspace_redesign_gui import editor as editor

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.dynamics import SPRING_PRESETS, DynamicsService
from rigora.application_services.meshes import MeshService
from rigora.application_services.rigging import RigService

pytestmark = pytest.mark.gui


def click_tool(window, key):
    """Click the actual docked tool button, including QAction checked-state behavior."""
    button = window.toolbox.widgetForAction(window.command_actions[key])
    assert button is not None
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)


def make_chain(window):
    """Create connected geometry whose joints and toolbar actions can be exercised on stage."""
    rig = RigService(window.viewmodel.documents)
    root = rig.create_bone((100, 160), (200, 160))
    child = rig.create_bone((200, 160), (280, 160), root)
    tip = rig.create_bone((280, 160), (340, 160), child)
    window.viewmodel.changed.emit()
    window.viewmodel.rig.select(root)
    return root, child, tip


def make_artwork(window):
    """Place one canonical image without entering a specialized authoring tool."""
    service = MeshService(window.viewmodel.documents)
    asset = service.register_image_bytes("prop.svg", Path("assets/examples/prop.svg").read_bytes())
    mesh = service.instantiate_asset(asset)
    window.viewmodel.changed.emit()
    window.viewmodel.mesh.select_mesh(mesh)
    return mesh


def test_mesh_toggle_and_selection_release_specialized_input(editor):
    """A repeated mesh click and the Select action both return input ownership to the scene."""
    window, vm = editor, editor.viewmodel
    mesh = make_artwork(window)
    baseline, steps = vm.documents.project, len(vm.documents.history.undo_stack)
    click_tool(window, "mesh")
    assert vm.mesh.active and vm.mesh.tool == "soft"
    assert window.command_actions["mesh"].isChecked()
    click_tool(window, "mesh")
    assert not vm.mesh.active and not window.command_actions["mesh"].isChecked()
    click_tool(window, "mesh")
    click_tool(window, "navigate")
    assert not vm.mesh.active and window.command_actions["navigate"].isChecked()
    assert vm.documents.project is baseline and len(vm.documents.history.undo_stack) == steps
    click_tool(window, "mesh")
    window.mesh_panel.tools.setCurrentIndex(window.mesh_panel.tools.findData("insert"))
    assert window.command_actions["mesh"].isChecked()
    click_tool(window, "mesh")
    assert not vm.mesh.active
    viewport = window.viewport
    viewport.zoom, viewport.offset = 1, QPointF(20, 20)
    owner = vm.mesh.service.mesh(mesh).object_id
    center = window.scene_workspace.polygons()[owner].boundingRect().center()
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=center.toPoint())
    assert vm.scene.selected == (owner,)
    for key in ("weights", "deform"):
        window.command_actions[key].trigger()
        assert vm.mesh.active and window.command_actions[key].isChecked()
        window.command_actions[key].trigger()
        assert not vm.mesh.active and not window.command_actions[key].isChecked()


def test_bone_draw_pin_close_and_escape_return_to_selection(editor):
    """Drawing/pinning toggle independently; closing the dialog never leaves their tools active."""
    window, vm = editor, editor.viewmodel
    make_chain(window)
    make_artwork(window)
    click_tool(window, "bone_editor")
    dialog = window.bone_editor
    assert dialog.isVisible() and window.command_actions["bone_editor"].isChecked()
    dialog.wireframe.setChecked(False)
    assert dialog.pin_radius.isEnabled()
    draw, pin = dialog.bone_buttons["Add bone"], dialog.bone_buttons["Add pin"]
    draw.click()
    assert vm.rig.active and vm.rig.tool == "draw" and draw.isChecked()
    draw.click()
    assert vm.rig.tool == "select" and not draw.isChecked()
    pin.click()
    assert vm.mesh.active and vm.mesh.tool == "area_pin" and pin.isChecked()
    pin.click()
    assert not vm.mesh.active and not pin.isChecked()
    draw.click()
    click_tool(window, "bone_editor")
    assert not dialog.isVisible() and vm.rig.tool == "select"
    assert not window.command_actions["bone"].isChecked()
    click_tool(window, "bone_editor")
    dialog = window.bone_editor
    dialog.bone_buttons["Add pin"].click()
    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    assert not dialog.isVisible() and not vm.mesh.active
    assert window.command_actions["navigate"].isChecked()
    window.command_actions["bone"].trigger()
    assert vm.rig.tool == "draw"
    window.command_actions["bone"].trigger()
    assert vm.rig.tool == "select"


def test_selection_releases_read_only_subdivision_preview(editor, qtbot):
    """A topology preview cannot continue intercepting clicks after Select or Mesh is chosen."""
    window, vm = editor, editor.viewmodel
    make_artwork(window)
    click_tool(window, "bone_editor")
    dialog = window.bone_editor
    dialog.wireframe.setChecked(True)
    dialog.density.setValue(3)
    qtbot.waitUntil(lambda: window.viewport.subdivision_pose is not None, timeout=10000)
    click_tool(window, "navigate")
    assert window.viewport.subdivision_pose is None
    assert not dialog.preview_subdivision.isChecked() and not dialog.preview_timer.isActive()
    dialog.preview_subdivision.setChecked(True)
    qtbot.waitUntil(lambda: window.viewport.subdivision_pose is not None, timeout=10000)
    click_tool(window, "mesh")
    assert vm.mesh.active and window.viewport.subdivision_pose is None
    assert not dialog.preview_subdivision.isChecked()


def test_editor_tab_ownership_does_not_change_another_tabs_tool(editor):
    """Old dialogs close on a tab switch and cannot steal the new document's tool."""
    window, vm = editor, editor.viewmodel
    make_chain(window)
    click_tool(window, "bone_editor")
    old = window.bone_editor
    old.bone_buttons["Add bone"].click()
    vm.new_project()
    assert not old.isVisible() and not window.command_actions["bone_editor"].isChecked()
    window.draw_bone()
    old.close()
    assert vm.rig.tool == "draw"
    window.navigate()
    make_chain(window)
    click_tool(window, "spring_editor")
    old_spring = window.spring_editor
    vm.activate_project(0)
    assert not old_spring.isVisible()
    assert not window.command_actions["spring_editor"].isChecked()
    assert vm.rig.tool == "select" and not vm.mesh.active


def test_spring_presets_apply_live_properties_undo_and_toggle(editor, qtbot):
    """Presets immediately configure members once, sliders update them, and preview is transient."""
    window, vm = editor, editor.viewmodel
    root, child, tip = make_chain(window)
    click_tool(window, "spring_editor")
    dialog = window.spring_editor
    for name, (frequency, damping, inertia, gravity, translate) in SPRING_PRESETS.items():
        steps = len(vm.documents.history.undo_stack)
        button = next(b for b in dialog.findChildren(QPushButton) if b.text() == name)
        button.click()
        assert not vm.animation_editor.error
        rules = [r for r in DynamicsService(vm.documents).scene.constraints if r.kind == "spring"]
        assert {r.owner_id for r in rules} == {root, child, tip}
        assert next(r for r in rules if r.owner_id == root).extra["spring_object_root"] is True
        for rule in rules:
            assert rule.parameters["frequency"] == frequency
            assert rule.parameters["damping"] == damping
            assert rule.parameters["inertia"] == inertia
            assert rule.parameters["gravity"] == gravity
            assert rule.parameters["translate"] is translate
        assert len(vm.documents.history.undo_stack) == steps + 1
    before = vm.documents.project
    dialog.speed.setValue(80)
    qtbot.waitUntil(lambda: not dialog.apply_timer.isActive())
    assert vm.documents.project is not before
    assert all(
        r.parameters["frequency"] == pytest.approx(9.7)
        for r in DynamicsService(vm.documents).scene.constraints
        if r.kind == "spring"
    )
    vm.undo()
    assert vm.documents.project == before
    assert dialog.fields["frequency"].value() == SPRING_PRESETS["Squashy"][0]
    baseline, steps = vm.documents.project, len(vm.documents.history.undo_stack)
    dialog.play_button.click()
    assert not vm.playback.session.playback.is_playing
    assert dialog.preview_timer.isActive() and window.rig_workspace.spring_timer.isActive()
    dialog.play_button.click()
    assert not vm.playback.session.playback.is_playing and not dialog.preview_timer.isActive()
    window.rig_workspace.begin_springs()
    assert window.rig_workspace.spring_timer.isActive()
    click_tool(window, "spring_editor")
    assert not dialog.isVisible() and not window.rig_workspace.spring_timer.isActive()
    assert vm.documents.project is baseline and len(vm.documents.history.undo_stack) == steps


def test_empty_spring_preset_explains_selection_without_creating_rules(editor):
    """Presets remain usable before assignment and explain which selection is needed."""
    window, vm = editor, editor.viewmodel
    click_tool(window, "spring_editor")
    dialog = window.spring_editor
    baseline = vm.documents.project
    dialog.preset("Rubbery")
    assert vm.documents.project is baseline
    assert "Select a bone" in dialog.status.text()
    dialog.close()


def test_pending_spring_controls_keep_their_group_and_do_not_reassign_removed_bones(editor, qtbot):
    """Switching groups flushes the former group's values; removal cancels pending updates."""
    window, vm = editor, editor.viewmodel
    _, child, tip = make_chain(window)
    click_tool(window, "spring_editor")
    dialog = window.spring_editor
    dialog.preset("Rubbery")
    DynamicsService(vm.documents).configure((tip,), group="Tail", frequency=7)
    dialog.refresh("Default")
    dialog.fields["gravity"].setValue(345)
    assert dialog.apply_timer.isActive()
    dialog.groups.setCurrentItem(dialog.groups.topLevelItem(1))
    rules = {
        r.owner_id: r for r in DynamicsService(vm.documents).scene.constraints if r.kind == "spring"
    }
    assert rules[child].parameters["gravity"] == 345
    assert rules[tip].parameters["frequency"] == 7
    vm.rig.select(tip)
    dialog.fields["frequency"].setValue(9)
    dialog.unassign()
    qtbot.wait(200)
    assert not dialog.apply_timer.isActive()
    assert all(
        r.owner_id != tip
        for r in DynamicsService(vm.documents).scene.constraints
        if r.kind == "spring"
    )
    dialog.groups.setCurrentItem(dialog.groups.topLevelItem(0))
    dialog.fields["frequency"].setValue(8)
    assert dialog.apply_timer.isActive()
    vm.undo()
    restored = vm.documents.project
    qtbot.wait(200)
    assert vm.documents.project is restored and not dialog.apply_timer.isActive()


def test_live_springs_target_kinematic_pose_instead_of_resimulating_playback(editor):
    """Settling at a held animation frame returns to its target, not a twice-delayed pose."""
    window, vm = editor, editor.viewmodel
    root, child, tip = make_chain(window)
    animation = AnimationEditingService(vm.documents)
    animation.key(root, "transform.rotation", 0, 0)
    animation.key(root, "transform.rotation", 12, 70)
    DynamicsService(vm.documents).configure((child, tip), frequency=3, damping=1)
    vm.changed.emit()
    vm.playback.seek(6)
    pose = vm.documents.animation.pose
    assert pose.spring_targets is not None
    target = pose.spring_targets
    assert abs(pose.nodes[child].local.rotation - target[child].local.rotation) > 1
    baseline, steps = vm.documents.project, len(vm.documents.history.undo_stack)
    workspace = window.rig_workspace
    workspace.begin_springs()
    for _ in range(160):
        workspace.spring_clock -= 1 / 60
        workspace.tick_springs()
    for key in (child, tip):
        assert window.viewport.pose.nodes[key].world_matrix == pytest.approx(
            target[key].world_matrix, abs=0.001
        )
    assert vm.documents.project is baseline and len(vm.documents.history.undo_stack) == steps
    workspace.stop_springs()
    assert window.viewport.source_pose == pose
    for key in (root, child, tip):
        assert window.viewport.pose.nodes[key] == pose.for_display().nodes[key]
