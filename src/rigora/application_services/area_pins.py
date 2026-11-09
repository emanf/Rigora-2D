"""Object-relative and bone-attached artwork anchors with undoable setup operations."""

import math
from dataclasses import replace
from typing import Any

from rigora.application_services.meshes import MeshService
from rigora.domain.entities import Mesh
from rigora.domain.geometry import affine, inverse, multiply, transform_point
from rigora.domain.mesh_geometry import Point
from rigora.domain.project import ProjectError


class AreaPinService(MeshService):
    """Author soft image anchors without changing ordinary skin weights or rig constraints."""

    def editable_pin_mesh(self, mesh_id: str) -> Mesh:
        """Apply the same Object/layer locks to service clients and viewport authoring."""
        from rigora.application_services.scene_editing import SceneEditingService

        mesh = self.mesh(mesh_id)
        locks = SceneEditingService(self.document)
        if locks.locked(mesh_id) or mesh.object_id and locks.locked(mesh.object_id):
            raise ProjectError("Unlock the artwork before editing its pins.")
        return mesh

    def pin_binding(self, mesh_id: str, bone_id: str | None) -> dict[str, Any]:
        """Capture an explicit bone or the enclosing Object's kinematic coordinate frame.

        The serialized bone_id/bone_bind fields retain legacy pack compatibility;
        target_kind distinguishes new Object targets from original bone targets.
        """
        from rigora.application_services.characters import CharacterService

        pose = self.document.animation.pose
        mesh = self.mesh(mesh_id)
        if bone_id is None:
            root = CharacterService(self.document).object_root(mesh_id)
            target = root.id if root else mesh.object_id
            kind = "object"
        else:
            target, kind = bone_id, "bone"
            characters = CharacterService(self.document)
            artwork_owner, bone_owner = (
                characters.object_root(mesh_id),
                characters.object_root(target),
            )
            if artwork_owner and bone_owner and artwork_owner.id != bone_owner.id:
                raise ProjectError("Choose a bone belonging to this artwork's Object.")
        node = pose.nodes.get(target or "")
        if node is None or kind == "bone" and node.kind != "bone":
            raise ProjectError("Choose an existing attachment target for the image-area pin.")
        binding = node.world_matrix
        if kind == "bone":
            stage = next(
                (d for d in self.scene.deformers if d.owner_id == mesh_id and d.kind == "skinning"),
                None,
            )
            group = stage.parameters.get("object_group") if stage else None
            if group and group in pose.nodes:
                assert stage is not None
                delta = multiply(
                    pose.nodes[group].world_matrix,
                    inverse(tuple(stage.parameters["object_group_bind"])),
                )
                binding = multiply(delta, binding)
        return {
            "bone_id": target,
            "target_kind": kind,
            "bone_bind": binding,
            "object_bind": pose.nodes[str(mesh.object_id)].world_matrix,
        }

    def area_pin_at(
        self,
        mesh_id: str,
        scene_point: Point,
        bone_id: str | None = None,
        radius: float = 50,
        strength: float = 1,
    ) -> str:
        """Map a click on evaluated artwork back to its bind mesh before adding a pin.

        Barycentric inversion supports posed/rotated meshes rather than assuming
        that displayed pixels are still at their undeformed source coordinates.
        The resulting anchor captures the displayed position without a pose jump.
        """
        from rigora.domain.mesh_geometry import barycentric

        mesh = self.editable_pin_mesh(mesh_id)
        pose = self.document.animation.pose
        if not mesh.object_id or mesh.id not in pose.meshes:
            raise ProjectError("Choose visible bound artwork before adding a pin.")
        local = transform_point(inverse(pose.nodes[mesh.object_id].world_matrix), *scene_point)
        vertices = {v.id: (v.x, v.y) for v in mesh.vertices}
        evaluated = dict(
            zip((v.id for v in mesh.vertices), pose.meshes[mesh.id].positions, strict=True)
        )
        for face in mesh.triangles:
            try:
                weights = barycentric(local, *(evaluated[k] for k in face))
            except ProjectError:
                continue
            if min(weights) >= -1e-8:
                source = tuple(
                    sum(w * vertices[k][axis] for w, k in zip(weights, face, strict=True))
                    for axis in (0, 1)
                )
                with self.document.command_group("Add image-area pin"):
                    key = self.add_area_pin(
                        mesh_id, (source[0], source[1]), bone_id, radius, strength
                    )
                    pinned = self.mesh(mesh_id)
                    pins = [dict(p) for p in pinned.extra["area_pins"]]
                    for pin in pins:
                        if pin["vertex_id"] == key:
                            pin["object_bind"] = multiply(
                                tuple(pin["object_bind"]),
                                affine(local[0] - source[0], local[1] - source[1], 0, 1, 1, 0, 0),
                            )
                    self.replace_mesh(
                        replace(pinned, extra={**pinned.extra, "area_pins": pins}),
                        "Capture displayed pin position",
                    )
                return key
        raise ProjectError("Click inside the selected artwork's evaluated mesh.")

    def add_area_pin(
        self,
        mesh_id: str,
        point: Point,
        bone_id: str | None = None,
        radius: float = 50,
        strength: float = 1,
    ) -> str:
        """Anchor a soft image region to a selected bone or its character root at bind pose.

        Unlike a world-space rig constraint, this anchor follows the character. A vertex
        inserted at the clicked location provides an exact anchor; nearby vertices fade
        smoothly toward their ordinary skinning result. Original weights remain editable.
        """
        if (
            not all(math.isfinite(v) for v in (*point, radius, strength))
            or radius <= 0
            or not 0 <= strength <= 1
        ):
            raise ProjectError("Area pins require a finite point and positive influence radius.")
        mesh = self.editable_pin_mesh(mesh_id)
        stage = next(
            (d for d in self.scene.deformers if d.owner_id == mesh_id and d.kind == "skinning"),
            None,
        )
        if stage is None:
            raise ProjectError("Bind the artwork to bones before adding image-area pins.")
        binding = self.pin_binding(mesh_id, bone_id)
        from rigora.domain.mesh_geometry import barycentric, insert_vertex

        by_id = {v.id: v for v in mesh.vertices}
        if not any(
            min(barycentric(point, *((by_id[k].x, by_id[k].y) for k in face))) >= -1e-8
            for face in mesh.triangles
        ):
            raise ProjectError("Place image-area pins inside the artwork mesh.")
        existing = next((v for v in mesh.vertices if math.dist((v.x, v.y), point) < 1e-7), None)
        if existing:
            vertex_id = existing.id
        else:
            mesh, vertex_id = insert_vertex(mesh, *point)
        assert mesh.object_id is not None
        pin = {
            "vertex_id": vertex_id,
            "x": point[0],
            "y": point[1],
            "radius": radius,
            "strength": strength,
            **binding,
        }
        self.replace_mesh(
            replace(
                mesh,
                extra={
                    **mesh.extra,
                    "area_pins": [
                        *(
                            p
                            for p in mesh.extra.get("area_pins", ())
                            if p["vertex_id"] != vertex_id
                        ),
                        pin,
                    ],
                },
            ),
            "Add image-area pin",
        )
        return vertex_id

    def update_area_pins(
        self,
        mesh_id: str,
        vertices: tuple[str, ...],
        *,
        radius: float | None = None,
        strength: float | None = None,
        bone_id: str | None = "",
    ) -> None:
        """Edit selected influences once; an empty target keeps attachment, None selects Object.

        Attachment changes capture the displayed anchor to avoid a setup jump. Radius
        and strength edits retain the original attachment frame and ordinary weights.
        """
        if radius is not None and (not math.isfinite(radius) or radius <= 0):
            raise ProjectError("Pin radius must be finite and positive.")
        if strength is not None and (not math.isfinite(strength) or not 0 <= strength <= 1):
            raise ProjectError("Pin strength must be between zero and one.")
        mesh = self.editable_pin_mesh(mesh_id)
        chosen = set(vertices)
        pose = self.document.animation.pose
        positions = dict(
            zip((v.id for v in mesh.vertices), pose.meshes[mesh_id].positions, strict=True)
        )
        pins = []
        for old in mesh.extra.get("area_pins", ()):
            pin = dict(old)
            if pin["vertex_id"] in chosen:
                if radius is not None:
                    pin["radius"] = radius
                if strength is not None:
                    pin["strength"] = strength
                if bone_id != "":
                    pin.update(self.pin_binding(mesh_id, bone_id))
                    x, y = positions[pin["vertex_id"]]
                    pin["object_bind"] = multiply(
                        pin["object_bind"], affine(x - pin["x"], y - pin["y"], 0, 1, 1, 0, 0)
                    )
            pins.append(pin)
        updated = replace(mesh, extra={**mesh.extra, "area_pins": pins})
        if updated != mesh:
            self.replace_mesh(updated, "Edit image-area pins")

    def move_area_pin(self, mesh_id: str, vertex_id: str, scene_point: Point) -> str:
        """Relocate an anchor in displayed artwork, retaining source vertices and skin weights.

        A new interpolated vertex supplies the new exact anchor. The original stays in
        the mesh so existing vertex keys and topology references remain valid.
        """
        mesh = self.editable_pin_mesh(mesh_id)
        pin = next(
            (p for p in mesh.extra.get("area_pins", ()) if p["vertex_id"] == vertex_id), None
        )
        if pin is None:
            raise ProjectError("Choose an existing image-area pin.")
        target = None if pin.get("target_kind") == "object" else str(pin["bone_id"])
        with self.document.command_group("Move image-area pin"):
            key = self.area_pin_at(
                mesh_id, scene_point, target, pin["radius"], pin.get("strength", 1)
            )
            if key != vertex_id and any(
                p["vertex_id"] == key for p in mesh.extra.get("area_pins", ())
            ):
                raise ProjectError("Move the pin away from the existing anchor.")
            if key != vertex_id:
                self.remove_area_pins(mesh_id, (vertex_id,))
        return key

    def remove_area_pins(self, mesh_id: str, vertices: tuple[str, ...] = ()) -> None:
        """Release selected image anchors, or all anchors when no vertices are selected."""
        mesh = self.editable_pin_mesh(mesh_id)
        pins = [
            p
            for p in mesh.extra.get("area_pins", ())
            if vertices and p["vertex_id"] not in vertices
        ]
        self.replace_mesh(
            replace(mesh, extra={**mesh.extra, "area_pins": pins}), "Release image-area pins"
        )
