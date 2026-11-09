"""First-use skin action insertion and saved-sheet color-card targeting."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QColorDialog
from test_object_scene_actions_gui import object_scene
from test_roots_soft_drag_gui import editor as editor
from test_scene_character_tracks_gui import action_choices
from test_workspace_redesign_gui import readable_offscreen_fonts as readable_offscreen_fonts

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.characters import CharacterService
from rigora.application_services.content_library import ContentService
from rigora.application_services.object_library import object_roots
from rigora.infrastructure.content_packs import read_pack
from rigora.presentation.widgets.window_frame import CustomDialog

pytestmark = pytest.mark.gui


@pytest.mark.parametrize("premade", (False, True))
def test_first_skin_action_inserts_without_an_existing_scene_track(editor, qtbot, premade):
    """The first saved-skin channel appears after one Apply, alongside any placed source motion."""
    vm, doc = editor.viewmodel, editor.viewmodel.documents
    if premade:
        entry = next(e for e in vm.content.entries if e.item.name == "Dash · Runner")
        _, files = read_pack(entry.path)
        ContentService(doc).place(entry.item, files)
        root = object_roots(doc.scene)[0].id
        vm.changed.emit()
        editor.object_edit.enter(root)
    else:
        service, _, root, _, _ = object_scene(editor)
    service = CharacterService(doc)
    panel = editor.character_panel
    panel.show_page("skin")
    panel.all_parts.setChecked(True)
    sheets = panel.skin_choices
    if not sheets.group.count():
        sheets.name.setText("Body")
        sheets.new_group()
    sheets.name.setText("Saved look")
    sheets.save()
    assert not sheets.note.text()
    group = next(
        g for g in service.record(root).extra["skins"] if g["id"] == sheets.group.currentData()
    )
    saved = group["variants"][-1]["id"]
    editor.object_edit.exit()
    editor.scene_workspace.select_entries((root,))
    existing = AnimationEditingService(doc).timeline
    assert existing is None or not any(
        t.extra.get("appearance_kind") == "skins" for t in existing.tracks
    )
    baseline, count = doc.project, len(doc.history.undo_stack)
    editor.timeline.open_picker()
    dialog = action_choices(editor.timeline.picker, "skins", group["id"])
    dialog.select_choice(saved)
    if not premade:
        dialog.cards.setCurrentRow(-1)
    QTest.mouseClick(dialog.apply_button, Qt.MouseButton.LeftButton)
    assert not vm.animation_editor.error, dialog.note.text()
    assert len(doc.history.undo_stack) == count + 1
    track = AnimationEditingService(doc).timeline
    assert track and any(t.extra.get("appearance_kind") == "skins" for t in track.tracks)
    assert (root, "Skin") in editor.timeline._groups
    assert any(
        k.extra.get("appearance_choice", {}).get("id") == saved
        for t in track.tracks
        for k in t.keyframes
    )
    doc.undo()
    assert doc.project == baseline


def test_color_card_after_saving_opens_its_own_evaluated_color(editor, qtbot, monkeypatch):
    """Save a sheet, then double-click nonfirst color cards through real viewport events."""
    vm, doc = editor.viewmodel, editor.viewmodel.documents
    entry = next(e for e in vm.content.entries if e.item.name == "Dash · Runner")
    _, files = read_pack(entry.path)
    ContentService(doc).place(entry.item, files)
    root = object_roots(doc.scene)[0].id
    vm.changed.emit()
    editor.object_edit.enter(root)
    panel = editor.character_panel
    panel.show_page("skin")
    panel.all_parts.setChecked(True)
    if not panel.skin_choices.group.count():
        panel.skin_choices.name.setText("Palette")
        panel.skin_choices.new_group()
    panel.skin_choices.name.setText("Saved before recolor")
    panel.skin_choices.save()
    assert not panel.skin_choices.note.text()
    assert panel.color_list.count() > 2
    opened = []
    expected = None

    def choose(dialog):
        """Inspect the actual picker's initial color and cancel without modifying artwork."""
        color = dialog.findChild(QColorDialog).currentColor().name()
        opened.append(color)
        assert color == expected
        return 0

    monkeypatch.setattr(CustomDialog, "exec", choose)
    for index in (1, panel.color_list.count() - 1):
        card = panel.color_list.item(index)
        panel.color_list.scrollToItem(card)
        qtbot.wait(10)
        expected = QColor(card.data(Qt.ItemDataRole.UserRole)).name()
        identity = card.data(Qt.ItemDataRole.UserRole + 1)
        point = panel.color_list.visualItemRect(card).center()
        QTest.mouseClick(panel.color_list.viewport(), Qt.MouseButton.LeftButton, pos=point)
        QTest.mouseDClick(panel.color_list.viewport(), Qt.MouseButton.LeftButton, pos=point)
        assert panel.paints.currentData() == identity
        assert len(opened) > 0
        panel.skin_choices.save()
        assert panel.paints.currentData() == identity
