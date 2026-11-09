"""Visible, cancellable first-run illustration generation using the shared worker."""

from typing import Any

from PySide6.QtWidgets import QLabel, QProgressBar, QPushButton, QVBoxLayout

from rigora.presentation.widgets.window_frame import CustomDialog


class ContentSetupDialog(CustomDialog):
    """Show progress for generated sources and previews without blocking the application."""

    def __init__(self, parent: Any) -> None:
        super().__init__(parent, "Preparing artwork")
        self.model = parent.viewmodel.content
        self.completed = False
        self.resize(510, 220)
        box = QVBoxLayout(self.content)
        title = QLabel("Preparing local artwork and previews")
        font = title.font()
        font.setPixelSize(18)
        font.setBold(True)
        title.setFont(font)
        box.addWidget(title)
        hint = QLabel(
            "Templates and Character Creation use separate catalogs. PNG previews "
            "are generated once and kept in your local cache."
        )
        hint.setWordWrap(True)
        box.addWidget(hint)
        self.description = QLabel()
        box.addWidget(self.description)
        self.progress = QProgressBar()
        box.addWidget(self.progress)
        cancel = QPushButton("Cancel generation")
        cancel.clicked.connect(self.reject)
        box.addWidget(cancel)

    def update_progress(self, current: int, total: int, label: str) -> None:
        """Display completed source entries and the current human-readable operation."""
        self.progress.setRange(0, total)
        self.progress.setValue(current)
        self.description.setText(f"{current} / {total} · {label}")
        if current == total:
            self.completed = True
            self.accept()

    def reject(self) -> None:
        """Cancel only preparation; leave the active project and existing cache untouched."""
        if not self.completed:
            self.model.cancel_generation = True
        super().reject()


def connect_content_setup(window: Any) -> None:
    """Create the first-run popup only when a worker actually needs to generate content."""
    window.content_setup = None

    def progress(current: int, total: int, label: str) -> None:
        if window._closed:
            return
        if window.content_setup is None:
            window.content_setup = ContentSetupDialog(window)
            window.content_setup.show()
        window.content_setup.update_progress(current, total, label)

    def completed() -> None:
        if window.content_setup is not None and not window.viewmodel.content.busy:
            dialog, window.content_setup = window.content_setup, None
            dialog.completed = True
            dialog.accept()
            dialog.deleteLater()

    window.viewmodel.content.generation_progress.connect(progress)
    window.viewmodel.content.changed.connect(completed)
