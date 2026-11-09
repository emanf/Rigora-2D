"""Real Scene/Object editing controls, saved looks, object drops and motion speed changes."""

import json
import os
from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QFontDatabase
from PySide6.QtWidgets import QApplication, QComboBox, QDoubleSpinBox
from test_roots_soft_drag_gui import editor as editor

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.appearance import AppearanceService
from rigora.application_services.characters import CharacterService
from rigora.application_services.rigging import RigService
from rigora.presentation.widgets.window_frame import CustomDialog

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def readable_offscreen_fonts(qapp):
    """Register the host UI font before widgets cache their layout measurements."""
    font = Path(os.environ.get("WINDIR", "/nonexistent")) / "Fonts" / "segoeui.ttf"
    if font.exists():
        QFontDatabase.addApplicationFont(str(font))


def object_scene(window):
    """Create an editable object with separate body and clothing artwork."""
    vm = window.viewmodel
    service, look = CharacterService(vm.documents), AppearanceService(vm.documents)
    body = look.create_shape("ellipse", 200, 200, 80, 100)
    dress = look.create_shape("rectangle", 200, 250, 70, 50)
    root = service.create_object(tuple(str(service.mesh(k).object_id) for k in (body, dress)))
    vm.changed.emit()
    window.scene_workspace.select_entries((root,))
    window.object_edit.enter(root)
    return service, look, root, body, dress


def test_template_bones_follow_overlay_toggle_in_main_scene(editor, qtbot):
    """Imported template armatures stay visible after leaving Object Editor and on refresh."""
    vm, viewport = editor.viewmodel, editor.viewport
    shelf = editor.content_shelf
    shelf.collection.setCurrentText("Human rigs")
    shelf.search.setText("Human · full body")
    template = next(
        shelf.results.item(i)
        for i in range(shelf.results.count())
        if shelf.results.item(i).text() == "Human · full body"
    )
    shelf.apply(template)
    qtbot.waitUntil(
        lambda: not vm.content.busy and bool(vm.documents.project.scenes[0].skeletons),
        timeout=15000,
    )
    assert not editor.object_edit.active
    qtbot.wait(30)
    editor.rig_workspace.frame_rig()
    assert not vm.rig.active and not editor.object_edit.active
    assert viewport.composer_artwork_only
    assert any(node.kind == "bone" and node.visible for node in viewport.pose.nodes.values())
    action = editor.command_actions["bone_overlay"]
    assert action.isChecked() and viewport.show_bones
    original, undo_count = vm.documents.project, len(vm.documents.history.undo_stack)
    for theme in ("dark", "light"):
        editor.apply_theme(theme)
        shown = viewport.grab().toImage()
        action.trigger()
        hidden = viewport.grab().toImage()
        assert not action.isChecked() and not viewport.show_bones
        assert hidden != shown
        vm.changed.emit()
        assert viewport.grab().toImage() == hidden
        action.trigger()
        vm.changed.emit()
        assert action.isChecked() and viewport.show_bones
        assert viewport.grab().toImage() == shown
    assert vm.documents.project is original
    assert len(vm.documents.history.undo_stack) == undo_count


def test_main_scene_contains_only_objects_and_local_tools_open_editor(editor):
    service, _, root, body, dress = object_scene(editor)
    vm = editor.viewmodel
    bone = RigService(vm.documents).create_bone((210, 220), (240, 230))
    action = service.new_motion(root, "Idle")
    AnimationEditingService(vm.documents).key(bone, "transform.rotation", 0, 15)
    vm.changed.emit()
    assert bone in editor.scene_workspace.items
    assert set(vm.documents.animation.pose.meshes) == {body, dress}
    editor.object_edit.exit()
    assert set(editor.scene_workspace.items) == {root, *(c.id for c in vm.documents.scene.cameras)}
    assert not vm.rig.active and not vm.mesh.active
    assert editor.viewport.composer_artwork_only
    assert editor.timeline.clips.findData(action) == -1
    editor.timeline.open_picker()
    assert set(editor.timeline.picker.object_rows) == {
        root,
        *(c.id for c in vm.documents.scene.cameras),
    }
    labels = [
        editor.timeline.picker.tree.topLevelItem(i).text(0)
        for i in range(editor.timeline.picker.tree.topLevelItemCount())
    ]
    assert "Mesh Deformation" not in labels
    editor.timeline.picker.close()
    editor.scene_workspace.select_entries((root,))
    editor.command_actions["mesh"].trigger()
    assert editor.object_edit.active and vm.mesh.active
    assert vm.documents.animation_context == root
    assert editor.timeline.clips.findData(action) >= 0
    editor.object_edit.exit()
    assert not vm.mesh.active


