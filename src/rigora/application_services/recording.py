"""Bounded PCM recording assembly shared by desktop device capture and headless clients."""

import io
import wave

from rigora.domain.project import ProjectError


class PcmRecording:
    """Accumulate interleaved signed 16-bit PCM without mutating a document until publication."""

    def __init__(self, rate: int = 16000, channels: int = 1) -> None:
        """Validate device format before accepting any sample data."""
        if (
            type(rate) is not int
            or not 8000 <= rate <= 192000
            or type(channels) is not int
            or channels not in (1, 2)
        ):
            raise ProjectError("Recording requires 8–192 kHz mono/stereo signed 16-bit PCM.")
        self.rate, self.channels = rate, channels
        self.data = bytearray()
        self.paused = False
        self.limit = min(16 * 1024 * 1024 - 64, rate * channels * 2 * 1800)

    @property
    def seconds(self) -> float:
        """Return completed sample duration, ignoring an incomplete final sample fragment."""
        return (len(self.data) // (self.channels * 2)) / self.rate

    def append(self, data: bytes) -> None:
        """Accept arbitrary device chunk boundaries and reject overflow before changing data."""
        if self.paused:
            return
        if len(self.data) + len(data) > self.limit:
            raise ProjectError("Recording reached its 16 MiB / 30-minute limit. Stop and save it.")
        self.data.extend(data)

    def wav(self) -> bytes:
        """Encode completed samples as WAV, retaining the capture buffer for retry."""
        size = len(self.data) // (self.channels * 2) * self.channels * 2
        if size == 0:
            raise ProjectError("No audio samples were recorded.")
        output = io.BytesIO()
        with wave.open(output, "wb") as audio:
            audio.setparams((self.channels, 2, self.rate, 0, "NONE", "not compressed"))
            audio.writeframes(self.data[:size])
        return output.getvalue()
