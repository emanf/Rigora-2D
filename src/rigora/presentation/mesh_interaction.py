"""Viewport hit testing, transient mesh gestures and neutral influence/control overlays."""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, cast

from PySide6.QtCore import QEvent, QLineF, QObject, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QCursor,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QPicture,
    QPixmap,
    QPolygonF,
)

from rigora.application_services.skinning import BrushOperation, SkinService, weight_brush
from rigora.domain.entities import Mesh
from rigora.domain.geometry import Matrix, inverse, transform_point
from rigora.domain.project import ProjectError
from rigora.domain.validation import json_copy
from rigora.engine.deformation import DeformationPlan, lattice_controls
from rigora.engine.ffd_controls import soft_drag_weights
from rigora.engine.state import ScenePose
from rigora.presentation import transform_gizmo
from rigora.presentation.artwork import mesh_polygon, triangle_edges
from rigora.presentation.themes import PALETTES
from rigora.presentation.viewmodels.meshes import MeshViewModel
from rigora.presentation.widgets.meshes import MeshPanel
from rigora.presentation.widgets.viewport import Viewport


@dataclass
class ControlScale:
    """Retain a selection's original local points and opposite resize anchor during a drag."""

    anchor: QPointF
    start: QPointF
    offset: QPointF
    points: dict[int, QPointF]
    rotation: bool = False
    vertex_ids: tuple[str, ...] = ()
    handle: int = 0
    resize_cursor: QCursor | None = None


