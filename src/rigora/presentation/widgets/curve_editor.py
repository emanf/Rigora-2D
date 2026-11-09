"""Contextual transition-graph editing with draggable dots and offline easing presets."""

from dataclasses import replace
from typing import Any

from PySide6.QtCore import QEvent, QMimeData, QPointF, QRectF, QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QKeyEvent, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from rigora.domain.project import ProjectError
from rigora.engine.transition_curves import TransitionCurve, curve_presets
from rigora.presentation.icons import IconProvider
from rigora.presentation.themes import palette_colors
from rigora.presentation.widgets.asset_cards import configure_card_grid
from rigora.presentation.widgets.window_frame import CustomDialog

CURVE_MIME = "application/x-rigora-curve"


def graph_path(
    curve: TransitionCurve, area: QRectF, low: float = 0, high: float = 1
) -> QPainterPath:
    """Sample a normalized transition into a thumbnail/graph rectangle, including overshoot."""
    path = QPainterPath()
    for i in range(161):
        t = i / 160
        point = QPointF(
            area.left() + t * area.width(),
            area.bottom() - (curve.sample(t) - low) / (high - low) * area.height(),
        )
        if i:
            path.lineTo(point)
        else:
            path.moveTo(point)
    return path


class CurvePresets(QListWidget):
    """Searchable original graph thumbnails carrying a whitelisted preset name on drag."""

    def __init__(self, parent: QWidget) -> None:
        """Build an offline draggable preset shelf independent of document state."""
        super().__init__(parent)
        self.setAccessibleName("Transition graph presets · drag onto a tween or graph")
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setSupportedDragActions(Qt.DropAction.CopyAction)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        configure_card_grid(self)
        for name in curve_presets():
            item = QListWidgetItem(name)
            item.setToolTip(name + " · click to preview or drag onto a tween")
            self.addItem(item)
        self.refresh_thumbnails()

    def refresh_thumbnails(self) -> None:
        """Repaint cached graph icons after light/dark palette changes."""
        presets = curve_presets()
        for i in range(self.count()):
            item = self.item(i)
            curve = presets[item.text()]
            pixmap = QPixmap(100, 56)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(QColor(palette_colors(self.palette())["preview_ink"]), 2))
            values = [y for _, y in curve.points]
            painter.drawPath(
                graph_path(curve, QRectF(6, 6, 88, 44), min(0, *values), max(1, *values))
            )
            painter.end()
            item.setIcon(QIcon(pixmap))

    def changeEvent(self, event: QEvent) -> None:
        """Keep preset strokes visible after a host palette change."""
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            self.refresh_thumbnails()

    def filter(self, text: str) -> None:
        """Filter names without discarding preset identities or thumbnails."""
        for i in range(self.count()):
            self.item(i).setHidden(text.casefold() not in self.item(i).text().casefold())

    def mimeTypes(self) -> list[str]:
        """Declare the data-only preset drag format."""
        return [CURVE_MIME]

    def mimeData(self, items: Any) -> QMimeData:
        """Encode one preset name; no executable or serialized Python data crosses the drag."""
        data = QMimeData()
        if items:
            data.setData(CURVE_MIME, items[0].text().encode())
        return data


