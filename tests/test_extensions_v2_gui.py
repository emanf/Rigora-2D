"""Real editor integration for declarative extensions and independently owned UI contributions."""

import zipfile
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMenu
from test_roots_soft_drag_gui import editor as editor

from rigora.sdk.scaffold import generate_plugin

ROOT = Path(__file__).resolve().parents[1]
STUDIO = "org.rigora.studio_tools"
HEALTH = "org.rigora.rig_health"
pytestmark = pytest.mark.gui


def test_integrated_tool_menus_surfaces_presets_and_disable(editor, qtbot):
    """Add native controls and editable content without resetting unrelated UI."""
    window, vm = editor, editor.viewmodel
    vm.enable_plugin(HEALTH, trust=True)
    health = window.plugin_workspace.docks[0].widget()
    vm.enable_plugin(STUDIO, trust=True)
    assert not vm.plugin_error
    assert window.plugin_workspace.docks[0].widget() is health
    toolbar = window.plugin_workspace.host.toolbars["Studio tools"]
    tool = window.command_actions[STUDIO + ".draw_chain"]
    assert tool in toolbar.actions()
    assert any(
        action.menu() and action.text() == "Studio tools"
        for action in window.menus["Rig"].actions()
    )
    tool.trigger()
    QTest.mouseClick(window.viewport, Qt.MouseButton.LeftButton, pos=QPoint(250, 220))
    assert len(vm.documents.project.scenes[0].skeletons[0].bones) == 4
    assert len(vm.documents.history.undo_stack) == 1
    label = window.plugin_workspace._widget_mounts[STUDIO + ".selection"][1]
    assert label.text() == "Selected: 3"
    menu = QMenu(window)
    window.plugin_workspace.populate_context(menu, "scene", item_id="clicked")
    assert any(action.text() == "Add three-bone chain" for action in menu.actions())
    vm.plugins.discover()
    vm.plugins.restore()
    assert window.plugin_workspace.docks[0].widget() is health
    assert window.plugin_workspace._widget_mounts[STUDIO + ".selection"][1] is label
    window.show_character_wizard()
    wizard = window.character_wizard
    name = next(n for n in wizard.extension_presets if n.startswith("Studio explorer"))
    item = next(
        wizard.presets.item(i)
        for i in range(wizard.presets.count())
        if wizard.presets.item(i).data(Qt.ItemDataRole.UserRole) == name
    )
    wizard.choose_design(item)
    assert wizard.recipe.name == "Studio explorer"
    assert item.isSelected()
    qtbot.waitUntil(lambda: not vm.content.busy, timeout=10000)
    assert any(entry.item.category == "Studio templates" for entry in vm.content.entries)
    assert window.content_shelf.collection.findText("Studio templates") >= 0
    vm.plugins.disable(STUDIO)
    assert STUDIO + ".draw_chain" not in window.command_actions
    assert "Studio tools" not in window.plugin_workspace.host.toolbars
    assert not wizard.extension_presets
    assert window.plugin_workspace.docks[0].widget() is health
    assert len(vm.documents.project.scenes[0].skeletons[0].bones) == 4


def test_live_action_widget_and_context_hooks_are_owned(editor):
    """Runtime registration/removal and editor context reach callbacks through the public host."""
    window, vm = editor, editor.viewmodel
    vm.enable_plugin(STUDIO, trust=True)
    context = vm.plugins.contexts[STUDIO]
    observed = []
    context.hook(
        STUDIO + ".selected",
        "selection.changed",
        lambda request: observed.append(dict(request.state)),
    )
    context.action(
        STUDIO + ".extra",
        "Extra editor action",
        lambda request: observed.append(dict(request.arguments)),
        placements=("surface:timeline.actions", "context:assets"),
        when=("project",),
    )
    action = window.command_actions[STUDIO + ".extra"]
    assert action.isEnabled()
    menu = QMenu(window)
    window.plugin_workspace.populate_context(menu, "assets", asset_id="selected-source")
    menu.actions()[0].trigger()
    assert observed[-1] == {"asset_id": "selected-source"}
    vm.run_plugin(STUDIO + ".chain", {"count": 2})
    assert any(record.get("bone_ids") for record in observed)
    context.remove(STUDIO + ".extra")
    assert STUDIO + ".extra" not in window.command_actions
    assert not window.plugin_workspace.host.mounts.get(STUDIO + ".extra")


def test_zip_install_ui_keeps_code_disabled(editor, qtbot, tmp_path, monkeypatch):
    """The primary install button loads a package asynchronously without granting trust."""
    package = generate_plugin(tmp_path / "source", "org.install.ui")
    archive = tmp_path / "example.zip"
    with zipfile.ZipFile(archive, "w") as output:
        for path in package.iterdir():
            output.write(path, package.name + "/" + path.name)
    monkeypatch.setattr(
        "rigora.presentation.widgets.plugin_manager.choose_open_file",
        lambda *args: (str(archive), ""),
    )
    editor.show_plugins()
    dialog = editor.plugin_dialog
    dialog.install_button.click()
    assert dialog.jobs
    qtbot.waitUntil(lambda: not dialog.jobs, timeout=10000)
    assert "org.install.ui" in editor.viewmodel.plugins.states
    assert "org.install.ui" not in editor.viewmodel.plugins.contexts
    assert "Installed" in dialog.output.toPlainText()


def test_closing_hook_changes_are_included_in_unsaved_decision(editor):
    """A modifying closing hook runs before the existing discard guard and creates one undo step."""
    vm = editor.viewmodel
    vm.enable_plugin(STUDIO, trust=True)
    context = vm.plugins.contexts[STUDIO]
    context.hook(
        STUDIO + ".closing",
        "app.closing",
        lambda request: request.service("rig").create_bone((20, 20), (100, 20)),
    )
    observed = []
    editor.confirm_discard = lambda: observed.append(len(vm.documents.history.undo_stack)) or False
    editor.close()
    assert not editor._closed and observed[-1] == 1
    context.remove(STUDIO + ".closing")
    editor.confirm_discard = lambda: True
