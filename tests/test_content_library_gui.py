"""Offline browser discovery, previews, semantic application, favorites and local pack sharing."""

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPointF, Qt, QThread
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel
from test_object_scene_actions_gui import readable_offscreen_fonts as readable_offscreen_fonts

from rigora.app.application import ApplicationInfo
from rigora.application_services.content_library import ContentService
from rigora.domain.character_recipe import MOTION_CHOICES
from rigora.infrastructure.preferences import PreferencesStore
from rigora.presentation.viewmodels.main_window import MainWindowViewModel
from rigora.presentation.views.main_window import MainWindow


@pytest.fixture
def library_window(qtbot, tmp_path):
    """Open the real custom browser with isolated on-disk library/preferences."""
    import gc

    gc.collect()
    vm = MainWindowViewModel(ApplicationInfo(), preferences=PreferencesStore(tmp_path / "ui.json"))
    window = MainWindow(vm)
    window.confirm_discard = lambda: True
    qtbot.addWidget(window)
    window.show()
    window.command_actions["library"].trigger()
    browser = window.content_browser
    qtbot.waitUntil(
        lambda: not vm.content.busy and browser.preview_document is not None, timeout=10000
    )
    yield window, browser
    browser.close()
    window.close()
    gc.collect()


def select(browser, name, qtbot):
    """Filter one named installed asset and wait for its isolated preview to validate."""
    browser.collection.setCurrentText("All")
    browser.character_view.setCurrentIndex(0)
    browser.search.setText(name)
    qtbot.waitUntil(lambda: not browser.model.busy, timeout=10000)
    assert browser.current.item.name == name


def test_source_badges_and_available_scenery_categories(library_window, qtbot):
    """Cached PNG posters do not advertise raster source artwork."""
    from rigora.presentation.widgets.asset_cards import FORMAT_ROLE

    window, browser = library_window
    shelf = window.content_shelf
    shelf.collection.setCurrentText("Environment")
    assert shelf.results.count() == 17
    assert all(
        shelf.results.item(i).data(FORMAT_ROLE) == "SVG" for i in range(shelf.results.count())
    )
    shelf.prop_family.setCurrentIndex(shelf.prop_family.findData("trees"))
    assert shelf.results.count() == 4
    browser.character_view.setCurrentIndex(0)
    browser.collection.setCurrentText("Vehicles")
    qtbot.waitUntil(lambda: not browser.model.busy, timeout=15000)
    assert browser.results.count() == 8
    assert browser.character_view.count() == 2
    assert {browser.results.item(i).data(FORMAT_ROLE) for i in range(browser.results.count())} == {
        "SVG"
    }


def test_reference_kids_have_decodable_thumbnails_and_working_browser_preview(
    library_window, qtbot
):
    """The real browser decodes and applies independent SVG parts, including the ponytail."""
    window, browser = library_window
    for name in ("Dash · Runner", "Scout · Explorer"):
        select(browser, name, qtbot)
        assert not browser.model.error
        assert browser.preview_document is not None
        assert browser.scene_clip.currentText() == "Stand"
        assert browser.scene_clip.count() == len(MOTION_CHOICES)
        assert browser._loaded
        assert len(browser.preview_document.project.scenes[0].meshes) >= 40
    browser.apply()
    qtbot.waitUntil(lambda: not browser.model.busy, timeout=15000)
    assert len(window.viewmodel.documents.project.scenes[0].meshes) == len(
        browser.preview_document.project.scenes[0].meshes
    )


def test_prop_family_filters_and_browsing_use_prebuilt_posters(library_window, qtbot, monkeypatch):
    """Both browsers expose twelve-item families; catalog refresh loads PNG posters only."""
    from rigora.presentation.widgets import workspace_panels

    window, browser = library_window
    original = workspace_panels.decode_artwork
    decoded = []
    limits = []

    def record(data, limit):
        """Observe poster decoding without replacing the real image-loading path."""
        decoded.append(data[:8])
        limits.append(limit)
        return original(data, limit)

    monkeypatch.setattr(workspace_panels, "decode_artwork", record)
    browser.model.reload()
    qtbot.waitUntil(lambda: not browser.model.busy, timeout=15000)
    assert len(decoded) == 287 and set(decoded) == {b"\x89PNG\r\n\x1a\n"}
    assert set(limits) == {144}
    for category, family, count in (
        ("Environment", "trees", 4),
        ("Environment", "bushes", 6),
        ("Environment", "terrain", 4),
    ):
        browser.collection.setCurrentText(category)
        browser.prop_family.setCurrentIndex(browser.prop_family.findData(family))
        qtbot.waitUntil(lambda: not browser.model.busy, timeout=15000)
        assert browser.results.count() == count
        assert all(
            family in browser.results.item(i).data(Qt.ItemDataRole.UserRole).item.tags
            for i in range(count)
        )
    shelf = window.content_shelf
    shelf.collection.setCurrentText("Environment")
    shelf.prop_family.setCurrentIndex(shelf.prop_family.findData("trees"))
    assert shelf.results.count() == 4
    shelf.results.setCurrentRow(0)
    shelf.preview()
    qtbot.waitUntil(lambda: not browser.model.busy, timeout=15000)
    assert browser.results.count() == 4 and browser.prop_family.currentData() == "trees"
    assert not browser.search.text()
    browser.collection.setCurrentText("Characters")
    qtbot.waitUntil(lambda: not browser.model.busy, timeout=15000)
    assert browser.results.count() == 5


