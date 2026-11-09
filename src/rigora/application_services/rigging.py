"""Undoable rest-rig authoring over the canonical document and animation geometry."""

import math
from collections.abc import Mapping
from dataclasses import replace
from typing import Any
from uuid import uuid4

from rigora.application_services.commands import ScenePatch
from rigora.application_services.documents import DocumentService
from rigora.application_services.foot_contacts import edited_contacts
from rigora.domain.entities import (
    Bone,
    Character,
    Constraint,
    Group,
    SceneObject,
    Skeleton,
    Transform,
)
from rigora.domain.geometry import Matrix, affine, decompose, inverse, multiply, transform_point
from rigora.domain.mesh_geometry import normalize_weights
from rigora.domain.project import Project, ProjectError, Scene
from rigora.engine.chain_pull import pull_chain, selected_roots
from rigora.engine.evaluation import SceneEvaluator
from rigora.engine.sampling import number
from rigora.engine.state import ScenePose


def from_matrix(matrix: Matrix, pivot: Transform | None = None) -> Transform:
    """Convert affine geometry to an authoring transform without losing a supplied pivot."""
    x, y, rotation, sx, sy, px, py = decompose(
        matrix, pivot.pivot_x if pivot else 0, pivot.pivot_y if pivot else 0
    )
    return Transform(x=x, y=y, rotation=rotation, scale_x=sx, scale_y=sy, pivot_x=px, pivot_y=py)


