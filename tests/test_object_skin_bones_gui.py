"""Premade character color editing and bone discovery through the Object Editor."""

from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QFocusEvent, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QColorDialog, QDialogButtonBox
from test_character_objects_gui import editor as editor
from test_character_objects_gui import scene_objects, wait_for_artwork
from test_object_scene_actions_gui import readable_offscreen_fonts as readable_offscreen_fonts
from test_roots_soft_drag_gui import pointer
from test_timeline_title_gui import add_animal

from rigora.application_services.character_creation import CharacterCreationService, build_character
from rigora.application_services.characters import CharacterService
from rigora.application_services.vector_creation import vector_colors
from rigora.domain.character_recipe import character_preset
from rigora.presentation.widgets.window_frame import CustomDialog

pytestmark = pytest.mark.gui


def specimen(editor, qtbot, kind):
    """Use the creator's normal animal and human assembly paths."""
    if kind == "animal":
        root, color = add_animal(editor), vector_colors("Animals", "bean")[0]
    else:
        recipe = replace(character_preset("Classic"), motions=("Stand",))
        root = CharacterCreationService(editor.viewmodel.documents).create(build_character(recipe))
        editor.viewmodel.changed.emit()
        color = recipe.colors["Skin"]
    asset_count = len(editor.viewmodel.documents.project.assets)
    qtbot.waitUntil(lambda: len(editor.viewport.artwork.images) >= asset_count, timeout=15000)
    return root, color


@pytest.mark.parametrize("kind", ("animal", "human"))
def test_premade_bones_are_reachable_in_object_layer_tree(editor, qtbot, monkeypatch, kind):
    """The container's visible tree includes the skeleton and selectable bone rows."""
    root, _ = specimen(editor, qtbot, kind)
    editor.object_edit.enter(root)
    editor.character_panel.show_page("bones")
    qtbot.wait(30)
    tree = editor.tree
    rig = editor.viewmodel.documents.project.scenes[0].skeletons[0]
    bone = max(rig.bones, key=lambda b: b.length)
    item = editor.scene_workspace.items[bone.id]
    ancestor = item.parent()
    ancestors = []
    while ancestor:
        ancestors.append(ancestor)
        ancestor = ancestor.parent()
    anchor = tree.itemFromIndex(tree.rootIndex())
    assert anchor in ancestors, [a.text(0) for a in ancestors]
    for ancestor in ancestors:
        ancestor.setExpanded(True)
    tree.scrollToItem(item)
    assert tree.visualItemRect(item).isValid() and not item.isHidden()
    QTest.mouseClick(
        tree.viewport(), Qt.MouseButton.LeftButton, pos=tree.visualItemRect(item).center()
    )
    assert bone.id in editor.viewmodel.scene.selected
    assert bone.id in editor.viewmodel.rig.selected
    painted = editor.viewport.grab().toImage()
    with monkeypatch.context() as patch:
        patch.setattr(editor.viewport, "_draw_needle", lambda *args, **kwargs: None)
        assert editor.viewport.grab().toImage() != painted
    output = Path("build/object-skin-bones-review")
    output.mkdir(parents=True, exist_ok=True)
    editor.grab().save(str(output / f"bones-{kind}.png"))