class CurveCanvas(QWidget):
    """Edit normalized dots while preserving fixed endpoints and strict time ordering."""

    changed = Signal(object)
    selection_changed = Signal(int)

    @property
    def selected(self) -> int:
        """Return the point shared by the graph and its accessible numerical editor."""
        return getattr(self, "_selected", -1)

    @selected.setter
    def selected(self, index: int) -> None:
        """Notify equivalent controls whenever pointer or keyboard selection changes."""
        if index != self.selected:
            self._selected = index
            self.selection_changed.emit(index)
            self.update()

    def __init__(self, parent: QWidget) -> None:
        """Own a transient graph and local edit history, separate from project Undo."""
        super().__init__(parent)
        self.curve = TransitionCurve()
        self.selected = -1
        self.progress = 0.0
        self.snap = False
        self._undo: list[TransitionCurve] = []
        self._redo: list[TransitionCurve] = []
        self._drag_source: TransitionCurve | None = None
        self.setMinimumSize(380, 230)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAcceptDrops(True)
        self.setAccessibleName(
            "Transition graph · double-click to add dots, drag to edit, Delete to remove"
        )
        self.setAccessibleDescription(
            "Ctrl+arrows select a point; arrows nudge it. Shift makes larger steps and Alt "
            "makes fine steps. Home/End select anchors; Insert adds a point. "
            "Point selector, time and value fields provide equivalent controls."
        )
        self.setToolTip(self.accessibleDescription())

    def area(self) -> QRectF:
        """Reserve labels around the graph's editable rectangle."""
        return QRectF(self.rect()).adjusted(42, 20, -20, -32)

    def limits(self) -> tuple[float, float]:
        """Fit overshooting graphs while keeping a stable minimum progress interval."""
        values = [y for _, y in self.curve.points]
        return min(-0.2, min(values) - 0.1), max(1.2, max(values) + 0.1)

    def point_at(self, x: float, y: float) -> QPointF:
        """Map a normalized progress point into widget pixels."""
        area, (low, high) = self.area(), self.limits()
        return QPointF(
            area.left() + x * area.width(), area.bottom() - (y - low) / (high - low) * area.height()
        )

    def value_at(self, point: QPointF) -> tuple[float, float]:
        """Map pointer pixels to bounded graph values, applying optional tenth-unit snapping."""
        area, (low, high) = self.area(), self.limits()
        x = max(0.0, min(1.0, (point.x() - area.left()) / area.width()))
        y = max(-4.0, min(5.0, low + (area.bottom() - point.y()) / area.height() * (high - low)))
        return (round(x * 10) / 10, round(y * 10) / 10) if self.snap else (x, y)

    def set_curve(self, curve: TransitionCurve) -> None:
        """Replace transient controls and retain one local history entry for a changed graph."""
        if curve != self.curve:
            self._undo.append(self.curve)
            self._redo.clear()
        self.curve, self.selected = curve, -1
        self.update()
        self.changed.emit(curve)

    def undo(self) -> None:
        """Restore the previous local graph without changing project history."""
        if self._undo:
            self._redo.append(self.curve)
            self.curve, self.selected = self._undo.pop(), -1
            self.update()
            self.changed.emit(self.curve)

    def redo(self) -> None:
        """Reapply a local graph edit."""
        if self._redo:
            self._undo.append(self.curve)
            self.curve, self.selected = self._redo.pop(), -1
            self.update()
            self.changed.emit(self.curve)

    def add_dot(self) -> None:
        """Insert a sample in the largest unused time interval, within the 257-dot budget."""
        a, b = max(
            zip(self.curve.points, self.curve.points[1:], strict=False),
            key=lambda pair: pair[1][0] - pair[0][0],
        )
        if len(self.curve.points) < 257:
            x = (a[0] + b[0]) / 2
            point = x, self.curve.sample(x)
            self.set_curve(replace(self.curve, points=tuple(sorted((*self.curve.points, point)))))
            self.selected = self.curve.points.index(point)

    def delete_dot(self) -> None:
        """Remove a selected interior point while preserving both endpoint anchors."""
        if 0 < self.selected < len(self.curve.points) - 1:
            self.set_curve(
                replace(
                    self.curve,
                    points=tuple(p for i, p in enumerate(self.curve.points) if i != self.selected),
                )
            )

    def edit_point(self, index: int, x: float, y: float) -> None:
        """Move an interior point, keeping endpoints fixed and neighboring times ordered."""
        if not 0 < index < len(self.curve.points) - 1:
            return
        points = list(self.curve.points)
        x = max(points[index - 1][0] + 1e-5, min(points[index + 1][0] - 1e-5, x))
        points[index] = x, max(-4.0, min(5.0, y))
        self.set_curve(replace(self.curve, points=tuple(points)))
        self.selected = index

    def paintEvent(self, event: Any) -> None:
        """Draw a neutral grid, evaluated curve, editable dots and moving preview marker."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), self.palette().base())
        tone = self.palette().windowText().color()
        grid = QColor(tone)
        grid.setAlpha(35)
        painter.setPen(QPen(grid, 1))
        area = self.area()
        for i in range(11):
            x = area.left() + i * area.width() / 10
            painter.drawLine(QPointF(x, area.top()), QPointF(x, area.bottom()))
        for i in range(6):
            y = area.top() + i * area.height() / 5
            painter.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
        painter.setPen(QPen(tone, 2))
        painter.drawPath(graph_path(self.curve, area, *self.limits()))
        for index, (x, y) in enumerate(self.curve.points):
            painter.setBrush(tone if index == self.selected else self.palette().base())
            painter.drawEllipse(self.point_at(x, y), 4, 4)
        painter.setBrush(tone)
        painter.drawEllipse(self.point_at(self.progress, self.curve.sample(self.progress)), 5, 5)
        painter.drawText(QPointF(area.left(), self.height() - 9), "Time  0%")
        painter.drawText(QPointF(area.right() - 35, self.height() - 9), "100%")
        painter.drawText(QPointF(4, 14), "Progress")

    def mousePressEvent(self, event: Any) -> None:
        """Pick the nearest dot without changing its value until the pointer moves."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            self.selected = next(
                (
                    i
                    for i, (x, y) in enumerate(self.curve.points)
                    if (self.point_at(x, y) - event.position()).manhattanLength() <= 12
                ),
                -1,
            )
            self._drag_source = self.curve
            self.update()

    def mouseMoveEvent(self, event: Any) -> None:
        """Drag an interior dot without crossing neighbors or modifying endpoint anchors."""
        i = self.selected
        if not (event.buttons() & Qt.MouseButton.LeftButton and 0 < i < len(self.curve.points) - 1):
            return
        x, y = self.value_at(event.position())
        points = list(self.curve.points)
        x = max(points[i - 1][0] + 1e-5, min(points[i + 1][0] - 1e-5, x))
        points[i] = x, y
        self.curve = replace(self.curve, points=tuple(points))
        self.update()
        self.changed.emit(self.curve)

    def mouseReleaseEvent(self, event: Any) -> None:
        """Commit one local Undo entry for the completed handle drag."""
        if self._drag_source is not None and self._drag_source != self.curve:
            self._undo.append(self._drag_source)
            self._redo.clear()
        self._drag_source = None

    def mouseDoubleClickEvent(self, event: Any) -> None:
        """Insert an editable dot at an unused interior time with one native double-click."""
        x, y = self.value_at(event.position())
        if (
            0 < x < 1
            and len(self.curve.points) < 257
            and all(abs(p[0] - x) > 1e-5 for p in self.curve.points)
        ):
            points = tuple(sorted((*self.curve.points, (x, y))))
            self.set_curve(replace(self.curve, points=points))
            self.selected = points.index((x, y))

    def keyPressEvent(self, event: Any) -> None:
        """Route local graph deletion and Undo/Redo ahead of application shortcuts."""
        key = event.key()
        arrows = (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down)
        if key in (Qt.Key.Key_Home, Qt.Key.Key_End):
            self.selected = 0 if key == Qt.Key.Key_Home else len(self.curve.points) - 1
            event.accept()
            return
        if key in arrows:
            if self.selected < 0:
                self.selected = min(1, len(self.curve.points) - 1)
            elif event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.selected = max(
                    0,
                    min(
                        len(self.curve.points) - 1,
                        self.selected + (1 if key in (Qt.Key.Key_Right, Qt.Key.Key_Down) else -1),
                    ),
                )
            else:
                x, y = self.curve.points[self.selected]
                step = 0.1 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 0.01
                if event.modifiers() & Qt.KeyboardModifier.AltModifier:
                    step *= 0.1
                self.edit_point(
                    self.selected,
                    x
                    + (step if key == Qt.Key.Key_Right else -step if key == Qt.Key.Key_Left else 0),
                    y + (step if key == Qt.Key.Key_Up else -step if key == Qt.Key.Key_Down else 0),
                )
            event.accept()
            return
        if key == Qt.Key.Key_Insert:
            self.add_dot()
            event.accept()
            return
        if (
            event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace)
            and 0 < self.selected < len(self.curve.points) - 1
        ):
            self.delete_dot()
            return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_Z:
            self.redo() if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else self.undo()
            return
        super().keyPressEvent(event)

    def event(self, event: QEvent) -> bool:
        """Keep editing shortcuts inside the graph rather than deleting scene/timeline content."""
        if (
            isinstance(event, QKeyEvent)
            and event.type() == QEvent.Type.ShortcutOverride
            and (
                event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace)
                or event.modifiers() & Qt.KeyboardModifier.ControlModifier
                and event.key() == Qt.Key.Key_Z
            )
        ):
            event.accept()
            return True
        return super().event(event)

    def dragEnterEvent(self, event: Any) -> None:
        """Accept only the data-only easing preset format."""
        if event.mimeData().hasFormat(CURVE_MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event: Any) -> None:
        """Retain the easing-preset drop target while the pointer moves."""
        self.dragEnterEvent(event)

    def dropEvent(self, event: Any) -> None:
        """Resolve a known preset name without evaluating arbitrary drag data."""
        curve = curve_presets().get(
            bytes(event.mimeData().data(CURVE_MIME)).decode("utf-8", errors="replace")
        )
        if curve:
            self.set_curve(curve)
            event.acceptProposedAction()


