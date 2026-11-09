"""Real pointer gestures for constrained drawing, oriented resizing and movable artwork pivots."""

import math
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from test_roots_soft_drag_gui import drag, pointer
from test_roots_soft_drag_gui import editor as root_editor

from rigora.application_services.appearance import AppearanceService
from rigora.application_services.scene_editing import SceneEditingService
from rigora.domain.geometry import transform_point
from rigora.presentation import transform_gizmo

pytestmark = pytest.mark.gui


@pytest.fixture
def editor(qtbot, tmp_path, monkeypatch):
    """Use real input and artwork with the unrelated library poster loader isolated."""
    yield from root_editor.__wrapped__(qtbot, tmp_path, monkeypatch)


@pytest.mark.parametrize(
    "mods,size,origin",
    [
        (Qt.KeyboardModifier.NoModifier, (90, 40), (160, 140)),
        (Qt.KeyboardModifier.ShiftModifier, (90, 90), (160, 140)),
        (Qt.KeyboardModifier.AltModifier, (180, 80), (70, 100)),
        (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.AltModifier, (180, 180), (70, 50)),
    ],
)
@pytest.mark.parametrize("reverse", (False, True))
def test_draw_modifiers_match_live_preview_and_committed_svg(editor, mods, size, origin, reverse):
    """Shift/Alt combine in every quadrant, and preview and committed geometry agree."""
    viewport, vm = editor.viewport, editor.viewmodel
    viewport.zoom, viewport.offset = 1, QPointF(20, 30)
    editor.command_actions["draw_shape"].trigger()
    a, b = QPointF(160, 140), QPointF(250, 180)
    if reverse:
        a, b = b, a
    pointer(viewport, QMouseEvent.Type.MouseButtonPress, a + viewport.offset, mods)
    pointer(viewport, QMouseEvent.Type.MouseMove, b + viewport.offset, mods)
    rect = editor.shape_workspace.rectangle()
    assert (rect.width(), rect.height()) == size
    if not reverse:
        assert rect.topLeft().toTuple() == origin
    before = len(vm.documents.history.undo_stack)
    pointer(viewport, QMouseEvent.Type.MouseButtonRelease, b + viewport.offset, mods)
    mesh = vm.documents.animation.pose.meshes[vm.mesh.mesh_id]
    node = vm.documents.animation.pose.nodes[mesh.object_id]
    points = [QPointF(*transform_point(node.world_matrix, *p)) for p in mesh.positions]
    actual = transform_gizmo.bounds(points, padding=0)
    assert actual == rect
    assert (node.local.pivot_x, node.local.pivot_y) == (size[0] / 2, size[1] / 2)
    assert len(vm.documents.history.undo_stack) == before + 1


def shape(editor, rotation=0):
    """Prepare one selected shape in a predictable viewport without specialized tool modes."""
    vm, viewport = editor.viewmodel, editor.viewport
    shapes = AppearanceService(vm.documents)
    mesh = shapes.create_shape("rectangle", 180, 120, 200, 120)
    owner = str(shapes.mesh(mesh).object_id)
    SceneEditingService(vm.documents).set_transform(owner, rotation=rotation)
    vm.changed.emit()
    editor.scene_workspace.select_entries((owner,))
    editor.selection_properties.ratio.setChecked(False)
    viewport.zoom, viewport.offset = 1, QPointF(20, 30)
    return owner


