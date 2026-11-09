"""Offline content discovery, scratch previews and canonical undoable application."""

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.deformation import DeformationPreset, DeformationService
from rigora.application_services.documents import DocumentService
from rigora.application_services.meshes import MeshService
from rigora.application_services.rigging import RigService
from rigora.domain.content import ContentItem, ContentPack
from rigora.domain.draw_order import scene_draw_order
from rigora.domain.entities import Character, Group, Skeleton, Transform, nested_records
from rigora.domain.project import Project, ProjectError
from rigora.domain.validation import json_copy, portable_relative_path
from rigora.engine.sampling import number
from rigora.infrastructure.content_packs import read_pack, write_pack
from rigora.infrastructure.preferences import PreferencesStore
from rigora.infrastructure.project_storage import _decode
from rigora.resources import asset_path


def content_project(item: ContentItem, files: Mapping[str, bytes]) -> Project:
    """Read an inline or bounded archive scene without extracting or executing pack content.

    Large editable performances live in separate JSON members so catalog browsing
    only loads metadata. Legacy inline scene payloads continue to work unchanged.
    """
    if "project" in item.payload:
        return Project.from_dict(json_copy(item.payload["project"]))
    name = item.payload.get("project_source")
    if not isinstance(name, str) or name not in files:
        raise ProjectError("The content scene member is missing.")
    portable_relative_path(name)
    data = files[name]
    # Match the archive member bound so full creator action catalogs remain importable.
    if len(data) > 32 * 1024 * 1024:
        raise ProjectError("A content scene may contain at most 32 MiB of project JSON.")
    return _decoded_content_project(data)


@lru_cache(maxsize=4)
def _decoded_content_project(data: bytes) -> Project:
    """Reuse validated immutable source scenes, bounded independently of placed instances."""
    return Project.from_dict(_decode(data))


@dataclass(frozen=True)
class LibraryEntry:
    """One immutable browser entry retaining pack provenance and its local archive location."""

    path: Path
    pack: ContentPack
    item: ContentItem

    @property
    def key(self) -> str:
        """Return a namespaced browser identity independent of display names and paths."""
        return f"{self.pack.id}/{self.item.id}"


