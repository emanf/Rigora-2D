"""Visual asset publishing, populated collection menus and explicit placement workflows."""

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox
from test_object_assets_gui import object_in_scene
from test_roots_soft_drag_gui import editor as editor

from rigora.application_services.object_library import ObjectLibraryService
from rigora.infrastructure.content_packs import read_pack
from rigora.presentation.widgets.object_package import ObjectPackageDialog

pytestmark = pytest.mark.gui


def select_object(editor, key):
    """Select the actual card by stable definition identity."""
    cards = editor.object_assets.cards
    item = next(
        cards.item(i)
        for i in range(cards.count())
        if cards.item(i).data(Qt.ItemDataRole.UserRole) == "object:" + key
    )
    cards.setCurrentItem(item)
    return item


def test_objects_menu_order_confirmations_and_current_scene_instance_removal(
    editor, qtbot, monkeypatch
):
    """Cancellation changes nothing; removing instances preserves the reusable definition."""
    root, key = object_in_scene(editor)
    assets, vm = editor.object_assets, editor.viewmodel
    library = ObjectLibraryService(vm.documents)
    library.place(key)
    first = vm.documents.scene.id
    second = vm.documents.add_scene("Other")
    vm.documents.select_scene(second)
    library.place(key)
    inactive = vm.documents.scene
    vm.documents.select_scene(first)
    vm.changed.emit()
    item = select_object(editor, key)
    observed = []

    def inspect():
        menu = QApplication.activePopupWidget()
        assert isinstance(menu, QMenu)
        observed.extend(action.text() for action in menu.actions())
        menu.close()

    QTimer.singleShot(0, inspect)
    assets.context_menu(assets.cards.visualItemRect(item).center())
    assert observed[:4] == [
        "Edit",
        "Add to Scene",
        "Remove…",
        "Remove All Related Objects in Scene…",
    ]
    before = vm.documents.project
    monkeypatch.setattr(
        "rigora.presentation.object_assets.ask_question",
        lambda *_: QMessageBox.StandardButton.Cancel,
    )
    assets.remove_scene_instances()
    assets.remove()
    assert vm.documents.project == before
    monkeypatch.setattr(
        "rigora.presentation.object_assets.ask_question", lambda *_: QMessageBox.StandardButton.Yes
    )
    assets.remove_scene_instances()
    assert key in library.entries() and not library.scene_instances((key,))
    assert next(s for s in vm.documents.project.scenes if s.id == second) == inactive
    vm.undo()
    assert vm.documents.project == before
    select_object(editor, key)
    assets.remove()
    assert key not in library.entries() and len(vm.documents.scene.groups) == 2
    vm.undo()
    assert vm.documents.project == before


def test_export_custom_templates_import_and_double_click_stays_in_scene(
    editor, qtbot, monkeypatch, tmp_path
):
    """Write portable files and a shared custom entry reusable by another project."""
    _, key = object_in_scene(editor)
    assets, vm, shelf = editor.object_assets, editor.viewmodel, editor.content_shelf
    select_object(editor, key)

    def metadata(dialog):
        dialog.name.setText("Global hero")
        dialog.category.setEditText("Game heroes")
        dialog.show()
        QApplication.processEvents()
        assert dialog.grab().save(str(tmp_path / "object-package-dialog.png"))
        return 1

    monkeypatch.setattr(ObjectPackageDialog, "exec", metadata)
    package = tmp_path / "hero.rigpack"
    monkeypatch.setattr(
        "rigora.presentation.object_assets.choose_save_file", lambda *_: (str(package), "")
    )
    assets.export_objects()
    qtbot.waitUntil(lambda: not vm.content.busy, timeout=20000)
    assert not vm.content.error, vm.content.error
    assert read_pack(package)[0].items[0].name == "Global hero"
    select_object(editor, key)
    assets.export_objects(custom=True)
    qtbot.waitUntil(lambda: not vm.content.busy, timeout=20000)
    assert not vm.content.error, vm.content.error
    assert any(e.item.category == "Game heroes" for e in vm.content.entries)
    assert shelf.tabs.currentIndex() == 1 and shelf.collection.currentText() == "Game heroes"
    assert {shelf.collection.itemText(i) for i in range(shelf.collection.count())} <= {
        "All",
        "Game heroes",
        "Recent",
        "Favorites",
    }
    shelf.tabs.setCurrentIndex(0)
    assert shelf.collection.findText("Game heroes") == -1
    vm.new_project("Destination")
    target = vm.documents
    scene = target.scene
    monkeypatch.setattr(
        "rigora.presentation.object_assets.choose_open_file", lambda *_: (str(package), "")
    )
    assets.import_objects()
    qtbot.waitUntil(lambda: not vm.content.busy, timeout=20000)
    assert not vm.content.error, vm.content.error
    assert target.scene == scene and len(ObjectLibraryService(target).entries()) == 1
    shelf.tabs.setCurrentIndex(1)
    shelf.collection.setCurrentText("Game heroes")
    shelf.search.clear()
    assert shelf.results.count() == 1
    shelf.results.itemDoubleClicked.emit(shelf.results.item(0))
    qtbot.waitUntil(lambda: not vm.content.busy and not editor.content_drop.placing, timeout=20000)
    assert not vm.content.error, vm.content.error
    assert not editor.object_edit.active and target.scene.groups
    assert vm.documents is target


def test_template_context_menu_imports_to_objects_without_placing_and_double_click_adds_to_scene(
    editor, qtbot, monkeypatch
):
    """Both menu actions are real, and a double-click from Object Editor returns to Scene."""
    _, _ = object_in_scene(editor)
    vm, shelf = editor.viewmodel, editor.content_shelf
    item = next(
        shelf.results.item(i)
        for i in range(shelf.results.count())
        if shelf.results.item(i).data(Qt.ItemDataRole.UserRole).item.kind == "artwork"
    )
    observed = []

    def drag(drag, *_):
        assert drag.pixmap().width() == 1
        assert drag.pixmap().toImage().pixelColor(0, 0).alpha() == 0
        assert drag.mimeData().hasFormat("application/x-rigora-content")
        return Qt.DropAction.IgnoreAction

    shelf.results.setCurrentItem(item)
    monkeypatch.setattr(QDrag, "exec", drag)
    shelf.results.startDrag(Qt.DropAction.CopyAction)

    def trigger():
        menu = QApplication.activePopupWidget()
        assert isinstance(menu, QMenu)
        observed.extend(a.text() for a in menu.actions())
        menu.actions()[0].trigger()
        menu.close()

    before = vm.documents.scene
    count = len(ObjectLibraryService(vm.documents).entries())
    QTimer.singleShot(0, trigger)
    shelf.context_menu(shelf.results.visualItemRect(item).center())
    qtbot.waitUntil(lambda: not vm.content.busy, timeout=20000)
    assert observed == ["Add to Objects", "Add to Scene"]
    assert vm.documents.scene == before
    assert len(ObjectLibraryService(vm.documents).entries()) == count + 1
    entry_key = item.data(Qt.ItemDataRole.UserRole).key
    root = vm.documents.scene.groups[0].id
    editor.object_edit.enter(root)
    item = next(
        shelf.results.item(i)
        for i in range(shelf.results.count())
        if shelf.results.item(i).data(Qt.ItemDataRole.UserRole).key == entry_key
    )
    shelf.results.itemDoubleClicked.emit(item)
    qtbot.waitUntil(lambda: not vm.content.busy and not editor.content_drop.placing, timeout=20000)
    assert not vm.content.error, vm.content.error
    assert not editor.object_edit.active
    assert len(vm.documents.scene.objects) == 2
