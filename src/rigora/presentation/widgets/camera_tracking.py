"""Local camera preview, explicit calibration and atomic editable performance recording."""

import time
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QThreadPool
from PySide6.QtMultimedia import QMediaDevices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from rigora.application_services.asset_pipeline import AssetPipeline
from rigora.application_services.audio import AudioService
from rigora.application_services.commands import ScenePatch
from rigora.application_services.tracking import TrackingSample, TrackingTake
from rigora.domain.project import ProjectError
from rigora.presentation.viewmodels.camera_tracking import CameraCapture
from rigora.presentation.viewmodels.content_library import LibraryJob
from rigora.presentation.viewmodels.microphone import MicrophoneCapture
from rigora.presentation.widgets.file_dialogs import choose_open_file
from rigora.presentation.widgets.window_frame import CustomDialog

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


class CameraTrackingDialog(CustomDialog):
    """Keep live observations isolated until Stop and keep publishes one reversible take."""

    def __init__(self, window: "MainWindow") -> None:
        """Build local model/device controls without starting a camera or downloading models."""
        super().__init__(window, "Camera performance")
        self.host, self.document = window, window.viewmodel.documents
        self.take: TrackingTake | None = None
        self.busy = False
        self.resize(680, 520)
        box = QVBoxLayout(self.content)
        info = QLabel(
            "Choose local MediaPipe .task models, then Start preview. Hold a neutral pose "
            "and Calibrate before Record. Capture stays on this computer."
        )
        info.setWordWrap(True)
        box.addWidget(info)
        form = QFormLayout()
        self.target, self.devices = QComboBox(), QComboBox()
        self.target.setAccessibleName("Camera target character or face")
        self.devices.setAccessibleName("Camera input device")
        self.devices.addItem("Default camera", "")
        for device in QMediaDevices.videoInputs():
            self.devices.addItem(device.description(), bytes(device.id().data()).hex())
        scene = self.document.scene if self.document.project else None
        if scene:
            roots = {g.id for g in scene.groups if "face" in g.extra}
            for group in scene.groups:
                if group.id in roots:
                    self.target.addItem(group.name, group.id)
            for rig in scene.skeletons:
                if rig.extra.get("object_id") not in roots:
                    self.target.addItem(rig.name, rig.id)
        form.addRow("Character / face", self.target)
        form.addRow("Camera", self.devices)
        self.face_enabled, self.body_enabled = (
            QCheckBox("Track face and head"),
            QCheckBox("Track body"),
        )
        self.face_enabled.setChecked(True)
        prefs = window.viewmodel.preferences.data
        self.face_model = QLineEdit(str(prefs.get("tracking_face_model", "")))
        self.body_model = QLineEdit(str(prefs.get("tracking_body_model", "")))
        for label, enabled, field in (
            ("Face model", self.face_enabled, self.face_model),
            ("Body model", self.body_enabled, self.body_model),
        ):
            row = QHBoxLayout()
            field.setAccessibleName(label)
            field.setPlaceholderText("Choose a local .task model")
            row.addWidget(field)
            button = QPushButton("Choose…")
            button.clicked.connect(
                lambda checked=False, selected=field: self.choose_model(selected)
            )
            row.addWidget(button)
            form.addRow(enabled)
            form.addRow(label, row)
        self.smoothing = QDoubleSpinBox()
        self.smoothing.setRange(0, 0.95)
        self.smoothing.setSingleStep(0.05)
        self.smoothing.setValue(0.35)
        self.smoothing.setAccessibleName("Camera smoothing")
        form.addRow("Smoothing", self.smoothing)
        self.turns = QCheckBox("Switch authored Object views from head turns")
        self.turns.setToolTip(
            "Requires authored Front, Front 3/4 and Side views. Uses turn thresholds with "
            "hysteresis; keeps ordinary editable View keys. Rear views are not inferred."
        )
        form.addRow(self.turns)
        self.record_voice = QCheckBox("Record microphone with this take")
        self.microphones = QComboBox()
        self.microphones.setAccessibleName("Performance microphone input")
        self.microphones.addItem("Default microphone", "")
        for audio_device in QMediaDevices.audioInputs():
            self.microphones.addItem(
                audio_device.description(), bytes(audio_device.id().data()).hex()
            )
        form.addRow(self.record_voice)
        form.addRow("Voice input", self.microphones)
        box.addLayout(form)
        self.buttons: dict[str, QPushButton] = {}
        for actions in (
            (
                ("Start preview", "videocam", self.start),
                ("Calibrate", "center_focus_strong", self.calibrate),
                ("Record", "fiber_manual_record", self.record),
            ),
            (
                ("Stop and keep take", "stop", self.keep),
                ("Discard / stop preview", "close", self.discard),
            ),
        ):
            row = QHBoxLayout()
            for label, icon, callback in actions:
                button = QPushButton(window.icons.icon(icon), label)
                button.setProperty("materialIcon", icon)
                button.clicked.connect(callback)
                self.buttons[label] = button
                row.addWidget(button)
            box.addLayout(row)
        self.status = QLabel("Camera is off. Recording supports up to 600 samples / 30,000 keys.")
        self.status.setWordWrap(True)
        box.addWidget(self.status)
        limits = QLabel(
            "Face tracking drives visible mouth poses, blinks and head tilt; full face "
            "rigs also support gaze/brows. Body capture uses calibrated planar limb "
            "angles on matching human bones. Hidden or low-confidence regions hold "
            "their last pose. Mouth poses are visual tracking, not phoneme recognition."
        )
        limits.setWordWrap(True)
        box.addWidget(limits)
        self.capture = CameraCapture(self)
        self.microphone = MicrophoneCapture(self)
        self.capture.sample.connect(self.receive)
        self.capture.changed.connect(self.refresh)
        self.microphone.changed.connect(self.microphone_status)
        self.finished.connect(lambda _: self.discard())
        self.host.viewmodel.changed.connect(self.check_revision)
        self.refresh()

    def microphone_status(self) -> None:
        """Stop synchronized capture on microphone failure while retaining stopped take data."""
        if self.microphone.error:
            self.capture.failed(self.microphone.error)

    def choose_model(self, field: QLineEdit) -> None:
        """Use the platform picker for an existing task bundle."""
        path, _ = choose_open_file(
            self, "Choose local tracking model", field.text(), "MediaPipe (*.task)"
        )
        if path:
            field.setText(path)

    def check_revision(self) -> None:
        """Release hardware promptly when tab/lifecycle changes invalidate capture ownership."""
        if not self.take:
            return
        try:
            if self.host.viewmodel.documents is not self.document:
                raise ProjectError("Active project changed.")
            self.take.check_ownership()
        except ProjectError:
            self.capture.stop()
            self.microphone.stop_device()
            self.take.recording = False
            self.status.setText("Project changed. Capture stopped; the take was not applied.")

    def refresh(self) -> None:
        """Expose only actions valid for the active device, retained take and worker state."""
        if self.capture.error and not self.capture.active:
            self.microphone.stop_device()
            if self.take:
                self.take.recording = False
        if self.capture.error and not self.capture.active and self.take and not self.take.frames:
            self.take = None
        active = self.capture.active
        recording = bool(self.take and self.take.recording)
        self.buttons["Start preview"].setEnabled(
            not self.capture.job and not self.take and not self.busy
        )
        self.buttons["Calibrate"].setEnabled(active and not recording and not self.busy)
        self.buttons["Record"].setEnabled(active and not recording and not self.busy)
        self.record_voice.setEnabled(not recording and not self.busy)
        self.microphones.setEnabled(not recording and not self.busy)
        self.buttons["Stop and keep take"].setEnabled(
            bool(self.take and self.take.frames) and not self.busy
        )
        for widget in (
            self.target,
            self.devices,
            self.face_model,
            self.body_model,
            self.face_enabled,
            self.body_enabled,
            self.smoothing,
            self.turns,
        ):
            widget.setEnabled(not self.take and not self.busy)
        if self.capture.error:
            self.status.setText(self.capture.error)

    def start(self) -> None:
        """Capture a stable target revision, then start the explicitly requested local models."""
        try:
            if self.host.viewmodel.documents is not self.document:
                raise ProjectError(
                    "Return to the original project tab or reopen Camera performance."
                )
            self.host.viewmodel.playback.pause()
            self.take = TrackingTake(
                self.document,
                str(self.target.currentData()),
                self.smoothing.value(),
                turns=self.turns.isChecked(),
            )
            face = Path(self.face_model.text()) if self.face_enabled.isChecked() else None
            body = Path(self.body_model.text()) if self.body_enabled.isChecked() else None
            self.capture.start(face, body, str(self.devices.currentData()))
            prefs = self.host.viewmodel.preferences
            prefs.data.update(
                tracking_face_model=self.face_model.text(),
                tracking_body_model=self.body_model.text(),
            )
            prefs.save()
            self.status.setText("Loading local models… Camera opens after model initialization.")
        except (ProjectError, OSError, ValueError) as error:
            self.take = None
            self.status.setText(str(error))
        self.refresh()

    def calibrate(self) -> None:
        """Reset neutral calibration only outside a recording."""
        try:
            if self.take:
                self.take.calibrate()
                self.status.setText("Neutral pose calibrated. Move to preview, or Record.")
        except ProjectError as error:
            self.status.setText(str(error))

    def record(self) -> None:
        """Begin retaining filtered observations without editing project keys."""
        try:
            if self.take:
                if self.record_voice.isChecked():
                    self.microphone.start(str(self.microphones.currentData()))
                self.take.record(time.monotonic() - self.capture.clock)
                self.status.setText("Recording editable controls… Stop and keep to commit.")
        except ProjectError as error:
            self.microphone.discard()
            self.status.setText(str(error))
        self.refresh()

    def receive(self, sample: TrackingSample) -> None:
        """Preview canonical geometry and stop stale sessions without publishing keys."""
        if not self.take:
            return
        try:
            self.check_revision()
            if not self.capture.active:
                return
            pose = self.take.feed(sample)
            if pose:
                self.host.viewport.set_pose(pose)
            if self.take.recording:
                self.status.setText(
                    f"Recording · {len(self.take.frames)} samples · "
                    f"{len(self.take.values)} editable channels"
                )
            elif sample.face or sample.angles:
                self.status.setText("Tracking · Calibrate a neutral pose, then Record.")
            else:
                self.status.setText("Tracking lost · holding the last pose.")
        except (ProjectError, ValueError) as error:
            self.capture.stop()
            self.microphone.stop_device()
            self.take.recording = False
            self.status.setText(str(error))
        self.refresh()

    def keep(self) -> None:
        """Release hardware and prepare keys off-thread before checking publication ownership."""
        self.capture.stop()
        take = self.take
        if not take or self.busy:
            return
        take.stop(time.monotonic() - self.capture.clock)
        try:
            voice = self.microphone.finish() if self.microphone.recording else None
        except ProjectError as error:
            take.recording = False
            self.status.setText(str(error))
            self.refresh()
            return
        take.recording, self.busy = False, True

        def complete(command: ScenePatch) -> None:
            """Publish on the GUI thread only while this take owns the active source revision."""
            self.busy = False
            if self.take is not take or self.host._closed:
                return
            try:
                if self.host.viewmodel.documents is not self.document:
                    raise ProjectError("Active project changed.")
                take.check_ownership()
            except ProjectError:
                self.status.setText("Project changed. The stopped take was retained, not applied.")
            else:
                try:
                    with self.document.command_group("Record camera performance and voice"):
                        self.document.execute(command)
                        if voice:
                            asset = AssetPipeline(self.document).audio_bytes(
                                "Performance voice.wav", voice
                            )
                            AudioService(self.document).attach(
                                str(asset["asset_id"]), start=take.start
                            )
                    self.take = None
                    self.microphone.discard()
                    self.capture.error = ""
                    self.host.viewmodel.changed.emit()
                    self.host.update_animation()
                    self.status.setText(
                        "Performance recorded as editable keys · Undo is available."
                    )
                except (ProjectError, OSError, ValueError) as error:
                    self.status.setText(str(error))
            self.refresh()

        def failed(message: str) -> None:
            """Retain the stopped take for retry after a rejected or failed publication."""
            self.busy = False
            self.status.setText(message)
            self.refresh()

        job = LibraryJob(take.recorded_command)
        job.signals.done.connect(complete)
        job.signals.failed.connect(failed)
        QThreadPool.globalInstance().start(job)
        self.status.setText("Preparing editable take…")
        self.refresh()

    def discard(self) -> None:
        """Release capture and drop unpublished observations without changing document history."""
        self.capture.stop()
        self.microphone.discard()
        self.take = None
        self.capture.error = ""
        if not self.host._closed:
            self.host.update_animation()
        self.refresh()
