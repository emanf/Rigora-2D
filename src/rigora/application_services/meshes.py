"""Undoable artwork and mesh editing over the canonical document service."""

from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from rigora.application_services.commands import ScenePatch
from rigora.application_services.documents import DocumentService
from rigora.domain.draw_order import scene_draw_order
from rigora.domain.entities import Mesh, SceneObject, Transform
from rigora.domain.mesh_geometry import (
    Point,
    barycentric,
    grid_mesh,
    insert_vertex,
    move_vertices,
    normalize_weights,
    remove_vertices,
    validate_embedding,
)
from rigora.domain.project import ProjectError, Scene
from rigora.engine.subdivision import subdivide
from rigora.infrastructure.artwork import inspect_artwork


class MeshService:
    """Apply complete validated mesh edits without Qt, file dialogs or renderer state."""

    def __init__(self, document: DocumentService) -> None:
        """Attach to a document while leaving selection and active tools to presentation."""
        self.document = document

    @property
    def scene(self) -> Scene:
        """Resolve the live first scene after commands and undo/redo."""
        if self.document.project is None:
            raise ProjectError("Create or open a project before editing artwork.")
        return self.document.scene

    def commit(self, label: str, **changes: Any) -> None:
        """Commit changed collections atomically through the shared reversible command history."""
        scene = self.scene
        if "objects" in changes and "draw_order" not in changes:
            existing = {o.id for o in scene.objects}
            added = tuple(o.id for o in changes["objects"] if o.id not in existing)
            if added:
                changes["draw_order"] = tuple(
                    dict.fromkeys((*scene_draw_order(scene), *scene.draw_order, *added))
                )
        self.document.execute(
            ScenePatch(label, scene.id, {k: getattr(scene, k) for k in changes}, changes)
        )

    def mesh(self, key: str) -> Mesh:
        """Resolve a mesh UUID with an actionable stale-selection error."""
        mesh = next((m for m in self.scene.meshes if m.id == key), None)
        if mesh is None:
            raise ProjectError("The selected mesh no longer exists.")
        return mesh

    def replace_mesh(self, mesh: Mesh, label: str = "Edit mesh") -> None:
        """Replace one existing mesh without changing its owner or source bytes."""
        self.mesh(mesh.id)
        self.commit(label, meshes=tuple(mesh if m.id == mesh.id else m for m in self.scene.meshes))

    def import_image(self, path: Path, columns: int | None = None, rows: int | None = None) -> str:
        """Import Full topology by default; explicit grid dimensions retain regular cells."""
        return self.import_image_bytes(
            path.name, self.document._read_asset_file(path), columns, rows
        )

    def import_image_bytes(
        self, name: str, data: bytes, columns: int | None = None, rows: int | None = None
    ) -> str:
        """Embed original artwork and create a fitted object/UV mesh in one undo step."""
        with self.document.command_group("Import artwork and mesh"):
            asset_id = self.register_image_bytes(name, data)
            return self.instantiate_asset(asset_id, columns, rows)

    def register_image_bytes(self, name: str, data: bytes) -> str:
        """Validate and embed an image in the project library without creating scene geometry."""
        info = inspect_artwork(data)
        metadata: dict[str, Any] = {}
        original = data
        if info.kind == "raster":
            from rigora.infrastructure.raster_color import normalized_raster

            data, metadata = normalized_raster(data)
            info = inspect_artwork(data)
        with self.document.command_group("Register artwork"):
            if metadata:
                source = self.document.register_asset_bytes(
                    name, original, kind="sequence", metadata={"container": "source-image"}
                )
                metadata["source_asset_id"] = source.id
                name = Path(name).stem + ".png"
            asset = self.document.register_asset_bytes(
                name,
                data,
                kind=info.kind,
                media_type=info.media_type,
                metadata={"image_width": info.width, "image_height": info.height, **metadata},
            )
        return asset.id

    def instantiate_asset(
        self, asset_id: str, columns: int | None = None, rows: int | None = None
    ) -> str:
        """Place artwork with Full triangles unless explicit grid dimensions are supplied.

        The original source is shared; topology, subdivision settings and the scene
        object belong to this instance and are created together in one undo step.
        """
        project = self.document.project
        if project is None:
            raise ProjectError("Create or open a project before placing artwork.")
        asset = next((a for a in project.assets if a.id == asset_id), None)
        if asset is None:
            raise ProjectError("The selected project asset no longer exists.")
        data = self.document.read_asset(asset_id)
        info = inspect_artwork(data)
        scene = self.scene
        if columns is None and rows is None:
            mesh = subdivide(info.width, info.height)
            subdivision = {"mode": "full", "density": 4, "alignment": 1, "expand": 0}
        else:
            columns, rows = 4 if columns is None else columns, 4 if rows is None else rows
            mesh = grid_mesh(info.width, info.height, columns, rows)
            subdivision = {
                "mode": "grid",
                "density": max(columns, rows),
                "columns": columns,
                "rows": rows,
            }
        mesh = replace(mesh, extra={**mesh.extra, "subdivision": subdivision})
        scale = min(
            1, scene.settings.width * 0.8 / info.width, scene.settings.height * 0.8 / info.height
        )
        obj = SceneObject(
            name=(Path(asset.name).stem or "Artwork")[:200],
            asset_id=asset.id,
            transform=Transform(
                x=(scene.settings.width - info.width) / 2,
                y=(scene.settings.height - info.height) / 2,
                scale_x=scale,
                scale_y=scale,
                pivot_x=info.width / 2,
                pivot_y=info.height / 2,
            ),
        )
        mesh = replace(mesh, name=f"{obj.name[:190]} mesh", object_id=obj.id, asset_id=asset.id)
        self.commit(
            "Place artwork instance", objects=(*scene.objects, obj), meshes=(*scene.meshes, mesh)
        )
        return mesh.id

    def move(self, key: str, positions: Mapping[str, Point]) -> None:
        """Move selected base vertices without collapsing/inverting triangles or changing UVs."""
        self.replace_mesh(move_vertices(self.mesh(key), positions), "Move mesh vertices")

    def insert(self, key: str, x: float, y: float) -> str:
        """Insert a vertex, splitting a shared edge/face when hit-testing finds one."""
        mesh, vertex = insert_vertex(self.mesh(key), x, y)
        self.replace_mesh(mesh, "Insert mesh vertex")
        return vertex

    def delete(self, key: str, vertices: set[str]) -> None:
        """Delete vertices, adjacent faces and their pin/mask/key references as one undo step."""
        mesh = remove_vertices(self.mesh(key), vertices)
        mesh = replace(
            mesh,
            extra={
                **mesh.extra,
                "area_pins": [
                    p for p in mesh.extra.get("area_pins", ()) if p["vertex_id"] not in vertices
                ],
            },
        )
        stages = []
        paths: set[tuple[str, str]] = set()
        for stage in self.scene.deformers:
            params = dict(stage.parameters)
            if stage.owner_id == key:
                for field in ("pins", "weights", "offsets"):
                    if field in params:
                        params[field] = {
                            k: value for k, value in params[field].items() if k not in vertices
                        }
                        paths.update((stage.id, f"parameters.{field}.{k}") for k in vertices)
            stages.append(replace(stage, parameters=params))
        self.commit(
            "Delete mesh vertices",
            meshes=tuple(mesh if m.id == key else m for m in self.scene.meshes),
            deformers=tuple(stages),
            timelines=tuple(
                replace(
                    t,
                    tracks=tuple(
                        track
                        for track in t.tracks
                        if track.owner_id not in vertices
                        and not any(
                            track.owner_id == owner
                            and (
                                track.property_path == path
                                or track.property_path.startswith(path + ".")
                            )
                            for owner, path in paths
                        )
                    ),
                )
                for t in self.scene.timelines
            ),
        )

    def set_flags(
        self,
        key: str,
        vertices: set[str],
        *,
        pinned: bool | None = None,
        protected: bool | None = None,
    ) -> None:
        """Set per-vertex deformation anchors or authoring protection as one undoable edit."""
        changes: dict[str, Any] = {
            k: v for k, v in (("pinned", pinned), ("protected", protected)) if v is not None
        }
        mesh = self.mesh(key)
        self.replace_mesh(
            replace(
                mesh,
                vertices=tuple(
                    replace(v, **changes) if v.id in vertices else v for v in mesh.vertices
                ),
            ),
            "Pin/protect mesh vertices",
        )

    def connect_triangle(self, key: str, vertices: tuple[str, str, str]) -> None:
        """Create a face from three selected stable vertex IDs with full topology validation."""
        mesh = self.mesh(key)
        candidate = replace(mesh, triangles=(*mesh.triangles, vertices))
        validate_embedding(candidate)
        self.replace_mesh(candidate, "Create mesh triangle")

    def regenerate(self, key: str, columns: int, rows: int, *, discard_edits: bool = False) -> None:
        """Replace topology only after explicit consent, removing dependent stages and tracks
        together.
        """
        if not discard_edits:
            raise ProjectError(
                "Regeneration replaces mesh edits, weights and deformation keys; confirm first."
            )
        mesh = self.mesh(key)
        width, height = mesh.extra.get("image_width"), mesh.extra.get("image_height")
        if not isinstance(width, (int, float)) or not isinstance(height, (int, float)):
            raise ProjectError("This mesh has no source image dimensions for grid generation.")
        grid = grid_mesh(width, height, columns, rows)
        mesh = replace(
            mesh,
            vertices=grid.vertices,
            triangles=grid.triangles,
            extra={
                **mesh.extra,
                "area_pins": [],
                "subdivision": {"mode": "grid", "columns": columns, "rows": rows},
            },
        )
        removed = {v.id for v in self.mesh(key).vertices}
        removed.update(d.id for d in self.scene.deformers if d.owner_id == key)
        self.commit(
            "Regenerate mesh grid",
            meshes=tuple(mesh if m.id == key else m for m in self.scene.meshes),
            deformers=tuple(d for d in self.scene.deformers if d.id not in removed),
            timelines=tuple(
                replace(t, tracks=tuple(k for k in t.tracks if k.owner_id not in removed))
                for t in self.scene.timelines
            ),
        )

    def subdivide(
        self,
        keys: tuple[str, ...],
        *,
        mode: str,
        density: int,
        alignment: int = 1,
        expand: float = 0,
        discard_edits: bool = False,
        progress: Callable[[int], None] | None = None,
    ) -> None:
        """Replace selected source topology atomically, transferring skin weights and bindings.

        Vertex keys and topology-dependent deformers need explicit discard consent. Bone
        bindings and image-area pins survive; new weights interpolate old base triangles.
        All target geometry is prepared before committing so a failed mask changes nothing.
        """
        from shapely import Point as SpatialPoint
        from shapely import Polygon, STRtree

        from rigora.infrastructure.artwork_mask import artwork_mask

        if not discard_edits:
            raise ProjectError("Confirm subdivision before replacing topology and its keys.")
        changed = {}
        removed: set[str] = set()
        targets = tuple(dict.fromkeys(keys))
        for index, key in enumerate(targets):
            if progress:
                progress(round(100 * index / len(targets)))
            old = self.mesh(key)
            width, height = old.extra.get("image_width"), old.extra.get("image_height")
            if not isinstance(width, (int, float)) or not isinstance(height, (int, float)):
                raise ProjectError("Subdivision needs source image dimensions.")
            mask = None
            if mode == "mask":
                if not old.asset_id:
                    raise ProjectError("Mask subdivision needs original artwork.")
                mask = artwork_mask(self.document.read_asset(old.asset_id))

            def report_mesh(value: int, step: int = index) -> None:
                """Map this mesh's generation phase to the complete batch progress."""
                if progress:
                    progress(round((100 * step + 80 * value / 100) / len(targets)))

            generated = subdivide(
                width,
                height,
                mode=mode,
                density=density,
                alignment=alignment,
                expand=expand,
                mask=mask,
                progress=report_mesh if progress else None,
            )
            pins = []
            for pin in old.extra.get("area_pins", ()):
                existing = next(
                    (
                        v
                        for v in generated.vertices
                        if (v.x - pin["x"]) ** 2 + (v.y - pin["y"]) ** 2 < 1e-14
                    ),
                    None,
                )
                if existing:
                    vertex_id = existing.id
                else:
                    generated, vertex_id = insert_vertex(generated, pin["x"], pin["y"])
                pins.append({**pin, "vertex_id": vertex_id})
            by_id = {v.id: v for v in old.vertices}
            source_faces = [tuple(by_id[k] for k in face) for face in old.triangles]
            spatial_index = STRtree([Polygon([(v.x, v.y) for v in face]) for face in source_faces])
            vertices = []
            for vertex_index, vertex in enumerate(generated.vertices):
                weights: dict[str, float] = {}
                for face_index in spatial_index.query(SpatialPoint(vertex.x, vertex.y)):
                    source = source_faces[int(face_index)]
                    factors = barycentric((vertex.x, vertex.y), *((v.x, v.y) for v in source))
                    if min(factors) >= -1e-8:
                        for v, factor in zip(source, factors, strict=True):
                            for bone, value in v.weights.items():
                                weights[bone] = weights.get(bone, 0) + max(0, factor) * value
                        break
                else:
                    if old.vertices:
                        nearest = min(
                            old.vertices,
                            key=lambda v: (v.x - vertex.x) ** 2 + (v.y - vertex.y) ** 2,
                        )
                        weights = dict(nearest.weights)
                vertices.append(replace(vertex, weights=normalize_weights(weights, 16)))
                if progress and vertex_index % 128 == 0:
                    progress(
                        round(
                            (100 * index + 80 + 20 * (vertex_index + 1) / len(generated.vertices))
                            / len(targets)
                        )
                    )
            changed[key] = replace(
                old,
                vertices=tuple(vertices),
                triangles=generated.triangles,
                extra={
                    **old.extra,
                    "area_pins": pins,
                    "subdivision": {
                        "mode": mode,
                        "density": density,
                        "alignment": alignment,
                        "expand": expand,
                    },
                },
            )
            removed.update(v.id for v in old.vertices)
            removed.update(
                d.id
                for d in self.scene.deformers
                if d.owner_id == key and d.kind not in ("skinning", "appearance")
            )
            if progress:
                progress(round(100 * (index + 1) / len(targets)))
        if not changed:
            raise ProjectError("Select artwork before subdividing.")
        self.commit(
            "Subdivide artwork",
            meshes=tuple(changed.get(m.id, m) for m in self.scene.meshes),
            deformers=tuple(d for d in self.scene.deformers if d.id not in removed),
            timelines=tuple(
                replace(t, tracks=tuple(k for k in t.tracks if k.owner_id not in removed))
                for t in self.scene.timelines
            ),
        )
