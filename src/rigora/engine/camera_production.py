"""Deterministic camera follow and interpolated shot framing over ordinary constraints."""

from typing import TYPE_CHECKING

from rigora.domain.entities import Constraint
from rigora.domain.geometry import affine, decompose, inverse, multiply, transform_point
from rigora.engine.sampling import number

if TYPE_CHECKING:
    from rigora.engine.constraints import ConstraintContext


def camera_follow(rule: Constraint, context: "ConstraintContext") -> None:
    """Keep the camera pivot centered on the target pivot plus authored world-pixel offsets."""
    camera, target = context.node(rule.owner_id), context.node(rule.target_id)
    matrix = target.world_matrix
    placement = context.nodes.get(str(rule.parameters.get("placement_owner", "")))
    if placement:
        matrix = multiply(
            multiply(placement.world_matrix, inverse(tuple(rule.parameters["placement_bind"]))),
            matrix,
        )
    x, y = transform_point(matrix, target.local.pivot_x, target.local.pivot_y)
    a, b, c, d, _, _ = camera.world_matrix
    context.position(
        camera.id,
        x
        + number(rule.parameters.get("offset_x", 0))
        - a * camera.local.pivot_x
        - c * camera.local.pivot_y,
        y
        + number(rule.parameters.get("offset_y", 0))
        - b * camera.local.pivot_x
        - d * camera.local.pivot_y,
    )


def shot_transition(rule: Constraint, context: "ConstraintContext") -> None:
    """Blend destination framing from the previous camera, including different frame sizes."""
    progress = min(1, max(0, number(rule.parameters.get("progress", 1))))
    if progress >= 1:
        return
    if rule.parameters.get("easing", "smooth") == "smooth":
        progress = progress * progress * (3 - 2 * progress)
    source, target = context.node(rule.target_id), context.node(rule.owner_id)
    ratio_x = number(rule.parameters["source_width"]) / number(rule.parameters["target_width"])
    ratio_y = number(rule.parameters["source_height"]) / number(rule.parameters["target_height"])
    first = decompose(multiply(source.world_matrix, (ratio_x, 0, 0, ratio_y, 0, 0)))
    last = decompose(target.world_matrix)
    values = [a + (b - a) * progress for a, b in zip(first, last, strict=True)]
    values[2] = first[2] + ((last[2] - first[2] + 180) % 360 - 180) * progress
    context.world(target.id, affine(*values))
