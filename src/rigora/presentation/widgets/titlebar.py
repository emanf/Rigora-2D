"""Frameless caption with OS-managed movement and native Windows system menu."""

import ctypes
import sys
from collections.abc import Callable

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QIcon, QMouseEvent
from PySide6.QtWidgets import QDockWidget, QFrame, QHBoxLayout, QLabel, QMenu, QToolButton, QWidget

from rigora.presentation.icons import IconProvider


def system_menu(window: QWidget, point: QPoint) -> bool:
    """Display the Windows system menu with state-appropriate commands; report platform support."""
    if sys.platform != "win32":
        return False
    user32 = ctypes.windll.user32
    user32.GetSystemMenu.restype = ctypes.c_void_p
    user32.GetSystemMenu.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.TrackPopupMenu.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    user32.PostMessageW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_size_t,
        ctypes.c_ssize_t,
    ]
    handle = int(window.winId())
    menu = user32.GetSystemMenu(handle, False)
    user32.EnableMenuItem.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint]
    maximized, minimized = window.isMaximized(), window.isMinimized()
    for command, enabled in (
        (0xF120, maximized or minimized),  # Restore
        (0xF000, not maximized and not minimized),  # Size
        (0xF010, not maximized and not minimized),  # Move
        (0xF020, not minimized),
        (0xF030, not maximized),
    ):
        user32.EnableMenuItem(menu, command, 0 if enabled else 1)
    command = user32.TrackPopupMenu(menu, 0x100 | 0x2, point.x(), point.y(), 0, handle, None)
    if command:
        user32.PostMessageW(handle, 0x0112, command, 0)
    return True


class TitleBar(QFrame):
    """Custom caption containing app identity and standard window operation controls."""

    def __init__(
        self,
        window: QWidget,
        icons: IconProvider,
        *,
        title: str | None = None,
        branding: bool = True,
    ) -> None:
        """Build compact branding, draggable caption space, and accessible window buttons."""
        super().__init__(window)
        self.host, self.icons = window, icons
        self.setObjectName("TitleBar")
        self.setFixedHeight(40)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(10)
        self.logo = QToolButton(self)
        self.logo.setObjectName("WindowMenu")
        self.logo.setFixedSize(24, 24)
        self.logo.setIconSize(QSize(14, 14))
        self.logo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.logo.setAutoRaise(True)
        self.logo.setStyleSheet("border: none; background: transparent; padding: 0;")
        self.logo.setToolTip("Rigora window menu · Alt+Space")
        self.logo.setAccessibleName("Window menu")
        self.logo.clicked.connect(self.show_system_menu)
        layout.addWidget(self.logo)
        self.logo.setVisible(branding)
        self.caption = QLabel(title or "", self)
        self.caption.setObjectName("Muted")
        self.caption.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.caption.setVisible(title is not None)
        layout.addWidget(self.caption)
        layout.addStretch(1)
        if title is not None:
            window.windowTitleChanged.connect(self.caption.setText)
        self.minimize_button = self._button("minimize", "Minimize", window.showMinimized)
        self.maximize_button = self._button(
            "crop_square", "Maximize / restore", self.toggle_maximized
        )
        self.close_button = self._button("close", "Close · Alt+F4", window.close)
        self.close_button.setObjectName("WindowClose")
        self.close_button.setProperty("materialIcon", "close")
        for button in (self.minimize_button, self.maximize_button, self.close_button):
            layout.addWidget(button)
        self.refresh()

    def _button(self, icon: str, tooltip: str, callback: Callable[[], object]) -> QToolButton:
        """Create a fixed-size caption control bound to a standard window operation."""
        button = QToolButton(self)
        button.setFixedSize(44, 40)
        button.setProperty("windowControl", True)
        button.setProperty("nativeHover", False)
        button.setAccessibleName(tooltip)
        button.setToolTip(tooltip)
        button.setProperty("materialIcon", icon)
        button.clicked.connect(callback)
        return button

    def refresh(self) -> None:
        """Reload branding and theme-aware icons, including the current maximize state."""
        self.logo.setIcon(self.icons.branding())
        for button in (self.minimize_button, self.close_button):
            button.setIcon(self.icons.icon(str(button.property("materialIcon")), 18))
        close_icon = QIcon(self.icons.icon("close", 18))
        close_icon.addPixmap(
            self.icons.icon("close", 18, "#ffffff").pixmap(18, 18), QIcon.Mode.Active
        )
        self.close_button.setIcon(close_icon)
        self.maximize_button.setIcon(
            self.icons.icon("filter_none" if self.host.isMaximized() else "crop_square", 18)
        )

    def toggle_maximized(self) -> None:
        """Switch the host between maximized and normal window states."""
        if self.host.isMaximized():
            self.host.showNormal()
        else:
            self.host.showMaximized()
        self.refresh()

    def show_system_menu(self) -> None:
        """Open native window commands or a themed Qt fallback on other platforms."""
        point = self.mapToGlobal(QPoint(0, self.height()))
        if system_menu(self.host, point):
            return
        menu = QMenu(self)
        for title, icon, callback in (
            ("Restore", "filter_none", self.host.showNormal),
            ("Minimize", "minimize", self.host.showMinimized),
            ("Maximize", "crop_square", self.host.showMaximized),
            ("Close", "close", self.host.close),
        ):
            menu.addAction(self.icons.icon(icon), title, callback)
        menu.exec(point)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Delegate caption dragging to the OS and right-clicks to the window menu."""
        if isinstance(self.host, QDockWidget) and event.button() == Qt.MouseButton.LeftButton:
            event.ignore()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.host.windowHandle()
            if handle is not None:
                handle.startSystemMove()
            event.accept()
        elif event.button() == Qt.MouseButton.RightButton:
            self.show_system_menu()
        else:
            super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """Toggle panel docking, or maximize a regular window, on a left double-click."""
        if isinstance(self.host, QDockWidget) and event.button() == Qt.MouseButton.LeftButton:
            if self.host.isMaximized() or self.host.isMinimized():
                self.host.showNormal()
            self.host.setFloating(not self.host.isFloating())
        elif event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximized()
        else:
            super().mouseDoubleClickEvent(event)