class RigService:
    """Edit the first scene through validated atomic commands, preserving stable identities."""

    def __init__(self, document: DocumentService) -> None:
        """Attach to a document without copying its model or owning UI selection."""
        self.document = document
        self._bone_cache: tuple[Scene, dict[str, Bone]] | None = None
        from rigora.application_services.scene_editing import SceneEditingService

        self._selection_locks = SceneEditingService(document)

    @property
    def scene(self) -> Scene:
        """Resolve the current immutable scene after every command or undo."""
        if self.document.project is None:
            raise ProjectError("Create or open a project before rigging.")
        return self.document.scene

    def commit(self, label: str, **changes: Any) -> None:
        """Commit changed scene collections as one undo step after full graph validation."""
        scene = self.scene
        self.document.execute(
            ScenePatch(label, scene.id, {key: getattr(scene, key) for key in changes}, changes)
        )

    def bone(self, key: str) -> Bone:
        """Resolve a bone from a revision-bound index, including during ancestor lock checks."""
        scene = self.scene
        if self._bone_cache is None or self._bone_cache[0] is not scene:
            self._bone_cache = (
                scene,
                {bone.id: bone for rig in scene.skeletons for bone in rig.bones},
            )
        if key in self._bone_cache[1]:
            return self._bone_cache[1][key]
        raise ProjectError("The selected bone no longer exists.")

    def ensure_root(self, skeleton_id: str) -> str:
        """Upgrade an existing rig with one reversible, identity master-control insertion."""
        from rigora.domain.rig_roots import rooted_skeleton

        source = next((r for r in self.scene.skeletons if r.id == skeleton_id), None)
        if source is None:
            raise ProjectError("Choose an existing skeleton for its Rig Root.")
        rooted = rooted_skeleton(source)
        if rooted is not source:
            self.commit(
                "Add Rig Root",
                skeletons=tuple(rooted if r.id == skeleton_id else r for r in self.scene.skeletons),
            )
        return next(b.id for b in rooted.bones if b.extra.get("rig_root"))

    def prepare_object_rig(self, owner_id: str) -> str:
        """Expose an owned Skeleton and Rig Root before the first drawing gesture.

        Existing rigs retain their transforms. A new empty rig starts at the
        artwork's local center, or the empty Object's origin. No skin binding is
        added until a deforming bone is drawn or artwork is explicitly bound.
        """
        from rigora.application_services.characters import CharacterService
        from rigora.domain.rig_roots import rooted_skeleton

        if self._selection_locks.locked(owner_id):
            raise ProjectError("Unlock the Object before adding its skeleton.")
        characters = CharacterService(self.document)
        members = characters.members(owner_id)
        record = characters.record(owner_id)
        rig = next(
            (
                r
                for r in self.scene.skeletons
                if r.id in members
                or r.extra.get("object_id") == owner_id
                or isinstance(record, Character)
                and r.id == record.skeleton_id
            ),
            None,
        )
        if rig is not None and rig.bones:
            return self.ensure_root(rig.id)
        pose = self.document.animation.pose
        points = [
            transform_point(pose.nodes[str(mesh.object_id)].world_matrix, *point)
            for key, mesh in pose.meshes.items()
            if key in members
            for point in mesh.positions
        ]
        x = (min(p[0] for p in points) + max(p[0] for p in points)) / 2 if points else 0
        y = (min(p[1] for p in points) + max(p[1] for p in points)) / 2 if points else 0
        anchor = str(
            record.extra.get("object_id") or record.extra.get("root_object_id") or owner_id
        )
        basis = pose.nodes[anchor].world_matrix if anchor in pose.nodes else (1, 0, 0, 1, 0, 0)
        source = rig or Skeleton(name="Skeleton")
        rooted = rooted_skeleton(
            replace(source, extra={**source.extra, "object_id": anchor, "library_bind": basis})
        )
        rig = rooted
        root = replace(rig.bones[0], transform=Transform(x=x, y=y))
        self.commit(
            "Add skeleton",
            skeletons=tuple(r for r in self.scene.skeletons if r.id != rig.id)
            + (replace(rig, bones=(root,)),),
            meshes=tuple(
                replace(mesh, extra={**mesh.extra, "rig_skeleton_id": rig.id})
                if mesh.id in members
                else mesh
                for mesh in self.scene.meshes
            ),
        )
        return root.id

    def rest_pose(self) -> ScenePose:
        """Evaluate authored rest transforms without animation tracks or constraints."""
        session = self.document._animation
        return SceneEvaluator(
            replace(self.scene, clips=(), constraints=()),
            apply_joint_limits=False,
            scope=self.document.animation_scope,
            local_object=self.document.animation_context,
            deformation_plan=session.evaluator.deformation if session else None,
        ).evaluate(0)

    def preview_pose(self) -> ScenePose:
        """Evaluate rest data plus the document's configured constraint solvers for rig editing."""
        session = self.document._animation
        return SceneEvaluator(
            replace(self.scene, clips=()),
            solvers=self.document.constraint_solvers,
            deformers=self.document.deformer_solvers,
            scope=self.document.animation_scope,
            local_object=self.document.animation_context,
            deformation_plan=session.evaluator.deformation if session else None,
        ).evaluate(0)

    @staticmethod
    def control_scene(scene: Scene) -> Scene:
        """Keep the transform graph for gesture solving without artwork or timeline payloads."""
        controls = {
            r.id
            for r in (
                *scene.groups,
                *scene.objects,
                *(b for rig in scene.skeletons for b in rig.bones),
            )
        }
        return Scene(
            id=scene.id,
            settings=scene.settings,
            layers=scene.layers,
            groups=scene.groups,
            objects=scene.objects,
            skeletons=scene.skeletons,
            constraints=tuple(
                c
                for c in scene.constraints
                if c.owner_id in controls and (c.target_id is None or c.target_id in controls)
            ),
        )

    def editable(self, key: str) -> Bone:
        """Reject edits beneath a locked ancestor while allowing explicit unlock operations."""
        bone = self.bone(key)
        if self._selection_locks.locked(key):
            raise ProjectError("This bone or its character is locked; unlock it before editing.")
        cursor = bone
        while True:
            if cursor.locked:
                raise ProjectError(f"Bone '{cursor.name}' is locked; unlock it before editing.")
            if cursor.parent_id is None:
                return bone
            cursor = self.bone(cursor.parent_id)

    def _replace_bones(self, label: str, replacements: dict[str, Bone]) -> None:
        """Replace bones and their edited standing contacts in one reversible command."""
        transforms = {
            key: bone.transform
            for key, bone in replacements.items()
            if bone.transform != self.bone(key).transform
            and bone.parent_id == self.bone(key).parent_id
        }
        contacts = (
            edited_contacts(self.scene, self.preview_pose(), transforms, self.scene.constraints)
            if transforms
            else {}
        )
        for key in contacts:
            if self._selection_locks.locked(key):
                raise ProjectError("Unlock the standing contact control before posing its foot.")
        controls = {
            field: tuple(
                replace(r, transform=contacts[r.id]) if r.id in contacts else r
                for r in getattr(self.scene, field)
            )
            for field in ("objects", "groups")
            if any(r.id in contacts for r in getattr(self.scene, field))
        }
        self.commit(
            label,
            skeletons=tuple(
                replace(rig, bones=tuple(replacements.get(b.id, b) for b in rig.bones))
                for rig in self.scene.skeletons
            ),
            **controls,
        )

    def unique_name(self, requested: str) -> str:
        """Keep names predictable and distinct without using them as persistent references."""
        names = {b.name for rig in self.scene.skeletons for b in rig.bones}
        candidate = requested[:190]
        index = 1
        while candidate in names:
            candidate = f"{requested[:180]}.{index:03d}"
            index += 1
        return candidate

    def origin(self, character_id: str | None = None) -> tuple[float, float]:
        """Read the internal default drawing position without exposing a viewport control."""
        owner = next((c for c in self.scene.characters if c.id == character_id), None)
        default = (self.scene.settings.width / 2, self.scene.settings.height * 0.85)
        if character_id and owner is None:
            raise ProjectError("The character root no longer exists.")
        if owner:
            rig = next((r for r in self.scene.skeletons if r.id == owner.skeleton_id), None)
            root = (
                next((b for b in rig.bones if not b.extra.get("rig_root")), None) if rig else None
            )
            if root:
                default = root.transform.x, root.transform.y
        point = (owner.extra if owner else self.scene.extra).get("rig_origin", default)
        if not isinstance(point, (tuple, list)) or len(point) != 2:
            raise ProjectError("The rig origin must contain two finite coordinates.")
        result = number(point[0]), number(point[1])
        if owner and owner.extra.get("root_object_id"):
            anchor = self.document.animation.pose.nodes.get(owner.extra["root_object_id"])
            if anchor:
                return transform_point(anchor.world_matrix, *result)
        return result

    def constrain_origin(
        self, x: float, y: float, character_id: str, *, free: bool = False
    ) -> tuple[float, float]:
        """Clamp a default drawing position to artwork unless the caller requests free placement."""
        point = number(x), number(y)
        owner = next((c for c in self.scene.characters if c.id == character_id), None)
        if free or owner is None or not owner.mesh_ids:
            return point
        pose = self.document.animation.pose
        meshes = [
            m for m in self.scene.meshes if m.id in owner.mesh_ids and m.object_id in pose.nodes
        ]
        if len(meshes) == 1:
            mesh = meshes[0]
            matrix = pose.nodes[str(mesh.object_id)].world_matrix
            local = transform_point(inverse(matrix), *point)
            local = (
                min(mesh.extra.get("image_width", 1), max(0, local[0])),
                min(mesh.extra.get("image_height", 1), max(0, local[1])),
            )
            return transform_point(matrix, *local)
        bounds = [
            transform_point(pose.nodes[str(m.object_id)].world_matrix, a, b)
            for m in meshes
            for a in (0, m.extra.get("image_width", 1))
            for b in (0, m.extra.get("image_height", 1))
        ]
        if bounds:
            clamped = tuple(
                min(max(p[i] for p in bounds), max(min(p[i] for p in bounds), point[i]))
                for i in (0, 1)
            )
            return clamped[0], clamped[1]
        return point

    def move_origin(
        self, x: float, y: float, character_id: str | None = None, *, free: bool = False
    ) -> None:
        """Store an internal default drawing position without changing skeletal geometry."""
        point = self.constrain_origin(x, y, character_id or "", free=free)
        if point == self.origin(character_id):
            return
        if character_id:
            owner = next(c for c in self.scene.characters if c.id == character_id)
            anchor_id = owner.extra.get("root_object_id")
            anchor = self.document.animation.pose.nodes.get(str(anchor_id or ""))
            if anchor:
                point = transform_point(inverse(anchor.world_matrix), *point)
            self.commit(
                "Move character root",
                characters=tuple(
                    replace(c, extra={**c.extra, "rig_origin": point})
                    if c.id == character_id
                    else c
                    for c in self.scene.characters
                ),
            )
        else:
            self.commit("Move rig origin", extra={**self.scene.extra, "rig_origin": point})

    def create_bone(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        parent_id: str | None = None,
        *,
        skeleton_id: str | None = None,
        new_skeleton: bool = False,
    ) -> str:
        """Create a bone from displayed world endpoints, relative to its visible parent.

        A skeleton ID chooses the character for a new root branch. With no parent,
        new_skeleton starts an independent character rather than extending the first rig.
        """
        scene = self.scene
        rigs = list(scene.skeletons)
        context = self.document.animation_context
        if context and not parent_id and not skeleton_id and not new_skeleton:
            owned = next(
                (
                    r
                    for r in rigs
                    if r.extra.get("object_id") == context
                    or any(c.id == context and c.skeleton_id == r.id for c in scene.characters)
                ),
                None,
            )
            skeleton_id = owned.id if owned else None
            new_skeleton = owned is None
        world_start = start
        if parent_id:
            self.editable(parent_id)
            parent = self.document.animation.pose.nodes[parent_id].world_matrix
            start, end = (
                transform_point(inverse(parent), *start),
                transform_point(inverse(parent), *end),
            )
            index = next(
                i for i, rig in enumerate(rigs) if any(b.id == parent_id for b in rig.bones)
            )
            if skeleton_id and rigs[index].id != skeleton_id:
                raise ProjectError("The selected parent is outside the target skeleton.")
        elif skeleton_id:
            index = next((i for i, r in enumerate(rigs) if r.id == skeleton_id), -1)
            if index < 0:
                raise ProjectError("The image's skeleton no longer exists.")
        elif rigs and not new_skeleton:
            index = 0
        else:
            rigs.append(Skeleton(name="Skeleton"))
            index = len(rigs) - 1
        groups = scene.groups
        if self.document.separated_animation and context is None:
            from rigora.application_services.characters import CharacterService

            actor = next((c for c in scene.characters if c.skeleton_id == rigs[index].id), None)
            root = CharacterService(self.document).object_root(actor.id) if actor else None
            context = root.id if root else actor.id if actor else rigs[index].extra.get("object_id")
            if context is None:
                container = Group(name="Object", extra={"object_container": True})
                groups = (*groups, container)
                context = container.id
        master = next((b for b in rigs[index].bones if b.extra.get("rig_root")), None)
        if parent_id is None and master is not None:
            matrix = self.document.animation.pose.nodes[master.id].world_matrix
            start, end = (
                transform_point(inverse(matrix), *start),
                transform_point(inverse(matrix), *end),
            )
        dx, dy = end[0] - start[0], end[1] - start[1]
        if math.hypot(dx, dy) < 1e-6:
            raise ProjectError("Drag a nonzero bone length in the viewport.")
        rotation = math.degrees(math.atan2(dy, dx))
        interior = max(0.0, 180 - abs((rotation + 180) % 360 - 180))
        bone = Bone(
            name=self.unique_name("Bone"),
            parent_id=parent_id,
            length=math.hypot(dx, dy),
            extra={"minimum_joint_angle": min(30.0, interior)}
            if parent_id and not self.bone(parent_id).extra.get("rig_root")
            else {},
            transform=Transform(x=start[0], y=start[1], rotation=rotation),
        )
        if parent_id is None and master is not None:
            bone = replace(bone, parent_id=master.id)
        rigs[index] = replace(
            rigs[index],
            bones=(*rigs[index].bones, bone),
            extra={**({"object_id": context} if context else {}), **rigs[index].extra},
        )
        from rigora.domain.rig_roots import rooted_skeleton

        rigs[index] = rooted_skeleton(rigs[index])
        characters = scene.characters
        if not any(character.skeleton_id == rigs[index].id for character in characters):
            characters = (
                *characters,
                Character(
                    name="Character",
                    skeleton_id=rigs[index].id,
                    extra={
                        "rig_origin": world_start,
                        **({"object_id": context} if context else {}),
                    },
                ),
            )
        self.commit("Create bone", skeletons=tuple(rigs), characters=characters, groups=groups)
        if context and self.document.animation_context != context:
            from rigora.application_services.characters import CharacterService

            self.document.set_animation_context(
                context, frozenset(CharacterService(self.document).members(context))
            )
        return bone.id

    def set_minimum_joint_angle(self, selected: tuple[str, ...], angle: float) -> None:
        """Save a direct-parent fold limit for selected joints in one undo command.

        Zero disables the limit. Roots have no incoming joint and are ignored.
        Existing projects without a stored limit keep their unrestricted poses.
        """
        angle = number(angle, "Minimum joint angle")
        if not 0 <= angle <= 180:
            raise ProjectError("Minimum joint angle must be from 0 to 180 degrees.")
        changes = {}
        for key in selected:
            bone = self.editable(key)
            if bone.parent_id and bone.extra.get("minimum_joint_angle", 0) != angle:
                changes[key] = replace(bone, extra={**bone.extra, "minimum_joint_angle": angle})
        if changes:
            self._replace_bones("Set minimum joint angle", changes)

    def update(self, key: str, **changes: Any) -> None:
        """Edit bone properties with validation and one reversible history entry."""
        bone = self.bone(key)
        if set(changes) - {"locked", "visible"}:
            self.editable(key)
        if set(changes) - {"name", "length", "transform", "visible", "locked", "color", "group"}:
            raise ProjectError("Unsupported bone property; use topology commands for parenting.")
        if bone.extra.get("rig_root") and changes.get("length", 0) != 0:
            raise ProjectError("Rig Root is a zero-length master control.")
        self._replace_bones("Edit bone", {key: replace(bone, **changes)})

    def set_group(
        self, group: str, *, visible: bool | None = None, locked: bool | None = None
    ) -> None:
        """Change visibility or locking for every bone assigned to a named group."""
        changes: dict[str, Any] = {
            k: v for k, v in (("visible", visible), ("locked", locked)) if v is not None
        }
        self._replace_bones(
            "Edit bone group",
            {
                b.id: replace(b, **changes)
                for rig in self.scene.skeletons
                for b in rig.bones
                if b.group == group
            },
        )

    def reparent(self, key: str, parent_id: str | None) -> None:
        """Change parent while preserving rest world geometry, rejecting cycles and shear."""
        bone = self.editable(key)
        rig = next(r for r in self.scene.skeletons if bone in r.bones)
        if bone.extra.get("rig_root"):
            raise ProjectError("Rig Root stays above its deforming chains.")
        if parent_id is None:
            parent_id = next((b.id for b in rig.bones if b.extra.get("rig_root")), None)
        if parent_id is not None and not any(b.id == parent_id for b in rig.bones):
            raise ProjectError("Choose a parent in the same skeleton.")
        pose = self.rest_pose()
        world = pose.nodes[key].world_matrix
        local = multiply(inverse(pose.nodes[parent_id].world_matrix), world) if parent_id else world
        self._replace_bones(
            "Reparent bone",
            {key: replace(bone, parent_id=parent_id, transform=from_matrix(local, bone.transform))},
        )

    def insert(self, key: str) -> str:
        """Split a bone and insert a child without moving its existing children in rest space."""
        bone = self.editable(key)
        if bone.length < 1e-6:
            raise ProjectError("A zero-length bone cannot be split.")
        pose = self.rest_pose()
        inserted = Bone(
            name=self.unique_name(f"{bone.name}.Split"),
            parent_id=key,
            length=bone.length / 2,
            transform=Transform(x=bone.length / 2),
            group=bone.group,
            color=bone.color,
        )
        world = multiply(pose.nodes[key].world_matrix, inserted.transform.matrix())
        replacements = {key: replace(bone, length=bone.length / 2)}
        for rig in self.scene.skeletons:
            for child in rig.bones:
                if child.parent_id == key:
                    self.editable(child.id)
                    replacements[child.id] = replace(
                        child,
                        parent_id=inserted.id,
                        transform=from_matrix(
                            multiply(inverse(world), pose.nodes[child.id].world_matrix),
                            child.transform,
                        ),
                    )
        rigs = tuple(
            replace(
                rig,
                bones=tuple(replacements.get(b.id, b) for b in rig.bones)
                + ((inserted,) if bone in rig.bones else ()),
            )
            for rig in self.scene.skeletons
        )
        self.commit("Insert bone", skeletons=rigs)
        return inserted.id

    def delete(self, key: str) -> None:
        """Delete a bone with its dependent rig data through the shared batch operation."""
        self.delete_many((key,))

    def delete_many(self, keys: tuple[str, ...], *, remove_rig: bool = False) -> None:
        """Remove selected bones atomically, promote children and repair their references.

        Remaining bound bones receive removed influences (prefer surviving ancestors).
        A mesh with no remaining influences loses its skin stage but retains its art.
        Constraints, bone-owned slots and animation tracks are removed with their owners.
        One undo restores topology, weights, bindings and keys together.
        """
        if not keys:
            return
        removed = set(keys)
        for key in keys:
            self.editable(key)
        from rigora.application_services.scene_attachments import SceneAttachmentService

        scene_links = SceneAttachmentService(self.document)
        if scene_links.references_targets(removed):
            with self.document.command_group("Delete bones and release attachments"):
                scene_links.release_targets(removed)
                self.delete_many(keys, remove_rig=remove_rig)
            return
        scene, pose = self.scene, self.rest_pose()
        if any(
            b.extra.get("rig_root")
            and b.id in removed
            and (not remove_rig or not {member.id for member in rig.bones} <= removed)
            for rig in scene.skeletons
            for b in rig.bones
        ):
            raise ProjectError(
                "Rig Root is protected; delete the whole Object to remove its skeleton."
            )
        bones = {b.id: b for rig in scene.skeletons for b in rig.bones}
        replacements = {}
        parent: str | None
        for bone in bones.values():
            if bone.id in removed or bone.parent_id not in removed:
                continue
            self.editable(bone.id)
            parent = bone.parent_id
            while parent in removed:
                parent = bones[parent].parent_id
            world = pose.nodes[bone.id].world_matrix
            local = multiply(inverse(pose.nodes[parent].world_matrix), world) if parent else world
            replacements[bone.id] = replace(
                bone, parent_id=parent, transform=from_matrix(local, bone.transform)
            )

        def refers(value: Any) -> bool:
            """Find removed bone identities in constraint parameter trees."""
            if isinstance(value, str):
                return value in removed
            if isinstance(value, Mapping):
                return any(refers(k) or refers(v) for k, v in value.items())
            return isinstance(value, (tuple, list)) and any(refers(v) for v in value)

        rules = tuple(
            c
            for c in scene.constraints
            if c.owner_id not in removed and c.target_id not in removed and not refers(c.parameters)
        )
        detached = {}
        for rule in scene.constraints:
            if rule.kind == "parent" and rule.target_id in removed and rule.owner_id not in removed:
                owner = next(
                    (r for r in (*scene.objects, *scene.groups) if r.id == rule.owner_id), None
                )
                if isinstance(owner, (SceneObject, Group)):
                    from rigora.application_services.scene_editing import SceneEditingService

                    if SceneEditingService(self.document).locked(owner.id):
                        raise ProjectError("Unlock attached artwork before deleting its bone.")
                    current = self.document.animation.pose
                    world = current.nodes[owner.id].world_matrix
                    local = (
                        multiply(inverse(current.nodes[owner.parent_id].world_matrix), world)
                        if owner.parent_id
                        else world
                    )
                    detached[owner.id] = replace(
                        owner, transform=from_matrix(local, owner.transform)
                    )
        discarded = removed | {c.id for c in scene.constraints if c not in rules}
        stages = []
        meshes = {m.id: m for m in scene.meshes}
        for stage in scene.deformers:
            if stage.kind != "skinning":
                stages.append(stage)
                continue
            bindings = dict(stage.parameters.get("bind_matrices", {}))
            survivors = {key: value for key, value in bindings.items() if key not in removed}
            if len(survivors) == len(bindings):
                stages.append(stage)
                continue
            mesh = meshes[stage.owner_id]
            transfers: dict[str, str | None] = {}
            for key in removed.intersection(bindings):
                parent = bones[key].parent_id
                while parent and parent not in survivors:
                    parent = bones[parent].parent_id
                transfers[key] = parent or (
                    min(
                        survivors,
                        key=lambda other: math.dist(
                            pose.nodes[key].world_matrix[4:], pose.nodes[other].world_matrix[4:]
                        ),
                    )
                    if survivors
                    else None
                )
            vertices = []
            for vertex in mesh.vertices:
                weights: dict[str, float] = {}
                for key, weight in vertex.weights.items():
                    target = transfers.get(key, key)
                    if target is not None and target not in removed:
                        weights[target] = weights.get(target, 0) + weight
                vertices.append(replace(vertex, weights=normalize_weights(weights, 16)))
            meshes[mesh.id] = replace(mesh, vertices=tuple(vertices))
            if survivors:
                stages.append(
                    replace(stage, parameters={**stage.parameters, "bind_matrices": survivors})
                )
            else:
                discarded.add(stage.id)
        # Weights can also exist without a skin stage; remove their missing references.
        for key, mesh in tuple(meshes.items()):
            meshes[key] = replace(
                mesh,
                extra={
                    **mesh.extra,
                    "area_pins": [
                        p for p in mesh.extra.get("area_pins", ()) if p["bone_id"] not in removed
                    ],
                },
                vertices=tuple(
                    replace(
                        v,
                        weights=normalize_weights(
                            {k: w for k, w in v.weights.items() if k not in removed}, 16
                        ),
                    )
                    if removed.intersection(v.weights)
                    else v
                    for v in mesh.vertices
                ),
            )
        slots = tuple(slot for slot in scene.slots if slot.owner_id not in removed)
        discarded.update(slot.id for slot in scene.slots if slot not in slots)
        attachments = tuple(a for a in scene.attachments if a.slot_id not in discarded)
        discarded.update(a.id for a in scene.attachments if a not in attachments)
        self.commit(
            "Delete selected bones",
            objects=tuple(detached.get(o.id, o) for o in scene.objects),
            groups=tuple(detached.get(g.id, g) for g in scene.groups),
            skeletons=tuple(
                replace(
                    rig,
                    bones=tuple(
                        replacements.get(b.id, b) for b in rig.bones if b.id not in removed
                    ),
                )
                for rig in scene.skeletons
            ),
            meshes=tuple(meshes.values()),
            deformers=tuple(stages),
            constraints=rules,
            slots=slots,
            attachments=attachments,
            timelines=tuple(
                replace(
                    t, tracks=tuple(track for track in t.tracks if track.owner_id not in discarded)
                )
                for t in scene.timelines
            ),
            clips=tuple(
                replace(
                    c,
                    extra={
                        **c.extra,
                        "fk_bones": tuple(k for k in c.extra["fk_bones"] if k not in removed),
                        **(
                            {
                                "spring_baked_bones": tuple(
                                    k for k in c.extra["spring_baked_bones"] if k not in removed
                                )
                            }
                            if "spring_baked_bones" in c.extra
                            else {}
                        ),
                    },
                )
                if "fk_bones" in c.extra
                else c
                for c in scene.clips
            ),
            draw_order=tuple(k for k in scene.draw_order if k not in discarded),
        )

    def duplicate(self, key: str) -> tuple[str, ...]:
        """Copy a rest branch with fresh bone IDs, without copying animation or skin bindings."""
        return self._copy_branch(key, None)

    def mirror(self, key: str, axis_x: float) -> tuple[str, ...]:
        """Reflect a complete branch in world space with new identities and side-aware names."""
        return self._copy_branch(key, axis_x)

    def _copy_branch(self, key: str, axis_x: float | None) -> tuple[str, ...]:
        """Preserve branch topology while copying rest transforms into the original skeleton."""
        if self.editable(key).extra.get("rig_root"):
            raise ProjectError("Duplicate the Object or a chain below Rig Root.")
        pose = self.rest_pose()
        selected = {key}
        bones = []
        for node in pose.nodes.values():
            if node.id == key or node.parent_id in selected:
                selected.add(node.id)
                bones.append(self.bone(node.id))
        reflection: Matrix = (1, 0, 0, 1, 0, 0) if axis_x is None else (-1, 0, 0, 1, 2 * axis_x, 0)
        copies: dict[str, Bone] = {}
        worlds: dict[str, Matrix] = {}
        for bone in bones:
            world = multiply(reflection, pose.nodes[bone.id].world_matrix)
            parent = copies.get(bone.parent_id or "")
            parent_world = worlds.get(bone.parent_id or "")
            if parent_world is None and bone.parent_id:
                parent_world = pose.nodes[bone.parent_id].world_matrix
            local = multiply(inverse(parent_world), world) if parent_world else world
            name = (
                bone.name[:-2] + (".R" if bone.name.endswith(".L") else ".L")
                if bone.name.endswith((".L", ".R"))
                else bone.name + ".Mirror"
            )
            if axis_x is None:
                name = bone.name + ".Copy"
            copies[bone.id] = replace(
                bone,
                id=str(uuid4()),
                name=self.unique_name(name),
                parent_id=parent.id if parent else bone.parent_id,
                transform=from_matrix(local, bone.transform),
            )
            worlds[bone.id] = world
        self.commit(
            "Duplicate bone branch" if axis_x is None else "Mirror bone branch",
            skeletons=tuple(
                replace(
                    rig, bones=(*rig.bones, *(copies[b.id] for b in rig.bones if b.id in copies))
                )
                for rig in self.scene.skeletons
            ),
        )
        return tuple(b.id for b in copies.values())

    def template(self, name: str) -> str:
        """Insert an original named chain, biped or quadruped rest rig as one command."""
        recipes = {
            "Winged": (
                ("body", None, 450, 300, -90, 90),
                ("head", 0, 90, 0, 0, 45),
                ("wing.L", 0, 55, 0, -90, 130),
                ("wingtip.L", 2, 130, 0, -15, 100),
                ("wing.R", 0, 55, 0, 90, 130),
                ("wingtip.R", 4, 130, 0, 15, 100),
                ("tail", 0, 0, 0, 180, 85),
            ),
            "Flexible spine": (
                ("root", None, 300, 300, 0, 90),
                ("spine.1", 0, 90, 0, 10, 90),
                ("spine.2", 1, 90, 0, -10, 90),
                ("spine.3", 2, 90, 0, -10, 90),
                ("tip", 3, 90, 0, 10, 70),
            ),
            "Chain": (
                ("root", None, 400, 240, 0, 100),
                ("middle", 0, 100, 0, 20, 90),
                ("tip", 1, 90, 0, 20, 70),
            ),
            "Biped": (
                ("hips", None, 450, 290, -90, 70),
                ("spine", 0, 70, 0, 0, 90),
                ("head", 1, 90, 0, 0, 45),
                ("arm.L", 1, 65, 0, -80, 85),
                ("forearm.L", 3, 85, 0, -20, 75),
                ("arm.R", 1, 65, 0, 80, 85),
                ("forearm.R", 5, 85, 0, 20, 75),
                ("leg.L", 0, 0, -25, 190, 95),
                ("shin.L", 7, 95, 0, 15, 90),
                ("leg.R", 0, 0, 25, 170, 95),
                ("shin.R", 9, 95, 0, -15, 90),
            ),
            "Quadruped": (
                ("body", None, 300, 260, 0, 240),
                ("neck", 0, 240, 0, -50, 70),
                ("head", 1, 70, 0, 40, 70),
                ("front.L", 0, 210, 0, 80, 85),
                ("front_lower.L", 3, 85, 0, 15, 75),
                ("rear.L", 0, 15, 0, 100, 85),
                ("rear_lower.L", 5, 85, 0, -25, 75),
                ("front.R", 0, 190, -12, 70, 85),
                ("front_lower.R", 7, 85, 0, 25, 75),
                ("rear.R", 0, 35, -12, 110, 85),
                ("rear_lower.R", 9, 85, 0, -15, 75),
            ),
        }
        if name not in recipes:
            raise ProjectError("Unknown skeleton template.")
        bones: list[Bone] = []
        for label, parent, x, y, angle, length in recipes[name]:
            bones.append(
                Bone(
                    name=self.unique_name(label),
                    parent_id=bones[parent].id if parent is not None else None,
                    transform=Transform(x=x, y=y, rotation=angle),
                    length=length,
                    group=name,
                )
            )
        from rigora.domain.rig_roots import rooted_skeleton

        skeleton = rooted_skeleton(
            Skeleton(name=f"{name} rig", bones=tuple(bones)),
            position=(bones[0].transform.x, bones[0].transform.y),
        )
        self.commit(
            "Add skeleton template",
            skeletons=(*self.scene.skeletons, skeleton),
            characters=(*self.scene.characters, Character(name=name, skeleton_id=skeleton.id)),
        )
        return bones[0].id

    def add_constraint(
        self, owner: str, kind: str, target: str | None = None, **parameters: Any
    ) -> str:
        """Add a constraint, creating an editable scene target when an IK chain needs one."""
        owner_node = self.rest_pose().nodes.get(owner)
        if owner_node is None or owner_node.kind not in ("bone", "object"):
            raise ProjectError("Choose a bone or object constraint owner.")
        if owner_node.kind == "bone":
            self.editable(owner)
        if kind == "spring":
            from rigora.application_services.dynamics import DynamicsService

            return DynamicsService(self.document).configure((owner,), **parameters)[0]
        if kind not in ("two_bone_ik", "pin", "limits", "spring") and target is None:
            raise ProjectError("Choose a target before adding this constraint.")
        objects = self.scene.objects
        if kind == "two_bone_ik":
            if self.bone(owner).extra.get("rig_root"):
                raise ProjectError("Choose a deforming chain below Rig Root for IK.")
            children = [
                b for rig in self.scene.skeletons for b in rig.bones if b.parent_id == owner
            ]
            if not children:
                raise ProjectError("Two-bone IK needs a direct child bone.")
            child = children[0]
            parameters.setdefault("end_bone_id", child.id)
            if target is None:
                node = self.rest_pose().nodes[child.id]
                x, y = transform_point(node.world_matrix, node.length, 0)
                control = SceneObject(
                    name=f"{self.bone(owner).name} IK target"[:200], transform=Transform(x=x, y=y)
                )
                objects = (*objects, control)
                target = control.id
        if kind == "pin" and target is None:
            point = transform_point(
                owner_node.world_matrix,
                number(parameters.get("point_x", 0)),
                number(parameters.get("point_y", 0)),
            )
            parameters.setdefault("x", point[0])
            parameters.setdefault("y", point[1])
        if kind in ("parent", "space_switch") and target:
            parameters.setdefault(
                "offset",
                multiply(
                    inverse(self.rest_pose().nodes[target].world_matrix), owner_node.world_matrix
                ),
            )
        constraint = Constraint(
            name=f"{kind} · {owner_node.name}"[:200],
            owner_id=owner,
            target_id=target,
            kind=kind,
            parameters=parameters,
        )
        self.commit(
            "Add rig constraint", objects=objects, constraints=(*self.scene.constraints, constraint)
        )
        return constraint.id

    def update_constraint(self, key: str, *, keep_world: bool = False, **changes: Any) -> None:
        """Replace an existing constraint while preserving identity and unrelated parameters."""
        if set(changes) - {"parameters", "target_id", "enabled", "order", "name"}:
            raise ProjectError("Unsupported constraint edit.")
        rule = next((c for c in self.scene.constraints if c.id == key), None)
        if rule is None:
            raise ProjectError("The selected constraint no longer exists.")
        target = changes.get("target_id", rule.target_id)
        if (
            keep_world
            and rule.kind in ("parent", "space_switch")
            and target
            and target != rule.target_id
        ):
            pose = self.preview_pose()
            if target not in pose.nodes:
                raise ProjectError("Choose a valid transform target for the new space.")
            params = dict(changes.get("parameters", rule.parameters))
            params["offset"] = multiply(
                inverse(pose.nodes[target].world_matrix), pose.nodes[rule.owner_id].world_matrix
            )
            changes["parameters"] = params
        self.commit(
            "Edit constraint",
            constraints=tuple(
                replace(c, **changes) if c.id == key else c for c in self.scene.constraints
            ),
        )

    def remove_constraint(self, key: str) -> None:
        """Remove one constraint while retaining its reusable target object."""
        if any(c.id == key and c.kind == "scene_attachment" for c in self.scene.constraints):
            raise ProjectError(
                "Use Scene attachments → Release object to preserve its pose and keys."
            )
        self.commit(
            "Remove constraint", constraints=tuple(c for c in self.scene.constraints if c.id != key)
        )

    def move_target(self, key: str, x: float, y: float) -> None:
        """Move an object target in scene space through an undoable validated command."""
        pose = self.rest_pose()
        obj = next((o for o in self.scene.objects if o.id == key), None)
        if obj is None:
            raise ProjectError("Choose an object control target.")
        world = pose.nodes[key].world_matrix
        changed: Matrix = (*world[:4], x, y)
        local = (
            multiply(inverse(pose.nodes[obj.parent_id].world_matrix), changed)
            if obj.parent_id
            else changed
        )
        self.commit(
            "Move rig target",
            objects=tuple(
                replace(o, transform=from_matrix(local, obj.transform)) if o.id == key else o
                for o in self.scene.objects
            ),
        )

    def parent_matrix(self, bone: Bone, pose: ScenePose) -> Matrix:
        """Resolve the effective parent of an authored bone, including rig-only placement.

        A skeletal root has no bone parent, but its displayed world matrix can
        still inherit its owning Object. Remove that placement before storing a
        changed local transform so Scene translation is never applied twice.
        """
        if bone.parent_id:
            return pose.nodes[bone.parent_id].world_matrix
        evaluator = self.document.animation.evaluator
        owner = evaluator.library_rigs.get(bone.id)
        if owner is not None and owner in pose.nodes:
            return multiply(
                pose.nodes[owner].world_matrix, inverse(evaluator.spring_bindings[owner])
            )
        return (1, 0, 0, 1, 0, 0)

    def drag(self, key: str, tool: str, x: float, y: float) -> None:
        """Commit a scene-space move or endpoint rotation/length edit from a viewport handle."""
        if tool == "pull":
            self.pull(key, x, y)
            return
        if tool not in ("move", "rotate", "length"):
            raise ProjectError("Choose a supported bone drag tool.")
        bone = self.editable(key)
        pose = self.preview_pose()
        parent = self.parent_matrix(bone, pose)
        if tool == "move":
            world = pose.nodes[key].world_matrix
            changed: Matrix = (*world[:4], x, y)
            transform = from_matrix(multiply(inverse(parent), changed), bone.transform)
            self.update(key, transform=transform)
        else:
            px, py = transform_point(inverse(parent), x, y)
            transform = bone.transform
            dx, dy = px - transform.x - transform.pivot_x, py - transform.y - transform.pivot_y
            vx = transform.scale_x * (bone.length - transform.pivot_x)
            vy = -transform.scale_y * transform.pivot_y
            changes: dict[str, Any] = {}
            if tool == "length":
                if abs(transform.scale_x) < 1e-12:
                    raise ProjectError("Restore nonzero X scale before editing length.")
                radius = math.hypot(dx, dy)
                if radius < abs(vy):
                    raise ProjectError("This endpoint is too close to the scaled pivot.")
                vx = math.copysign(math.sqrt(max(0, radius * radius - vy * vy)), vx)
                changes["length"] = transform.pivot_x + vx / transform.scale_x
            angle = math.degrees(math.atan2(dy, dx) - math.atan2(vy, vx))
            changes["transform"] = replace(transform, rotation=angle)
            self.update(key, **changes)

    def pull(self, key: str, x: float, y: float) -> None:
        """Pose an ancestor chain toward a world tip, anchoring its root and preserving lengths."""
        cursor = self.editable(key)
        if cursor.extra.get("rig_root"):
            raise ProjectError("Move Rig Root directly; pull a deforming chain for IK.")
        endpoint_rule = next(
            (
                c
                for c in self.scene.constraints
                if c.enabled
                and c.kind == "two_bone_ik"
                and c.parameters.get("mode") != "fk"
                and c.parameters.get("end_bone_id") == key
                and c.target_id
            ),
            None,
        )
        if endpoint_rule and endpoint_rule.target_id:
            self.move_target(endpoint_rule.target_id, x, y)
            return
        ancestors = [cursor]
        while cursor.parent_id:
            parent = self.editable(cursor.parent_id)
            if parent.extra.get("rig_root"):
                break
            cursor = parent
            ancestors.append(cursor)
        ancestors.reverse()
        identities = {bone.id for bone in ancestors}
        if any(
            c.enabled
            and c.kind != "spring"
            and c.owner_id in identities
            and not (c.kind == "two_bone_ik" and c.parameters.get("mode") == "fk")
            for c in self.scene.constraints
        ):
            raise ProjectError(
                "Pull the rig's constraint target, or disable its constraints before posing."
            )
        pose = self.preview_pose()
        edges = [ancestors[-1]]
        for child, parent in zip(reversed(ancestors[1:]), reversed(ancestors[:-1]), strict=True):
            child_root = transform_point(pose.nodes[child.id].world_matrix, 0, 0)
            parent_matrix = pose.nodes[parent.id].world_matrix
            if math.dist(child_root, transform_point(parent_matrix, 0, 0)) >= 1e-6:
                edges.append(parent)
        edges.reverse()
        points = tuple(transform_point(pose.nodes[b.id].world_matrix, 0, 0) for b in edges)
        points += (transform_point(pose.nodes[key].world_matrix, self.bone(key).length, 0),)
        solved = pull_chain(points, (x, y))
        segments = {
            bone.id: (
                solved[i],
                solved[i + 1],
                math.atan2(points[i + 1][1] - points[i][1], points[i + 1][0] - points[i][0]),
            )
            for i, bone in enumerate(edges)
        }
        matrices: dict[str, Matrix] = {}
        replacements = {}
        for bone in ancestors:
            node = pose.nodes[bone.id]
            parent_matrix = matrices.get(
                bone.parent_id or "",
                pose.nodes[bone.parent_id].world_matrix if bone.parent_id else (1, 0, 0, 1, 0, 0),
            )
            if bone.id in segments:
                start, end, original_angle = segments[bone.id]
                a, b, c, d, _, _ = node.world_matrix
                angle = math.atan2(end[1] - start[1], end[0] - start[0]) - original_angle
                cosine, sine = math.cos(angle), math.sin(angle)
                world: Matrix = (
                    cosine * a - sine * b,
                    sine * a + cosine * b,
                    cosine * c - sine * d,
                    sine * c + cosine * d,
                    *start,
                )
            else:
                world = multiply(parent_matrix, node.local_matrix)
            matrices[bone.id] = world
            replacements[bone.id] = replace(
                bone, transform=from_matrix(multiply(inverse(parent_matrix), world), bone.transform)
            )
        self._replace_bones("Pull connected chain", replacements)

    def plan_drag(
        self, key: str, tool: str, x: float, y: float, selected: tuple[str, ...] = ()
    ) -> tuple[ScenePatch, ScenePose]:
        """Plan and evaluate a gesture in an isolated session; never edit the source document."""
        scratch = DocumentService(
            constraint_solvers=self.document.constraint_solvers,
            deformer_solvers=self.document.deformer_solvers,
            track_samplers=self.document.track_samplers,
        )
        scratch._link_objects = False
        assert self.document.project is not None
        scratch.project = Project(
            scenes=(self.control_scene(self.scene),), assets=self.document.project.assets
        )
        scratch.set_animation_context(
            self.document.animation_context, self.document.animation_scope, prepare=False
        )
        service = RigService(scratch)
        if tool.startswith("rig_"):
            roots = []
            for identity in selected or (key,):
                root = service.bone(identity)
                while root.parent_id:
                    root = service.bone(root.parent_id)
                if root.id not in roots:
                    roots.append(root.id)
            root = service.bone(key)
            while root.parent_id:
                root = service.bone(root.parent_id)
            pose = service.preview_pose()
            origin, anchor = pose.nodes[root.id].world_matrix[4:], pose.nodes[key].world_matrix[4:]
            service.transform_selection(
                tuple(roots),
                root.id,
                tool.replace("rig_", "selection_", 1),
                x + origin[0] - anchor[0] if tool == "rig_move" else x,
                y + origin[1] - anchor[1] if tool == "rig_move" else y,
                include_descendants=True,
            )
        elif tool == "chain_rotate":
            service.rotate_fk_selection(selected or (key,), x)
        elif tool.startswith("chain_"):
            service.transform_selection(
                selected or (key,),
                key,
                tool.replace("chain_", "selection_", 1),
                x,
                y,
                include_descendants=True,
            )
        elif tool.startswith("selection_"):
            service.transform_selection(selected or (key,), key, tool, x, y)
        elif tool == "target":
            service.move_target(key, x, y)
        elif tool == "move" and len(selected) > 1:
            service.move_selection(selected, key, x, y)
        else:
            service.drag(key, tool, x, y)
        fields = tuple(
            field
            for field in ("objects", "groups", "skeletons")
            if getattr(self.scene, field) != getattr(service.scene, field)
        )
        command = ScenePatch(
            "Edit rig gesture",
            self.scene.id,
            {field: getattr(self.scene, field) for field in fields},
            {field: getattr(service.scene, field) for field in fields},
        )
        preview = SceneEvaluator(
            replace(self.scene, **command.after, clips=()),
            solvers=self.document.constraint_solvers,
            deformers=self.document.deformer_solvers,
            scope=self.document.animation_scope,
            local_object=self.document.animation_context,
            deformation_plan=(
                self.document._animation.evaluator.deformation if self.document._animation else None
            ),
        ).evaluate(0)
        return command, preview

    def rotate_fk_selection(self, selected: tuple[str, ...], angle: float) -> None:
        """Rotate each selected joint in parent space, inheriting motion through children.

        Apply the same degree delta once per selected identity. Local origins stay
        fixed, including bones with nonzero pivots; unselected locals remain intact.
        Validate inherited branches before committing one reversible patch.
        """
        angle = number(angle)
        selected = tuple(dict.fromkeys(selected))
        pose = self.preview_pose()
        affected = set(selected)
        for node in pose.nodes.values():
            if node.kind == "bone" and node.parent_id in affected:
                affected.add(node.id)
        for identity in affected:
            self.editable(identity)
        changes = {}
        for identity in selected:
            bone = self.editable(identity)
            local = pose.nodes[identity].local_matrix
            cx, cy = local[4:]
            delta = multiply(affine(cx, cy, angle, 1, 1, 0, 0), affine(-cx, -cy, 0, 1, 1, 0, 0))
            changes[identity] = replace(
                bone, transform=from_matrix(multiply(delta, local), bone.transform)
            )
        self._replace_bones("Rotate selected FK joints", changes)

    def transform_selection(
        self,
        selected: tuple[str, ...],
        key: str,
        tool: str,
        x: float,
        y: float,
        *,
        include_descendants: bool = False,
    ) -> None:
        """Transform selected world bones while compensating unselected children to stay put.

        Move takes the primary bone's target origin; rotate takes a degree delta in X;
        scale takes a uniform multiplier in X. Ancestors outside the selection never
        participate in the solve. Child local compensation preserves their world pose,
        unless include_descendants requests FK inheritance. A connected FK selection
        pivots at its highest selected base joint, independent of selection order.
        Other multi-selections share their bounds center.
        """
        selected = tuple(dict.fromkeys(selected))
        for identity in selected:
            self.editable(identity)
        if key not in selected:
            raise ProjectError("The dragged bone must belong to the selection.")
        pose = self.preview_pose()
        points = [
            transform_point(pose.nodes[k].world_matrix, offset, 0)
            for k in selected
            for offset in (0, self.bone(k).length)
        ]
        cx = (min(p[0] for p in points) + max(p[0] for p in points)) / 2
        cy = (min(p[1] for p in points) + max(p[1] for p in points)) / 2
        pivot_keys = (
            selected_roots({k: n.parent_id for k, n in pose.nodes.items()}, selected)
            if include_descendants
            else selected
        )
        if len(pivot_keys) == 1:
            cx, cy = pose.nodes[pivot_keys[0]].world_matrix[4:]
        affected = set(selected)
        master_control = (
            include_descendants and len(selected) == 1 and self.bone(key).extra.get("rig_root")
        )
        if include_descendants and not master_control:
            for node in pose.nodes.values():
                if node.kind == "bone" and node.parent_id in affected:
                    affected.add(node.id)
        for identity in affected:
            self.editable(identity)
        if tool == "selection_move":
            origin = pose.nodes[key].world_matrix[4:]
            delta = affine(number(x) - origin[0], number(y) - origin[1], 0, 1, 1, 0, 0)
        elif tool in ("selection_rotate", "selection_scale"):
            angle, scale = (number(x), 1.0) if tool.endswith("rotate") else (0.0, number(x))
            if not 0.01 <= scale <= 100:
                raise ProjectError("Bone scale must be from 0.01 to 100.")
            delta = multiply(
                affine(cx, cy, angle, scale, scale, 0, 0), affine(-cx, -cy, 0, 1, 1, 0, 0)
            )
        else:
            raise ProjectError("Unsupported selection transform.")
        desired = {
            k: multiply(delta, n.world_matrix) if k in affected else n.world_matrix
            for k, n in pose.nodes.items()
        }
        changes = {}
        for rig in self.scene.skeletons:
            for bone in rig.bones:
                if master_control and bone.id not in selected:
                    continue
                if bone.id not in affected and bone.parent_id not in affected:
                    continue
                self.editable(bone.id)
                parent = (
                    desired[bone.parent_id] if bone.parent_id else self.parent_matrix(bone, pose)
                )
                changes[bone.id] = replace(
                    bone,
                    transform=from_matrix(
                        multiply(inverse(parent), desired[bone.id]), bone.transform
                    ),
                )
        self._replace_bones("Transform selected bones", changes)

    def move_selection(self, selected: tuple[str, ...], key: str, x: float, y: float) -> None:
        """Translate selected branches once, retaining selected descendants' local transforms."""
        pose = self.preview_pose()
        origin = transform_point(pose.nodes[key].world_matrix, 0, 0)
        dx, dy = x - origin[0], y - origin[1]
        replacements = {}
        for identity in selected:
            bone = self.editable(identity)
            parent_id = bone.parent_id
            while parent_id and parent_id not in selected:
                parent_id = self.bone(parent_id).parent_id
            if parent_id:
                continue
            world = pose.nodes[identity].world_matrix
            parent = self.parent_matrix(bone, pose)
            replacements[identity] = replace(
                bone,
                transform=from_matrix(
                    multiply(inverse(parent), (*world[:4], world[4] + dx, world[5] + dy)),
                    bone.transform,
                ),
            )
        self._replace_bones("Move selected bones", replacements)
