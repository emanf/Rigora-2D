"""One selection tool exposes real move, rotate and scale gestures without tool switching."""

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QStyle, QStyleOptionSpinBox, QToolBar
from test_mesh_gui import mesh_window as mesh_window
from test_rigging_gui import move_pointer
from test_workspace_redesign_gui import editor as editor

from rigora.application_services.rigging import RigService
from rigora.domain.geometry import transform_point
from rigora.presentation import transform_gizmo

pytestmark = pytest.mark.gui


def bones(window):
    """Place a three-bone branch where all transform grips are visible at 100% zoom."""
    rig = RigService(window.viewmodel.documents)
    root = rig.create_bone((100, 160), (200, 160))
    middle = rig.create_bone((200, 160), (280, 160), root)
    tip = rig.create_bone((280, 160), (350, 160), middle)
    window.viewmodel.changed.emit()
    window.rig_workspace.set_mode(True)
    window.viewmodel.rig.select(middle)
    window.navigate()
    window.bone_mode_buttons["selection_move"].click()
    window.viewport.zoom, window.viewport.offset = 1, QPointF(20, 20)
    return root, middle, tip


def drag(viewport, start, end, modifiers=Qt.KeyboardModifier.NoModifier):
    """Send one complete pointer gesture through the same widget event routes as real input."""
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, modifiers, start)
    QTest.mouseMove(viewport, end)
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, modifiers, end)


def test_default_bone_move_selected_group_and_explicit_chain_are_distinct(editor):
    window, vm = editor, editor.viewmodel
    root, middle, tip = bones(window)
    viewport = window.viewport
    before = vm.documents.animation.pose
    baseline = vm.documents.project
    count = len(vm.documents.history.undo_stack)
    drag(viewport, QPoint(260, 180), QPoint(284, 204))
    assert not vm.rig.error
    after = vm.documents.animation.pose
    assert after.nodes[middle].world_matrix[4:] == pytest.approx((224, 184))
    for key in (root, tip):
        assert after.nodes[key].world_matrix == pytest.approx(before.nodes[key].world_matrix)
    assert len(vm.documents.history.undo_stack) == count + 1
    vm.undo()
    assert vm.documents.project == baseline
    vm.rig.select_many((middle, tip))
    drag(viewport, QPoint(260, 180), QPoint(284, 204))
    assert not vm.rig.error
    assert vm.documents.animation.pose.nodes[tip].world_matrix[4:] == pytest.approx((304, 184))
    vm.undo()
    vm.rig.select(tip)
    window.bone_mode_buttons["pull"].click()
    drag(viewport, QPoint(330, 180), QPoint(310, 235), Qt.KeyboardModifier.ControlModifier)
    assert not vm.rig.error
    after = vm.documents.animation.pose
    assert after.nodes[middle].world_matrix != before.nodes[middle].world_matrix
    assert after.nodes[root].world_matrix[4:] == pytest.approx(before.nodes[root].world_matrix[4:])


def test_hidden_bone_overlay_retains_pointer_selection_move_and_undo(editor):
    """Hide the armature without hiding scene nodes or disabling their interaction geometry."""
    window, vm = editor, editor.viewmodel
    _, middle, _ = bones(window)
    vm.rig.select_many(())
    viewport = window.viewport
    before_image = viewport.grab().toImage()
    baseline = vm.documents.project
    count = len(vm.documents.history.undo_stack)
    window.command_actions["bone_overlay"].trigger()
    assert not viewport.show_bones
    assert viewport.grab().toImage() != before_image
    assert vm.documents.project is baseline and len(vm.documents.history.undo_stack) == count
    assert viewport.pose.nodes[middle].visible
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=QPoint(260, 180))
    assert vm.rig.selected == (middle,)
    drag(viewport, QPoint(260, 180), QPoint(284, 204))
    assert not vm.rig.error
    assert vm.documents.animation.pose.nodes[middle].world_matrix[4:] == pytest.approx((224, 184))
    assert not viewport.show_bones and len(vm.documents.history.undo_stack) == count + 1
    vm.undo()
    assert vm.documents.project == baseline
    assert window.canvas_label.isVisible()
    header = window.canvas_label.parentWidget().layout()
    assert header.itemAt(header.count() - 1).widget() is window.canvas_label
    window.command_actions["bone_overlay"].trigger()
    assert viewport.show_bones


