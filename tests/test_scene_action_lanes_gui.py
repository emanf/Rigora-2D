"""Scene actions share the dope sheet grid, preserve source data, and expose real editors."""

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QContextMenuEvent, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from test_roots_soft_drag_gui import drag, pointer
from test_roots_soft_drag_gui import editor as editor
from test_scene_character_tracks_gui import action_choices
from test_scene_character_tracks_gui import dressed_object as dressed_object
from test_workspace_redesign_gui import readable_offscreen_fonts as readable_offscreen_fonts

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.characters import CharacterService
from rigora.application_services.documents import DocumentService
from rigora.presentation.widgets.key_canvas import ActionGlyph
from rigora.presentation.widgets.timeline_ruler import ROW_HEIGHT

pytestmark = pytest.mark.gui


def point(canvas, frame, kind):
    """Map a semantic lane/frame to viewport pixels without native mouse positioning."""
    row = next(row for row, (_, key) in canvas.action_rows.items() if key == kind)
    return canvas.mapFromScene(QPointF(frame * canvas.pixels, (row + 0.5) * ROW_HEIGHT))


def right_click(canvas, position):
    """Deliver Qt context events directly, without invoking OS input or stealing focus."""
    event = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse, position, canvas.viewport().mapToGlobal(position)
    )
    QApplication.sendEvent(canvas.viewport(), event)


def test_flat_rows_icons_overview_and_saved_choice_editing(editor, dressed_object, qtbot):
    """Multiple appearance collections stay on one lane and icon keys edit their saved data."""
    root, _, meshes, clothing, (red, blue), skin, (_, dark) = dressed_object
    doc, timeline = editor.viewmodel.documents, editor.timeline
    characters = CharacterService(doc)
    characters.show_variant(root, clothing, blue, True, auto_key=True, frame=12)
    characters.apply_skin(root, skin, dark, auto_key=True, frame=18)
    another = characters.skin_group(root, "Jacket palette")
    saved = characters.save_skin(root, another, (meshes[1],), "Original jacket")
    characters.apply_skin(root, another, saved, auto_key=True, frame=18)
    animation = AnimationEditingService(doc)
    animation.add_channels(((root, "transform.x"), (root, "transform.y")))
    animation.key(root, "transform.x", 0, 0)
    animation.key(root, "transform.x", 40, 100)
    editor.viewmodel.changed.emit()
    timeline.pages.setCurrentIndex(0)
    qtbot.wait(20)
    row = next(
        timeline.tracks.topLevelItem(i)
        for i in range(timeline.tracks.topLevelItemCount())
        if timeline.tracks.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole + 1) == root
    )
    assert [row.child(i).text(0) for i in range(row.childCount())] == [
        "TRANSFORM",
        "Skin",
        "Clothing",
    ]
    assert all(row.child(i).childCount() == 0 for i in range(row.childCount()))
    canvas = timeline.dope
    overview = next(i for i, ids in canvas.overview_rows.items() if ids)
    assert canvas.rows[overview] is None and overview not in canvas.summary_rows
    header_point = canvas.mapFromScene(QPointF(12 * canvas.pixels, (overview + 0.5) * ROW_HEIGHT))
    assert canvas.action_at(header_point) is None and canvas.lane_at(header_point) == ()
    baseline = doc.project
    drag(canvas.viewport(), QPointF(header_point), QPointF(header_point) + QPointF(32, 0))
    assert doc.project is baseline
    for kind in ("skins", "outfits"):
        position = point(canvas, 18 if kind == "skins" else 12, kind)
        assert isinstance(canvas.itemAt(position), ActionGlyph)
        right_click(canvas, position)
        dialog = timeline.action_editor
        assert dialog.kind == kind and dialog.refs
        assert not dialog.end.isVisible() and not dialog.speed.isVisible()
        assert doc.project is baseline
        if kind == "skins":
            dialog.group.setCurrentIndex(dialog.group.findData(another))
            assert dialog.cards.currentItem().data(Qt.ItemDataRole.UserRole) == saved
    dialog = timeline.action_editor
    assert dialog.cards.currentItem().data(Qt.ItemDataRole.UserRole) == blue
    dialog.select_choice(red)
    assert doc.project is baseline
    dialog.apply()
    assert not timeline.editor.error
    assert doc.animation.evaluate(12).nodes[characters.mesh(meshes[1]).object_id].visible
    assert not doc.animation.evaluate(12).nodes[characters.mesh(meshes[2]).object_id].visible
    assert (
        characters.record(root).extra
        == next(g for g in baseline.scenes[0].groups if g.id == root).extra
    )
    new_point = point(canvas, 36, "outfits")
    right_click(canvas, new_point)
    assert timeline.action_editor.at_frame.value() == 36
    assert not timeline.action_editor.refs
    timeline.action_editor.select_choice(blue)
    timeline.action_editor.apply()
    assert not timeline.editor.error
    assert doc.animation.evaluate(35).nodes[characters.mesh(meshes[1]).object_id].visible
    assert doc.animation.evaluate(36).nodes[characters.mesh(meshes[2]).object_id].visible
    timeline.action_editor.delete()
    assert not timeline.editor.error
    assert doc.animation.evaluate(36).nodes[characters.mesh(meshes[1]).object_id].visible
    editor.resizeDocks([editor.docks["timeline"]], [380], Qt.Orientation.Vertical)
    qtbot.wait(20)
    timeline.grab().save("build/scene-action-lanes.png")


