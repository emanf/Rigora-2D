"""Shared cubic control-point canvas for original vector artwork and Object/camera motion paths."""

from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from rigora.application_services.path_editing import PathEditingService
from rigora.domain.project import ProjectError
from rigora.presentation.themes import palette_colors, transparency_brush
from rigora.presentation.widgets.clip_editor import numeric
from rigora.presentation.widgets.window_frame import CustomDialog

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


class PathCanvas(QWidget):
    """Drag cubic anchors/handles on a fixed local canvas without mutating project data."""

    changed = Signal()

    def __init__(self) -> None:
        """Retain only transient curve controls; Apply owns the eventual Undo command."""
        super().__init__()
        self.points = [(40.0, 256.0), (128.0, 40.0), (384.0, 480.0), (472.0, 256.0)]
        self.canvas_width, self.canvas_height = 512.0, 512.0
        self.drag_index: int | None = None
        self.setMinimumSize(380, 280)
        self.setMouseTracking(True)

    def display(self, point: tuple[float, float]) -> QPointF:
        """Map authored coordinates into a stable padded preview rectangle."""
        return QPointF(
            16 + point[0] * (self.width() - 32) / self.canvas_width,
            16 + point[1] * (self.height() - 32) / self.canvas_height,
        )

    def paintEvent(self, event: object) -> None:
        """Render cubic geometry and distinguish anchors from tangent handles."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = palette_colors(self.palette())
        painter.fillRect(self.rect(), transparency_brush(self.palette()))
        painter.setPen(QPen(QColor(colors["grid"]), 1))
        for i in range(len(self.points) - 1):
            if i % 3 != 1:
                painter.drawLine(self.display(self.points[i]), self.display(self.points[i + 1]))
        curve = QPainterPath(self.display(self.points[0]))
        for i in range(1, len(self.points), 3):
            curve.cubicTo(*(self.display(p) for p in self.points[i : i + 3]))
        painter.setPen(QPen(QColor(colors["preview_ink"]), 2))
        painter.drawPath(curve)
        for i, point in enumerate(self.points):
            painter.setBrush(QColor(colors["preview_ink"] if i % 3 == 0 else colors["grid"]))
            painter.drawEllipse(self.display(point), 5, 5)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Pick a visible control handle within ten pixels."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_index = next(
                (
                    i
                    for i, p in enumerate(self.points)
                    if (self.display(p) - event.position()).manhattanLength() <= 12
                ),
                None,
            )
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Update transient controls live without creating history entries."""
        if self.drag_index is not None:
            p = event.position()
            self.points[self.drag_index] = (
                min(
                    self.canvas_width,
                    max(0.0, (p.x() - 16) * self.canvas_width / (self.width() - 32)),
                ),
                min(
                    self.canvas_height,
                    max(0.0, (p.y() - 16) * self.canvas_height / (self.height() - 32)),
                ),
            )
            self.changed.emit()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Finish transient handle manipulation; Apply remains the sole source commit."""
        self.drag_index = None


class PathEditor(CustomDialog):
    """Author persistent vector controls or a live scene/parent-space path-progress channel."""

    def __init__(self, host: "MainWindow") -> None:
        """List workspace owners and reuse their authored controls."""
        super().__init__(host, "Bezier artwork & motion paths")
        self.host, self.document = host, host.viewmodel.documents
        self.scene_id, self.context = self.document.scene.id, self.document.animation_context
        self.mesh_id = ""
        self.stroke_width = 2.0
        self.resize(660, 760)
        box = QVBoxLayout(self.content)
        form = QFormLayout()
        box.addLayout(form)
        self.mode, self.owner = QComboBox(), QComboBox()
        self.mode.addItems(("Motion path", "Vector artwork"))
        self.owner.addItem("Choose Object or camera", "")
        for item in (
            *self.document.scene.groups,
            *self.document.scene.objects,
            *self.document.scene.cameras,
        ):
            if self.document.animation_scope is None or item.id in self.document.animation_scope:
                self.owner.addItem(item.name, item.id)
        self.orient, self.closed = QCheckBox("Follow tangent"), QCheckBox("Closed filled curve")
        self.space = QComboBox()
        self.space.addItem("World", "world")
        self.space.addItem("Parent", "parent")
        self.start = numeric(self, "Path start", minimum=0, maximum=1e7)
        self.end = numeric(self, "Path end", minimum=0, maximum=1e7)
        self.end.setValue(self.document.scene.settings.fps)
        self.fill, self.stroke = QLineEdit("#bcbcbc"), QLineEdit("#ffffff")
        for label, field in (
            ("Mode", self.mode),
            ("Owner", self.owner),
            ("Space", self.space),
            ("Start frame", self.start),
            ("End frame", self.end),
            ("", self.orient),
            ("", self.closed),
            ("Fill #RRGGBB", self.fill),
            ("Outline #RRGGBB", self.stroke),
        ):
            form.addRow(label, field)
        self.canvas = PathCanvas()
        box.addWidget(self.canvas, 1)
        self.note = QLabel("Drag anchors and tangent handles. Apply commits one undoable edit.")
        self.note.setWordWrap(True)
        box.addWidget(self.note)
        row = QHBoxLayout()
        box.addLayout(row)
        for label, callback in (
            ("Add segment", self.add_segment),
            ("Remove segment", self.remove_segment),
            ("Apply", self.apply),
            ("Close", self.close),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            row.addWidget(button)
        self.owner.currentIndexChanged.connect(self.load)
        self.mode.currentIndexChanged.connect(self.mode_changed)
        selected = next(iter(host.viewmodel.scene.selected), "")
        self.owner.setCurrentIndex(max(0, self.owner.findData(selected)))
        self.mode_changed()

    def mode_changed(self) -> None:
        """Expose only fields relevant to the selected authoring task."""
        artwork = self.mode.currentIndex() == 1
        for field in (self.space, self.start, self.end, self.orient):
            field.setEnabled(not artwork)
        for art_field in (self.closed, self.fill, self.stroke):
            art_field.setEnabled(artwork)
        self.load()

    def load(self) -> None:
        """Read stored controls without modifying the document or its playback frame."""
        self.mesh_id = ""
        self.stroke_width = 2.0
        scene = self.document.scene
        if self.mode.currentIndex() == 0:
            self.canvas.canvas_width = float(scene.settings.width)
            self.canvas.canvas_height = float(scene.settings.height)
            rule = next(
                (
                    c
                    for c in scene.constraints
                    if c.owner_id == self.owner.currentData() and c.kind == "motion_path"
                ),
                None,
            )
            if rule:
                self.canvas.points = list(rule.parameters["points"])
                self.orient.setChecked(rule.parameters.get("orient", False))
                self.space.setCurrentIndex(
                    self.space.findData(rule.parameters.get("space", "world"))
                )
                timeline = self.document.animation.evaluator.timeline
                track = (
                    next(
                        (
                            t
                            for t in timeline.tracks
                            if t.owner_id == rule.id
                            and t.property_path == "parameters.progress"
                            and not t.extra.get("motion_window")
                        ),
                        None,
                    )
                    if timeline
                    else None
                )
                if track and track.keyframes:
                    self.start.setValue(min(k.frame for k in track.keyframes))
                    self.end.setValue(max(k.frame for k in track.keyframes))
        else:
            mesh = next(
                (
                    m
                    for m in scene.meshes
                    if m.object_id == self.owner.currentData() and m.extra.get("bezier_art")
                ),
                None,
            )
            self.canvas.canvas_width = self.canvas.canvas_height = 512.0
            if mesh:
                self.mesh_id = mesh.id
                data = mesh.extra["bezier_art"]
                self.canvas.points = list(data["points"])
                self.canvas.canvas_width, self.canvas.canvas_height = data["width"], data["height"]
                self.closed.setChecked(data["closed"])
                self.fill.setText(data["fill"])
                self.stroke.setText(data["stroke"])
                self.stroke_width = data.get("stroke_width", 2.0)
        self.canvas.update()

    def add_segment(self) -> None:
        """Append a complete control triplet, keeping the previous endpoint connected."""
        if len(self.canvas.points) < 193:
            x, y = self.canvas.points[-1]
            self.canvas.points.extend((x + 10 * i, y) for i in (1, 2, 3))
            self.canvas.update()

    def remove_segment(self) -> None:
        """Retain at least one complete cubic segment."""
        if len(self.canvas.points) > 4:
            del self.canvas.points[-3:]
            self.canvas.update()

    def apply(self) -> None:
        """Publish shared service data only in the original document/scene/workspace."""

        def edit(_: object) -> None:
            if (
                self.host.viewmodel.documents is not self.document
                or self.document.scene.id != self.scene_id
                or self.document.animation_context != self.context
            ):
                raise ProjectError("Reopen the curve editor in the active workspace.")
            service = PathEditingService(self.document)
            if self.mode.currentIndex() == 0:
                service.motion(
                    self.owner.currentData(),
                    self.canvas.points,
                    self.start.value(),
                    self.end.value(),
                    orient=self.orient.isChecked(),
                    space=self.space.currentData(),
                )
            else:
                self.mesh_id = service.artwork(
                    self.canvas.points,
                    mesh_id=self.mesh_id,
                    closed=self.closed.isChecked(),
                    fill=self.fill.text(),
                    stroke=self.stroke.text(),
                    stroke_width=self.stroke_width,
                    width=self.canvas.canvas_width,
                    height=self.canvas.canvas_height,
                )

        self.host.viewmodel.scene.run(edit)
        self.note.setText(
            self.host.viewmodel.scene.error
            or "Curve saved. Motion progress is editable in the timeline."
        )
