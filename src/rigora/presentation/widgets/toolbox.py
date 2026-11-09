"""Four-edge Tools docking owned exclusively by the Scene preview workspace."""

from typing import Any, cast

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QCursor, QKeyEvent, QMouseEvent, QPainter, QPaintEvent, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QDockWidget,
    QFrame,
    QMainWindow,
    QToolBar,
    QToolButton,
    QWidget,
)

_AREAS = {
    "left": Qt.DockWidgetArea.LeftDockWidgetArea,
    "right": Qt.DockWidgetArea.RightDockWidgetArea,
    "top": Qt.DockWidgetArea.TopDockWidgetArea,
    "bottom": Qt.DockWidgetArea.BottomDockWidgetArea,
}


class ToolboxGrip(QWidget):
    """Keyboard-accessible six-dot handle for moving Tools between preview edges."""

    def __init__(self, dock: "ToolboxDock") -> None:
        """Expose drag and keyboard placement without a desktop-window caption."""
        super().__init__(dock)
        self.dock = dock
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Move tools within Scene preview")
        self.setToolTip(
            "Drag to a Scene preview edge · Arrow keys choose an edge · Home resets left"
        )

    def sizeHint(self) -> QSize:
        """Turn the handle sideways for a horizontal tool strip."""
        return QSize(20, 44) if self.dock.edge in ("top", "bottom") else QSize(44, 20)

    def paintEvent(self, event: QPaintEvent) -> None:
        """Paint neutral dots with a rounded hover/focus target in either orientation."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        if self.underMouse() or self.hasFocus():
            painter.setBrush(self.palette().color(QPalette.ColorRole.Mid))
            painter.setOpacity(0.2)
            painter.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), 4, 4)
        painter.setOpacity(0.55)
        painter.setBrush(self.palette().color(QPalette.ColorRole.Text))
        horizontal = self.dock.edge in ("top", "bottom")
        for a in (-5, 0, 5):
            for b in (-2, 2):
                offset = QPoint(b, a) if horizontal else QPoint(a, b)
                painter.drawEllipse(self.rect().center() + offset, 1, 1)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Select an edge directly without moving or focusing the document canvas."""
        edges: dict[int, str] = {
            Qt.Key.Key_Home: "left",
            Qt.Key.Key_Left: "left",
            Qt.Key.Key_Right: "right",
            Qt.Key.Key_Up: "top",
            Qt.Key.Key_Down: "bottom",
        }
        if edge := edges.get(event.key()):
            self.dock.dock_to(edge)
            event.accept()
        else:
            super().keyPressEvent(event)


