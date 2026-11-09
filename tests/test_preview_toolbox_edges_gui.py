"""The Tools strip docks only inside Preview without changing the document."""

import json
from pathlib import Path
from time import perf_counter

import pytest
from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from test_character_objects_gui import editor as editor
from test_preview_toolbox_gui import drag_grip
from test_timeline_title_gui import add_animal

pytestmark = pytest.mark.gui


@pytest.mark.parametrize("edge", ("left", "top", "right", "bottom"))
def test_tools_attach_to_each_preview_edge(editor, qtbot, edge):
    """Real grip gestures rotate the strip and reserve space within the Preview workspace."""
    strip = editor.docks["tools"]
    workspace = strip.parentWidget()
    assert workspace is not editor
    assert workspace.isAncestorOf(editor.viewport)
    baseline = editor.viewmodel.documents.project
    rect = workspace.rect()
    point = {
        "left": QPoint(2, rect.center().y()),
        "right": QPoint(rect.right() - 2, rect.center().y()),
        "top": QPoint(rect.center().x(), 2),
        "bottom": QPoint(rect.center().x(), rect.bottom() - 2),
    }[edge]
    drag_grip(strip, workspace.mapToGlobal(point))
    qtbot.waitUntil(lambda: strip.edge == edge)
    assert not strip.isFloating() and not strip.isWindow()
    assert workspace.rect().contains(strip.geometry())
    assert not strip.geometry().intersects(editor.viewport.geometry())
    horizontal = edge in ("top", "bottom")
    assert editor.toolbox.orientation() == (
        Qt.Orientation.Horizontal if horizontal else Qt.Orientation.Vertical
    )
    assert strip.width() > strip.height() if horizontal else strip.height() > strip.width()
    assert editor.viewmodel.documents.project is baseline


def test_tools_reject_other_panels_and_outside_drops(editor, qtbot):
    """Scene, Assets, headers and the desktop never become tool docking targets."""
    strip = editor.docks["tools"]
    before = strip.edge
    panels = [editor.docks[key].titleBarWidget() for key in ("hierarchy", "assets", "timeline")]
    panels += [editor.tab_row, editor.viewport_header]
    for panel in panels:
        point = panel.mapToGlobal(panel.rect().center())
        assert strip.dock_target(point) is None
        drag_grip(strip, point)
        qtbot.wait(10)
        assert strip.edge == before and not strip.isWindow()
    bounds = QRect(strip.parentWidget().mapToGlobal(QPoint()), strip.parentWidget().size())
    assert strip.dock_target(bounds.topLeft() - QPoint(1, 1)) is None
    editor.viewmodel.show_welcome()
    assert strip.dock_target(bounds.center()) is None


def test_keyboard_edges_and_old_floating_preferences_stay_in_preview(editor, qtbot):
    """Keyboard placement, malformed preferences and legacy float requests cannot escape."""
    strip = editor.docks["tools"]
    for key, edge in (
        (Qt.Key.Key_Up, "top"),
        (Qt.Key.Key_Right, "right"),
        (Qt.Key.Key_Down, "bottom"),
        (Qt.Key.Key_Home, "left"),
    ):
        QTest.keyClick(strip.grip, key)
        qtbot.waitUntil(lambda expected=edge: strip.edge == expected)
        assert not strip.isFloating()
    strip.setFloating(True)
    assert not strip.isFloating() and not strip.isWindow()
    for value in ({"edge": "float", "x": -900, "space": "screen"}, {"edge": []}):
        strip.restore_placement(value)
        assert strip.edge == "left" and not strip.isWindow()


def test_drag_feedback_keeps_scene_geometry_stable_and_escape_cancels(editor, qtbot):
    """Measure real pointer dispatch plus viewport paint without relayout during a drag."""

    def pointer(target, kind, point):
        """Send captured pointer events with their actual global positions."""
        QApplication.sendEvent(
            target,
            QMouseEvent(
                kind,
                QPointF(point),
                QPointF(target.mapToGlobal(point)),
                Qt.MouseButton.LeftButton
                if kind == QMouseEvent.Type.MouseButtonPress
                else Qt.MouseButton.NoButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            ),
        )

    add_animal(editor)
    qtbot.wait(50)
    strip = editor.docks["tools"]
    workspace = strip.parentWidget()
    baseline, geometry = editor.viewmodel.documents.project, editor.viewport.geometry()
    start = strip.grip.rect().center()
    pointer(strip.grip, QMouseEvent.Type.MouseButtonPress, start)
    samples = []
    for i in range(120):
        screen = workspace.mapToGlobal(QPoint(workspace.width() - 2, 50 + i % 80))
        local = strip.mapFromGlobal(screen)
        begin = perf_counter()
        pointer(strip, QMouseEvent.Type.MouseMove, local)
        editor.viewport.repaint()
        samples.append((perf_counter() - begin) * 1000)
        assert editor.viewport.geometry() == geometry
        assert strip.edge == "left" and not strip.isWindow()
    assert strip.drop_preview.isVisible()
    QTest.keyClick(strip.grip, Qt.Key.Key_Escape)
    assert strip.drop_preview.isHidden() and strip._press is None
    assert strip.grip.cursor().shape() == Qt.CursorShape.OpenHandCursor
    qtbot.wait(20)
    assert strip.edge == "left" and editor.viewmodel.documents.project is baseline
    report = Path("build/toolbox-preview-performance.json")
    report.write_text(
        json.dumps(
            {
                "sample_count": len(samples),
                "pointer_and_offscreen_viewport_paint_p95_ms": sorted(samples)[113],
                "viewport_size": [geometry.width(), geometry.height()],
                "scene_character_count": len(baseline.scenes[0].characters),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    for theme in ("dark", "light"):
        editor.apply_theme(theme)
        for edge in ("left", "top", "right", "bottom"):
            strip.dock_to(edge)
            qtbot.wait(10)
            assert editor.grab().save(f"build/tools-{theme}-{edge}.png")
