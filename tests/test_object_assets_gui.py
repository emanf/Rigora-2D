"""Headless end-to-end Object cards, Scene drops and focused clipboard keyboard workflows."""

import json

import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt, QTimer
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu
from test_project_asset_drag_gui import bounds_center, drag_event, send
from test_roots_soft_drag_gui import editor as editor

from rigora.application_services.appearance import AppearanceService
from rigora.application_services.characters import CharacterService
from rigora.application_services.object_library import LINK, ObjectLibraryService
from rigora.application_services.scene_editing import SceneEditingService
from rigora.infrastructure.project_storage import ProjectStorage

pytestmark = pytest.mark.gui
CTRL = Qt.KeyboardModifier.ControlModifier


@pytest.fixture(autouse=True)
def clear_clipboard(qapp):
    """Release Qt-owned MIME data while the offscreen QApplication is still alive."""
    yield
    qapp.clipboard().clear()


def object_in_scene(editor):
    """Create a reusable compound object through the same commands as the app."""
    doc = editor.viewmodel.documents
    service = CharacterService(doc)
    mesh = AppearanceService(doc).create_shape("rectangle", 100, 120, 80, 100)
    root = service.create_object((service.mesh(mesh).object_id,), "Hero")
    key = service.record(root).extra[LINK]["definition"]
    editor.viewmodel.changed.emit()
    return root, key


def test_double_click_edits_asset_and_refreshes_composite_poster_on_back(editor, qtbot):
    """Asset editing adds no placement and its poster reflects all edited colored parts."""
    root, key = object_in_scene(editor)
    assets, vm = editor.object_assets, editor.viewmodel
    owner = vm.documents

    def card():
        return next(
            assets.cards.item(i)
            for i in range(assets.cards.count())
            if assets.cards.item(i).data(Qt.ItemDataRole.UserRole) == "object:" + key
        )

    qtbot.waitUntil(lambda: key in assets._thumbnails, timeout=10000)
    before = card().icon().pixmap(96, 96).toImage()
    assets.cards.setCurrentItem(card())
    assets.cards.itemDoubleClicked.emit(card())
    assert editor.object_edit.active and vm.documents is not owner
    assert len(owner.scene.groups) == 1
    snapshot = vm.documents
    shapes = AppearanceService(snapshot)
    part = shapes.create_shape("ellipse", 130, 20, 100, 100)
    CharacterService(snapshot).add_object_parts(editor.object_edit.key, (part,))
    shapes.edit((part,), {"tint.amount": 1, "tint.r": 255, "tint.g": 0, "tint.b": 0})
    vm.changed.emit()
    assert len(owner.scene.groups) == 1 and len(owner.scene.meshes) == 2
    assert assets.persistence_document(snapshot) is owner
    editor.object_edit.button.click()
    assert vm.documents is owner and not editor.object_edit.active
    qtbot.waitUntil(
        lambda: (
            key in assets._thumbnails
            and assets._thumbnails[key][0] == assets._thumbnail_inputs[key]
        ),
        timeout=10000,
    )
    after = card().icon().pixmap(96, 96).toImage()
    assert before != after
    assert any(
        (color := after.pixelColor(x, y)).red() > 180 and color.green() < 80
        for x in range(after.width())
        for y in range(after.height())
    )
    expected = after
    editor.refresh_asset_thumbnails()
    assert card().icon().pixmap(96, 96).toImage() == expected


def test_drawn_scene_object_icon_survives_artwork_decode_and_composer_return(editor, qtbot):
    """A top-level shape uses the Object glyph instead of switching to a source thumbnail."""
    from test_roots_soft_drag_gui import drag

    vm, viewport = editor.viewmodel, editor.viewport
    viewport.zoom, viewport.offset = 1, QPointF(20, 30)
    editor.command_actions["draw_shape"].trigger()
    drag(viewport, QPointF(180, 150), QPointF(380, 270))
    mesh = vm.mesh.mesh
    key = mesh.object_id
    QTest.keyClick(viewport, Qt.Key.Key_Escape)
    qtbot.waitUntil(lambda: mesh.asset_id in viewport.artwork.images, timeout=10000)
    expected = editor.icons.icon("widgets").pixmap(20, 20).toImage()
    editor.refresh_asset_thumbnails()
    assert editor.scene_workspace.items[key].icon(0).pixmap(20, 20).toImage() == expected
    editor.object_edit.enter(key)
    editor.object_edit.exit()
    editor.refresh_asset_thumbnails()
    assert editor.scene_workspace.items[key].icon(0).pixmap(20, 20).toImage() == expected


