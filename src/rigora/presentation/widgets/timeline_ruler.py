"""Independent timeline header whose pixels never participate in key-area scrolling."""

import math
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPainter, QPolygonF
from PySide6.QtWidgets import QWidget

if TYPE_CHECKING:
    from rigora.presentation.widgets.key_canvas import KeyCanvas

RULER_HEIGHT = 40
ROW_HEIGHT = 24


class TimeRuler(QWidget):
    """Draw fixed time/marker lanes and delegate scrubbing to the canonical transport."""

    def __init__(self, canvas: "KeyCanvas") -> None:
        """Own only header interaction, retaining the canvas's horizontal time mapping."""
        super().__init__(canvas)
        self.canvas = canvas
        self.start: float | None = None
        self._end_drag = False
        self._original_end = canvas.end
        self._end_press_frame = 0.0
        self.show_marker_labels = True
        self.setAccessibleName("Timeline ruler · drag to scrub, Shift-drag to select a range")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip(
            "Drag to scrub · Left/Right: step one frame · Shift-drag: select range · "
            "Drag End to cap the last playable cell · Loop-closing keys may follow the cap"
        )

    def paintEvent(self, event: Any) -> None:
        """Paint adaptive ticks and elided marker names in separate, opaque header lanes."""
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().window())
        tone = self.palette().windowText().color()
        painter.setPen(tone)
        canvas = self.canvas
        left = canvas.mapToScene(0, 0).x() / canvas.pixels
        right = canvas.mapToScene(self.width(), 0).x() / canvas.pixels
        spacing = max(55, painter.fontMetrics().horizontalAdvance(str(max(0, int(right)))) + 18)
        raw = spacing / canvas.pixels
        power = 10 ** math.floor(math.log10(max(1, raw)))
        step = next(n * power for n in (1, 2, 5, 10) if n * power >= raw)
        minor = max(1, 10 ** math.ceil(math.log10(4 / max(0.01, canvas.pixels))))
        for frame in range(max(0, math.floor(left / minor) * minor), int(right) + minor, minor):
            x = canvas.mapFromScene(QPointF(frame * canvas.pixels, 0)).x()
            painter.drawLine(
                x, 22 if frame % 10 == 0 else 29 if frame % 5 == 0 else 34, x, RULER_HEIGHT
            )
        for frame in range(max(0, math.floor(left / step) * step), int(right) + step, step):
            x = canvas.mapFromScene(QPointF(frame * canvas.pixels, 0)).x()
            label = str(frame)
            painter.drawText(
                QPointF(x - painter.fontMetrics().horizontalAdvance(label) / 2, 15), label
            )
            painter.drawLine(x, 20, x, RULER_HEIGHT)
        markers = sorted(canvas.markers, key=lambda m: m.frame)
        for i, marker in enumerate(markers):
            x = canvas.mapFromScene(QPointF(marker.frame * canvas.pixels, 0)).x()
            next_x = (
                canvas.mapFromScene(QPointF(markers[i + 1].frame * canvas.pixels, 0)).x()
                if i + 1 < len(markers)
                else self.width()
            )
            available = min(self.width(), next_x) - max(0, x) - 8
            painter.drawLine(x, 25, x, 39)
            if self.show_marker_labels and available > 24:
                text = painter.fontMetrics().elidedText(
                    marker.name, Qt.TextElideMode.ElideRight, available
                )
                painter.drawText(QPointF(max(0, x) + 4, 35), text)
        x = canvas.mapFromScene(QPointF(canvas.frame * canvas.pixels, 0)).x()
        painter.setBrush(tone)
        painter.drawPolygon(QPolygonF([QPointF(x - 5, 0), QPointF(x + 5, 0), QPointF(x, 8)]))
        end = canvas.mapFromScene(QPointF(canvas.end_boundary_x, 0)).x()
        painter.drawLine(end, 0, end, RULER_HEIGHT)
        painter.drawPolygon(
            QPolygonF(
                [QPointF(end, 20), QPointF(end + 10, 20), QPointF(end + 10, 32), QPointF(end, 36)]
            )
        )

    def end_handle(self) -> QRectF:
        """Return the flag hit area in fixed-header coordinates, independent of scrolling."""
        x = self.canvas.mapFromScene(QPointF(self.canvas.end_boundary_x, 0)).x()
        return QRectF(x - 2, 18, 16, 22)

    def drag_end(self, event: QMouseEvent) -> None:
        """Preview a bounded end-frame delta while retaining the flag's press offset."""
        point = self.viewport_position(event)
        time = self.canvas.mapToScene(point).x() / self.canvas.pixels
        end = self._original_end + time - self._end_press_frame
        self.canvas.end = min(
            10_000_000, max(self.canvas.start + 1, round(end) if self.canvas.snap else end)
        )
        self.update()
        self.canvas.viewport().update()

    def frame_at(self, event: QMouseEvent) -> float:
        """Map a header pointer to nonnegative snapped or fractional time."""
        return self.canvas.frame_at(self.viewport_position(event))

    def viewport_position(self, event: QMouseEvent) -> QPoint:
        """Convert sibling header/body coordinates before applying the shared time mapping."""
        return event.position().toPoint() + self.pos() - self.canvas.viewport().pos()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Begin a scrub, optionally retaining the start of a range selection."""
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            event.accept()
        if event.button() == Qt.MouseButton.RightButton:
            self.canvas.seek_requested.emit(self.frame_at(event))
        if event.button() == Qt.MouseButton.LeftButton:
            if self.end_handle().contains(event.position()):
                self._end_drag = True
                self._original_end = self.canvas.end
                point = self.viewport_position(event)
                self._end_press_frame = self.canvas.mapToScene(point).x() / self.canvas.pixels
                event.accept()
                return
            frame = self.frame_at(event)
            self.start = frame if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else None
            self.canvas.seek_requested.emit(frame)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Retain ruler keyboard ownership after scrubbing and step the shared playhead."""
        if not self.canvas.step_frame_key(event):
            super().keyPressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Seek continuously while Qt retains the header's mouse grab."""
        if event.buttons() & Qt.MouseButton.LeftButton:
            if self._end_drag:
                self.drag_end(event)
                return
            self.canvas.seek_requested.emit(self.frame_at(event))

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Publish a completed ruler range without moving authored keys."""
        if self._end_drag:
            self.drag_end(event)
            self._end_drag = False
            if self.canvas.end != self._original_end:
                self.canvas.end_frame_changed.emit(self.canvas.end)
            return
        if self.start is not None:
            end = self.frame_at(event)
            self.canvas.range_selected.emit(min(self.start, end), max(self.start, end))
        self.start = None
