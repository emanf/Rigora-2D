"""Pointer coverage follows source alpha and original vectors through evaluated mesh geometry."""

from dataclasses import replace

import pytest
from PySide6.QtCore import QByteArray, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

from rigora.domain.mesh_geometry import grid_mesh
from rigora.domain.project import Scene
from rigora.engine.evaluation import SceneEvaluator
from rigora.presentation.artwork import ArtworkCache, decode_artwork, mesh_contains

RING = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
    b'<path fill="white" fill-rule="evenodd" '
    b'd="M10 10H90V90H10Z M35 35H65V65H35Z"/></svg>'
)


@pytest.mark.parametrize("vector", [False, True])
@pytest.mark.parametrize("pixel_ratio", [1, 2])
@pytest.mark.parametrize("mirrored", [False, True])
def test_transparent_margins_and_holes_are_not_pickable_after_affine_transform(
    qapp, vector, pixel_ratio, mirrored
):
    """Opaque coverage survives skew/zoom/DPI while a rectangular grid cannot hide source holes."""
    mesh = grid_mesh(100, 100, 4, 4)
    pose = SceneEvaluator(Scene(meshes=(mesh,))).evaluate(0).meshes[mesh.id]
    image = QSvgRenderer(QByteArray(RING)) if vector else decode_artwork(RING)

    def screen(x, y):
        return QPointF(200 + (-1.8 if mirrored else 1.8) * x + 0.3 * y, 70 + 0.2 * x + 1.2 * y)

    points = tuple(screen(*p) for p in pose.positions)
    assert mesh_contains(pose, points, image, screen(23, 42), pixel_ratio=pixel_ratio)
    assert not mesh_contains(pose, points, image, screen(47, 54), pixel_ratio=pixel_ratio)
    assert not mesh_contains(pose, points, image, screen(4, 8), pixel_ratio=pixel_ratio)
    assert not mesh_contains(pose, points, image, screen(23, 42), opacity=0)
    assert mesh_contains(pose, points, image, screen(23, 42), opacity=0.5)


def test_pick_uses_original_svg_detail_instead_of_its_tiny_thumbnail(qapp):
    """Thin curves remain pickable at high zoom even when the preview texture cannot show them."""
    data = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16">'
        b'<path d="M1 8H15" stroke="white" stroke-width=".05"/></svg>'
    )
    cache = ArtworkCache()
    cache.put("hair", decode_artwork(data, 2), data)
    mesh = grid_mesh(16, 16, 2, 2)
    pose = SceneEvaluator(Scene(meshes=(mesh,))).evaluate(0).meshes[mesh.id]
    points = tuple(QPointF(x * 64 + y * 4, y * 64) for x, y in pose.positions)
    assert mesh_contains(pose, points, cache.vectors["hair"], QPointF(500, 512))
    assert not mesh_contains(pose, points, cache.vectors["hair"], QPointF(500, 520))


def test_deformed_mesh_and_uv_flip_pick_the_same_raster_pixels_as_rendering(qapp):
    """Picking follows both nonuniform deformation and UV placement, rather than original bounds."""
    image = QImage(100, 100, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.fillRect(0, 0, 30, 100, QColor("white"))
    painter.end()
    mesh = grid_mesh(100, 100, 1, 1)
    pose = SceneEvaluator(Scene(meshes=(mesh,))).evaluate(0).meshes[mesh.id]
    pose = replace(pose, uv=tuple((1 - u, v) for u, v in pose.uv))
    points = tuple(QPointF(x + y * x / 100, y) for x, y in pose.positions)
    assert mesh_contains(pose, points, image, QPointF(150, 80))
    assert not mesh_contains(pose, points, image, QPointF(15, 20))