class ContentLibrary:
    """Own installed pack discovery and local browsing preferences without importing Qt."""

    def __init__(
        self,
        preferences: PreferencesStore,
        *,
        bundled: Path | None = None,
        allowed_roots: tuple[Path, ...] | None = None,
        cache_root: Path | None = None,
    ) -> None:
        """Locate read-only bundled content and a user-owned pack folder beside preferences."""
        self.preferences = preferences
        self.root = preferences.path.parent / "content-packs"
        from rigora.application_services.illustration_cache import cached_catalog

        self.cache_root = cache_root or preferences.path.parent / "cache" / "content"
        self.bundled = bundled or cached_catalog(self.cache_root) / "templates.rigpack"
        self.generation_progress: Any = None
        self.generation_cancelled: Any = None
        self.isolate_preparation = False
        self._discover_bundled = bundled is None
        self.warnings: list[str] = []
        self.additional_packs: tuple[Path, ...] = ()
        self.allowed_roots = allowed_roots

    @property
    def bundled_packs(self) -> tuple[Path, ...]:
        """Rediscover bundled collections on refresh, including packs added after startup."""
        return (
            (
                self.bundled,
                *sorted(
                    path for path in self.bundled.parent.glob("*.rigpack") if path != self.bundled
                ),
            )
            if self._discover_bundled
            else (self.bundled,)
        )

    def entries(self) -> tuple[LibraryEntry, ...]:
        """Discover a bounded collection, skipping broken user packs with visible diagnostics."""
        result: list[LibraryEntry] = []
        self.warnings.clear()
        if self._discover_bundled:
            from rigora.application_services.illustration_cache import ensure_catalog

            prepare = ensure_catalog
            if self.isolate_preparation:
                from rigora.application_services.catalog_preparation import prepare_catalog

                prepare = prepare_catalog
            self.bundled = (
                prepare(self.cache_root, self.generation_progress, self.generation_cancelled)
                / "templates.rigpack"
            )
        installed = sorted(self.root.glob("*.rigpack"))
        if len(installed) > 128:
            self.warnings.append(
                "Showing the first 128 installed packs; move unused packs elsewhere."
            )
        directories = self.preferences.data.get("template_pack_directories", [])
        local_templates: list[Path] = []
        for directory in directories[:16] if isinstance(directories, list) else ():
            if isinstance(directory, str):
                try:
                    local_templates.extend(sorted(Path(directory).glob("*.rigpack"))[:128])
                except OSError as error:
                    self.warnings.append(f"Local template folder: {error}")
        paths = (*self.bundled_packs, *local_templates, *self.additional_packs, *installed[:128])
        seen: set[str] = set()
        for path in paths:
            try:
                if self.allowed_roots is not None and not any(
                    path.resolve().is_relative_to(root) for root in self.allowed_roots
                ):
                    raise ProjectError("Content pack is outside authorized asset directories.")
                pack, _ = read_pack(path, metadata_only=True)
                if pack.items and all(
                    item.kind == "artwork"
                    and item.extra.get("recovery") == "paired color and alpha PNG streams"
                    for item in pack.items
                ):
                    # Reference-only texture recoveries are not reusable animation content.
                    continue
                if pack.id in seen:
                    continue
                seen.add(pack.id)
                result.extend(LibraryEntry(path, pack, item) for item in pack.items)
            except ProjectError as error:
                self.warnings.append(f"{path.name}: {error}")
        return tuple(result)

    def install(self, path: Path) -> str:
        """Validate and copy a portable pack to the local library without extracting files."""
        pack, files = read_pack(path)
        self.root.mkdir(parents=True, exist_ok=True)
        destination = self.root / f"{pack.id}.rigpack"
        if destination.exists():
            raise ProjectError("This pack is already installed; existing content was preserved.")
        if len(list(self.root.glob("*.rigpack"))) >= 128:
            raise ProjectError("The local library supports at most 128 installed packs.")
        write_pack(destination, pack, files)
        return pack.name

    def favorite(self, key: str) -> bool:
        """Read membership from bounded validated preference data."""
        values = self.preferences.data.get("content_favorites", [])
        return isinstance(values, list) and key in values

    def toggle_favorite(self, key: str) -> None:
        """Persist a reversible browsing preference independently of project history."""
        values = self.preferences.data.get("content_favorites", [])
        values = (
            [value for value in values if isinstance(value, str)]
            if isinstance(values, list)
            else []
        )
        self.preferences.data["content_favorites"] = (
            [v for v in values if v != key] if key in values else [*values, key]
        )[-512:]
        self.preferences.save()

    def used(self, key: str) -> None:
        """Record recent successful applications without marking a document dirty."""
        values = self.preferences.data.get("content_recent", [])
        values = (
            [v for v in values if isinstance(v, str) and v != key]
            if isinstance(values, list)
            else []
        )
        self.preferences.data["content_recent"] = [key, *values][:32]
        self.preferences.save()


