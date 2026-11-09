"""Native selectable timeline keys, connected tween spans and inline progress graphs."""

import math
from collections.abc import Mapping
from typing import Any

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QIcon,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QWheelEvent,
)
from PySide6.QtWidgets import QFrame, QGraphicsItem, QGraphicsScene, QGraphicsView, QWidget

from rigora.application_services.animation_editing import KeyRef
from rigora.domain.entities import Keyframe, Marker, Track
from rigora.domain.project import ProjectError
from rigora.engine.sampling import CompiledTrack, TrackSampler
from rigora.engine.transition_curves import TransitionCurve, curve_presets
from rigora.presentation.icons import IconProvider
from rigora.presentation.widgets.timeline_ruler import ROW_HEIGHT, RULER_HEIGHT, TimeRuler


class ActionGlyph(QGraphicsItem):
    """An icon-shaped key with a visible, compact selection outline."""

    def __init__(self, icon: QIcon, tone: QColor) -> None:
        """Keep the bundled vector-font icon sharp at the current display density."""
        super().__init__()
        self.icon = icon
        self.tone = tone

    def boundingRect(self) -> QRectF:
        """Include a generous hit target without extending into neighboring rows."""
        return QRectF(-9, -12, 18, 24)

    def paint(self, painter: QPainter, option: Any, widget: QWidget | None = None) -> None:
        """Use neutral selection feedback distinct from the icon silhouette."""
        selected_tone = self.tone if self.tone.lightness() < 128 else QColor("#eeeeee")
        if self.isSelected():
            painter.setPen(QPen(selected_tone, 1))
            painter.setBrush(QColor("#cfcfcf" if self.tone.lightness() < 128 else "#454545"))
            painter.drawRoundedRect(QRectF(-9, -10, 18, 20), 3, 3)
        self.icon.paint(painter, QRect(-8, -8, 16, 16))
        pen = QPen(selected_tone if self.isSelected() else self.tone, 1)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawLine(QPointF(0, -11), QPointF(0, -9))
        painter.drawLine(QPointF(0, 9), QPointF(0, 11))


