import json
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QFocusEvent, QFont, QImage, QRawFont
from PySide6.QtWidgets import QDialog, QMessageBox

from rigora.app.application import ApplicationInfo
from rigora.domain.project import SceneSettings
from rigora.infrastructure.preferences import PreferencesStore
from rigora.presentation.icons import IconProvider
from rigora.presentation.themes import PALETTES, ThemeManager
from rigora.presentation.viewmodels.main_window import MainWindowViewModel
from rigora.presentation.views.main_window import MainWindow
from rigora.presentation.widgets.dialogs import CommandPalette, ProjectSettingsDialog
from rigora.presentation.widgets.viewport import Viewport
from rigora.resources import asset_path

pytestmark = pytest.mark.gui


@pytest.fixture
def workspace(qtbot, tmp_path):
    model = MainWindowViewModel(
        ApplicationInfo(), preferences=PreferencesStore(tmp_path / "workspace.json")
    )
    window = MainWindow(model)
    qtbot.addWidget(window, before_close_func=lambda w: setattr(w, "confirm_discard", lambda: True))
    window.show()
    yield window
    window.confirm_discard = lambda: True
    window.close()


def test_welcome_and_real_document_state(workspace, tmp_path):
    assert workspace.stack.currentIndex() == 0
    assert not workspace.command_actions["save"].isEnabled()
    workspace.viewmodel.new_project("Character")
    assert workspace.stack.currentIndex() == 1
    assert workspace.viewport.has_project
    assert workspace.project_tabs.tabText(0).endswith(" *")
    assert workspace.titlebar.caption.isHidden()
    workspace.viewmodel.save_project(tmp_path / "character.rigora")
    assert not workspace.project_tabs.tabText(0).endswith(" *")
    assert workspace.command_actions["save"].isEnabled()
    assert workspace.command_actions["play"].isEnabled()
    assert not workspace.command_actions["play"].property("futureFeature")


def test_welcome_keeps_scene_tools_and_preview_order(workspace, qtbot):
    """Welcome keeps scene panels visible; Tools appear only with the preview workspace."""
    scene, tools = workspace.docks["hierarchy"], workspace.docks["tools"]
    qtbot.wait(30)
    assert workspace.stack.currentIndex() == 0
    assert all(
        not workspace.docks[key].visibleRegion().isEmpty()
        for key in ("hierarchy", "assets", "timeline")
    )
    assert tools.visibleRegion().isEmpty() and not tools.isHidden()
    assert tools not in workspace.tabifiedDockWidgets(scene)
    workspace.viewmodel.new_project()
    qtbot.wait(20)
    tool_position = tools.mapTo(workspace, QPoint())
    assert scene.x() + scene.width() <= tool_position.x()
    assert tool_position.x() + tools.width() <= workspace.viewport.mapTo(workspace, QPoint()).x()
    assert abs(tools.height() - workspace.viewport.height()) <= 2
    workspace.docks["assets"].hide()
    workspace.viewmodel.show_welcome()
    workspace.viewmodel.changed.emit()
    assert not scene.isHidden() and not tools.isHidden()
    assert workspace.docks["assets"].isHidden()
    workspace.viewmodel.activate_project(0)
    assert workspace.docks["assets"].isHidden()


def test_welcome_panel_changes_persist_and_reset_without_a_project(workspace, qtbot, tmp_path):
    """Welcome edits are real workspace preferences, and Reset works before opening a project."""
    workspace.docks["tools"].hide()
    workspace.docks["assets"].setFloating(True)
    workspace.docks["assets"].resize(410, 380)
    workspace.close()
    other = MainWindow(
        MainWindowViewModel(
            ApplicationInfo(), preferences=PreferencesStore(tmp_path / "workspace.json")
        )
    )
    qtbot.addWidget(other)
    other.show()
    qtbot.wait(30)
    assert other.stack.currentIndex() == 0
    assert other.docks["tools"].isHidden()
    assert other.docks["assets"].isFloating()
    assert other.docks["assets"].width() == pytest.approx(410, abs=8)
    other.restore_layout()
    qtbot.wait(30)
    assert all(
        not other.docks[key].isHidden() and not other.docks[key].isFloating()
        for key in ("hierarchy", "tools", "assets", "timeline")
    )
    other.close()