def test_unplaced_saved_object_edits_undoes_and_saves_its_owning_project(
    editor, qtbot, tmp_path, monkeypatch
):
    """Editing an unplaced definition never adds a placement or saves its working tab."""
    root, key = object_in_scene(editor)
    vm, assets, owner = editor.viewmodel, editor.object_assets, editor.viewmodel.documents
    SceneEditingService(owner).delete_entries((root,))
    vm.changed.emit()
    assets.edit(key)
    draft = vm.documents
    assert draft is not owner and editor.object_edit.active
    part = next(o.id for o in draft.scene.objects)
    before = owner.project
    CharacterService(draft).rename(part, "New part name")
    vm.changed.emit()
    assert owner.project != before and not owner.scene.objects and not owner.scene.groups
    vm.undo()
    assert owner.project == before
    vm.redo()
    saved = owner.project
    destination = tmp_path / "owner.rigora"
    monkeypatch.setattr(
        "rigora.presentation.views.main_window.choose_save_file",
        lambda *_: (str(destination), ""),
    )
    assert editor.save_project(wait=True)
    assert ProjectStorage().load_document(destination).project == saved
    assert owner.path == destination and draft.path is None and not owner.dirty
    editor.object_edit.button.click()
    assert vm.documents is owner and draft not in vm.workspace.documents


