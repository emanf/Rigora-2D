"""Timeline chrome, grouped editing, live filtering and stage preview menu integration."""

from itertools import product
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QToolButton
from test_timeline_redesign_gui import window as window

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.character_creation import CharacterCreationService
from rigora.application_services.vector_creation import build_vector, vector_colors
from rigora.domain.vector_catalog import VectorRecipe

pytestmark = pytest.mark.gui


def add_animal(window, name="bean"):
    """Insert an actual creator specimen through the same service as the wizard."""
    primary, accent = vector_colors("Animals", name)
    key = CharacterCreationService(window.viewmodel.documents).create(
        build_vector(VectorRecipe(design_id=name, name=name, primary=primary, accent=accent))
    )
    window.viewmodel.changed.emit()
    return key


def click_view(timeline, action, qtbot):
    """Exercise a native popup action through its painted menu hit target."""
    menu = timeline.view_button.menu()
    menu.popup(timeline.view_button.mapToGlobal(QPoint(0, timeline.view_button.height())))
    qtbot.waitUntil(menu.isVisible)
    QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(action).center())
    assert not menu.isVisible()


def test_playback_lives_in_docked_and_floating_titlebar(window, qtbot):
    """The same transport survives floating, theme changes and playback without an extra row."""
    key = add_animal(window)
    window.object_edit.enter(key)
    timeline, dock = window.timeline, window.docks["timeline"]
    assert timeline.transport.parentWidget() is dock.titlebar
    assert timeline.layout().itemAt(0).widget() is timeline.pages
    play = next(
        b
        for b in timeline.transport.findChildren(QToolButton)
        if b.defaultAction() is window.command_actions["play"]
    )
    output = Path("build/timeline-title-review")
    output.mkdir(parents=True, exist_ok=True)
    for theme, width in product(("dark", "light"), (1280, 1500)):
        window.resize(width, 950)
        window.viewmodel.set_theme(theme)
        qtbot.wait(20)
        assert timeline.transport.geometry().right() < dock.titlebar.close_button.geometry().left()
        assert timeline.frame.geometry().bottom() < dock.titlebar.height()
        assert timeline.transport.rect().contains(
            timeline.range_label.rect().translated(
                timeline.range_label.mapTo(timeline.transport, QPoint())
            )
        )
        assert (
            abs(
                timeline.playback_buttons.geometry().center().x()
                - timeline.transport.rect().center().x()
            )
            <= 1
        )
        assert timeline.frame.geometry().left() - timeline.clips.geometry().right() >= 8
        assert timeline.speed.geometry().left() - timeline.max_frame.geometry().right() >= 8
        assert timeline.range_label.geometry().left() - timeline.speed.geometry().right() >= 8
        dock.grab().save(str(output / f"timeline-{theme}.png"))
        dock.grab().save(str(output / f"timeline-{theme}-{width}.png"))
        menu = timeline.view_button.menu()
        menu.popup(timeline.view_button.mapToGlobal(QPoint(0, timeline.view_button.height())))
        qtbot.waitUntil(menu.isVisible)
        menu.grab().save(str(output / f"view-{theme}.png"))
        menu.hide()
    dock.setFloating(True)
    qtbot.wait(20)
    assert timeline.transport.parentWidget() is dock.titlebar
    assert timeline.transport.isVisible() and dock.titlebar.close_button.isVisible()
    assert (
        abs(
            timeline.playback_buttons.geometry().center().x()
            - timeline.transport.rect().center().x()
        )
        <= 1
    )
    QTest.mouseClick(play, Qt.MouseButton.LeftButton)
    assert window.viewmodel.playback.session.playback.is_playing
    QTest.mouseClick(play, Qt.MouseButton.LeftButton)
    assert not window.viewmodel.playback.session.playback.is_playing
    dock.setFloating(False)
    qtbot.wait(20)
    assert timeline.transport.isVisible()
    timeline.pages.setCurrentWidget(timeline.clip_editor)
    qtbot.wait(20)
    dock.grab().save(str(output / "clips-spacing.png"))
    window.object_edit.exit()
    timeline.pages.setCurrentWidget(timeline.motion_blocks)
    qtbot.wait(20)
    dock.grab().save(str(output / "motion-spacing.png"))


