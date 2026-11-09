"""Bone overlays stay readable on transparency tiles while retaining their vector source."""

import io
import math
from xml.etree import ElementTree

import pytest
from PIL import Image
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

from rigora.application_services.content_thumbnails import render_content_thumbnail
from rigora.infrastructure.bone_contrast import outline_svg
from rigora.infrastructure.motion_catalog import skeletons
from rigora.presentation.bone_shape import BoneShape
from rigora.resources import asset_path

pytestmark = pytest.mark.gui


@pytest.mark.parametrize("background", ("#ffffff", "#161616", "#b5b5b5"))
@pytest.mark.parametrize("length", (12, 40, 120))
def test_bone_has_dark_and_light_screen_sized_edges_at_different_zoom_levels(
    qapp, background, length
):
    """Dark edges survive light surfaces and the neutral outer halo survives dark surfaces."""
    image = QImage(200, 100, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(background))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    shape = BoneShape()
    shape.draw(painter, QPointF(30, 50), QPointF(30 + length, 50))
    painter.end()
    colors = [image.pixelColor(x, y).red() for x in range(23, 38 + length) for y in range(28, 73)]
    assert min(colors) < 65
    assert max(colors) > 225
    assert shape.contains(QPointF(30, 50), QPointF(30, 50), QPointF(30 + length, 50))


def test_outline_keeps_original_silhouettes_and_only_uses_a_bounded_renderer_cache(qapp):
    """The outline traces replaceable paths/circles and does not rewrite the canonical asset."""
    data = asset_path("shapes/bone.svg").read_bytes()
    original = ElementTree.fromstring(data)
    outlined = ElementTree.fromstring(outline_svg(data, "#202020", 140))
    for a, b in zip(original.iter(), outlined.iter(), strict=True):
        for key in ("d", "cx", "cy", "r", "points", "transform"):
            assert a.get(key) == b.get(key)
    shape = BoneShape()
    image = QImage(240, 100, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("#303030"))
    painter = QPainter(image)
    for length in range(10, 190):
        shape.draw(painter, QPointF(20, 50), QPointF(20 + length, 50))
    painter.end()
    assert len(shape.outlines) <= 64
    assert len(shape.tiles) <= 128
    assert shape.tile_bytes <= 8 * 1024**2
    assert shape.tile_bytes == sum(tile.sizeInBytes() for tile, _ in shape.tiles.values())
    assert shape.data == data == asset_path("shapes/bone.svg").read_bytes()


def test_bone_navigation_rotation_and_dpi_reuse_source_derived_tiles(qapp, monkeypatch):
    """Moving and rotating fixed-length bones avoids SVG work; tint, zoom and DPI invalidate."""
    shape = BoneShape()
    rendered = []
    original = QSvgRenderer.render

    def render(renderer, *args):
        rendered.append(renderer)
        return original(renderer, *args)

    monkeypatch.setattr(QSvgRenderer, "render", render)
    image = QImage(400, 400, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("#303030"))
    painter = QPainter(image)
    for angle in range(0, 360, 12):
        root = QPointF(150 + angle / 12, 150)
        tip = root + QPointF(
            100 * math.cos(math.radians(angle)), 100 * math.sin(math.radians(angle))
        )
        shape.draw(painter, root, tip)
    assert len(rendered) == 3
    assert len(shape.tiles) == 1
    shape.draw(painter, QPointF(100, 100), QPointF(220, 100))
    shape.draw(painter, QPointF(100, 150), QPointF(200, 150), "#ef5350")
    assert len(rendered) == 9
    assert image.pixelColor(140, 150).red() > image.pixelColor(140, 150).green() * 1.5
    painter.end()
    image.setDevicePixelRatio(2)
    painter = QPainter(image)
    shape.draw(painter, QPointF(30, 50), QPointF(130, 50))
    painter.end()
    assert len(rendered) == 12
    assert len(shape.tiles) == 4
    assert shape.tile_bytes == sum(tile.sizeInBytes() for tile, _ in shape.tiles.values())
    assert shape.tile_bytes <= 8 * 1024**2


def test_rig_card_poster_has_visible_dark_structure_on_its_transparent_background():
    """Actual evaluated rig posters retain transparency and a readable minimum edge width."""
    image = Image.open(io.BytesIO(render_content_thumbnail(skeletons()[0], {}))).convert("RGBA")
    assert image.getpixel((0, 0))[3] == 0
    pixels = image.load()
    assert (
        sum(
            1
            for x in range(image.width)
            for y in range(image.height)
            if pixels[x, y][3] > 160 and max(pixels[x, y][:3]) < 85
        )
        > 80
    )
