"""Composer controls exercise the shared mesh and dynamics services in a real Qt window."""

from pathlib import Path

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from rigora.app.application import ApplicationInfo
from rigora.domain.geometry import transform_point
from rigora.infrastructure.preferences import PreferencesStore
from rigora.presentation.viewmodels.main_window import MainWindowViewModel
from rigora.presentation.views.main_window import MainWindow
from rigora.presentation.widgets.composer_editors import BoneEditor, SpringEditor


@pytest.mark.gui
def test_composer_subdivision_pin_tool_controls_and_screenshots(qtbot, tmp_path, monkeypatch):
    """Buttons change real topology and pointer pins, with portable readable editor layouts."""
    vm = MainWindowViewModel(ApplicationInfo(), preferences=PreferencesStore(tmp_path / "ui.json"))
    window = MainWindow(vm)
    qtbot.addWidget(window, before_close_func=lambda w: setattr(w, "confirm_discard", lambda: True))
    window.show()
    vm.open_project(Path("examples/image-import-example.rigora"))
    qtbot.waitUntil(lambda: bool(window.viewport.artwork.images), timeout=10000)
    window.viewport.fit_canvas()
    editor = BoneEditor(window)
    window.bone_editor = editor
    qtbot.addWidget(editor)
    editor.show()
    editor.wireframe.setChecked(False)
    assert not editor.division_type.isEnabled()
    assert not editor.density.isEnabled()
    assert not editor.preview_subdivision.isEnabled()
    editor.wireframe.setChecked(True)
    assert editor.division_type.isEnabled() and editor.density.isEnabled()
    editor.division_type.setCurrentIndex(editor.division_type.findData("mask"))
    assert editor.expand.isEnabled()
    window.set_viewport_wireframe(False)
    assert not editor.wireframe.isChecked() and not editor.expand.isEnabled()
    assert not editor.preview_timer.isActive() and window.viewport.subdivision_pose is None
    window.set_viewport_wireframe(True)
    assert editor.expand.isEnabled()
    editor.division_type.setCurrentIndex(editor.division_type.findData("grid"))
    assert not editor.alignment.isEnabled() and not editor.expand.isEnabled()
    editor.division_type.setCurrentIndex(editor.division_type.findData("full"))
    assert [editor.division_type.itemText(i) for i in range(3)] == ["Full", "Mask", "Grid"]
    monkeypatch.setattr(
        "rigora.presentation.widgets.composer_editors.ask_question",
        lambda *args: QMessageBox.StandardButton.Yes,
    )
    baseline = vm.documents.project
    history = len(vm.documents.history.undo_stack)
    assert editor.preview_subdivision.isChecked()
    editor.density.setValue(3)
    editor.density.setValue(5)
    qtbot.waitUntil(lambda: window.viewport.subdivision_pose is not None, timeout=10000)
    assert vm.documents.project is baseline and len(vm.documents.history.undo_stack) == history
    assert editor.progress.value() == 100
    prepared_mesh = editor.prepared[0].project.scenes[0].meshes[0]
    assert prepared_mesh.extra["subdivision"]["density"] == 5
    window.mesh_workspace.frame_artwork()
    assert window.viewport.grab().save(str(tmp_path / "subdivision-preview.png"))
    QTest.mouseClick(
        window.viewport, Qt.MouseButton.LeftButton, pos=window.viewport.rect().center()
    )
    QTest.keyClick(window.viewport, Qt.Key.Key_Delete)
    assert vm.documents.project is baseline and len(vm.documents.history.undo_stack) == history
    editor.alignment.setValue(3)
    qtbot.waitUntil(
        lambda: (
            editor.prepared is not None
            and editor.prepared[0].project.scenes[0].meshes[0].extra["subdivision"]["alignment"]
            == 3
            and window.viewport.subdivision_pose is not None
        ),
        timeout=10000,
    )
    editor.regenerate()
    qtbot.waitUntil(lambda: editor.subdivision_job is None, timeout=10000)
    assert window.viewport.subdivision_pose is None
    assert len(vm.documents.history.undo_stack) == history + 1
    editor.preview_subdivision.setChecked(False)
    assert not vm.mesh.error
    mesh = vm.mesh.mesh
    assert mesh.extra["subdivision"]["mode"] == "full"
    editor.wireframe.setChecked(True)
    assert window.viewport.mesh_wireframe
    vm.rig.selected = ()
    editor.add_pin()
    assert vm.mesh.active and vm.mesh.tool == "area_pin"
    x, y = mesh.extra["image_width"] / 2, mesh.extra["image_height"] / 2
    point = transform_point(window.viewport.pose.nodes[mesh.object_id].world_matrix, x, y)
    screen = QPointF(*point) * window.viewport.zoom + window.viewport.offset
    QTest.mouseClick(window.viewport, Qt.MouseButton.LeftButton, pos=screen.toPoint())
    assert not vm.mesh.error
    assert len(vm.mesh.mesh.extra["area_pins"]) == 1
    editor.release_pin()
    assert not vm.mesh.mesh.extra["area_pins"]
    assert editor.grab().save(str(tmp_path / "bone-editor.png"))
    editor.hide()
    springs = SpringEditor(window)
    qtbot.addWidget(springs)
    springs.show()
    springs.bounciness.setValue(90)
    springs.speed.setValue(70)
    assert springs.fields["frequency"].value() == pytest.approx(8.55)
    assert springs.fields["damping"].value() == pytest.approx(0.17, abs=0.01)
    springs.translate.setChecked(True)
    assert springs.fields["stretch"].isEnabled()
    assert springs.grab().save(str(tmp_path / "spring-editor.png"))
    springs.hide()
    assert window.grab().save(str(tmp_path / "full-triangles.png"))
    editor.show()
    previous_meshes = vm.documents.project.scenes[0].meshes
    editor.regenerate()
    vm.mesh.service.commit("Concurrent edit", extra={"concurrent": True})
    concurrent = vm.documents.project
    qtbot.waitUntil(lambda: editor.subdivision_job is None, timeout=10000)
    assert vm.documents.project is concurrent
    assert vm.documents.project.scenes[0].meshes == previous_meshes
    assert "changed during subdivision" in editor.status.text()
    editor.hide()
    if window.object_edit.active:
        window.object_edit.exit()
    vm.scene.select((mesh.object_id,))
    baseline = vm.documents.project
    window.command_actions["isolate"].trigger()
    assert window.object_edit.active
    assert mesh.object_id in window.viewport.isolated_ids
    assert window.viewport.isolated_ids == window.object_edit.ids
    assert vm.documents.project is baseline
    window.command_actions["isolate"].trigger()
    assert window.viewport.isolated_ids is None
