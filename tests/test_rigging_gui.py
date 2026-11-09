"""Real viewport rig gestures and contextual inspector commands share undoable services."""

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QImage, QMouseEvent, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from rigora.app.application import ApplicationInfo
from rigora.domain.entities import Constraint, SceneObject, Transform
from rigora.domain.geometry import transform_point
from rigora.infrastructure.preferences import PreferencesStore
from rigora.presentation.bone_shape import BoneShape
from rigora.presentation.viewmodels.main_window import MainWindowViewModel
from rigora.presentation.views.main_window import MainWindow


def move_pointer(widget, point):
    """Deliver Qt pointer input independently of desktop focus and OS cursor routing."""
    QApplication.sendEvent(
        widget,
        QMouseEvent(
            QMouseEvent.Type.MouseMove,
            QPointF(point),
            widget.mapToGlobal(point),
            Qt.MouseButton.NoButton,
            QApplication.mouseButtons(),
            QApplication.keyboardModifiers(),
        ),
    )


@pytest.fixture
def rig_window(qtbot, tmp_path):
    """Create an isolated editor without close prompts or persisted owner preferences."""
    model = MainWindowViewModel(
        ApplicationInfo(), preferences=PreferencesStore(tmp_path / "ui.json")
    )
    window = MainWindow(model)
    qtbot.addWidget(window, before_close_func=lambda w: setattr(w, "confirm_discard", lambda: True))
    window.resize(1600, 1000)
    window.show()
    model.new_project()
    qtbot.wait(1)
    window.viewport.fit_canvas()
    return window


def test_draw_select_move_endpoint_and_undo_from_viewport(rig_window, qtbot):
    window = rig_window
    vm, viewport = window.viewmodel, window.viewport
    window.command_actions["bone"].trigger()
    assert vm.rig.active and vm.rig.tool == "draw"
    start = QPoint(100, 80)
    end = QPoint(160, 80)
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
    move_pointer(viewport, end)
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=end)
    assert len(vm.rig.service.scene.skeletons[0].bones) == 2
    root = vm.rig.bone
    assert root.length > 0 and vm.documents.dirty
    vm.rig.set_tool("move")
    origin = (
        viewport.offset + QPointF(root.transform.x, root.transform.y) * viewport.zoom
    ).toPoint()
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=origin)
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=origin + QPoint(25, 20))
    assert vm.rig.bone.transform.x == pytest.approx(root.transform.x + 25 / viewport.zoom)
    window.command_actions["undo"].trigger()
    assert vm.rig.bone.transform == root.transform
    vm.rig.set_tool("length")
    tip = origin + QPoint(60, 0)
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=tip)
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=tip + QPoint(25, 0))
    assert vm.rig.bone.length > root.length
    window.rig_panel.name.setText("Arm.L")
    window.rig_panel.apply_bone()
    assert vm.rig.bone.name == "Arm.L"
    window.rig_panel.locked.setChecked(True)
    assert vm.rig.bone.locked and root.id in viewport.locked_bones
    window.rig_panel.locked.setChecked(False)
    window.rig_panel.visible.setChecked(False)
    assert not vm.rig.pose.nodes[root.id].visible


def test_needle_selection_tip_attachment_and_live_preview(rig_window):
    window = rig_window
    vm, viewport = window.viewmodel, window.viewport
    vm.rig.run(lambda s: s.create_bone((400, 400), (700, 400)))
    parent = vm.rig.bone
    vm.rig.select("")
    window.command_actions["navigate"].trigger()
    QApplication.processEvents()
    body = (viewport.offset + QPointF(460, 400) * viewport.zoom).toPoint()
    before = viewport.grab().toImage().pixelColor(body)
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=body)
    assert vm.rig.selected == (parent.id,)
    after = viewport.grab().toImage().pixelColor(body)
    assert abs(before.red() - before.green()) <= 12
    assert after.red() > after.green() * 1.5
    window.command_actions["bone"].trigger()
    vm.rig.select("")
    tip = (viewport.offset + QPointF(700, 400) * viewport.zoom).toPoint()
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=tip + QPoint(3, 0))
    assert vm.rig.selected == (parent.id,)
    move_pointer(viewport, tip + QPoint(20, 20))
    short = viewport.grab().toImage()
    move_pointer(viewport, tip + QPoint(80, 20))
    assert viewport.grab().toImage() != short
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=tip + QPoint(80, 20))
    child = vm.rig.bone
    assert child.parent_id == parent.id
    assert child.transform.x == pytest.approx(parent.length)
    assert child.transform.y == pytest.approx(0)
    window.command_actions["navigate"].trigger()
    assert vm.rig.tool == "select"
    count = len(vm.rig.service.scene.skeletons[0].bones)
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=body)
    assert len(vm.rig.service.scene.skeletons[0].bones) == count


