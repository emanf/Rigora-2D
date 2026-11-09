"""Drawn artwork stays editable in the composer's shared hierarchy without importing images."""

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from test_roots_soft_drag_gui import drag
from test_roots_soft_drag_gui import editor as editor

from rigora.application_services.appearance import AppearanceService

pytestmark = pytest.mark.gui


def test_drawn_shape_double_click_keeps_its_row_in_parts_and_bones(editor, qtbot):
    """A real draw/open gesture exposes the shape, preserves isolation, and survives rename/undo."""
    window, vm, viewport = editor, editor.viewmodel, editor.viewport
    viewport.zoom, viewport.offset = 1, QPointF(20, 30)
    window.command_actions["draw_shape"].trigger()
    window.shape_workspace.kind.setCurrentText("rectangle")
    drag(viewport, QPointF(180, 150), QPointF(380, 270))
    mesh = vm.mesh.service.mesh(vm.mesh.mesh_id)
    owner = str(mesh.object_id)
    QTest.keyClick(viewport, Qt.Key.Key_Escape)
    shapes = AppearanceService(vm.documents)
    outside_mesh = shapes.create_shape("ellipse", 900, 600, 80, 80)
    outside = str(shapes.mesh(outside_mesh).object_id)
    vm.changed.emit()
    before = vm.documents.project
    qtbot.waitUntil(lambda: mesh.asset_id in viewport.artwork.images, timeout=10000)

    QTest.mouseDClick(viewport, Qt.MouseButton.LeftButton, pos=QPointF(280, 210).toPoint())
    QApplication.processEvents()
    assert window.object_edit.active and window.object_edit.key == owner
    assert vm.documents.project is before

    def visible_shape():
        """Check an actual displayed row, not merely an item retained in the tree model."""
        item = window.scene_workspace.items[owner]
        rect = window.tree.visualItemRect(item)
        assert not item.isHidden() and not rect.isEmpty()
        assert window.tree.viewport().rect().intersects(rect)
        assert window.scene_workspace.items[outside].isHidden()
        return item

    for page in ("parts", "bones"):
        window.character_panel.show_page(page)
        QApplication.processEvents()
        visible_shape()
    assert not vm.documents.project.scenes[0].skeletons

    item = visible_shape()
    window.tree.setCurrentItem(item)
    item.setText(0, "Edited shape")
    QApplication.processEvents()
    assert visible_shape().text(0) == "Edited shape"
    vm.undo()
    QApplication.processEvents()
    assert vm.documents.project == before
    visible_shape()
    window.object_edit.exit()
    assert not window.scene_workspace.items[outside].isHidden()
