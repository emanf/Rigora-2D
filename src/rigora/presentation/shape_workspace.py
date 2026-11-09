"""Viewport drag-to-draw of real SVG shapes with the normal navigation and undo model."""

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPen
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QComboBox, QHBoxLayout, QLabel, QWidget

from rigora.application_services.appearance import AppearanceService
from rigora.domain.project import ProjectError
from rigora.engine.vector_appearance import shape_svg
from rigora.presentation.transform_gizmo import modifiers_after

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


class ShapeWorkspace(QObject):
    """Own a toggled shape gesture without taking over bone or mesh selection tools."""

    def __init__(self, window: "MainWindow") -> None:
        """Install a small tool-options row and defer authored edits until release."""
        super().__init__(window)
        self.host = window
        self.active = False
        self.start: QPointF | None = None
        self.end: QPointF | None = None
        self.document: object = None
        self.modifiers = Qt.KeyboardModifier.NoModifier
        self.guide: QSvgRenderer | None = None
        self.guide_size: tuple[str, float, float] | None = None
        self.options = QWidget()
        row = QHBoxLayout(self.options)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel("Draw:"))
        self.kind = QComboBox()
        self.kind.addItems(["ellipse", "rectangle", "triangle", "diamond", "star"])
        row.addWidget(self.kind)
        self.kind.setAccessibleName("Vector shape to draw")
        self.options.setToolTip("Shift: equal width and height · Alt: draw from center · Esc: exit")
        window.viewport_header_layout.insertWidget(0, self.options)
        self.options.hide()
        window.viewport.installEventFilter(self)
        window.viewport.shape_overlay = self.draw
        window.viewmodel.changed.connect(self.check_document)
        window._tool_group.triggered.connect(lambda _: self.deactivate())
        window.viewmodel.rig.changed.connect(self.check_tool)
        window.viewmodel.mesh.changed.connect(self.check_tool)

    def toggle(self, active: bool | None = None) -> None:
        """Enter or leave drawing, restoring ordinary selection on repeated activation."""
        enabled = not self.active if active is None else active
        self.active = False
        self.start = self.end = None
        self.release_modifiers()
        self.host.navigate()
        if enabled:
            self.host.rig_workspace.set_mode(False)
            self.host.mesh_workspace.set_mode(False)
        if enabled and not self.host.viewmodel.documents.project:
            self.host.viewmodel.new_project()
        self.active = enabled
        self.options.setVisible(self.active)
        self.host.command_actions["draw_shape"].setChecked(self.active)
        self.document = self.host.viewmodel.documents
        self.host.viewport.update()

    def deactivate(self) -> None:
        """Release drawing when another tool is selected without recursively navigating."""
        self.active = False
        self.start = self.end = None
        self.release_modifiers()
        self.options.hide()
        self.host.command_actions["draw_shape"].setChecked(False)
        self.host.viewport.update()

    def check_document(self) -> None:
        """A tab change cancels a shape without leaking it into another project."""
        if self.document is not self.host.viewmodel.documents:
            self.toggle(False)

    def check_tool(self) -> None:
        """A specialized editor takes ownership immediately, including non-toolbar entry points."""
        vm = self.host.viewmodel
        if self.active and (vm.rig.active or vm.mesh.active):
            self.deactivate()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Reserve only shape-tool drags while letting middle/Space pan work normally."""
        if not self.active:
            return False
        vm, viewport = self.host.viewmodel, self.host.viewport
        if watched is not viewport and not isinstance(event, QKeyEvent):
            return False
        if isinstance(event, QKeyEvent) and event.key() == Qt.Key.Key_Escape:
            self.toggle(False)
            return True
        if isinstance(event, QKeyEvent) and event.key() in (Qt.Key.Key_Shift, Qt.Key.Key_Alt):
            if event.type() == QEvent.Type.ShortcutOverride:
                event.accept()
                return self.start is not None
            self.modifiers = modifiers_after(event)
            viewport.update()
            return True
        if event.type() == QEvent.Type.FocusOut:
            self.start = self.end = None
            self.release_modifiers()
            viewport.update()
        if (
            not isinstance(event, QMouseEvent)
            or viewport.pan_tool
            or viewport._space
            or event.buttons() & Qt.MouseButton.MiddleButton
        ):
            return False
        if vm.rig.active or vm.mesh.active or not self.host.command_actions["navigate"].isChecked():
            self.toggle(False)
            return False
        viewport.setCursor(Qt.CursorShape.CrossCursor)
        self.modifiers = event.modifiers()
        if (
            event.type() == QEvent.Type.MouseButtonPress
            and event.button() == Qt.MouseButton.LeftButton
        ):
            if not vm.documents.project:
                vm.new_project()
            viewport.setFocus()
            self.start = self.end = viewport.scene_point(event.position())
            if app := QApplication.instance():
                app.installEventFilter(self)
            return True
        if self.start is not None and event.type() == QEvent.Type.MouseMove:
            self.end = viewport.scene_point(event.position())
            viewport.update()
            return True
        if (
            self.start is not None
            and event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self.end = viewport.scene_point(event.position())
            rect = self.rectangle()
            self.start = self.end = None
            self.release_modifiers()
            if rect.width() >= 2 and rect.height() >= 2:
                try:
                    with vm.documents.command_group("Draw shape"):
                        key = AppearanceService(vm.documents).create_shape(
                            self.kind.currentText(), rect.x(), rect.y(), rect.width(), rect.height()
                        )
                        if self.host.object_edit.active:
                            self.host.object_edit.adoption(recenter=False)(
                                vm.documents, {"mesh_ids": (key,)}
                            )
                    vm.changed.emit()
                    vm.mesh.select_mesh(key)
                    owner = AppearanceService(vm.documents).mesh(key).object_id
                    if owner:
                        vm.scene.select((owner,))
                    self.host.character_panel.show_page("skin")
                except ProjectError as error:
                    self.host.statusBar().showMessage(str(error), 8000)
            viewport.update()
            return True
        return False

    def release_modifiers(self) -> None:
        """Release application-level modifier capture at the end of a drawing gesture."""
        if app := QApplication.instance():
            app.removeEventFilter(self)

    def rectangle(self) -> QRectF:
        """Resolve one scene-space rectangle shared by live guides and the committed shape."""
        assert self.start is not None and self.end is not None
        delta = self.end - self.start
        if self.modifiers & Qt.KeyboardModifier.ShiftModifier:
            side = max(abs(delta.x()), abs(delta.y()))
            delta = QPointF(-side if delta.x() < 0 else side, -side if delta.y() < 0 else side)
        origin = (
            self.start - delta if self.modifiers & Qt.KeyboardModifier.AltModifier else self.start
        )
        return QRectF(origin, self.start + delta).normalized()

    def draw(self, painter: QPainter) -> None:
        """Show a light geometric placement guide before any SVG asset is created."""
        if self.start is None or self.end is None:
            return
        viewport = self.host.viewport
        scene_rect = self.rectangle()
        rect = QRectF(
            scene_rect.topLeft() * viewport.zoom + viewport.offset,
            scene_rect.bottomRight() * viewport.zoom + viewport.offset,
        )
        painter.setPen(QPen(QColor("#bcbcbc"), 1, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)
        if 2 <= scene_rect.width() <= 16384 and 2 <= scene_rect.height() <= 16384:
            signature = self.kind.currentText(), scene_rect.width(), scene_rect.height()
            if signature != self.guide_size:
                self.guide = QSvgRenderer(shape_svg(signature[1], signature[2], signature[0]))
                self.guide_size = signature
            if self.guide:
                painter.save()
                painter.setOpacity(0.65)
                self.guide.render(painter, rect)
                painter.restore()
