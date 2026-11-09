"""Validated frame-source references shared by import, evaluation and project graph checks."""

import math
from collections.abc import Mapping
from typing import Any

from rigora.domain.validation import ProjectError, identifier


def validate_sequence(value: Any) -> Mapping[str, Any]:
    """Require a bounded immutable-compatible frame list and explicit playback timing."""
    if not isinstance(value, Mapping) or set(value) != {"assets", "fps", "start", "loop"}:
        raise ProjectError("Sprite sequence needs assets, fps, start and loop fields.")
    assets, fps, start = value["assets"], value["fps"], value["start"]
    if not isinstance(assets, (tuple, list)) or not 1 <= len(assets) <= 256:
        raise ProjectError("Sprite sequence requires 1–256 source asset IDs.")
    for asset in assets:
        identifier(asset)
    if (
        type(fps) not in (int, float)
        or not math.isfinite(fps)
        or not 0 < fps <= 240
        or type(start) not in (int, float)
        or not math.isfinite(start)
        or start < 0
        or type(value["loop"]) is not bool
    ):
        raise ProjectError("Sprite sequence timing is invalid.")
    return value


def frame_asset(sequence: Mapping[str, Any], frame: float, scene_fps: float) -> str:
    """Choose a deterministic source at any absolute frame, independently of playback history."""
    assets = sequence["assets"]
    index = math.floor(max(0, frame - sequence["start"]) * sequence["fps"] / scene_fps + 1e-9)
    index = index % len(assets) if sequence["loop"] else min(len(assets) - 1, index)
    result: str = assets[index]
    return result
