"""Simple character ownership, wardrobe variants, facing and reusable motion placement."""

from collections.abc import Mapping
from dataclasses import replace
from typing import Any
from uuid import uuid4

from rigora.application_services.animation_editing import (
    AnimationEditingService,
    copied_timeline,
    motion_source_end,
)
from rigora.application_services.scene_editing import SceneEditingService
from rigora.domain.entities import (
    AnimationClip,
    Character,
    Group,
    SceneObject,
    Timeline,
    Track,
    Transform,
)
from rigora.domain.geometry import transform_point
from rigora.domain.project import ProjectError
from rigora.domain.validation import json_copy
from rigora.engine.sampling import number
from rigora.engine.state import ScenePose


class CharacterService(SceneEditingService):
    """Compose existing scene/rig/clip commands instead of creating a parallel character model."""

    def _extra_patch(self, owner: str, field: str, value: Any) -> dict[str, Any]:
        """Build a collection patch for object-owned appearance lists, retaining legacy actors."""
        record = self.record(owner)
        collection = (
            "characters"
            if isinstance(record, Character)
            else "groups"
            if isinstance(record, Group)
            else "objects"
        )
        return {
            collection: tuple(
                replace(r, extra={**r.extra, field: value}) if r.id == owner else r
                for r in getattr(self.scene, collection)
            )
        }

    def scene_objects(self) -> tuple[str, ...]:
        """Return whole stage objects, suppressing internal artwork and skeleton controls."""
        records = self.records()
        actors = {key: c.id for c in self.scene.characters for key in c.object_ids}
        part_groups = {key for c in self.scene.characters for key in c.extra.get("part_groups", ())}
        result = []
        for entry in (*self.scene.groups, *self.scene.objects, *self.scene.characters):
            if entry.extra.get("studio_floor_plant"):
                continue
            root = self.object_root(entry.id)
            if root and root.id != entry.id:
                continue
            if entry.id in actors:
                continue
            if entry.id in part_groups:
                continue
            parent = getattr(entry, "parent_id", None)
            if parent in records and self.object_root(str(parent)):
                continue
            result.append(entry.id)
        return tuple(result)

    def skin_group(self, owner: str, name: str) -> str:
        """Define an independent skin/color group on a solid or rigged object."""
        groups = json_copy(self.record(owner).extra.get("skins", ()))
        key = str(uuid4())
        root = self.record(owner)
        groups.append(
            {
                "id": key,
                "name": name.strip() or "Skin",
                "variants": [],
                **(
                    {"object_view": root.extra.get("active_view", "Default")}
                    if root.extra.get("view_slots")
                    else {}
                ),
            }
        )
        self.commit("Add skin group", **self._extra_patch(owner, "skins", groups))
        return key

    def appearance_groups(self, owner: str, kind: str) -> tuple[dict[str, Any], ...]:
        """Offer the edited view's saved looks in Object Editor, and all looks in Scene."""
        root = self.record(owner)
        groups = tuple(root.extra.get(kind, ()))
        if self.document.animation_context != owner or not root.extra.get("view_slots"):
            return groups
        from rigora.application_services.object_views import ObjectViewsService

        members = ObjectViewsService(self.document).edit_members(owner)
        active = root.extra.get("active_view", "Default")
        result = []
        for group in groups:
            variants = tuple(
                v
                for v in group["variants"]
                if (
                    group.get("object_view") == active
                    or any(k in members for k, _, _ in v.get("values", ()))
                    or set(v.get("meshes", ())).intersection(members)
                )
            )
            if variants or not group["variants"] and group.get("object_view", "Default") == active:
                result.append({**group, "variants": variants})
        return tuple(result)

    def key_appearance(
        self,
        owner: str,
        kind: str,
        group_id: str,
        name: str,
        values: dict[tuple[str, str], float],
        *,
        choice: dict[str, Any] | None = None,
        frame: float | None = None,
    ) -> None:
        """Step-key an appearance choice above source motion tracks without editing the source.

        Each group uses ordinary visibility/color scalars. Before the first choice key,
        the source action or default appearance remains in control.
        """
        editor = AnimationEditingService(self.document)
        frame = self.document.animation.pose.frame if frame is None else number(frame)
        timeline = editor.timeline or Timeline(name="Animation")
        clip = editor.clip or editor.blank_clip(timeline)
        tracks = list(timeline.tracks)
        if any(
            t.locked
            and not t.extra.get("motion_window")
            and t.extra.get("appearance_owner") == owner
            and t.extra.get("appearance_kind") == kind
            for t in tracks
        ):
            raise ProjectError("Unlock the appearance row before adding keys.")
        for index, candidate in enumerate(tracks):
            if (
                candidate.extra.get("appearance_owner") == owner
                and candidate.extra.get("appearance_group") == group_id
                and not candidate.extra.get("motion_window")
                and (candidate.owner_id, candidate.property_path) not in values
                and any(k.frame == frame for k in candidate.keyframes)
            ):
                editor.editable(candidate)
                tracks[index] = replace(
                    candidate, keyframes=tuple(k for k in candidate.keyframes if k.frame != frame)
                )
        for channel, value in values.items():
            track = next(
                (
                    t
                    for t in tracks
                    if (t.owner_id, t.property_path) == channel
                    and t.extra.get("appearance_group") == group_id
                    and not t.extra.get("motion_window")
                ),
                None,
            )
            if track is None:
                track = Track(
                    name=("Skin" if kind == "skins" else "Clothing") + " · " + name,
                    owner_id=channel[0],
                    property_path=channel[1],
                    extra={
                        "appearance_owner": owner,
                        "appearance_group": group_id,
                        "appearance_kind": kind,
                        "active_from_first_key": True,
                    },
                )
                tracks.append(track)
            editor.editable(track)
            updated = editor.keyed_track(track, frame, value, "step")
            if choice is not None:
                updated = replace(
                    updated,
                    keyframes=tuple(
                        replace(k, extra={**k.extra, "appearance_choice": choice})
                        if k.frame == frame
                        else k
                        for k in updated.keyframes
                    ),
                )
            tracks = [updated if t.id == track.id else t for t in tracks]
        editor.publish(
            "Key appearance choice",
            replace(timeline, tracks=tuple(tracks)),
            replace(clip, out_frame=max(clip.out_frame, frame)),
        )

    def save_skin(self, owner: str, group_id: str, mesh_ids: tuple[str, ...], name: str) -> str:
        """Snapshot evaluated SVG paints, borders and raster tint without copying image data."""
        from rigora.application_services.appearance import AppearanceService

        if not mesh_ids or not set(mesh_ids) <= set(self.meshes_for((owner,))):
            raise ProjectError("Select image parts inside this object for the skin.")
        groups = json_copy(self.record(owner).extra.get("skins", ()))
        group = next((g for g in groups if g["id"] == group_id), None)
        if group is None:
            raise ProjectError("Choose a skin group first.")
        key = str(uuid4())
        with self.document.command_group("Save skin preset"):
            appearance = AppearanceService(self.document)
            values: list[tuple[str, str, float]] = []
            for mesh_id in mesh_ids:
                stage = appearance.ensure(mesh_id)
                look = self.document.animation.pose.meshes[mesh_id].appearance
                for i, paint in enumerate(look.get("palette", ())):
                    values.extend(
                        (stage, f"parameters.palette.{i}.{c}", paint[c]) for c in ("r", "g", "b")
                    )
                values.extend(
                    (stage, f"parameters.tint.{c}", v) for c, v in look.get("tint", {}).items()
                )
                values.append((stage, "parameters.stroke_width", look.get("stroke_width", -1)))
            group["variants"].append({"id": key, "name": name.strip() or "Skin", "values": values})
            group.setdefault("default", key)
            group["selected"] = key
            self.commit("Save skin preset", **self._extra_patch(owner, "skins", groups))
        return key

    def appearance_default(
        self, owner: str, kind: str, group_id: str, variant_id: str | None
    ) -> None:
        """Choose the default skin or clothing option, including no clothing."""
        if kind not in ("skins", "outfits"):
            raise ProjectError("Choose Skin or Clothing.")
        groups = json_copy(self.record(owner).extra.get(kind, ()))
        group = next((g for g in groups if g["id"] == group_id), None)
        if (
            group is None
            or variant_id is not None
            and not any(v["id"] == variant_id for v in group["variants"])
        ):
            raise ProjectError("Choose an existing appearance option.")
        group["default"] = variant_id
        self.commit("Set appearance default", **self._extra_patch(owner, kind, groups))

    def apply_skin(
        self,
        owner: str,
        group_id: str,
        variant_id: str,
        *,
        auto_key: bool = False,
        frame: float | None = None,
    ) -> None:
        """Apply a saved look to base artwork or step-key it in either workspace's timeline."""
        groups = json_copy(self.record(owner).extra.get("skins", ()))
        group = next((g for g in groups if g["id"] == group_id), None)
        variant = (
            next((v for v in group["variants"] if v["id"] == variant_id), None) if group else None
        )
        if variant is None or group is None:
            raise ProjectError("Choose an existing skin option.")
        values = {
            (key, path): value
            for key, path, value in variant["values"]
            if any(d.id == key for d in self.scene.deformers)
        }
        with self.document.command_group("Switch skin"):
            if auto_key:
                self.key_appearance(
                    owner,
                    "skins",
                    group_id,
                    group["name"],
                    values,
                    choice={"id": variant_id, "name": variant["name"], "visible": True},
                    frame=frame,
                )
            else:
                from rigora.application_services.appearance import AppearanceService

                appearance = AppearanceService(self.document)
                for stage in {k for k, _ in values}:
                    appearance.edit(
                        (str(appearance.stage(stage).owner_id),),
                        {
                            p.removeprefix("parameters."): v
                            for (k, p), v in values.items()
                            if k == stage
                        },
                    )
            assert group is not None
            if not auto_key:
                group["selected"] = variant_id
                self.commit("Remember skin choice", **self._extra_patch(owner, "skins", groups))

    def create_object(self, keys: tuple[str, ...] = (), name: str = "Object") -> str:
        """Create a solid compound object, preserving parts' world poses without inventing a rig."""
        pose = self.document.animation.pose
        meshes = set(self.meshes_for(keys))
        points = [
            transform_point(pose.nodes[str(m.object_id)].world_matrix, *point)
            for m in pose.meshes.values()
            if m.id in meshes
            for point in m.positions
        ]
        center = (
            tuple((min(p[i] for p in points) + max(p[i] for p in points)) / 2 for i in (0, 1))
            if points
            else (self.scene.settings.width / 2, self.scene.settings.height / 2)
        )
        group = Group(
            name=name.strip() or "Object",
            transform=Transform(x=center[0], y=center[1]),
            extra={"object_container": True},
        )
        with self.document.command_group("Create object"):
            self.commit("Create object container", groups=(*self.scene.groups, group))
            if keys:
                self.move_entries(keys, group.id)
            skin_stages = tuple(
                replace(
                    d,
                    parameters={
                        **d.parameters,
                        "object_group": group.id,
                        "object_group_bind": self.document.animation.pose.nodes[
                            group.id
                        ].world_matrix,
                    },
                )
                if d.kind == "skinning"
                and d.owner_id in meshes
                and not d.parameters.get("object_group")
                else d
                for d in self.scene.deformers
            )
            if skin_stages != self.scene.deformers:
                self.commit("Own object skin space", deformers=skin_stages)
        return group.id

    def object_root(self, key: str) -> Group | None:
        """Find the outer compound object for an artwork, folder, character or bone identity."""
        records = self._records()
        if key not in records:
            mesh = next((m for m in self.scene.meshes if m.id == key), None)
            key = str(mesh.object_id) if mesh else key
        entry = records.get(key)
        actor = (
            entry
            if isinstance(entry, Character)
            else next(
                (
                    c
                    for c in self.scene.characters
                    if c.id == self._character_parents.get(key) or c.skeleton_id == key
                ),
                None,
            )
        )
        if actor and actor.object_ids:
            key = actor.object_ids[0]
        elif actor and actor.extra.get("object_id"):
            key = actor.extra["object_id"]
        found = None
        while key in records:
            entry = records[key]
            if isinstance(entry, Group) and entry.extra.get("object_container"):
                found = entry
            key = getattr(entry, "parent_id", None) or ""
        return found

    def promote_object(self, key: str) -> str:
        """Give a solid image an editable container without changing its animated identity.

        The existing transform and channels stay on the container. A new identity-transform
        child owns the original mesh, so every sampled pose and authored key remains intact.
        """
        source = self.record(key)
        if isinstance(source, Group):
            return source.id
        if not isinstance(source, SceneObject) or any(
            source.id in actor.object_ids for actor in self.scene.characters
        ):
            raise ProjectError("Choose a solid object to add editable parts.")
        root = Group(
            id=source.id,
            name=source.name,
            parent_id=source.parent_id,
            layer_id=source.layer_id,
            transform=source.transform,
            extra={**source.extra, "object_container": True, "visible": source.visible},
        )
        part = SceneObject(
            name=source.name, parent_id=root.id, layer_id=source.layer_id, asset_id=source.asset_id
        )
        self.commit(
            "Add object container",
            groups=(*self.scene.groups, root),
            objects=tuple(part if obj.id == source.id else obj for obj in self.scene.objects),
            meshes=tuple(
                replace(mesh, object_id=part.id) if mesh.object_id == source.id else mesh
                for mesh in self.scene.meshes
            ),
            draw_order=tuple(
                part.id if identity == source.id else identity for identity in self.scene.draw_order
            ),
        )
        return root.id

    def add_object_parts(self, object_id: str, mesh_ids: tuple[str, ...]) -> None:
        """Adopt source parts into a compound object while retaining imported folder structure."""
        target = self.record(object_id)
        if not isinstance(target, Group):
            raise ProjectError("Choose an object container first.")
        incoming = set(mesh_ids)
        records = self.records()
        roots = set()
        for mesh_id in mesh_ids:
            key = str(self.mesh(mesh_id).object_id)
            parent = getattr(records[key], "parent_id", None)
            while parent and parent != object_id:
                if not isinstance(records.get(parent), Group):
                    break
                if set(self.meshes_for((parent,))) - incoming:
                    break
                key, parent = parent, getattr(records[parent], "parent_id", None)
            if parent != object_id:
                roots.add(key)
        with self.document.command_group("Add object parts"):
            if roots:
                self.move_entries(tuple(sorted(roots)), object_id)
            if not target.extra.get("object_container") and self.object_root(object_id) is None:
                self.update_records(
                    {target.id: replace(target, extra={**target.extra, "object_container": True})},
                    "Mark object container",
                )
            actor = next(
                (
                    c
                    for c in self.scene.characters
                    if c.object_ids
                    and c.object_ids[0] in self.members(object_id)
                    or c.extra.get("object_id") == object_id
                ),
                None,
            )
            if actor:
                from rigora.application_services.image_rigging import ImageRigService

                ImageRigService(self.document).add_parts(actor.id, mesh_ids)

    def character(self, key: str) -> Character:
        """Resolve a character UUID independently of viewport bone selection."""
        found = next((c for c in self.scene.characters if c.id == key), None)
        if found is None:
            raise ProjectError("Choose a character first.")
        return found

    def rename_character(self, key: str, name: str) -> None:
        """Rename the scene's character record without conflating it with a layer or skeleton."""
        self.character(key)
        self.commit(
            "Rename character",
            characters=tuple(
                replace(c, name=name) if c.id == key else c for c in self.scene.characters
            ),
        )

    def outfit_mode(self, character_id: str, group_id: str, multiple: bool) -> None:
        """Set a clothing group's exclusivity, keeping at most its first visible variation."""
        actor = self.record(character_id)
        groups = json_copy(actor.extra.get("outfits", []))
        group = next((g for g in groups if g["id"] == group_id), None)
        if group is None:
            raise ProjectError("Choose a clothing group first.")
        group["multiple"] = bool(multiple)
        with self.document.command_group("Change clothing group"):
            self.commit(
                "Change clothing policy",
                **self._extra_patch(actor.id, "outfits", groups),
            )
            first = next((v for v in group["variants"] if v.get("visible")), None)
            if not multiple and first:
                self.show_variant(character_id, group_id, first["id"], True)

    def meshes_for(self, keys: tuple[str, ...]) -> tuple[str, ...]:
        """Resolve images inside selected folders as well as direct image/mesh selections."""
        records = self.records()
        selected = set(keys)
        for actor in self.scene.characters:
            if (
                actor.id in selected
                or actor.skeleton_id in selected
                or actor.extra.get("object_id") in selected
            ):
                selected.update(actor.object_ids)
                selected.add(actor.skeleton_id)
        for rig in self.scene.skeletons:
            if (
                rig.id in selected
                or rig.extra.get("object_id") in selected
                or rig.extra.get("object_id") in records
                and self._has_ancestor(str(rig.extra["object_id"]), selected, records)
            ):
                selected.update(b.id for b in rig.bones)
        selected.update(
            d.owner_id
            for d in self.scene.deformers
            if d.kind == "skinning" and selected.intersection(d.parameters.get("bind_matrices", {}))
        )
        return tuple(
            m.id
            for m in self.scene.meshes
            if m.id in selected
            or m.object_id in selected
            or self._has_ancestor(m.object_id or "", selected, records)
        )

    def owner(self, mesh_id: str) -> Character | None:
        """Find the character owning a part, including older explicit bone bindings."""
        mesh = self.mesh(mesh_id)
        explicit = next(
            (
                c
                for c in self.scene.characters
                if mesh_id in c.mesh_ids or c.skeleton_id == mesh.extra.get("rig_skeleton_id")
            ),
            None,
        )
        return explicit or next(
            (c for c in self.scene.characters if mesh_id in self.meshes_for((c.skeleton_id,))), None
        )

    def members(self, character_id: str) -> set[str]:
        """Collect actor-owned channels for look, motion and group operations."""
        entry = self.records().get(character_id)
        if isinstance(entry, (Group, SceneObject)):
            records = self.records()
            keys = {entry.id} | {
                key for key in records if self._has_ancestor(key, {entry.id}, records)
            }
            keys.update(m.id for m in self.scene.meshes if m.object_id in keys)
            keys.update(
                key
                for rig in self.scene.skeletons
                if rig.extra.get("object_id") in keys
                for key in (rig.id, *(bone.id for bone in rig.bones))
            )
            for actor in self.scene.characters:
                if set(actor.object_ids) & keys or actor.extra.get("object_id") in keys:
                    keys.update({actor.id, actor.skeleton_id, *self.members(actor.id)})
            keys.update(d.id for d in self.scene.deformers if d.owner_id in keys)
            keys.update(c.id for c in self.scene.constraints if c.owner_id in keys)
            keys.update(o.id for o in self.scene.objects if o.extra.get("contact_owner") in keys)
            keys.update(v.id for m in self.scene.meshes if m.id in keys for v in m.vertices)
            return keys
        c = self.character(character_id)
        mesh_ids = set(c.mesh_ids) | set(self.meshes_for((c.id, c.skeleton_id)))
        keys = {*c.object_ids, *mesh_ids}
        keys.update(m.object_id for m in self.scene.meshes if m.id in mesh_ids and m.object_id)
        keys.update(
            k for k in c.extra.get("part_groups", ()) if any(g.id == k for g in self.scene.groups)
        )
        keys.update(b.id for r in self.scene.skeletons if r.id == c.skeleton_id for b in r.bones)
        records = self.records()
        keys.update(
            constraint.target_id
            for constraint in self.scene.constraints
            if constraint.owner_id in keys
            and constraint.target_id in records
            and records[constraint.target_id].extra.get("studio_floor_plant")
        )
        keys.update(d.id for d in self.scene.deformers if d.owner_id in keys)
        keys.update(c.id for c in self.scene.constraints if c.owner_id in keys)
        keys.update(o.id for o in self.scene.objects if o.extra.get("contact_owner") in keys)
        keys.update(v.id for m in self.scene.meshes if m.id in keys for v in m.vertices)
        return keys

    def part_group(
        self, character_id: str, keys: tuple[str, ...], name: str = "Parts folder"
    ) -> str:
        """Create an owned parts folder, including empty folders in isolated character editing."""
        actor = self.character(character_id)
        with self.document.command_group("Add parts folder"):
            group = self.group(keys, name)
            self.commit(
                "Own parts folder",
                characters=tuple(
                    replace(
                        c,
                        extra={**c.extra, "part_groups": [*c.extra.get("part_groups", ()), group]},
                    )
                    if c.id == actor.id
                    else c
                    for c in self.scene.characters
                ),
            )
        return group

    def delete_character(self, character_id: str) -> None:
        """Delete one complete character while retaining reusable imported source assets."""
        actor = self.character(character_id)
        rig = next(r for r in self.scene.skeletons if r.id == actor.skeleton_id)
        owned = set(actor.object_ids)
        records = self.records()
        bone_ids = {b.id for b in rig.bones}
        owned.update(
            c.target_id
            for c in self.scene.constraints
            if c.owner_id in bone_ids
            and c.target_id in records
            and records[c.target_id].extra.get("studio_floor_plant")
        )
        for group in self.scene.groups:
            parts = {
                o.id for o in self.scene.objects if self._has_ancestor(o.id, {group.id}, records)
            }
            if not group.extra.get("scene_folder") and (
                group.id in actor.extra.get("part_groups", ()) or parts and parts <= owned
            ):
                owned.add(group.id)
        from rigora.application_services.rigging import RigService

        with self.document.command_group("Delete character"):
            RigService(self.document).delete_many(tuple(b.id for b in rig.bones), remove_rig=True)
            self.delete_entries(tuple(owned))
            self.commit(
                "Remove character container",
                characters=tuple(c for c in self.scene.characters if c.id != actor.id),
                skeletons=tuple(r for r in self.scene.skeletons if r.id != actor.skeleton_id),
            )

    def flip(self, keys: tuple[str, ...], *, vertical: bool = False) -> None:
        """Mirror character parts and rig together about their shared visible bounds."""
        expanded = set(keys)
        records = self.records()
        placed_rigs = {
            r.id
            for r in self.scene.skeletons
            if (owner := r.extra.get("object_id")) in records
            and (owner in expanded or self._has_ancestor(str(owner), expanded, records))
            and (
                r.extra.get("library_bind")
                or any(
                    d.kind == "skinning" and d.parameters.get("object_group") == owner
                    for d in self.scene.deformers
                )
            )
        }
        for mesh_id in self.meshes_for(keys):
            actor = self.owner(mesh_id)
            if actor:
                expanded.update(actor.object_ids)
                expanded.update(
                    b.id
                    for r in self.scene.skeletons
                    if r.id == actor.skeleton_id and r.id not in placed_rigs
                    for b in r.bones
                    if b.parent_id is None
                )
        pose = self.document.animation.pose
        points = [
            transform_point(pose.nodes[m.object_id].world_matrix, *p)
            for m in pose.meshes.values()
            if m.object_id in expanded
            for p in m.positions
        ]
        if not points:
            raise ProjectError("Select artwork or a character to flip.")
        cx, cy = (min(p[i] for p in points) + max(p[i] for p in points) for i in (0, 1))
        baseline = self.document.fork() if self.auto_key else None
        with self.document.command_group("Flip facing"):
            self.transform(
                tuple(expanded),
                scale_x=1 if vertical else -1,
                scale_y=-1 if vertical else 1,
                center_x=cx / 2,
                center_y=cy / 2,
            )
            editor = AnimationEditingService(self.document)
            if (
                baseline
                and editor.timeline
                and editor.clip
                and pose.frame > self.scene.settings.start_frame
            ):
                boundary = max(self.scene.settings.start_frame, pose.frame - 1e-5)
                channels = tuple(
                    (t.owner_id, t.property_path)
                    for t in editor.timeline.tracks
                    if t.owner_id in expanded
                    and t.property_path.startswith("transform.")
                    and any(k.frame == pose.frame for k in t.keyframes)
                )
                previous = AnimationEditingService(baseline)
                previous.auto_key_values(previous.capture_values(channels, boundary), boundary)
                assert previous.timeline is not None
                raw = {
                    channel: next(
                        k.value
                        for t in previous.timeline.tracks
                        if (t.owner_id, t.property_path) == channel
                        for k in t.keyframes
                        if k.frame == boundary
                    )
                    for channel in channels
                }
                tracks = []
                for track in editor.timeline.tracks:
                    channel = track.owner_id, track.property_path
                    if channel in raw:
                        track = editor.keyed_track(track, boundary, raw.pop(channel), "step")
                    tracks.append(track)
                editor.publish(
                    "Key facing change", replace(editor.timeline, tracks=tuple(tracks)), editor.clip
                )

    def wardrobe_group(self, character_id: str, name: str, *, multiple: bool = False) -> str:
        """Create a named outfit group; each variant may contain several imported image parts."""
        c = self.record(character_id)
        key = str(uuid4())
        groups = [
            *json_copy(c.extra.get("outfits", [])),
            {
                "id": key,
                "name": name.strip() or "Outfits",
                "multiple": multiple,
                "variants": [],
                **(
                    {"object_view": c.extra.get("active_view", "Default")}
                    if c.extra.get("view_slots")
                    else {}
                ),
            },
        ]
        self.commit(
            "Add outfit group",
            **self._extra_patch(c.id, "outfits", groups),
        )
        return key

    def add_variant(
        self,
        character_id: str,
        group_id: str,
        mesh_ids: tuple[str, ...],
        name: str,
        *,
        occludes: tuple[str, ...] = (),
        visibility_roots: tuple[str, ...] = (),
        match_any: bool = False,
    ) -> str:
        """Register clothing and covered body parts, retaining replaceable source meshes."""
        c = self.record(character_id)
        groups = json_copy(c.extra.get("outfits", []))
        group = next((g for g in groups if g["id"] == group_id), None)
        if group is None or not mesh_ids:
            raise ProjectError("Choose an outfit group and select its image parts in Scene.")
        for key in mesh_ids:
            self.mesh(key)
        if visibility_roots and not set(visibility_roots) <= self.members(character_id):
            raise ProjectError("Variant visibility controls must belong to this object.")
        if not set(occludes) <= set(self.meshes_for((character_id,))) or set(occludes) & set(
            mesh_ids
        ):
            raise ProjectError("Covered body parts must be other image parts inside this object.")
        variant: dict[str, Any] = {
            "id": str(uuid4()),
            "name": name.strip() or "Outfit",
            "meshes": list(mesh_ids),
            "visible": False,
            **({"occludes": list(occludes)} if occludes else {}),
            **({"visibility_roots": list(visibility_roots)} if visibility_roots else {}),
            **({"match_any": True} if match_any else {}),
        }
        group["variants"].append(variant)
        group.setdefault("default", variant["id"])
        with self.document.command_group("Add outfit variant"):
            from rigora.application_services.image_rigging import ImageRigService

            if isinstance(c, Character):
                ImageRigService(self.document).add_parts(character_id, mesh_ids)
            elif not set(mesh_ids) <= set(self.meshes_for((character_id,))):
                raise ProjectError("Clothing parts must belong to this object.")
            self.commit(
                "Add outfit variant",
                **self._extra_patch(c.id, "outfits", groups),
            )
            self.show_variant(character_id, group_id, variant["id"], True)
        return str(variant["id"])

    def variant_visible(self, variant: Mapping[str, Any], pose: ScenePose) -> bool:
        """Match a variation against evaluated controls, including gated facial subposes."""
        owners = tuple(variant.get("visibility_roots", ())) or tuple(
            pose.meshes[key].object_id for key in variant.get("meshes", ()) if key in pose.meshes
        )
        states = [pose.nodes[str(owner)].visible for owner in owners if owner in pose.nodes]
        return bool(states) and (any(states) if variant.get("match_any") else all(states))

    def show_variant(
        self,
        character_id: str,
        group_id: str,
        variant_id: str | None,
        visible: bool,
        *,
        auto_key: bool = False,
        frame: float | None = None,
    ) -> None:
        """Show one, many or no variants using normal animatable object visibility."""
        c = self.record(character_id)
        groups = json_copy(c.extra.get("outfits", []))
        group = next((g for g in groups if g["id"] == group_id), None)
        if group is None:
            raise ProjectError("Choose an outfit group.")
        if variant_id is not None and not any(v["id"] == variant_id for v in group["variants"]):
            raise ProjectError("Choose an existing clothing option.")
        if auto_key:
            pose = (
                self.document.animation.evaluate(frame)
                if frame is not None
                else self.document.animation.pose
            )
            for saved_group in groups:
                for variant in saved_group["variants"]:
                    variant["visible"] = self.variant_visible(variant, pose)
        channels = {}
        with self.document.command_group("Switch outfit"):
            for variant in group["variants"]:
                if (
                    variant_id is None
                    or variant["id"] == variant_id
                    or not group["multiple"]
                    and visible
                ):
                    variant["visible"] = visible if variant["id"] == variant_id else False
                    objects = tuple(variant.get("visibility_roots", ())) or tuple(
                        self.mesh(k).object_id for k in variant["meshes"] if self.mesh(k).object_id
                    )
                    if auto_key:
                        channels.update(
                            {(str(k), "visibility"): float(variant["visible"]) for k in objects}
                        )
                    else:
                        self.flags(tuple(str(k) for k in objects), visible=variant["visible"])
            variants = [v for g in groups for v in g["variants"]]
            covered = {k for v in variants if v["visible"] for k in v.get("occludes", ())}
            for key in {k for v in variants for k in v.get("occludes", ())}:
                owner = self.mesh(key).object_id
                if owner:
                    if auto_key:
                        channels[owner, "visibility"] = float(key not in covered)
                    else:
                        self.flags((owner,), visible=key not in covered)
            if channels:
                chosen = next((v for v in group["variants"] if v["id"] == variant_id), None)
                self.key_appearance(
                    character_id,
                    "outfits",
                    group_id,
                    group["name"],
                    channels,
                    choice={
                        "id": variant_id,
                        "name": chosen["name"] if chosen else "None",
                        "visible": visible if chosen else False,
                    },
                    frame=frame,
                )
            if not auto_key:
                self.commit(
                    "Remember outfit selection",
                    **self._extra_patch(c.id, "outfits", groups),
                )

    def saved_outfit_sets(self, character_id: str) -> Mapping[str, Any]:
        """Read coordinated Creator sets from the compound Object rather than individual meshes."""
        record = self.record(character_id)
        root = self.object_root(character_id)
        saved = root or (
            self.record(str(record.extra["object_id"])) if record.extra.get("object_id") else record
        )
        values = saved.extra.get("creator_outfit_sets", {})
        return dict(values) if isinstance(values, Mapping) else {}

    def apply_outfit_set(self, character_id: str, name: str, *, auto_key: bool = False) -> None:
        """Apply saved category choices atomically through ordinary appearance keys."""
        choices = self.saved_outfit_sets(character_id).get(name)
        if not isinstance(choices, Mapping):
            raise ProjectError("Choose a saved outfit set.")
        root = self.object_root(character_id)
        owner = root.id if root else character_id
        groups = self.appearance_groups(owner, "outfits")
        selected = []
        for category, value in choices.items():
            group = next((g for g in groups if g["name"] == category), None)
            variant = (
                next((v for v in group["variants"] if v["name"] == value), None) if group else None
            )
            if group is None or variant is None:
                raise ProjectError(
                    "This set has a missing part; restore its retained alternatives."
                )
            selected.append((group["id"], variant["id"]))
        with self.document.command_group("Apply outfit set"):
            for group_id, variant_id in selected:
                self.show_variant(owner, group_id, variant_id, True, auto_key=auto_key)

    def motions(self, character_id: str) -> tuple[AnimationClip, ...]:
        """List this character's reusable clips, excluding scene arrangements."""
        owners = self.members(character_id)
        timelines = {t.id: t for t in self.scene.timelines}
        return tuple(
            c
            for c in self.scene.clips
            if not c.extra.get("motion_sequence")
            and not c.extra.get("main_scene")
            and (
                c.extra.get("character_id") == character_id
                or c.extra.get("object_id") in owners
                or any(t.owner_id in owners for t in timelines[c.timeline_id].tracks)
            )
        )

    def remove_motion(self, owner: str, clip_id: str) -> None:
        """Remove an Object action and its linked Scene placements in one reversible edit.

        Artwork and deformation stages remain. Shared timelines survive while referenced
        by another clip; state-machine references must be released before deletion.
        """
        source = next((c for c in self.motions(owner) if c.id == clip_id), None)
        if source is None:
            raise ProjectError("Choose an animation belonging to this Object.")
        if self.locked(owner):
            raise ProjectError("Unlock the Object before removing its animation.")
        for record in (*self.scene.groups, *self.scene.objects, *self.scene.characters):
            definition = record.extra.get("state_machine", {})
            if isinstance(definition, Mapping) and any(
                isinstance(state, Mapping) and state.get("clip") == clip_id
                for state in definition.get("states", ())
            ):
                raise ProjectError(
                    "Remove this animation from its state machine before deleting it."
                )
        clips = tuple(c for c in self.scene.clips if c.id != clip_id)
        retained = {c.timeline_id for c in clips}
        timelines = tuple(
            replace(
                timeline,
                tracks=tuple(
                    t
                    for t in timeline.tracks
                    if t.extra.get("motion_window", {}).get("source") != clip_id
                ),
            )
            for timeline in self.scene.timelines
            if timeline.id != source.timeline_id or timeline.id in retained
        )
        self.commit("Remove object animation", clips=clips, timelines=timelines)

    def new_motion(self, character_id: str, name: str, source_id: str | None = None) -> str:
        """Create a named actor action; duplicated source keys receive independent identities."""
        owner = self.record(character_id)
        if not isinstance(owner, (Character, Group, SceneObject)):
            raise ProjectError("Choose an object or character to create an animation.")
        name = name.strip() or "Character motion"
        if self.document.separated_animation and self.document.animation_context != character_id:
            self.document.set_animation_context(character_id, frozenset(self.members(character_id)))
        source = next((c for c in self.motions(character_id) if c.id == source_id), None)
        if source_id and source is None:
            raise ProjectError("Choose an existing character motion to duplicate.")
        timeline = (
            copied_timeline(next(t for t in self.scene.timelines if t.id == source.timeline_id))
            if source
            else Timeline(name=name)
        )
        owners = self.members(character_id)
        timeline = replace(
            timeline, name=name, tracks=tuple(t for t in timeline.tracks if t.owner_id in owners)
        )
        clip = AnimationClip(
            name=name.strip() or "Character motion",
            timeline_id=timeline.id,
            out_frame=source.out_frame if source else self.scene.settings.end_frame,
            in_frame=source.in_frame if source else 0,
            extra={
                "character_id" if isinstance(owner, Character) else "object_id": character_id,
                **(
                    {"object_view": owner.extra.get("active_view", "Default")}
                    if owner.extra.get("view_slots")
                    else {}
                ),
            },
        )
        AnimationEditingService(self.document).publish("Create character motion", timeline, clip)
        return clip.id

    def place_motion(
        self,
        character_id: str,
        source_id: str,
        start: float,
        seconds: float,
        speed: float = 1,
        repeat: bool = True,
    ) -> str:
        """Place a reusable action in a scene sequence; original source keys remain editable."""
        source = next((c for c in self.motions(character_id) if c.id == source_id), None)
        if source is None:
            raise ProjectError("Choose a motion belonging to this character.")
        if self.document.separated_animation and self.document.animation_context:
            self.document.set_animation_context(None)
        start, seconds, speed = number(start), number(seconds), number(speed)
        if start < 0 or not 0.01 <= seconds <= 3600 or not 0.01 <= speed <= 100:
            raise ProjectError("Motion start, duration or speed is outside its supported range.")
        editor = AnimationEditingService(self.document)
        target = next((c for c in self.scene.clips if c.extra.get("motion_sequence")), None)
        if target is None:
            target = next((c for c in self.scene.clips if c.extra.get("main_scene")), None)
        timeline = next(
            (t for t in self.scene.timelines if target and t.id == target.timeline_id),
            Timeline(name="Scene motions"),
        )
        target = target or AnimationClip(
            name="Scene motions",
            timeline_id=timeline.id,
            out_frame=self.scene.settings.end_frame,
            extra={"motion_sequence": True},
        )
        if any(
            t.editing_locked and t.extra.get("motion_window", {}).get("character") == character_id
            for t in timeline.tracks
        ):
            raise ProjectError("Unlock the Animation row before adding an action.")
        segment_id = str(uuid4())
        metadata: dict[str, Any] = {
            "id": segment_id,
            "character": character_id,
            "name": source.name,
            "source": source.id,
            "start": start,
            "end": start + seconds * self.scene.settings.fps,
            "speed": speed,
            "repeat": repeat,
            "source_start": source.in_frame,
            "source_end": motion_source_end(source),
        }
        original = next(t for t in self.scene.timelines if t.id == source.timeline_id)
        owners = self.members(character_id)
        tracks = tuple(
            replace(
                t,
                id=str(uuid4()),
                locked=True,
                visible=True,
                keyframes=tuple(replace(k, id=str(uuid4())) for k in t.keyframes),
                extra={
                    **t.extra,
                    "motion_window": metadata,
                    "source_track": t.id,
                    "source_visible": t.visible,
                },
            )
            for t in original.tracks
            if t.owner_id in owners
        )
        if not tracks:
            raise ProjectError("Add animation keys to this motion before placing it.")
        editor.publish(
            "Place character motion",
            replace(
                timeline,
                tracks=(
                    *(t for t in timeline.tracks if t.extra.get("motion_window")),
                    *tracks,
                    *(t for t in timeline.tracks if not t.extra.get("motion_window")),
                ),
            ),
            replace(
                target,
                out_frame=max(target.out_frame, metadata["end"]),
                extra={**target.extra, "motion_sequence": True},
            ),
        )
        return segment_id

    def remove_segment(self, segment_id: str) -> None:
        """Remove one arranged motion block while retaining its reusable source action."""
        editor = AnimationEditingService(self.document)
        if editor.timeline and editor.clip:
            if any(
                t.editing_locked and t.extra.get("motion_window", {}).get("id") == segment_id
                for t in editor.timeline.tracks
            ):
                raise ProjectError("Unlock the Animation row before removing an action.")
            editor.publish(
                "Remove motion block",
                replace(
                    editor.timeline,
                    tracks=tuple(
                        t
                        for t in editor.timeline.tracks
                        if t.extra.get("motion_window", {}).get("id") != segment_id
                    ),
                ),
                editor.clip,
            )

    def edit_segment(self, segment_id: str, **changes: Any) -> None:
        """Move/trim a motion block or change playback speed without rewriting source animation."""
        editor = AnimationEditingService(self.document)
        if not editor.timeline or not editor.clip:
            raise ProjectError("Open the scene motion sequence first.")
        if changes.keys() - {
            "start",
            "end",
            "speed",
            "repeat",
            "layer",
            "weight",
            "blend",
            "fade_in",
            "fade_out",
            "mask",
            "muted",
            "solo",
        }:
            raise ProjectError("Unsupported motion timing setting.")
        if not any(
            t.extra.get("motion_window", {}).get("id") == segment_id for t in editor.timeline.tracks
        ):
            raise ProjectError("The motion block no longer exists.")
        tracks = []
        for track in editor.timeline.tracks:
            window = track.extra.get("motion_window", {})
            if window.get("id") == segment_id:
                if track.editing_locked:
                    raise ProjectError("Unlock the Animation row before editing an action.")
                metadata = {**window, **changes}
                from rigora.engine.motion_layers import influence

                influence(metadata, number(metadata["start"]))
                layer = number(metadata.get("layer", 0))
                if layer != int(layer) or not 0 <= layer <= 100:
                    raise ProjectError("Layer order must be an integer from 0 to 100.")
                mask = metadata.get("mask", ())
                if not isinstance(mask, (tuple, list)) or any(
                    k not in self.members(metadata["character"]) for k in mask
                ):
                    raise ProjectError("Layer masks must use parts of this Object.")
                if mask:
                    metadata["mask"] = sorted(
                        set(mask) | {c.id for c in self.scene.constraints if c.owner_id in mask}
                    )
                for flag in ("muted", "solo", "repeat"):
                    if type(metadata.get(flag, False)) is not bool:
                        raise ProjectError("Layer mute, solo and loop flags must be boolean.")
                if metadata["start"] - window["start"] != metadata["end"] - window["end"]:
                    metadata["source_offset"] = (
                        window.get("source_offset", 0)
                        + (metadata["start"] - window["start"]) * window["speed"]
                    )
                if (
                    number(metadata["start"]) < 0
                    or number(metadata["end"]) <= number(metadata["start"])
                    or not 0.01 <= number(metadata["speed"]) <= 100
                ):
                    raise ProjectError("Motion duration and speed must be positive.")
                track = replace(track, extra={**track.extra, "motion_window": metadata})
            tracks.append(track)
        editor.publish(
            "Edit motion block",
            replace(editor.timeline, tracks=tuple(tracks)),
            replace(
                editor.clip,
                out_frame=max(
                    editor.clip.out_frame,
                    *(t.extra.get("motion_window", {}).get("end", 0) for t in tracks),
                ),
            ),
        )
