"""Inspect and edit scene relationships without deleting their endpoints."""

from dataclasses import dataclass, replace

from rigora.application_services.characters import CharacterService
from rigora.application_services.image_rigging import ImageRigService
from rigora.application_services.rigging import RigService, from_matrix
from rigora.application_services.scene_editing import SceneEditingService
from rigora.domain.entities import Bone, Character, Group, SceneObject, Skeleton
from rigora.domain.geometry import inverse, multiply
from rigora.domain.mesh_geometry import normalize_weights
from rigora.domain.project import ProjectError


@dataclass(frozen=True, slots=True)
class Binding:
    """One removable relationship identified independently of either persistent endpoint."""

    id: str
    kind: str
    source: str
    target: str | None


class BindingService(SceneEditingService):
    """Share binding inspection, attachment and reversible cleanup across all clients."""

    def relationships(self, scope: frozenset[str] | None = None) -> tuple[Binding, ...]:
        """Describe all hierarchy, skin, area-pin and constraint connections in this scene."""
        rows = []
        records = self.records()
        for entry in records.values():
            parent = records.get(getattr(entry, "parent_id", None) or "")
            structural = (
                isinstance(parent, Group)
                and parent.extra.get("object_container")
                or isinstance(parent, Bone)
                and parent.extra.get("rig_root")
            )
            if isinstance(entry, (Bone, Group, SceneObject)) and entry.parent_id and not structural:
                rows.append(Binding(f"parent:{entry.id}", "Parent", entry.id, entry.parent_id))
            if isinstance(entry, Bone) and entry.extra.get("spring_group"):
                rows.append(Binding(f"spring-anchor:{entry.id}", "Spring anchor", entry.id, None))
        for stage in self.scene.deformers:
            if stage.kind == "skinning":
                rows.extend(
                    Binding(f"skin:{stage.id}:{bone}", "Skin", stage.owner_id, bone)
                    for bone in stage.parameters.get("bind_matrices", {})
                )
        for mesh in self.scene.meshes:
            rows.extend(
                Binding(f"pin:{mesh.id}:{pin['vertex_id']}", "Area pin", mesh.id, pin["bone_id"])
                for pin in mesh.extra.get("area_pins", ())
            )
        rows.extend(
            Binding(
                f"constraint:{rule.id}",
                rule.kind.replace("_", " ").title(),
                rule.owner_id,
                rule.target_id,
            )
            for rule in self.scene.constraints
            if rule.kind != "scene_attachment"
        )
        return tuple(
            row
            for row in rows
            if scope is None
            or row.source in scope
            and (not row.id.startswith("parent:") or row.target in scope)
        )

    def groups(self, scope: frozenset[str] | None = None) -> tuple[tuple[Binding, ...], ...]:
        """Partition connections by shared endpoints, normalizing meshes to their artwork.

        Structural Object membership is excluded by ``relationships``. The result
        contains disjoint connected sets and never changes authored hierarchy.
        """
        owners = {m.id: str(m.object_id) for m in self.scene.meshes}
        parents: dict[str, str] = {}

        def root(key: str) -> str:
            """Resolve and compress an endpoint's connected-component representative."""
            parents.setdefault(key, key)
            cursor = key
            while parents[cursor] != cursor:
                cursor = parents[cursor]
            while parents[key] != key:
                parent = parents[key]
                parents[key] = cursor
                key = parent
            return cursor

        rows = self.relationships(scope)
        for row in rows:
            source = owners.get(row.source, row.source)
            root(source)
            if row.target:
                target = owners.get(row.target, row.target)
                parents[root(target)] = root(source)
        groups: dict[str, list[Binding]] = {}
        for row in rows:
            groups.setdefault(root(owners.get(row.source, row.source)), []).append(row)
        return tuple(tuple(rows) for rows in groups.values())

    def bind(self, sources: tuple[str, ...], target: str, *, rigid: bool = False) -> None:
        """Bind bones to parents, artwork to bones, or rigid artwork to other artwork.

        Sources may be meshes, scene objects or folders. Target selection never deletes
        data; invalid or cyclic combinations roll back the entire command group.
        """
        records = self.records()
        meshes = {m.id: m for m in self.scene.meshes}
        target = str(meshes[target].object_id) if target in meshes else target
        destination = records.get(target)
        if not isinstance(destination, (Bone, Group, SceneObject)):
            raise ProjectError("Choose a bone, image, shape or folder as the binding target.")
        keys = tuple(dict.fromkeys(k for k in sources if k != target))
        if not keys:
            raise ProjectError("Choose a source different from the binding target.")
        if self.locked(target):
            raise ProjectError("Unlock the binding target first.")
        keys = tuple(dict.fromkeys(str(meshes[k].object_id) if k in meshes else k for k in keys))
        keys = tuple(k for k in keys if k != target)
        if not keys:
            raise ProjectError("Choose a source different from the binding target.")
        for key in keys:
            if not isinstance(records.get(key), (Bone, SceneObject, Group)) or self.locked(key):
                raise ProjectError("Select unlocked bones, images, shapes or folders to bind.")
        with self.document.command_group("Bind selection"):
            bones = tuple(k for k in keys if isinstance(records[k], Bone))
            artwork = tuple(k for k in keys if k not in bones)
            if bones:
                if not isinstance(destination, Bone):
                    raise ProjectError("A bone's parent must be another bone in its skeleton.")
                self.move_bones(bones, target)
            if artwork:
                whole = tuple(
                    key
                    for key in artwork
                    if isinstance(records[key], Group)
                    and records[key].extra.get("object_container")
                )
                if whole:
                    self.attach(whole, target)
                artwork = tuple(key for key in artwork if key not in whole)
                if not artwork:
                    return
                parts = CharacterService(self.document).meshes_for(artwork)
                owners = set(artwork) | {
                    key for key in records if self._has_ancestor(key, set(artwork), records)
                }
                self.remove_relationships(
                    tuple(
                        row.id
                        for row in self.relationships()
                        if row.source in owners
                        and row.id.startswith("constraint:")
                        and row.kind == "Parent"
                    ),
                    cleanup_physics=False,
                )
                if isinstance(destination, Bone) and not rigid:
                    if not parts:
                        raise ProjectError(
                            "The selected artwork has no mesh to skin. Use Rigid follow."
                        )
                    for mesh_id in parts:
                        ImageRigService(self.document).bind_image(mesh_id, target)
                else:
                    ImageRigService(self.document).detach(parts, cleanup_physics=False)
                    self.attach(artwork, target)

    def unbind(self, sources: tuple[str, ...]) -> None:
        """Remove selected sources' bindings, preserving bones and character membership.

        Selecting a bone also releases artwork driven by it and its physics/constraints.
        Other bones in the same rig retain their bindings and animation.
        """
        records = self.records()
        keys = set(sources)
        if not keys:
            raise ProjectError("Select bones or artwork to unbind first.")
        mesh_owners = {m.id: str(m.object_id) for m in self.scene.meshes}
        for key in keys:
            if key not in mesh_owners and not isinstance(
                records.get(key), (Bone, SceneObject, Group, Character, Skeleton)
            ):
                raise ProjectError("The selected binding source no longer exists.")
            if self.locked(mesh_owners.get(key, key)):
                raise ProjectError("Unlock the selected source before unbinding.")
        bones = {k for k in keys if isinstance(records.get(k), Bone)}
        meshes = CharacterService(self.document).meshes_for(tuple(keys - bones))
        keys.update(meshes)
        containers = {key for key in keys if isinstance(records.get(key), (Group, SceneObject))}
        owners = keys | {key for key in records if self._has_ancestor(key, containers, records)}
        keys.update(owners)
        rows = tuple(
            row.id
            for row in self.relationships()
            if row.source in keys
            and (not row.id.startswith("parent:") or row.source in bones)
            or row.target in bones
            and (row.kind != "Parent" or row.id.startswith("constraint:"))
        )
        with self.document.command_group("Unbind selection"):
            self.remove_relationships(rows)
            ImageRigService(self.document).detach(meshes)
            self.remove_physics(bones)

    def remove_relationships(
        self, identities: tuple[str, ...], *, cleanup_physics: bool = True
    ) -> None:
        """Remove inspected rows; stale identities fail instead of deleting entries."""
        if not identities:
            return
        rows = {row.id: row for row in self.relationships()}
        if any(key not in rows for key in identities):
            raise ProjectError("A binding changed. Refresh the binding list and try again.")
        selected = [rows[key] for key in dict.fromkeys(identities)]
        mesh_owners = {m.id: str(m.object_id) for m in self.scene.meshes}
        for row in selected:
            if self.locked(mesh_owners.get(row.source, row.source)):
                raise ProjectError("Unlock the bound source before removing its binding.")
        pose = self.document.animation.pose
        candidates: set[str] = set()
        removed_rules = {
            row.id.split(":")[1] for row in selected if row.id.startswith("constraint:")
        }
        skin: dict[str, set[str | None]] = {}
        pins: dict[str, set[str]] = {}
        parents = []
        for row in selected:
            if row.id.startswith("skin:"):
                skin.setdefault(row.id.split(":")[1], set()).add(row.target)
                if row.target:
                    candidates.add(row.target)
            elif row.id.startswith("pin:"):
                pins.setdefault(row.source, set()).add(row.id.split(":")[2])
                if row.target:
                    candidates.add(row.target)
            elif row.id.startswith("parent:"):
                parents.append(row.source)
            elif row.kind in ("Spring", "Spring anchor"):
                candidates.add(row.source)
        stages = []
        meshes = {m.id: m for m in self.scene.meshes}
        discarded = set(removed_rules)
        for stage in self.scene.deformers:
            excluded = skin.get(stage.id)
            if not excluded:
                stages.append(stage)
                continue
            mesh = meshes[stage.owner_id]
            bindings = {
                k: v
                for k, v in stage.parameters.get("bind_matrices", {}).items()
                if k not in excluded
            }
            extra = dict(mesh.extra)
            extra["unbound_bones"] = tuple(
                dict.fromkeys((*extra.get("unbound_bones", ()), *(k for k in excluded if k)))
            )
            extra["area_pins"] = [
                p for p in extra.get("area_pins", ()) if bindings and p["bone_id"] not in excluded
            ]
            if not bindings:
                extra.pop("rig_skeleton_id", None)
                extra["auto_bind_artwork"] = False
                discarded.add(stage.id)
            else:
                stages.append(
                    replace(stage, parameters={**stage.parameters, "bind_matrices": bindings})
                )
            meshes[mesh.id] = replace(
                mesh,
                extra=extra,
                vertices=tuple(
                    replace(
                        vertex,
                        weights=normalize_weights(
                            {k: w for k, w in vertex.weights.items() if k not in excluded}, 16
                        ),
                    )
                    for vertex in mesh.vertices
                ),
            )
        for key, removed in pins.items():
            mesh = meshes[key]
            meshes[key] = replace(
                mesh,
                extra={
                    **mesh.extra,
                    "area_pins": [
                        p for p in mesh.extra.get("area_pins", ()) if p["vertex_id"] not in removed
                    ],
                },
            )
        changes = {}
        records = self.records()
        characters = CharacterService(self.document)
        containers = {key: characters.object_root(key) for key in parents}
        for rule in self.scene.constraints:
            if rule.id not in removed_rules or rule.kind not in ("parent", "space_switch"):
                continue
            owner = records.get(rule.owner_id)
            if isinstance(owner, (SceneObject, Group)):
                world = pose.nodes[owner.id].world_matrix
                local = (
                    multiply(inverse(pose.nodes[owner.parent_id].world_matrix), world)
                    if owner.parent_id
                    else world
                )
                changes[owner.id] = replace(owner, transform=from_matrix(local, owner.transform))
            if rule.target_id and isinstance(records.get(rule.target_id), Bone):
                candidates.add(rule.target_id)
        with self.document.command_group("Remove bindings"):
            self.commit(
                "Release skin and constraints",
                meshes=tuple(meshes.values()),
                deformers=tuple(stages),
                constraints=tuple(c for c in self.scene.constraints if c.id not in removed_rules),
                timelines=tuple(
                    replace(t, tracks=tuple(v for v in t.tracks if v.owner_id not in discarded))
                    for t in self.scene.timelines
                ),
            )
            self.update_records(changes, "Keep detached artwork in place")
            for key in parents:
                if isinstance(records[key], Bone):
                    RigService(self.document).reparent(key, None)
                    candidates.add(key)
                else:
                    owner = containers[key]
                    self.move_entries((key,), owner.id if owner and owner.id != key else None)
            active = {
                row.target
                for row in self.relationships()
                if row.kind in ("Skin", "Area pin")
                or row.kind == "Parent"
                and row.id.startswith("constraint:")
            }
            explicit = {row.source for row in selected if row.kind in ("Spring", "Spring anchor")}
            if cleanup_physics:
                self.remove_physics((candidates - active) | explicit)

    def remove_physics(self, bones: set[str]) -> None:
        """Release physics, pin/IK constraints and activation keys for detached bones only.

        Authored and baked transform keys remain editable animation. Shared spring groups
        and their master controls survive while another member still uses them.
        """
        if not bones:
            return

        def refers(value: object) -> bool:
            """Find bone references in compound IK/space-switch constraint parameters."""
            from collections.abc import Mapping

            if isinstance(value, str):
                return value in bones
            if isinstance(value, Mapping):
                return any(refers(k) or refers(v) for k, v in value.items())
            return isinstance(value, (tuple, list)) and any(refers(v) for v in value)

        rules = tuple(
            c
            for c in self.scene.constraints
            if c.owner_id not in bones and c.target_id not in bones and not refers(c.parameters)
        )
        discarded = {c.id for c in self.scene.constraints if c not in rules}
        active = {c.owner_id for c in rules if c.kind == "spring"}
        active.update(
            b.id
            for r in self.scene.skeletons
            for b in r.bones
            if b.id not in bones and b.extra.get("spring_group")
        )
        unused_masters = set()
        for rig in self.scene.skeletons:
            members = {b.id for b in rig.bones}
            if members & bones and not members & active:
                unused_masters.update(members)
                if rig.extra.get("object_id"):
                    unused_masters.add(rig.extra["object_id"])
        self.commit(
            "Release detached bone physics",
            constraints=rules,
            skeletons=tuple(
                replace(
                    r,
                    bones=tuple(
                        replace(b, extra={k: v for k, v in b.extra.items() if k != "spring_group"})
                        if b.id in bones
                        else b
                        for b in r.bones
                    ),
                )
                for r in self.scene.skeletons
            ),
            timelines=tuple(
                replace(
                    t,
                    tracks=tuple(
                        v
                        for v in t.tracks
                        if not (
                            v.owner_id in discarded
                            or v.owner_id in bones
                            and v.property_path.startswith("spring.")
                            or v.owner_id in unused_masters
                            and v.property_path == "spring.master"
                        )
                    ),
                )
                for t in self.scene.timelines
            ),
        )
