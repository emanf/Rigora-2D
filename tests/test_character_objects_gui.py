"""Real editor routes for whole-character selection and isolated object authoring."""

from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QMenu
from test_roots_soft_drag_gui import drag, pointer
from test_roots_soft_drag_gui import editor as root_editor

from rigora.application_services.appearance import AppearanceService
from rigora.application_services.characters import CharacterService
from rigora.application_services.image_rigging import ImageRigService
from rigora.domain.geometry import transform_point

pytestmark = pytest.mark.gui


@pytest.fixture
def editor(qtbot, tmp_path, monkeypatch):
    """Use the real editor while keeping unrelated library poster jobs outside gesture tests."""
    yield from root_editor.__wrapped__(qtbot, tmp_path, monkeypatch)


def scene_objects(window):
    """Create a multipart actor and an unrelated solid shape with real SVG geometry."""
    vm = window.viewmodel
    shapes = AppearanceService(vm.documents)
    first = shapes.create_shape("ellipse", 100, 100, 120, 180)
    second = shapes.create_shape("rectangle", 180, 160, 100, 100)
    other = shapes.create_shape("star", 500, 200, 150, 150)
    images = ImageRigService(vm.documents)
    actor = images.convert((first, second), "Test character")
    vm.changed.emit()
    return images, actor, first, second, other


def wait_for_artwork(window, qtbot):
    """Wait for real source decoding before exercising painted-pixel pointer selection."""
    qtbot.waitUntil(
        lambda: all(
            a.id in window.viewport.artwork.images
            for a in window.viewmodel.documents.project.assets
        ),
        timeout=10000,
    )


def test_preview_double_click_isolates_complete_actor_and_restores_view(editor, qtbot):
    images, actor, a, b, other = scene_objects(editor)
    vm, viewport = editor.viewmodel, editor.viewport
    wait_for_artwork(editor, qtbot)
    viewport.zoom, viewport.offset = 1, QPointF(20, 30)
    saved = viewport.zoom, QPointF(viewport.offset)
    editor.scene_workspace.select_entries((images.mesh(a).object_id,))
    assert set(vm.scene.selected) == set(CharacterService(vm.documents).character(actor).object_ids)
    before = vm.documents.project
    pointer(viewport, QMouseEvent.Type.MouseButtonDblClick, QPointF(170, 220))
    assert editor.object_edit.active
    assert not viewport.pose.nodes[images.mesh(other).object_id].visible
    assert viewport.pose.nodes[images.mesh(b).object_id].visible
    assert editor.scene_workspace.items[images.mesh(other).object_id].isHidden()
    editor.scene_workspace.select_entries((images.mesh(a).object_id,))
    assert vm.scene.selected == (images.mesh(a).object_id,)
    editor.object_edit.button.click()
    assert not editor.object_edit.active and viewport.isolated_ids is None
    assert set(vm.scene.selected) == set(CharacterService(vm.documents).character(actor).object_ids)
    assert (viewport.zoom, viewport.offset) == saved
    assert viewport.pose.nodes[images.mesh(other).object_id].visible
    assert vm.documents.project == before


def test_scene_double_click_and_both_context_menus_open_object_mode(editor, monkeypatch, qtbot):
    images, actor, a, _, _ = scene_objects(editor)
    wait_for_artwork(editor, qtbot)
    assert images.mesh(a).object_id not in editor.scene_workspace.items
    item = editor.scene_workspace.items[actor]
    editor.tree.itemDoubleClicked.emit(item, 0)
    assert editor.object_edit.active
    editor.object_edit.exit()
    menus = []

    class CapturedMenu(QMenu):
        """Capture native menu contents without opening a blocking platform event loop."""

        def exec(self, *args):
            menus.append(self)

    monkeypatch.setattr("PySide6.QtWidgets.QMenu", CapturedMenu)
    item = editor.scene_workspace.items[actor]
    editor.tree.scrollToItem(item)
    editor.scene_workspace.context_menu(editor.tree.visualItemRect(item).center())
    action = next(a for a in menus[-1].actions() if a.text() == "Edit object / character")
    action.trigger()
    assert editor.object_edit.active
    editor.object_edit.exit()
    editor.viewport.zoom, editor.viewport.offset = 1, QPointF()
    editor.scene_workspace.viewport_menu(QPointF(150, 200).toPoint())
    assert "Edit object / character" in [a.text() for a in menus[-1].actions()]


def test_object_edit_tabs_restore_camera_and_membership_after_changes(editor):
    images, _, a, _, other = scene_objects(editor)
    vm, viewport = editor.viewmodel, editor.viewport
    original_document = vm.documents
    viewport.zoom, viewport.offset = 0.7, QPointF(31, 42)
    editor.object_edit.enter(images.mesh(a).object_id)
    vm.scene.run(lambda s: s.rename(images.mesh(a).object_id, "Renamed"))
    assert editor.object_edit.active
    assert editor.scene_workspace.items[images.mesh(other).object_id].isHidden()
    vm.new_project()
    assert not editor.object_edit.active and viewport.isolated_ids is None
    editor.cycle_project(-1)
    assert vm.documents is original_document
    assert viewport.zoom == 0.7 and viewport.offset == QPointF(31, 42)


