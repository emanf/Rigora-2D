"""Worker decoding, native SVG deformation and raster mapping of evaluated artwork triangles."""

import math
from collections import Counter, OrderedDict
from collections.abc import Callable
from functools import lru_cache
from io import BytesIO
from typing import cast
from uuid import uuid4

from PySide6.QtCore import (
    QByteArray,
    QCoreApplication,
    QObject,
    QPointF,
    QRectF,
    QRunnable,
    Qt,
    Signal,
)
from PySide6.QtGui import QImage, QPainter, QPainterPath, QPolygonF, QRegion, QTransform
from PySide6.QtSvg import QSvgRenderer
from shiboken6 import isValid

from rigora.domain.geometry import Matrix, inverse, multiply, transform_point
from rigora.domain.project import ProjectError
from rigora.engine.state import MeshPose
from rigora.infrastructure.artwork import inspect_artwork


@lru_cache(maxsize=128)
def triangle_edges(triangles: tuple[tuple[int, ...], ...]) -> tuple[tuple[int, int], ...]:
    """Index each topology edge once, independent of changing vertex positions or camera."""
    return tuple(
        dict.fromkeys(
            (a, b) if a < b else (b, a)
            for face in triangles
            for a, b in zip(face, (*face[1:], face[0]), strict=True)
        )
    )


def mesh_polygon(
    positions: tuple[tuple[float, float], ...], matrix: Matrix, zoom: float, offset: QPointF
) -> QPolygonF:
    """Map a mesh into viewport pixels in Qt, sharing geometry across paint and picking."""
    a, b, c, d, x, y = matrix
    transform = QTransform(
        a * zoom,
        b * zoom,
        c * zoom,
        d * zoom,
        x * zoom + offset.x(),
        y * zoom + offset.y(),
    )
    return transform.map(QPolygonF([QPointF(*point) for point in positions]))


