"""Project-local linked Objects and portable, identity-safe authoring clipboard data."""

import json
from collections.abc import Mapping
from dataclasses import fields, is_dataclass, replace
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from rigora.application_services.commands import ProjectPatch
from rigora.domain.content import ContentItem, ContentPack
from rigora.domain.entities import ENTITY_COLLECTIONS, Entity, Group, SceneObject, nested_records
from rigora.domain.geometry import multiply
from rigora.domain.project import Project, ProjectError, Scene, SceneSettings
from rigora.domain.validation import json_copy

LIBRARY = "object_library"
LINK = "linked_object"
INSTANCE_FIELDS = ("visible", "opacity", "locked", "pivot_edited", "depth")


def asset_references(value: Any) -> set[str]:
    """Collect identity references in serialized records and extension metadata."""
    if isinstance(value, str):
        return {value}
    if isinstance(value, Mapping):
        return set(value).union(*(asset_references(v) for v in value.values()))
    if isinstance(value, (tuple, list)):
        return set().union(*(asset_references(v) for v in value))
    return set()


def remap_ids(value: Any, identities: Mapping[str, str]) -> Any:
    """Rewrite identities in record fields, metadata maps and animated property paths."""
    if isinstance(value, Mapping):
        return {identities.get(k, k): remap_ids(v, identities) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [remap_ids(v, identities) for v in value]
    if isinstance(value, str):
        if value in identities:
            return identities[value]
        return ".".join(identities.get(p, p) for p in value.split(".")) if "." in value else value
    return value


def remap_scene(scene: Scene, identities: Mapping[str, str]) -> Scene:
    """Clone typed records with fresh IDs while sharing immutable non-reference values.

    Constructors still validate changed records. Dense animation keys avoid a
    serialization/JSON parse cycle, and untouched geometry/metadata stay shared.
    """

    def visit(value: Any) -> Any:
        """Rewrite references and owned identities without thawing unchanged values."""
        if is_dataclass(value) and not isinstance(value, (type, Mapping)):
            changes = {}
            for item in fields(value):
                old = getattr(value, item.name)
                new = visit(old)
                if new is not old:
                    changes[item.name] = new
            return replace(value, **changes) if changes else value
        if isinstance(value, Mapping):
            revised = {identities.get(key, key): visit(child) for key, child in value.items()}
            if len(revised) == len(value) and all(
                key in value and child is value[key] for key, child in revised.items()
            ):
                return value
            return revised
        if isinstance(value, tuple):
            revised_tuple = tuple(visit(child) for child in value)
            return (
                value
                if all(a is b for a, b in zip(value, revised_tuple, strict=True))
                else revised_tuple
            )
        if isinstance(value, str):
            return remap_ids(value, identities)
        return value

    return cast(Scene, visit(scene))


def object_roots(scene: Scene) -> tuple[Entity, ...]:
    """List reusable stage objects, excluding scene folders and owned internal parts."""
    records = {r.id: r for r in (*scene.groups, *scene.objects)}
    actors = {k for c in scene.characters for k in (*c.object_ids, *c.extra.get("part_groups", ()))}
    result = []
    for entry in (*records.values(), *scene.characters):
        if entry.extra.get("scene_folder") or entry.extra.get("studio_floor_plant"):
            continue
        if entry.id in actors:
            continue
        parent = getattr(entry, "parent_id", None)
        while parent in records and records[parent].extra.get("scene_folder"):
            parent = getattr(records[parent], "parent_id", None)
        if parent in records or entry.extra.get("object_id") in records:
            continue
        result.append(entry)
    return tuple(result)


def object_fragment(scene: Scene, roots: tuple[str, ...]) -> Scene:
    """Copy the selected ownership graph, including rigs, clothing, dynamics and actions.

    External parents, layer assignments and constraints are detached. Scene-level
    tracks on a root's transform, visibility and opacity stay with its placement.
    No animation runtime is created, including for inactive scenes.
    """
    records = {r.id: r for r in (*scene.groups, *scene.objects)}
    owned = set(roots)
    while True:
        expanded = set(owned)
        for entry in (*scene.groups, *scene.objects):
            if getattr(entry, "parent_id", None) in owned or entry.extra.get("object_id") in owned:
                expanded.add(entry.id)
        for actor in scene.characters:
            if (
                actor.id in owned
                or actor.extra.get("object_id") in owned
                or set(actor.object_ids).intersection(owned)
            ):
                expanded.update(
                    (
                        actor.id,
                        actor.skeleton_id,
                        *actor.object_ids,
                        *actor.extra.get("part_groups", ()),
                    )
                )
        for rig in scene.skeletons:
            if rig.id in owned or rig.extra.get("object_id") in owned:
                expanded.update((rig.id, *(b.id for b in rig.bones)))
        expanded.update(
            c.target_id
            for c in scene.constraints
            if c.owner_id in owned
            and c.target_id in records
            and records[c.target_id].extra.get("studio_floor_plant")
        )
        for field in ("meshes", "slots", "attachments", "deformers"):
            for entry in getattr(scene, field):
                if any(
                    getattr(entry, k, None) in owned
                    for k in ("object_id", "owner_id", "slot_id", "mesh_id")
                ):
                    expanded.add(entry.id)
        if expanded == owned:
            break
        owned = expanded
    for rule in scene.constraints:
        if (
            rule.kind != "scene_attachment"
            and rule.owner_id in owned
            and rule.target_id in (*owned, None)
        ):
            owned.add(rule.id)
    clips = tuple(
        c
        for c in scene.clips
        if c.extra.get("object_id") in owned or c.extra.get("character_id") in owned
    )
    timeline_ids = {c.timeline_id for c in clips}
    timelines = tuple(t for t in scene.timelines if t.id in timeline_ids)
    collections: dict[str, Any] = {
        k: tuple(e for e in getattr(scene, k) if e.id in owned) for k in ENTITY_COLLECTIONS
    }
    collections.update(clips=clips, timelines=timelines, layers=())
    for field in ("groups", "objects"):
        collections[field] = tuple(
            replace(e, parent_id=e.parent_id if e.parent_id in owned else None, layer_id=None)
            for e in collections[field]
        )
    return Scene(
        name="Object",
        settings=scene.settings,
        **collections,
        draw_order=tuple(k for k in scene.draw_order if k in owned),
    )


def _shared_fragment(scene: Scene, root: Entity) -> Scene:
    """Normalize instance-only fields for cheap immutable content comparisons."""
    from rigora.domain.entities import Transform

    fragment = object_fragment(scene, (root.id,))
    changes: dict[str, Any] = {}
    for field in ("groups", "objects", "characters"):
        values = []
        for entry in getattr(fragment, field):
            extra = {
                k: v
                for k, v in entry.extra.items()
                if k != LINK and (entry.id != root.id or k not in INSTANCE_FIELDS)
            }
            updates: dict[str, Any] = {"extra": extra}
            if entry.id == root.id:
                if isinstance(entry, (Group, SceneObject)):
                    updates["transform"] = Transform()
                if isinstance(entry, SceneObject):
                    updates["visible"] = True
            values.append(replace(entry, **updates))
        changes[field] = tuple(values)
    return replace(fragment, id=root.id, settings=SceneSettings(), **changes)


def _canonical(scene: Scene, root: Entity, identities: Mapping[str, str]) -> dict[str, Any]:
    """Encode shared content only when an actual content edit needs publication."""
    data = _shared_fragment(scene, root).to_dict()
    data.pop("id")
    return cast(dict[str, Any], remap_ids(data, identities))


def _snapshot_scene(data: Mapping[str, Any]) -> Scene:
    """Decode a library definition with an ephemeral scene identity."""
    return Scene.from_dict({**json_copy(data), "id": str(uuid4())})


def _merge_instance(scene: Scene, root: Entity, definition: Mapping[str, Any]) -> Scene:
    """Replace shared records while retaining instance IDs, scene tracks and root overrides."""
    link = root.extra[LINK]
    mapping = dict(link["ids"])
    fragment = _snapshot_scene(definition["scene"])
    for record in nested_records(fragment):
        mapping.setdefault(record.id, str(uuid4()))
    mapping[definition["root"]] = root.id
    incoming = Scene.from_dict(remap_ids(fragment.to_dict(), mapping))
    previous = object_fragment(scene, (root.id,))
    removed = {e.id for e in nested_records(previous)}
    updates: dict[str, Any] = {}
    for field in ENTITY_COLLECTIONS:
        additions = []
        for entry in getattr(incoming, field):
            if entry.id == root.id:
                extra = {**entry.extra, LINK: {"definition": link["definition"], "ids": mapping}}
                for key in INSTANCE_FIELDS:
                    if key in root.extra:
                        extra[key] = root.extra[key]
                values: dict[str, Any] = {"extra": extra}
                if isinstance(root, (Group, SceneObject)) and isinstance(
                    entry, (Group, SceneObject)
                ):
                    values.update(
                        transform=root.transform, parent_id=root.parent_id, layer_id=root.layer_id
                    )
                if isinstance(entry, SceneObject):
                    values["visible"] = getattr(root, "visible", root.extra.get("visible", True))
                entry = replace(entry, **values)
            additions.append(entry)
        retained = tuple(e for e in getattr(scene, field) if e.id not in removed)
        if field == "timelines":
            valid = {e.id for e in nested_records(incoming)}
            retained = tuple(
                replace(
                    t,
                    tracks=tuple(
                        track
                        for track in t.tracks
                        if track.owner_id not in removed or track.owner_id in valid
                    ),
                )
                for t in retained
            )
        updates[field] = (*retained, *additions)
    order = list(scene.draw_order)
    positions = [i for i, key in enumerate(order) if key in removed]
    insertion = min(positions, default=len(order))
    order = [k for k in order if k not in removed]
    order[insertion:insertion] = incoming.draw_order
    candidate = replace(scene, **updates, draw_order=tuple(order))
    from rigora.application_services.animation_editing import synchronized_motion_windows

    return replace(
        candidate,
        timelines=synchronized_motion_windows(
            candidate.timelines,
            incoming.clips,
            lambda key: {r.id for r in nested_records(object_fragment(candidate, (key,)))},
        ),
    )


def synchronize_objects(before: Project, after: Project) -> Project:
    """Publish new objects and propagate linked edits atomically without evaluating scenes.

    Called only at completed command boundaries. Definition snapshots survive the
    deletion of their final placement; Undo restores definitions and instances together.
    """
    library = dict(after.extra.get(LIBRARY, {}))
    scenes = list(after.scenes)
    previous = {s.id: s for s in before.scenes}
    changed_definitions = set()
    for index, scene in enumerate(scenes):
        if previous.get(scene.id) is scene:
            continue
        transforms: dict[str, Group | SceneObject] = {
            r.id: r for r in (*scene.groups, *scene.objects) if isinstance(r, (Group, SceneObject))
        }
        rig_changes = {}
        for rig in scene.skeletons:
            owner = rig.extra.get("object_id")
            if owner not in transforms or "library_bind" in rig.extra:
                continue
            if any(
                d.kind == "skinning" and d.parameters.get("object_group") == owner
                for d in scene.deformers
            ):
                continue
            basis = transforms[owner].transform.matrix()
            parent = transforms[owner].parent_id
            while parent in transforms:
                basis = multiply(transforms[parent].transform.matrix(), basis)
                parent = transforms[parent].parent_id
            rig_changes[rig.id] = replace(rig, extra={**rig.extra, "library_bind": basis})
        if rig_changes:
            scene = replace(
                scene, skeletons=tuple(rig_changes.get(r.id, r) for r in scene.skeletons)
            )
        for root in object_roots(scene):
            link = root.extra.get(LINK)
            if not link and root.extra.get("object_library_excluded"):
                continue
            if not link:
                key = str(uuid4())
                fragment = object_fragment(scene, (root.id,))
                link = {"definition": key, "ids": {e.id: e.id for e in nested_records(fragment)}}
                root = replace(root, extra={**root.extra, LINK: link})
                field = (
                    "groups"
                    if isinstance(root, Group)
                    else "objects"
                    if isinstance(root, SceneObject)
                    else "characters"
                )
                scene = replace(
                    scene,
                    **cast(
                        dict[str, Any],
                        {
                            field: tuple(
                                root if r.id == root.id else r for r in getattr(scene, field)
                            )
                        },
                    ),
                )
            key = link["definition"]
            old_root = (
                next((r for r in object_roots(previous[scene.id]) if r.id == root.id), None)
                if scene.id in previous
                else None
            )
            if (
                key in library
                and old_root is not None
                and _shared_fragment(previous[scene.id], old_root) == _shared_fragment(scene, root)
            ):
                continue
            ids = dict(link["ids"])
            local_ids = set(ids.values())
            for record in nested_records(object_fragment(scene, (root.id,))):
                if record.id not in local_ids:
                    ids[record.id] = record.id
            if ids != link["ids"]:
                link = {**link, "ids": ids}
                root = replace(root, extra={**root.extra, LINK: link})
                field = (
                    "groups"
                    if isinstance(root, Group)
                    else "objects"
                    if isinstance(root, SceneObject)
                    else "characters"
                )
                scene = replace(
                    scene,
                    **cast(
                        dict[str, Any],
                        {
                            field: tuple(
                                root if r.id == root.id else r for r in getattr(scene, field)
                            )
                        },
                    ),
                )
            inverse = {v: k for k, v in link["ids"].items()}
            canonical = _canonical(scene, root, inverse)
            definition = {
                "root": inverse.get(root.id, root.id),
                "name": root.name,
                "scene": canonical,
            }
            if library.get(key) != definition:
                library[key] = definition
                changed_definitions.add(key)
        scenes[index] = scene
    if changed_definitions:
        for index, scene in enumerate(scenes):
            for root in object_roots(scene):
                link = root.extra.get(LINK, {})
                key = link.get("definition")
                if key in changed_definitions:
                    inverse = {v: k for k, v in link["ids"].items()}
                    if _canonical(scene, root, inverse) != library[key]["scene"]:
                        scene = _merge_instance(scene, root, library[key])
            scenes[index] = scene
    if not library and LIBRARY not in after.extra:
        return after
    if library == after.extra.get(LIBRARY, {}) and tuple(scenes) == after.scenes:
        return after
    return replace(after, scenes=tuple(scenes), extra={**after.extra, LIBRARY: library})


class ObjectLibraryService:
    """Expose saved objects and scene/selection duplication through document commands."""

    def __init__(self, document: Any) -> None:
        """Use the caller-owned document and its ordinary reversible command boundary."""
        self.document = document

    def entries(self) -> Mapping[str, Any]:
        """Read project-local definitions; no sources or runtimes are eagerly loaded."""
        return (
            cast(Mapping[str, Any], self.document.project.extra.get(LIBRARY, {}))
            if self.document.project
            else {}
        )

    def edit_snapshot(self, key: str) -> tuple[Any, str]:
        """Open saved contents in an isolated authoring document without placing a scene copy.

        Asset bytes remain shared and immutable until edited. The presentation owns
        the working tab; publish_snapshot applies its edits to this project.
        """
        from rigora.application_services.commands import CommandHistory

        entry = self.entries().get(key)
        if entry is None:
            raise ProjectError("Choose a saved Object.")
        snapshot = self.document.fork()
        snapshot.set_animation_context(None, prepare=False)
        project = snapshot.project
        snapshot.execute(
            ProjectPatch(
                "Open saved Object",
                {"name": project.name, "scenes": project.scenes, "extra": project.extra},
                {
                    "name": ("Object · " + entry["name"])[:200],
                    "scenes": (Scene(name=entry["name"]),),
                    "extra": {LIBRARY: {key: entry}},
                },
            )
        )
        root = ObjectLibraryService(snapshot).place(key, (0, 0))
        snapshot._link_objects = True
        snapshot.history = CommandHistory()
        snapshot._saved = snapshot.project
        return snapshot, root

    def publish_snapshot(self, key: str, snapshot: Any, expected: Mapping[str, Any]) -> Any:
        """Apply a working Object revision and its assets atomically to every linked copy.

        Reject concurrent source edits or removal instead of overwriting them. Root
        placement overrides survive, and opening/editing an unplaced asset adds no
        scene instance. The owning project's history retains each completed edit.
        """
        if self.entries().get(key) != expected:
            raise ProjectError("The saved Object changed elsewhere. Reopen it before editing.")
        definition = ObjectLibraryService(snapshot).entries().get(key)
        if definition is None:
            raise ProjectError("Keep the edited Object root in its working document.")
        if definition == expected:
            return expected

        project = self.document.project
        assets = {a.id: a for a in project.assets}
        contents = {}
        used = asset_references(definition)
        for asset in snapshot.project.assets:
            if asset.id in used and assets.get(asset.id) != asset:
                if asset.storage == "embedded":
                    contents[asset.source] = snapshot.read_asset(asset.id)
                assets[asset.id] = asset
        scenes = []
        for scene in project.scenes:
            for root in object_roots(scene):
                if root.extra.get(LINK, {}).get("definition") == key:
                    scene = _merge_instance(scene, root, definition)
            scenes.append(scene)
        library = {**self.entries(), key: definition}
        with self.document.command_group("Edit saved Object"):
            self.document.execute(
                ProjectPatch(
                    "Publish saved Object contents",
                    {"scenes": project.scenes, "assets": project.assets, "extra": project.extra},
                    {
                        "scenes": tuple(scenes),
                        "assets": tuple(assets.values()),
                        "extra": {**project.extra, LIBRARY: library},
                    },
                )
            )
            self.document._asset_data.update(contents)
        return self.entries()[key]

    def scene_instances(self, keys: tuple[str, ...]) -> tuple[str, ...]:
        """Resolve selected definitions' complete placements in the active scene only."""
        return tuple(
            root.id
            for root in object_roots(self.document.scene)
            if root.extra.get(LINK, {}).get("definition") in keys
        )

    def remove_scene_instances(self, keys: tuple[str, ...]) -> None:
        """Delete current-scene placements through shared locking, ownership and Undo rules."""
        from rigora.application_services.scene_editing import SceneEditingService

        instances = self.scene_instances(keys)
        if instances:
            SceneEditingService(self.document).delete_entries(instances)

    def export_package(
        self,
        keys: tuple[str, ...],
        path: Path,
        *,
        category: str = "Objects",
        author: str = "Rigora user",
        license: str = "All rights reserved",
        name: str = "",
        thumbnails: Mapping[str, bytes] | None = None,
        overwrite: bool = False,
    ) -> None:
        """Write portable Objects with complete rigs, looks, actions and source bytes."""
        from rigora.application_services.content_thumbnails import placeholder_thumbnail
        from rigora.infrastructure.content_packs import write_pack

        if not keys or any(key not in self.entries() for key in keys):
            raise ProjectError("Select saved Objects to export.")
        files, items = {}, []
        project = self.document.project
        for index, key in enumerate(keys):
            entry = self.entries()[key]
            used = asset_references(entry)
            assets = tuple(a for a in project.assets if a.id in used)
            sources = {}
            for asset in assets:
                source = f"sources/{asset.id}/{Path(asset.source).name}"
                files[source], sources[asset.id] = self.document.read_asset(asset.id), source
            specimen = Project(
                name=entry["name"], assets=assets, scenes=(_snapshot_scene(entry["scene"]),)
            )
            member, poster = f"objects/{index}.json", f"posters/{index}.png"
            files[member] = json.dumps(specimen.to_dict(), ensure_ascii=False).encode("utf-8")
            files[poster] = (thumbnails or {}).get(key) or placeholder_thumbnail()
            items.append(
                ContentItem(
                    name=name.strip() if name.strip() and len(keys) == 1 else entry["name"],
                    author=author,
                    license=license,
                    category=category,
                    kind="scene",
                    tags=("object",),
                    thumbnail=poster,
                    payload={"project_source": member, "sources": sources},
                )
            )
        pack = ContentPack(
            name=name.strip() or (items[0].name if len(items) == 1 else f"{len(items)} Objects"),
            author=author,
            license=license,
            items=tuple(items),
        )
        write_pack(path, pack, files, overwrite=overwrite)

    def import_content(self, item: ContentItem, files: Mapping[str, bytes]) -> tuple[str, ...]:
        """Import standalone content into saved Objects without changing any scene placements."""
        from rigora.application_services.content_library import ContentService

        if item.kind not in ("scene", "rig", "artwork"):
            raise ProjectError(
                "This template requires an existing target; add a standalone Object first."
            )
        snapshot = self.document.fork()
        snapshot.set_animation_context(None, prepare=False)
        snapshot.execute(
            ProjectPatch(
                "Prepare Object import", {"scenes": snapshot.project.scenes}, {"scenes": (Scene(),)}
            )
        )
        ContentService(snapshot).apply(item, dict(files))
        roots = tuple(r.id for r in object_roots(snapshot.scene))
        if not roots:
            raise ProjectError("The package contains no reusable Objects.")
        source = ObjectLibraryService(snapshot)
        definitions = source.objects_to_definitions(source.copy_objects(roots))["definitions"]
        project = self.document.project
        library, keys = dict(self.entries()), []
        for definition in definitions:
            key = str(uuid4())
            library[key] = definition
            keys.append(key)
        with self.document.command_group("Import saved Objects"):
            self.document.execute(
                ProjectPatch(
                    "Import Object definitions and sources",
                    {"assets": project.assets, "extra": project.extra},
                    {
                        "assets": snapshot.project.assets,
                        "extra": {**project.extra, LIBRARY: library},
                    },
                )
            )
            self.document._asset_data.update(snapshot._asset_data)
        return tuple(keys)

    def import_package(self, path: Path) -> tuple[str, ...]:
        """Read a bounded data-only package and import all its items as one undoable edit."""
        from rigora.infrastructure.content_packs import read_pack

        pack, files = read_pack(path)
        with self.document.command_group("Import Object package"):
            return tuple(key for item in pack.items for key in self.import_content(item, files))

    def save(self, keys: tuple[str, ...]) -> tuple[str, ...]:
        """Publish selected stage objects, migrating objects from older projects on demand."""
        from rigora.application_services.characters import CharacterService

        service = CharacterService(self.document)
        if not keys:
            raise ProjectError("Select an Object to save.")
        keys = tuple(
            dict.fromkeys(root.id if (root := service.object_root(k)) else k for k in keys)
        )
        with self.document.command_group("Save as Object"):
            changes = {}
            for key in keys:
                entry = service.record(key)
                if not isinstance(entry, (Group, SceneObject)) and not any(
                    c.id == key for c in self.document.scene.characters
                ):
                    raise ProjectError("Save the Object that owns this part or bone.")
                if isinstance(entry, Group) and entry.extra.get("scene_folder"):
                    raise ProjectError("Save an Object inside the scene folder.")
                changes[key] = replace(
                    entry,
                    extra={k: v for k, v in entry.extra.items() if k != "object_library_excluded"},
                )
            service.update_records(changes, "Publish saved Objects")
            project = self.document.project
            linked = synchronize_objects(
                replace(project, scenes=tuple(replace(s) for s in project.scenes)),
                project,
            )
            self.document.execute(
                ProjectPatch(
                    "Save as Object",
                    {"scenes": project.scenes, "extra": project.extra},
                    {"scenes": linked.scenes, "extra": linked.extra},
                )
            )
        return tuple(service.record(key).extra[LINK]["definition"] for key in keys)

    def remove(self, keys: tuple[str, ...]) -> None:
        """Remove definitions while retaining and detaching every existing placement."""
        project = self.document.project
        library = json_copy(self.entries())
        for key in keys:
            if key not in library:
                raise ProjectError("Choose a saved Object.")
            library.pop(key)
        scenes = []
        for scene in project.scenes:
            changes: dict[str, Any] = {}
            for field in ("groups", "objects", "characters"):
                changes[field] = tuple(
                    replace(
                        e,
                        extra={
                            **{k: v for k, v in e.extra.items() if k != LINK},
                            "object_library_excluded": True,
                        },
                    )
                    if e.extra.get(LINK, {}).get("definition") in keys
                    else e
                    for e in getattr(scene, field)
                )
            scenes.append(replace(scene, **changes))
        self.document.execute(
            ProjectPatch(
                "Remove saved Objects",
                {"scenes": project.scenes, "extra": project.extra},
                {"scenes": tuple(scenes), "extra": {**project.extra, LIBRARY: library}},
            )
        )

    def copy_definitions(self, keys: tuple[str, ...]) -> dict[str, Any]:
        """Copy library definitions without placing or evaluating any scene object."""
        if not keys or any(k not in self.entries() for k in keys):
            raise ProjectError("Select saved Objects to copy.")
        return {
            "kind": "definitions",
            "project": self.document.project.id,
            "definitions": [json_copy(self.entries()[k]) for k in keys],
        }

    def objects_to_definitions(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Convert copied objects into library entries without adding temporary scene placements."""
        if payload.get("project") != self.document.project.id:
            raise ProjectError("Paste these objects in their original project.")
        scene = Scene.from_dict(json_copy(payload["scene"]))
        records = {r.id: r for r in nested_records(scene)}
        definitions = []
        for key in payload["roots"]:
            root = records[key]
            definitions.append(
                {"root": root.id, "name": root.name, "scene": _canonical(scene, root, {})}
            )
        return {"kind": "definitions", "project": payload["project"], "definitions": definitions}

    def place(
        self, key: str, position: tuple[float, float] | None = None, parent: str | None = None
    ) -> str:
        """Place a linked copy with fresh entity IDs and a centered, independent transform."""
        from rigora.application_services.scene_editing import SceneEditingService

        definition = self.entries().get(key)
        if definition is None:
            raise ProjectError("Choose a saved Object in this project.")
        source = _snapshot_scene(definition["scene"])
        ids = {e.id: str(uuid4()) for e in nested_records(source)}
        fragment = Scene.from_dict(remap_ids(source.to_dict(), ids))
        root = ids[definition["root"]]
        field = next(
            k
            for k in ("groups", "objects", "characters")
            if any(e.id == root for e in getattr(fragment, k))
        )
        fragment = replace(
            fragment,
            **cast(
                dict[str, Any],
                {
                    field: tuple(
                        replace(
                            e,
                            name=definition["name"],
                            extra={**e.extra, LINK: {"definition": key, "ids": ids}},
                        )
                        if e.id == root
                        else e
                        for e in getattr(fragment, field)
                    )
                },
            ),
        )
        with self.document.command_group("Place linked Object"):
            self._append(fragment)
            service = SceneEditingService(self.document)
            service.center_entries((root,), position)
            if parent is not None:
                service.move_entries((root,), parent)
        return root

    def _append(self, fragment: Scene) -> None:
        """Merge a validated fragment into the active scene in one command."""
        from rigora.application_services.commands import ScenePatch
        from rigora.domain.draw_order import scene_draw_order

        scene = self.document.scene
        changes = {k: (*getattr(scene, k), *getattr(fragment, k)) for k in ENTITY_COLLECTIONS}
        changes["draw_order"] = tuple(
            dict.fromkeys(
                (
                    *scene_draw_order(scene),
                    *scene.draw_order,
                    *scene_draw_order(fragment),
                    *fragment.draw_order,
                )
            )
        )
        self.document.execute(
            ScenePatch("Paste objects", scene.id, {k: getattr(scene, k) for k in changes}, changes)
        )

    def copy_scene(self, key: str) -> dict[str, Any]:
        """Serialize an entire scene, retaining linked definition identities for paste."""
        scene = next((s for s in self.document.project.scenes if s.id == key), None)
        if scene is None:
            raise ProjectError("Choose an existing scene.")
        return {"kind": "scene", "project": self.document.project.id, "scene": scene.to_dict()}

    def copy_objects(self, keys: tuple[str, ...]) -> dict[str, Any]:
        """Snapshot selected object contents for a later paste without retaining UI state."""
        if not keys:
            raise ProjectError("Select objects to copy.")
        fragment = object_fragment(self.document.scene, keys)
        return {
            "kind": "objects",
            "project": self.document.project.id,
            "scene": fragment.to_dict(),
            "roots": list(keys),
        }

    def paste(self, payload: Mapping[str, Any], parent: str | None = None) -> tuple[str, ...]:
        """Paste scene or object data with fresh IDs; reject cross-project dangling sources."""
        if payload.get("project") != self.document.project.id:
            raise ProjectError("Paste these objects into a scene in their original project.")
        if payload.get("kind") == "definitions":
            project = self.document.project
            library = json_copy(self.entries())
            keys = []
            for definition in payload["definitions"]:
                fragment = _snapshot_scene(definition["scene"])
                replace(project, scenes=(fragment,), extra={})
                if definition["root"] not in {r.id for r in object_roots(fragment)}:
                    raise ProjectError("A saved Object needs a valid root.")
                key = str(uuid4())
                keys.append(key)
                library[key] = {**json_copy(definition), "name": definition["name"] + " copy"}
            self.document.execute(
                ProjectPatch(
                    "Paste saved Objects",
                    {"extra": project.extra},
                    {"extra": {**project.extra, LIBRARY: library}},
                )
            )
            return tuple(keys)
        source = Scene.from_dict(json_copy(payload.get("scene")))
        ids = {r.id: str(uuid4()) for r in nested_records(source)}
        ids[source.id] = str(uuid4())
        fragment = Scene.from_dict(remap_ids(source.to_dict(), ids))
        # Link maps translate canonical IDs to new local IDs, never their keys.
        for field in ("groups", "objects", "characters"):
            original = {e.id: e for e in getattr(source, field)}
            values = []
            for e in getattr(fragment, field):
                old = next((v for k, v in original.items() if ids[k] == e.id), None)
                if old and LINK in old.extra:
                    link = old.extra[LINK]
                    e = replace(
                        e,
                        extra={
                            **e.extra,
                            LINK: {
                                "definition": link["definition"],
                                "ids": {k: ids.get(v, v) for k, v in link["ids"].items()},
                            },
                        },
                    )
                values.append(e)
            fragment = replace(fragment, **cast(dict[str, Any], {field: tuple(values)}))
        with self.document.command_group(
            "Paste scene" if payload.get("kind") == "scene" else "Paste objects"
        ):
            if payload.get("kind") == "scene":
                fragment = replace(fragment, name=source.name + " copy")
                project = self.document.project
                self.document.execute(
                    ProjectPatch(
                        "Paste scene",
                        {"scenes": project.scenes},
                        {"scenes": (*project.scenes, fragment)},
                    )
                )
                return (fragment.id,)
            if payload.get("kind") != "objects":
                raise ProjectError("The clipboard does not contain Rigora objects or a scene.")
            self._append(fragment)
            roots = tuple(ids[k] for k in payload["roots"])
            if parent:
                from rigora.application_services.scene_editing import SceneEditingService

                SceneEditingService(self.document).move_entries(roots, parent)
            return roots
