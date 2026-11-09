"""Deterministic constraint scheduling and extensible Qt-free transform solvers."""

import math
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any

from rigora.domain.entities import Constraint
from rigora.domain.geometry import Matrix, affine, decompose, inverse, multiply, transform_point
from rigora.domain.validation import ProjectError
from rigora.engine.sampling import EvaluationError, number
from rigora.engine.state import NodePose, TransformValues


class ConstraintContext:
    """Own a frame's mutable working map; published poses remain immutable snapshots."""

    def __init__(self, nodes: list[NodePose]) -> None:
        """Retain parent-first insertion order for deterministic descendant recomposition."""
        self.nodes = {node.id: node for node in nodes}

    def node(self, key: str | None) -> NodePose:
        """Resolve a transform target and reject missing or unsupported owner identities."""
        if key not in self.nodes:
            raise EvaluationError("Choose an existing object or bone transform target.")
        return self.nodes[key]

    def local(self, key: str, local: TransformValues, length: float | None = None) -> None:
        """Replace local values and recompute that node and its descendants in this frame."""
        node = self.node(key)
        if length is not None and number(length, "Constrained bone length") < 0:
            raise EvaluationError("Constrained bone length cannot be negative.")
        self.nodes[key] = replace(
            node, local=local, length=node.length if length is None else length
        )
        affected = {key}
        for identity, current in self.nodes.items():
            if identity != key and current.parent_id not in affected:
                continue
            affected.add(identity)
            matrix = affine(*current.local)
            parent = self.nodes.get(current.parent_id or "")
            world = multiply(parent.world_matrix, matrix) if parent else matrix
            if not all(
                math.isfinite(v)
                for v in (*matrix, *world, *transform_point(world, current.length, 0))
            ):
                raise EvaluationError("Constraint geometry exceeds the finite numeric range.")
            self.nodes[identity] = replace(current, local_matrix=matrix, world_matrix=world)

    def world(self, key: str, matrix: Matrix) -> None:
        """Set a world transform using the current parent space, rejecting unrepresentable shear."""
        node = self.node(key)
        parent = self.nodes.get(node.parent_id or "")
        local = multiply(inverse(parent.world_matrix), matrix) if parent else matrix
        self.local(key, TransformValues(*decompose(local, node.local.pivot_x, node.local.pivot_y)))

    def position(self, key: str, x: float, y: float) -> None:
        """Move a world origin without changing the node's linear transform."""
        self.world(key, (*self.node(key).world_matrix[:4], x, y))


type ConstraintSolver = Callable[[Constraint, ConstraintContext], None]


def scalar(constraint: Constraint, key: str, default: float) -> float:
    """Read a finite solver parameter without accepting boolean or JSON object values."""
    return number(constraint.parameters.get(key, default), key)


def aim(constraint: Constraint, context: ConstraintContext) -> None:
    """Aim local positive X at a target origin, with an optional degree offset."""
    owner, target = context.node(constraint.owner_id), context.node(constraint.target_id)
    x, y = target.world_matrix[4:]
    parent = context.nodes.get(owner.parent_id or "")
    if parent:
        x, y = transform_point(inverse(parent.world_matrix), x, y)
    ox, oy = owner.local_matrix[4:]
    if math.hypot(x - ox, y - oy) < 1e-10:
        return
    angle = math.degrees(math.atan2(y - oy, x - ox)) + scalar(constraint, "offset", 0)
    if owner.local.scale_x < 0:
        angle -= 180
    local = owner.local._replace(rotation=angle)
    matrix = affine(*local)
    local = local._replace(x=local.x + ox - matrix[4], y=local.y + oy - matrix[5])
    context.local(owner.id, local)


def copy_transform(constraint: Constraint, context: ConstraintContext) -> None:
    """Copy a target's world transform into the constrained node's current parent space."""
    context.world(constraint.owner_id, context.node(constraint.target_id).world_matrix)