@pytest.mark.parametrize("handle", [4, 8])
def test_bone_resize_and_rotate_grips_work_in_selection_mode(editor, handle):
    window, vm = editor, editor.viewmodel
    root, middle, tip = bones(window)
    viewport = window.viewport
    before = vm.documents.animation.pose
    rect = viewport.bone_transform_bounds()
    start = transform_gizmo.handles(rect)[handle]
    end = (
        rect.center() + (start - rect.center()) * 1.4
        if handle == 4
        else QPointF(rect.center().x() + (rect.center().y() - start.y()), rect.center().y())
    )
    count = len(vm.documents.history.undo_stack)
    drag(viewport, start.toPoint(), end.toPoint())
    assert not vm.rig.error
    assert vm.rig.tool == "select"
    after = vm.documents.animation.pose
    assert after.nodes[middle].world_matrix != before.nodes[middle].world_matrix
    assert after.nodes[root].world_matrix == pytest.approx(before.nodes[root].world_matrix)
    assert after.nodes[tip].world_matrix == pytest.approx(before.nodes[tip].world_matrix)
    assert len(vm.documents.history.undo_stack) == count + 1


@pytest.mark.parametrize("scope", ["selection_move", "chain_move"])
def test_attached_tip_rotates_about_base_and_respects_scope(editor, scope):
    """A shared parent/child joint remains easy to rotate without selecting the child."""
    window, vm = editor, editor.viewmodel
    assert window.bone_mode_buttons["chain_move"].isChecked()
    root, middle, tip = bones(window)
    window.bone_mode_buttons[scope].click()
    viewport = window.viewport
    before = vm.documents.animation.pose
    pivot = viewport.bone_transform_pivot()
    start = QPointF(300, 180)
    end = pivot + QPointF(0, 80)
    move_pointer(viewport, start.toPoint())
    assert viewport.cursor().shape() == Qt.CursorShape.BitmapCursor
    count = len(vm.documents.history.undo_stack)
    drag(viewport, start.toPoint(), end.toPoint())
    assert not vm.rig.error and vm.rig.selected == (middle,)
    after = vm.documents.animation.pose
    assert after.nodes[middle].world_matrix[4:] == pytest.approx((200, 160))
    assert transform_point(after.nodes[middle].world_matrix, 80, 0) == pytest.approx((200, 240))
    assert after.nodes[root].world_matrix == pytest.approx(before.nodes[root].world_matrix)
    expected = (200, 240) if scope == "chain_move" else (280, 160)
    assert after.nodes[tip].world_matrix[4:] == pytest.approx(expected)
    assert len(vm.documents.history.undo_stack) == count + 1
    vm.undo()
    assert (
        vm.documents.animation.pose.nodes[middle].world_matrix == before.nodes[middle].world_matrix
    )


@pytest.mark.parametrize("pair", [(0, 1), (1, 2)])
@pytest.mark.parametrize("reverse", [False, True])
def test_two_selected_chain_bodies_rotate_at_highest_selected_joint(editor, pair, reverse):
    """Ctrl-select two of three bones, then rotate their bodies without translating the chain."""
    window, vm = editor, editor.viewmodel
    keys = bones(window)
    selected = tuple(keys[i] for i in pair)
    if reverse:
        selected = selected[::-1]
    body = {keys[0]: QPoint(160, 180), keys[1]: QPoint(260, 180), keys[2]: QPoint(340, 180)}
    vm.rig.select(selected[0])
    QTest.mouseClick(
        window.viewport,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        body[selected[1]],
    )
    assert vm.rig.selected == selected
    window.bone_mode_buttons["chain_move"].click()
    before = vm.documents.animation.pose
    baseline = vm.documents.project
    top = keys[pair[0]]
    pivot = window.viewport.offset + QPointF(*before.nodes[top].world_matrix[4:])
    assert window.viewport.bone_transform_pivot() == pivot
    start = body[keys[1]]
    end = pivot + QPointF(0, start.x() - pivot.x())
    move_pointer(window.viewport, start)
    assert window.viewport.cursor().shape() == Qt.CursorShape.BitmapCursor
    count = len(vm.documents.history.undo_stack)
    drag(window.viewport, start, end.toPoint())
    assert not vm.rig.error and vm.rig.selected == selected
    after = vm.documents.animation.pose
    assert after.nodes[top].world_matrix[4:] == pytest.approx(before.nodes[top].world_matrix[4:])
    assert after.nodes[top].world_matrix[:2] == pytest.approx((0, 1))
    for index in range(pair[0] + 1, 3):
        parent, child = keys[index - 1], keys[index]
        assert after.nodes[child].world_matrix[4:] == pytest.approx(
            transform_point(after.nodes[parent].world_matrix, vm.rig.service.bone(parent).length, 0)
        )
        if child in selected:
            assert after.nodes[child].local.rotation == pytest.approx(
                before.nodes[child].local.rotation + 90
            )
        else:
            assert after.nodes[child].local == pytest.approx(before.nodes[child].local)
    if pair[0] == 1:
        assert after.nodes[keys[0]].world_matrix == before.nodes[keys[0]].world_matrix
    assert len(vm.documents.history.undo_stack) == count + 1
    vm.undo()
    assert vm.documents.project == baseline


