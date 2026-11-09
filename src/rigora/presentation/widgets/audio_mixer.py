"""Independent sound/music/voice placements over canonical clip audio services."""

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from rigora.application_services.audio import AudioService
from rigora.domain.project import ProjectError
from rigora.presentation.widgets.clip_editor import numeric
from rigora.presentation.widgets.file_dialogs import choose_open_file
from rigora.presentation.widgets.window_frame import CustomDialog

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


class AudioMixer(CustomDialog):
    """Edit up to 32 portable PCM WAV tracks; playback/export use the same envelope timing."""

    def __init__(self, host: "MainWindow") -> None:
        """Capture a scene/action and expose source selection separately from track placements."""
        super().__init__(host, "Audio tracks")
        self.host, self.document = host, host.viewmodel.documents
        self.scene_id, self.context = self.document.scene.id, self.document.animation_context
        self.clip_id = self.document.selected_clip_id
        self.resize(510, 680)
        box = QVBoxLayout(self.content)
        form = QFormLayout()
        box.addLayout(form)
        self.tracks, self.sources = QComboBox(), QComboBox()
        self.track_name = QLineEdit("Audio")
        self.start_frame = numeric(self, "Audio start frame", minimum=0, maximum=1e7)
        self.trim_start = numeric(self, "Source trim in seconds", minimum=0, maximum=1800)
        self.trim_end = numeric(self, "Source trim out seconds", minimum=0, maximum=1800)
        self.gain = numeric(self, "Track gain", minimum=0, maximum=1)
        self.gain.setValue(1)
        self.rate = numeric(self, "Audio playback rate", minimum=0.05, maximum=20)
        self.rate.setValue(1)
        self.source_offset = numeric(self, "Source advance in seconds", minimum=0, maximum=1800)
        self.custom_loop_start = QCheckBox("Use a separate loop origin")
        self.loop_start = numeric(self, "Loop origin frame", minimum=0, maximum=1e7)
        self.loop_start.setEnabled(False)
        self.custom_loop_start.toggled.connect(self.loop_start.setEnabled)
        self.loop_frames = numeric(self, "Audio loop period in frames", minimum=0, maximum=1e7)
        self.limit_end = QCheckBox("Limit playback to end frame")
        self.end_frame = numeric(self, "Audio end frame", minimum=0, maximum=1e7)
        self.end_frame.setEnabled(False)
        self.limit_end.toggled.connect(self.end_frame.setEnabled)
        self.fade_in = numeric(self, "Fade in seconds", minimum=0, maximum=1800)
        self.fade_out = numeric(self, "Fade out seconds", minimum=0, maximum=1800)
        self.muted, self.solo = QCheckBox("Mute"), QCheckBox("Solo")
        for label, field in (
            ("Track", self.tracks),
            ("Name", self.track_name),
            ("Source", self.sources),
            ("Start · frame", self.start_frame),
            ("Trim in · seconds", self.trim_start),
            ("Trim out · seconds", self.trim_end),
            ("Gain", self.gain),
            ("Rate × · changes pitch", self.rate),
            ("Source advance · seconds", self.source_offset),
            ("Loop period · 0 disables", self.loop_frames),
            ("Loop origin", self.custom_loop_start),
            ("Loop from · frame", self.loop_start),
            ("End limit", self.limit_end),
            ("End · frame", self.end_frame),
            ("Fade in · seconds", self.fade_in),
            ("Fade out · seconds", self.fade_out),
        ):
            form.addRow(label, field)
        flags = QHBoxLayout()
        flags.addWidget(self.muted)
        flags.addWidget(self.solo)
        form.addRow(flags)
        self.note = QLabel(
            "Tracks mix during playback and video export. Trims and fades use source seconds."
        )
        self.note.setWordWrap(True)
        box.addWidget(self.note)
        row = QHBoxLayout()
        box.addLayout(row)
        for label, callback in (
            ("Import WAV…", self.import_source),
            ("Save track", self.apply),
            ("Remove", self.remove),
            ("Close", self.close),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            row.addWidget(button)
        self.tracks.currentIndexChanged.connect(self.load)
        self.sources.currentIndexChanged.connect(self.source_changed)
        host.viewmodel.media.imported.connect(self.imported)
        self.refresh()

    def check(self) -> None:
        """Reject writing to another document, scene, Object workspace or clip."""
        if (
            self.host.viewmodel.documents is not self.document
            or self.document.scene.id != self.scene_id
            or self.document.animation_context != self.context
            or self.document.selected_clip_id != self.clip_id
        ):
            raise ProjectError("Reopen Audio tracks in the active action before editing.")

    def refresh(self, identity: str = "") -> None:
        """Update saved placements and registered sources after explicit edits/imports."""
        selected = self.sources.currentData()
        with QSignalBlocker(self.sources), QSignalBlocker(self.tracks):
            self.sources.clear()
            for asset in self.document.project.assets if self.document.project else ():
                if asset.kind == "audio":
                    self.sources.addItem(asset.name, asset.id)
            self.sources.setCurrentIndex(max(0, self.sources.findData(selected)))
            self.tracks.clear()
            self.tracks.addItem("New track", "")
            for track in AudioService(self.document).tracks():
                self.tracks.addItem(track.get("name", "Voice"), track["id"])
            self.tracks.setCurrentIndex(max(0, self.tracks.findData(identity)))
        self.load()

    def source_changed(self) -> None:
        """Default a new placement's trim range to the entire source."""
        asset = (
            next(
                (a for a in self.document.project.assets if a.id == self.sources.currentData()),
                None,
            )
            if self.document.project
            else None
        )
        if asset:
            self.trim_start.setValue(0)
            self.trim_end.setValue(asset.extra.get("duration_seconds", 0))

    def load(self) -> None:
        """Restore fields by track identity; changing selection does not change the project."""
        data = next(
            (
                t
                for t in AudioService(self.document).tracks()
                if t["id"] == self.tracks.currentData()
            ),
            None,
        )
        if not data:
            self.source_offset.setValue(0)
            self.custom_loop_start.setChecked(False)
            self.source_changed()
            return
        self.sources.setCurrentIndex(self.sources.findData(data["asset_id"]))
        self.track_name.setText(data.get("name", "Voice"))
        self.start_frame.setValue(data.get("start_frame", 0))
        self.trim_start.setValue(data.get("trim_start", 0))
        if self.document.project is None:
            return
        asset = next((a for a in self.document.project.assets if a.id == data["asset_id"]), None)
        if asset is None:
            self.note.setText("The audio source is missing. Choose an imported source.")
            return
        self.trim_end.setValue(data.get("trim_end", asset.extra["duration_seconds"]))
        self.gain.setValue(data.get("gain", 1))
        self.rate.setValue(data.get("rate", 1))
        self.source_offset.setValue(data.get("source_offset", 0))
        self.custom_loop_start.setChecked(data.get("loop_start_frame") is not None)
        self.loop_start.setValue(data.get("loop_start_frame") or 0)
        self.loop_frames.setValue(data.get("loop_frames", 0))
        self.limit_end.setChecked(data.get("end_frame") is not None)
        self.end_frame.setValue(data.get("end_frame") or 0)
        self.fade_in.setValue(data.get("fade_in", 0))
        self.fade_out.setValue(data.get("fade_out", 0))
        self.muted.setChecked(data.get("muted", False))
        self.solo.setChecked(data.get("solo", False))

    def apply(self) -> None:
        """Publish one complete track edit through the scene ViewModel/history route."""
        identity = self.tracks.currentData()

        def edit(_: object) -> None:
            nonlocal identity
            self.check()
            identity = AudioService(self.document).put_track(
                self.sources.currentData(),
                identity=identity,
                name=self.track_name.text(),
                start=self.start_frame.value(),
                trim_start=self.trim_start.value(),
                trim_end=self.trim_end.value(),
                gain=self.gain.value(),
                fade_in=self.fade_in.value(),
                fade_out=self.fade_out.value(),
                muted=self.muted.isChecked(),
                solo=self.solo.isChecked(),
                rate=self.rate.value(),
                source_offset=self.source_offset.value(),
                loop_start_frame=self.loop_start.value()
                if self.custom_loop_start.isChecked()
                else None,
                loop_frames=self.loop_frames.value(),
                end_frame=self.end_frame.value() if self.limit_end.isChecked() else None,
            )

        self.host.viewmodel.scene.run(edit)
        self.clip_id = self.document.selected_clip_id
        self.note.setText(self.host.viewmodel.scene.error or "Audio track saved.")
        if not self.host.viewmodel.scene.error:
            self.refresh(identity)

    def remove(self) -> None:
        """Remove a placement without deleting its source or neighboring tracks."""

        def edit(_: object) -> None:
            self.check()
            AudioService(self.document).remove_track(self.tracks.currentData())

        self.host.viewmodel.scene.run(edit)
        self.note.setText(self.host.viewmodel.scene.error or "Audio placement removed.")
        if not self.host.viewmodel.scene.error:
            self.refresh()

    def import_source(self) -> None:
        """Use a native picker and the shared bounded media-import worker."""
        filename, _ = choose_open_file(self, "Import audio source", "", "PCM WAV (*.wav)")
        if filename:
            source = Path(filename)
            self.host.viewmodel.media.submit(
                "audio_import", {"path": str(source)}, source.parent, (source.parent,)
            )

    def imported(self, result: object) -> None:
        """Refresh only the original context, without applying a source by selection."""
        try:
            self.check()
            self.refresh(self.tracks.currentData())
        except ProjectError as error:
            self.note.setText(str(error))
