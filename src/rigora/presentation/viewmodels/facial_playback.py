"""Dialog-owned voice audition with no dependency on a scene's timeline or audio mix."""

import time
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QAudioDevice, QMediaDevices, QMediaPlayer

from rigora.application_services.asset_pipeline import AssetPipeline
from rigora.application_services.audio import AudioPosition
from rigora.application_services.documents import DocumentService
from rigora.presentation.viewmodels.audio_playback import AudioPlayback


class FacialPlayback(QObject):
    """Preview staged PCM and mouth cues using an isolated asset owner and local clock.

    The source document never enters the main workspace. Audio bytes are copied to
    the real project only by explicit Apply/Attach actions in the owning dialog.
    """

    changed = Signal()

    def __init__(self, parent: QObject, clock: Callable[[], float] = time.monotonic) -> None:
        """Create dormant playback; opening the dialog does not play sound or open a device."""
        super().__init__(parent)
        self.clock = clock
        self.document = DocumentService()
        self.document.new()
        self.audio = AudioPlayback(self)
        self.asset_id: str | None = None
        self.data: bytes | None = None
        self.audio_duration = 0.0
        self.cue_duration = 0.0
        self.seconds = 0.0
        self.playing = False
        self.gain, self.muted = 1.0, False
        self.device_id = ""
        self._audio_seconds = 0.0
        self._audio_anchor = clock()
        self._audio_ended = False
        self._pending_seek = False
        self._last_time = clock()
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.tick)

    @property
    def duration(self) -> float:
        """Include silent cue-only tails when there is no voice at that time."""
        return max(self.audio_duration, self.cue_duration)

    def load(self, data: bytes | None, name: str = "Voice.wav") -> None:
        """Validate and stage one source without publishing anything to the user's project."""
        if data == self.data:
            return
        self.stop()
        document = DocumentService()
        document.new()
        asset_id = (
            str(AssetPipeline(document).audio_bytes(name, data)["asset_id"]) if data else None
        )
        self.audio.sync_position(None, None, False, 1)
        self.document, self.asset_id, self.data = document, asset_id, data
        assert document.project is not None
        asset = next((a for a in document.project.assets if a.id == asset_id), None)
        self.audio_duration = float(asset.extra["duration_seconds"]) if asset else 0
        self._audio_ended = False
        self.changed.emit()

    def set_mix(self, gain: float, muted: bool) -> None:
        """Audition volume and mute independently of the scene's audio settings."""
        self.gain, self.muted = gain, muted
        if self.audio.output is not None:
            self.audio.output.setVolume(gain)
            self.audio.output.setMuted(muted or self.audio.muted)
        self.changed.emit()

    def output_device(self) -> QAudioDevice:
        """Resolve the selected physical output without falling back from a missing user choice."""
        if not self.device_id:
            return QMediaDevices.defaultAudioOutput()
        return next(
            (
                d
                for d in QMediaDevices.audioOutputs()
                if bytes(d.id().data()).hex() == self.device_id
            ),
            QAudioDevice(),
        )

    def set_output_device(self, device_id: str) -> None:
        """Switch the local audition's speaker/headset; never change the OS or scene output."""
        self.device_id = device_id
        device = self.output_device()
        if device.isNull():
            self.audio.error = "Audio output is unavailable. Choose a connected speaker or headset."
            self.pause()
            return
        self.audio.error = ""
        if self.audio.output is not None:
            self.audio.output.setDevice(device)
        self.changed.emit()

    def play_pause(self) -> None:
        """Play only this source/cue range, restarting from zero after its endpoint."""
        if self.playing:
            self.pause()
            return
        if self.duration <= 0:
            return
        if self.seconds >= self.duration:
            self.seconds = 0
            self._audio_ended = False
        self.audio.error = ""
        self.playing = True
        self._last_time = self.clock()
        self._audio_seconds, self._audio_anchor = self.seconds, self._last_time
        self.sync_audio()
        if self.playing:
            self.timer.start()
        self.changed.emit()

    def pause(self) -> None:
        """Freeze the audition at its current local time without changing a scene playhead."""
        self.playing = False
        self.timer.stop()
        if self.audio.player is not None:
            self.sync_audio()
        self.changed.emit()

    def stop(self) -> None:
        """Stop local audio and return its preview playhead to zero."""
        self.seconds = 0
        self._audio_ended = False
        self.pause()

    def seek(self, seconds: float) -> None:
        """Pause and scrub the preview range in source-relative seconds."""
        self.seconds = max(0, min(self.duration, seconds))
        self._audio_ended = self.seconds >= self.audio_duration
        self.pause()

    def tick(self) -> None:
        """Follow the audio device's clock without repeatedly seeking or restarting its decoder."""
        if not self.playing:
            return
        now = self.clock()
        player = self.audio.player
        if self.asset_id and not self._audio_ended and player is not None:
            if (
                player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
                and player.mediaStatus() != QMediaPlayer.MediaStatus.StalledMedia
            ):
                self.seconds = min(
                    self.audio_duration, self._audio_seconds + max(0, now - self._audio_anchor)
                )
        else:
            self.seconds = min(self.duration, self.seconds + max(0, now - self._last_time))
        self._last_time = now
        if self.seconds >= self.duration and (not self.asset_id or self._audio_ended):
            self.playing = False
            self.timer.stop()
        if self.audio.error:
            self.playing = False
            self.timer.stop()
        self.changed.emit()

    def sync_audio(self) -> None:
        """Apply explicit play/pause/seek commands; periodic visual updates never call this."""
        device = self.output_device()
        if self.asset_id and device.isNull():
            self.audio.error = (
                "No audio output is available. Choose a connected speaker or headset."
            )
            self.playing = False
            self.timer.stop()
            return
        position = (
            AudioPosition(self.asset_id, self.seconds, self.audio_duration, self.gain, self.muted)
            if self.asset_id
            else None
        )
        previous = self.audio.player
        self._pending_seek = True
        self._audio_seconds, self._audio_anchor = self.seconds, self.clock()
        self.audio.sync_position(self.document, position, self.playing, 1)
        player = self.audio.player
        if player is not None and player is not previous:
            player.mediaStatusChanged.disconnect(self.audio.ready)
            player.mediaStatusChanged.connect(self.media_status)
            player.positionChanged.connect(self.audio_position)
            player.errorOccurred.connect(lambda *_: self.changed.emit())
        if self.audio.output is not None:
            self.audio.output.setDevice(device)
        if player is not None and player.mediaStatus() in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        ):
            self._pending_seek = False

    def audio_position(self, milliseconds: int) -> None:
        """Anchor smooth portrait timing to actual decoded playback positions."""
        self._audio_seconds, self._audio_anchor = milliseconds / 1000, self.clock()

    def media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        """Restore initial asynchronous seeks once and finish only after audio really drains."""
        player = self.audio.player
        if player is None:
            return
        if self._pending_seek and status in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        ):
            self._pending_seek = False
            player.setPosition(round(self.seconds * 1000))
            if self.playing:
                player.play()
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._audio_ended = True
            self.audio.wanted_playing = False
            self.seconds, self._last_time = self.audio_duration, self.clock()
            if self.duration <= self.audio_duration:
                self.playing = False
                self.timer.stop()
            self.changed.emit()

    def close(self) -> None:
        """Stop and release the buffered decoder before the owning dialog disappears."""
        self.stop()
        self.audio.sync_position(None, None, False, 1)
        if self.audio.player is not None:
            self.audio.player.setSource(QUrl())
        if self.audio.buffer is not None:
            self.audio.buffer.close()