def test_shelf_preview_keeps_other_characters_visible_across_performance_changes(
    library_window, qtbot
):
    """Opening one docked character selects its row without silently filtering out its peers."""
    window, browser = library_window
    shelf = window.content_shelf
    shelf.collection.setCurrentText("Characters")
    shelf.results.setCurrentRow(0)
    browser.search.setText("Dash")
    qtbot.waitUntil(lambda: not browser.model.busy, timeout=15000)
    shelf.preview()
    qtbot.waitUntil(lambda: not browser.model.busy, timeout=15000)
    assert not browser.search.text()
    assert browser.results.count() == 5
    names = (
        "Dash · Runner",
        "Willow · Dancer",
        "Reed · Tall sketch",
        "Scout · Explorer",
        "Bolt · Stick robot",
    )
    for name in names:
        index = next(
            i for i in range(browser.results.count()) if browser.results.item(i).text() == name
        )
        browser.results.setCurrentRow(index)
        qtbot.waitUntil(lambda: not browser.model.busy, timeout=15000)
        for action in ("Walk", "Run") if name.startswith("Bolt") else ("Walk", "Run"):
            browser.scene_clip.setCurrentText(action)
            assert browser.preview_document is not None
            assert browser.preview_document.animation.evaluator.clip.name == action
            assert browser.results.count() == 5 and not browser.search.text()
            assert not browser.compatibility.text()
    index = next(
        i for i in range(browser.results.count()) if browser.results.item(i).text() == names[0]
    )
    browser.results.setCurrentRow(index)
    qtbot.waitUntil(lambda: not browser.model.busy, timeout=15000)
    assert browser.scene_clip.currentText() == "Run"
    assert browser.preview_document.animation.evaluator.clip.name == "Run"
    assert "5 of 287" in browser.status.text()
    assert window.viewmodel.documents.project is None
    browser.search.setText("no such character anywhere")
    assert browser.results.count() == 0 and "0 of 287" in browser.status.text()
    browser.search.clear()
    qtbot.waitUntil(lambda: not browser.model.busy, timeout=15000)
    assert browser.results.count() == 5


def test_library_refresh_discards_performance_payload_from_an_older_template(
    library_window, qtbot, monkeypatch
):
    """A changed template cannot retain old artwork behind a saved performance choice."""
    from dataclasses import replace
    from uuid import uuid4

    from rigora.domain.validation import json_copy

    _window, browser = library_window
    select(browser, "Dash · Runner", qtbot)
    browser.scene_clip.setCurrentText("Run")
    qtbot.waitUntil(lambda: not browser.model.busy, timeout=15000)
    key = browser.current.key
    assert key in browser.model.scene_performances
    payload = json_copy(browser.current.item.payload)
    from rigora.application_services.content_library import content_project

    payload["project"] = content_project(browser.current.item, browser.files).to_dict()
    payload.pop("performance_clips", None)
    clips = payload["project"]["scenes"][0]["clips"]
    for clip in clips:
        clip["id"] = str(uuid4())
    run_id = next(c["id"] for c in clips if c["name"] == "Run")
    payload["selected_clip"] = run_id
    revised = tuple(
        replace(entry, item=replace(entry.item, version="next", payload=payload))
        if entry.key == key
        else entry
        for entry in browser.model.entries
    )
    monkeypatch.setattr(browser.model.library, "entries", lambda: revised)
    browser.model.reload()
    qtbot.waitUntil(lambda: not browser.model.busy, timeout=15000)
    assert browser.model.scene_performances[key].version == "next"
    assert browser.model.entry(key).item.version == "next"
    assert browser.scene_clip.currentText() == "Run"
    assert browser.scene_clip.currentData() == run_id
    assert browser.preview_document.animation.evaluator.clip.name == "Run"
    configured = browser.model.entry(key).item.payload["project"]["scenes"][0]
    assert configured["clips"][0]["id"] == run_id


