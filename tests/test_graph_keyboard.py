"""Graph editing has native numerical equivalents and preserves timing anchors and Undo."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from rigora.engine.transition_curves import TransitionCurve
from rigora.presentation.icons import IconProvider
from rigora.presentation.widgets.curve_editor import CurveCanvas, CurveEditor

pytestmark = pytest.mark.gui


def test_keyboard_point_navigation_nudging_limits_and_undo(qtbot):
    canvas = CurveCanvas(None)
    qtbot.addWidget(canvas)
    curve = TransitionCurve(points=((0, 0), (0.5, 0.5), (1, 1)))
    canvas.set_curve(curve)
    canvas.selected = 1
    QTest.keyClick(canvas, Qt.Key.Key_Right)
    assert canvas.curve.points[1] == pytest.approx((0.51, 0.5))
    assert canvas.selected == 1
    canvas.undo()
    assert canvas.curve == curve
    canvas.selected = 1
    QTest.keyClick(canvas, Qt.Key.Key_Up, Qt.KeyboardModifier.ShiftModifier)
    assert canvas.curve.points[1][1] == pytest.approx(0.6)
    QTest.keyClick(canvas, Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)
    assert canvas.selected == 2
    original = canvas.curve
    QTest.keyClick(canvas, Qt.Key.Key_Down)
    assert canvas.curve == original
    canvas.edit_point(1, 2, 8)
    assert canvas.curve.points[1] == pytest.approx((1 - 1e-5, 5))


def test_native_point_fields_follow_selection_and_share_graph_constraints(qtbot):
    from PySide6.QtWidgets import QWidget

    parent = QWidget()
    qtbot.addWidget(parent)
    editor = CurveEditor(parent, IconProvider())
    curve = TransitionCurve(points=((0, 0), (0.5, 0.5), (1, 1)))
    editor.chart.set_curve(curve)
    editor.point_index.setCurrentIndex(1)
    assert editor.chart.selected == 1 and editor.point_time.isEnabled()
    editor.point_value.setValue(0.7)
    assert editor.chart.curve.points[1] == pytest.approx((0.5, 0.7))
    editor.chart.undo()
    assert editor.chart.curve == curve
    editor.point_index.setCurrentIndex(2)
    assert not editor.point_value.isEnabled() and not editor.point_time.isEnabled()
