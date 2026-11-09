"""Actual pointer routing for protected roots, image bone drawing and area deformation."""

import math
from dataclasses import replace

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from test_image_rigging_and_soft_drag import image_bytes
from test_workspace_redesign_gui import editor as workspace_editor

from rigora.application_services.deformation import deformation_presets
from rigora.application_services.image_rigging import ImageRigService
from rigora.application_services.rigging import RigService
from rigora.domain.geometry import transform_point

pytestmark = pytest.mark.gui


@pytest.fixture
def editor(qtbot, tmp_path, monkeypatch):
    """Isolate gestures from unrelated asynchronous content-poster decoding."""
    from rigora.presentation.widgets.workspace_panels import ContentShelf

    monkeypatch.setattr(ContentShelf, "load_thumbnails", lambda *_: None)
    yield from workspace_editor.__wrapped__(qtbot, tmp_path)


def pointer(viewport, kind, position, modifiers=Qt.KeyboardModifier.NoModifier):
    """Send a real viewport event with explicit buttons, including headless platforms."""
    button = (
        Qt.MouseButton.NoButton if kind == QMouseEvent.Type.MouseMove else Qt.MouseButton.LeftButton
    )
    buttons = (
        Qt.MouseButton.NoButton
        if kind == QMouseEvent.Type.MouseButtonRelease
        else Qt.MouseButton.LeftButton
    )
    event = QMouseEvent(kind, position, position, button, buttons, modifiers)
    QApplication.sendEvent(viewport, event)


def drag(viewport, start, end, modifiers=Qt.KeyboardModifier.NoModifier):
    """Exercise press, live preview and release through all installed event filters."""
    pointer(viewport, QMouseEvent.Type.MouseButtonPress, start, modifiers)
    pointer(viewport, QMouseEvent.Type.MouseMove, end, modifiers)
    pointer(viewport, QMouseEvent.Type.MouseButtonRelease, end, modifiers)


def test_draw_single_image_uses_automatic_mesh_binding(editor):
    vm, viewport = editor.viewmodel, editor.viewport
    service = ImageRigService(vm.documents)
    mesh_id = service.import_image_bytes("Character.svg", image_bytes())
    vm.changed.emit()
    vm.mesh.select_mesh(mesh_id)
    editor.draw_bone()
    viewport.zoom, viewport.offset = 0.6, QPointF(-200, -50)
    count = len(vm.documents.history.undo_stack)
    drag(viewport, QPointF(300, 160), QPointF(390, 160), Qt.KeyboardModifier.AltModifier)
    assert not vm.rig.error
    assert any(d.owner_id == mesh_id and d.kind == "skinning" for d in service.scene.deformers)
    assert len(vm.documents.history.undo_stack) == count + 1
    assert len(service.scene.characters) == 1


@pytest.mark.parametrize("ffd", (False, True))
def test_soft_drag_moves_area_smoothly_with_one_undo_and_escape(editor, ffd):
    vm, viewport = editor.viewmodel, editor.viewport
    service = ImageRigService(vm.documents)
    mesh_id = service.import_image_bytes("Character.svg", image_bytes())
    vm.changed.emit()
    vm.mesh.select_mesh(mesh_id)
    editor.mesh_workspace.activate_tool("control" if ffd else "vertex")
    if ffd:
        vm.mesh.run(lambda s: s.add(mesh_id, deformation_presets()[0]))
        vm.mesh.stage_id = service.scene.deformers[0].id
    else:
        mesh = service.mesh(mesh_id)
        service.replace_mesh(
            replace(
                mesh,
                vertices=tuple(replace(v, protected=i == 0) for i, v in enumerate(mesh.vertices)),
            )
        )
        vm.changed.emit()
    editor.toggle_soft_drag(True)
    interaction = editor.mesh_workspace.interaction
    viewport.zoom, viewport.offset = 0.6, QPointF(-200, -50)
    interaction.soft_radius = 140
    center = interaction.handles()[0][2] if ffd else interaction.points()[6]
    start = center + QPointF(5, 6)
    end = start + QPointF(30, 18)
    baseline, count = vm.documents.project, len(vm.documents.history.undo_stack)
    pointer(viewport, QMouseEvent.Type.MouseButtonPress, start)
    pointer(viewport, QMouseEvent.Type.MouseMove, end)
    once = dict(vm.mesh.preview_values)
    assert len(once) > 2 and any(value for value in once.values())
    pointer(viewport, QMouseEvent.Type.MouseMove, end)
    assert vm.mesh.preview_values == once
    pointer(viewport, QMouseEvent.Type.MouseButtonRelease, end)
    assert not vm.mesh.error
    assert len(vm.documents.history.undo_stack) == count + 1
    vm.undo()
    assert vm.documents.project == baseline
    pointer(viewport, QMouseEvent.Type.MouseButtonPress, start)
    pointer(viewport, QMouseEvent.Type.MouseMove, end)
    QTest.keyClick(viewport, Qt.Key.Key_Escape)
    assert vm.documents.project == baseline and not vm.mesh.preview_values


