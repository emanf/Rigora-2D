"""Evaluated selection measurements and reversible property-strip authoring commands."""

from dataclasses import dataclass, replace
from typing import Any

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.characters import CharacterService
from rigora.application_services.documents import DocumentService
from rigora.domain.entities import Bone, Camera, Group, SceneObject, Transform
from rigora.domain.geometry import inverse, transform_point
from rigora.domain.project import ProjectError
from rigora.engine.sampling import number
from rigora.engine.state import ScenePose


@dataclass(frozen=True)
class SelectionMetrics:
    """Parent-space pivot position for one node; scene bounds for a multi-node selection."""

    x: float
    y: float
    width: float
    height: float
    rotation: float
    opacity: float
    visible: bool
    depth: int = 0


class SelectionPropertyService(CharacterService):
    """Reuse scene/character commands for numeric edits, flips, appearance and reset."""

    def __init__(self, document: DocumentService) -> None:
        """Cache local extents so repainting a transform does not walk unchanged vertices."""
        super().__init__(document)
        self._bounds: dict[str, tuple[object, tuple[float, float, float, float]]] = {}

    def geometry_bounds(
        self, key: str, points: tuple[tuple[float, float], ...]
    ) -> tuple[float, float, float, float]:
        """Cache immutable local extents by identity without hashing every vertex."""
        cached = self._bounds.get(key)
        if cached is not None and cached[0] is points:
            return cached[1]
        if not points:
            return 0, 0, 0, 0
        left = right = points[0][0]
        top = bottom = points[0][1]
        for x, y in points:
            left, right = min(left, x), max(right, x)
            top, bottom = min(top, y), max(bottom, y)
        result = left, top, right, bottom
        if len(self._bounds) >= 128:
            self._bounds.pop(next(iter(self._bounds)))
        self._bounds[key] = points, result
        return result

    def metrics(self, keys: tuple[str, ...], pose: ScenePose | None = None) -> SelectionMetrics:
        """Measure evaluated artwork without rasterization or changing its saved mesh geometry."""
        pose = pose or self.document.animation.pose
        nodes = [pose.nodes[k] for k in keys if k in pose.nodes]
        if not nodes:
            raise ProjectError("Select an object or bone to edit its properties.")
        single = len(nodes) == 1
        basis = inverse(nodes[0].world_matrix) if single else None
        points = []
        for mesh_id in self.meshes_for(keys):
            mesh = pose.meshes.get(mesh_id)
            if mesh and mesh.object_id and mesh.object_id in pose.nodes:
                matrix = pose.nodes[mesh.object_id].world_matrix
                left, top, right, bottom = self.geometry_bounds(mesh_id, mesh.positions)
                for point in ((left, top), (right, top), (right, bottom), (left, bottom)):
                    world = transform_point(matrix, *point)
                    points.append(transform_point(basis, *world) if basis else world)
        from rigora.engine.cameras import camera_corners

        for camera in self.scene.cameras:
            if camera.id in keys:
                points.extend(
                    transform_point(basis, *p) if basis else p
                    for p in camera_corners(camera, pose, self.scene.settings)
                )
        if not points:
            for node in nodes:
                for point in ((0.0, 0.0), (node.length, 0.0)):
                    world = transform_point(node.world_matrix, *point)
                    points.append(transform_point(basis, *world) if basis else world)
        left, top = (min(p[i] for p in points) for i in (0, 1))
        width, height = (max(p[i] for p in points) - value for i, value in ((0, left), (1, top)))
        node = nodes[0]
        if single:
            width *= abs(node.local.scale_x)
            height *= abs(node.local.scale_y)
        parent = pose.nodes.get(node.parent_id or "")
        opacity = (
            node.opacity / parent.opacity if parent and parent.opacity > 1e-9 else node.opacity
        )
        return SelectionMetrics(
            node.local.x + node.local.pivot_x if single else left,
            node.local.y + node.local.pivot_y if single else top,
            width,
            height,
            node.local.rotation,
            opacity * 100,
            all(n.visible for n in nodes),
            int(self.record(node.id).extra.get("depth", 0)),
        )

    def appearance(
        self, keys: tuple[str, ...], *, opacity: float | None = None, visible: bool | None = None
    ) -> None:
        """Set opacity/visibility, recording existing channels or explicit Auto key edits."""
        if opacity is not None and not 0 <= number(opacity) <= 100:
            raise ProjectError("Opacity must be between 0 and 100 percent.")
        with self.document.command_group("Edit selection appearance"):
            for key in keys:
                record = self.record(key)
                if not isinstance(record, (SceneObject, Group, Bone)) or self.locked(key):
                    raise ProjectError("Choose unlocked objects or bones.")
                editor = AnimationEditingService(self.document)
                animated = (
                    {t.property_path for t in editor.timeline.tracks if t.owner_id == key}
                    if editor.timeline
                    else set()
                )
                values = {}
                if opacity is not None:
                    values["opacity"] = opacity / 100
                if visible is not None:
                    values["visibility"] = float(visible)
                keyed = {
                    (key, path): value
                    for path, value in values.items()
                    if self.auto_key or path in animated
                }
                if keyed:
                    editor.auto_key_values(keyed, self.document.animation.pose.frame)
                if "opacity" in values and (key, "opacity") not in keyed:
                    record = replace(record, extra={**record.extra, "opacity": values["opacity"]})
                    self.update_records({key: record}, "Set opacity")
                if "visibility" in values and (key, "visibility") not in keyed:
                    self.flags((key,), visible=bool(visible))

    def edit(self, keys: tuple[str, ...], field: str, value: float, *, ratio: bool = True) -> None:
        """Edit a measured component; dimensions stay independent of a single node's rotation."""
        value = number(value)
        state = self.metrics(keys)
        cx = state.x + state.width / 2 if len(keys) > 1 else None
        cy = state.y + state.height / 2 if len(keys) > 1 else None
        if field == "depth":
            if not value.is_integer():
                raise ProjectError("Depth (Z) must be a whole number.")
            self.set_depth(keys, int(value))
        elif field == "opacity":
            self.appearance(keys, opacity=value)
        elif field in ("x", "y") and len(keys) == 1:
            node = self.document.animation.pose.nodes[keys[0]]
            dx = value - state.x if field == "x" else 0.0
            dy = value - state.y if field == "y" else 0.0
            parent = self.document.animation.pose.nodes.get(node.parent_id or "")
            if parent:
                a, b, c, d, _, _ = parent.world_matrix
                dx, dy = a * dx + c * dy, b * dx + d * dy
            self.transform(keys, dx=dx, dy=dy)
        elif field in ("x", "y"):
            self.transform(keys, **{"dx" if field == "x" else "dy": value - getattr(state, field)})
        elif field == "rotation":
            self.transform(keys, rotation=value - state.rotation, center_x=cx, center_y=cy)
        elif field in ("width", "height"):
            previous = getattr(state, field)
            if previous <= 1e-8 or value <= 0:
                raise ProjectError(
                    "Choose artwork with a nonzero size and enter a positive dimension."
                )
            factor = value / previous
            self.transform(
                keys,
                scale_x=factor if ratio or field == "width" else 1,
                scale_y=factor if ratio or field == "height" else 1,
                center_x=cx,
                center_y=cy,
            )
        else:
            raise ProjectError("Unsupported selection property.")

    def reset(self, keys: tuple[str, ...]) -> None:
        """Restore rest dimensions/appearance and center selected nodes in the camera in one undo.

        Part placements inside groups/characters are preserved. A selected bone retains its base
        joint pivot. Auto key records the reset at the playhead instead of deleting motion data.
        """
        cameras = tuple(key for key in keys if isinstance(self.record(key), Camera))
        if cameras:
            from rigora.engine.cameras import camera_size

            with self.document.command_group("Reset selection"):
                others = tuple(key for key in keys if key not in cameras)
                if others:
                    self.reset(others)
                for key in cameras:
                    record = self.record(key)
                    assert isinstance(record, Camera)
                    if self.locked(key):
                        raise ProjectError("Unlock the camera before resetting its transform.")
                    width, height = camera_size(record, self.scene.settings)
                    transform = Transform(pivot_x=width / 2, pivot_y=height / 2)
                    if self.auto_key or self.records_transforms((key,)):
                        AnimationEditingService(self.document).auto_key_values(
                            {
                                (key, f"transform.{path}"): getattr(transform, path)
                                for path in (
                                    "x",
                                    "y",
                                    "rotation",
                                    "scale_x",
                                    "scale_y",
                                    "pivot_x",
                                    "pivot_y",
                                )
                            },
                            self.document.animation.pose.frame,
                        )
                    else:
                        self.update_records(
                            {key: replace(record, transform=transform)}, "Reset camera transform"
                        )
            return
        pose = self.document.animation.pose
        if self.records_transforms(keys):
            self.auto_key = True
        targets = tuple(
            k
            for k in keys
            if k in pose.nodes and not self._has_ancestor(k, set(keys), self.records())
        )
        if not targets:
            raise ProjectError("Select an object to reset.")
        with self.document.command_group("Reset selection"):
            self.set_depth(
                tuple(k for k in targets if isinstance(self.record(k), (Group, SceneObject))), 0
            )
            if len(targets) > 1:
                primary = pose.nodes[targets[0]]
                before = self.metrics(targets)
                self.transform(
                    targets,
                    rotation=-before.rotation,
                    scale_x=1 / primary.local.scale_x if abs(primary.local.scale_x) > 1e-8 else 1,
                    scale_y=1 / primary.local.scale_y if abs(primary.local.scale_y) > 1e-8 else 1,
                    center_x=before.x + before.width / 2,
                    center_y=before.y + before.height / 2,
                )
                current = self.metrics(targets)
                self.transform(
                    targets,
                    dx=self.scene.settings.width / 2 - current.x - current.width / 2,
                    dy=self.scene.settings.height / 2 - current.y - current.height / 2,
                )
                self.appearance(keys, opacity=100, visible=True)
                return
            for key in targets:
                record = self.record(key)
                if not isinstance(record, (SceneObject, Group, Bone)) or self.locked(key):
                    raise ProjectError("Choose unlocked objects or bones to reset.")
                node = pose.nodes[key]
                points: list[tuple[float, float]] = []
                for mesh_id in self.meshes_for((key,)):
                    mesh = self.mesh(mesh_id)
                    matrix = (
                        pose.nodes[mesh.object_id].world_matrix
                        if mesh.object_id
                        else node.world_matrix
                    )
                    points.extend(
                        transform_point(
                            inverse(node.world_matrix), *transform_point(matrix, v.x, v.y)
                        )
                        for v in mesh.vertices
                    )
                px, py = record.transform.pivot_x, record.transform.pivot_y
                if points and not isinstance(record, Bone):
                    px, py = (
                        (min(p[i] for p in points) + max(p[i] for p in points)) / 2 for i in (0, 1)
                    )
                cx, cy = self.scene.settings.width / 2, self.scene.settings.height / 2
                if node.parent_id and node.parent_id in pose.nodes:
                    cx, cy = transform_point(
                        inverse(pose.nodes[node.parent_id].world_matrix), cx, cy
                    )
                values: dict[str, Any] = {
                    "x": cx - px,
                    "y": cy - py,
                    "rotation": 0.0,
                    "scale_x": 1.0,
                    "scale_y": 1.0,
                    "pivot_x": px,
                    "pivot_y": py,
                }
                if self.auto_key:
                    AnimationEditingService(self.document).auto_key_values(
                        {(key, f"transform.{p}"): v for p, v in values.items()}, pose.frame
                    )
                else:
                    self.update_records(
                        {
                            key: replace(
                                record,
                                transform=replace(record.transform, **values),
                                extra={**record.extra, "pivot_edited": True},
                            )
                        },
                        "Reset object transform",
                    )
            self.appearance(keys, opacity=100, visible=True)
