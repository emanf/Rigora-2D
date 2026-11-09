"""Inspect authored character views using original vectors and the shared transparency surface."""

from dataclasses import replace
from typing import Any

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from rigora.application_services.character_creation import character_portrait
from rigora.domain.character_recipe import VIEWS, CharacterRecipe
from rigora.presentation.themes import transparency_brush
from rigora.presentation.widgets.window_frame import CustomDialog


class VectorView(QWidget):
    """Retain one SVG renderer; resizing and painting never generate character data."""

    def __init__(self, source: bytes, parent: QWidget) -> None:
        """Own the supplied SVG renderer for the lifetime of its preview widget."""
        super().__init__(parent)
        self.renderer = QSvgRenderer(QByteArray(source), self)
        self.renderer.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.setMinimumSize(150, 260)

    def paintEvent(self, event: Any) -> None:
        """Paint the same checkerboard used by the main workspace and thumbnails."""
        painter = QPainter(self)
        painter.fillRect(self.rect(), transparency_brush(self.palette()))
        self.renderer.render(painter, QRectF(self.rect()).adjusted(12, 12, -12, -12))


class TurnaroundPreview(CustomDialog):
    """Show a transient view contact sheet without changing the active character or project."""

    def __init__(self, parent: QWidget, recipe: CharacterRecipe) -> None:
        """Compose five static original-vector views from the current recipe."""
        super().__init__(parent, "Character views")
        self.resize(920, 420)
        box = QVBoxLayout(self.content)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        sheet = QWidget()
        row = QHBoxLayout(sheet)
        for view in VIEWS:
            column = QVBoxLayout()
            column.addWidget(QLabel(view))
            preview = VectorView(character_portrait(replace(recipe, view=view, motions=())), sheet)
            preview.setAccessibleName(view + " character preview")
            column.addWidget(preview, 1)
            row.addLayout(column)
        scroll.setWidget(sheet)
        box.addWidget(scroll, 1)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        box.addWidget(close)
