"""Offscreen pointer, background subdivision and transactional live Skin previews."""

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QMouseEvent
from PySide6.QtWidgets import QColorDialog, QMessageBox, QScrollArea
from test_roots_soft_drag_gui import editor as root_editor
from test_roots_soft_drag_gui import pointer

from rigora.application_services.appearance import AppearanceService
from rigora.application_services.deformation import deformation_presets
from rigora.application_services.meshes import MeshService
from rigora.presentation.widgets.window_frame import CustomDialog
from rigora.resources import asset_path

pytestmark = pytest.mark.gui


def test_subdivision_density_is_limited_to_ten_in_both_editors(editor):
    """Both density controls and their live sliders stop at ten without rewriting saved meshes."""
    artwork(editor)
    original = editor.viewmodel.documents.project
    editor.show_bone_editor()
    for field in (editor.bone_editor.density, editor.mesh_panel.density):
        assert field.maximum() == 10
        field.setValue(32)
        assert field.value() == 10
    assert editor.viewmodel.documents.project is original


@pytest.fixture
def editor(qtbot, tmp_path, monkeypatch):
    """Exercise real widgets while isolating unrelated library poster decoding."""
    yield from root_editor.__wrapped__(qtbot, tmp_path, monkeypatch)


def artwork(editor):
    """Select a dense ordinary SVG, ready for either point or surface editing."""
    vm = editor.viewmodel
    service = MeshService(vm.documents)
    mesh_id = service.import_image(asset_path("examples/prop.svg"), 16, 16)
    vm.changed.emit()
    vm.mesh.select_mesh(mesh_id)
    return mesh_id


def test_default_surface_grab_falloff_and_animation_at_playhead(editor):
    """Dragging between dots works immediately and captures an animated dense surface."""
    mesh_id = artwork(editor)
    vm, viewport = editor.viewmodel, editor.viewport
    vm.mesh.stage_id = vm.mesh.service.add(mesh_id, deformation_presets()[0])
    vm.changed.emit()
    editor.command_actions["mesh"].trigger()
    assert vm.mesh.active and vm.mesh.tool == "soft"
    assert not vm.mesh.stage_id
    assert editor.soft_drag_button.isChecked()
    editor.soft_drag_falloff.setValue(65)
    editor.soft_drag_radius.setValue(140)
    interaction = editor.mesh_workspace.interaction
    assert interaction.soft_falloff == 0.65
    viewport.zoom, viewport.offset = 1, QPointF(-700, -350)
    vm.animation_editor.set_auto_key(True)
    assert vm.mesh.auto_key
    initial = vm.mesh.pose.meshes[mesh_id].positions
    vm.playback.seek(20)
    points = interaction.points()
    start = (points[100] + points[101] + points[117]) / 3
    count = len(vm.documents.history.undo_stack)
    pointer(viewport, QMouseEvent.Type.MouseButtonPress, start)
    pointer(viewport, QMouseEvent.Type.MouseMove, start + QPointF(25, 12))
    preview = vm.mesh.pose.meshes[mesh_id].positions
    assert preview != initial
    pointer(viewport, QMouseEvent.Type.MouseButtonRelease, start + QPointF(25, 12))
    assert not vm.mesh.error
    assert vm.mesh.pose.meshes[mesh_id].positions == preview
    assert len(vm.documents.history.undo_stack) == count + 1
    lane = editor.timeline._groups["", "Mesh deformation"]
    assert len(editor.timeline.row_tracks(lane)) == len(vm.animation_editor.service.timeline.tracks)
    assert lane.childCount() == 0
    vm.playback.seek(0)
    assert viewport.pose.meshes[mesh_id].positions == initial
    vm.playback.seek(10)
    halfway = viewport.pose.meshes[mesh_id].positions
    assert halfway != initial and halfway != preview
    editor.command_actions["mesh"].trigger()
    assert not vm.mesh.active


