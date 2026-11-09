"""Damped angular secondary motion for sampled animation and transient interactive bone posing."""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from rigora.domain.entities import Constraint
from rigora.domain.geometry import affine, inverse, multiply, transform_point
from rigora.domain.project import ProjectError
from rigora.engine.sampling import number
from rigora.engine.state import NodePose


@dataclass
class SpringState:
    """One transient angular oscillator and its preceding joint velocity for inertial forcing."""

    angle: float
    velocity: float
    root: tuple[float, float]
    root_velocity: tuple[float, float] = (0, 0)
    displacement: tuple[float, ...] = (0, 0)
    displacement_velocity: tuple[float, ...] = (0, 0)


class SpringSimulation:
    """Advance parent-anchored bone oscillators while recomposing descendant geometry."""

    def __init__(self) -> None:
        """Create instance-owned simulation memory without retaining authored projects."""
        self.states: dict[str, SpringState] = {}

    def excite(
        self, nodes: Sequence[NodePose], rules: tuple[Constraint, ...], *, strain: float = 0.25
    ) -> None:
        """Displace existing live states for a visible release test, without changing target poses.

        Angular displacement respects each rule's limits. Axial displacement uses
        world length and stretch/squash bounds; attachment points remain untouched.
        """
        strain = number(strain, "Spring test strain")
        sources = {node.id: node for node in nodes}
        for rule in rules:
            state = self.states.get(rule.id)
            node = sources.get(rule.owner_id)
            if (
                not rule.enabled
                or state is None
                or node is None
                or not node.parent_id
                and not rule.extra.get("spring_object_root")
            ):
                continue
            heading = math.atan2(node.world_matrix[1], node.world_matrix[0])
            if rule.parameters.get("rotate", True):
                angle = min(36.0, float(rule.parameters.get("clockwise", 65)))
                state.angle, state.velocity = heading + math.radians(angle), 0
            if rule.parameters.get("translate", False):
                ratio = max(
                    -float(rule.parameters.get("squash", 0)) / 100,
                    min(float(rule.parameters.get("stretch", 0)) / 100, strain),
                )
                length = node.length * math.hypot(node.world_matrix[0], node.world_matrix[1])
                state.displacement = (
                    math.cos(heading) * length * ratio,
                    math.sin(heading) * length * ratio,
                )
                state.displacement_velocity = (0, 0)

    def advance(
        self, nodes: Sequence[NodePose], rules: tuple[Constraint, ...], dt: float
    ) -> list[NodePose]:
        """Integrate a parent-first target pose while preserving authored attachment points.

        Each output node inherits its already resolved parent once. Simulation
        states are instance-owned; the sampled target nodes remain immutable.
        """
        dt = number(dt, "Spring time step")
        if not 0 < dt <= 0.25:
            raise ProjectError("Spring time steps must be positive and at most 0.25 seconds.")
        resolved: dict[str, NodePose] = {}
        by_owner = {r.owner_id: r for r in rules if r.enabled}
        active = {r.id for r in by_owner.values()}
        self.states = {key: state for key, state in self.states.items() if key in active}
        for source in nodes:
            # Parent-first input lets each descendant inherit the final parent once,
            # instead of recomposing whole subtrees for every spring in the chain.
            parent = resolved.get(source.parent_id or "")
            world = (
                multiply(parent.world_matrix, source.local_matrix)
                if parent
                else source.world_matrix
            )
            node = replace(source, world_matrix=world)
            if not all(math.isfinite(v) for v in (*world, *transform_point(world, node.length, 0))):
                raise ProjectError("Spring geometry exceeds the finite numeric range.")
            resolved[source.id] = node
            rule = by_owner.get(source.id)
            if rule is None:
                continue
            if node.kind != "bone" or parent is None and not rule.extra.get("spring_object_root"):
                raise ProjectError(
                    "Spring secondary motion requires a child bone; roots remain fixed."
                )
            # A first bone belongs to its object root, whose driving transform
            # is already in world_matrix. Its skeletal parent remains None.
            parent_world = (
                parent.world_matrix
                if parent
                else multiply(source.world_matrix, inverse(source.local_matrix))
            )
            frequency = number(rule.parameters.get("frequency", 3), "Spring frequency")
            damping = number(rule.parameters.get("damping", 0.5), "Spring damping")
            strength = number(rule.parameters.get("strength", 1), "Spring strength")
            gravity = number(rule.parameters.get("gravity", 0), "Spring gravity")
            inertia = number(rule.parameters.get("inertia", 0.6), "Spring inertia")
            maximum = number(rule.parameters.get("max_angle", 65), "Spring angular limit")
            clockwise = number(rule.parameters.get("clockwise", maximum))
            counterclockwise = number(rule.parameters.get("counterclockwise", maximum))
            translate = rule.parameters.get("translate", False)
            rotate = rule.parameters.get("rotate", True)
            stretch = number(rule.parameters.get("stretch", 0))
            squash = number(rule.parameters.get("squash", 0))
            if not (
                0.5 <= frequency <= 12
                and 0.05 <= damping <= 3
                and 0 <= strength <= 1
                and 0 <= inertia <= 3
                and -10000 <= gravity <= 10000
                and 0 <= maximum <= 170
                and 0 <= clockwise <= 180
                and 0 <= counterclockwise <= 180
                and type(translate) is bool
                and type(rotate) is bool
                and 0 <= stretch <= 300
                and 0 <= squash <= 100
            ):
                raise ProjectError("Spring settings exceed their supported physical ranges.")
            target = math.atan2(source.world_matrix[1], source.world_matrix[0])
            reference = target
            if "rest_rotation" in rule.parameters:
                rest = node.local._replace(
                    rotation=number(rule.parameters["rest_rotation"], "Spring rest angle")
                )
                rest_matrix = multiply(parent_world, affine(*rest))
                reference = math.atan2(rest_matrix[1], rest_matrix[0])
            root = node.world_matrix[4:]
            state = self.states.get(rule.id)
            if state is None:
                state = SpringState(target, 0, root)
                self.states[rule.id] = state
            root_velocity = tuple((a - b) / dt for a, b in zip(root, state.root, strict=True))
            acceleration = tuple(
                max(-100000, min(100000, (a - b) / dt))
                for a, b in zip(root_velocity, state.root_velocity, strict=True)
            )
            target_scale = math.hypot(source.world_matrix[0], source.world_matrix[1])
            length = max(1, node.length * target_scale)
            force = -acceleration[0] * math.sin(state.angle) + acceleration[1] * math.cos(
                state.angle
            )
            torque = (-inertia * force + gravity * math.cos(state.angle)) / length
            steps = max(1, math.ceil(dt * 240 - 1e-10))
            step = dt / steps
            omega = math.tau * frequency
            for _ in range(steps):
                error = math.remainder(target - state.angle, math.tau)
                state.velocity += (
                    omega * omega * error - 2 * damping * omega * state.velocity + torque
                ) * step
                state.angle += state.velocity * step
                offset = math.remainder(state.angle - reference, math.tau)
                bounded = max(-math.radians(counterclockwise), min(math.radians(clockwise), offset))
                if bounded != offset:
                    state.angle = reference + bounded
                    state.velocity = 0
                if translate:
                    forces = (-inertia * acceleration[0], -inertia * acceleration[1] + gravity)
                    state.displacement_velocity = tuple(
                        speed
                        + (-omega * omega * offset - 2 * damping * omega * speed + force) * step
                        for offset, speed, force in zip(
                            state.displacement, state.displacement_velocity, forces, strict=True
                        )
                    )
                    state.displacement = tuple(
                        offset + speed * step
                        for offset, speed in zip(
                            state.displacement, state.displacement_velocity, strict=True
                        )
                    )
            state.root, state.root_velocity = root, (root_velocity[0], root_velocity[1])
            angle = target + math.remainder(state.angle - target, math.tau) * strength
            matrix = inverse(parent_world)
            vx, vy = math.cos(angle), math.sin(angle)
            local_heading = math.atan2(
                matrix[1] * vx + matrix[3] * vy, matrix[0] * vx + matrix[2] * vy
            )
            if node.local.scale_x < 0:
                local_heading -= math.pi
            strain = 1.0
            if translate:
                # Axial strain stretches the bone, never the gap between parent and child.
                # Scaling its local X also carries skinned artwork and descendant joints.
                heading = (
                    angle if rotate else math.atan2(node.world_matrix[1], node.world_matrix[0])
                )
                axis = (math.cos(heading), math.sin(heading))
                distance = sum(a * b for a, b in zip(state.displacement, axis, strict=True))
                bounded = max(-length * squash / 100, min(length * stretch / 100, distance))
                if distance != bounded:
                    state.displacement = tuple(bounded * a for a in axis)
                    state.displacement_velocity = (0, 0)
                # Keep even 100% squash invertible for descendant transform solvers.
                strain = max(0.001, 1 + bounded / length * strength)
            local = node.local._replace(
                rotation=math.degrees(local_heading) if rotate else node.local.rotation,
            )
            matrix = affine(*local)
            pa, pb, pc, pd = parent_world[:4]
            inherited_scale = math.hypot(
                pa * matrix[0] + pc * matrix[1], pb * matrix[0] + pd * matrix[1]
            )
            # Elastic parent scale moves the attachment, but must not multiply the child's
            # own strain down the chain. Preserve its target world length before stretching.
            if inherited_scale:
                local = local._replace(
                    scale_x=local.scale_x * target_scale * strain / inherited_scale
                )
            matrix = affine(*local)
            # Rotating/scaling a nonzero pivot must not move the bone's base joint.
            local = local._replace(
                x=local.x + node.local_matrix[4] - matrix[4],
                y=local.y + node.local_matrix[5] - matrix[5],
            )
            matrix = affine(*local)
            world = multiply(parent_world, matrix)
            if not all(
                math.isfinite(v) for v in (*matrix, *world, *transform_point(world, node.length, 0))
            ):
                raise ProjectError("Spring geometry exceeds the finite numeric range.")
            resolved[node.id] = replace(node, local=local, local_matrix=matrix, world_matrix=world)
        return list(resolved.values())


