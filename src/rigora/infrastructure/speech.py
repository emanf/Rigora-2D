"""Bounded local Rhubarb integration; no network calls or speech data uploads."""

import io
import json
import math
import struct
import subprocess
import tempfile
import threading
import time
import wave
from collections.abc import Iterator
from pathlib import Path

from rigora.domain.project import ProjectError
from rigora.engine.sampling import number
from rigora.infrastructure.media_import import audio_metadata

RHUBARB_SHAPES = {
    "A": "MBP",
    "B": "E",
    "C": "E",
    "D": "AI",
    "E": "O",
    "F": "WQ",
    "G": "FV",
    "H": "L",
    "X": "Rest",
}


def mono_pcm_chunks(data: bytes, rate: int = 16000) -> Iterator[bytes]:
    """Stream bounded 16-bit mono PCM blocks at the acoustic model's sample rate.

    Original WAV channels and integer sample widths are downmixed and linearly
    resampled. The common mono 16 kHz path copies source frames without conversion.
    """
    with wave.open(io.BytesIO(data)) as source:
        channels, width, native = (
            source.getnchannels(),
            source.getsampwidth(),
            source.getframerate(),
        )
        count = source.getnframes()
        if (channels, width, native) == (1, 2, rate):
            while block := source.readframes(rate // 4):
                yield block
            return
        stride = channels * width
        total = math.ceil(count * rate / native)
        for first in range(0, total, rate // 4):
            end = min(total, first + rate // 4)
            start_frame = min(count - 1, first * native // rate)
            end_frame = min(count, math.ceil(end * native / rate) + 1)
            source.setpos(start_frame)
            raw = source.readframes(end_frame - start_frame)

            def sample(index: int, raw: bytes = raw, start_frame: int = start_frame) -> float:
                """Read normalized native samples without allocating a decoded whole-file copy."""
                offset = (min(count - 1, index) - start_frame) * stride
                value = (
                    sum(
                        int.from_bytes(
                            raw[offset + c * width : offset + (c + 1) * width],
                            "little",
                            signed=width != 1,
                        )
                        for c in range(channels)
                    )
                    / channels
                )
                return float((value - 128 if width == 1 else value) / 2 ** (width * 8 - 1))

            values = []
            for index in range(first, end):
                at = index * native / rate
                left, fraction = int(at), at - int(at)
                value = sample(left) * (1 - fraction) + sample(left + 1) * fraction
                values.append(max(-32768, min(32767, round(value * 32767))))
            yield struct.pack("<" + "h" * len(values), *values)


def analyze_builtin_speech(
    data: bytes, *, cancel: threading.Event | None = None
) -> tuple[tuple[float, str], ...]:
    """Estimate editable English visemes offline using the bundled acoustic/phone model."""
    from rigora.infrastructure.live_speech import LivePhonemes

    if len(data) > 16 * 1024 * 1024:
        raise ProjectError("Speech analysis supports WAV sources up to 16 MiB.")
    duration = float(audio_metadata(data)["duration_seconds"])
    if duration <= 0:
        raise ProjectError("Choose a nonempty WAV recording.")
    cancelled = cancel or threading.Event()
    deadline = time.monotonic() + 300

    def check() -> None:
        """Bound worker time and honor cancellation between small decoder blocks."""
        if cancelled.is_set():
            raise ProjectError("Speech analysis cancelled; no keys changed.")
        if time.monotonic() > deadline:
            raise ProjectError("Speech analysis exceeded its five-minute limit.")

    check()
    decoder = LivePhonemes(16000)
    try:
        for block in mono_pcm_chunks(data):
            check()
            decoder.feed(block)
        check()
        values = dict(decoder.close().cues)
        values = {min(t, duration): shape for t, shape in values.items()}
        values[duration] = "Rest"
        return tuple(sorted(values.items()))
    finally:
        decoder.close()


def read_speech_cues(data: bytes, duration: float) -> tuple[tuple[float, str], ...]:
    """Validate ordered nonoverlapping Rhubarb intervals and fill silence between them."""
    if len(data) > 2 * 1024 * 1024:
        raise ProjectError("Speech cue output exceeds 2 MiB.")
    try:
        payload = json.loads(data)
        rows = payload["mouthCues"]
        if not isinstance(rows, list) or not 1 <= len(rows) <= 4998:
            raise ValueError("cue count")
        events: dict[float, str] = {0: "Rest"}
        previous = 0.0
        for row in rows:
            start, end = number(row["start"]), number(row["end"])
            if not previous <= start < end <= duration + 0.05:
                raise ValueError("cue interval")
            events[min(start, duration)] = RHUBARB_SHAPES[row["value"]]
            events[min(end, duration)] = "Rest"
            previous = end
        events[duration] = "Rest"
        if len(events) > 5000:
            raise ValueError("too many mouth changes; split the recording")
        return tuple(sorted(events.items()))
    except (KeyError, TypeError, ValueError, ProjectError) as error:
        raise ProjectError("Speech analysis returned invalid mouth cue intervals.") from error


def analyze_speech(
    data: bytes,
    executable: Path,
    *,
    transcript: str = "",
    recognizer: str = "phonetic",
    cancel: threading.Event | None = None,
) -> tuple[tuple[float, str], ...]:
    """Run a user-selected Rhubarb binary on private WAV bytes with timeout and cancellation.

    The phonetic recognizer supports languages beyond English. PocketSphinx is an
    explicit English option; a transcript can improve recognition but is never uploaded.
    """
    duration = float(audio_metadata(data)["duration_seconds"])
    if not executable.is_file():
        raise ProjectError("Choose an installed Rhubarb Lip Sync executable first.")
    if recognizer not in ("phonetic", "pocketSphinx") or len(transcript) > 100000:
        raise ProjectError(
            "Choose a supported recognizer and a transcript below 100,000 characters."
        )
    cancelled = cancel or threading.Event()
    if cancelled.is_set():
        raise ProjectError("Speech analysis cancelled; no keys changed.")
    with tempfile.TemporaryDirectory(prefix="rigora-speech-") as folder:
        root = Path(folder)
        source, output = root / "voice.wav", root / "cues.json"
        source.write_bytes(data)
        args = [
            str(executable.resolve()),
            "-f",
            "json",
            "-r",
            recognizer,
            "--extendedShapes",
            "GHX",
            "--threads",
            "2",
            "-o",
            str(output),
        ]
        if transcript.strip():
            script = root / "dialog.txt"
            script.write_text(transcript, encoding="utf-8")
            args.extend(("-d", str(script)))
        args.append(str(source))
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=errors,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            deadline = time.monotonic() + 300
            try:
                while process.poll() is None:
                    if cancelled.wait(0.05):
                        raise ProjectError("Speech analysis cancelled; no keys changed.")
                    if time.monotonic() > deadline:
                        raise ProjectError("Speech analysis exceeded its five-minute limit.")
                if process.returncode or not output.is_file():
                    errors.seek(0)
                    raise ProjectError(
                        "Rhubarb analysis failed: " + errors.read(2048).decode(errors="replace")
                    )
                if output.stat().st_size > 2 * 1024 * 1024:
                    raise ProjectError("Speech cue output exceeds 2 MiB.")
                return read_speech_cues(output.read_bytes(), duration)
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()
