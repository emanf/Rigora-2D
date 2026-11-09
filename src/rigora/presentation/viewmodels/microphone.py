"""Explicit-start microphone capture over Qt devices and a Qt-free bounded PCM session."""

from PySide6.QtCore import QIODevice, QObject, Signal
from PySide6.QtMultimedia import QAudioDevice, QAudioFormat, QAudioSource, QMediaDevices, QtAudio

from rigora.application_services.recording import PcmRecording
from rigora.domain.project import ProjectError


class MicrophoneCapture(QObject):
    """Own a selected input device only between explicit start and stop actions."""

    changed = Signal()
    samples = Signal(bytes, int)

    def __init__(self, parent: QObject) -> None:
        """Initialize dormant capture state; device enumeration does not start recording."""
        super().__init__(parent)
        self.source: QAudioSource | None = None
        self.device: QIODevice | None = None
        self.recording: PcmRecording | None = None
        self.error = ""
        self.active = False

    def start(self, device_id: str = "") -> None:
        """Start one chosen mono PCM input after the caller explicitly requests recording."""
        if self.active:
            raise ProjectError("Stop the current recording before starting another.")
        if self.recording and self.recording.data:
            raise ProjectError("Keep or discard the previous recording before starting another.")
        devices = QMediaDevices.audioInputs()
        if device_id and not any(bytes(d.id().data()).hex() == device_id for d in devices):
            raise ProjectError("The selected microphone is unavailable. Choose an input again.")
        device = next(
            (d for d in devices if bytes(d.id().data()).hex() == device_id),
            QMediaDevices.defaultAudioInput(),
        )
        if device.isNull():
            raise ProjectError("No microphone is available. Connect an audio input first.")
        audio_format = QAudioFormat()
        audio_format.setChannelCount(1)
        audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        rate = next(
            (
                rate
                for rate in (16000, 48000, device.preferredFormat().sampleRate())
                if self.supports(device, audio_format, rate)
            ),
            None,
        )
        if rate is None:
            raise ProjectError("The chosen microphone does not expose supported mono 16-bit PCM.")
        audio_format.setSampleRate(rate)
        self.discard()
        self.recording = PcmRecording(rate)
        self.source = QAudioSource(device, audio_format, self)
        self.device = self.source.start()
        if self.device is None or self.source.error() != QtAudio.Error.NoError:
            self.discard()
            raise ProjectError(
                "Could not open the selected microphone. Check OS device access and input settings."
            )
        self.device.readyRead.connect(self.read)
        self.source.stateChanged.connect(self.state_changed)
        self.active, self.error = True, ""
        self.changed.emit()

    @staticmethod
    def supports(device: QAudioDevice, audio_format: QAudioFormat, rate: int) -> bool:
        """Probe one format without opening its device."""
        audio_format.setSampleRate(rate)
        return device.isFormatSupported(audio_format)

    def read(self) -> None:
        """Drain ready PCM chunks and stop safely at the bounded recording limit."""
        if self.device is None or self.recording is None:
            return
        try:
            data = bytes(self.device.readAll().data())
            self.recording.append(data)
            if data:
                self.samples.emit(data, self.recording.rate)
        except ProjectError as error:
            self.error = str(error)
            self.stop_device()
        self.changed.emit()

    def state_changed(self, state: QtAudio.State) -> None:
        """Surface unplugging/device failures without publishing partial project edits."""
        if (
            self.active
            and state == QtAudio.State.StoppedState
            and self.source
            and self.source.error() != QtAudio.Error.NoError
        ):
            self.error = (
                "Microphone capture stopped. Recorded samples are retained; stop to keep them."
            )
            self.active = False
            self.changed.emit()

    def stop_device(self) -> None:
        """Release the input while retaining sample bytes for a safe save/retry."""
        self.active = False
        if self.source:
            self.source.stop()
            self.source.deleteLater()
        self.source, self.device = None, None

    def finish(self) -> bytes:
        """Stop device capture before returning an owned portable recording."""
        if self.active:
            self.read()
        self.stop_device()
        if self.recording is None:
            raise ProjectError("Start a microphone recording first.")
        return self.recording.wav()

    def discard(self) -> None:
        """Release input and drop uncommitted samples on discard or dialog close."""
        self.stop_device()
        self.recording = None
        self.error = ""
