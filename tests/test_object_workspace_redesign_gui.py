"""Dedicated object pages, character containers and direct native multi-part import."""

from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, Qt
from test_character_objects_gui import editor as object_editor
from test_character_objects_gui import scene_objects
from test_object_scene_actions_gui import readable_offscreen_fonts as readable_offscreen_fonts
from test_roots_soft_drag_gui import drag

from rigora.application_services.characters import CharacterService
from rigora.application_services.content_library import ContentService
from rigora.application_services.rigging import RigService
from rigora.domain.character_recipe import MOTION_CHOICES

pytestmark = pytest.mark.gui


@pytest.fixture
def editor(qtbot, tmp_path, monkeypatch):
    """Exercise real editor widgets with unrelated library poster jobs isolated."""
    yield from object_editor.__wrapped__(qtbot, tmp_path, monkeypatch)


@pytest.mark.parametrize("assets_visible", (True, False))
def test_dedicated_pages_restore_docks_and_reuse_one_layers_tree(panel_editor, assets_visible):
    """Repeated entry owns one tree, and all four tasks stay in the studio workspace."""
    editor = panel_editor
    _, actor, *_ = scene_objects(editor)
    editor.docks["assets"].setVisible(assets_visible)
    saved = {k: editor.docks[k].isHidden() for k in ("hierarchy", "inspector", "assets")}
    tabs = [editor.project_tabs.tabData(i) for i in range(editor.project_tabs.count())]
    assert "welcome" not in tabs and len(tabs) > 0
    panel = editor.character_panel
    for _ in range(2):
        editor.filter.setText("Test character")
        editor.object_edit.enter(actor)
        assert not editor.filter.text()
        assert editor.object_edit.context.isVisible() and panel.isVisible()
        assert editor.hierarchy_content.parent() is panel.structure_host
        assert editor.docks["hierarchy"].isHidden()
        assert editor.docks["inspector"].isHidden() == saved["inspector"]
        assert editor.docks["assets"].isHidden() == saved["assets"]
        assert editor.tab_row.isHidden()
        editor.refresh_document()
        assert editor.tab_row.isHidden()
        assert editor.inspector.indexOf(panel) == -1
        assert editor.tree.rootIndex() == editor.tree.indexFromItem(
            editor.scene_workspace.items[actor]
        )
        for index, page in enumerate(("tree", "skin", "clothing", "motions")):
            panel.show_page(page)
            assert editor.object_edit.pages.currentIndex() == index
            assert panel.structure_host.isVisible()
        editor.object_edit.exit()
        assert not editor.tab_row.isHidden()
        assert [editor.project_tabs.tabData(i) for i in range(editor.project_tabs.count())] == tabs
        assert not panel.isVisible() and not editor.object_edit.context.isVisible()
        assert editor.docks["hierarchy"].widget() is editor.hierarchy_content
        assert {k: editor.docks[k].isHidden() for k in saved} == saved
        assert not editor.tree.rootIndex().isValid()
        assert editor.filter.text() == "Test character"


@pytest.fixture
def panel_editor(qtbot, tmp_path, monkeypatch):
    """Use the real workspace without generating unrelated Template artwork for panel checks."""
    from rigora.application_services.content_library import ContentLibrary

    monkeypatch.setattr(ContentLibrary, "entries", lambda self: ())
    yield from object_editor.__wrapped__(qtbot, tmp_path, monkeypatch)


@pytest.mark.parametrize("page", ("parts", "skin"))
@pytest.mark.parametrize("hidden", (False, True))
def test_object_bone_drawing_renders_above_artwork_on_all_pages(editor, monkeypatch, page, hidden):
    """Real object entry and bone gestures keep new joints visible over opaque vector layers."""
    images, actor, _, _, other = scene_objects(editor)
    vm, viewport = editor.viewmodel, editor.viewport
    editor.tree.itemDoubleClicked.emit(editor.scene_workspace.items[actor], 0)
    assert editor.object_edit.active
    editor.character_panel.show_page(page)
    if hidden:
        editor.command_actions["bone_overlay"].trigger()
    editor.show_bone_editor()
    editor.bone_editor.bone_buttons["Add bone"].click()
    viewport.zoom, viewport.offset = 1, QPointF(20, 30)
    drag(viewport, QPointF(170, 180), QPointF(210, 250))
    assert not vm.rig.error
    bone = vm.rig.selected[0]
    assert bone in editor.object_edit.ids and viewport.pose.nodes[bone].visible
    assert not viewport.pose.nodes[images.mesh(other).object_id].visible
    painted = viewport.grab().toImage()
    with monkeypatch.context() as patch:
        patch.setattr(viewport, "_draw_needle", lambda *args, **kwargs: None)
        without_bone = viewport.grab().toImage()
    assert painted != without_bone
    assert viewport.show_bones is not hidden
    editor.bone_editor.close()
    assert viewport.rig_tool == "select" and viewport.show_bones is not hidden


