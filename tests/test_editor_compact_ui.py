"""Compact editor controls, live zoom readouts and persistent item-view navigation."""

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QToolButton
from test_character_objects_gui import editor as editor
from test_object_scene_actions_gui import readable_offscreen_fonts as readable_offscreen_fonts
from test_timeline_title_gui import add_animal

from rigora.application_services.characters import CharacterService
from rigora.application_services.commands import ScenePatch
from rigora.domain.entities import Group

pytestmark = pytest.mark.gui


def percent(zoom):
    """Match the readout's one-decimal presentation without comparing widget geometry."""
    return f"{zoom * 100:.1f}".rstrip("0").rstrip(".") + "%"


def test_scene_object_and_timeline_zoom_readouts_follow_zoom_fit_and_restore(editor):
    """Independent time/canvas percentages follow real navigation and Object Editor exit."""
    root = add_animal(editor)
    viewport, timeline = editor.viewport, editor.timeline
    viewport.zoom_at(0.75 / viewport.zoom)
    assert editor.canvas_zoom.text() == editor.zoom_status.text() == "75%"
    editor.object_edit.enter(root)
    assert editor.canvas_zoom.text() == percent(viewport.zoom)
    viewport.zoom_at(1.25)
    assert editor.canvas_zoom.text() == percent(viewport.zoom)
    timeline.dope.zoom(1.25)
    assert timeline.zoom_label.text() == "125%"
    timeline.frame_curves()
    assert timeline.zoom_label.text() == percent(timeline.dope.pixels / 8)
    editor.object_edit.exit()
    assert viewport.zoom == pytest.approx(0.75)
    assert editor.canvas_zoom.text() == "75%"
    assert timeline.zoom_label.text() == percent(timeline.dope.pixels / 8)


def test_compact_parts_and_bone_actions_keep_real_binding_and_undo(editor, qtbot):
    """The reorganized controls reuse authoring actions and leave the layer scroll area clear."""
    root = add_animal(editor)
    editor.object_edit.enter(root)
    panel, vm = editor.character_panel, editor.viewmodel
    assert not editor.tree.header().isVisible() and not editor.hierarchy_note.isVisible()
    assert panel.name.mapTo(panel, QPoint()).y() == panel.object_views.mapTo(panel, QPoint()).y()
    assert not panel.tabs.isVisible() and not panel.binding_controls.isVisible()
    assert panel.folder_button.width() == panel.assets_button.width() == 28
    assert all(
        not button.text().startswith(
            ("Flip facing", "Flip vertically", "Bone Editor", "Spring Editor", "Edit mesh")
        )
        for button in panel.findChildren(QAbstractButton)
    )
    scene = vm.documents.project.scenes[0]
    mesh = next(
        m
        for m in scene.meshes
        if any(d.kind == "skinning" and d.owner_id == m.id for d in scene.deformers)
    )
    bind_bone = next(
        key
        for d in scene.deformers
        if d.kind == "skinning" and d.owner_id == mesh.id
        for key in d.parameters["bind_matrices"]
    )

    def bound():
        """Inspect canonical skinning stages shared by imported and hand-authored rigs."""
        return any(
            d.kind == "skinning" and d.owner_id == mesh.id
            for d in vm.documents.project.scenes[0].deformers
        )

    editor.scene_workspace.select_entries((mesh.object_id,))
    panel.show_page("bones")
    panel.binding_toggle.setChecked(True)
    assert panel.binding_controls.isVisible() and not panel.tabs.isVisible()
    assert all(button.isVisible() for button in panel.bind_buttons)
    assert (
        editor.main_tool_buttons["bind_parts"].defaultAction()
        is panel.bind_buttons[0].defaultAction()
    )
    before = len(vm.documents.history.undo_stack)
    QTest.mouseClick(panel.bind_buttons[1], Qt.MouseButton.LeftButton)
    assert not panel.status.text()
    assert not bound()
    assert len(vm.documents.history.undo_stack) == before + 1
    QTest.mouseClick(editor.main_tool_buttons["bind_parts"], Qt.MouseButton.LeftButton)
    dialog = editor.bindings_dialog
    assert dialog.isVisible()
    dialog.target.setCurrentIndex(dialog.target.findData(bind_bone))
    QTest.mouseClick(dialog.bind_button, Qt.MouseButton.LeftButton)
    assert not dialog.status.text()
    dialog.close()
    assert not panel.status.text()
    assert bound()
    assert len(vm.documents.history.undo_stack) == before + 2
    vm.undo()
    assert not bound()
    vm.undo()
    assert bound()
    output = Path("build/editor-compact-review")
    output.mkdir(parents=True, exist_ok=True)
    for page in ("parts", "bones", "skin", "clothing", "motions"):
        panel.show_page(page)
        qtbot.wait(20)
        panel.grab().save(str(output / f"{page}.png"))
        assert all(
            button.width() == 28
            for button in panel.findChildren(QToolButton)
            if button.objectName() == "PanelAction"
        )
    panel.show_page("parts")
    qtbot.wait(20)
    editor.grab().save(str(output / "workspace.png"))