class ToolboxDock(QDockWidget):
    """Reserve a tool strip inside Preview; no app-wide docking or desktop floating.

    A nested QMainWindow owns both this dock and the viewport. Custom grip drags
    show a local drop marker, then change the dock area once on release. Invalid
    drops leave the existing placement intact and never resize other panels.
    """

    def __init__(self, parent: QWidget) -> None:
        """Build the tool dock before its Preview workspace becomes available."""
        super().__init__("Tools", parent)
        self.host: QMainWindow | None = None
        self.bar: QToolBar | None = None
        self._edge = "left"
        self._press: QPoint | None = None
        self._dragging = False
        self._queued = False
        # A distinct name prevents old app-wide dock state from reclaiming Tools.
        self.setObjectName("preview_tools")
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self.grip = ToolboxGrip(self)
        self.grip.installEventFilter(self)
        self.setTitleBarWidget(self.grip)
        self.drop_preview = QFrame(parent)
        self.drop_preview.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.drop_preview.setStyleSheet(
            "background: rgba(180, 180, 180, 35); border: 1px solid #888888;"
        )
        self.drop_preview.hide()

    @property
    def drag_handle(self) -> QWidget:
        """Expose the stable caption used throughout a complete pointer gesture."""
        return self.grip

    @property
    def edge(self) -> str:
        """Return the current local placement independently of legacy desktop state."""
        return self._edge

    def setWidget(self, widget: QWidget) -> None:
        """Wrap the shared toolbar with spacing and let the dock fill its preview edge."""
        self.bar = cast(QToolBar, widget)
        self.bar.setIconSize(QSize(20, 20))
        self.bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.bar.installEventFilter(self)
        content = QWidget()
        box = QBoxLayout(QBoxLayout.Direction.TopToBottom, content)
        box.setSpacing(0)
        box.addWidget(widget)
        box.addStretch(1)
        super().setWidget(content)
        self.arrange()

    def attach_preview(self, preview: QWidget) -> QMainWindow:
        """Own the viewport and Tools in a child workspace, returned for the main layout."""
        self.host = QMainWindow(self.parentWidget(), Qt.WindowType.Widget)
        self.host.setObjectName("ScenePreviewWorkspace")
        self.host.setDockOptions(QMainWindow.DockOption(0))
        self.host.setCentralWidget(preview)
        self.drop_preview.setParent(self.host)
        self.dock_to(self.edge)
        return self.host

    def setFloating(self, floating: bool) -> None:
        """Keep legacy floating requests inside Preview rather than opening a tool window."""
        if not floating:
            super().setFloating(False)

    def arrange(self) -> None:
        """Orient the existing tools and constrain only the strip's short dimension."""
        self._queued = False
        if self.bar is None:
            return
        horizontal = self.edge in ("top", "bottom")
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | (
                QDockWidget.DockWidgetFeature.DockWidgetVerticalTitleBar
                if horizontal
                else QDockWidget.DockWidgetFeature.NoDockWidgetFeatures
            )
        )
        self.bar.setOrientation(
            Qt.Orientation.Horizontal if horizontal else Qt.Orientation.Vertical
        )
        self.bar.setMinimumSize(0, 0)
        self.bar.setMaximumSize(16777215, 16777215)
        self.grip.setFixedSize(self.grip.sizeHint())
        content = self.widget()
        assert content is not None
        content.setMinimumSize(0, 0)
        content.setMaximumSize(16777215, 16777215)
        box = cast(QBoxLayout, content.layout())
        box.setDirection(
            QBoxLayout.Direction.LeftToRight if horizontal else QBoxLayout.Direction.TopToBottom
        )
        if horizontal:
            box.setContentsMargins(10, 2, 4, 2)
            content.setFixedHeight(44)
            self.bar.setFixedHeight(40)
        else:
            box.setContentsMargins(2, 10, 2, 4)
            content.setFixedWidth(44)
            self.bar.setFixedWidth(40)
        if layout := self.bar.layout():
            layout.setContentsMargins(3, 2, 3, 2)
            layout.setSpacing(2)
        for action in self.bar.actions():
            button = self.bar.widgetForAction(action)
            if isinstance(button, QToolButton):
                button.setFixedSize(34, 34)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Capture a grip gesture and update only its local docking marker until release."""
        kind = event.type()
        if self._press is not None and (
            kind == QEvent.Type.ApplicationDeactivate
            or isinstance(event, QKeyEvent)
            and event.key() == Qt.Key.Key_Escape
        ):
            self.finish_drag()
            return True
        if watched is self.grip:
            if kind in (QEvent.Type.Enter, QEvent.Type.Leave):
                self.grip.update()
            if self._press is None and kind in (
                QEvent.Type.Enter,
                QEvent.Type.HoverMove,
                QEvent.Type.MouseMove,
            ):
                self.grip.setCursor(Qt.CursorShape.OpenHandCursor)
                event.accept()
                return True
        if isinstance(event, QMouseEvent):
            if (
                watched is self.grip
                and kind == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
            ):
                self._press = event.globalPosition().toPoint()
                self._dragging = False
                cast(QApplication, QApplication.instance()).installEventFilter(self)
                self.grip.setCursor(Qt.CursorShape.ClosedHandCursor)
                self.grabMouse(QCursor(Qt.CursorShape.ClosedHandCursor))
                return True
            if self._press is not None and kind == QEvent.Type.MouseMove:
                point = event.globalPosition().toPoint()
                self._dragging |= (
                    point - self._press
                ).manhattanLength() >= QApplication.startDragDistance()
                if self._dragging:
                    self.show_drop_preview(point)
                return True
            if self._press is not None and kind == QEvent.Type.MouseButtonRelease:
                point, moved = event.globalPosition().toPoint(), self._dragging
                self.finish_drag()
                if moved:
                    QTimer.singleShot(0, self, lambda: self.snap(point))
                return True
        if (
            watched is self.bar
            and kind
            in (QEvent.Type.ActionAdded, QEvent.Type.ActionRemoved, QEvent.Type.StyleChange)
            and not self._queued
        ):
            self._queued = True
            QTimer.singleShot(0, self, self.arrange)
        return super().eventFilter(watched, event)

    def finish_drag(self) -> None:
        """Release pointer capture and temporary feedback after release or cancellation."""
        self._press, self._dragging = None, False
        self.releaseMouse()
        self.grip.setCursor(Qt.CursorShape.OpenHandCursor)
        cast(QApplication, QApplication.instance()).removeEventFilter(self)
        self.drop_preview.hide()

    def check_layout(self) -> None:
        """Refresh tool geometry after restoring a workspace without altering other docks."""
        self.arrange()

    def dock_to(self, edge: str) -> None:
        """Reserve one of the four Preview edges without entering the outer dock layout."""
        if edge not in _AREAS:
            return
        self._edge = edge
        self.arrange()
        if self.host is not None:
            visible = not self.isHidden()
            if self.host.dockWidgetArea(self) != _AREAS[edge]:
                self.host.addDockWidget(_AREAS[edge], self)
            self.setVisible(visible)

    def dock_target(self, global_point: QPoint) -> tuple[str, QRect] | None:
        """Return a local edge and global marker bounds only for points inside Preview."""
        if self.host is None or not self.host.isVisible():
            return None
        rect = QRect(self.host.mapToGlobal(QPoint()), self.host.size())
        if not rect.contains(global_point):
            return None
        distance, edge = min(
            (global_point.x() - rect.left(), "left"),
            (rect.right() - global_point.x(), "right"),
            (global_point.y() - rect.top(), "top"),
            (rect.bottom() - global_point.y(), "bottom"),
        )
        if distance > 48:
            return None
        bounds = QRect(rect)
        if edge in ("left", "right"):
            bounds.setWidth(min(48, rect.width()))
            if edge == "right":
                bounds.moveRight(rect.right())
        else:
            bounds.setHeight(min(48, rect.height()))
            if edge == "bottom":
                bounds.moveBottom(rect.bottom())
        return edge, bounds

    def show_drop_preview(self, global_point: QPoint) -> None:
        """Show input-transparent feedback only inside the preview docking workspace."""
        target = self.dock_target(global_point)
        if target is None or self.host is None:
            self.drop_preview.hide()
            return
        bounds = target[1]
        self.drop_preview.setGeometry(
            QRect(self.host.mapFromGlobal(bounds.topLeft()), bounds.size())
        )
        self.drop_preview.show()
        self.drop_preview.raise_()

    def snap(self, global_point: QPoint) -> None:
        """Commit a valid edge drop; retain the original placement for every other drop."""
        self.drop_preview.hide()
        if target := self.dock_target(global_point):
            self.dock_to(target[0])

    def reset_position(self) -> None:
        """Restore Tools to the left edge within Preview."""
        self.dock_to("left")

    def placement(self) -> dict[str, Any]:
        """Persist only the preview-local edge; desktop coordinates are never retained."""
        return {"edge": self.edge, "space": "preview"}

    def restore_placement(self, value: Any) -> None:
        """Restore four-edge placement; migrate obsolete floating placements to the left."""
        if isinstance(value, dict):
            edge = value.get("edge")
            self.dock_to(edge if isinstance(edge, str) and edge in _AREAS else "left")