def test_tip_attachment_uses_constrained_visible_parent(rig_window):
    window = rig_window
    vm, viewport = window.viewmodel, window.viewport
    vm.rig.run(lambda s: s.create_bone((400, 400), (700, 400)))
    parent = vm.rig.bone
    target = SceneObject(transform=Transform(x=650, y=300, rotation=30))
    rule = Constraint(owner_id=parent.id, target_id=target.id, kind="copy_transform")
    vm.rig.run(lambda s: s.commit("Place parent control", objects=(target,), constraints=(rule,)))
    window.command_actions["bone"].trigger()
    vm.rig.select("")
    tip = QPointF(*transform_point(vm.rig.pose.nodes[parent.id].world_matrix, parent.length, 0))
    screen = (viewport.offset + tip * viewport.zoom).toPoint()
    end = screen + QPoint(40, 30)
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=screen)
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=end)
    child = vm.rig.bone
    assert child.parent_id == parent.id
    assert child.transform.x == pytest.approx(parent.length)
    assert child.transform.y == pytest.approx(0, abs=1e-9)
    actual = transform_point(vm.rig.pose.nodes[child.id].world_matrix, child.length, 0)
    expected = viewport.scene_point(QPointF(end))
    assert actual == pytest.approx((expected.x(), expected.y()))


def test_svg_bone_root_silhouette_selection_and_replacement(qapp, tmp_path):
    """Align both SVG circles with bone endpoints and support a locally replaced SVG."""
    shape = BoneShape()
    root, tip = QPointF(100, 60), QPointF(250, 60)
    assert shape.contains(QPointF(95, 60), root, tip)
    assert shape.contains(QPointF(255, 60), root, tip)
    assert not shape.contains(QPointF(240, 70), root, tip)
    assert not shape.contains(QPointF(85, 30), root, tip)
    assert shape.contains(root, root, root)
    assert not shape.contains(root + QPointF(12, 0), root, root)
    image = QImage(300, 160, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    shape.draw(painter, root, tip)
    shape.draw(painter, root + QPointF(0, 60), tip + QPointF(0, 60), "#ef5350")
    painter.end()
    normal, selected = image.pixelColor(140, 60), image.pixelColor(140, 120)
    assert normal.alpha() == selected.alpha() == 255
    assert abs(normal.red() - normal.green()) < 12
    assert selected.red() > selected.green() * 1.5
    replacement = tmp_path / "bone.svg"
    replacement.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1536">'
        '<path d="M400 170 H624 V1402 H400 Z" fill="#ffffff"/></svg>'
    )
    assert BoneShape(replacement).contains(QPointF(240, 70), root, tip)


def test_invalid_custom_bone_svg_falls_back(qapp, tmp_path, caplog):
    """A damaged cosmetic asset must not prevent opening or interacting with a project."""
    replacement = tmp_path / "bone.svg"
    replacement.write_text("invalid SVG")
    shape = BoneShape(replacement)
    assert shape.contains(QPointF(130, 60), QPointF(100, 60), QPointF(250, 60))
    assert "using fallback" in caplog.text


