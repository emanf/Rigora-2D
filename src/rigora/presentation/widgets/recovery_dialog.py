"""Explicit recovery selection using application chrome and independent unsaved tabs."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from rigora.presentation.viewmodels.project_io import ProjectIOViewModel
from rigora.presentation.widgets.window_frame import CustomDialog


class RecoveryDialog(CustomDialog):
    """Offer private recovery packages without replacing an open project or its source file."""

    def __init__(self, parent: QWidget, model: ProjectIOViewModel) -> None:
        """List snapshot headers; decode the chosen complete package on the I/O worker."""
        super().__init__(parent, "Recover unsaved work")
        self.model = model
        self.resize(620, 440)
        box = QVBoxLayout(self.content)
        label = QLabel(
            "Recovered work opens in a separate unsaved tab. Original projects are preserved."
        )
        label.setWordWrap(True)
        box.addWidget(label)
        self.entries = QListWidget()
        self.entries.setAccessibleName("Recoverable projects")
        for entry in model.store.entries():
            item = QListWidgetItem(
                entry.name
                + "\n"
                + (entry.source or "Unsaved project")
                + (" · previous snapshot" if entry.path.suffix == ".bak" else "")
            )
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self.entries.addItem(item)
        if not self.entries.count():
            box.addWidget(QLabel("No recovery snapshots are available."))
        self.entries.setCurrentRow(0)
        box.addWidget(self.entries, 1)
        restore = QPushButton("Recover selected")
        restore.setEnabled(bool(self.entries.count()))
        restore.clicked.connect(self.restore)
        box.addWidget(restore)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        box.addWidget(close)

    def restore(self) -> None:
        """Queue the selected recovery and leave source documents and other snapshots untouched."""
        item = self.entries.currentItem()
        if item:
            self.model.recover(item.data(Qt.ItemDataRole.UserRole))
            self.close()