def limits(constraint: Constraint, context: ConstraintContext) -> None:
    """Clamp authored local translation and rotation against explicitly supplied bounds."""
    node = context.node(constraint.owner_id)
    values = node.local._asdict()
    for field in ("x", "y", "rotation"):
        low = scalar(constraint, f"min_{field}", -1e300)
        high = scalar(constraint, f"max_{field}", 1e300)
        if low > high:
            raise EvaluationError(f"min_{field} must not exceed max_{field}.")
        values[field] = min(high, max(low, values[field]))
    context.local(node.id, TransformValues(**values))


def minimum_joint_angle(constraint: Constraint, context: ConstraintContext) -> None:
    """Limit folding relative to the direct parent; straight is 180 degrees.

    Measure world directions so mirrored and nonuniform parent scales retain the
    same visible limit. Preserve the joint origin and length, and the bend side.
    """
    node = context.node(constraint.owner_id)
    parent = context.nodes.get(node.parent_id or "")
    limit = scalar(constraint, "angle", 0)
    if not 0 <= limit <= 180:
        raise EvaluationError("Minimum joint angle must be from 0 to 180 degrees.")
    if parent is None or parent.kind != "bone" or limit == 0:
        return
    pa, pb = parent.world_matrix[:2]
    a, b = node.world_matrix[:2]
    if min(math.hypot(pa, pb), math.hypot(a, b)) < 1e-10:
        return
    turn = math.atan2(pa * b - pb * a, pa * a + pb * b)
    maximum = math.radians(180 - limit)
    if abs(turn) <= maximum + 1e-10:
        return
    angle = math.atan2(pb, pa) + math.copysign(maximum, turn)
    ia, ib, ic, id_, _, _ = inverse(parent.world_matrix)
    dx, dy = math.cos(angle), math.sin(angle)
    rotation = math.degrees(math.atan2(ib * dx + id_ * dy, ia * dx + ic * dy))
    if node.local.scale_x < 0:
        rotation -= 180
    rotation = node.local.rotation + (rotation - node.local.rotation + 180) % 360 - 180
    local = node.local._replace(rotation=rotation)
    matrix = affine(*local)
    local = local._replace(
        x=local.x + node.local_matrix[4] - matrix[4],
        y=local.y + node.local_matrix[5] - matrix[5],
    )
    context.local(node.id, local)


def parent_space(constraint: Constraint, context: ConstraintContext) -> None:
    """Follow a selected space with an explicit affine offset, without changing hierarchy."""
    offset = constraint.parameters.get("offset", (1, 0, 0, 1, 0, 0))
    if not isinstance(offset, (tuple, list)) or len(offset) != 6:
        raise EvaluationError("Space offset requires six affine matrix components.")
    a, b, c, d, x, y = (number(v, "Space offset") for v in offset)
    context.world(
        constraint.owner_id,
        multiply(context.node(constraint.target_id).world_matrix, (a, b, c, d, x, y)),
    )


def pin(constraint: Constraint, context: ConstraintContext) -> None:
    """Pin any selected local point to a fixed scene position or a moving target origin."""
    owner = context.node(constraint.owner_id)
    px, py = scalar(constraint, "point_x", 0), scalar(constraint, "point_y", 0)
    current_x, current_y = transform_point(owner.world_matrix, px, py)
    if constraint.target_id:
        x, y = context.node(constraint.target_id).world_matrix[4:]
    else:
        if "x" not in constraint.parameters or "y" not in constraint.parameters:
            raise EvaluationError("Set a fixed scene X and Y or choose a pin target.")
        x, y = scalar(constraint, "x", current_x), scalar(constraint, "y", current_y)
    context.position(
        owner.id, owner.world_matrix[4] + x - current_x, owner.world_matrix[5] + y - current_y
    )


def tracking(constraint: Constraint, context: ConstraintContext) -> None:
    """Follow target translation while preserving rotation, scale and an explicit XY offset."""
    x, y = context.node(constraint.target_id).world_matrix[4:]
    context.position(
        constraint.owner_id,
        x + scalar(constraint, "offset_x", 0),
        y + scalar(constraint, "offset_y", 0),
    )


