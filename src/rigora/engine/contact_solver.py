"""Weighted two-segment foot contacts with stable anchor space and optional root compensation."""

import math
from dataclasses import replace
from typing import TYPE_CHECKING

from rigora.domain.entities import Constraint
from rigora.domain.geometry import inverse, multiply, transform_point
from rigora.engine.sampling import EvaluationError, number

if TYPE_CHECKING:
    from rigora.engine.constraints import ConstraintContext


def foot_contact(rule: Constraint, context: "ConstraintContext") -> None:
    """Solve the lower-leg tip onto an anchor, blending in local space without editing rest data."""
    from rigora.engine.constraints import two_bone_ik

    weight = min(1.0, max(0.0, number(rule.parameters.get("weight", 0))))
    if weight == 0:
        return
    upper = context.node(rule.owner_id)
    lower = context.node(str(rule.parameters.get("end_bone_id", "")))
    target = context.node(rule.target_id)
    before = dict(context.nodes)
    affected = [upper.id, lower.id]
    placement = context.nodes.get(str(rule.parameters.get("placement_owner", "")))
    delta = (
        multiply(tuple(rule.parameters["placement_bind"]), inverse(placement.world_matrix))
        if placement
        else (1, 0, 0, 1, 0, 0)
    )
    # Object placement is applied after constraints/skinning. Solve its inverse
    # here so the scene-space anchor is neither doubled nor dragged with the hip.
    anchor_world = transform_point(delta, *target.world_matrix[4:])
    context.nodes[target.id] = replace(
        target, world_matrix=(*target.world_matrix[:4], *anchor_world)
    )
    if rule.parameters.get("compensate", True):
        parent = context.nodes.get(upper.parent_id or "")
        anchor = anchor_world
        if parent:
            anchor = transform_point(inverse(parent.world_matrix), *anchor)
        dx, dy = anchor[0] - upper.local.x, anchor[1] - upper.local.y
        distance = math.hypot(dx, dy)
        if min(upper.length, lower.length) <= 1e-8:
            raise EvaluationError("Foot contacts require positive-length leg segments.")
        minimum_angle = number(rule.parameters.get("minimum_angle", 0))
        minimum = math.sqrt(
            max(
                0,
                upper.length**2
                + lower.length**2
                - 2 * upper.length * lower.length * math.cos(math.radians(minimum_angle)),
            )
        )
        reach = min(upper.length + lower.length - 1e-7, max(minimum + 1e-7, distance))
        if abs(distance - reach) > 1e-8:
            if distance <= 1e-8:
                dx, dy, distance = 1.0, 0.0, 1.0
                offset = -reach
            else:
                offset = distance - reach
            context.local(
                upper.id,
                upper.local._replace(
                    x=upper.local.x + dx * offset / distance,
                    y=upper.local.y + dy * offset / distance,
                ),
            )
    two_bone_ik(replace(rule, kind="two_bone_ik"), context)
    context.nodes[target.id] = target
    foot_id = str(rule.parameters.get("foot_bone_id", ""))
    if foot_id:
        foot = context.node(foot_id)
        angle = number(rule.parameters.get("angle", 0))
        if rule.parameters.get("anchor_space") == "object" and target.parent_id:
            parent = context.node(target.parent_id)
            angle += math.degrees(math.atan2(parent.world_matrix[1], parent.world_matrix[0]))
        dx, dy = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        angle = math.degrees(
            math.atan2(delta[1] * dx + delta[3] * dy, delta[0] * dx + delta[2] * dy)
        )
        parent = context.nodes.get(foot.parent_id or "")
        if parent:
            a, b, c, d, _, _ = inverse(parent.world_matrix)
            dx, dy = math.cos(math.radians(angle)), math.sin(math.radians(angle))
            angle = math.degrees(math.atan2(b * dx + d * dy, a * dx + c * dy))
        if foot.local.scale_x < 0:
            angle -= 180
        context.local(foot.id, foot.local._replace(rotation=angle))
        affected.append(foot.id)
    solved = dict(context.nodes)
    for key in affected:
        original, destination = before[key], solved[key]
        values = {}
        for field in original.local._fields:
            old, new = getattr(original.local, field), getattr(destination.local, field)
            delta = (new - old + 180) % 360 - 180 if field == "rotation" else new - old
            values[field] = old + delta * weight
        context.local(key, original.local._replace(**values))
