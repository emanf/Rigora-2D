"""Native current Creator controls keep visible defaults independent of retained alternatives."""

import pytest
from PySide6.QtCore import QPointF, Qt
from test_roots_soft_drag_gui import editor as editor

from rigora.presentation.widgets.asset_cards import AssetCardDelegate
from rigora.presentation.widgets.character_wizard import CharacterWizard

pytestmark = pytest.mark.gui


def creator(editor, qtbot):
    """Open the current Creator and wait for its real isolated preview and card assets."""
    dialog = CharacterWizard(editor)
    editor.test_creator = dialog
    dialog.show()
    qtbot.waitUntil(
        lambda: (
            dialog.model.ready == dialog.recipe
            and not dialog.model.busy
            and dialog.model.cards_current()
        ),
        timeout=30000,
    )
    return dialog


def select_design(dialog, name):
    """Choose a displayed preset through its actual item data."""
    dialog.choose_design(
        next(
            dialog.presets.item(i)
            for i in range(dialog.presets.count())
            if dialog.presets.item(i).text().split("\n")[0] == name
        )
    )


@pytest.fixture
def wizard(editor, qtbot):
    dialog = creator(editor, qtbot)
    yield dialog
    dialog.close()


def test_card_preview_click_and_retention_checkbox_remain_independent(wizard, qtbot):
    grid = wizard.grids["Hands"]
    wizard.sections["Hands"].property("sectionHeader").setChecked(True)
    wizard.options_scroll.ensureWidgetVisible(grid)
    qtbot.wait(5)
    item = next(
        grid.item(i)
        for i in range(grid.count())
        if grid.item(i).data(Qt.ItemDataRole.UserRole) == "Fist"
    )
    rect = grid.visualItemRect(item)
    qtbot.mouseClick(grid.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    assert wizard.recipe.poses["Hands"] == "Fist"
    assert item.checkState() == Qt.CheckState.Unchecked
    qtbot.mouseClick(
        grid.viewport(), Qt.MouseButton.LeftButton, pos=AssetCardDelegate.check_rect(rect).center()
    )
    assert item.checkState() == Qt.CheckState.Checked
    assert "Fist" in wizard.recipe.alternatives["Hands"]
    assert wizard.recipe.poses["Hands"] == "Fist"


def test_mirror_controls_are_view_local_and_comparison_never_changes_scene(wizard, editor, qtbot):
    baseline = editor.viewmodel.documents.project
    wizard.hand_flips["right"].setChecked(True)
    assert wizard.recipe.hand_flips["Front 3/4"]["right"]
    wizard.view.setCurrentText("Front")
    assert not wizard.hand_flips["right"].isChecked()
    wizard.view.setCurrentText("Front 3/4")
    assert wizard.hand_flips["right"].isChecked()
    wizard.compare_views()
    assert wizard.turnaround.isVisible()
    assert editor.viewmodel.documents.project is baseline
    wizard.turnaround.close()


def test_preview_transport_and_loading_are_isolated_from_scene(wizard, editor, qtbot):
    baseline = editor.viewmodel.documents.project
    assert wizard.loading.height() == 3
    wizard.select_motion("Run")
    wizard.play.click()
    qtbot.waitUntil(lambda: wizard.model.preview.animation.playback.frame > 0, timeout=5000)
    assert not editor.viewmodel.playback.session.playback.is_playing
    assert editor.viewmodel.documents.project is baseline
    wizard.play.click()
    assert not wizard.model.preview.animation.playback.is_playing


def test_dialog_resize_preserves_preview_center_and_manual_zoom(wizard, qtbot):
    """Resizing the editor retains the viewed scene center, including after zoom and pan."""
    preview = wizard.preview
    preview.zoom_at(1.2)
    preview.offset += QPointF(30, -20)
    zoom, size = preview.zoom, preview.size()
    center = preview.scene_point(QPointF(preview.width() / 2, preview.height() / 2))
    wizard.resize(900, 560)
    qtbot.waitUntil(lambda: preview.size() != size)
    assert preview.zoom == zoom
    assert preview.scene_point(QPointF(preview.width() / 2, preview.height() / 2)).toTuple() == (
        pytest.approx(center.toTuple())
    )