def test_legacy_hidden_scene_layout_recovers_once(qtbot, tmp_path):
    """Recover the old hidden startup panels without overriding subsequent View choices."""
    store = PreferencesStore(tmp_path / "legacy.json")
    saved = Path(__file__).parent / "fixtures/welcome-hidden-scene-layout.json"
    store.data.update(json.loads(saved.read_text(encoding="utf-8")))
    other = MainWindow(MainWindowViewModel(ApplicationInfo(), preferences=store))
    qtbot.addWidget(other)
    other.show()
    qtbot.wait(30)
    scene, tools = other.docks["hierarchy"], other.docks["tools"]
    assert not scene.visibleRegion().isEmpty()
    assert tools.visibleRegion().isEmpty() and not tools.isHidden()
    other.viewmodel.new_project()
    qtbot.wait(20)
    tool_position = tools.mapTo(other, QPoint())
    assert scene.x() + scene.width() <= tool_position.x()
    assert tool_position.x() + tools.width() <= other.viewport.mapTo(other, QPoint()).x()
    other.confirm_discard = lambda: True
    assert store.data["workspace_panels_version"] == 1
    scene.hide()
    other._save_workspace()
    other._restore_workspace()
    assert scene.isHidden()
    other.close()


def test_project_tabs_preserve_history_view_and_header_integration(workspace, qtbot, tmp_path):
    model = workspace.viewmodel
    model.new_project("First")
    first = model.documents
    qtbot.wait(1)
    workspace.viewport.zoom = 0.75
    workspace.viewport.offset = QPointF(19, 23)
    model.new_project("Second")
    second = model.documents
    model.edit_settings("Second edited", "Scene", SceneSettings(width=800))
    assert workspace.project_tabs.count() == 2
    assert workspace.project_tabs.tabText(1) == "Second edited *"
    workspace.project_tabs.setCurrentIndex(0)
    assert model.documents is first and not first.can_undo
    assert workspace.viewport.zoom == 0.75
    assert workspace.viewport.offset == QPointF(19, 23)
    assert workspace.menu_bar.parent() is workspace.titlebar
    assert workspace.titlebar.logo.iconSize().width() == 14
    assert "border: none" in workspace.titlebar.logo.styleSheet()
    workspace.project_tabs.moveTab(0, 1)
    assert model.documents is first
    assert model.workspace.documents == (second, first)
    workspace.cycle_project(1)
    assert not model.welcome_selected
    assert model.documents is second
    model.undo()
    assert model.documents.project.name == "Second"
    model.save_project(tmp_path / "second.rigora")
    with pytest.raises(Exception, match="another project tab"):
        model.activate_project(1)
        model.save_project(tmp_path / "second.rigora")


def test_cancel_tab_and_window_close_preserves_all_projects(workspace, monkeypatch):
    model = workspace.viewmodel
    model.new_project("First")
    first = model.documents
    model.new_project("Second")
    second = model.documents
    monkeypatch.setattr(
        "rigora.presentation.views.main_window.ask_question",
        lambda *a, **k: QMessageBox.StandardButton.Cancel,
    )
    workspace.close_tab_by_id(first.session_id)
    assert model.documents is second
    assert model.workspace.documents == (first, second)
    answers = iter((QMessageBox.StandardButton.Discard, QMessageBox.StandardButton.Cancel))
    monkeypatch.setattr(
        "rigora.presentation.views.main_window.ask_question", lambda *a, **k: next(answers)
    )
    assert not workspace.close()
    assert model.workspace.documents == (first, second)
    assert model.documents is second


def test_save_all_and_closing_saved_tab_does_not_prompt_other_tab(workspace, tmp_path, monkeypatch):
    model = workspace.viewmodel
    model.new_project("First")
    first = model.documents
    model.new_project("Second")
    second = model.documents
    destinations = iter((tmp_path / "first.rigora", tmp_path / "second.rigora"))
    monkeypatch.setattr(
        "rigora.presentation.views.main_window.choose_save_file",
        lambda *a, **k: (str(next(destinations)), ""),
    )
    workspace.save_all_projects()
    assert not first.dirty and not second.dirty
    assert model.documents is second
    model.edit_settings("Dirty second", "Scene", SceneSettings())
    monkeypatch.setattr(
        "rigora.presentation.views.main_window.ask_question",
        lambda *a, **k: pytest.fail("Unexpected prompt"),
    )
    workspace.close_tab_by_id(first.session_id)
    assert model.workspace.documents == (second,)


