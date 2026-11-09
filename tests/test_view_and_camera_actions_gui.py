"""Real template editing, empty turnarounds, camera cuts and shared action-row presentation."""

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from test_roots_soft_drag_gui import editor as editor
from test_scene_action_lanes_gui import right_click
from test_scene_character_tracks_gui import action_choices
from test_workspace_redesign_gui import readable_offscreen_fonts as readable_offscreen_fonts

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.appearance import AppearanceService
from rigora.application_services.cameras import CameraService
from rigora.application_services.characters import CharacterService
from rigora.application_services.content_library import ContentService
from rigora.application_services.object_library import object_roots
from rigora.application_services.scene_editing import SceneEditingService
from rigora.domain.object_views import VIEW_SLOTS
from rigora.engine.cameras import active_camera
from rigora.infrastructure.content_packs import read_pack
from rigora.presentation.widgets.key_canvas import ActionGlyph
from rigora.presentation.widgets.timeline_ruler import ROW_HEIGHT

pytestmark = pytest.mark.gui


@pytest.mark.parametrize("name", ("Dash · Runner", "Bolt · Stick robot"))
def test_template_views_are_editable_empty_slots_and_timeline_keys(editor, qtbot, name):
    """Current human and robot Templates support Default and independent blank sides."""
    vm, doc = editor.viewmodel, editor.viewmodel.documents
    entry = next(e for e in vm.content.entries if e.item.name == name)
    _, files = read_pack(entry.path)
    ContentService(doc).place(entry.item, files)
    root = object_roots(doc.scene)[0].id
    vm.changed.emit()
    editor.object_edit.enter(root)
    panel = editor.character_panel
    panel.show_page("parts")
    assert panel.object_views.currentText() == "Default"
    assert (
        tuple(panel.object_views.itemText(i) for i in range(panel.object_views.count()))
        == VIEW_SLOTS
    )
    assert panel.object_views.isEnabled()
    assert not editor.add_scene_button.isVisible() and not editor.camera_button.isVisible()
    original = set(editor.object_edit.ids) - {root}
    panel.object_views.setCurrentText("Front")
    assert editor.object_edit.ids == {root}
    panel.object_views.setCurrentText("Side")
    assert panel.object_views.isEnabled() and editor.object_edit.ids == {root}
    panel.show_page("skin")
    panel.all_parts.setChecked(True)
    assert panel.scope() == () and panel.skin_choices.group.count() == 0
    assert not any(n.visible for k, n in doc.animation.pose.nodes.items() if k in original)
    art = AppearanceService(doc)
    mesh = art.create_shape("ellipse", 50, 60, 40, 80)
    CharacterService(doc).add_object_parts(root, (mesh,))
    part = art.mesh(mesh).object_id
    vm.changed.emit()
    assert part in editor.object_edit.ids
    panel.skin_choices.name.setText("Side palette")
    panel.skin_choices.new_group()
    panel.skin_choices.save()
    assert not panel.skin_choices.note.text()
    assert panel.skin_choices.group.count() == 1
    panel.object_views.setCurrentText("Default")
    assert part not in editor.object_edit.ids
    assert original <= set(editor.object_edit.ids)
    panel.object_views.setCurrentText("Side")
    assert part in editor.object_edit.ids
    panel.object_views.setCurrentText("Default")
    editor.object_edit.exit()
    assert editor.add_scene_button.isVisible() and editor.camera_button.isVisible()
    editor.scene_workspace.select_entries((root,))
    editor.timeline.open_picker()
    dialog = action_choices(editor.timeline.picker, "views")
    dialog.select_choice("Side")
    dialog.at_frame.setValue(18)
    dialog.apply()
    assert not editor.timeline.editor.error, dialog.note.text()
    assert doc.animation.evaluate(18).nodes[part].visible
    assert not doc.animation.evaluate(17).nodes[part].visible
    assert (root, "View") in editor.timeline._groups
    canvas = editor.timeline.dope
    row = next(row for row, (_, kind) in canvas.action_rows.items() if kind == "views")
    position = canvas.mapFromScene(QPointF(18 * canvas.pixels, (row + 0.5) * ROW_HEIGHT))
    assert isinstance(canvas.itemAt(position), ActionGlyph)
    dialog.close()
    editor.object_edit.enter(root)
    assert panel.object_views.currentText() == "Default"
    assert not doc.animation.pose.nodes[part].visible
    qtbot.wait(10)


