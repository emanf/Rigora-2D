"""Real source-window drag/drop applies data presets without opening another editor."""

import pytest
from PySide6.QtCore import QPointF

from rigora.app.application import ApplicationInfo
from rigora.application_services.characters import CharacterService
from rigora.application_services.content_library import ContentService
from rigora.domain.geometry import transform_point
from rigora.infrastructure.preferences import PreferencesStore
from rigora.presentation.viewmodels.main_window import MainWindowViewModel
from rigora.presentation.views.main_window import MainWindow

pytestmark = pytest.mark.gui


@pytest.fixture
def editor(qtbot, tmp_path, catalog_root):
    """Use actual catalog generation and thumbnail loading, entirely offscreen."""
    vm = MainWindowViewModel(
        ApplicationInfo(), preferences=PreferencesStore(tmp_path / "preferences.json")
    )
    vm.content.library.cache_root = catalog_root
    window = MainWindow(vm)
    qtbot.addWidget(window)
    window.confirm_discard = lambda: True
    window.resize(1400, 900)
    window.show()
    qtbot.waitUntil(lambda: not vm.content.busy, timeout=120000)
    assert not vm.content.error
    vm.new_project()
    try:
        yield window
    finally:
        window.close()


@pytest.fixture(scope="module")
def catalog_root(catalog_cache_root):
    """Share only generated immutable source packs; each editor retains independent state."""
    return catalog_cache_root


@pytest.mark.parametrize(
    "category",
    (
        "Human walks",
        "FFD motions",
        "Spring dynamics",
        "Fire & smoke",
        "Water & weather",
        "Shapes",
        "Home & interiors",
    ),
)
def test_drag_empty_space_previews_and_places_one_undoable_object(editor, qtbot, category):
    """Use the real hover/drop controller and inspect its source document and ghost geometry."""
    vm = editor.viewmodel
    workspace = editor.content_drop
    entry = next(e for e in vm.content.entries if e.item.category == category)
    baseline = vm.documents.project
    point = QPointF(480, 300)
    expected = editor.viewport.scene_point(point)
    workspace.move(entry.key, point)
    qtbot.waitUntil(lambda: editor.viewport.drop_pose is not None, timeout=30000)
    assert vm.documents.project is baseline
    assert editor.viewport.drop_pose.nodes
    workspace.drop(entry.key, point)
    qtbot.waitUntil(lambda: not vm.content.busy and not workspace.placing, timeout=30000)
    assert not vm.content.error
    doc = vm.documents
    roots = CharacterService(doc).scene_objects()
    assert len(roots) == 1
    root = CharacterService(doc).record(roots[0])
    assert transform_point(
        doc.animation.pose.nodes[root.id].world_matrix,
        root.transform.pivot_x,
        root.transform.pivot_y,
    ) == pytest.approx(expected.toTuple())
    assert not editor.object_edit.active
    assert vm.scene.selected == (root.id,)
    assert len(doc.history.undo_stack) == 1
    vm.undo()
    assert doc.project == baseline


def test_motion_and_spring_apply_to_selected_rig_without_new_objects(editor, qtbot):
    """Double-click application resolves the selected rig rather than a different scene rig."""
    vm = editor.viewmodel
    rig_entry = next(e for e in vm.content.entries if e.item.name == "Human · full body")
    rig_id = ContentService(vm.documents).place(rig_entry.item, {}, position=(500, 400))
    root = CharacterService(vm.documents).object_root(rig_id)
    vm.changed.emit()
    editor.scene_workspace.select_entries((root.id,))
    for category in ("Human runs", "Spring dynamics"):
        entry = next(e for e in vm.content.entries if e.item.category == category)
        baseline = vm.documents.project
        count = len(vm.documents.history.undo_stack)
        editor.content_drop.apply_to_selection(entry.key)
        qtbot.waitUntil(lambda: not vm.content.busy, timeout=30000)
        assert not vm.content.error
        assert len(vm.documents.scene.skeletons) == 1
        assert len(CharacterService(vm.documents).scene_objects()) == 1
        assert len(vm.documents.history.undo_stack) == count + 1
        vm.undo()
        assert vm.documents.project == baseline