def decode_artwork(
    data: bytes, preview_limit: int = 2048, *, upscale_vectors: bool = False
) -> QImage:
    """Decode bounded previews off-thread; optionally enlarge vectors for readable card icons."""
    info = inspect_artwork(data)
    scale = preview_limit / max(info.width, info.height)
    if info.kind != "vector" or not upscale_vectors:
        scale = min(1.0, scale)
    width, height = max(1, round(info.width * scale)), max(1, round(info.height * scale))
    if info.kind == "vector":
        renderer = QSvgRenderer(QByteArray(data))
        if not renderer.isValid():
            raise ProjectError("Qt could not render this static SVG.")
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
    else:
        try:
            from PIL import Image
        except ImportError:
            image = QImage.fromData(QByteArray(data))
            if image.isNull() or image.width() != info.width or image.height() != info.height:
                raise ProjectError("The image pixel data is corrupt or unsupported.") from None
            if scale < 1:
                image = image.scaled(
                    width,
                    height,
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
        else:
            # The render extra already provides Pillow. Decode raster pixels there
            # so parallel workers avoid Qt's process-wide image-plugin loader.
            try:
                with Image.open(BytesIO(data)) as source:
                    if source.size != (info.width, info.height):
                        raise ProjectError("Image pixels do not match their validated bounds.")
                    rgba = source.convert("RGBA")
                    if scale < 1:
                        rgba = rgba.resize((width, height), Image.Resampling.LANCZOS)
                    pixels = rgba.tobytes()
                image = QImage(pixels, width, height, width * 4, QImage.Format.Format_RGBA8888)
            except (OSError, ValueError) as error:
                raise ProjectError("The image pixel data is corrupt or unsupported.") from error
        # Conversion owns its pixels independently of the decoder's temporary buffer.
        image = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    return image


class ArtworkResult(QObject):
    """Carry immutable source bytes and an owned QImage back to the GUI thread."""

    finished = Signal(str, object, object, str)


class ArtworkJob(QRunnable):
    """Decode one bounded artwork request without touching widgets or document commands."""

    def __init__(self, read: Callable[[], bytes], preview_limit: int = 2048) -> None:
        """Capture only a read operation; the GUI decides whether a completion is still relevant."""
        super().__init__()
        self.read = read
        self.token = str(uuid4())
        self.preview_limit = preview_limit
        self.signals = ArtworkResult(QCoreApplication.instance())

    def run(self) -> None:
        """Publish a detached image or a recoverable error; never mutate the active project."""
        try:
            data = self.read()
            image = decode_artwork(data, self.preview_limit)
        except (OSError, ProjectError, ValueError) as error:
            self.signals.finished.emit(self.token, None, None, str(error))
        else:
            self.signals.finished.emit(self.token, data, image, "")
        finally:
            if isValid(self.signals):
                self.signals.deleteLater()


class ArtworkCache:
    """Adapt previews to a 128 MiB budget while retaining original sources in document storage."""

    def __init__(self) -> None:
        """Initialize an empty owned LRU cache without allocating image pixels."""
        self.images: OrderedDict[str, QImage] = OrderedDict()
        self.vectors: dict[str, QSvgRenderer] = {}
        self.originals: dict[str, bytes] = {}
        self.looks: OrderedDict[tuple[str, str], QImage | QSvgRenderer] = OrderedDict()
        self.limit = 2048

    def adapt(self, count: int) -> None:
        """Share preview pixels among referenced artwork to avoid evicting needed small images."""
        self.limit = max(1, min(2048, int(math.sqrt(128 * 1024**2 / 4 / max(1, count)))))
        for key, image in tuple(self.images.items()):
            if max(image.width(), image.height()) > self.limit:
                self.put(key, image)

    def put(self, key: str, image: QImage, source: bytes | None = None) -> None:
        """Cache thumbnails and retain original SVG renderers for scalable vector painting."""
        if source is not None:
            self.looks = OrderedDict((k, v) for k, v in self.looks.items() if k[0] != key)
            self.vectors.pop(key, None)
            self.originals[key] = source
        if source is not None and inspect_artwork(source).kind == "vector":
            renderer = QSvgRenderer(QByteArray(source))
            if not renderer.isValid():
                raise ProjectError("Qt could not render this static SVG.")
            self.vectors[key] = renderer
        if max(image.width(), image.height()) > self.limit:
            image = image.scaled(
                self.limit,
                self.limit,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self.images[key] = image
        self.images.move_to_end(key)
        while sum(i.sizeInBytes() for i in self.images.values()) > 128 * 1024**2:
            self.images.popitem(last=False)

    def get(self, key: str) -> QImage | None:
        """Resolve a preview and mark it as recently rendered."""
        image = self.images.get(key)
        if image is not None:
            self.images.move_to_end(key)
        return image

    def clear(self) -> None:
        """Release raster thumbnails and vector documents on eviction or project closure."""
        self.images.clear()
        self.vectors.clear()
        self.originals.clear()
        self.looks.clear()

    def styled(self, key: str, appearance: object) -> QImage | QSvgRenderer | None:
        """Reuse bounded frame looks, recoloring original vectors and tinting raster previews."""
        from collections.abc import Mapping

        from rigora.engine.vector_appearance import paint_changed, styled_artwork

        if not isinstance(appearance, Mapping) or not appearance:
            return self.vectors.get(key) or self.get(key)
        if not paint_changed(appearance):
            return self.vectors.get(key) or self.get(key)
        identity = key, repr(appearance)
        if identity in self.looks:
            self.looks.move_to_end(identity)
            return self.looks[identity]
        source = self.originals.get(key)
        if key in self.vectors and source:
            result: QImage | QSvgRenderer = QSvgRenderer(
                QByteArray(styled_artwork(source, appearance))
            )
        elif source and appearance.get("palette"):
            preview = self.get(key)
            limit = max(preview.width(), preview.height()) if preview is not None else self.limit
            result = decode_artwork(styled_artwork(source, appearance, raster_limit=limit), limit)
        else:
            original = self.get(key)
            if original is None:
                return None
            result = original.copy()
            tint = appearance.get("tint", {})
            amount = min(1, max(0, tint.get("amount", 0)))
            if amount:
                from PySide6.QtGui import QColor

                painter = QPainter(result)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
                red, green, blue = (
                    round(min(255, max(0, tint.get(c, 255)))) for c in ("r", "g", "b")
                )
                painter.fillRect(
                    result.rect(),
                    QColor(
                        red,
                        green,
                        blue,
                        round(amount * 255),
                    ),
                )
                painter.end()
        self.looks[identity] = result
        while (
            len(self.looks) > 16
            or sum(v.sizeInBytes() for v in self.looks.values() if isinstance(v, QImage))
            > 64 * 1024**2
        ):
            self.looks.popitem(last=False)
        return result


@lru_cache(maxsize=128)
def _source_faces(
    uv: tuple[tuple[float, float], ...],
    triangles: tuple[tuple[int, ...], ...],
    width: int,
    height: int,
) -> tuple[tuple[tuple[tuple[float, float], ...], Matrix | None], ...]:
    """Compile unchanged UV triangle inverses once per topology and source resolution."""
    result = []
    for face in triangles:
        source = tuple((uv[i][0] * width, uv[i][1] * height) for i in face)
        a, b, c = source
        basis = (b[0] - a[0], b[1] - a[1], c[0] - a[0], c[1] - a[1], a[0], a[1])
        try:
            mapping = inverse(basis)
        except ProjectError:
            mapping = None
        result.append((source, mapping))
    return tuple(result)


@lru_cache(maxsize=128)
def _boundary_loops(triangles: tuple[tuple[int, ...], ...]) -> tuple[tuple[int, ...], ...]:
    """Extract closed mesh boundaries once; ambiguous/nonmanifold topology uses triangle clips."""
    edges = [(a, b) for face in triangles for a, b in zip(face, (*face[1:], face[0]), strict=True)]
    counts = Counter((min(a, b), max(a, b)) for a, b in edges)
    boundary = [(a, b) for a, b in edges if counts[min(a, b), max(a, b)] == 1]
    following = dict(boundary)
    if len(following) != len(boundary) or any(value > 2 for value in counts.values()):
        return ()
    loops = []
    while following:
        start = next(iter(following))
        ring, cursor = [], start
        while cursor in following:
            ring.append(cursor)
            cursor = following.pop(cursor)
        if cursor != start or len(ring) < 3:
            return ()
        loops.append(tuple(ring))
    return tuple(loops)


def _affine_patch(
    mesh: MeshPose,
    points: tuple[QPointF, ...],
    faces: tuple[tuple[tuple[tuple[float, float], ...], Matrix | None], ...],
    width: int,
    height: int,
    tolerance: float,
) -> tuple[Matrix, QRegion, frozenset[int]] | None:
    """Clip a large unchanged vector region once during a localized vertex edit.

    Three representative triangles find a shared affine map without assuming the
    first vertex stayed fixed. Boundary extraction is cached by topology, including
    interior holes; ambiguous boundaries retain the ordinary triangle path.
    """
    if len(faces) < 128:
        return None
    best: tuple[Matrix, tuple[bool, ...]] | None = None
    count = 0
    for index in (0, len(faces) // 2, len(faces) - 1):
        mapping = faces[index][1]
        if mapping is None:
            continue
        p, q, r = (points[i] for i in mesh.triangles[index])
        matrix = multiply(
            (q.x() - p.x(), q.y() - p.y(), r.x() - p.x(), r.y() - p.y(), p.x(), p.y()),
            mapping,
        )
        matches = tuple(
            math.dist(transform_point(matrix, u * width, v * height), (p.x(), p.y())) <= tolerance
            for (u, v), p in zip(mesh.uv, points, strict=True)
        )
        matched = sum(matches)
        if matched > count:
            best, count = (matrix, matches), matched
    if best is None or count < len(points) * 0.8:
        return None
    matrix, matches = best
    indices = frozenset(
        index for index, face in enumerate(mesh.triangles) if all(matches[i] for i in face)
    )
    loops = _boundary_loops(tuple(face for i, face in enumerate(mesh.triangles) if i in indices))
    if not loops:
        return None
    path = QPainterPath()
    for ring in loops:
        path.addPolygon(QPolygonF([points[i] for i in ring]))
        path.closeSubpath()
    return matrix, QRegion(path.toFillPolygon().toPolygon()), indices


def draw_mesh(
    painter: QPainter, mesh: MeshPose, points: tuple[QPointF, ...], image: QImage | QSvgRenderer
) -> None:
    """Warp raster pixels or original SVG vector primitives through the evaluated mesh triangles."""
    size = image.defaultSize() if isinstance(image, QSvgRenderer) else image.size()
    batches: list[tuple[Matrix, QRegion]] = []
    raster_batches: dict[Matrix, QPainterPath] = {}
    device = painter.device()
    tolerance = 0.25 / (device.devicePixelRatioF() if device else 1)
    painter.save()
    # Shared triangle edges need hard clip coverage to avoid double-blended translucent seams.
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    faces = _source_faces(mesh.uv, mesh.triangles, size.width(), size.height())
    first = next(
        (
            (face, mapping)
            for face, (_source, mapping) in zip(mesh.triangles, faces, strict=True)
            if mapping is not None
        ),
        None,
    )
    if first is not None:
        face, uniform_mapping = first
        p, q, r = (points[i] for i in face)
        matrix = multiply(
            (q.x() - p.x(), q.y() - p.y(), r.x() - p.x(), r.y() - p.y(), p.x(), p.y()),
            uniform_mapping,
        )
        uniform = all(
            math.dist(
                transform_point(matrix, u * size.width(), v * size.height()), (point.x(), point.y())
            )
            <= tolerance
            for (u, v), point in zip(mesh.uv, points, strict=True)
        )
        loops = _boundary_loops(mesh.triangles) if uniform else ()
        if loops:
            path = QPainterPath()
            for ring in loops:
                path.addPolygon(QPolygonF([points[i] for i in ring]))
                path.closeSubpath()
            if isinstance(image, QSvgRenderer):
                viewport = QPainterPath()
                viewport.addRect(QRectF(painter.viewport()))
                path = path.intersected(viewport)
                painter.setClipRegion(
                    QRegion(path.toFillPolygon().toPolygon()), Qt.ClipOperation.IntersectClip
                )
                painter.setTransform(QTransform(*matrix))
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                image.render(painter, QRectF(0, 0, size.width(), size.height()))
            else:
                painter.setClipPath(path, Qt.ClipOperation.IntersectClip)
                painter.setTransform(QTransform(*matrix))
                painter.drawImage(QPointF(), image)
            painter.restore()
            return
    patch = (
        _affine_patch(mesh, points, faces, size.width(), size.height(), tolerance)
        if isinstance(image, QSvgRenderer)
        else None
    )
    patch_added = False
    for index, (face, (source, mapping)) in enumerate(zip(mesh.triangles, faces, strict=True)):
        if patch is not None and index in patch[2]:
            if not patch_added:
                batches.append((patch[0], patch[1]))
                patch_added = True
            continue
        if mapping is None:
            continue
        target = [points[i] for i in face]
        if any(not math.isfinite(v) or abs(v) > 1e7 for p in target for v in (p.x(), p.y())):
            continue
        p, q, r = target
        destination = (q.x() - p.x(), q.y() - p.y(), r.x() - p.x(), r.y() - p.y(), p.x(), p.y())
        matrix = multiply(destination, mapping)
        path = QPainterPath(p)
        path.lineTo(q)
        path.lineTo(r)
        path.closeSubpath()
        if isinstance(image, QSvgRenderer):
            # Regions keep shared-edge coverage hard while SVG curves retain antialiasing.
            clipped = QPolygonF(target).intersected(QPolygonF(QRectF(painter.viewport())))
            if clipped.isEmpty():
                continue
            region = QRegion(clipped.toPolygon())
            candidates = (
                range(len(batches))
                if len(batches) <= 32
                else (0, *range(len(batches) - 32, len(batches)))
            )
            for index in candidates:
                previous, coverage = batches[index]
                if all(
                    math.dist(transform_point(previous, *uv), (point.x(), point.y())) <= tolerance
                    for uv, point in zip(source, target, strict=True)
                ):
                    batches[index] = previous, coverage.united(region)
                    break
            else:
                batches.append((matrix, region))
            continue
        # Rigid raster regions need one source draw, regardless of subdivision.
        # Quantization removes affine noise far below a device pixel at supported sizes.
        normalized = cast(Matrix, tuple(0.0 if abs(v) < 1e-10 else round(v, 8) for v in matrix))
        raster_batches.setdefault(normalized, QPainterPath()).addPath(path)
    if isinstance(image, QImage):
        for matrix, path in raster_batches.items():
            painter.save()
            painter.setClipPath(path, Qt.ClipOperation.IntersectClip)
            painter.setTransform(QTransform(*matrix))
            painter.drawImage(QPointF(), image)
            painter.restore()
    if isinstance(image, QSvgRenderer):
        for matrix, region in batches:
            painter.save()
            painter.setClipRegion(region, Qt.ClipOperation.IntersectClip)
            painter.setTransform(QTransform(*matrix))
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            image.render(painter, QRectF(0, 0, size.width(), size.height()))
            painter.restore()
    painter.restore()


def mesh_contains(
    mesh: MeshPose,
    points: tuple[QPointF, ...],
    image: QImage | QSvgRenderer,
    point: QPointF,
    *,
    opacity: float = 1.0,
    pixel_ratio: float = 1.0,
) -> bool:
    """Probe painted coverage at a screen point using the actual deformed artwork renderer.

    A three-pixel scratch image preserves SVG curves, holes, source alpha and UV
    deformation without allocating an object-sized mask or using SVG thumbnails.
    Only the center device pixel counts; transparent margins never enlarge the
    pick area. Effective alpha below 8/255 is ignored as visually negligible.
    """
    if opacity * 255 < 8 or not any(
        QPolygonF([points[i] for i in triangle]).containsPoint(point, Qt.FillRule.OddEvenFill)
        for triangle in mesh.triangles
    ):
        return False
    sample = QImage(3, 3, QImage.Format.Format_ARGB32_Premultiplied)
    sample.setDevicePixelRatio(pixel_ratio)
    sample.fill(Qt.GlobalColor.transparent)
    painter = QPainter(sample)
    try:
        painter.setOpacity(opacity)
        center = QPointF(1.5 / pixel_ratio, 1.5 / pixel_ratio)
        draw_mesh(painter, mesh, tuple(p - point + center for p in points), image)
    finally:
        painter.end()
    return sample.pixelColor(1, 1).alpha() >= 8
