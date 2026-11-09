"""Real mesh widgets: artwork, lattice gestures, keys, brushes and tab isolation."""

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest

from rigora.app.application import ApplicationInfo
from rigora.domain.project import ProjectError
from rigora.domain.validation import json_copy
from rigora.engine.deformation import DeformationPlan, lattice_controls
from rigora.infrastructure.preferences import PreferencesStore
from rigora.presentation.artwork import ArtworkJob, decode_artwork
from rigora.presentation.viewmodels.main_window import MainWindowViewModel
from rigora.presentation.views.main_window import MainWindow
from rigora.resources import asset_path


@pytest.fixture
def mesh_window(qtbot, tmp_path):
    """Open an isolated editor and wait for original worker-decoded artwork to arrive."""
    vm = MainWindowViewModel(ApplicationInfo(), preferences=PreferencesStore(tmp_path / "ui.json"))
    window = MainWindow(vm)
    qtbot.addWidget(window, before_close_func=lambda w: setattr(w, "confirm_discard", lambda: True))
    window.show()
    window.mesh_workspace.example("Character torso")
    qtbot.waitUntil(lambda: bool(window.viewport.artwork.images), timeout=10000)
    window.viewport.fit_canvas()
    return window


def sampled_controls(model):
    """Inspect the displayed FFD pose, including its keyed channels at the playhead."""
    params = json_copy(model.service.stage(model.stage_id).parameters)
    session = model.document.animation
    for (owner, path), value in session.evaluator.mesh_values(session.pose.frame).items():
        if owner == model.stage_id:
            DeformationPlan.override_parameter(params, path, value)
    return lattice_controls(params)[2]


def test_ffd_drag_multi_selection_key_edit_and_undo(mesh_window, qtbot):
    window = mesh_window
    model, panel, viewport = window.viewmodel.mesh, window.mesh_panel, window.viewport
    interaction = window.mesh_workspace.interaction
    panel.tools.setCurrentIndex(panel.tools.findData("control"))
    assert model.mesh.asset_id in viewport.artwork.vectors
    stage_id = model.stage_id
    handles = interaction.handles()
    start = handles[0][2].toPoint()
    before = model.pose.meshes[model.mesh_id].positions
    count = len(model.document.history.undo_stack)
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(viewport, start + QPoint(22, 8))
    assert model.pose.meshes[model.mesh_id].positions != before
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=start + QPoint(22, 8))
    assert len(model.document.history.undo_stack) == count + 1
    assert sampled_controls(model)[0][0] > 0
    window.viewmodel.undo()
    assert model.service.stage(stage_id).parameters["controls"][0] == (0, 0)
    model.controls = (0, 1)
    model.changed.emit()
    panel.properties.setCurrentIndex(
        next(
            i
            for i in range(panel.properties.count())
            if panel.properties.itemData(i) == (stage_id, "parameters.controls.0.0")
        )
    )
    panel.frame.setValue(10)
    panel.value.setValue(42)
    assert panel.target() == (stage_id, "parameters.controls.0.0")
    panel.set_key()
    assert not model.error, model.error
    assert any(
        k.frame == 10 and k.value == 42
        for t in model.service.scene.timelines[0].tracks
        if t.owner_id == stage_id and t.property_path.endswith(".0.0")
        for k in t.keyframes
    )
    panel.set_key(delete=True)
    remaining = next(
        t for t in model.service.scene.timelines[0].tracks if t.property_path.endswith(".0.0")
    )
    assert [(k.frame, k.value) for k in remaining.keyframes] == [(0, 0)]
    first = model.document
    window.viewmodel.new_project()
    assert model.mesh is None and model.selected == ()
    window.viewmodel.activate_project(0)
    assert model.document is first and model.mesh is not None and model.stage_id == stage_id


