"""Spring Editor motion is discoverable and editable in ordinary timeline channel rows."""

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from test_character_objects_gui import editor as editor
from test_editor_tool_lifecycle_gui import make_chain
from test_object_scene_actions_gui import readable_offscreen_fonts as readable_offscreen_fonts
from test_timeline_title_gui import add_animal

from rigora.application_services.dynamics import DynamicsService

pytestmark = pytest.mark.gui


@pytest.mark.parametrize("object_mode", (False, True))
def test_spring_editor_creates_visible_expandable_editable_timeline_channels(
    editor, qtbot, object_mode
):
    """Use real assignment/test-motion commands in Scene and premade-character Object Editor."""
    vm, timeline = editor.viewmodel, editor.timeline
    if object_mode:
        root = add_animal(editor)
        qtbot.waitUntil(
            lambda: len(editor.viewport.artwork.images) >= len(vm.documents.project.assets),
            timeout=15000,
        )
        editor.object_edit.enter(root)
        child = next(
            b.id for r in vm.scene.service.scene.skeletons for b in r.bones if b.name == "tail"
        )
    else:
        _, child, _ = make_chain(editor)
    editor.show_spring_editor()
    dialog = editor.spring_editor
    vm.rig.select(child)
    dialog.include_children.setChecked(False)
    dialog.assign()
    assert not vm.animation_editor.error
    timeline.search.setText("unrelated filter")
    timeline.only_selected.setChecked(True)
    dialog.create_motion_test()
    vm.playback.pause()
    assert not vm.animation_editor.error
    service = DynamicsService(vm.documents)
    clip = service.clip
    assert clip.extra.get("spring_motion_test")
    assert clip.id in {c.id for c in vm.documents.context_clips()}
    assert timeline.clips.currentData() == clip.id
    if object_mode:
        assert clip.extra["object_id"] == editor.object_edit.key
    assert not timeline.search.text() and not timeline.only_selected.isChecked()
    rows = [row for (_, lane), row in timeline._groups.items() if lane == "Spring"]
    assert rows and all(row.isExpanded() and not row.isHidden() for row in rows)
    tracks = service.timeline.tracks
    assert all(t.extra.get("spring_motion_test") for t in tracks)
    assert sum(row.childCount() for row in rows) == len(tracks)
    assert {(t.id, k.id) for t in tracks for k in t.keyframes} <= set(timeline.dope.keys)
    vm.playback.seek(18)
    assert vm.documents.animation.pose.frame == 18
    assert vm.documents.animation.pose.spring_targets is not None
    row = rows[0]
    before = vm.documents.project
    ids = set(timeline.row_tracks(row))
    row.setCheckState(2, Qt.CheckState.Unchecked)
    qtbot.waitUntil(lambda: all(not t.visible for t in service.timeline.tracks if t.id in ids))
    vm.undo()
    assert vm.documents.project == before
    output = Path("build/spring-timeline-review")
    output.mkdir(parents=True, exist_ok=True)
    timeline.tracks.expandAll()
    editor.grab().save(str(output / ("object.png" if object_mode else "scene.png")))
    dialog.close()


def test_filtered_spring_summary_only_keys_visible_group(editor):
    """Filtering Hair prevents parent-lane context actions from keying hidden Ear tracks."""
    from PySide6.QtWidgets import QMenu

    _, child, tip = make_chain(editor)
    service = DynamicsService(editor.viewmodel.documents)
    service.configure((child,), group="Hair")
    service.configure((tip,), group="Ear")
    service.activation("Hair", True, 0)
    service.activation("Ear", True, 0)
    editor.viewmodel.changed.emit()
    timeline = editor.timeline
    timeline.search.setText("Hair")
    rows = [r for (_, lane), r in timeline._groups.items() if lane == "Spring" and not r.isHidden()]
    ids = tuple(key for row in rows for key in timeline.row_tracks(row))
    assert ids
    assert all(
        t.extra.get("spring_group") == "Hair" for t in service.timeline.tracks if t.id in ids
    )
    menu = QMenu(timeline)
    timeline.add_spring_actions(menu, ids)
    assert any("Off" in action.text() for action in menu.actions())
    editor.viewmodel.playback.seek(12)
    next(action for action in menu.actions() if "Off" in action.text()).trigger()
    active = {r.owner_id for r in editor.viewmodel.documents.animation.evaluator.active_springs(12)}
    assert child not in active and tip in active
    timeline.search.clear()
    ids = tuple(
        key
        for (_, lane), row in timeline._groups.items()
        if lane == "Spring"
        for key in timeline.row_tracks(row)
    )
    assert len(ids) == 2