@pytest.mark.parametrize("kind", ("animal", "human"))
@pytest.mark.parametrize("keyed_skin", (False, True))
def test_premade_skin_palette_changes_render_and_commit_once(
    editor, qtbot, monkeypatch, kind, keyed_skin
):
    """The chosen swatch changes visible pixels, commits once and supports Undo."""
    root, primary = specimen(editor, qtbot, kind)
    editor.object_edit.enter(root)
    panel, vm = editor.character_panel, editor.viewmodel
    panel.show_page("skin")
    panel.all_parts.setChecked(True)
    if keyed_skin:
        service = CharacterService(vm.documents)
        group = service.skin_group(root, "Palette")
        service.save_skin(root, group, panel.scope(), "Original")
        vm.changed.emit()
        choices = panel.skin_choices
        choices.key.setChecked(True)
        choices.choose_card(choices.cards.item(0))
    qtbot.wait(30)
    # Pick the broad body fill instead of a small pupil or attachment stroke.
    index = next(i for i in range(panel.paints.count()) if panel.paints.itemData(i)[1] == primary)
    panel.color_list.setCurrentRow(index)
    paint = panel.paints.currentData()
    original = vm.documents.project
    before = editor.viewport.grab().toImage()
    count = len(vm.documents.history.undo_stack)

    def choose(dialog):
        """Use the live picker signal before taking the normal Apply route."""
        dialog.findChild(QColorDialog).setCurrentColor(QColor("#ff1122"))
        assert not vm.scene.error
        assert vm.scene.preview is not None
        assert editor.viewport.grab().toImage() != before
        assert vm.documents.project is original
        actions = dialog.findChild(QDialogButtonBox, "ColorDialogActions")
        assert actions is not None
        assert actions.button(QDialogButtonBox.StandardButton.Ok).text() == "Apply"
        return 1

    monkeypatch.setattr(CustomDialog, "exec", choose)
    panel.paint_color()
    assert not panel.status.text()
    assert len(vm.documents.history.undo_stack) == count + 1
    paints = [
        p
        for mesh in editor.viewport.pose.meshes.values()
        for p in mesh.appearance.get("palette", ())
        if (p["role"], p["source"]) == paint
    ]
    assert paints and all((p["r"], p["g"], p["b"]) == (255, 17, 34) for p in paints)
    assert editor.viewport.grab().toImage() != before
    output = Path("build/object-skin-bones-review")
    output.mkdir(parents=True, exist_ok=True)
    editor.grab().save(str(output / f"skin-{kind}.png"))
    vm.undo()
    assert vm.documents.project == original


@pytest.mark.parametrize("accept", (False, True))
def test_color_picker_actual_apply_and_cancel_buttons(editor, qtbot, accept):
    """Labeled modal actions accept once or discard a live color preview without history."""
    root, primary = specimen(editor, qtbot, "animal")
    editor.object_edit.enter(root)
    panel, vm = editor.character_panel, editor.viewmodel
    panel.show_page("skin")
    panel.all_parts.setChecked(True)
    index = next(i for i in range(panel.paints.count()) if panel.paints.itemData(i)[1] == primary)
    panel.color_list.setCurrentRow(index)
    original, count = vm.documents.project, len(vm.documents.history.undo_stack)
    errors = []

    def choose():
        """Drive the real modal event loop and always dismiss it if an assertion fails."""
        dialog = QApplication.activeModalWidget()
        try:
            assert isinstance(dialog, CustomDialog)
            dialog.findChild(QColorDialog).setCurrentColor(QColor("#3355cc"))
            assert vm.scene.preview is not None and vm.documents.project is original
            QApplication.sendEvent(editor.viewport, QFocusEvent(QFocusEvent.Type.FocusOut))
            assert vm.scene.preview is not None
            actions = dialog.findChild(QDialogButtonBox, "ColorDialogActions")
            button = actions.button(
                QDialogButtonBox.StandardButton.Ok
                if accept
                else QDialogButtonBox.StandardButton.Cancel
            )
            assert button.isVisible() and button.width() > 28
            assert button.text().replace("&", "") == ("Apply" if accept else "Cancel")
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        except BaseException as error:
            errors.append(error)
            if dialog:
                dialog.reject()

    QTimer.singleShot(0, choose)
    panel.paint_color()
    assert not errors, errors
    assert vm.scene.preview is None and not panel.status.text()
    assert len(vm.documents.history.undo_stack) == count + int(accept)
    if accept:
        assert vm.documents.project != original
        vm.undo()
    assert vm.documents.project == original


def test_viewport_focus_loss_still_cancels_its_own_scene_drag(editor, qtbot):
    """Discard a pointer-owned preview on focus loss without committing or leaving a drag active."""
    scene_objects(editor)
    wait_for_artwork(editor, qtbot)
    vm, viewport, workspace = editor.viewmodel, editor.viewport, editor.scene_workspace
    viewport.zoom, viewport.offset = 1, QPointF()
    original = vm.documents.project
    before = vm.documents.animation.pose
    count = len(vm.documents.history.undo_stack)
    pointer(viewport, QMouseEvent.Type.MouseButtonPress, QPointF(135, 170))
    pointer(viewport, QMouseEvent.Type.MouseMove, QPointF(155, 185))
    assert workspace.drag is not None and vm.scene.preview is not None
    QApplication.sendEvent(viewport, QFocusEvent(QFocusEvent.Type.FocusOut))
    assert workspace.drag is None and vm.scene.preview is None
    assert viewport.pose.nodes == before.nodes
    assert vm.documents.project is original and len(vm.documents.history.undo_stack) == count
