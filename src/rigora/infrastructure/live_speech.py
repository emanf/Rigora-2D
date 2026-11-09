"""Incremental, offline phone decoding from owned PCM bytes; never opens a microphone."""

import math
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rigora.application_services.facial import viseme
from rigora.domain.project import ProjectError


@dataclass(frozen=True)
class SpeechSample:
    """Latest provisional mouth and full editable cue snapshot in capture-relative seconds."""

    seconds: float
    mouth: str
    cues: tuple[tuple[float, str], ...]
    energy: float = 0


class LivePhonemes:
    """Own one optional PocketSphinx decoder on its worker thread until explicit close."""

    def __init__(self, rate: int) -> None:
        """Load bundled US-English acoustic/phone models without network or device access."""
        if rate not in (16000, 48000):
            raise ProjectError("Live phoneme capture requires mono 16-bit PCM at 16 or 48 kHz.")
        try:
            from pocketsphinx import Decoder, get_model_path
        except ImportError as error:
            raise ProjectError(
                "The built-in speech engine is missing. Repair the Rigora installation."
            ) from error
        model = Path(get_model_path()) / "en-us"
        self.decoder: Any = Decoder(
            hmm=str(model / "en-us"),
            allphone=str(model / "en-us-phone.lm.bin"),
            lm=None,
            dict=None,
            samprate=rate,
            loglevel="ERROR",
        )
        self.rate, self.samples, self.offset = rate, 0, 0.0
        self.fragment = b""
        self.closed = False
        self.prefix: tuple[tuple[float, str], ...] = ()
        self.latest = SpeechSample(0, "Rest", ((0, "Rest"),))
        self.decoder.start_utt()

    def feed(self, data: bytes) -> SpeechSample:
        """Decode at most half a second, retaining complete samples and bounded utterances."""
        if self.closed or len(data) > self.rate:
            raise ProjectError("Feed an open speech decoder at most half a second per chunk.")
        block = self.fragment + data
        size = len(block) // 2 * 2
        block, self.fragment = block[:size], block[size:]
        if not block:
            return self.latest
        self.decoder.process_raw(block, False, False)
        self.samples += size // 2
        values = array("h", block)
        energy = math.sqrt(sum(value * value for value in values) / len(values)) / 32768
        self.latest = self._sample(energy)
        # Reset decoder history every ten seconds; PCM and committed cues retain global time.
        if self.samples / self.rate - self.offset >= 10:
            self.decoder.end_utt()
            self.latest = self._sample(energy)
            self.prefix = self.latest.cues
            self.offset = self.samples / self.rate
            self.decoder.start_utt()
        return self.latest

    def _sample(self, energy: float) -> SpeechSample:
        """Convert provisional phoneme intervals to existing editable mouth names."""
        seconds = self.samples / self.rate
        events = dict(self.prefix)
        events.setdefault(0, "Rest")
        segments = self.decoder.seg()
        if segments:
            for segment in segments:
                shape = viseme(segment.word)
                at = min(seconds, self.offset + segment.start_frame / 100)
                events[at] = shape
        cues = tuple(sorted(events.items()))
        if len(cues) > 4998:
            raise ProjectError("Live speech reached its 5000-cue limit. Stop and keep the take.")
        mouth = cues[-1][1] if energy >= 0.006 else "Rest"
        return SpeechSample(seconds, mouth, cues, energy)

    def close(self) -> SpeechSample:
        """Flush final phoneme intervals once and return to Rest at the captured endpoint."""
        if not self.closed:
            self.decoder.end_utt()
            self.closed = True
            final = self._sample(self.latest.energy)
            events = dict(final.cues)
            events[final.seconds] = "Rest"
            self.latest = SpeechSample(final.seconds, "Rest", tuple(sorted(events.items())))
        return self.latest