@pytest.mark.parametrize("at_tip", [False, True])
def test_circle_cursor_snaps_and_attaches_at_either_joint(rig_window, at_tip):
    """Hover and authoring use the same snapped root/tip even when no bone is selected."""
    window = rig_window
    vm, viewport = window.viewmodel, window.viewport
    window.command_actions["bone"].trigger()
    move_pointer(viewport, QPoint(12, 12))
    assert viewport._rig_drag is None
    assert viewport.grab().toImage().pixelColor(18, 12).red() > 80
    vm.rig.run(lambda service: service.create_bone((400, 400), (700, 400)))
    parent = vm.rig.bone
    window.draw_bone()
    vm.rig.select("")
    joint = QPointF(700 if at_tip else 400, 400)
    screen = (viewport.offset + joint * viewport.zoom).toPoint()
    move_pointer(viewport, screen + QPoint(4, 3))
    assert viewport._draw_snap[0] == parent.id
    assert viewport._rig_cursor == joint
    assert viewport.cursor().shape() == Qt.CursorShape.BlankCursor
    viewport.zoom_at(1.4, QPointF(screen))
    assert viewport._rig_cursor == joint
    vm.rig.run(lambda service: service.update(parent.id, locked=True))
    move_pointer(viewport, screen + QPoint(3, 3))
    assert viewport._draw_snap is None
    vm.rig.run(lambda service: service.update(parent.id, locked=False, visible=False))
    move_pointer(viewport, screen + QPoint(4, 3))
    assert viewport._draw_snap is None
    vm.rig.run(lambda service: service.update(parent.id, visible=True))
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=screen + QPoint(4, 3))
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=screen + QPoint(40, 40))
    child = vm.rig.bone
    assert child.parent_id == parent.id
    assert child.transform.x == pytest.approx(parent.length if at_tip else 0)
    assert child.transform.y == pytest.approx(0)
    assert transform_point(vm.rig.pose.nodes[child.id].world_matrix, 0, 0) == pytest.approx(
        (joint.x(), joint.y())
    )


def test_alt_toggles_snap_during_hover_and_drag_and_drops_free_bone(rig_window):
    """Alt immediately restores raw pointer endpoints and removes parenting during a drag."""
    window = rig_window
    vm, viewport = window.viewmodel, window.viewport
    vm.rig.run(lambda service: service.create_bone((400, 400), (700, 400)))
    parent = vm.rig.bone
    vm.rig.run(lambda service: service.create_bone((1000, 400), (1200, 400)))
    target = vm.rig.bone
    window.command_actions["bone"].trigger()
    QApplication.processEvents()
    start = (viewport.offset + QPointF(700, 400) * viewport.zoom).toPoint() + QPoint(5, 3)
    end = (viewport.offset + QPointF(1000, 400) * viewport.zoom).toPoint() + QPoint(4, 3)
    move_pointer(viewport, start)
    snapped = viewport.grab().toImage()
    QTest.keyPress(viewport, Qt.Key.Key_Control)
    assert viewport._draw_snap[0] == parent.id
    QTest.keyRelease(viewport, Qt.Key.Key_Control)
    QTest.keyPress(viewport, Qt.Key.Key_Alt)
    assert viewport._draw_snap is None
    assert viewport._rig_cursor == viewport.scene_point(QPointF(start))
    assert viewport.grab().toImage() != snapped
    QTest.keyRelease(viewport, Qt.Key.Key_Alt)
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
    assert vm.rig.selected == (parent.id,)
    move_pointer(viewport, end)
    assert viewport._draw_snap[0] == target.id
    assert viewport._rig_cursor == QPointF(1000, 400)
    QTest.keyPress(viewport, Qt.Key.Key_Alt)
    assert not vm.rig.selected
    assert viewport._draw_snap is None
    assert viewport._rig_drag[2] == viewport.scene_point(QPointF(start))
    assert viewport._rig_cursor == viewport.scene_point(QPointF(end))
    QTest.keyRelease(viewport, Qt.Key.Key_Alt)
    assert vm.rig.selected == (parent.id,)
    assert viewport._rig_cursor == QPointF(1000, 400)
    QTest.keyPress(viewport, Qt.Key.Key_Alt)
    QTest.mouseRelease(
        viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.AltModifier, pos=end
    )
    QTest.keyRelease(viewport, Qt.Key.Key_Alt)
    free_bone = vm.rig.bone
    assert vm.rig.service.bone(free_bone.parent_id).extra.get("rig_root")
    node = vm.rig.pose.nodes[free_bone.id]
    raw_start, raw_end = viewport.scene_point(QPointF(start)), viewport.scene_point(QPointF(end))
    assert transform_point(node.world_matrix, 0, 0) == pytest.approx((raw_start.x(), raw_start.y()))
    assert transform_point(node.world_matrix, node.length, 0) == pytest.approx(
        (raw_end.x(), raw_end.y())
    )
    window.command_actions["undo"].trigger()
    assert free_bone.id not in vm.rig.pose.nodes