def test_registered_assets_are_visible_and_undoable(workspace, tmp_path):
    workspace.viewmodel.new_project("Sources")
    source = tmp_path / "art.svg"
    source.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    workspace.viewmodel.register_asset(source)
    assert workspace.project_assets.item(0).text() == "art.svg"
    previous_icon = workspace.project_assets.item(0).icon().cacheKey()
    workspace.viewmodel.set_theme("light")
    assert workspace.project_assets.item(0).icon().cacheKey() != previous_icon
    assert workspace.project_assets.item(0).text() == "art.svg"
    workspace.viewmodel.undo()
    assert workspace.project_assets.count() == 0
    assert not workspace.project_assets.empty_state.isHidden()
    assert workspace.project_assets.empty_action.text() == "Import assets…"
    assert workspace.import_artwork_button.isHidden()


def test_viewport_shortcuts_do_not_capture_text_input(workspace, qtbot):
    workspace.viewmodel.new_project()
    workspace.activateWindow()
    qtbot.waitUntil(workspace.isActiveWindow)
    workspace.filter.setFocus()
    qtbot.keyClicks(workspace.filter, "rig1")
    assert workspace.filter.text() == "rig1"
    assert workspace.viewport.grid_visible
    workspace.viewport.setFocus()
    qtbot.keyClick(workspace.viewport, Qt.Key.Key_G)
    assert not workspace.viewport.grid_visible


def test_caption_buttons_and_close_guard(workspace, monkeypatch):
    assert workspace.windowFlags() & Qt.WindowType.FramelessWindowHint
    workspace.titlebar.maximize_button.click()
    assert workspace.isMaximized()
    workspace.titlebar.maximize_button.click()
    assert not workspace.isMaximized()
    workspace.titlebar.minimize_button.click()
    assert workspace.isMinimized()
    workspace.showNormal()
    workspace.viewmodel.new_project()
    monkeypatch.setattr(
        "rigora.presentation.views.main_window.ask_question",
        lambda *a, **k: QMessageBox.StandardButton.Cancel,
    )
    assert not workspace.close()
    assert workspace.isVisible()
    monkeypatch.setattr(
        "rigora.presentation.views.main_window.ask_question",
        lambda *a, **k: QMessageBox.StandardButton.Discard,
    )
    assert workspace.close()


def test_canceled_save_prevents_discard(workspace, monkeypatch):
    workspace.viewmodel.new_project()
    monkeypatch.setattr(
        "rigora.presentation.views.main_window.ask_question",
        lambda *a, **k: QMessageBox.StandardButton.Save,
    )
    monkeypatch.setattr(
        "rigora.presentation.views.main_window.choose_save_file", lambda *a, **k: ("", "")
    )
    assert not workspace.confirm_discard()
    assert workspace.viewmodel.documents.dirty


def test_dark_palette_and_persisted_light_viewport(workspace, tmp_path, qtbot):
    assert all(color[1:3] == color[3:5] == color[5:7] for color in PALETTES["dark"].values())
    workspace.apply_theme("light")
    assert workspace.viewport.theme == "light"
    store = PreferencesStore(tmp_path / "workspace.json")
    other = MainWindow(MainWindowViewModel(ApplicationInfo(), preferences=store))
    qtbot.addWidget(other)
    assert other.viewport.theme == "light"
    assert other.command_actions["theme"].isChecked()
    other.close()


def test_layout_hide_restore_and_persistence(workspace, qtbot, tmp_path):
    workspace.viewmodel.new_project()
    workspace.docks["assets"].hide()
    workspace.viewmodel.save_project(tmp_path / "layout.rigora")
    workspace.close()
    other = MainWindow(
        MainWindowViewModel(
            ApplicationInfo(), preferences=PreferencesStore(tmp_path / "workspace.json")
        )
    )
    qtbot.addWidget(other)
    other.viewmodel.open_project(tmp_path / "layout.rigora")
    other.show()
    assert other.docks["assets"].isHidden()
    other.restore_layout()
    assert not other.docks["assets"].isHidden()
    other.close()


def test_closing_welcome_does_not_persist_all_panels_hidden(workspace, qtbot, tmp_path):
    workspace.close()
    other = MainWindow(
        MainWindowViewModel(
            ApplicationInfo(), preferences=PreferencesStore(tmp_path / "workspace.json")
        )
    )
    qtbot.addWidget(other)
    other.show()
    assert all(
        not other.docks[key].isHidden() for key in ("tools", "hierarchy", "assets", "timeline")
    )
    other.viewmodel.new_project()
    assert all(
        not other.docks[key].isHidden() for key in ("tools", "hierarchy", "assets", "timeline")
    )
    assert other.docks["inspector"].isHidden()
    other.confirm_discard = lambda: True
    other.close()


