"""Portable rigid Scene attachment states and owner-local reusable grip points."""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from rigora.domain.geometry import IDENTITY, Matrix, affine
from rigora.domain.validation import ProjectError

ATTACHMENT_PATH = "object.attachment"


def matrix(value: Any) -> Matrix:
    """Accept a bounded finite, invertible affine transform from inert project metadata."""
    if (
        not isinstance(value, (tuple, list))
        or len(value) != 6
        or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1e12 for v in value)
        or abs(value[0] * value[3] - value[1] * value[2]) < 1e-12
    ):
        raise ProjectError("Attachment transforms need six finite values and a nonzero scale.")
    return cast(Matrix, tuple(float(v) for v in value))


@dataclass(frozen=True, slots=True)
class AttachmentState:
    """One held following state; a missing target means independent Scene space."""

    target_id: str | None = None
    point: str = ""
    source_point: str = ""
    offset: Matrix = IDENTITY
    bind_matrix: Matrix = IDENTITY
    inherit_rotation: bool = True
    inherit_scale: bool = True

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AttachmentState":
        """Validate only supported fields so malformed states cannot silently change meaning."""
        if not isinstance(value, Mapping):
            raise ProjectError("Attachment state must be an object with a target and offsets.")
        if set(value) - {
            "target_id",
            "point",
            "source_point",
            "offset",
            "bind_matrix",
            "inherit_rotation",
            "inherit_scale",
        }:
            raise ProjectError("Unsupported attachment settings.")
        target = value.get("target_id")
        if target is not None and (not isinstance(target, str) or not target or len(target) > 128):
            raise ProjectError("Choose an existing attachment target or World.")
        for key in ("point", "source_point"):
            if not isinstance(value.get(key, ""), str) or len(value.get(key, "")) > 128:
                raise ProjectError("Choose a valid attachment point.")
        for key in ("inherit_rotation", "inherit_scale"):
            if type(value.get(key, True)) is not bool:
                raise ProjectError("Attachment inheritance options must be enabled or disabled.")
        return cls(
            target,
            value.get("point", ""),
            value.get("source_point", ""),
            matrix(value.get("offset", IDENTITY)),
            matrix(value.get("bind_matrix", IDENTITY)),
            value.get("inherit_rotation", True),
            value.get("inherit_scale", True),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return fresh JSON-safe metadata shared by constraints, keys and API clients."""
        return {
            "target_id": self.target_id,
            "point": self.point,
            "source_point": self.source_point,
            "offset": list(self.offset),
            "inherit_rotation": self.inherit_rotation,
            "inherit_scale": self.inherit_scale,
            "bind_matrix": list(self.bind_matrix),
        }


def point_matrix(record: Any, identity: str = "", view: str = "") -> Matrix:
    """Resolve an implicit origin/tip/grip or a named point local to its owning transform."""
    if not identity:
        return IDENTITY
    if identity in ("@tip", "@grip") and hasattr(record, "length"):
        return affine(record.length * (0.5 if identity == "@grip" else 1), 0, 0, 1, 1, 0, 0)
    for point in record.extra.get("attachment_points", ()):
        if point.get("id") == identity:
            return matrix(point.get("views", {}).get(view, point["matrix"]))
    raise ProjectError("This attachment point is missing. Choose another point or Object origin.")


def points(record: Any) -> tuple[tuple[str, str], ...]:
    """Offer readable built-in points and persisted points without exposing database IDs."""
    result = [("", "Object origin" if not hasattr(record, "length") else "Joint")]
    if hasattr(record, "length") and record.length:
        if record.name.casefold().startswith("hand"):
            result.append(("@grip", "Grip"))
        result.append(("@tip", "Tip"))
    result.extend((p["id"], p["name"]) for p in record.extra.get("attachment_points", ()))
    return tuple(result)


def validate_points(value: Any) -> None:
    """Bound owner-local definitions and preserve their optional per-view registration."""
    if not isinstance(value, (tuple, list)) or len(value) > 128:
        raise ProjectError("An object or bone supports at most 128 attachment points.")
    identities = set()
    for point in value:
        if not isinstance(point, Mapping) or set(point) - {"id", "name", "matrix", "views"}:
            raise ProjectError("Invalid attachment point definition.")
        for field in ("id", "name"):
            if (
                not isinstance(point.get(field), str)
                or not point[field].strip()
                or len(point[field]) > 128
            ):
                raise ProjectError("Attachment points need a name and local identity.")
        if point["id"] in identities or point["id"].startswith("@"):
            raise ProjectError("Attachment point identities must be unique within their owner.")
        identities.add(point["id"])
        matrix(point.get("matrix"))
        views = point.get("views", {})
        if not isinstance(views, Mapping) or len(views) > 6:
            raise ProjectError("Attachment points support up to six view offsets.")
        from rigora.domain.object_views import VIEW_SLOTS

        if any(key not in VIEW_SLOTS for key in views):
            raise ProjectError("Attachment point view offsets need an existing Object view.")
        for item in views.values():
            matrix(item)


def validate_scene(scene: Any, records: Mapping[str, Any]) -> None:
    """Validate portable grip definitions and every held reference before project publication."""
    from rigora.domain.entities import Bone, Camera, Group, SceneObject

    rules = {c.owner_id: c for c in scene.constraints if c.kind == "scene_attachment"}
    if len(rules) != sum(c.kind == "scene_attachment" for c in scene.constraints):
        raise ProjectError("Each Scene object can have only one attachment setup.")

    def check(owner: str, state: AttachmentState) -> None:
        source = records.get(owner)
        if not isinstance(source, (Group, SceneObject)) or isinstance(source, Camera):
            raise ProjectError("Scene attachments need an object as their source.")
        point_matrix(source, state.source_point)
        if state.target_id is not None:
            target = records.get(state.target_id)
            if not isinstance(target, (Bone, Group, SceneObject)) or isinstance(target, Camera):
                raise ProjectError("Scene attachment references a missing object or bone.")
            if state.target_id == owner:
                raise ProjectError("An object cannot attach to itself.")
            point_matrix(target, state.point)
        elif state.point:
            raise ProjectError("An independent object cannot use a target grip.")

    for record in records.values():
        if "attachment_points" in record.extra:
            if not isinstance(record, (Bone, Group, SceneObject)):
                raise ProjectError("Only objects and bones can own attachment points.")
            validate_points(record.extra["attachment_points"])
    for owner, rule in rules.items():
        check(owner, AttachmentState.from_dict({**rule.parameters, "target_id": rule.target_id}))
    for timeline in scene.timelines:
        for track in timeline.tracks:
            if track.property_path != ATTACHMENT_PATH:
                continue
            if track.keyframes and track.owner_id not in rules:
                raise ProjectError("Attachment keys need an attachment setup for their object.")
            for key in track.keyframes:
                if key.interpolation != "step" or "scene_attachment" not in key.extra:
                    raise ProjectError("Attachment keys need a held target state.")
                check(track.owner_id, AttachmentState.from_dict(key.extra["scene_attachment"]))
