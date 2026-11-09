"""Length-preserving joint projection for interactive chain posing with an anchored root."""

import math
from collections.abc import Mapping

from rigora.domain.project import ProjectError

type Point = tuple[float, float]


def selected_roots(parents: Mapping[str, str | None], selected: tuple[str, ...]) -> tuple[str, ...]:
    """Return selected branches without selected ancestors in a validated acyclic hierarchy.

    Preserve selection order, omit stale identities, and collapse parent/child
    selections so connected FK groups use their highest selected base joint.
    """
    chosen = set(selected)
    roots = []
    for key in dict.fromkeys(selected):
        if key not in parents:
            continue
        parent = parents[key]
        while parent and parent not in chosen:
            parent = parents.get(parent)
        if parent is None:
            roots.append(key)
    return tuple(roots)


def pull_chain(joints: tuple[Point, ...], target: Point) -> tuple[Point, ...]:
    """Reach toward a target without moving the first joint or stretching any segment.

    Unreachable targets clamp to the chain's total reach. A deterministic bend
    seed resolves straight-chain folds; bounded iterations keep pointer work finite.
    """
    if len(joints) < 2 or not all(
        type(v) in (int, float) and math.isfinite(v) for p in (*joints, target) for v in p
    ):
        raise ProjectError("Chain pulling requires finite joints and a target.")
    lengths = [math.dist(a, b) for a, b in zip(joints[:-1], joints[1:], strict=True)]
    if min(lengths) < 1e-8 or not math.isfinite(sum(lengths)):
        raise ProjectError("Give every pulled bone a positive length.")
    points = list(joints)
    origin = points[0]
    reach, distance = sum(lengths), math.dist(origin, target)
    if not math.isfinite(distance):
        raise ProjectError("The pull target exceeds the finite geometry range.")
    if distance >= reach:
        direction = ((target[0] - origin[0]) / distance, (target[1] - origin[1]) / distance)
        for i, length in enumerate(lengths):
            points[i + 1] = (
                points[i][0] + direction[0] * length,
                points[i][1] + direction[1] * length,
            )
        return tuple(points)
    direction = (
        (
            (target[0] - origin[0]) / max(distance, 1e-9),
            (target[1] - origin[1]) / max(distance, 1e-9),
        )
        if distance > 1e-9
        else (1.0, 0.0)
    )
    if all(
        abs((p[0] - origin[0]) * direction[1] - (p[1] - origin[1]) * direction[0]) < 1e-7
        for p in points
    ):
        for i in range(1, len(points) - 1):
            bend = math.sin(math.pi * i / (len(points) - 1)) * reach * 0.1
            points[i] = (points[i][0] - direction[1] * bend, points[i][1] + direction[0] * bend)
    for _ in range(96):
        points[-1] = target
        for i in reversed(range(len(lengths))):
            points[i] = project_joint(
                points[i], points[i + 1], lengths[i], joints[i], joints[i + 1]
            )
        points[0] = origin
        for i, length in enumerate(lengths):
            points[i + 1] = project_joint(
                points[i + 1], points[i], length, joints[i + 1], joints[i]
            )
        if math.dist(points[-1], target) < 1e-5:
            break
    return tuple(points)


def project_joint(
    point: Point, anchor: Point, length: float, old: Point, old_anchor: Point
) -> Point:
    """Place a joint at a fixed distance, retaining a stable direction for coincident input."""
    dx, dy = point[0] - anchor[0], point[1] - anchor[1]
    radius = math.hypot(dx, dy)
    if radius < 1e-12:
        dx, dy = old[0] - old_anchor[0], old[1] - old_anchor[1]
        radius = math.hypot(dx, dy)
    return anchor[0] + dx * length / radius, anchor[1] + dy * length / radius
