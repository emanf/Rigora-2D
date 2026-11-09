"""Welcome is a disposable startup window rather than a document tab."""

import pytest
from PySide6.QtCore import QPointF, Qt, QTimer
from test_workspace import workspace as workspace

pytestmark = pytest.mark.gui


def test_startup_window_closes_when_a_project_starts(workspace, qtbot):
    from shiboken6 import isValid

    qtbot.waitUntil(lambda: workspace.welcome_window is not None)
    start = workspace.welcome_window
    assert start.isWindow() and start.isVisible()
    assert workspace.project_tabs.count() == 0
    assert workspace.stack.currentWidget() is not start
    workspace.viewmodel.new_project("My project")
    qtbot.waitUntil(lambda: workspace.welcome_window is None)
    qtbot.waitUntil(lambda: not isValid(start))
    assert workspace.project_tabs.count() == 1
    assert workspace.project_tabs.tabText(0) == "My project *"
    assert not workspace.viewmodel.welcome_open


def test_reopening_start_does_not_replace_or_reset_the_active_project(workspace, qtbot):
    workspace.viewmodel.new_project("In progress")
    qtbot.wait(10)
    doc = workspace.viewmodel.documents
    workspace.viewport.zoom = 0.6
    workspace.viewport.offset = QPointF(19, 25)
    workspace.command_actions["welcome"].trigger()
    qtbot.waitUntil(lambda: workspace.welcome_window is not None)
    start = workspace.welcome_window
    assert start.isVisible() and workspace.viewmodel.documents is doc
    assert workspace.project_tabs.count() == 1
    assert workspace.command_actions["save"].isEnabled()
    start.continue_button.click()
    qtbot.waitUntil(lambda: workspace.welcome_window is None)
    assert workspace.viewmodel.documents is doc
    assert workspace.viewport.zoom == 0.6 and workspace.viewport.offset == QPointF(19, 25)


def test_recent_project_starts_from_the_window(workspace, qtbot, tmp_path):
    path = tmp_path / "Recent project.rigora"
    workspace.viewmodel.new_project("Recent project")
    workspace.viewmodel.save_project(path)
    workspace.viewmodel.close_project(0)
    workspace.viewmodel.show_welcome()
    qtbot.waitUntil(lambda: workspace.welcome_window is not None)
    start = workspace.welcome_window
    item = start.recent.item(0)
    assert item.data(Qt.ItemDataRole.UserRole) == str(path)
    start.recent.itemActivated.emit(item)
    qtbot.waitUntil(lambda: workspace.welcome_window is None, timeout=10000)
    assert workspace.viewmodel.documents.path == path


def test_new_project_button_and_cancel_keep_expected_startup_lifecycle(workspace, qtbot):
    from rigora.presentation.widgets.dialogs import ProjectSettingsDialog

    qtbot.waitUntil(lambda: workspace.welcome_window is not None)
    start = workspace.welcome_window
    for accept in (False, True):

        def answer(create=accept):
            dialog = next(d for d in workspace.findChildren(ProjectSettingsDialog) if d.isVisible())
            dialog.project_name.setText("From startup")
            dialog.accept() if create else dialog.reject()

        QTimer.singleShot(10, answer)
        start.new_button.click()
        if not accept:
            assert workspace.welcome_window is start and start.isVisible()
            assert workspace.viewmodel.documents.project is None
    qtbot.waitUntil(lambda: workspace.welcome_window is None)
    assert workspace.viewmodel.documents.project.name == "From startup"


def test_failed_open_keeps_startup_window_and_recent_search_is_visual(
    workspace, qtbot, tmp_path, monkeypatch
):
    qtbot.waitUntil(lambda: workspace.welcome_window is not None)
    start = workspace.welcome_window
    errors = []
    monkeypatch.setattr(
        "rigora.presentation.views.main_window.show_warning", lambda *args: errors.append(args)
    )
    monkeypatch.setattr(
        "rigora.presentation.views.main_window.choose_open_file",
        lambda *args: (str(tmp_path / "missing.rigora"), ""),
    )
    start.open_button.click()
    assert start.progress.isVisible() and not start.open_button.isEnabled()
    qtbot.waitUntil(lambda: bool(errors), timeout=10000)
    assert workspace.welcome_window is start and start.isVisible()
    assert start.open_button.isEnabled() and start.progress.isHidden()
    for name in ("Character study", "Evening scene", "Walk cycle"):
        workspace.viewmodel.preferences.add_recent(tmp_path / (name + ".rigora"))
    start.refresh_recent()
    start.search.setText("walk")
    assert sum(not start.recent.item(i).isHidden() for i in range(3)) == 1
    start.search.clear()
    for theme in ("dark", "light"):
        workspace.viewmodel.set_theme(theme)
        qtbot.wait(10)
        assert start.grab().save(f"build/start-window-{theme}.png")
