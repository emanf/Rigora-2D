"""Vector face controls and an offline waveform-assisted phoneme cue editor."""

from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import (
    QEvent,
    QPointF,
    QRectF,
    QSignalBlocker,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
)
from PySide6.QtGui import QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtMultimedia import QMediaDevices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from rigora.application_services.asset_pipeline import AssetPipeline
from rigora.application_services.audio import AudioService
from rigora.application_services.documents import DocumentService
from rigora.application_services.facial import EXPRESSIONS, VISEMES, FaceService, waveform
from rigora.application_services.speech_performance import SpeechTake
from rigora.domain.project import ProjectError
from rigora.engine.state import ScenePose
from rigora.infrastructure.live_speech import SpeechSample
from rigora.presentation.viewmodels.content_library import LibraryJob
from rigora.presentation.viewmodels.facial_playback import FacialPlayback
from rigora.presentation.viewmodels.live_speech import LiveSpeech
from rigora.presentation.viewmodels.microphone import MicrophoneCapture
from rigora.presentation.widgets.asset_cards import CARD_GAP, CARD_IMAGE_SIZE, CARD_SIZE
from rigora.presentation.widgets.face_preview import FacePreview, face_icon
from rigora.presentation.widgets.file_dialogs import choose_open_file
from rigora.presentation.widgets.window_frame import CustomDialog
from rigora.resources import asset_path

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


class WaveformWidget(QWidget):
    """Display local audio peaks and translate clicks into normalized cue times."""

    seek = Signal(float)

    def __init__(self) -> None:
        """Own a small immutable waveform envelope without decoding or playing audio."""
        super().__init__()
        self.duration = 0.0
        self.peaks: tuple[float, ...] = ()
        self.frame_time = 0.0
        self.cues: tuple[tuple[float, str], ...] = ()
        self.setMinimumHeight(110)
        self.setAccessibleName("Audio waveform; click to scrub")

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw peaks in the current neutral palette and show duration and playhead."""
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().base())
        painter.setPen(QPen(self.palette().text().color(), 1))
        height = max(1, self.height() - 52)
        for index, peak in enumerate(self.peaks):
            x = index * self.width() / len(self.peaks)
            painter.drawLine(
                QPointF(x, height * (0.5 - 0.45 * peak)), QPointF(x, height * (0.5 + 0.45 * peak))
            )
        painter.drawText(
            8, self.height() - 7, f"0 s     {self.duration:.2f} s · PCM WAV · click to scrub"
        )
        extent = max(self.duration, self.cues[-1][0] if self.cues else 0)
        if extent:
            last_label = -100.0
            for seconds, shape in self.cues:
                x = seconds / extent * self.width()
                painter.setPen(QPen(self.palette().mid().color(), 1))
                painter.drawLine(QPointF(x, height + 2), QPointF(x, height + 22))
                if x > last_label + 28:
                    painter.setPen(self.palette().text().color())
                    painter.drawText(QRectF(x + 3, height + 2, 40, 20), shape)
                    last_label = x
        elif not self.peaks:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No voice loaded")
        if extent:
            x = self.frame_time / extent * self.width()
            painter.setPen(QPen(self.palette().highlight().color(), 2))
            painter.drawLine(QPointF(x, 0), QPointF(x, height))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Scrub the local preview in seconds without changing waveform data or scene keys."""
        extent = max(self.duration, self.cues[-1][0] if self.cues else 0)
        if event.button() == Qt.MouseButton.LeftButton and extent:
            self.seek.emit(max(0, min(1, event.position().x() / max(1, self.width()))) * extent)