def test_browser_recovers_when_pack_changes_between_character_selections(
    library_window, qtbot, tmp_path, monkeypatch
):
    """A live pack rebuild refreshes stale source maps before constructing another preview."""
    from dataclasses import replace

    from rigora.infrastructure.content_packs import read_pack, write_pack

    _window, browser = library_window
    select(browser, "Dash · Runner", qtbot)
    original = browser.current
    pack, files = read_pack(original.path)
    path = tmp_path / "live-templates.rigpack"
    write_pack(path, pack, files)
    redirected = tuple(
        replace(e, path=path) if e.path == original.path else e for e in browser.model.entries
    )
    browser.model.entries = redirected
    browser.model.changed.emit()
    qtbot.waitUntil(lambda: not browser.model.busy, timeout=15000)
    updated = replace(pack, items=tuple(replace(i, version="rebuilt") for i in pack.items))
    write_pack(path, updated, files, overwrite=True)
    by_id = {i.id: i for i in updated.items}
    monkeypatch.setattr(
        browser.model.library,
        "entries",
        lambda: tuple(
            replace(e, pack=updated, item=by_id[e.item.id]) if e.path == path else e
            for e in redirected
        ),
    )
    # No Refresh click: selecting a sibling reads the changed archive and triggers recovery.
    select(browser, "Scout · Explorer", qtbot)
    assert browser.current.item.version == "rebuilt"
    assert browser.preview_document is not None and not browser.model.error
    browser.scene_clip.setCurrentText("Run")
    assert browser.preview_document.animation.evaluator.clip.name == "Run"
    select(browser, "Dash · Runner", qtbot)
    assert browser.current.item.version == "rebuilt" and browser.preview_document is not None


def test_preview_apply_pose_motion_favorites_and_undo(library_window, qtbot, monkeypatch, qapp):
    """Previews stay isolated while rig, pose and clip application edits the actual project."""
    window, browser = library_window
    vm = window.viewmodel
    assert len(vm.content.entries) == 287
    assert vm.documents.project is None
    original = ContentService.preview
    threads = []

    def checked_preview(self, *args, **kwargs):
        """Record GUI ownership of scratch command evaluation after worker storage reads."""
        threads.append(QThread.currentThread())
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ContentService, "preview", checked_preview)
    select(browser, "Human · full body", qtbot)
    assert browser.preview.pose.nodes and vm.documents.project is None
    assert not browser.compatibility.text()
    browser.apply()
    assert len(vm.documents.project.scenes[0].skeletons) == 1
    assert len(vm.documents.history.undo_stack) == 1
    assert vm.rig.active
    baseline = vm.documents.project
    select(browser, "Relaxed · Walk", qtbot)
    assert browser.preview_document.project != baseline and vm.documents.project is baseline
    browser.apply()
    assert vm.documents.project != baseline
    vm.undo()
    assert vm.documents.project == baseline
    select(browser, "Idle", qtbot)
    browser.favorite_button.click()
    qtbot.waitUntil(lambda: not vm.content.busy, timeout=10000)
    assert vm.content.library.favorite(browser.current.key)
    assert browser.timer.isActive()
    qtbot.wait(100)
    assert browser.preview_document.animation.pose.frame > 0
    assert vm.documents.project == baseline
    browser.apply()
    assert vm.documents.animation.evaluator.clip.name == "Idle"
    assert not vm.rig.active
    assert vm.documents.animation.evaluate(0).nodes != vm.documents.animation.evaluate(11.5).nodes
    vm.undo()
    assert vm.documents.project == baseline
    select(browser, "Cat · Walk", qtbot)
    assert "anatomy" in browser.compatibility.text()
    source = vm.documents.project
    browser.apply()
    assert vm.documents.project is source and browser.preview_document is not None
    assert threads and all(thread == qapp.thread() for thread in threads)


