"""Validated scene organization and transform commands shared by desktop and Python clients."""

import math
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.commands import ProjectPatch, ScenePatch
from rigora.application_services.meshes import MeshService
from rigora.domain.entities import (
    Bone,
    Character,
    Constraint,
    Entity,
    Group,
    Layer,
    SceneObject,
    Skeleton,
    Transform,
)
from rigora.domain.geometry import affine, decompose, inverse, multiply, transform_point
from rigora.domain.project import ProjectError, Scene
from rigora.domain.validation import integer
from rigora.engine.chain_pull import selected_roots
from rigora.engine.sampling import number


class SceneEditingService(MeshService):
    """Edit canonical scene entries without storing GUI selection or transient previews."""

    auto_key = False
    sprite_edit = False
    part_edit = False
    _record_cache: tuple[Scene, dict[str, Entity]] | None = None

    def records(self) -> dict[str, Entity]:
        """Return an owned map of selectable identities, including organization layers."""
        return dict(self._records())

    def _records(self) -> dict[str, Entity]:
        """Index each immutable scene revision once for repeated picks and lock checks."""
        scene = self.scene
        if self._record_cache is not None and self._record_cache[0] is scene:
            return self._record_cache[1]
        records = {
            r.id: r
            for r in (
                *scene.layers,
                *scene.groups,
                *scene.cameras,
                *scene.objects,
                *scene.skeletons,
                *scene.characters,
                *(b for s in scene.skeletons for b in s.bones),
            )
        }
        self._record_cache = scene, records
        self._rig_parents = {
            bone.id: rig.extra["object_id"]
            for rig in scene.skeletons
            if rig.extra.get("object_id") in records
            for bone in rig.bones
        }
        rigs = {r.id: r for r in scene.skeletons}
        self._character_parents = {
            key: c.id
            for c in scene.characters
            for key in (
                *c.object_ids,
                *c.extra.get("part_groups", ()),
                *(b.id for b in rigs[c.skeleton_id].bones),
            )
        }
        return records

    def record(self, key: str) -> Entity:
        """Resolve a stable identity against the current project revision."""
        record = self._records().get(key)
        if record is None:
            raise ProjectError("The selected scene entry no longer exists.")
        return record

    def locked(self, key: str) -> bool:
        """Include ancestor and layer protection while leaving locked entries inspectable."""
        records, visited = self._records(), set()
        pending = [key]
        while pending:
            identity = pending.pop()
            if identity in visited or identity not in records:
                continue
            visited.add(identity)
            entry = records[identity]
            if getattr(entry, "locked", False) or entry.extra.get("locked", False):
                return True
            if identity in self._character_parents:
                pending.append(self._character_parents[identity])
            if identity in self._rig_parents:
                pending.append(self._rig_parents[identity])
            pending.extend(
                k
                for k in (getattr(entry, "parent_id", None), getattr(entry, "layer_id", None))
                if k
            )
        return False

    def update_records(self, changes: Mapping[str, Entity], label: str) -> None:
        """Replace complete records atomically while preserving every unrelated collection."""
        scene = self.scene
        updated: dict[str, Any] = {}
        for field in ("objects", "groups", "cameras", "layers", "skeletons", "characters"):
            values = tuple(changes.get(r.id, r) for r in getattr(scene, field))
            if field == "skeletons":
                values = tuple(
                    replace(r, bones=tuple(changes.get(b.id, b) for b in r.bones)) for r in values
                )
            if values != getattr(scene, field):
                updated[field] = values
        if updated:
            self.document.execute(
                ScenePatch(label, scene.id, {k: getattr(scene, k) for k in updated}, updated)
            )

    def flags(
        self, keys: tuple[str, ...], *, visible: bool | None = None, locked: bool | None = None
    ) -> None:
        """Change authored visibility and selection locks; skeleton flags apply to all bones."""
        expanded = set(keys)
        for skeleton in self.scene.skeletons:
            if skeleton.id in expanded:
                expanded.update(b.id for b in skeleton.bones)
        changes = {}
        for key in expanded:
            entry = self.record(key)
            fields: dict[str, Any] = {}
            extra = dict(entry.extra)
            for name, value in (("visible", visible), ("locked", locked)):
                if value is None:
                    continue
                if isinstance(entry, (Bone, Layer)) or (
                    name == "visible" and isinstance(entry, SceneObject)
                ):
                    fields[name] = value
                else:
                    extra[name] = value
            changes[key] = replace(entry, **fields, extra=extra)
        self.update_records(changes, "Change scene visibility / locking")

    def rename(self, key: str, name: str) -> None:
        """Rename a scene entry through entity validation and ordinary undo history."""
        self.update_records(
            {key: replace(self.record(key), name=name.strip())}, "Rename scene entry"
        )

    def set_depth(self, keys: tuple[str, ...], value: int) -> None:
        """Set local Z offsets; parent offsets accumulate and layer order breaks ties."""
        depth = integer(value, "Depth (Z)", -1_000_000, 1_000_000)
        changes = {}
        for key in keys:
            record = self.record(key)
            if not isinstance(record, (Group, SceneObject)) or self.locked(key):
                raise ProjectError("Choose unlocked Objects or parts to change Depth (Z).")
            if record.extra.get("depth", 0) != depth:
                changes[key] = replace(record, extra={**record.extra, "depth": depth})
        self.update_records(changes, "Set Depth (Z)")

    def rename_scene(self, name: str, scene_id: str | None = None) -> None:
        """Rename an existing scene without activating or evaluating it."""
        name = name.strip()
        if not name:
            raise ProjectError("Scene name cannot be empty.")
        project = self.document.project
        assert project is not None
        scene = next((s for s in project.scenes if s.id == (scene_id or self.scene.id)), None)
        if scene is None:
            raise ProjectError("The scene no longer exists.")
        self.document.execute(
            ScenePatch("Rename scene", scene.id, {"name": scene.name}, {"name": name})
        )

    def center_entries(
        self, keys: tuple[str, ...], position: tuple[float, float] | None = None
    ) -> None:
        """Center artwork bounds at a scene point, defaulting to the camera center.

        Newly imported parts may be outside Object Editor's previous mesh scope;
        evaluate those owners explicitly without changing the document's scope.
        """
        target = (
            tuple(number(v) for v in position)
            if position is not None
            else (self.scene.settings.width / 2, self.scene.settings.height / 2)
        )
        if len(target) != 2:
            raise ProjectError("Placement needs two finite scene coordinates.")
        records, pose = self.records(), self.document.animation.pose
        roots = set(keys)
        meshes = pose.meshes
        owners = frozenset(
            k for k in records if k in roots or self._has_ancestor(k, roots, records)
        )
        if (
            self.document.animation_scope is not None
            and not owners <= self.document.animation_scope
        ):
            evaluator = self.document.animation.evaluator
            meshes, _ = evaluator.deformation.evaluate(
                pose.nodes, evaluator.mesh_values(pose.frame), owners=owners
            )
        points = [
            transform_point(pose.nodes[m.object_id].world_matrix, *point)
            for m in meshes.values()
            if m.object_id is not None
            and m.object_id in pose.nodes
            and (m.object_id in roots or self._has_ancestor(m.object_id, roots, records))
            for point in m.positions
        ]
        if not points:
            from rigora.application_services.characters import CharacterService

            characters = CharacterService(self.document)
            members = set().union(*(characters.members(k) for k in keys))
            points = [
                transform_point(node.world_matrix, x, 0)
                for key, node in pose.nodes.items()
                if key in members and node.kind == "bone"
                for x in (0, node.length)
            ]
            if not points:
                points = [
                    transform_point(
                        pose.nodes[k].world_matrix,
                        pose.nodes[k].local.pivot_x,
                        pose.nodes[k].local.pivot_y,
                    )
                    for k in keys
                    if k in pose.nodes
                ]
        if points:
            xs, ys = zip(*points, strict=True)
            self.transform(
                keys,
                dx=target[0] - (min(xs) + max(xs)) / 2,
                dy=target[1] - (min(ys) + max(ys)) / 2,
            )

    def group(self, keys: tuple[str, ...] = (), name: str = "Group") -> str:
        """Create an editable folder and preserve selected children's world poses atomically."""
        group = Group(name=name)
        with self.document.command_group("Group scene entries"):
            self.commit("Create scene group", groups=(*self.scene.groups, group))
            if keys:
                self.move_entries(keys, group.id)
        return group.id

    def move_entries(
        self, keys: tuple[str, ...], parent: str | None, before: str | None = None
    ) -> None:
        """Reparent folders/artwork and reorder their rendered descendants without moving them.

        Animated transforms cannot be safely reparented without rebaking; reject them rather
        than silently changing their animation. Reordering within a parent remains available.
        """
        records = self.records()
        container = records.get(parent or "")
        if isinstance(container, Character):
            if self.locked(container.id):
                raise ProjectError("Unlock the destination character first.")
            if any(isinstance(records.get(k), Bone) for k in keys):
                self.move_bones(keys, container.skeleton_id, before)
                return
            from rigora.application_services.characters import CharacterService
            from rigora.application_services.image_rigging import ImageRigService

            parts = CharacterService(self.document).meshes_for(keys)
            with self.document.command_group("Move character parts"):
                self.move_entries(keys, None, before)
                ImageRigService(self.document).add_parts(container.id, parts)
            return
        if any(isinstance(records.get(key), Bone) for key in keys):
            self.move_bones(keys, parent, before)
            return
        if isinstance(records.get(parent or ""), Bone):
            self.attach(keys, parent or "")
            return
        if parent is not None and not isinstance(records.get(parent), (Group, SceneObject)):
            raise ProjectError("Drop artwork into a folder or another artwork object.")
        selected = set(keys)
        if not selected or len(selected) != len(keys):
            raise ProjectError("Select distinct artwork objects or folders to move.")
        for key in keys:
            if not isinstance(records.get(key), (Group, SceneObject)) or self.locked(key):
                raise ProjectError("Only unlocked artwork objects and folders can be moved.")
            cursor = parent
            while cursor is not None:
                if cursor in selected:
                    raise ProjectError("A folder cannot be moved into itself or its descendants.")
                cursor = getattr(records[cursor], "parent_id", None)
        if parent is not None and self.locked(parent):
            raise ProjectError("Unlock the destination folder first.")
        part_owner = next(
            (
                c
                for c in self.scene.characters
                if parent in (*c.object_ids, *c.extra.get("part_groups", ()))
            ),
            None,
        )
        if (
            isinstance(container, Group)
            and not container.extra.get("scene_folder")
            and not part_owner
        ):
            from rigora.application_services.characters import CharacterService

            existing = CharacterService(self.document).meshes_for((container.id,))
            part_owner = next(
                (c for c in self.scene.characters if existing and set(existing) <= set(c.mesh_ids)),
                None,
            )
        roots = tuple(key for key in keys if not self._has_ancestor(key, selected, records))
        pose = self.document.animation.pose
        changes = {}
        detached: set[str] = set()
        for key in roots:
            entry = records[key]
            assert isinstance(entry, (Group, SceneObject))
            attachments = {
                c.id
                for c in self.scene.constraints
                if c.owner_id == key
                and c.kind == "parent"
                and isinstance(records.get(c.target_id or ""), (Bone, SceneObject, Group))
            }
            if entry.parent_id == parent and not attachments:
                continue
            animated = any(
                track.owner_id == key and track.property_path.startswith("transform.")
                for timeline in self.scene.timelines
                for track in timeline.tracks
            )
            identity = (1, 0, 0, 1, 0, 0)
            old_space = pose.nodes[entry.parent_id].world_matrix if entry.parent_id else identity
            new_space = pose.nodes[parent].world_matrix if parent else identity
            parent_ids = {p for p in (entry.parent_id, parent) if p}
            for ancestor in tuple(parent_ids):
                cursor = getattr(records[ancestor], "parent_id", None)
                while cursor in records:
                    parent_ids.add(cursor)
                    cursor = getattr(records[cursor], "parent_id", None)
            dynamic_parent = any(
                t.owner_id in parent_ids
                for timeline in self.scene.timelines
                for t in timeline.tracks
            ) or any(c.owner_id in parent_ids for c in self.scene.constraints)
            same_space = not dynamic_parent and all(
                math.isclose(a, b, abs_tol=1e-9) for a, b in zip(old_space, new_space, strict=True)
            )
            if (animated and (not same_space or attachments)) or any(
                c.owner_id == key and c.id not in attachments for c in self.scene.constraints
            ):
                raise ProjectError(
                    "Reorder animated entries within their folder; rebake before reparenting."
                )
            detached.update(attachments)
            matrix = pose.nodes[key].world_matrix
            if parent:
                matrix = multiply(inverse(pose.nodes[parent].world_matrix), matrix)
            x, y, rotation, sx, sy, px, py = decompose(
                matrix, entry.transform.pivot_x, entry.transform.pivot_y
            )
            changes[key] = replace(
                entry,
                parent_id=parent,
                transform=Transform(
                    x=x, y=y, rotation=rotation, scale_x=sx, scale_y=sy, pivot_x=px, pivot_y=py
                ),
            )
        moving = [
            key
            for key in pose.render_order
            if isinstance(records.get(key), SceneObject)
            and (key in selected or self._has_ancestor(key, selected, records))
        ]
        order = [
            key
            for key in pose.render_order
            if isinstance(records.get(key), SceneObject) and key not in moving
        ]
        target = before
        if target in records and isinstance(records[target], Group):
            target = next(
                (key for key in order if self._has_ancestor(key, {target}, records)), None
            )
        index = order.index(target) if target in order else len(order)
        order[index:index] = moving
        with self.document.command_group("Move scene entries"):
            if detached:
                self.commit(
                    "Detach artwork from target",
                    constraints=tuple(c for c in self.scene.constraints if c.id not in detached),
                )
            self.update_records(changes, "Reparent scene entries")
            self.commit("Change render order", draw_order=tuple(order))
            if part_owner:
                from rigora.application_services.characters import CharacterService
                from rigora.application_services.image_rigging import ImageRigService

                parts = CharacterService(self.document).meshes_for(keys)
                if set(parts) - set(part_owner.mesh_ids):
                    ImageRigService(self.document).add_parts(part_owner.id, parts)

    def move_bones(
        self, keys: tuple[str, ...], parent: str | None, before: str | None = None
    ) -> None:
        """Reparent and reorder selected bone branches atomically, retaining rest geometry."""
        from rigora.application_services.rigging import RigService

        records = self.records()
        if (
            not keys
            or len(set(keys)) != len(keys)
            or any(not isinstance(records.get(k), Bone) for k in keys)
        ):
            raise ProjectError("Move bones separately from artwork and folders.")
        owners = {b.id: r.id for r in self.scene.skeletons for b in r.bones}
        destination = records.get(parent or "")
        if isinstance(destination, Skeleton):
            if any(owners[k] != destination.id for k in keys):
                raise ProjectError(
                    "Keep bones in their own skeleton; choose a bone in the same rig."
                )
            parent = None
        elif parent is not None and not isinstance(destination, Bone):
            raise ProjectError("Drop bones onto another bone, their skeleton, or the scene root.")
        if parent is not None and (
            self.locked(parent) or any(owners[k] != owners[parent] for k in keys)
        ):
            raise ProjectError("Choose an unlocked parent bone in the same skeleton.")
        if any(self.locked(k) for k in keys):
            raise ProjectError("Unlock the selected bones before reparenting.")
        roots = selected_roots({k: getattr(r, "parent_id", None) for k, r in records.items()}, keys)
        changed = {k for k in roots if getattr(records[k], "parent_id", None) != parent}
        spaces = set(changed)
        for key in (*changed, *((parent,) if parent else ())):
            cursor = getattr(records[key], "parent_id", None)
            while cursor in records:
                spaces.add(cursor)
                cursor = getattr(records[cursor], "parent_id", None)
        if parent:
            spaces.add(parent)
        if changed and (
            any(t.owner_id in spaces for timeline in self.scene.timelines for t in timeline.tracks)
            or any(c.enabled and c.owner_id in spaces for c in self.scene.constraints)
        ):
            raise ProjectError(
                "Reorder animated bones within their parent; rebake before reparenting."
            )
        with self.document.command_group("Move bone branches"):
            rigging = RigService(self.document)
            for key in roots:
                if key in changed:
                    rigging.reparent(key, parent)
            updated = []
            for rig in self.scene.skeletons:
                moving = [b for b in rig.bones if b.id in roots]
                ordered = [b for b in rig.bones if b.id not in roots]
                index = next((i for i, b in enumerate(ordered) if b.id == before), len(ordered))
                if (
                    before in records
                    and before not in roots
                    and (
                        before not in owners
                        or owners[before] != rig.id
                        or getattr(records[before], "parent_id", None) != parent
                    )
                    and moving
                ):
                    raise ProjectError("Reorder bones between siblings in the same skeleton.")
                ordered[index:index] = moving
                updated.append(replace(rig, bones=tuple(ordered)))
            if tuple(updated) != self.scene.skeletons:
                self.commit("Order bone siblings", skeletons=tuple(updated))

    @staticmethod
    def _has_ancestor(key: str, selected: set[str], records: Mapping[str, Entity]) -> bool:
        """Follow the already validated hierarchy without including the entry itself."""
        cursor = getattr(records[key], "parent_id", None)
        while isinstance(cursor, str) and cursor in records:
            if cursor in selected:
                return True
            cursor = getattr(records[cursor], "parent_id", None)
        return False

    def attach(self, keys: tuple[str, ...], bone_id: str) -> None:
        """Attach rigid artwork/folders to a transform using keep-world parent constraints.

        The target can be a bone or another artwork/folder. Dependency cycles are rejected
        before committing, including indirect cycles through other attachments.
        """
        from rigora.engine.constraints import ConstraintPlan
        from rigora.engine.scene_following import dependency_parents

        if not isinstance(self.records().get(bone_id), (Bone, SceneObject, Group)):
            raise ProjectError("Choose a bone, image, shape or folder as the attachment target.")
        if self.locked(bone_id):
            raise ProjectError("Unlock the destination before attaching artwork.")
        pose = self.document.animation.pose.for_display()
        rules = list(self.scene.constraints)
        records = self.records()
        keys = tuple(dict.fromkeys(keys))
        for key in keys:
            if not isinstance(self.record(key), (SceneObject, Group)) or self.locked(key):
                raise ProjectError("Select unlocked artwork or folders to attach.")
        keys = tuple(k for k in keys if not self._has_ancestor(k, set(keys), records))
        for key in keys:
            existing = [c for c in rules if c.owner_id == key]
            if any(c.kind != "parent" for c in existing):
                raise ProjectError("Remove the existing owner constraint before attaching.")
            rules = [c for c in rules if c.owner_id != key]
            rule = (
                existing[0]
                if existing
                else Constraint(name="Artwork attachment", kind="parent", owner_id=key)
            )
            rules.append(
                replace(
                    rule,
                    target_id=bone_id,
                    enabled=True,
                    parameters={
                        "offset": multiply(
                            inverse(pose.nodes[bone_id].world_matrix), pose.nodes[key].world_matrix
                        )
                    },
                )
            )
        plan = ConstraintPlan(
            tuple(rules),
            dependency_parents(
                {k: v.parent_id for k, v in pose.nodes.items()},
                self.document.animation.evaluator.scene_followers.bone_owners,
            ),
        )
        if any("cycle" in warning for warning in plan.warnings):
            raise ProjectError("A binding cannot target itself or create a dependency cycle.")
        self.commit("Attach artwork to target", constraints=tuple(rules))

    def delete_entries(self, keys: tuple[str, ...]) -> None:
        """Delete selected artwork/folders and dependent scene records in one undo step.

        Source assets remain available for other instances and undo. Bone deletion uses
        the shared rig service to repair references and dependent bindings.
        """
        from rigora.application_services.rigging import RigService

        if not keys:
            return
        records = self.records()
        preserved = records.get(self.document.animation_context or "")
        if preserved is not None:
            # Select All includes master controls, but clearing an Object's
            # contents must retain its protected skeleton anchor.
            keys = tuple(
                k
                for k in keys
                if not (isinstance(records.get(k), Bone) and records[k].extra.get("rig_root"))
            )
            if not keys:
                return
        if preserved is not None and any(isinstance(records.get(k), Skeleton) for k in keys):
            raise ProjectError(
                "Skeleton is protected in Object Editor; delete its Object in Scene."
            )
        if isinstance(preserved, SceneObject) and preserved.id in keys:
            from rigora.application_services.characters import CharacterService

            # A solid object's transform identity must survive removal of its
            # artwork, so convert it to the ordinary empty-capable container.
            with self.document.command_group("Delete object contents"):
                CharacterService(self.document).promote_object(preserved.id)
                self.delete_entries(keys)
            return
        for key in keys:
            if self.locked(key):
                raise ProjectError("Unlock the selection before deleting it.")
            if not isinstance(self.record(key), (Bone, SceneObject, Group, Character, Skeleton)):
                raise ProjectError("Select artwork, a folder or a bone to delete.")
        bone_keys = tuple(k for k in keys if isinstance(records[k], Bone))
        if bone_keys:
            artwork = tuple(k for k in keys if k not in bone_keys)
            with self.document.command_group("Delete scene selection"):
                if artwork:
                    self.delete_entries(artwork)
                remaining = self.records()
                RigService(self.document).delete_many(tuple(k for k in bone_keys if k in remaining))
            return
        removed = set(keys)
        for actor in self.scene.characters:
            if actor.id in removed:
                removed.update((*actor.object_ids, *actor.extra.get("part_groups", ())))
                if actor.extra.get("object_id") in records:
                    removed.add(actor.extra["object_id"])
        removed.update(k for k in records if self._has_ancestor(k, removed, records))
        removed.update(c.id for c in self.scene.characters if c.extra.get("object_id") in removed)
        if any(
            isinstance(records[k], Group) and records[k].extra.get("object_container") for k in keys
        ):
            removed.update(
                c.id for c in self.scene.characters if c.object_ids and set(c.object_ids) <= removed
            )
        rig_ids = {
            rig.id
            for rig in self.scene.skeletons
            if rig.id in removed
            or rig.extra.get("object_id") in removed
            or any(c.id in removed and c.skeleton_id == rig.id for c in self.scene.characters)
        }
        owned_bones = tuple(b.id for r in self.scene.skeletons if r.id in rig_ids for b in r.bones)
        from rigora.application_services.scene_attachments import SceneAttachmentService

        links = SceneAttachmentService(self.document)
        targets = removed | set(owned_bones)
        if links.references_targets(targets):
            with self.document.command_group("Delete object and release attachments"):
                links.release_targets(targets)
                self.delete_entries(keys)
            return
        controls = {
            g.id
            for g in self.scene.groups
            if g.extra.get("object_id") in removed and g.extra.get("studio_floor_plant")
        }
        controls.update(
            c.target_id
            for c in self.scene.constraints
            if c.owner_id in owned_bones
            and c.target_id in records
            and records[c.target_id].extra.get("studio_floor_plant")
        )
        if controls:
            keys = tuple(dict.fromkeys((*keys, *sorted(controls))))
            removed.update(controls)
        if owned_bones:
            with self.document.command_group("Delete whole object"):
                RigService(self.document).delete_many(owned_bones, remove_rig=True)
                self.delete_entries(keys)
            return
        removed.update(rig_ids)
        removed.update(c.id for c in self.scene.characters if c.skeleton_id in rig_ids)
        removed.update(k for k in records if self._has_ancestor(k, set(keys), records))
        if isinstance(preserved, (Group, Character)):
            removed.discard(preserved.id)
            if isinstance(preserved, Character):
                rig_ids.discard(preserved.skeleton_id)
                removed.discard(preserved.skeleton_id)
        if any(self.locked(key) for key in removed):
            raise ProjectError("Unlock the folder's children before deleting it.")
        scene = self.scene
        meshes = {m.id for m in scene.meshes if m.object_id in removed}
        removed.update(meshes)
        stages = {d.id for d in scene.deformers if d.owner_id in removed}
        slots = {s.id for s in scene.slots if s.owner_id in removed}
        removed.update((*stages, *slots))
        attachments = {a.id for a in scene.attachments if a.slot_id in slots or a.mesh_id in meshes}
        removed.update(attachments)
        removed.update(
            c.id for c in scene.constraints if c.owner_id in removed or c.target_id in removed
        )
        from rigora.application_services.image_rigging import ImageRigService

        image_rigs = ImageRigService(self.document)
        clips = tuple(
            c
            for c in scene.clips
            if not {c.extra.get("object_id"), c.extra.get("character_id")}.intersection(removed)
        )
        removed.update(c.id for c in scene.clips if c not in clips)
        clip_timelines = {c.timeline_id for c in scene.clips if c.id in removed}
        clip_timelines.difference_update(c.timeline_id for c in clips)
        self.commit(
            "Delete scene selection",
            objects=tuple(o for o in scene.objects if o.id not in removed),
            groups=tuple(g for g in scene.groups if g.id not in removed),
            cameras=tuple(c for c in scene.cameras if c.id not in removed),
            meshes=tuple(m for m in scene.meshes if m.id not in removed),
            deformers=tuple(d for d in scene.deformers if d.id not in removed),
            constraints=tuple(
                c
                for c in scene.constraints
                if c.owner_id not in removed and c.target_id not in removed
            ),
            slots=tuple(s for s in scene.slots if s.id not in removed),
            attachments=tuple(a for a in scene.attachments if a.id not in removed),
            timelines=tuple(
                replace(
                    t,
                    tracks=tuple(
                        track
                        for track in t.tracks
                        if track.owner_id not in removed
                        and track.extra.get("motion_window", {}).get("source") not in removed
                        and track.extra.get("motion_window", {}).get("character") not in removed
                    ),
                )
                for t in scene.timelines
                if t.id not in clip_timelines
            ),
            clips=clips,
            skeletons=tuple(r for r in scene.skeletons if r.id not in rig_ids),
            characters=tuple(
                image_rigs.without_parts(c, meshes) for c in scene.characters if c.id not in removed
            ),
            draw_order=tuple(k for k in scene.draw_order if k not in removed),
        )

    def remove_asset(self, key: str) -> None:
        """Remove an unused source from the project, retaining bytes for ordinary undo."""
        project = self.document.project
        if project is None or key not in {a.id for a in project.assets}:
            raise ProjectError("Select a registered source image.")
        assets = tuple(a for a in project.assets if a.id != key)
        from rigora.application_services.object_library import ObjectLibraryService

        def references(value: Any) -> bool:
            """Retain sources used by views, slots, sequences, audio and plugin metadata."""
            if isinstance(value, Mapping):
                return any(references(v) for v in value.values())
            if isinstance(value, (tuple, list)):
                return any(references(v) for v in value)
            return isinstance(value, str) and value == key

        for definition in ObjectLibraryService(self.document).entries().values():
            if references(definition["scene"]):
                raise ProjectError(
                    "This source is used by a saved Object. Remove that saved Object first."
                )
        try:
            candidate = replace(project, assets=assets)
            candidate.validate_references()
        except ProjectError as error:
            raise ProjectError(
                "This source is in use. Delete its scene instances or dependent layouts first."
            ) from error
        self.document.execute(
            ProjectPatch("Remove project source", {"assets": project.assets}, {"assets": assets})
        )

    def records_transforms(self, keys: tuple[str, ...]) -> bool:
        """Record an animated selection at the playhead without changing the Auto key preference.

        Existing keys override authored rest transforms. Empty lanes remain static until
        explicitly keyed, while an animated Transform lane records its changed components.
        """
        if self.auto_key:
            return True
        timeline = AnimationEditingService(self.document).timeline
        selected = set(keys)
        return bool(
            timeline
            and any(
                t.owner_id in selected and t.keyframes and t.property_path.startswith("transform.")
                for t in timeline.tracks
            )
        )

    def set_transform(self, key: str, **values: float) -> None:
        """Edit explicit local transform fields, honoring ancestor locks and record validation."""
        record = self.record(key)
        if self.locked(key) or not isinstance(record, (SceneObject, Bone, Group)):
            raise ProjectError("Choose an unlocked object or bone to edit its transform.")
        allowed = {"x", "y", "rotation", "scale_x", "scale_y"}
        if not values.keys() <= allowed:
            raise ProjectError("Unsupported transform property.")
        edits: dict[str, Any] = {k: number(v) for k, v in values.items()}
        transform = replace(record.transform, **edits)
        if self.records_transforms((key,)):
            AnimationEditingService(self.document).auto_key_values(
                {(key, f"transform.{name}"): value for name, value in edits.items()},
                self.document.animation.pose.frame,
            )
            return
        self.update_records({key: replace(record, transform=transform)}, "Edit object transform")

    def move_pivot(self, key: str, x: float, y: float) -> None:
        """Place an artwork/group pivot in world space while preserving its displayed geometry.

        Static edits compensate local translation. Existing animation or Auto key records the
        compensated position and pivot together at the displayed frame.
        """
        record = self.record(key)
        if not isinstance(record, (SceneObject, Group)) or self.locked(key):
            raise ProjectError("Choose an unlocked image, shape or folder to move its pivot.")
        pose = self.document.animation.pose
        node = pose.nodes[key]
        px, py = transform_point(inverse(node.world_matrix), number(x), number(y))
        recording = self.records_transforms((key,))
        context_timelines = {clip.timeline_id for clip in self.document.context_clips()}
        if not recording and any(
            t.owner_id == key and t.property_path.startswith("transform.")
            for timeline in self.scene.timelines
            if timeline.id in context_timelines
            for t in timeline.tracks
        ):
            raise ProjectError("Enable Auto key to move the pivot of animated artwork.")
        source = node.local_matrix if recording else record.transform.matrix()
        values = decompose(source, px, py)
        with self.document.command_group("Move object pivot"):
            if recording:
                AnimationEditingService(self.document).auto_key_values(
                    {
                        (key, f"transform.{name}"): value
                        for name, value in zip(
                            ("x", "y", "pivot_x", "pivot_y"),
                            (values[0], values[1], px, py),
                            strict=True,
                        )
                    },
                    pose.frame,
                )
                record = self.record(key)
            else:
                record = replace(
                    record,
                    transform=replace(
                        record.transform, x=values[0], y=values[1], pivot_x=px, pivot_y=py
                    ),
                )
            self.update_records(
                {key: replace(record, extra={**record.extra, "pivot_edited": True})},
                "Place object pivot",
            )

    def plan_transform(
        self,
        keys: tuple[str, ...],
        *,
        dx: float = 0,
        dy: float = 0,
        rotation: float = 0,
        scale_x: float = 1,
        scale_y: float = 1,
        center_x: float | None = None,
        center_y: float | None = None,
        space_id: str | None = None,
    ) -> tuple[dict[str, SceneObject | Bone | Group], bool]:
        """Compute validated local transforms without publishing a document revision.

        Preview and commit share selection expansion, constraints, locks and pivot math.
        The boolean indicates whether these transforms must be recorded as animation.
        """
        dx, dy, rotation, scale_x, scale_y = (
            number(v) for v in (dx, dy, rotation, scale_x, scale_y)
        )
        if abs(scale_x) < 1e-6 or abs(scale_y) < 1e-6:
            raise ProjectError("Object scale cannot be zero.")
        if (center_x is None) != (center_y is None):
            raise ProjectError("Transform pivot needs both coordinates.")
        delta = None
        if center_x is not None and center_y is not None:
            cx, cy = number(center_x), number(center_y)
            delta = multiply(
                affine(cx + dx, cy + dy, rotation, scale_x, scale_y, 0, 0),
                affine(-cx, -cy, 0, 1, 1, 0, 0),
            )
        records = self.records()
        if (dx or dy) and rotation == 0 and scale_x == scale_y == 1:
            # Rigid artwork connections move through their driver. Editing the
            # constrained source alone would otherwise be overwritten by evaluation.
            drivers = {
                c.owner_id: c.target_id
                for c in self.scene.constraints
                if c.kind == "parent"
                and c.enabled
                and isinstance(records.get(c.owner_id), (Group, SceneObject))
                and isinstance(records.get(c.target_id or ""), (Group, SceneObject))
            }
            redirected = []
            for key in keys:
                if self.locked(key):
                    raise ProjectError("Unlock the selected entry before moving its binding group.")
                visited = set()
                while key in drivers and key not in visited:
                    visited.add(key)
                    key = str(drivers[key])
                    if (
                        self.document.animation_scope is not None
                        and key not in self.document.animation_scope
                    ):
                        raise ProjectError(
                            "The binding target is outside this Object. "
                            "Edit it in the Scene or unbind first."
                        )
                redirected.append(key)
            redirected_keys = tuple(dict.fromkeys(redirected))
            if redirected_keys != keys:
                space_id = None
                keys = redirected_keys
        original = set(keys)
        if self.part_edit:
            owners = original | {k for k in records if self._has_ancestor(k, original, records)}
            meshes = {m.id for m in self.scene.meshes if m.object_id in owners}
            object_spaces = {
                d.parameters["object_group"]
                for d in self.scene.deformers
                if d.kind == "skinning" and d.parameters.get("object_group") in owners
            }
            object_space_bones = {
                bone
                for d in self.scene.deformers
                if d.kind == "skinning" and d.parameters.get("object_group") in owners
                for bone in d.parameters.get("bind_matrices", {})
            }
            # Helper controls can be added after skin binding and have no bind
            # matrix. They still share the owning rig's Object coordinate space.
            object_space_bones.update(
                bone.id
                for rig in self.scene.skeletons
                if rig.extra.get("object_id") in object_spaces
                for bone in rig.bones
            )
            object_space_bones.update(
                bone.id
                for rig in self.scene.skeletons
                if rig.extra.get("library_bind") and rig.extra.get("object_id") in owners
                for bone in rig.bones
            )
            influences = {
                bone
                for d in self.scene.deformers
                if d.kind == "skinning" and d.owner_id in meshes
                for bone in d.parameters.get("bind_matrices", {})
            }
            roots = {
                key
                for key in influences
                if key in records
                and key not in object_space_bones
                and getattr(records[key], "parent_id", None) not in influences
            }
            roots.update(
                c.target_id
                for c in self.scene.constraints
                if c.kind == "parent"
                and c.owner_id in owners
                and c.target_id is not None
                and isinstance(records.get(c.target_id), Bone)
            )
            roots.update(
                b.id
                for rig in self.scene.skeletons
                if rig.extra.get("object_id") in owners
                for b in rig.bones
                if b.parent_id is None and b.id not in object_space_bones
            )
            # Legacy cutout rigs use world-space floor controls. A whole-character
            # edit must carry those controls; individual part/bone edits must not.
            complete = {
                b.id
                for rig in self.scene.skeletons
                if rig.bones and {b.id for b in rig.bones} <= influences
                for b in rig.bones
                if b.id not in object_space_bones
            }
            roots.update(
                c.target_id
                for c in self.scene.constraints
                if c.owner_id in complete | roots
                and c.target_id in records
                and records[c.target_id].extra.get("studio_floor_plant")
            )
            keys = tuple(dict.fromkeys((*keys, *roots)))
        selected = set(keys)
        changes: dict[str, SceneObject | Bone | Group] = {}
        pose = self.document.animation.pose
        recording = self.records_transforms(keys)
        if space_id is not None:
            if space_id not in original or center_x is None or center_y is None:
                raise ProjectError("Local resizing needs a selected object and a complete pivot.")
            basis = pose.nodes[space_id].world_matrix
            local_pivot = transform_point(inverse(basis), center_x, center_y)
            local_delta = multiply(
                affine(*local_pivot, rotation, scale_x, scale_y, 0, 0),
                affine(-local_pivot[0], -local_pivot[1], 0, 1, 1, 0, 0),
            )
            delta = multiply(multiply(basis, local_delta), inverse(basis))
            if dx or dy:
                delta = multiply(affine(dx, dy, 0, 1, 1, 0, 0), delta)
        for key in keys:
            entry = self.record(key)
            if not isinstance(entry, (SceneObject, Bone, Group)):
                continue
            if self.locked(key):
                raise ProjectError("Unlock the selected entry and its parent/layer before editing.")
            parent = getattr(entry, "parent_id", None)
            cursor = parent
            inherited = False
            while cursor in records:
                if cursor in selected:
                    inherited = True
                    break
                cursor = getattr(records[cursor], "parent_id", None)
            if inherited:
                continue
            parent_matrix = (
                pose.nodes[parent].world_matrix
                if parent is not None and parent in pose.nodes
                else (1, 0, 0, 1, 0, 0)
            )
            if key in self.document.animation.evaluator.scene_followers.defaults:
                parent_matrix = multiply(
                    pose.nodes[key].world_matrix, inverse(pose.nodes[key].local_matrix)
                )
            x, y = dx, dy
            if parent_matrix != (1, 0, 0, 1, 0, 0):
                matrix = inverse(parent_matrix)
                ox, oy = transform_point(matrix, 0, 0)
                px, py = transform_point(matrix, dx, dy)
                x, y = px - ox, py - oy
            source = entry.transform
            if recording:
                local = pose.nodes[key].local
                source = replace(
                    source,
                    x=local.x,
                    y=local.y,
                    rotation=local.rotation,
                    scale_x=local.scale_x,
                    scale_y=local.scale_y,
                    pivot_x=local.pivot_x,
                    pivot_y=local.pivot_y,
                )
            value = replace(
                source,
                x=source.x + x,
                y=source.y + y,
                rotation=source.rotation + rotation,
                scale_x=source.scale_x * scale_x,
                scale_y=source.scale_y * scale_y,
            )
            if delta is not None:
                world = multiply(delta, pose.nodes[key].world_matrix)
                values_tuple = decompose(
                    multiply(inverse(parent_matrix), world), source.pivot_x, source.pivot_y
                )
                value = replace(
                    source,
                    x=values_tuple[0],
                    y=values_tuple[1],
                    rotation=values_tuple[2],
                    scale_x=values_tuple[3],
                    scale_y=values_tuple[4],
                )
            changes[key] = replace(entry, transform=value)
        return changes, recording

    def sprite_bindings(self, keys: tuple[str, ...]) -> set[str]:
        """Find skins whose artwork is edited relative to its rig, excluding whole Objects.

        Object-space skinning already carries the rig through its placement matrix.
        Rebasing its bind matrices during whole-Object movement would apply it twice.
        """
        if not self.sprite_edit:
            return set()
        records, selected = self.records(), set(keys)
        owners = selected | {k for k in records if self._has_ancestor(k, selected, records)}
        meshes = {m.id for m in self.scene.meshes if m.object_id in owners}
        return {
            d.id
            for d in self.scene.deformers
            if d.kind == "skinning"
            and d.owner_id in meshes
            and d.parameters.get("object_group") not in owners
        }

    def transform(
        self,
        keys: tuple[str, ...],
        *,
        dx: float = 0,
        dy: float = 0,
        rotation: float = 0,
        scale_x: float = 1,
        scale_y: float = 1,
        center_x: float | None = None,
        center_y: float | None = None,
        space_id: str | None = None,
    ) -> None:
        """Publish planned transforms or keys, rebasing only individually edited skins."""
        changes, recording = self.plan_transform(
            keys,
            dx=dx,
            dy=dy,
            rotation=rotation,
            scale_x=scale_x,
            scale_y=scale_y,
            center_x=center_x,
            center_y=center_y,
            space_id=space_id,
        )
        pose = self.document.animation.pose
        bindings = self.sprite_bindings(keys)
        if recording:
            values = {}
            for key, record in changes.items():
                for name in ("x", "y", "rotation", "scale_x", "scale_y"):
                    if not math.isclose(
                        getattr(record.transform, name),
                        getattr(pose.nodes[key].local, name),
                        abs_tol=1e-9,
                    ):
                        values[key, f"transform.{name}"] = getattr(record.transform, name)
            if values:
                AnimationEditingService(self.document).auto_key_values(values, pose.frame)
        else:
            with self.document.command_group("Transform scene selection"):
                self.update_records(changes, "Transform scene selection")
                if bindings:
                    updated = self.document.animation.pose
                    sprite_meshes = {
                        m.id: m.object_id
                        for m in self.scene.meshes
                        if m.object_id in keys
                        or (
                            m.object_id in self.records()
                            and self._has_ancestor(m.object_id, set(keys), self.records())
                        )
                    }
                    stages = []
                    for stage in self.scene.deformers:
                        owner = sprite_meshes.get(stage.owner_id)
                        if stage.id in bindings and owner:
                            delta = multiply(
                                updated.nodes[owner].world_matrix,
                                inverse(pose.nodes[owner].world_matrix),
                            )
                            stage = replace(
                                stage,
                                parameters={
                                    **stage.parameters,
                                    "object_bind": multiply(
                                        delta, tuple(stage.parameters["object_bind"])
                                    ),
                                },
                            )
                        stages.append(stage)
                    self.commit("Transform sprite binding", deformers=tuple(stages))
