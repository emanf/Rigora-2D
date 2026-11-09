"""Bound interactive work while retaining canonical geometry, linking and undo semantics."""

from dataclasses import replace

import pytest

from rigora.application_services.bone_animation import BoneAnimationService
from rigora.application_services.character_creation import CharacterCreationService, build_character
from rigora.application_services.characters import CharacterService
from rigora.application_services.documents import DocumentService
from rigora.application_services.rigging import RigService
from rigora.domain.character_recipe import character_preset


@pytest.mark.parametrize("animated", (False, True))
def test_bone_planning_never_publishes_reusable_objects_but_commit_does(monkeypatch, animated):
    """Mouse-move solves remain isolated; release still updates linked definitions atomically."""
    from rigora.application_services import object_library

    doc = DocumentService()
    doc.new()
    owner = CharacterCreationService(doc).create(build_character(character_preset("nova")))
    doc.set_animation_context(owner, frozenset(CharacterService(doc).members(owner)))
    bone = next(b for r in doc.scene.skeletons for b in r.bones if b.name == "upper_arm.L")
    original = object_library.synchronize_objects
    calls = []

    def synchronize(before, after):
        calls.append(after)
        return original(before, after)

    monkeypatch.setattr(object_library, "synchronize_objects", synchronize)
    baseline, count = doc.project, len(doc.history.undo_stack)
    service = BoneAnimationService(doc) if animated else RigService(doc)
    command, pose = service.plan_drag(bone.id, "chain_rotate", 25, 0, (bone.id,))
    assert not calls
    assert doc.project is baseline and len(doc.history.undo_stack) == count
    assert pose.nodes[bone.id].world_matrix != doc.animation.pose.nodes[bone.id].world_matrix
    doc.execute(command)
    assert calls and len(doc.history.undo_stack) == count + 1
    doc.undo()
    assert doc.project == baseline


def test_clip_switch_reuses_geometry_and_invalidates_after_a_mesh_edit():
    """Animation changes share compilation; changed geometry cannot reuse stale skin data."""
    from rigora.engine.evaluation import SceneEvaluator

    doc = DocumentService()
    doc.new()
    owner = CharacterCreationService(doc).create(build_character(character_preset("nova")))
    doc.set_animation_context(owner, frozenset(CharacterService(doc).members(owner)))
    compiled = doc.animation.evaluator.deformation
    for name in ("Run", "Walk", "Idle"):
        clip = next(c for c in doc.scene.clips if c.name == name)
        doc.select_animation_clip(clip.id)
        assert doc.animation.evaluator.deformation is compiled
        fresh = SceneEvaluator(doc.scene, clip.id, scope=doc.animation_scope, local_object=owner)
        assert doc.animation.evaluate(8).meshes == fresh.evaluate(8).meshes
    mesh = doc.scene.meshes[0]
    changed = replace(
        mesh, vertices=(replace(mesh.vertices[0], x=mesh.vertices[0].x + 1), *mesh.vertices[1:])
    )
    RigService(doc).commit("Edit surface", meshes=(changed, *doc.scene.meshes[1:]))
    doc.select_animation_clip(clip.id)
    assert doc.animation.evaluator.deformation is not compiled


@pytest.mark.gui
@pytest.mark.parametrize("vertex", (0, 144, 288))
@pytest.mark.parametrize("hole", (False, True))
def test_local_vector_edit_batches_unchanged_area_without_changing_pixels(
    qapp, monkeypatch, vertex, hole
):
    """Dense corner/interior edits retain alpha and geometry with bounded native clipping work."""
    from PySide6.QtCore import QByteArray, QPointF, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    from rigora.domain.mesh_geometry import grid_mesh
    from rigora.domain.project import Scene
    from rigora.engine.evaluation import SceneEvaluator
    from rigora.presentation import artwork

    mesh = grid_mesh(100, 100, 16, 16)
    if hole:
        vertices = {v.id: v for v in mesh.vertices}
        mesh = replace(
            mesh,
            triangles=tuple(
                face
                for face in mesh.triangles
                if not (
                    30 < sum(vertices[key].x for key in face) / 3 < 70
                    and 30 < sum(vertices[key].y for key in face) / 3 < 70
                )
            ),
        )
    pose = SceneEvaluator(Scene(meshes=(mesh,))).evaluate(0).meshes[mesh.id]
    points = tuple(QPointF(x * 2 + 10, y * 2 + 10) for x, y in pose.positions)
    points = tuple(p + QPointF(7, 3) if i == vertex else p for i, p in enumerate(points))
    source = QSvgRenderer(
        QByteArray(
            b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
            b'<rect width="100" height="100" fill="white" opacity="0.5"/>'
            b'<circle cx="50" cy="50" r="20" fill="black"/></svg>'
        )
    )

    def render():
        image = QImage(230, 230, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        artwork.draw_mesh(painter, pose, points, source)
        painter.end()
        return image

    count = 0
    original = artwork.QRegion

    def region(*args):
        nonlocal count
        count += 1
        return original(*args)

    monkeypatch.setattr(artwork, "QRegion", region)
    optimized = render()
    assert count < 32
    if hole:
        assert optimized.pixelColor(110, 110).alpha() == 0
    monkeypatch.setattr(artwork, "_affine_patch", lambda *args: None)
    reference = render()
    different = sum(
        optimized.pixel(x, y) != reference.pixel(x, y) for x in range(230) for y in range(230)
    )
    assert different < 230 * 230 * 0.005


@pytest.mark.gui
@pytest.mark.parametrize("scale", (0.25, 1, 3))
def test_native_mesh_mapping_matches_authoring_coordinates(qapp, scale):
    """Paint and hit geometry agree under rotation, mirroring, zoom and panning."""
    from PySide6.QtCore import QPointF

    from rigora.domain.geometry import affine, transform_point
    from rigora.presentation.artwork import mesh_polygon

    matrix = affine(35, -12, 33, -2, 0.6, 0, 0)
    positions = ((0, 0), (13, 25), (-42, 11))
    offset = QPointF(73, -81)
    polygon = mesh_polygon(positions, matrix, scale, offset)
    for i, point in enumerate(positions):
        x, y = transform_point(matrix, *point)
        assert polygon[i].x() == pytest.approx(x * scale + offset.x())
        assert polygon[i].y() == pytest.approx(y * scale + offset.y())