class CurveEditor(CustomDialog):
    """Preview one or several spans and apply their graph as one undoable command."""

    graph_changed = Signal(object, float)
    apply_requested = Signal(object)
    preview_ended = Signal()

    def __init__(self, parent: QWidget, icons: IconProvider) -> None:
        """Compose graph tools, presets and transient playback around Apply/Cancel."""
        super().__init__(parent, "Tween transition graph")
        self.resize(880, 540)
        self.targets: tuple[tuple[str, str], ...] = ()
        self.source: Any = None
        self.session, self.clip_id = "", ""
        self.start, self.end = 0.0, 24.0
        self.chart = CurveCanvas(self)
        layout = QVBoxLayout(self.content)
        self.caption = QLabel("Double-click to add dots · Drag to reshape · Delete to remove")
        layout.addWidget(self.caption)
        tools = QHBoxLayout()
        for text, icon, callback in (
            ("Add dot", "add_circle_outline", self.chart.add_dot),
            ("Delete dot", "remove_circle_outline", self.chart.delete_dot),
            ("Undo graph edit", "undo", self.chart.undo),
            ("Redo graph edit", "redo", self.chart.redo),
            ("Linear", "show_chart", lambda: self.chart.set_curve(TransitionCurve())),
            ("Reverse", "swap_horiz", lambda: self.chart.set_curve(self.chart.curve.reversed())),
            ("Repeat easing", "repeat", self.repeat_curve),
        ):
            button = QPushButton()
            button.setToolTip(text)
            button.setAccessibleName(text)
            button.setFixedWidth(34)
            button.setIcon(icons.icon(icon))
            button.setProperty("materialIcon", icon)
            button.clicked.connect(callback)
            tools.addWidget(button)
        self.repeat_count = QSpinBox()
        self.repeat_count.setRange(2, 8)
        self.repeat_count.setSuffix("×")
        self.repeat_count.setAccessibleName("Repeat easing sections")
        tools.addWidget(self.repeat_count)
        self.smooth = QCheckBox("Smooth dots")
        self.smooth.toggled.connect(self.set_smooth)
        tools.addWidget(self.smooth)
        self.snap = QCheckBox("Snap dots")
        self.snap.toggled.connect(lambda value: setattr(self.chart, "snap", value))
        tools.addWidget(self.snap)
        tools.addStretch()
        layout.addLayout(tools)
        split = QSplitter()
        self.presets = CurvePresets(self)
        shelf = QWidget()
        shelf_layout = QVBoxLayout(shelf)
        shelf_layout.setContentsMargins(0, 0, 0, 0)
        search = QLineEdit()
        search.setPlaceholderText("Find easing preset…")
        search.setAccessibleName("Find transition graph preset")
        search.textChanged.connect(self.presets.filter)
        shelf_layout.addWidget(search)
        shelf_layout.addWidget(self.presets, 1)
        split.addWidget(shelf)
        split.addWidget(self.chart)
        split.setSizes([280, 560])
        layout.addWidget(split, 1)
        self.presets.itemClicked.connect(
            lambda item: self.chart.set_curve(curve_presets()[item.text()])
        )
        self.chart.changed.connect(self.changed_curve)
        point_tools = QHBoxLayout()
        self.point_index = QComboBox()
        self.point_index.setAccessibleName("Selected transition point")
        self.point_index.currentIndexChanged.connect(lambda i: setattr(self.chart, "selected", i))
        point_tools.addWidget(self.point_index, 1)
        self.point_time, self.point_value = QDoubleSpinBox(), QDoubleSpinBox()
        for field, label, low, high in (
            (self.point_time, "Point time", 0, 1),
            (self.point_value, "Point value", -4, 5),
        ):
            field.setRange(low, high)
            field.setDecimals(5)
            field.setSingleStep(0.01)
            field.setKeyboardTracking(False)
            field.setAccessibleName(label)
            point_tools.addWidget(QLabel(label))
            point_tools.addWidget(field)
            field.valueChanged.connect(self.edit_selected_point)
        layout.addLayout(point_tools)
        self.chart.selection_changed.connect(self.sync_point_editor)
        self.chart.changed.connect(self.sync_point_editor)
        self.sync_point_editor()
        playback = QHBoxLayout()
        self.play = QCheckBox("Loop preview")
        self.play.setChecked(True)
        playback.addWidget(self.play)
        self.progress = QSlider(Qt.Orientation.Horizontal)
        self.progress.setRange(0, 1000)
        self.progress.setAccessibleName("Tween preview time")
        self.progress.valueChanged.connect(self.preview)
        playback.addWidget(self.progress, 1)
        layout.addLayout(playback)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        bottom = QHBoxLayout()
        bottom.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        bottom.addWidget(cancel)
        self.apply = QPushButton("Apply graph")
        self.apply.setIcon(icons.icon("check"))
        self.apply.setProperty("materialIcon", "check")
        self.apply.clicked.connect(lambda: self.apply_requested.emit(self.chart.curve))
        bottom.addWidget(self.apply)
        layout.addLayout(bottom)
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self.tick)

    def open_curve(self, curve: TransitionCurve) -> None:
        """Open transient preview with clean local graph history."""
        self.message.clear()
        self.chart.set_curve(curve)
        self.chart._undo.clear()
        self.chart._redo.clear()
        self.show()
        self.raise_()
        self.timer.start()

    def changed_curve(self, curve: TransitionCurve) -> None:
        """Synchronize smoothing controls without authoring another graph edit."""
        self.smooth.blockSignals(True)
        self.smooth.setChecked(curve.smooth)
        self.smooth.blockSignals(False)
        self.preview()

    def set_smooth(self, enabled: bool) -> None:
        """Change interpolation on the transient graph."""
        self.chart.set_curve(replace(self.chart.curve, smooth=enabled))

    def repeat_curve(self) -> None:
        """Repeat progress sections with readable feedback if the dot budget is exceeded."""
        try:
            self.chart.set_curve(self.chart.curve.repeated(self.repeat_count.value()))
            self.message.clear()
        except ProjectError as error:
            self.message.setText(str(error))

    def preview(self) -> None:
        """Publish a transient graph sample without moving the saved playback cursor."""
        self.chart.progress = self.progress.value() / 1000
        self.chart.update()
        self.graph_changed.emit(
            self.chart.curve, self.start + self.chart.progress * (self.end - self.start)
        )

    def tick(self) -> None:
        """Advance only the popup's optional looping preview."""
        if self.play.isChecked():
            self.progress.setValue((self.progress.value() + 20) % 1001)

    def sync_point_editor(self, *_: Any) -> None:
        """Expose every point through native named controls, including read-only endpoints."""
        with (
            QSignalBlocker(self.point_index),
            QSignalBlocker(self.point_time),
            QSignalBlocker(self.point_value),
        ):
            labels = [
                f"Point {i + 1} · {x:.3f}, {y:.3f}"
                for i, (x, y) in enumerate(self.chart.curve.points)
            ]
            if self.point_index.count() != len(labels):
                self.point_index.clear()
                self.point_index.addItems(labels)
            else:
                for i, label in enumerate(labels):
                    if self.point_index.itemText(i) != label:
                        self.point_index.setItemText(i, label)
            index = self.chart.selected
            self.point_index.setCurrentIndex(index)
            enabled = 0 < index < len(self.chart.curve.points) - 1
            self.point_time.setEnabled(enabled)
            self.point_value.setEnabled(enabled)
            if index >= 0:
                x, y = self.chart.curve.points[index]
                self.point_time.setValue(x)
                self.point_value.setValue(y)

    def edit_selected_point(self, *_: Any) -> None:
        """Commit one numerical edit through the same constraints and Undo as pointer edits."""
        self.chart.edit_point(
            self.chart.selected, self.point_time.value(), self.point_value.value()
        )

    def done(self, result: int) -> None:
        """Stop preview before Apply/Cancel closes the contextual window."""
        self.timer.stop()
        self.preview_ended.emit()
        super().done(result)
