"""Validated, deterministic movement direction to authored Object view mappings."""

import math
from collections.abc import Mapping
from typing import Any

from rigora.domain.object_views import VIEW_SLOTS
from rigora.domain.project import ProjectError
from rigora.engine.sampling import number

DIRECTIONS = ("idle", "left", "right", "up", "down")


def movement_settings(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a stable driver ID, pixel/second threshold and exactly five authored slots."""
    driver, slots = raw.get("driver"), raw.get("slots")
    speed = number(raw.get("minimum_speed", 8))
    if (
        not isinstance(driver, str)
        or not driver
        or not 0 <= speed <= 1e6
        or not isinstance(slots, Mapping)
        or set(slots) != set(DIRECTIONS)
        or any(value not in VIEW_SLOTS for value in slots.values())
    ):
        raise ProjectError("Movement views need a driver, five valid slots and a bounded speed.")
    return {"driver": driver, "minimum_speed": speed, "slots": dict(slots)}


def movement_direction(dx: float, dy: float, seconds: float, minimum: float) -> str:
    """Choose the dominant screen-space axis, using Idle below the authored speed threshold."""
    if seconds <= 0 or math.hypot(dx, dy) / seconds <= minimum:
        return "idle"
    return ("right" if dx >= 0 else "left") if abs(dx) >= abs(dy) else ("down" if dy >= 0 else "up")
