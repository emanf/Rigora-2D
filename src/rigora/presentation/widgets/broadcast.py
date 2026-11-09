"""Explicit local browser-source output using the shared final renderer and bounded workers."""

from typing import TYPE_CHECKING

from PySide6.QtCore import QThreadPool, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)
from shiboken6 import isValid

from rigora.application_services.rendering import svg_pose
from rigora.domain.project import ProjectError
from rigora.infrastructure.broadcast import LocalBroadcast
from rigora.presentation.viewmodels.content_library import LibraryJob
from rigora.presentation.widgets.window_frame import CustomDialog

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


class BroadcastOutput(CustomDialog):
    """Publish one scene locally until Stop, close or a workspace change."""

    def __init__(self, host: "MainWindow") -> None:
        """Build dormant output controls; opening this window never starts a listener."""
        super().__init__(host, "Local broadcast output")
        self.host = host
        self.document = host.viewmodel.documents
        self.scene_id = self.document.scene.id
        self.output = LocalBroadcast()
        self.job: LibraryJob | None = None
        self.generation = 0
        self.resize(540, 340)
        box = QVBoxLayout(self.content)
        form = QFormLayout()
        box.addLayout(form)
        self.frame_width, self.frame_height, self.fps, self.port = (QSpinBox() for _ in range(4))
        for field, maximum, default in (
            (self.frame_width, 1920, 1280),
            (self.frame_height, 1080, 720),
            (self.fps, 30, 24),
            (self.port, 65535, 0),
        ):
            field.setRange(0 if field is self.port else 1, maximum)
            field.setValue(default)
        for name, field in (
            ("Width", self.frame_width),
            ("Height", self.frame_height),
            ("FPS", self.fps),
            ("Port · 0 chooses free", self.port),
        ):
            form.addRow(name, field)
        self.follow_preview = QCheckBox("Include live Puppet/capture previews")
        self.follow_preview.setChecked(True)
        form.addRow(self.follow_preview)
        self.address = QLineEdit()
        self.address.setReadOnly(True)
        self.address.setAccessibleName("Private local browser-source URL")
        form.addRow("Browser source URL", self.address)
        self.note = QLabel(
            "Start output, then copy its URL into an OBS Browser Source. "
            "Transparency and the active camera are rendered without editor controls. "
            "Capture application audio separately in your broadcast software."
        )
        self.note.setWordWrap(True)
        box.addWidget(self.note)
        row = QHBoxLayout()
        box.addLayout(row)
        self.start_button = QPushButton(self.icons.icon("cast"), "Start output")
        self.stop_button = QPushButton(self.icons.icon("stop"), "Stop")
        self.start_button.clicked.connect(self.start)
        self.stop_button.clicked.connect(self.stop)
        row.addWidget(self.start_button)
        row.addWidget(self.stop_button)
        copy = QPushButton(self.icons.icon("content_copy"), "Copy URL")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.address.text()))
        row.addWidget(copy)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.finished.connect(lambda _: self.stop())
        self.host.viewmodel.changed.connect(self.check_context)
        self.refresh()

    def refresh(self) -> None:
        """Protect output dimensions/device-independent configuration during a live session."""
        active = self.output.server is not None
        self.start_button.setEnabled(not active and self.job is None)
        self.stop_button.setEnabled(active)
        for field in (self.frame_width, self.frame_height, self.fps, self.port):
            field.setEnabled(not active)

    def check_context(self) -> None:
        """Stop when a different project, scene or Object Editor replaces the selected output."""
        if self.output.server and (
            self.host.viewmodel.documents is not self.document
            or self.document.project is None
            or self.document.scene.id != self.scene_id
            or self.document.animation_context is not None
        ):
            self.stop()
            self.note.setText(
                "Output stopped because the workspace changed. Return to Scene and restart."
            )

    def start(self) -> None:
        """Begin only on explicit request, preserving the active document and transport."""
        try:
            if (
                self.host.viewmodel.documents is not self.document
                or self.document.project is None
                or self.document.scene.id != self.scene_id
                or self.document.animation_context
            ):
                raise ProjectError("Open local output in the main Scene you want to publish.")
            if self.job:
                raise ProjectError(
                    "Wait for the previous frame to finish before restarting output."
                )
            self.generation += 1
            self.address.setText(self.output.start(port=self.port.value(), fps=self.fps.value()))
            self.timer.start(max(1, round(1000 / self.fps.value())))
            self.note.setText("Publishing locally · waiting for the first rendered frame.")
            self.tick()
        except ProjectError as error:
            self.note.setText(str(error))
        self.refresh()

    def tick(self) -> None:
        """Render a single immutable snapshot off-thread; busy producers skip extra frames."""
        if not self.output.server or self.job:
            return
        self.check_context()
        if not self.output.server:
            return
        scratch = self.document.fork()
        pose = self.host.viewport.source_pose if self.follow_preview.isChecked() else None
        pose = pose or self.document.animation.pose
        width, height, generation = (
            self.frame_width.value(),
            self.frame_height.value(),
            self.generation,
        )

        def render() -> bytes:
            """Rasterize current original vectors and camera overlays without any Qt objects."""
            import resvg_py

            return resvg_py.svg_to_bytes(
                svg_string=svg_pose(scratch, pose, width=width, height=height).decode(),
                skip_system_fonts=True,
            )

        def complete(png: bytes) -> None:
            """Discard late frames after Stop and retain only the newest successful image."""
            self.job = None
            if not isValid(self) or self.host._closed:
                return
            if generation == self.generation and self.output.server:
                try:
                    self.output.publish(png)
                    self.note.setText(
                        f"Publishing locally · {self.output.frames} frames · {width} × {height}"
                    )
                except ProjectError as error:
                    self.note.setText(str(error))
            self.refresh()

        def failed(message: str) -> None:
            """Retain the last valid frame and report a render failure on the GUI thread."""
            self.job = None
            if not isValid(self) or self.host._closed:
                return
            if generation == self.generation:
                self.note.setText(message)
            self.refresh()

        self.job = LibraryJob(render)
        self.job.signals.done.connect(complete)
        self.job.signals.failed.connect(failed)
        self.pool.start(self.job)

    def stop(self) -> None:
        """Release the local listener immediately and invalidate outstanding render results."""
        self.generation += 1
        self.timer.stop()
        self.output.stop()
        self.address.clear()
        self.note.setText("Output is off.")
        self.refresh()