class ContentService(MeshService):
    """Instantiate templates, semantic poses, actions, art and deformation without UI rules."""

    def skeleton(self, key: str) -> Skeleton:
        """Resolve an explicit target rig rather than guessing among multiple anatomies."""
        rig = next(
            (r for r in self.scene.skeletons if r.id == key or any(b.id == key for b in r.bones)),
            None,
        )
        if rig is None:
            raise ProjectError("Choose a target skeleton for this pose or action.")
        return rig

    def mapping(self, rig: Skeleton) -> dict[str, str]:
        """Resolve explicit semantic mappings, retaining names for user-authored custom rigs."""
        mapping = rig.extra.get("semantic_mapping")
        if not isinstance(mapping, Mapping) and len({b.name for b in rig.bones}) != len(rig.bones):
            raise ProjectError("Custom rig bone names must be unique for semantic mapping.")
        result = (
            dict(mapping) if isinstance(mapping, Mapping) else {b.name: b.id for b in rig.bones}
        )
        if not all(value in {b.id for b in rig.bones} for value in result.values()):
            raise ProjectError("The rig's semantic mapping references missing bones.")
        return result

    def compatibility(self, item: ContentItem, target: str = "", mesh_id: str = "") -> str:
        """Return an actionable compatibility reason before any command or preview is applied."""
        if item.engine_version != 1:
            return "This content needs a different animation engine version."
        try:
            if item.kind in ("pose", "action", "spring"):
                if not target and item.payload.get("fallback_rig"):
                    return ""
                rig = self.skeleton(target)
                if item.kind == "spring":
                    return ""
                required_anatomy = item.payload.get("anatomy")
                if (
                    required_anatomy
                    and rig.extra.get("anatomy") != required_anatomy
                    and not (
                        required_anatomy == "human"
                        and rig.extra.get("anatomy") in ("biped", "robot")
                    )
                ):
                    return f"Requires anatomy {required_anatomy!r}; choose a compatible template."
                mapping = self.mapping(rig)
                required = {
                    str(c["semantic"]) for c in item.payload["channels"] if not c.get("optional")
                }
                missing = sorted(required - mapping.keys())
                if missing:
                    return "Missing semantic bones: " + ", ".join(missing)
            elif item.kind == "deformation":
                if not mesh_id and item.payload.get("fallback_mesh"):
                    return ""
                self.mesh(mesh_id)
            return ""
        except (ProjectError, KeyError, TypeError) as error:
            return str(error)

    def apply(
        self, item: ContentItem, files: dict[str, bytes], *, target: str = "", mesh_id: str = ""
    ) -> str:
        """Apply one compatible asset as one undo command, rolling back all dependent operations."""
        reason = self.compatibility(item, target, mesh_id)
        if reason:
            raise ProjectError(reason)
        try:
            with self.document.command_group(f"Apply {item.name}"):
                created_rig = False
                if (
                    item.kind in ("action", "spring")
                    and not target
                    and item.payload.get("fallback_rig")
                ):
                    target = self.apply_rig(self.fallback_rig(str(item.payload["fallback_rig"])))
                    created_rig = True
                if item.kind == "deformation" and not mesh_id and item.payload.get("fallback_mesh"):
                    specimen_source = (
                        b'<svg xmlns="http://www.w3.org/2000/svg" width="180" height="180">'
                        b'<rect x="10" y="10" width="160" height="160" rx="32" fill="#cccccc" '
                        b'stroke="#303030" stroke-width="3"/>'
                        b'<circle cx="65" cy="70" r="7" fill="#303030"/>'
                        b'<circle cx="115" cy="70" r="7" fill="#303030"/>'
                        b'<path d="M 55 110 Q 90 145 125 110" fill="none" stroke="#303030" '
                        b'stroke-width="5" stroke-linecap="round"/></svg>'
                    )
                    mesh_id = self.import_image_bytes(
                        "Elastic specimen.svg", specimen_source, columns=8, rows=8
                    )
                    from rigora.application_services.characters import CharacterService

                    owner = self.mesh(mesh_id).object_id
                    if owner:
                        CharacterService(self.document).promote_object(owner)
                if item.kind == "rig":
                    return self.apply_rig(item)
                if item.kind == "spring":
                    from rigora.application_services.template_effects import apply_spring

                    return apply_spring(self.document, item, target, demonstration=created_rig)
                if item.kind in ("pose", "action"):
                    return self.apply_motion(item, target)
                if item.kind == "deformation":
                    if "motion" in item.payload or "shape" in item.payload:
                        from rigora.application_services.ffd_motion import FfdMotionService

                        return FfdMotionService(self.document).apply_item(item, mesh_id)
                    return DeformationService(self.document).add(
                        mesh_id,
                        DeformationPreset(
                            item.name, str(item.payload["kind"]), item.payload.get("parameters", {})
                        ),
                    )
                if item.kind == "artwork":
                    source = str(item.payload["source"])
                    placed_mesh = self.import_image_bytes(
                        Path(source).name,
                        files[source],
                        columns=item.payload.get("columns"),
                        rows=item.payload.get("rows"),
                    )
                    if item.payload.get("object_template"):
                        from rigora.application_services.characters import CharacterService

                        owner = self.mesh(placed_mesh).object_id
                        if owner:
                            characters = CharacterService(self.document)
                            root = characters.promote_object(owner)
                            characters.rename(root, item.name)
                    return placed_mesh
                return self.apply_scene(item, files)
        except (KeyError, TypeError, ValueError, IndexError) as error:
            raise ProjectError(f"Incompatible content payload: {error}") from error

    def apply_rig(self, item: ContentItem) -> str:
        """Allocate fresh bone identities and preserve explicit anatomy and semantic mappings."""
        source = Skeleton.from_dict(json_copy(item.payload["skeleton"]))
        ids = {b.id: str(uuid4()) for b in source.bones}
        if any(b.parent_id and b.parent_id not in ids for b in source.bones):
            raise ProjectError("The template references a missing parent bone.")
        mapping = {semantic: ids[key] for semantic, key in self.mapping(source).items()}
        owner = Group(
            name=item.name,
            transform=Transform(x=self.scene.settings.width / 2, y=self.scene.settings.height / 2),
            extra={"object_container": True},
        )
        if bounds := item.payload.get("rig_bounds"):
            cx, cy = (
                (number(bounds[0]) + number(bounds[2])) / 2,
                (number(bounds[1]) + number(bounds[3])) / 2,
            )
            owner = replace(
                owner,
                transform=replace(
                    owner.transform,
                    x=owner.transform.x - cx,
                    y=owner.transform.y - cy,
                    pivot_x=cx,
                    pivot_y=cy,
                ),
            )
        rig = replace(
            source,
            id=str(uuid4()),
            name=item.name,
            bones=tuple(
                replace(b, id=ids[b.id], parent_id=ids.get(b.parent_id or "")) for b in source.bones
            ),
            extra={**json_copy(source.extra), "semantic_mapping": mapping, "object_id": owner.id},
        )
        from rigora.domain.rig_roots import rooted_skeleton

        rig = rooted_skeleton(rig)
        self.commit(
            "Instantiate skeleton template",
            skeletons=(*self.scene.skeletons, rig),
            groups=(*self.scene.groups, owner),
            characters=(
                *self.scene.characters,
                Character(name=item.name, skeleton_id=rig.id, extra={"object_id": owner.id}),
            ),
        )
        return rig.id

    def fallback_rig(self, anatomy: str) -> ContentItem:
        """Resolve an original bone-only specimen without importing any character artwork."""
        from rigora.infrastructure.motion_catalog import skeletons

        family = "chain" if anatomy == "chain" else anatomy
        return next(i for i in skeletons() if i.payload["skeleton"].get("anatomy") == family)

    def apply_motion(self, item: ContentItem, target: str) -> str:
        """Map explicit semantics onto a compatible rig; motions use the canonical numeric keys."""
        from rigora.domain.entities import Keyframe, Timeline, Track

        rig = self.skeleton(target)
        mapping, channels = self.mapping(rig), item.payload["channels"]
        if item.kind == "pose":
            service = RigService(self.document)
            for channel in channels:
                bone = service.editable(mapping[str(channel["semantic"])])
                path = str(channel["path"])
                if path not in ("rotation", "x", "y", "scale_x", "scale_y"):
                    raise ProjectError("Static bone poses support transform components only.")
                service.update(
                    bone.id, transform=replace(bone.transform, **{path: channel["value"]})
                )
            return rig.id
        from rigora.domain.entities import AnimationClip

        fps = number(item.payload.get("fps", self.scene.settings.fps), "Motion FPS")
        if fps <= 0:
            raise ProjectError("Motion frame rate must be positive.")
        factor = self.scene.settings.fps / fps
        relative = item.payload.get("relative", False)
        bones = {b.id: b for b in rig.bones}
        reference = number(item.payload.get("reference_leg_length", 1))
        if reference <= 0:
            raise ProjectError("Motion reference lengths must be positive.")
        leg = sum(bones[mapping[key]].length for key in ("thigh.L", "shin.L") if key in mapping)
        translation_scale = leg / reference if leg else 1
        start = self.document.animation.pose.frame
        tracks = []
        for channel in channels:
            semantic = str(channel["semantic"])
            if semantic not in mapping and channel.get("optional"):
                continue
            owner = mapping[semantic]
            RigService(self.document).editable(owner)
            path = str(channel["path"])
            if path not in ("rotation", "x", "y", "scale_x", "scale_y"):
                raise ProjectError("Motion channels support transform components only.")
            base = getattr(bones[owner].transform, path) if relative else 0
            values = [
                (
                    number(time) * factor,
                    base
                    + number(value) * (translation_scale if relative and path in ("x", "y") else 1),
                )
                for time, value in channel["keys"]
            ]
            if len(values) < 2 or any(
                a[0] >= b[0] for a, b in zip(values, values[1:], strict=False)
            ):
                raise ProjectError(
                    "Motion channels need at least two strictly increasing keyframes."
                )
            if relative:
                from rigora.application_services.template_effects import smooth_keys

                keys = smooth_keys(values, loop=bool(item.payload.get("loop", True)))
            else:
                keys = tuple(Keyframe(frame=time, value=value) for time, value in values)
            tracks.append(
                Track(
                    name=f"{channel['semantic']} · {channel['path']}",
                    owner_id=owner,
                    property_path=f"transform.{path}",
                    keyframes=keys,
                )
            )
        timeline = Timeline(name=item.name, tracks=tuple(tracks))
        clip = AnimationClip(
            name=item.name,
            timeline_id=timeline.id,
            out_frame=max(
                0,
                number(item.payload["duration"], "Motion duration") * factor
                - (1 if relative and item.payload.get("loop", True) else 0),
            ),
            loop=item.payload.get("loop", True),
            annotation=item.description,
            extra={
                "object_id": str(rig.extra["object_id"]),
                "template_motion": item.id,
                "continuous_loop": bool(item.payload.get("loop", True)),
            }
            if relative and rig.extra.get("object_id")
            else {},
        )
        AnimationEditingService(self.document).publish("Apply reusable animation", timeline, clip)
        if relative and rig.extra.get("object_id") and not self.document.animation_context:
            from rigora.application_services.characters import CharacterService

            CharacterService(self.document).place_motion(
                str(rig.extra["object_id"]),
                clip.id,
                start,
                number(item.payload["duration"]) * factor / self.scene.settings.fps,
                repeat=clip.loop,
            )
        return clip.id

    def apply_scene(self, item: ContentItem, files: dict[str, bytes]) -> str:
        """Merge a scene fragment with fresh identities and re-embedded original sources."""
        source = content_project(item, files)
        if len(source.scenes) != 1:
            raise ProjectError("Reusable scene assets require exactly one scene.")
        selected = item.payload.get("selected_clip")
        if selected is not None and not any(c.id == selected for c in source.scenes[0].clips):
            raise ProjectError("Choose an existing performance from this content scene.")
        ids = {record.id: str(uuid4()) for record in nested_records(source)}
        for asset in source.assets:
            content = files[str(item.payload["sources"][asset.id])]
            registered = self.document.register_asset_bytes(
                asset.name,
                content,
                kind=asset.kind,
                media_type=asset.media_type,
                metadata={
                    k: v
                    for k, v in asset.extra.items()
                    if k not in ("sprite_sequence", "layered_layout")
                },
            )
            ids[asset.id] = registered.id

        def remap(value: Any) -> Any:
            """Remap identities, references, weight-map keys and semantic metadata."""
            if isinstance(value, dict):
                return {ids.get(k, k): remap(v) for k, v in value.items()}
            if isinstance(value, list):
                return [remap(v) for v in value]
            if isinstance(value, str):
                return ids.get(value, ".".join(ids.get(part, part) for part in value.split(".")))
            return value

        from rigora.application_services.commands import ProjectPatch
        from rigora.domain.entities import ENTITY_COLLECTIONS

        assert self.document.project is not None
        before = self.document.project.assets
        replacements = {ids[asset.id]: remap(json_copy(asset.extra)) for asset in source.assets}
        after = tuple(
            replace(asset, extra=replacements[asset.id]) if asset.id in replacements else asset
            for asset in before
        )
        self.document.execute(
            ProjectPatch("Remap imported source metadata", {"assets": before}, {"assets": after})
        )

        from rigora.application_services.object_library import remap_scene

        fragment = remap_scene(source.scenes[0], ids)
        # Pack imports start a new project-local definition, independent of their origin.
        from rigora.application_services.object_library import LINK

        fragment = replace(
            fragment,
            **cast(
                dict[str, Any],
                {
                    field: tuple(
                        replace(r, extra={k: v for k, v in r.extra.items() if k != LINK})
                        for r in getattr(fragment, field)
                    )
                    for field in ("groups", "objects", "characters")
                },
            ),
        )
        if item.payload.get("object_template"):
            # Recipe cycles include a seam key beyond the last displayed frame.
            # Older generated packs omitted this metadata; retain their seconds
            # when adapting to another scene frame rate.
            fragment = replace(
                fragment,
                clips=tuple(
                    replace(c, extra={**c.extra, "continuous_loop": True})
                    if c.loop
                    and c.extra.get("recipe_motion")
                    and not c.extra.get("continuous_loop")
                    else c
                    for c in fragment.clips
                ),
            )
            factor = self.scene.settings.fps / fragment.settings.fps
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
                                        replace(
                                            k,
                                            frame=k.frame * factor,
                                            tangent_in=(k.tangent_in[0] * factor, k.tangent_in[1])
                                            if k.tangent_in
                                            else None,
                                            tangent_out=(
                                                k.tangent_out[0] * factor,
                                                k.tangent_out[1],
                                            )
                                            if k.tangent_out
                                            else None,
                                        )
                                        for k in track.keyframes
                                    ),
                                )
                                for track in t.tracks
                            ),
                            markers=tuple(
                                replace(marker, frame=marker.frame * factor) for marker in t.markers
                            ),
                        )
                        for t in fragment.timelines
                    ),
                    clips=tuple(
                        replace(
                            c,
                            in_frame=c.in_frame * factor,
                            out_frame=(c.out_frame + 1) * factor - 1
                            if c.loop and c.extra.get("continuous_loop")
                            else c.out_frame * factor,
                        )
                        for c in fragment.clips
                    ),
                )
        changes = {
            key: (*getattr(self.scene, key), *getattr(fragment, key)) for key in ENTITY_COLLECTIONS
        }
        changes["draw_order"] = tuple(
            dict.fromkeys(
                (
                    *scene_draw_order(self.scene),
                    *self.scene.draw_order,
                    *scene_draw_order(fragment),
                    *fragment.draw_order,
                )
            )
        )
        self.commit("Merge reusable scene", **changes)
        if fragment.clips:
            requested = ids[str(selected)] if selected is not None else fragment.clips[0].id
            if any(c.id == requested for c in self.document.context_clips()):
                self.document.select_animation_clip(requested)
            elif (
                selected is not None
                and item.payload.get("object_template")
                and self.document.animation_context is None
            ):
                from rigora.application_services.characters import CharacterService

                owner = next((g for g in fragment.groups if g.extra.get("object_container")), None)
                clip = next(c for c in fragment.clips if c.id == requested)
                if owner:
                    from rigora.application_services.animation_editing import motion_source_end

                    CharacterService(self.document).place_motion(
                        owner.id,
                        clip.id,
                        self.document.animation.pose.frame,
                        (motion_source_end(clip) - clip.in_frame) / self.scene.settings.fps,
                        repeat=clip.loop,
                    )
        return fragment.id

    def preview(
        self,
        item: ContentItem,
        files: dict[str, bytes],
        *,
        target: str = "",
        mesh_id: str = "",
        specimen: bool = False,
        demonstrate: bool = False,
    ) -> DocumentService:
        """Evaluate an isolated prospective result without changing the real document or history."""
        scratch = self.document.fork()
        if specimen and not target and item.payload.get("fallback_rig"):
            scratch.new("Template preview")
        if specimen and item.kind in ("rig", "scene", "artwork"):
            scratch.new("Template preview")
        if specimen and self.compatibility(item, target, mesh_id):
            scratch.new("Template preview")
            service = ContentService(scratch)
            if item.kind in ("pose", "action"):
                from rigora.application_services.character_creation import build_character
                from rigora.application_services.illustration_cache import recipe_for
                from rigora.domain.illustration_catalog import design_by_id

                anatomy = str(item.payload.get("anatomy", ""))
                identity = (
                    "sumi" if "quadruped" in anatomy or anatomy in ("cat", "fox", "dog") else "nova"
                )
                built = build_character(recipe_for(design_by_id(identity)))
                before = {rig.id for rig in scratch.scene.skeletons}
                service.apply(built.item, built.files)
                target = next(rig.id for rig in scratch.scene.skeletons if rig.id not in before)
                reason = service.compatibility(item, target, mesh_id)
                if reason:
                    raise ProjectError(reason)
            elif item.kind == "deformation":
                mesh_id = service.import_image(asset_path("examples/prop.svg"), 8, 8)
        ContentService(scratch).apply(item, files, target=target, mesh_id=mesh_id)
        if item.kind == "spring" and (specimen or demonstrate) and target:
            from rigora.application_services.dynamics import DynamicsService

            rig = ContentService(scratch).skeleton(target)
            DynamicsService(scratch).motion_test(tuple(b.id for b in rig.bones if b.parent_id))
        return scratch

    def place(
        self,
        item: ContentItem,
        files: dict[str, bytes],
        *,
        target: str = "",
        mesh_id: str = "",
        position: tuple[float, float] | None = None,
        object_id: str = "",
    ) -> str:
        """Apply a template and position its new roots at a scene-space drop point in one undo.

        Targeted motions and deformers retain their target's transform. New scene fragments
        move as a unit, including animation translation keys, so the preview matches playback.
        A rig's object_id optionally adopts its container into an existing stage object.
        """

        context = self.document.animation_context
        if context and item.kind == "rig":
            object_id = context
        if object_id and not target and item.kind in ("action", "spring"):
            raise ProjectError(
                "Add a skeleton to this Object and bind its artwork before applying motion."
            )
        original = {record.id for record in nested_records(self.scene)}
        with self.document.command_group(f"Place {item.name}"):
            prior_rigs = {r.id for r in self.scene.skeletons}
            result = self.apply(item, files, target=target, mesh_id=mesh_id)
            created_rig = next((r for r in self.scene.skeletons if r.id not in prior_rigs), None)
            new_roots = any(g.id not in original for g in self.scene.groups)
            positioned = (
                replace(item, payload={**item.payload, "object_template": True})
                if new_roots and item.kind in ("action", "deformation", "spring")
                else item
            )
            if position is not None and (
                item.kind not in ("pose", "action", "deformation", "spring") or new_roots
            ):
                self.position_created(positioned, original, position)
            if created_rig and object_id:
                self._adopt_rig(created_rig.id, object_id)
            if context:
                self._adopt_created(original, context)
            return result

    def _adopt_created(self, original: set[str], context: str) -> None:
        """Keep newly dropped templates inside the active Object, including empty preview space."""
        from rigora.application_services.characters import CharacterService
        from rigora.domain.entities import SceneObject

        records = tuple(nested_records(self.scene))
        created = {r.id for r in records if r.id not in original}
        roots = tuple(
            r.id
            for r in records
            if r.id in created
            and isinstance(r, (Group, SceneObject))
            and r.parent_id not in created
            and r.parent_id != context
        )
        if roots:
            CharacterService(self.document).move_entries(roots, context)
        if self.document.animation_scope is not None:
            self.document.animation_scope = self.document.animation_scope | frozenset(created)

    def position_created(
        self, item: ContentItem, original: set[str], position: tuple[float, float]
    ) -> None:
        """Position already imported roots without rebuilding their artwork or animation keys."""
        from rigora.application_services.scene_editing import SceneEditingService
        from rigora.domain.entities import Bone, Group, SceneObject
        from rigora.domain.geometry import transform_point

        records = [
            r
            for r in nested_records(self.scene)
            if isinstance(r, (Bone, Group, SceneObject)) and r.id not in original
        ]
        created = {r.id for r in records}
        cameras = {camera.id for camera in self.scene.cameras}
        bone_owners = {
            b.id: rig.extra.get("object_id") for rig in self.scene.skeletons for b in rig.bones
        }
        roots = tuple(
            r.id
            for r in records
            if (r.parent_id or bone_owners.get(r.id)) not in created and r.id not in cameras
        )
        pose = self.document.animation.pose
        if item.payload.get("object_template"):
            objects = [
                r for r in records if isinstance(r, Group) and r.extra.get("object_container")
            ]
            if len(objects) == 1:
                root = objects[0]
                center = transform_point(
                    pose.nodes[root.id].world_matrix,
                    root.transform.pivot_x,
                    root.transform.pivot_y,
                )
                SceneEditingService(self.document).transform(
                    (root.id,),
                    dx=number(position[0]) - center[0],
                    dy=number(position[1]) - center[1],
                )
                return
        points = [
            transform_point(pose.nodes[key].world_matrix, 0, 0)
            for key in roots
            if key in pose.nodes
        ]
        if points:
            dx = number(position[0]) - min(p[0] for p in points)
            dy = number(position[1]) - min(p[1] for p in points)
            SceneEditingService(self.document).transform(roots, dx=dx, dy=dy)
            timelines = tuple(
                replace(
                    timeline,
                    tracks=tuple(
                        replace(
                            track,
                            keyframes=tuple(
                                replace(
                                    k,
                                    value=number(k.value)
                                    + (dx if track.property_path == "transform.x" else dy),
                                )
                                for k in track.keyframes
                            ),
                        )
                        if track.owner_id in roots
                        and track.property_path in ("transform.x", "transform.y")
                        and track.blend_mode == "override"
                        else track
                        for track in timeline.tracks
                    ),
                )
                for timeline in self.scene.timelines
            )
            if timelines != self.scene.timelines:
                self.commit("Position template animation", timelines=timelines)

    def _adopt_rig(self, skeleton_id: str, object_id: str) -> None:
        """Parent a placed rig container without moving the destination's artwork or bones."""
        from rigora.application_services.characters import CharacterService
        from rigora.domain.entities import SceneObject

        characters = CharacterService(self.document)
        destination = characters.record(object_id)
        if not isinstance(destination, (Group, SceneObject)) or characters.locked(object_id):
            raise ProjectError("Drop the skeleton onto an unlocked scene object.")
        owner = characters.object_root(skeleton_id)
        if owner is None:
            raise ProjectError("The skeleton template has no object container.")
        root = characters.object_root(object_id)
        target = root.id if root else characters.promote_object(object_id)
        characters.move_entries((owner.id,), target)

    def export_own(
        self,
        path: Path,
        name: str,
        author: str,
        license: str,
        *,
        rig_id: str = "",
        overwrite: bool = False,
    ) -> None:
        """Share a custom skeleton or complete current scene with original embedded source bytes."""
        files: dict[str, bytes] = {}
        payload: dict[str, Any]
        kind: Literal["rig", "scene"]
        if rig_id:
            rig = self.skeleton(rig_id)
            payload = {
                "skeleton": replace(
                    rig, extra={**json_copy(rig.extra), "semantic_mapping": self.mapping(rig)}
                ).to_dict()
            }
            kind, category = "rig", "Skeleton templates"
        else:
            assert self.document.project is not None
            project = replace(self.document.project, scenes=(self.scene,))
            sources = {}
            for asset in project.assets:
                key = f"sources/{asset.id}/{Path(asset.source).name}"
                files[key], sources[asset.id] = self.document.read_asset(asset.id), key
            files["scene.json"] = json.dumps(
                project.to_dict(), ensure_ascii=False, allow_nan=False
            ).encode("utf-8")
            payload = {"project_source": "scene.json", "sources": sources}
            kind, category = "scene", "Scenes & backgrounds"
        item = ContentItem(
            name=name, author=author, license=license, kind=kind, category=category, payload=payload
        )
        from rigora.application_services.content_thumbnails import render_content_thumbnail

        try:
            poster = render_content_thumbnail(item, files)
        except (ImportError, ProjectError):
            # A catalog poster must not prevent sharing a valid scene without render extras.
            from rigora.application_services.content_thumbnails import placeholder_thumbnail

            poster = placeholder_thumbnail()
        files["thumbnail.png"] = poster
        item = replace(item, thumbnail="thumbnail.png")
        pack = ContentPack(name=name, author=author, license=license, items=(item,))
        write_pack(path, pack, files, overwrite=overwrite)
