"""Readable default docks, trailing menu marks and layout persistence across real launches."""

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QFont, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolButton
from test_character_objects_gui import editor as editor
from test_object_scene_actions_gui import readable_offscreen_fonts as readable_offscreen_fonts
from test_timeline_title_gui import add_animal
from test_workspace import workspace as workspace

from rigora.app.application import ApplicationInfo
from rigora.infrastructure.preferences import PreferencesStore
from rigora.presentation.viewmodels.main_window import MainWindowViewModel
from rigora.presentation.views.main_window import MainWindow

pytestmark = pytest.mark.gui


@pytest.mark.parametrize("project", (False, True))
def test_dock_separator_can_shrink_then_expand_assets(workspace, qtbot, project):
    """Divider drags retain their size and remain usable after reaching the panel minimum."""
    editor = workspace
    editor.setFont(QFont("Segoe UI", 14))
    if project:
        editor.viewmodel.new_project()
    editor.resize(1200, 900)
    qtbot.wait(40)
    assets = editor.docks["assets"]
    original = editor.viewmodel.documents.project
    for delta in (-140, 300, -180):
        width = assets.width()
        handle = assets.resize_grip
        start = handle.rect().center()
        end = start + QPoint(delta, 0)
        for kind, point, buttons in (
            (QMouseEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton),
            (QMouseEvent.Type.MouseMove, end, Qt.MouseButton.LeftButton),
            (QMouseEvent.Type.MouseButtonRelease, end, Qt.MouseButton.NoButton),
        ):
            QApplication.sendEvent(
                handle,
                QMouseEvent(
                    kind,
                    QPointF(point),
                    QPointF(handle.mapToGlobal(point)),
                    Qt.MouseButton.NoButton
                    if kind == QMouseEvent.Type.MouseMove
                    else Qt.MouseButton.LeftButton,
                    buttons,
                    Qt.KeyboardModifier.NoModifier,
                ),
            )
            qtbot.wait(10)
        qtbot.wait(350)
        assert assets.width() == pytest.approx(max(assets.minimumWidth(), width - delta), abs=2)
    assert editor.viewmodel.documents.project is original
    if project:
        scrollbar = editor.viewport_header.horizontalScrollBar()
        assert scrollbar.maximum() > 0
        scrollbar.setValue(scrollbar.maximum())
        fit = next(
            button
            for button in editor.viewport_header.findChildren(QToolButton)
            if button.defaultAction() is editor.command_actions["fit"]
        )
        assert fit.visibleRegion().boundingRect().width() == fit.width()


def reopen(editor, qtbot, project):
    """Close normally, create a fresh shell/store and open the same saved project."""
    preferences = editor.viewmodel.preferences.path
    editor.viewmodel.save_project(project)
    editor.close()
    model = MainWindowViewModel(ApplicationInfo(), preferences=PreferencesStore(preferences))
    other = MainWindow(model)
    # Offscreen restoreGeometry clamps to its smaller virtual screen. Keep this
    # dock-layout test on the same logical display size as the original window.
    other.resize(editor.size())
    other.confirm_discard = lambda: True
    qtbot.addWidget(other)
    other.show()
    model.open_project(project)
    qtbot.wait(50)
    return other


def test_default_panels_are_visible_readable_and_timeline_is_balanced(editor, qtbot):
    """Scene and Assets flank the preview while the tool strip overlays its left edge."""
    qtbot.wait(50)
    scene, assets = editor.docks["hierarchy"], editor.docks["assets"]
    assert all(
        not editor.docks[key].isHidden() and not editor.docks[key].visibleRegion().isEmpty()
        for key in ("tools", "hierarchy", "assets", "timeline")
    )
    assert scene.x() < editor.viewport.mapTo(editor, QPoint()).x() < assets.x()
    assert scene.y() == assets.y()
    assert scene.width() >= 280 and assets.width() >= 280
    assert 250 <= editor.docks["timeline"].height() <= 330
    assert editor.viewport.width() >= 650
    button = editor.import_artwork_button
    assert QRect(assets.mapTo(editor, QPoint()), assets.size()).contains(
        QRect(button.mapTo(editor, QPoint()), button.size())
    )
    assert button.isHidden()
    empty_action = editor.project_assets.empty_action
    assert empty_action.visibleRegion().boundingRect() == empty_action.rect()
    output = Path("build/workspace-layout-review")
    output.mkdir(parents=True, exist_ok=True)
    editor.grab().save(str(output / "default.png"))