class MeshInteraction(QObject):
    """Translate pointer gestures into a single validated authoring command on release."""

    def __init__(self, viewport: Viewport, model: MeshViewModel, panel: MeshPanel) -> None:
        """Attach event routing and painting while retaining standard viewport navigation."""
        super().__init__(viewport)
        self.viewport, self.model, self.panel = viewport, model, panel
        self.pin_pick: Callable[[QPointF], str] | None = None
        self.drag: tuple[QPointF, dict[tuple[str, str], float]] | None = None
        self.painting = False
        self.cursor: QPointF | None = None
        self.marquee: tuple[QPointF, QPointF] | None = None
        self.marquee_extend = False
        self.scale: ControlScale | None = None
        self.soft_radius = 100.0
        self.soft_strength = 1.0
        self.soft_falloff = 1.0
        self._soft_weights: dict[tuple[str, str], float] | None = None
        self._soft_frames: dict[str, Matrix] = {}
        self._gesture_context: tuple[object, ...] | None = None
        self.pin_bone: str | None = None
        self.pin_radius = 50.0
        self._points_pose: ScenePose | None = None
        self._points_view: tuple[str, float, float, float] | None = None
        self._points = QPolygonF()
        self._topology_signature: tuple[object, ...] = ()
        self._topology_picture: QPicture | None = None
        self._topology_tile: QPixmap | None = None
        self._topology_coverage = QRectF()
        viewport.installEventFilter(self)
        viewport.mesh_overlay = self.draw
        viewport.mesh_cursor = self.cursor_at

    def cursor_at(self, point: QPointF) -> QCursor | None:
        """Match mesh/FFD hit areas and retain the active drag's cursor until release."""
        model = self.model
        if not model.active or model.mesh is None:
            return None
        if self.scale:
            if not self.scale.rotation and self.scale.resize_cursor is not None:
                return self.scale.resize_cursor
            return transform_gizmo.cursor(
                8 if self.scale.rotation else self.scale.handle, self.viewport.icons
            )
        if self.drag:
            return QCursor(
                Qt.CursorShape.ClosedHandCursor
                if model.tool == "soft"
                else Qt.CursorShape.SizeAllCursor
            )
        if model.tool == "soft":
            return QCursor(Qt.CursorShape.OpenHandCursor)
        if self.marquee or model.tool in ("insert", "area_pin", "paint"):
            return QCursor(Qt.CursorShape.CrossCursor)
        frame = self.control_box(self.handles()) if model.tool == "control" else self.vertex_box()
        if frame:
            for index, (screen, _, _) in enumerate(frame[1]):
                if (screen - point).manhattanLength() < 10:
                    rotating = index == 8 or (
                        self.panel.control_mode.currentText() == "Rotate"
                        if model.tool == "control"
                        else model.transform_mode == "rotate"
                    )
                    return transform_gizmo.cursor(
                        8 if rotating else index, self.viewport.icons, [p[0] for p in frame[1]]
                    )
        if model.tool == "control":
            if any((p[2] - point).manhattanLength() < 16 for p in self.handles()) or (
                frame and frame[0].contains(self.local(point))
            ):
                return QCursor(Qt.CursorShape.SizeAllCursor)
        elif self.pick(point):
            return QCursor(Qt.CursorShape.SizeAllCursor)
        return QCursor(Qt.CursorShape.CrossCursor)

    def matrix(self) -> tuple[float, float, float, float, float, float]:
        """Read the sampled object transform; transient mesh edits do not change node transforms."""
        mesh = self.model.mesh
        pose = self.model.document.animation.pose if self.model.document else None
        return (
            pose.nodes[mesh.object_id].world_matrix
            if mesh and mesh.object_id and pose
            else (1, 0, 0, 1, 0, 0)
        )

    def local(self, point: QPointF) -> QPointF:
        """Map a pointer to object-local coordinates; singular transforms reject authoring."""
        p = self.viewport.scene_point(point)
        return QPointF(*transform_point(inverse(self.matrix()), p.x(), p.y()))

    def screen(self, point: tuple[float, float], matrix: Matrix | None = None) -> QPointF:
        """Map one local evaluated vertex or field control into viewport pixels."""
        return (
            QPointF(*transform_point(matrix if matrix is not None else self.matrix(), *point))
            * self.viewport.zoom
            + self.viewport.offset
        )

    def points(self) -> Sequence[QPointF]:
        """Return current deformed vertices for consistent overlay drawing and hit testing."""
        mesh, pose = self.model.mesh, self.model.pose
        if mesh is None or pose is None or mesh.id not in pose.meshes:
            return ()
        view = (mesh.id, self.viewport.zoom, self.viewport.offset.x(), self.viewport.offset.y())
        if pose is self._points_pose and view == self._points_view:
            return cast(Sequence[QPointF], self._points)
        if (
            pose is self._points_pose
            and self._points_view is not None
            and self._points_view[:2] == view[:2]
        ):
            delta = QPointF(view[2] - self._points_view[2], view[3] - self._points_view[3])
            self._points = self._points.translated(delta)
            self._points_view = view
            return cast(Sequence[QPointF], self._points)
        matrix = pose.nodes[mesh.object_id].world_matrix if mesh.object_id else (1, 0, 0, 1, 0, 0)
        points = mesh_polygon(
            pose.meshes[mesh.id].positions, matrix, self.viewport.zoom, self.viewport.offset
        )
        self._points = (
            points
            if all(
                math.isfinite(v) and abs(v) < 1e7
                for point in cast(Sequence[QPointF], points)
                for v in (point.x(), point.y())
            )
            else QPolygonF()
        )
        self._points_pose, self._points_view = pose, view
        # Qt exposes sequence operations at runtime but omits them from QPolygonF's stubs.
        return cast(Sequence[QPointF], self._points)

    def parameters(self) -> dict[str, Any]:
        """Resolve sampled stage parameters, including transient control movement."""
        model = self.model
        if not model.stage_id or not model.document or not model.service:
            return {}
        session = model.document.animation
        plan = session.evaluator.deformation
        params: dict[str, Any] = json_copy(plan.parameters.get(model.stage_id, {}))
        values = {**session.evaluator.mesh_values(session.pose.frame), **model.preview_values}
        for (owner, path), value in values.items():
            if owner == model.stage_id:
                DeformationPlan.override_parameter(params, path, value)
        return params

    def handles(self) -> list[tuple[tuple[str, str], tuple[str, str], QPointF, float, float]]:
        """Expose lattice or pin coordinate channels alongside their displayed local positions."""
        model = self.model
        if not model.service or not model.stage_id:
            return []
        stage = model.service.stage(model.stage_id)
        matrix = self.matrix()
        params = self.parameters()
        result = []
        if stage.kind in ("ffd", "lattice"):
            columns, rows, controls = lattice_controls(params)
            x, y, width, height = params["bounds"]
            for i, (dx, dy) in enumerate(controls):
                point = (
                    x + i % columns * width / (columns - 1) + dx,
                    y + i // columns * height / (rows - 1) + dy,
                )
                result.append(
                    (
                        (stage.id, f"parameters.controls.{i}.0"),
                        (stage.id, f"parameters.controls.{i}.1"),
                        self.screen(point, matrix),
                        dx,
                        dy,
                    )
                )
        elif stage.kind == "pin":
            for key, pin in params.get("pins", {}).items():
                result.append(
                    (
                        (stage.id, f"parameters.pins.{key}.x"),
                        (stage.id, f"parameters.pins.{key}.y"),
                        self.screen((pin["x"], pin["y"]), matrix),
                        pin["x"],
                        pin["y"],
                    )
                )
        return result

    def pick(self, point: QPointF) -> tuple[str, ...]:
        """Pick vertices, edge endpoint pairs or triangle triples with screen-space tolerances."""
        mesh = self.model.mesh
        if mesh is None:
            return ()
        points = self.points()
        if not points:
            return ()
        indices = {v.id: i for i, v in enumerate(mesh.vertices)}
        if self.model.tool == "triangle":
            for face in reversed(mesh.triangles):
                if QPolygonF([points[indices[key]] for key in face]).containsPoint(
                    point, Qt.FillRule.OddEvenFill
                ):
                    return face
        elif self.model.tool == "edge":
            by_id = {v.id: points[i] for i, v in enumerate(mesh.vertices)}
            closest: tuple[float, tuple[str, ...]] = (10, ())
            edges = {
                tuple(sorted((face[i], face[(i + 1) % 3])))
                for face in mesh.triangles
                for i in range(3)
            }
            for edge in edges:
                a, b = by_id[edge[0]], by_id[edge[1]]
                delta = b - a
                t = min(
                    1,
                    max(
                        0,
                        QPointF.dotProduct(point - a, delta)
                        / max(1e-9, QPointF.dotProduct(delta, delta)),
                    ),
                )
                distance = math.hypot((point - a - delta * t).x(), (point - a - delta * t).y())
                if distance < closest[0]:
                    closest = distance, edge
            return closest[1]
        else:
            closest_vertex: tuple[float, str] = (10, "")
            for vertex, screen in zip(mesh.vertices, points, strict=True):
                distance = math.hypot((screen - point).x(), (screen - point).y())
                if distance < closest_vertex[0]:
                    closest_vertex = distance, vertex.id
            return (closest_vertex[1],) if closest_vertex[1] else ()
        return ()

    def begin(self, event: QMouseEvent) -> None:
        """Start one gesture after hit testing the selected authoring tool."""
        model, point = self.model, event.position()
        if not model.mesh or not model.service:
            return
        model.editing_started.emit()
        self._gesture_context = self.context()
        self._soft_weights = None
        self._soft_frames = {}
        extend = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if model.tool == "soft":
            self.begin_soft_drag(point)
        elif model.tool == "area_pin":
            picked = self.pin_pick(point) if self.pin_pick is not None else ""
            if picked and picked != model.mesh_id:
                model.select_mesh(picked)
            scene_point = self.viewport.scene_point(point)
            assert model.document is not None
            document = model.document
            model.run(
                lambda _: SkinService(document).area_pin_at(
                    model.mesh_id,
                    (scene_point.x(), scene_point.y()),
                    self.pin_bone,
                    self.pin_radius,
                )
            )
        elif model.tool == "insert":
            local = self.local(point)
            model.run(lambda s: s.insert(model.mesh_id, local.x(), local.y()))
        elif model.tool == "paint":
            self.painting = True
            self.dab(point)
        elif model.tool == "control":
            handles = self.handles()
            frame = self.control_box(handles)
            if frame:
                for handle_index, (screen, local, anchor) in enumerate(frame[1]):
                    if (screen - point).manhattanLength() < 10:
                        values = self.control_values(handles)
                        self.drag = self.local(point), values
                        self.scale = ControlScale(
                            frame[0].center()
                            if handle_index == 8
                            or self.panel.control_mode.currentText() == "Rotate"
                            else anchor,
                            local,
                            self.local(point) - local,
                            {
                                i: self.local(handles[i][2])
                                for i in model.controls
                                if i < len(handles)
                            },
                            handle_index == 8 or self.panel.control_mode.currentText() == "Rotate",
                            handle=handle_index,
                            resize_cursor=transform_gizmo.cursor(
                                handle_index, self.viewport.icons, [p[0] for p in frame[1]]
                            ),
                        )
                        return
            nearest = min(
                range(len(handles)),
                key=lambda i: (handles[i][2] - point).manhattanLength(),
                default=-1,
            )
            if nearest >= 0 and (handles[nearest][2] - point).manhattanLength() < 16:
                if extend:
                    model.controls = (
                        tuple(i for i in model.controls if i != nearest)
                        if nearest in model.controls
                        else (*model.controls, nearest)
                    )
                elif nearest not in model.controls:
                    model.controls = (nearest,)
                values = self.control_values(handles)
                self.drag = self.local(point), values
                model.changed.emit()
            elif frame and frame[0].contains(self.local(point)) and not extend:
                self.drag = self.local(point), self.control_values(handles)
            else:
                self.marquee = point, point
                self.marquee_extend = extend
        else:
            frame = self.vertex_box()
            if frame:
                for handle_index, (screen, local, anchor) in enumerate(frame[1]):
                    if (screen - point).manhattanLength() < 10:
                        session = model.document.animation if model.document else None
                        sampled = (
                            session.evaluator.mesh_values(session.pose.frame) if session else {}
                        )
                        values = {
                            (v.id, axis): sampled.get((v.id, axis), getattr(v, axis))
                            for v in model.mesh.vertices
                            if v.id in model.selected and not v.protected
                            for axis in ("x", "y")
                        }
                        self.drag = self.local(point), values
                        self.scale = ControlScale(
                            frame[0].center()
                            if handle_index == 8 or model.transform_mode == "rotate"
                            else anchor,
                            local,
                            self.local(point) - local,
                            {
                                i: self.local(p)
                                for i, (v, p) in enumerate(
                                    zip(model.mesh.vertices, self.points(), strict=True)
                                )
                                if v.id in model.selected and not v.protected
                            },
                            handle_index == 8 or model.transform_mode == "rotate",
                            tuple(v.id for v in model.mesh.vertices),
                            handle=handle_index,
                            resize_cursor=transform_gizmo.cursor(
                                handle_index, self.viewport.icons, [p[0] for p in frame[1]]
                            ),
                        )
                        return
            hit = self.pick(point)
            if not hit or extend or not set(hit).issubset(model.selected):
                model.select(hit, extend)
            if hit:
                session = model.document.animation if model.document else None
                sampled = session.evaluator.mesh_values(session.pose.frame) if session else {}
                values = {
                    (v.id, axis): sampled.get((v.id, axis), getattr(v, axis))
                    for v in model.mesh.vertices
                    if v.id in model.selected and not v.protected
                    for axis in ("x", "y")
                }
                self.drag = self.local(point), values
            else:
                self.marquee = point, point
                self.marquee_extend = extend

    def begin_soft_drag(self, point: QPointF) -> None:
        """Grab a fixed weighted neighborhood in displayed pixels without requiring a dot hit."""
        model = self.model
        assert model.mesh is not None and model.document is not None
        handles = self.handles()
        sampled = model.document.animation.evaluator.mesh_values(
            model.document.animation.pose.frame
        )
        if handles:
            positions = {i: (h[2].x(), h[2].y()) for i, h in enumerate(handles)}
            channels = {i: ((h[0], h[3]), (h[1], h[4])) for i, h in enumerate(handles)}
        else:
            positions = {
                i: (p.x(), p.y())
                for i, (v, p) in enumerate(zip(model.mesh.vertices, self.points(), strict=True))
                if not v.protected and not v.pinned
            }
            channels = {
                i: (
                    ((v.id, "x"), sampled.get((v.id, "x"), v.x)),
                    ((v.id, "y"), sampled.get((v.id, "y"), v.y)),
                )
                for i, v in enumerate(model.mesh.vertices)
            }
        weights = soft_drag_weights(
            positions,
            (point.x(), point.y()),
            self.soft_radius,
            self.soft_strength,
            self.soft_falloff,
        )
        self._soft_weights = {
            key: weight for i, weight in weights.items() for key, _ in channels[i]
        }
        if self._soft_weights:
            values = {key: value for i in weights for key, value in channels[i]}
            self.drag = self.local(point), values

    def control_values(
        self, handles: list[tuple[tuple[str, str], tuple[str, str], QPointF, float, float]]
    ) -> dict[tuple[str, str], float]:
        """Capture only the selected control channels as an immutable gesture baseline."""
        return {
            key: value
            for i in self.model.controls
            if i < len(handles)
            for key, value in ((handles[i][0], handles[i][3]), (handles[i][1], handles[i][4]))
        }

    def control_box(
        self, handles: list[tuple[tuple[str, str], tuple[str, str], QPointF, float, float]]
    ) -> tuple[QRectF, list[tuple[QPointF, QPointF, QPointF]]] | None:
        """Return local selection bounds and eight padded screen handles with opposite anchors."""
        points = [self.local(handles[i][2]) for i in self.model.controls if i < len(handles)]
        return self.selection_box(points)

    def vertex_box(self) -> tuple[QRectF, list[tuple[QPointF, QPointF, QPointF]]] | None:
        """Provide the same transform handles for selected ordinary mesh vertices."""
        mesh, pose = self.model.mesh, self.model.pose
        selected = set(self.model.selected)
        return (
            self.selection_box(
                [
                    QPointF(*p)
                    for v, p in zip(mesh.vertices, pose.meshes[mesh.id].positions, strict=True)
                    if v.id in selected and not v.protected
                ]
            )
            if mesh and pose and mesh.id in pose.meshes
            else None
        )

    def selection_box(
        self, points: list[QPointF]
    ) -> tuple[QRectF, list[tuple[QPointF, QPointF, QPointF]]] | None:
        """Share eight resize handles and opposite anchors between vertices and field controls."""
        if len(points) < 2:
            return None
        xs, ys = [p.x() for p in points], [p.y() for p in points]
        rect = QRectF(QPointF(min(xs), min(ys)), QPointF(max(xs), max(ys)))
        matrix = self.matrix()
        px = 12 / max(1e-9, self.viewport.zoom * math.hypot(matrix[0], matrix[1]))
        py = 12 / max(1e-9, self.viewport.zoom * math.hypot(matrix[2], matrix[3]))
        padded = rect.adjusted(-px, -py, px, py)
        handles_out = []
        for x, y in ((0, 0), (0.5, 0), (1, 0), (1, 0.5), (1, 1), (0.5, 1), (0, 1), (0, 0.5)):
            local = QPointF(rect.left() + x * rect.width(), rect.top() + y * rect.height())
            anchor = QPointF(rect.right() - x * rect.width(), rect.bottom() - y * rect.height())
            screen = self.screen(
                (padded.left() + x * padded.width(), padded.top() + y * padded.height()), matrix
            )
            handles_out.append((screen, local, anchor))
        top = handles_out[1][0]
        center = self.screen((rect.center().x(), rect.center().y()), matrix)
        direction = top - center
        length = max(1e-9, math.hypot(direction.x(), direction.y()))
        rotation = top + direction * (24 / length)
        handles_out.append((rotation, self.local(rotation), rect.center()))
        return rect, handles_out

    def finish_marquee(self, position: QPointF) -> None:
        """Select FFD/pin controls or mesh vertices inside the current drag rectangle."""
        assert self.marquee is not None
        rect = QRectF(self.marquee[0], position).normalized()
        self.marquee = None
        if self.model.tool == "control":
            chosen = tuple(i for i, handle in enumerate(self.handles()) if rect.contains(handle[2]))
            self.model.controls = tuple(
                dict.fromkeys((*(self.model.controls if self.marquee_extend else ()), *chosen))
            )
            self.model.changed.emit()
        elif self.model.mesh:
            chosen_vertices = tuple(
                v.id
                for v, point in zip(self.model.mesh.vertices, self.points(), strict=True)
                if rect.contains(point)
            )
            self.model.select(chosen_vertices, self.marquee_extend)

    def dab(self, point: QPointF) -> None:
        """Preview one normalized weight brush dab without appending a document history entry."""
        model, panel = self.model, self.panel
        mesh, pose = model.preview_mesh or model.mesh, model.pose
        bone = panel.bones.currentData()
        if mesh is None or pose is None or not bone:
            raise ProjectError("Bind artwork and select a bone before painting weights.")
        stage = (
            next(
                (
                    d
                    for d in model.service.scene.deformers
                    if d.owner_id == mesh.id and d.kind == "skinning"
                ),
                None,
            )
            if model.service
            else None
        )
        if stage is None or bone not in stage.parameters.get("bind_matrices", {}):
            raise ProjectError("Bind the selected bone to this mesh before painting.")
        center = self.viewport.scene_point(point)
        model.preview_mesh = weight_brush(
            mesh,
            SkinService.positions(mesh, pose),
            (center.x(), center.y()),
            str(bone),
            panel.radius.value(),
            panel.strength.value(),
            cast(BrushOperation, panel.operation.currentText()),
            panel.limit.value(),
        )
        self.viewport.update()
        model.changed.emit()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Route authoring input while preserving ordinary viewport navigation."""
        model, viewport = self.model, self.viewport
        if (self.drag or self.painting or self.marquee) and (
            not model.active or self._gesture_context != self.context()
        ):
            self.drag, self.painting, self.marquee, self.scale = None, False, None, None
            model.cancel_preview()
        if event.type() == QEvent.Type.FocusOut:
            self.drag, self.painting = None, False
            self.marquee, self.scale = None, None
            if model.preview_values or model.preview_mesh:
                model.cancel_preview()
        if not model.active or model.mesh is None:
            return False
        if isinstance(event, QMouseEvent):
            if (
                viewport.pan_tool
                or viewport._space
                or viewport._drag is not None
                or event.button() == Qt.MouseButton.MiddleButton
                or event.buttons() & Qt.MouseButton.MiddleButton
            ):
                return False
            viewport.refresh_cursor(event.position())
        try:
            if isinstance(event, QKeyEvent) and event.type() == QEvent.Type.KeyPress:
                if event.key() == Qt.Key.Key_Escape:
                    self.drag, self.painting = None, False
                    self.marquee, self.scale = None, None
                    model.cancel_preview()
                    return True
                if (
                    event.key() == Qt.Key.Key_A
                    and event.modifiers() & Qt.KeyboardModifier.ControlModifier
                ):
                    self.panel.select_all()
                    return True
                if event.key() == Qt.Key.Key_Delete:
                    model.run(lambda s: s.delete(model.mesh_id, set(model.selected)))
                    return True
            if not isinstance(event, QMouseEvent):
                return False
            if (
                event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
                and not (viewport._space or viewport.pan_tool)
            ):
                viewport.setFocus()
                self.begin(event)
                if self.drag and model.document:
                    session = model.document.animation
                    plan = session.evaluator.deformation
                    if any(owner in plan.vertices for owner, _ in self.drag[1]) and any(
                        s.enabled for s in plan.stages[model.mesh_id]
                    ):
                        self._soft_frames = plan.vertex_drag_frames(
                            model.mesh,
                            session.pose.nodes,
                            session.evaluator.mesh_values(session.pose.frame),
                        )
                self.cursor = event.position()
                viewport.refresh_cursor(event.position())
                return True
            if event.type() == QEvent.Type.MouseMove:
                previous, self.cursor = self.cursor, event.position()
                if self.marquee:
                    self.marquee = self.marquee[0], event.position()
                    viewport.update()
                    return True
                if self.drag:
                    self.update_drag(event.position(), event.modifiers())
                    viewport.set_pose(model.pose)
                    viewport.update()
                    return True
                if self.painting:
                    delta = event.position() - previous if previous is not None else QPointF()
                    count = min(
                        64,
                        max(
                            1,
                            math.ceil(
                                math.hypot(delta.x(), delta.y())
                                / max(1, self.panel.radius.value() * viewport.zoom * 0.25)
                            ),
                        ),
                    )
                    for i in range(count):
                        self.dab(event.position() - delta * (1 - (i + 1) / count))
                    return True
                viewport.update()
            if (
                event.type() == QEvent.Type.MouseButtonRelease
                and event.button() == Qt.MouseButton.LeftButton
                and (self.drag or self.painting or self.marquee)
            ):
                if self.marquee:
                    self.finish_marquee(event.position())
                    viewport.refresh_cursor(event.position())
                    viewport.update()
                    return True
                if self.drag:
                    self.update_drag(event.position(), event.modifiers())
                self.drag, self.painting = None, False
                self.scale = None
                model.finish_preview()
                viewport.refresh_cursor(event.position())
                return True
        except (ProjectError, ValueError) as error:
            self.drag, self.painting = None, False
            self.marquee, self.scale = None, None
            model.error = str(error)
            model.cancel_preview()
            return True
        return False

    def context(self) -> tuple[object, ...]:
        """Identify the document, revision, time and editor selection owning a pending gesture."""
        model = self.model
        return (
            model.document,
            model.document.project if model.document else None,
            model.mesh_id,
            model.stage_id,
            model.tool,
            model.transform_mode,
            model.document.animation.pose.frame
            if model.document and model.document.project
            else None,
        )

    def update_drag(
        self, position: QPointF, modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier
    ) -> None:
        """Preview a local displacement, including release positions without a final move event."""
        if self.drag is None:
            return
        start, values = self.drag
        if (self.local(position) - start).manhattanLength() <= 1e-9:
            self.model.preview_values = {}
            return
        if self.scale:
            scale = self.scale
            point = self.local(position) - scale.offset
            dx, dy = scale.start.x() - scale.anchor.x(), scale.start.y() - scale.anchor.y()
            sx = (point.x() - scale.anchor.x()) / dx if abs(dx) > 1e-9 else 1
            sy = (point.y() - scale.anchor.y()) / dy if abs(dy) > 1e-9 else 1
            handles = self.handles()
            self.model.preview_values = {}
            for i, original in scale.points.items():
                if i >= (len(scale.vertex_ids) if scale.vertex_ids else len(handles)):
                    continue
                transformed = QPointF(
                    scale.anchor.x() + (original.x() - scale.anchor.x()) * sx,
                    scale.anchor.y() + (original.y() - scale.anchor.y()) * sy,
                )
                if scale.rotation:
                    angle = math.atan2(
                        point.y() - scale.anchor.y(), point.x() - scale.anchor.x()
                    ) - math.atan2(
                        scale.start.y() - scale.anchor.y(), scale.start.x() - scale.anchor.x()
                    )
                    if modifiers & Qt.KeyboardModifier.ShiftModifier:
                        angle = math.radians(round(math.degrees(angle) / 15) * 15)
                    vx, vy = original.x() - scale.anchor.x(), original.y() - scale.anchor.y()
                    transformed = scale.anchor + QPointF(
                        vx * math.cos(angle) - vy * math.sin(angle),
                        vx * math.sin(angle) + vy * math.cos(angle),
                    )
                delta = transformed - original
                xkey = (scale.vertex_ids[i], "x") if scale.vertex_ids else handles[i][0]
                ykey = (scale.vertex_ids[i], "y") if scale.vertex_ids else handles[i][1]
                if scale.vertex_ids and self._soft_frames:
                    frame = self._soft_frames.get(xkey[0], (1, 0, 0, 1, 0, 0))
                    delta = QPointF(*transform_point(frame, delta.x(), delta.y()))
                for key, offset in ((xkey, delta.x()), (ykey, delta.y())):
                    self.model.preview_values[key] = values[key] + offset
            return
        delta = self.local(position) - start
        if self._soft_frames:
            self.model.preview_values = {}
            for key, value in values.items():
                frame = self._soft_frames.get(key[0], (1, 0, 0, 1, 0, 0))
                dx, dy = transform_point(frame, delta.x(), delta.y())
                weight = self._soft_weights.get(key, 0) if self._soft_weights is not None else 1
                self.model.preview_values[key] = value + (dx if key[1] == "x" else dy) * weight
            return
        self.model.preview_values = (
            {
                key: value
                + (delta.x() if key[1].endswith(("x", ".0")) else delta.y())
                * (self._soft_weights.get(key, 0) if self._soft_weights is not None else 1)
                for key, value in values.items()
            }
            if delta.manhattanLength() > 1e-9
            else {}
        )

    def draw_topology(self, painter: QPainter, mesh: Mesh, points: Sequence[QPointF]) -> None:
        """Replay native drawing commands for unchanged topology, selection and weight colors.

        The picture contains zoomed scene coordinates, so panning needs only a translation.
        Geometry, zoom, theme, selection, vertex flags and heatmap inputs rebuild the picture.
        Field controls and the live brush cursor remain independently interactive.
        """
        model, viewport, pose = self.model, self.viewport, self.model.pose
        if pose is None:
            return
        bone = (
            self.panel.bones.currentData()
            if self.panel.heatmap.isChecked() and model.tool == "paint"
            else None
        )
        signature = (
            mesh,
            pose.meshes[mesh.id],
            pose.nodes.get(mesh.object_id or ""),
            viewport.zoom,
            viewport.devicePixelRatioF(),
            viewport.theme,
            model.selected,
            bone,
        )
        if self._topology_picture is None or signature != self._topology_signature:
            colors = PALETTES[viewport.theme]
            local = tuple(point - viewport.offset for point in points)
            picture = QPicture()
            target = QPainter(picture)
            target.setRenderHint(QPainter.RenderHint.Antialiasing)
            target.setPen(QPen(QColor(colors["muted"]), 0.8))
            target.drawLines(
                [
                    QLineF(local[a], local[b])
                    for a, b in triangle_edges(pose.meshes[mesh.id].triangles)
                ]
            )
            selected = set(model.selected)
            markers: dict[tuple[bool, float | None, bool], list[QPointF]] = {}
            flags: dict[bool, list[QLineF]] = {False: [], True: []}
            for vertex, point in zip(mesh.vertices, local, strict=True):
                weight = vertex.weights.get(bone, 0) if bone is not None else None
                chosen = vertex.id in selected
                markers.setdefault((chosen, weight, vertex.pinned), []).append(point)
                if vertex.protected:
                    flags[chosen].append(QLineF(point - QPointF(4, 4), point + QPointF(4, 4)))
            for (chosen, weight, pinned), dots in sorted(
                markers.items(), key=lambda item: item[0][0]
            ):
                fill = (
                    QColor.fromRgbF(weight, weight, weight)
                    if weight is not None
                    else QColor(colors["canvas"])
                )
                radius = 6 if weight is not None else 4 if chosen else 2.5
                border = 2 if chosen else 1
                cap = Qt.PenCapStyle.SquareCap if pinned else Qt.PenCapStyle.RoundCap
                for tone, width in (
                    (QColor(colors["text"] if chosen else colors["muted"]), radius * 2 + border),
                    (fill, radius * 2 - border),
                ):
                    pen = QPen(tone, width)
                    pen.setCapStyle(cap)
                    target.setPen(pen)
                    target.drawPoints(dots)
            for chosen, lines in flags.items():
                target.setPen(
                    QPen(QColor(colors["text"] if chosen else colors["muted"]), 2 if chosen else 1)
                )
                target.drawLines(lines)
            target.end()
            self._topology_signature, self._topology_picture = signature, picture
            self._topology_tile = None
        visible = QRectF(viewport.rect()).translated(-viewport.offset)
        bounds = QRectF(self._topology_picture.boundingRect())
        if not bounds.intersects(visible):
            return
        if self._topology_tile is None or not self._topology_coverage.contains(
            bounds.intersected(visible)
        ):
            rect = bounds.toAlignedRect()
            if (
                rect.width() * rect.height() * viewport.devicePixelRatioF() ** 2 * 4 > 16 * 1024**2
                or max(rect.width(), rect.height()) > 8192
            ):
                rect = bounds.intersected(visible.adjusted(-128, -128, 128, 128)).toAlignedRect()
            tile = QPixmap(
                round(rect.width() * viewport.devicePixelRatioF()),
                round(rect.height() * viewport.devicePixelRatioF()),
            )
            tile.setDevicePixelRatio(viewport.devicePixelRatioF())
            tile.fill(Qt.GlobalColor.transparent)
            target = QPainter(tile)
            target.drawPicture(-QPointF(rect.topLeft()), self._topology_picture)
            target.end()
            self._topology_tile, self._topology_coverage = tile, QRectF(rect)
        painter.drawPixmap(viewport.offset + self._topology_coverage.topLeft(), self._topology_tile)

    def draw(self, painter: QPainter) -> None:
        """Draw topology, vertex flags, neutral weights and field controls."""
        model, mesh, viewport = (
            self.model,
            self.model.preview_mesh or self.model.mesh,
            self.viewport,
        )
        if not model.active or mesh is None:
            return
        if model.tool == "area_pin" and viewport.pin_overlay is not None:
            return
        colors = PALETTES[viewport.theme]
        points = self.points()
        if not points:
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.draw_topology(painter, mesh, points)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for pin in mesh.extra.get("area_pins", ()) if viewport.pin_overlay is None else ():
            anchor = next(
                (points[i] for i, v in enumerate(mesh.vertices) if v.id == pin["vertex_id"]), None
            )
            if anchor is not None:
                painter.setPen(QPen(QColor(colors["text"]), 2))
                painter.drawEllipse(anchor, 5, 5)
                painter.drawLine(anchor - QPointF(8, 0), anchor + QPointF(8, 0))
                painter.drawLine(anchor - QPointF(0, 8), anchor + QPointF(0, 8))
        if model.stage_id and model.service:
            try:
                handles = self.handles()
                stage = model.service.stage(model.stage_id)
                painter.setPen(QPen(QColor(colors["text"]), 1, Qt.PenStyle.DashLine))
                if stage.kind in ("ffd", "lattice"):
                    columns, rows, _ = lattice_controls(self.parameters())
                    for i in range(len(handles)):
                        for j in (
                            i + 1 if i % columns < columns - 1 else -1,
                            i + columns if i // columns < rows - 1 else -1,
                        ):
                            if j >= 0:
                                painter.drawLine(handles[i][2], handles[j][2])
                for i, (_, _, point, _, _) in enumerate(handles):
                    painter.setPen(QPen(QColor(colors["text"]), 2 if i in model.controls else 1))
                    painter.setBrush(
                        QColor(colors["text"] if i in model.controls else colors["panel"])
                    )
                    painter.drawEllipse(
                        point, 5 if i in model.controls else 4, 5 if i in model.controls else 4
                    )
                frame = self.control_box(handles) if model.tool == "control" else None
                if frame:
                    corners = [frame[1][i][0] for i in (0, 2, 4, 6)]
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.setPen(QPen(QColor(colors["text"]), 1, Qt.PenStyle.DashLine))
                    painter.drawPolygon(QPolygonF(corners))
                    painter.setBrush(QColor(colors["panel"]))
                    painter.drawLine(frame[1][1][0], frame[1][8][0])
                    for index, (point, _, _) in enumerate(frame[1]):
                        if index == 8:
                            painter.drawEllipse(point, 4, 4)
                        else:
                            painter.drawRect(QRectF(point - QPointF(3, 3), point + QPointF(3, 3)))
            except ProjectError:
                pass
        if model.tool in ("vertex", "edge", "triangle"):
            frame = self.vertex_box()
            if frame:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor(colors["text"]), 1, Qt.PenStyle.DashLine))
                painter.drawPolygon(QPolygonF([frame[1][i][0] for i in (0, 2, 4, 6)]))
                painter.setBrush(QColor(colors["panel"]))
                painter.drawLine(frame[1][1][0], frame[1][8][0])
                for index, (point, _, _) in enumerate(frame[1]):
                    if index == 8:
                        painter.drawEllipse(point, 4, 4)
                    else:
                        painter.drawRect(QRectF(point - QPointF(4, 4), point + QPointF(4, 4)))
        if model.tool in ("paint", "soft") and self.cursor is not None:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(colors["text"]), 1))
            radius = (
                self.soft_radius
                if model.tool == "soft"
                else self.panel.radius.value() * viewport.zoom
            )
            painter.drawEllipse(self.cursor, radius, radius)
            if model.tool == "soft":
                painter.setPen(QPen(QColor(colors["muted"]), 1, Qt.PenStyle.DotLine))
                painter.drawEllipse(self.cursor, radius * 0.5, radius * 0.5)
        if self.marquee:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(colors["text"]), 1, Qt.PenStyle.DashLine))
            painter.drawRect(QRectF(*self.marquee).normalized())
