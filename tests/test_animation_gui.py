"""Transport presentation uses elapsed-time services and isolated project tabs."""

from dataclasses import replace

import pytest
from animation_fixtures import open_animation_fixture

pytest.importorskip("PySide6")

from rigora.app.application import ApplicationInfo
from rigora.application_services.commands import ProjectPatch
from rigora.infrastructure.preferences import PreferencesStore
from rigora.presentation.viewmodels.main_window import MainWindowViewModel
from rigora.presentation.views.main_window import MainWindow


@pytest.fixture
def animation_window(qtbot, tmp_path):
    """Create a disposable real shell with isolated preferences and no cleanup prompts."""
    model = MainWindowViewModel(
        ApplicationInfo(), preferences=PreferencesStore(tmp_path / "ui.json")
    )
    window = MainWindow(model)
    qtbot.addWidget(window, before_close_func=lambda w: setattr(w, "confirm_discard", lambda: True))
    window.show()
    open_animation_fixture(model)
    qtbot.wait(1)
    return window


def test_viewmodel_play_pause_seek_stop_elapsed_time_and_tab_isolation(qapp, tmp_path):
    model = MainWindowViewModel(
        ApplicationInfo(), preferences=PreferencesStore(tmp_path / "ui.json")
    )
    open_animation_fixture(model)
    first = model.documents
    model.save_project(tmp_path / "first.rigora")
    playback = model.playback
    now = [100.0]
    playback.clock = lambda: now[0]
    playback.play_pause()
    now[0] += 0.5
    playback.tick()
    assert first.animation.pose.frame == 15
    playback.pause()
    assert not playback.timer.isActive()
    playback.seek(23.5)
    assert first.animation.pose == first.animation.evaluate(23.5)
    open_animation_fixture(model)
    second = model.documents
    playback.seek(7)
    model.activate_project(0)
    assert playback.session is first.animation and first.animation.playback.frame == 23.5
    assert second.animation.playback.frame == 7
    model.show_welcome()
    assert playback.session is first.animation and not playback.timer.isActive()
    model.activate_project(0)
    playback.stop()
    assert first.animation.playback.frame == 0 and not first.dirty


def test_timeline_scrubbing_clip_selection_and_evaluated_viewport(animation_window, tmp_path):
    window = animation_window
    model = window.viewmodel
    model.save_project(tmp_path / "animation.rigora")
    assert window.command_actions["play"].isEnabled()
    expected_keys = {
        (t.id, k.id) for t in model.animation_editor.service.timeline.tracks for k in t.keyframes
    }
    assert set(window.timeline.dope.keys) == expected_keys
    assert window.timeline.tracks.topLevelItemCount() == 2
    assert len(window.viewport.pose.render_order) == 6
    before = window.viewport.grab().toImage()
    window.timeline.frame.setValue(15.25)
    assert window.viewport.pose == model.documents.animation.evaluate(15.25)
    assert window.viewport.grab().toImage() != before
    ruler = window.timeline.dope.ruler
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtTest import QTest

    x = window.timeline.dope.mapFromScene(QPointF(30 * window.timeline.dope.pixels, 0)).x()
    QTest.mouseClick(ruler, Qt.MouseButton.LeftButton, pos=QPoint(x, 10))
    assert window.viewport.pose.frame == 30
    window.timeline.clips.setCurrentIndex(1)
    assert set(window.timeline.dope.keys) == {
        (t.id, k.id)
        for t in model.animation_editor.service.timeline.tracks
        if t.owner_id in window.scene_workspace.items
        for k in t.keyframes
    }
    assert model.documents.animation.playback.range.end == 119
    now = [0.0]
    model.playback.clock = lambda: now[0]
    window.command_actions["play"].trigger()
    assert window.command_actions["play"].property("materialIcon") == "pause"
    now[0] = 0.25
    model.playback.tick()
    assert window.viewport.pose.frame == 7.5
    window.command_actions["stop"].trigger()
    assert window.viewport.pose.frame == 0 and not model.playback.timer.isActive()
    window.command_actions["loop"].trigger()
    assert not model.documents.animation.playback.loop
    assert not model.documents.dirty


def test_unsupported_clip_is_reported_and_another_clip_remains_usable(animation_window):
    window = animation_window
    doc = window.viewmodel.documents
    scene = doc.project.scenes[0]
    bad_track = replace(scene.timelines[0].tracks[0], property_path="future.unsupported")
    bad_timeline = replace(scene.timelines[0], tracks=(bad_track,))
    changed = replace(scene, timelines=(bad_timeline, scene.timelines[1]))
    doc.execute(
        ProjectPatch("Unsupported extension track", {"scenes": (scene,)}, {"scenes": (changed,)})
    )
    window.viewmodel.changed.emit()
    assert "unsupported" in window.viewmodel.playback.error
    assert not window.command_actions["play"].isEnabled()
    assert doc.project.scenes[0] is changed
    window.timeline.clips.setCurrentIndex(1)
    assert not window.viewmodel.playback.error and window.command_actions["play"].isEnabled()
    assert doc.project.scenes[0].timelines[0].tracks[0].property_path == "future.unsupported"