def test_draw_endpoint_snaps_without_changing_existing_parentage(rig_window):
    """A released tip aligns exactly to a target joint while existing hierarchy stays intact."""
    window = rig_window
    vm, viewport = window.viewmodel, window.viewport
    vm.rig.run(lambda service: service.create_bone((400, 400), (700, 400)))
    parent = vm.rig.bone
    vm.rig.run(lambda service: service.create_bone((1000, 400), (1200, 400)))
    target = vm.rig.bone
    window.command_actions["bone"].trigger()
    start = (viewport.offset + QPointF(700, 400) * viewport.zoom).toPoint()
    end = (viewport.offset + QPointF(1000, 400) * viewport.zoom).toPoint() + QPoint(4, 3)
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=end)
    child = vm.rig.bone
    assert child.parent_id == parent.id
    node = vm.rig.pose.nodes[child.id]
    assert transform_point(node.world_matrix, node.length, 0) == pytest.approx((1000, 400))
    assert vm.rig.service.bone(vm.rig.service.bone(target.id).parent_id).extra.get("rig_root")


def test_bone_remains_visible_and_movable_outside_camera(rig_window):
    """Negative scene coordinates stay visible, selectable and undoable outside the frame."""
    window = rig_window
    vm, viewport = window.viewmodel, window.viewport
    vm.rig.run(lambda service: service.create_bone((-80, 50), (-20, 50)))
    bone = vm.rig.bone
    viewport.zoom, viewport.offset = 1, QPointF(200, 100)
    viewport.grid_visible = False
    vm.rig.set_tool("move")
    body = viewport.grab().toImage().pixelColor(140, 150)
    assert body.red() > body.green() * 1.5
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=QPoint(140, 150))
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=QPoint(110, 160))
    assert vm.rig.bone.transform.x == pytest.approx(-110)
    assert vm.rig.bone.transform.y == pytest.approx(60)
    assert vm.rig.bone.length == bone.length
    window.command_actions["undo"].trigger()
    assert vm.rig.bone.transform == bone.transform


def test_live_chain_pose_anchors_root_and_commits_once_or_cancels(rig_window):
    """Dragging updates actual geometry before release, while Escape leaves authoring unchanged."""
    window = rig_window
    vm, viewport = window.viewmodel, window.viewport
    vm.rig.run(lambda s: s.create_bone((400, 400), (600, 400)))
    root = vm.rig.bone.id
    vm.rig.run(lambda s: s.create_bone((600, 400), (800, 400), root))
    middle = vm.rig.bone.id
    vm.rig.run(lambda s: s.create_bone((800, 400), (1000, 400), middle))
    tip = vm.rig.bone.id
    window.command_actions["navigate"].trigger()
    start = (viewport.offset + QPointF(900, 400) * viewport.zoom).toPoint()
    end = start + QPoint(-30, 50)
    original = vm.documents.project
    count = len(vm.documents.history.undo_stack)
    original_pose = vm.rig.pose
    for commit in (False, True):
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
        move_pointer(viewport, end)
        assert vm.documents.project is original
        assert len(vm.documents.history.undo_stack) == count
        assert vm.rig.pose.nodes[tip].world_matrix != original_pose.nodes[tip].world_matrix
        assert transform_point(vm.rig.pose.nodes[root].world_matrix, 0, 0) == pytest.approx(
            (400, 400)
        )
        if commit:
            QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=end)
            assert len(vm.documents.history.undo_stack) == count + 1
            vm.undo()
        else:
            QTest.keyClick(viewport, Qt.Key.Key_Escape)
            QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=end)
        assert vm.documents.project == original
        assert vm.rig.pose.nodes[tip].world_matrix == original_pose.nodes[tip].world_matrix