class SpringCursor:
    """Retain fixed ticks and bounded checkpoints for an immutable evaluator's spring inputs.

    Forward playback extends the current state; backward seeks restore a preceding
    checkpoint. Fractional samples use copies. Cold seeks replay from clip start,
    retaining the full settling history instead of truncating slow oscillators.
    """

    def __init__(self) -> None:
        """Start without a sampled window or published pose."""
        self.begin: float | None = None
        self.tick = 0
        self.simulation = SpringSimulation()
        self.pose: tuple[NodePose, ...] = ()
        self.checkpoints: dict[int, tuple[dict[str, SpringState], tuple[NodePose, ...]]] = {}

    def reset(self, begin: float | None = None) -> None:
        """Discard a previous window, including any partially failed integration."""
        self.begin, self.tick = begin, 0
        self.simulation = SpringSimulation()
        self.pose = ()
        self.checkpoints.clear()

    def checkpoint(self) -> None:
        """Keep at most 64 one-second states plus the initial state, independent of clip length."""
        self.checkpoints[self.tick] = (
            {key: replace(value) for key, value in self.simulation.states.items()},
            self.pose,
        )
        if len(self.checkpoints) > 65:
            self.checkpoints.pop(next(key for key in self.checkpoints if key != 0))

    def rewind(self, tick: int) -> None:
        """Restore the closest earlier fixed state without retaining authored scene snapshots."""
        self.tick = max(key for key in self.checkpoints if key <= tick)
        states, self.pose = self.checkpoints[self.tick]
        self.simulation.states = {key: replace(value) for key, value in states.items()}


