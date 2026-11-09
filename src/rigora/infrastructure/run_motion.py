"""Cached, periodic sampling of licensed run trajectories for proportion-aware 2D retargeting."""

import json
from dataclasses import dataclass
from functools import lru_cache

from rigora.resources import asset_path


@dataclass(frozen=True)
class RunStyle:
    """Own retargeting proportions and cadence for one distinct selectable run performance."""

    reference: str
    frames: int
    stride: float
    lift: float
    arms: float
    elbow: float
    lean: float
    bob: float = 0
    energy: float = 1


RUN_STYLES = {
    "Jog": RunStyle("Jog_Fwd_Loop", 32, 0.85, 0.82, 27, 88, 2, energy=0.85),
    "Sprint": RunStyle("Sprint_Loop", 20, 1.08, 1.12, 43, 102, 4.5),
    "Run alternate": RunStyle("Running_B", 32, 0.9, 0.95, 30, 82, 2.5),
    "Anime run": RunStyle("Sprint_Loop", 22, 1.04, 1.08, 8, 20, 5),
    "Bouncy run": RunStyle("base", 28, 0.94, 1.18, 43, 98, 1.5, bob=2.5, energy=1.15),
    "Heavy run": RunStyle("Running_B", 38, 0.82, 0.8, 23, 78, 3.2, bob=1, energy=0.9),
}


@lru_cache(maxsize=1)
def variant_channels() -> dict[str, dict[str, tuple[float, ...]]]:
    """Read all additional numeric references once, independently of preview frame changes."""
    record = json.loads(
        asset_path("motions/run-variants/variants.json").read_text(encoding="utf-8")
    )
    return {
        name: {key: tuple(values) for key, values in clip["channels"].items()}
        for name, clip in record["clips"].items()
    }


@lru_cache(maxsize=1)
def channels() -> dict[str, tuple[float, ...]]:
    """Read the small bundled numeric reference once; playback requires no model or network."""
    record = json.loads(asset_path("motions/kaykit-run/run.json").read_text(encoding="utf-8"))
    return {key: tuple(values) for key, values in record["channels"].items()}


def run_sample(phase: float, reference: str = "base") -> dict[str, float]:
    """Sample a seamless Catmull-Rom loop with matching boundary positions and velocities."""
    data = channels() if reference == "base" else variant_channels()[reference]
    count = len(data["height"])
    position = (phase % 1) * count
    index, t = int(position), position % 1
    result = {}
    for key, values in data.items():
        a, b, c, d = (values[i % count] for i in (index - 1, index, index + 1, index + 2))
        result[key] = 0.5 * (
            2 * b
            + (c - a) * t
            + (2 * a - 5 * b + 4 * c - d) * t * t
            + (-a + 3 * b - 3 * c + d) * t * t * t
        )
    return result
