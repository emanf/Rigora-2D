"""The documented Scene Tools package performs real edits with transactional Undo and owned UI."""

from pathlib import Path

import pytest

from rigora.application_services.appearance import AppearanceService
from rigora.application_services.characters import CharacterService
from rigora.application_services.documents import DocumentService
from rigora.application_services.plugin_commands import PluginCommandService
from rigora.application_services.plugins import PluginManager
from rigora.application_services.scene_editing import SceneEditingService
from rigora.domain.project import ProjectError
from rigora.infrastructure.preferences import PreferencesStore

PACKAGE = Path(__file__).resolve().parents[1] / "examples/plugins/scene_tools/rigora_scene_tools"
PREFIX = "org.rigora.example.scene_tools"


def tutorial_manager(tmp_path):
    """Trust only the tutorial in a temporary test profile, leaving the owner's profile alone."""
    manager = PluginManager(PreferencesStore(tmp_path / "profile.json"))
    manager.discover((PACKAGE,), installed=False, allowed_roots=(PACKAGE,))
    manager.trust(PREFIX)
    manager.enable(PREFIX)
    return manager


def make_object(document):
    """Create two actual vector parts in one Object for duplicate-root and rollback checks."""
    artwork = AppearanceService(document)
    first = artwork.create_shape("rectangle", 100, 100, 40, 60)
    second = artwork.create_shape("ellipse", 130, 160, 30, 30)
    parts = tuple(str(artwork.mesh(key).object_id) for key in (first, second))
    root = CharacterService(document).create_object(parts, "Tutorial Object")
    return root, parts


def test_documented_plugin_moves_each_root_once_and_rolls_back_invalid_inputs(tmp_path):
    """Two selected parts move once; invalid values and locks preserve project/history."""
    manager = tutorial_manager(tmp_path)
    try:
        doc = DocumentService()
        doc.new()
        root, parts = make_object(doc)
        commands = PluginCommandService(manager)
        before, count = doc.project, len(doc.history.undo_stack)
        state = {"selection": parts}
        initial = doc.animation.pose.nodes[root].local.x
        result = commands.execute(PREFIX + ".nudge", doc, {}, state=state)
        assert result["object_ids"] == (root,) or result["object_ids"] == [root]
        assert doc.animation.pose.nodes[root].local.x == initial + 24
        assert len(doc.history.undo_stack) == count + 1
        doc.undo()
        assert doc.project == before
        doc.redo()
        for value in (float("inf"), 10001, "invalid"):
            source, count = doc.project, len(doc.history.undo_stack)
            with pytest.raises(ProjectError):
                commands.execute(PREFIX + ".nudge", doc, {"distance": value}, state=state)
            assert doc.project is source and len(doc.history.undo_stack) == count
        SceneEditingService(doc).flags((root,), locked=True)
        source, count = doc.project, len(doc.history.undo_stack)
        with pytest.raises(ProjectError, match="Unlock"):
            commands.execute(PREFIX + ".nudge", doc, {}, state=state)
        assert doc.project is source and len(doc.history.undo_stack) == count
    finally:
        manager.shutdown()


@pytest.mark.gui
def test_tutorial_menus_panel_rebind_and_disable_follow_the_current_project(
    qtbot, tmp_path, monkeypatch
):
    """Actual desktop controls dispatch against the selected tab and disappear on disable."""
    from rigora.app.application import ApplicationInfo
    from rigora.presentation.viewmodels.main_window import MainWindowViewModel
    from rigora.presentation.views.main_window import MainWindow

    monkeypatch.setattr(
        "rigora.presentation.widgets.workspace_panels.ContentShelf.load_thumbnails", lambda *_: None
    )
    manager = tutorial_manager(tmp_path)
    model = MainWindowViewModel(ApplicationInfo(), preferences=manager.preferences, plugins=manager)
    window = MainWindow(model)
    window.confirm_discard = lambda: True
    qtbot.addWidget(window)
    window.show()
    try:
        model.new_project()
        root, _ = make_object(model.documents)
        model.changed.emit()
        window.scene_workspace.select_entries((root,))
        action = window.command_actions[PREFIX + ".nudge"]
        assert action.isEnabled()
        assert action in window.plugin_workspace.host.toolbars["Scene tools"].actions()
        window.command_actions[PREFIX + ".show"].trigger()
        panel = next(w for c, w in window.plugin_workspace.bindings if c.id == PREFIX + ".panel")
        assert panel.isVisible() and panel.button.isEnabled()
        first = model.documents
        count = len(first.history.undo_stack)
        panel.distance.setValue(48)
        panel.button.click()
        assert len(first.history.undo_stack) == count + 1
        saved = first.project
        model.new_project()
        assert not panel.button.isEnabled() and not action.isEnabled()
        other, _ = make_object(model.documents)
        model.changed.emit()
        window.scene_workspace.select_entries((other,))
        panel.button.click()
        assert first.project is saved
        manager.disable(PREFIX)
        assert PREFIX + ".nudge" not in window.command_actions
        assert "Scene tools" not in window.plugin_workspace.host.toolbars
        assert not window.plugin_workspace.bindings
    finally:
        window.close()
        manager.shutdown()