def test_marquee_multi_bone_move_is_live_and_does_not_collapse_selection(rig_window):
    """A drag rectangle selects several branches and Move translates them together in one step."""
    window = rig_window
    vm, viewport = window.viewmodel, window.viewport
    vm.rig.run(lambda s: s.create_bone((400, 300), (650, 300)))
    first = vm.rig.bone.id
    vm.rig.run(lambda s: s.create_bone((400, 600), (650, 600)))
    second = vm.rig.bone.id
    window.command_actions["navigate"].trigger()
    start = (viewport.offset + QPointF(350, 250) * viewport.zoom).toPoint()
    end = (viewport.offset + QPointF(700, 650) * viewport.zoom).toPoint()
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
    move_pointer(viewport, end)
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=end)
    assert set(vm.rig.selected) == {first, second}
    window.command_actions["move"].trigger()
    point = (viewport.offset + QPointF(500, 300) * viewport.zoom).toPoint()
    baseline = vm.documents.project
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=point)
    move_pointer(viewport, point + QPoint(20, 15))
    assert set(vm.rig.selected) == {first, second}
    for key, y in ((first, 300), (second, 600)):
        assert transform_point(vm.rig.pose.nodes[key].world_matrix, 0, 0) == pytest.approx(
            (400 + 20 / viewport.zoom, y + 15 / viewport.zoom)
        )
    assert vm.documents.project is baseline
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=point + QPoint(20, 15))
    vm.undo()
    assert vm.documents.project == baseline


def test_templates_ik_target_fk_switch_constraints_and_tab_state(rig_window, tmp_path):
    window = rig_window
    vm, panel = window.viewmodel, window.rig_panel
    vm.rig.run(lambda service: service.template("Chain"))
    root = vm.rig.bone.id
    vm.rig.run(lambda service: service.add_constraint(root, "two_bone_ik"))
    rule = vm.rig.service.scene.constraints[0]
    assert panel.constraints.count() == 1 and not vm.rig.pose.warnings
    vm.rig.set_tool("select")
    viewport = window.viewport
    QApplication.processEvents()
    position = (
        viewport.offset
        + QPointF(*vm.rig.pose.nodes[rule.target_id].world_matrix[4:]) * viewport.zoom
    ).toPoint()
    old_x = vm.rig.pose.nodes[rule.target_id].world_matrix[4]
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=position)
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=position + QPoint(15, 0))
    assert vm.rig.pose.nodes[rule.target_id].world_matrix[4] == pytest.approx(
        old_x + 15 / viewport.zoom
    )
    panel.target_x.setValue(500)
    panel.target_y.setValue(320)
    vm.rig.run(lambda service: service.move_target(rule.target_id, 500, 320))
    assert vm.rig.pose.nodes[rule.target_id].world_matrix[4:] == (500, 320)
    panel.ik_mode.setCurrentText("fk")
    panel.apply_constraint()
    assert vm.rig.service.scene.constraints[0].parameters["mode"] == "fk"
    first = vm.documents
    vm.save_project(tmp_path / "rig.rigora")
    assert not first.dirty
    vm.new_project("Other")
    assert not vm.rig.active and not vm.rig.selected
    vm.activate_project(0)
    assert vm.rig.active and vm.rig.bone.id == root
    assert not first.dirty
    window.rig_workspace.set_mode(False)
    assert window.command_actions["play"].isEnabled()


def test_rig_material_icons_follow_dark_light_theme_changes(rig_window):
    from PySide6.QtWidgets import QAbstractButton

    window = rig_window
    button = window.rig_panel.tool_buttons["select"]
    before = button.icon().pixmap(20, 20).toImage()
    window.viewmodel.set_theme("light")
    assert button.icon().pixmap(20, 20).toImage() != before
    for control in window.rig_panel.findChildren(QAbstractButton):
        name = control.property("materialIcon")
        if name:
            assert (
                control.icon().pixmap(20, 20).toImage()
                == window.icons.icon(name).pixmap(20, 20).toImage()
            )
