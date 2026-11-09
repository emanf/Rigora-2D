"""Render the replaceable bone SVG with consistent endpoint mapping and hit testing."""

import logging
import math
from collections import OrderedDict
from pathlib import Path
from xml.etree import ElementTree

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QTransform
from PySide6.QtSvg import QSvgRenderer

from rigora.infrastructure.bone_contrast import outline_svg
from rigora.resources import asset_path

_LOG = logging.getLogger(__name__)
_ROOT = QPointF(512, 1402)
_LENGTH = 1232.0
_FALLBACK = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1536">
<g fill="#a8a9ad" stroke="#414246" stroke-width="11">
<path d="M512 204 L393 1112 L512 1358 L631 1112 Z"/>
<circle cx="512" cy="170" r="54"/><circle cx="512" cy="1402" r="54"/>
</g></svg>"""


class BoneShape:
    """Own cached SVG variants and a silhouette mask; keep project geometry independent."""

    def __init__(self, path: Path | None = None) -> None:
        """Load one local SVG per viewport, falling back safely if a replacement is invalid."""
        try:
            data = (path or asset_path("shapes/bone.svg")).read_bytes()
            renderer = QSvgRenderer(QByteArray(data))
            if not renderer.isValid() or renderer.viewBoxF().isEmpty():
                raise ValueError("Invalid bone SVG")
            ElementTree.fromstring(data)
        except (OSError, ValueError, ElementTree.ParseError) as error:
            _LOG.warning("Cannot load bone shape; using fallback: %s", error)
            data = _FALLBACK
        self.data = data
        self.renderers = {"": QSvgRenderer(QByteArray(data))}
        self.outlines: OrderedDict[tuple[str, float], QSvgRenderer] = OrderedDict()
        self.tiles: OrderedDict[tuple[float, float, str, float], tuple[QImage, QPointF]] = (
            OrderedDict()
        )
        self.tile_bytes = 0
        self.bounds = self.renderers[""].viewBoxF()
        self.mask = QImage(512, 768, QImage.Format.Format_ARGB32_Premultiplied)
        self.mask.fill(Qt.GlobalColor.transparent)
        painter = QPainter(self.mask)
        self.renderers[""].render(painter, QRectF(self.mask.rect()))
        painter.end()

    @staticmethod
    def transform(root: QPointF, tip: QPointF, width_scale: float = 1) -> QTransform:
        """Map template root (512,1402) and tip (512,170) onto the displayed endpoints."""
        delta = tip - root
        scale = math.hypot(delta.x(), delta.y()) / _LENGTH
        transform = QTransform()
        transform.translate(root.x(), root.y())
        transform.rotate(math.degrees(math.atan2(delta.y(), delta.x())) + 90)
        transform.scale(scale * width_scale, scale)
        transform.translate(-_ROOT.x(), -_ROOT.y())
        return transform

    def renderer(self, tone: str) -> QSvgRenderer:
        """Reuse vector variants, tinting explicit SVG paint colors while retaining shading."""
        if tone not in self.renderers:
            tree = ElementTree.fromstring(self.data)
            tint = QColor(tone)
            for element in tree.iter():
                for attribute in ("fill", "stroke", "stop-color", "color"):
                    color = QColor(element.get(attribute, ""))
                    if color.isValid():
                        strength = color.lightnessF()
                        color.setRedF(tint.redF() * strength)
                        color.setGreenF(tint.greenF() * strength)
                        color.setBlueF(tint.blueF() * strength)
                        element.set(attribute, color.name())
                        if color.alpha() < 255 and attribute in ("fill", "stroke"):
                            try:
                                opacity = float(element.get(f"{attribute}-opacity", "1"))
                            except ValueError:
                                opacity = 1.0
                            element.set(f"{attribute}-opacity", str(opacity * color.alphaF()))
            self.renderers[tone] = QSvgRenderer(QByteArray(ElementTree.tostring(tree)))
        return self.renderers[tone]

    def draw(
        self,
        painter: QPainter,
        root: QPointF,
        tip: QPointF,
        tone: str = "",
        *,
        preview: bool = False,
        width_scale: float = 1,
    ) -> None:
        """Paint sharp source-derived editor overlays, reusing bounded supersampled tiles.

        Length, width, tint and output DPI determine the tile. Rotation and placement
        reuse it, avoiding repeated SVG stroke expansion during FK and navigation.
        Unusually large or externally scaled overlays retain direct vector rendering.
        This cache never supplies character artwork or deformation textures.
        """
        if root == tip:
            painter.save()
            painter.setPen(QPen(QColor(tone or "#bcbcbc"), 2))
            painter.setBrush(QColor("#242424"))
            painter.drawEllipse(root, 6, 6)
            painter.drawLine(root + QPointF(-10, 0), root + QPointF(10, 0))
            painter.drawLine(root + QPointF(0, -10), root + QPointF(0, 10))
            painter.restore()
            return
        painter.save()
        if preview:
            painter.setOpacity(painter.opacity() * 0.85)
        length = math.hypot(tip.x() - root.x(), tip.y() - root.y())
        ratio = painter.device().devicePixelRatioF() * 2
        key = (round(length, 6), width_scale, tone, ratio)
        if (
            not 1e-5 <= length <= 2048
            or not 0 < width_scale <= 8
            or not (
                painter.worldTransform().isIdentity() or painter.worldTransform().isTranslating()
            )
        ):
            self._draw_vector(painter, root, tip, tone, width_scale)
        else:
            tile = self.tiles.get(key)
            if tile is None:
                end = QPointF(key[0], 0)
                bounds = self.transform(QPointF(), end, width_scale).mapRect(self.bounds)
                padding = 3 * max(1, width_scale)
                rect = bounds.adjusted(-padding, -padding, padding, padding).toAlignedRect()
                needed = (
                    max(1, math.ceil(rect.width() * ratio))
                    * max(1, math.ceil(rect.height() * ratio))
                    * 4
                )
                if needed > 8 * 1024**2:
                    self._draw_vector(painter, root, tip, tone, width_scale)
                    painter.restore()
                    return
                image = QImage(
                    max(1, math.ceil(rect.width() * ratio)),
                    max(1, math.ceil(rect.height() * ratio)),
                    QImage.Format.Format_ARGB32_Premultiplied,
                )
                image.setDevicePixelRatio(ratio)
                image.fill(Qt.GlobalColor.transparent)
                target = QPainter(image)
                target.setRenderHint(QPainter.RenderHint.Antialiasing)
                target.translate(-rect.x(), -rect.y())
                self._draw_vector(target, QPointF(), end, tone, width_scale)
                target.end()
                while self.tiles and (
                    len(self.tiles) >= 128 or self.tile_bytes + image.sizeInBytes() > 8 * 1024**2
                ):
                    _, (old, _) = self.tiles.popitem(last=False)
                    self.tile_bytes -= old.sizeInBytes()
                tile = image, QPointF(rect.topLeft())
                self.tiles[key] = tile
                self.tile_bytes += image.sizeInBytes()
            self.tiles.move_to_end(key)
            painter.translate(root)
            painter.rotate(math.degrees(math.atan2(tip.y() - root.y(), tip.x() - root.x())))
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(tile[1], tile[0])
        painter.restore()

    def _draw_vector(
        self, painter: QPainter, root: QPointF, tip: QPointF, tone: str, width_scale: float
    ) -> None:
        """Draw source geometry and cosmetic outlines at the caller's current output scale."""
        painter.save()
        painter.setWorldTransform(self.transform(root, tip, width_scale), True)
        scale = max(0.001, math.hypot(tip.x() - root.x(), tip.y() - root.y()) / _LENGTH)
        dark = QColor(tone).darker(170).name() if tone else "#202020"
        for color, pixels in (("#eeeeee", 4.5), (dark, 2.5)):
            key = (color, round(pixels / scale, 1))
            renderer = self.outlines.get(key)
            if renderer is None:
                renderer = QSvgRenderer(QByteArray(outline_svg(self.data, *key)))
                self.outlines[key] = renderer
                while len(self.outlines) > 64:
                    self.outlines.popitem(last=False)
            else:
                self.outlines.move_to_end(key)
            renderer.render(painter, renderer.viewBoxF())
        self.renderer(tone).render(painter, self.bounds)
        painter.restore()

    def contains(self, point: QPointF, root: QPointF, tip: QPointF, width_scale: float = 1) -> bool:
        """Hit-test the rendered silhouette, including the root behind the bone origin."""
        if root == tip:
            return math.hypot(point.x() - root.x(), point.y() - root.y()) <= 10
        inverse, valid = self.transform(root, tip, width_scale).inverted()
        if not valid:
            return False
        local = inverse.map(point)
        if not self.bounds.contains(local):
            return False
        x = int((local.x() - self.bounds.x()) / self.bounds.width() * self.mask.width())
        y = int((local.y() - self.bounds.y()) / self.bounds.height() * self.mask.height())
        return (
            self.mask.pixelColor(
                min(x, self.mask.width() - 1), min(y, self.mask.height() - 1)
            ).alpha()
            > 16
        )
