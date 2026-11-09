"""Shared square thumbnail grids for saved looks, wardrobe and action choices."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidget

from rigora.presentation.widgets.asset_cards import configure_card_grid


def configure_cards(view: QListWidget, *, compact: bool = False) -> None:
    """Give saved looks, wardrobe pieces and color swatches a consistent visual grid."""
    configure_card_grid(view)
    view.setMinimumHeight(170 if compact else 235)
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
