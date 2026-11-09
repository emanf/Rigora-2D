"""Typed, immutable authoring records. These describe data, not an animation engine."""

import math
import types
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import MISSING, dataclass, field, fields, is_dataclass
from functools import cache
from threading import RLock
from types import MappingProxyType
from typing import Any, Literal, TypeVar, cast, get_args, get_origin, get_type_hints
from uuid import uuid4

from rigora.domain.geometry import Matrix, affine
from rigora.domain.validation import (
    ProjectError,
    frozen_extra,
    identifier,
    json_copy,
    portable_relative_path,
    text,
)

R = TypeVar("R", bound="Record")


@cache
def _record_hints(kind: type) -> dict[str, Any]:
    """Resolve a record's fixed schema once, independently of its changing field values."""
    return get_type_hints(kind)


def _encode(value: Any) -> Any:
    """Convert immutable records and containers to ordinary JSON-compatible values."""
    if isinstance(value, Record):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {key: _encode(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_encode(item) for item in value]
    return value


def _convert(hint: Any, value: Any) -> Any:
    """Validate a typed field and normalize its nested records and immutable containers."""
    origin, args = get_origin(hint), get_args(hint)
    if hint is Any:
        return json_copy(value)
    if origin is types.UnionType:
        for option in args:
            try:
                return _convert(option, value)
            except ProjectError:
                pass
        raise ProjectError("Value does not match its optional record type.")
    if hint is type(None):
        if value is not None:
            raise ProjectError("Expected null.")
        return None
    if origin is Literal:
        if value not in args or type(value) is not type(args[0]):
            raise ProjectError(f"Expected one of {args}.")
        return value
    if origin is tuple:
        if not isinstance(value, (list, tuple)) or len(value) > 100_000:
            raise ProjectError("Expected a bounded list of values.")
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(_convert(args[0], item) for item in value)
        if len(value) != len(args):
            raise ProjectError(f"Expected exactly {len(args)} components.")
        return tuple(_convert(kind, item) for kind, item in zip(args, value, strict=True))
    if origin is Mapping:
        return frozen_extra(value)
    if isinstance(hint, type) and issubclass(hint, Record):
        return value if isinstance(value, hint) else hint.from_dict(value)
    if hint is float:
        if type(value) not in (float, int):
            raise ProjectError("Numeric properties must be finite numbers.")
        try:
            number = float(value)
        except OverflowError as error:
            raise ProjectError("Numeric properties exceed the supported finite range.") from error
        if not math.isfinite(number):
            raise ProjectError("Numeric properties must be finite numbers.")
        return number
    if hint in (str, int, bool):
        if type(value) is not hint:
            raise ProjectError(f"Expected {hint.__name__}.")
        if hint is str:
            try:
                value.encode("utf-8")
            except UnicodeError as error:
                raise ProjectError("Invalid Unicode.") from error
        return value
    raise ProjectError(f"Unsupported record field type: {hint}")


@dataclass(frozen=True, slots=True, kw_only=True)
class Record:
    """Base codec that validates annotated fields and preserves optional extension data."""

    def __post_init__(self) -> None:
        """Normalize every declared field and report validation errors with its record path."""
        hints = _record_hints(cast(type, type(self)))
        for item in fields(self):
            try:
                value = _convert(hints[item.name], getattr(self, item.name))
            except ProjectError as error:
                raise ProjectError(f"{type(self).__name__}.{item.name}: {error}") from error
            object.__setattr__(self, item.name, value)

    def to_dict(self) -> dict[str, Any]:
        """Return mutable JSON data while retaining unknown optional fields."""
        result = {
            item.name: _encode(getattr(self, item.name))
            for item in fields(self)
            if item.name != "extra"
        }
        return {**_encode(getattr(self, "extra", {})), **result}

    @classmethod
    def from_dict(cls: type[R], value: Any) -> R:
        """Construct a validated record from JSON without inventing persistent identities."""
        if not isinstance(value, dict):
            raise ProjectError(f"{cls.__name__} must be a JSON object.")
        if issubclass(cls, Entity) and "id" not in value:
            raise ProjectError(f"{cls.__name__} is missing its persistent id.")
        known = {item.name: item for item in fields(cls) if item.name != "extra"}
        for name, item in known.items():
            if name not in value and item.default is MISSING and item.default_factory is MISSING:
                raise ProjectError(f"{cls.__name__} is missing {name}.")
        kwargs = {name: value[name] for name in known if name in value}
        if any(item.name == "extra" for item in fields(cls)):
            kwargs["extra"] = {name: val for name, val in value.items() if name not in known}
        elif set(value) - set(known):
            raise ProjectError(f"Unknown fields in {cls.__name__}.")
        return cls(**kwargs)


@dataclass(frozen=True, slots=True, kw_only=True)
class Entity(Record):
    """Named persistent record with a UUID and inert, preserved extension fields."""

    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = "Untitled"
    extra: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        """Validate field types, stable identity, display name, and reference UUID syntax."""
        Record.__post_init__(self)
        identifier(self.id)
        text(self.name, "Entity name")
        for item in fields(self):
            value = getattr(self, item.name)
            if item.name.endswith("_id") and item.name != "plugin_id" and value is not None:
                identifier(value)
            if item.name.endswith("_ids"):
                for reference in value:
                    identifier(reference)


@dataclass(frozen=True, slots=True, kw_only=True)
class Transform(Record):
    """Local affine transform in pixels and degrees around a local pivot."""

    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0
    pivot_x: float = 0.0
    pivot_y: float = 0.0
    extra: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def matrix(self) -> Matrix:
        """Return the shared affine composition for translation, pivot, rotation and scale."""
        return affine(
            self.x, self.y, self.rotation, self.scale_x, self.scale_y, self.pivot_x, self.pivot_y
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectSettings(Record):
    """Project-wide coordinate, unit, time, and color conventions."""

    units: Literal["pixels"] = "pixels"
    coordinate_system: Literal["top-left-x-right-y-down"] = "top-left-x-right-y-down"
    time_unit: Literal["frames"] = "frames"
    color_profile: Literal["srgb"] = "srgb"
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True, kw_only=True)
class Layer(Entity):
    """Ordered visibility and locking metadata for scene organization."""

    visible: bool = True
    locked: bool = False
    order: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class Group(Entity):
    """Transform parent that organizes objects and other groups within one scene."""

    parent_id: str | None = None
    layer_id: str | None = None
    transform: Transform = field(default_factory=Transform)


@dataclass(frozen=True, slots=True, kw_only=True)
class Camera(Group):
    """Orthographic scene camera; its affine frame maps output pixels into world space.

    Scaling the frame zooms the view out. Cameras own no artwork and cannot be
    used as artwork parents. The image source is a normal packaged project asset.
    """

    width: float = 1920.0
    height: float = 1080.0
    match_scene: bool = True
    active: bool = False
    enabled: bool = True
    asset_id: str | None = None
    background_mode: Literal["transparent", "color", "image"] = "transparent"
    background_color: str = "#000000"
    background_fit: Literal["cover", "contain", "stretch"] = "cover"
    background_opacity: float = 1.0

    def __post_init__(self) -> None:
        """Reject invalid frames, singular transforms and malformed background colors."""
        Entity.__post_init__(self)
        if not 1 <= self.width <= 16384 or not 1 <= self.height <= 16384:
            raise ProjectError("Camera dimensions must be between 1 and 16384 pixels.")
        if abs(self.transform.scale_x) < 1e-6 or abs(self.transform.scale_y) < 1e-6:
            raise ProjectError("Camera scale must be nonzero.")
        if not 0 <= self.background_opacity <= 1:
            raise ProjectError("Camera background opacity must be between zero and one.")
        color = self.background_color
        if len(color) not in (7, 9) or not color.startswith("#"):
            raise ProjectError("Camera color must use #RRGGBB or #RRGGBBAA.")
        if any(c not in "0123456789abcdefABCDEF" for c in color[1:]):
            raise ProjectError("Camera color contains invalid hexadecimal digits.")


@dataclass(frozen=True, slots=True, kw_only=True)
class SceneObject(Entity):
    """Renderable-object description referencing an optional source asset and parent."""

    parent_id: str | None = None
    layer_id: str | None = None
    asset_id: str | None = None
    transform: Transform = field(default_factory=Transform)
    visible: bool = True


@dataclass(frozen=True, slots=True, kw_only=True)
class Asset(Entity):
    """Opaque source descriptor with a relative location and optional integrity digest."""

    kind: Literal["raster", "vector", "audio", "sequence"] = "raster"
    source: str
    storage: Literal["embedded", "external"] = "external"
    media_type: str = "application/octet-stream"
    sha256: str | None = None

    def __post_init__(self) -> None:
        """Validate portable source paths, storage policy, and digest syntax."""
        Entity.__post_init__(self)
        portable_relative_path(self.source)
        if self.storage == "embedded" and not self.source.startswith("assets/"):
            raise ProjectError("Embedded assets must live under assets/ in the package.")
        if self.sha256 is not None and (
            len(self.sha256) != 64 or any(c not in "0123456789abcdef" for c in self.sha256)
        ):
            raise ProjectError("Asset sha256 must be a lowercase hexadecimal SHA-256 digest.")


@dataclass(frozen=True, slots=True, kw_only=True)
class AssetReference(Entity):
    """Stable indirection to a project-owned source asset."""

    asset_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Bone(Entity):
    """Local rest transform and length in an acyclic skeleton hierarchy."""

    parent_id: str | None = None
    length: float = 100.0
    transform: Transform = field(default_factory=Transform)
    visible: bool = True
    locked: bool = False
    color: str = "#bcbcbc"
    group: str = "Default"

    def __post_init__(self) -> None:
        """Validate the bone record and reject negative rest lengths."""
        Entity.__post_init__(self)
        if self.length < 0:
            raise ProjectError("Bone length cannot be negative.")
        text(self.group, "Bone group")
        if (
            len(self.color) != 7
            or self.color[0] != "#"
            or any(value not in "0123456789abcdefABCDEF" for value in self.color[1:])
        ):
            raise ProjectError("Bone color must be a #RRGGBB hexadecimal value.")


@dataclass(frozen=True, slots=True, kw_only=True)
class Skeleton(Entity):
    """Owner of a stable collection of bones with scene-validated parent links."""

    bones: tuple[Bone, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class Character(Entity):
    """Instance linking one skeleton to scene objects and deformable meshes."""

    skeleton_id: str
    object_ids: tuple[str, ...] = ()
    mesh_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class Vertex(Entity):
    """Stable mesh vertex with position, UV coordinates, and normalized bone weights."""

    x: float
    y: float
    uv: tuple[float, float] = (0.0, 0.0)
    weights: Mapping[str, Any] = field(default_factory=dict)
    pinned: bool = False
    protected: bool = False

    def __post_init__(self) -> None:
        """Validate finite vertex coordinates and bone weights that sum to one."""
        Entity.__post_init__(self)
        for bone, weight in self.weights.items():
            identifier(bone)
            number = _convert(float, weight)
            if not 0 <= number <= 1:
                raise ProjectError("Skin weights must be from zero to one.")
        if self.weights and not math.isclose(sum(self.weights.values()), 1.0, abs_tol=1e-6):
            raise ProjectError("Skin weights must sum to one.")


@dataclass(frozen=True, slots=True, kw_only=True)
class Mesh(Entity):
    """Indexed triangle geometry with stable vertices and an optional source asset."""

    asset_id: str | None = None
    object_id: str | None = None
    vertices: tuple[Vertex, ...] = ()
    triangles: tuple[tuple[str, str, str], ...] = ()

    def __post_init__(self) -> None:
        """Reject duplicate vertices, missing triangle references, and zero-area faces."""
        Entity.__post_init__(self)
        vertices = {v.id: v for v in self.vertices}
        if len(vertices) != len(self.vertices):
            raise ProjectError("Mesh vertex IDs must be unique.")
        faces: set[tuple[str, ...]] = set()
        edges: dict[tuple[str, ...], int] = {}
        for triangle in self.triangles:
            key = tuple(sorted(triangle))
            if key in faces:
                raise ProjectError("Mesh contains duplicate triangles.")
            faces.add(key)
            for i in range(3):
                edge = tuple(sorted((triangle[i], triangle[(i + 1) % 3])))
                edges[edge] = edges.get(edge, 0) + 1
                if edges[edge] > 2:
                    raise ProjectError("Mesh contains a nonmanifold edge.")
            if len(set(triangle)) != 3 or any(v not in vertices for v in triangle):
                raise ProjectError("Mesh triangle references are invalid.")
            a, b, c = (vertices[key] for key in triangle)
            if abs((b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)) < 1e-12:
                raise ProjectError("Mesh contains a degenerate triangle.")


@dataclass(frozen=True, slots=True, kw_only=True)
class Slot(Entity):
    """Ordered attachment switch owned by a scene object or skeleton bone."""

    owner_id: str
    attachment_ids: tuple[str, ...] = ()
    active_attachment_id: str | None = None
    draw_order: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class Attachment(Entity):
    """Slot content referencing a source asset or mesh with a local transform."""

    slot_id: str
    asset_id: str | None = None
    mesh_id: str | None = None
    transform: Transform = field(default_factory=Transform)


@dataclass(frozen=True, slots=True, kw_only=True)
class Keyframe(Entity):
    """Frame-time value and interpolation metadata stored without evaluating animation."""

    frame: float
    value: Any
    interpolation: Literal["step", "linear", "bezier"] = "linear"
    tangent_in: tuple[float, float] | None = None
    tangent_out: tuple[float, float] | None = None

    def __post_init__(self) -> None:
        """Reject negative times and freeze arbitrary finite JSON key values."""
        Entity.__post_init__(self)
        if self.frame < 0:
            raise ProjectError("Keyframe time cannot be negative.")
        if isinstance(self.value, (dict, list)):
            object.__setattr__(self, "value", frozen_extra({"value": self.value})["value"])


@dataclass(frozen=True, slots=True, kw_only=True)
class Track(Entity):
    """Ordered property keys with playback enable, edit locking and normalized blend influence."""

    owner_id: str
    property_path: str
    keyframes: tuple[Keyframe, ...] = ()
    blend_mode: Literal["override", "additive"] = "override"
    weight: float = 1.0
    locked: bool = False
    visible: bool = True

    @property
    def evaluation_enabled(self) -> bool:
        """Combine this lane's eye state with its linked source lane's enable state."""
        return self.visible and bool(self.extra.get("source_visible", True))

    @property
    def editing_locked(self) -> bool:
        """Expose the interval lock separately from protected linked source keys."""
        window = self.extra.get("motion_window")
        return bool(window.get("locked", False)) if window else self.locked

    def __post_init__(self) -> None:
        """Validate the property path, increasing unique key times, and blend weight."""
        Entity.__post_init__(self)
        text(self.property_path, "Animated property path")
        frames = [key.frame for key in self.keyframes]
        if frames != sorted(set(frames)) or not 0 <= self.weight <= 1:
            raise ProjectError("Track keys must have unique increasing times and weight 0–1.")


@dataclass(frozen=True, slots=True, kw_only=True)
class Marker(Entity):
    """Named timeline frame with a persistent animator annotation."""

    frame: float
    annotation: str = ""

    def __post_init__(self) -> None:
        """Require a nonnegative finite frame for navigation and clip exchange."""
        Entity.__post_init__(self)
        if self.frame < 0:
            raise ProjectError("Marker time cannot be negative.")


@dataclass(frozen=True, slots=True, kw_only=True)
class Timeline(Entity):
    """Named collection of property tracks within a scene."""

    tracks: tuple[Track, ...] = ()
    markers: tuple[Marker, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class AnimationClip(Entity):
    """Inclusive playback range referencing a scene timeline."""

    timeline_id: str
    in_frame: float = 0.0
    out_frame: float = 119.0
    loop: bool = False
    annotation: str = ""

    def __post_init__(self) -> None:
        """Validate clip identity, timeline reference syntax, and ordered frame range."""
        Entity.__post_init__(self)
        if not 0 <= self.in_frame <= self.out_frame:
            raise ProjectError("Animation clip range is invalid.")


@dataclass(frozen=True, slots=True, kw_only=True)
class Deformer(Entity):
    """Serializable ordered deformation contract targeting a scene object, mesh, or bone."""

    owner_id: str
    kind: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    enabled: bool = True
    order: int = 0

    def __post_init__(self) -> None:
        """Validate the owner reference and nonempty deformation type identifier."""
        Entity.__post_init__(self)
        text(self.kind, "Extension type")


@dataclass(frozen=True, slots=True, kw_only=True)
class Constraint(Deformer):
    """Deformation-style rule with an optional target in the same scene."""

    target_id: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class PluginExtension(Entity):
    """Versioned plugin-owned JSON payload that is never imported or executed on load."""

    plugin_id: str
    version: int = 1
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate plugin identity and positive payload version."""
        Entity.__post_init__(self)
        text(self.plugin_id, "Plugin ID")
        if self.version < 1:
            raise ProjectError("Plugin data version must be positive.")


@cache
def _entity_fields(kind: type) -> tuple[str, ...]:
    """Index entity-bearing fields, excluding numeric topology and opaque metadata."""

    def contains(hint: Any) -> bool:
        """Follow typed record containers; scalar tuples cannot own persistent entities."""
        if hint is Any:
            return True
        if get_origin(hint) in (tuple, types.UnionType):
            return any(contains(part) for part in get_args(hint) if part is not Ellipsis)
        if isinstance(hint, type) and is_dataclass(hint):
            return issubclass(hint, Entity) or bool(_entity_fields(hint))
        return False

    hints = _record_hints(kind)
    return tuple(f.name for f in fields(kind) if f.name != "extra" and contains(hints[f.name]))


_timeline_records: OrderedDict[int, tuple[Timeline, tuple[Entity, ...]]] = OrderedDict()
_timeline_records_lock = RLock()
_timeline_record_count = 0


def nested_records(value: Any) -> tuple[Entity, ...]:
    """Collect entities in schema order, retaining duplicate occurrences for validation.

    Dense immutable timelines reuse their owned-record index across scene transforms.
    A locked bounded cache shares only immutable records; reference and uniqueness
    checks still run against each current Project revision.
    """
    result: list[Entity] = []

    def visit(item: Any) -> None:
        """Append owned records while retaining duplicate occurrences for ID validation."""
        global _timeline_record_count
        timeline = isinstance(item, Timeline)
        if timeline:
            with _timeline_records_lock:
                cached = _timeline_records.get(id(item))
                if cached is not None and cached[0] is item:
                    _timeline_records.move_to_end(id(item))
                    result.extend(cached[1])
                    return
        start = len(result)
        if isinstance(item, Entity):
            result.append(item)
        if is_dataclass(item) and not isinstance(item, type):
            for name in _entity_fields(type(item)):
                visit(getattr(item, name))
        elif isinstance(item, tuple):
            for child in item:
                visit(child)
        if timeline:
            records = tuple(result[start:])
            if len(records) <= 200_000:
                with _timeline_records_lock:
                    previous = _timeline_records.pop(id(item), None)
                    if previous is not None:
                        _timeline_record_count -= len(previous[1])
                    _timeline_records[id(item)] = item, records
                    _timeline_record_count += len(records)
                    while len(_timeline_records) > 64 or _timeline_record_count > 200_000:
                        _timeline_record_count -= len(_timeline_records.popitem(last=False)[1][1])

    visit(value)
    return tuple(result)


ENTITY_COLLECTIONS: Mapping[str, type[Entity]] = MappingProxyType(
    {
        "layers": Layer,
        "groups": Group,
        "cameras": Camera,
        "objects": SceneObject,
        "characters": Character,
        "skeletons": Skeleton,
        "meshes": Mesh,
        "slots": Slot,
        "attachments": Attachment,
        "clips": AnimationClip,
        "timelines": Timeline,
        "deformers": Deformer,
        "constraints": Constraint,
        "extensions": PluginExtension,
    }
)
