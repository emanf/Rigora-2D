"""Canonical project and scene containers."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any
from uuid import UUID, uuid4

from rigora.domain.entities import (
    ENTITY_COLLECTIONS,
    AnimationClip,
    Asset,
    AssetReference,
    Attachment,
    Bone,
    Camera,
    Character,
    Constraint,
    Deformer,
    Entity,
    Group,
    Keyframe,
    Layer,
    Marker,
    Mesh,
    PluginExtension,
    ProjectSettings,
    SceneObject,
    Skeleton,
    Slot,
    Timeline,
    Vertex,
    nested_records,
)
from rigora.domain.validation import (
    ProjectError as ProjectError,
)
from rigora.domain.validation import (
    frozen_extra,
    identifier,
    integer,
    text,
)
from rigora.domain.validation import (
    json_copy as json_copy,
)
from rigora.domain.validation import (
    mapping as mapping,
)


@lru_cache(maxsize=32768)
def _canonical_id(value: str) -> str:
    """Reuse UUID normalization across immutable revisions while retaining alias detection."""
    return str(UUID(value))


@dataclass(frozen=True, slots=True)
class SceneSettings:
    """Validated canvas dimensions, integer frame rate, and inclusive frame range."""

    width: int = 1920
    height: int = 1080
    fps: int = 24
    start_frame: int = 0
    end_frame: int = 120
    extra: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        """Validate canvas and frame bounds and freeze unknown optional settings."""
        integer(self.width, "Canvas width", 1, 16384)
        integer(self.height, "Canvas height", 1, 16384)
        integer(self.fps, "Frame rate", 1, 240)
        integer(self.start_frame, "Start frame", 0, 10_000_000)
        integer(self.end_frame, "End frame", self.start_frame, 10_000_000)
        object.__setattr__(self, "extra", frozen_extra(self.extra))

    def to_dict(self) -> dict[str, Any]:
        """Encode known settings and preserved optional fields into JSON data."""
        return {
            **json_copy(self.extra),
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "start_frame": self.start_frame,
            "end_frame": self.end_frame,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "SceneSettings":
        """Parse required scene settings without dropping compatible unknown fields."""
        data = mapping(value, "Scene settings")
        keys = ("width", "height", "fps", "start_frame", "end_frame")
        if not all(key in data for key in keys):
            raise ProjectError("Scene settings are missing required fields.")
        return cls(
            **{key: data[key] for key in keys},
            extra=json_copy({key: val for key, val in data.items() if key not in keys}),
        )


@dataclass(frozen=True, slots=True)
class Scene:
    """Immutable scene container owning the complete authoring entity graph."""

    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = "Scene 01"
    settings: SceneSettings = field(default_factory=SceneSettings)
    extra: Mapping[str, Any] = field(default_factory=dict, repr=False)
    layers: tuple[Layer, ...] = ()
    groups: tuple[Group, ...] = ()
    objects: tuple[SceneObject, ...] = ()
    characters: tuple[Character, ...] = ()
    skeletons: tuple[Skeleton, ...] = ()
    meshes: tuple[Mesh, ...] = ()
    slots: tuple[Slot, ...] = ()
    attachments: tuple[Attachment, ...] = ()
    clips: tuple[AnimationClip, ...] = ()
    timelines: tuple[Timeline, ...] = ()
    deformers: tuple[Deformer, ...] = ()
    constraints: tuple[Constraint, ...] = ()
    extensions: tuple[PluginExtension, ...] = ()
    draw_order: tuple[str, ...] = ()
    cameras: tuple[Camera, ...] = ()

    def __post_init__(self) -> None:
        """Validate scene identity, collection types, settings, and draw-order ID syntax."""
        identifier(self.id)
        text(self.name, "Scene name")
        if not isinstance(self.settings, SceneSettings):
            raise ProjectError("Scene settings are invalid.")
        object.__setattr__(self, "extra", frozen_extra(self.extra))
        for key, kind in ENTITY_COLLECTIONS.items():
            values = getattr(self, key)
            if not isinstance(values, tuple) or not all(isinstance(v, kind) for v in values):
                raise ProjectError(f"Scene {key} must contain {kind.__name__} records.")
        if any(isinstance(g, Camera) for g in self.groups):
            raise ProjectError("Cameras belong in the scene cameras collection.")
        if not isinstance(self.draw_order, tuple):
            raise ProjectError("Scene draw order must be a tuple of IDs.")
        for value in self.draw_order:
            identifier(value)

    def to_dict(self) -> dict[str, Any]:
        """Serialize all scene collections and compatible optional scene fields."""
        return {
            **json_copy(self.extra),
            "id": self.id,
            "name": self.name,
            "settings": self.settings.to_dict(),
            **{key: [item.to_dict() for item in getattr(self, key)] for key in ENTITY_COLLECTIONS},
            "draw_order": list(self.draw_order),
        }

    @classmethod
    def from_dict(cls, value: Any) -> "Scene":
        """Decode scene collections through their typed record codecs."""
        data = mapping(value, "Scene")
        if not all(key in data for key in ("id", "name", "settings")):
            raise ProjectError("Scene is missing its id, name, or settings.")
        collections: dict[str, Any] = {}
        for key, kind in ENTITY_COLLECTIONS.items():
            values = data.get(key, [])
            if not isinstance(values, list):
                raise ProjectError(f"Scene {key} must be a JSON list.")
            collections[key] = tuple(kind.from_dict(item) for item in values)
        order = data.get("draw_order", [])
        if not isinstance(order, list):
            raise ProjectError("Scene draw_order must be a JSON list.")
        return cls(
            data["id"],
            data["name"],
            SceneSettings.from_dict(data["settings"]),
            json_copy(
                {
                    k: v
                    for k, v in data.items()
                    if k not in {"id", "name", "settings", "draw_order", *ENTITY_COLLECTIONS}
                }
            ),
            **collections,
            draw_order=tuple(order),
        )


@dataclass(frozen=True, slots=True)
class Project:
    """Canonical immutable authoring document with shared assets and independent scenes."""

    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = "Untitled project"
    scenes: tuple[Scene, ...] = field(default_factory=lambda: (Scene(),))
    extra: Mapping[str, Any] = field(default_factory=dict, repr=False)
    settings: ProjectSettings = field(default_factory=ProjectSettings)
    assets: tuple[Asset, ...] = ()
    asset_references: tuple[AssetReference, ...] = ()
    extensions: tuple[PluginExtension, ...] = ()

    def __post_init__(self) -> None:
        """Validate project structure, embedded source uniqueness, and all graph references."""
        identifier(self.id)
        text(self.name, "Project name")
        if not isinstance(self.scenes, tuple) or not 1 <= len(self.scenes) <= 100:
            raise ProjectError("A project must have 1–100 scenes.")
        if not all(isinstance(scene, Scene) for scene in self.scenes):
            raise ProjectError("Project scenes are invalid.")
        ids = [self.id, *(scene.id for scene in self.scenes)]
        if len({_canonical_id(value) for value in ids}) != len(ids):
            raise ProjectError("Project and scene IDs must be unique.")
        object.__setattr__(self, "extra", frozen_extra(self.extra))
        if not isinstance(self.settings, ProjectSettings):
            raise ProjectError("Project settings are invalid.")
        for values, kind in (
            (self.assets, Asset),
            (self.asset_references, AssetReference),
            (self.extensions, PluginExtension),
        ):
            if not isinstance(values, tuple) or not all(isinstance(v, kind) for v in values):
                raise ProjectError(f"Project collection requires {kind.__name__} records.")
        embedded_sources = [asset.source for asset in self.assets if asset.storage == "embedded"]
        if len(set(embedded_sources)) != len(embedded_sources):
            raise ProjectError("Embedded asset paths must be unique.")
        self.validate_references()

    def validate_references(self) -> None:
        """Reject duplicate IDs, missing or incompatible references, and parent cycles."""
        records = nested_records(self)
        ids = [self.id, *(scene.id for scene in self.scenes), *(r.id for r in records)]
        if len({_canonical_id(value) for value in ids}) != len(ids):
            raise ProjectError("All persistent entity IDs must be unique across the project.")
        assets = {asset.id: asset for asset in self.assets}
        for asset in self.assets:
            if "sprite_sequence" in asset.extra:
                from rigora.domain.sprite_sequence import validate_sequence

                sequence = validate_sequence(asset.extra["sprite_sequence"])
                if any(
                    key not in assets or assets[key].kind not in ("raster", "vector")
                    for key in sequence["assets"]
                ):
                    raise ProjectError("Sequence descriptor references missing image assets.")
            if "layered_layout" in asset.extra:
                layout = asset.extra["layered_layout"]
                if not isinstance(layout, (tuple, list)) or not 1 <= len(layout) <= 128:
                    raise ProjectError("Layered artwork layout must contain 1–128 entries.")
                for index, layer in enumerate(layout):
                    if (
                        not isinstance(layer, Mapping)
                        or "asset_id" not in layer
                        or "parent" not in layer
                    ):
                        raise ProjectError("Layered artwork entry is invalid.")
                    parent = layer["parent"]
                    if parent is not None and (
                        type(parent) is not int
                        or not 0 <= parent < index
                        or layout[parent]["asset_id"] is not None
                    ):
                        raise ProjectError(
                            "Layered artwork parent must reference an earlier group."
                        )
                    key = layer["asset_id"]
                    if key is not None and not isinstance(key, str):
                        raise ProjectError("Layered source asset IDs must be strings.")
                    if key is not None and (
                        key not in assets or assets[key].kind not in ("raster", "vector")
                    ):
                        raise ProjectError("Layered layout references a missing image asset.")
        for reference in self.asset_references:
            if reference.asset_id not in assets:
                raise ProjectError("Asset reference points to a missing asset.")
        for scene in self.scenes:
            local = {record.id: record for record in nested_records(scene)}
            from rigora.domain.scene_attachments import validate_scene

            validate_scene(scene, local)
            targets: dict[str, Entity] = {**assets, **local}
            for record in local.values():
                # These leaves own no graph references. Mesh validation below still
                # checks every vertex influence against the current scene's bones.
                if isinstance(record, (Vertex, Keyframe, Marker)):
                    continue
                for field_name in (
                    "parent_id",
                    "layer_id",
                    "asset_id",
                    "object_id",
                    "skeleton_id",
                    "owner_id",
                    "target_id",
                    "slot_id",
                    "mesh_id",
                    "timeline_id",
                    "active_attachment_id",
                ):
                    target_reference = getattr(record, field_name, None)
                    if target_reference is not None and target_reference not in targets:
                        raise ProjectError(
                            f"{record.name}.{field_name} references a missing entity."
                        )
                for field_name in ("object_ids", "mesh_ids", "attachment_ids"):
                    if any(ref not in local for ref in getattr(record, field_name, ())):
                        raise ProjectError(
                            f"{record.name}.{field_name} references a missing entity."
                        )
                for field_name in ("owner_id", "target_id"):
                    local_reference = getattr(record, field_name, None)
                    if local_reference is not None and local_reference not in local:
                        raise ProjectError(f"{field_name} must reference an entity in its scene.")
                if (
                    isinstance(record, Camera)
                    and record.asset_id is not None
                    and assets[record.asset_id].kind not in ("raster", "vector")
                ):
                    raise ProjectError("Camera backgrounds require image assets.")
                if isinstance(record, (Group, SceneObject)):
                    parent = targets.get(record.parent_id or "")
                    kinds = (Group,) if isinstance(record, Group) else (Group, SceneObject)
                    if isinstance(parent, Camera):
                        raise ProjectError("Cameras cannot own artwork or other cameras.")
                    if parent is not None and not isinstance(parent, kinds):
                        raise ProjectError("Object/group parent has an incompatible type.")
                if isinstance(record, Group):
                    view_assets = record.extra.get("object_view_assets", ())
                    if not isinstance(view_assets, (list, tuple)) or any(
                        not isinstance(key, str) or key not in assets for key in view_assets
                    ):
                        raise ProjectError("Object Views references a missing source asset.")
                asset_id = getattr(record, "asset_id", None)
                if asset_id is not None and asset_id not in assets:
                    raise ProjectError("asset_id must reference an asset.")
                layer_id = getattr(record, "layer_id", None)
                if layer_id is not None and not isinstance(local.get(layer_id), Layer):
                    raise ProjectError("layer_id must reference a scene layer.")
                if isinstance(record, Character) and (
                    not isinstance(local.get(record.skeleton_id), Skeleton)
                    or any(not isinstance(local.get(ref), SceneObject) for ref in record.object_ids)
                    or any(not isinstance(local.get(ref), Mesh) for ref in record.mesh_ids)
                ):
                    raise ProjectError("Character references have incompatible entity types.")
                if isinstance(record, AnimationClip) and not isinstance(
                    local.get(record.timeline_id), Timeline
                ):
                    raise ProjectError("Clip must reference a timeline.")
                if isinstance(record, Slot) and (
                    (
                        record.active_attachment_id is not None
                        and record.active_attachment_id not in record.attachment_ids
                    )
                    or any(
                        not isinstance(local.get(ref), Attachment) for ref in record.attachment_ids
                    )
                    or not isinstance(local.get(record.owner_id), (SceneObject, Bone))
                ):
                    raise ProjectError("Slot ownership or attachment membership is invalid.")
                if isinstance(record, Deformer) and not isinstance(
                    local.get(record.owner_id),
                    (SceneObject, Mesh, Bone, Group)
                    if isinstance(record, Constraint)
                    else (SceneObject, Mesh, Bone),
                ):
                    raise ProjectError(
                        "Choose a compatible object, mesh, bone, or constraint group owner."
                    )
                if isinstance(record, Attachment):
                    slot = local.get(record.slot_id)
                    if not isinstance(slot, Slot) or record.id not in slot.attachment_ids:
                        raise ProjectError("Attachment and slot membership must agree.")
                if isinstance(record, Mesh):
                    if "sprite_sequence" in record.extra:
                        from rigora.domain.sprite_sequence import validate_sequence

                        sequence = validate_sequence(record.extra["sprite_sequence"])
                        if any(
                            key not in assets or assets[key].kind not in ("raster", "vector")
                            for key in sequence["assets"]
                        ):
                            raise ProjectError("Sprite sequence references missing image assets.")
                    if record.object_id is not None and not isinstance(
                        local.get(record.object_id), SceneObject
                    ):
                        raise ProjectError("Mesh object_id must reference a scene object.")
                    for vertex in record.vertices:
                        if any(not isinstance(local.get(bone), Bone) for bone in vertex.weights):
                            raise ProjectError("Vertex weights reference a missing bone.")
            for skeleton in scene.skeletons:
                bone_ids = {bone.id for bone in skeleton.bones}
                if any(
                    bone.parent_id is not None and bone.parent_id not in bone_ids
                    for bone in skeleton.bones
                ):
                    raise ProjectError("A bone parent must belong to the same skeleton.")
            for record in local.values():
                if not isinstance(record, (Bone, Group, SceneObject)):
                    continue
                visited: set[str] = set()
                current: Entity | None = record
                while current is not None:
                    if current.id in visited:
                        raise ProjectError("Parent hierarchy contains a cycle.")
                    visited.add(current.id)
                    current = local.get(getattr(current, "parent_id", "") or "")
            if len(scene.draw_order) != len(set(scene.draw_order)) or any(
                not isinstance(local.get(key), (SceneObject, Slot)) for key in scene.draw_order
            ):
                raise ProjectError("Draw order must contain unique object/slot IDs.")

    def to_dict(self) -> dict[str, Any]:
        """Encode the complete canonical model without derived caches or workspace state."""
        return {
            **json_copy(self.extra),
            "id": self.id,
            "name": self.name,
            "scenes": [scene.to_dict() for scene in self.scenes],
            "settings": self.settings.to_dict(),
            "assets": [asset.to_dict() for asset in self.assets],
            "asset_references": [ref.to_dict() for ref in self.asset_references],
            "extensions": [ext.to_dict() for ext in self.extensions],
        }

    @classmethod
    def from_dict(cls, value: Any) -> "Project":
        """Construct a validated project while retaining compatible unknown metadata."""
        data = mapping(value, "Project")
        if not all(key in data for key in ("id", "name", "scenes")):
            raise ProjectError("Project is missing its id, name, or scenes.")
        if not isinstance(data["scenes"], list) or not 1 <= len(data["scenes"]) <= 100:
            raise ProjectError("A project must have 1–100 scenes.")
        for key in ("assets", "asset_references", "extensions"):
            if not isinstance(data.get(key, []), list):
                raise ProjectError(f"Project {key} must be a JSON list.")
        return cls(
            data["id"],
            data["name"],
            tuple(Scene.from_dict(s) for s in data["scenes"]),
            json_copy(
                {
                    k: v
                    for k, v in data.items()
                    if k
                    not in (
                        "id",
                        "name",
                        "scenes",
                        "settings",
                        "assets",
                        "asset_references",
                        "extensions",
                    )
                }
            ),
            settings=ProjectSettings.from_dict(data.get("settings", {})),
            assets=tuple(Asset.from_dict(v) for v in data.get("assets", [])),
            asset_references=tuple(
                AssetReference.from_dict(v) for v in data.get("asset_references", [])
            ),
            extensions=tuple(PluginExtension.from_dict(v) for v in data.get("extensions", [])),
        )
