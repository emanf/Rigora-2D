"""Scene-authored FFD keys remain discoverable under their owning Object."""

import pytest
from PySide6.QtCore import QPointF, Qt
from test_object_workspace_redesign_gui import panel_editor as panel_editor

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.appearance import AppearanceService
from rigora.application_services.characters import CharacterService
from rigora.application_services.content_library import ContentService, LibraryEntry
from rigora.domain.content import ContentPack
from rigora.infrastructure.content_packs import write_pack
from rigora.infrastructure.effect_catalog import ffd_presets
from rigora.presentation.widgets.timeline_tracks import row_channels

pytestmark = pytest.mark.gui


def motion():
    """Use the real original normalized FFD motion without building unrelated posters."""
    return next(item for item in ffd_presets() if "motion" in item.payload)


def test_scene_ffd_has_an_editable_named_object_action_linked_to_its_scene_placement(panel_editor):
    """A dropped FFD source appears in Object Editor and edits update its placed Scene action."""
    editor = panel_editor
    vm, doc = editor.viewmodel, editor.viewmodel.documents
    item = motion()
    stage = ContentService(doc).place(item, {}, position=(400, 300))
    vm.changed.emit()
    characters = CharacterService(doc)
    owner = characters.scene_objects()[0]
    source = next((c for c in characters.motions(owner) if c.name == item.name), None)
    assert source is not None
    scene_clip = AnimationEditingService(doc).clip
    editor.object_edit.enter(owner)
    assert AnimationEditingService(doc).clip.id == source.id
    assert editor.timeline.clips.currentText() == item.name
    assert stage in doc.animation.evaluator.deformation.deformers
    assert any(
        editor.character_panel.motion.itemData(i) == source.id
        for i in range(editor.character_panel.motion.count())
    )
    animation = AnimationEditingService(doc)
    track = next(t for t in animation.timeline.tracks if t.owner_id == stage)
    frame = track.keyframes[1].frame
    previous = next(t for t in doc.scene.timelines if t.id == scene_clip.timeline_id)
    animation.key(stage, track.property_path, frame, track.keyframes[1].value + 5)
    editor.object_edit.exit()
    current = next(t for t in doc.scene.timelines if t.id == scene_clip.timeline_id)
    assert current != previous
    arranged = next(t for t in current.tracks if t.extra.get("source_track") == track.id)
    assert arranged.keyframes[1].value == pytest.approx(track.keyframes[1].value + 5)


