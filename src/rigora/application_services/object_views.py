"""Portable object turnarounds with one active representation and independent saved edits."""

import base64
import json
import zlib
from collections.abc import Mapping
from dataclasses import replace
from typing import Any
from uuid import uuid4

from rigora.application_services.character_creation import CharacterBuild, build_character
from rigora.application_services.characters import CharacterService
from rigora.application_services.content_library import content_project
from rigora.application_services.documents import DocumentService
from rigora.application_services.meshes import MeshService
from rigora.domain.character_recipe import CharacterRecipe, canonical_view
from rigora.domain.content import ContentItem
from rigora.domain.entities import ENTITY_COLLECTIONS, Group, Timeline, Track, nested_records
from rigora.domain.object_views import VIEW_SLOTS, view_partitions
from rigora.domain.project import ProjectError, Scene
from rigora.domain.validation import json_copy

MAX_VIEW_BYTES = 32 * 1024 * 1024


def encode_view(scene: Scene, document: DocumentService) -> dict[str, str]:
    """Compress inactive keys so palette edits copy only a small snapshot descriptor."""
    used = {m.asset_id for m in scene.meshes}
    assert document.project is not None
    payload = {
        "scene": scene.to_dict(),
        "assets": {a.id: a.sha256 for a in document.project.assets if a.id in used},
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    if len(raw) > MAX_VIEW_BYTES:
        raise ProjectError("An Object View exceeds the 32 MiB snapshot limit.")
    return {"codec": "zlib+base64", "data": base64.b64encode(zlib.compress(raw)).decode("ascii")}


def decode_view(saved: Any, document: DocumentService) -> Scene:
    """Bound decompression and resolve opaque snapshot asset IDs by content digest."""
    if not isinstance(saved, Mapping):
        raise ProjectError("The saved Object View must be a snapshot descriptor.")
    assert document.project is not None
    if saved.get("codec") is None:
        return Scene.from_dict(json_copy(saved))
    data = saved.get("data")
    if (
        saved.get("codec") != "zlib+base64"
        or not isinstance(data, str)
        or len(data) > 8 * 1024 * 1024
    ):
        raise ProjectError("Unsupported or oversized Object View snapshot.")
    try:
        decoder = zlib.decompressobj()
        raw = decoder.decompress(base64.b64decode(data, validate=True), MAX_VIEW_BYTES + 1)
        if len(raw) > MAX_VIEW_BYTES or not decoder.eof or decoder.unused_data:
            raise ValueError("Invalid snapshot size or stream")
        payload = json.loads(raw)
        if not isinstance(payload, dict) or not isinstance(payload.get("assets"), dict):
            raise ValueError("Invalid snapshot asset manifest")
        by_digest = {a.sha256: a.id for a in document.project.assets}
        ids = {key: by_digest[digest] for key, digest in payload["assets"].items()}
        return Scene.from_dict(remap(payload["scene"], ids))
    except (ValueError, zlib.error, KeyError, TypeError) as error:
        raise ProjectError("The saved Object View is corrupt or missing source assets.") from error


def remap(value: Any, ids: dict[str, str]) -> Any:
    """Rewrite record identities, metadata references and property-path prefixes together."""
    if isinstance(value, dict):
        return {ids.get(k, k): remap(v, ids) for k, v in value.items()}
    if isinstance(value, list):
        return [remap(v, ids) for v in value]
    if isinstance(value, str):
        return ids.get(value, ".".join(ids.get(p, p) for p in value.split(".")))
    return value


class ObjectViewsService(MeshService):
    """Manage editable turnaround slots and older portable recipe snapshots.

    Slots retain canonical part/bone identities under one persistent Object. The
    evaluator selects their geometry from held view keys. Legacy snapshot sides
    are materialized on demand; explicit recipe preparation remains available to
    callers that need generated turnaround artwork.
    """

    def root(self, key: str) -> Group:
        """Require a recipe-backed compound Object rather than an arbitrary selection."""
        root = CharacterService(self.document).object_root(key)
        if root is None:
            raise ProjectError("Choose an Object to edit its views.")
        if not isinstance(root.extra.get("object_views", {}), Mapping):
            raise ProjectError("Object Views contains an invalid snapshot list.")
        return root

    def current(self, key: str) -> str:
        """Return the active human-readable turnaround view."""
        root = self.root(key)
        if root.extra.get("view_slots"):
            return str(root.extra.get("active_view", "Default"))
        return canonical_view(str(root.extra.get("character_recipe", {}).get("view", "Default")))

    def edited_view(self, key: str) -> str:
        """Use Default for artwork that has not yet been partitioned into editable slots."""
        root = self.root(key)
        return str(root.extra.get("active_view", "Default"))

    def switch(self, key: str, view: str) -> None:
        """Select a slot, retaining local records and leaving missing views empty."""
        if view not in VIEW_SLOTS:
            raise ProjectError("Choose Default or a turnaround view.")
        root = self.root(key)
        partitions = view_partitions(self.scene, root)
        changes: dict[str, Any] = {}
        extra = dict(root.extra)
        saved = root.extra.get("object_views", {}).get(view)
        if saved and not partitions[view]:
            source = decode_view(saved, self.document)
            source_root = next(g for g in source.groups if g.extra.get("object_container"))
            ids = {r.id: str(uuid4()) for r in nested_records(source)}
            ids[source_root.id] = root.id
            fragment = Scene.from_dict(remap(source.to_dict(), ids))
            imported = next(g for g in fragment.groups if g.id == root.id)
            partitions[view] = view_partitions(fragment, replace(root, extra={}))["Default"]
            for collection in ENTITY_COLLECTIONS:
                additions = tuple(r for r in getattr(fragment, collection) if r.id != root.id)
                if collection == "clips":
                    additions = tuple(
                        replace(
                            c, name=f"{view} · {c.name}", extra={**c.extra, "object_view": view}
                        )
                        for c in additions
                    )
                changes[collection] = (*getattr(self.scene, collection), *additions)
            extra["view_payloads"] = {
                **root.extra.get("view_payloads", {}),
                view: dict(imported.extra),
            }
            for family in ("skins", "outfits"):
                extra[family] = (
                    *root.extra.get(family, ()),
                    *(
                        {**group, "name": f"{view} · {group['name']}", "object_view": view}
                        for group in imported.extra.get(family, ())
                    ),
                )
            changes["draw_order"] = tuple(
                dict.fromkeys((*self.scene.draw_order, *fragment.draw_order))
            )
        groups = changes.get("groups", self.scene.groups)
        self.commit(
            "Change editable Object View",
            **{
                **changes,
                "groups": tuple(
                    replace(
                        g,
                        extra={
                            **extra,
                            "view_slots": True,
                            "active_view": view,
                            "view_members": {k: sorted(v) for k, v in partitions.items()},
                        },
                    )
                    if g.id == root.id
                    else g
                    for g in groups
                ),
            },
        )

    def edit_members(self, key: str) -> frozenset[str]:
        """Return only the active representation and the persistent editable Object container."""
        root = self.root(key)
        return frozenset({root.id, *view_partitions(self.scene, root)[self.edited_view(key)]})

    def key_view(self, key: str, view: str, frame: float) -> None:
        """Step-key a representation in Scene without changing its saved base view."""
        from rigora.application_services.animation_editing import AnimationEditingService

        if self.document.animation_context:
            raise ProjectError("Key Object Views in the main scene.")
        if view not in VIEW_SLOTS:
            raise ProjectError("Choose an Object View.")
        root = self.root(key)
        with self.document.command_group("Key Object View"):
            if not root.extra.get("view_slots"):
                self.switch(key, "Default")
            editor = AnimationEditingService(self.document)
            timeline = editor.timeline or Timeline(name="Scene actions")
            clip = editor.clip or editor.blank_clip(timeline)
            track = next(
                (
                    t
                    for t in timeline.tracks
                    if t.owner_id == root.id and t.property_path == "object.view"
                ),
                None,
            ) or Track(
                name="View",
                owner_id=root.id,
                property_path="object.view",
                extra={"view_owner": root.id, "active_from_first_key": True},
            )
            editor.editable(track)
            updated = editor.keyed_track(track, frame, VIEW_SLOTS.index(view), "step")
            editor.publish(
                "Key Object View",
                replace(
                    timeline,
                    tracks=tuple(updated if t.id == track.id else t for t in timeline.tracks)
                    if any(t.id == track.id for t in timeline.tracks)
                    else (*timeline.tracks, updated),
                ),
                replace(clip, out_frame=max(clip.out_frame, frame)),
            )

    def available(self, key: str) -> tuple[str, ...]:
        """Return authored views; scenery and transport sprites keep their single presentation."""
        from rigora.domain.vector_catalog import vector_views

        root = self.root(key)
        if root.extra.get("view_slots") or not root.extra.get("character_recipe"):
            return VIEW_SLOTS
        recipe = root.extra["character_recipe"]
        if recipe.get("artwork_collection") == "painted":
            return ("Side",) if recipe.get("kind") == "Vehicles" else ("Front",)
        return vector_views(str(recipe.get("kind", "Humans")))

    def snapshot(self, key: str) -> Scene:
        """Copy only the Object's owned records, excluding stage tracks and nested snapshots."""
        root = self.root(key)
        members = CharacterService(self.document).members(root.id)
        clips = tuple(c for c in self.scene.clips if c.extra.get("object_id") == root.id)
        timelines = {c.timeline_id for c in clips}
        changes: dict[str, Any] = {}
        for collection in ENTITY_COLLECTIONS:
            changes[collection] = tuple(
                row
                for row in getattr(self.scene, collection)
                if row.id in members
                or collection == "constraints"
                and row.owner_id in members
                or collection == "clips"
                and row in clips
                or collection == "timelines"
                and row.id in timelines
            )
        changes["groups"] = tuple(
            replace(
                g,
                extra={
                    k: v
                    for k, v in g.extra.items()
                    if k not in ("object_views", "object_view_assets")
                },
            )
            if g.id == root.id
            else g
            for g in changes["groups"]
        )
        changes["draw_order"] = tuple(k for k in self.scene.draw_order if k in members)
        return Scene(settings=self.scene.settings, **changes)

    def prepare(self, key: str, view: str) -> CharacterBuild:
        """Read a saved view or generate original vectors off-thread; never mutate the document."""
        view = canonical_view(view)
        if view not in self.available(key):
            raise ProjectError("Choose an available authored Object View.")
        root = self.root(key)
        fields = json_copy(root.extra["character_recipe"])
        saved = next(
            (v for k, v in root.extra.get("object_views", {}).items() if canonical_view(k) == view),
            None,
        )
        if saved is None:
            if fields.get("kind") in ("Animals", "Household", "Environment", "Vehicles"):
                from rigora.application_services.vector_creation import build_vector
                from rigora.domain.vector_catalog import VectorRecipe

                return build_vector(VectorRecipe(**{**fields, "view": view}))
            recipe = CharacterRecipe(
                **{
                    **fields,
                    "dress": tuple(fields["dress"]),
                    "motions": tuple(fields["motions"]),
                    "view": view,
                }
            )
            return build_character(recipe)
        assert self.document.project is not None
        scene = decode_view(saved, self.document)
        used = {m.asset_id for m in scene.meshes}
        assets = tuple(a for a in self.document.project.assets if a.id in used)
        project = replace(self.document.project, scenes=(scene,), assets=assets)
        files = {f"sources/{a.id}": self.document.read_asset(a.id) for a in assets}
        files["character.json"] = json.dumps(project.to_dict()).encode()
        item = ContentItem(
            name=root.name,
            kind="scene",
            category="Characters",
            author="Rigora contributors",
            license="CC0-1.0",
            payload={
                "project_source": "character.json",
                "sources": {a.id: f"sources/{a.id}" for a in assets},
                "object_template": True,
            },
        )
        return CharacterBuild(
            item, files, next(g.id for g in scene.groups if g.extra.get("object_container"))
        )

    def apply(self, key: str, built: CharacterBuild) -> None:
        """Commit one view replacement as one undo operation and retain inactive view snapshots."""
        root = self.root(key)
        prior = self.snapshot(root.id)
        source = content_project(built.item, built.files)
        incoming = source.scenes[0]
        incoming_root = next(g for g in incoming.groups if g.id == built.root_id)
        snapshots = {
            **root.extra.get("object_views", {}),
            self.current(root.id): encode_view(prior, self.document),
        }
        ids = {row.id: str(uuid4()) for row in nested_records(incoming)}
        # Parts have semantic names across views; retain identities used by scene
        # tracks and source-action blocks, without evaluating inactive skeletons.
        for collection in ENTITY_COLLECTIONS:
            previous = {row.name: row.id for row in getattr(prior, collection)}
            for row in getattr(incoming, collection):
                if row.name in previous and collection not in ("deformers", "constraints"):
                    ids[row.id] = previous[row.name]
        ids[incoming_root.id] = root.id
        previous_actions = {c.extra.get("recipe_motion", c.name): c for c in prior.clips}
        for clip in incoming.clips:
            if old_clip := previous_actions.get(clip.extra.get("recipe_motion", clip.name)):
                ids[clip.id] = old_clip.id
                ids[clip.timeline_id] = old_clip.timeline_id
        for family in ("skins", "outfits"):
            previous_groups = {g["name"]: g for g in root.extra.get(family, ())}
            for group in incoming_root.extra.get(family, ()):
                if old_group := previous_groups.get(group["name"]):
                    ids[group["id"]] = old_group["id"]
                    variants = {v["name"]: v["id"] for v in old_group["variants"]}
                    ids.update(
                        {
                            v["id"]: variants[v["name"]]
                            for v in group["variants"]
                            if v["name"] in variants
                        }
                    )
        old_bones = {b.name: b.id for r in prior.skeletons for b in r.bones}
        for rig in incoming.skeletons:
            for bone in rig.bones:
                if bone.name in old_bones:
                    ids[bone.id] = old_bones[bone.name]
        for mesh in incoming.meshes:
            old = next((m for m in prior.meshes if m.id == ids[mesh.id]), None)
            if old:
                for a, b in zip(mesh.vertices, old.vertices, strict=False):
                    ids[a.id] = b.id
        with self.document.command_group("Change Object View"):
            for asset in source.assets:
                assert self.document.project is not None
                registered = next(
                    (
                        a
                        for a in self.document.project.assets
                        if asset.sha256 and a.sha256 == asset.sha256
                    ),
                    None,
                )
                if registered is None:
                    registered = self.document.register_asset_bytes(
                        asset.name,
                        built.files[str(built.item.payload["sources"][asset.id])],
                        kind=asset.kind,
                        media_type=asset.media_type,
                        metadata=asset.extra,
                    )
                ids[asset.id] = registered.id
            # Retiming keeps existing stage blocks and object motion durations in
            # seconds when the destination uses a different frame rate.
            fragment = Scene.from_dict(remap(incoming.to_dict(), ids))
            factor = self.scene.settings.fps / incoming.settings.fps
            if factor != 1:
                fragment = replace(
                    fragment,
                    timelines=tuple(
                        replace(
                            t,
                            tracks=tuple(
                                replace(
                                    track,
                                    keyframes=tuple(
                                        replace(k, frame=k.frame * factor) for k in track.keyframes
                                    ),
                                )
                                for track in t.tracks
                            ),
                            markers=tuple(replace(m, frame=m.frame * factor) for m in t.markers),
                        )
                        for t in fragment.timelines
                    ),
                    clips=tuple(
                        replace(c, in_frame=c.in_frame * factor, out_frame=c.out_frame * factor)
                        for c in fragment.clips
                    ),
                )
            fragment = replace(
                fragment,
                groups=tuple(
                    replace(
                        g,
                        name=root.name,
                        transform=root.transform,
                        parent_id=root.parent_id,
                        extra={
                            **g.extra,
                            "object_views": snapshots,
                            "object_view_assets": sorted(
                                set(root.extra.get("object_view_assets", ()))
                                | {m.asset_id for m in prior.meshes}
                                | {m.asset_id for m in fragment.meshes}
                            ),
                        },
                    )
                    if g.id == root.id
                    else g
                    for g in fragment.groups
                ),
            )
            changes = {}
            for collection in ENTITY_COLLECTIONS:
                removed = {row.id for row in getattr(prior, collection)}
                changes[collection] = tuple(
                    row for row in getattr(self.scene, collection) if row.id not in removed
                ) + getattr(fragment, collection)
            owned = set(prior.draw_order)
            order = list(self.scene.draw_order)
            insertion = next((i for i, k in enumerate(order) if k in owned), len(order))
            order = [k for k in order if k not in owned]
            order[insertion:insertion] = fragment.draw_order
            changes["draw_order"] = tuple(order)
            self.commit("Change Object View", **changes)
