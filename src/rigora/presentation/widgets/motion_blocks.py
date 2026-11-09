"""A direct motion arrangement view: move blocks, trim edges and adjust source speed."""

from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFocusEvent, QKeyEvent, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from rigora.application_services.characters import CharacterService
from rigora.presentation.viewmodels.animation_editor import AnimationEditorViewModel


class MotionBlocks(QWidget):
    """Render shared motion-window metadata without a separate animation playback system."""

    objects_dropped = Signal(object, float)

    def __init__(self, model: AnimationEditorViewModel) -> None:
        """Bind numeric settings to the same source clips used by the canonical track sampler."""
        super().__init__()
        self.model = model
        self.selected = ""
        self.blocks: list[dict[str, Any]] = []
        self.drag: tuple[dict[str, Any], float, str, float] | None = None
        box = QVBoxLayout(self)
        box.setContentsMargins(8, 6, 8, 6)
        box.setSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(8)
        box.addLayout(row)
        row.addWidget(QLabel("Speed ×"))
        self.speed = QDoubleSpinBox()
        self.speed.setRange(0.01, 100)
        self.speed.setValue(1)
        self.speed.setKeyboardTracking(False)
        row.addWidget(self.speed)
        self.speed.editingFinished.connect(self.apply_speed)
        self.repeat = QCheckBox("Repeat")
        row.addWidget(self.repeat)
        self.repeat.clicked.connect(self.apply_speed)
        remove = QPushButton("Remove block")
        remove.clicked.connect(self.remove)
        row.addWidget(remove)
        row.addStretch()
        self.note = QLabel(
            "Drag an Object from Scene onto this timeline to choose its animation. "
            "Drag edges to trim; drag the block to move."
        )
        self.note.setWordWrap(True)
        box.addWidget(self.note)
        self.canvas = BlockCanvas(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.canvas)
        box.addWidget(scroll, 1)
        model.changed.connect(self.refresh)
        model.focus_changed.connect(self.refresh)
        model.playback.changed.connect(self.canvas.update)

    def refresh(self) -> None:
        """Read unique blocks from evaluated tracks and preserve selection across Undo."""
        self.drag = None
        timeline = self.model.service.timeline if self.model.service else None
        unique = (
            {
                t.extra["motion_window"]["id"]: dict(t.extra["motion_window"])
                for t in timeline.tracks
                if t.extra.get("motion_window")
            }
            if timeline
            else {}
        )
        self.blocks = sorted(unique.values(), key=lambda b: (b["character"], b["start"]))
        if self.model.composer_owners is not None and self.model.service:
            actors = {
                c.id
                for c in self.model.service.scene.characters
                if c.skeleton_id in self.model.composer_owners
            }
            self.blocks = [b for b in self.blocks if b["character"] in actors]
        if self.selected not in unique:
            self.selected = ""
        selected = next((b for b in self.blocks if b["id"] == self.selected), None)
        if selected is None:
            self.selected = ""
        self.speed.setEnabled(selected is not None)
        self.repeat.setEnabled(selected is not None)
        if selected:
            self.speed.setValue(selected["speed"])
            self.repeat.setChecked(selected["repeat"])
        self.canvas.setMinimumHeight(max(130, 60 + 42 * len({b["character"] for b in self.blocks})))
        self.canvas.update()

    def apply_speed(self) -> None:
        """Speed changes source time; trimming changes only the visible interval."""
        if self.selected:
            self.model.run(
                lambda s: CharacterService(s.document).edit_segment(
                    self.selected, speed=self.speed.value(), repeat=self.repeat.isChecked()
                )
            )

    def remove(self) -> None:
        """Delete only the arranged instance, leaving its library motion untouched."""
        if self.selected:
            self.model.run(lambda s: CharacterService(s.document).remove_segment(self.selected))


