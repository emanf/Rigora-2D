"""Resolve rigid Scene followers against final placed bones without changing skin space."""

import math
from bisect import bisect_right
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from rigora.domain.entities import Constraint, Track
from rigora.domain.geometry import IDENTITY, Matrix, affine, inverse, multiply
from rigora.domain.scene_attachments import ATTACHMENT_PATH, AttachmentState, point_matrix
from rigora.engine.constraints import ConstraintContext, ConstraintPlan
from rigora.engine.sampling import EvaluationError
from rigora.engine.state import NodePose


def dependency_parents(
    parents: Mapping[str, str | None], bone_owners: Mapping[str, str]
) -> dict[str, str | None]:
    """Include implicit Object ownership when checking cycles across separate skeletons."""
    result = dict(parents)
    for bone, owner in bone_owners.items():
        if not result.get(bone) and owner in result:
            result[bone] = owner
    return result


def inherited(matrix: Matrix, rotation: bool, scale: bool) -> Matrix:
    """Keep affine targets intact by default; explicitly filter optional inherited components."""
    if rotation and scale:
        return matrix
    a, b, c, d, x, y = matrix
    sx = math.hypot(a, b)
    sy = (a * d - b * c) / max(sx, 1e-12)
    angle = math.degrees(math.atan2(b, a)) if rotation else 0
    return affine(x, y, angle, sx if scale else 1, sy if scale else 1, 0, 0)


