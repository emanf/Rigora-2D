"""Render an open scene workspace with a camera border and cursor-anchored navigation."""

import math
import weakref
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from time import perf_counter
from typing import cast

from PySide6.QtCore import QEvent, QLineF, QObject, QPointF, QRectF, QSizeF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QFocusEvent,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
    QTransform,
    QWheelEvent,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QWidget

from rigora.domain.geometry import transform_point
from rigora.domain.project import ProjectError, SceneSettings
from rigora.engine.cameras import active_camera, camera_corners, camera_size
from rigora.engine.chain_pull import selected_roots
from rigora.engine.state import MeshPose, ScenePose
from rigora.presentation import transform_gizmo
from rigora.presentation.artwork import ArtworkCache, draw_mesh, mesh_polygon, triangle_edges
from rigora.presentation.bone_shape import BoneShape
from rigora.presentation.icons import IconProvider
from rigora.presentation.themes import palette_colors, transparency_brush

SELECTED_BONE_COLOR = "#ef5350"
INACTIVE_CAMERA_OPACITY = 0.28


@dataclass(frozen=True)
class _MeshLayer:
    """Device-resolution artwork positioned in zoomed scene space, independent of panning.

    Bounds include the entire mesh; the tile may cover only a window of oversized art.
    Retained tiles belong to the viewport and share its bounded LRU cache.
    """

    signature: tuple[object, ...]
    tile: QPixmap
    origin: QPointF
    bounds: QRectF
    translation: QPointF

    def covers(self, visible: QRectF) -> bool:
        """Whether all currently visible mesh pixels are already present in the tile."""
        return QRectF(self.origin, self.tile.deviceIndependentSize()).contains(
            self.bounds.intersected(visible)
        )