@pytest.mark.parametrize("handle", (1, 3, 5, 7))
def test_off_center_side_handle_changes_only_its_own_axis(editor, handle):
    """Off-center hit tolerance never converts small perpendicular motion into huge scaling."""
    owner = shape(editor, rotation=37)
    vm, work = editor.viewmodel, editor.scene_workspace
    rect, mapping, _ = work.transform_frame()
    assert mapping is not None
    local = transform_gizmo.handles(rect)[handle]
    offset = QPointF(2, 3)
    start = mapping.map(local + offset)
    movement = QPointF(
        40 if handle == 3 else -40 if handle == 7 else 17,
        24 if handle == 5 else -24 if handle == 1 else 13,
    )
    end = mapping.map(local + offset + movement)
    before = vm.documents.animation.pose.nodes[owner]
    count = len(vm.documents.history.undo_stack)
    drag(editor.viewport, start, end)
    assert not vm.scene.error
    after = vm.documents.animation.pose.nodes[owner]
    horizontal = handle in (3, 7)
    assert (after.local.scale_y if horizontal else after.local.scale_x) == pytest.approx(1)
    assert (after.local.scale_x if horizontal else after.local.scale_y) > 1.1
    opposite = transform_gizmo.handles(rect)[(handle + 4) % 8]
    assert transform_point(after.world_matrix, *opposite.toTuple()) == pytest.approx(
        transform_point(before.world_matrix, *opposite.toTuple())
    )
    assert len(vm.documents.history.undo_stack) == count + 1


def test_alt_resize_is_centered_and_modifiers_update_without_pointer_motion(editor):
    """Alt can change a live gesture's anchor without adding edits or restarting the drag."""
    owner = shape(editor)
    work, viewport, vm = editor.scene_workspace, editor.viewport, editor.viewmodel
    rect, mapping, _ = work.transform_frame()
    start = transform_gizmo.handles(rect, mapping)[3]
    end = start + QPointF(40, 0)
    pointer(viewport, QMouseEvent.Type.MouseButtonPress, start)
    pointer(viewport, QMouseEvent.Type.MouseMove, end)
    first = vm.scene.preview.nodes[owner].local.scale_x
    QTest.keyPress(viewport, Qt.Key.Key_Alt)
    assert vm.scene.preview.nodes[owner].local.scale_x > first
    old_center = transform_point(vm.documents.animation.pose.nodes[owner].world_matrix, 100, 60)
    assert transform_point(vm.scene.preview.nodes[owner].world_matrix, 100, 60) == pytest.approx(
        old_center
    )
    pointer(viewport, QMouseEvent.Type.MouseButtonRelease, end, Qt.KeyboardModifier.AltModifier)
    QTest.keyRelease(viewport, Qt.Key.Key_Alt)
    assert vm.documents.animation.pose.nodes[owner].local.scale_y == 1


def test_drawing_modifier_keys_update_without_pointer_motion(editor):
    """The actual Shift/Alt key lifecycle updates guides and Escape leaves no partial shape."""
    viewport = editor.viewport
    viewport.zoom, viewport.offset = 1, QPointF()
    editor.command_actions["draw_shape"].trigger()
    pointer(viewport, QMouseEvent.Type.MouseButtonPress, QPointF(160, 140))
    pointer(viewport, QMouseEvent.Type.MouseMove, QPointF(250, 180))

    def key(kind, code, modifiers):
        """Describe held keys directly; QTest's modifier argument synthesizes extra releases."""
        QApplication.sendEvent(viewport, QKeyEvent(kind, code, modifiers))

    key(QEvent.Type.KeyPress, Qt.Key.Key_Shift, Qt.KeyboardModifier.ShiftModifier)
    assert editor.shape_workspace.rectangle().size().toTuple() == (90, 90)
    key(
        QEvent.Type.KeyPress,
        Qt.Key.Key_Alt,
        Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.AltModifier,
    )
    assert editor.shape_workspace.rectangle() == QRectF(70, 50, 180, 180)
    key(QEvent.Type.KeyRelease, Qt.Key.Key_Shift, Qt.KeyboardModifier.AltModifier)
    assert editor.shape_workspace.rectangle() == QRectF(70, 100, 180, 80)
    key(QEvent.Type.KeyRelease, Qt.Key.Key_Alt, Qt.KeyboardModifier.NoModifier)
    assert editor.shape_workspace.rectangle() == QRectF(160, 140, 90, 40)
    QTest.keyClick(viewport, Qt.Key.Key_Escape)
    assert not editor.viewmodel.documents.project.scenes[0].objects


