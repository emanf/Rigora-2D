"""Human-readable scalar channel descriptions shared by timeline clients and plugin metadata."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from rigora.domain.entities import Constraint, Deformer, Entity, Vertex


@dataclass(frozen=True)
class AnimationChannel:
    """One real engine-supported scalar property with its owner, display group and base value."""

    owner: Entity
    path: str
    group: str
    label: str
    base: float

    @property
    def key(self) -> tuple[str, str]:
        """Identify a channel independently of editable labels and display grouping."""
        return self.owner.id, self.path

    @property
    def lane(self) -> str:
        """Name one logical editing lane while retaining canonical scalar channels."""
        if self.path.startswith("transform."):
            return "Transform"
        if self.path == "visibility":
            return "Visible"
        if self.path.startswith("spring."):
            return "Spring"
        if self.path in ("motion.fk", "motion.spring_baked"):
            return "Motion"
        if isinstance(self.owner, Constraint) and self.owner.kind == "foot_contact":
            return "Foot contact"
        if isinstance(self.owner, Constraint) and self.owner.kind == "motion_path":
            return "Path"
        if isinstance(self.owner, Constraint) and self.owner.kind == "shot_transition":
            return "Transition"
        if isinstance(self.owner, Deformer):
            if self.owner.kind == "appearance":
                if self.path.startswith(("parameters.palette.", "parameters.tint.")):
                    return "Color"
                if self.path == "parameters.stroke_width":
                    return "Outline"
            elif self.owner.kind in (
                "ffd",
                "lattice",
                "pin",
                "bend",
                "bulge",
                "twist",
                "squash_stretch",
                "transform",
                "vertex_offset",
                "mesh_sculpt",
                "skinning",
            ):
                return "Deformation"
        if self.group in ("Control points", "Vertex position"):
            return self.group
        return self.group if self.group in ("Opacity", "Bone length") else self.label


def describe_channel(
    owner: Entity, path: str, base: float, metadata: Mapping[str, Any]
) -> AnimationChannel:
    """Describe canonical paths, allowing a deformer plugin to label its existing numeric leaves."""
    groups = {
        "transform.x": ("Position", "X"),
        "transform.y": ("Position", "Y"),
        "transform.rotation": ("Rotation", "Angle"),
        "transform.scale_x": ("Scale", "X"),
        "transform.scale_y": ("Scale", "Y"),
        "transform.pivot_x": ("Pivot", "X"),
        "transform.pivot_y": ("Pivot", "Y"),
        "visibility": ("Visibility", "Visible"),
        "camera.active": ("Camera", "Active camera"),
        "object.view": ("View", "View"),
        "object.attachment": ("Attachment", "Attachment"),
        "opacity": ("Opacity", "Opacity"),
        "length": ("Bone length", "Length"),
        "spring.enabled": ("Spring", "Group enabled"),
        "spring.master": ("Spring", "Master enabled"),
        "motion.fk": ("Motion", "FK pose"),
        "motion.spring_baked": ("Motion", "Baked secondary pose"),
    }
    group, label = groups.get(
        path, ("Parameters", path.removeprefix("parameters.").replace("_", " "))
    )
    if isinstance(owner, Vertex):
        group, label = "Vertex position", path.upper()
    if path.startswith("parameters.controls."):
        parts = path.split(".")
        if len(parts) == 4 and parts[2].isdigit() and parts[3] in ("0", "1"):
            group, label = (
                "Control points",
                f"Point {int(parts[2]) + 1} · {'X' if parts[3] == '0' else 'Y'}",
            )
    if isinstance(owner, Deformer):
        hints = metadata.get(owner.kind, {})
        hint = hints.get(path, {}) if isinstance(hints, Mapping) else {}
        if isinstance(hint, Mapping):
            for key in ("group", "label"):
                value = hint.get(key)
                if isinstance(value, str) and value.strip() and len(value) <= 100:
                    if key == "group":
                        group = value
                    else:
                        label = value
    return AnimationChannel(owner, path, group, label, base)
