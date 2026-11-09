"""Explicit inverse-bind skinning and bounded, normalized weight brush operations."""

import math
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, Literal

from rigora.application_services.area_pins import AreaPinService
from rigora.domain.entities import Deformer, Mesh
from rigora.domain.geometry import transform_point
from rigora.domain.mesh_geometry import Point, normalize_weights
from rigora.domain.project import ProjectError
from rigora.engine.state import ScenePose

type BrushOperation = Literal["add", "subtract", "smooth", "normalize"]


def weight_brush(
    mesh: Mesh,
    positions: Mapping[str, Point],
    center: Point,
    bone_id: str,
    radius: float,
    strength: float,
    operation: BrushOperation,
    limit: int = 4,
) -> Mesh:
    """Return one brush dab in scene pixels; protected vertices are excluded from publication."""
    if (
        not math.isfinite(radius)
        or radius <= 0
        or not 0 <= strength <= 1
        or operation not in ("add", "subtract", "smooth", "normalize")
    ):
        raise ProjectError("Brush radius, strength or operation is invalid.")
    neighbors: dict[str, set[str]] = {v.id: set() for v in mesh.vertices}
    for face in mesh.triangles:
        for key in face:
            neighbors[key].update(k for k in face if k != key)
    by_id = {v.id: v for v in mesh.vertices}
    vertices = []
    for vertex in mesh.vertices:
        point = positions[vertex.id]
        distance = math.dist(point, center)
        if vertex.protected or distance >= radius:
            vertices.append(vertex)
            continue
        amount = strength * (1 - distance / radius) ** 2
        values = dict(vertex.weights)
        if operation == "smooth":
            adjacent = [by_id[k].weights for k in neighbors[vertex.id]]
            if adjacent:
                keys = set(values).union(*(set(weights) for weights in adjacent))
                values = {
                    k: values.get(k, 0) * (1 - amount)
                    + amount * sum(w.get(k, 0) for w in adjacent) / len(adjacent)
                    for k in keys
                }
        elif operation != "normalize":
            old = values.get(bone_id, 0)
            target = min(1.0, max(0.0, old + (amount if operation == "add" else -amount)))
            others = sum(v for k, v in values.items() if k != bone_id)
            values = (
                {k: v * (1 - target) / others for k, v in values.items() if k != bone_id}
                if others
                else {}
            )
            if target:
                values[bone_id] = target
        vertices.append(replace(vertex, weights=normalize_weights(values, limit)))
    return replace(mesh, vertices=tuple(vertices))


class SkinService(AreaPinService):
    """Bind at the displayed pose and use the same canonical weight records for all clients."""

    def bind(
        self,
        mesh_id: str,
        bones: tuple[str, ...],
        *,
        auto_weight: bool = True,
        limit: int = 4,
        automatic: bool = False,
    ) -> str:
        """Capture world bind matrices, optionally initializing nearest-segment weights.

        Explicit binding restores drawing's automatic-weighting policy. Automatic
        reweighting retains the user's excluded influences and disabled-stage state.
        """
        mesh = self.mesh(mesh_id)
        if len(bones) > 1:
            controllers = {
                b.id for rig in self.scene.skeletons for b in rig.bones if b.extra.get("rig_root")
            }
            bones = tuple(key for key in bones if key not in controllers)
        pose = self.document.animation.pose
        if mesh.id not in pose.meshes:
            from rigora.engine.evaluation import SceneEvaluator

            # Newly imported artwork can be outside the active object's deformation
            # scope until this binding makes it a member. Capture its displayed geometry
            # in the same local space as the selected bones before changing ownership.
            pose = SceneEvaluator(
                self.scene,
                pose.clip_id,
                solvers=self.document.constraint_solvers,
                deformers=self.document.deformer_solvers,
                select_first_clip=False,
                local_object=self.document.animation_context,
            ).evaluate(pose.requested_frame)
        if not bones or any(k not in pose.nodes or pose.nodes[k].kind != "bone" for k in bones):
            raise ProjectError("Select at least one existing bone before binding artwork.")
        if mesh.object_id is None or mesh.object_id not in pose.nodes:
            raise ProjectError("Skinning needs a mesh attached to an artwork object.")
        params: dict[str, Any] = {
            "intensity": 1,
            "object_bind": pose.nodes[mesh.object_id].world_matrix,
            "bind_matrices": {k: pose.nodes[k].world_matrix for k in bones},
        }
        from rigora.application_services.characters import CharacterService

        root = CharacterService(self.document).object_root(mesh_id)
        if root and root.id in pose.nodes:
            params.update(object_group=root.id, object_group_bind=pose.nodes[root.id].world_matrix)
        old = next(
            (d for d in self.scene.deformers if d.owner_id == mesh.id and d.kind == "skinning"),
            None,
        )
        stage = (
            replace(old, parameters=params, enabled=old.enabled if automatic else True)
            if old
            else Deformer(
                owner_id=mesh.id,
                name="Bone skinning",
                kind="skinning",
                order=min(
                    (d.order for d in self.scene.deformers if d.owner_id == mesh.id), default=0
                )
                - 1,
                parameters=params,
            )
        )
        if auto_weight:
            positions = self.positions(mesh, pose)
            segments = [
                (
                    key,
                    transform_point(pose.nodes[key].world_matrix, 0, 0),
                    transform_point(pose.nodes[key].world_matrix, pose.nodes[key].length, 0),
                )
                for key in bones
            ]
            vertices = []
            for v in mesh.vertices:
                if v.protected:
                    if any(k not in bones for k in v.weights):
                        raise ProjectError(
                            "Protected weights reference bones outside this binding."
                        )
                    vertices.append(v)
                    continue
                x, y = positions[v.id]
                weights = {}
                for key, (ax, ay), (bx, by) in segments:
                    dx, dy = bx - ax, by - ay
                    t = max(
                        0, min(1, ((x - ax) * dx + (y - ay) * dy) / max(1e-9, dx * dx + dy * dy))
                    )
                    weights[key] = 1 / max(1, math.hypot(x - ax - t * dx, y - ay - t * dy)) ** 2
                vertices.append(replace(v, weights=normalize_weights(weights, limit)))
            mesh = replace(mesh, vertices=tuple(vertices))
        elif any(k not in bones for v in mesh.vertices for k in v.weights):
            raise ProjectError("Existing vertex weights require additional bones in the bind set.")
        if not automatic:
            extra = dict(mesh.extra)
            extra.pop("unbound_bones", None)
            mesh = replace(mesh, extra={**extra, "auto_bind_artwork": True})
        stages = tuple(stage if old and d.id == old.id else d for d in self.scene.deformers)
        self.commit(
            "Bind artwork to bones",
            meshes=tuple(mesh if m.id == mesh.id else m for m in self.scene.meshes),
            deformers=stages if old else (*stages, stage),
        )
        return stage.id

    @staticmethod
    def positions(mesh: Mesh, pose: ScenePose) -> dict[str, Point]:
        """Map evaluated mesh positions into scene pixels for a scale-independent brush radius."""
        points = pose.meshes[mesh.id].positions
        matrix = pose.nodes[mesh.object_id].world_matrix if mesh.object_id else (1, 0, 0, 1, 0, 0)
        return {
            v.id: transform_point(matrix, *p) for v, p in zip(mesh.vertices, points, strict=True)
        }