def test_bone_resize_hover_drag_cancel_and_pan_cursors(editor):
    """Each handle advertises its direction; drag cursors latch and navigation takes precedence."""
    window = editor
    bones(window)
    viewport = window.viewport
    rect = viewport.bone_transform_bounds()
    expected = [
        Qt.CursorShape.SizeFDiagCursor,
        Qt.CursorShape.SizeVerCursor,
        Qt.CursorShape.SizeBDiagCursor,
        Qt.CursorShape.SizeHorCursor,
    ]
    for index, point in enumerate(transform_gizmo.handles(rect)[:8]):
        move_pointer(viewport, point.toPoint())
        assert viewport.cursor().shape() == expected[index % 4]
    start = transform_gizmo.handles(rect)[4].toPoint()
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
    move_pointer(viewport, QPoint(700, 400))
    assert viewport.cursor().shape() == Qt.CursorShape.SizeFDiagCursor
    QTest.keyClick(viewport, Qt.Key.Key_Escape)
    assert viewport._bone_transform is None
    move_pointer(viewport, QPoint(700, 400))
    assert viewport.cursor().shape() == Qt.CursorShape.CrossCursor
    QTest.keyPress(viewport, Qt.Key.Key_Space)
    assert viewport.cursor().shape() == Qt.CursorShape.OpenHandCursor
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=QPoint(700, 400))
    assert viewport.cursor().shape() == Qt.CursorShape.ClosedHandCursor
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=QPoint(700, 400))
    QTest.keyRelease(viewport, Qt.Key.Key_Space)


def test_shift_tip_rotation_snaps_and_escape_cancels_without_history(editor):
    """Direct joint rotation snaps to 15 degrees and cancelled drags never commit."""
    import math

    window, vm = editor, editor.viewmodel
    _, middle, _ = bones(window)
    viewport = window.viewport
    baseline = vm.documents.project
    start, end = QPoint(300, 180), QPoint(297, 204)
    drag(viewport, start, end, Qt.KeyboardModifier.ShiftModifier)
    matrix = vm.documents.animation.pose.nodes[middle].world_matrix
    assert matrix[:2] == pytest.approx((math.cos(math.radians(15)), math.sin(math.radians(15))))
    vm.undo()
    assert vm.documents.project == baseline
    count = len(vm.documents.history.undo_stack)
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
    move_pointer(viewport, end)
    assert vm.rig.pose.nodes[middle].world_matrix != matrix
    QTest.keyClick(viewport, Qt.Key.Key_Escape)
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=end)
    assert vm.documents.project == baseline
    assert len(vm.documents.history.undo_stack) == count