def two_bone_ik(constraint: Constraint, context: ConstraintContext) -> None:
    """Solve a connected two-joint chain analytically in root-parent space with stable folding."""
    mode = constraint.parameters.get("mode", "ik")
    if mode == "fk":
        return
    if mode != "ik":
        raise EvaluationError("IK mode must be 'ik' or 'fk'.")
    root = context.node(constraint.owner_id)
    child_id = constraint.parameters.get("end_bone_id")
    if not isinstance(child_id, str):
        raise EvaluationError("Choose the direct child as end_bone_id.")
    child = context.node(child_id)
    if root.kind != "bone" or child.kind != "bone" or child.parent_id != root.id:
        raise EvaluationError("Two-bone IK requires a bone and its direct child.")
    for node in (root, child):
        if not all(
            math.isclose(value, expected, abs_tol=1e-8)
            for value, expected in (
                (abs(node.local.scale_x), 1),
                (abs(node.local.scale_y), 1),
                (node.local.pivot_x, 0),
                (node.local.pivot_y, 0),
            )
        ):
            raise EvaluationError(
                "IK joints need unit-magnitude scales and zero pivots; "
                "parent-space transforms remain supported."
            )
    if not math.isclose(child.local.x, root.length, abs_tol=1e-7) or abs(child.local.y) > 1e-7:
        raise EvaluationError("Connect the child at the root bone's endpoint before enabling IK.")
    l1, l2 = root.length, child.length
    if min(l1, l2) < 1e-8:
        raise EvaluationError("Both IK bones need positive lengths.")
    target = context.node(constraint.target_id)
    x, y = target.world_matrix[4:]
    parent = context.nodes.get(root.parent_id or "")
    if parent:
        x, y = transform_point(inverse(parent.world_matrix), x, y)
    dx, dy = x - root.local.x, y - root.local.y
    distance = math.hypot(dx, dy)
    bend = scalar(constraint, "bend", 1)
    if bend not in (-1, 1):
        raise EvaluationError("Bend direction must be -1 or 1.")
    stretch = constraint.parameters.get("stretch", False)
    if type(stretch) is not bool:
        raise EvaluationError("Stretch must be a boolean.")
    maximum_stretch = scalar(constraint, "max_stretch", 1.5)
    if not 1 <= maximum_stretch <= 10:
        raise EvaluationError("Maximum stretch must be between 1 and 10.")
    factor = min(maximum_stretch, max(1, distance / (l1 + l2))) if stretch else 1
    l1, l2 = l1 * factor, l2 * factor
    low = scalar(constraint, "min_reach", 0)
    high = scalar(constraint, "max_reach", l1 + l2)
    if not 0 <= low <= high:
        raise EvaluationError("Reach limits require 0 <= min_reach <= max_reach.")
    reach = min(l1 + l2, max(abs(l1 - l2), min(high, max(low, distance))))
    direction = math.atan2(dy, dx) if distance > 1e-10 else math.radians(root.local.rotation)
    if reach < 1e-10:
        shoulder, elbow = direction, bend * math.pi
    else:
        shoulder = direction - bend * math.acos(
            max(-1, min(1, (l1 * l1 + reach * reach - l2 * l2) / (2 * l1 * reach)))
        )
        elbow = bend * math.acos(
            max(-1, min(1, (reach * reach - l1 * l1 - l2 * l2) / (2 * l1 * l2)))
        )
    root_heading = math.pi if root.local.scale_x < 0 else 0
    child_heading = math.pi if child.local.scale_x < 0 else 0
    orientation = root.local.scale_x * root.local.scale_y
    context.local(root.id, root.local._replace(rotation=math.degrees(shoulder - root_heading)), l1)
    context.local(
        child.id,
        child.local._replace(x=l1, rotation=math.degrees((elbow - child_heading) / orientation)),
        l2,
    )