def test_vertex_edge_triangle_selection_pin_protect_and_paint(mesh_window):
    window = mesh_window
    model, panel = window.viewmodel.mesh, window.mesh_panel
    interaction, viewport = window.mesh_workspace.interaction, window.viewport
    panel.tools.setCurrentIndex(panel.tools.findData("vertex"))
    point = interaction.points()[0].toPoint()
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=point)
    assert model.selected == (model.mesh.vertices[0].id,)
    panel.protected.click()
    assert model.mesh.vertices[0].protected
    panel.pinned.click()
    assert model.mesh.vertices[0].pinned
    panel.tools.setCurrentIndex(panel.tools.findData("triangle"))
    points = interaction.points()
    center = ((points[0] + points[1] + points[8]) / 3).toPoint()
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=center)
    assert len(model.selected) == 3
    window.mesh_workspace.example("Waving arm")
    model = window.viewmodel.mesh
    panel.tools.setCurrentIndex(panel.tools.findData("paint"))
    mesh = model.mesh
    center = interaction.points()[38].toPoint()
    count = len(model.document.history.undo_stack)
    old = tuple(v.weights for v in mesh.vertices)
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=center)
    QTest.mouseMove(viewport, center + QPoint(20, 0))
    assert model.preview_mesh is not None
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=center + QPoint(20, 0))
    assert tuple(v.weights for v in model.mesh.vertices) != old
    assert len(model.document.history.undo_stack) == count + 1
    window.viewmodel.undo()
    assert tuple(v.weights for v in model.mesh.vertices) == old


def test_worker_import_rejects_stale_project_and_corrupt_pixel_data(mesh_window, qtbot):
    window = mesh_window
    data = asset_path("examples/prop.svg").read_bytes()
    before = len(window.viewmodel.mesh.service.scene.meshes)
    window.mesh_workspace.submit(ArtworkJob(lambda: data), "new.svg", True)
    doc = window.viewmodel.documents
    doc.update_settings(
        "Changed during decode", doc.project.scenes[0].name, doc.project.scenes[0].settings
    )
    window.viewmodel.changed.emit()
    qtbot.waitUntil(lambda: not window.mesh_workspace.jobs, timeout=10000)
    assert len(window.viewmodel.mesh.service.scene.meshes) == before
    assert "changed while decoding" in window.viewmodel.mesh.error
    with pytest.raises(ProjectError):
        decode_artwork(b"not an image")
    for name in ("arm", "torso", "prop"):
        image = decode_artwork(asset_path(f"examples/{name}.svg").read_bytes())
        assert not image.isNull() and image.hasAlphaChannel()


def test_multiple_control_auto_key_drag_and_transport_fields(mesh_window):
    window = mesh_window
    model, panel, viewport = window.viewmodel.mesh, window.mesh_panel, window.viewport
    panel.tools.setCurrentIndex(panel.tools.findData("control"))
    handles = window.mesh_workspace.interaction.handles()
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=handles[0][2].toPoint())
    QTest.mouseClick(
        viewport,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        pos=handles[1][2].toPoint(),
    )
    assert model.controls == (0, 1)
    panel.auto_key.setChecked(True)
    before = len(model.document.history.undo_stack)
    start = handles[0][2].toPoint()
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=start + QPoint(15, 0))
    assert not model.error, model.error
    assert len(model.document.history.undo_stack) == before + 1
    assert model.service.stage(model.stage_id).parameters["controls"][0] == (0, 0)
    tracks = model.document.animation.evaluator.timeline.tracks
    for index in (0, 1):
        assert any(t.property_path == f"parameters.controls.{index}.0" for t in tracks)
    window.viewmodel.playback.seek(24)
    assert panel.frame.value() == 24
    window.viewmodel.undo()
    assert len(model.document.animation.evaluator.timeline.tracks) == 1


