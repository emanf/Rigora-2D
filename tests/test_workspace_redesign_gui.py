"""Stage-first layout, source placement, synchronized selection and usable FFD/Puppet controls."""

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QFontDatabase, QMouseEvent

from rigora.app.application import ApplicationInfo
from rigora.application_services.content_library import ContentService
from rigora.application_services.meshes import MeshService
from rigora.domain.geometry import transform_point
from rigora.infrastructure.preferences import PreferencesStore
from rigora.presentation.viewmodels.main_window import MainWindowViewModel
from rigora.presentation.views.main_window import MainWindow

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def readable_offscreen_fonts(qapp):
    """Provide readable host font metrics before the isolated test window is constructed."""
    font = Path(os.environ.get("WINDIR", "/nonexistent")) / "Fonts" / "segoeui.ttf"
    if font.exists():
        QFontDatabase.addApplicationFont(str(font))


def test_character_templates_show_in_docked_shelf_and_refresh(editor, qtbot):
    """The visible shelf searches the current cast and recovers a stale catalog."""
    shelf = editor.content_shelf
    shelf.collection.setCurrentText("Characters")
    shelf.search.clear()
    assert shelf.results.count() == 5
    shelf.character_view.setCurrentText("All views")
    shelf.search.setText("Dash")
    assert shelf.results.count() == 1
    assert shelf.results.item(0).text() == "Dash · Runner"
    shelf.search.setText("Scout")
    assert shelf.results.count() == 1
    assert shelf.results.item(0).text() == "Scout · Explorer"
    shelf.model.entries = ()
    shelf.model.changed.emit()
    assert shelf.results.count() == 0
    qtbot.mouseClick(shelf.refresh_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: not shelf.model.busy, timeout=15000)
    assert shelf.results.count() == 1


@pytest.fixture
def editor(qtbot, tmp_path):
    """Create an isolated visible workspace and wait for its bounded original content discovery."""
    model = MainWindowViewModel(
        ApplicationInfo(), preferences=PreferencesStore(tmp_path / "ui.json")
    )
    window = MainWindow(model)
    window.confirm_discard = lambda: True
    qtbot.addWidget(window)
    window.resize(1600, 1000)
    window.show()
    model.new_project()
    qtbot.waitUntil(lambda: not model.content.busy, timeout=15000)
    yield window
    if window.puppet_stage:
        window.puppet_stage.close()
    window.close()


