"""Work-count regressions for responsive painting and immutable interaction previews."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip("PySide6")

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.commands import ScenePatch
from rigora.application_services.documents import DocumentService
from rigora.domain.entities import Bone, SceneObject, Skeleton, nested_records
from rigora.domain.mesh_geometry import grid_mesh
from rigora.domain.project import Scene
from rigora.engine.evaluation import SceneEvaluator


def test_entity_walk_skips_numeric_topology_but_preserves_duplicate_entities(monkeypatch):
    """Indexing a dense mesh visits entity containers, never every UV or triangle scalar."""
    import rigora.domain.entities as entities

    mesh = grid_mesh(100, 100, 20, 20)
    calls = []
    original = entities.is_dataclass

    def record(value):
        calls.append(value)
        return original(value)

    monkeypatch.setattr(entities, "is_dataclass", record)
    records = nested_records(mesh)
    assert records == (mesh, *mesh.vertices)
    assert not any(isinstance(value, (str, int, float)) for value in calls)
    assert nested_records((mesh, mesh)) == (*records, *records)


def test_timeline_describes_only_requested_lanes_without_enumerating_all_vertices(monkeypatch):
    """Detailed geometry never forces a full channel catalog just to label existing tracks."""
    from rigora.application_services.meshes import MeshService
    from rigora.application_services.rigging import RigService

    doc = DocumentService()
    doc.new()
    MeshService(doc).import_image_bytes(
        "square.svg", b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"/>', 32, 32
    )
    bone = RigService(doc).create_bone((0, 0), (100, 0))
    service = AnimationEditingService(doc)

    def no_full_catalog():
        raise AssertionError(
            "Existing timeline lanes must not enumerate every possible vertex channel"
        )

    monkeypatch.setattr(service, "properties", no_full_catalog)
    descriptors = service.channels(((bone, "transform.x"), (bone, "unsupported")))
    assert len(descriptors) == 1 and descriptors[0].key == (bone, "transform.x")


def test_channel_picker_skips_dense_vertex_catalog_until_explicitly_enabled(monkeypatch):
    """Ordinary track picking reuses compilation and does not construct hidden vertex channels."""
    from rigora.application_services import animation_editing
    from rigora.application_services.meshes import MeshService

    doc = DocumentService()
    doc.new()
    MeshService(doc).import_image_bytes(
        "square.svg", b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"/>', 32, 32
    )
    service = AnimationEditingService(doc)
    doc.animation.evaluate(0)

    def no_rebuild(*args):
        raise AssertionError(
            "Track picker must reuse compiled geometry and skip hidden vertex records"
        )

    monkeypatch.setattr(animation_editing, "DeformationPlan", no_rebuild)
    monkeypatch.setattr(animation_editing, "nested_records", no_rebuild)
    assert service.channels(include_vertices=False)


def test_fork_reuses_compilation_without_evaluating_or_sharing_transport(monkeypatch):
    """Scratch previews reuse compiled immutable inputs and leave live playback independent."""
    doc = DocumentService()
    doc.new()
    session = doc.animation
    session.seek(9)
    session.play()
    calls = []
    original = SceneEvaluator.evaluate

    def evaluate(self, *args, **kwargs):
        calls.append(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(SceneEvaluator, "evaluate", evaluate)
    scratch = doc.fork()
    assert not calls
    assert scratch.animation.evaluator is session.evaluator
    assert scratch.animation.pose is session.pose
    assert not scratch.animation.playback.is_playing
    scratch.animation.seek(12)
    assert session.playback.frame == 9 and session.playback.is_playing
    scene = scratch.project.scenes[0]
    scratch.execute(
        ScenePatch("New object", scene.id, {"objects": ()}, {"objects": (SceneObject(),)})
    )
    assert scratch.animation.evaluator is not session.evaluator
    assert not doc.project.scenes[0].objects


def test_auto_key_publishes_all_channels_once_without_enumerating_vertex_channels(monkeypatch):
    """Multi-channel posing validates one final project rather than one project per scalar."""
    doc = DocumentService()
    doc.new()
    bone = Bone()
    scene = doc.project.scenes[0]
    doc.execute(
        ScenePatch("Rig", scene.id, {"skeletons": ()}, {"skeletons": (Skeleton(bones=(bone,)),)})
    )
    service = AnimationEditingService(doc)
    calls = []
    execute = doc.execute

    def publish(command):
        calls.append(command)
        execute(command)

    def describe_all():
        raise AssertionError("Scalar input must not enumerate the whole scene")

    monkeypatch.setattr(doc, "execute", publish)
    monkeypatch.setattr(service, "channels", describe_all)
    before = doc.project
    service.auto_key_values(
        {
            (bone.id, "transform.x"): 20,
            (bone.id, "transform.y"): 30,
            (bone.id, "transform.rotation"): 15,
        },
        12,
    )
    assert len(calls) == 1
    assert all(
        [key.frame for key in track.keyframes] == [0, 12] for track in service.timeline.tracks
    )
    doc.undo()
    assert doc.project == before


def test_rigid_raster_batches_and_viewport_reuses_art_until_inputs_change(qapp, qtbot, monkeypatch):
    """Dense wireframe, hover and pan reuse pixels; source/zoom/pose changes stay visible."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter

    from rigora.presentation import artwork
    from rigora.presentation.widgets import viewport as viewport_module

    source = QImage(100, 100, QImage.Format.Format_ARGB32_Premultiplied)
    source.fill(QColor("white"))
    obj = SceneObject()
    mesh = replace(grid_mesh(100, 100, 20, 20), object_id=obj.id, asset_id=str(uuid4()))
    pose = SceneEvaluator(Scene(objects=(obj,), meshes=(mesh,))).evaluate(0)
    calls = []

    class CountingPainter(QPainter):
        def drawImage(self, *args, **kwargs):
            calls.append(1)
            return super().drawImage(*args, **kwargs)

    target = QImage(200, 200, source.format())
    target.fill(Qt.GlobalColor.transparent)
    painter = CountingPainter(target)
    artwork.draw_mesh(
        painter,
        pose.meshes[mesh.id],
        tuple(QPointF(*p) for p in pose.meshes[mesh.id].positions),
        source,
    )
    painter.end()
    assert len(calls) == 1
    viewport = viewport_module.Viewport()
    qtbot.addWidget(viewport)
    viewport.resize(320, 320)
    viewport.set_scene(Scene().settings)
    viewport.zoom = 1.0
    viewport.set_pose(pose)
    viewport.artwork.put(mesh.asset_id, source)
    alternate = str(uuid4())
    red = source.copy()
    red.fill(QColor("red"))
    viewport.artwork.put(alternate, red)
    viewport.mesh_wireframe = True
    draws = []
    draw = viewport_module.draw_mesh

    def record(*args):
        draws.append(1)
        return draw(*args)

    monkeypatch.setattr(viewport_module, "draw_mesh", record)
    viewport.grab()
    assert len(draws) == 1
    viewport.selected_nodes = (obj.id,)
    viewport.refresh_cursor(QPointF(30, 30))
    viewport.grab()
    assert len(draws) == 1
    viewport.offset += QPointF(3, 0)
    viewport.grab()
    assert len(draws) == 1
    viewport.artwork.put(mesh.asset_id, source.copy())
    viewport.grab()
    assert len(draws) == 2
    viewport.mesh_wireframe = False
    viewport.grab()
    assert len(draws) == 3
    viewport.set_pose(replace(pose, frame=2))
    viewport.grab()
    assert len(draws) == 3
    node = pose.nodes[obj.id]
    viewport.set_pose(
        replace(pose, nodes={obj.id: replace(node, world_matrix=(*node.world_matrix[:4], 12, 0))})
    )
    moved = viewport.grab().toImage()
    assert len(draws) == 3
    ratio = viewport.devicePixelRatioF()
    assert moved.pixelColor(round(7 * ratio), round(37 * ratio)) != QColor("white")
    assert moved.pixelColor(round(110 * ratio), round(37 * ratio)) == QColor("white")
    switched = replace(pose.meshes[mesh.id], asset_id=alternate)
    viewport.set_pose(replace(pose, meshes={mesh.id: switched}))
    output = viewport.grab().toImage()
    assert len(draws) == 4
    assert (
        output.pixelColor(
            round(20 * viewport.devicePixelRatioF()), round(20 * viewport.devicePixelRatioF())
        ).green()
        == 0
    )