class KeyCanvas(QGraphicsView):
    """Present immutable timeline data; release emits one edit rather than mutating it per pixel."""

    selected_keys = Signal(object)
    edited_keys = Signal(object)
    seek_requested = Signal(float)
    step_requested = Signal(int)
    lane_selected = Signal(object)
    range_selected = Signal(float, float)
    context_requested = Signal(object)
    insert_requested = Signal(object, float)
    inspect_requested = Signal()
    channels_dropped = Signal(object, float)
    objects_dropped = Signal(object, float)
    curve_requested = Signal(object)
    curve_dropped = Signal(object, str)
    preview_requested = Signal(object, float)
    preview_finished = Signal()
    end_frame_changed = Signal(float)
    zoom_changed = Signal(float)
    action_requested = Signal(object)
    motion_edited = Signal(object)
    motion_removed = Signal(str)

    def __init__(self, parent: QWidget) -> None:
        """Use Qt selection, rubber bands and scroll bars with independent time/value scales."""
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.pixels = 8.0
        self.rows: list[str | None] = []
        self.summary_rows: dict[int, tuple[str, ...]] = {}
        self.icons: IconProvider | None = None
        self.action_rows: dict[int, tuple[str, str]] = {}
        self.overview_rows: dict[int, tuple[str, ...]] = {}
        self._overview: dict[int, tuple[set[float], set[tuple[float, float]]]] = {}
        self.motions: list[dict[str, Any]] = []
        self.motion_graphics: list[QGraphicsItem] = []
        self.selected_motion = ""
        self._action_drag: tuple[dict[str, Any], float, str] | None = None
        self._motion_preview: dict[str, Any] | None = None
        self.tracks: tuple[Track, ...] = ()
        self.samplers: Mapping[str, TrackSampler] = {}
        self.markers: tuple[Marker, ...] = ()
        self.keys: dict[KeyRef, QGraphicsItem] = {}
        self.source: dict[KeyRef, Keyframe] = {}
        self.snap = True
        self.frame = 0.0
        self.end = 120.0
        self.start = 0.0
        self._building = False
        self._pressed: dict[QGraphicsItem, QPointF] = {}
        self._pan: QPoint | None = None
        self._drop_position: QPointF | None = None
        self._hover_slot: QPointF | None = None
        self.spans: list[tuple[tuple[KeyRef, ...], QGraphicsItem]] = []
        self._span_graphics: list[QGraphicsItem] = []
        self._body_start: QPointF | None = None
        self._body_selection = False
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setViewportMargins(0, RULER_HEIGHT, 0, 0)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.ruler = TimeRuler(self)
        self.setAccessibleName("Dope sheet keys and tween spans")
        self.setToolTip(
            "Click or right-click: seek · Double-click empty slot: add key · Ctrl+wheel: zoom"
        )
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setRubberBandSelectionMode(Qt.ItemSelectionMode.IntersectsItemShape)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.scene().selectionChanged.connect(self.selection_changed)
        self.setMinimumHeight(100)

    def rebuild(
        self,
        tracks: tuple[Track, ...],
        rows: list[str | None],
        markers: tuple[Marker, ...],
        selected: tuple[KeyRef, ...],
        end: float,
        summaries: dict[int, tuple[str, ...]] | None = None,
    ) -> None:
        """Recreate source/expanded key items, preserving scroll position."""
        self._building = True
        self._action_drag = None
        self._motion_preview = None
        self.motion_graphics.clear()
        horizontal, vertical = self.horizontalScrollBar().value(), self.verticalScrollBar().value()
        at_start = horizontal == self.horizontalScrollBar().minimum()
        self._pressed.clear()
        self._hover_slot = None
        self._body_start = None
        self.scene().clear()
        self.spans.clear()
        self._span_graphics.clear()
        self.keys.clear()
        self.source.clear()
        self.tracks, self.rows, self.markers, self.end = tracks, rows, markers, end
        indexed = {t.id: t for t in tracks if t.visible}
        self._overview = {}
        for row, ids in self.overview_rows.items():
            frames: set[float] = set()
            intervals: set[tuple[float, float]] = set()
            for identity in ids:
                track = indexed.get(identity)
                if track is None:
                    continue
                window = track.extra.get("motion_window") or track.extra.get("camera_action")
                if window:
                    frames.update((window["start"], window["end"]))
                    intervals.add((window["start"], window["end"]))
                else:
                    frames.update(k.frame for k in track.keyframes)
            self._overview[row] = frames, intervals
        if summaries is not None:
            self.summary_rows = summaries
        foreground = self.palette().color(self.foregroundRole())
        for track in tracks:
            if not track.visible or track.id not in rows:
                continue
            try:
                CompiledTrack(track, self.samplers)
            except ProjectError as error:
                self.setToolTip(str(error))
                continue
            for key in track.keyframes:
                ref = track.id, key.id
                row = rows.index(track.id)
                item = self.key_item(row, foreground)
                y = ROW_HEIGHT / 2 + row * ROW_HEIGHT
                item.setPos(key.frame * self.pixels, y)
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, not track.locked)
                item.setZValue(3)
                item.setData(0, (ref,))
                item.setSelected(ref in selected)
                choice = key.extra.get("appearance_choice")
                item.setToolTip(
                    f"{key.extra['attachment_label']} · frame {key.frame:g} "
                    "· Right-click: edit attachment"
                    if "attachment_label" in key.extra
                    else f"{choice['name']} · frame {key.frame:g} · Right-click: edit choice"
                    if choice
                    else f"{track.name} · frame {key.frame:g} · {key.value}"
                )
                self.keys[ref], self.source[ref] = item, key
        self.add_summaries(foreground)
        self.draw_motions()
        self.update_spans()
        width = max(
            600,
            self.end * self.pixels + 100,
            max((k.frame * self.pixels + 100 for k in self.source.values()), default=0),
        )
        # Include the entire centered frame-zero cell, even at close zoom levels.
        gutter = max(20, self.pixels / 2 + 8)
        self.setSceneRect(-gutter, 0, width + gutter, len(rows) * ROW_HEIGHT)
        self.horizontalScrollBar().setValue(
            self.horizontalScrollBar().minimum() if at_start else horizontal
        )
        self.verticalScrollBar().setValue(vertical)
        self._building = False
        self.sync_selection(selected)
        self.viewport().update()
        self.ruler.update()
        self.zoom_changed.emit(self.pixels / 8)

    def add_summaries(self, tone: QColor) -> None:
        """Represent compound properties as shared keys that select and move their real members."""
        for row, ids in self.summary_rows.items():
            grouped: dict[float, list[tuple[Track, Keyframe]]] = {}
            for track in self.tracks:
                if track.id in ids and track.visible:
                    for key in track.keyframes:
                        grouped.setdefault(key.frame, []).append((track, key))
            for frame, records in grouped.items():
                item = self.key_item(row, tone)
                item.setPos(frame * self.pixels, ROW_HEIGHT / 2 + row * ROW_HEIGHT)
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
                item.setFlag(
                    QGraphicsItem.GraphicsItemFlag.ItemIsMovable,
                    not any(t.locked for t, _ in records),
                )
                item.setZValue(3)
                refs = tuple((t.id, k.id) for t, k in records)
                item.setData(0, refs)
                choices = tuple(
                    dict.fromkeys(
                        str(k.extra["appearance_choice"]["name"])
                        for _, k in records
                        if k.extra.get("appearance_choice")
                    )
                )
                item.setToolTip(
                    f"{', '.join(choices)} · frame {frame:g} · Right-click: edit choice"
                    if choices
                    else f"{len(refs)} grouped keys · frame {frame:g}"
                )
                for track, key in records:
                    self.keys[track.id, key.id], self.source[track.id, key.id] = item, key

    def key_item(self, row: int, tone: QColor) -> QGraphicsItem:
        """Use semantic appearance icons while preserving ordinary key selection and dragging."""
        kind = self.action_rows.get(row, ("", ""))[1]
        if self.icons and kind in ("skins", "outfits", "views", "camera_cut", "attachment"):
            item = ActionGlyph(
                self.icons.icon(
                    {
                        "skins": "palette",
                        "outfits": "dry_cleaning",
                        "views": "360",
                        "camera_cut": "videocam",
                        "attachment": "link",
                    }[kind],
                    16,
                ),
                tone,
            )
            self.scene().addItem(item)
            return item
        return self.scene().addEllipse(-4, -4, 8, 8, QPen(tone), tone)

    def draw_motions(self) -> None:
        """Draw named spans and running-icon endpoints on the same frame grid as scalar keys."""
        for item in self.motion_graphics:
            self.scene().removeItem(item)
        self.motion_graphics.clear()
        if not self.icons:
            return
        if self.selected_motion and not any(b["id"] == self.selected_motion for b in self.motions):
            self.selected_motion = ""
        lanes = {(owner, kind): row for row, (owner, kind) in self.action_rows.items()}
        for source in self.motions:
            block = (
                self._motion_preview
                if self._motion_preview and self._motion_preview["id"] == source["id"]
                else source
            )
            kind = block.get("kind", "motion")
            row = lanes.get(
                ("__cameras__" if kind.startswith("camera_") else block["character"], kind)
            )
            if row is None:
                continue
            x, end = block["start"] * self.pixels, block["end"] * self.pixels
            y = row * ROW_HEIGHT + ROW_HEIGHT / 2
            selected = block["id"] == self.selected_motion
            tone = QColor("#dddddd" if selected else "#929292")
            body = self.scene().addRect(
                QRectF(x, y - 9, end - x, 18),
                QPen(Qt.PenStyle.NoPen),
                QColor(255, 255, 255, 12 if selected else 0),
            )
            label = self.scene().addSimpleText(
                self.fontMetrics().elidedText(
                    f"{block['name']} · {block['speed']:g}×",
                    Qt.TextElideMode.ElideRight,
                    max(0, round(end - x - 28)),
                )
            )
            label.setBrush(tone)
            label.setPos(
                (x + end - label.boundingRect().width()) / 2, y - label.boundingRect().height() / 2
            )
            path = QPainterPath(QPointF(x + 8, y))
            if label.text():
                path.lineTo(max(x + 8, label.pos().x() - 6), y)
                path.moveTo(min(end - 8, label.pos().x() + label.boundingRect().width() + 6), y)
            path.lineTo(end - 8, y)
            line = self.scene().addPath(path, QPen(tone, 1.5))
            parts: list[tuple[QGraphicsItem, str]] = [
                (body, "move"),
                (line, "move"),
                (label, "move"),
            ]
            for edge, position in (("start", x), ("end", end)):
                icon = ActionGlyph(
                    self.icons.icon(
                        "camera_enhance" if kind.startswith("camera_") else "directions_run",
                        16,
                        tone.name(),
                    ),
                    tone,
                )
                icon.setPos(position, y)
                icon.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
                self.scene().addItem(icon)
                icon.setSelected(selected)
                parts.append((icon, edge))
            for item, edge in parts:
                item.setData(6, (block["id"], edge))
                item.setZValue(4 if edge != "move" else 1)
                item.setCursor(
                    Qt.CursorShape.ArrowCursor
                    if block.get("locked")
                    else Qt.CursorShape.SizeHorCursor
                    if edge != "move"
                    else Qt.CursorShape.SizeAllCursor
                )
                item.setToolTip(
                    f"{block['name']} · {block['start']:g}–{block['end']:g} fr · "
                    f"{block['speed']:g}×\nDrag to move/trim · Right-click: speed, loop and source"
                )
                self.motion_graphics.append(item)

    def action_at(self, point: QPoint) -> dict[str, Any] | None:
        """Resolve motion endpoints, appearance keys, or empty action cells to stable identities."""
        for item in self.items(point):
            motion = item.data(6)
            if motion:
                block = next((b for b in self.motions if b["id"] == motion[0]), None)
                if block:
                    return {
                        "owner": block["character"],
                        "kind": block.get("kind", "motion"),
                        "frame": block["start"],
                        "segment": block["id"],
                        "edge": motion[1],
                    }
        row = int(self.mapToScene(point).y() // ROW_HEIGHT)
        lane = self.action_rows.get(row)
        if lane is None:
            return None
        refs = tuple(ref for item in self.items(point) for ref in (item.data(0) or ()))
        frame = self.source[refs[0]].frame if refs else self.frame_at(point)
        return {"owner": lane[0], "kind": lane[1], "frame": frame, "refs": refs}

    def update_spans(self) -> None:
        """Paint connected intervals and their actual easing thumbnails behind circular keys."""
        for item in self._span_graphics:
            self.scene().removeItem(item)
        self._span_graphics.clear()
        self.spans.clear()
        seen = set()
        tone = self.palette().windowText().color()
        for track in self.tracks:
            if not track.visible:
                continue
            for left, right in zip(track.keyframes, track.keyframes[1:], strict=False):
                a, b = (track.id, left.id), (track.id, right.id)
                if left.interpolation == "step" or a not in self.keys or b not in self.keys:
                    continue
                first, last = self.keys[a], self.keys[b]
                signature = (first, last)
                if signature in seen or first.pos().y() != last.pos().y():
                    continue
                seen.add(signature)
                x, y, end = first.pos().x(), first.pos().y(), last.pos().x()
                if end <= x:
                    continue
                refs = tuple(dict.fromkeys((*first.data(0), *last.data(0))))
                fill = QColor(tone)
                fill.setAlpha(55 if any(self.keys[r].isSelected() for r in refs) else 22)
                body = self.scene().addRect(QRectF(x, y - 8, end - x, 16), QPen(fill), fill)
                body.setData(2, refs)
                body.setZValue(1)
                body.setCursor(Qt.CursorShape.SizeHorCursor)
                body.setToolTip(
                    f"{track.name} · {left.frame:g}–{right.frame:g} · Double-click: edit graph"
                )
                path = QPainterPath(QPointF(x, y))
                if "transition_curve" in left.extra or left.interpolation == "bezier":
                    try:
                        graph = (
                            TransitionCurve.from_data(left.extra["transition_curve"])
                            if "transition_curve" in left.extra
                            else None
                        )
                        sampler = CompiledTrack(track, self.samplers)
                        samples = []
                        for i in range(65):
                            t = i / 64
                            progress = (
                                graph.sample(t)
                                if graph
                                else (
                                    (
                                        float(
                                            sampler.sample(
                                                left.frame + t * (right.frame - left.frame)
                                            )
                                            or 0
                                        )
                                        - float(left.value)
                                    )
                                    / (float(right.value) - float(left.value))
                                    if left.value != right.value
                                    else t
                                )
                            )
                            samples.append(progress)
                        low, high = min(0, *samples), max(1, *samples)
                        for i, progress in enumerate(samples):
                            point = QPointF(
                                x + i / 64 * (end - x), y + 6 - (progress - low) / (high - low) * 12
                            )
                            if i:
                                path.lineTo(point)
                            else:
                                path.moveTo(point)
                    except ProjectError:
                        path.lineTo(end, y)
                else:
                    path.lineTo(end, y)
                line = self.scene().addPath(path, QPen(tone, 1.4))
                line.setZValue(2)
                line.setData(2, refs)
                line.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                self.spans.append((refs, body))
                self._span_graphics.extend((body, line))

    def span_at(self, point: QPoint) -> tuple[KeyRef, ...]:
        """Resolve a body or curve stroke to its actual endpoint selection."""
        for item in self.items(point):
            if item.data(2):
                return tuple(item.data(2))
        return ()

    def select_refs(self, refs: tuple[KeyRef, ...]) -> None:
        """Select a complete span without recursively publishing intermediate selections."""
        self.sync_selection(refs)
        self.selected_keys.emit(refs)

    def selection_changed(self) -> None:
        """Share Qt rubber-band and Ctrl selection with the editor ViewModel."""
        if not self._building:
            self.selected_keys.emit(
                tuple(ref for ref, item in self.keys.items() if item.isSelected())
            )

    def sync_selection(self, selected: tuple[KeyRef, ...]) -> None:
        """Mirror selection without recursively publishing another selection change."""
        self._building = True
        for item in set(self.keys.values()):
            item.setSelected(any(ref in selected for ref in item.data(0)))
        self._building = False
        if selected and self.selected_motion:
            self.selected_motion = ""
            self.draw_motions()

    def drawBackground(self, painter: QPainter, rect: QRectF | QRect) -> None:
        """Draw neutral row/time guides using only the currently visible scene interval."""
        painter.fillRect(rect, self.palette().base())
        color = self.palette().color(self.foregroundRole())
        for row in range(
            max(0, int(rect.top() // ROW_HEIGHT)),
            min(len(self.rows), int(rect.bottom() // ROW_HEIGHT) + 1),
        ):
            if self.rows[row] is None and row not in self.summary_rows:
                painter.fillRect(
                    QRectF(rect.left(), row * ROW_HEIGHT, rect.width(), ROW_HEIGHT),
                    self.palette().alternateBase(),
                )
        step = max(1, 10 ** math.ceil(math.log10(4 / max(0.01, self.pixels))))
        major = max(10, step)
        shade = QColor(0, 0, 0, 85)
        for frame in range(
            max(0, int(rect.left() / self.pixels / major) * major),
            int(rect.right() / self.pixels) + major,
            major,
        ):
            painter.fillRect(
                QRectF((frame - 0.5) * self.pixels, rect.top(), self.pixels, rect.height()),
                shade,
            )
        for frame in range(
            max(0, int(rect.left() / self.pixels / step) * step),
            int(rect.right() / self.pixels) + step,
            step,
        ):
            color.setAlpha(28 if frame % 5 == 0 else 15)
            painter.setPen(QPen(shade if frame % 10 == 0 else color, 0))
            # Time positions are cell centers; coarse zoom groups frames into wider cells.
            x = (frame - step / 2) * self.pixels
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
        color.setAlpha(30)
        painter.setPen(QPen(color, 0))
        for y in range(
            max(0, int(rect.top() / ROW_HEIGHT) * ROW_HEIGHT),
            int(rect.bottom()) + ROW_HEIGHT,
            ROW_HEIGHT,
        ):
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        painter.save()
        painter.setOpacity(0.4)
        painter.setPen(QPen(self.palette().windowText().color(), 1))
        painter.setBrush(self.palette().windowText())
        for row, (frames, intervals) in self._overview.items():
            overview_y = row * ROW_HEIGHT + ROW_HEIGHT / 2
            if not rect.top() - ROW_HEIGHT <= overview_y <= rect.bottom() + ROW_HEIGHT:
                continue
            for start, end in intervals:
                painter.drawLine(
                    QPointF(start * self.pixels, overview_y), QPointF(end * self.pixels, overview_y)
                )
            for overview_frame in frames:
                if rect.left() - 4 <= overview_frame * self.pixels <= rect.right() + 4:
                    painter.drawEllipse(QPointF(overview_frame * self.pixels, overview_y), 2.5, 2.5)
        painter.restore()

    @property
    def end_boundary_x(self) -> float:
        """Return the scene-space edge after the inclusive last playable frame cell."""
        return (self.end + 0.5) * self.pixels

    def drawForeground(self, painter: QPainter, rect: QRectF | QRect) -> None:
        """Draw only scene-space indicators; time labels belong to the independent header."""
        color = self.palette().color(self.foregroundRole())
        painter.setPen(QPen(color, 1))
        painter.drawLine(
            QPointF(self.frame * self.pixels, rect.top()),
            QPointF(self.frame * self.pixels, rect.bottom()),
        )
        end = outside = self.end_boundary_x
        shade = QColor(self.palette().window().color())
        shade.setAlpha(140)
        if rect.right() > outside:
            painter.fillRect(
                QRectF(
                    max(outside, rect.left()),
                    rect.top(),
                    rect.right() - max(outside, rect.left()),
                    rect.height(),
                ),
                shade,
            )
        painter.setPen(QPen(color, 1, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(end, rect.top()), QPointF(end, rect.bottom()))
        if self._hover_slot is not None and not self._pressed:
            painter.save()
            painter.setOpacity(0.35)
            painter.setPen(QPen(color, 1))
            painter.setBrush(color)
            painter.drawEllipse(self._hover_slot, 4, 4)
            painter.restore()
        if self._drop_position is not None:
            painter.save()
            painter.setOpacity(0.45)
            x, y = self._drop_position.x(), self._drop_position.y()
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            painter.setBrush(color)
            painter.drawPolygon(
                QPolygonF(
                    [QPointF(x, y - 6), QPointF(x + 6, y), QPointF(x, y + 6), QPointF(x - 6, y)]
                )
            )
            painter.restore()

    def resizeEvent(self, event: Any) -> None:
        """Align the fixed ruler with the scrolling body, excluding native scroll bars."""
        super().resizeEvent(event)
        if hasattr(self, "ruler"):
            area = self.viewport().geometry()
            self.ruler.setGeometry(area.x(), area.y() - RULER_HEIGHT, area.width(), RULER_HEIGHT)

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        """Repaint independent labels and all invalidated key-area pixels after scrolling."""
        super().scrollContentsBy(dx, dy)
        if hasattr(self, "ruler"):
            self.ruler.update()
            self.viewport().update()

    def capture_positions(self) -> None:
        """Snapshot drag origins for lane constraints and the single release-time command."""
        self._pressed = {item: QPointF(item.pos()) for item in self.keys.values()}

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Start workspace panning or capture origins before Qt begins native key manipulation."""
        if event.button() == Qt.MouseButton.MiddleButton or (
            event.button() == Qt.MouseButton.LeftButton
            and event.modifiers() & Qt.KeyboardModifier.AltModifier
        ):
            self._pan = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        action = self.action_at(event.position().toPoint())
        if event.button() == Qt.MouseButton.LeftButton and action and action.get("segment"):
            block = next(b for b in self.motions if b["id"] == action["segment"])
            self.selected_motion = block["id"]
            self.select_refs(())
            self._action_drag = (
                (dict(block), self.mapToScene(event.position().toPoint()).x(), action["edge"])
                if not block.get("locked")
                else None
            )
            self.seek_requested.emit(self.frame_at(event.position().toPoint()))
            self.draw_motions()
            event.accept()
            return
        self.selected_motion = ""
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            self.seek_requested.emit(self.frame_at(event.position().toPoint()))
            self.lane_selected.emit(self.lane_at(event.position().toPoint()))
        self.capture_positions()
        self._body_start = None
        point = event.position().toPoint()
        item = self.itemAt(point)
        refs = self.span_at(point)
        if (
            event.button() == Qt.MouseButton.LeftButton
            and refs
            and (item is None or not item.data(0))
        ):
            self.select_refs(refs)
            self._body_selection = True
            self._body_start = self.mapToScene(point)
            event.accept()
            return
        if item is not None and item.data(0) and self._body_selection and not event.modifiers():
            self.select_refs(tuple(item.data(0)))
        self._body_selection = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Constrain keys to their lanes and evaluate transient span movement."""
        if self._action_drag:
            block, press, edge = self._action_drag
            delta = (self.mapToScene(event.position().toPoint()).x() - press) / self.pixels
            delta = round(delta) if self.snap else delta
            preview = dict(block)
            if edge == "move":
                delta = max(-block["start"], delta)
                preview.update(start=block["start"] + delta, end=block["end"] + delta)
            elif edge == "start":
                preview["start"] = max(0, min(block["end"] - 1, block["start"] + delta))
            else:
                preview["end"] = max(block["start"] + 1, block["end"] + delta)
            self._motion_preview = preview
            self.draw_motions()
            event.accept()
            return
        if not event.buttons():
            point = self.mapToScene(event.position().toPoint())
            row = int(point.y() // ROW_HEIGHT)
            active = 0 <= row < len(self.rows) and (
                self.rows[row] is not None or row in self.summary_rows
            )
            self._hover_slot = (
                QPointF(
                    self.frame_at(event.position().toPoint()) * self.pixels,
                    row * ROW_HEIGHT + ROW_HEIGHT / 2,
                )
                if active and self.itemAt(event.position().toPoint()) is None
                else None
            )
            self.viewport().update()
        if self._pan is not None:
            pan_delta = event.position().toPoint() - self._pan
            self._pan = event.position().toPoint()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - pan_delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - pan_delta.y())
        else:
            if self._body_start is not None:
                dx = self.mapToScene(event.position().toPoint()).x() - self._body_start.x()
                for item, previous in self._pressed.items():
                    if (
                        item.isSelected()
                        and item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsMovable
                    ):
                        item.setPos(previous.x() + dx, previous.y())
            else:
                super().mouseMoveEvent(event)
            selected = [
                (item, previous) for item, previous in self._pressed.items() if item.isSelected()
            ]
            if selected:
                item, previous = selected[0]
                frame_delta = (item.pos().x() - previous.x()) / self.pixels
                frame_delta = round(frame_delta) if self.snap else frame_delta
                frame_delta = max(frame_delta, -min(p.x() / self.pixels for _, p in selected))
                selected_items = {item for item, _ in selected}
                gap = (1 if self.snap else 1e-4) * self.pixels
                for track in self.tracks:
                    for left, right in zip(track.keyframes, track.keyframes[1:], strict=False):
                        a, b = (
                            self.keys.get((track.id, left.id)),
                            self.keys.get((track.id, right.id)),
                        )
                        if (
                            left.interpolation == "step"
                            or a not in self._pressed
                            or b not in self._pressed
                        ):
                            continue
                        duration = self._pressed[b].x() - self._pressed[a].x()
                        if a in selected_items and b not in selected_items:
                            frame_delta = min(frame_delta, max(0, duration - gap) / self.pixels)
                        elif b in selected_items and a not in selected_items:
                            frame_delta = max(frame_delta, min(0, gap - duration) / self.pixels)
                for item, previous in selected:
                    item.setPos(previous.x() + frame_delta * self.pixels, previous.y())
            edits = self.drag_edits()
            if edits:
                self.update_spans()
                frame = next(iter(edits.values()))["frame"]
                self.preview_requested.emit(edits, frame)

    def drag_edits(self) -> dict[KeyRef, dict[str, Any]]:
        """Collect transient endpoint changes using their press-time positions."""
        return {
            ref: {"frame": item.pos().x() / self.pixels}
            for ref, item in self.keys.items()
            if item in self._pressed and item.pos() != self._pressed[item]
        }

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Commit moved keys as one command, rejecting invalid edits upstream."""
        if self._action_drag:
            self.mouseMoveEvent(event)
            original, _, _ = self._action_drag
            preview = self._motion_preview
            self._action_drag = None
            self._motion_preview = None
            if preview and preview != original:
                self.motion_edited.emit(preview)
            self.draw_motions()
            event.accept()
            return
        if self._pan is not None:
            self._pan = None
            self.unsetCursor()
            return
        super().mouseReleaseEvent(event)
        edits: dict[KeyRef, dict[str, Any]] = {}
        for ref, item in self.keys.items():
            previous = self._pressed.get(item)
            if previous is not None and item.pos() != previous:
                frame = item.pos().x() / self.pixels
                edits[ref] = {"frame": frame}
        self._pressed.clear()
        self._body_start = None
        if edits:
            self.edited_keys.emit(edits)
        self.preview_finished.emit()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """Insert sampled keys in an empty lane, or open precision controls for existing keys."""
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseDoubleClickEvent(event)
            return
        action = self.action_at(event.position().toPoint())
        if action:
            self._action_drag = None
            self._pressed.clear()
            self.action_requested.emit(action)
            event.accept()
            return
        refs = self.span_at(event.position().toPoint())
        if refs:
            self._pressed.clear()
            self._body_start = None
            self.select_refs(refs)
            self._body_selection = True
            self.curve_requested.emit(refs)
            event.accept()
            return
        if self.itemAt(event.position().toPoint()) is not None:
            # Qt can start a native drag here without calling this view's mousePressEvent.
            self.capture_positions()
            super().mouseDoubleClickEvent(event)
            self.inspect_requested.emit()
            return
        point = self.mapToScene(event.position().toPoint())
        row = int(point.y() // ROW_HEIGHT)
        tracks = (
            (self.rows[row],)
            if 0 <= row < len(self.rows) and self.rows[row]
            else self.summary_rows.get(row, ())
        )
        if tracks:
            frame = max(0.0, point.x() / self.pixels)
            self.insert_requested.emit(tracks, round(frame) if self.snap else frame)

    def dragEnterEvent(self, event: Any) -> None:
        """Accept inert channel payloads while leaving authoring validation to shared services."""
        if (
            event.mimeData().hasFormat("application/x-rigora-scene")
            or event.mimeData().hasFormat("application/x-rigora-curve")
            or event.mimeData().hasFormat("application/x-rigora-animation-channels")
        ):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: Any) -> None:
        """Keep the channel copy active while the pointer chooses a destination frame."""
        self.dragEnterEvent(event)
        if event.isAccepted():
            point = self.mapToScene(event.position().toPoint())
            frame = max(0.0, point.x() / self.pixels)
            self._drop_position = QPointF(
                (round(frame) if self.snap else frame) * self.pixels, point.y()
            )
            self.viewport().update()

    def dragLeaveEvent(self, event: Any) -> None:
        """Discard prospective key feedback without changing any authoring records."""
        self._drop_position = None
        self.viewport().update()
        event.accept()

    def dropEvent(self, event: Any) -> None:
        """Publish the drop frame and opaque payload for source/session validation."""
        if event.mimeData().hasFormat("application/x-rigora-curve"):
            refs = self.span_at(event.position().toPoint())
            name = bytes(event.mimeData().data("application/x-rigora-curve")).decode(
                "utf-8", errors="replace"
            )
            self._drop_position = None
            if refs and name in curve_presets():
                self.curve_dropped.emit(refs, name)
                event.acceptProposedAction()
            else:
                event.ignore()
            self.viewport().update()
            return
        frame = max(0.0, self.mapToScene(event.position().toPoint()).x() / self.pixels)
        self._drop_position = None
        self.viewport().update()
        signal = (
            self.objects_dropped
            if event.mimeData().hasFormat("application/x-rigora-scene")
            else self.channels_dropped
        )
        signal.emit(event.mimeData(), round(frame) if self.snap else frame)
        event.acceptProposedAction()

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Use Ctrl-wheel for time zoom; ordinary wheel behavior remains native scrolling."""
        if event.modifiers() & (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
        ):
            self.zoom(1.2 if event.angleDelta().y() > 0 else 1 / 1.2, event.position().x())
            event.accept()
        elif event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - event.angleDelta().y()
            )
            event.accept()
        else:
            super().wheelEvent(event)

    def contextMenuEvent(self, event: Any) -> None:
        """Let the containing workspace provide shared clipboard and curve commands."""
        action = self.action_at(event.pos())
        if action:
            self.action_requested.emit(action)
            event.accept()
            return
        self.seek_requested.emit(self.frame_at(event.pos()))
        self.lane_selected.emit(self.lane_at(event.pos()))
        item = self.itemAt(event.pos())
        refs = (
            tuple(item.data(0)) if item is not None and item.data(0) else self.span_at(event.pos())
        )
        if refs and not all(self.keys[r].isSelected() for r in refs):
            self.select_refs(refs)
        self.context_requested.emit(event.globalPos())

    def step_frame_key(self, event: QKeyEvent) -> bool:
        """Step focused time surfaces without intercepting tree or text-field arrow keys."""
        if event.modifiers() == Qt.KeyboardModifier.NoModifier and event.key() in (
            Qt.Key.Key_Left,
            Qt.Key.Key_Right,
        ):
            self.step_requested.emit(1 if event.key() == Qt.Key.Key_Right else -1)
            event.accept()
            return True
        return False

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Cancel a motion preview or delete the selected arranged instance."""
        if self.step_frame_key(event):
            return
        if event.key() == Qt.Key.Key_Escape and self._action_drag:
            self._action_drag = None
            self._motion_preview = None
            self.draw_motions()
            event.accept()
        elif event.key() == Qt.Key.Key_Delete and self.selected_motion:
            self.motion_removed.emit(self.selected_motion)
            event.accept()
        else:
            super().keyPressEvent(event)

    def focusOutEvent(self, event: Any) -> None:
        """Discard unfinished motion timing when another editor takes keyboard focus."""
        if self._action_drag:
            self._action_drag = None
            self._motion_preview = None
            self.draw_motions()
        super().focusOutEvent(event)

    def frame_at(self, position: QPoint) -> float:
        """Map body clicks to the same nonnegative frame slots as the ruler."""
        frame = max(0.0, self.mapToScene(position).x() / self.pixels)
        return round(frame) if self.snap else frame

    def lane_at(self, position: QPoint) -> tuple[str, ...]:
        """Resolve a logical property row; owner headers deliberately have no animation lane."""
        row = int(self.mapToScene(position).y() // ROW_HEIGHT)
        key = self.rows[row] if 0 <= row < len(self.rows) else None
        return (key,) if key else self.summary_rows.get(row, ())

    def zoom(self, factor: float, anchor: float | None = None) -> None:
        """Scale time around a pointer or the visible playhead without moving authored keys."""
        if anchor is None:
            anchor = min(
                self.viewport().width(),
                max(0, self.mapFromScene(QPointF(self.frame * self.pixels, 0)).x()),
            )
        frame = self.mapToScene(round(anchor), 0).x() / self.pixels
        self.pixels = max(0.05, min(200, self.pixels * factor))
        self.rebuild(
            self.tracks,
            self.rows,
            self.markers,
            tuple(ref for ref, item in self.keys.items() if item.isSelected()),
            self.end,
        )
        self.horizontalScrollBar().setValue(round(frame * self.pixels - anchor))

    def leaveEvent(self, event: QEvent) -> None:
        """Clear prospective key feedback when the pointer leaves the frame grid."""
        self._hover_slot = None
        self.viewport().update()
        super().leaveEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        """Recolor persistent graphics when the application palette changes."""
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange and hasattr(self, "keys"):
            selected = tuple(ref for ref, item in self.keys.items() if item.isSelected())
            self.rebuild(self.tracks, self.rows, self.markers, selected, self.end)