def test_install_export_user_rig_and_drag_drop_into_viewport(
    library_window, qtbot, tmp_path, monkeypatch
):
    """Portable packs install off-thread, and internal drops resolve installed identities only."""
    from rigora.presentation.widgets import content_browser

    window, browser = library_window
    vm = window.viewmodel
    select(browser, "Human · full body", qtbot)
    browser.apply()
    destination = tmp_path / "shared rig.rigpack"
    monkeypatch.setattr(content_browser, "choose_save_file", lambda *args: (str(destination), ""))
    browser.share_name.setText("My custom biped")
    browser.export(True)
    assert destination.is_file()
    monkeypatch.setattr(content_browser, "choose_open_file", lambda *args: (str(destination), ""))
    browser.install()
    qtbot.waitUntil(lambda: not vm.content.busy and len(vm.content.entries) == 288, timeout=10000)
    select(browser, "My custom biped", qtbot)
    before = len(vm.documents.project.scenes[0].skeletons)
    mime = browser.results.mimeData([browser.results.currentItem()])
    viewport = window.viewport
    enter = QDragEnterEvent(
        viewport.rect().center(),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(viewport, enter)
    assert enter.isAccepted()
    event = QDropEvent(
        QPointF(viewport.rect().center()),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(viewport, event)
    qtbot.waitUntil(lambda: not vm.content.busy, timeout=10000)
    assert len(vm.documents.project.scenes[0].skeletons) == before + 1
    vm.undo()
    assert len(vm.documents.project.scenes[0].skeletons) == before


def test_preview_autoplays_loops_through_properties_and_reopen(library_window, qtbot):
    """Animated preview preferences survive strength/speed edits, selection, pause and reopen."""
    window, browser = library_window
    select(browser, "Soft breathing", qtbot)
    assert browser.timer.isActive() and browser.loop_preview.isChecked()
    assert browser.preview_document.animation.playback.loop
    assert not browser.preview.mesh_wireframe
    browser.mesh_overlay.setChecked(True)
    assert browser.preview.mesh_wireframe and browser.timer.isActive()
    browser.mesh_overlay.setChecked(False)
    qtbot.wait(150)
    original = browser.model.document.project if browser.model.document else None
    phase = browser.preview_document.animation.pose.frame
    browser.ffd_strength.setValue(0.6)
    assert browser.timer.isActive()
    assert browser.preview_document.animation.pose.frame == pytest.approx(phase)
    browser.ffd_speed.setValue(1.4)
    assert browser.timer.isActive()
    before = browser.preview_document.animation.pose.frame
    qtbot.wait(100)
    assert browser.preview_document.animation.pose.frame != before
    end = browser.preview_document.animation.playback.range.end
    browser.preview_document.animation.seek(end - 0.1)
    qtbot.wait(100)
    assert browser.preview_document.animation.pose.frame < end
    browser.play_preview()
    assert not browser.timer.isActive()
    browser.ffd_strength.setValue(0.7)
    assert not browser.timer.isActive()
    browser.play_preview()
    browser.close()
    browser.show()
    assert browser.timer.isActive()
    assert (browser.model.document.project if browser.model.document else None) is original
    select(browser, "Dash · Runner", qtbot)
    assert browser.preview.pose.meshes and not browser.preview.show_bones
    assert browser.preview.height() >= 320


def test_drop_character_on_welcome_creates_project(library_window, qtbot):
    """Welcome accepts a real template drop even when the project viewport is hidden."""
    window, browser = library_window
    select(browser, "Reed · Tall sketch", qtbot)
    assert browser.model.document is None
    mime = browser.results.mimeData([browser.results.currentItem()])
    qtbot.waitUntil(lambda: window.welcome_window is not None)
    target = window.welcome_window.content
    point = target.rect().center()
    enter = QDragEnterEvent(
        point,
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(target, enter)
    assert enter.isAccepted()
    drop = QDropEvent(
        QPointF(point),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(target, drop)
    qtbot.waitUntil(lambda: not window.viewmodel.content.busy, timeout=15000)
    assert len(window.viewmodel.documents.project.scenes[0].meshes) == len(
        browser.preview_document.project.scenes[0].meshes
    )


def test_switch_from_character_motion_to_ffd(library_window, qtbot):
    """A populated character scene retains responsive previews across content kinds."""
    window, browser = library_window
    select(browser, "Dash · Runner", qtbot)
    browser.apply()
    for name in (
        "Reed · Tall sketch",
        "Bolt · Stick robot",
        "Natural · Walk",
        "Soft breathing",
    ):
        select(browser, name, qtbot)
        assert browser.preview_document is not None, (
            name,
            browser.compatibility.text(),
            browser.model.error,
            browser._loaded,
        )
    assert browser.timer.isActive()


def test_unchanged_pack_reuses_thumbnail_decodes(library_window, qtbot, monkeypatch):
    """Changing template kinds reuses validated pack bytes and already decoded thumbnails."""
    from rigora.presentation.widgets import content_browser

    _, browser = library_window
    previous = dict(browser._decoded)
    decoded = []
    original = content_browser.decode_artwork

    def decode(data, limit):
        """Record real decode work without altering native SVG/image behavior."""
        import hashlib

        digest = hashlib.sha256(data).hexdigest()
        decoded.append(digest)
        return original(data, limit)

    monkeypatch.setattr(content_browser, "decode_artwork", decode)
    select(browser, "Natural · Walk", qtbot)
    assert not set(decoded).intersection(previous)
    assert browser.preview_document is not None


def test_studio_performance_preview_apply_and_drag_share_clip_choice(library_window, qtbot):
    """Performance selection changes the scratch preview and both application routes."""
    window, browser = library_window
    select(browser, "Dash · Runner", qtbot)
    assert [browser.scene_clip.itemText(i) for i in range(browser.scene_clip.count())] == list(
        MOTION_CHOICES
    )
    browser.scene_clip.setCurrentIndex(browser.scene_clip.findText("Run"))
    assert browser.preview_document.animation.evaluator.clip.name == "Run"
    assert browser.current.item.payload["performance_clips"][0]["name"] == "Stand"
    configured = window.viewmodel.content.entry(browser.current.key)
    assert configured.item.payload["selected_clip"] == browser.scene_clip.currentData()
    browser.apply()
    assert window.viewmodel.documents.animation.evaluator.clip.extra.get("motion_sequence")
    assert any(
        t.extra.get("motion_window", {}).get("name") == "Run"
        for t in window.viewmodel.documents.project.scenes[0].timelines[-1].tracks
    )
    assert set(MOTION_CHOICES) <= {
        c.name for c in window.viewmodel.documents.project.scenes[0].clips
    }
    window.viewmodel.undo()
    window.content_drop.cache[configured.path] = (browser.files, {})
    window.content_drop.drop(configured.key, QPointF(window.viewport.rect().center()))
    qtbot.waitUntil(lambda: not window.content_drop.placing, timeout=15000)
    assert window.viewmodel.documents.animation.evaluator.clip.extra.get("motion_sequence")
    assert any(
        t.extra.get("motion_window", {}).get("name") == "Run"
        for t in window.viewmodel.documents.project.scenes[0].timelines[-1].tracks
    )


def test_welcome_has_no_study_buttons_and_reusable_packs_remain_available(library_window, qtbot):
    """Welcome omits examples while normal library browsing retains reusable character packs."""
    window, browser = library_window
    qtbot.waitUntil(lambda: window.welcome_window is not None)
    texts = [w.text() for w in window.welcome_window.findChildren(QAbstractButton)]
    labels = [w.text() for w in window.welcome_window.findChildren(QLabel)]
    assert not any(
        text.startswith(("Animation study", "Rigging study", "People ·", "Animals ·"))
        for text in texts
    )
    assert "EXAMPLES & CHARACTER STUDIES" not in labels
    assert "demo" not in window.command_actions and "rig_demo" not in window.command_actions
    window.open_content_library("Characters")
    browser.search.clear()
    qtbot.waitUntil(lambda: not browser.model.busy, timeout=10000)
    assert browser.results.count() == 5
    assert window.viewmodel.documents.project is None
    window.open_content_library("Animals")
    browser.search.clear()
    qtbot.waitUntil(lambda: not browser.model.busy, timeout=10000)
    assert browser.results.count() == 3
    browser.hide()
    window.viewmodel.show_welcome()
    output = Path("build/welcome-cleanup-review.png")
    window.grab().save(str(output))


def test_hidden_library_never_runs_specimen_animation(library_window, qtbot):
    """Shelf application and document refresh cannot restart a hidden browser's animation."""
    window, browser = library_window
    browser.hide()
    select(browser, "Dash · Runner", qtbot)
    assert browser.preview_document is not None and browser._playing
    assert not browser.timer.isActive()
    window.viewmodel.content.bind(window.viewmodel.content.document)
    qtbot.waitUntil(lambda: not browser.model.busy, timeout=15000)
    assert not browser.timer.isActive()
    browser.tick()
    assert not browser.timer.isActive()
    browser.show()
    assert browser.timer.isActive()
    browser.hide()
    assert not browser.timer.isActive()
