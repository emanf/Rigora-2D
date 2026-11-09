"""Bounded deterministic PCM mixing, shared trim/fade timing and streaming WAV output."""

import io
import math
import struct
import wave
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from rigora.domain.project import ProjectError
from rigora.engine.sampling import number


def track_state(
    track: Mapping[str, Any], frame: float, fps: float, duration: float
) -> tuple[float, float, float]:
    """Resolve source seconds, exclusive trim end and linear fade-adjusted gain at a scene frame."""
    trim_start, trim_end = (
        number(track.get("trim_start", 0)),
        number(track.get("trim_end", duration)),
    )
    start = number(track.get("start_frame", 0))
    rate = number(track.get("rate", 1))
    loop_frames = number(track.get("loop_frames", 0))
    loop_start = track.get("loop_start_frame")
    offset = number(track.get("source_offset", 0))
    end_frame = track.get("end_frame")
    if (
        not 0.05 <= rate <= 20
        or not 0 <= loop_frames <= 1e7
        or (end_frame is not None and not 0 <= number(end_frame) <= 1e7)
        or (loop_start is not None and not 0 <= number(loop_start) <= 1e7)
    ):
        raise ProjectError("Audio rate, loop period or end frame is outside its supported range.")
    origin = number(loop_start) if loop_start is not None else start
    sampled = origin + (frame - origin) % loop_frames if loop_frames and frame >= origin else frame
    elapsed = (sampled - start) / fps
    active = elapsed >= 0
    elapsed = elapsed * rate + offset
    length = trim_end - trim_start
    gain = number(track.get("gain", 1))
    fade_in, fade_out = number(track.get("fade_in", 0)), number(track.get("fade_out", 0))
    if not 0 <= trim_start < trim_end <= duration or not 0 <= gain <= 1:
        raise ProjectError("Audio trims must fit the source and volume must be 0–1.")
    if not 0 <= offset < length:
        raise ProjectError("Audio source advance must fit the trimmed source.")
    if min(fade_in, fade_out) < 0 or max(fade_in, fade_out) > length:
        raise ProjectError("Audio fades must fit the trimmed duration.")
    if end_frame is not None and frame >= end_frame:
        return trim_end, trim_end, 0
    envelope = min(
        1 if active else 0,
        elapsed / fade_in if fade_in else 1,
        (length - elapsed) / fade_out if fade_out else 1,
    )
    return trim_start + elapsed, trim_end, gain * max(0, envelope)


def write_mix(
    path: Path | io.BytesIO,
    sources: tuple[tuple[Mapping[str, Any], bytes], ...],
    *,
    start: float,
    duration: float,
    fps: float,
    cancelled: Callable[[], None] = lambda: None,
    rate: int = 48000,
) -> None:
    """Stream a stereo 16-bit mix in bounded blocks with linear resampling and clipping.

    Sources retain their native PCM channel count, width and rate. Mono is duplicated;
    sources with more than two channels are downmixed to mono. No audio device is used.
    """
    frames = math.ceil(duration * rate)
    if not 0 < frames * 4 <= 128 * 1024 * 1024:
        raise ProjectError("Mixed WAV output exceeds the 128 MiB audio budget.")
    decoded = []
    solo = any(t.get("solo") and not t.get("muted") for t, _ in sources)
    for track, data in sources:
        if track.get("muted") or solo and not track.get("solo"):
            continue
        with wave.open(io.BytesIO(data)) as source:
            width, channels, source_rate, count = (
                source.getsampwidth(),
                source.getnchannels(),
                source.getframerate(),
                source.getnframes(),
            )
            raw = source.readframes(count)
        decoded.append((track, raw, width, channels, source_rate, count))
    with wave.open(str(path) if isinstance(path, Path) else path, "wb") as target:
        target.setparams((2, 2, rate, frames, "NONE", "not compressed"))
        for first in range(0, frames, 2048):
            cancelled()
            output = [0.0] * (min(2048, frames - first) * 2)
            for track, raw, width, channels, source_rate, count in decoded:
                track_state(track, start, fps, count / source_rate)
                trim_start = track.get("trim_start", 0)
                trim_end = track.get("trim_end", count / source_rate)
                track_start = track.get("start_frame", 0) / fps
                fade_in, fade_out = track.get("fade_in", 0), track.get("fade_out", 0)
                length = trim_end - trim_start
                for i in range(len(output) // 2):
                    elapsed = start / fps + (first + i) / rate - track_start
                    seconds = trim_start + elapsed
                    gain = track.get("gain", 1) * max(
                        0,
                        min(
                            1,
                            elapsed / fade_in if fade_in else 1,
                            (length - elapsed) / fade_out if fade_out else 1,
                        ),
                    )
                    if (
                        track.get("rate", 1) != 1
                        or track.get("loop_frames")
                        or track.get("end_frame") is not None
                        or track.get("source_offset", 0)
                    ):
                        seconds, _, gain = track_state(
                            track, start + (first + i) / rate * fps, fps, count / source_rate
                        )
                    if seconds < trim_start or seconds >= trim_end or gain <= 0:
                        continue
                    at = seconds * source_rate
                    index, fraction = int(at), at - int(at)
                    for side in range(2):
                        values = []
                        for sample in (index, min(count - 1, index + 1)):
                            selected = (
                                range(channels) if channels > 2 else (min(side, channels - 1),)
                            )
                            value = 0.0
                            for channel in selected:
                                offset = (sample * channels + channel) * width
                                scalar = int.from_bytes(
                                    raw[offset : offset + width], "little", signed=width != 1
                                )
                                value += (scalar - 128 if width == 1 else scalar) / (
                                    2 ** (width * 8 - 1)
                                )
                            values.append(value / len(selected))
                        output[2 * i + side] += (
                            values[0] * (1 - fraction) + values[1] * fraction
                        ) * gain
            target.writeframesraw(
                struct.pack(
                    "<" + "h" * len(output),
                    *(max(-32768, min(32767, round(value * 32767))) for value in output),
                )
            )