class Viewport(QWidget):
    """Evaluated transform preview with checkerboard, grid and cursor-anchored navigation."""

    zoom_changed = Signal(float)
    pose_changed = Signal()
    bone_selected = Signal(str, bool)
    bone_created = Signal(float, float, float, float)
    bone_dragged = Signal(str, str, float, float)
    bone_drag_started = Signal()
    bone_drag_preview = Signal(str, str, float, float)
    bone_drag_cancelled = Signal()
    bones_selected = Signal(object, bool)
    content_dropped = Signal(str, object)
    content_hovered = Signal(str, object)
    content_left = Signal()
    asset_dropped = Signal(str, str, object)
    asset_hovered = Signal(str, str, object)
    files_dropped = Signal(object, object)

    def __init__(self, parent: QWidget | None = None, *, icons: IconProvider | None = None) -> None:
        """Initialize canvas preferences, the view transform, and navigation gestures."""
        super().__init__(parent)
        self.icons = icons
        self.bone_drag_started.connect(self.capture_snap_modifier)
        self._pointer: QPointF | None = None
        self.scene_cursor: Callable[[QPointF], QCursor | None] | None = None
        self.mesh_cursor: Callable[[QPointF], QCursor | None] | None = None
        self.pin_cursor: Callable[[QPointF], QCursor | None] | None = None
        self.setMinimumSize(160, 160)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setAccessibleName("Scene viewport")
        self.setToolTip("Wheel: zoom · Middle-drag or Space + drag: pan · F: fit canvas · 1: 100%")
        self.settings = SceneSettings()
        self.theme = "dark"
        self.zoom = 0.4
        self.preview_quality = 1.0
        self.camera_guides = "Off"
        self.last_paint_ms = 0.0
        self.raster_hits = self.raster_misses = 0
        self.profile_paint = False
        self.mesh_paint_ms: dict[str, float] = {}
        self.offset = QPointF(0, 0)
        self.grid_visible = True
        self.checker_visible = True
        self.frame_color: str | None = None
        self.preview_background: QImage | None = None
        self.camera_backdrop: tuple[str, QSvgRenderer] | None = None
        self.camera_lens: tuple[str, QSvgRenderer] | None = None
        self.camera_frame_only = False
        self.show_cameras = True
        self.frame_visible = True
        self.has_project = False
        self.scene_hint = "EMPTY SCENE"
        self.node_labels = True
        self.show_bones = True
        self.composer_artwork_only = False
        self.pan_tool = False
        self._space = False
        self._bone_transform: transform_gizmo.Gesture | None = None
        self._drag: QPointF | None = None
        self.pose: ScenePose | None = None
        self.source_pose: ScenePose | None = None
        self.reference_pose: ScenePose | None = None
        self.subdivision_pose: ScenePose | None = None
        self.isolated_ids: frozenset[str] | None = None
        self.drop_pose: ScenePose | None = None
        self.drop_translation = QPointF()
        self.drop_message = ""
        self.mesh_wireframe = False
        self.mesh_editing = False
        self.ghost_poses: tuple[ScenePose, ...] = ()
        self.motion_trails: tuple[tuple[tuple[float, float], ...], ...] = ()
        self.rig_mode = False
        self.rig_tool = "select"
        self.selected_bones: tuple[str, ...] = ()
        self.selected_nodes: tuple[str, ...] = ()
        self.bone_colors: dict[str, str] = {}
        self.spring_colors: dict[str, str] = {}
        self.spring_highlight: set[str] = set()
        self.bone_display_size = 1.0
        self.bone_display_opacity = 1.0
        self.bone_connections = True
        self.locked_bones: set[str] = set()
        self.rig_target = ""
        self.ik_endpoints: set[str] = set()
        self._rig_drag: tuple[str, str, QPointF] | None = None
        self._rig_cursor: QPointF | None = None
        self._draw_origin: QPointF | None = None
        self._draw_position: QPointF | None = None
        self._draw_snap: tuple[str, QPointF] | None = None
        self._draw_parent = ""
        self._rig_press: QPointF | None = None
        self._toggle_bone_on_click = ""
        self._drag_pose: ScenePose | None = None
        self._movement_snap: QPointF | None = None
        self.bone_movement = "chain_move"
        self._selection_box: tuple[QPointF, QPointF] | None = None
        self._selection_extend = False
        self.artwork = ArtworkCache()
        self._artwork_pose: ScenePose | None = None
        self._artwork_view: tuple[object, ...] = ()
        self._artwork_layer: QPixmap | None = None
        self._mesh_layers: OrderedDict[str, _MeshLayer] = OrderedDict()
        self.bone_shape = BoneShape()
        self.mesh_overlay: Callable[[QPainter], None] | None = None
        self.pin_overlay: Callable[[QPainter], None] | None = None
        self.scene_overlay: Callable[[QPainter], None] | None = None
        self.extension_overlay: Callable[[QPainter], None] | None = None
        self.shape_overlay: Callable[[QPainter], None] | None = None
        self.extension_pointer: Callable[[str, float, float, bool], None] | None = None
        self._extension_drag = False

    def set_pose(self, pose: ScenePose | None) -> None:
        """Display the engine's immutable geometry snapshot without changing canvas navigation."""
        if pose is None or self.source_pose is None or pose.scene_id != self.source_pose.scene_id:
            self.mesh_paint_ms.clear()
            self.isolated_ids = None
        if pose is None:
            self._artwork_pose, self._artwork_layer = None, None
            self._mesh_layers.clear()
        self.source_pose = pose
        pose = pose.for_display() if pose else None
        self.pose = (
            replace(
                pose,
                nodes={
                    key: replace(node, visible=node.visible and key in self.isolated_ids)
                    for key, node in pose.nodes.items()
                },
            )
            if pose and self.isolated_ids is not None
            else pose
        )
        self.update()
        self.pose_changed.emit()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Accept internal content identities for validation by the active library adapter."""
        if (
            event.mimeData().hasUrls()
            or event.mimeData().hasFormat("application/x-rigora-project-asset")
            or event.mimeData().hasFormat("application/x-rigora-content")
        ):
            event.acceptProposedAction()
            self.dragMoveEvent(event)
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent | QDragEnterEvent) -> None:
        """Track internal template drags in scene space for non-destructive placement feedback."""
        if event.mimeData().hasFormat("application/x-rigora-project-asset"):
            raw = bytes(event.mimeData().data("application/x-rigora-project-asset").data())
            session = bytes(event.mimeData().data("application/x-rigora-session").data())
            if 0 < len(raw) <= 64 and len(session) <= 64:
                try:
                    self.asset_hovered.emit(raw.decode(), session.decode(), event.position())
                    event.acceptProposedAction()
                    return
                except UnicodeError:
                    pass
            event.ignore()
            return
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        raw = bytes(event.mimeData().data("application/x-rigora-content").data())
        if 0 < len(raw) <= 128:
            try:
                self.content_hovered.emit(raw.decode("utf-8"), event.position())
                event.acceptProposedAction()
                return
            except UnicodeError:
                pass
        event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        """Discard transient placement feedback when a drag leaves this surface."""
        self.content_left.emit()
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        """Forward a bounded installed identity for validation by the active content adapter."""
        self.content_left.emit()
        if event.mimeData().hasUrls():
            paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
            if 0 < len(paths) <= 128:
                self.files_dropped.emit(paths, event.position())
                event.acceptProposedAction()
                return
            event.ignore()
            return
        if event.mimeData().hasFormat("application/x-rigora-project-asset"):
            raw = bytes(event.mimeData().data("application/x-rigora-project-asset").data())
            session = bytes(event.mimeData().data("application/x-rigora-session").data())
            if 0 < len(raw) <= 64 and len(session) <= 64:
                try:
                    self.asset_dropped.emit(raw.decode(), session.decode(), event.position())
                    event.acceptProposedAction()
                    return
                except UnicodeError:
                    pass
            event.ignore()
            return
        raw = bytes(event.mimeData().data("application/x-rigora-content").data())
        if len(raw) <= 128:
            try:
                self.content_dropped.emit(raw.decode("utf-8"), event.position())
                event.acceptProposedAction()
                return
            except UnicodeError:
                pass
        event.ignore()

    def set_scene(self, settings: SceneSettings, *, reset: bool = False) -> None:
        """Display validated canvas settings, optionally fitting the new canvas bounds."""
        self.settings = settings
        self.has_project = True
        if reset:
            self.fit_canvas()
        self.update()

    def scene_point(self, position: QPointF) -> QPointF:
        """Map a viewport position to scene pixels through the inverse view transform."""
        return (position - self.offset) / self.zoom

    def zoom_at(self, factor: float, anchor: QPointF | None = None) -> None:
        """Clamp zoom and retain the same scene point beneath the selected screen anchor."""
        anchor = anchor if anchor is not None else QPointF(self.rect().center())
        scene = self.scene_point(anchor)
        self.zoom = min(8.0, max(0.001, self.zoom * factor))
        self.offset = anchor - scene * self.zoom
        self.zoom_changed.emit(self.zoom)
        if self.rig_mode and self.rig_tool == "draw" and self._draw_position is not None:
            self._update_draw_cursor(self._draw_position, QApplication.keyboardModifiers())
        self.update()

    def fit_canvas(self) -> None:
        """Center the canvas inside the viewport with a navigation margin."""
        self.zoom = min(
            (self.width() - 80) / self.settings.width,
            (self.height() - 80) / self.settings.height,
            1.0,
        )
        self.zoom = max(0.001, self.zoom)
        self.offset = QPointF(
            (self.width() - self.settings.width * self.zoom) / 2,
            (self.height() - self.settings.height * self.zoom) / 2,
        )
        self.zoom_changed.emit(self.zoom)
        if self.rig_mode and self.rig_tool == "draw" and self._draw_position is not None:
            self._update_draw_cursor(self._draw_position, QApplication.keyboardModifiers())
        self.update()

    def paintEvent(self, event: object) -> None:
        """Paint workspace transparency and a camera border without clipping scene geometry."""
        started = perf_counter()
        self.raster_hits = self.raster_misses = 0
        c = palette_colors(self.palette())
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(c["canvas"]))
        if not self.has_project:
            return
        canvas = QRectF(self.offset, self.settings_size())
        painter.save()
        if self.preview_background is not None:
            painter.drawImage(QRectF(self.rect()), self.preview_background)
        elif self.checker_visible:
            painter.fillRect(self.rect(), transparency_brush(self.palette()))
        if self.grid_visible:
            step = 100 * self.zoom
            while step < 24:
                step *= 2
            painter.setPen(QPen(QColor(c["grid"]), 0.5))
            x = self.offset.x() % step
            while x < self.width():
                painter.drawLine(QPointF(x, 0), QPointF(x, self.height()))
                x += step
            y = self.offset.y() % step
            while y < self.height():
                painter.drawLine(QPointF(0, y), QPointF(self.width(), y))
                y += step
        self.draw_camera_layer(painter, self.camera_backdrop)
        if self.camera_frame_only:
            painter.setClipRect(canvas)
        if self.reference_pose is not None:
            painter.save()
            painter.setOpacity(0.35)
            self._draw_pose(painter, c, self.reference_pose, labels=False)
            painter.restore()
        if self.ghost_poses or self.motion_trails:
            for ghost in self.ghost_poses:
                painter.save()
                painter.setOpacity(0.18)
                self._draw_pose(painter, c, ghost, labels=False)
                painter.restore()
            painter.setPen(QPen(QColor(c["text"]), 1, Qt.PenStyle.DotLine))
            for trail in self.motion_trails:
                for first, second in zip(trail, trail[1:], strict=False):
                    painter.drawLine(
                        self.offset + QPointF(*first) * self.zoom,
                        self.offset + QPointF(*second) * self.zoom,
                    )
        self._draw_pose(painter, c, self.subdivision_pose, labels=self.node_labels)
        if self.drop_pose:
            painter.save()
            painter.setOpacity(0.45)
            self._draw_pose(
                painter, c, self.drop_pose, labels=False, translation=self.drop_translation
            )
            painter.restore()
        self.draw_camera_layer(painter, self.camera_lens)
        if self.extension_overlay and self.subdivision_pose is None:
            self.extension_overlay(painter)
        if self.shape_overlay:
            self.shape_overlay(painter)
        if self.mesh_overlay and self.subdivision_pose is None:
            self.mesh_overlay(painter)
        if self.scene_overlay and self.subdivision_pose is None:
            self.scene_overlay(painter)
        if self.pin_overlay and self.subdivision_pose is None:
            self.pin_overlay(painter)
        if self.rig_mode and self.rig_tool == "select" and self.subdivision_pose is None:
            rect = self.bone_transform_bounds()
            if rect:
                hovered = (
                    self._bone_transform.handle
                    if self._bone_transform
                    else transform_gizmo.pick(rect, self._pointer)
                    if self._pointer is not None
                    else None
                )
                transform_gizmo.draw(painter, rect, SELECTED_BONE_COLOR, hovered)
                pivot = self.bone_transform_pivot()
                if pivot:
                    painter.setPen(QPen(QColor(SELECTED_BONE_COLOR), 1.5))
                    painter.drawEllipse(pivot, 5, 5)
                    painter.drawLine(pivot - QPointF(8, 0), pivot + QPointF(8, 0))
                    painter.drawLine(pivot - QPointF(0, 8), pivot + QPointF(0, 8))
                if len(self.selected_bones) == 1 and self.pose:
                    node = self.pose.nodes.get(self.selected_bones[0])
                    if node and self.bone_movement != "pull":
                        tip = (
                            QPointF(*transform_point(node.world_matrix, node.length, 0)) * self.zoom
                            + self.offset
                        )
                        painter.drawEllipse(tip, 7, 7)
        if self.rig_mode and self._rig_drag and self._rig_cursor and self._rig_drag[1] == "draw":
            self._draw_needle(
                painter,
                self._rig_drag[2] * self.zoom + self.offset,
                self._rig_cursor * self.zoom + self.offset,
                SELECTED_BONE_COLOR,
                preview=True,
            )
        painter.restore()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(self.frame_color or c["preview_ink"]), 1))
        if (
            self.frame_visible
            and self.show_cameras
            and self.pose
            and self.pose.cameras
            and self.isolated_ids is None
        ):
            current = active_camera(self.pose)
            painter.save()
            # Draw the output frame last so coincident frames and labels cannot obscure it.
            for camera in sorted(
                self.pose.cameras, key=lambda entry: current is not None and entry.id == current.id
            ):
                if camera.id not in self.pose.nodes or not camera.extra.get("visible", True):
                    continue
                points = QPolygonF(
                    [
                        self.offset + QPointF(*p) * self.zoom
                        for p in camera_corners(camera, self.pose, self.settings)
                    ]
                )
                active = current is not None and current.id == camera.id
                painter.setOpacity(1 if active else INACTIVE_CAMERA_OPACITY)
                painter.setPen(QPen(QColor("#ffffff"), 2 if active else 1))
                painter.drawPolygon(points)
                if active and self.camera_guides != "Off":
                    painter.setOpacity(0.45)
                    painter.setPen(QPen(QColor("#ffffff"), 1))
                    if "Thirds" in self.camera_guides:
                        for amount in (1 / 3, 2 / 3):
                            painter.drawLine(
                                points.at(0) + (points.at(1) - points.at(0)) * amount,
                                points.at(3) + (points.at(2) - points.at(3)) * amount,
                            )
                            painter.drawLine(
                                points.at(0) + (points.at(3) - points.at(0)) * amount,
                                points.at(1) + (points.at(2) - points.at(1)) * amount,
                            )
                    if "safe" in self.camera_guides.lower():
                        painter.drawPolygon(
                            QPolygonF(
                                [
                                    points.at(0)
                                    + (points.at(1) - points.at(0)) * x
                                    + (points.at(3) - points.at(0)) * y
                                    for x, y in ((0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9))
                                ]
                            )
                        )
                    painter.setOpacity(1)
                painter.drawText(
                    points.at(0) + QPointF(4, -7), camera.name + (" · Active" if active else "")
                )
            painter.restore()
        elif self.frame_visible and self.isolated_ids is None:
            painter.drawRect(canvas)
        painter.setPen(QColor(c["muted"]))
        quality_hint = f" · Preview {self.preview_quality:.0%}" if self.preview_quality < 1 else ""
        painter.drawText(18, self.height() - 18, self.scene_hint + quality_hint)
        if self.drop_message:
            painter.drawText(18, 28, self.drop_message)
        if self._movement_snap is not None:
            marker = self._movement_snap * self.zoom + self.offset
            painter.setPen(QPen(QColor(c["text"]), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(marker, 10, 10)
            painter.drawLine(marker - QPointF(14, 0), marker + QPointF(14, 0))
            painter.drawLine(marker - QPointF(0, 14), marker + QPointF(0, 14))
            painter.drawText(marker + QPointF(14, -14), "Joint snap · Alt: free")
        self._draw_joint_cursor(painter, c)
        if self._selection_box:
            painter.setPen(QPen(QColor(c["text"]), 1, Qt.PenStyle.DashLine))
            fill = QColor(c["selected"])
            fill.setAlpha(70)
            painter.setBrush(fill)
            painter.drawRect(QRectF(*self._selection_box).normalized())
        self.last_paint_ms = (perf_counter() - started) * 1000

    def draw_camera_layer(self, painter: QPainter, layer: tuple[str, QSvgRenderer] | None) -> None:
        """Clip a shared background or lens overlay to its evaluated camera frame."""
        if layer and self.pose and self.isolated_ids is None:
            key, renderer = layer
            camera = next((c for c in self.pose.cameras if c.id == key), None)
            if camera and key in self.pose.nodes:
                a, b, cx, d, x, y = self.pose.nodes[key].world_matrix
                painter.save()
                painter.setTransform(
                    QTransform(
                        a * self.zoom,
                        b * self.zoom,
                        cx * self.zoom,
                        d * self.zoom,
                        x * self.zoom + self.offset.x(),
                        y * self.zoom + self.offset.y(),
                    )
                )
                painter.setClipRect(QRectF(0, 0, *camera_size(camera, self.settings)))
                renderer.render(painter, QRectF(0, 0, *camera_size(camera, self.settings)))
                painter.restore()

    def _draw_pose(
        self,
        painter: QPainter,
        colors: dict[str, str],
        pose: ScenePose | None = None,
        *,
        labels: bool = True,
        translation: QPointF | None = None,
    ) -> None:
        """Draw evaluated object axes and bone endpoints as an explicit transform preview."""
        pose = pose or self.pose
        if pose is None:
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        base_opacity = painter.opacity()
        bone_opacity = max(base_opacity, 0.8) if pose is self.drop_pose else base_opacity
        offset = self.offset + (translation if translation is not None else QPointF())
        self._draw_artwork(painter, colors, pose, offset)
        pose = pose.for_display()
        mesh_owners = {mesh.object_id for mesh in pose.meshes.values()}
        # The display toggle also applies on artwork pages and in the main scene.
        # Drawing exposes joints temporarily even when that overlay is hidden.
        bones_visible = self.show_bones or self.rig_mode and self.rig_tool == "draw"
        for key in pose.render_order:
            node = pose.nodes[key]
            if not node.visible or node.kind == "bone" and not bones_visible:
                continue
            painter.setOpacity(base_opacity * node.opacity)
            if (
                key in mesh_owners or key in pose.particles or key in pose.region_owners
            ) and node.kind != "bone":
                continue
            local_points = (
                ((0.0, 0.0), (node.length, 0.0))
                if node.kind == "bone"
                else ((0.0, 0.0), (28.0, 0.0), (0.0, 28.0))
            )
            points = []
            for x, y in local_points:
                world_x, world_y = transform_point(node.world_matrix, x, y)
                points.append(offset + QPointF(world_x * self.zoom, world_y * self.zoom))
            if any(
                not math.isfinite(value) or abs(value) > 1e8
                for point in points
                for value in (point.x(), point.y())
            ):
                continue
            origin = points[0]
            selected = node.id in self.selected_nodes or (
                node.id in self.selected_bones and self.rig_mode
            )
            tone = self.spring_colors.get(node.id, self.bone_colors.get(node.id, colors["text"]))
            if self.theme == "light" and tone == "#bcbcbc":
                tone = colors["text"]
            if selected or node.id in self.spring_highlight:
                tone = SELECTED_BONE_COLOR
            painter.setPen(
                QPen(
                    QColor(tone),
                    2 if selected else 1.5,
                )
            )
            if node.kind == "bone":
                painter.setOpacity(bone_opacity * node.opacity * self.bone_display_opacity)
                self._draw_needle(painter, origin, points[1], tone)
                if selected:
                    painter.drawRect(QRectF(points[1] - QPointF(4, 4), QSizeF(8, 8)))
                    painter.drawLine(origin, origin + QPointF(36, 0))
                    painter.drawLine(origin, origin + QPointF(0, -36))
                    if self.rig_tool == "rotate":
                        pivot = (
                            offset
                            + QPointF(
                                *transform_point(
                                    node.world_matrix, node.local.pivot_x, node.local.pivot_y
                                )
                            )
                            * self.zoom
                        )
                        painter.drawEllipse(pivot, 30, 30)
                        painter.drawLine(pivot - QPointF(5, 0), pivot + QPointF(5, 0))
                        painter.drawLine(pivot - QPointF(0, 5), pivot + QPointF(0, 5))
            else:
                painter.drawLine(origin, points[1])
                painter.drawEllipse(origin, 3, 3)
                painter.setPen(QPen(QColor(colors["muted"]), 1.5))
                painter.drawLine(origin, points[2])
                if self.rig_mode and node.id == self.rig_target:
                    painter.drawEllipse(origin, 9, 9)
            painter.setPen(QColor(SELECTED_BONE_COLOR if selected else colors["text"]))
            if labels:
                painter.drawText(origin + QPointF(8, -8), node.name)
        painter.setOpacity(base_opacity)

    def _draw_artwork(
        self, painter: QPainter, colors: dict[str, str], pose: ScenePose, offset: QPointF
    ) -> None:
        """Composite retained device-resolution parts without retessellating during panning.

        Geometry, zoom, DPI, source and wireframe changes invalidate part pixels; camera
        translation only changes placement. Oversized parts retain a padded visible window
        and refill when newly exposed artwork exceeds it. The primary pose owns a 64 MiB
        part cache plus one viewport-sized composite. SVGs render from original vectors.
        """
        if not pose.meshes and not pose.particles:
            self._artwork_pose, self._artwork_layer = None, None
            return
        primary = pose is (self.subdivision_pose or self.pose)
        # Mesh editing owns its topology and point overlay in one screen-space pass.
        wireframe = (
            self.mesh_wireframe and not self.mesh_editing
        ) or self.subdivision_pose is not None
        sources: dict[str | None, tuple[str, object]] = {}
        for key in {mesh.asset_id for mesh in pose.meshes.values()}:
            if vector := self.artwork.vectors.get(key or ""):
                sources[key] = ("vector", weakref.ref(vector))
            else:
                source = self.artwork.images.get(key or "")
                sources[key] = ("raster", source.cacheKey() if source is not None else None)
        raster_view = (
            self.devicePixelRatioF(),
            self.preview_quality,
            self.zoom,
            wireframe,
            colors["text"],
        )
        view = (self.width(), self.height(), offset.x(), offset.y(), raster_view, sources)
        if primary and self._artwork_pose is pose and self._artwork_view == view:
            if self._artwork_layer is not None:
                painter.drawPixmap(QPointF(), self._artwork_layer)
            return
        layer = QPixmap(
            round(self.width() * self.devicePixelRatioF()),
            round(self.height() * self.devicePixelRatioF()),
        )
        layer.setDevicePixelRatio(self.devicePixelRatioF())
        layer.fill(Qt.GlobalColor.transparent)
        target = QPainter(layer)
        visible = QRectF(self.rect()).translated(-offset)
        part_budget = min(16 * 1024**2, 64 * 1024**2 // max(1, len(pose.meshes)))
        remaining = {
            mesh.id
            for mesh in pose.meshes.values()
            if mesh.object_id is not None
            and mesh.object_id in pose.nodes
            and pose.nodes[mesh.object_id].visible
        }
        meshes: dict[str | None, list[MeshPose]] = {}
        for mesh in pose.meshes.values():
            meshes.setdefault(mesh.object_id, []).append(mesh)
        for key in pose.render_order:
            node = pose.nodes[key]
            if not node.visible:
                continue
            target.setOpacity(node.opacity)
            for particle in pose.particles.get(key, ()):
                target.save()
                a, b, c, d, x, y = particle.matrix
                target.setWorldTransform(
                    QTransform(
                        a * self.zoom,
                        b * self.zoom,
                        c * self.zoom,
                        d * self.zoom,
                        x * self.zoom + offset.x(),
                        y * self.zoom + offset.y(),
                    )
                )
                target.setOpacity(node.opacity * particle.opacity)
                target.setPen(Qt.PenStyle.NoPen)
                target.setBrush(QColor(particle.color))
                if particle.shape == "circle":
                    target.drawEllipse(QRectF(-1, -1, 2, 2))
                else:
                    target.drawRect(QRectF(-1, -1, 2, 2))
                target.restore()
            for mesh in meshes.get(key, ()):
                remaining.discard(mesh.id)
                translation = QPointF(*node.world_matrix[4:]) * self.zoom
                signature = (
                    mesh.asset_id,
                    sources[mesh.asset_id],
                    mesh.appearance,
                    mesh.positions,
                    mesh.uv,
                    mesh.triangles,
                    node.world_matrix[:4],
                    raster_view,
                )
                cached = self._mesh_layers.get(mesh.id) if primary else None
                if cached is not None and cached.signature == signature:
                    shift = translation - cached.translation
                    if not shift.isNull():
                        cached = replace(
                            cached,
                            origin=cached.origin + shift,
                            bounds=cached.bounds.translated(shift),
                            translation=translation,
                        )
                        self._mesh_layers[mesh.id] = cached
                if (
                    cached is not None
                    and cached.signature == signature
                    and not cached.bounds.intersects(visible)
                ):
                    continue
                if cached is not None and cached.signature == signature and cached.covers(visible):
                    self.raster_hits += 1
                    self._mesh_layers.move_to_end(mesh.id)
                    target.drawPixmap(offset + cached.origin, cached.tile)
                    continue
                polygon = mesh_polygon(mesh.positions, node.world_matrix, self.zoom, QPointF())
                points = tuple(cast(Sequence[QPointF], polygon))
                if any(
                    not math.isfinite(value) or abs(value) > 1e8
                    for point in points
                    for value in (point.x(), point.y())
                ):
                    continue
                bounds = QRectF()
                if points:
                    xs, ys = [p.x() for p in points], [p.y() for p in points]
                    bounds = QRectF(QPointF(min(xs), min(ys)), QPointF(max(xs), max(ys)))
                bounds = QRectF(bounds.adjusted(-2, -2, 2, 2).toAlignedRect())
                if not bounds.intersects(visible):
                    continue
                rect = bounds.toAlignedRect()
                if (
                    rect.width() * rect.height() * self.devicePixelRatioF() ** 2 * 4 > part_budget
                    or max(rect.width(), rect.height()) > 8192
                ):
                    # Bound zoomed/oversized allocations, retaining a small pan overscan.
                    rect = bounds.intersected(
                        visible.adjusted(-128, -128, 128, 128)
                    ).toAlignedRect()
                origin = QPointF(rect.topLeft())
                self.raster_misses += 1
                mesh_started = perf_counter() if self.profile_paint else 0.0
                ratio = self.devicePixelRatioF() * self.preview_quality
                tile = QPixmap(
                    max(1, round(rect.width() * ratio)),
                    max(1, round(rect.height() * ratio)),
                )
                tile.setDevicePixelRatio(ratio)
                tile.fill(Qt.GlobalColor.transparent)
                part = QPainter(tile)
                local = tuple(point - origin for point in points)
                image = self.artwork.styled(mesh.asset_id or "", mesh.appearance)
                if image is not None:
                    draw_mesh(part, mesh, local, image)
                if wireframe:
                    part.setPen(QPen(QColor(colors["text"]), 1))
                    part.drawLines(
                        [QLineF(local[a], local[b]) for a, b in triangle_edges(mesh.triangles)]
                    )
                part.end()
                if self.profile_paint:
                    self.mesh_paint_ms[mesh.id] = (perf_counter() - mesh_started) * 1000
                target.drawPixmap(offset + origin, tile)
                if primary:
                    self._mesh_layers.pop(mesh.id, None)
                    needed = tile.width() * tile.height() * 4
                    used = sum(
                        p.tile.width() * p.tile.height() * 4 for p in self._mesh_layers.values()
                    )
                    for old in tuple(self._mesh_layers):
                        if len(self._mesh_layers) < 1024 and used + needed <= 64 * 1024**2:
                            break
                        # Protect parts about to be painted, preventing a sequential
                        # scene larger than the cache from missing on every part.
                        if old not in remaining:
                            evicted = self._mesh_layers.pop(old)
                            used -= evicted.tile.width() * evicted.tile.height() * 4
                    if len(self._mesh_layers) >= 1024 or used + needed > 64 * 1024**2:
                        continue
                    self._mesh_layers[mesh.id] = _MeshLayer(
                        signature, tile, origin, bounds, translation
                    )
                    self._mesh_layers.move_to_end(mesh.id)
        target.end()
        painter.drawPixmap(QPointF(), layer)
        if primary:
            self._artwork_pose, self._artwork_view, self._artwork_layer = pose, view, layer

    def _draw_needle(
        self, painter: QPainter, root: QPointF, tip: QPointF, tone: str, *, preview: bool = False
    ) -> None:
        """Render the shared replaceable armature for bones and live drawing feedback."""
        if not self.bone_connections and not preview:
            painter.setBrush(QColor(tone))
            radius = 4 * self.bone_display_size
            painter.drawEllipse(root, radius, radius)
            painter.drawEllipse(tip, radius, radius)
            return
        self.bone_shape.draw(
            painter,
            root,
            tip,
            "" if tone == "#bcbcbc" else tone,
            preview=preview,
            width_scale=self.bone_display_size,
        )

    def _bone_joints(self) -> list[tuple[str, QPointF]]:
        """List editable visible endpoints, preferring tips when multiple joints coincide."""
        joints = []
        for at_tip in (True, False):
            for node in reversed(tuple(self.pose.nodes.values())) if self.pose else ():
                if node.kind != "bone" or not node.visible or node.id in self.locked_bones:
                    continue
                point = transform_point(node.world_matrix, node.length if at_tip else 0, 0)
                if all(math.isfinite(value) and abs(value) < 1e8 for value in point):
                    joints.append((node.id, QPointF(*point)))
        return joints

    def _snap_joint(self, point: QPointF) -> tuple[str, QPointF] | None:
        """Find a joint within fourteen screen pixels regardless of the current zoom."""
        closest = None
        distance = 14.0
        for key, joint in self._bone_joints():
            candidate = math.hypot((joint - point).x(), (joint - point).y()) * self.zoom
            if candidate < distance:
                closest, distance = (key, joint), candidate
        return closest

    def _update_draw_cursor(self, position: QPointF, modifiers: Qt.KeyboardModifier) -> None:
        """Constrain Shift drags to 45-degree rays and retain independent Alt joint magnets."""
        self._draw_position = position
        self.capture_snap_modifier()
        free = bool(modifiers & Qt.KeyboardModifier.AltModifier)
        point = self.scene_point(position)
        direction = None
        origin = None
        if self._draw_origin is not None:
            origin_snap = None if free else self._snap_joint(self._draw_origin)
            origin = origin_snap[1] if origin_snap else self._draw_origin
            self._rig_drag = ("", "draw", origin)
            parent = origin_snap[0] if origin_snap else ""
            if parent != self._draw_parent:
                self._draw_parent = parent
                self.bone_selected.emit(parent, False)
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                delta = point - origin
                angle = round(math.atan2(delta.y(), delta.x()) / (math.pi / 4)) * (math.pi / 4)
                direction = QPointF(math.cos(angle), math.sin(angle))
                point = origin + direction * math.hypot(delta.x(), delta.y())
        self._draw_snap = None if free else self._snap_joint(point)
        if self._draw_snap and direction is not None and origin is not None:
            delta = self._draw_snap[1] - origin
            # A positional magnet may shorten the ray, but must never break its locked direction.
            cross = direction.x() * delta.y() - direction.y() * delta.x()
            if abs(cross) * self.zoom > 1e-6 or QPointF.dotProduct(direction, delta) < 0:
                self._draw_snap = None
        self._rig_cursor = self._draw_snap[1] if self._draw_snap else point
        self.refresh_cursor()
        self.update()

    def _draw_joint_cursor(self, painter: QPainter, colors: dict[str, str]) -> None:
        """Show endpoint circles and a circular cursor at the resolved drawing position."""
        if not self.rig_mode or self.rig_tool != "draw" or self.pan_tool or self._space:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(colors["muted"]), 1))
        for _, point in self._bone_joints():
            painter.drawEllipse(point * self.zoom + self.offset, 6, 6)
        if self._draw_position is not None and self._rig_cursor is not None:
            point = self._rig_cursor * self.zoom + self.offset
            tone = SELECTED_BONE_COLOR if self._draw_snap else colors["text"]
            painter.setPen(QPen(QColor(tone), 1.5))
            painter.drawEllipse(point, 6, 6)
            if self._draw_snap:
                painter.drawEllipse(point, 9, 9)
            if self._rig_drag and self._draw_origin is not None:
                painter.drawEllipse(self._rig_drag[2] * self.zoom + self.offset, 6, 6)
        painter.restore()

    def refresh_cursor(self, position: QPointF | None = None) -> None:
        """Match the system pointer to navigation or the viewport's circular drawing cursor."""
        drawing = (
            self.rig_mode and self.rig_tool == "draw" and not self.pan_tool and not self._space
        )
        if drawing and self._draw_position is None and self.underMouse():
            self._update_draw_cursor(
                QPointF(self.mapFromGlobal(QCursor.pos())), QApplication.keyboardModifiers()
            )
            return
        if position is not None:
            if position != self._pointer:
                self.update()
            self._pointer = QPointF(position)
        point = self._pointer
        if self._drag is not None:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif self.pan_tool or self._space:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        elif point is not None and self.pin_cursor and (pin_cursor := self.pin_cursor(point)):
            self.setCursor(pin_cursor)
        elif drawing:
            self.setCursor(
                Qt.CursorShape.BlankCursor
                if self._draw_position is not None
                else Qt.CursorShape.CrossCursor
            )
        elif self.rig_mode and self.rig_tool == "select" and point is not None:
            rect = self.bone_transform_bounds()
            handle = transform_gizmo.pick(rect, point) if rect else None
            extending = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier)
            if extending:
                handle = None
            if self._bone_transform:
                handle = self._bone_transform.handle
            if handle is not None:
                self.setCursor(transform_gizmo.cursor(handle, self.icons))
            elif self._rig_drag:
                self.setCursor(
                    Qt.CursorShape.ClosedHandCursor
                    if self.bone_movement == "pull"
                    else Qt.CursorShape.SizeAllCursor
                )
            elif not extending and self.bone_rotation_tip(point):
                self.setCursor(transform_gizmo.cursor(8, self.icons))
            elif self.pose is not None and (hit := self.bone_at(point)) is not None:
                endpoint = hit in self.ik_endpoints
                self.setCursor(
                    transform_gizmo.cursor(8, self.icons)
                    if self.bone_movement == "chain_move"
                    and not endpoint
                    and self.pose.nodes[hit].length > 0
                    else QCursor(Qt.CursorShape.OpenHandCursor)
                    if self.bone_movement == "pull" or endpoint
                    else QCursor(Qt.CursorShape.SizeAllCursor)
                )
            else:
                self.setCursor(Qt.CursorShape.CrossCursor)
        elif point is not None:
            resolved = None
            for provider in (self.mesh_cursor, self.scene_cursor):
                if provider is None:
                    continue
                try:
                    resolved = provider(point)
                except (ProjectError, ValueError):
                    resolved = QCursor(Qt.CursorShape.ForbiddenCursor)
                if resolved is not None:
                    break
            self.setCursor(
                resolved if resolved is not None else QCursor(Qt.CursorShape.ArrowCursor)
            )
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def cancel_rig_gesture(self) -> None:
        """Discard transient placement and snap state without changing any project geometry."""
        live = self._rig_drag is not None and self._rig_drag[1] != "draw"
        application = QApplication.instance()
        if application:
            application.removeEventFilter(self)
        self._rig_drag, self._rig_cursor, self._rig_press, self._selection_box = (
            None,
            None,
            None,
            None,
        )
        self._draw_origin, self._draw_position, self._draw_snap = None, None, None
        self._draw_parent = ""
        self._bone_transform = None
        self._toggle_bone_on_click = ""
        self._drag_pose, self._movement_snap = None, None
        if live:
            self.bone_drag_cancelled.emit()
        self.refresh_cursor()
        self.update()

    def settings_size(self) -> QSizeF:
        """Return canvas dimensions scaled into viewport coordinates."""
        return QSizeF(self.settings.width * self.zoom, self.settings.height * self.zoom)

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Translate wheel movement into zoom around the cursor position."""
        self.zoom_at(1.2 ** (event.angleDelta().y() / 120), event.position())
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Begin panning for the middle button or the active space/pan gesture."""
        if event.button() == Qt.MouseButton.MiddleButton or (
            event.button() == Qt.MouseButton.LeftButton and (self._space or self.pan_tool)
        ):
            self._drag = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
        elif self.rig_mode and event.button() == Qt.MouseButton.RightButton:
            self.cancel_rig_gesture()
            self.bone_selected.emit("", False)
        elif self.extension_pointer and event.button() == Qt.MouseButton.LeftButton:
            point = self.scene_point(event.position())
            self._extension_drag = True
            self.extension_pointer(
                "press",
                point.x(),
                point.y(),
                bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier),
            )
            event.accept()
        elif self.rig_mode and event.button() == Qt.MouseButton.LeftButton:
            self.begin_rig_drag(event)
            event.accept()
        else:
            super().mousePressEvent(event)

    def begin_rig_drag(self, event: QMouseEvent) -> None:
        """Hit-test scene geometry and start a single undoable rig gesture."""
        point = self.scene_point(event.position())
        self._drag_pose = self.pose
        self._movement_snap = None
        if self.rig_tool == "draw":
            self._draw_origin = point
            self._draw_parent = self.selected_bones[0] if self.selected_bones else ""
            self._rig_drag = ("", "draw", point)
            self._update_draw_cursor(event.position(), event.modifiers())
            return
        if self.pose is None:
            return
        self._bone_transform = None
        if len(self.selected_bones) == 1 and self.rig_tool == "select":
            node = self.pose.nodes.get(self.selected_bones[0])
            if node and node.length == 0 and node.id not in self.locked_bones:
                root = QPointF(*node.world_matrix[4:])
                if (root - point).manhattanLength() * self.zoom <= 12:
                    tool = (
                        "selection_move" if self.bone_movement == "selection_move" else "chain_move"
                    )
                    self._rig_drag = (node.id, tool, root - point)
                    self._rig_press = event.position()
                    self.bone_drag_started.emit()
                    self.refresh_cursor(event.position())
                    return
        rect = (
            self.bone_transform_bounds()
            if self.rig_tool == "select"
            and not event.modifiers() & Qt.KeyboardModifier.ControlModifier
            else None
        )
        handle = transform_gizmo.pick(rect, event.position()) if rect else None
        rotation_tip = (
            self.bone_rotation_tip(event.position())
            if rect is not None and handle is None
            else None
        )
        if rotation_tip and not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            handle = 8
        if handle is not None and self.selected_bones:
            assert rect is not None
            self._bone_transform = transform_gizmo.Gesture(
                rect, event.position(), handle, self.bone_transform_pivot()
            )
            prefix = (
                "rig"
                if self.bone_movement == "rig_move"
                else "selection"
                if self.bone_movement == "selection_move"
                else "chain"
            )
            tool = f"{prefix}_rotate" if handle == 8 else f"{prefix}_scale"
            self._rig_drag = (self.selected_bones[0], tool, QPointF())
            self._rig_press = event.position()
            self.bone_drag_started.emit()
            self.refresh_cursor(event.position())
            return
        if self.rig_target in self.pose.nodes:
            target = QPointF(*self.pose.nodes[self.rig_target].world_matrix[4:])
            if (target - point).manhattanLength() * self.zoom < 16:
                self._rig_drag = (self.rig_target, "target", target - point)
                self._rig_press = event.position()
                self.bone_drag_started.emit()
                return
        for node in reversed(tuple(self.pose.nodes.values())):
            if node.kind != "bone" or not node.visible or node.id in self.locked_bones:
                continue
            root = QPointF(*transform_point(node.world_matrix, 0, 0))
            tip = QPointF(*transform_point(node.world_matrix, node.length, 0))
            vx, vy = tip.x() - root.x(), tip.y() - root.y()
            fraction = min(
                1,
                max(
                    0,
                    ((point.x() - root.x()) * vx + (point.y() - root.y()) * vy)
                    / max(1e-12, vx * vx + vy * vy),
                ),
            )
            nearest = root + (tip - root) * fraction
            pivot = QPointF(
                *transform_point(node.world_matrix, node.local.pivot_x, node.local.pivot_y)
            )
            radius = math.hypot(point.x() - pivot.x(), point.y() - pivot.y()) * self.zoom
            ring = (
                node.id in self.selected_bones
                and self.rig_tool == "rotate"
                and abs(radius - 30) < 9
            )
            screen_point = point * self.zoom + self.offset
            if (
                self.bone_shape.contains(
                    screen_point,
                    root * self.zoom + self.offset,
                    tip * self.zoom + self.offset,
                    self.bone_display_size,
                )
                or (nearest - point).manhattanLength() * self.zoom < 10
                or ring
            ):
                extend = bool(
                    event.modifiers()
                    & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
                )
                self._toggle_bone_on_click = (
                    node.id if extend and node.id in self.selected_bones else ""
                )
                if node.id not in self.selected_bones:
                    self.bone_selected.emit(node.id, extend)
                tool = self.rig_tool
                if tool == "select":
                    tool = self.bone_movement
                    if tool == "chain_move" and node.id in self.ik_endpoints:
                        tool = "pull"
                    elif tool == "chain_move" and node.length > 0:
                        rect = self.bone_transform_bounds()
                        if rect is not None:
                            self._bone_transform = transform_gizmo.Gesture(
                                rect, event.position(), 8, self.bone_transform_pivot()
                            )
                            tool = "chain_rotate"
                offset = (
                    root - point
                    if tool in ("move", "selection_move", "chain_move", "rig_move")
                    else tip - point
                    if tool == "pull"
                    else root
                )
                self._rig_drag = (node.id, tool, offset)
                self._rig_cursor = point
                self._rig_press = event.position()
                self.bone_drag_started.emit()
                self.refresh_cursor(event.position())
                return
        if self.rig_tool == "select":
            self._selection_box = (event.position(), event.position())
            self._selection_extend = bool(
                event.modifiers()
                & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
            )
            self.update()
        else:
            self.bone_selected.emit("", False)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Translate the viewport while a navigation drag is active."""
        self.refresh_cursor(event.position())
        if self._drag is not None:
            self.offset += event.position() - self._drag
            self._drag = event.position()
            self.update()
        elif self._extension_drag and self.extension_pointer:
            point = self.scene_point(event.position())
            self.extension_pointer(
                "move",
                point.x(),
                point.y(),
                bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier),
            )
            event.accept()
        elif self._selection_box is not None:
            self._selection_box = (self._selection_box[0], event.position())
            self.update()
        elif self._rig_drag is not None:
            if self._rig_drag[1] == "draw":
                self._update_draw_cursor(event.position(), event.modifiers())
            else:
                self._rig_cursor = self.scene_point(event.position())
                if (
                    self._rig_press is not None
                    and (event.position() - self._rig_press).manhattanLength() > 3
                ):
                    key, tool, offset = self._rig_drag
                    target = self.rig_drag_target(
                        key, tool, offset, event.position(), event.modifiers()
                    )
                    self.bone_drag_preview.emit(key, tool, target.x(), target.y())
                self.update()
        elif self.rig_mode and self.rig_tool == "draw" and not self.pan_tool and not self._space:
            self._update_draw_cursor(event.position(), event.modifiers())
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Finish a navigation drag and restore the tool cursor."""
        self._drag = None
        application = QApplication.instance()
        if application:
            application.removeEventFilter(self)
        if (
            self._extension_drag
            and self.extension_pointer
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._extension_drag = False
            point = self.scene_point(event.position())
            self.extension_pointer(
                "release",
                point.x(),
                point.y(),
                bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier),
            )
            event.accept()
            return
        if self._selection_box is not None and event.button() == Qt.MouseButton.LeftButton:
            box = QRectF(self._selection_box[0], event.position()).normalized()
            self._selection_box = None
            self.bones_selected.emit(self.bones_in_rectangle(box), self._selection_extend)
            self.update()
            return
        if self._rig_drag is not None and event.button() == Qt.MouseButton.LeftButton:
            if self._rig_drag[1] == "draw":
                self._update_draw_cursor(event.position(), event.modifiers())
            key, tool, start = self._rig_drag
            moved = (
                self._rig_press is not None
                and (event.position() - self._rig_press).manhattanLength() > 3
            )
            end = self._rig_cursor if tool == "draw" else self.scene_point(event.position())
            self._rig_drag, self._rig_cursor = None, None
            self._rig_press = None
            self._draw_origin = None
            self._draw_parent = ""
            assert end is not None
            if tool == "draw":
                self.bone_created.emit(start.x(), start.y(), end.x(), end.y())
                self._update_draw_cursor(event.position(), event.modifiers())
            elif moved:
                target = self.rig_drag_target(key, tool, start, event.position(), event.modifiers())
                self.bone_dragged.emit(key, tool, target.x(), target.y())
            else:
                self.bone_drag_cancelled.emit()
                if self._toggle_bone_on_click:
                    self.bone_selected.emit(self._toggle_bone_on_click, True)
            self._toggle_bone_on_click = ""
            self._bone_transform = None
            self._drag_pose, self._movement_snap = None, None
            self.update()
        self.refresh_cursor()
        super().mouseReleaseEvent(event)

    def rig_drag_target(
        self,
        key: str,
        tool: str,
        offset: QPointF,
        position: QPointF,
        modifiers: Qt.KeyboardModifier,
    ) -> QPointF:
        """Resolve baseline geometry with pixel-sized joint magnets unless Alt is held.

        Translation aligns whole selections. Rotation snaps only to reachable joints
        on the original radius, preserving anchored FK lengths. Parenting is untouched.
        """
        target = self.scene_point(position)
        translating = tool in ("move", "selection_move", "chain_move", "rig_move")
        if translating or tool in ("pull", "target"):
            target += offset
        if self._bone_transform:
            _, angle, scale, _ = self._bone_transform.values(
                position, centered=True, snap=bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
            )
            target = QPointF(angle if tool.endswith("_rotate") else scale, 0)
        self._movement_snap = None
        pose = self._drag_pose
        rotating = tool.endswith("_rotate") and self._bone_transform is not None
        if (
            pose is None
            or key not in pose.nodes
            or modifiers & Qt.KeyboardModifier.AltModifier
            or not (translating or rotating)
        ):
            return target
        moving = {k for k in self.selected_bones if k in pose.nodes} or {key}
        if tool.startswith("rig_"):
            roots = set()
            for identity in moving:
                node = pose.nodes[identity]
                while node.parent_id and node.parent_id in pose.nodes:
                    node = pose.nodes[node.parent_id]
                roots.add(node.id)
            moving = roots
        if tool.startswith(("rig_", "chain_")) or tool == "move":
            for node in pose.nodes.values():
                if node.kind == "bone" and node.parent_id in moving:
                    moving.add(node.id)
        sources: list[QPointF] = []
        destinations: list[QPointF] = []
        rotation_roots = (
            set(
                selected_roots({k: n.parent_id for k, n in pose.nodes.items()}, self.selected_bones)
            )
            if tool == "chain_rotate"
            else moving
        )
        if rotating and tool == "chain_rotate" and len(rotation_roots) != 1:
            return target
        for node in pose.nodes.values():
            if node.kind != "bone" or not node.visible or node.id in self.locked_bones:
                continue
            points = [
                QPointF(*transform_point(node.world_matrix, distance, 0))
                for distance in (0, node.length)
            ]
            if node.id not in moving:
                destinations.extend(points)
            elif not rotating or node.id in rotation_roots:
                sources.extend(points)
        origin = QPointF(*pose.nodes[key].world_matrix[4:])
        delta = target - origin
        pivot = (
            self.scene_point(self._bone_transform.pivot or self._bone_transform.rect.center())
            if rotating and self._bone_transform
            else QPointF()
        )
        angle = math.radians(target.x()) if rotating else 0
        closest = 14.0
        result = QPointF(target)
        for source in sources:
            vector = source - pivot
            moved = (
                pivot
                + QPointF(
                    vector.x() * math.cos(angle) - vector.y() * math.sin(angle),
                    vector.x() * math.sin(angle) + vector.y() * math.cos(angle),
                )
                if rotating
                else source + delta
            )
            for joint in destinations:
                distance = math.hypot((joint - moved).x(), (joint - moved).y()) * self.zoom
                if distance >= closest:
                    continue
                if rotating:
                    radius = math.hypot(vector.x(), vector.y())
                    other = joint - pivot
                    if radius < 1e-8 or abs(radius - math.hypot(other.x(), other.y())) > 1e-6:
                        continue
                    degrees = math.degrees(
                        math.atan2(other.y(), other.x()) - math.atan2(vector.y(), vector.x())
                    )
                    result = QPointF((degrees + 180) % 360 - 180, 0)
                else:
                    result = target + joint - moved
                closest, self._movement_snap = distance, joint
        return result

    def refresh_drag_snap(self, modifiers: Qt.KeyboardModifier) -> None:
        """Toggle magnets on Alt press/release without requiring another pointer move."""
        if (
            self._rig_drag
            and self._rig_press is not None
            and self._pointer is not None
            and (self._pointer - self._rig_press).manhattanLength() > 3
        ):
            key, tool, offset = self._rig_drag
            target = self.rig_drag_target(key, tool, offset, self._pointer, modifiers)
            self.bone_drag_preview.emit(key, tool, target.x(), target.y())
            self.update()

    def capture_snap_modifier(self) -> None:
        """Give active drags first access to Alt before the menu bar's mnemonic handling."""
        application = QApplication.instance()
        if application:
            application.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Apply drawing modifiers immediately and reserve Alt from menu mnemonic handling."""
        if (
            (self._rig_drag or (self.rig_mode and self.rig_tool == "draw" and self.hasFocus()))
            and isinstance(event, QKeyEvent)
            and (
                event.key() == Qt.Key.Key_Alt
                or event.key() == Qt.Key.Key_Shift
                and self.rig_mode
                and self.rig_tool == "draw"
            )
        ):
            modifiers = transform_gizmo.modifiers_after(event)
            if event.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
                if self.rig_tool == "draw" and self._draw_position is not None:
                    self._update_draw_cursor(self._draw_position, modifiers)
                else:
                    self.refresh_drag_snap(modifiers)
            if event.type() in (
                QEvent.Type.KeyPress,
                QEvent.Type.KeyRelease,
                QEvent.Type.ShortcutOverride,
            ):
                event.accept()
                return True
        return False

    def bone_at(self, point: QPointF) -> str | None:
        """Resolve visible armature silhouettes using the same screen geometry as picking."""
        if self.pose is None:
            return None
        for key in self.selected_bones:
            node = self.pose.nodes.get(key)
            if node and node.length == 0 and node.visible and key not in self.locked_bones:
                root = QPointF(*node.world_matrix[4:]) * self.zoom + self.offset
                if math.hypot(point.x() - root.x(), point.y() - root.y()) <= 10:
                    return key
        for node in reversed(tuple(self.pose.nodes.values())):
            if node.kind != "bone" or not node.visible or node.id in self.locked_bones:
                continue
            root = QPointF(*node.world_matrix[4:]) * self.zoom + self.offset
            tip = (
                QPointF(*transform_point(node.world_matrix, node.length, 0)) * self.zoom
                + self.offset
            )
            line = tip - root
            fraction = max(
                0.0,
                min(
                    1.0,
                    QPointF.dotProduct(point - root, line)
                    / max(1e-12, QPointF.dotProduct(line, line)),
                ),
            )
            nearest = root + line * fraction
            if (
                self.bone_shape.contains(point, root, tip, self.bone_display_size)
                or (nearest - point).manhattanLength() < 10
            ):
                return node.id
        return None

    def bone_rotation_tip(self, point: QPointF) -> str | None:
        """Use the selected tip for rotation even where it overlaps a child joint."""
        if (
            self.rig_tool != "select"
            or self.pose is None
            or len(self.selected_bones) != 1
            or self.bone_movement == "pull"
        ):
            return None
        key = self.selected_bones[0]
        if key in self.ik_endpoints:
            return None
        node = self.pose.nodes.get(key)
        if node and node.length > 0 and node.visible and key not in self.locked_bones:
            tip = (
                QPointF(*transform_point(node.world_matrix, node.length, 0)) * self.zoom
                + self.offset
            )
            if math.hypot(point.x() - tip.x(), point.y() - tip.y()) <= 9:
                return key
        return None

    def bone_transform_pivot(self) -> QPointF | None:
        """Use the selected joint as a single-bone pivot, or the group bounds center."""
        if self.pose is None or not self.selected_bones:
            return None
        keys = self.selected_bones
        if self.bone_movement == "chain_move":
            keys = selected_roots({k: n.parent_id for k, n in self.pose.nodes.items()}, keys)
        if self.bone_movement == "rig_move":
            roots = []
            for key in keys:
                node = self.pose.nodes.get(key)
                if node is None:
                    continue
                while node.parent_id and node.parent_id in self.pose.nodes:
                    node = self.pose.nodes[node.parent_id]
                if node.id not in roots:
                    roots.append(node.id)
            keys = tuple(roots)
        if len(keys) != 1:
            if keys != self.selected_bones:
                rect = transform_gizmo.bounds(
                    [
                        QPointF(*transform_point(self.pose.nodes[k].world_matrix, distance, 0))
                        * self.zoom
                        + self.offset
                        for k in keys
                        for distance in (0, self.pose.nodes[k].length)
                    ]
                )
                return rect.center() if rect else None
            rect = self.bone_transform_bounds()
            return rect.center() if rect else None
        node = self.pose.nodes.get(keys[0])
        if node is None:
            return None
        return QPointF(*node.world_matrix[4:]) * self.zoom + self.offset

    def bone_transform_bounds(self) -> QRectF | None:
        """Frame selected bone endpoints for the universal transform tool."""
        if self.pose is None:
            return None
        return transform_gizmo.bounds(
            [
                QPointF(*transform_point(node.world_matrix, distance, 0)) * self.zoom + self.offset
                for key in self.selected_bones
                if key in self.pose.nodes
                for node in (self.pose.nodes[key],)
                if node.visible and key not in self.locked_bones
                for distance in (0, node.length)
            ]
        )

    def bones_in_rectangle(self, rect: QRectF) -> tuple[str, ...]:
        """Select editable bone segments intersecting a screen-space marquee."""
        if self.pose is None:
            return ()
        borders = [
            QLineF(rect.topLeft(), rect.topRight()),
            QLineF(rect.topRight(), rect.bottomRight()),
            QLineF(rect.bottomRight(), rect.bottomLeft()),
            QLineF(rect.bottomLeft(), rect.topLeft()),
        ]
        selected = []
        for node in self.pose.nodes.values():
            if node.kind != "bone" or not node.visible or node.id in self.locked_bones:
                continue
            root = QPointF(*transform_point(node.world_matrix, 0, 0)) * self.zoom + self.offset
            tip = (
                QPointF(*transform_point(node.world_matrix, node.length, 0)) * self.zoom
                + self.offset
            )
            segment = QLineF(root, tip)
            if (
                rect.contains(root)
                or rect.contains(tip)
                or any(
                    segment.intersects(edge)[0] == QLineF.IntersectionType.BoundedIntersection
                    for edge in borders
                )
            ):
                selected.append(node.id)
        return tuple(selected)

    def leaveEvent(self, event: QEvent) -> None:
        """Hide idle drawing feedback when the pointer leaves the viewport."""
        if self._rig_drag is None and self._selection_box is None:
            self._draw_position, self._draw_snap, self._rig_cursor = None, None, None
            self.unsetCursor()
            self.update()
        super().leaveEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Temporarily enable space-drag panning without consuming unrelated shortcuts."""
        if event.key() == Qt.Key.Key_Alt and self._rig_drag and self._rig_drag[1] != "draw":
            self.refresh_drag_snap(event.modifiers() | Qt.KeyboardModifier.AltModifier)
            event.accept()
        elif event.key() == Qt.Key.Key_Escape:
            if self._extension_drag and self.extension_pointer:
                self._extension_drag = False
                self.extension_pointer("cancel", 0, 0, False)
            self.cancel_rig_gesture()
            event.accept()
        elif (
            self.rig_mode
            and event.key() == Qt.Key.Key_A
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.bones_selected.emit(
                tuple(dict.fromkeys(key for key, _ in self._bone_joints())), False
            )
            event.accept()
        elif event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space = True
            self.refresh_cursor()
            self.update()
        elif (
            event.key() in (Qt.Key.Key_Alt, Qt.Key.Key_Shift)
            and self.rig_mode
            and self.rig_tool == "draw"
        ):
            if self._draw_position is not None:
                self._update_draw_cursor(
                    self._draw_position, transform_gizmo.modifiers_after(event)
                )
            event.accept()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        """Release temporary space-drag navigation."""
        if event.key() == Qt.Key.Key_Alt and self._rig_drag and self._rig_drag[1] != "draw":
            self.refresh_drag_snap(transform_gizmo.modifiers_after(event))
            event.accept()
        elif event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space = False
            self.refresh_cursor()
            self.update()
        elif (
            event.key() in (Qt.Key.Key_Alt, Qt.Key.Key_Shift)
            and self.rig_mode
            and self.rig_tool == "draw"
        ):
            if self._draw_position is not None:
                self._update_draw_cursor(
                    self._draw_position, transform_gizmo.modifiers_after(event)
                )
            event.accept()
        else:
            super().keyReleaseEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        """Clear held-key and drag state so a lost focus cannot leave panning stuck."""
        self._space = False
        if self._extension_drag and self.extension_pointer:
            self._extension_drag = False
            self.extension_pointer("cancel", 0, 0, False)
        self._drag = None
        self.cancel_rig_gesture()
        super().focusOutEvent(event)