def test_layout_selection_scene_icons_and_reusable_instances(editor, qtbot):
    """Keep a dominant stage, full bottom timeline and a working default Select tool."""
    window, vm = editor, editor.viewmodel
    service = MeshService(vm.documents)
    service.register_image_bytes("prop.svg", Path("assets/examples/prop.svg").read_bytes())
    vm.changed.emit()
    item = window.project_assets.item(0)
    window.place_asset(item)
    window.place_asset(window.project_assets.item(0))
    assert len(vm.documents.project.assets) == 1 and len(service.scene.objects) == 2
    assert window.dockWidgetArea(window.docks["hierarchy"]) == Qt.DockWidgetArea.LeftDockWidgetArea
    assert window.dockWidgetArea(window.docks["assets"]) == Qt.DockWidgetArea.RightDockWidgetArea
    assert window.corner(Qt.Corner.BottomRightCorner) == Qt.DockWidgetArea.BottomDockWidgetArea
    assert window.command_actions["navigate"].isChecked() and not vm.mesh.active
    before_height = window.docks["timeline"].height()
    window.resizeDocks([window.docks["timeline"]], [600], Qt.Orientation.Vertical)
    qtbot.wait(50)
    assert window.docks["timeline"].height() >= before_height + 120
    assert window.timeline.dope.height() >= 100
    window.resizeDocks([window.docks["timeline"]], [340], Qt.Orientation.Vertical)
    grip = window.docks["timeline"].resize_grip
    qtbot.wait(30)
    initial_height = window.docks["timeline"].height()
    point = QPointF(grip.rect().center())
    qtbot.mousePress(grip, Qt.MouseButton.LeftButton, pos=point.toPoint())
    from PySide6.QtWidgets import QApplication

    QApplication.sendEvent(
        grip,
        QMouseEvent(
            QMouseEvent.Type.MouseMove,
            point - QPointF(0, 120),
            QPointF(grip.mapToGlobal(point.toPoint())) - QPointF(0, 120),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    qtbot.mouseRelease(grip, Qt.MouseButton.LeftButton, pos=point.toPoint())
    qtbot.waitUntil(lambda: window.docks["timeline"].height() >= initial_height + 100)
    assert window.docks["timeline"].height() >= initial_height + 100
    window.resizeDocks([window.docks["timeline"]], [340], Qt.Orientation.Vertical)
    window.viewmodel.scene.select(())
    mesh = service.scene.meshes[-1]
    node = vm.documents.animation.pose.nodes[mesh.object_id]
    point = (
        window.viewport.offset
        + QPointF(*transform_point(node.world_matrix, 120, 120)) * window.viewport.zoom
    )
    qtbot.mouseClick(window.viewport, Qt.MouseButton.LeftButton, pos=point.toPoint())
    assert vm.scene.selected == (mesh.object_id,)
    assert window.scene_workspace.items[mesh.object_id].isSelected()
    source = vm.documents.project
    count = len(vm.documents.history.undo_stack)
    qtbot.mousePress(window.viewport, Qt.MouseButton.LeftButton, pos=point.toPoint())
    QApplication.sendEvent(
        window.viewport,
        QMouseEvent(
            QMouseEvent.Type.MouseMove,
            point + QPointF(30, 10),
            point + QPointF(30, 10),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    assert vm.documents.project is source and vm.scene.preview is not None
    qtbot.mouseRelease(
        window.viewport, Qt.MouseButton.LeftButton, pos=(point + QPointF(30, 10)).toPoint()
    )
    assert vm.documents.project is not source and len(vm.documents.history.undo_stack) == count + 1
    vm.undo()
    assert vm.documents.project == source
    row = window.scene_workspace.items[mesh.object_id]
    window.scene_workspace.click_column(row, 1)
    qtbot.waitUntil(lambda: not vm.documents.animation.pose.nodes[mesh.object_id].visible)
    window.scene_workspace.click_column(window.scene_workspace.items[mesh.object_id], 2)
    qtbot.waitUntil(lambda: vm.scene.service.locked(mesh.object_id))
    dock = window.docks["tools"]
    dock.setFloating(True)
    assert not dock.isWindow() and dock.parentWidget().isAncestorOf(window.viewport)
    assert dock.width() == 44 and dock.grip.isVisible()
    dock.setFloating(False)


def test_ffd_scale_numeric_and_animated_key_edit(editor, qtbot):
    """FFD Scale is explicit, applies to sampled dots and updates an existing animation channel."""
    window, vm = editor, editor.viewmodel
    mesh = MeshService(vm.documents).import_image(Path("assets/examples/prop.svg"), 3, 3)
    vm.changed.emit()
    vm.mesh.select_mesh(mesh)
    window.mesh_workspace.set_mode(True)
    panel = window.mesh_panel
    panel.add_stage()
    vm.mesh.controls = (0, 1, 3, 4)
    vm.mesh.changed.emit()
    window.command_actions["scale"].trigger()
    assert panel.control_mode.currentText() == "Scale" and vm.mesh.tool == "control"
    baseline = vm.documents.project
    panel.control_fields["scale_x"].setValue(150)
    panel.transform_controls()
    assert vm.documents.project != baseline
    vm.undo()
    assert vm.documents.project == baseline
    entry = next(e for e in vm.content.entries if e.item.name == "Soft breathing")
    stage = ContentService(vm.documents).apply(entry.item, {}, mesh_id=mesh)
    vm.changed.emit()
    vm.mesh.stage_id = stage
    vm.mesh.controls = (0, 1, 3, 4)
    vm.playback.seek(10)
    vm.mesh.auto_key = False
    previous = vm.documents.animation.evaluate(10).meshes[mesh].positions
    vm.mesh.edit_controls("transform", scale_x=1.5, scale_y=1.5)
    assert vm.documents.animation.evaluate(10).meshes[mesh].positions != previous


def test_puppet_preview_hotkey_record_and_stop_are_actual_commands(editor, qtbot):
    """Real panel controls trigger a shared evaluator and prepare one recorded undo item."""
    vm = editor.viewmodel
    template = next(e.item for e in vm.content.entries if e.item.name == "Human · full body")
    ContentService(vm.documents).apply(template, {})
    vm.changed.emit()
    editor.show_puppet()
    puppet = editor.puppet_stage
    puppet.motion.setCurrentIndex(puppet.motion.findText("Natural · Walk"))
    puppet.hotkey.setText("W")
    puppet.add_motion()
    assert puppet.cards.count() == 1
    original = vm.documents.project
    puppet.preview_button.click()
    qtbot.keyClick(puppet, Qt.Key.Key_W)
    qtbot.wait(100)
    assert puppet.session.events and vm.documents.project is original
    puppet.stop_button.click()
    assert vm.documents.project is original
    count = len(vm.documents.history.undo_stack)
    puppet.record_button.click()
    qtbot.keyClick(puppet, Qt.Key.Key_W)
    qtbot.wait(150)
    puppet.stop_button.click()
    qtbot.waitUntil(lambda: not puppet.busy, timeout=15000)
    assert len(vm.documents.history.undo_stack) == count + 1
    assert vm.documents.project != original
    vm.undo()
    assert vm.documents.project == original


def test_shelf_drags_show_readonly_placement_and_target_ffd(editor, qtbot):
    """Template shelf drags place independently and FFD drops edit only hovered artwork."""
    window, vm = editor, editor.viewmodel
    entry = next(e for e in vm.content.entries if e.item.name == "Rock")
    shelf = window.content_shelf
    row = next(
        shelf.results.item(i)
        for i in range(shelf.results.count())
        if shelf.results.item(i).data(Qt.ItemDataRole.UserRole).key == entry.key
    )
    assert shelf.results.mimeData([row]).hasFormat("application/x-rigora-content")
    baseline = vm.documents.project
    point = QPointF(window.viewport.rect().center())
    before_pixels = window.viewport.grab().toImage()
    window.content_drop.move(entry.key, point)
    qtbot.waitUntil(lambda: window.viewport.drop_pose is not None, timeout=15000)
    assert vm.documents.project is baseline
    assert window.viewport.drop_pose.meshes
    assert window.viewport.grab().toImage() != before_pixels
    anchor = window.viewport.scene_point(point)
    window.content_drop.drop(entry.key, point)
    assert len(vm.documents.project.scenes[0].objects) == 1
    mesh = vm.documents.project.scenes[0].meshes[0]
    owner = vm.documents.animation.pose.nodes[mesh.object_id]
    points = [
        transform_point(owner.world_matrix, *p)
        for p in vm.documents.animation.pose.meshes[mesh.id].positions
    ]
    assert tuple((min(p[i] for p in points) + max(p[i] for p in points)) / 2 for i in (0, 1)) == (
        pytest.approx(anchor.toTuple())
    )
    ffd = next(e for e in vm.content.entries if e.item.name == "Soft breathing")
    qtbot.waitUntil(lambda: not window.mesh_workspace.jobs, timeout=15000)
    qtbot.wait(50)
    polygon = window.scene_workspace.polygons()[mesh.object_id]
    target = polygon.boundingRect().center()
    baseline = vm.documents.project
    window.content_drop.move(ffd.key, target)
    qtbot.waitUntil(
        lambda: window.content_drop.document is not None and window.viewport.drop_pose is not None,
        timeout=15000,
    )
    assert not vm.content.error, vm.content.error
    assert vm.documents.project is baseline
    assert set(window.viewport.drop_pose.nodes) == {mesh.object_id}
    window.content_drop.drop(ffd.key, target)
    assert len(vm.documents.project.scenes[0].deformers) == 1
    assert window.viewport.drop_pose is None


def test_mouse_drag_from_character_shelf_publishes_native_copy_payload(editor, qtbot, monkeypatch):
    """Exercise the item view's drag threshold and native copy route, not only drop signals."""
    from PySide6.QtGui import QDragEnterEvent, QDropEvent
    from PySide6.QtWidgets import QApplication

    from rigora.presentation.widgets import content_browser

    window, vm = editor, editor.viewmodel
    shelf = window.content_shelf
    window.library_tabs.setCurrentWidget(shelf)
    shelf.collection.setCurrentText("Characters")
    source = shelf.results
    source.setCurrentRow(
        next(i for i in range(source.count()) if source.item(i).text() == "Dash · Runner")
    )
    qtbot.wait(30)
    calls = []

    class Drag:
        """Intercept the OS drag executor while delivering its actual advertised MIME payload."""

        def __init__(self, parent):
            """Retain the originating list for lifecycle assertions."""
            self.parent = parent

        def setMimeData(self, data):
            """Store the same identity payload that the real QDrag receives."""
            self.data = data

        def setPixmap(self, pixmap):
            """Accept the native cursor image without changing the source thumbnail."""
            pass

        def exec(self, actions, default):
            """Deliver copy events to the actual stage and return the supported native result."""
            calls.append((actions, default))
            target = window.viewport
            point = target.rect().center()
            enter = QDragEnterEvent(
                point, actions, self.data, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
            )
            QApplication.sendEvent(target, enter)
            assert enter.isAccepted()
            drop = QDropEvent(
                QPointF(point),
                actions,
                self.data,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
            QApplication.sendEvent(target, drop)
            assert drop.isAccepted()
            return Qt.DropAction.CopyAction

    monkeypatch.setattr(content_browser, "QDrag", Drag)
    assert source.model().mimeTypes() == ["application/x-rigora-content"]
    point = source.visualItemRect(source.currentItem()).center()
    qtbot.mousePress(source.viewport(), Qt.MouseButton.LeftButton, pos=point)
    end = QPointF(point) - QPointF(50, 0)
    QApplication.sendEvent(
        source.viewport(),
        QMouseEvent(
            QMouseEvent.Type.MouseMove,
            end,
            end,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    qtbot.mouseRelease(source.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert calls == [(Qt.DropAction.CopyAction, Qt.DropAction.CopyAction)]
    qtbot.waitUntil(lambda: not vm.content.busy, timeout=15000)
    assert source.count() == 5
    assert len(vm.documents.project.scenes[0].skeletons) == 1
    from rigora.application_services.content_library import content_project
    from rigora.infrastructure.content_packs import read_pack

    entry = source.currentItem().data(Qt.ItemDataRole.UserRole)
    _, files = read_pack(entry.path)
    assert len(vm.documents.project.scenes[0].objects) == len(
        content_project(entry.item, files).scenes[0].objects
    )