def test_mesh_override_pose_is_cached_and_in_place_changes_invalidate(qapp):
    """Repeated FFD/vertex overlay reads evaluate once while mutable input changes stay live."""
    from PySide6.QtCore import QObject

    from rigora.application_services.meshes import MeshService
    from rigora.presentation.viewmodels.meshes import MeshViewModel

    doc = DocumentService()
    doc.new()
    service = MeshService(doc)
    key = service.import_image_bytes(
        "square.svg",
        b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
        b'<rect width="100" height="100" fill="white"/></svg>',
    )
    parent = QObject()
    model = MeshViewModel(parent)
    model.bind(doc)
    model.select_mesh(key)
    mesh = model.mesh
    before = doc.project
    channel = (mesh.vertices[0].id, "x")
    model.preview_values[channel] = 20
    first = model.pose
    assert model.pose is first
    model.preview_values[channel] = 30
    second = model.pose
    assert second is not first and second.meshes[key].positions[0][0] == 30
    doc.animation.seek(2)
    assert model.pose is not second
    model.cancel_preview()
    assert model.pose is doc.animation.pose and doc.project is before


@pytest.mark.parametrize(
    "tool", ["move", "chain_rotate", "selection_rotate", "selection_scale", "pull"]
)
def test_fast_bone_preview_matches_keyed_geometry_and_records_only_on_release(qapp, tool):
    """Live overrides match keyed geometry without authoring during pointer moves."""
    from PySide6.QtCore import QObject

    from rigora.application_services.bone_animation import BoneAnimationService
    from rigora.application_services.rigging import RigService
    from rigora.presentation.viewmodels.rigging import RigViewModel

    doc = DocumentService()
    doc.new()
    rig = RigService(doc)
    rig.template("Chain")
    bones = rig.scene.skeletons[0].bones
    root, tip = bones[0].id, bones[-1].id
    edit = AnimationEditingService(doc)
    edit.key(root, "transform.rotation", 0, 0)
    edit.key(root, "transform.rotation", 24, 35)
    doc.animation.seek(12)
    parent = QObject()
    model = RigViewModel(parent)
    model.bind(doc)
    model.selected = (tip,)
    x, y = doc.animation.pose.nodes[tip].world_matrix[4:]
    x, y = (
        (1.1, 0) if tool == "selection_scale" else (15, 0) if "rotate" in tool else (x + 10, y + 15)
    )
    _, expected = BoneAnimationService(doc).plan_drag(tip, tool, x, y, model.selected)
    before, count = doc.project, len(doc.history.undo_stack)
    model.begin_preview()
    model.preview_drag(tip, tool, x, y)
    assert not model.error and model._preview_values is not None
    assert doc.project is before and len(doc.history.undo_stack) == count
    for key in expected.nodes:
        assert model.pose.nodes[key].world_matrix == pytest.approx(expected.nodes[key].world_matrix)
    model.drag(tip, tool, x, y)
    assert not model.error and len(doc.history.undo_stack) == count + 1
    for key in expected.nodes:
        assert doc.animation.pose.nodes[key].world_matrix == pytest.approx(
            expected.nodes[key].world_matrix
        )
    doc.undo()
    assert doc.project == before


