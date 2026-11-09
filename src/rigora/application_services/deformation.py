"""Undoable deformation stack authoring and extensible original parameter presets."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from rigora.application_services.meshes import MeshService
from rigora.domain.entities import Deformer
from rigora.domain.mesh_geometry import Point, move_vertices
from rigora.domain.project import ProjectError
from rigora.domain.validation import json_copy
from rigora.engine.deformation import (
    DeformationContext,
    builtin_deformers,
    default_parameters,
    lattice_controls,
)
from rigora.engine.sampling import number


@dataclass(frozen=True)
class DeformationPreset:
    """Data-only named parameters; callers may inject additional original preset definitions."""

    name: str
    kind: str
    parameters: Mapping[str, Any]


def deformation_presets() -> tuple[DeformationPreset, ...]:
    """Return neutral and expressive original parameter sets without shared mutable state."""
    return (
        DeformationPreset("Custom FFD", "ffd", {}),
        DeformationPreset("Local lattice", "lattice", {}),
        DeformationPreset("Bend", "bend", {"amount": 35}),
        DeformationPreset("Bulge", "bulge", {"amount": 0.3}),
        DeformationPreset("Twist", "twist", {"amount": 60}),
        DeformationPreset("Squash / stretch", "squash_stretch", {"amount": 0.7}),
        DeformationPreset("Transform", "transform", {}),
        DeformationPreset("Weighted offset", "vertex_offset", {}),
        DeformationPreset("Local pins", "pin", {"pins": {}}),
    )


class DeformationService(MeshService):
    """Publish validated non-destructive stage edits through the document command history."""

    def sculpt_vertices(self, key: str, positions: Mapping[str, Point]) -> None:
        """Commit a surface gesture, retaining valid rest geometry beneath folded poses.

        Coordinates use the same pre-stack vertex channels as animation. Existing sculpt
        offsets accumulate the gesture delta, so subsequent edits do not jump or drift.
        """
        mesh = self.mesh(key)
        vertices = {v.id: v for v in mesh.vertices}
        if not set(positions) <= vertices.keys():
            raise ProjectError("The selected vertex no longer exists.")
        if any(vertices[k].protected for k in positions):
            raise ProjectError("Unprotect selected vertices before moving them.")
        positions = {k: (number(p[0]), number(p[1])) for k, p in positions.items()}
        stack = self.document.animation.evaluator.deformation.stages[key]
        first = next((d for d in stack if d.enabled and d.kind != "appearance"), None)
        stage = (
            first
            if first
            and first.owner_id == key
            and first.kind == "mesh_sculpt"
            and first.parameters.get("intensity", 1) == 1
            and "weights" not in first.parameters
            else None
        )
        if stage is None:
            try:
                changed = move_vertices(mesh, positions)
            except ProjectError as error:
                if str(error) not in (
                    "This edit would collapse or invert a triangle.",
                    "This edit would create overlapping base triangles.",
                ):
                    raise
            else:
                self.replace_mesh(changed, "Move mesh vertices")
                return
            stage = Deformer(
                owner_id=key,
                name="Mesh shape",
                kind="mesh_sculpt",
                order=min((d.order for d in stack), default=0) - 1,
            )
        params = json_copy(stage.parameters)
        offsets = params.setdefault("offsets", {})
        for identity, point in positions.items():
            vertex = vertices[identity]
            previous = offsets.get(identity, (0, 0))
            offsets[identity] = [
                previous[0] + point[0] - vertex.x,
                previous[1] + point[1] - vertex.y,
            ]
        stage = replace(stage, parameters=params)
        self.validate(stage)
        self.commit(
            "Sculpt mesh",
            deformers=(*(d for d in self.scene.deformers if d.id != stage.id), stage),
        )

    def stage(self, key: str) -> Deformer:
        """Resolve a stable stage UUID and reject stale inspector state."""
        stage = next((d for d in self.scene.deformers if d.id == key), None)
        if stage is None:
            raise ProjectError("The selected deformer no longer exists.")
        return stage

    def add(
        self, mesh_id: str, preset: DeformationPreset, *, columns: int = 3, rows: int = 3
    ) -> str:
        """Append a preset with explicit field bounds and neutral lattice controls."""
        mesh = self.mesh(mesh_id)
        parameters = {**default_parameters(preset.kind, mesh), **json_copy(preset.parameters)}
        if preset.kind in ("ffd", "lattice"):
            parameters.update(columns=columns, rows=rows)
            _, _, controls = lattice_controls(parameters)
            parameters["controls"] = [list(p) for p in controls]
        stage = Deformer(
            owner_id=mesh.id,
            name=preset.name,
            kind=preset.kind,
            parameters=parameters,
            order=max((d.order for d in self.scene.deformers if d.owner_id == mesh.id), default=-1)
            + 1,
        )
        self.validate(stage)
        self.commit("Add deformer", deformers=(*self.scene.deformers, stage))
        return stage.id

    def validate(self, stage: Deformer) -> None:
        """Validate callable parameters against base geometry before accepting an authored edit."""
        mesh = self.mesh(stage.owner_id)
        params = {
            **default_parameters(stage.kind, mesh),
            **json_copy(stage.parameters),
            "_kind": stage.kind,
        }
        solvers = {**builtin_deformers(), **self.document.deformer_solvers}
        if stage.kind not in solvers:
            raise ProjectError("This deformation kind has no installed solver.")
        if not 0 <= number(params["intensity"], "Intensity") <= 10:
            raise ProjectError("Intensity must be between 0 and 10.")
        weights = params.get("weights")
        known_vertices = {v.id for v in mesh.vertices}
        if weights is not None and (
            not isinstance(weights, Mapping)
            or any(
                k not in known_vertices or not 0 <= number(value, "Mask") <= 1
                for k, value in weights.items()
            )
        ):
            raise ProjectError("A vertex mask needs existing vertices and weights between 0 and 1.")
        if stage.kind != "skinning":
            solvers[stage.kind](
                DeformationContext(mesh, tuple((v.x, v.y) for v in mesh.vertices), params, {})
            )

    def update(self, key: str, **changes: Any) -> None:
        """Replace a stage record atomically while keeping its stable ID and stack position."""
        stage = replace(self.stage(key), **changes)
        if "parameters" in changes or "kind" in changes:
            self.validate(stage)
        self.commit(
            "Edit deformer",
            deformers=tuple(stage if d.id == key else d for d in self.scene.deformers),
        )

    def parameters(self, key: str, **changes: Any) -> None:
        """Merge explicit parameter values without altering unaffected custom settings."""
        stage = self.stage(key)
        self.update(key, parameters={**json_copy(stage.parameters), **changes})

    def remove(self, key: str) -> None:
        """Remove a stage and its owned animation tracks together as one reversible operation."""
        self.stage(key)
        self.commit(
            "Remove deformer",
            deformers=tuple(d for d in self.scene.deformers if d.id != key),
            timelines=tuple(
                replace(t, tracks=tuple(k for k in t.tracks if k.owner_id != key))
                for t in self.scene.timelines
            ),
        )

    def reorder(self, key: str, direction: int) -> None:
        """Move one stage within its mesh stack and normalize order values deterministically."""
        selected = self.stage(key)
        stack = sorted(
            (d for d in self.scene.deformers if d.owner_id == selected.owner_id),
            key=lambda d: d.order,
        )
        index = next(i for i, d in enumerate(stack) if d.id == key)
        target = min(len(stack) - 1, max(0, index + direction))
        stack.insert(target, stack.pop(index))
        orders = {d.id: i for i, d in enumerate(stack)}
        self.commit(
            "Reorder deformers",
            deformers=tuple(
                replace(d, order=orders[d.id]) if d.id in orders else d
                for d in self.scene.deformers
            ),
        )

    def controls(self, key: str, offsets: Mapping[int, tuple[float, float]]) -> None:
        """Move one or several FFD/lattice controls in local pixels without modifying the mesh."""
        stage = self.stage(key)
        _, _, current = lattice_controls(stage.parameters)
        controls = [list(p) for p in current]
        for index, point in offsets.items():
            if not 0 <= index < len(controls):
                raise ProjectError("The lattice control index is outside the field.")
            controls[index] = list(point)
        self.parameters(key, controls=controls)

    def anchors(self, key: str, vertices: set[str]) -> None:
        """Create movable pin anchors at selected base vertices, preserving existing anchors."""
        stage = self.stage(key)
        if stage.kind != "pin":
            raise ProjectError("Choose a Local pins deformer before creating pin anchors.")
        mesh = self.mesh(stage.owner_id)
        pins = json_copy(stage.parameters.get("pins", {}))
        for vertex in mesh.vertices:
            if vertex.id in vertices:
                pins.setdefault(vertex.id, {"x": vertex.x, "y": vertex.y, "strength": 1})
        self.parameters(key, pins=pins)

    def mask(self, key: str, vertices: set[str], weight: float) -> None:
        """Set selected vertex influence; unlisted vertices receive zero influence."""
        if not 0 <= weight <= 1:
            raise ProjectError("Mask weights must be between 0 and 1.")
        stage = self.stage(key)
        weights = json_copy(stage.parameters.get("weights", {}))
        weights.update({key: weight for key in vertices})
        self.parameters(key, weights=weights)