def test_creative_category_cards_are_visible_and_have_fixed_preview_images(editor, qtbot):
    """The catalog exposes populated effect categories and decoded previews in the actual shelf."""
    shelf = editor.content_shelf
    editor.library_tabs.setCurrentWidget(shelf)
    expected = {
        "Human walks": 12,
        "Human runs": 9,
        "Skeleton templates": 11,
        "FFD motions": 20,
        "FFD shapes": 6,
        "Spring dynamics": 20,
    }
    for category, count in expected.items():
        shelf.collection.setCurrentText(category)
        qtbot.waitUntil(lambda: not editor.viewmodel.content.busy, timeout=30000)
        assert shelf.results.count() == count
        assert all(not shelf.results.item(i).icon().isNull() for i in range(count))
        assert any(
            shelf.results.visualItemRect(shelf.results.item(i)).intersects(
                shelf.results.viewport().rect()
            )
            for i in range(count)
        )
        assert all(
            shelf.results.visualItemRect(shelf.results.item(i)).size()
            == shelf.results.visualItemRect(shelf.results.item(0)).size()
            for i in range(count)
        )


def test_creator_added_hair_and_gloves_preview_play_and_publish_retained_parts(editor, qtbot):
    """Exercise current option cards, isolated playback and the real publish operation."""
    from PySide6.QtCore import Qt

    from rigora.domain.creator_options import COMPONENT_CHOICES

    editor.show_character_wizard()
    wizard = editor.character_wizard
    baseline = editor.viewmodel.documents.project

    def ready():
        assert not wizard.model.error
        return wizard.model.ready == wizard.recipe and not wizard.model.busy

    try:
        qtbot.waitUntil(ready, timeout=30000)
        for category, selected, retained in (
            ("Hair", "bun", "locs"),
            ("Hands", "Open", "Wave"),
            ("Clothing", "shirt", "tee"),
        ):
            grid = wizard.grids[category]
            assert grid.count() == len(COMPONENT_CHOICES[category])
            items = {
                grid.item(i).data(Qt.ItemDataRole.UserRole): grid.item(i)
                for i in range(grid.count())
            }
            assert all(not item.icon().isNull() for item in items.values())
            wizard.choose_card(category, items[selected])
            items[retained].setCheckState(Qt.CheckState.Checked)
            qtbot.waitUntil(ready, timeout=30000)
            assert retained in wizard.recipe.alternatives[category]
        wizard.select_motion("Run")
        qtbot.mouseClick(wizard.play, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda: wizard.timer.isActive(), timeout=30000)
        qtbot.waitUntil(lambda: wizard.model.preview.animation.pose.frame > 0, timeout=5000)
        assert editor.viewmodel.documents.project is baseline
        wizard.play.setChecked(False)
        wizard.toggle_play(False)
        qtbot.waitUntil(ready, timeout=30000)
        wizard.create_character()
        qtbot.waitUntil(lambda: not wizard.isVisible(), timeout=30000)
        root = CharacterService(editor.viewmodel.documents).scene_objects()[0]
        groups = CharacterService(editor.viewmodel.documents).appearance_groups(root, "outfits")
        for category, expected in (("Hair", {"bun", "locs"}), ("Hands", {"Open", "Wave"})):
            group = next(g for g in groups if g["name"] == category)
            assert {v["name"] for v in group["variants"]} == expected
        editor.viewmodel.documents.undo()
        assert editor.viewmodel.documents.project == baseline
    finally:
        wizard.close()


def test_object_editor_empty_space_drop_adds_owned_bones_without_exiting(editor, qtbot):
    """A real empty-preview drop remains in Object Editor and targets its enclosing Object."""
    from rigora.application_services.object_templates import build_artwork
    from rigora.infrastructure.object_catalog import shapes

    vm = editor.viewmodel
    built = build_artwork(shapes()[0])
    mesh = ContentService(vm.documents).place(built.item, built.files, position=(400, 300))
    root = CharacterService(vm.documents).object_root(mesh)
    vm.changed.emit()
    editor.object_edit.enter(root.id)
    assert editor.object_edit.active
    entry = next(e for e in vm.content.entries if e.item.name == "Human · full body")
    editor.content_drop.drop(entry.key, QPointF(30, 30))
    qtbot.waitUntil(
        lambda: not vm.content.busy and bool(vm.documents.scene.skeletons), timeout=30000
    )
    assert not vm.content.error
    assert editor.object_edit.active
    rig = vm.documents.scene.skeletons[0]
    assert CharacterService(vm.documents).object_root(rig.id).id == root.id
    assert CharacterService(vm.documents).scene_objects() == (root.id,)