def test_character_scene_group_delete_and_undo_preserve_part_folders(editor):
    """A scene folder wraps a whole character without flattening its editable layer tree."""
    images, actor, first, _, other = scene_objects(editor)
    vm = editor.viewmodel
    service = CharacterService(vm.documents)
    original_actor = service.character(actor)
    parts_folder = service.part_group(actor, original_actor.object_ids)
    bone = images.draw_bone(first, (160, 180), (200, 180))
    vm.changed.emit()
    editor.object_edit.exit()
    editor.scene_workspace.select_entries((actor,))
    editor.scene_workspace.group_selection()
    assert not vm.scene.error
    scene_folder = next(g for g in service.scene.groups if g.extra.get("scene_folder"))
    assert service.record(parts_folder).parent_id == scene_folder.id
    assert all(service.record(k).parent_id == parts_folder for k in original_actor.object_ids)
    assert (
        editor.scene_workspace.items[actor].parent().data(0, Qt.ItemDataRole.UserRole)
        == scene_folder.id
    )
    before, count = vm.documents.project, len(vm.documents.history.undo_stack)
    editor.scene_workspace.select_entries((scene_folder.id,))
    editor.scene_workspace.delete_selection()
    assert not vm.scene.error
    assert not service.scene.characters and not service.scene.skeletons
    assert service.scene.meshes == (images.mesh(other),)
    assert parts_folder not in service.records() and bone not in service.records()
    assert len(vm.documents.history.undo_stack) == count + 1
    vm.undo()
    assert vm.documents.project == before


def test_character_flags_preserve_clothing_and_owned_folder_lock(editor):
    """Container visibility never resets part visibility, while container locking protects bones."""
    images, actor, a, b, _ = scene_objects(editor)
    vm = editor.viewmodel
    service = CharacterService(vm.documents)
    bone = images.draw_bone(a, (160, 180), (200, 180))
    folder = service.part_group(actor, ())
    service.flags((str(images.mesh(b).object_id),), visible=False)
    service.flags((actor,), visible=False, locked=True)
    vm.changed.emit()
    pose = vm.documents.animation.pose
    assert all(not pose.nodes[k].visible for k in service.character(actor).object_ids)
    assert not pose.nodes[bone].visible
    assert service.locked(bone) and service.locked(folder)
    service.flags((actor,), visible=True, locked=False)
    vm.changed.emit()
    pose = vm.documents.animation.pose
    assert pose.nodes[str(images.mesh(a).object_id)].visible
    assert not pose.nodes[str(images.mesh(b).object_id)].visible
    assert pose.nodes[bone].visible and not service.locked(bone)


def test_object_folders_ignore_bone_picks_and_anchor_part_can_be_deleted(editor):
    """Folders ignore bone picks, and deleting an anchor keeps the character editor open."""
    images, actor, a, _, _ = scene_objects(editor)
    vm = editor.viewmodel
    bone = images.draw_bone(a, (160, 180), (200, 180))
    vm.changed.emit()
    vm.rig.select(bone)
    editor.show_bone_editor()
    assert editor.object_edit.active and vm.rig.selected == (bone,)
    editor.bone_editor.close()
    editor.scene_workspace.select_entries((bone,))
    editor.character_panel.add_folder()
    assert not editor.character_panel.status.text()
    service = CharacterService(vm.documents)
    folder = service.character(actor).extra["part_groups"][0]
    assert folder in editor.object_edit.ids and not editor.scene_workspace.items[folder].isHidden()
    root = RigService(vm.documents).origin(actor)
    editor.scene_workspace.select_entries((str(images.mesh(a).object_id),))
    editor.scene_workspace.delete_selection()
    assert not vm.scene.error and editor.object_edit.active
    assert editor.object_edit.key == actor
    assert RigService(vm.documents).origin(actor) == pytest.approx(root)