def builtin_solvers() -> dict[str, ConstraintSolver]:
    """Return an instance-owned solver registry that callers may extend through injection."""
    from rigora.engine.bezier_paths import motion_path
    from rigora.engine.camera_production import camera_follow, shot_transition
    from rigora.engine.contact_solver import foot_contact

    return {
        "foot_contact": foot_contact,
        "motion_path": motion_path,
        "camera_follow": camera_follow,
        "shot_transition": shot_transition,
        "two_bone_ik": two_bone_ik,
        "aim": aim,
        "copy_transform": copy_transform,
        "limits": limits,
        "minimum_joint_angle": minimum_joint_angle,
        "parent": parent_space,
        "space_switch": parent_space,
        "pin": pin,
        "track": tracking,
    }


class ConstraintPlan:
    """Compile target dependencies once; cyclic or invalid rules produce actionable warnings."""

    def __init__(
        self,
        constraints: tuple[Constraint, ...],
        parents: Mapping[str, str | None],
        solvers: Mapping[str, ConstraintSolver] | None = None,
    ) -> None:
        """Order dependencies before numeric priority while retaining stored order for ties."""
        self.solvers = builtin_solvers()
        self.solvers.update(solvers or {})
        active = sorted(
            (
                c
                for c in constraints
                if c.enabled and not (c.kind == "two_bone_ik" and c.parameters.get("mode") == "fk")
            ),
            key=lambda c: c.order,
        )
        warnings = []
        valid = []
        for c in active:
            if c.kind not in self.solvers:
                warnings.append(
                    f"Constraint '{c.name}' ({c.kind}) is not evaluated; unknown solver."
                )
            elif c.owner_id not in parents or (
                c.target_id is not None and c.target_id not in parents
            ):
                warnings.append(
                    f"Constraint '{c.name}': choose valid transform owners and targets."
                )
            else:
                valid.append(c)
        writes = {}
        for c in valid:
            affected = {c.owner_id}
            for key in parents:
                if parents[key] in affected:
                    affected.add(key)
            writes[c.id] = affected
        dependencies: dict[str, set[str]] = {c.id: set() for c in valid}
        for index, current in enumerate(valid):
            for previous in valid[:index]:
                if current.owner_id == previous.owner_id:
                    dependencies[current.id].add(previous.id)
            for other in valid:
                if current.owner_id != other.owner_id and current.owner_id in writes[other.id]:
                    dependencies[current.id].add(other.id)
                if current.target_id in writes[other.id]:
                    dependencies[current.id].add(other.id)
        ordered = []
        pending = list(valid)
        while pending:
            ready = next((c for c in pending if not dependencies[c.id]), None)
            if ready is None:
                warnings.extend(
                    f"Constraint '{c.name}': cycle; choose a target outside the driven branch."
                    for c in pending
                )
                break
            pending.remove(ready)
            ordered.append(ready)
            for refs in dependencies.values():
                refs.discard(ready.id)
        self.ordered = tuple(ordered)
        self.warnings = tuple(warnings)

    def apply(
        self,
        nodes: list[NodePose],
        *,
        skip_owners: frozenset[str] = frozenset(),
        parameters: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> tuple[list[NodePose], tuple[str, ...]]:
        """Run each solver atomically, retaining unaffected rules and the last valid geometry."""
        if not self.ordered:
            return nodes, self.warnings
        context = ConstraintContext(nodes)
        warnings = list(self.warnings)
        for constraint in self.ordered:
            if parameters and constraint.id in parameters:
                constraint = replace(
                    constraint, parameters={**constraint.parameters, **parameters[constraint.id]}
                )
            if (
                constraint.owner_id in skip_owners
                or constraint.parameters.get("end_bone_id") in skip_owners
            ):
                continue
            previous = context.nodes.copy()
            try:
                self.solvers[constraint.kind](constraint, context)
            except (ProjectError, ValueError, OverflowError, ZeroDivisionError) as error:
                context.nodes = previous
                warnings.append(f"Constraint '{constraint.name}': {error}")
        return list(context.nodes.values()), tuple(warnings)
