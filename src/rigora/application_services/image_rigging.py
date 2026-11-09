"""Single-image free-bone authoring through existing subdivision and skinning commands."""

from dataclasses import replace
from typing import Any

from rigora.application_services.rigging import RigService
from rigora.application_services.skinning import SkinService
from rigora.domain.entities import Character, Skeleton
from rigora.domain.geometry import inverse, transform_point
from rigora.domain.project import ProjectError
from rigora.domain.validation import json_copy
from rigora.engine.subdivision import subdivide


class ImageRigService(SkinService):
    """Keep an image's explicitly chosen rig automatically bound while adding bones."""

    def convert(self, mesh_ids: tuple[str, ...], name: str = "") -> str:
        """Convert selected solid images to one character with an empty, editable skeleton."""
        if not mesh_ids:
            raise ProjectError("Select at least one image to convert to a character.")
        meshes = tuple(self.mesh(k) for k in dict.fromkeys(mesh_ids))
        existing = {m.extra.get("rig_skeleton_id") for m in meshes} - {None}
        if len(existing) > 1:
            raise ProjectError(
                "These images belong to different characters. Reattach them explicitly."
            )
        if existing:
            actor = next((c for c in self.scene.characters if c.skeleton_id in existing), None)
            if actor:
                self.add_parts(actor.id, mesh_ids)
                return actor.id
        root = meshes[0]
        rig = next((r for r in self.scene.skeletons if r.id in existing), None) or Skeleton(
            name=(name or root.name.removesuffix(" mesh"))[:190] + " rig"
        )
        character = Character(
            name=(name or root.name.removesuffix(" mesh"))[:200],
            skeleton_id=rig.id,
            object_ids=tuple(m.object_id for m in meshes if m.object_id),
            mesh_ids=tuple(m.id for m in meshes),
            extra={
                "root_object_id": root.object_id,
                "rig_origin": (
                    root.extra.get("image_width", 1) / 2,
                    root.extra.get("image_height", 1) * 0.9,
                ),
            },
        )
        selected = set(mesh_ids)
        self.commit(
            "Convert solid artwork to character",
            skeletons=self.scene.skeletons if existing else (*self.scene.skeletons, rig),
            characters=(*self.scene.characters, character),
            meshes=tuple(
                replace(m, extra={**m.extra, "rig_skeleton_id": rig.id}) if m.id in selected else m
                for m in self.scene.meshes
            ),
        )
        return character.id

    def add_parts(self, character_id: str, mesh_ids: tuple[str, ...]) -> None:
        """Add solid images to a character and bind them when it already has a skeleton."""
        from rigora.application_services.scene_editing import SceneEditingService

        actor = next((c for c in self.scene.characters if c.id == character_id), None)
        if actor is None:
            raise ProjectError("Choose a character first.")
        parts = tuple(self.mesh(k) for k in dict.fromkeys(mesh_ids))
        selection = SceneEditingService(self.document)
        if selection.locked(character_id) or any(
            selection.locked(str(part.object_id)) for part in parts
        ):
            raise ProjectError("Unlock the character and image parts before assigning them.")
        if any(m.extra.get("rig_skeleton_id") not in (None, actor.skeleton_id) for m in parts):
            raise ProjectError(
                "Reattach parts from another character with an explicit bone target."
            )
        rig = next(r for r in self.scene.skeletons if r.id == actor.skeleton_id)
        with self.document.command_group("Add character parts"):
            self.commit(
                "Assign character parts",
                characters=tuple(
                    replace(
                        c,
                        mesh_ids=tuple(dict.fromkeys((*c.mesh_ids, *(m.id for m in parts)))),
                        object_ids=tuple(
                            dict.fromkeys(
                                (*c.object_ids, *(m.object_id for m in parts if m.object_id))
                            )
                        ),
                    )
                    if c.id == actor.id
                    else c
                    for c in self.scene.characters
                ),
                meshes=tuple(
                    replace(m, extra={**m.extra, "rig_skeleton_id": rig.id})
                    if m.id in mesh_ids
                    else m
                    for m in self.scene.meshes
                ),
            )
            if rig.bones:
                for part in parts:
                    if part.id not in actor.mesh_ids:
                        self.bind_image(part.id, rig.bones[0].id)

    def without_parts(self, actor: Character, mesh_ids: set[str]) -> Character:
        """Preserve a root's world position when its anchor image leaves a character."""
        objects = {m.object_id for m in self.scene.meshes if m.id in mesh_ids}
        remaining = tuple(k for k in actor.object_ids if k not in objects)
        extra: dict[str, Any] = json_copy(actor.extra)
        if extra.get("root_object_id") in objects:
            world = RigService(self.document).origin(actor.id)
            extra.pop("root_object_id", None)
            extra["rig_origin"] = world
            if remaining:
                node = self.document.animation.pose.nodes.get(remaining[0])
                if node:
                    extra["root_object_id"] = remaining[0]
                    extra["rig_origin"] = transform_point(inverse(node.world_matrix), *world)
        for group in extra.get("outfits", ()):
            for variant in group.get("variants", ()):
                variant["meshes"] = [k for k in variant["meshes"] if k not in mesh_ids]
        return replace(
            actor,
            mesh_ids=tuple(k for k in actor.mesh_ids if k not in mesh_ids),
            object_ids=remaining,
            extra=extra,
        )

    def detach(self, mesh_ids: tuple[str, ...], *, cleanup_physics: bool = True) -> None:
        """Release skinning and pins, retaining the character and its editable bones."""
        from rigora.application_services.bindings import BindingService

        keys = set(mesh_ids)
        for key in keys:
            self.mesh(key)
        if not keys:
            return
        bindings = BindingService(self.document)
        with self.document.command_group("Unbind artwork"):
            bindings.remove_relationships(
                tuple(
                    row.id
                    for row in bindings.relationships()
                    if row.source in keys and row.kind in ("Skin", "Area pin")
                ),
                cleanup_physics=cleanup_physics,
            )
            changed = []
            for mesh in self.scene.meshes:
                if mesh.id not in keys:
                    changed.append(mesh)
                    continue
                extra = json_copy(mesh.extra)
                extra.pop("rig_skeleton_id", None)
                extra.pop("area_pins", None)
                extra["auto_bind_artwork"] = False
                changed.append(
                    replace(
                        mesh,
                        extra=extra,
                        vertices=tuple(replace(v, weights={}) for v in mesh.vertices),
                    )
                )
            self.commit("Keep artwork unbound", meshes=tuple(changed))

    def prepare(self, mesh_id: str) -> None:
        """Refine untouched import grids once, preserving edited topology, stages and keys."""
        mesh = self.mesh(mesh_id)
        subdivision = mesh.extra.get("subdivision", {})
        if subdivision.get("mode", "grid") != "grid" or len(mesh.vertices) > 25:
            return
        if (
            any(d.owner_id == mesh_id for d in self.scene.deformers)
            or any(v.pinned or v.protected or v.weights for v in mesh.vertices)
            or any(
                t.owner_id in {v.id for v in mesh.vertices}
                for tl in self.scene.timelines
                for t in tl.tracks
            )
        ):
            return
        width, height = mesh.extra.get("image_width"), mesh.extra.get("image_height")
        if not isinstance(width, (int, float)) or not isinstance(height, (int, float)):
            # Authored vector parts are valid binding surfaces, but are not
            # canonical import grids eligible for automatic topology replacement.
            return
        # Only the canonical, untouched import grid is eligible for automatic refinement.
        from rigora.domain.mesh_geometry import grid_mesh

        original = grid_mesh(
            width, height, subdivision.get("columns", 4), subdivision.get("rows", 4)
        )
        indices = {v.id: i for i, v in enumerate(mesh.vertices)}
        expected_indices = {v.id: i for i, v in enumerate(original.vertices)}
        if [(v.x, v.y, v.uv) for v in mesh.vertices] != [
            (v.x, v.y, v.uv) for v in original.vertices
        ] or [tuple(indices[k] for k in face) for face in mesh.triangles] != [
            tuple(expected_indices[k] for k in face) for face in original.triangles
        ]:
            return
        generated = subdivide(width, height, mode="full", density=8, alignment=1)
        self.replace_mesh(
            replace(
                mesh,
                vertices=generated.vertices,
                triangles=generated.triangles,
                extra={**mesh.extra, "subdivision": {"mode": "full", "density": 8, "alignment": 1}},
            ),
            "Prepare image deformation mesh",
        )

    def bind_image(
        self, mesh_id: str, bone_id: str, *, rigid: bool = False, automatic: bool = False
    ) -> None:
        """Bind a complete skeleton and record image ownership without altering source art."""
        RigService(self.document).bone(bone_id)
        rig = next(r for r in self.scene.skeletons if any(b.id == bone_id for b in r.bones))
        with self.document.command_group("Bind image rig"):
            self.prepare(mesh_id)
            excluded = self.mesh(mesh_id).extra.get("unbound_bones", ()) if automatic else ()
            members = (
                (bone_id,)
                if rigid
                else tuple(
                    b.id for b in rig.bones if b.id not in excluded and not b.extra.get("rig_root")
                )
            )
            if not members:
                return
            self.bind(mesh_id, members, automatic=automatic)
            mesh = self.mesh(mesh_id)
            extra = dict(mesh.extra)
            if not automatic:
                extra.pop("unbound_bones", None)
            self.replace_mesh(
                replace(
                    mesh,
                    extra={
                        **extra,
                        "rig_skeleton_id": rig.id,
                        "auto_bind_artwork": True,
                    },
                )
            )
            characters = []
            for actor in self.scene.characters:
                if actor.skeleton_id != rig.id:
                    characters.append(self.without_parts(actor, {mesh_id}))
                    continue
                extra = json_copy(actor.extra)
                if mesh.object_id and not actor.object_ids:
                    world = RigService(self.document).origin(actor.id)
                    matrix = self.document.animation.pose.nodes[mesh.object_id].world_matrix
                    extra.update(
                        root_object_id=mesh.object_id,
                        rig_origin=transform_point(inverse(matrix), *world),
                    )
                characters.append(
                    replace(
                        actor,
                        extra=extra,
                        name=mesh.name.removesuffix(" mesh")
                        if actor.name == "Character"
                        else actor.name,
                        object_ids=tuple(
                            dict.fromkeys(
                                (*actor.object_ids, *((mesh.object_id,) if mesh.object_id else ()))
                            )
                        ),
                        mesh_ids=tuple(dict.fromkeys((*actor.mesh_ids, mesh.id))),
                    )
                )
            if not any(c.skeleton_id == rig.id for c in characters):
                matrix = self.document.animation.pose.nodes[str(mesh.object_id)].world_matrix
                root_bone = next(b for b in rig.bones if b.parent_id is None)
                world = self.document.animation.pose.nodes[root_bone.id].world_matrix[4:]
                characters.append(
                    Character(
                        name=mesh.name.removesuffix(" mesh"),
                        skeleton_id=rig.id,
                        object_ids=(str(mesh.object_id),),
                        mesh_ids=(mesh.id,),
                        extra={
                            "root_object_id": mesh.object_id,
                            "rig_origin": transform_point(inverse(matrix), *world),
                        },
                    )
                )
            self.commit(
                "Assign image rig ownership",
                characters=tuple(characters),
            )

    def draw_bone(
        self,
        mesh_id: str,
        start: tuple[float, float],
        end: tuple[float, float],
        parent_id: str | None = None,
    ) -> str:
        """Draw and reweight the target image atomically; unrelated image rigs stay separate."""
        mesh = self.mesh(mesh_id)
        actor = next((c for c in self.scene.characters if mesh_id in c.mesh_ids), None)
        rig_id = mesh.extra.get("rig_skeleton_id") or (actor.skeleton_id if actor else None)
        stage = next(
            (d for d in self.scene.deformers if d.owner_id == mesh_id and d.kind == "skinning"),
            None,
        )
        if stage and not rig_id:
            members = stage.parameters.get("bind_matrices", {})
            rig_id = next(
                (r.id for r in self.scene.skeletons if any(b.id in members for b in r.bones)), None
            )
        if (
            parent_id
            and rig_id
            and not any(
                r.id == rig_id and any(b.id == parent_id for b in r.bones)
                for r in self.scene.skeletons
            )
        ):
            raise ProjectError(
                "The selected parent belongs to another image rig. Choose that artwork first."
            )
        with self.document.command_group("Draw image bone"):
            if not rig_id and not parent_id:
                character_id = self.convert((mesh_id,))
                rig_id = next(c.skeleton_id for c in self.scene.characters if c.id == character_id)
            key = RigService(self.document).create_bone(
                start, end, parent_id, skeleton_id=rig_id, new_skeleton=not rig_id and not parent_id
            )
            character = next(
                c for c in self.scene.characters if c.skeleton_id == self.bone_skeleton(key)
            )
            for target in character.mesh_ids or (mesh_id,):
                if self.mesh(target).extra.get("auto_bind_artwork", True):
                    self.bind_image(target, key, automatic=True)
        return key

    def bone_skeleton(self, bone_id: str) -> str:
        """Resolve rig ownership without relying on the first skeleton in the scene."""
        return next(r.id for r in self.scene.skeletons if any(b.id == bone_id for b in r.bones))
