"""Normalized editable transition graphs shared by playback, previews and timeline thumbnails."""

import math
from bisect import bisect_right
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from rigora.domain.project import ProjectError


@dataclass(frozen=True)
class TransitionCurve:
    """Time-ordered progress dots; endpoints stay fixed while interior values may overshoot."""

    points: tuple[tuple[float, float], ...] = ((0.0, 0.0), (1.0, 1.0))
    smooth: bool = False

    def __post_init__(self) -> None:
        """Bound graph complexity and require finite, strictly increasing normalized times."""
        if not 2 <= len(self.points) <= 257 or type(self.smooth) is not bool:
            raise ProjectError("Transition graphs require 2–257 dots and a smooth flag.")
        if self.points[0] != (0, 0) or self.points[-1] != (1, 1):
            raise ProjectError("Transition graph endpoints must be (0, 0) and (1, 1).")
        previous = -1.0
        for x, y in self.points:
            if (
                type(x) not in (int, float)
                or type(y) not in (int, float)
                or not previous < x <= 1
                or not -4 <= y <= 5
                or (previous >= 0 and x - previous < 1e-6)
                or not math.isfinite(x)
                or not math.isfinite(y)
            ):
                raise ProjectError("Graph dots need increasing times in 0–1 and values in −4–5.")
            previous = x

    @classmethod
    def from_data(cls, data: Any) -> "TransitionCurve":
        """Read bounded JSON metadata without executing or accepting unknown graph fields."""
        if not isinstance(data, Mapping) or set(data) != {"points", "smooth"}:
            raise ProjectError("Invalid transition graph data.")
        raw = data["points"]
        if not isinstance(raw, (tuple, list)) or not 2 <= len(raw) <= 257:
            raise ProjectError("Transition graphs require 2–257 dots.")
        if any(not isinstance(p, (tuple, list)) or len(p) != 2 for p in raw):
            raise ProjectError("Each graph dot requires time and progress.")
        return cls(tuple((p[0], p[1]) for p in raw), data["smooth"])

    def to_data(self) -> dict[str, Any]:
        """Return portable metadata stored on the outgoing key, independent of span duration."""
        return {"points": [list(p) for p in self.points], "smooth": self.smooth}

    def sample(self, time: float) -> float:
        """Evaluate a polyline or cubic Hermite graph, holding its exact endpoint values."""
        if time <= 0:
            return 0.0
        if time >= 1:
            return 1.0
        i = bisect_right(self.points, (time, math.inf)) - 1
        x, y = self.points[i]
        end, value = self.points[i + 1]
        t = (time - x) / (end - x)
        if not self.smooth:
            return y + (value - y) * t
        before = self.points[max(0, i - 1)]
        after = self.points[min(len(self.points) - 1, i + 2)]
        left = (value - before[1]) / (end - before[0])
        right = (after[1] - y) / (after[0] - x)
        return (
            (2 * t**3 - 3 * t**2 + 1) * y
            + (t**3 - 2 * t**2 + t) * (end - x) * left
            + (-2 * t**3 + 3 * t**2) * value
            + (t**3 - t**2) * (end - x) * right
        )

    def reversed(self) -> "TransitionCurve":
        """Reverse temporal progress while retaining normalized start/end values."""
        return TransitionCurve(tuple((1 - x, 1 - y) for x, y in reversed(self.points)), self.smooth)

    def repeated(self, count: int) -> "TransitionCurve":
        """Repeat easing in equal time/progress sections without resetting the animated pose."""
        if not 1 <= count <= 8 or (len(self.points) - 1) * count + 1 > 257:
            raise ProjectError("Repeat 1–8 sections with at most 257 total dots.")
        return TransitionCurve(
            tuple(
                ((x + section) / count, (y + section) / count)
                for section in range(count)
                for x, y in self.points[:-1]
            )
            + ((1.0, 1.0),),
            self.smooth,
        )


def _bounce(time: float) -> float:
    """Evaluate an original piecewise parabolic settling bounce in normalized progress."""
    if time < 1 / 2.75:
        return 7.5625 * time * time
    if time < 2 / 2.75:
        return 7.5625 * (time - 1.5 / 2.75) ** 2 + 0.75
    if time < 2.5 / 2.75:
        return 7.5625 * (time - 2.25 / 2.75) ** 2 + 0.9375
    return 7.5625 * (time - 2.625 / 2.75) ** 2 + 0.984375


def curve_presets() -> dict[str, TransitionCurve]:
    """Provide 24 original sampled math presets; no external motion assets are required."""
    result = {"Linear": TransitionCurve()}
    for name, function in (
        ("Quadratic", lambda t: t * t),
        ("Cubic", lambda t: t**3),
        ("Quartic", lambda t: t**4),
        ("Sine", lambda t: 1 - math.cos(t * math.pi / 2)),
        ("Exponential", lambda t: (2 ** (10 * t) - 1) / 1023),
        ("Back", lambda t: 2.70158 * t**3 - 1.70158 * t**2),
        ("Bounce", lambda t: 1 - _bounce(1 - t)),
    ):
        for mode in ("in", "out", "in-out"):
            points = []
            for i in range(33):
                t = i / 32
                value = (
                    function(t)
                    if mode == "in"
                    else 1 - function(1 - t)
                    if mode == "out"
                    else function(2 * t) / 2
                    if t < 0.5
                    else 1 - function(2 - 2 * t) / 2
                )
                points.append((t, value))
            points[0], points[-1] = (0.0, 0.0), (1.0, 1.0)
            result[f"{name} ease {mode}"] = TransitionCurve(tuple(points))
    for name, sign in (("Spring settle", 1), ("Anticipate spring", -1)):
        spring_points = tuple(
            (i / 64, i / 64 + sign * math.sin(i / 64 * math.pi * 6) * (1 - i / 64) * i / 64)
            for i in range(65)
        )
        result[name] = TransitionCurve(spring_points)
    return result