def test_ctrl_click_toggle_and_ctrl_drag_preserve_group(editor):
    """Ctrl toggles on a click but retains the clicked selection through a group drag."""
    window, vm = editor, editor.viewmodel
    root, middle, tip = bones(window)
    viewport = window.viewport
    QTest.mouseClick(
        viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, QPoint(340, 180)
    )
    assert vm.rig.selected == (middle, tip)
    QTest.mouseClick(
        viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, QPoint(340, 180)
    )
    assert vm.rig.selected == (middle,)
    QTest.mouseClick(
        viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, QPoint(340, 180)
    )
    drag(viewport, QPoint(260, 180), QPoint(284, 204), Qt.KeyboardModifier.ControlModifier)
    assert vm.rig.selected == (middle, tip)
    assert not vm.rig.error
    assert vm.documents.animation.pose.nodes[root].world_matrix[4:] == pytest.approx((100, 160))
    assert vm.documents.animation.pose.nodes[tip].world_matrix[4:] == pytest.approx((304, 184))


def test_context_options_and_visible_top_actions(editor, qtbot, monkeypatch, tmp_path):
    """Header controls follow tool context; actual Open and spin/checkbox clicks remain usable."""
    window, vm = editor, editor.viewmodel
    from rigora.presentation.views import main_window

    selected_paths = []
    chosen = tmp_path / "chosen.rigora"
    monkeypatch.setattr(main_window, "choose_open_file", lambda *args: (str(chosen), ""))
    monkeypatch.setattr(vm.project_io, "open", lambda path: selected_paths.append(path))
    QTest.mouseClick(window.main_tool_buttons["open"], Qt.MouseButton.LeftButton)
    assert selected_paths == [chosen]
    _, middle, tip = bones(window)
    assert window.bone_options.isVisible() and not window.selection_options.isVisible()
    assert window.minimum_joint_angle.value() == 30
    window.minimum_joint_angle.setFocus()
    window.minimum_joint_angle.selectAll()
    QTest.keyClicks(window.minimum_joint_angle, "90")
    QTest.keyClick(window.minimum_joint_angle, Qt.Key.Key_Return)
    assert vm.rig.service.bone(middle).extra["minimum_joint_angle"] == 90
    option = QStyleOptionSpinBox()
    window.minimum_joint_angle.initStyleOption(option)
    arrow = window.minimum_joint_angle.style().subControlRect(
        QStyle.ComplexControl.CC_SpinBox,
        option,
        QStyle.SubControl.SC_SpinBoxUp,
        window.minimum_joint_angle,
    )
    QTest.mouseClick(window.minimum_joint_angle, Qt.MouseButton.LeftButton, pos=arrow.center())
    assert vm.rig.service.bone(middle).extra["minimum_joint_angle"] == 91
    window.viewport.setFocus()
    vm.rig.select_many((middle, tip))
    assert window.minimum_joint_angle.prefix() == "≈"
    count = len(vm.documents.history.undo_stack)
    window.minimum_joint_angle.setFocus()
    window.minimum_joint_angle.selectAll()
    QTest.keyClicks(window.minimum_joint_angle, "30")
    QTest.keyClick(window.minimum_joint_angle, Qt.Key.Key_Return)
    assert all(vm.rig.service.bone(key).extra["minimum_joint_angle"] == 30 for key in (middle, tip))
    assert len(vm.documents.history.undo_stack) == count + 1
    QTest.mouseClick(window.wireframe_option, Qt.MouseButton.LeftButton)
    assert window.viewport.mesh_wireframe
    assert window.menuWidget().height() == window.titlebar.height() + window.main_tools.height()
    assert not window.plugin_workspace.toolbar.isVisible()
    qtbot.wait(10)
    assert window.docks["tools"].parentWidget().isAncestorOf(window.viewport)
    assert window.docks["tools"].height() >= window.viewport.height()
    for button in window.main_tool_buttons.values():
        assert button.isVisible() and button.height() >= 24
        assert window.main_tools.rect().contains(
            button.mapTo(window.main_tools, button.rect().center())
        )
    assert window.grab().save(str(tmp_path / "bone-options.png"))
    window.apply_theme("light")
    assert window.grab().save(str(tmp_path / "bone-options-light.png"))
    window.apply_theme("dark")
    vm.rig.set_tool("draw")
    assert not window.bone_options.isVisible() and window.context_hint.isVisible()
    window.command_actions["pan"].setChecked(True)
    window.toggle_pan()
    assert not window.wireframe_option.isVisible()
    window.navigate()
    window.set_composer_target("sprite")
    assert window.selection_options.isVisible() and not window.bone_options.isVisible()
    qtbot.wait(10)