def test_running_endpoints_move_trim_speed_cancel_and_reload(
    editor, dressed_object, qtbot, tmp_path
):
    """Motion icons manipulate windows, with one Undo per gesture and reusable sources intact."""
    root = dressed_object[0]
    doc, timeline = editor.viewmodel.documents, editor.timeline
    characters = CharacterService(doc)
    source = characters.motions(root)[0]
    saved_timeline = next(t for t in doc.scene.timelines if t.id == source.timeline_id)
    segment = characters.place_motion(root, source.id, 12, 2)
    editor.viewmodel.changed.emit()
    timeline.pages.setCurrentIndex(0)
    qtbot.wait(20)
    canvas = timeline.dope
    endpoints = [item for item in canvas.motion_graphics if item.data(6)[1] != "move"]
    assert len(endpoints) == 2 and all(isinstance(item, ActionGlyph) for item in endpoints)
    timeline.search.setText(source.name)
    assert not timeline._groups[root, "Animation"].isHidden()
    timeline.search.clear()
    timeline.only_selected.setChecked(True)
    assert not timeline._groups[root, "Animation"].isHidden()
    timeline.only_selected.setChecked(False)
    assert not timeline.pages.isTabVisible(timeline.pages.indexOf(timeline.motion_blocks))
    count = len(doc.history.undo_stack)
    begin = point(canvas, 30, "motion")
    drag(canvas.viewport(), QPointF(begin), QPointF(begin) + QPointF(32, 0))
    assert not timeline.editor.error and len(doc.history.undo_stack) == count + 1
    block = next(b for b in canvas.motions if b["id"] == segment)
    assert (block["start"], block["end"]) == (16, 64)
    edge = point(canvas, block["end"], "motion")
    drag(canvas.viewport(), QPointF(edge), QPointF(edge) + QPointF(24, 0))
    assert not timeline.editor.error and len(doc.history.undo_stack) == count + 2
    block = next(b for b in canvas.motions if b["id"] == segment)
    assert block["end"] == 67
    before = doc.project
    start = QPointF(point(canvas, 30, "motion"))
    pointer(canvas.viewport(), QMouseEvent.Type.MouseButtonPress, start)
    pointer(canvas.viewport(), QMouseEvent.Type.MouseMove, start + QPointF(48, 0))
    assert canvas._motion_preview is not None and doc.project is before
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    pointer(canvas.viewport(), QMouseEvent.Type.MouseButtonRelease, start + QPointF(48, 0))
    assert canvas._motion_preview is None and doc.project is before
    right_click(canvas, point(canvas, 16, "motion"))
    dialog = timeline.action_editor
    assert dialog.segment == segment
    dialog.speed.setValue(1.75)
    dialog.repeat.setChecked(False)
    dialog.apply()
    assert not timeline.editor.error
    block = next(b for b in canvas.motions if b["id"] == segment)
    assert (block["speed"], block["repeat"]) == (1.75, False)
    assert next(t for t in doc.scene.timelines if t.id == source.timeline_id) == saved_timeline
    before = doc.project
    dialog.end.setValue(1)
    dialog.apply()
    assert timeline.editor.error and doc.project is before
    dialog.close()
    doc.save(tmp_path / "action-spans.rigora")
    loaded = DocumentService()
    loaded.open(doc.path)
    loaded.set_animation_context(None)
    for frame in (0, 16, 27, 66, 70):
        assert loaded.animation.evaluate(frame).meshes == doc.animation.evaluate(frame).meshes
    timeline.grab().save("build/scene-animation-span.png")
    animation_row = timeline._groups[root, "Animation"]
    assert animation_row.checkState(1) == Qt.CheckState.Unchecked
    animation_row.setCheckState(2, Qt.CheckState.Unchecked)
    qtbot.waitUntil(lambda: not canvas.motion_graphics)
    assert characters.motions(root)[0] == source


def test_pending_action_cannot_edit_a_different_object_context(editor, dressed_object):
    """A retained editor rejects scene/object changes rather than modifying an unrelated clip."""
    root = dressed_object[0]
    dialog = action_choices(editor.timeline.picker, "motion")
    doc = editor.viewmodel.documents
    editor.object_edit.enter(root)
    before = doc.project
    dialog.apply()
    assert "timeline changed" in dialog.note.text().lower()
    assert doc.project is before


def test_action_picker_rejects_ambiguous_types_and_uses_focused_card(editor, dressed_object):
    """Mixed types are rejected; a focused motion still inserts after card deselection."""
    timeline, doc = editor.timeline, editor.viewmodel.documents
    picker = timeline.picker
    rows = [
        picker.tree.topLevelItem(i)
        for i in range(picker.tree.topLevelItemCount())
        if picker.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole + 6)
    ]
    baseline = doc.project
    picker.add(rows)
    assert doc.project is baseline and "one action type" in picker.count.text()
    dialog = action_choices(picker, "outfits", dressed_object[3])
    dialog.select_choice(None)
    assert not dialog.shown.isEnabled()
    dialog = action_choices(picker, "motion")
    dialog.cards.clearSelection()
    assert dialog.cards.currentItem() is not None
    dialog.apply()
    assert not timeline.editor.error and len(timeline.dope.motions) == 1
