"""Shared custom window chrome with native resize, Snap and caption feedback."""

import ctypes
import sys
from typing import Any, cast

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPainter, QPaintEvent, QPalette, QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QFrame,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from rigora.presentation.icons import IconProvider
from rigora.presentation.menu_labels import menu_text
from rigora.presentation.widgets.titlebar import TitleBar


def bounded_window_geometry(rect: QRect, minimum: QSize, available: QRect) -> QRect:
    """Keep a resizable dialog inside its screen's work area while honoring usable minima."""
    width = min(rect.width(), max(minimum.width(), available.width() - 16))
    height = min(rect.height(), max(minimum.height(), available.height() - 16))
    x = max(available.left(), min(rect.x(), available.right() - width + 1))
    y = max(available.top(), min(rect.y(), available.bottom() - height + 1))
    return QRect(x, y, width, height)


class WindowFrameController(QObject):
    """Supply shared movement, resize, window state and native hover behavior to a host."""

    def __init__(self, host: QWidget, titlebar: TitleBar) -> None:
        """Attach Qt lifecycle filtering and retain native frame state for this host."""
        super().__init__(host)
        self.host, self.titlebar = host, titlebar
        self.outline = QFrame(host)
        self.outline.setObjectName("WindowOutline")
        self.outline.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.outline.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.handle = 0
        app = cast(QApplication, QApplication.instance())
        self.native_enabled = sys.platform == "win32" and app.platformName() == "windows"
        host.installEventFilter(self)

    def set_maximize_hover(self, hovered: bool) -> None:
        """Expose native nonclient hover as a stylesheet state on the Qt caption control."""
        button = self.titlebar.maximize_button
        if button.property("nativeHover") != hovered:
            button.setProperty("nativeHover", hovered)
            button.style().unpolish(button)
            button.style().polish(button)
            button.update()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Refresh frame state and supply platform-managed resize gestures on empty edges."""
        if event.type() == QEvent.Type.PaletteChange:
            self.host.setWindowIcon(self.titlebar.icons.branding(boxed=True))
            self.titlebar.refresh()
        if event.type() in (QEvent.Type.Show, QEvent.Type.Resize, QEvent.Type.WindowStateChange):
            # Chrome children fill the host; an input-transparent overlay keeps
            # the outer edge visible without changing their layout or hit tests.
            self.outline.setGeometry(self.host.rect())
            self.outline.setVisible(self.host.isWindow())
            self.outline.raise_()
        if event.type() == QEvent.Type.WindowStateChange:
            self.titlebar.refresh()
        elif event.type() == QEvent.Type.Show and self.host.isWindow():
            if self.native_enabled:
                user32 = ctypes.windll.user32
                user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
                user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
                self.handle = int(self.host.winId())
                style = user32.GetWindowLongW(self.handle, -16)
                user32.SetWindowLongW(self.handle, -16, style | 0x000F0000)
        elif (
            event.type() == QEvent.Type.MouseButtonPress
            and isinstance(event, QMouseEvent)
            and event.button() == Qt.MouseButton.LeftButton
            and not self.host.isMaximized()
        ):
            point = event.position()
            edges = Qt.Edge(0)
            if point.x() < 6:
                edges |= Qt.Edge.LeftEdge
            elif point.x() >= self.host.width() - 6:
                edges |= Qt.Edge.RightEdge
            if point.y() < 6:
                edges |= Qt.Edge.TopEdge
            elif point.y() >= self.host.height() - 6:
                edges |= Qt.Edge.BottomEdge
            handle = self.host.windowHandle()
            if edges and handle is not None and self.host.isWindow():
                return handle.startSystemResize(edges)
        return False

    def native_event(self, message: Any) -> tuple[bool, int]:
        """Handle resize/Snap hit tests and bridge native maximize hover and press states."""
        if not self.handle or not self.native_enabled or not self.host.isWindow():
            return False, 0
        from ctypes.wintypes import MSG, POINT

        msg = MSG.from_address(int(message))
        if msg.hWnd != self.handle:
            return False, 0
        button = self.titlebar.maximize_button
        if msg.message == 0x0084:
            position = POINT(
                ctypes.c_short(msg.lParam & 0xFFFF).value,
                ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value,
            )
            user32 = ctypes.windll.user32
            user32.ScreenToClient.argtypes = [ctypes.c_void_p, ctypes.POINTER(POINT)]
            user32.ScreenToClient(self.handle, ctypes.byref(position))
            ratio = self.host.devicePixelRatioF()
            point = QPoint(round(position.x / ratio), round(position.y / ratio))
            if not self.host.isMaximized():
                left, right = point.x() < 6, point.x() >= self.host.width() - 6
                top, bottom = point.y() < 6, point.y() >= self.host.height() - 6
                hit = (
                    13
                    if top and left
                    else 14
                    if top and right
                    else 16
                    if bottom and left
                    else 17
                    if bottom and right
                    else 10
                    if left
                    else 11
                    if right
                    else 12
                    if top
                    else 15
                    if bottom
                    else 0
                )
                if hit:
                    return True, hit
            if button.isVisible() and button.rect().contains(button.mapFrom(self.host, point)):
                return True, 9  # HTMAXBUTTON preserves the Windows Snap affordance.
        elif msg.message == 0x00A0:
            self.set_maximize_hover(msg.wParam == 9)

            class TrackMouseEvent(ctypes.Structure):
                """Windows structure requesting nonclient leave notifications."""

                _fields_ = [
                    ("size", ctypes.c_uint),
                    ("flags", ctypes.c_uint),
                    ("window", ctypes.c_void_p),
                    ("hover_time", ctypes.c_uint),
                ]

            tracking = TrackMouseEvent(ctypes.sizeof(TrackMouseEvent), 0x12, self.handle, 0)
            ctypes.windll.user32.TrackMouseEvent(ctypes.byref(tracking))
        elif msg.message in (0x02A2, 0x0200, 0x001F, 0x0008):
            self.set_maximize_hover(False)
            if msg.message != 0x0200:
                button.setDown(False)
        elif msg.message == 0x00A1 and msg.wParam == 9:
            self.set_maximize_hover(True)
            button.setDown(True)
            return True, 0
        elif msg.message == 0x00A2 and button.isDown():
            button.setDown(False)
            if msg.wParam == 9:
                button.click()
            return True, 0
        return False, 0


class FramelessMainWindow(QMainWindow):
    """Main window host whose caption behavior is supplied by a shared frame controller."""

    titlebar: TitleBar
    frame: WindowFrameController

    def nativeEvent(self, eventType: Any, message: Any) -> tuple[bool, int]:
        """Delegate native caption messages to the shared frame before Qt's default handling."""
        if hasattr(self, "frame"):
            result = self.frame.native_event(message)
            if result[0]:
                return result
        return cast(tuple[bool, int], super().nativeEvent(eventType, message))