def test_mesh_brush_controls_fit_a_narrow_editor(editor, qtbot):
    """Contextual brush options must not force the whole application wider than the window."""
    artwork(editor)
    editor.command_actions["mesh"].trigger()
    editor.resize(1200, 850)
    qtbot.wait(10)
    assert editor.width() <= 1200
    assert editor.soft_drag_radius.isVisible() and editor.soft_drag_falloff.isVisible()


def test_edit_mesh_reveals_subdivision_and_owns_one_overlay_until_toggled_off(
    editor, qtbot, monkeypatch
):
    """The actual tool opens visible controls, draws topology once and leaves no editing dots."""
    from rigora.presentation.widgets import viewport as viewport_module

    vm, panel, viewport = editor.viewmodel, editor.mesh_panel, editor.viewport
    service = MeshService(vm.documents)
    mesh_id = service.import_image(asset_path("examples/prop.svg"))
    vm.changed.emit()
    vm.mesh.select_mesh(mesh_id)
    panel.tabs.setCurrentIndex(3)
    editor.docks["inspector"].hide()
    editor.set_viewport_wireframe(True)
    editor.command_actions["mesh"].trigger()
    qtbot.wait(10)
    assert vm.mesh.active and viewport.mesh_editing
    assert editor.docks["inspector"].isVisible()
    assert editor.inspector.currentWidget() is panel and panel.tabs.currentIndex() == 0
    assert panel.division.currentData() == "full"
    assert not editor.wireframe_option.isVisible() and not viewport.mesh_wireframe
    page = panel.tabs.currentWidget()
    assert isinstance(page, QScrollArea)
    assert page.verticalScrollBar().value() == 0
    for control in (panel.division, panel.density, panel.subdivide_button):
        assert control.isVisible()
        assert (
            page.viewport().rect().contains(control.mapTo(page.viewport(), control.rect().center()))
        )

    topology, generic_edges = [], []
    interaction = editor.mesh_workspace.interaction
    original_draw, original_edges = interaction.draw_topology, viewport_module.triangle_edges

    def draw_topology(*args):
        topology.append(1)
        return original_draw(*args)

    def triangle_edges(*args):
        generic_edges.append(1)
        return original_edges(*args)

    monkeypatch.setattr(interaction, "draw_topology", draw_topology)
    monkeypatch.setattr(viewport_module, "triangle_edges", triangle_edges)
    editor.mesh_workspace.frame_artwork()
    # A retained Bone Editor wireframe preference cannot add a second topology pass.
    editor.set_viewport_wireframe(True)
    viewport.grab()
    assert topology and not generic_edges
    editor.grab().save("build/edit-mesh-subdivision-review.png")
    topology.clear()
    editor.command_actions["mesh"].trigger()
    viewport.grab()
    assert not vm.mesh.active and not viewport.mesh_editing and not viewport.mesh_wireframe
    assert not topology and not generic_edges
    editor.command_actions["mesh"].trigger()
    assert vm.mesh.active and viewport.mesh_editing