def test_switching_to_solid_resets_actor_target_and_source_drops_adopt_once(editor):
    """Editing a solid cannot accidentally recolor the previous character; drops follow focus."""
    images, actor, a, _, other = scene_objects(editor)
    vm, panel = editor.viewmodel, editor.character_panel
    editor.scene_workspace.select_entries((actor,))
    editor.object_edit.enter(actor)
    panel.show_page("skin")
    editor.object_edit.exit()
    editor.object_edit.enter(str(images.mesh(other).object_id))
    assert panel.actor.currentData() is None and panel.scope() == (other,)
    assert panel.convert_button.isVisible() is False  # Only the Parts page shows conversion.
    panel.show_page("parts")
    assert panel.convert_button.isVisible()
    assert vm.scene.selected == (str(images.mesh(other).object_id),)
    editor.object_edit.exit()
    editor.object_edit.enter(actor)
    before = len(CharacterService(vm.documents).character(actor).mesh_ids)
    count = len(vm.documents.history.undo_stack)
    editor.drop_project_asset(images.mesh(a).asset_id, vm.documents.session_id, QPointF())
    assert len(CharacterService(vm.documents).character(actor).mesh_ids) == before + 1
    assert len(vm.documents.history.undo_stack) == count + 1


def test_native_multi_import_directly_adopts_parts_and_clothing(
    editor, tmp_path, monkeypatch, qtbot
):
    """Native picks adopt asynchronously into the edited actor with one Undo per complete import."""
    _, actor, *_ = scene_objects(editor)
    vm = editor.viewmodel
    editor.object_edit.enter(actor)
    paths = []
    for index in range(2):
        source = tmp_path / f"Part {index}.svg"
        source.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="60">'
            '<rect width="40" height="60" fill="#884422"/></svg>'
        )
        paths.append(str(source))
    monkeypatch.setattr(
        "rigora.presentation.widgets.file_dialogs.choose_open_files", lambda *args: paths
    )
    count = len(vm.documents.history.undo_stack)
    editor.character_panel.import_images(False)
    qtbot.waitUntil(lambda: not vm.media.busy, timeout=15000)
    assert not vm.media.error
    service = CharacterService(vm.documents)
    assert len(service.character(actor).mesh_ids) == 4
    assert len(vm.documents.history.undo_stack) == count + 1
    vm.undo()
    assert len(service.character(actor).mesh_ids) == 2
    editor.character_panel.show_page("clothing")
    editor.character_panel.outfit_name.setText("Autumn outfit")
    count = len(vm.documents.history.undo_stack)
    editor.character_panel.import_images(True)
    qtbot.waitUntil(lambda: not vm.media.busy, timeout=15000)
    assert not vm.media.error
    group = service.character(actor).extra["outfits"][0]
    assert group["variants"][0]["name"] == "Autumn outfit"
    assert len(group["variants"][0]["meshes"]) == 2
    assert len(service.character(actor).mesh_ids) == 4
    assert len(vm.documents.history.undo_stack) == count + 1


def test_real_character_all_four_tasks_are_renderable(current_pack, editor, qtbot):
    """Review actual separated vector artwork and all workspace pages, including ready actions."""
    pack, files = current_pack("templates")
    ContentService(editor.viewmodel.documents).apply(pack.items[4], files)
    editor.viewmodel.changed.emit()
    asset_count = len(editor.viewmodel.documents.project.assets)
    qtbot.waitUntil(
        lambda: len(editor.viewport.artwork.images) >= asset_count,
        timeout=15000,
    )
    actor = editor.viewmodel.documents.project.scenes[0].characters[0]
    editor.object_edit.enter(actor.id)
    panel = editor.character_panel
    output = Path("build/scene-object-redesign")
    output.mkdir(parents=True, exist_ok=True)
    for page in ("tree", "skin", "clothing", "motions"):
        panel.show_page(page)
        qtbot.wait(100)
        assert (panel.structure_host if page == "tree" else panel.tabs.currentWidget()).isVisible()
        assert editor.grab().save(str(output / f"{page}.png"))
    assert panel.motion_list.count() == len(MOTION_CHOICES)
    panel.motion_list.setCurrentRow(2)
    assert panel.motion.currentIndex() == 2
    panel.show_page("skin")
    panel.all_parts.setChecked(True)
    assert panel.color_list.count() >= 6
    assert panel.color_list.item(0).data(Qt.ItemDataRole.UserRole)
    editor.object_edit.exit()
    qtbot.wait(100)
    assert editor.grab().save(str(output / "scene.png"))
