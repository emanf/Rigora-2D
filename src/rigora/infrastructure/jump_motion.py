"""Small cached CC0 jump references sampled into normalized, neutral-ended 2D trajectories."""

import json
from functools import lru_cache

from rigora.resources import asset_path


@lru_cache(maxsize=1)
def clips() -> dict[str, dict[str, list[float]]]:
    """Load numeric short/long jumps once; source meshes and textures are not runtime inputs."""
    data = json.loads(asset_path("motions/kaykit-jump/jump.json").read_text(encoding="utf-8"))
    return {name: record["channels"] for name, record in data["clips"].items()}


def jump_sample(action: str, phase: float) -> dict[str, float]:
    """Return height/ankle deltas from neutral, removing small source endpoint drift."""
    data = clips()["Jump_Full_Long" if action == "High jump" else "Jump_Full_Short"]
    t = min(1.0, max(0.0, phase))
    position = t * (len(data["height"]) - 1)
    index, u = int(position), position % 1
    result = {}
    for key, values in data.items():
        n = len(values)
        a, b, c, d = (
            values[max(0, min(n - 1, i))] for i in (index - 1, index, index + 1, index + 2)
        )
        value = 0.5 * (
            2 * b
            + (c - a) * u
            + (2 * a - 5 * b + 4 * c - d) * u * u
            + (-a + 3 * b - 3 * c + d) * u * u * u
        )
        result[key] = value - values[0] - (values[-1] - values[0]) * t * t * (3 - 2 * t)
    for side in ("r", "l"):
        result["lift." + side] = result["height"] - result["foot." + side + ".y"]
    return result