def test_camera_cut_animation_effect_rows_and_card_editing(editor, qtbot):
    """A shared Camera header exposes real cuts, motion and effect intervals."""
    vm, doc, timeline = editor.viewmodel, editor.viewmodel.documents, editor.timeline
    camera1 = doc.scene.cameras[0].id
    camera2 = CameraService(doc).add()
    vm.changed.emit()
    timeline.open_picker()
    picker = timeline.picker
    picker.objects.setCurrentItem(picker.object_rows[camera1])
    cut = action_choices(picker, "camera_cut")
    cut.select_choice(camera2)
    cut.at_frame.setValue(20)
    QTest.mouseClick(cut.apply_button, Qt.MouseButton.LeftButton)
    assert not timeline.editor.error, cut.note.text()
    assert active_camera(doc.animation.evaluate(19)).id == camera1
    assert active_camera(doc.animation.evaluate(20)).id == camera2
    for kind, preset in (("camera_motion", "earthquake"), ("camera_effect", "rain")):
        dialog = action_choices(picker, kind)
        dialog.camera.setCurrentIndex(dialog.camera.findData(camera2))
        dialog.select_choice(preset)
        dialog.at_frame.setValue(20)
        dialog.end.setValue(60)
        dialog.apply()
        assert not timeline.editor.error, dialog.note.text()
    SceneEditingService(doc).flags((camera1,), locked=False)
    AnimationEditingService(doc).add_channels(((camera1, "transform.x"),))
    vm.changed.emit()
    header = next(
        timeline.tracks.topLevelItem(i)
        for i in range(timeline.tracks.topLevelItemCount())
        if timeline.tracks.topLevelItem(i).text(0) == "Camera"
    )
    assert {header.child(i).text(0) for i in range(header.childCount())} == {
        "TRANSFORM",
        "Cut",
        "Animation",
        "Effect",
    }
    assert all(header.child(i).childCount() == 0 for i in range(header.childCount()))
    canvas = timeline.dope
    row = next(row for row, (_, kind) in canvas.action_rows.items() if kind == "camera_cut")
    position = canvas.mapFromScene(QPointF(20 * canvas.pixels, (row + 0.5) * ROW_HEIGHT))
    assert isinstance(canvas.itemAt(position), ActionGlyph)
    right_click(canvas, position)
    assert timeline.action_editor.cards.currentItem().data(Qt.ItemDataRole.UserRole) == camera2
    timeline.action_editor.close()
    vm.playback.seek(0)
    row = next(row for row, (_, kind) in canvas.action_rows.items() if kind == "camera_motion")
    position = canvas.mapFromScene(QPointF(20 * canvas.pixels, (row + 0.5) * ROW_HEIGHT))
    right_click(canvas, position)
    edit = timeline.action_editor
    assert edit.camera.currentData() == camera2
    assert edit.cards.currentItem().data(Qt.ItemDataRole.UserRole) == "earthquake"
    identity = edit.segment
    edit.speed.setValue(2)
    edit.end.setValue(64)
    edit.apply()
    assert not timeline.editor.error, edit.note.text()
    windows = [
        t.extra["camera_action"]
        for t in timeline.editor.service.timeline.tracks
        if t.extra.get("camera_action", {}).get("id") == identity
    ]
    assert windows and all(w["end"] == 64 and w["speed"] == 2 for w in windows)
    doc.undo()
    vm.changed.emit()
    edit.close()
    vm.playback.seek(35)
    assert editor.viewport.camera_lens is not None
    assert editor.viewport.camera_lens[1].isValid()
    editor.resizeDocks([editor.docks["timeline"]], [380], Qt.Orientation.Vertical)
    qtbot.wait(10)
    timeline.grab().save("build/camera-action-rows.png")