def test_soft_drag_toolbar_render_and_tab_metadata_isolation(editor, qtbot):
    """The controls fit the editor and project tabs preserve internal origin metadata."""
    from pathlib import Path

    vm, viewport = editor.viewmodel, editor.viewport
    service = ImageRigService(vm.documents)
    mesh_id = service.import_image_bytes("Character.svg", image_bytes())
    service.draw_bone(mesh_id, (900, 540), (980, 540))
    character = service.scene.characters[0]
    RigService(vm.documents).move_origin(820, 600, character.id, free=True)
    vm.changed.emit()
    vm.mesh.select_mesh(mesh_id)
    editor.mesh_workspace.activate_tool("vertex")
    editor.toggle_soft_drag(True)
    qtbot.waitUntil(lambda: bool(viewport.artwork.vectors), timeout=10000)
    editor.mesh_workspace.frame_artwork()
    assert editor.mesh_drag_options.isVisible()
    assert editor.soft_drag_radius.isEnabled()
    assert editor.soft_drag_button.isChecked()
    pointer(
        viewport,
        QMouseEvent.Type.MouseMove,
        QPointF(viewport.width() * 0.58, viewport.height() * 0.46),
    )
    qtbot.wait(1)
    # Native grab exercises the real paint overlays, not a synthetic UI mockup.
    Path("build/root-soft-review").mkdir(parents=True, exist_ok=True)
    editor.grab().save("build/root-soft-review/soft-drag.png")
    vm.new_project()
    editor.cycle_project(-1)
    editor.object_edit.enter(character.id)
    assert RigService(vm.documents).origin(character.id) == (820, 600)


@pytest.mark.parametrize("soft", (False, True))
def test_soft_drag_follows_pointer_on_a_rotated_skinned_image(editor, soft):
    """Skinning must not rotate or scale a user's screen-space drag a second time."""
    vm, viewport = editor.viewmodel, editor.viewport
    service, rig = ImageRigService(vm.documents), RigService(vm.documents)
    mesh_id = service.import_image_bytes("Character.svg", image_bytes())
    bone = service.draw_bone(mesh_id, (900, 540), (1000, 540))
    rig.update(bone, transform=replace(rig.bone(bone).transform, rotation=90))
    vm.changed.emit()
    vm.mesh.select_mesh(mesh_id)
    editor.mesh_workspace.activate_tool("vertex")
    if soft:
        editor.toggle_soft_drag(True)
    else:
        vm.mesh.stage_id = vm.mesh.service.add(mesh_id, deformation_presets()[0])
        vm.changed.emit()
    viewport.zoom, viewport.offset = 0.6, QPointF(-150, -30)
    interaction = editor.mesh_workspace.interaction
    index = len(service.mesh(mesh_id).vertices) // 2
    start = QPointF(interaction.points()[index])
    pointer(viewport, QMouseEvent.Type.MouseButtonPress, start)
    pointer(viewport, QMouseEvent.Type.MouseMove, start + QPointF(20, 0))
    after = interaction.points()[index]
    assert after.x() - start.x() == pytest.approx(20, abs=0.01)
    assert after.y() - start.y() == pytest.approx(0, abs=0.01)
    QTest.keyClick(viewport, Qt.Key.Key_Escape)


