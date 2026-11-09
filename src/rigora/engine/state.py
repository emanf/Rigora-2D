"""Immutable evaluated runtime state, separate from persistent authoring records."""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, NamedTuple

from rigora.domain.entities import Camera
from rigora.domain.geometry import Matrix, multiply

if TYPE_CHECKING:
    from rigora.engine.particles import Particle


class TransformValues(NamedTuple):
    """Evaluated local translation, authored rotation, scale and pivot components."""

    x: float
    y: float
    rotation: float
    scale_x: float
    scale_y: float
    pivot_x: float
    pivot_y: float


@dataclass(frozen=True, slots=True)
class NodePose:
    """One evaluated transform and its resolved world geometry."""

    id: str
    name: str
    kind: str
    parent_id: str | None
    local: TransformValues
    local_matrix: Matrix
    world_matrix: Matrix
    length: float
    visible: bool
    opacity: float = 1.0


@dataclass(frozen=True, slots=True)
class MeshPose:
    """Immutable evaluated local geometry, UVs and indexed triangles ready for any renderer."""

    id: str
    name: str
    object_id: str | None
    asset_id: str | None
    vertex_ids: tuple[str, ...]
    positions: tuple[tuple[float, float], ...]
    uv: tuple[tuple[float, float], ...]
    triangles: tuple[tuple[int, ...], ...]
    warnings: tuple[str, ...]
    appearance: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True, slots=True)
class ScenePose:
    """A reproducible scene sample with ordered nodes and deferred-stage diagnostics."""

    scene_id: str
    clip_id: str | None
    requested_frame: float
    frame: float
    nodes: Mapping[str, NodePose]
    render_order: tuple[str, ...]
    warnings: tuple[str, ...]
    meshes: Mapping[str, MeshPose] = field(default_factory=lambda: MappingProxyType({}))
    # Live dynamics must target the pre-simulation pose, not simulate their own output again.
    spring_targets: Mapping[str, NodePose] | None = field(default=None, repr=False)
    # Skinning consumes bind-space bones; overlays apply the same placement as the skin.
    bone_placements: Mapping[str, Matrix] = field(default_factory=lambda: MappingProxyType({}))

    cameras: tuple[Camera, ...] = ()
    region_owners: frozenset[str] = frozenset()
    particles: Mapping[str, tuple["Particle", ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def for_display(self) -> "ScenePose":
        """Resolve bone overlays into scene space without changing solver or mesh inputs.

        The returned snapshot is display-only and idempotent. Mesh geometry and
        non-bone nodes are shared; authoring and physics retain the original pose.
        """
        if not self.bone_placements:
            return self
        return replace(
            self,
            nodes=MappingProxyType(
                {
                    key: replace(
                        node, world_matrix=multiply(self.bone_placements[key], node.world_matrix)
                    )
                    if key in self.bone_placements
                    else node
                    for key, node in self.nodes.items()
                }
            ),
            bone_placements=MappingProxyType({}),
        )

    def to_dict(self) -> dict[str, Any]:
        """Encode a headless pose without persistent data or transport state."""
        from rigora.domain.validation import json_copy

        return {
            "scene_id": self.scene_id,
            "clip_id": self.clip_id,
            "requested_frame": self.requested_frame,
            "frame": self.frame,
            "nodes": [
                {
                    "id": node.id,
                    "name": node.name,
                    "kind": node.kind,
                    "parent_id": node.parent_id,
                    "local": node.local._asdict(),
                    "local_matrix": list(node.local_matrix),
                    "world_matrix": list(node.world_matrix),
                    "length": node.length,
                    "visible": node.visible,
                    "opacity": node.opacity,
                }
                for node in self.nodes.values()
            ],
            "render_order": list(self.render_order),
            "bone_placements": {key: list(matrix) for key, matrix in self.bone_placements.items()},
            "meshes": [
                {
                    "id": mesh.id,
                    "name": mesh.name,
                    "object_id": mesh.object_id,
                    "asset_id": mesh.asset_id,
                    "vertices": [
                        {"id": key, "x": point[0], "y": point[1], "uv": list(uv)}
                        for key, point, uv in zip(
                            mesh.vertex_ids, mesh.positions, mesh.uv, strict=True
                        )
                    ],
                    "triangles": [list(face) for face in mesh.triangles],
                    "warnings": list(mesh.warnings),
                    "appearance": json_copy(mesh.appearance),
                }
                for mesh in self.meshes.values()
            ],
            "warnings": list(self.warnings),
            "particles": {
                owner: [
                    {
                        "matrix": list(p.matrix),
                        "color": p.color,
                        "opacity": p.opacity,
                        "shape": p.shape,
                    }
                    for p in parts
                ]
                for owner, parts in self.particles.items()
            },
        }