def test_define_defaults_and_key_skin_clothing_from_main_and_object_timelines(editor, qtbot):
    service, look, root, body, dress = object_scene(editor)
    vm, panel = editor.viewmodel, editor.character_panel
    editor.scene_workspace.select_entries((str(service.mesh(body).object_id),))
    panel.show_page("skin")
    skin = panel.skin_choices
    skin.name.setText("Body colors")
    skin.new_group()
    assert skin.group.count() == 1
    skin.name.setText("Original")
    skin.save()
    original = service.record(root).extra["skins"][0]["variants"][0]["id"]
    look.edit((body,), {"tint.r": 255, "tint.g": 0, "tint.b": 0, "tint.amount": 0.6})
    vm.changed.emit()
    skin.name.setText("Warm")
    skin.save()
    warm = service.record(root).extra["skins"][0]["variants"][1]["id"]
    skin.variant.setCurrentIndex(skin.variant.findData(original))
    skin.set_default()
    assert service.record(root).extra["skins"][0]["default"] == original
    service.apply_skin(root, skin.group.currentData(), original)
    panel.show_page("clothing")
    editor.scene_workspace.select_entries((str(service.mesh(dress).object_id),))
    panel.outfit_name.setText("Outfits")
    panel.add_outfit_group()
    panel.outfits.setCurrentItem(panel.outfits.topLevelItem(0))
    panel.outfit_name.setText("Summer dress")
    panel.add_outfit()
    assert not panel.status.text()
    clothing = service.record(root).extra["outfits"][0]
    variant = clothing["variants"][0]["id"]
    service.new_motion(root, "Idle")
    vm.changed.emit()
    vm.playback.seek(10)
    panel.show_page("skin")
    skin.variant.setCurrentIndex(skin.variant.findData(warm))
    skin.apply()
    assert not skin.note.text()
    action = vm.documents.selected_clip_id
    assert vm.documents.animation.pose.meshes[body].appearance["tint"]["amount"] == 0.6
    editor.object_edit.exit()
    editor.scene_workspace.select_entries((root,))
    controls = editor.object_controls
    editor.docks["inspector"].show()
    editor.docks["inspector"].raise_()
    editor.inspector.setCurrentIndex(0)
    controls.refresh()
    assert controls.skins.variant.count() == 2 and controls.outfits.variant.count() == 2
    assert controls.animation.findData(action) >= 0
    vm.playback.seek(20)
    controls.skins.variant.setCurrentIndex(controls.skins.variant.findData(warm))
    controls.skins.apply()
    controls.outfits.variant.setCurrentIndex(controls.outfits.variant.findData(None))
    controls.outfits.apply()
    assert not controls.skins.note.text() and not controls.outfits.note.text()
    main = vm.documents.selected_clip_id
    assert main != action
    part = str(service.mesh(dress).object_id)
    assert not vm.documents.animation.pose.nodes[part].visible
    vm.playback.seek(0)
    controls.skins.refresh_value()
    controls.outfits.refresh_value()
    assert controls.skins.variant.currentData() == original
    assert controls.outfits.variant.currentData() == variant
    vm.playback.seek(20)
    assert controls.skins.variant.currentData() == warm
    assert controls.outfits.variant.currentData() is None
    assert any(owner == root and "Skin" in lane for owner, lane in editor.timeline._groups)
    assert any(owner == root and "Clothing" in lane for owner, lane in editor.timeline._groups)
    qtbot.waitUntil(
        lambda: len(editor.viewport.artwork.images) >= len(vm.documents.project.assets),
        timeout=15000,
    )
    Path("build/object-choices").mkdir(parents=True, exist_ok=True)
    editor.grab().save("build/object-choices/scene.png")
    editor.object_edit.enter(root)
    assert vm.documents.selected_clip_id == action and vm.documents.animation.pose.frame == 10
    panel.show_page("skin")
    qtbot.wait(30)
    assert panel.tabs.currentWidget().horizontalScrollBar().maximum() == 0
    editor.grab().save("build/object-choices/object-editor.png")
    editor.object_edit.exit()
    assert vm.documents.selected_clip_id == main and vm.documents.animation.pose.frame == 20


def test_object_drag_to_timeline_chooses_animation_and_controls_speed(editor, monkeypatch):
    service, _, root, body, _ = object_scene(editor)
    vm = editor.viewmodel
    source = service.new_motion(root, "Walk")
    part = str(service.mesh(body).object_id)
    animation = AnimationEditingService(vm.documents)
    animation.key(part, "transform.rotation", 0, 0)
    animation.key(part, "transform.rotation", 30, 60)
    editor.object_edit.exit()
    editor.scene_workspace.select_entries((root,))
    before = len(vm.documents.history.undo_stack)

    def choose(dialog):
        """Exercise the actual drop picker while keeping all UI offscreen."""
        assert dialog.objectName() == "ObjectAnimationPicker"
        choices = dialog.findChildren(QComboBox)
        assert choices[0].currentData() == source
        speed = next(
            w
            for w in dialog.findChildren(QDoubleSpinBox)
            if w.accessibleName() == "Animation speed"
        )
        speed.setValue(2)
        return 1

    monkeypatch.setattr(CustomDialog, "exec", choose)
    mime = QMimeData()
    mime.setData("application/x-rigora-session", vm.documents.session_id.encode())
    mime.setData("application/x-rigora-scene", json.dumps([root]).encode())
    canvas = editor.timeline.dope
    point = canvas.mapFromScene(QPointF(15 * canvas.pixels, 10))
    enter = QDragEnterEvent(
        QPoint(point),
        Qt.DropAction.MoveAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(canvas.viewport(), enter)
    assert enter.isAccepted()
    drop = QDropEvent(
        QPointF(point),
        Qt.DropAction.MoveAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(canvas.viewport(), drop)
    assert drop.isAccepted()
    blocks = editor.timeline.motion_blocks
    assert len(blocks.blocks) == 1 and blocks.blocks[0]["speed"] == 2
    assert blocks.blocks[0]["start"] == 15
    assert len(vm.documents.history.undo_stack) == before + 1
    assert editor.timeline.pages.currentIndex() == 0
    assert editor.timeline.dope.motions[0]["id"] == blocks.blocks[0]["id"]
    blocks.speed.setValue(0.75)
    blocks.speed.editingFinished.emit()
    assert blocks.blocks[0]["speed"] == 0.75
    source_keys = next(
        t
        for t in service.scene.timelines
        if t.id == next(c.timeline_id for c in service.scene.clips if c.id == source)
    ).tracks
    assert [k.frame for k in source_keys[0].keyframes] == [0, 30]
    assert source_keys[0].keyframes[-1].value == 60
    count = len(blocks.blocks)
    mime.setData("application/x-rigora-session", b"another-document")
    editor.object_controls.drop_object(mime, 50)
    assert len(blocks.blocks) == count
