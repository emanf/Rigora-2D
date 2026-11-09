"""Pixel, work-count and document-isolation regressions for detailed scene navigation."""

from dataclasses import replace
from uuid import uuid4

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from test_workspace_redesign_gui import editor as editor

from rigora.application_services.meshes import MeshService
from rigora.application_services.rigging import RigService
from rigora.domain.entities import SceneObject, Transform
from rigora.domain.mesh_geometry import grid_mesh
from rigora.domain.project import Scene
from rigora.engine.evaluation import SceneEvaluator
from rigora.presentation.widgets import viewport as viewport_module

pytestmark = pytest.mark.gui


def send_mouse(viewport, kind, point, button, buttons):
    """Exercise the real viewport and installed editor event filters with held buttons."""
    QApplication.sendEvent(
        viewport,
        QMouseEvent(kind, point, point, button, buttons, Qt.KeyboardModifier.NoModifier),
    )


@pytest.mark.parametrize("vector", [False, True])
def test_pan_reuses_whole_parts_and_reveals_offscreen_art(qtbot, monkeypatch, vector):
    """Panning reveals previously clipped pixels and objects without redrawing cached parts."""
    viewport = viewport_module.Viewport()
    qtbot.addWidget(viewport)
    viewport.resize(320, 200)
    viewport.set_scene(Scene().settings)
    viewport.zoom, viewport.offset = 1, QPointF(20, 20)
    viewport.grid_visible = False
    first, second = SceneObject(), SceneObject(transform=Transform(x=1200))
    key, other = str(uuid4()), str(uuid4())
    mesh = replace(grid_mesh(1000, 100, 4, 4), object_id=first.id, asset_id=key)
    hidden = replace(grid_mesh(100, 100, 2, 2), object_id=second.id, asset_id=other)
    pose = SceneEvaluator(Scene(objects=(first, second), meshes=(mesh, hidden))).evaluate(0)
    viewport.set_pose(pose)
    image = QImage(1000, 100, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("red"))
    painter = QPainter(image)
    painter.fillRect(800, 0, 200, 100, QColor("blue"))
    painter.end()
    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="100">'
        b'<rect width="1000" height="100" fill="red"/>'
        b'<rect x="800" width="200" height="100" fill="blue"/></svg>'
    )
    viewport.artwork.put(key, image, svg if vector else None)
    green = QImage(100, 100, image.format())
    green.fill(QColor("lime"))
    viewport.artwork.put(other, green)
    calls = []
    draw = viewport_module.draw_mesh

    def record(*args):
        calls.append(args[1].id)
        return draw(*args)

    monkeypatch.setattr(viewport_module, "draw_mesh", record)
    viewport.grab()
    assert calls == [mesh.id]
    viewport.offset = QPointF(-750.5, 20.5)
    panned = viewport.grab().toImage()
    assert calls == [mesh.id]
    ratio = viewport.devicePixelRatioF()
    assert panned.pixelColor(round(100 * ratio), round(60 * ratio)) == QColor("blue")
    viewport._mesh_layers.clear()
    viewport._artwork_pose = None
    assert panned == viewport.grab().toImage()
    viewport.offset = QPointF(-1100, 20)
    output = viewport.grab().toImage()
    assert calls == [mesh.id, mesh.id, hidden.id]
    assert output.pixelColor(round(140 * ratio), round(60 * ratio)) == QColor("lime")
    moved = replace(second, transform=Transform(x=1220, y=10))
    viewport.set_pose(
        SceneEvaluator(Scene(objects=(first, moved), meshes=(mesh, hidden))).evaluate(0)
    )
    translated = viewport.grab().toImage()
    assert calls == [mesh.id, mesh.id, hidden.id]
    assert translated.pixelColor(round(150 * ratio), round(70 * ratio)) == QColor("lime")
    assert translated.pixelColor(round(105 * ratio), round(25 * ratio)) != QColor("lime")
    viewport._mesh_layers.clear()
    viewport._artwork_pose = None
    assert translated == viewport.grab().toImage()
    viewport.zoom = 1.5
    viewport.grab()
    assert len(calls) > 3


def test_oversized_mesh_has_bounded_pan_window_and_refills_exposed_pixels(qtbot, monkeypatch):
    """Very large zoomed art never allocates a scene-sized pixmap or leaves blank pan strips."""
    viewport = viewport_module.Viewport()
    qtbot.addWidget(viewport)
    viewport.resize(320, 200)
    viewport.set_scene(Scene().settings)
    viewport.zoom, viewport.offset = 1, QPointF(-100, -100)
    obj = SceneObject()
    mesh = replace(grid_mesh(20000, 20000, 2, 2), object_id=obj.id, asset_id=str(uuid4()))
    viewport.set_pose(SceneEvaluator(Scene(objects=(obj,), meshes=(mesh,))).evaluate(0))
    image = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("white"))
    viewport.artwork.put(mesh.asset_id, image)
    calls = []
    draw = viewport_module.draw_mesh

    def record(*args):
        calls.append(1)
        return draw(*args)

    monkeypatch.setattr(viewport_module, "draw_mesh", record)
    viewport.grab()
    tile = viewport._mesh_layers[mesh.id].tile
    ratio = viewport.devicePixelRatioF()
    assert tile.width() <= (viewport.width() + 258) * ratio
    viewport.offset -= QPointF(30, 30)
    viewport.grab()
    assert len(calls) == 1
    viewport.offset -= QPointF(250, 250)
    output = viewport.grab().toImage()
    assert len(calls) == 2
    viewport._mesh_layers.clear()
    viewport._artwork_pose = None
    assert output == viewport.grab().toImage()


