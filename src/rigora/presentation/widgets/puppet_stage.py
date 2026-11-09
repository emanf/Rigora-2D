"""Original motion-card workspace with isolated preview, keyboard triggers and recorded
performance.
"""

import time
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtMultimedia import QMediaDevices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from rigora.application_services.asset_pipeline import AssetPipeline
from rigora.application_services.audio import AudioService
from rigora.application_services.characters import CharacterService
from rigora.application_services.puppet import PuppetService, PuppetSession
from rigora.domain.project import ProjectError
from rigora.presentation.viewmodels.audio_playback import AudioPlayback
from rigora.presentation.viewmodels.microphone import MicrophoneCapture
from rigora.presentation.widgets.asset_cards import configure_card_grid
from rigora.presentation.widgets.file_dialogs import choose_open_file, choose_save_file
from rigora.presentation.widgets.window_frame import CustomDialog

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


class PuppetStage(CustomDialog):
    """Trigger freely distributable body/FFD recipes and object effects against explicit targets."""

    def __init__(self, window: "MainWindow") -> None:
        """Build motion cards using the existing shared catalog, command services and custom
        chrome.
        """
        super().__init__(window, "Rigora Puppet Stage")
        self.host, self.model = window, window.viewmodel
        self.session: PuppetSession | None = None
        self.busy = False
        self.audio = AudioPlayback(self)
        self.microphone = MicrophoneCapture(self)
        self.stopped_take: PuppetSession | None = None
        self.stopped_voice: bytes | None = None
        self.stop_token = object()
        self._profile: tuple[Any, ...] = ()
        self._clock = time.monotonic()
        self.resize(560, 740)
        box = QVBoxLayout(self.content)
        self.target = QComboBox()
        self.target.setAccessibleName("Puppet target rig, artwork or object")
        self.target.currentIndexChanged.connect(self.filter_content)
        box.addWidget(self.target)
        self.motion = QComboBox()
        self.motion.setAccessibleName("Compatible body or FFD motion")
        box.addWidget(self.motion)
        row = QHBoxLayout()
        row.addWidget(self.button("Add motion card", "add", self.add_motion))
        self.effect = QComboBox()
        for name, key in (
            ("Flip horizontal", "flip_x"),
            ("Flip vertical", "flip_y"),
            ("Toggle visibility", "visibility"),
            ("Toggle opacity", "opacity"),
        ):
            self.effect.addItem(name, key)
        row.addWidget(self.effect)
        row.addWidget(self.button("Add effect", "add", self.add_effect))
        box.addLayout(row)
        self.cards = QListWidget()
        configure_card_grid(self.cards)
        self.cards.setAccessibleName("Motion cards · click while previewing to trigger")
        self.cards.currentItemChanged.connect(self.select_card)
        self.cards.itemClicked.connect(self.trigger_item)
        box.addWidget(self.cards, 1)
        settings = QHBoxLayout()
        self.hotkey = QLineEdit("1")
        self.hotkey.setMaxLength(1)
        self.hotkey.setMaximumWidth(42)
        self.hotkey.setAccessibleName("Motion card hotkey")
        self.speed = QDoubleSpinBox()
        self.speed.setRange(0.05, 20)
        self.speed.setValue(1)
        self.speed.setAccessibleName("Motion card speed")
        self.loop = QCheckBox("Loop")
        self.pin = QCheckBox("Default")
        for widget in (
            QLabel("Key"),
            self.hotkey,
            QLabel("Speed ×"),
            self.speed,
            self.loop,
            self.pin,
        ):
            settings.addWidget(widget)
        settings.addWidget(self.button("Save", "check", self.save_card))
        settings.addWidget(self.button("Remove", "delete", self.remove_card))
        box.addLayout(settings)
        files = QHBoxLayout()
        files.addWidget(self.button("Load profile…", "folder_open", self.load_profile))
        files.addWidget(self.button("Share profile…", "folder_zip", self.share_profile))
        files.addWidget(self.button("Spring selected bones", "waves", window.add_springs))
        files.addWidget(self.button("Capture action as replay", "replay", self.capture_replay))
        box.addLayout(files)
        voice_row = QHBoxLayout()
        self.play_audio = QCheckBox("Play clip audio")
        self.play_audio.setChecked(True)
        self.record_voice = QCheckBox("Record microphone")
        self.voice_devices = QComboBox()
        self.voice_devices.addItem("Default microphone", "")
        for device in QMediaDevices.audioInputs():
            self.voice_devices.addItem(device.description(), bytes(device.id().data()).hex())
        for voice_widget in (self.play_audio, self.record_voice, self.voice_devices):
            voice_row.addWidget(voice_widget)
        box.addLayout(voice_row)
        self.microphone.changed.connect(self.microphone_status)
        controls = QHBoxLayout()
        self.preview_button = self.button("Preview", "visibility", lambda: self.start(False))
        self.record_button = self.button("Record", "fiber_manual_record", lambda: self.start(True))
        self.stop_button = self.button("Stop", "stop", self.stop)
        for control in (self.preview_button, self.record_button, self.stop_button):
            controls.addWidget(control)
        controls.addWidget(self.button("Discard take", "delete", lambda: self.stop(cancel=True)))
        box.addLayout(controls)
        self.live = QCheckBox("Live view · temporarily hide authoring docks")
        box.addWidget(self.live)
        self.note = QLabel(
            "Select a target, add cards, then Preview or Record. Click cards or press their keys.\n"
            "Preview leaves the project unchanged. Record → Stop commits one undoable performance."
        )
        self.note.setWordWrap(True)
        box.addWidget(self.note)
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.tick)
        self._docks: dict[str, bool] = {}
        self.model.changed.connect(self.refresh)
        self.model.content.changed.connect(self.filter_content)
        self.model.content.changed.connect(self.update_jobs)
        self.refresh()

    def button(self, label: str, icon: str, callback: Any) -> QPushButton:
        """Create a shared Material action with accessible text and theme metadata."""
        button = QPushButton(self.icons.icon(icon), label)
        button.setProperty("materialIcon", icon)
        button.clicked.connect(callback)
        return button

    def service(self) -> PuppetService:
        """Resolve the currently active project only when an authoring action executes."""
        return PuppetService(self.model.documents)

    def refresh(self) -> None:
        """Synchronize targets and persisted cards while preserving selection and preview
        ownership.
        """
        if self.session and (
            self.model.documents is not self.session.document
            or self.session.document.project is not self.session.original
            or self.session.document.scene.id != self.session.scratch.scene.id
        ):
            self.stop(cancel=True)
            self.note.setText(
                "Project changed · Puppet preview stopped; its scratch edits were discarded."
            )
        project = self.model.documents.project
        key = id(project), self.model.documents.context_key
        if key == self._profile:
            return
        self._profile = key
        target, selected = self.target.currentData(), self.cards.currentItem()
        selected_id = selected.data(Qt.ItemDataRole.UserRole).id if selected else ""
        with QSignalBlocker(self.target):
            self.target.clear()
            if project:
                scene = self.model.documents.scene
                for label, records in (
                    ("Rig", scene.skeletons),
                    ("Artwork", scene.meshes),
                    ("Object", scene.objects),
                    ("Object", tuple(g for g in scene.groups if g.extra.get("object_container"))),
                ):
                    for record in records:
                        self.target.addItem(f"{label} · {record.name}", record.id)
                self.target.setCurrentIndex(max(0, self.target.findData(target)))
        self.cards.clear()
        if project:
            try:
                for card in self.service().cards():
                    icon = next(
                        (
                            self.host.content_shelf.icons.get(entry.key)
                            for entry in self.model.content.entries
                            if entry.item.id == card.content.get("id")
                        ),
                        None,
                    )
                    item = QListWidgetItem(
                        icon or self.icons.icon("movie"),
                        f"{card.hotkey.upper()} · {card.name}"
                        + ("\nDefault" if card.pinned else ""),
                    )
                    item.setData(Qt.ItemDataRole.UserRole, card)
                    self.cards.addItem(item)
                    if card.id == selected_id:
                        self.cards.setCurrentItem(item)
            except ProjectError as error:
                self.note.setText(str(error))
        self.filter_content()

    def filter_content(self, *_: Any) -> None:
        """List only reusable body/FFD motions compatible with the explicitly chosen target."""
        if not hasattr(self, "motion"):
            return
        selected = self.motion.currentData()
        self.motion.clear()
        if self.model.documents.project:
            target = str(self.target.currentData() or "")
            for entry in self.model.content.entries:
                if (
                    entry.item.kind == "action"
                    or (entry.item.kind == "deformation" and "motion" in entry.item.payload)
                ) and not self.service().compatibility(entry.item, target, target):
                    self.motion.addItem(entry.item.name, entry.item)
            scene = self.model.documents.scene
            if target in {o.id for o in (*scene.groups, *scene.objects, *scene.characters)}:
                for clip in CharacterService(self.model.documents).motions(target):
                    self.motion.addItem("Replay · " + clip.name, {"clip_id": clip.id})
            if selected:
                self.motion.setCurrentIndex(max(0, self.motion.findData(selected)))

    def publish(self, operation: Any) -> None:
        """Apply profile edits with shared validation and no hidden changes to active
        performances.
        """
        if self.session or self.busy:
            self.note.setText("Stop the active performance before editing its card profile.")
            return
        try:
            operation(self.service())
            self.model.changed.emit()
        except (ProjectError, OSError, ValueError) as error:
            self.note.setText(str(error))

    def add_motion(self) -> None:
        """Add a compatible catalog motion as a target-bound card with a portable embedded
        recipe.
        """
        item = self.motion.currentData()
        if item:
            if isinstance(item, dict):
                self.publish(
                    lambda service: service.add_replay(
                        str(self.target.currentData()),
                        item["clip_id"],
                        hotkey=self.hotkey.text() or "1",
                    )
                )
                return
            self.publish(
                lambda service: service.add(
                    str(self.target.currentData()), item, hotkey=self.hotkey.text() or "1"
                )
            )

    def capture_replay(self) -> None:
        """Capture the selected Object's current action as an editable, project-local replay."""
        self.publish(
            lambda service: service.capture_replay(
                str(self.target.currentData()), hotkey=self.hotkey.text() or "1"
            )
        )

    def microphone_status(self) -> None:
        """Release a failed input and retain recorded PCM until explicit Stop/Discard."""
        if self.microphone.error:
            self.microphone.stop_device()
            self.note.setText(self.microphone.error + " · Stop keeps the captured voice.")

    def add_effect(self) -> None:
        """Create a real flip/visibility/opacity card for the selected scene object."""
        self.publish(
            lambda service: service.add(
                str(self.target.currentData()),
                hotkey=self.hotkey.text() or "1",
                kind=self.effect.currentData(),
            )
        )

    def select_card(
        self, current: QListWidgetItem | None, previous: QListWidgetItem | None
    ) -> None:
        """Load persisted card settings without changing the project or triggering a motion."""
        if current:
            card = current.data(Qt.ItemDataRole.UserRole)
            self.hotkey.setText(card.hotkey)
            self.speed.setValue(card.speed)
            self.loop.setChecked(card.loop)
            self.pin.setChecked(card.pinned)

    def save_card(self) -> None:
        """Persist editable hotkey, loop, speed and default-card settings through normal undo."""
        item = self.cards.currentItem()
        if item:
            old = item.data(Qt.ItemDataRole.UserRole)
            self.publish(
                lambda service: service.set_cards(
                    tuple(
                        replace(
                            card,
                            hotkey=self.hotkey.text().upper(),
                            speed=self.speed.value(),
                            loop=self.loop.isChecked(),
                            pinned=self.pin.isChecked(),
                        )
                        if card.id == old.id
                        else card
                        for card in service.cards()
                    )
                )
            )

    def remove_card(self) -> None:
        """Remove one card from the profile without removing any already recorded animation."""
        item = self.cards.currentItem()
        if item:
            key = item.data(Qt.ItemDataRole.UserRole).id
            self.publish(
                lambda service: service.set_cards(tuple(c for c in service.cards() if c.id != key))
            )

    def start(self, recording: bool) -> None:
        """Begin an isolated performance and optionally trigger pinned default motions."""
        if self.session or self.busy:
            return
        if self.stopped_take:
            self.note.setText("Keep or discard the stopped take before starting another.")
            return
        try:
            self.host.rig_workspace.set_mode(False)
            self.host.mesh_workspace.set_mode(False)
            self.model.playback.pause()
            self.session = PuppetSession(self.model.documents, recording=recording)
            self.stopped_take, self.stopped_voice = None, None
            if recording and self.record_voice.isChecked():
                self.microphone.start(str(self.voice_devices.currentData()))
            self._clock = time.monotonic()
            self.note.setText(
                "RECORDING · Stop commits one undo step"
                if recording
                else "PREVIEW · Project unchanged"
            )
            self._docks = {key: not dock.isHidden() for key, dock in self.host.docks.items()}
            if self.live.isChecked():
                for dock in self.host.docks.values():
                    dock.hide()
            for card in self.service().cards():
                if card.pinned:
                    self.session.trigger(card, self.session.start_frame)
            self.timer.start()
            self.record_voice.setEnabled(False)
            self.voice_devices.setEnabled(False)
            self.setFocus()
        except ProjectError as error:
            self.microphone.stop_device()
            self.session = None
            self.note.setText(str(error))

    def trigger_item(self, item: QListWidgetItem) -> None:
        """Trigger a clicked card only while preview/record is explicitly active."""
        if self.session:
            try:
                self.session.trigger(item.data(Qt.ItemDataRole.UserRole), self.current_frame())
            except (ProjectError, KeyError, ValueError, ZeroDivisionError) as error:
                self.note.setText(str(error))

    def current_frame(self) -> float:
        """Convert monotonic performance time into the project's canonical frame units."""
        assert self.session
        fps = self.session.scratch.scene.settings.fps
        return self.session.start_frame + (time.monotonic() - self._clock) * fps

    def tick(self) -> None:
        """Display the scratch evaluator without adding keys or changing the source document."""
        if self.session:
            if (
                self.session.document is not self.model.documents
                or self.session.document.project is not self.session.original
                or self.session.document.scene.id != self.session.scratch.scene.id
            ):
                self.stop(cancel=True)
                return
            try:
                self.host.viewport.set_pose(self.session.pose(self.current_frame()))
                self.audio.sync_frame(
                    self.session.scratch if self.play_audio.isChecked() else None,
                    self.session.frame,
                    self.play_audio.isChecked(),
                    1,
                )
            except ProjectError as error:
                self.stop(cancel=True)
                self.note.setText(str(error))

    def stop(self, checked: bool = False, *, cancel: bool = False) -> None:
        """Restore authoring panels and prepare a recorded command off the GUI thread."""
        if self.busy and not cancel:
            return
        if cancel:
            self.stop_token = object()
            self.busy = False
        live = self.session is not None
        self.timer.stop()
        self.record_voice.setEnabled(True)
        self.voice_devices.setEnabled(True)
        self.audio.sync_frame(None, 0, False, 1)
        session, self.session = self.session or self.stopped_take, None
        voice = self.stopped_voice
        if self.microphone.recording and not cancel:
            try:
                voice = self.microphone.finish()
            except ProjectError as error:
                self.note.setText(str(error))
        self.microphone.stop_device()
        self.stopped_take, self.stopped_voice = (None, None) if cancel else (session, voice)
        if session and not session.recording:
            self.stopped_take, self.stopped_voice = None, None
        if cancel:
            self.microphone.discard()
        for key, visible in self._docks.items():
            self.host.docks[key].setVisible(visible)
        self._docks.clear()
        self.host.update_animation()
        if session and session.recording and not cancel:
            if live:
                session.frame = max(
                    session.frame,
                    session.start_frame
                    + (time.monotonic() - self._clock) * session.scratch.scene.settings.fps,
                )
            self.busy = True
            token = self.stop_token = object()
            self.note.setText("Preparing recorded keys…")

            def complete(command: Any) -> None:
                """Publish prepared data on the GUI thread only against its captured source
                revision.
                """
                if self.host._closed or token is not self.stop_token:
                    return
                self.busy = False
                if (
                    self.model.documents is not session.document
                    or session.document.project is not session.original
                    or session.document.scene.id != session.scratch.scene.id
                ):
                    self.note.setText("Project changed · recording was not applied.")
                elif command or voice:
                    try:
                        with session.document.command_group("Record Puppet performance and voice"):
                            session.apply_recorded(command)
                            if voice:
                                asset = AssetPipeline(session.document).audio_bytes(
                                    "Puppet voice.wav", voice
                                )
                                AudioService(session.document).attach(
                                    str(asset["asset_id"]), start=session.start_frame
                                )
                    except (ProjectError, OSError, ValueError) as error:
                        self.note.setText(str(error))
                        return
                    self.stopped_take, self.stopped_voice = None, None
                    self.microphone.discard()
                    self.model.changed.emit()
                    self.note.setText(
                        "Performance recorded · Undo restores the original animation."
                    )
                else:
                    self.stopped_take, self.stopped_voice = None, None
                    self.microphone.discard()
                    self.note.setText("No card triggers were recorded.")

            self.model.content.background(session.recorded_command, complete)

    def update_jobs(self) -> None:
        """Release recording controls after a worker failure and retain its diagnostic text."""
        if self.busy and not self.model.content.busy and self.model.content.error:
            self.busy = False
            self.note.setText(self.model.content.error)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Use card hotkeys only inside this active performance window, preserving text editing."""
        if self.session and not event.isAutoRepeat() and event.text().isalnum():
            for row in range(self.cards.count()):
                item = self.cards.item(row)
                if (
                    item
                    and item.data(Qt.ItemDataRole.UserRole).hotkey.upper() == event.text().upper()
                ):
                    self.trigger_item(item)
            event.accept()
        elif event.key() == Qt.Key.Key_Escape:
            self.stop(cancel=True)
            event.accept()
        else:
            super().keyPressEvent(event)

    def share_profile(self) -> None:
        """Export embedded data recipes so another project can explicitly remap their targets."""
        filename, _ = choose_save_file(
            self, "Share Puppet profile", "My performance.rigpuppet", "Puppet profile (*.rigpuppet)"
        )
        if filename:
            self.publish(lambda service: service.export_profile(Path(filename)))

    def load_profile(self) -> None:
        """Read a data-only profile and remap its cards onto the selected target when requested."""
        filename, _ = choose_open_file(
            self, "Load Puppet profile", "", "Puppet profile (*.rigpuppet)"
        )
        if filename:
            self.publish(
                lambda service: service.import_profile(
                    Path(filename), str(self.target.currentData() or "")
                )
            )

    def closeEvent(self, event: QCloseEvent) -> None:
        """Cancel transient preview on close; explicit Stop is required to publish recording
        keys.
        """
        self.stop(cancel=True)
        super().closeEvent(event)