def test_layer_disclosure_selection_and_scroll_survive_edits_undo_and_context_switch(editor, qtbot):
    """Retain independent Scene/Object navigation after edits, undo and context switches."""
    root = add_animal(editor)
    editor.tree.setMaximumHeight(220)
    vm = editor.viewmodel
    scene = vm.documents.project.scenes[0]
    folder = Group(name="Scene folder")
    folders = (
        folder,
        *(Group(name=f"Folder {i}", parent_id=folder.id if i < 3 else None) for i in range(45)),
    )
    vm.documents.execute(
        ScenePatch(
            "Add scene folders",
            scene.id,
            {"groups": scene.groups},
            {"groups": (*scene.groups, *folders)},
        )
    )
    vm.changed.emit()
    editor.tree.topLevelItem(0).setExpanded(True)
    editor.scene_workspace.items[folder.id].setExpanded(True)
    editor.tree.doItemsLayout()
    editor.tree.verticalScrollBar().setValue(180)
    scene_scroll = editor.tree.verticalScrollBar().value()
    assert scene_scroll > 0
    vm.scene.run(lambda s: s.rename(folders[-1].id, "Renamed folder"))
    qtbot.wait(10)
    assert editor.scene_workspace.items[folder.id].isExpanded()
    assert editor.tree.verticalScrollBar().value() == scene_scroll
    editor.scene_workspace.items[folder.id].setExpanded(False)
    scene_scroll = editor.tree.verticalScrollBar().value()
    editor.object_edit.enter(root)
    qtbot.wait(20)
    rig = vm.documents.project.scenes[0].skeletons[0]
    head = next(b for b in rig.bones if b.name == "head")
    editor.scene_workspace.items[head.id].setExpanded(False)
    mesh = vm.documents.project.scenes[0].meshes[0]
    editor.scene_workspace.select_entries((mesh.object_id,))
    editor.tree.doItemsLayout()
    editor.tree.verticalScrollBar().setValue(100)
    object_scroll = editor.tree.verticalScrollBar().value()
    assert object_scroll > 0
    vm.scene.run(lambda s: s.rename(mesh.object_id, "Renamed part"))
    qtbot.wait(10)
    assert not editor.scene_workspace.items[head.id].isExpanded()
    assert editor.scene_workspace.items[mesh.object_id].isSelected()
    assert editor.tree.verticalScrollBar().value() == object_scroll
    vm.undo()
    assert not editor.scene_workspace.items[head.id].isExpanded()
    assert editor.tree.verticalScrollBar().value() == object_scroll
    editor.object_edit.exit()
    qtbot.wait(10)
    assert not editor.scene_workspace.items[folder.id].isExpanded()
    assert editor.tree.verticalScrollBar().value() == scene_scroll
    editor.tree.topLevelItem(0).setExpanded(False)
    scene = vm.documents.project.scenes[0]
    vm.documents.execute(
        ScenePatch("Rename scene", scene.id, {"name": scene.name}, {"name": "Renamed scene"})
    )
    vm.changed.emit()
    assert not editor.tree.topLevelItem(0).isExpanded()


def test_motion_cards_keep_selection_and_scroll_when_a_part_changes(editor, qtbot):
    """Card reconstruction keeps the chosen animation and its visible scroll position."""
    root = add_animal(editor)
    editor.object_edit.enter(root)
    vm, panel = editor.viewmodel, editor.character_panel
    service = CharacterService(vm.documents)
    for index in range(16):
        service.new_motion(root, f"Motion {index}")
    vm.changed.emit()
    panel.show_page("motions")
    panel.motion_list.setCurrentRow(10)
    vm.playback.pause()
    qtbot.wait(20)
    selected = panel.motion_list.currentItem().data(Qt.ItemDataRole.UserRole)
    panel.motion_list.verticalScrollBar().setValue(100)
    scroll = panel.motion_list.verticalScrollBar().value()
    assert scroll > 0
    part = vm.documents.project.scenes[0].objects[0]
    vm.scene.run(lambda s: s.rename(part.id, "Renamed without navigation reset"))
    qtbot.wait(20)
    assert panel.motion_list.currentItem().data(Qt.ItemDataRole.UserRole) == selected
    assert panel.motion_list.verticalScrollBar().value() == scroll
    assert not vm.playback.session.playback.is_playing