def test_remove_animation_requires_confirmation_and_undo_restores_the_action(panel_editor):
    """Exercise the real safe-default dialog, cancel path, deletion and in-editor Undo."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox

    from rigora.presentation.widgets.message_dialogs import MessageDialog

    editor = panel_editor
    vm, doc = editor.viewmodel, editor.viewmodel.documents
    item = motion()
    ContentService(doc).place(item, {})
    vm.changed.emit()
    characters = CharacterService(doc)
    owner = characters.scene_objects()[0]
    (source,) = characters.motions(owner)
    editor.object_edit.enter(owner)
    panel = editor.character_panel
    panel.show_page("motions")
    baseline, count = doc.project, len(doc.history.undo_stack)

    def answer(button):
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, MessageDialog)
        assert source.name in dialog.box.text() and "linked Scene" in dialog.box.text()
        assert dialog.box.defaultButton() is dialog.box.button(QMessageBox.StandardButton.Cancel)
        dialog.box.button(button).click()

    QTimer.singleShot(0, lambda: answer(QMessageBox.StandardButton.Cancel))
    panel.remove_motion_button.click()
    assert doc.project == baseline and len(doc.history.undo_stack) == count
    QTimer.singleShot(0, lambda: answer(QMessageBox.StandardButton.Yes))
    panel.remove_motion_button.click()
    assert source.id not in {c.id for c in doc.scene.clips}
    assert panel.motion.count() == 0 and not panel.remove_motion_button.isEnabled()
    assert editor.object_edit.active and owner in characters.records()
    assert len(doc.history.undo_stack) == count + 1
    vm.undo()
    assert doc.project == baseline
    assert panel.motion.count() == 1 and panel.remove_motion_button.isEnabled()
    assert panel.motion.currentData() == source.id


def deformation_row(editor, owner):
    """Resolve the public Object lane, without exposing mesh/stage ownership rows."""
    row = editor.timeline._groups.get((owner, "Deformation"))
    assert row is not None
    assert row.parent().data(0, Qt.ItemDataRole.UserRole + 1) == owner
    assert not row.isHidden() and row.parent().isExpanded()
    return row


def test_new_project_ffd_drop_exposes_all_keys_and_they_remain_editable(
    panel_editor, qtbot, tmp_path
):
    """Deliver a real pack drop, inspect keys, retime the group and preserve Undo/save/open."""
    editor = panel_editor
    vm, doc = editor.viewmodel, editor.viewmodel.documents
    item = motion()
    pack = ContentPack(name="FFD test", author="Rigora", license="CC0-1.0", items=(item,))
    path = tmp_path / "ffd.rigpack"
    write_pack(path, pack, {})
    entry = LibraryEntry(path, pack, item)
    vm.content.entries = (entry,)
    baseline = doc.project
    editor.content_drop.drop(entry.key, QPointF(480, 300))
    qtbot.waitUntil(lambda: bool(doc.scene.deformers) and not vm.content.busy, timeout=30000)
    assert not vm.content.error and not editor.object_edit.active
    stage = next(d for d in doc.scene.deformers if d.kind == "ffd")
    animation = AnimationEditingService(doc)
    assert animation.clip.extra.get("motion_sequence") is True
    expected = {t.id for t in animation.timeline.tracks if t.owner_id == stage.id}
    owner = CharacterService(doc).scene_objects()[0]
    row = editor.timeline._groups[owner, "Animation"]
    assert set(editor.timeline.row_tracks(row)) == expected
    editor.timeline.only_selected.setChecked(True)
    assert not row.isHidden()
    editor.timeline.only_selected.setChecked(False)
    assert doc.animation.evaluate(0).meshes != doc.animation.evaluate(6).meshes
    editor.object_edit.enter(owner)
    source = animation.clip
    expected_source = {t.id for t in animation.timeline.tracks if t.owner_id == stage.id}
    assert {track for track, _ in editor.timeline.dope.keys} == expected_source
    refs = tuple(editor.timeline.dope.keys)
    original_keys = animation.timeline
    animation.edit_keys(
        {ref: {"frame": editor.timeline.dope.source[ref].frame + 3} for ref in refs}
    )
    vm.changed.emit()
    assert min(k.frame for t in animation.timeline.tracks for k in t.keyframes) == 3
    doc.undo()
    assert animation.timeline == original_keys
    editor.object_edit.exit()
    saved = tmp_path / "ffd.rigora"
    doc.save(saved)
    doc.open(saved)
    vm.changed.emit()
    assert set(editor.timeline.row_tracks(editor.timeline._groups[owner, "Animation"])) == expected
    assert source.id in {c.id for c in CharacterService(doc).motions(owner)}
    assert doc.project != baseline


def test_scene_vertex_keys_share_one_deformation_lane_under_the_object(panel_editor):
    """Direct mesh keys use the same surface ownership rules as stage-controlled animation."""
    editor = panel_editor
    vm, doc = editor.viewmodel, editor.viewmodel.documents
    mesh_id = AppearanceService(doc).create_shape("rectangle", 100, 100, 120, 120)
    characters = CharacterService(doc)
    mesh = characters.mesh(mesh_id)
    part = str(mesh.object_id)
    owner = characters.create_object((part,), "Vertex Object")
    vertex = next(v for v in mesh.vertices if not v.protected)
    animation = AnimationEditingService(doc)
    animation.key(vertex.id, "x", 0, vertex.x)
    animation.key(vertex.id, "x", 12, vertex.x + 10)
    vm.changed.emit()
    row = editor.timeline._groups.get((owner, "Mesh deformation"))
    assert row is not None and row.parent().data(0, Qt.ItemDataRole.UserRole + 1) == owner
    assert set(editor.timeline.row_tracks(row)) == {t.id for t in animation.timeline.tracks}
    assert len(editor.timeline.dope.keys) == 2


def test_targeted_ffd_is_visible_and_add_track_discovers_nested_object_controls(panel_editor):
    """Compound Object selection exposes deformation stages on its artwork parts in Scene."""
    editor = panel_editor
    vm, doc = editor.viewmodel, editor.viewmodel.documents
    mesh_id = AppearanceService(doc).create_shape("rectangle", 100, 100, 120, 120)
    characters = CharacterService(doc)
    part = str(characters.mesh(mesh_id).object_id)
    owner = characters.create_object((part,), "Elastic Object")
    stage = ContentService(doc).place(motion(), {}, mesh_id=mesh_id)
    vm.changed.emit()
    editor.scene_workspace.select_entries((owner,))
    assert editor.timeline._groups[owner, "Animation"]
    editor.timeline.open_picker()
    picker = editor.timeline.picker
    channels = {
        key
        for i in range(picker.tree.topLevelItemCount())
        for key in row_channels(picker.tree.topLevelItem(i))
    }
    expected = {(t.owner_id, t.property_path) for t in AnimationEditingService(doc).timeline.tracks}
    assert expected <= channels and all(key[0] == stage for key in expected)
    assert not any(
        picker.tree.topLevelItem(i).text(0) == "Mesh Deformation"
        for i in range(picker.tree.topLevelItemCount())
    )


def test_object_editor_ffd_clip_belongs_to_its_object_and_keeps_scene_tracks_separate(panel_editor):
    """A first local FFD action stays editable without becoming a Scene arrangement."""
    editor = panel_editor
    vm, doc = editor.viewmodel, editor.viewmodel.documents
    mesh_id = AppearanceService(doc).create_shape("rectangle", 100, 100, 120, 120)
    characters = CharacterService(doc)
    owner = characters.promote_object(str(characters.mesh(mesh_id).object_id))
    vm.changed.emit()
    editor.object_edit.enter(owner)
    stage = ContentService(doc).place(motion(), {}, mesh_id=mesh_id)
    vm.changed.emit()
    animation = AnimationEditingService(doc)
    assert animation.clip.extra.get("object_id") == owner
    tracks = {t.id for t in animation.timeline.tracks if t.owner_id == stage}
    assert tracks and {key for key, _ in editor.timeline.dope.keys} == tracks
    editor.object_edit.exit()
    vm.changed.emit()
    assert animation.clip is None
    assert not editor.timeline.dope.keys


def test_scene_animation_eye_mutes_ffd_and_lock_blocks_interval_drag(panel_editor, qtbot):
    """Exercise row controls against evaluated geometry and the actual span drag handler."""
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest

    from rigora.domain.project import ProjectError

    editor = panel_editor
    vm, doc = editor.viewmodel, editor.viewmodel.documents
    stage = ContentService(doc).place(motion(), {}, position=(400, 300))
    vm.changed.emit()
    owner = CharacterService(doc).scene_objects()[0]
    mesh = doc.animation.evaluator.deformation.deformers[stage].owner_id
    frame = 12
    active = doc.animation.evaluate(frame).meshes[mesh].positions
    row = editor.timeline._groups[owner, "Animation"]
    assert row.checkState(1) == Qt.CheckState.Unchecked
    row.setCheckState(2, Qt.CheckState.Unchecked)
    qtbot.waitUntil(lambda: not AnimationEditingService(doc).timeline.tracks[0].visible)
    assert doc.animation.evaluate(frame).meshes[mesh].positions != active
    row = editor.timeline._groups[owner, "Animation"]
    row.setCheckState(2, Qt.CheckState.Checked)
    qtbot.waitUntil(lambda: AnimationEditingService(doc).timeline.tracks[0].visible)
    row = editor.timeline._groups[owner, "Animation"]
    row.setCheckState(1, Qt.CheckState.Checked)
    qtbot.waitUntil(lambda: AnimationEditingService(doc).timeline.tracks[0].editing_locked)
    dope = editor.timeline.dope
    assert dope.motions[0]["locked"]
    body = next(item for item in dope.motion_graphics if item.data(6)[1] == "move")
    point = dope.mapFromScene(body.sceneBoundingRect().center())
    before = doc.project
    QTest.mousePress(dope.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert dope._action_drag is None
    QTest.mouseRelease(dope.viewport(), Qt.MouseButton.LeftButton, pos=point + QPoint(30, 0))
    assert doc.project is before
    with pytest.raises(ProjectError, match="Unlock"):
        CharacterService(doc).remove_segment(dope.motions[0]["id"])
    assert doc.animation.evaluate(frame).meshes[mesh].positions == active
