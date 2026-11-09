"""Shared card geometry stays fixed across artwork, labels and panel resizing."""

import pytest


@pytest.mark.gui
def test_card_wells_and_gaps_match_in_every_shared_grid(qtbot):
    """Measure actual item rectangles, including after wrapping and panel resizing."""
    from PySide6.QtCore import QSize, Qt
    from PySide6.QtGui import QIcon, QPixmap
    from PySide6.QtWidgets import QListWidget, QListWidgetItem, QWidget

    from rigora.presentation.widgets.asset_cards import (
        CARD_GAP,
        CARD_IMAGE_SIZE,
        CARD_SIZE,
        AssetCardDelegate,
    )
    from rigora.presentation.widgets.character_wizard import ChoiceGrid
    from rigora.presentation.widgets.content_browser import ContentDragList
    from rigora.presentation.widgets.creator_cards import configure_cards
    from rigora.presentation.widgets.curve_editor import CurvePresets
    from rigora.presentation.widgets.scene_tree import ProjectImageList

    parent = QWidget()
    qtbot.addWidget(parent)
    ordinary = QListWidget()
    configure_cards(ordinary)
    views = (ordinary, ContentDragList(), ProjectImageList(), ChoiceGrid(), CurvePresets(parent))
    for view in views:
        qtbot.addWidget(view)
        view.clear()
        for i in range(12):
            pixmap = QPixmap(8 if i % 2 else 120, 120 if i % 2 else 8)
            pixmap.fill(Qt.GlobalColor.white)
            item = QListWidgetItem(QIcon(pixmap), "Short" if i % 2 else "Two line card caption")
            view.addItem(item)
        for width in (430, 580, 315):
            view.resize(width, 600)
            view.show()
            qtbot.wait(20)
            rects = [view.visualItemRect(view.item(i)) for i in range(view.count())]
            assert all(r.size() == QSize(CARD_SIZE, CARD_SIZE) for r in rects)
            wells = [AssetCardDelegate.image_rect(r) for r in rects]
            assert all(w.size() == QSize(CARD_IMAGE_SIZE, CARD_IMAGE_SIZE) for w in wells)
            for first, second in zip(rects, rects[1:], strict=False):
                if first.top() == second.top():
                    assert second.left() - first.right() - 1 == CARD_GAP
            below = next(r for r in rects if r.top() > rects[0].top())
            assert below.top() - rects[0].bottom() - 1 == CARD_GAP
        view.close()


@pytest.mark.gui
def test_shared_card_checkbox_uses_its_visible_hit_target(qtbot):
    """The include checkbox and preview selection stay independent in generic card views."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QListWidget, QListWidgetItem

    from rigora.presentation.widgets.asset_cards import AssetCardDelegate, configure_card_grid

    view = QListWidget()
    qtbot.addWidget(view)
    configure_card_grid(view)
    item = QListWidgetItem("Alternative")
    item.setCheckState(Qt.CheckState.Unchecked)
    view.addItem(item)
    view.show()
    qtbot.wait(20)
    rect = view.visualItemRect(item)
    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    assert item.checkState() == Qt.CheckState.Unchecked
    qtbot.mouseClick(
        view.viewport(),
        Qt.MouseButton.LeftButton,
        pos=AssetCardDelegate.check_rect(rect).center(),
    )
    assert item.checkState() == Qt.CheckState.Checked
    qtbot.keyClick(view, Qt.Key.Key_Space)
    assert item.checkState() == Qt.CheckState.Unchecked


@pytest.mark.gui
def test_small_vector_features_fill_the_thumbnail_resolution(qtbot):
    """Tiny eyes and lips are rendered from vectors rather than enlarged low-resolution pixels."""
    from rigora.presentation.artwork import decode_artwork

    source = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="8" height="4" viewBox="0 0 8 4">'
        b'<ellipse cx="4" cy="2" rx="3" ry="1" fill="black"/></svg>'
    )
    original = decode_artwork(source, 128)
    icon = decode_artwork(source, 128, upscale_vectors=True)
    assert (original.width(), original.height()) == (8, 4)
    assert (icon.width(), icon.height()) == (128, 64)


@pytest.mark.gui
def test_cards_and_previews_share_live_theme_checkerboards(qtbot, qapp):
    """Paint both palettes and switch live without baking the checker into source media."""
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QListWidget, QListWidgetItem, QWidget

    from rigora.domain.project import SceneSettings
    from rigora.presentation.icons import IconProvider
    from rigora.presentation.themes import PALETTES, ThemeManager
    from rigora.presentation.widgets.asset_cards import AssetCardDelegate, configure_card_grid
    from rigora.presentation.widgets.face_preview import FacePreview
    from rigora.presentation.widgets.video_rig import PosePreview
    from rigora.presentation.widgets.viewport import Viewport

    original_palette, original_style = qapp.palette(), qapp.styleSheet()
    themes = ThemeManager(qapp, IconProvider())
    host = QWidget()
    qtbot.addWidget(host)
    cards = QListWidget()
    qtbot.addWidget(cards)
    configure_card_grid(cards)
    cards.addItem(QListWidgetItem("Readable caption"))
    cards.resize(200, 180)
    cards.show()
    scene = Viewport()
    qtbot.addWidget(scene)
    scene.set_scene(SceneSettings())
    scene.grid_visible = scene.frame_visible = False
    face = FacePreview()
    qtbot.addWidget(face)
    video = PosePreview(host)
    previews = (scene, face, video)
    try:
        for name in ("dark", "light", "dark"):
            themes.apply(name)
            qtbot.wait(30)
            colors = PALETTES[name]
            well = AssetCardDelegate.image_rect(cards.visualItemRect(cards.item(0)))
            card = cards.grab().toImage()
            # The image well is empty: only the shared checker should be present.
            sampled = {
                card.pixelColor(cards.viewport().pos() + well.topLeft() + QPoint(x, y)).name()
                for x, y in ((10, 10), (18, 10))
            }
            assert sampled == {colors["checker_a"], colors["checker_b"]}
            for preview in previews:
                image = preview.grab().toImage()
                assert {image.pixelColor(x, y).name() for x, y in ((2, 2), (14, 2))} == sampled
            assert (
                card.pixelColor(
                    cards.viewport().pos()
                    + cards.visualItemRect(cards.item(0)).topLeft()
                    + QPoint(3, 60)
                ).name()
                == colors["raised"]
            )
    finally:
        cards.close()
        qapp.setPalette(original_palette)
        qapp.setStyleSheet(original_style)