@pytest.mark.parametrize("theme", ("dark", "light"))
def test_view_menu_marks_are_plain_and_on_right_with_working_toggles(editor, qtbot, theme):
    """Native View clicks toggle Assets and change only its plain trailing mark."""
    editor.apply_theme(theme)
    dock = editor.docks["assets"]
    menu, action = editor.menus["View"], dock.toggleViewAction()
    menu.popup(editor.menu_bar.mapToGlobal(QPoint(0, editor.menu_bar.height())))
    qtbot.waitUntil(menu.isVisible)
    menu.setActiveAction(None)
    assert action.isChecked() and not action.icon().isNull()
    row = menu.actionGeometry(action)
    checked = menu.grab().toImage()
    action.trigger()
    qtbot.waitUntil(dock.isHidden)
    menu.setActiveAction(None)
    unchecked = menu.grab().toImage()
    changed = [
        (x, y)
        for y in range(row.top(), row.bottom() + 1)
        for x in range(row.left(), row.right() + 1)
        if checked.pixel(x, y) != unchecked.pixel(x, y)
    ]
    assert changed and min(x for x, _ in changed) > row.right() - 32
    assert max(x for x, _ in changed) < row.right() - 4
    output = Path("build/workspace-layout-review")
    output.mkdir(parents=True, exist_ok=True)
    checked.save(str(output / f"view-{theme}.png"))
    QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=row.center())
    qtbot.waitUntil(lambda: not dock.isHidden())
    assert action.isChecked() and not menu.isVisible()


def test_docked_floating_sizes_and_internal_divider_survive_relaunch(editor, qtbot, tmp_path):
    """A fresh preferences instance restores floating geometry, dock height and panel data views."""
    dock = editor.docks["assets"]
    dock.setFloating(True)
    dock.resize(420, 390)
    dock.move(90, 110)
    editor.resizeDocks([editor.docks["timeline"]], [360], Qt.Orientation.Vertical)
    editor.timeline.splitter.setSizes([390, 900])
    editor.library_tabs.setCurrentIndex(1)
    editor.timeline.pages.setCurrentIndex(1)
    qtbot.wait(40)
    geometry = dock.geometry()
    height = editor.docks["timeline"].height()
    sizes = editor.timeline.splitter.sizes()
    other = reopen(editor, qtbot, tmp_path / "layout.rigora")
    restored = other.docks["assets"]
    assert restored.isFloating() and not restored.isHidden()
    assert abs(restored.x() - geometry.x()) <= 8 and abs(restored.y() - geometry.y()) <= 8
    assert abs(restored.width() - geometry.width()) <= 8
    assert abs(restored.height() - geometry.height()) <= 8
    assert abs(other.docks["timeline"].height() - height) <= 8
    assert other.library_tabs.currentIndex() == other.timeline.pages.currentIndex() == 1
    # Measure the displayed divider, not QSplitter's stale hidden-page geometry.
    other.timeline.pages.setCurrentIndex(0)
    qtbot.wait(20)
    ratio = other.timeline.splitter.sizes()[0] / sum(other.timeline.splitter.sizes())
    assert ratio == pytest.approx(sizes[0] / sum(sizes), abs=0.02)
    other.close()


def test_closing_object_editor_preserves_scene_and_its_own_sizes(editor, qtbot, tmp_path):
    """Object isolation's hidden docks and compact timeline must not replace the Scene layout."""
    root = add_animal(editor)
    editor.resizeDocks([editor.docks["timeline"]], [340], Qt.Orientation.Vertical)
    qtbot.wait(20)
    scene_height = editor.docks["timeline"].height()
    editor.object_edit.enter(root)
    qtbot.wait(30)
    editor.studio_splitter.setSizes([editor.studio_splitter.width() - 420, 420])
    editor.resizeDocks([editor.docks["timeline"]], [300], Qt.Orientation.Vertical)
    qtbot.wait(20)
    width = editor.studio_splitter.sizes()[1]
    other = reopen(editor, qtbot, tmp_path / "object-layout.rigora")
    assert all(
        not other.docks[key].isHidden() for key in ("tools", "hierarchy", "assets", "timeline")
    )
    assert abs(other.docks["timeline"].height() - scene_height) <= 8
    other.object_edit.enter(root)
    qtbot.wait(50)
    assert other.studio_splitter.sizes()[1] == pytest.approx(width, abs=8)
    assert other.docks["timeline"].height() == pytest.approx(300, abs=8)
    other.close()


def test_reset_workspace_layout_restores_defaults_without_editing_project(editor, qtbot):
    """The View command resets floating placement, visibility and dividers without data edits."""
    editor.docks["assets"].setFloating(True)
    editor.docks["hierarchy"].hide()
    editor.resizeDocks([editor.docks["timeline"]], [460], Qt.Orientation.Vertical)
    editor.timeline.splitter.setSizes([500, 600])
    original = editor.viewmodel.documents.project
    before = len(editor.viewmodel.documents.history.undo_stack)
    action = editor.command_actions["restore"]
    assert action.text() == "Reset Workspace Layout" and action in editor.menus["View"].actions()
    action.trigger()
    qtbot.wait(40)
    assert not editor.docks["assets"].isFloating()
    assert all(
        not editor.docks[key].isHidden() for key in ("tools", "hierarchy", "assets", "timeline")
    )
    assert 250 <= editor.docks["timeline"].height() <= 330
    assert editor.docks["hierarchy"].x() < editor.docks["assets"].x()
    assert editor.docks["hierarchy"].y() == editor.docks["assets"].y()
    assert editor.viewmodel.documents.project is original
    assert len(editor.viewmodel.documents.history.undo_stack) == before
