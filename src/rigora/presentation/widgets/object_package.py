"""Metadata and category choices for portable Objects and the shared custom library."""

import getpass

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from rigora.domain.content import CATEGORIES
from rigora.presentation.widgets.window_frame import CustomDialog


class ObjectPackageDialog(CustomDialog):
    """Collect explicit package metadata with a visual Object preview and editable category."""

    def __init__(
        self, parent: QWidget, name: str, icon: QIcon, categories: tuple[str, ...], *, custom: bool
    ):
        """Keep Cancel focused and leave native path picking to the export action."""
        super().__init__(parent, "Save to Custom Templates" if custom else "Export Object Package")
        self.setMinimumWidth(520)
        outer = QVBoxLayout(self.content)
        intro = QLabel(
            "Available across your projects in Content → Custom."
            if custom
            else "A portable .rigpack with artwork, bones, clothing and animations."
        )
        intro.setWordWrap(True)
        outer.addWidget(intro)
        row = QHBoxLayout()
        preview = QLabel()
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setFixedSize(112, 112)
        preview.setPixmap(icon.pixmap(96, 96))
        row.addWidget(preview)
        form = QFormLayout()
        self.name = QLineEdit(name)
        self.name.setMaxLength(200)
        form.addRow("Name", self.name)
        self.category = QComboBox()
        self.category.setEditable(True)
        self.category.addItems(tuple(dict.fromkeys(("Objects", *categories, *CATEGORIES))))
        if editor := self.category.lineEdit():
            editor.setMaxLength(200)
        self.category.setToolTip("Choose a category or type a new category name.")
        form.addRow("Category", self.category)
        self.author = QLineEdit(getpass.getuser())
        self.author.setMaxLength(200)
        form.addRow("Author", self.author)
        self.license = QLineEdit("All rights reserved")
        self.license.setMaxLength(200)
        form.addRow("License", self.license)
        row.addLayout(form, 1)
        outer.addLayout(row)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(
            "Save to Custom Templates" if custom else "Choose Export File…"
        )
        outer.addWidget(buttons)
