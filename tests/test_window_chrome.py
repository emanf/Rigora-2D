"""Welcome navigation and shared custom chrome preserve standard desktop workflows."""

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton, QScrollArea, QToolBar

from rigora.app.application import ApplicationInfo
from rigora.infrastructure.preferences import PreferencesStore
from rigora.presentation.themes import PALETTES
from rigora.presentation.viewmodels.main_window import MainWindowViewModel
from rigora.presentation.views.main_window import MainWindow
from rigora.presentation.widgets.about_dialog import AboutDialog
from rigora.presentation.widgets.dialogs import CommandPalette, ProjectSettingsDialog
from rigora.presentation.widgets.message_dialogs import MessageDialog, ask_question
from rigora.presentation.widgets.window_frame import CustomDialog, DockPanel

pytestmark = pytest.mark.gui


@pytest.fixture
def window(qtbot, tmp_path):
    """Provide an isolated shell whose cleanup never opens a save prompt."""
    model = MainWindowViewModel(
        ApplicationInfo(), preferences=PreferencesStore(tmp_path / "ui.json")
    )
    widget = MainWindow(model)
    qtbot.addWidget(widget, before_close_func=lambda w: setattr(w, "confirm_discard", lambda: True))
    widget.show()
    return widget


def test_branding_is_monochrome_and_updates_in_open_windows(window, qtbot):
    """Theme changes update existing branding, preserving transparent joints and margins."""
    qtbot.waitUntil(lambda: window.welcome_window is not None)
    welcome = window.welcome_window
    about = AboutDialog(window, window.viewmodel.info)
    qtbot.addWidget(about)
    about.show()
    dialog = CustomDialog(window, "Branding check")
    qtbot.addWidget(dialog)
    dialog.show()
    for theme, ink, tile in (("light", 0, 255), ("dark", 255, 0), ("light", 0, 255)):
        window.apply_theme(theme)
        QApplication.processEvents()
        images = [
            window.titlebar.logo.icon().pixmap(64, 64).toImage(),
            welcome.logo.pixmap().toImage(),
            about.logo.pixmap().toImage(),
        ]
        for image in images:
            assert not image.isNull()
            assert image.pixelColor(0, image.height() // 2).alpha() == 0
            colors = {
                image.pixelColor(x, y).getRgb()[:3]
                for y in range(image.height())
                for x in range(image.width())
                if image.pixelColor(x, y).alpha() > 0
            }
            assert colors == {(ink, ink, ink)}
        for widget in (window, welcome, about, dialog):
            image = widget.windowIcon().pixmap(64, 64).toImage()
            assert image.pixelColor(8, 32).getRgb() == (tile, tile, tile, 255)
        assert QApplication.windowIcon().pixmap(64, 64).toImage() == image


def test_welcome_stays_open_without_losing_project_or_canvas(window, qtbot):
    assert window.project_tabs.count() == 0
    window.viewmodel.new_project("Character")
    document = window.viewmodel.documents
    qtbot.wait(1)
    window.viewport.zoom = 0.65
    window.viewport.offset = QPointF(24, 48)
    window.docks["assets"].hide()
    window.viewmodel.show_welcome()
    assert window.stack.currentIndex() == 1 and window.viewmodel.welcome_selected
    assert window.viewmodel.workspace.documents == (document,)
    assert window.command_actions["save"].isEnabled()
    assert window.command_actions["save_all"].isEnabled()
    window.viewmodel.close_welcome()
    assert window.viewmodel.documents is document and document.dirty
    assert window.viewport.zoom == 0.65 and window.viewport.offset == QPointF(24, 48)
    assert window.docks["assets"].isHidden()


def test_only_projects_are_tabs_and_last_close_leaves_empty_workspace(window):
    window.viewmodel.new_project("First")
    window.viewmodel.new_project("Second")
    selected = window.viewmodel.documents
    window.project_tabs.moveTab(0, 1)
    assert all(window.project_tabs.tabData(i) != "welcome" for i in range(2))
    assert window.viewmodel.documents is selected
    window.confirm_discard = lambda: True
    window.close_current_project()
    window.close_current_project()
    assert window.project_tabs.count() == 0
    assert window.stack.currentIndex() == 0 and window.welcome_window is None


def test_close_welcome_reopen_and_project_tabs_without_it(window, qtbot):
    """Closing Welcome preserves sessions and permits an empty workspace."""
    qtbot.waitUntil(lambda: window.welcome_window is not None)
    close_button = window.welcome_window.titlebar.close_button
    close_button.click()
    assert window.project_tabs.count() == 0 and window.stack.currentIndex() == 0
    window.cycle_project(1)
    window.viewmodel.new_project("First")
    first = window.viewmodel.documents
    qtbot.wait(1)
    assert all(
        not window.docks[key].isHidden() for key in ("hierarchy", "tools", "assets", "timeline")
    )
    assert window.docks["inspector"].isHidden()
    window.viewport.zoom = 0.75
    window.viewmodel.new_project("Second")
    second = window.viewmodel.documents
    window.project_tabs.moveTab(0, 1)
    assert window.viewmodel.workspace.documents == (second, first)
    window.command_actions["welcome"].trigger()
    assert window.project_tabs.count() == 2 and window.welcome_window is not None
    window.command_actions["close_project"].trigger()
    assert not window.viewmodel.welcome_open and window.viewmodel.documents is second
    window.project_tabs.setCurrentIndex(1)
    assert window.viewmodel.documents is first and window.viewport.zoom == 0.75
    window.confirm_discard = lambda: True
    window.close_current_project()
    window.close_current_project()
    assert window.project_tabs.count() == 0 and window.stack.currentIndex() == 0
    window.command_actions["welcome"].trigger()
    assert window.project_tabs.count() == 0 and window.welcome_window is not None


def test_save_all_and_close_cancel_restore_welcome(window, monkeypatch, tmp_path):
    window.viewmodel.new_project("First")
    window.viewmodel.new_project("Second")
    window.viewmodel.show_welcome()
    destinations = iter((tmp_path / "first.rigora", tmp_path / "second.rigora"))
    monkeypatch.setattr(
        "rigora.presentation.views.main_window.choose_save_file",
        lambda *a, **k: (str(next(destinations)), ""),
    )
    window.save_all_projects()
    assert window.viewmodel.welcome_selected
    assert all(not doc.dirty for doc in window.viewmodel.workspace.documents)
    window.viewmodel.activate_project(0)
    window.viewmodel.edit_settings(
        "Changed", "Scene", window.viewmodel.documents.project.scenes[0].settings
    )
    window.viewmodel.show_welcome()
    monkeypatch.setattr(
        "rigora.presentation.views.main_window.ask_question",
        lambda *a, **k: QMessageBox.StandardButton.Cancel,
    )
    assert not window.close()
    assert window.viewmodel.welcome_selected and window.stack.currentIndex() == 1
    assert len(window.viewmodel.workspace.documents) == 2


def test_shared_application_dialog_chrome(window, qtbot):
    """Application dialogs keep custom controls; file selection belongs to the OS."""
    dialogs = [
        ProjectSettingsDialog(window),
        CommandPalette(window, list(window.command_actions.values()), window.icons),
        MessageDialog(
            window,
            "Decision",
            "Save?",
            QMessageBox.Icon.Question,
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        ),
    ]
    for dialog in dialogs:
        qtbot.addWidget(dialog)
        dialog.show()
        assert isinstance(dialog, CustomDialog)
        assert dialog.windowFlags() & Qt.WindowType.FramelessWindowHint
        assert dialog.titlebar.caption.text() == dialog.windowTitle()
        dialog.titlebar.maximize_button.click()
        assert dialog.isMaximized()
        dialog.titlebar.maximize_button.click()
        assert not dialog.isMaximized()
        dialog.close()


def test_about_shows_creator_branding_and_anchored_close_button(window):
    """The real About action presents identity, contact links and a reachable footer."""

    def inspect_about():
        """Inspect the active modal and dismiss it even if a layout assertion fails."""
        dialog = QApplication.activeModalWidget()
        try:
            assert isinstance(dialog, CustomDialog)
            text = "\n".join(label.text() for label in dialog.findChildren(QLabel))
            assert "eManF" in text
            assert "emanf.cc0@gmail.com" in text
            assert "https://github.com/emanf/rigora-2d" in text
            assert "https://emanf.ir" in text
            assert window.viewmodel.info.version in text
            logo = dialog.findChild(QLabel, "AboutIcon")
            assert logo is not None and not logo.pixmap().isNull()
            close = dialog.findChild(QPushButton, "AboutClose")
            assert close is not None and close.isVisible()
            assert close.mapTo(dialog, close.rect().center()).y() > dialog.height() - 80
            close.click()
            assert not dialog.isVisible()
        finally:
            if dialog is not None:
                dialog.close()

    QTimer.singleShot(0, inspect_about)
    window.show_about()


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_about_footer_stays_reachable_when_details_scroll(window, qtbot, theme):
    """Small windows retain accessible links and a visible default Close button in either theme."""
    window.viewmodel.set_theme(theme)
    dialog = AboutDialog(window, window.viewmodel.info)
    qtbot.addWidget(dialog)
    dialog.resize(560, 420)
    dialog.show()
    scroll = dialog.findChild(QScrollArea)
    assert scroll.verticalScrollBar().maximum() > 0
    assert dialog.close_button.isVisible()
    assert (
        dialog.close_button.mapTo(dialog, dialog.close_button.rect().bottomRight()).y()
        < dialog.height()
    )
    links = dialog.findChildren(QLabel, "AboutLink")
    assert len(links) == 3
    assert all(
        link.focusPolicy() == Qt.FocusPolicy.StrongFocus and link.accessibleName() for link in links
    )
    qtbot.keyClick(dialog, Qt.Key.Key_Return)
    assert not dialog.isVisible()


def test_custom_message_decisions_and_caption_close_cancel(window):
    def choose_save():
        """Select the standard Save decision from the active custom modal dialog."""
        modal = window.window().findChildren(MessageDialog)[-1]
        modal.box.button(QMessageBox.StandardButton.Save).click()

    QTimer.singleShot(0, choose_save)
    assert (
        ask_question(
            window,
            "Save",
            "Save changes?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        == QMessageBox.StandardButton.Save
    )

    def dismiss():
        """Dismiss the caption without granting a destructive decision."""
        modal = window.window().findChildren(MessageDialog)[-1]
        modal.titlebar.close_button.click()

    QTimer.singleShot(0, dismiss)
    assert (
        ask_question(
            window,
            "Replace",
            "Replace file?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        == QMessageBox.StandardButton.Cancel
    )


def test_decision_dialog_focus_and_enter_start_on_cancel(window, qtbot):
    """Only the safe initial keyboard choice is emphasized; Tab can select another action."""
    dialog = MessageDialog(
        window,
        "Save changes?",
        "Unsaved work",
        QMessageBox.Icon.Question,
        QMessageBox.StandardButton.Save
        | QMessageBox.StandardButton.Discard
        | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Cancel,
    )
    qtbot.addWidget(dialog)
    dialog.show()
    cancel = dialog.box.button(QMessageBox.StandardButton.Cancel)
    assert dialog.focusWidget() is cancel
    assert dialog.box.defaultButton() is cancel
    assert sum(button.isDefault() for button in dialog.findChildren(QPushButton)) == 1, [
        (
            button.text(),
            button.isDefault(),
            button.autoDefault(),
            button.parentWidget().objectName(),
        )
        for button in dialog.findChildren(QPushButton)
    ]
    QTest.keyClick(cancel, Qt.Key.Key_Return)
    assert dialog.result() == int(QMessageBox.StandardButton.Cancel)
    dialog.show()
    save = dialog.box.button(QMessageBox.StandardButton.Save)
    save.setFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(save, Qt.Key.Key_Return)
    assert dialog.result() == int(QMessageBox.StandardButton.Save)
    settings = ProjectSettingsDialog(window)
    qtbot.addWidget(settings)
    settings.show()
    cancel = settings.buttons.button(settings.buttons.StandardButton.Cancel)
    assert settings.focusWidget() is cancel and cancel.isDefault()
    QTest.keyClick(cancel, Qt.Key.Key_Escape)
    assert settings.result() == settings.DialogCode.Rejected


def test_floating_panel_compact_caption_preserves_redocking(window):
    window.viewmodel.new_project("Panels")
    dock = window.docks["inspector"]
    assert isinstance(dock, DockPanel)
    dock.show()
    dock.setFloating(True)
    assert dock.isFloating() and dock.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert dock.titlebar.maximize_button.isHidden()
    assert dock.titlebar.minimize_button.isHidden()
    assert dock.titlebar.close_button.isVisible()
    dock.setFloating(False)
    assert not dock.isFloating()
    assert not dock.isMaximized()
    assert dock.titlebar.maximize_button.isHidden()
    dock.titlebar.close_button.click()
    assert dock.isHidden()
    dock.toggleViewAction().trigger()
    assert not dock.isHidden()


def test_menu_alignment_toolbar_geometry_and_native_hover_state(window, qtbot):
    assert window.titlebar.caption.isHidden()
    assert "/" not in [
        label.text() for label in window.titlebar.findChildren(type(window.titlebar.caption))
    ]
    menu_center = window.menu_bar.geometry().center().y()
    assert abs(menu_center - window.titlebar.rect().center().y()) <= 1
    window.frame.set_maximize_hover(True)
    assert window.titlebar.maximize_button.property("nativeHover")
    window.frame.set_maximize_hover(False)
    assert not window.titlebar.maximize_button.property("nativeHover")
    window.viewmodel.new_project("Tools")
    toolbar = window.findChild(QToolBar, "toolbox")
    navigate = toolbar.widgetForAction(window.command_actions["navigate"])
    assert navigate.width() == navigate.height() and navigate.width() >= 32
    qtbot.mouseMove(navigate, navigate.rect().center())
    assert navigate.isChecked()
    menu_image = window.menu_bar.grab().toImage()
    assert menu_image.pixelColor(0, menu_image.height() - 1).name() == PALETTES["dark"]["canvas"]


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_caption_state_layers_and_close_red_feedback(window, theme):
    """Verify the rendered state colors used by Qt and native caption event bridges."""
    window.viewmodel.set_theme(theme)
    button = window.titlebar.maximize_button
    window.frame.set_maximize_hover(True)
    assert button.grab().toImage().pixelColor(3, 20).name() == PALETTES[theme]["hover"]
    button.setDown(True)
    assert button.grab().toImage().pixelColor(3, 20).name() == PALETTES[theme]["selected"]
    button.setDown(False)
    window.frame.set_maximize_hover(False)
    close = window.titlebar.close_button
    close.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
    assert close.grab().toImage().pixelColor(3, 20).name() == "#c42b1c"
    close.setDown(True)
    assert close.grab().toImage().pixelColor(3, 20).name() == "#a82216"
    close.setDown(False)
    close.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)


def test_theme_change_preserves_child_caption_close_feedback(window, qtbot):
    """Recoloring all buttons must retain white active close glyphs on a dialog's red surface."""
    dialog = CustomDialog(window, "Shared caption")
    qtbot.addWidget(dialog)
    dialog.show()
    window.viewmodel.set_theme("light")
    expected = window.icons.icon("close", 18, "#ffffff").pixmap(18, 18).toImage()
    actual = dialog.titlebar.close_button.icon().pixmap(18, 18, QIcon.Mode.Active).toImage()
    assert actual == expected


def test_theme_change_recolors_existing_media_controls(window, qtbot):
    """Open output/import controls must follow palette switches without reopening their dialogs."""
    window.viewmodel.new_project()
    window.show_output()
    window.show_media_import()
    controls = (
        (window.output_dialog.queue_button, "add_to_queue"),
        (window.media_dialog.import_button, "file_download"),
    )
    for theme in ("light", "dark"):
        window.viewmodel.set_theme(theme)
        for button, name in controls:
            expected = window.icons.icon(name).pixmap(20, 20).toImage()
            assert button.icon().pixmap(20, 20).toImage() == expected