def test_object_property_groups_filter_real_members_and_restore_individual_view(window, qtbot):
    """A filtered grouped lane edits matching channels atomically and restores disclosure."""
    key = add_animal(window)
    window.object_edit.enter(key)
    vm, timeline = window.viewmodel, window.timeline
    service = AnimationEditingService(vm.documents)
    head = next(b for rig in service.scene.skeletons for b in rig.bones if b.name == "head")
    service.add_channels(((head.id, "opacity"), (head.id, "visibility")), frame=0)
    vm.changed.emit()
    assert timeline.group_properties.isChecked()
    assert [timeline.tracks.topLevelItem(i).text(0) for i in range(3)] == [
        "TRANSFORM",
        "OPACITY",
        "VISIBILITY",
    ]
    baseline, count = vm.documents.project, len(vm.documents.history.undo_stack)
    timeline.search.setText("  HEAD rotation  ")
    group = timeline._groups["", "Transform"]
    head_branch = {head.id} | {
        b.id for rig in service.scene.skeletons for b in rig.bones if b.parent_id == head.id
    }
    expected = {
        t.id
        for t in service.timeline.tracks
        if t.owner_id in head_branch and t.property_path == "transform.rotation"
    }
    assert expected and set(timeline.row_tracks(group)) == expected
    assert {ref[0] for ref in timeline.dope.keys} == expected
    group.setCheckState(1, Qt.CheckState.Checked)
    qtbot.waitUntil(lambda: len(vm.documents.history.undo_stack) == count + 1)
    assert len(vm.documents.history.undo_stack) == count + 1
    assert {t.id for t in service.timeline.tracks if t.locked} == expected
    vm.undo()
    assert vm.documents.project == baseline
    baseline = vm.documents.project
    timeline.search.setText("no matching part")
    assert not timeline.dope.keys
    timeline.search.clear()
    timeline.group_properties.setChecked(False)
    timeline.tracks.collapseAll()
    first = timeline.tracks.topLevelItem(0)
    assert not first.isExpanded()
    timeline.search.setText("head rotation")
    assert {ref[0] for ref in timeline.dope.keys} == expected
    assert first.isExpanded()
    timeline.search.clear()
    assert not first.isExpanded()
    timeline.group_properties.setChecked(True)
    vm.scene.select((head.id,))
    timeline.only_selected.setChecked(True)
    visible = {
        t.owner_id
        for t in service.timeline.tracks
        if t.id in timeline.row_tracks(timeline._groups["", "Transform"])
    }
    assert visible == head_branch
    assert vm.documents.project is baseline


def test_scene_keeps_separate_named_character_property_rows(window):
    """Grouping Object Editor parts never merges distinct scene characters' animation."""
    roots = [add_animal(window, name) for name in ("bean", "tansy")]
    vm = window.viewmodel
    service = AnimationEditingService(vm.documents)
    service.add_channels(
        tuple(
            (key, path)
            for key in roots
            for path in ("transform.x", "transform.rotation", "opacity", "visibility")
        ),
        frame=0,
    )
    vm.changed.emit()
    timeline = window.timeline
    assert not timeline.group_properties.isEnabled()
    assert {
        timeline.tracks.topLevelItem(i).text(0) for i in range(timeline.tracks.topLevelItemCount())
    } == {"bean", "tansy"}
    for key in roots:
        for lane in ("Transform", "Opacity", "Visible"):
            row = timeline._groups[key, lane]
            assert row.parent() is not None
            assert all(
                t.owner_id == key
                for t in service.timeline.tracks
                if t.id in timeline.row_tracks(row)
            )


def test_view_menu_controls_ruler_and_animated_bone_overlays(window, qtbot, monkeypatch):
    """Menu toggles change rendered previews, retain comparison time and never author data."""
    key = add_animal(window)
    window.object_edit.enter(key)
    vm, timeline = window.viewmodel, window.timeline
    service = AnimationEditingService(vm.documents)
    service.marker("Action / Passing / Opposite", 12)
    vm.changed.emit()
    window.rig_workspace.set_mode(True)
    vm.playback.seek(10)
    assert vm.rig.animating and window.viewport.rig_mode
    baseline, count = vm.documents.project, len(vm.documents.history.undo_stack)
    ruler = timeline.dope.ruler
    labels = ruler.grab().toImage()
    markers, keys = timeline.dope.markers, set(timeline.dope.keys)
    click_view(timeline, timeline.marker_labels, qtbot)
    assert not ruler.show_marker_labels
    assert ruler.grab().toImage() != labels
    assert timeline.dope.markers == markers and set(timeline.dope.keys) == keys
    click_view(timeline, timeline.compare, qtbot)
    assert vm.animation_editor.compare == 10
    vm.playback.seek(20)
    click_view(timeline, timeline.onion, qtbot)
    click_view(timeline, timeline.trails, qtbot)
    assert vm.animation_editor.compare == 10
    assert {pose.frame for pose in window.viewport.ghost_poses} == {10, 19, 21}
    assert window.viewport.motion_trails
    painted = []
    draw = window.viewport._draw_pose

    def record(*args, **kwargs):
        """Observe actual ghost drawing while preserving the production renderer."""
        if kwargs.get("labels") is False:
            painted.append(args[2].frame)
        return draw(*args, **kwargs)

    monkeypatch.setattr(window.viewport, "_draw_pose", record)
    window.viewport.grab()
    assert {10, 19, 21} <= set(painted)
    click_view(timeline, timeline.snap, qtbot)
    assert not timeline.dope.snap and not vm.playback.snap and not vm.animation_editor.snap
    click_view(timeline, timeline.trails, qtbot)
    click_view(timeline, timeline.onion, qtbot)
    click_view(timeline, timeline.compare, qtbot)
    assert not window.viewport.ghost_poses and not window.viewport.motion_trails
    assert vm.documents.project is baseline and len(vm.documents.history.undo_stack) == count
    timeline.compare.setChecked(True)
    vm.new_project()
    assert not timeline.compare.isChecked()