class CustomDialog(QDialog):
    """Modal dialog host sharing the application's caption and standard window controls."""

    def __init__(self, parent: QWidget, title: str = "") -> None:
        """Create custom chrome above a separate content widget for reusable dialog layouts."""
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowMinMaxButtonsHint
            | Qt.WindowType.WindowSystemMenuHint
        )
        self.setWindowTitle(title)
        icons = getattr(parent.window(), "icons", None)
        self.icons = icons if isinstance(icons, IconProvider) else IconProvider()
        self.titlebar = TitleBar(self, self.icons, title=title, branding=False)
        self.content = QWidget(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        layout.addWidget(self.titlebar)
        layout.addWidget(self.content, 1)
        self.frame = WindowFrameController(self, self.titlebar)
        self.setWindowIcon(parent.windowIcon())

    def showEvent(self, event: QShowEvent) -> None:
        """Start standard decision dialogs on their safe cancellation/close action."""
        super().showEvent(event)
        if not self.property("initialGeometryFitted"):
            self.setProperty("initialGeometryFitted", True)
            app = cast(QApplication, QApplication.instance())
            if app.platformName() != "offscreen" and self.screen() is not None:
                self.setGeometry(
                    bounded_window_geometry(
                        self.geometry(), self.minimumSize(), self.screen().availableGeometry()
                    )
                )
        for action in self.content.findChildren(QPushButton):
            action.setAutoDefault(False)
            action.installEventFilter(self)
        for box in self.content.findChildren(QDialogButtonBox):
            button = box.button(QDialogButtonBox.StandardButton.Cancel)
            if button is None:
                button = box.button(QDialogButtonBox.StandardButton.Close)
            if button is not None and button.isEnabled():
                button.setDefault(True)
                button.setFocus(Qt.FocusReason.OtherFocusReason)
                for other in self.content.findChildren(QPushButton):
                    if other is not button:
                        other.setDefault(False)
                break

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Activate the focused button with Enter without Qt creating extra default outlines."""
        if (
            isinstance(watched, QPushButton)
            and isinstance(event, QKeyEvent)
            and event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and watched.isEnabled()
        ):
            watched.click()
            return True
        return super().eventFilter(watched, event)

    def nativeEvent(self, eventType: Any, message: Any) -> tuple[bool, int]:
        """Delegate native caption messages to the shared frame before Qt's default handling."""
        if hasattr(self, "frame"):
            result = self.frame.native_event(message)
            if result[0]:
                return result
        return cast(tuple[bool, int], super().nativeEvent(eventType, message))


class DockPanel(QDockWidget):
    """Dockable panel with a shared title/close caption in every placement mode."""

    def __init__(self, title: str, parent: QWidget, icons: IconProvider) -> None:
        """Install a draggable caption and an overlapping, layout-free resize target."""
        super().__init__(title, parent)
        self.windowTitleChanged.connect(self.update_menu_title)
        self.update_menu_title(title)
        self.titlebar = TitleBar(self, icons, title=title, branding=False)
        self.titlebar.setProperty("panelCaption", True)
        self.titlebar.caption.setObjectName("PanelCaption")
        self.setTitleBarWidget(self.titlebar)
        self.frame = WindowFrameController(self, self.titlebar)
        self.resize_grip = DockResizeGrip(self)
        self.topLevelChanged.connect(self.update_chrome)
        self.update_chrome(False)

    def update_menu_title(self, title: str) -> None:
        """Keep literal panel ampersands from becoming menu keyboard mnemonics."""
        self.toggleViewAction().setText(menu_text(title))

    def update_chrome(self, floating: bool) -> None:
        """Keep compact title/close controls and the shared floating-window outline."""
        self.style().unpolish(self)
        self.style().polish(self)
        self.titlebar.setFixedHeight(32)
        self.titlebar.minimize_button.hide()
        self.titlebar.maximize_button.hide()
        self.titlebar.close_button.setFixedSize(32, 32)
        self.resize_grip.queue_position()
        if floating and not self.windowFlags() & Qt.WindowType.FramelessWindowHint:
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
            self.show()

    def nativeEvent(self, eventType: Any, message: Any) -> tuple[bool, int]:
        """Delegate native caption messages to the shared frame before Qt's default handling."""
        if hasattr(self, "frame"):
            result = self.frame.native_event(message)
            if result[0]:
                return result
        return cast(tuple[bool, int], super().nativeEvent(eventType, message))


class DockResizeGrip(QWidget):
    """Seven-pixel pointer target overlapping a one-pixel native dock divider.

    This widget belongs to the main window, outside the panel's content layout.
    Its transparent idle surface reserves no space. The native layout continues
    to enforce panel minimum sizes during pointer and keyboard resizing.
    """

    def __init__(self, dock: DockPanel) -> None:
        """Track dock placement and follow its inner edge without entering its title bar."""
        super().__init__(dock.parentWidget())
        self.dock = dock
        self.host = dock.parentWidget()
        self.origin: tuple[float, int] | None = None
        self.axis = Qt.Orientation.Vertical
        self.direction = -1
        self._queued = False
        self._owner_removed = False
        self.setObjectName("DockResizeGrip")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(f"Resize {dock.windowTitle()} panel")
        self.setToolTip("Drag the divider to resize · Arrow keys resize by 32 pixels")
        dock.installEventFilter(self)
        dock.destroyed.connect(self.owner_destroyed)
        if self.host is not None:
            self.host.installEventFilter(self)
        self.hide()
        self.queue_position()

    def owner_destroyed(self) -> None:
        """Retire the overlap target when a plugin or workspace removes its panel."""
        self._owner_removed = True
        self.hide()
        self.deleteLater()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Coalesce geometry updates after native dock layout changes."""
        if event.type() in (
            QEvent.Type.Move,
            QEvent.Type.Resize,
            QEvent.Type.Show,
            QEvent.Type.Hide,
            QEvent.Type.LayoutRequest,
        ):
            self.queue_position()
        return False

    def queue_position(self) -> None:
        """Follow the native divider once after the current layout operation completes."""
        if not self._queued and not self._owner_removed:
            self._queued = True
            QTimer.singleShot(0, self, self.position_at_divider)

    def position_at_divider(self) -> None:
        """Overlap the inner dock edge and hide when the panel floats or is not visible."""
        self._queued = False
        if self._owner_removed:
            return
        host = self.host
        if not isinstance(host, QMainWindow):
            return
        area = host.dockWidgetArea(self.dock)
        if not self.dock.isVisible() or self.dock.isFloating() or not area:
            self.hide()
            return
        rect = self.dock.geometry()
        horizontal = area in (
            Qt.DockWidgetArea.LeftDockWidgetArea,
            Qt.DockWidgetArea.RightDockWidgetArea,
        )
        self.axis = Qt.Orientation.Horizontal if horizontal else Qt.Orientation.Vertical
        self.direction = (
            1
            if area in (Qt.DockWidgetArea.LeftDockWidgetArea, Qt.DockWidgetArea.TopDockWidgetArea)
            else -1
        )
        if horizontal:
            edge = rect.right() + 1 if self.direction == 1 else rect.left() - 1
            bounds = QRect(edge - 3, rect.top(), 7, rect.height())
        else:
            edge = rect.bottom() + 1 if self.direction == 1 else rect.top() - 1
            bounds = QRect(rect.left(), edge - 3, rect.width(), 7)
        self.setGeometry(bounds.intersected(host.rect()))
        self.setCursor(Qt.CursorShape.SizeHorCursor if horizontal else Qt.CursorShape.SizeVerCursor)
        self.show()
        self.raise_()

    def resize_extent(self, extent: int) -> None:
        """Let the native layout enforce viewport and panel minima on the current axis."""
        if isinstance(self.host, QMainWindow) and not self.dock.isFloating():
            self.host.resizeDocks([self.dock], [max(1, extent)], self.axis)

    def paintEvent(self, event: QPaintEvent) -> None:
        """Highlight a single line on hover/focus without filling the overlap target."""
        if not (self.underMouse() or self.hasFocus()):
            return
        painter = QPainter(self)
        painter.setPen(self.palette().color(QPalette.ColorRole.Mid))
        if self.axis == Qt.Orientation.Horizontal:
            painter.drawLine(self.width() // 2, 0, self.width() // 2, self.height())
        else:
            painter.drawLine(0, self.height() // 2, self.width(), self.height() // 2)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Capture the global origin and panel extent for a continuous gesture."""
        if event.button() == Qt.MouseButton.LeftButton:
            horizontal = self.axis == Qt.Orientation.Horizontal
            self.origin = (
                event.globalPosition().x() if horizontal else event.globalPosition().y(),
                self.dock.width() if horizontal else self.dock.height(),
            )
            event.accept()
        else:
            event.ignore()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Resize live while maintaining the same pointer-to-edge offset throughout the drag."""
        if self.origin:
            position, extent = self.origin
            current = (
                event.globalPosition().x()
                if self.axis == Qt.Orientation.Horizontal
                else event.globalPosition().y()
            )
            self.resize_extent(round(extent + self.direction * (current - position)))
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Finish the resize gesture without changing project data or undo history."""
        self.origin = None
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Resize along the divider's axis using the same direction as pointer movement."""
        horizontal = self.axis == Qt.Orientation.Horizontal
        backward, forward = (
            (Qt.Key.Key_Left, Qt.Key.Key_Right) if horizontal else (Qt.Key.Key_Up, Qt.Key.Key_Down)
        )
        if event.key() in (backward, forward):
            extent = self.dock.width() if horizontal else self.dock.height()
            self.resize_extent(extent + self.direction * (32 if event.key() == forward else -32))
            event.accept()
        else:
            super().keyPressEvent(event)
