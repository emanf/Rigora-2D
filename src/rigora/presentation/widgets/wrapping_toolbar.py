"""Compact wrapping command groups with local, persistent drag ordering."""

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent, QResizeEvent
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QSizePolicy, QToolButton, QWidget

from rigora.presentation.icons import IconProvider


class ToolbarGrip(QToolButton):
    """Move one command group without dragging the window or activating a command."""

    def __init__(self, bar: "WrappingToolbar", key: str, label: str) -> None:
        """Expose pointer reordering and keyboard alternatives on a small Material grip."""
        super().__init__(bar)
        self.bar, self.key = bar, key
        self.setObjectName("ToolbarGrip")
        self.setIcon(bar.icons.icon("drag_indicator"))
        self.setProperty("materialIcon", "drag_indicator")
        self.setFixedSize(16, 32)
        self.setIconSize(QSize(14, 18))
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(f"Arrange {label}")
        self.setToolTip(f"Drag {label} to reorder · Arrow keys move · Home/End · Escape cancels")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Retain a stable pointer origin until the drag threshold is crossed."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.bar.begin_drag(self.key, self.mapTo(self.bar, event.position().toPoint()))
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Preview the insertion point while all controls retain their original positions."""
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.bar.preview_drag(self.mapTo(self.bar, event.position().toPoint()))
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Commit a valid drop once, or cancel a click and any out-of-toolbar release."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.bar.finish_drag(self.mapTo(self.bar, event.position().toPoint()))
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Provide deterministic order changes without requiring pointer precision."""
        order = self.bar.order()
        index = order.index(self.key)
        targets: dict[int, int] = {
            Qt.Key.Key_Left: index - 1,
            Qt.Key.Key_Up: index - 1,
            Qt.Key.Key_Right: index + 1,
            Qt.Key.Key_Down: index + 1,
            Qt.Key.Key_Home: 0,
            Qt.Key.Key_End: len(order) - 1,
        }
        if event.key() == Qt.Key.Key_Escape:
            self.bar.cancel_drag()
        elif event.key() in targets:
            self.bar.cancel_drag()
            self.bar.move_group(self.key, targets[event.key()])
        else:
            super().keyPressEvent(event)
            return
        event.accept()


