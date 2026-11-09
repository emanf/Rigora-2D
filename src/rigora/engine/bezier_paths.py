"""Editable cubic paths sampled deterministically for vector artwork and motion constraints."""

import math
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from rigora.domain.entities import Constraint
from rigora.domain.geometry import inverse, transform_point
from rigora.domain.project import ProjectError
from rigora.engine.sampling import number

if TYPE_CHECKING:
    from rigora.engine.constraints import ConstraintContext


def control_points(raw: Any) -> tuple[tuple[float, float], ...]:
    """Require 1–64 cubic segments, finite bounded coordinates and complete control triplets."""
    if not isinstance(raw, (list, tuple)) or not 4 <= len(raw) <= 193 or (len(raw) - 1) % 3:
        raise ProjectError("Cubic paths need 4 + 3n control points, up to 64 segments.")
    result = []
    for point in raw:
        if not isinstance(point, (tuple, list)) or len(point) != 2:
            raise ProjectError("Each control point requires X and Y.")
        pair = number(point[0]), number(point[1])
        if max(abs(v) for v in pair) > 1e6:
            raise ProjectError("Path coordinates must remain within one million pixels.")
        result.append(pair)
    return tuple(result)


def path_point(points: Sequence[tuple[float, float]], progress: float) -> tuple[float, float]:
    """Evaluate joined cubic segments with exact endpoint clamping and no playback history."""
    count = (len(points) - 1) // 3
    value = min(1, max(0, progress)) * count
    index = min(count - 1, int(value))
    t = value - index
    p = points[index * 3 : index * 3 + 4]
    return tuple(
        sum(
            p[i][axis] * factor
            for i, factor in enumerate(
                ((1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t * t, t**3)
            )
        )
        for axis in (0, 1)
    )  # type: ignore[return-value]


def motion_path(rule: Constraint, context: "ConstraintContext") -> None:
    """Move the owner's pivot along controls, optionally orienting it to the tangent."""
    points = control_points(rule.parameters.get("points"))
    progress = number(rule.parameters.get("progress", 0))
    x, y = path_point(points, progress)
    node = context.node(rule.owner_id)
    parent = context.nodes.get(node.parent_id or "")
    parent_space = rule.parameters.get("space", "world") == "parent"
    ahead, behind = path_point(points, progress + 1e-5), path_point(points, progress - 1e-5)
    if parent and parent_space:
        x, y = transform_point(parent.world_matrix, x, y)
        ahead = transform_point(parent.world_matrix, *ahead)
        behind = transform_point(parent.world_matrix, *behind)
    if rule.parameters.get("orient", False) and math.dist(ahead, behind) > 1e-9:
        dx, dy = ahead[0] - behind[0], ahead[1] - behind[1]
        if parent:
            a, b, c, d, _, _ = inverse(parent.world_matrix)
            dx, dy = a * dx + c * dy, b * dx + d * dy
        angle = math.degrees(math.atan2(dy, dx)) + number(rule.parameters.get("angle", 0))
        if node.local.scale_x < 0:
            angle -= 180
        context.local(node.id, node.local._replace(rotation=angle))
        node = context.node(node.id)
    a, b, c, d, _, _ = node.world_matrix
    context.position(
        node.id,
        x - a * node.local.pivot_x - c * node.local.pivot_y,
        y - b * node.local.pivot_x - d * node.local.pivot_y,
    )
