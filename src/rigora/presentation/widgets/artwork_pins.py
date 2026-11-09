"""Visual setup controls for Object-relative and bone-attached artwork pins."""

from collections import defaultdict
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QEvent, QObject, QPointF, QSignalBlocker, Qt
from PySide6.QtGui import QColor, QCursor, QKeyEvent, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QLabel

from rigora.application_services.area_pins import AreaPinService
from rigora.application_services.scene_editing import SceneEditingService
from rigora.domain.geometry import transform_point
from rigora.domain.project import ProjectError
from rigora.presentation.themes import PALETTES

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow
    from rigora.presentation.widgets.composer_editors import BoneEditor

type PinKey = tuple[str, str]


class ArtworkPins(QGroupBox):
    """Own transient pin selection and setup drags without intercepting navigation or posing."""

    def __init__(self, window: "MainWindow", editor: "BoneEditor") -> None:
        """Use canonical services for mutations and retain only bounded screen-space overlays."""
        super().__init__("Artwork pins", editor)
        self.host, self.editor, self.document = window, editor, editor.document
        self.selected: tuple[PinKey, ...] = ()
        self.editable = True
        self.drag: tuple[QPointF, dict[PinKey, QPointF], object] | None = None
        self.delta = QPointF()
        self._drag_view: tuple[object, ...] = ()
        self.pointer: QPointF | None = None
        self._marker_key: tuple[Any, ...] = ()
        self._marker_pose: object = None
        self._markers: list[tuple[PinKey, Any, QPointF]] = []
        self._bones: tuple[str, ...] = ()
        form = QFormLayout(self)
        self.target = QComboBox()
        self.target.setAccessibleName("Pin attachment target")
        self.target.addItem("Object root", None)
        form.addRow("Attach to", self.target)
        self.radius = QDoubleSpinBox()
        self.radius.setRange(1, 2000)
        self.radius.setValue(50)
        self.radius.setSuffix(" px")
        self.radius.setAccessibleName("Pin influence radius")
        self.radius.setKeyboardTracking(False)
        form.addRow("Radius", self.radius)
        self.strength = QDoubleSpinBox()
        self.strength.setRange(0, 100)
        self.strength.setValue(100)
        self.strength.setSuffix(" %")
        self.strength.setAccessibleName("Pin influence strength")
        self.strength.setKeyboardTracking(False)
        form.addRow("Strength", self.strength)
        self.summary = QLabel("Click a pin to edit. Ctrl-click selects several.")
        self.summary.setWordWrap(True)
        form.addRow(self.summary)
        self.target.currentIndexChanged.connect(self.change_target)
        self.radius.editingFinished.connect(
            lambda: self.change_properties(radius=self.radius.value())
        )
        self.strength.editingFinished.connect(
            lambda: self.change_properties(strength=self.strength.value() / 100)
        )
        self.radius.valueChanged.connect(lambda _: window.viewport.update())
        window.viewmodel.changed.connect(self.refresh)
        window.viewmodel.rig.changed.connect(self.bone_selection)
        self.install_overlay()
        window.viewport.installEventFilter(self)
        self.refresh()

    def available(self) -> bool:
        """Keep modeless editor controls isolated from other documents and read-only previews."""
        return bool(
            self.editor.isVisible()
            and self.document is self.host.viewmodel.documents
            and self.document.project
            and self.host.viewport.subdivision_pose is None
        )

    def install_overlay(self) -> None:
        """Expose independent pin drawing/cursors while the modeless editor owns them."""
        self.host.viewport.pin_overlay = self.draw
        self.host.viewport.pin_cursor = self.cursor_at

    def detach(self) -> None:
        """Release bound callbacks before the owning dialog can be deleted or replaced."""
        self.drag = None
        if self.host.viewport.pin_overlay == self.draw:
            self.host.viewport.pin_overlay = None
            self.host.viewport.pin_cursor = None
        self.host.viewport.update()

    def refresh(self) -> None:
        """Reconcile targets and selection only after authoring changes, never on pointer moves."""
        if self.document is not self.host.viewmodel.documents or not self.document.project:
            self.selected, self.drag = (), None
            return
        target = self.target.currentData()
        with QSignalBlocker(self.target):
            self.target.clear()
            self.target.addItem("Object root", None)
            for rig in self.document.scene.skeletons:
                for bone in rig.bones:
                    self.target.addItem(bone.name, bone.id)
            self.target.setCurrentIndex(max(0, self.target.findData(target)))
        existing = {
            (mesh.id, p["vertex_id"])
            for mesh in self.document.scene.meshes
            for p in mesh.extra.get("area_pins", ())
        }
        self.selected = tuple(key for key in self.selected if key in existing)
        self.selection_controls()

    def bone_selection(self) -> None:
        """Allow a newly selected bone to change the active placement target immediately."""
        selected = self.host.viewmodel.rig.selected
        model = self.host.viewmodel.mesh
        if selected != self._bones and selected and model.active and model.tool == "area_pin":
            index = self.target.findData(selected[0])
            if index >= 0:
                self.target.setCurrentIndex(index)
        self._bones = selected

    def selection_controls(self) -> None:
        """Show selected pin properties without treating display synchronization as edits."""
        if not self.selected:
            self.summary.setText("Click a pin to edit. Ctrl-click selects several.")
            return
        mesh_id, vertex_id = self.selected[0]
        mesh = AreaPinService(self.document).mesh(mesh_id)
        pin = next(p for p in mesh.extra["area_pins"] if p["vertex_id"] == vertex_id)
        with (
            QSignalBlocker(self.target),
            QSignalBlocker(self.radius),
            QSignalBlocker(self.strength),
        ):
            target = None if pin.get("target_kind") == "object" else pin["bone_id"]
            self.target.setCurrentIndex(max(0, self.target.findData(target)))
            self.radius.setValue(pin["radius"])
            self.strength.setValue(pin.get("strength", 1) * 100)
        self.summary.setText(f"{len(self.selected)} selected · {self.target.currentText()}")

    def change_target(self) -> None:
        """Retarget selected pins or update the default for subsequent placement clicks."""
        self.change_properties(bone_id=self.target.currentData())

    def change_properties(self, **values: Any) -> None:
        """Publish a multi-mesh property edit as one undoable action."""
        if not self.available() or not self.selected:
            return
        grouped: dict[str, list[str]] = defaultdict(list)
        for mesh_id, vertex_id in self.selected:
            grouped[mesh_id].append(vertex_id)

        def apply(_: Any) -> None:
            with self.document.command_group("Edit artwork pins"):
                for mesh_id, vertices in grouped.items():
                    AreaPinService(self.document).update_area_pins(
                        mesh_id, tuple(vertices), **values
                    )

        self.host.viewmodel.mesh.run(apply)
        self.selection_controls()

    def markers(self) -> list[tuple[PinKey, Any, QPointF]]:
        """Cache visible, unlocked markers for all layers by displayed pose and navigation."""
        view, doc = self.host.viewport, self.document
        pose = view.pose
        if not self.available() or pose is None:
            return []
        signature = (id(doc.scene.meshes), id(pose), view.zoom, view.offset.x(), view.offset.y())
        if signature == self._marker_key:
            return self._markers
        result = []
        locks = SceneEditingService(doc)
        for mesh in doc.scene.meshes:
            pins = mesh.extra.get("area_pins", ())
            node = pose.nodes.get(mesh.object_id or "")
            if (
                not pins
                or mesh.id not in pose.meshes
                or not node
                or not node.visible
                or locks.locked(mesh.id)
                or mesh.object_id
                and locks.locked(mesh.object_id)
            ):
                continue
            points = dict(
                zip((v.id for v in mesh.vertices), pose.meshes[mesh.id].positions, strict=True)
            )
            for pin in pins:
                key = (mesh.id, pin["vertex_id"])
                if pin["vertex_id"] in points:
                    p = transform_point(node.world_matrix, *points[pin["vertex_id"]])
                    result.append((key, pin, QPointF(*p) * view.zoom + view.offset))
        self._marker_key, self._marker_pose, self._markers = signature, pose, result
        return result

    def pick(self, point: QPointF) -> PinKey | None:
        """Give an existing pin a constant screen-space hit area before artwork placement."""
        return next(
            (key for key, _, p in reversed(self.markers()) if (p - point).manhattanLength() < 14),
            None,
        )

    def navigation(self) -> tuple[object, ...]:
        """Guard a pending setup gesture against time, zoom, pan and editing-context changes."""
        view = self.host.viewport
        return (
            self.document.context_key,
            self.document.animation.pose.frame,
            view.zoom,
            view.offset.x(),
            view.offset.y(),
        )

    def cursor_at(self, point: QPointF) -> QCursor | None:
        """Advertise pin editing only where a real handle or active placement tool exists."""
        if not self.available() or not self.editable:
            return None
        model = self.host.viewmodel.mesh
        if self.drag or self.pick(point):
            return QCursor(Qt.CursorShape.SizeAllCursor)
        return (
            QCursor(Qt.CursorShape.CrossCursor)
            if model.active and model.tool == "area_pin"
            else None
        )

    def remove(self) -> None:
        """Delete only selected anchors; preserve vertices, skin weights and Object ownership."""
        if not self.selected:
            return
        grouped: dict[str, list[str]] = defaultdict(list)
        for mesh_id, vertex_id in self.selected:
            grouped[mesh_id].append(vertex_id)

        def apply(_: Any) -> None:
            with self.document.command_group("Remove artwork pins"):
                for mesh_id, vertices in grouped.items():
                    AreaPinService(self.document).remove_area_pins(mesh_id, tuple(vertices))

        self.host.viewmodel.mesh.run(apply)
        self.selected = ()
        self.selection_controls()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Route setup gestures ahead of bones; keep pan, zoom, Pose and cancellation standard."""
        view, model = self.host.viewport, self.host.viewmodel.mesh
        if not self.available() or not self.editable:
            return False
        if event.type() == QEvent.Type.FocusOut:
            self.drag = None
            self.delta = QPointF()
            view.update()
        if isinstance(event, QKeyEvent) and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape and (self.drag or self.selected):
                self.drag, self.selected = None, ()
                self.selection_controls()
                view.update()
                return True
            if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.selected:
                self.remove()
                return True
        if (
            not isinstance(event, QMouseEvent)
            or view.pan_tool
            or view._space
            or event.buttons() & Qt.MouseButton.MiddleButton
        ):
            return False
        adding = model.active and model.tool == "area_pin"
        try:
            if (
                event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
            ):
                point = event.position()
                key = self.pick(point)
                if key:
                    extend = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
                    if extend:
                        self.selected = (
                            tuple(k for k in self.selected if k != key)
                            if key in self.selected
                            else (*self.selected, key)
                        )
                    elif key not in self.selected:
                        self.selected = (key,)
                    self.selection_controls()
                    origins = {k: p for k, _, p in self.markers() if k in self.selected}
                    self.drag = (point, origins, self.document.project) if origins else None
                    self._drag_view = self.navigation()
                    self.delta = QPointF()
                    view.setFocus()
                    view.update()
                    return True
                if adding:
                    mesh_id = self.host.mesh_workspace.pin_artwork(point)
                    target = self.target.currentData()
                    scene = view.scene_point(point)
                    created = []
                    model.run(
                        lambda _: created.append(
                            AreaPinService(self.document).area_pin_at(
                                mesh_id,
                                (scene.x(), scene.y()),
                                target,
                                self.radius.value(),
                                self.strength.value() / 100,
                            )
                        )
                    )
                    if created:
                        self.selected = ((mesh_id, created[0]),)
                        model.select_mesh(mesh_id)
                        self.selection_controls()
                    self.editor.status.setText(
                        model.error
                        or "Pin added. Click again to place another; drag a pin to reposition."
                    )
                    view.setFocus()
                    view.update()
                    return True
                self.selected = ()
                self.selection_controls()
            elif event.type() == QEvent.Type.MouseMove:
                self.pointer = event.position()
                if self.drag:
                    self.delta = event.position() - self.drag[0]
                    view.refresh_cursor(event.position())
                    view.update()
                    return True
                if adding:
                    view.update()
            elif (
                event.type() == QEvent.Type.MouseButtonRelease
                and event.button() == Qt.MouseButton.LeftButton
                and self.drag
            ):
                start, origins, revision = self.drag
                delta = event.position() - start
                self.drag = None
                if (
                    delta.manhattanLength() > 2
                    and self.document.project is revision
                    and self._drag_view == self.navigation()
                ):
                    moved = []

                    def apply(_: Any) -> None:
                        with self.document.command_group("Move artwork pins"):
                            for (mesh_id, vertex_id), point in origins.items():
                                p = view.scene_point(point + delta)
                                key = AreaPinService(self.document).move_area_pin(
                                    mesh_id, vertex_id, (p.x(), p.y())
                                )
                                moved.append((mesh_id, key))

                    model.run(apply)
                    if not model.error:
                        self.selected = tuple(moved)
                self.selection_controls()
                self.delta = QPointF()
                view.refresh_cursor(event.position())
                view.update()
                return True
        except (ProjectError, ValueError) as error:
            self.drag = None
            self.editor.status.setText(str(error))
            return True
        return False

    def draw(self, painter: QPainter) -> None:
        """Show all pins, selected influence regions and their explicit attachment targets."""
        if not self.available():
            return
        view = self.host.viewport
        pose = view.pose
        if pose is None:
            return
        colors = PALETTES[view.theme]
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        model = self.host.viewmodel.mesh
        if self.editable and model.active and model.tool == "area_pin" and self.pointer is not None:
            painter.setPen(QPen(QColor(colors["muted"]), 1, Qt.PenStyle.DotLine))
            r = self.radius.value() * view.zoom
            painter.drawEllipse(self.pointer, r, r)
        for key, pin, source in self.markers():
            selected = key in self.selected
            point = source + self.delta if self.drag and key in self.drag[1] else source
            tone = QColor("#ed5555" if selected else colors["text"])
            painter.setPen(QPen(tone, 2))
            painter.setBrush(QColor(colors["canvas"]))
            painter.drawEllipse(point, 5, 5)
            painter.drawLine(point - QPointF(8, 0), point + QPointF(8, 0))
            painter.drawLine(point - QPointF(0, 8), point + QPointF(0, 8))
            if selected:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(tone, 1, Qt.PenStyle.DashLine))
                matrix = pose.nodes[
                    str(next(m.object_id for m in self.document.scene.meshes if m.id == key[0]))
                ].world_matrix
                painter.save()
                from PySide6.QtGui import QTransform

                painter.translate(point)
                a, b, c, d = (v * view.zoom for v in matrix[:4])
                painter.setWorldTransform(QTransform(a, b, c, d, 0, 0), True)
                painter.drawEllipse(QPointF(), pin["radius"], pin["radius"])
                painter.restore()
                target = pose.nodes.get(pin["bone_id"])
                if target and pin.get("target_kind") != "object":
                    painter.drawLine(
                        point, QPointF(*target.world_matrix[4:]) * view.zoom + view.offset
                    )
                painter.setPen(QPen(tone, 1))
                label = (
                    "Object root"
                    if pin.get("target_kind") == "object"
                    else target.name
                    if target
                    else "Missing target"
                )
                painter.drawText(point + QPointF(12, -12), label)
        painter.restore()
