"""Ordered action layers and time-varying influence shared by preview and offline evaluation."""

from collections.abc import Mapping
from typing import Any

from rigora.domain.entities import Track
from rigora.engine.sampling import EvaluationError, number


def influence(window: Mapping[str, Any], frame: float) -> float:
    """Return the bounded action envelope in scene frames, including mute and linear fades."""
    start, end = number(window["start"]), number(window["end"])
    weight = number(window.get("weight", 1))
    fade_in, fade_out = number(window.get("fade_in", 0)), number(window.get("fade_out", 0))
    if not 0 <= weight <= 1 or min(fade_in, fade_out) < 0 or max(fade_in, fade_out) > end - start:
        raise EvaluationError("Layer weight must be 0–1 and fades must fit the action duration.")
    if window.get("blend", "override") not in ("override", "additive"):
        raise EvaluationError("Choose Override or Additive layer blending.")
    if window.get("muted") or not start <= frame <= end:
        return 0
    return weight * min(
        1, (frame - start) / fade_in if fade_in else 1, (end - frame) / fade_out if fade_out else 1
    )


def ordered_layers(tracks: tuple[Track, ...]) -> tuple[Track, ...]:
    """Order actions below manual channels and resolve Solo independently for each character."""
    tracks = tuple(track for track in tracks if track.evaluation_enabled)
    solo = {
        t.extra["motion_window"]["character"]
        for t in tracks
        if t.extra.get("motion_window", {}).get("solo")
        and not t.extra["motion_window"].get("muted")
    }
    result = []
    for track in tracks:
        window = track.extra.get("motion_window")
        if window:
            influence(window, number(window["start"]))
            mask = window.get("mask", ())
            if mask and track.owner_id not in mask:
                continue
            if window.get("muted") or window["character"] in solo and not window.get("solo"):
                continue
        result.append(track)
    return tuple(
        sorted(
            result,
            key=lambda t: (
                0 if t.extra.get("motion_window") else 1,
                number(t.extra.get("motion_window", {}).get("layer", 0)),
            ),
        )
    )