def test_many_small_parts_do_not_churn_the_artwork_cache(qtbot, monkeypatch):
    """A detailed rig with more than 128 parts retains all tiles that fit its pixel budget."""
    viewport = viewport_module.Viewport()
    qtbot.addWidget(viewport)
    viewport.resize(320, 240)
    viewport.set_scene(Scene().settings)
    viewport.zoom = 1
    key = str(uuid4())
    objects = tuple(
        SceneObject(transform=Transform(x=i % 16 * 10, y=i // 16 * 10)) for i in range(160)
    )
    meshes = tuple(
        replace(grid_mesh(5, 5, 1, 1), object_id=obj.id, asset_id=key) for obj in objects
    )
    viewport.set_pose(SceneEvaluator(Scene(objects=objects, meshes=meshes)).evaluate(0))
    image = QImage(5, 5, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("white"))
    viewport.artwork.put(key, image)
    calls = []
    draw = viewport_module.draw_mesh

    def record(*args):
        calls.append(1)
        return draw(*args)

    monkeypatch.setattr(viewport_module, "draw_mesh", record)
    viewport.grab()
    assert len(calls) == 160 and len(viewport._mesh_layers) == 160
    viewport.offset += QPointF(7, 5)
    viewport.grab()
    assert len(calls) == 160


def test_multiple_large_parts_share_the_cache_budget_without_pan_churn(qtbot, monkeypatch):
    """Large overlapping parts retain cropped overscan instead of evicting each other."""
    viewport = viewport_module.Viewport()
    qtbot.addWidget(viewport)
    viewport.resize(320, 240)
    viewport.set_scene(Scene().settings)
    viewport.zoom, viewport.offset = 1, QPointF(-100, -100)
    key = str(uuid4())
    objects = tuple(SceneObject() for _ in range(5))
    meshes = tuple(
        replace(grid_mesh(2000, 2000, 1, 1), object_id=obj.id, asset_id=key) for obj in objects
    )
    viewport.set_pose(SceneEvaluator(Scene(objects=objects, meshes=meshes)).evaluate(0))
    image = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("white"))
    viewport.artwork.put(key, image)
    calls = []
    draw = viewport_module.draw_mesh

    def record(*args):
        calls.append(1)
        return draw(*args)

    monkeypatch.setattr(viewport_module, "draw_mesh", record)
    viewport.grab()
    viewport.offset -= QPointF(7, 5)
    viewport.grab()
    assert len(calls) == 5
    assert (
        sum(p.tile.width() * p.tile.height() * 4 for p in viewport._mesh_layers.values())
        <= 64 * 1024**2
    )


def test_asset_arrival_invalidates_only_parts_using_that_source(qtbot, monkeypatch):
    """Another thumbnail or a missing part cannot rerender the whole detailed scene."""
    viewport = viewport_module.Viewport()
    qtbot.addWidget(viewport)
    viewport.resize(320, 240)
    viewport.set_scene(Scene().settings)
    viewport.zoom = 1
    objects = SceneObject(), SceneObject(transform=Transform(x=100))
    meshes = tuple(
        replace(grid_mesh(80, 80, 2, 2), object_id=obj.id, asset_id=str(uuid4())) for obj in objects
    )
    viewport.set_pose(SceneEvaluator(Scene(objects=objects, meshes=meshes)).evaluate(0))
    image = QImage(80, 80, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("white"))
    viewport.artwork.put(meshes[0].asset_id, image)
    calls = []
    draw = viewport_module.draw_mesh

    def record(*args):
        calls.append(args[1].id)
        return draw(*args)

    monkeypatch.setattr(viewport_module, "draw_mesh", record)
    viewport.grab()
    assert calls == [meshes[0].id]
    viewport.artwork.put(str(uuid4()), image.copy())
    viewport.grab()
    assert calls == [meshes[0].id]
    viewport.artwork.put(meshes[1].asset_id, image.copy())
    viewport.grab()
    assert calls == [meshes[0].id, meshes[1].id]
    viewport.artwork.put(meshes[1].asset_id, image.copy())
    viewport.grab()
    assert calls == [meshes[0].id, meshes[1].id, meshes[1].id]


@pytest.mark.parametrize("mode", ["scene", "bone", "mesh"])
@pytest.mark.parametrize("gesture", ["hand", "space", "middle"])
def test_pan_preserves_authoring_state_and_skips_edit_hit_tests(editor, monkeypatch, mode, gesture):
    """Hand, Space and middle navigation leave selections, source geometry and undo intact."""
    vm, viewport = editor.viewmodel, editor.viewport
    mesh_id = MeshService(vm.documents).import_image_bytes(
        "square.svg",
        b'<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">'
        b'<rect width="200" height="200" fill="white"/></svg>',
        20,
        20,
    )
    root = RigService(vm.documents).create_bone((50, 50), (150, 50))
    vm.changed.emit()
    owner = vm.mesh.service.mesh(mesh_id).object_id
    editor.scene_workspace.select_entries((owner,))
    if mode == "bone":
        editor.rig_workspace.set_mode(True)
        vm.rig.set_tool("draw")
        vm.rig.select(root)
    elif mode == "mesh":
        vm.mesh.select_mesh(mesh_id)
        editor.mesh_workspace.set_mode(True)
        vm.mesh.tool = "vertex"
        vm.mesh.selected = (vm.mesh.mesh.vertices[0].id,)
    viewport.zoom, viewport.offset = 1, QPointF(10, 10)
    project, history = vm.documents.project, len(vm.documents.history.undo_stack)
    selected = vm.scene.selected, vm.rig.selected, vm.mesh.selected
    old_pick = editor.scene_workspace.pick
    old_mesh_pick = editor.mesh_workspace.interaction.pick

    def pick(point, **kwargs):
        assert viewport._drag is None, "Navigation must not run authoring hit tests"
        return old_pick(point, **kwargs)

    def mesh_pick(point):
        assert viewport._drag is None, "Navigation must not scan dense editable triangles"
        return old_mesh_pick(point)

    monkeypatch.setattr(editor.scene_workspace, "pick", pick)
    monkeypatch.setattr(editor.mesh_workspace.interaction, "pick", mesh_pick)
    viewport.pan_tool = gesture == "hand"
    if gesture == "space":
        QTest.keyPress(viewport, Qt.Key.Key_Space)
    button = Qt.MouseButton.MiddleButton if gesture == "middle" else Qt.MouseButton.LeftButton
    start = QPointF(80, 80)
    send_mouse(viewport, QEvent.Type.MouseButtonPress, start, button, button)
    assert viewport._drag is not None
    for delta in (QPointF(10, 5), QPointF(20, 10), QPointF(30, 15)):
        send_mouse(viewport, QEvent.Type.MouseMove, start + delta, Qt.MouseButton.NoButton, button)
        viewport.grab()
    send_mouse(
        viewport, QEvent.Type.MouseButtonRelease, start + delta, button, Qt.MouseButton.NoButton
    )
    if gesture == "space":
        QTest.keyRelease(viewport, Qt.Key.Key_Space)
    assert viewport.offset == QPointF(40, 25) and viewport._drag is None
    assert vm.documents.project is project and len(vm.documents.history.undo_stack) == history
    assert (vm.scene.selected, vm.rig.selected, vm.mesh.selected) == selected
    assert editor.mesh_workspace.interaction.drag is None
    assert editor.scene_workspace.drag is None


def test_pan_translates_cached_hit_geometry_and_topology_picture(editor, monkeypatch):
    """Outlines, mesh dots and precise picks follow the camera without remapping each vertex."""
    vm, viewport = editor.viewmodel, editor.viewport
    mesh_id = MeshService(vm.documents).import_image_bytes(
        "square.svg",
        b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
        b'<rect width="100" height="100" fill="white"/></svg>',
        20,
        20,
    )
    vm.changed.emit()
    viewport.zoom, viewport.offset = 1, QPointF(10, 10)
    workspace = editor.scene_workspace
    owner = vm.mesh.service.mesh(mesh_id).object_id
    vm.mesh.select_mesh(mesh_id)
    editor.mesh_workspace.set_mode(True)
    old = QPointF(workspace.polygons()[owner].at(0))
    interaction = editor.mesh_workspace.interaction
    vm.mesh.tool = "vertex"
    point = QPointF(interaction.points()[0])
    viewport.grab()
    picture, tile = interaction._topology_picture, interaction._topology_tile

    def no_remap(*args):
        raise AssertionError("Pan must translate retained polygons rather than remap vertices")

    monkeypatch.setattr("rigora.presentation.scene_workspace.transform_point", no_remap)
    monkeypatch.setattr(interaction, "screen", no_remap)
    delta = QPointF(23, 11)
    viewport.offset += delta
    assert workspace.polygons()[owner].at(0) == old + delta
    assert interaction.points()[0] == point + delta
    viewport.grab()
    assert interaction._topology_picture is picture and interaction._topology_tile is tile
    vm.mesh.selected = (vm.mesh.mesh.vertices[0].id,)
    viewport.grab()
    assert interaction._topology_picture is not picture
    assert interaction.pick(point + delta) == vm.mesh.selected
