"""Shared screen-space move/rotate/scale handles for artwork, bones and editable points."""

import math
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QKeyEvent, QPainter, QPen, QPolygonF, QTransform

from rigora.presentation.icons import IconProvider


def modifiers_after(event: QKeyEvent) -> Qt.KeyboardModifier:
    """Resolve Shift/Alt after a key transition without truncating other modifier bits.

    Qt toggles the transitioning key in its reported modifiers. Integer masking
    avoids the enum complement dropping higher bits such as Alt on Shift release.
    """
    flag = (
        Qt.KeyboardModifier.ShiftModifier
        if event.key() == Qt.Key.Key_Shift
        else Qt.KeyboardModifier.AltModifier
    )
    bits = event.modifiers().value
    return Qt.KeyboardModifier(
        bits | flag.value if event.type() == QEvent.Type.KeyPress else bits & ~flag.value
    )


def bounds(points: list[QPointF], padding: float = 12) -> QRectF | None:
    """Return a usable handle box even for horizontal, vertical or single-point selections."""
    if not points:
        return None
    xs, ys = [p.x() for p in points], [p.y() for p in points]
    center = QPointF((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
    width, height = (
        max(24, max(xs) - min(xs) + padding * 2),
        max(24, max(ys) - min(ys) + padding * 2),
    )
    return QRectF(center.x() - width / 2, center.y() - height / 2, width, height)


def handles(rect: QRectF, mapping: QTransform | None = None) -> list[QPointF]:
    """Order eight resize handles clockwise, followed by the separate rotation grip."""
    points = [
        QPointF(rect.left() + x * rect.width(), rect.top() + y * rect.height())
        for x, y in ((0, 0), (0.5, 0), (1, 0), (1, 0.5), (1, 1), (0.5, 1), (0, 1), (0, 0.5))
    ]
    if mapping is not None:
        points = [mapping.map(p) for p in points]
    normal = points[1] - points[5]
    length = math.hypot(normal.x(), normal.y())
    return points + [points[1] + normal * (24 / max(1e-9, length))]


def pick(
    rect: QRectF,
    point: QPointF,
    mapping: QTransform | None = None,
    pivot: QPointF | None = None,
) -> int | None:
    """Hit-test handles before artwork with a constant device-independent pixel tolerance."""
    if pivot is not None and math.hypot(*(pivot - point).toTuple()) <= 8:
        return 9
    distances = [
        (math.hypot(*(p - point).toTuple()), i) for i, p in enumerate(handles(rect, mapping))
    ]
    distance, index = min(distances)
    return index if distance <= 8 else None


def draw(
    painter: QPainter,
    rect: QRectF,
    color: str,
    hover: int | None = None,
    mapping: QTransform | None = None,
    pivot: QPointF | None = None,
) -> None:
    """Paint a neutral bounding box, resize squares and connected rotation grip."""
    painter.save()
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor(color), 1))
    points = handles(rect, mapping)
    painter.drawPolygon(QPolygonF([points[i] for i in (0, 2, 4, 6)]))
    painter.drawLine(points[1], points[8])
    for index, p in enumerate(points[:8]):
        painter.setBrush(QColor(color) if index == hover else Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(p - QPointF(4, 4), p + QPointF(4, 4)))
    painter.setBrush(QColor(color) if hover == 8 else Qt.BrushStyle.NoBrush)
    painter.drawEllipse(points[8], 6, 6)
    if pivot is not None:
        painter.setBrush(QColor(color) if hover == 9 else Qt.BrushStyle.NoBrush)
        painter.drawEllipse(pivot, 5, 5)
        painter.drawLine(pivot - QPointF(9, 0), pivot + QPointF(9, 0))
        painter.drawLine(pivot - QPointF(0, 9), pivot + QPointF(0, 9))
    painter.restore()


def cursor(
    handle: int, icons: IconProvider | None = None, points: list[QPointF] | None = None
) -> QCursor:
    """Use native directional resizing and a Material rotation cursor, including rotated boxes."""
    if handle == 9:
        return QCursor(Qt.CursorShape.SizeAllCursor)
    if handle == 8:
        return (
            QCursor(icons.icon("rotate_right", 24).pixmap(24, 24), 12, 12)
            if icons
            else QCursor(Qt.CursorShape.CrossCursor)
        )
    if points is not None:
        delta = points[handle] - points[(handle + 4) % 8]
        axis = round(math.atan2(delta.y(), delta.x()) / (math.pi / 4)) % 4
    else:
        axis = (1, 2, 3, 0, 1, 2, 3, 0)[handle]
    return QCursor(
        (
            Qt.CursorShape.SizeHorCursor,
            Qt.CursorShape.SizeFDiagCursor,
            Qt.CursorShape.SizeVerCursor,
            Qt.CursorShape.SizeBDiagCursor,
        )[axis]
    )


@dataclass
class Gesture:
    """Retain the original box and pointer so every preview derives from the press state."""

    rect: QRectF
    start: QPointF
    handle: int
    pivot: QPointF | None = None
    mapping: QTransform | None = None

    def values(
        self,
        point: QPointF,
        centered: bool = False,
        snap: bool = False,
        proportional: bool | None = None,
    ) -> tuple[QPointF, float, float, float]:
        """Return screen pivot, rotation delta and X/Y factors; corners preserve proportions."""
        pivot = (
            self.pivot
            if self.pivot is not None and (centered or self.handle == 8)
            else self.rect.center()
            if self.handle == 8 or centered
            else handles(self.rect)[(self.handle + 4) % 8]
        )
        screen_pivot = self.mapping.map(pivot) if self.mapping is not None else pivot
        if self.handle == 8:
            a, b = self.start - screen_pivot, point - screen_pivot
            angle = math.degrees(math.atan2(b.y(), b.x()) - math.atan2(a.y(), a.x()))
            angle = (angle + 180) % 360 - 180
            if snap:
                angle = round(angle / 15) * 15
            return screen_pivot, angle, 1, 1
        inverse = self.mapping.inverted()[0] if self.mapping is not None else QTransform()
        a, b = inverse.map(self.start) - pivot, inverse.map(point) - pivot
        sx = b.x() / a.x() if self.handle not in (1, 5) and abs(a.x()) > 1e-9 else 1
        sy = b.y() / a.y() if self.handle not in (3, 7) and abs(a.y()) > 1e-9 else 1
        uniform = centered or self.handle % 2 == 0 if proportional is None else proportional
        if uniform:
            factor = (
                sy
                if proportional is not None and self.handle in (1, 5)
                else sx
                if proportional is not None and self.handle in (3, 7)
                else (a.x() * b.x() + a.y() * b.y()) / max(1e-9, a.x() ** 2 + a.y() ** 2)
            )
            sx = sy = factor
        return screen_pivot, 0, max(0.01, min(100, sx)), max(0.01, min(100, sy))