def test_viewport_cursor_zoom_fit_and_focus_cleanup(qtbot):
    view = Viewport()
    qtbot.addWidget(view)
    view.resize(220, 200)
    view.set_scene(SceneSettings(width=16384, height=16384), reset=True)
    assert view.settings_size().width() <= view.width() - 79
    anchor = QPointF(80, 65)
    before = view.scene_point(anchor)
    view.zoom_at(2, anchor)
    after = view.scene_point(anchor)
    assert abs(before.x() - after.x()) < 1e-8
    assert abs(before.y() - after.y()) < 1e-8
    view._space = True
    view._drag = QPointF(2, 2)
    view.focusOutEvent(QFocusEvent(QFocusEvent.Type.FocusOut))
    assert not view._space and view._drag is None


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_viewport_transparency_fills_workspace_and_camera_is_only_border(qapp, qtbot, theme):
    """Camera bounds must not change the background or hide the surrounding workspace."""
    view = Viewport()
    manager = ThemeManager(qapp, IconProvider())
    manager.apply(theme)
    qtbot.addWidget(view)
    view.resize(400, 300)
    view.set_scene(SceneSettings(width=200, height=100))
    view.zoom, view.offset = 1, QPointF(100, 100)
    view.theme, view.grid_visible = theme, False
    image = view.grab().toImage()
    colors = PALETTES[theme]
    assert image.pixelColor(6, 6).name() == colors["checker_a"]
    assert image.pixelColor(18, 6).name() == colors["checker_b"]
    assert image.pixelColor(102, 102).name() == colors["checker_a"]
    assert image.pixelColor(114, 102).name() == colors["checker_b"]
    assert image.pixelColor(100, 140).name() == colors["preview_ink"]
    view.checker_visible = False
    image = view.grab().toImage()
    assert image.pixelColor(6, 6).name() == colors["canvas"]
    assert image.pixelColor(114, 102).name() == colors["canvas"]
    assert image.pixelColor(100, 140).name() == colors["preview_ink"]
    manager.apply("dark")


def test_command_search_distinguishes_context_and_available_paths(workspace, qtbot):
    palette = CommandPalette(workspace, list(workspace.command_actions.values()), workspace.icons)
    qtbot.addWidget(palette)
    palette.filter("save as")
    assert palette.results.count() == 1
    assert "context" in palette.results.item(0).text()
    palette.filter("play / pause")
    assert "context" in palette.results.item(0).text()
    palette.filter("draw bone")
    assert "context" in palette.results.item(0).text()
    palette.filter("edit mesh")
    assert "context" in palette.results.item(0).text()
    palette.filter("motion paths")
    assert "Bezier artwork & motion paths" in palette.results.item(0).text()
    assert not workspace.command_actions["path"].property("futureFeature")
    palette.filter("quick start")
    assert palette.results.count() == 1


def test_project_settings_validate_before_closing(workspace, qtbot):
    dialog = ProjectSettingsDialog(workspace)
    qtbot.addWidget(dialog)
    dialog.project_name.setText(" ")
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.validation.text()
    dialog.project_name.setText("Valid project")
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_bundled_material_glyphs_and_transparent_brand(qapp):
    icons = IconProvider()
    raw = QRawFont.fromFont(QFont(icons.family))
    assert all(raw.supportsCharacter(int(code, 16)) for code in icons.codepoints.values())
    for name in ("close", "minimize", "crop_square", "filter_none", "save", "pan_tool"):
        assert not icons.icon(name).pixmap(24, 24).isNull()
    with pytest.raises(ValueError):
        icons.icon("this_icon_does_not_exist")
    image = QImage(str(asset_path("icons/app/rigora.png")))
    assert image.hasAlphaChannel() and image.pixelColor(0, 0).alpha() == 0
    assert image.width() >= 512


@pytest.mark.parametrize(
    "name", ["../secret", str(Path.cwd() / "secret"), "C:\\secret", "..\\secret", "C:secret"]
)
def test_resource_paths_cannot_escape(name):
    with pytest.raises(ValueError):
        asset_path(name)
