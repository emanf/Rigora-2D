"""Camera shot cards with bounded background thumbnails, composition guides and follow controls."""

from typing import TYPE_CHECKING

from PySide6.QtCore import QSignalBlocker, Qt, QThreadPool
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from rigora.application_services.camera_shots import CameraShotService
from rigora.application_services.output import OutputSettings, raster_frame
from rigora.domain.project import ProjectError
from rigora.infrastructure.media_import import png_bytes
from rigora.presentation.viewmodels.content_library import LibraryJob
from rigora.presentation.widgets.clip_editor import numeric
from rigora.presentation.widgets.creator_cards import configure_cards
from rigora.presentation.widgets.window_frame import CustomDialog

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


class CameraShots(CustomDialog):
    """Author cut/blend shots and camera following, reusing the canonical scene evaluator."""

    def __init__(self, host: "MainWindow") -> None:
        """Capture one scene timeline; thumbnail generation never seeks the source document."""
        super().__init__(host, "Camera shots")
        self.host, self.document = host, host.viewmodel.documents
        self.scene_id, self.context = self.document.scene.id, self.document.animation_context
        self.clip_id = self.document.selected_clip_id
        self.job: LibraryJob | None = None
        self.closed = False
        self.resize(700, 720)
        box = QVBoxLayout(self.content)
        form = QFormLayout()
        box.addLayout(form)
        self.camera, self.follow_target, self.guides, self.easing = (QComboBox() for _ in range(4))
        for camera in self.document.scene.cameras:
            self.camera.addItem(camera.name, camera.id)
        self.follow_target.addItem("No follow", "")
        for key, node in self.document.animation.pose.nodes.items():
            if node.kind != "camera":
                self.follow_target.addItem(node.name, key)
        self.guides.addItems(("Off", "Thirds", "Safe area", "Thirds + safe"))
        self.guides.setCurrentText(host.viewport.camera_guides)
        self.guides.currentTextChanged.connect(self.guide_changed)
        self.easing.addItems(("smooth", "linear"))
        self.at_frame = numeric(self, "Shot start", minimum=0, maximum=1e7)
        self.at_frame.setValue(self.document.cursor_frame)
        self.duration = numeric(self, "Transition frames; zero is a cut", minimum=0, maximum=7200)
        self.offset_x = numeric(self, "Follow X offset")
        self.offset_y = numeric(self, "Follow Y offset")
        for label, field in (
            ("Camera", self.camera),
            ("Start frame", self.at_frame),
            ("Blend frames · 0 = cut", self.duration),
            ("Blend easing", self.easing),
            ("Composition guides", self.guides),
            ("Follow target", self.follow_target),
            ("Follow offset X", self.offset_x),
            ("Follow offset Y", self.offset_y),
        ):
            form.addRow(label, field)
        self.cards = QListWidget()
        configure_cards(self.cards, compact=True)
        self.cards.setAccessibleName("Scene camera shots")
        box.addWidget(self.cards, 1)
        self.note = QLabel(
            "Select a shot to inspect its frame. Curved motion is authored in Motion paths."
        )
        self.note.setWordWrap(True)
        box.addWidget(self.note)
        row = QHBoxLayout()
        box.addLayout(row)
        for label, callback in (
            ("Save shot", self.apply),
            ("Remove cut", self.remove),
            ("Set follow", self.follow),
            ("Refresh previews", self.thumbnails),
            ("Close", self.close),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            row.addWidget(button)
        self.cards.currentItemChanged.connect(self.select)
        self.refresh()
        self.thumbnails()

    def check(self) -> None:
        """Reject stale or Object Editor camera writes."""
        if (
            self.host.viewmodel.documents is not self.document
            or self.document.scene.id != self.scene_id
            or self.document.animation_context
            or self.document.selected_clip_id != self.clip_id
        ):
            raise ProjectError("Reopen Camera shots in the original main Scene timeline.")

    def refresh(self) -> None:
        """Build chronological shot cards without altering the playback position."""
        with QSignalBlocker(self.cards):
            self.cards.clear()
            for shot in CameraShotService(self.document).shots():
                item = QListWidgetItem(
                    self.host.icons.icon("videocam"),
                    f"{shot['name']}\n{shot['frame']:g}–{shot['end']:g} fr",
                )
                item.setData(Qt.ItemDataRole.UserRole, shot)
                self.cards.addItem(item)

    def guide_changed(self, value: str) -> None:
        """Change an editor-only composition overlay across the active camera border."""
        self.host.viewport.camera_guides = value
        self.host.viewport.update()

    def select(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        """Inspect a saved shot by moving the normal playhead, without authoring a key."""
        if current:
            shot = current.data(Qt.ItemDataRole.UserRole)
            self.camera.setCurrentIndex(self.camera.findData(shot["camera"]))
            self.at_frame.setValue(shot["frame"])
            self.host.viewmodel.playback.seek(shot["frame"])
            rule = next(
                (
                    c
                    for c in self.document.scene.constraints
                    if c.kind == "shot_transition"
                    and c.extra.get("shot_frame") == shot["frame"]
                    and c.extra.get("clip_id") == self.clip_id
                ),
                None,
            )
            self.duration.setValue(0)
            if rule:
                timeline = next(
                    (
                        t
                        for t in self.document.scene.timelines
                        if any(track.owner_id == rule.id for track in t.tracks)
                    ),
                    None,
                )
                track = (
                    next((t for t in timeline.tracks if t.owner_id == rule.id), None)
                    if timeline
                    else None
                )
                if track and track.keyframes:
                    self.duration.setValue(track.keyframes[-1].frame - track.keyframes[0].frame)

    def apply(self) -> None:
        """Commit cut/transition data in one Undo step."""

        def edit(_: object) -> None:
            self.check()
            CameraShotService(self.document).shot(
                self.camera.currentData(),
                self.at_frame.value(),
                duration=self.duration.value(),
                easing=self.easing.currentText(),
            )

        self.host.viewmodel.scene.run(edit)
        self.clip_id = self.document.selected_clip_id
        self.note.setText(self.host.viewmodel.scene.error or "Shot saved.")
        if not self.host.viewmodel.scene.error:
            self.refresh()

    def remove(self) -> None:
        """Remove the chosen boundary while keeping its camera and animation."""

        def edit(_: object) -> None:
            self.check()
            CameraShotService(self.document).remove_shot(self.at_frame.value())

        self.host.viewmodel.scene.run(edit)
        self.note.setText(self.host.viewmodel.scene.error or "Cut removed; cameras retained.")
        if not self.host.viewmodel.scene.error:
            self.refresh()

    def follow(self) -> None:
        """Create/edit/remove a real follow constraint, never just a display camera transform."""

        def edit(_: object) -> None:
            self.check()
            CameraShotService(self.document).follow(
                self.camera.currentData(),
                self.follow_target.currentData(),
                offset_x=self.offset_x.value(),
                offset_y=self.offset_y.value(),
            )

        self.host.viewmodel.scene.run(edit)
        self.note.setText(self.host.viewmodel.scene.error or "Camera follow saved.")

    def thumbnails(self) -> None:
        """Render at most 64 small cards off-thread from an isolated immutable revision."""
        if self.job:
            return
        snapshot, baseline = self.document.fork(), self.document.project
        shots = CameraShotService(snapshot).shots()[:64]

        def render() -> list[bytes]:
            settings = OutputSettings(width=160, height=90)
            return [png_bytes(raster_frame(snapshot, shot["frame"], settings)) for shot in shots]

        def complete(images: list[bytes]) -> None:
            self.job = None
            if self.closed or self.document.project is not baseline:
                return
            for index, data in enumerate(images):
                if index >= self.cards.count():
                    break
                pixmap = QPixmap()
                pixmap.loadFromData(data)
                self.cards.item(index).setIcon(QIcon(pixmap))

        self.job = LibraryJob(render)
        self.job.signals.done.connect(complete)
        self.job.signals.failed.connect(self.failed)
        QThreadPool.globalInstance().start(self.job)

    def failed(self, message: str) -> None:
        """Report unavailable rendering dependencies or invalid scene geometry without data loss."""
        self.job = None
        if not self.closed:
            self.note.setText(message)

    def done(self, result: int) -> None:
        """Discard thumbnails completed after this authoring window closes."""
        self.closed = True
        super().done(result)
