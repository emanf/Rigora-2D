"""Standard Qt popup behavior with plain trailing marks for enabled toggle actions."""

from PySide6.QtCore import QRect
from PySide6.QtGui import QIcon, QPainter, QPaintEvent, QPalette
from PySide6.QtWidgets import QMenu, QWidget

from rigora.resources import asset_path


class ToggleMenu(QMenu):
    """Retain native menu interaction and icons while marking checked icon actions on the right."""

    def __init__(self, title: str = "", parent: QWidget | None = None) -> None:
        """Cache the bundled Material marks; non-icon toggles use the shared menu stylesheet."""
        super().__init__(title, parent)
        self.checks = {
            theme: QIcon(str(asset_path(f"icons/controls/check-{theme}.png")))
            for theme in ("dark", "light")
        }

    def paintEvent(self, event: QPaintEvent) -> None:
        """Paint marks omitted by Qt when a checkable menu action also supplies an icon."""
        super().paintEvent(event)
        painter = QPainter(self)
        theme = (
            "dark"
            if self.palette().color(QPalette.ColorRole.WindowText).lightness() > 128
            else "light"
        )
        for action in self.actions():
            if (
                action.isVisible()
                and action.isCheckable()
                and action.isChecked()
                and not action.icon().isNull()
            ):
                row = self.actionGeometry(action)
                rect = QRect(row.right() - 22, row.center().y() - 7, 16, 16)
                mode = QIcon.Mode.Normal if action.isEnabled() else QIcon.Mode.Disabled
                self.checks[theme].paint(painter, rect, mode=mode)