def test_full_scene_drag_moves_character_parts_and_bound_bones_once(editor, qtbot):
    images, _, a, b, other = scene_objects(editor)
    vm, viewport = editor.viewmodel, editor.viewport
    bone = images.draw_bone(a, (160, 180), (220, 180))
    vm.changed.emit()
    wait_for_artwork(editor, qtbot)
    viewport.zoom, viewport.offset = 1, QPointF()
    before = vm.documents.animation.pose
    count = len(vm.documents.history.undo_stack)
    drag(viewport, QPointF(135, 170), QPointF(155, 185))
    after = vm.documents.animation.pose
    for key in (images.mesh(a).object_id, images.mesh(b).object_id, bone):
        assert after.nodes[key].world_matrix[4:] == pytest.approx(
            (before.nodes[key].world_matrix[4] + 20, before.nodes[key].world_matrix[5] + 15)
        )
    assert after.nodes[images.mesh(other).object_id] == before.nodes[images.mesh(other).object_id]
    assert len(vm.documents.history.undo_stack) == count + 1


def test_object_mode_filters_other_channels_and_evaluates_part_animation(editor):
    images, actor, a, _, other = scene_objects(editor)
    vm = editor.viewmodel
    from rigora.application_services.animation_editing import AnimationEditingService

    animation = AnimationEditingService(vm.documents)
    own = images.mesh(a).object_id
    outside = images.mesh(other).object_id
    editor.object_edit.enter(own)
    x = vm.documents.animation.pose.nodes[own].local.x
    animation.key(own, "transform.x", 0, x)
    animation.key(own, "transform.x", 30, x + 50)
    animation.key(outside, "transform.rotation", 0, 0)
    vm.changed.emit()
    baseline = vm.documents.animation.pose.nodes[own].world_matrix[4]
    vm.playback.seek(30)
    assert vm.documents.animation.pose.nodes[own].world_matrix[4] == pytest.approx(baseline + 50)
    editor.object_edit.enter(own)
    assert vm.animation_editor.composer_owners
    editor.timeline.group_properties.setChecked(False)
    outside_row = next(
        editor.timeline.tracks.topLevelItem(i)
        for i in range(editor.timeline.tracks.topLevelItemCount())
        if editor.timeline.tracks.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole + 1) == outside
    )
    assert outside_row.isHidden()
    local_clip = vm.documents.selected_clip_id
    editor.object_edit.exit()
    assert editor.timeline.clips.findData(local_clip) == -1


def test_drawing_toggles_and_creates_editable_shape_with_one_undo(editor):
    vm, viewport = editor.viewmodel, editor.viewport
    viewport.zoom, viewport.offset = 1, QPointF()
    count = len(vm.documents.history.undo_stack)
    editor.command_actions["draw_shape"].trigger()
    assert editor.shape_workspace.active
    drag(viewport, QPointF(120, 100), QPointF(320, 240))
    assert len(vm.documents.history.undo_stack) == count + 1
    mesh = vm.documents.animation.pose.meshes[vm.mesh.mesh_id]
    assert mesh.appearance["shape"]["start"] == "ellipse"
    assert transform_point(
        vm.documents.animation.pose.nodes[mesh.object_id].world_matrix, 0, 0
    ) == (120, 100)
    editor.command_actions["navigate"].trigger()
    assert not editor.shape_workspace.active
    vm.undo()
    assert not vm.documents.project.scenes[0].objects


def test_motion_block_drag_trim_cancel_and_character_panel_render(editor, qtbot):
    images, actor, a, _, _ = scene_objects(editor)
    vm = editor.viewmodel
    service = CharacterService(vm.documents)
    clip = service.new_motion(actor, "Turn")
    from rigora.application_services.animation_editing import AnimationEditingService

    anim = AnimationEditingService(vm.documents)
    anim.key(images.mesh(a).object_id, "transform.rotation", 0, 0)
    anim.key(images.mesh(a).object_id, "transform.rotation", 30, 25)
    block = service.place_motion(actor, clip, 10, 2)
    vm.changed.emit()
    panel = editor.timeline.motion_blocks
    editor.timeline.pages.setCurrentWidget(panel)
    qtbot.wait(10)
    canvas = panel.canvas
    rect = canvas.rects()[0][1]
    count = len(vm.documents.history.undo_stack)
    drag(canvas, rect.center(), rect.center() + QPointF(35, 0))
    assert len(vm.documents.history.undo_stack) == count + 1
    assert panel.blocks[0]["start"] > 10
    before = vm.documents.project
    rect = canvas.rects()[0][1]
    pointer(canvas, QMouseEvent.Type.MouseButtonPress, rect.topRight() + QPointF(-3, 10))
    pointer(canvas, QMouseEvent.Type.MouseMove, rect.topRight() + QPointF(40, 10))
    from PySide6.QtTest import QTest

    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert vm.documents.project == before and panel.drag is None
    editor.scene_workspace.select_entries((images.mesh(a).object_id,))
    editor.object_edit.enter(images.mesh(a).object_id)
    editor.character_panel.show_page("motions")
    assert editor.character_panel.motion.findData(clip) >= 0
    assert not panel.blocks
    assert vm.documents.selected_clip_id == clip
    editor.object_edit.exit()
    assert panel.blocks[0]["id"] == block
    Path("build/character-objects-review").mkdir(parents=True, exist_ok=True)
    editor.grab().save("build/character-objects-review/object-edit.png")
