"""Real pin placement, visual selection, setup dragging and modeless editor lifecycle."""

from dataclasses import replace

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from test_object_workspace_redesign_gui import panel_editor as panel_editor
from test_roots_soft_drag_gui import drag, pointer

from rigora.application_services.appearance import AppearanceService
from rigora.application_services.area_pins import AreaPinService
from rigora.application_services.image_rigging import ImageRigService
from rigora.application_services.rigging import RigService
from rigora.domain.geometry import transform_point

pytestmark = pytest.mark.gui


def prepare(window, qtbot):
    """Prepare one actual bound vector Object without full catalog generation."""
    vm, doc = window.viewmodel, window.viewmodel.documents
    mesh = AppearanceService(doc).create_shape("rectangle", 100, 100, 300, 240)
    images = ImageRigService(doc)
    actor = images.convert((mesh,), "Pin test")
    root = images.draw_bone(mesh, (150, 180), (250, 180))
    images.draw_bone(mesh, (250, 180), (350, 180), root)
    vm.changed.emit()
    window.object_edit.enter(actor)
    qtbot.waitUntil(lambda: not window.mesh_workspace.jobs, timeout=10000)
    vm.rig.select("")
    vm.mesh.select_mesh(mesh)
    window.show_bone_editor()
    window.bone_editor.preview_subdivision.setChecked(False)
    window.viewport.zoom, window.viewport.offset = 1, QPointF(70, 30)
    window.viewport.set_pose(doc.animation.pose)
    window.viewport.repaint()
    return mesh, root


def click_local(window, mesh_id, point):
    """Click a source point on the unposed rectangle in current editor coordinates."""
    view = window.viewport
    mesh = AreaPinService(window.viewmodel.documents).mesh(mesh_id)
    world = transform_point(view.pose.nodes[mesh.object_id].world_matrix, *point)
    screen = QPointF(*world) * view.zoom + view.offset
    assert view.rect().contains(screen.toPoint())
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=screen.toPoint())
    return screen


def test_repeated_placement_target_controls_selection_delete_and_undo(panel_editor, qtbot):
    window = panel_editor
    mesh_id, root = prepare(window, qtbot)
    doc, view = window.viewmodel.documents, window.viewport
    dialog, service = window.bone_editor, AreaPinService(doc)
    dialog.bone_buttons["Add pin"].click()
    assert dialog.pins.target.currentData() is None
    first = click_local(window, mesh_id, (80, 80))
    pins = service.mesh(mesh_id).extra["area_pins"]
    assert len(pins) == 1 and pins[0]["target_kind"] == "object"
    first_id = pins[0]["vertex_id"]
    dialog.pins.selected = ()
    dialog.pins.target.setCurrentIndex(dialog.pins.target.findData(root))
    second = click_local(window, mesh_id, (220, 150))
    pins = service.mesh(mesh_id).extra["area_pins"]
    assert len(pins) == 2 and pins[1]["bone_id"] == root
    assert len(dialog.pins.markers()) == 2
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=first.toPoint())
    assert dialog.pins.selected == ((mesh_id, first_id),)
    QTest.mouseClick(
        view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, second.toPoint()
    )
    assert len(dialog.pins.selected) == 2
    original, count = doc.project, len(doc.history.undo_stack)
    dialog.pins.radius.setValue(75)
    dialog.pins.radius.editingFinished.emit()
    assert all(p["radius"] == 75 for p in service.mesh(mesh_id).extra["area_pins"])
    assert len(doc.history.undo_stack) == count + 1
    window.viewmodel.undo()
    assert doc.project == original
    QTest.keyClick(view, Qt.Key.Key_Delete)
    assert not service.mesh(mesh_id).extra["area_pins"]
    assert service.mesh(mesh_id).vertices and doc.scene.skeletons
    window.viewmodel.undo()
    assert doc.project == original
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=first.toPoint())
    assert view.grab().save("build/artwork-pin-editor.png")
    assert dialog.grab().save("build/artwork-pin-controls.png")
    dialog.close()
    assert view.pin_overlay is None and view.pin_cursor is None


def test_pin_drag_commits_once_and_pose_mode_cannot_move_pin_setup(panel_editor, qtbot):
    window = panel_editor
    mesh_id, root = prepare(window, qtbot)
    doc, view = window.viewmodel.documents, window.viewport
    dialog, service = window.bone_editor, AreaPinService(doc)
    dialog.bone_buttons["Add pin"].click()
    click_local(window, mesh_id, (80, 80))
    original, count = doc.project, len(doc.history.undo_stack)
    start = dialog.pins.markers()[0][2]
    drag(view, start, start + QPointF(30, 20))
    assert not window.viewmodel.mesh.error
    assert len(doc.history.undo_stack) == count + 1
    assert len(service.mesh(mesh_id).extra["area_pins"]) == 1
    moved = service.mesh(mesh_id).extra["area_pins"][0]
    assert (moved["x"], moved["y"]) == pytest.approx((110, 100), abs=1)
    window.viewmodel.undo()
    assert doc.project == original
    dialog.bone_buttons["Preview / pose"].click()
    assert not dialog.pins.editable and dialog.pins.markers()
    before = service.mesh(mesh_id).extra["area_pins"]
    bone = RigService(doc).bone(root)
    RigService(doc).update(
        root, transform=replace(bone.transform, rotation=bone.transform.rotation + 20)
    )
    assert service.mesh(mesh_id).extra["area_pins"] == before


def test_pin_setup_drag_is_transient_and_escape_cancels_without_undo(panel_editor, qtbot):
    """Moving a handle does not rebuild or publish authoring records on each mouse event."""
    import json
    import statistics
    import time
    from pathlib import Path

    from PySide6.QtCore import QEvent

    window = panel_editor
    mesh_id, _ = prepare(window, qtbot)
    dialog, view, doc = window.bone_editor, window.viewport, window.viewmodel.documents
    dialog.bone_buttons["Add pin"].click()
    start = click_local(window, mesh_id, (80, 80))
    original, count = doc.project, len(doc.history.undo_stack)
    pointer(view, QEvent.Type.MouseButtonPress, start)
    frames = []
    for delta in range(5, 29, 2):
        started = time.perf_counter()
        pointer(view, QEvent.Type.MouseMove, start + QPointF(delta, 10))
        view.repaint()
        frames.append((time.perf_counter() - started) * 1000)
        assert doc.project is original and len(doc.history.undo_stack) == count
    Path("build/artwork-pin-performance.json").write_text(
        json.dumps(
            {
                "case": "one setup pin, two deforming bones, vector artwork",
                "samples": len(frames),
                "median_ms": statistics.median(frames),
                "max_ms": max(frames),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    QTest.keyClick(view, Qt.Key.Key_Escape)
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=(start + QPointF(25, 10)).toPoint())
    assert dialog.pins.drag is None
    assert doc.project is original and len(doc.history.undo_stack) == count
