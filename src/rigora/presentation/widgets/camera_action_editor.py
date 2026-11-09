"""Camera-cut and preset cards for the shared scene dope sheet."""

from dataclasses import replace
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QElapsedTimer, Qt, QTimer
from PySide6.QtGui import QHideEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.cameras import CameraService
from rigora.application_services.documents import DocumentService
from rigora.domain.project import ProjectError
from rigora.engine.camera_actions import EFFECT_PRESETS, MOTION_PRESETS
from rigora.presentation.widgets.clip_editor import numeric
from rigora.presentation.widgets.creator_cards import configure_cards
from rigora.presentation.widgets.window_frame import CustomDialog

if TYPE_CHECKING:
    from rigora.presentation.widgets.timeline import Timeline


class CameraActionEditor(CustomDialog):
    """Keep camera cuts and reusable move/effect settings above canonical timeline records."""

    def __init__(self, timeline: "Timeline", action: dict[str, Any]) -> None:
        """Inspect stable action identities; picking a card never writes until Apply."""
        super().__init__(timeline, "Camera action")
        self.timeline, self.kind = timeline, action["kind"]
        document = timeline.editor.document
        assert document is not None
        self.document: DocumentService = document
        self.scene_id = self.document.scene.id
        self.clip_id = self.document.selected_clip_id
        self.segment = action.get("segment", "")
        self.refs = action.get("refs", ())
        self._preview_document: DocumentService | None = None
        self._preview_source: object = None
        self._preview_pose: object = None
        self._preview_clock = QElapsedTimer()
        self._preview_timer = QTimer(self)
        self._preview_timer.setInterval(33)
        self._preview_timer.timeout.connect(self.preview_tick)
        self._preview_debounce = QTimer(self)
        self._preview_debounce.setSingleShot(True)
        self._preview_debounce.setInterval(90)
        self._preview_debounce.timeout.connect(self.build_preview)
        self.resize(620, 560)
        box = QVBoxLayout(self.content)
        box.addWidget(
            QLabel(
                {
                    "camera_cut": "Camera cut",
                    "camera_motion": "Camera animation",
                    "camera_effect": "Camera effect",
                }[self.kind]
            )
        )
        form = QFormLayout()
        box.addLayout(form)
        self.camera = QComboBox()
        for camera in self.document.scene.cameras:
            self.camera.addItem(camera.name, camera.id)
        self.camera.setCurrentIndex(max(0, self.camera.findData(action["owner"])))
        self.at_frame = numeric(self, "Camera action start", minimum=0, maximum=1e7)
        self.at_frame.setValue(action["frame"])
        self.end = numeric(self, "Camera action end", minimum=1, maximum=1e7)
        self.end.setValue(action["frame"] + 2 * self.document.scene.settings.fps)
        self.speed = numeric(self, "Camera action speed", minimum=0.01, maximum=100)
        self.speed.setValue(1)
        self.amount = numeric(self, "Camera action amount", minimum=0, maximum=2)
        self.amount.setValue(1)
        if self.kind == "camera_effect":
            self.amount.setMaximum(1)
        form.addRow("Frame" if self.kind == "camera_cut" else "Start", self.at_frame)
        if self.kind != "camera_cut":
            form.addRow("Camera", self.camera)
            form.addRow("End", self.end)
            form.addRow("Speed", self.speed)
            form.addRow("Strength", self.amount)
        else:
            self.camera.hide()
            self.end.hide()
            self.speed.hide()
            self.amount.hide()
        self.cards = QListWidget()
        configure_cards(self.cards, compact=True)
        self.cards.setAccessibleName("Camera action presets")
        catalog = (
            {c.id: c.name for c in self.document.scene.cameras}
            if self.kind == "camera_cut"
            else MOTION_PRESETS
            if self.kind == "camera_motion"
            else EFFECT_PRESETS
        )
        for key, name in catalog.items():
            item = QListWidgetItem(
                timeline.icons.icon(
                    "videocam" if self.kind == "camera_cut" else "camera_enhance", 40
                ),
                name,
            )
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setToolTip(name)
            self.cards.addItem(item)
        self.cards.setCurrentRow(0)
        box.addWidget(self.cards, 1)
        self.note = QLabel(
            "Cuts hold until the next cut. Moves and lens effects use editable intervals."
        )
        self.note.setWordWrap(True)
        box.addWidget(self.note)
        self.preview = QCheckBox("Preview in scene")
        self.preview.setChecked(True)
        self.preview.setToolTip(
            "Loop this choice temporarily. Apply saves it; Close restores the scene."
        )
        box.addWidget(self.preview)
        footer = QHBoxLayout()
        box.addLayout(footer)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        footer.addWidget(close)
        self.remove = QPushButton("Remove action")
        self.remove.setEnabled(bool(self.segment or self.refs))
        self.remove.clicked.connect(self.delete)
        footer.addWidget(self.remove)
        footer.addStretch()
        self.apply_button = QPushButton(
            "Apply changes" if self.segment or self.refs else "Insert action"
        )
        self.apply_button.clicked.connect(self.apply)
        footer.addWidget(self.apply_button)
        service = timeline.editor.service
        tracks = service.timeline.tracks if service and service.timeline else ()
        if self.segment:
            window = next(
                (
                    t.extra["camera_action"]
                    for t in tracks
                    if t.extra.get("camera_action", {}).get("id") == self.segment
                ),
                None,
            )
            if window:
                self.select_choice(window["preset"])
                self.end.setValue(window["end"])
                self.speed.setValue(window["speed"])
                self.amount.setValue(window["amount"])
        elif self.refs:
            chosen = next(
                (
                    t.owner_id
                    for t in tracks
                    for k in t.keyframes
                    if (t.id, k.id) in self.refs and k.value >= 0.5
                ),
                None,
            )
            if chosen:
                self.select_choice(chosen)
        self.cards.currentRowChanged.connect(self.schedule_preview)
        self.camera.currentIndexChanged.connect(self.schedule_preview)
        for field in (self.at_frame, self.end, self.speed, self.amount):
            field.valueChanged.connect(self.schedule_preview)
        self.preview.toggled.connect(self.schedule_preview)
        self.timeline.editor.changed.connect(self.check_preview_context)
        self._preview_debounce.start(0)

    def schedule_preview(self, *args: Any) -> None:
        """Coalesce card and numeric changes before rebuilding one isolated preview scene."""
        self._preview_timer.stop()
        self._preview_debounce.stop()
        if self.preview.isChecked():
            self._preview_debounce.start()
        else:
            self.stop_preview()

    def build_preview(self) -> None:
        """Apply the inspected action to a fork; camera preview never authors source records."""
        if not self.isVisible() or not self.preview.isChecked():
            return
        item = self.cards.currentItem()
        if item is None:
            return
        try:
            self.validate()
            scratch = self.document.fork()
            cameras = CameraService(scratch)
            choice = item.data(Qt.ItemDataRole.UserRole)
            target = choice if self.kind == "camera_cut" else self.camera.currentData()
            if not cameras.camera(target).enabled:
                raise ProjectError("Enable this camera to preview its output.")
            # The inspected camera remains the output throughout its audition, even if
            # the source arrangement has other cuts inside the preview interval.
            editor = AnimationEditingService(scratch)
            if editor.timeline and editor.clip:
                editor.publish(
                    "Preview camera",
                    replace(
                        editor.timeline,
                        tracks=tuple(
                            t for t in editor.timeline.tracks if t.property_path != "camera.active"
                        ),
                    ),
                    editor.clip,
                )
            cameras.activate(target)
            if self.kind != "camera_cut":
                cameras.action(
                    target,
                    choice,
                    self.kind,
                    self.at_frame.value(),
                    self.end.value(),
                    speed=self.speed.value(),
                    amount=self.amount.value(),
                    identity=self.segment,
                )
            self._preview_document = scratch
            self._preview_source = self.document.project
            self._preview_pose = None
            self._preview_clock.start()
            self.note.setText("Preview only · Apply saves this choice. Close restores the scene.")
            self.preview_tick()
            if self.kind != "camera_cut" and self._preview_document is not None:
                self._preview_timer.start()
        except (ProjectError, ValueError, KeyError, TypeError) as error:
            self.stop_preview()
            self.note.setText(str(error))

    def check_preview_context(self) -> None:
        """Discard an audition immediately if authoring data or the active workspace changes."""
        if self._preview_document is None:
            return
        try:
            self.validate()
            if self.document.project is not self._preview_source or (
                self._preview_pose is not None
                and self.timeline.editor.preview_pose is not self._preview_pose
            ):
                self.stop_preview()
        except ProjectError:
            self.stop_preview()

    def preview_tick(self) -> None:
        """Evaluate the retained fork at elapsed time; source tracks and cursor remain untouched."""
        self.check_preview_context()
        if self._preview_document is None:
            return
        try:
            start, end = self.at_frame.value(), self.end.value()
            frame = start
            if self.kind != "camera_cut":
                span = end - start
                frame += (
                    span * 0.25
                    + self._preview_clock.elapsed() / 1000 * self.document.scene.settings.fps
                ) % span
            self.timeline.editor.preview_scene(self._preview_document, frame)
            self._preview_pose = self.timeline.editor.preview_pose
        except (ProjectError, ValueError, ZeroDivisionError) as error:
            self.stop_preview()
            self.note.setText(str(error))

    def stop_preview(self) -> None:
        """Stop both timers and restore only the display pose owned by this dialog."""
        self._preview_timer.stop()
        self._preview_debounce.stop()
        self._preview_document, self._preview_source = None, None
        if (
            self._preview_pose is not None
            and self.timeline.editor.preview_pose is self._preview_pose
        ):
            self.timeline.editor.clear_key_preview()
        self._preview_pose = None

    def hideEvent(self, event: QHideEvent) -> None:
        """Restore the source viewport on Close, Escape, window hiding or workspace shutdown."""
        self.stop_preview()
        super().hideEvent(event)

    def select_choice(self, key: str) -> None:
        """Restore camera or preset identity without comparing translated labels."""
        for i in range(self.cards.count()):
            item = self.cards.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == key:
                self.cards.setCurrentRow(i)
                return

    def refresh_icons(self) -> None:
        """Keep open preset cards synchronized with the shared icon theme."""
        for i in range(self.cards.count()):
            item = self.cards.item(i)
            if item:
                item.setIcon(
                    self.timeline.icons.icon(
                        "videocam" if self.kind == "camera_cut" else "camera_enhance", 40
                    )
                )

    def validate(self) -> None:
        """Reject stale scene, clip and editor contexts before making any changes."""
        if (
            self.timeline.editor.document is not self.document
            or self.document.scene.id != self.scene_id
            or self.document.selected_clip_id != self.clip_id
            or self.document.animation_context
        ):
            raise ProjectError("Return to the original scene timeline to edit this camera action.")

    def apply(self) -> None:
        """Commit a camera cut or a regenerated preset interval as one Undo operation."""
        item = self.cards.currentItem()
        if item is None:
            return
        self.stop_preview()
        choice = item.data(Qt.ItemDataRole.UserRole)

        def commit(service: Any) -> None:
            """Share the same camera actions with API, rendering and viewport clients."""
            self.validate()
            with self.document.command_group("Edit camera action"):
                cameras = CameraService(self.document)
                if self.kind == "camera_cut":
                    if self.refs:
                        service.edit_keys(
                            {ref: {"frame": self.at_frame.value()} for ref in self.refs}
                        )
                    cameras.activate(choice, frame=self.at_frame.value())
                else:
                    self.segment = cameras.action(
                        self.camera.currentData(),
                        choice,
                        self.kind,
                        self.at_frame.value(),
                        self.end.value(),
                        speed=self.speed.value(),
                        amount=self.amount.value(),
                        identity=self.segment,
                    )

        self.timeline.editor.run(commit)
        if self.timeline.editor.error:
            self.note.setText(self.timeline.editor.error)
            return
        self.clip_id = self.document.selected_clip_id
        service = self.timeline.editor.service
        self.refs = (
            tuple(
                (t.id, k.id)
                for t in service.timeline.tracks
                for k in t.keyframes
                if t.property_path == "camera.active" and k.frame == self.at_frame.value()
            )
            if service and service.timeline
            else ()
        )
        self.note.setText("Camera action saved.")
        self.remove.setEnabled(True)
        self.apply_button.setText("Apply changes")
        self.timeline.pages.setCurrentIndex(0)

    def delete(self) -> None:
        """Delete the inspected interval or exclusive camera-cut keys without deleting cameras."""
        self.stop_preview()

        def commit(service: Any) -> None:
            self.validate()
            if self.segment:
                CameraService(self.document).remove_action(self.segment)
            else:
                service.edit_keys({ref: {} for ref in self.refs}, delete=True)

        self.timeline.editor.run(commit)
        if self.timeline.editor.error:
            self.note.setText(self.timeline.editor.error)
        else:
            self.close()