def sample_springs(
    nodes: Sequence[NodePose],
    rules: tuple[Constraint, ...],
    frame: float,
    start: float,
    fps: int,
    sample: Callable[[float], tuple[NodePose, ...]],
    *,
    cursor: SpringCursor | None = None,
    rules_at: Callable[[float], tuple[Constraint, ...]] | None = None,
) -> tuple[list[NodePose], tuple[str, ...]]:
    """Reconstruct fixed samples, optionally reusing an evaluator-owned integer-tick cursor.

    A cursor belongs to one immutable rule set and sampler. Callers with transient
    overrides omit it. Cached and uncached results remain independent of seek order.
    """
    if not rules:
        return list(nodes), ()
    begin = start
    ticks = max(0, math.floor((frame - begin) / fps * 60))
    history = cursor if cursor is not None else SpringCursor()
    try:
        if history.begin != begin:
            history.reset(begin)
            history.pose = tuple(
                history.simulation.advance(
                    sample(begin), rules_at(begin) if rules_at else rules, 1 / 60
                )
            )
            history.checkpoint()
        elif history.tick > ticks:
            history.rewind(ticks)
        for i in range(history.tick + 1, ticks + 1):
            time = begin + i / 60 * fps
            history.pose = tuple(
                history.simulation.advance(
                    sample(time), rules_at(time) if rules_at else rules, 1 / 60
                )
            )
            history.tick = i
            if i % 60 == 0:
                history.checkpoint()
        last = begin + ticks / 60 * fps
        result = list(history.pose) if ticks else list(nodes)
        if frame > last + 1e-9:
            simulation = SpringSimulation()
            simulation.states = {
                key: replace(state) for key, state in history.simulation.states.items()
            }
            result = simulation.advance(
                nodes, rules_at(frame) if rules_at else rules, (frame - last) / fps
            )
        return result, ()
    except (ProjectError, ValueError, OverflowError) as error:
        history.reset()
        return list(nodes), (f"Spring secondary motion: {error}",)
