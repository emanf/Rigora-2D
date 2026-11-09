"""Qt-free affine editing and corner-based redistribution of free-form lattice controls."""

import math
from collections.abc import Mapping
from typing import Any

from rigora.domain.project import ProjectError
from rigora.engine.deformation import lattice_controls
from rigora.engine.sampling import number


def soft_drag_weights(
    points: Mapping[int, tuple[float, float]],
    center: tuple[float, float],
    radius: float,
    strength: float = 1,
    falloff: float = 1,
) -> dict[int, float]:
    """Capture smooth, compact-support influence around a press in one coordinate space.

    Weights stay fixed throughout a gesture so event frequency cannot amplify a drag.
    Full quintic falloff has zero first and second derivatives at both boundaries;
    reducing falloff blends toward a uniformly weighted neighborhood.
    """
    radius, strength, falloff = number(radius), number(strength), number(falloff)
    cx, cy = number(center[0]), number(center[1])
    if radius <= 0 or not 0 <= strength <= 1 or not 0 <= falloff <= 1:
        raise ProjectError(
            "Soft Drag needs a positive radius and strength/falloff from zero to one."
        )
    result = {}
    for index, (x, y) in points.items():
        t = math.hypot(number(x) - cx, number(y) - cy) / radius
        if t < 1:
            result[index] = strength * (1 - falloff * t * t * t * (10 + t * (-15 + 6 * t)))
    return result


def edit_controls(
    parameters: Mapping[str, Any],
    selected: tuple[int, ...],
    *,
    dx: float = 0,
    dy: float = 0,
    rotation: float = 0,
    scale_x: float = 1,
    scale_y: float = 1,
    operation: str = "transform",
) -> dict[int, tuple[float, float]]:
    """Return new offsets for selected absolute control positions, preserving unselected dots."""
    columns, rows, offsets = lattice_controls(parameters)
    x, y, width, height = parameters["bounds"]
    base = tuple(
        (x + i % columns * width / (columns - 1), y + i // columns * height / (rows - 1))
        for i in range(len(offsets))
    )
    points = tuple((a + ox, b + oy) for (a, b), (ox, oy) in zip(base, offsets, strict=True))
    selected = tuple(dict.fromkeys(selected))
    if operation in ("reset_all", "average", "align_root"):
        selected = tuple(range(len(points)))
    if not selected or any(type(i) is not int or not 0 <= i < len(points) for i in selected):
        raise ProjectError("Select editable FFD lattice dots before transforming them.")
    dx, dy, rotation, scale_x, scale_y = (number(v) for v in (dx, dy, rotation, scale_x, scale_y))
    cx = (min(points[i][0] for i in selected) + max(points[i][0] for i in selected)) / 2
    cy = (min(points[i][1] for i in selected) + max(points[i][1] for i in selected)) / 2
    if operation == "mirror_x":
        scale_x = -1
    elif operation == "mirror_y":
        scale_y = -1
    elif operation == "align_root":
        dx, dy = x + width / 2 - cx, y + height / 2 - cy
    elif operation not in ("transform", "reset", "reset_all", "average", "align_x", "align_y"):
        raise ProjectError("Unknown FFD control operation.")
    angle = math.radians(rotation)
    cosine, sine = math.cos(angle), math.sin(angle)
    result: dict[int, tuple[float, float]] = {}
    for i in selected:
        px, py = points[i]
        if operation.startswith("reset"):
            result[i] = (0, 0)
            continue
        if operation == "average":
            u, v = i % columns / (columns - 1), i // columns / (rows - 1)
            weights = (
                (0, (1 - u) * (1 - v)),
                (columns - 1, u * (1 - v)),
                (len(points) - columns, (1 - u) * v),
                (len(points) - 1, u * v),
            )
            nx = sum(points[k][0] * weight for k, weight in weights)
            ny = sum(points[k][1] * weight for k, weight in weights)
        else:
            px, py = (px - cx) * scale_x, (py - cy) * scale_y
            nx, ny = cx + px * cosine - py * sine + dx, cy + px * sine + py * cosine + dy
            nx = cx if operation == "align_x" else nx
            ny = cy if operation == "align_y" else ny
        result[i] = (number(nx - base[i][0]), number(ny - base[i][1]))
    return result
