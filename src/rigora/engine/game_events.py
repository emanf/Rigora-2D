"""Typed data-only animation events, arranged-source timing and deterministic interval delivery."""

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from rigora.domain.entities import AnimationClip, Marker
from rigora.domain.project import Scene
from rigora.domain.validation import ProjectError, json_copy
from rigora.engine.motion_layers import influence, ordered_layers

EVENT_TYPES = ("custom", "footstep", "sound", "hit", "spawn", "despawn", "signal")


def event_data(kind: str, payload: Any) -> dict[str, Any]:
    """Validate a bounded JSON object; events never contain executable code."""
    payload = json_copy(payload)
    if kind not in EVENT_TYPES or not isinstance(payload, dict):
        raise ProjectError("Choose a supported event type and a JSON object payload.")
    if len(json.dumps(payload).encode()) > 16384:
        raise ProjectError("Game event payloads are limited to 16 KiB.")
    return {"type": kind, "payload": payload}


@dataclass(frozen=True)
class GameEvent:
    """One event occurrence in scene frames, carrying only user-authored typed data."""

    id: str
    name: str
    frame: float
    kind: str
    payload: Mapping[str, Any]
    target: str = ""

    def to_dict(self, *, start: float = 0, fps: float = 24) -> dict[str, Any]:
        """Serialize timing relative to a sampled output range without changing source frames."""
        return {
            "id": self.id,
            "name": self.name,
            "frame": self.frame,
            "seconds": (self.frame - start) / fps,
            "type": self.kind,
            "payload": json_copy(self.payload),
            "target": self.target,
        }


def scene_events(scene: Scene, clip: AnimationClip | None) -> tuple[GameEvent, ...]:
    """Resolve local markers and reusable action events with speed, repeats and layer mute/solo."""
    if clip is None:
        return ()
    timelines = {t.id: t for t in scene.timelines}
    timeline = timelines[clip.timeline_id]
    output = []

    def append(marker: Marker, frame: float, identity: str, target: str = "") -> None:
        data = marker.extra.get("game_event")
        if data is not None and not isinstance(data, Mapping):
            raise ProjectError("Game event metadata must be a typed JSON object.")
        if data and clip.in_frame <= frame <= clip.out_frame:
            valid = event_data(data.get("type", "custom"), data.get("payload", {}))
            output.append(
                GameEvent(identity, marker.name, frame, valid["type"], valid["payload"], target)
            )
            if len(output) > 4096:
                raise ProjectError("A clip may resolve at most 4096 game event occurrences.")

    for marker in timeline.markers:
        append(marker, marker.frame, marker.id)
    windows = {
        t.extra["motion_window"]["id"]: t.extra["motion_window"]
        for t in ordered_layers(timeline.tracks)
        if t.extra.get("motion_window")
    }
    clips = {c.id: c for c in scene.clips}
    for key, window in windows.items():
        source = clips.get(window["source"])
        if source is None:
            continue
        if not any(m.extra.get("game_event") for m in timelines[source.timeline_id].markers):
            continue
        span = window["source_end"] - window["source_start"]
        offset, speed = window.get("source_offset", 0), window["speed"]
        repeats = window.get("repeat") and span > 0
        count = (
            math.ceil(((window["end"] - window["start"]) * speed + abs(offset)) / span) + 2
            if repeats
            else 1
        )
        if count > 4098:
            raise ProjectError("Reduce source repeats to stay within the event sampling budget.")
        first = math.floor(offset / span) if repeats else 0
        for cycle in range(first, first + count):
            for marker in timelines[source.timeline_id].markers:
                if repeats and marker.frame >= window["source_end"]:
                    continue
                frame = (
                    window["start"]
                    + (marker.frame - window["source_start"] - offset + cycle * span) / speed
                )
                if influence(window, frame) > 0:
                    append(marker, frame, f"{key}:{marker.id}:{cycle}", window["character"])
    return tuple(sorted(output, key=lambda e: (e.frame, e.id)))


def crossed_events(
    events: tuple[GameEvent, ...],
    previous: float,
    candidate: float,
    *,
    start: float,
    duration: float,
    loop: bool,
) -> tuple[GameEvent, ...]:
    """Deliver each occurrence in (previous, candidate], preserving loop order."""
    output = []
    loops = math.ceil(max(0, candidate - start) / duration) if loop and duration > 0 else 0
    if loops > 4096:
        raise ProjectError("Playback step exceeds the game-event loop budget.")
    for cycle in range(loops + 1):
        for event in events:
            at = event.frame + cycle * duration
            if previous < at <= candidate:
                output.append(event)
                if len(output) > 4096:
                    raise ProjectError("Playback step exceeds the game-event delivery budget.")
    return tuple(output)