@pytest.mark.parametrize("zoom, free", ((0.5, False), (1.5, True)))
def test_shift_bone_drawing_locks_all_eight_directions_and_keeps_length(editor, zoom, free):
    """Preview, release and Undo agree on all 45-degree directions, with independent Alt."""
    vm, viewport = editor.viewmodel, editor.viewport
    editor.draw_bone()
    viewport.zoom, viewport.offset = zoom, QPointF(40, 30)
    origin = QPointF(250, 250)
    modifiers = Qt.KeyboardModifier.ShiftModifier
    if free:
        modifiers |= Qt.KeyboardModifier.AltModifier
    for degrees in range(0, 360, 45):
        angle = math.radians(degrees + 13)
        end = origin + QPointF(math.cos(angle), math.sin(angle)) * 110
        baseline, count = vm.documents.project, len(vm.documents.history.undo_stack)
        start_screen, end_screen = (p * zoom + viewport.offset for p in (origin, end))
        pointer(viewport, QMouseEvent.Type.MouseButtonPress, start_screen, modifiers)
        pointer(viewport, QMouseEvent.Type.MouseMove, end_screen, modifiers)
        expected = (
            origin + QPointF(math.cos(math.radians(degrees)), math.sin(math.radians(degrees))) * 110
        )
        assert (viewport._rig_cursor.x(), viewport._rig_cursor.y()) == pytest.approx(
            (expected.x(), expected.y())
        )
        pointer(viewport, QMouseEvent.Type.MouseButtonRelease, end_screen, modifiers)
        bone = vm.rig.bone
        assert not vm.rig.error and RigService(vm.documents).bone(bone.parent_id).extra.get(
            "rig_root"
        )
        node = vm.documents.animation.pose.nodes[bone.id]
        assert transform_point(node.world_matrix, bone.length, 0) == pytest.approx(
            (expected.x(), expected.y())
        )
        assert bone.length == pytest.approx(110)
        assert len(vm.documents.history.undo_stack) == count + 1
        vm.undo()
        assert vm.documents.project == baseline


def test_shift_direction_changes_live_and_does_not_snap_to_off_angle_joint(editor):
    """Shift changes a held preview immediately; positional magnets cannot override its ray."""
    vm, viewport = editor.viewmodel, editor.viewport
    rig = RigService(vm.documents)
    parent = rig.create_bone((100, 200), (200, 200))
    rig.create_bone((280, 275), (340, 275))
    vm.changed.emit()
    editor.draw_bone()
    viewport.zoom, viewport.offset = 1, QPointF(20, 30)
    start, end = QPointF(220, 230), QPointF(305, 310)
    pointer(viewport, QMouseEvent.Type.MouseButtonPress, start)
    pointer(viewport, QMouseEvent.Type.MouseMove, end)
    raw = QPointF(viewport._rig_cursor)
    assert viewport._draw_snap is not None

    def key(kind, code, modifiers):
        """Send held modifiers directly; QTest synthesizes extra releases for modifier flags."""
        QApplication.sendEvent(viewport, QKeyEvent(kind, code, modifiers))

    key(QKeyEvent.Type.KeyPress, Qt.Key.Key_Shift, Qt.KeyboardModifier.ShiftModifier)
    assert vm.rig.selected == (parent,)
    assert viewport._draw_snap is None
    delta = viewport._rig_cursor - QPointF(200, 200)
    assert delta.x() == pytest.approx(delta.y())
    key(QKeyEvent.Type.KeyRelease, Qt.Key.Key_Shift, Qt.KeyboardModifier.NoModifier)
    assert viewport._rig_cursor == raw
    key(QKeyEvent.Type.KeyPress, Qt.Key.Key_Shift, Qt.KeyboardModifier.ShiftModifier)
    constrained = QPointF(viewport._rig_cursor)
    key(
        QKeyEvent.Type.KeyPress,
        Qt.Key.Key_Alt,
        Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.AltModifier,
    )
    assert not vm.rig.selected
    delta = viewport._rig_cursor - viewport.scene_point(start)
    assert delta.x() == pytest.approx(delta.y())
    key(QKeyEvent.Type.KeyRelease, Qt.Key.Key_Alt, Qt.KeyboardModifier.ShiftModifier)
    assert vm.rig.selected == (parent,)
    assert viewport._rig_cursor == constrained
    pointer(viewport, QMouseEvent.Type.MouseButtonRelease, end, Qt.KeyboardModifier.ShiftModifier)
    key(QKeyEvent.Type.KeyRelease, Qt.Key.Key_Shift, Qt.KeyboardModifier.NoModifier)
    child = vm.rig.bone
    assert child.parent_id == parent and not vm.rig.error
    node = vm.documents.animation.pose.nodes[child.id]
    assert transform_point(node.world_matrix, child.length, 0) == pytest.approx(
        (constrained.x(), constrained.y())
    )