def test_artwork_grips_toolbar_and_direct_bind_workflow(editor, qtbot, tmp_path):
    window, vm = editor, editor.viewmodel
    vm.open_project(Path("examples/image-import-example.rigora"))
    qtbot.waitUntil(lambda: bool(window.viewport.artwork.images), timeout=10000)
    mesh = vm.documents.project.scenes[0].meshes[0]
    owner = mesh.object_id
    window.set_composer_target("sprite")
    vm.scene.select((owner,))
    window.mesh_workspace.frame_artwork()
    viewport = window.viewport
    before = vm.documents.animation.pose
    rect = window.scene_workspace.transform_bounds()
    for index, point in enumerate(transform_gizmo.handles(rect)):
        move_pointer(viewport, point.toPoint())
        assert viewport.cursor().shape() == transform_gizmo.cursor(index, window.icons).shape()
    anchor = viewport.scene_point(rect.topLeft())
    start = transform_gizmo.handles(rect)[4]
    end = rect.topLeft() + (start - rect.topLeft()) * 1.25
    count = len(vm.documents.history.undo_stack)
    drag(viewport, start.toPoint(), end.toPoint())
    assert not vm.scene.error and len(vm.documents.history.undo_stack) == count + 1
    after = vm.documents.animation.pose
    assert after.nodes[owner].world_matrix != before.nodes[owner].world_matrix
    assert transform_point(after.nodes[owner].world_matrix, 0, 0) == pytest.approx(
        (anchor.x(), anchor.y()), abs=1.5
    )
    toolbox = window.findChild(QToolBar, "toolbox")
    from rigora.presentation.menu_labels import display_text

    visible = [display_text(a.text()) for a in toolbox.actions() if not a.isSeparator()]
    assert visible == [
        "Select & transform",
        "Pan canvas",
        "Draw vector shape",
        "Create character…",
        "Bone Editor…",
        "Spring Editor…",
        "Motion Pilot…",
        "Edit mesh",
    ]
    toolbar = window.main_tools
    buttons = window.main_tool_buttons
    order = toolbar.order()
    assert order.index("files") < order.index("history") < order.index("commands")
    palette_button = buttons["palette"]
    qtbot.wait(30)
    assert toolbar.rect().contains(palette_button.mapTo(toolbar, palette_button.rect().center()))
    window.show_bone_editor()
    dialog = window.bone_editor
    qtbot.addWidget(dialog)
    vm.rig.selected = ()
    dialog.bind_artwork()
    assert not vm.mesh.error and "Image bound" in dialog.status.text()
    dialog.preview()
    assert not dialog.preview_subdivision.isChecked()
    assert viewport.subdivision_pose is None
    vm.rig.select(vm.documents.project.scenes[0].skeletons[0].bones[-1].id)
    dialog.hide()
    assert window.grab().save(str(tmp_path / "unified-workspace.png"))


def test_ffd_rotation_grip_works_without_switching_to_rotate(mesh_window):
    """The separate rotation grip transforms selected FFD points while Move remains active."""
    window = mesh_window
    model, panel = window.viewmodel.mesh, window.mesh_panel
    window.mesh_workspace.activate_tool("control")
    assert model.active and model.tool == "control"
    model.controls = (0, 1, 3, 4)
    panel.control_mode.setCurrentText("Move")
    interaction = window.mesh_workspace.interaction
    frame = interaction.control_box(interaction.handles())
    for index, (point, _, _) in enumerate(frame[1]):
        move_pointer(window.viewport, point.toPoint())
        assert (
            window.viewport.cursor().shape()
            == transform_gizmo.cursor(index, window.icons, [p[0] for p in frame[1]]).shape()
        )
    start = frame[1][8][0]
    center = interaction.screen((frame[0].center().x(), frame[0].center().y()))
    vector = start - center
    end = center + QPointF(-vector.y(), vector.x())
    before = model.pose.meshes[model.mesh_id].positions
    count = len(model.document.history.undo_stack)
    drag(window.viewport, start.toPoint(), end.toPoint())
    assert not model.error
    assert panel.control_mode.currentText() == "Move"
    assert model.pose.meshes[model.mesh_id].positions != before
    assert len(model.document.history.undo_stack) == count + 1
    model.document.undo()
    assert model.pose.meshes[model.mesh_id].positions == before
