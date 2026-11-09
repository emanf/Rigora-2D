"""Real offscreen pointer placement, compact asset rendering and workspace persistence."""

import json
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem
from test_character_objects_gui import editor as editor
from test_object_scene_actions_gui import readable_offscreen_fonts as readable_offscreen_fonts
from test_timeline_title_gui import add_animal
from test_workspace_layout_menus_gui import reopen

from rigora.application_services.image_rigging import ImageRigService

pytestmark = pytest.mark.gui


def drag_grip(strip, global_target, before_release=None):
    """Keep one global gesture active even when undocking swaps and hides its caption."""
    handle = strip.drag_handle
    start = handle.mapToGlobal(handle.rect().center())
    # Later events intentionally go through the dock, as real mouse capture does.
    for kind, screen, target in (
        (QMouseEvent.Type.MouseButtonPress, start, handle),
        (QMouseEvent.Type.MouseMove, global_target, strip),
        (QMouseEvent.Type.MouseButtonRelease, global_target, strip),
    ):
        if kind == QMouseEvent.Type.MouseButtonRelease and before_release:
            before_release()
        event = QMouseEvent(
            kind,
            QPointF(target.mapFromGlobal(screen)),
            QPointF(screen),
            Qt.MouseButton.NoButton
            if kind == QMouseEvent.Type.MouseMove
            else Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton
            if kind == QMouseEvent.Type.MouseButtonRelease
            else Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(target, event)


def test_toolbox_fills_preview_side_and_stays_inside_preview(editor, qtbot):
    """Tools reserve their own preview column without becoming a desktop window."""
    strip, preview, scene = editor.docks["tools"], editor.viewport, editor.docks["hierarchy"]
    qtbot.wait(30)
    assert not strip.isFloating() and not strip.isWindow()
    assert strip.parentWidget().isAncestorOf(preview) and strip is not scene
    assert abs(strip.height() - preview.height()) <= 2
    assert strip.titleBarWidget() is strip.grip and strip.grip.isVisible()
    before = editor.viewmodel.documents.project
    drop = preview.mapToGlobal(QPoint(180, 80))
    drag_grip(strip, drop)
    assert not strip.isFloating() and not strip.isWindow()
    assert strip.width() == 44 and strip.grip.height() == 20
    position = strip.pos()
    qtbot.wait(50)
    assert strip.pos() == position
    outside = scene.mapToGlobal(QPoint(scene.width() // 2, 130))
    drag_grip(strip, outside)
    qtbot.wait(30)
    assert not strip.isFloating() and strip.pos() == position
    right = preview.mapToGlobal(QPoint(preview.width() - 2, 90))
    drag_grip(strip, right)
    qtbot.wait(20)
    assert not strip.isFloating() and strip.edge == "right"
    assert abs(strip.height() - preview.height()) <= 2
    strip.reset_position()
    qtbot.wait(20)
    assert strip.edge == "left" and abs(strip.height() - preview.height()) <= 2
    strip.toggleViewAction().trigger()
    assert strip.isHidden()
    strip.toggleViewAction().trigger()
    assert not strip.isHidden()
    assert editor.viewmodel.documents.project is before


def test_dots_show_drop_feedback_only_at_preview_edges(editor, qtbot):
    """Feedback and release use identical bounds inside the preview workspace."""
    strip = editor.docks["tools"]
    qtbot.wait(30)
    center = strip.parentWidget()
    point = center.mapToGlobal(QPoint(center.width() - 2, center.height() // 2))

    def check_drop_preview():
        assert strip.drop_preview.isVisible()
        assert strip.drop_preview.geometry().contains(center.mapFromGlobal(point))
        assert center.rect().contains(strip.drop_preview.geometry())

    drag_grip(strip, point, before_release=check_drop_preview)
    qtbot.wait(30)
    assert not strip.isFloating() and strip.edge == "right"
    assert strip.drop_preview.isHidden()

    def check_no_drop_preview():
        assert strip.drop_preview.isHidden()

    for name in ("assets", "hierarchy"):
        caption = editor.docks[name].titlebar
        drag_grip(
            strip,
            caption.mapToGlobal(caption.rect().center()),
            before_release=check_no_drop_preview,
        )
        qtbot.wait(20)
        assert not strip.isFloating() and strip.edge == "right"
        assert strip not in editor.tabifiedDockWidgets(editor.docks[name])


def test_tools_never_merge_into_scene_or_other_panel_tabs(editor, qtbot):
    """App panel-tab requests retain Tools inside their own preview workspace."""
    strip, scene = editor.docks["tools"], editor.docks["hierarchy"]
    editor.tabifyDockWidget(scene, strip)
    qtbot.waitUntil(lambda: strip not in editor.tabifiedDockWidgets(scene))
    assert not strip.isFloating() and not scene.isHidden()
    assert abs(strip.height() - editor.viewport.height()) <= 2
    assert strip.titleBarWidget() is strip.grip
    editor.tabifyDockWidget(scene, editor.docks["inspector"])
    strip.reset_position()
    qtbot.wait(20)
    assert strip not in editor.tabifiedDockWidgets(scene)
    assert strip.parentWidget().isAncestorOf(editor.viewport)


def test_toolbox_square_controls_and_grip_cursor_lifecycle(editor, qtbot):
    """Real buttons remain centered, with rounded states and an idle/drag cursor that resets."""
    strip, bar = editor.docks["tools"], editor.toolbox
    qtbot.wait(20)
    assert strip.width() == 44
    buttons = [bar.widgetForAction(a) for a in bar.actions() if not a.isSeparator()]
    assert all(button.width() == button.height() == 34 for button in buttons)
    assert buttons[0].mapTo(strip, QPoint()).y() - strip.grip.geometry().bottom() >= 10, (
        strip.widget().layout().contentsMargins().top(),
        strip.widget().geometry().getRect(),
        bar.geometry().getRect(),
    )
    assert all(
        abs(button.mapTo(strip, button.rect().center()).x() - strip.rect().center().x()) <= 1
        for button in buttons
    ), (
        strip.geometry().getRect(),
        bar.geometry().getRect(),
        [b.geometry().getRect() for b in buttons],
    )
    output = Path("build/toolbox-polish-review")
    output.mkdir(parents=True, exist_ok=True)
    selected = bar.widgetForAction(editor.command_actions["navigate"])
    for theme in ("dark", "light"):
        editor.apply_theme(theme)
        selected.setChecked(True)
        for state in ("checked", "hover", "pressed"):
            selected.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, state == "hover")
            selected.setDown(state == "pressed")
            qtbot.wait(5)
            picture = selected.grab().toImage()
            assert picture.pixelColor(0, 0) != picture.pixelColor(2, picture.height() // 2)
            picture.save(str(output / f"{theme}-{state}.png"))
        selected.setDown(False)
        selected.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
        strip.grab().save(str(output / f"{theme}-attached.png"))
    editor.apply_theme("dark")
    grip = strip.grip
    for point in (QPoint(3, 3), QPoint(20, 8), QPoint(20, 12), QPoint(40, 17)):
        event = QMouseEvent(
            QMouseEvent.Type.MouseMove,
            QPointF(point),
            QPointF(grip.mapToGlobal(point)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        event.ignore()
        QApplication.sendEvent(grip, event)
        assert event.isAccepted()
        assert grip.cursor().shape() == Qt.CursorShape.OpenHandCursor
    point = grip.rect().center()
    for kind, buttons, expected in (
        (
            QMouseEvent.Type.MouseButtonPress,
            Qt.MouseButton.LeftButton,
            Qt.CursorShape.ClosedHandCursor,
        ),
        (
            QMouseEvent.Type.MouseButtonRelease,
            Qt.MouseButton.NoButton,
            Qt.CursorShape.OpenHandCursor,
        ),
    ):
        QApplication.sendEvent(
            grip,
            QMouseEvent(
                kind,
                QPointF(point),
                QPointF(grip.mapToGlobal(point)),
                Qt.MouseButton.LeftButton,
                buttons,
                Qt.KeyboardModifier.NoModifier,
            ),
        )
        assert grip.cursor().shape() == expected
    strip.grab().save(str(output / "grip.png"))


@pytest.mark.parametrize("edge", ("top", "right", "bottom"))
def test_toolbox_and_timeline_channel_widths_survive_relaunch(editor, qtbot, tmp_path, edge):
    """Every preview-local edge and user channel widths survive fresh launch and reset."""
    strip = editor.docks["tools"]
    strip.dock_to(edge)
    editor.timeline.tracks.setColumnWidth(1, 39)
    editor.timeline.tracks.setColumnWidth(2, 37)
    other = reopen(editor, qtbot, tmp_path / "tool-layout.rigora")
    restored = other.docks["tools"]
    assert restored.parentWidget().isAncestorOf(other.viewport) and not restored.isWindow()
    assert not restored.isFloating() and restored.edge == edge
    assert not restored.isHidden()
    assert other.timeline.tracks.columnWidth(1) == 39
    assert other.timeline.tracks.columnWidth(2) == 37
    other.viewmodel.changed.emit()
    assert other.timeline.tracks.columnWidth(1) == 39
    other.restore_layout()
    qtbot.wait(20)
    assert not restored.isFloating() and restored.edge == "left"
    assert abs(restored.height() - other.viewport.height()) <= 2
    assert other.timeline.tracks.columnWidth(1) == 26
    other.close()


def test_hidden_toolbox_restores_with_an_unchecked_view_action(editor, qtbot, tmp_path):
    """Saving from a visible preview preserves an explicit hidden choice on the next launch."""
    editor.docks["tools"].toggleViewAction().trigger()
    assert editor.docks["tools"].isHidden()
    other = reopen(editor, qtbot, tmp_path / "hidden-tools.rigora")
    assert other.docks["tools"].isHidden()
    assert not other.docks["tools"].toggleViewAction().isChecked()
    other.docks["tools"].toggleViewAction().trigger()
    assert not other.docks["tools"].isHidden()
    other.close()


def test_restoring_an_independent_toolbox_does_not_rewrite_native_layout(
    editor, monkeypatch, qtbot
):
    """An already docked saved column must not enter Qt's native split/animation path again."""
    strip = editor.docks["tools"]
    geometry = strip.geometry()

    def unexpected_split(*args):
        pytest.fail("Restoring an existing Tools column must retain the native layout tree")

    monkeypatch.setattr(editor, "splitDockWidget", unexpected_split)
    strip.restore_placement({"edge": "left", "space": "screen"})
    assert strip.geometry() == geometry
    assert not strip.isFloating() and strip.titleBarWidget() is strip.grip
    saved = Path(__file__).parent / "fixtures/toolbox-startup-layout.json"
    editor.viewmodel.preferences.data.update(json.loads(saved.read_text(encoding="utf-8")))
    editor._restore_workspace()
    qtbot.wait(20)
    assert not strip.isFloating()
    assert strip not in editor.tabifiedDockWidgets(editor.docks["hierarchy"])
    assert editor.dockWidgetArea(strip) == Qt.DockWidgetArea.NoDockWidgetArea
    left_edge = max(
        dock.x() + dock.width()
        for dock in editor.docks.values()
        if editor.dockWidgetArea(dock) == Qt.DockWidgetArea.LeftDockWidgetArea
        and not dock.visibleRegion().isEmpty()
    )
    assert editor.centralWidget().x() - left_edge == 1


def test_compact_tree_assets_and_timeline_remain_readable_and_interactive(editor, qtbot):
    """A real creator rig exposes guides/state controls and compact source cards in both themes."""
    add_animal(editor)
    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40">'
        b'<circle cx="20" cy="20" r="8" fill="#aaaaaa"/></svg>'
    )
    images = ImageRigService(editor.viewmodel.documents)
    mesh = images.import_image_bytes("Transparent SVG.svg", svg)
    editor.viewmodel.changed.emit()
    asset = images.mesh(mesh).asset_id
    qtbot.waitUntil(lambda: asset in editor.viewport.artwork.images, timeout=10000)
    tree = editor.tree
    assert tree.iconSize().width() == 20
    assert tree.columnWidth(1) < 30 and tree.columnWidth(2) < 30
    first = tree.topLevelItem(0)
    first.setExpanded(True)
    option = QStyleOptionViewItem()
    index = tree.model().index(0, 1)
    tree.itemDelegateForColumn(1).initStyleOption(option, index)
    assert option.decorationSize.width() == 12
    item = next(
        editor.project_assets.item(i)
        for i in range(editor.project_assets.count())
        if editor.project_assets.item(i).data(Qt.ItemDataRole.UserRole) == asset
    )
    editor.project_assets.scrollToItem(item)
    qtbot.wait(20)
    rect = editor.project_assets.visualItemRect(item)
    from rigora.presentation.widgets.asset_cards import CARD_IMAGE_SIZE, CARD_SIZE

    assert rect.height() == CARD_SIZE
    assert editor.project_assets.iconSize().width() == CARD_IMAGE_SIZE
    assert editor.timeline.tracks.columnWidth(1) == editor.timeline.tracks.columnWidth(2) == 26
    output = Path("build/preview-toolbox-review")
    output.mkdir(parents=True, exist_ok=True)
    for theme in ("dark", "light"):
        editor.apply_theme(theme)
        qtbot.wait(20)
        editor.grab().save(str(output / f"workspace-{theme}.png"))
        editor.docks["tools"].grab().save(str(output / f"toolbox-{theme}.png"))
        editor.project_assets.grab().save(str(output / f"assets-{theme}.png"))
    editor.apply_theme("dark")