def test_shift_alt_side_resize_preserves_ratio_about_pivot(editor):
    """Shift constrains a side drag and Alt keeps its custom reference point anchored."""
    owner = shape(editor, rotation=37)
    work, vm = editor.scene_workspace, editor.viewmodel
    rect, mapping, _ = work.transform_frame()
    start = transform_gizmo.handles(rect, mapping)[3]
    end = mapping.map(transform_gizmo.handles(rect)[3] + QPointF(35, 17))
    pivot = work.pivot_point(work.transform_frame())
    drag(
        editor.viewport,
        start,
        end,
        Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.AltModifier,
    )
    assert not vm.scene.error
    node = vm.documents.animation.pose.nodes[owner]
    assert node.local.scale_x == pytest.approx(node.local.scale_y)
    assert node.local.scale_x > 1.2
    assert (work.pivot_point(work.transform_frame()) - pivot).manhattanLength() < 1e-6


def test_resize_grip_at_scene_origin_still_drags(editor):
    """A valid pointer position of (0, 0) must never be confused with an absent gesture."""
    owner = shape(editor)
    vm, work = editor.viewmodel, editor.scene_workspace
    SceneEditingService(vm.documents).set_transform(owner, x=-200, y=-60)
    vm.changed.emit()
    rect, mapping, _ = work.transform_frame()
    start = transform_gizmo.handles(rect, mapping)[3]
    assert editor.viewport.scene_point(start).isNull()
    drag(editor.viewport, start, start + QPointF(40, 0))
    assert vm.documents.animation.pose.nodes[owner].local.scale_x == pytest.approx(1.2)


def test_pivot_drag_keeps_artwork_fixed_then_controls_rotation_and_undo(editor, qtbot):
    """The pivot moves independently, survives rotation, and can be reset to image center."""
    owner = shape(editor, rotation=25)
    work, viewport, vm = editor.scene_workspace, editor.viewport, editor.viewmodel
    before = vm.documents.project
    matrix = vm.documents.animation.pose.nodes[owner].world_matrix
    pivot = work.pivot_point(work.transform_frame())
    target = pivot + QPointF(55, 45)
    count = len(vm.documents.history.undo_stack)
    drag(viewport, pivot + QPointF(2, 1), target + QPointF(2, 1))
    assert not vm.scene.error
    assert vm.documents.animation.pose.nodes[owner].world_matrix == pytest.approx(matrix)
    assert (work.pivot_point(work.transform_frame()) - target).manhattanLength() < 1e-7
    assert len(vm.documents.history.undo_stack) == count + 1
    vm.undo()
    assert vm.documents.project == before
    vm.redo()
    rect, mapping, _ = work.transform_frame()
    start = transform_gizmo.handles(rect, mapping)[8]
    vector = start - target
    angle = math.radians(40)
    end = target + QPointF(
        vector.x() * math.cos(angle) - vector.y() * math.sin(angle),
        vector.x() * math.sin(angle) + vector.y() * math.cos(angle),
    )
    drag(viewport, start, end)
    assert not vm.scene.error
    assert (work.pivot_point(work.transform_frame()) - target).manhattanLength() < 1e-6
    assert vm.documents.animation.pose.nodes[owner].local.rotation == pytest.approx(65)
    Path("build/shape-transform-review").mkdir(parents=True, exist_ok=True)
    qtbot.waitUntil(lambda: bool(viewport.artwork.vectors), timeout=10000)
    editor.grab().save("build/shape-transform-review/pivot.png")
    work.center_pivot()
    node = vm.documents.animation.pose.nodes[owner]
    assert (node.local.pivot_x, node.local.pivot_y) == pytest.approx((100, 60))


def test_gizmo_click_and_cancel_make_no_change(editor):
    """Clicking a grip or cancelling a pivot preview never changes geometry or history."""
    shape(editor, rotation=37)
    work, viewport, vm = editor.scene_workspace, editor.viewport, editor.viewmodel
    before, count = vm.documents.project, len(vm.documents.history.undo_stack)
    rect, mapping, _ = work.transform_frame()
    start = transform_gizmo.handles(rect, mapping)[3]
    drag(viewport, start, start)
    assert vm.documents.project == before and len(vm.documents.history.undo_stack) == count

    pivot = work.pivot_point(work.transform_frame())
    pointer(viewport, QMouseEvent.Type.MouseButtonPress, pivot)
    pointer(viewport, QMouseEvent.Type.MouseMove, pivot + QPointF(30, 20))
    QTest.keyClick(viewport, Qt.Key.Key_Escape)
    assert vm.documents.project == before and len(vm.documents.history.undo_stack) == count