class SceneFollowPlan:
    """Compile following order at state boundaries and binary-search held attachment keys."""

    def __init__(
        self,
        rules: tuple[Constraint, ...],
        parents: Mapping[str, str | None],
        bone_owners: Mapping[str, str],
        bindings: Mapping[str, Matrix],
        *,
        records: Mapping[str, Any] | None = None,
        tracks: tuple[Track, ...] = (),
        dependencies: tuple[Constraint, ...] = (),
    ) -> None:
        """Compile static and keyed links once; no graph construction runs during playback."""
        self.bone_owners, self.bindings = bone_owners, bindings
        self.records = records or {}
        self.rules = rules
        self.rule_ids = {c.owner_id: c.id for c in rules if c.kind == "scene_attachment"}
        self.defaults = {
            c.owner_id: AttachmentState.from_dict({**c.parameters, "target_id": c.target_id})
            for c in rules
            if c.kind == "scene_attachment"
        }
        self.keys: dict[str, tuple[tuple[float, ...], tuple[AttachmentState, ...]]] = {}
        boundaries: set[float] = set()
        for track in tracks:
            if (
                track.property_path != ATTACHMENT_PATH
                or not track.evaluation_enabled
                or track.weight <= 0
            ):
                continue
            states = tuple(
                AttachmentState.from_dict(k.extra["scene_attachment"])
                if "scene_attachment" in k.extra
                else self.defaults.get(track.owner_id, AttachmentState())
                for k in track.keyframes
            )
            self.keys[track.owner_id] = tuple(k.frame for k in track.keyframes), states
            boundaries.update(k.frame for k in track.keyframes)
        self.boundaries = (float("-inf"), *sorted(boundaries))
        cache: dict[tuple[str | None, ...], ConstraintPlan] = {}
        dependency_warnings: list[str] = []
        plans = []
        parents = dependency_parents(parents, bone_owners)
        solvers = {
            "parent": self.follow,
            "space_switch": self.follow,
            "scene_attachment": self.follow,
        }
        for frame in self.boundaries:
            active_states = self.states(frame)
            targets = tuple(
                active_states[c.owner_id].target_id if c.kind == "scene_attachment" else c.target_id
                for c in rules
            )
            if targets not in cache:
                active = tuple(
                    replace(c, target_id=target) for c, target in zip(rules, targets, strict=True)
                )
                cache[targets] = ConstraintPlan(active, parents, solvers)
                if dependencies and self.defaults:
                    graph = ConstraintPlan(
                        (*dependencies, *active),
                        parents,
                        {c.kind: self.follow for c in (*dependencies, *active)},
                    )
                    dependency_warnings.extend(w for w in graph.warnings if "cycle" in w)
            plans.append(cache[targets])
        self.plans = tuple(plans)
        self.warnings = tuple(
            dict.fromkeys(
                [
                    *(w for plan in cache.values() for w in plan.warnings),
                    *dependency_warnings,
                ]
            )
        )

    def states(self, frame: float) -> dict[str, AttachmentState]:
        """Sample each held state independently of previous seeks or playback direction."""
        result = dict(self.defaults)
        for owner, (times, values) in self.keys.items():
            index = bisect_right(times, frame) - 1
            if index >= 0:
                result[owner] = values[index]
        return result

    def follow(self, rule: Constraint, context: ConstraintContext) -> None:
        """Follow a final target, retaining affine geometry and authored local controls."""
        matrix = IDENTITY
        if rule.target_id:
            target = context.node(rule.target_id)
            matrix = target.world_matrix
            owner = self.bone_owners.get(target.id)
            if owner and owner in context.nodes:
                matrix = multiply(
                    multiply(context.node(owner).world_matrix, inverse(self.bindings[owner])),
                    matrix,
                )
        if rule.kind != "scene_attachment":
            context.world(rule.owner_id, multiply(matrix, rule.parameters.get("offset", IDENTITY)))
            return
        if not rule.target_id:
            parent = context.nodes.get(context.node(rule.owner_id).parent_id or "")
            matrix = parent.world_matrix if parent else IDENTITY
        matrix = inherited(
            matrix, rule.parameters["inherit_rotation"], rule.parameters["inherit_scale"]
        )
        world = multiply(multiply(matrix, rule.parameters["_point"]), rule.parameters["_offset"])
        node = context.node(rule.owner_id)
        world = multiply(
            world, multiply(inverse(rule.parameters["bind_matrix"]), node.local_matrix)
        )
        if not all(math.isfinite(value) for value in world):
            raise EvaluationError("Attachment exceeds the finite coordinate range.")
        # Scene following is an affine effect. Keep authored local controls unchanged;
        # world matrices may contain shear from a rotated, nonuniformly scaled target.
        context.nodes[node.id] = replace(node, world_matrix=world)
        affected = {node.id}
        for key, child in context.nodes.items():
            if key != node.id and child.parent_id in affected:
                affected.add(key)
                child_world = multiply(
                    context.node(child.parent_id).world_matrix, child.local_matrix
                )
                if not all(math.isfinite(value) for value in child_world):
                    raise EvaluationError("Attached artwork exceeds the finite coordinate range.")
                context.nodes[key] = replace(
                    child,
                    world_matrix=child_world,
                )

    def apply(
        self,
        nodes: list[NodePose],
        *,
        frame: float = 0,
        skip_owners: frozenset[str] = frozenset(),
        parameters: Mapping[str, Mapping[str, Any]] | None = None,
        views: Mapping[str, str] | None = None,
    ) -> tuple[list[NodePose], tuple[str, ...]]:
        """Apply precompiled following with live point definitions and held offsets."""
        if not self.rules:
            return nodes, ()
        values = {key: dict(value) for key, value in (parameters or {}).items()}
        for owner, state in self.states(frame).items():
            target_point = (
                point_matrix(
                    self.records[state.target_id],
                    state.point,
                    (views or {}).get(state.target_id, ""),
                )
                if state.target_id
                else IDENTITY
            )
            source_point = point_matrix(
                self.records[owner], state.source_point, (views or {}).get(owner, "")
            )
            values[self.rule_ids[owner]] = {
                **state.to_dict(),
                "_point": target_point,
                "_offset": multiply(state.offset, inverse(source_point)),
            }
        plan = self.plans[max(0, bisect_right(self.boundaries, frame) - 1)]
        return plan.apply(nodes, skip_owners=skip_owners, parameters=values)