class BlockCanvas(QWidget):
    """Paint and manipulate motion windows with one history command per completed drag."""

    def __init__(self, panel: MotionBlocks) -> None:
        """Use a flexible time scale shared by blocks and the playhead."""
        super().__init__(panel)
        self.panel = panel
        self.setMinimumHeight(130)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: Any) -> None:
        """Accept data-only scene object drags; the controller validates their document."""
        if event.mimeData().hasFormat("application/x-rigora-scene"):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: Any) -> None:
        """Keep the source drag active while the pointer chooses a frame."""
        self.dragEnterEvent(event)

    def dropEvent(self, event: Any) -> None:
        """Request an action picker at the dropped, frame-snapped scene time."""
        self.panel.objects_dropped.emit(
            event.mimeData(), max(0, round((event.position().x() - 120) / self.scale()))
        )
        event.acceptProposedAction()

    def scale(self) -> float:
        """Fit all arranged content without creating enormous scrolling surfaces."""
        if self.panel.drag:
            return self.panel.drag[3]
        end = max([120, *[b["end"] for b in self.panel.blocks]])
        return float(max(0.001, (self.width() - 140) / end))

    def rects(self) -> list[tuple[dict[str, Any], QRectF]]:
        """Place each character on a separate readable motion lane."""
        actors = list(dict.fromkeys(b["character"] for b in self.panel.blocks))
        return [
            (
                b,
                QRectF(
                    120 + b["start"] * self.scale(),
                    30 + actors.index(b["character"]) * 42,
                    max(8, (b["end"] - b["start"]) * self.scale()),
                    30,
                ),
            )
            for b in self.panel.blocks
        ]

    def paintEvent(self, event: Any) -> None:
        """Draw neutral blocks, trim grips and the shared timeline playhead."""
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#181818"))
        painter.setPen(QColor("#aaaaaa"))
        import math

        end = max([120, *[b["end"] for b in self.panel.blocks]])
        step = max(20, math.ceil(end / 60) * 10)
        for frame in range(0, math.ceil(end) + 1, step):
            painter.drawText(QPointF(120 + frame * self.scale(), 17), str(frame))
        for block, rect in self.rects():
            service = self.panel.model.service
            if service:
                actor = CharacterService(service.document).records().get(block["character"])
                painter.drawText(
                    QRectF(6, rect.top(), 108, rect.height()),
                    Qt.AlignmentFlag.AlignVCenter,
                    actor.name if actor else "Character",
                )
            painter.setBrush(QColor("#454545" if block["id"] == self.panel.selected else "#303030"))
            painter.setPen(
                QPen(QColor("#999999" if block["id"] == self.panel.selected else "#555555"), 1)
            )
            painter.drawRoundedRect(rect, 3, 3)
            painter.drawText(
                rect.adjusted(8, 0, -8, 0), Qt.AlignmentFlag.AlignVCenter, block["name"]
            )
            painter.drawLine(rect.topLeft() + QPointF(5, 5), rect.bottomLeft() + QPointF(5, -5))
            painter.drawLine(rect.topRight() + QPointF(-5, 5), rect.bottomRight() + QPointF(-5, -5))
        if self.panel.model.playback.session:
            x = 120 + self.panel.model.playback.session.pose.frame * self.scale()
            painter.setPen(QColor("#eeeeee"))
            painter.drawLine(QPointF(x, 20), QPointF(x, self.height()))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Choose a block and retain timing baselines for preview without document edits."""
        if (
            event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton)
            and event.position().x() >= 120
        ):
            self.panel.model.playback.seek(
                max(0, round((event.position().x() - 120) / self.scale()))
            )
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.setFocus()
        for block, rect in reversed(self.rects()):
            if rect.contains(event.position()):
                self.panel.selected = block["id"]
                self.panel.speed.setEnabled(True)
                self.panel.repeat.setEnabled(True)
                self.panel.speed.setValue(block["speed"])
                self.panel.repeat.setChecked(block["repeat"])
                edge = (
                    "start"
                    if abs(event.position().x() - rect.left()) < 9
                    else "end"
                    if abs(event.position().x() - rect.right()) < 9
                    else "move"
                )
                self.panel.drag = dict(block), event.position().x(), edge, self.scale()
                self.update()
                return

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Preview a trimmed/moved interval with frame snapping and matching resize cursors."""
        if self.panel.drag:
            original, press, edge, scale = self.panel.drag
            delta = round((event.position().x() - press) / scale)
            for block in self.panel.blocks:
                if block["id"] != original["id"]:
                    continue
                if edge == "move":
                    delta = max(-original["start"], delta)
                    block["start"] = original["start"] + delta
                    block["end"] = original["end"] + delta
                elif edge == "start":
                    block["start"] = max(0, min(original["end"] - 1, original["start"] + delta))
                else:
                    block["end"] = max(original["start"] + 1, original["end"] + delta)
            self.update()
            return
        for _, rect in self.rects():
            if rect.contains(event.position()):
                self.setCursor(
                    Qt.CursorShape.SizeHorCursor
                    if min(
                        abs(event.position().x() - rect.left()),
                        abs(event.position().x() - rect.right()),
                    )
                    < 9
                    else Qt.CursorShape.SizeAllCursor
                )
                return
        self.unsetCursor()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Commit one edit only after the timing gesture is complete."""
        if not self.panel.drag:
            return
        self.mouseMoveEvent(event)
        original, _, _, _ = self.panel.drag
        self.panel.drag = None
        block = next(b for b in self.panel.blocks if b["id"] == original["id"])
        if block == original:
            return
        self.panel.model.run(
            lambda s: CharacterService(s.document).edit_segment(
                block["id"], start=block["start"], end=block["end"]
            )
        )

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Escape discards a timing preview; Delete removes the selected instance."""
        if event.key() == Qt.Key.Key_Escape:
            self.panel.refresh()
        elif event.key() == Qt.Key.Key_Delete:
            self.panel.remove()
        else:
            super().keyPressEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        """Losing the editor cancels uncommitted timing gestures."""
        if self.panel.drag:
            self.panel.refresh()
        super().focusOutEvent(event)