@pytest.mark.parametrize("locked", (True, False))
@pytest.mark.parametrize("handle", (1, 3, 5, 7))
def test_ratio_lock_applies_to_rotated_object_resize_handles(editor, locked, handle):
    """The property padlock constrains side grips, with one reversible release-time edit."""
    owner = shape(editor, rotation=37)
    editor.selection_properties.ratio.setChecked(locked)
    work, vm = editor.scene_workspace, editor.viewmodel
    rect, mapping, _ = work.transform_frame()
    local = transform_gizmo.handles(rect)[handle]
    movement = QPointF(
        35 if handle == 3 else -35 if handle == 7 else 12,
        25 if handle == 5 else -25 if handle == 1 else 9,
    )
    count = len(vm.documents.history.undo_stack)
    drag(editor.viewport, mapping.map(local), mapping.map(local + movement))
    assert not vm.scene.error
    node = vm.documents.animation.pose.nodes[owner]
    if locked:
        assert node.local.scale_x == pytest.approx(node.local.scale_y)
    else:
        assert (node.local.scale_y if handle in (3, 7) else node.local.scale_x) == pytest.approx(1)
    assert max(node.local.scale_x, node.local.scale_y) > 1.1
    assert len(vm.documents.history.undo_stack) == count + 1


@pytest.mark.parametrize("free", (False, True))
def test_pivot_snaps_to_all_bounds_references_and_alt_bypasses(editor, free):
    """Every corner, edge midpoint and center can be reached and grabbed again after snapping."""
    owner = shape(editor, rotation=37)
    work, vm, viewport = editor.scene_workspace, editor.viewmodel, editor.viewport
    viewport.zoom = 0.65
    rect, mapping, _ = work.transform_frame()
    targets = transform_gizmo.handles(rect, mapping)[:8] + [mapping.map(rect.center())]
    matrix = vm.documents.animation.pose.nodes[owner].world_matrix
    modifiers = Qt.KeyboardModifier.AltModifier if free else Qt.KeyboardModifier.NoModifier
    for target in targets:
        start = work.pivot_point(work.transform_frame())
        near = target + QPointF(5, 3)
        drag(viewport, start, near, modifiers)
        assert not vm.scene.error
        node = vm.documents.animation.pose.nodes[owner]
        assert node.world_matrix == pytest.approx(matrix)
        actual = transform_point(node.world_matrix, node.local.pivot_x, node.local.pivot_y)
        expected = viewport.scene_point(near if free else target)
        assert actual == pytest.approx(expected.toTuple())


def test_pivot_alt_transition_changes_snap_without_mouse_movement(editor):
    """Modifier-only previews switch between the nearest corner and the exact held pointer."""
    owner = shape(editor)
    work, viewport, vm = editor.scene_workspace, editor.viewport, editor.viewmodel
    rect, mapping, _ = work.transform_frame()
    target = mapping.map(rect.topLeft())
    start = work.pivot_point(work.transform_frame())
    near = target + QPointF(5, 3)
    pointer(viewport, QMouseEvent.Type.MouseButtonPress, start)
    pointer(viewport, QMouseEvent.Type.MouseMove, near)
    assert (work.pivot_point(work.transform_frame()) - target).manhattanLength() < 1e-6
    QApplication.sendEvent(
        viewport, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Alt, Qt.KeyboardModifier.AltModifier)
    )
    assert (work.pivot_point(work.transform_frame()) - near).manhattanLength() < 1e-6
    QApplication.sendEvent(
        viewport, QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Alt, Qt.KeyboardModifier.NoModifier)
    )
    assert (work.pivot_point(work.transform_frame()) - target).manhattanLength() < 1e-6
    pointer(viewport, QMouseEvent.Type.MouseButtonRelease, near)
    assert not vm.scene.error and vm.documents.animation.pose.nodes[
        owner
    ].local.pivot_x == pytest.approx(0)