@pytest.mark.parametrize("accept", (False, True))
def test_skin_picker_previews_live_and_commits_only_on_apply(editor, monkeypatch, accept):
    """Two live colors never touch document/history until Apply; Cancel restores the viewport."""
    vm = editor.viewmodel
    service = AppearanceService(vm.documents)
    mesh_id = service.create_shape("rectangle", 100, 100, 120, 80)
    vm.changed.emit()
    original, count = vm.documents.project, len(vm.documents.history.undo_stack)
    panel = editor.character_panel
    initial = vm.documents.animation.pose.meshes[mesh_id].appearance

    def exec_picker(dialog):
        picker = dialog.findChild(QColorDialog)
        for color in ("#1188ff", "#cc3322"):
            picker.setCurrentColor(QColor(color))
            assert vm.documents.project is original
            assert len(vm.documents.history.undo_stack) == count
            assert vm.scene.preview is not None
            assert (
                editor.viewport.pose.meshes[mesh_id].appearance["tint"]["r"] == QColor(color).red()
            )
        return int(accept)

    monkeypatch.setattr(CustomDialog, "exec", exec_picker)
    result = panel.pick_color(
        "#ffffff",
        lambda look, color: look.edit(
            (mesh_id,), {"tint.r": QColor(color).red(), "tint.amount": 0.5}
        ),
    )
    assert vm.scene.preview is None
    if accept:
        assert result == "#cc3322"
        assert len(vm.documents.history.undo_stack) == count + 1
        assert editor.viewport.pose.meshes[mesh_id].appearance != initial
        vm.undo()
        assert vm.documents.project == original
    else:
        assert result is None and vm.documents.project is original
        assert editor.viewport.pose.meshes[mesh_id].appearance == initial


def test_edit_mesh_subdivision_is_background_undoable_and_discards_stale_results(
    editor, qtbot, monkeypatch
):
    """Mesh inspector exposes the same modes as Bone Editor and never adopts another revision."""
    mesh_id = artwork(editor)
    vm, panel, workspace = editor.viewmodel, editor.mesh_panel, editor.mesh_workspace
    monkeypatch.setattr(
        "rigora.presentation.mesh_workspace.ask_question", lambda *a: QMessageBox.StandardButton.Yes
    )
    original, count = vm.mesh.mesh, len(vm.documents.history.undo_stack)
    panel.division.setCurrentIndex(panel.division.findData("full"))
    panel.density.setValue(7)
    panel.alignment.setValue(2)
    workspace.regenerate()
    assert workspace.subdivision_job is not None
    assert not panel.subdivide_button.isEnabled()
    qtbot.waitUntil(lambda: workspace.subdivision_job is None, timeout=15000)
    assert not vm.mesh.error
    assert vm.mesh.mesh.extra["subdivision"]["density"] == 7
    assert vm.mesh.mesh.extra["subdivision"]["alignment"] == 2
    assert len(vm.documents.history.undo_stack) == count + 1
    vm.undo()
    assert vm.mesh.mesh == original
    panel.division.setCurrentIndex(panel.division.findData("mask"))
    assert panel.expand.isEnabled()
    panel.division.setCurrentIndex(panel.division.findData("grid"))
    assert not panel.expand.isEnabled()
    assert not panel.alignment.isEnabled()
    workspace.regenerate()
    vm.mesh.service.commit("Concurrent edit", extra={"concurrent_mesh": True})
    current = vm.documents.project
    qtbot.waitUntil(lambda: workspace.subdivision_job is None, timeout=15000)
    assert vm.documents.project is current
    assert vm.mesh.service.mesh(mesh_id) == original


def test_subdivision_keeps_animated_skin_colors(editor, qtbot, monkeypatch):
    """Changing topology replaces mesh keys without discarding an independent appearance layer."""
    mesh_id = artwork(editor)
    vm, panel = editor.viewmodel, editor.mesh_panel
    look = AppearanceService(vm.documents)
    look.edit((mesh_id,), {"tint.r": 60, "tint.amount": 0.4})
    vm.changed.emit()
    vm.playback.seek(20)
    look.edit((mesh_id,), {"tint.r": 220}, auto_key=True)
    vm.changed.emit()
    before = vm.documents.animation.evaluate(10).meshes[mesh_id].appearance
    monkeypatch.setattr(
        "rigora.presentation.mesh_workspace.ask_question", lambda *a: QMessageBox.StandardButton.Yes
    )
    panel.density.setValue(5)
    editor.mesh_workspace.regenerate()
    qtbot.waitUntil(lambda: editor.mesh_workspace.subdivision_job is None, timeout=15000)
    assert not vm.mesh.error
    assert vm.documents.animation.evaluate(10).meshes[mesh_id].appearance == before