def test_custom_ffd_marquee_move_and_resize_selected_dots(mesh_window):
    """Custom FFD moves and scales a selected sub-grid live, preserving other dots and undo."""
    window = mesh_window
    model, panel, viewport = window.viewmodel.mesh, window.mesh_panel, window.viewport
    interaction = window.mesh_workspace.interaction
    panel.tools.setCurrentIndex(panel.tools.findData("control"))
    handles = interaction.handles()
    columns, _, _ = lattice_controls(model.service.stage(model.stage_id).parameters)
    first = handles[0][2].toPoint() - QPoint(20, 20)
    last = handles[columns + 1][2].toPoint() + QPoint(8, 8)
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=first)
    QTest.mouseMove(viewport, last)
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=last)
    selected = {0, 1, columns, columns + 1}
    assert set(model.controls) == selected
    baseline = model.document.project
    count = len(model.document.history.undo_stack)
    original_geometry = model.pose.meshes[model.mesh_id].positions
    point = handles[0][2].toPoint()
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseMove(viewport, point + QPoint(15, 10))
    assert model.document.project is baseline
    assert model.pose.meshes[model.mesh_id].positions != original_geometry
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=point + QPoint(15, 10))
    assert len(model.document.history.undo_stack) == count + 1
    window.viewmodel.undo()
    assert model.document.project == baseline

    point = interaction.handles()[0][2].toPoint()
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseMove(viewport, point + QPoint(10, 10))
    panel.tools.setCurrentIndex(panel.tools.findData("vertex"))
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=point + QPoint(10, 10))
    assert model.document.project == baseline
    baseline = model.document.project
    panel.tools.setCurrentIndex(panel.tools.findData("control"))
    handles = interaction.handles()
    frame = interaction.control_box(handles)
    start = frame[1][4][0].toPoint()
    old_controls = sampled_controls(model)
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
    assert interaction.scale is not None
    QTest.mouseMove(viewport, start + QPoint(30, 25))
    assert model.document.project is baseline
    assert model.pose.meshes[model.mesh_id].positions != original_geometry
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=start + QPoint(30, 25))
    controls = sampled_controls(model)
    for index, control in enumerate(controls):
        assert (control != old_controls[index]) == (index in selected and index != 0)
    assert len(model.document.history.undo_stack) == count + 1
    window.viewmodel.undo()
    assert model.document.project == baseline


@pytest.mark.parametrize("format", ["png", "jpeg", "svg"])
def test_image_import_through_native_picker_result(
    mesh_window, qtbot, tmp_path, format, monkeypatch
):
    """Import native multi-picker paths unchanged, including spaces and each artwork format."""
    window = mesh_window
    source = tmp_path / f"image with spaces.{format}"
    if format == "svg":
        source.write_bytes(asset_path("examples/torso.svg").read_bytes())
    elif format == "jpeg":
        assert QImage(str(asset_path("icons/app/rigora.png"))).save(str(source), "JPEG")
    else:
        source.write_bytes(asset_path("icons/app/rigora.png").read_bytes())
    window.viewmodel.rig.run(lambda s: s.create_bone((50, 50), (100, 50)))
    before = len(window.viewmodel.mesh.service.scene.meshes)

    monkeypatch.setattr(
        "rigora.presentation.widgets.file_dialogs.QFileDialog.getOpenFileNames",
        lambda *args, **kwargs: ([str(source)], "Images"),
    )
    if format == "png":
        QTest.mouseClick(window.import_artwork_button, Qt.MouseButton.LeftButton)
    else:
        window.command_actions["import"].trigger()
    window.media_dialog.browse()
    window.media_dialog.submit()
    qtbot.waitUntil(lambda: not window.viewmodel.media.busy, timeout=10000)
    assert not window.viewmodel.media.error
    qtbot.waitUntil(lambda: not window.mesh_workspace.jobs, timeout=10000)
    assert len(window.viewmodel.mesh.service.scene.meshes) == before, window.viewmodel.mesh.error
    assert window.library_tabs.currentWidget() is window.project_assets_page
    item = window.project_assets.item(window.project_assets.count() - 1)
    qtbot.wait(10)
    QTest.mouseClick(
        window.project_assets.viewport(),
        Qt.MouseButton.LeftButton,
        pos=window.project_assets.visualItemRect(item).center(),
    )
    QTest.mouseDClick(
        window.project_assets.viewport(),
        Qt.MouseButton.LeftButton,
        pos=window.project_assets.visualItemRect(item).center(),
    )
    assert len(window.viewmodel.mesh.service.scene.meshes) == before + 1
    qtbot.waitUntil(lambda: not window.mesh_workspace.jobs, timeout=10000)
    mesh = window.viewmodel.mesh.mesh
    assert mesh.asset_id in window.viewport.artwork.images
    assert window.viewmodel.documents.read_asset(mesh.asset_id) == source.read_bytes()
    assert not window.viewmodel.mesh.active and not window.viewmodel.rig.active
    assert window.viewmodel.mesh.service.scene.skeletons[0].bones
    window.viewmodel.save_project(tmp_path / f"{format}-import.rigora")
    from rigora.application_services.documents import DocumentService

    reopened = DocumentService()
    reopened.open(tmp_path / f"{format}-import.rigora")
    assert reopened.read_asset(mesh.asset_id) == source.read_bytes()
