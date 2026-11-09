"""Editable guided character assembly using the canonical artwork, rig and skin services."""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from rigora.application_services.asset_pipeline import AssetPipeline
from rigora.application_services.content_library import ContentService
from rigora.application_services.rigging import RigService
from rigora.application_services.scene_editing import SceneEditingService
from rigora.application_services.skinning import SkinService
from rigora.domain.entities import Mesh
from rigora.domain.geometry import transform_point
from rigora.domain.project import ProjectError
from rigora.engine.sampling import number
from rigora.engine.state import ScenePose

RIG_TEMPLATES = ("Biped", "Quadruped", "Winged", "Flexible spine", "Chain")
PART_ROLES = (
    "Artwork",
    "Body",
    "Head",
    "Arm L",
    "Arm R",
    "Hand L",
    "Hand R",
    "Leg L",
    "Leg R",
    "Foot L",
    "Foot R",
    "Tail",
    "Wing L",
    "Wing R",
)


def fingerprint(mesh: Mesh) -> str:
    """Identify untouched generated topology, including weights and vertex protection flags."""
    payload = {"vertices": [v.to_dict() for v in mesh.vertices], "triangles": mesh.triangles}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class RiggingGuideService(SkinService):
    """Compose undoable guide steps without keeping a parallel wizard project model."""

    def import_parts(self, paths: tuple[Path, ...]) -> tuple[str, ...]:
        """Import up to 32 original artwork files as independent editable parts atomically."""
        if not 1 <= len(paths) <= 32:
            raise ProjectError("Import between one and 32 artwork parts per step.")
        result = []
        with self.document.command_group("Import character parts"):
            for path in paths:
                mesh_id = str(AssetPipeline(self.document).image(path, place=True)["mesh_id"])
                mesh = self.mesh(mesh_id)
                self.replace_mesh(
                    replace(mesh, extra={**mesh.extra, "wizard_pristine": fingerprint(mesh)})
                )
                result.append(mesh_id)
        return tuple(result)

    def identify(self, parts: Mapping[str, tuple[str, str]]) -> None:
        """Persist user labels and part roles on real scene objects in one reversible command."""
        scene = SceneEditingService(self.document)
        changes = {}
        for key, (name, role) in parts.items():
            record = scene.record(key)
            if key not in {o.id for o in self.scene.objects} or scene.locked(key):
                raise ProjectError("Choose unlocked artwork objects to identify.")
            if not name.strip() or len(name) > 200 or role not in PART_ROLES:
                raise ProjectError(
                    "Use a part name up to 200 characters and a supported part role."
                )
            changes[key] = replace(
                record, name=name.strip(), extra={**record.extra, "character_part": role}
            )
        scene.update_records(changes, "Identify character parts")

    def generate_rig(self, template: str, meshes: tuple[str, ...], *, scale: float = 1) -> str:
        """Create an anatomical template fitted to artwork bounds; all local bones stay editable."""
        if template not in RIG_TEMPLATES or not 0.01 <= number(scale) <= 100:
            raise ProjectError("Choose a rig template and a size multiplier between 0.01 and 100.")
        if not meshes:
            raise ProjectError("Import or select artwork before generating its rig.")
        pose = self.document.animation.pose
        points: list[tuple[float, float]] = []
        for key in meshes:
            mesh = self.mesh(key)
            if mesh.object_id is None:
                raise ProjectError("Artwork needs a scene object before fitting a rig.")
            matrix = pose.nodes[mesh.object_id].world_matrix
            points.extend(transform_point(matrix, *p) for p in pose.meshes[key].positions)
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        with self.document.command_group("Generate and fit character rig"):
            root = RigService(self.document).template(template)
            rig = next(r for r in self.scene.skeletons if any(b.id == root for b in r.bones))
            pose = self.document.animation.pose
            ends = [
                transform_point(pose.nodes[b.id].world_matrix, x, 0)
                for b in rig.bones
                for x in (0, b.length)
            ]
            rx, ry = [p[0] for p in ends], [p[1] for p in ends]
            factor = (
                0.9
                * scale
                * min(
                    max(1, max(xs) - min(xs)) / max(1, max(rx) - min(rx)),
                    max(1, max(ys) - min(ys)) / max(1, max(ry) - min(ry)),
                )
            )
            dx = (max(xs) + min(xs)) / 2 - (max(rx) + min(rx)) / 2 * factor
            dy = (max(ys) + min(ys)) / 2 - (max(ry) + min(ry)) / 2 * factor
            bones = tuple(
                replace(
                    b,
                    length=b.length * factor,
                    transform=replace(
                        b.transform,
                        x=b.transform.x * factor + (dx if b.parent_id is None else 0),
                        y=b.transform.y * factor + (dy if b.parent_id is None else 0),
                    ),
                )
                for b in rig.bones
            )
            self.commit(
                "Fit rig to artwork",
                skeletons=tuple(
                    replace(r, bones=bones) if r.id == rig.id else r for r in self.scene.skeletons
                ),
            )
        return rig.id

    def generate_meshes(
        self, meshes: tuple[str, ...], columns: int, rows: int, *, replace_edits: bool = False
    ) -> None:
        """Regenerate pristine guide meshes or explicitly approved replacements atomically."""
        if not meshes:
            raise ProjectError("Select artwork meshes first.")
        with self.document.command_group("Generate character meshes"):
            for key in meshes:
                mesh = self.mesh(key)
                stages = any(d.owner_id == key for d in self.scene.deformers)
                animated = any(
                    t.owner_id in {v.id for v in mesh.vertices}
                    for line in self.scene.timelines
                    for t in line.tracks
                )
                if not replace_edits and (
                    stages or animated or mesh.extra.get("wizard_pristine") != fingerprint(mesh)
                ):
                    raise ProjectError(
                        "Mesh contains edits or weights. Keep it, or explicitly enable replacement."
                    )
                self.regenerate(key, columns, rows, discard_edits=True)
                mesh = self.mesh(key)
                self.replace_mesh(
                    replace(mesh, extra={**mesh.extra, "wizard_pristine": fingerprint(mesh)})
                )

    def bind_parts(
        self, rig_id: str, meshes: tuple[str, ...], assignments: Mapping[str, str] | None = None
    ) -> None:
        """Bind parts to chosen bones or all template bones with editable weights."""
        rig = next((r for r in self.scene.skeletons if r.id == rig_id), None)
        if rig is None or not meshes:
            raise ProjectError("Choose a generated rig and artwork parts to bind.")
        bones = tuple(b.id for b in rig.bones)
        if assignments and (
            not set(assignments) <= set(meshes) or not set(assignments.values()) <= set(bones)
        ):
            raise ProjectError("Part assignments must use selected meshes and bones in this rig.")
        with self.document.command_group("Bind character parts"):
            for key in meshes:
                self.bind(key, (assignments[key],) if assignments and key in assignments else bones)
            objects = tuple(self.mesh(key).object_id for key in meshes)
            self.commit(
                "Link character artwork",
                characters=tuple(
                    replace(
                        c,
                        object_ids=tuple(
                            dict.fromkeys((*c.object_ids, *(key for key in objects if key)))
                        ),
                        mesh_ids=tuple(dict.fromkeys((*c.mesh_ids, *meshes))),
                    )
                    if c.skeleton_id == rig_id
                    else c
                    for c in self.scene.characters
                ),
            )

    def test_pose(self, bone_id: str, angle: float) -> ScenePose:
        """Evaluate a disposable rotation offset and deformed meshes without history."""
        if not -180 <= number(angle) <= 180:
            raise ProjectError("Test deflection must stay within −180 to 180 degrees.")
        RigService(self.document).editable(bone_id)
        scratch = self.document.fork()
        frame = scratch.animation.pose.frame
        rest = scratch.animation.pose.nodes[bone_id].local.rotation
        from rigora.application_services.animation_editing import AnimationEditingService

        AnimationEditingService(scratch).key(bone_id, "transform.rotation", frame, rest + angle)
        return scratch.animation.pose

    def share(
        self,
        path: Path,
        *,
        name: str = "My character",
        author: str = "",
        license: str = "All rights reserved",
        overwrite: bool = False,
    ) -> None:
        """Export the current assembled scene as a self-contained editable content template."""
        ContentService(self.document).export_own(
            path, name, author or "Unknown author", license, overwrite=overwrite
        )
