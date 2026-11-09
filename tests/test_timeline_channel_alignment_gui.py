"""Timeline state controls remain usable at the channel panel's resized right edge."""

import base64

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QHeaderView, QStyle, QStyleOptionViewItem
from test_roots_soft_drag_gui import editor as editor

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.appearance import AppearanceService

pytestmark = pytest.mark.gui


def test_channel_resize_anchors_controls_and_old_preferences_cannot_restore_trailing_gap(
    editor, qtbot
):
    """Resize the actual splitter, restore an old header, and click the relocated state cells."""
    vm, timeline = editor.viewmodel, editor.timeline
    mesh = AppearanceService(vm.documents).create_shape("rectangle", 100, 120, 80, 100)
    owner = vm.documents.scene.meshes[0].object_id
    assert mesh == vm.documents.scene.meshes[0].id
    service = AnimationEditingService(vm.documents)
    service.add_channels(((owner, "transform.x"),))
    vm.changed.emit()
    tree, header = timeline.tracks, timeline.tracks.header()

    def resize_and_check(width):
        """Verify actual viewport geometry, including a narrow name column and both state cells."""
        timeline.splitter.setSizes([width, timeline.splitter.width() - width])
        qtbot.wait(10)
        right = tree.viewport().width()
        assert header.sectionViewportPosition(2) + header.sectionSize(2) == right
        assert header.sectionViewportPosition(1) + header.sectionSize(
            1
        ) == header.sectionViewportPosition(2)
        assert header.sectionViewportPosition(0) + header.sectionSize(
            0
        ) == header.sectionViewportPosition(1)
        assert header.sectionSize(1) == header.sectionSize(2) == 26
        assert tree.horizontalScrollBar().maximum() == 0

    for width in (180, 340, 520, 210):
        resize_and_check(width)
    for column, width in enumerate((200, 90, 110)):
        header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(column, width)
    editor.viewmodel.preferences.data["panel_state"] = {
        "timeline_channels": base64.b64encode(header.saveState().data()).decode("ascii")
    }
    editor._restore_workspace()
    resize_and_check(360)
    tree.expandAll()
    qtbot.wait(10)

    def click_state(column):
        """Use the real checkbox hit target after the name column has changed width."""
        row = next(
            r
            for r in timeline._groups.values()
            if timeline.row_tracks(r) and r.data(column, Qt.ItemDataRole.CheckStateRole) is not None
        )
        index = tree.indexFromItem(row, column)
        option = QStyleOptionViewItem()
        option.initFrom(tree.viewport())
        option.rect = tree.visualRect(index)
        tree.itemDelegate().initStyleOption(option, index)
        point = (
            tree.style()
            .subElementRect(QStyle.SubElement.SE_ItemViewItemCheckIndicator, option, tree)
            .center()
        )
        QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=point)

    click_state(1)
    qtbot.waitUntil(lambda: service.timeline.tracks[0].locked)
    click_state(2)
    qtbot.waitUntil(lambda: not service.timeline.tracks[0].visible)
    editor.restore_layout()
    resize_and_check(300)
