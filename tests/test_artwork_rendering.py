"""Real Qt image decoding and seam-free UV triangle rendering with transparent source art."""

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

from rigora.application_services.documents import DocumentService
from rigora.application_services.meshes import MeshService
from rigora.domain.mesh_geometry import grid_mesh
from rigora.domain.project import Scene
from rigora.engine.evaluation import SceneEvaluator
from rigora.presentation.artwork import ArtworkCache, decode_artwork, draw_mesh


def test_svg_deformation_uses_original_vectors_at_high_zoom(qapp):
    """Subpixel source detail stays sharp when a deformed SVG is enlarged beyond its thumbnail."""
    source = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16">'
        b'<path d="M1 8 H15" stroke="white" stroke-width=".05"/></svg>'
    )
    cache = ArtworkCache()
    cache.put("vector", decode_artwork(source, 2), source)
    assert cache.get("vector").width() == 2
    renderer = cache.vectors["vector"]
    assert isinstance(renderer, QSvgRenderer)
    mesh = grid_mesh(16, 16, 4, 4)
    pose = SceneEvaluator(Scene(meshes=(mesh,))).evaluate(0).meshes[mesh.id]
    output = QImage(1024, 1024, QImage.Format.Format_ARGB32_Premultiplied)
    output.fill(Qt.GlobalColor.transparent)

    class VectorPainter(QPainter):
        """Reject bitmap texture rendering so the test cannot pass through a raster fallback."""

        def drawImage(self, *args, **kwargs):
            raise AssertionError("SVG rendering must not paint a cached raster")

    painter = VectorPainter(output)
    draw_mesh(
        painter, pose, tuple(QPointF(x * 64 + y * 4, y * 64) for x, y in pose.positions), renderer
    )
    painter.end()
    assert output.pixelColor(500, 511).alpha() > 200
    cache.clear()
    assert not cache.vectors


@pytest.mark.parametrize("opacity", [1, 0.5])
def test_vector_deformation_preserves_alpha_across_triangle_boundaries(qapp, opacity):
    """Clipped vector patches must not introduce seams or double-opacity along shared edges."""
    source = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
        f'<rect width="100" height="100" fill="white" opacity="{opacity}"/></svg>'
    ).encode()
    renderer = QSvgRenderer(QByteArray(source))
    mesh = grid_mesh(100, 100, 5, 5)
    pose = SceneEvaluator(Scene(meshes=(mesh,))).evaluate(0).meshes[mesh.id]
    image = QImage(120, 120, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.black)
    painter = QPainter(image)
    draw_mesh(painter, pose, tuple(QPointF(x + 10, y + 10) for x, y in pose.positions), renderer)
    painter.end()
    expected = image.pixelColor(15, 17)
    assert expected.red() > 100
    assert all(image.pixelColor(x, y) == expected for x in range(12, 108) for y in range(12, 108))


@pytest.mark.parametrize("format", ["PNG", "JPEG"])
def test_actual_raster_import_decode_and_preserved_source(format, qapp):
    source = QImage(120, 80, QImage.Format.Format_RGB32)
    source.fill(QColor("#c3c3c3"))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert source.save(buffer, format)
    original = bytes(data)
    image = decode_artwork(original)
    assert (image.width(), image.height()) == (120, 80)
    doc = DocumentService()
    doc.new()
    service = MeshService(doc)
    key = service.import_image_bytes(f"image.{format.lower()}", original)
    assert doc.read_asset(service.mesh(key).asset_id) == original
    assert doc.animation.pose.meshes[key].triangles


def test_opaque_and_translucent_triangles_have_no_internal_clip_seams(qapp):
    mesh = grid_mesh(100, 100, 5, 5)
    pose = SceneEvaluator(Scene(meshes=(mesh,))).evaluate(0).meshes[mesh.id]
    for alpha in (255, 128):
        source = QImage(100, 100, QImage.Format.Format_ARGB32_Premultiplied)
        source.fill(QColor(240, 240, 240, alpha))
        output = QImage(120, 120, QImage.Format.Format_ARGB32_Premultiplied)
        output.fill(Qt.GlobalColor.black)
        painter = QPainter(output)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        points = tuple(QPointF(x + 10, y + 10) for x, y in pose.positions)
        draw_mesh(painter, pose, points, source)
        painter.end()
        expected = output.pixelColor(15, 17)
        assert expected.red() > 100
        assert all(
            output.pixelColor(x, y) == expected for x in range(12, 108) for y in range(12, 108)
        )