def test_objects_tabs_scene_save_drop_and_linked_preview_placement(editor, qtbot):
    """Scene→Objects saving and Objects→viewport placement use the real MIME/event routes."""
    root, key = object_in_scene(editor)
    assets, doc = editor.object_assets, editor.viewmodel.documents
    assert [editor.library_tabs.tabText(i) for i in range(3)] == ["Objects", "Imports", "Content"]
    cards = assets.cards
    editor.library_tabs.setCurrentWidget(cards)
    assert cards.viewport().acceptDrops()
    index = next(
        i
        for i in range(cards.count())
        if cards.item(i).data(Qt.ItemDataRole.UserRole) == "object:" + key
    )
    data = QMimeData()
    data.setData("application/x-rigora-scene", json.dumps([root]).encode())
    data.setData("application/x-rigora-session", doc.session_id.encode())
    point = QPointF(20, 20)
    assert send(cards.viewport(), drag_event(QDragEnterEvent, data, point)).isAccepted()
    assert send(
        cards.viewport(),
        QDropEvent(
            point,
            Qt.DropAction.CopyAction,
            data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    ).isAccepted()
    assert editor.library_tabs.currentWidget() is cards
    cards.setCurrentRow(index)
    mime = cards.mimeData([cards.item(index)])
    viewport = editor.viewport
    viewport.zoom, viewport.offset = 0.7, QPointF(33, 41)
    point = QPointF(300, 230)
    before, count = doc.project, len(doc.history.undo_stack)
    assert send(viewport, drag_event(QDragEnterEvent, mime, point)).isAccepted()
    assert viewport.drop_pose is not None, viewport.drop_message
    ghost = viewport.drop_pose
    center = bounds_center(ghost, ghost.meshes)
    assert (
        viewport.offset + QPointF(*center) * viewport.zoom + viewport.drop_translation
    ).toTuple() == pytest.approx(point.toTuple())
    assert doc.project is before
    send(
        viewport,
        QDropEvent(
            point,
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    assert doc.project is not before and len(doc.history.undo_stack) == count + 1
    roots = [g for g in doc.scene.groups if g.extra.get(LINK, {}).get("definition") == key]
    assert len(roots) == 2
    peer = next(g for g in roots if g.id != root)
    meshes = CharacterService(doc).meshes_for((peer.id,))
    assert bounds_center(doc.animation.pose, meshes) == pytest.approx(
        viewport.scene_point(point).toTuple()
    )


def test_scene_and_object_copy_cut_paste_duplicate_shortcuts_and_text_focus(editor, qtbot):
    """Actual shortcuts duplicate objects and scenes while inline text editing keeps normal Copy."""
    root, key = object_in_scene(editor)
    doc, workspace = editor.viewmodel.documents, editor.scene_workspace
    workspace.select_entries((root,))
    viewport = editor.viewport
    viewport.setFocus()
    QTest.keyClick(viewport, Qt.Key.Key_C, CTRL)
    QTest.keyClick(viewport, Qt.Key.Key_V, CTRL)
    assert len([g for g in doc.scene.groups if g.extra.get(LINK, {}).get("definition") == key]) == 2
    QTest.keyClick(viewport, Qt.Key.Key_D, CTRL)
    assert len([g for g in doc.scene.groups if g.extra.get(LINK, {}).get("definition") == key]) == 3
    QTest.keyClick(viewport, Qt.Key.Key_X, CTRL)
    assert len([g for g in doc.scene.groups if g.extra.get(LINK, {}).get("definition") == key]) == 2
    QTest.keyClick(viewport, Qt.Key.Key_V, CTRL)
    assert len([g for g in doc.scene.groups if g.extra.get(LINK, {}).get("definition") == key]) == 3
    scene = doc.scene.id
    editor.tree.clearSelection()
    workspace.scene_items[scene].setSelected(True)
    editor.tree.setFocus()
    QTest.keyClick(editor.tree, Qt.Key.Key_C, CTRL)
    QTest.keyClick(editor.tree, Qt.Key.Key_V, CTRL)
    assert len(doc.project.scenes) == 2 and doc.scene.id != scene
    copied = doc.scene.id
    assert len(doc.scene.groups) == 3
    editor.tree.clearSelection()
    workspace.scene_items[copied].setSelected(True)
    QTest.keyClick(editor.tree, Qt.Key.Key_D, CTRL)
    assert len(doc.project.scenes) == 3
    QTest.keyClick(editor.tree, Qt.Key.Key_X, CTRL)
    assert len(doc.project.scenes) == 2
    QTest.keyClick(editor.tree, Qt.Key.Key_V, CTRL)
    assert len(doc.project.scenes) == 3
    editor.filter.setText("Text selection")
    editor.filter.setFocus()
    editor.filter.selectAll()
    QTest.keyClick(editor.filter, Qt.Key.Key_C, CTRL)
    assert QApplication.clipboard().text() == "Text selection"


def test_library_clipboard_and_cut_last_scene_are_undoable(editor):
    """Saved Object duplication creates a new definition; cutting the last scene keeps one empty."""
    _, key = object_in_scene(editor)
    doc, assets = editor.viewmodel.documents, editor.object_assets
    cards = assets.cards
    cards.setCurrentRow(
        next(
            i
            for i in range(cards.count())
            if cards.item(i).data(Qt.ItemDataRole.UserRole) == "object:" + key
        )
    )
    before = len(ObjectLibraryService(doc).entries())
    QTest.keyClick(cards, Qt.Key.Key_D, CTRL)
    assert len(ObjectLibraryService(doc).entries()) == before + 1
    original = doc.project
    scene = doc.scene.id
    assets.command("cut", scene_id=scene)
    assert len(doc.project.scenes) == 1 and doc.scene.id != scene
    assert not doc.scene.groups and not doc.scene.objects
    editor.viewmodel.undo()
    assert doc.project == original


def test_context_menu_commands_and_paste_into_library_keep_scene_unchanged(editor):
    """Right-click actions invoke the same commands; pasting into Objects stores a definition."""
    root, _ = object_in_scene(editor)
    assets, workspace, doc = (
        editor.object_assets,
        editor.scene_workspace,
        editor.viewmodel.documents,
    )
    workspace.select_entries((root,))
    observed = []

    def inspect():
        """Inspect and close the actual offscreen menu without sending any desktop input."""
        menu = QApplication.activePopupWidget()
        assert isinstance(menu, QMenu)
        observed.extend(a.text().split("\t")[0] for a in menu.actions())
        menu.close()

    QTimer.singleShot(0, inspect)
    workspace.context_menu(editor.tree.visualItemRect(workspace.items[root]).center())
    assert {"Copy", "Cut", "Paste", "Duplicate", "Save as Object"} <= set(observed)
    observed.clear()
    QTimer.singleShot(0, inspect)
    workspace.context_menu(editor.tree.visualItemRect(workspace.scene_items[doc.scene.id]).center())
    assert {"Copy", "Cut", "Paste", "Duplicate", "Rename scene", "Delete scene"} <= set(observed)
    workspace.select_entries((root,))
    assets.command("copy")
    scene = doc.scene
    count = len(ObjectLibraryService(doc).entries())
    assets.command("paste", library=True)
    assert doc.scene == scene
    assert len(ObjectLibraryService(doc).entries()) == count + 1
