"""Live whole-character paint cost and safe native hand-variant visibility gestures."""

import json
import time
from dataclasses import replace
from pathlib import Path
from statistics import median

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QColorDialog
from test_character_objects_gui import editor as editor
from test_object_scene_actions_gui import readable_offscreen_fonts as readable_offscreen_fonts

from rigora.application_services.character_creation import CharacterCreationService, build_character
from rigora.application_services.characters import CharacterService
from rigora.domain.character_recipe import character_preset
from rigora.presentation.widgets.window_frame import CustomDialog

pytestmark = pytest.mark.gui


@pytest.fixture
def character(editor, qtbot):
    """Build a real child girl with normal motions and its replaceable hand wardrobe."""
    recipe = replace(character_preset("Classic"), alternatives={"Hands": ("Relaxed", "Open")})
    vm = editor.viewmodel
    root = CharacterCreationService(vm.documents).create(build_character(recipe))
    vm.changed.emit()
    qtbot.waitUntil(
        lambda: len(editor.viewport.artwork.images) >= len(vm.documents.project.assets),
        timeout=15000,
    )
    editor.object_edit.enter(root)
    service = CharacterService(vm.documents)
    group = service.skin_group(root, "Palette")
    service.save_skin(root, group, service.meshes_for((root,)), "Original")
    vm.changed.emit()
    qtbot.wait(30)
    return root, recipe


def test_live_skin_preview_batches_parts_and_stays_responsive(editor, character, monkeypatch):
    """Measure evaluated vector painting while limiting each color to one document publication."""
    root, recipe = character
    vm, panel = editor.viewmodel, editor.character_panel
    panel.show_page("skin")
    panel.all_parts.setChecked(True)
    index = next(
        i
        for i in range(panel.paints.count())
        if panel.paints.itemData(i)[1] == recipe.colors["Skin"]
    )
    panel.color_list.setCurrentRow(index)
    publications = []
    original_fork = vm.documents.fork

    def fork():
        """Count real scratch publications, excluding final Apply and unrelated commands."""
        scratch = original_fork()
        count = []
        publications.append(count)
        execute = scratch.execute

        def publish(command):
            count.append(command)
            execute(command)

        monkeypatch.setattr(scratch, "execute", publish)
        return scratch

    monkeypatch.setattr(vm.documents, "fork", fork)
    measurements = {}
    for keyed in (False, True):
        if keyed:
            service = CharacterService(vm.documents)
            group = service.record(root).extra["skins"][0]
            service.apply_skin(root, group["id"], group["variants"][0]["id"], auto_key=True)
            vm.changed.emit()
        original = vm.documents.project
        timings = []

        def choose(dialog, timings=timings, original=original):
            """Exercise color signals and actual raster composition of the changed vectors."""
            picker = dialog.findChild(QColorDialog)
            for color in ("#cc8866", "#8855aa", "#449988", "#eebb99"):
                start = time.perf_counter()
                picker.setCurrentColor(QColor(color))
                editor.viewport.grab()
                timings.append((time.perf_counter() - start) * 1000)
                assert vm.scene.preview is not None and not vm.scene.error
                assert vm.documents.project is original
            return 0

        monkeypatch.setattr(CustomDialog, "exec", choose)
        panel.paint_color()
        assert vm.documents.project is original and vm.scene.preview is None
        measurements["keyed" if keyed else "base"] = timings
        assert median(timings) < 160, timings
    assert publications and all(len(commands) == 1 for commands in publications)
    output = Path("build/skin-responsiveness.json")
    output.write_text(json.dumps(measurements, indent=2), encoding="utf-8")


@pytest.mark.parametrize("keyed", (False, True))
def test_native_hand_card_switch_defers_rebuild_and_undoes(editor, character, qtbot, keyed):
    """Hide the current hands and show replacements through check states and native key events."""
    root, _ = character
    vm, panel = editor.viewmodel, editor.character_panel
    service = CharacterService(vm.documents)
    group = next(g for g in service.record(root).extra["outfits"] if g["name"] == "Hands")
    panel.show_page("clothing")
    panel.outfit_groups.setCurrentIndex(panel.outfit_groups.findData(group["id"]))
    panel.outfit_key.setChecked(keyed)
    original = vm.documents.project
    count = len(vm.documents.history.undo_stack)
    relaxed = next(v for v in group["variants"] if v["name"] == "Relaxed")
    opened = next(v for v in group["variants"] if v["name"] == "Open")

    def card(variant):
        """Reacquire stable identities after each completed document refresh."""
        return next(
            panel.outfit_cards.item(i)
            for i in range(panel.outfit_cards.count())
            if panel.outfit_cards.item(i).data(Qt.ItemDataRole.UserRole)
            == (group["id"], variant["id"])
        )

    card(relaxed).setCheckState(Qt.CheckState.Unchecked)
    assert vm.documents.project is original
    qtbot.waitUntil(lambda: len(vm.documents.history.undo_stack) == count + 1)
    for offset, variant in enumerate((opened, relaxed, opened, relaxed), 2):
        item = card(variant)
        panel.outfit_cards.setCurrentItem(item)
        panel.outfit_cards.setFocus()
        QTest.keyClick(panel.outfit_cards, Qt.Key.Key_Space)
        qtbot.waitUntil(
            lambda offset=offset: len(vm.documents.history.undo_stack) == count + offset
        )
        assert not panel.status.text()
        assert service.variant_visible(variant, vm.documents.animation.pose)
    for _ in range(5):
        vm.undo()
    assert vm.documents.project == original


def test_native_layer_hand_visibility_clicks_keep_items_alive(editor, character, qtbot):
    """Use the layer eye controls repeatedly without rebuilding inside itemClicked delivery."""
    root, _ = character
    vm, panel, tree = editor.viewmodel, editor.character_panel, editor.tree
    panel.show_page("parts")
    service = CharacterService(vm.documents)
    group = next(g for g in service.record(root).extra["outfits"] if g["name"] == "Hands")
    relaxed = next(v for v in group["variants"] if v["name"] == "Relaxed")
    hand = service.record(service.mesh(relaxed["meshes"][0]).object_id)
    original, count = vm.documents.project, len(vm.documents.history.undo_stack)
    for offset in range(1, 7):
        item = editor.scene_workspace.items[hand.id]
        parent = item.parent()
        while parent:
            parent.setExpanded(True)
            parent = parent.parent()
        tree.scrollToItem(item)
        tree.doItemsLayout()
        point = QPoint(
            tree.header().sectionViewportPosition(1) + tree.columnWidth(1) // 2,
            tree.visualItemRect(item).center().y(),
        )
        QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=point)
        qtbot.waitUntil(
            lambda offset=offset: len(vm.documents.history.undo_stack) == count + offset
        )
        assert not vm.scene.error and editor.object_edit.key == root
    for _ in range(6):
        vm.undo()
    assert vm.documents.project == original