@pytest.mark.parametrize("vector", [False, True])
def test_uniform_batch_preserves_mesh_holes(qapp, vector):
    """Boundary batching retains empty interior regions for both original SVGs and raster pixels."""
    from PySide6.QtCore import QByteArray, QPointF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    from rigora.presentation.artwork import draw_mesh

    mesh = grid_mesh(100, 100, 4, 4)
    vertices = {v.id: v for v in mesh.vertices}
    mesh = replace(
        mesh,
        triangles=tuple(
            f
            for f in mesh.triangles
            if not (
                25 < sum(vertices[k].x for k in f) / 3 < 75
                and 25 < sum(vertices[k].y for k in f) / 3 < 75
            )
        ),
    )
    pose = SceneEvaluator(Scene(meshes=(mesh,))).evaluate(0).meshes[mesh.id]
    source = QImage(100, 100, QImage.Format.Format_ARGB32_Premultiplied)
    source.fill(QColor("white"))
    if vector:
        source = QSvgRenderer(
            QByteArray(
                b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
                b'<rect width="100" height="100" fill="white"/></svg>'
            )
        )
    output = QImage(100, 100, QImage.Format.Format_ARGB32_Premultiplied)
    output.fill(Qt.GlobalColor.transparent)
    painter = QPainter(output)
    draw_mesh(painter, pose, tuple(QPointF(*p) for p in pose.positions), source)
    painter.end()
    assert output.pixelColor(50, 50).alpha() == 0
    assert output.pixelColor(10, 10).alpha() == 255


def test_dense_bone_editor_coalesces_control_changes_and_keeps_preview_uncommitted(
    qtbot, tmp_path, monkeypatch
):
    """Maximum density/alignment uses one background job and leaves project/history untouched."""
    from rigora.app.application import ApplicationInfo
    from rigora.infrastructure.preferences import PreferencesStore
    from rigora.presentation.viewmodels.main_window import MainWindowViewModel
    from rigora.presentation.views.main_window import MainWindow
    from rigora.presentation.widgets.composer_editors import BoneEditor

    vm = MainWindowViewModel(ApplicationInfo(), preferences=PreferencesStore(tmp_path / "ui.json"))
    window = MainWindow(vm)
    qtbot.addWidget(window)
    window.confirm_discard = lambda: True
    window.show()
    vm.open_project(Path("examples/image-import-example.rigora"))
    qtbot.waitUntil(lambda: bool(window.viewport.artwork.images), timeout=10000)
    editor = BoneEditor(window)
    calls = []
    generate = editor.generate_subdivision

    def record(apply):
        calls.append(apply)
        generate(apply)

    monkeypatch.setattr(editor, "generate_subdivision", record)
    qtbot.addWidget(editor)
    editor.show()
    editor.division_type.setCurrentIndex(editor.division_type.findData("full"))
    editor.wireframe.setChecked(True)
    assert editor.density.maximum() == 10
    for density in range(2, 11):
        editor.density.setValue(density)
    editor.alignment.setValue(10)
    baseline = vm.documents.project
    count = len(vm.documents.history.undo_stack)
    qtbot.waitUntil(
        lambda: editor.prepared is not None and window.viewport.subdivision_pose is not None,
        timeout=15000,
    )
    mesh = editor.prepared[0].project.scenes[0].meshes[0]
    assert (
        mesh.extra["subdivision"]["density"] == 10 and mesh.extra["subdivision"]["alignment"] == 10
    )
    assert len(mesh.triangles) > 100
    assert calls == [False]
    assert vm.documents.project is baseline and len(vm.documents.history.undo_stack) == count
    assert window.viewport.grab().save(str(tmp_path / "dense-preview.png"))
    editor.hide()
