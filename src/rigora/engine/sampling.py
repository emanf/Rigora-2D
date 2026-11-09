"""Compiled numeric tracks with deterministic, indexed interpolation."""

import math
from bisect import bisect_right
from collections.abc import Callable, Mapping
from typing import cast

from rigora.domain.entities import Track
from rigora.domain.validation import ProjectError
from rigora.engine.transition_curves import TransitionCurve

type TrackSampler = Callable[[Track, float], float | None]


class EvaluationError(ProjectError):
    """An unsupported or numerically invalid animation evaluation request."""


def number(value: object, label: str = "Animation value") -> float:
    """Require a finite numeric scalar without accepting booleans or overflowing integers."""
    if type(value) not in (int, float):
        raise EvaluationError(f"{label} must be a finite numeric scalar.")
    try:
        result = float(cast(float | int, value))
    except (ValueError, OverflowError) as error:
        raise EvaluationError(f"{label} exceeds the finite numeric range.") from error
    if not math.isfinite(result):
        raise EvaluationError(f"{label} must be finite.")
    return result


def _cubic(t: float, a: float, b: float, c: float, d: float) -> float:
    """Evaluate a cubic in Bernstein form without overflowing intermediate coefficients."""
    u = 1.0 - t
    return u * u * u * a + (3 * u * u * t) * b + (3 * u * t * t) * c + t * t * t * d


class CompiledTrack:
    """Preindex immutable keys and validate controls once, without caching sampled frames."""

    def __init__(self, track: Track, samplers: Mapping[str, TrackSampler] | None = None) -> None:
        """Prepare finite scalar keys and monotone Bézier time controls for one track."""
        self.source = track
        window = track.extra.get("motion_window")
        self.window = window
        if window is not None:
            if not isinstance(window, Mapping):
                raise EvaluationError("Motion windows must contain timing settings.")
            start, end, speed = (number(window[k]) for k in ("start", "end", "speed"))
            if (
                start < 0
                or end <= start
                or speed <= 0
                or number(window["source_end"]) < number(window["source_start"])
            ):
                raise EvaluationError("Motion window timing is invalid.")
        cycle = track.extra.get("cycle")
        self.cycle: tuple[float, float] | None = None
        if cycle is not None:
            if not isinstance(cycle, (tuple, list)) or len(cycle) != 2:
                raise EvaluationError("Track cycles require a start and end frame.")
            begin, end = number(cycle[0]), number(cycle[1])
            if end <= begin:
                raise EvaluationError("Track cycle end must follow its start.")
            self.cycle = begin, end
        sampler_id = track.extra.get("sampler")
        self.sampler = (samplers or {}).get(str(sampler_id)) if sampler_id is not None else None
        if sampler_id is not None and self.sampler is None:
            raise EvaluationError(f"Missing numeric track sampler: {sampler_id}.")
        self.frames = tuple(key.frame for key in track.keyframes)
        self.values = tuple(number(key.value, f"{track.name} key value") for key in track.keyframes)
        self.transitions = tuple(
            TransitionCurve.from_data(key.extra["transition_curve"])
            if "transition_curve" in key.extra
            else None
            for key in track.keyframes
        )
        curves: list[tuple[float, float, float, float] | None] = []
        for index, (left, right) in enumerate(
            zip(track.keyframes, track.keyframes[1:], strict=False)
        ):
            if left.interpolation != "bezier":
                curves.append(None)
                continue
            duration = right.frame - left.frame
            out = left.tangent_out or (duration / 3, 0.0)
            into = right.tangent_in or (-duration / 3, 0.0)
            x1, x2 = out[0] / duration, 1.0 + into[0] / duration
            if not (0 <= x1 <= 1 and 0 <= x2 <= 1 and x1 <= x2 + 1e-12):
                raise EvaluationError(
                    f"{track.name}: Bézier time handles must be ordered inside the segment."
                )
            x2 = max(x1, x2)
            y1 = number(self.values[index] + out[1], "Bézier outgoing control")
            y2 = number(self.values[index + 1] + into[1], "Bézier incoming control")
            curves.append((x1, x2, y1, y2))
        self.curves = tuple(curves)

    def weight_at(self, frame: float) -> float:
        """Combine source-track influence with the scene action's live fade envelope."""
        from rigora.engine.motion_layers import influence

        return self.source.weight * (influence(self.window, frame) if self.window else 1)

    def blend(
        self,
        current: float,
        sampled: float,
        base: float,
        frame: float,
        *,
        scale: bool = False,
        angle: bool = False,
    ) -> float:
        """Blend one channel; additive action layers store offsets relative to authored rest."""
        weight = self.weight_at(frame)
        mode = (
            self.window.get("blend", self.source.blend_mode)
            if self.window
            else self.source.blend_mode
        )
        if mode == "override":
            delta = sampled - current
            if angle and self.window:
                delta = (delta + 180) % 360 - 180
            return current + delta * weight
        if self.window and self.window.get("blend") == "additive":
            sampled = sampled / base if scale and abs(base) > 1e-10 else sampled - base
        return current * (1 - weight + sampled * weight) if scale else current + sampled * weight

    def sample(self, frame: float) -> float | None:
        """Sample independently; disabled lanes and inactive actions contribute nothing."""
        frame = number(frame, "Frame")
        if not self.source.evaluation_enabled:
            return None
        if self.window:
            window = self.window
            if self.weight_at(frame) <= 0:
                return None
            if frame < window["start"] or frame > window["end"]:
                return None
            frame = (
                window["source_start"]
                + window.get("source_offset", 0)
                + (frame - window["start"]) * window["speed"]
            )
            span = window["source_end"] - window["source_start"]
            if window.get("repeat") and span > 0:
                frame = window["source_start"] + (frame - window["source_start"]) % span
            else:
                frame = max(window["source_start"], min(window["source_end"], frame))
        if self.cycle and frame > self.cycle[1]:
            begin, end = self.cycle
            frame = begin + (frame - begin) % (end - begin)
        if self.sampler is not None:
            sampled = self.sampler(self.source, frame)
            return number(sampled, "Plugin track sample") if sampled is not None else None
        if not self.frames:
            return None
        index = bisect_right(self.frames, frame) - 1
        if index < 0:
            if self.source.extra.get("active_from_first_key"):
                return None
            return self.values[0]
        if index >= len(self.frames) - 1:
            return self.values[-1]
        if frame == self.frames[index]:
            return self.values[index]
        if self.source.keyframes[index].interpolation == "step":
            return self.values[index]
        t = (frame - self.frames[index]) / (self.frames[index + 1] - self.frames[index])
        left, right = self.values[index], self.values[index + 1]
        transition = self.transitions[index]
        if transition is not None:
            progress = transition.sample(t)
            return number((1 - progress) * left + progress * right, "Transition sample")
        curve = self.curves[index]
        if curve is None:
            return (1 - t) * left + t * right
        x1, x2, y1, y2 = curve
        if abs(x1 - 1 / 3) < 1e-15 and abs(x2 - 2 / 3) < 1e-15:
            return _cubic(t, left, y1, y2, right)
        low, high = 0.0, 1.0
        for _ in range(40):
            middle = (low + high) / 2
            if _cubic(middle, 0, x1, x2, 1) < t:
                low = middle
            else:
                high = middle
        return _cubic((low + high) / 2, left, y1, y2, right)