class WrappingToolbar(QFrame):
    """Lay out intact groups in rows, recomputing geometry only on UI layout changes.

    Ordering is view state. Dragging previews an insertion line; only release
    changes the order and notifies the owner to persist it. No native toolbars,
    floating panels, scrolling containers or scene commands are involved.
    """

    order_changed = Signal(object)
    height_changed = Signal(int)

    def __init__(self, icons: IconProvider, parent: QWidget) -> None:
        """Create a wrapping surface whose largest group defines its minimum useful width."""
        super().__init__(parent)
        self.icons = icons
        self.groups: dict[str, QWidget] = {}
        self.grips: dict[str, ToolbarGrip] = {}
        self._order: list[str] = []
        self._default: list[str] = []
        self._drag: tuple[str, QPoint] | None = None
        self._dragging = False
        self._insertion = 0
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.marker = QFrame(self)
        self.marker.setFrameShape(QFrame.Shape.VLine)
        self.marker.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.marker.hide()
        self._layout_timer = QTimer(self)
        self._layout_timer.setSingleShot(True)
        self._layout_timer.timeout.connect(self.reflow)

    def add_group(self, key: str, label: str, content: QWidget) -> None:
        """Take ownership of a content widget and pair it with its own movable grip."""
        group = QWidget(self)
        row = QHBoxLayout(group)
        row.setContentsMargins(0, 0, 4, 0)
        row.setSpacing(2)
        grip = ToolbarGrip(self, key, label)
        row.addWidget(grip)
        row.addWidget(content)
        self.groups[key], self.grips[key] = group, grip
        self._order.append(key)
        self._default.append(key)
        group.show()
        self._layout_timer.start(0)

    def order(self) -> list[str]:
        """Return a copy of the current stable group identities for preferences."""
        return list(self._order)

    def restore_order(self, saved: object) -> None:
        """Ignore unknown/duplicate IDs and append new groups in their default order."""
        values = saved if isinstance(saved, (list, tuple)) else ()
        order = list(dict.fromkeys(k for k in values if isinstance(k, str) and k in self.groups))
        order.extend(k for k in self._default if k not in order)
        if order != self._order:
            self._order = order
            self.reflow()
            self.order_changed.emit(self.order())

    def move_group(self, key: str, index: int) -> None:
        """Move a known group and publish one completed arrangement change."""
        order = self.order()
        order.remove(key)
        order.insert(max(0, min(len(order), index)), key)
        self.restore_order(order)

    def sizeHint(self) -> QSize:
        """Advertise the current row height without forcing a single wide row."""
        return QSize(800, max(44, self.height()))

    def minimumSizeHint(self) -> QSize:
        """Allow wrapping down to the width of one intact command group."""
        return QSize(
            max((g.sizeHint().width() + 16 for g in self.groups.values()), default=280), 44
        )

    def reflow(self) -> None:
        """Place groups left to right with equal row gaps and adjust the caption's height."""
        x, y, height = 8, 4, 36
        limit = max(1, self.width() - 8)
        for key in self._order:
            group = self.groups[key]
            size = group.sizeHint().expandedTo(group.minimumSizeHint())
            width = size.width()
            if x > 8 and x + width > limit:
                x, y, height = 8, y + height + 4, 36
            height = max(height, size.height())
            group.setGeometry(x, y, width, height)
            x += width + 4
        desired = y + height + 4
        if self.height() != desired or self.minimumHeight() != desired:
            self.setFixedHeight(desired)
            self.height_changed.emit(desired)

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Reflow immediately when the available application width changes."""
        super().resizeEvent(event)
        self.reflow()

    def event(self, event: QEvent) -> bool:
        """Refresh themed font metrics through one coalesced layout pass."""
        if hasattr(self, "_layout_timer") and event.type() in (
            QEvent.Type.LayoutRequest,
            QEvent.Type.FontChange,
            QEvent.Type.StyleChange,
        ):
            self._layout_timer.start(0)
        return super().event(event)

    def begin_drag(self, key: str, point: QPoint) -> None:
        """Keep the original layout stable throughout a pointer gesture."""
        self._drag, self._dragging = (key, point), False

    def preview_drag(self, point: QPoint) -> None:
        """Find the closest row and slot; out-of-surface drops remain invalid."""
        if not self._drag:
            return
        key, origin = self._drag
        if (
            not self._dragging
            and (point - origin).manhattanLength() < QApplication.startDragDistance()
        ):
            return
        self._dragging = True
        self.grips[key].setCursor(Qt.CursorShape.ClosedHandCursor)
        if not self.rect().contains(point):
            self.marker.hide()
            return
        rows = [self.groups[k].geometry() for k in self._order]
        nearest = min(rows, key=lambda r: abs(r.center().y() - point.y())).top()
        candidates = [i for i, rect in enumerate(rows) if rect.top() == nearest]
        index = next(
            (i for i in candidates if point.x() < rows[i].center().x()), candidates[-1] + 1
        )
        self._insertion = index
        rect = rows[index] if index <= candidates[-1] else rows[candidates[-1]]
        x = rect.left() - 2 if index <= candidates[-1] else rect.right() + 2
        self.marker.setGeometry(QRect(x, rect.top(), 2, rect.height()))
        self.marker.show()
        self.marker.raise_()

    def finish_drag(self, point: QPoint) -> None:
        """Commit an insertion after a valid drag, preserving all project data and focus."""
        if not self._drag:
            return
        self.preview_drag(point)
        key = self._drag[0]
        valid = self._dragging and self.rect().contains(point)
        index = self._insertion - (self._order.index(key) < self._insertion)
        self.cancel_drag()
        if valid:
            self.move_group(key, index)

    def cancel_drag(self) -> None:
        """Discard pointer state and feedback without changing the arrangement."""
        if self._drag:
            self.grips[self._drag[0]].setCursor(Qt.CursorShape.OpenHandCursor)
        self._drag, self._dragging = None, False
        self.marker.hide()