class FaceDialog(CustomDialog):
    """Key expressions, eyes and visemes through the shared facial animation service."""

    def __init__(self, window: "MainWindow") -> None:
        """Keep the portrait and transport visible while organizing authoring into focused tabs."""
        super().__init__(window, "Face & Lip Sync")
        self.host, self.document = window, window.viewmodel.documents
        self.scene_id = self.document.scene.id
        self.context = self.document.animation_context
        self.audio_asset: str | None = None
        self.audio_data: bytes | None = None
        self.staged_data: bytes | None = None
        self.staged_name = ""
        self.audio_is_staged = False
        self.local_playback = FacialPlayback(self)
        self.control_pose: ScenePose | None = None
        self.control_source: object = None
        self.control_root = ""
        self.speech_take: SpeechTake | None = None
        self.speech_pending = False
        self.speech_final: SpeechSample | None = None
        self.analysis_cancel = Event()
        self.analysis_job: LibraryJob | None = None
        self.example_document: DocumentService | None = None
        self.example_root = ""
        self.draft_document: DocumentService | None = None
        self.draft_source: object = None
        self.draft_signature: object = None
        self.resize(1120, 820)
        self.setMinimumSize(870, 650)
        outer = QVBoxLayout(self.content)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(12)
        heading = QLabel("Face performance")
        heading.setObjectName("FaceHeading")
        outer.addWidget(heading)
        self.faces, self.anchor, self.expression, self.mouth = (QComboBox() for _ in range(4))
        self.creators = QComboBox()
        self.faces.setAccessibleName("Face")
        self.creators.setAccessibleName("Creator character")
        source = QHBoxLayout()
        source.addWidget(QLabel("Character / face"))
        source.addWidget(self.faces, 1)
        self.face_buttons: dict[str, QPushButton] = {}
        create = self.button("Create face", "add", self.create_face)
        self.face_buttons["Create face"] = create
        source.addWidget(create)
        outer.addLayout(source)
        self.anchor.addItem("Free face at stage center", None)
        if self.document.project:
            for rig in self.document.scene.skeletons:
                for bone in rig.bones:
                    self.anchor.addItem(bone.name, bone.id)
        self.expression.addItems(list(EXPRESSIONS))
        self.mouth.addItem("Expression default", "")
        for shape in VISEMES:
            self.mouth.addItem(shape, shape)
        # Hidden adapters retain stable selection values for card and service consumers.
        self.expression.hide()
        self.mouth.hide()
        self.expression.setParent(self.content)
        self.mouth.setParent(self.content)
        self.expression.hide()
        self.mouth.hide()
        split = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(split, 1)
        left = QWidget()
        preview_box = QVBoxLayout(left)
        preview_box.setContentsMargins(0, 0, 12, 0)
        preview_box.setSpacing(8)
        self.portrait = FacePreview()
        preview_box.addWidget(self.portrait, 1)
        self.transport_bar = QHBoxLayout()
        self.play_button = self.button("", "play_arrow", self.local_playback.play_pause)
        self.play_button.setAccessibleName("Play or pause facial animation")
        self.play_button.setToolTip("Play / pause this face and voice preview only")
        self.transport_bar.addStretch()
        self.transport_bar.addWidget(self.play_button)
        self.stop_button = self.button("", "stop", self.local_playback.stop)
        self.stop_button.setToolTip("Stop preview and return to its start")
        self.transport_bar.addWidget(self.stop_button)
        self.frame_label = QLabel("Frame 0")
        self.transport_bar.addWidget(self.frame_label)
        self.transport_bar.addStretch()
        preview_box.addLayout(self.transport_bar)
        wave_title = QHBoxLayout()
        wave_title.addWidget(QLabel("VOICE / MOUTH CUES"))
        self.preview_cues = QCheckBox("Preview cues")
        self.preview_cues.setChecked(True)
        self.preview_cues.setToolTip("Audition draft mouth timing without creating project keys")
        wave_title.addWidget(self.preview_cues)
        wave_title.addStretch()
        wave_title.addWidget(self.button("Import WAV", "audio_file", self.load_audio))
        preview_box.addLayout(wave_title)
        self.wave = WaveformWidget()
        self.wave.setFixedHeight(124)
        self.wave.seek.connect(self.scrub)
        preview_box.addWidget(self.wave)
        self.audio_status = QLabel("Import a voice or use the English example in Audio.")
        self.audio_status.setWordWrap(True)
        self.audio_status.setObjectName("FaceMuted")
        preview_box.addWidget(self.audio_status)
        split.addWidget(left)
        self.tabs = QTabWidget()
        self.tabs.setAccessibleName("Face performance tools")
        split.addWidget(self.tabs)
        split.setSizes([560, 480])
        face = self.page("Face")
        expressions = self.card(face, "Expressions", "Pick a look to preview. Key it when ready.")
        self.expression_cards: dict[str, QToolButton] = {}
        grid = QGridLayout()
        grid.setSpacing(CARD_GAP)
        grid.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        for i, name in enumerate(EXPRESSIONS):
            card = QToolButton()
            card.setText(name)
            card.setIcon(face_icon(name))
            card.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            card.setIconSize(QSize(CARD_IMAGE_SIZE, CARD_IMAGE_SIZE))
            card.setCheckable(True)
            card.setProperty("faceChoice", True)
            card.setFixedSize(CARD_SIZE, CARD_SIZE)
            card.clicked.connect(lambda checked=False, n=name: self.expression.setCurrentText(n))
            card.clicked.connect(self.controls_changed)
            self.expression_cards[name] = card
            grid.addWidget(card, i // 3, i % 3)
        expressions.addLayout(grid)
        mouths = self.card(face, "Mouth shapes", "Speech poses use replaceable vector artwork.")
        grid = QGridLayout()
        grid.setSpacing(CARD_GAP)
        grid.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.mouth_cards: dict[str, QToolButton] = {}
        examples = {
            "Rest": "silence",
            "AI": "ah / eye",
            "E": "see",
            "O": "oh",
            "U": "you",
            "FV": "five",
            "L": "la",
            "MBP": "map / bob",
            "WQ": "we",
            "TH": "think",
        }
        for i, name in enumerate(VISEMES):
            card = QToolButton()
            card.setText(name)
            card.setIcon(face_icon(mouth=name))
            card.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            card.setIconSize(QSize(CARD_IMAGE_SIZE, CARD_IMAGE_SIZE))
            card.setFixedSize(CARD_SIZE, CARD_SIZE)
            card.setCheckable(True)
            card.setProperty("faceChoice", True)
            card.setToolTip(f"{name} · {examples[name]}")
            card.setAccessibleName(f"Mouth {name}: {examples[name]}")
            card.clicked.connect(
                lambda checked=False, n=name: self.mouth.setCurrentIndex(self.mouth.findData(n))
            )
            card.clicked.connect(self.controls_changed)
            self.mouth_cards[name] = card
            grid.addWidget(card, i // 3, i % 3)
        mouths.addLayout(grid)
        mouths.addWidget(
            self.button(
                "Use expression mouth", "restart_alt", lambda: self.mouth.setCurrentIndex(0)
            )
        )
        eyes = self.card(face, "Eyes & gaze", "Full facial rigs support gaze and eyelid controls.")
        self.look_x, self.look_y, self.blink = (QDoubleSpinBox() for _ in range(3))
        form = QFormLayout()
        for label, widget in (
            ("Look X", self.look_x),
            ("Look Y", self.look_y),
            ("Blink", self.blink),
        ):
            widget.setAccessibleName(label)
            widget.setRange(0 if widget is self.blink else -1, 1)
            widget.setSingleStep(0.1)
            form.addRow(label, widget)
        eyes.addLayout(form)
        blink_button = self.button("Add blink", "visibility_off", self.add_blink)
        self.face_buttons["Add blink"] = blink_button
        eyes.addWidget(blink_button)
        setup = self.card(
            face, "Rig setup", "Create a face, or enable speech on a Creator character."
        )
        setup.addWidget(self.anchor)
        setup.addWidget(self.creators)
        setup.addWidget(
            self.button("Enable character speech", "record_voice_over", self.enable_character)
        )
        face.addStretch()
        audio = self.page("Audio")
        voice = self.card(audio, "Voice track", "Import, record or try a spoken English example.")
        self.audio_sources = QComboBox()
        self.audio_sources.setAccessibleName("Voice source")
        self.audio_sources.currentIndexChanged.connect(self.select_audio)
        voice.addWidget(self.audio_sources)
        voice.addWidget(
            self.button("English voice example", "record_voice_over", self.load_example)
        )
        sample = QLabel(
            "“Hello! Welcome to Rigora. Bring your characters to life, one frame at a time.”"
        )
        sample.setWordWrap(True)
        sample.setObjectName("FaceMuted")
        voice.addWidget(sample)
        self.audio_start, self.volume = QDoubleSpinBox(), QDoubleSpinBox()
        self.audio_start.setRange(0, 1000000)
        self.audio_start.setAccessibleName("Audio start frame")
        self.volume.setRange(0, 1)
        self.volume.setSingleStep(0.1)
        self.volume.setValue(1)
        self.volume.setAccessibleName("Clip audio volume")
        self.audio_mute = QCheckBox("Mute voice")
        form = QFormLayout()
        form.addRow("Start frame", self.audio_start)
        form.addRow("Volume", self.volume)
        form.addRow(self.audio_mute)
        voice.addLayout(form)
        voice.addWidget(QLabel("Preview output"))
        self.audio_outputs = QComboBox()
        self.audio_outputs.setAccessibleName("Face preview audio output")
        voice.addWidget(self.audio_outputs)
        self.audio_devices = QMediaDevices(self)
        self.audio_devices.audioOutputsChanged.connect(self.refresh_output_devices)
        self.audio_outputs.currentIndexChanged.connect(self.update_preview_device)
        self.refresh_output_devices()
        voice.addWidget(self.button("Attach voice to timeline", "add", self.attach_audio))
        voice.addWidget(self.button("Detach clip audio", "link_off", self.detach_audio))
        voice.addWidget(self.button("Manage audio tracks…", "graphic_eq", window.show_audio_tracks))
        self.capture = MicrophoneCapture(self)
        self.speech = LiveSpeech(self)
        self.capture.samples.connect(self.speech.feed)
        self.speech.sample.connect(self.speech_preview)
        self.speech.finished.connect(self.speech_completed)
        self.speech.failed.connect(self.speech_failed)
        recording = self.card(audio, "Microphone", "Recording starts only when you press Record.")
        self.microphones = QComboBox()
        self.microphones.setAccessibleName("Microphone input device")
        self.microphones.addItem("Default microphone", "")
        for device in QMediaDevices.audioInputs():
            self.microphones.addItem(device.description(), bytes(device.id().data()).hex())
        recording.addWidget(self.microphones)
        self.live_speech = QCheckBox("Live phonemes · US English · offline")
        self.speech_gestures = QCheckBox("Audio-reactive head & eyebrows")
        recording.addWidget(self.live_speech)
        recording.addWidget(self.speech_gestures)
        self.record_button = self.button("Record", "mic", self.start_recording)
        self.keep_recording_button = self.button("Stop & keep", "stop", self.keep_recording)
        row = QHBoxLayout()
        row.addWidget(self.record_button)
        row.addWidget(self.keep_recording_button)
        recording.addLayout(row)
        recording.addWidget(self.button("Discard take", "delete", self.discard_recording))
        self.recording_status = QLabel()
        self.recording_status.setWordWrap(True)
        recording.addWidget(self.recording_status)
        self.capture.changed.connect(self.capture_status)
        self.capture_status()
        audio.addStretch()
        cue_page = self.page("Lip Sync")
        cue_card = self.card(
            cue_page, "Mouth timing", "Review cues against the waveform, then create editable keys."
        )
        self.cues = QPlainTextEdit()
        self.cues.setAccessibleName("Lip-sync cues: seconds, phoneme or mouth name")
        self.cues.setPlaceholderText("0, Rest\n0.15, MBP\n0.3, AI\n0.5, O")
        self.cues.setMinimumHeight(130)
        self.cue_time = QDoubleSpinBox()
        self.cue_time.setRange(0, 1800)
        self.cue_time.setDecimals(3)
        self.cue_time.setSuffix(" s")
        self.cue_time.setAccessibleName("Mouth cue time in seconds")
        self.cue_shape = QComboBox()
        self.cue_shape.setAccessibleName("Mouth cue shape")
        for name in VISEMES:
            self.cue_shape.addItem(face_icon(mouth=name), name, name)
        cue_fields = QFormLayout()
        cue_fields.addRow("Time", self.cue_time)
        cue_fields.addRow("Mouth", self.cue_shape)
        cue_card.addLayout(cue_fields)
        row = QHBoxLayout()
        row.addWidget(self.button("Set cue", "add", self.set_cue))
        row.addWidget(self.button("Remove cue", "delete", self.remove_cue))
        cue_card.addLayout(row)
        cue_card.addWidget(QLabel("Click the waveform to position a cue."))
        cue_card.addWidget(
            self.disclosure("Edit cue text · seconds, mouth or phoneme", (self.cues,))
        )
        cue_card.addWidget(self.cues)
        cue_card.addWidget(self.button("Suggest energy cues", "graphic_eq", self.suggest))
        cue_card.addWidget(self.button("Key mouth cues & audio", "key", self.key_cues))
        recognition = self.card(
            cue_page,
            "Speech recognition",
            "Built-in English phoneme model. Works offline; results stay editable.",
        )
        self.transcript = QPlainTextEdit()
        self.transcript.setPlaceholderText("Reference text · recognition uses the audio")
        self.transcript.setAccessibleName("Speech reference text")
        self.transcript.setMaximumHeight(78)
        recognition.addWidget(self.transcript)
        self.analyze_button = self.button("Analyze speech locally", "graphic_eq", self.analyze)
        recognition.addWidget(self.analyze_button)
        recognition.addWidget(self.button("Cancel analysis", "close", self.analysis_cancel.set))
        cue_page.addStretch()
        footer = QHBoxLayout()
        self.status = QLabel("Choose a face, or explore the example. Previewing never adds keys.")
        self.status.setWordWrap(True)
        footer.addWidget(self.status, 1)
        self.face_buttons["Preview controls"] = self.button("Preview", "visibility", self.preview)
        self.face_buttons["Key controls"] = self.button("Key pose", "key", self.key_controls)
        footer.addWidget(self.face_buttons["Preview controls"])
        footer.addWidget(self.face_buttons["Key controls"])
        close = self.button("Close", "close", self.reject)
        close.setDefault(True)
        footer.addWidget(close)
        outer.addLayout(footer)
        self.progress = QProgressBar()
        self.progress.setAccessibleName("Speech analysis progress")
        self.progress.setFixedHeight(3)
        self.progress.setTextVisible(False)
        self.progress.hide()
        outer.addWidget(self.progress)
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(45)
        self.preview_timer.timeout.connect(self.preview)
        for combo in (self.expression, self.mouth):
            combo.currentIndexChanged.connect(self.controls_changed)
        for field in (self.look_x, self.look_y, self.blink):
            field.valueChanged.connect(self.controls_changed)
        self.cues.textChanged.connect(self.update_cue_lane)
        self.preview_cues.toggled.connect(self.transport)
        self.volume.valueChanged.connect(self.update_preview_mix)
        self.audio_mute.toggled.connect(self.update_preview_mix)
        self.faces.currentIndexChanged.connect(self.refresh_controls)
        self.refresh()
        self.refresh_controls()
        self.local_playback.changed.connect(self.transport)
        window.viewmodel.animation_editor.document_changed.connect(self.document_updated)
        self.finished.connect(lambda _: self.cleanup())
        tracks = AudioService(self.document).tracks()
        audio_data = next((t for t in tracks if t["id"] == "legacy"), {})
        self.audio_start.setValue(audio_data.get("start_frame", 0))
        self.volume.setValue(audio_data.get("gain", 1))
        self.audio_mute.setChecked(audio_data.get("muted", False))
        index = self.audio_sources.findData(audio_data.get("asset_id"))
        if audio_data.get("asset_id") and index >= 0:
            self.audio_sources.setCurrentIndex(index)
        else:
            self.load_example()
        self.sync_cards()
        self.update_portrait()

    def button(self, text: str, icon: str, action: Callable[[], None]) -> QPushButton:
        """Build an accessible shared-icon control without accidental dialog default states."""
        button = QPushButton(self.host.icons.icon(icon), text)
        button.setAutoDefault(False)
        button.setAccessibleName(text or icon.replace("_", " "))
        button.clicked.connect(action)
        return button

    def disclosure(self, title: str, widgets: tuple[QWidget, ...]) -> QToolButton:
        """Collapse advanced controls under a visible, keyboard-accessible heading."""
        button = QToolButton()
        button.setText(title)
        button.setAccessibleName(title)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setCheckable(True)

        def toggle(expanded: bool) -> None:
            """Keep the Material expansion indicator and controlled widgets in sync."""
            button.setIcon(self.host.icons.icon("expand_more" if expanded else "chevron_right"))
            for widget in widgets:
                widget.setVisible(expanded)

        button.toggled.connect(toggle)
        toggle(False)
        return button

    def page(self, title: str) -> QVBoxLayout:
        """Use one scroll surface per task, keeping portrait and transport outside the tabs."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        box = QVBoxLayout(body)
        box.setContentsMargins(8, 12, 8, 8)
        box.setSpacing(12)
        scroll.setWidget(body)
        self.tabs.addTab(scroll, title)
        return box

    @staticmethod
    def card(parent: QVBoxLayout, title: str, description: str) -> QVBoxLayout:
        """Group a small set of related visual controls in a neutral outlined panel."""
        frame = QFrame()
        frame.setObjectName("FaceCard")
        box = QVBoxLayout(frame)
        box.setContentsMargins(12, 10, 12, 12)
        heading = QLabel(title)
        heading.setObjectName("FaceHeading")
        box.addWidget(heading)
        note = QLabel(description)
        note.setObjectName("FaceMuted")
        note.setWordWrap(True)
        box.addWidget(note)
        parent.addWidget(frame)
        return box

    def refresh(self) -> None:
        """Resolve persisted face descriptors after creation or undo without name-based identity."""
        blocker = QSignalBlocker(self.faces)
        previous = self.faces.currentData()
        self.faces.clear()
        if self.document.project:
            self.creators.clear()
            for group in self.document.scene.groups:
                if "face" in group.extra:
                    self.faces.addItem(group.name, group.id)
                if "character_recipe" in group.extra:
                    self.creators.addItem(group.name, group.id)
        index = self.faces.findData(previous)
        if index >= 0:
            self.faces.setCurrentIndex(index)
        previous_audio = "preview:audio" if self.audio_is_staged else self.audio_asset
        self.audio_sources.blockSignals(True)
        self.audio_sources.clear()
        self.audio_sources.addItem("Choose embedded audio…", None)
        if self.staged_data:
            self.audio_sources.addItem(f"{self.staged_name} · Preview", "preview:audio")
        if self.document.project:
            for asset in self.document.project.assets:
                if asset.kind == "audio":
                    self.audio_sources.addItem(asset.name, asset.id)
        self.audio_sources.setCurrentIndex(max(0, self.audio_sources.findData(previous_audio)))
        self.audio_sources.blockSignals(False)
        del blocker
        self.refresh_controls()

    def document_updated(self) -> None:
        """Refresh saved face and audio identities without moving any tab or scroll position."""
        if not self.isVisible():
            return
        try:
            self.check()
            self.refresh()
            self.refresh_controls()
            self.update_portrait()
        except ProjectError as error:
            self.status.setText(str(error))

    def sync_cards(self) -> None:
        """Keep one visible card selected for each control, including expression defaults."""
        for name, card in self.expression_cards.items():
            card.setChecked(name == self.expression.currentText())
        selected = self.mouth.currentData() or EXPRESSIONS[self.expression.currentText()][1]
        for name, card in self.mouth_cards.items():
            card.setChecked(name == selected)

    def controls_changed(self) -> None:
        """Coalesce fast gaze changes and card selections into a single scratch evaluation."""
        self.sync_cards()
        self.preview_timer.start()

    def update_portrait(self) -> None:
        """Show the actual selected face, falling back to a separate example document."""
        if self.faces.currentData():
            if self.host.viewmodel.documents is not self.document:
                return
            self.portrait.display(
                self.document,
                self.control_pose
                if self.control_source is self.document.project
                and self.control_root == self.faces.currentData()
                and self.control_pose is not None
                else self.document.animation.pose,
                str(self.faces.currentData()),
            )
        else:
            if self.example_document is None:
                self.example_document = DocumentService()
                self.example_document.new()
                self.example_root = FaceService(self.example_document).create()
            self.portrait.display(
                self.example_document,
                self.control_pose
                if self.control_source is self.example_document.project
                and self.control_root == self.example_root
                and self.control_pose is not None
                else self.example_document.animation.pose,
                self.example_root,
                example=True,
            )

    def update_cue_lane(self) -> None:
        """Draw only validated draft cues; invalid text remains editable and never becomes keys."""
        from rigora.application_services.facial import viseme

        values: list[tuple[float, str]] = []
        try:
            if len(self.cues.toPlainText()) > 200000:
                raise ValueError
            for line in self.cues.toPlainText().splitlines():
                if not line.strip():
                    continue
                time, shape = line.split(",")
                seconds = float(time)
                if not 0 <= seconds <= 1800 or len(values) >= 5000:
                    raise ValueError
                values.append((seconds, viseme(shape)))
        except (ProjectError, ValueError):
            values = []
        self.wave.cues = tuple(sorted(values))
        self.local_playback.cue_duration = self.wave.cues[-1][0] if self.wave.cues else 0
        self.wave.update()

    def show_draft(self, seconds: float) -> None:
        """Evaluate cached draft mouth keys for local audition without touching saved animation."""
        if not self.preview_cues.isChecked() or not self.wave.cues or seconds < 0:
            return
        if self.faces.currentData():
            self.check()
            source, root = self.document, str(self.faces.currentData())
        else:
            if self.example_document is None:
                self.update_portrait()
            assert self.example_document is not None
            source, root = self.example_document, self.example_root
        signature = (root, self.wave.cues, tuple(self.values().items()))
        if source.project is not self.draft_source or signature != self.draft_signature:
            self.draft_document = source.fork()
            FaceService(self.draft_document).controls(
                root,
                0,
                expression=self.expression.currentText(),
                mouth=self.mouth.currentData() or None,
                look_x=self.look_x.value(),
                look_y=self.look_y.value(),
                blink=self.blink.value(),
            )
            FaceService(self.draft_document).lip_sync(root, self.wave.cues)
            self.draft_source, self.draft_signature = source.project, signature
        assert self.draft_document is not None
        pose = self.draft_document.animation.evaluate(seconds * source.scene.settings.fps)
        self.portrait.display(source, pose, root, example=source is not self.document)

    def stage_audio(self, name: str, data: bytes) -> None:
        """Retain imported or bundled PCM locally until an explicit timeline application."""
        waveform(data)
        self.staged_name, self.staged_data = name, data
        self.audio_asset, self.audio_is_staged = None, True
        self.refresh()
        self.select_audio()

    def load_example(self) -> None:
        """Load the bundled English audition without adding any project data or undo entry."""
        try:
            self.stage_audio(
                "English welcome.wav", asset_path("audio/english-welcome.wav").read_bytes()
            )
            self.cues.setPlainText(
                asset_path("audio/english-welcome.cues").read_text(encoding="utf-8")
            )
            self.transcript.setPlainText(
                "Hello! Welcome to Rigora. Bring your characters to life, one frame at a time."
            )
            self.status.setText(
                "English example ready. Play previews here; Key mouth cues applies it."
            )
        except (ProjectError, OSError) as error:
            self.status.setText(str(error))

    def ensure_audio(self) -> str | None:
        """Embed the current preview source only inside an explicit undoable application."""
        if not self.audio_data:
            return None
        assert self.document.project is not None
        digest = sha256(self.audio_data).hexdigest()
        asset = next(
            (a for a in self.document.project.assets if a.kind == "audio" and a.sha256 == digest),
            None,
        )
        self.audio_asset = (
            asset.id
            if asset
            else str(
                AssetPipeline(self.document).audio_bytes(
                    self.staged_name or self.audio_sources.currentText(), self.audio_data
                )["asset_id"]
            )
        )
        return self.audio_asset

    def update_preview_mix(self) -> None:
        """Route preview gain/mute directly to the dialog's independent audio output."""
        self.local_playback.set_mix(self.volume.value(), self.audio_mute.isChecked())

    def refresh_output_devices(self) -> None:
        """Show the default output and retain an explicitly chosen headset across openings."""
        selected = self.audio_outputs.currentData()
        if selected is None:
            selected = str(self.host.viewmodel.preferences.data.get("face_audio_output", ""))
        with QSignalBlocker(self.audio_outputs):
            self.audio_outputs.clear()
            device = QMediaDevices.defaultAudioOutput()
            self.audio_outputs.addItem(
                f"System default · {device.description() or 'No output connected'}", ""
            )
            for output in QMediaDevices.audioOutputs():
                self.audio_outputs.addItem(output.description(), bytes(output.id().data()).hex())
            index = self.audio_outputs.findData(selected)
            if index < 0:
                self.audio_outputs.addItem("Disconnected output · choose another device", selected)
                index = self.audio_outputs.count() - 1
            self.audio_outputs.setCurrentIndex(index)
        self.local_playback.set_output_device(str(selected))

    def update_preview_device(self) -> None:
        """Apply only the chosen audition output and persist its stable device identity."""
        selected = str(self.audio_outputs.currentData() or "")
        self.local_playback.set_output_device(selected)
        self.host.viewmodel.preferences.data["face_audio_output"] = selected
        self.host.viewmodel.preferences.save()

    def edit_cue(self, *, remove: bool = False) -> None:
        """Edit one draft event without silently replacing invalid manually entered cue text."""
        from rigora.application_services.facial import viseme

        try:
            values: dict[float, str] = {}
            text = self.cues.toPlainText()
            if len(text) > 200000:
                raise ValueError("Cue text exceeds 200,000 characters.")
            for line in text.splitlines():
                if not line.strip():
                    continue
                time, shape = line.split(",")
                seconds = float(time)
                if not 0 <= seconds <= 1800:
                    raise ValueError("Cue times must be within 0–1800 seconds.")
                values[seconds] = viseme(shape)
            seconds = self.cue_time.value()
            # Displayed times have millisecond precision; preserve original decoder timestamps.
            nearest = next((t for t in values if abs(t - seconds) < 0.00051), seconds)
            if remove:
                values.pop(nearest, None)
            else:
                values[nearest] = str(self.cue_shape.currentData())
            if len(values) > 5000:
                raise ValueError("Supply at most 5000 cues.")
            self.cues.setPlainText("\n".join(f"{t:.5f}, {s}" for t, s in sorted(values.items())))
            self.status.setText("Draft cue updated. Key mouth cues to save it to the timeline.")
        except (ValueError, ProjectError) as error:
            self.status.setText(f"Check cue text before editing: {error}")

    def set_cue(self) -> None:
        """Insert or replace the mouth event at the selected draft time."""
        self.edit_cue()

    def remove_cue(self) -> None:
        """Remove only the event at the selected draft time."""
        self.edit_cue(remove=True)

    def cleanup(self) -> None:
        """Release worker intent, devices and dialog-owned preview signal connections."""
        self.preview_timer.stop()
        self.analysis_cancel.set()
        self.capture.discard()
        self.speech.stop()
        self.local_playback.changed.disconnect(self.transport)
        self.local_playback.close()
        editor = self.host.viewmodel.animation_editor
        editor.document_changed.disconnect(self.document_updated)

    def refresh_controls(self) -> None:
        """Expose only controls supported by a creator mouth or a complete facial rig."""
        group = (
            next(
                (g for g in self.document.scene.groups if g.id == self.faces.currentData()),
                None,
            )
            if self.document.project
            else None
        )
        complete = bool(group and group.extra.get("face", {}).get("kind") != "character-mouth")
        for card in self.expression_cards.values():
            card.setEnabled(complete or group is None)
            card.setToolTip(
                card.text()
                if complete or group is None
                else "Use Feelings and Eye pose variants in Object Editor for this character."
            )
        self.face_buttons["Key controls"].setEnabled(group is not None)
        for widget in (
            self.expression,
            self.look_x,
            self.look_y,
            self.blink,
            self.face_buttons["Add blink"],
        ):
            widget.setEnabled(complete)
            widget.setToolTip(
                ""
                if complete
                else "Creator characters use Feelings and Eye pose variants. "
                "Speech mouth controls remain available."
            )
        if hasattr(self, "portrait"):
            self.update_portrait()

    def enable_character(self) -> None:
        """Upgrade a selected older creator character without replacing its existing artwork."""
        editor = self.host.viewmodel.animation_editor
        key = str(self.creators.currentData())

        def operation(_: object) -> None:
            """Publish newly bound mouth variants in the owning document."""
            self.check()
            FaceService(self.document).enable_character(key)

        editor.run(operation)
        self.status.setText(editor.error or "Character speech shapes are ready.")
        self.refresh()
        index = self.faces.findData(key)
        if index >= 0:
            self.faces.setCurrentIndex(index)

    def select_audio(self) -> None:
        """Load a project or staged source into the isolated audition player."""
        selected = self.audio_sources.currentData()
        self.audio_is_staged = selected == "preview:audio"
        self.audio_asset = None if self.audio_is_staged else selected
        self.audio_data = None
        self.wave.duration, self.wave.peaks = 0, ()
        try:
            self.audio_data = (
                self.staged_data
                if self.audio_is_staged
                else (self.document.read_asset(self.audio_asset) if self.audio_asset else None)
            )
            if self.audio_data:
                self.wave.duration, self.wave.peaks = waveform(self.audio_data)
            self.local_playback.load(self.audio_data, self.audio_sources.currentText())
        except ProjectError as error:
            self.status.setText(str(error))
        self.wave.update()
        self.audio_status.setText(
            f"{self.audio_sources.currentText()} · {self.wave.duration:.2f} s · PCM WAV"
            if self.audio_data
            else "Import a voice or use the English example in Audio."
        )

    def start_recording(self) -> None:
        """Open the explicitly selected microphone without changing any project data."""
        try:
            self.check()
            self.local_playback.pause()
            self.speech_take = (
                SpeechTake(
                    self.document,
                    str(self.faces.currentData()),
                    gestures=self.speech_gestures.isChecked(),
                )
                if self.live_speech.isChecked()
                else None
            )
            self.capture.start(str(self.microphones.currentData()))
            self.speech_final = None
            if self.speech_take and self.capture.recording:
                self.speech.start(self.capture.recording.rate)
        except ProjectError as error:
            self.capture.error = str(error)
        self.capture_status()

    def capture_status(self) -> None:
        """Show capture state and protect samples until explicitly kept or discarded."""
        capture = self.capture
        has_data = bool(capture.recording and capture.recording.data)
        self.record_button.setEnabled(not capture.active and not has_data)
        self.keep_recording_button.setEnabled(capture.active or has_data)
        self.microphones.setEnabled(not capture.active)
        for widget in (self.live_speech, self.speech_gestures, self.faces):
            widget.setEnabled(not capture.active and not self.speech_pending)
        if self.speech_pending:
            self.record_button.setEnabled(False)
            self.keep_recording_button.setEnabled(False)
        seconds = capture.recording.seconds if capture.recording else 0
        self.recording_status.setText(
            "Finishing local phoneme recognition…"
            if self.speech_pending
            else capture.error
            or (
                f"Recording · {seconds:.1f} s"
                if capture.active
                else f"Uncommitted recording · {seconds:.1f} s"
                if has_data
                else "Microphone starts only when Record is pressed. Stop and keep embeds a WAV."
            )
        )

    def keep_recording(self) -> None:
        """Stop capture first, then publish its retained WAV through canonical import/undo."""
        try:
            data = self.capture.finish()
            self.check()
            if self.speech_take and self.live_speech.isChecked():
                if self.speech.job and not self.speech.cancel.is_set():
                    self.speech_pending = True
                    self.speech.stop(keep=True)
                    self.recording_status.setText("Finishing local phoneme recognition…")
                    self.capture_status()
                    return
                if self.speech_final is not None:
                    self.publish_speech(self.speech_final, data)
                    return
                raise ProjectError(
                    "Live recognition did not finish. Audio is retained; turn off Live preview "
                    "and keep the voice, or discard and record again."
                )
            self.speech.stop()
            self.speech_take = None
            self.audio_asset = str(
                AssetPipeline(self.document).audio_bytes("Recorded voice.wav", data)["asset_id"]
            )
            self.audio_is_staged = False
            self.host.viewmodel.animation_editor.document_changed.emit()
            self.capture.discard()
            self.refresh()
            self.select_audio()
            self.status.setText(
                "Recording embedded. Attach it to the clip, or analyze it for lip-sync."
            )
        except (ProjectError, OSError) as error:
            self.capture.error = str(error)
        self.capture_status()

    def discard_recording(self) -> None:
        """Discard only the uncommitted capture, retaining all already imported audio."""
        self.capture.discard()
        self.speech.stop()
        self.speech_take, self.speech_final, self.speech_pending = None, None, False
        self.control_pose = None
        self.update_portrait()
        self.capture.error = ""
        self.capture_status()

    def speech_preview(self, sample: SpeechSample) -> None:
        """Display an owned scratch pose while keeping provisional cues out of document history."""
        if not self.speech_take or self.speech_pending:
            return
        try:
            self.check()
            self.portrait.display(
                self.document, self.speech_take.preview(sample), str(self.faces.currentData())
            )
            self.recording_status.setText(f"Live phoneme · {sample.mouth} · {sample.seconds:.1f} s")
        except ProjectError as error:
            self.speech_failed(str(error))

    def speech_failed(self, message: str) -> None:
        """Release devices on failure and preserve voice bytes for a safe retry or raw import."""
        self.speech.stop()
        self.capture.stop_device()
        self.speech_pending = False
        self.capture.error = message
        self.control_pose = None
        self.update_portrait()
        self.capture_status()

    def speech_completed(self, sample: SpeechSample) -> None:
        """Publish only after an explicit Stop and keep, retaining failed takes for retry."""
        self.speech_final, self.speech_pending = sample, False
        if not self.speech_take:
            return
        try:
            self.publish_speech(sample, self.capture.finish())
        except (ProjectError, OSError) as error:
            self.capture.error = str(error)
            self.capture_status()

    def publish_speech(self, sample: SpeechSample, voice: bytes) -> None:
        """Keep normal waveform/cue editing available after atomic take publication."""
        self.check()
        assert self.speech_take is not None
        self.audio_asset = self.speech_take.keep(sample, voice)
        self.audio_is_staged = False
        self.audio_start.setValue(self.speech_take.start)
        self.speech_take, self.speech_final = None, None
        self.capture.discard()
        self.host.viewmodel.animation_editor.document_changed.emit()
        self.refresh()
        self.select_audio()
        self.cues.setPlainText("\n".join(f"{t:.3f}, {mouth}" for t, mouth in sample.cues))
        self.status.setText(
            "Speech recorded as editable mouth keys and synchronized voice · Undo available."
        )
        self.capture_status()

    def attach_audio(self) -> None:
        """Save clip timing, gain and mute as one undoable command."""
        editor = self.host.viewmodel.animation_editor

        def operation(_: object) -> None:
            """Validate the active document before associating its embedded source."""
            self.check()
            with self.document.command_group("Attach preview voice"):
                asset = self.ensure_audio()
                if not asset:
                    raise ProjectError("Choose a voice before attaching audio.")
                AudioService(self.document).attach(
                    asset,
                    start=self.audio_start.value(),
                    gain=self.volume.value(),
                    muted=self.audio_mute.isChecked(),
                )

        editor.run(operation)
        if not editor.error:
            self.audio_is_staged = False
            self.refresh()
            self.select_audio()
        self.status.setText(editor.error or "Audio attached. Play the timeline to hear it.")

    def detach_audio(self) -> None:
        """Remove playback association without deleting the audio source or mouth keys."""
        editor = self.host.viewmodel.animation_editor

        def operation(_: object) -> None:
            """Reject inactive tab writes through the regular visible error path."""
            self.check()
            AudioService(self.document).detach()

        editor.run(operation)
        self.status.setText(editor.error or "Audio detached; the embedded source is retained.")

    def analyze(self) -> None:
        """Run offline speech recognition on a worker and return editable, uncommitted cues."""
        if self.analysis_job or not self.audio_data:
            self.status.setText("Load or choose audio before analyzing speech.")
            return
        self.analysis_cancel.clear()
        data, source = self.audio_data, (self.audio_asset, self.audio_data)
        self.analyze_button.setEnabled(False)
        self.progress.setRange(0, 0)
        self.progress.show()
        self.status.setText("Analyzing locally… Audio and transcript stay on this computer.")

        def load() -> object:
            """Analyze immutable captured inputs without touching widgets from the worker."""
            return FaceService.speech_cues(
                data,
                cancel=self.analysis_cancel,
            )

        def completed(values: Any) -> None:
            """Expose results for review only when the source has not changed."""
            self.analysis_job = None
            self.analyze_button.setEnabled(True)
            self.progress.hide()
            if source != (self.audio_asset, self.audio_data) or self.analysis_cancel.is_set():
                return
            self.cues.setPlainText("\n".join(f"{time:.4f}, {shape}" for time, shape in values))
            self.status.setText("Speech analyzed. Review the cues, then Key mouth cues.")

        def failed(message: str) -> None:
            """Restore controls and surface recognizer setup or processing errors."""
            self.analysis_job = None
            self.analyze_button.setEnabled(True)
            self.progress.hide()
            self.status.setText(message)

        job = self.analysis_job = LibraryJob(load)
        job.signals.done.connect(completed)
        job.signals.failed.connect(failed)
        QThreadPool.globalInstance().start(job)

    def check(self) -> None:
        """Prevent a floating editor from writing into an inactive project tab."""
        if (
            self.host.viewmodel.documents is not self.document
            or self.document.scene.id != self.scene_id
            or self.document.animation_context != self.context
        ):
            raise ProjectError(
                "Return to the original scene and editor, or reopen Face & Lip Sync."
            )

    def create_face(self) -> None:
        """Create replaceable mouth and eye objects, optionally following a head bone."""

        def operation(_: object) -> None:
            """Create the face inside the current document's command history."""
            self.check()
            FaceService(self.document).create(parent_bone=self.anchor.currentData())

        self.host.viewmodel.animation_editor.run(operation)
        self.status.setText(self.host.viewmodel.animation_editor.error)
        self.refresh()
        self.faces.setCurrentIndex(self.faces.count() - 1)

    def values(self) -> dict[str, object]:
        """Return scalar control inputs independent of the persisted scene representation."""
        return {
            "expression": self.expression.currentText(),
            "mouth": self.mouth.currentData() or None,
            "look_x": self.look_x.value(),
            "look_y": self.look_y.value(),
            "blink": self.blink.value(),
        }

    def apply_controls(self, service: FaceService) -> None:
        """Apply current controls at the visible frame through canonical scalar channels."""
        self.check()
        service.controls(
            str(self.faces.currentData()),
            self.document.animation.pose.frame,
            expression=self.expression.currentText(),
            mouth=self.mouth.currentData() or None,
            look_x=self.look_x.value(),
            look_y=self.look_y.value(),
            blink=self.blink.value(),
        )

    def preview(self) -> None:
        """Show a scratch pose without creating keys in the real document."""
        try:
            self.check()
            self.local_playback.pause()
            if not self.faces.currentData():
                self.update_portrait()
                assert self.example_document is not None
                scratch = self.example_document.fork()
                FaceService(scratch).controls(
                    self.example_root,
                    0,
                    expression=self.expression.currentText(),
                    mouth=self.mouth.currentData() or None,
                    look_x=self.look_x.value(),
                    look_y=self.look_y.value(),
                    blink=self.blink.value(),
                )
                self.control_pose = scratch.animation.pose
                self.control_source, self.control_root = (
                    self.example_document.project,
                    self.example_root,
                )
                self.portrait.display(
                    self.example_document, self.control_pose, self.example_root, example=True
                )
                self.status.setText("Example preview only. Create or choose a face to add keys.")
                return
            scratch = self.document.fork()
            self.apply_controls(FaceService(scratch))
            self.control_pose = scratch.animation.pose
            self.control_source, self.control_root = (
                self.document.project,
                str(self.faces.currentData()),
            )
            self.portrait.display(self.document, self.control_pose, self.control_root)
            self.status.setText("Preview only. Key controls to retain this pose.")
        except (ProjectError, ValueError) as error:
            self.status.setText(str(error))

    def key_controls(self) -> None:
        """Commit the visible expression as one undoable set of ordinary timeline keys."""
        editor = self.host.viewmodel.animation_editor
        editor.run(lambda _: self.apply_controls(FaceService(self.document)))
        self.status.setText(editor.error or "Face controls keyed at the current frame.")

    def add_blink(self) -> None:
        """Insert a short closing/reopening cycle at the current playhead."""
        editor = self.host.viewmodel.animation_editor

        def operation(_: object) -> None:
            """Validate tab ownership before creating the blink cycle."""
            self.check()
            FaceService(self.document).blink(
                str(self.faces.currentData()), self.document.animation.pose.frame
            )

        editor.run(operation)
        self.status.setText(editor.error or "Blink added; edit its three keys in the dope sheet.")

    def load_audio(self) -> None:
        """Stage an explicitly chosen PCM WAV for audition before any project application."""
        path, _ = choose_open_file(self, "Lip-sync WAV", "", "PCM WAV (*.wav)")
        if not path:
            return
        try:
            self.check()
            data = self.document._read_asset_file(Path(path))
            self.stage_audio(Path(path).name, data)
            self.cues.clear()
            self.transcript.clear()
            self.status.setText(f"{Path(path).name} ready for local preview; apply to embed it.")
        except (ProjectError, OSError) as error:
            self.status.setText(str(error))

    def suggest(self) -> None:
        """Populate editable open/rest cues from the audio envelope without speech inference."""
        if self.audio_data:
            values = FaceService(self.document).audio_cues(self.audio_data)
            self.cues.setPlainText("\n".join(f"{time:.4f}, {shape}" for time, shape in values))
            self.status.setText(
                "Energy suggestions only. Replace shapes with phonemes for precise speech."
            )

    def key_cues(self) -> None:
        """Validate all cue rows before atomically publishing editable viseme visibility keys."""
        editor = self.host.viewmodel.animation_editor

        def operation(_: object) -> None:
            """Parse bounded text cues and preserve the current project's clip context."""
            self.check()
            if len(self.cues.toPlainText()) > 200000:
                raise ProjectError("Cue text exceeds 200,000 characters.")
            values = []
            for index, line in enumerate(self.cues.toPlainText().splitlines(), 1):
                if not line.strip():
                    continue
                parts = line.split(",")
                if len(parts) != 2:
                    raise ProjectError(f"Cue row {index}: use seconds, phoneme.")
                values.append((float(parts[0]), parts[1].strip()))
            with self.document.command_group("Key speech and audio"):
                asset = self.ensure_audio()
                FaceService(self.document).lip_sync(
                    str(self.faces.currentData()),
                    values,
                    start=self.audio_start.value(),
                    audio_asset=asset,
                )
                if asset:
                    AudioService(self.document).attach(
                        asset,
                        start=self.audio_start.value(),
                        gain=self.volume.value(),
                        muted=self.audio_mute.isChecked(),
                    )

        editor.run(operation)
        if not editor.error:
            self.audio_is_staged = False
            self.refresh()
            self.select_audio()
        self.status.setText(
            editor.error or "Mouth cues keyed. Move, copy or delete their keys in the dope sheet."
        )

    def changeEvent(self, event: QEvent) -> None:
        """Refresh cached face icons when the application's transparency palette changes."""
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            for name, button in getattr(self, "expression_cards", {}).items():
                button.setIcon(face_icon(name))
            for name, button in getattr(self, "mouth_cards", {}).items():
                button.setIcon(face_icon(mouth=name))

    def scrub(self, seconds: float) -> None:
        """Scrub only the dialog's source-relative clock, selecting nearby mouth events."""
        nearest = min(self.wave.cues, key=lambda cue: abs(cue[0] - seconds), default=None)
        if nearest and abs(nearest[0] - seconds) < max(
            0.03, self.wave.duration * 8 / max(1, self.wave.width())
        ):
            seconds = nearest[0]
            self.cue_shape.setCurrentIndex(self.cue_shape.findData(nearest[1]))
        self.cue_time.setValue(seconds)
        self.local_playback.seek(seconds)

    def transport(self) -> None:
        """Display local voice time and face audition without touching the scene transport."""
        playback = self.local_playback
        if playback.audio.error:
            self.audio_status.setText(playback.audio.error)
        elif playback.playing:
            self.audio_status.setText(
                f"Preview · {playback.output_device().description()} · "
                f"{'Muted' if playback.muted else f'{playback.gain:.0%} volume'}"
            )
        self.play_button.setIcon(
            self.host.icons.icon("pause" if playback.playing else "play_arrow")
        )
        self.frame_label.setText(f"{playback.seconds:.2f} / {playback.duration:.2f} s")
        self.wave.frame_time = playback.seconds
        self.wave.update()
        self.update_portrait()
        if self.wave.cues:
            try:
                self.show_draft(playback.seconds)
            except ProjectError as error:
                self.status.setText(str(error))
