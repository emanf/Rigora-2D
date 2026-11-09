"""Camera card auditions share scene rendering without authoring or moving the source cursor."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from test_roots_soft_drag_gui import editor as editor

from rigora.application_services.cameras import CameraService
from rigora.application_services.scene_editing import SceneEditingService
from rigora.engine.cameras import active_camera

pytestmark = pytest.mark.gui


def camera_preview(editor, kind, preset):
    """Open a real action dialog with a target camera interrupted by a later source cut."""
    doc = editor.viewmodel.documents
    cameras = CameraService(doc)
    first = doc.scene.cameras[0].id
    target = cameras.add("Audition camera")
    cameras.update(target, background_mode="color", background_color="#334455")
    SceneEditingService(doc).set_transform(target, x=180, y=60)
    cameras.activate(first, frame=30)
    editor.viewmodel.changed.emit()
    editor.viewmodel.playback.seek(12)
    editor.timeline.open_action({"owner": target, "kind": kind, "frame": 20})
    dialog = editor.timeline.action_editor
    dialog.select_choice(target if kind == "camera_cut" else preset)
    dialog.build_preview()
    dialog._preview_debounce.stop()
    dialog._preview_timer.stop()
    return doc, first, target, dialog


@pytest.mark.parametrize(
    "kind,preset", (("camera_cut", ""), ("camera_motion", "earthquake"), ("camera_effect", "rain"))
)
def test_card_choice_previews_in_scene_without_source_edits_and_restores_on_escape(
    editor, qtbot, kind, preset
):
    """Cut, motion and effect cards preview the chosen camera despite conflicting saved cuts."""
    doc, first, target, dialog = camera_preview(editor, kind, preset)
    qtbot.addWidget(dialog)
    original, history = doc.project, len(doc.history.undo_stack)
    clip = doc.selected_clip_id
    assert dialog._preview_document is not None, dialog.note.text()
    assert editor.timeline.editor.preview_pose is editor.viewport.source_pose
    assert active_camera(editor.viewport.pose).id == target
    assert active_camera(doc.animation.pose).id == first
    assert editor.viewport.camera_backdrop[0] == target
    if kind == "camera_effect":
        assert editor.viewport.camera_lens is not None
        assert editor.viewport.camera_lens[1].isValid()
    if kind == "camera_motion":
        displayed = editor.viewport.pose.nodes[target].world_matrix
        saved = doc.animation.evaluate(editor.viewport.pose.frame).nodes[target].world_matrix
        assert displayed != saved
    if kind != "camera_cut":
        scratch, frame = dialog._preview_document, editor.viewport.pose.frame
        qtbot.wait(50)
        dialog.preview_tick()
        assert dialog._preview_document is scratch
        assert editor.viewport.pose.frame != frame
    assert doc.project is original and len(doc.history.undo_stack) == history
    assert doc.animation.pose.frame == 12 and doc.selected_clip_id == clip

    dialog.preview.setChecked(False)
    assert editor.timeline.editor.preview_pose is None
    assert active_camera(editor.viewport.pose).id == first and editor.viewport.pose.frame == 12
    dialog.preview.setChecked(True)
    dialog.build_preview()
    assert editor.timeline.editor.preview_pose is not None
    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    assert not dialog.isVisible() and not dialog._preview_timer.isActive()
    assert editor.timeline.editor.preview_pose is None and editor.viewport.pose.frame == 12
    assert doc.project is original and len(doc.history.undo_stack) == history


def test_apply_commits_only_the_camera_action_and_source_changes_cancel_auditions(editor, qtbot):
    """Apply adds one source edit, while external edits discard the stale preview immediately."""
    doc, first, target, dialog = camera_preview(editor, "camera_effect", "rain")
    qtbot.addWidget(dialog)
    history = len(doc.history.undo_stack)
    cuts = [
        t for line in doc.scene.timelines for t in line.tracks if t.property_path == "camera.active"
    ]
    dialog.select_choice("blood")
    dialog.build_preview()
    assert set(editor.viewport.pose.cameras[1].extra["lens_effects"]) == {"blood"}
    dialog.apply()
    assert not editor.timeline.editor.error, dialog.note.text()
    assert len(doc.history.undo_stack) == history + 1
    assert editor.timeline.editor.preview_pose is None
    assert not dialog._preview_timer.isActive() and not dialog._preview_debounce.isActive()
    assert active_camera(editor.viewport.pose).id == first
    assert [
        t for line in doc.scene.timelines for t in line.tracks if t.property_path == "camera.active"
    ] == cuts
    assert any(
        t.owner_id == target and t.property_path == "camera.effect.blood"
        for line in doc.scene.timelines
        for t in line.tracks
    )
    dialog.select_choice("snow")
    dialog.build_preview()
    assert editor.timeline.editor.preview_pose is not None
    CameraService(doc).update(first, name="Renamed camera")
    editor.viewmodel.changed.emit()
    assert editor.timeline.editor.preview_pose is None
    assert not dialog._preview_timer.isActive()
    dialog.close()


def test_real_card_clicks_and_settings_rebuild_live_preview_and_close_cancels_pending_work(
    editor, qtbot
):
    """Card/field edits update the scene automatically; pending work cannot reopen a preview."""
    doc, first, target, dialog = camera_preview(editor, "camera_effect", "rain")
    qtbot.addWidget(dialog)
    original, history = doc.project, len(doc.history.undo_stack)
    scratch = dialog._preview_document
    item = next(
        dialog.cards.item(i)
        for i in range(dialog.cards.count())
        if dialog.cards.item(i).data(Qt.ItemDataRole.UserRole) == "vignette"
    )
    dialog.cards.scrollToItem(item)
    QTest.mouseClick(
        dialog.cards.viewport(),
        Qt.MouseButton.LeftButton,
        pos=dialog.cards.visualItemRect(item).center(),
    )
    qtbot.waitUntil(lambda: dialog._preview_document is not scratch, timeout=5000)
    assert dialog._preview_document is not None, dialog.note.text()
    assert dialog._preview_timer.isActive()
    assert active_camera(editor.viewport.pose).id == target
    camera = next(c for c in editor.viewport.pose.cameras if c.id == target)
    assert set(camera.extra["lens_effects"]) == {"vignette"}
    dialog.grab().save("build/camera-preview-cards.png")
    editor.viewport.grab().save("build/camera-action-live-preview.png")
    scratch = dialog._preview_document
    dialog.amount.setValue(0.35)
    dialog.speed.setValue(2)
    dialog.end.setValue(60)
    qtbot.waitUntil(lambda: dialog._preview_document is not scratch, timeout=5000)
    windows = [
        t.extra["camera_action"]
        for line in dialog._preview_document.scene.timelines
        for t in line.tracks
        if "camera_action" in t.extra
    ]
    assert windows and all(w["amount"] == 0.35 and w["speed"] == 2 for w in windows)
    assert all(w["end"] == 60 for w in windows)
    assert doc.project is original and len(doc.history.undo_stack) == history
    dialog.select_choice("grain")
    assert dialog._preview_debounce.isActive()
    dialog.close()
    qtbot.wait(120)
    assert not dialog._preview_debounce.isActive() and not dialog._preview_timer.isActive()
    assert editor.timeline.editor.preview_pose is None
    assert active_camera(editor.viewport.pose).id == first and editor.viewport.pose.frame == 12
