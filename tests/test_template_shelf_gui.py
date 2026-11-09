"""A loaded template catalog must stay visible or explain exactly why filters hide its cards."""

import pytest
from PySide6.QtCore import Qt
from test_workspace_redesign_gui import editor as editor
from test_workspace_redesign_gui import readable_offscreen_fonts as readable_offscreen_fonts

pytestmark = pytest.mark.gui


def has_visible_card(shelf):
    """Inspect real icon-view rectangles, rather than treating a nonzero model count as visible."""
    viewport = shelf.results.viewport().rect()
    return any(
        shelf.results.visualItemRect(shelf.results.item(i)).intersects(viewport)
        for i in range(shelf.results.count())
    )


def test_loaded_templates_show_cards_and_zero_matches_have_explicit_recovery(editor, qtbot):
    """Use real catalog and thumbnail workers without suppressing startup operations."""
    shelf, model = editor.content_shelf, editor.viewmodel.content
    editor.library_tabs.setCurrentWidget(shelf)
    assert len(model.entries) == 287 and not model.error
    assert shelf.results.count() == 287 and len(shelf.icons) == 287
    qtbot.waitUntil(lambda: has_visible_card(shelf), timeout=10000)
    baseline = editor.viewmodel.documents.project
    shelf.collection.setCurrentText("Characters")
    shelf.character_view.setCurrentText("Side")
    shelf.search.setText("no-matching-character-987654321")
    assert shelf.results.count() == 0
    assert shelf.result_pages.currentWidget() is shelf.empty
    assert "match" in shelf.empty_message.text()
    assert shelf.status.text() == "0 shown · 287 available"
    qtbot.mouseClick(shelf.recover, Qt.MouseButton.LeftButton)
    assert shelf.collection.currentText() == "All" and shelf.search.text() == ""
    assert shelf.character_view.currentData() == ""
    assert shelf.results.count() == 287
    assert shelf.result_pages.currentWidget() is shelf.results
    assert has_visible_card(shelf)
    assert editor.viewmodel.documents.project is baseline


def test_empty_categories_are_omitted_and_custom_has_a_route_back_to_templates(editor, qtbot):
    """Keep source/filter changes explicit, with a working route back to bundled templates."""
    shelf = editor.content_shelf
    editor.library_tabs.setCurrentWidget(shelf)
    assert shelf.collection.findText("Favorites") == -1
    assert shelf.collection.findText("Recent") == -1
    assert shelf.results.count() == 287
    shelf.tabs.setCurrentIndex(1)
    assert shelf.results.count() == 0
    assert [shelf.collection.itemText(i) for i in range(shelf.collection.count())] == ["All"]
    assert shelf.empty_message.text() == "No custom packs installed."
    assert shelf.recover.text() == "Browse templates"
    qtbot.mouseClick(shelf.recover, Qt.MouseButton.LeftButton)
    assert shelf.tabs.currentIndex() == 0 and shelf.results.count() == 287


def test_hidden_category_reload_rebuilds_card_geometry_without_manual_resize(editor, qtbot):
    """Changing a long scrolled icon view while hidden cannot leave an obsolete blank viewport."""
    shelf = editor.content_shelf
    editor.library_tabs.setCurrentWidget(shelf)
    shelf.results.scrollToBottom()
    editor.library_tabs.setCurrentIndex(0)
    assert editor.library_tabs.currentWidget() is not shelf
    shelf.collection.setCurrentText("Characters")
    shelf.character_view.setCurrentText("All views")
    shelf.model.reload()
    qtbot.waitUntil(lambda: not shelf.model.busy, timeout=30000)
    assert shelf.results.count() > 0
    editor.library_tabs.setCurrentWidget(shelf)
    qtbot.waitUntil(lambda: has_visible_card(shelf), timeout=10000)
    assert shelf.result_pages.currentWidget() is shelf.results
    assert "287 available" in shelf.status.text()
    shelf.grab().save("build/templates-visible-recovery.png")


def test_thumbnail_arrival_preserves_existing_cards_selection_and_scroll(editor, qtbot):
    """Loading preview images must not clear and rebuild an already usable template grid."""
    shelf = editor.content_shelf
    editor.library_tabs.setCurrentWidget(shelf)
    shelf.results.setCurrentRow(shelf.results.count() - 1)
    shelf.results.scrollToBottom()
    first, selected = shelf.results.item(0), shelf.results.currentItem()
    scroll = shelf.results.verticalScrollBar().value()
    shelf.load_thumbnails(shelf.model.entries[0].path)
    qtbot.waitUntil(lambda: not shelf.model.busy, timeout=10000)
    assert shelf.results.item(0) is first
    assert shelf.results.currentItem() is selected
    assert shelf.results.verticalScrollBar().value() == scroll
    assert has_visible_card(shelf)


def test_failed_thumbnail_batch_can_retry_without_losing_loaded_cards(editor, qtbot, monkeypatch):
    """A temporary image read failure must release the per-pack loading flag for Refresh."""
    import rigora.presentation.widgets.workspace_panels as module
    from rigora.domain.project import ProjectError

    shelf = editor.content_shelf
    path, attempts = shelf.model.entries[0].path, []
    original = module.read_pack

    def fail_once(source, **options):
        """Model one unavailable image batch without changing any real bundled files."""
        if source == path and not attempts:
            attempts.append(source)
            raise ProjectError("Temporary thumbnail read failure")
        return original(source, **options)

    monkeypatch.setattr(module, "read_pack", fail_once)
    first = shelf.results.item(0)
    shelf.load_thumbnails(path)
    qtbot.waitUntil(lambda: not shelf.model.busy, timeout=10000)
    assert path not in shelf.loading and "Temporary" in shelf.model.error
    assert shelf.results.count() == 287 and shelf.results.item(0) is first
    shelf.load_thumbnails(path)
    qtbot.waitUntil(lambda: not shelf.model.busy, timeout=10000)
    assert path not in shelf.loading and not shelf.model.error
    assert shelf.results.item(0) is first
