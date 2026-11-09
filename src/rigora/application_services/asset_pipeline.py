"""Non-destructive image, sequence, sprite, layered-art and audio import services."""

import json
import math
from dataclasses import replace
from pathlib import Path
from typing import Any

from rigora.application_services.commands import ProjectPatch
from rigora.application_services.meshes import MeshService
from rigora.domain.entities import Group, SceneObject, Transform
from rigora.domain.project import Project, ProjectError
from rigora.engine.sampling import number
from rigora.infrastructure.artwork import inspect_artwork
from rigora.infrastructure.media_import import (
    audio_metadata,
    pillow_image,
    png_bytes,
    read_illustrator,
    read_openraster,
    read_psd,
)


class AssetPipeline(MeshService):
    """Preserve original bytes and publish all derived records as one undoable import."""

    def batch(
        self,
        paths: tuple[Path, ...],
        *,
        place: bool = False,
        allow_unsupported: bool = False,
        parent: str | None = None,
        before: str | None = None,
        position: tuple[float, float] | None = None,
        center: bool = False,
    ) -> dict[str, Any]:
        """Add up to 128 mixed sources, rolling back failed files and reporting each result.

        Successful files form a single undo step. A failure cannot leave half of a layered
        document in the scene, and unrelated successes are still retained.
        """
        if not 1 <= len(paths) <= 128 or len(set(paths)) != len(paths):
            raise ProjectError("Choose 1–128 distinct source files.")
        if position is not None and (
            len(position) != 2 or not all(math.isfinite(v) for v in position)
        ):
            raise ProjectError("Drop position must contain two finite coordinates.")
        results: list[dict[str, Any]] = []
        with self.document.command_group("Add project assets"):
            for path in paths:
                try:
                    with self.document.command_group("Add source file"):
                        previous = {r.id for r in (*self.scene.groups, *self.scene.objects)}
                        if path.suffix.lower() in (".psd", ".psb", ".ora", ".ai"):
                            data = self.layered(
                                path, place=place, allow_unsupported=allow_unsupported
                            )
                        elif path.suffix.lower() == ".wav":
                            data = self.audio(path)
                        else:
                            data = self.image(path, place=place)
                        if place:
                            from rigora.application_services.scene_editing import (
                                SceneEditingService,
                            )

                            added = [
                                r
                                for r in (*self.scene.groups, *self.scene.objects)
                                if r.id not in previous
                            ]
                            ids = {r.id for r in added}
                            roots = tuple(
                                r.id for r in added if getattr(r, "parent_id", None) not in ids
                            )
                            if roots:
                                service = SceneEditingService(self.document)
                                if center:
                                    service.center_entries(roots)
                                elif position is not None:
                                    x, y = self.document.animation.pose.nodes[
                                        roots[0]
                                    ].world_matrix[4:]
                                    service.transform(
                                        roots,
                                        dx=position[0] - x + len(results) * 20,
                                        dy=position[1] - y + len(results) * 20,
                                    )
                                if parent is not None or before is not None:
                                    service.move_entries(roots, parent, before)
                    results.append({"name": path.name, "status": "added", "result": data})
                except (OSError, ProjectError, ValueError) as error:
                    results.append({"name": path.name, "status": "failed", "error": str(error)})
        added = sum(row["status"] == "added" for row in results)
        return {"files": results, "imported": added, "failed": len(results) - added}

    def place_source(
        self,
        asset_id: str,
        *,
        parent: str | None = None,
        before: str | None = None,
        position: tuple[float, float] | None = None,
    ) -> dict[str, Any]:
        """Place a source centered at a scene point, or camera center when omitted.

        Layered resources retain their layout with a centered container pivot.
        Positioning, parenting and instantiation share one reversible transaction.
        """
        from rigora.application_services.scene_editing import SceneEditingService

        asset = (
            next((a for a in self.document.project.assets if a.id == asset_id), None)
            if self.document.project
            else None
        )
        if asset is None:
            raise ProjectError("Choose a source in the active project.")
        with self.document.command_group("Place project asset"):
            if position is not None and parent is not None:
                from rigora.application_services.characters import CharacterService

                # Fresh parts inherit the destination's basis. Keeping an upright
                # world pose beneath a rotated, stretched parent would require shear.
                if CharacterService(self.document).locked(parent):
                    raise ProjectError("Unlock the destination before placing artwork.")
                parent = CharacterService(self.document).promote_object(parent)
            old = {r.id for r in (*self.scene.groups, *self.scene.objects)}
            meshes = {m.id for m in self.scene.meshes}
            if "sprite_sequence" in asset.extra:
                self.place_sequence(asset_id)
            elif "layered_layout" in asset.extra:
                self.place_layered(asset_id)
            elif asset.kind in ("raster", "vector"):
                self.instantiate_asset(asset_id)
            else:
                raise ProjectError("This source cannot be placed as artwork.")
            added = [r for r in (*self.scene.groups, *self.scene.objects) if r.id not in old]
            ids = {r.id for r in added}
            roots = tuple(r.id for r in added if getattr(r, "parent_id", None) not in ids)
            service = SceneEditingService(self.document)
            if position is not None and parent is not None:
                service.update_records(
                    {
                        entry.id: replace(entry, parent_id=parent)
                        for entry in added
                        if entry.id in roots and isinstance(entry, (Group, SceneObject))
                    },
                    "Place parts in object space",
                )
            service.center_entries(roots, position)
            if position is not None:
                for key in roots:
                    if isinstance(service.record(key), Group):
                        service.move_pivot(key, *position)
            if parent is not None or before is not None:
                service.move_entries(roots, parent, before)
        return {
            "root_ids": roots,
            "mesh_ids": tuple(m.id for m in self.scene.meshes if m.id not in meshes),
            "object_ids": tuple(o.id for o in self.scene.objects if o.id not in old),
        }

    def adopt(self, snapshot: Any, baseline: Project) -> None:
        """Publish a completed worker import only if its source document has not changed."""
        if self.document.project is not baseline or snapshot.project is None:
            raise ProjectError(
                "The project changed during import. Import again to keep both edits."
            )
        if (
            snapshot.project.assets == baseline.assets
            and snapshot.project.scenes == baseline.scenes
        ):
            return
        self.document.execute(
            ProjectPatch(
                "Import media",
                {"assets": baseline.assets, "scenes": baseline.scenes},
                {"assets": snapshot.project.assets, "scenes": snapshot.project.scenes},
            )
        )
        self.document._asset_data.update(snapshot._asset_data)

    def image(self, path: Path, *, place: bool = False) -> dict[str, Any]:
        """Import one original static image, optionally placing an independently editable mesh."""
        data = self.document._read_asset_file(path)
        info = inspect_artwork(data)
        if info.kind == "raster":
            import importlib.util

            if importlib.util.find_spec("PIL") is not None:
                pillow_image(data)
        with self.document.command_group("Import artwork"):
            key = self.register_image_bytes(path.name, data)
            mesh = self.instantiate_asset(key) if place else None
        assert self.document.project is not None
        asset = next(a for a in self.document.project.assets if a.id == key)
        return {
            "asset_id": key,
            "mesh_id": mesh,
            "media_type": asset.media_type,
            "object_id": self.mesh(mesh).object_id if mesh else None,
        }

    def sequence(
        self,
        paths: tuple[Path, ...],
        *,
        fps: float = 24,
        start: float = 0,
        loop: bool = True,
        place: bool = True,
    ) -> dict[str, Any]:
        """Import explicit frame order with equal bounds and deterministic frame-rate playback."""
        if not 1 <= len(paths) <= 256:
            raise ProjectError("Image sequences require 1–256 explicitly ordered image files.")
        if not 0 < number(fps, "Sequence FPS") <= 240 or number(start, "Start frame") < 0:
            raise ProjectError(
                "Sequence FPS must be above zero and at most 240; start is nonnegative."
            )
        if type(loop) is not bool:
            raise ProjectError("Sequence loop must be a boolean.")
        data = []
        total = 0
        for path in paths:
            blob = self.document._read_asset_file(path)
            total += len(blob)
            if total > 64 * 1024 * 1024:
                raise ProjectError("Image sequence sources exceed 64 MiB.")
            data.append(blob)
        infos = [inspect_artwork(value) for value in data]
        if len({(info.width, info.height) for info in infos}) != 1:
            raise ProjectError(
                "Sequence frames must have equal image bounds; source files were preserved."
            )
        with self.document.command_group("Import image sequence"):
            assets = [
                self.register_image_bytes(p.name, value)
                for p, value in zip(paths, data, strict=True)
            ]
            return self._sequence_records(paths[0].stem, assets, fps, start, loop, place)

    def _sequence_records(
        self,
        name: str,
        assets: list[str],
        fps: float,
        start: float,
        loop: bool,
        place: bool,
        source_asset_id: str | None = None,
    ) -> dict[str, Any]:
        """Register a portable sequence descriptor and optional independent mesh."""
        descriptor = {"assets": assets, "fps": fps, "start": start, "loop": loop}
        source = self.document.register_asset_bytes(
            f"{name}.rigsequence.json",
            json.dumps(descriptor).encode(),
            kind="sequence",
            media_type="application/vnd.rigora.sequence+json",
            metadata={"sprite_sequence": descriptor, "source_asset_id": source_asset_id},
        )
        mesh_id = self.instantiate_asset(assets[0]) if place else None
        if mesh_id:
            mesh = self.mesh(mesh_id)
            self.replace_mesh(
                replace(mesh, extra={**mesh.extra, "sprite_sequence": descriptor}),
                "Configure image sequence",
            )
        return {
            "asset_id": source.id,
            "frame_asset_ids": assets,
            "mesh_id": mesh_id,
            "fps": fps,
            "source_asset_id": source_asset_id,
        }

    def spritesheet(
        self,
        path: Path,
        *,
        frame_width: int,
        frame_height: int,
        fps: float = 24,
        count: int | None = None,
        margin: int = 0,
        spacing: int = 0,
        place: bool = True,
    ) -> dict[str, Any]:
        """Slice row-major PNG frames while retaining the complete original sheet."""
        for value in (frame_width, frame_height, margin, spacing):
            if type(value) is not int or value < 0:
                raise ProjectError(
                    "Sprite cell dimensions, margin and spacing must be nonnegative integers."
                )
        if not frame_width or not frame_height or not 0 < number(fps, "Sprite FPS") <= 240:
            raise ProjectError("Choose positive sprite dimensions and FPS from above zero to 240.")
        data = self.document._read_asset_file(path)
        image = pillow_image(data)
        columns = (image.width - 2 * margin + spacing) // (frame_width + spacing)
        rows = (image.height - 2 * margin + spacing) // (frame_height + spacing)
        total = count if count is not None else columns * rows
        if type(total) is not int or not 1 <= total <= min(256, columns * rows):
            raise ProjectError("Sprite sheet needs 1–256 cells completely inside its margins.")
        with self.document.command_group("Import sprite sheet"):
            original = self.document.register_asset_bytes(
                path.name, data, kind="sequence", metadata={"container": "spritesheet"}
            )
            assets = []
            for index in range(total):
                x = margin + index % columns * (frame_width + spacing)
                y = margin + index // columns * (frame_height + spacing)
                cell = image.crop((x, y, x + frame_width, y + frame_height))
                assets.append(
                    self.register_image_bytes(f"{path.stem}-{index:04d}.png", png_bytes(cell))
                )
            return self._sequence_records(path.stem, assets, fps, 0, True, place, original.id)

    def place_sequence(self, asset_id: str) -> str:
        """Place another independent instance of a registered sequence descriptor."""
        project = self.document.project
        asset = next((a for a in project.assets if a.id == asset_id), None) if project else None
        if asset is None or "sprite_sequence" not in asset.extra:
            raise ProjectError("Choose an imported image sequence or sprite sheet.")
        sequence = asset.extra["sprite_sequence"]
        with self.document.command_group("Place image sequence"):
            key = self.instantiate_asset(sequence["assets"][0])
            self.replace_mesh(replace(self.mesh(key), extra={"sprite_sequence": sequence}))
        return key

    def layered(
        self, path: Path, *, allow_unsupported: bool = False, place: bool = False
    ) -> dict[str, Any]:
        """Import ORA/PSD layers or acknowledged AI artboards, retaining the complete source."""
        data = self.document._read_asset_file(path)
        if path.suffix.lower() == ".ora":
            artwork = read_openraster(data, allow_unsupported=allow_unsupported)
        elif path.suffix.lower() in (".psd", ".psb"):
            artwork = read_psd(data, allow_unsupported=allow_unsupported)
        elif path.suffix.lower() == ".ai":
            artwork = read_illustrator(data, allow_unsupported=allow_unsupported)
        else:
            raise ProjectError(
                "Artwork containers support OpenRaster .ora, basic .psd/.psb "
                "and PDF-compatible .ai."
            )
        with self.document.command_group("Import layered artwork"):
            source = self.document.register_asset_bytes(
                path.name,
                data,
                kind="sequence",
                media_type=artwork.media_type,
                metadata={
                    "container": "layered",
                    "import_warnings": list(artwork.warnings),
                    "image_width": artwork.width,
                    "image_height": artwork.height,
                },
            )
            layout = []
            for layer in artwork.layers:
                asset = (
                    self.register_image_bytes(layer.name + ".png", layer.data)
                    if layer.data is not None
                    else None
                )
                layout.append(
                    {
                        "name": layer.name,
                        "parent": layer.parent,
                        "x": layer.x,
                        "y": layer.y,
                        "visible": layer.visible,
                        "opacity": layer.opacity,
                        "asset_id": asset,
                    }
                )
            updated = replace(source, extra={**source.extra, "layered_layout": layout})
            assert self.document.project is not None
            assets = self.document.project.assets
            self.document.execute(
                ProjectPatch(
                    "Register layered layout",
                    {"assets": assets},
                    {"assets": tuple(updated if a.id == source.id else a for a in assets)},
                )
            )
            result = (
                self.place_layered(source.id)
                if place
                else {"object_ids": [], "mesh_ids": [], "group_ids": []}
            )
        return {
            **result,
            "source_asset_id": source.id,
            "warnings": list(artwork.warnings),
            "width": artwork.width,
            "height": artwork.height,
        }

    def place_layered(self, asset_id: str) -> dict[str, Any]:
        """Instantiate an imported layered layout with fresh object, group and mesh identities."""
        project = self.document.project
        source = next((a for a in project.assets if a.id == asset_id), None) if project else None
        if source is None or "layered_layout" not in source.extra:
            raise ProjectError("Choose an imported layered artwork source.")
        layout = source.extra["layered_layout"]
        if not isinstance(layout, (list, tuple)) or not 1 <= len(layout) <= 128:
            raise ProjectError("Layered source layout is invalid.")
        objects, groups, meshes = [], [], []
        parents: dict[int, str] = {}
        with self.document.command_group("Place layered artwork"):
            container = Group(
                name=source.name,
                extra={"source_asset_id": source.id, "object_container": True},
            )
            groups.append(container)
            self.commit("Create imported resource folder", groups=(*self.scene.groups, container))
            for index, layer in enumerate(layout):
                parent = (
                    parents.get(layer["parent"]) if layer["parent"] is not None else container.id
                )
                if layer["parent"] is not None and parent is None:
                    raise ProjectError("Layer parent must reference an earlier group.")
                if layer["asset_id"] is None:
                    group = Group(
                        name=layer["name"],
                        parent_id=parent,
                        transform=Transform(x=layer["x"], y=layer["y"]),
                        extra={
                            "visible": layer["visible"],
                            "opacity": layer["opacity"],
                            "source_asset_id": source.id,
                        },
                    )
                    groups.append(group)
                    parents[index] = group.id
                    self.commit("Import layer group", groups=(*self.scene.groups, group))
                    continue
                key = self.instantiate_asset(layer["asset_id"])
                mesh = self.mesh(key)
                obj = next(o for o in self.scene.objects if o.id == mesh.object_id)
                obj = replace(
                    obj,
                    name=layer["name"],
                    parent_id=parent,
                    visible=layer["visible"],
                    transform=Transform(
                        x=layer["x"],
                        y=layer["y"],
                        pivot_x=mesh.extra["image_width"] / 2,
                        pivot_y=mesh.extra["image_height"] / 2,
                    ),
                    extra={"opacity": layer["opacity"], "source_asset_id": source.id},
                )
                self.commit(
                    "Position imported layer",
                    objects=tuple(
                        obj if item.id == obj.id else item for item in self.scene.objects
                    ),
                )
                objects.append(obj.id)
                meshes.append(key)
        return {
            "source_asset_id": source.id,
            "object_ids": objects,
            "mesh_ids": meshes,
            "group_ids": [g.id for g in groups],
        }

    def audio(self, path: Path) -> dict[str, Any]:
        """Embed original PCM WAV bytes and validated timing metadata without scene placement."""
        data = self.document._read_asset_file(path)
        return self.audio_bytes(path.name, data)

    def audio_bytes(self, name: str, data: bytes) -> dict[str, Any]:
        """Publish imported or recorded WAV bytes through the shared asset service."""
        metadata = audio_metadata(data)
        asset = self.document.register_asset_bytes(
            name,
            data,
            kind="audio",
            media_type="audio/wav",
            metadata=metadata,
        )
        return {"asset_id": asset.id, **metadata}
