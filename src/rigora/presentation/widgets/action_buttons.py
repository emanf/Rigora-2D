"""Compact Material action controls shared by layer and appearance panels."""

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QToolButton

from rigora.presentation.icons import IconProvider


def compact_button(
    icons: IconProvider, label: str, icon: str, callback: Callable[[], Any]
) -> QToolButton:
    """Create an icon-only command with a tooltip, keyboard focus and an accessible name."""
    button = QToolButton()
    button.setObjectName("PanelAction")
    button.setText(label)
    button.setAccessibleName(label)
    button.setToolTip(label)
    button.setIcon(icons.icon(icon))
    button.setProperty("materialIcon", icon)
    button.setIconSize(QSize(16, 16))
    button.setFixedSize(28, 28)
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
    button.clicked.connect(lambda _checked=False: callback())
    return button
