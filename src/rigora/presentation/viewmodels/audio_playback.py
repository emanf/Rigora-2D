"""Qt audio output follows canonical transport timing without temporary source files."""

from PySide6.QtCore import QBuffer, QIODevice, QObject, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from rigora.application_services.audio import AudioPosition, AudioService
from rigora.application_services.documents import DocumentService
from rigora.domain.project import ProjectError


class AudioPlayback(QObject):
    """Own one buffered player; clip switches, loops and seeking synchronize its source time."""

    def __init__(self, parent: QObject) -> None:
        """Create output lazily so silent projects never initialize an audio device."""
        super().__init__(parent)
        self.player: QMediaPlayer | None = None
        self.output: QAudioOutput | None = None
        self.buffer: QBuffer | None = None
        self.source: tuple[int, str] | None = None
        self.error = ""
        self.muted = False
        self.wanted_position = 0
        self.wanted_playing = False
        self.channels: dict[str, AudioPlayback] = {}

    def sync(self, document: DocumentService | None, playing: bool, speed: float) -> None:
        """Follow transport state, correcting decoder drift beyond 120 ms and loop wraps."""
        self.sync_frame(
            document,
            document.animation.playback.frame if document and document.project else 0,
            playing,
            speed,
        )

    def sync_frame(
        self, document: DocumentService | None, frame: float, playing: bool, speed: float
    ) -> None:
        """Follow an explicit canonical frame for scratch performances as well as transport."""
        try:
            positions = (
                AudioService(document).positions(frame) if (document and document.project) else ()
            )
            self.sync_position(document, positions[0] if positions else None, playing, speed)
            active = set()
            for position in positions[1:]:
                active.add(position.track_id)
                channel = self.channels.get(position.track_id)
                if channel is None:
                    channel = self.channels[position.track_id] = AudioPlayback(self)
                channel.muted = self.muted
                channel.sync_position(document, position, playing, speed)
            for identity in tuple(self.channels):
                if identity not in active:
                    channel = self.channels.pop(identity)
                    channel.sync_position(None, None, False, speed)
                    channel.deleteLater()
        except (ProjectError, OSError, ValueError) as error:
            self.error = str(error)
            self.sync_position(None, None, False, speed)
            for channel in self.channels.values():
                channel.sync_position(None, None, False, speed)

    def sync_position(
        self,
        document: DocumentService | None,
        position: AudioPosition | None,
        playing: bool,
        speed: float,
    ) -> None:
        """Own one decoder/output for one independently timed track; source bytes stay buffered."""
        try:
            if position is None or document is None:
                self.wanted_playing = False
                self.error = ""
                if self.player:
                    self.player.stop()
                self.source = None
                return
            source = (id(document), position.asset_id)
            if self.player is None:
                self.player = QMediaPlayer(self)
                self.output = QAudioOutput(self)
                self.player.setAudioOutput(self.output)
                self.player.errorOccurred.connect(self.failed)
                self.player.mediaStatusChanged.connect(self.ready)
            if self.source != source:
                self.player.stop()
                self.player.setSource(QUrl())
                if self.buffer:
                    self.buffer.close()
                    self.buffer.deleteLater()
                self.buffer = QBuffer(self)
                self.buffer.setData(document.read_asset(position.asset_id))
                self.buffer.open(QIODevice.OpenModeFlag.ReadOnly)
                self.player.setSourceDevice(self.buffer, QUrl("audio.wav"))
                self.source, self.error = source, ""
            assert self.output is not None
            self.output.setVolume(position.gain)
            self.output.setMuted(position.muted or self.muted)
            self.player.setPlaybackRate(speed * position.rate)
            milliseconds = round(max(0, position.seconds) * 1000)
            wrapped = milliseconds < self.wanted_position - 1
            self.wanted_position = milliseconds
            self.wanted_playing = (
                playing and position.start_seconds <= position.seconds < position.duration
            )
            if not playing or wrapped or abs(self.player.position() - milliseconds) > 120:
                self.player.setPosition(milliseconds)
            if self.wanted_playing:
                self.player.play()
            else:
                self.player.pause()
        except (ProjectError, OSError, ValueError) as error:
            self.error = str(error)
            if self.player:
                self.player.stop()

    def ready(self, status: QMediaPlayer.MediaStatus) -> None:
        """Reapply seeks requested during asynchronous decoding before the source became ready."""
        if self.player and status in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        ):
            if abs(self.player.position() - self.wanted_position) > 1:
                self.player.setPosition(self.wanted_position)
            if self.wanted_playing:
                self.player.play()

    def failed(self, *_: object) -> None:
        """Retain decoder/device errors for the host without breaking visual playback."""
        if self.player:
            self.error = self.player.errorString()
