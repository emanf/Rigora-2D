"""Retiming shared by sprite, editable-rig and runtime event manifests."""

import json
from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from typing import Any

from rigora.application_services.documents import DocumentService
from rigora.domain.project import ProjectError


def exported_events(
    document: DocumentService, frames: Sequence[float], fps: float
) -> list[dict[str, Any]]:
    """Map occurrences through explicit output samples, retaining authored source frames.

    Intervals interpolate in output time, so sparse samples and speed changes do not
    leave callbacks timed against the original scene FPS. Single-frame output keeps
    only occurrences at that frame. Reverse segments emit crossed events in reverse
    source order; held samples do not repeat callbacks. Bound expanded occurrences
    independently from the number of authored markers.
    """
    if not frames:
        return []
    events = document.animation.runtime_events
    source_frames = [event.frame for event in events]
    output: list[dict[str, Any]] = []

    def append(index: int, seconds: float) -> None:
        """Serialize one occurrence without allowing retiming to expand unboundedly."""
        if len(output) >= 4096:
            raise ProjectError("Export supports at most 4096 event occurrences.")
        event = events[index]
        item = event.to_dict()
        item["seconds"] = seconds
        # Unity JsonUtility cannot deserialize arbitrary JSON objects into dictionaries.
        item["payload_json"] = json.dumps(item["payload"], allow_nan=False, separators=(",", ":"))
        output.append(item)

    for index in range(
        bisect_left(source_frames, frames[0]), bisect_right(source_frames, frames[0])
    ):
        append(index, 0.0)
    for segment, (a, b) in enumerate(zip(frames, frames[1:], strict=False)):
        if a == b:
            continue
        indices = (
            range(bisect_right(source_frames, a), bisect_right(source_frames, b))
            if a < b
            else range(bisect_left(source_frames, a) - 1, bisect_left(source_frames, b) - 1, -1)
        )
        for index in indices:
            append(index, (segment + (events[index].frame - a) / (b - a)) / fps)
    return output
