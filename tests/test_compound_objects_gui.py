"""Empty compound objects, editable artwork parts and object-owned blank animations."""

import pytest
from PIL import Image
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QMouseEvent
from PySide6.QtWidgets import QColorDialog
from test_character_objects_gui import wait_for_artwork
from test_roots_soft_drag_gui import drag, pointer
from test_roots_soft_drag_gui import editor as editor

from rigora.application_services.appearance import AppearanceService
from rigora.application_services.characters import CharacterService
from rigora.presentation.widgets.window_frame import CustomDialog

pytestmark = pytest.mark.gui


def empty_object(window):
    """Create an object through its menu action and enter it through the real hierarchy signal."""
    window.command_actions["new_object"].trigger()
    root = window.viewmodel.scene.selected[0]
    window.tree.itemDoubleClicked.emit(window.scene_workspace.items[root], 0)
    assert window.object_edit.active and window.object_edit.key == root
    return root


def test_empty_object_can_own_blank_animation_and_receive_drawn_parts(editor):
    """Create first, name an empty animation, then draw several parts without creating a rig."""
    vm, panel, viewport = editor.viewmodel, editor.character_panel, editor.viewport
    root = empty_object(editor)
    assert not vm.documents.project.scenes[0].meshes
    assert panel.name.text() == "Object" and panel.motion_owner() == root
    assert editor.object_edit.pages.isTabEnabled(3)
    panel.show_page("motions")
    panel.motion_name.setText("My idle")
    panel.new_motion()
    assert not panel.status.text()
    assert panel.motion_list.count() == 1 and panel.motion.currentText() == "My idle"
    assert not vm.animation_editor.service.timeline.tracks
    editor.shape_workspace.toggle(True)
    for kind, start, end in (
        ("ellipse", QPointF(350, 180), QPointF(430, 270)),
        ("rectangle", QPointF(460, 250), QPointF(550, 320)),
    ):
        editor.shape_workspace.kind.setCurrentText(kind)
        before = len(vm.documents.history.undo_stack)
        drag(viewport, start, end)
        assert len(vm.documents.history.undo_stack) == before + 1
        mesh = vm.mesh.mesh
        assert mesh and mesh.object_id in editor.object_edit.ids
        assert CharacterService(vm.documents).object_root(mesh.id).id == root
    assert len(vm.documents.project.scenes[0].meshes) == 2
    assert not vm.documents.project.scenes[0].characters
    assert not vm.documents.project.scenes[0].skeletons
    editor.navigate()
    parts = tuple(str(m.object_id) for m in vm.documents.project.scenes[0].meshes)
    editor.scene_workspace.select_entries((parts[0],))
    assert vm.scene.selected == (parts[0],)
    panel.show_page("parts")
    panel.add_folder(empty=True)
    assert not panel.status.text()
    assert any(g.parent_id == root for g in vm.documents.project.scenes[0].groups)
    editor.object_edit.exit()
    editor.scene_workspace.select_entries((parts[0],))
    assert vm.scene.selected == (root,)
    local = {o.id: o.transform for o in vm.documents.project.scenes[0].objects}
    strip = editor.selection_properties
    strip.fields["rotation"].setValue(35)
    strip.fields["rotation"].editingFinished.emit()
    assert not vm.scene.error
    assert vm.documents.animation.pose.nodes[root].local.rotation == pytest.approx(35)
    assert {o.id: o.transform for o in vm.documents.project.scenes[0].objects} == local


def test_native_parts_import_selected_svg_colors_and_raster_tint(
    editor, tmp_path, monkeypatch, qtbot
):
    """Mixed native imports stay in the object; color and tint edits affect only selected parts."""
    vm, panel = editor.viewmodel, editor.character_panel
    root = empty_object(editor)
    svg = tmp_path / "Two colors.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80">'
        '<rect width="80" height="80" fill="#123456"/>'
        '<circle cx="40" cy="40" r="20" fill="#ddaa22"/></svg>'
    )
    png = tmp_path / "Picture.png"
    Image.new("RGBA", (70, 60), (120, 180, 90, 255)).save(png)
    monkeypatch.setattr(
        "rigora.presentation.widgets.file_dialogs.choose_open_files",
        lambda *args: [str(svg), str(png)],
    )
    panel.import_images(False)
    qtbot.waitUntil(lambda: not vm.media.busy, timeout=15000)
    assert not vm.media.error
    service = CharacterService(vm.documents)
    meshes = service.meshes_for((root,))
    assert len(meshes) == 2 and not service.scene.characters and not service.scene.skeletons
    vector = next(m for m in service.scene.meshes if m.name.startswith("Two colors"))
    raster = next(m for m in service.scene.meshes if m.name.startswith("Picture"))
    editor.scene_workspace.select_entries((str(vector.object_id),))
    panel.show_page("skin")
    assert panel.scope() == (vector.id,) and panel.color_list.count() == 2

    def choose(dialog):
        """Exercise the embedded color picker's live preview and normal Apply path."""
        dialog.findChild(QColorDialog).setCurrentColor(QColor("#ff1122"))
        return 1

    monkeypatch.setattr(CustomDialog, "exec", choose)
    panel.paint_color()
    assert not panel.status.text()
    assert vm.documents.animation.pose.meshes[vector.id].appearance
    assert not vm.documents.animation.pose.meshes[raster.id].appearance
    editor.scene_workspace.select_entries((str(raster.object_id),))
    panel.show_page("skin")
    assert panel.scope() == (raster.id,) and panel.color_list.count() == 0
    panel.tint.setValue(45)
    panel.pick_tint()
    tint = vm.documents.animation.pose.meshes[raster.id].appearance["tint"]
    assert tint["amount"] == pytest.approx(0.45) and tint["r"] == 255
    assert service.object_root(vector.id).id == service.object_root(raster.id).id == root


def test_scene_whole_object_drag_and_object_editor_part_drag(editor, qtbot):
    """The same pointer gesture moves the whole composition in Scene and one part in Object Edit."""
    vm, viewport = editor.viewmodel, editor.viewport
    look = AppearanceService(vm.documents)
    a = look.create_shape("rectangle", 200, 180, 100, 100)
    b = look.create_shape("ellipse", 360, 180, 80, 100)
    service = CharacterService(vm.documents)
    root = service.create_object(tuple(str(look.mesh(k).object_id) for k in (a, b)))
    vm.changed.emit()
    wait_for_artwork(editor, qtbot)
    viewport.zoom, viewport.offset = 1, QPointF(20, 30)
    editor.scene_workspace.select_entries((str(look.mesh(a).object_id),))
    assert vm.scene.selected == (root,)
    before = vm.documents.animation.pose
    drag(viewport, QPointF(250, 240), QPointF(285, 260))
    assert not vm.scene.error
    for mesh in (look.mesh(a), look.mesh(b)):
        old = before.nodes[mesh.object_id].world_matrix
        new = vm.documents.animation.pose.nodes[mesh.object_id].world_matrix
        assert new[4:] == pytest.approx((old[4] + 35, old[5] + 20))
    editor.tree.itemDoubleClicked.emit(editor.scene_workspace.items[root], 0)
    viewport.zoom, viewport.offset = 1, QPointF(20, 30)
    editor.scene_workspace.select_entries((str(look.mesh(a).object_id),))
    before = vm.documents.animation.pose
    drag(viewport, QPointF(285, 260), QPointF(305, 280))
    assert not vm.scene.error
    other = str(look.mesh(b).object_id)
    assert vm.documents.animation.pose.nodes[other].world_matrix == before.nodes[other].world_matrix
    moved = str(look.mesh(a).object_id)
    assert vm.documents.animation.pose.nodes[moved].world_matrix[4:] == pytest.approx(
        tuple(value + 20 for value in before.nodes[moved].world_matrix[4:])
    )


def test_empty_viewport_marker_moves_and_opens_and_single_svg_can_grow(editor):
    """Empty objects are pickable; an existing single image can gain a blank action and parts."""
    vm, viewport = editor.viewmodel, editor.viewport
    editor.command_actions["new_object"].trigger()
    root = vm.scene.selected[0]
    viewport.zoom = 1
    point = QPointF(viewport.width() / 2, viewport.height() / 2)
    viewport.offset = point - QPointF(*vm.documents.animation.pose.nodes[root].world_matrix[4:])
    before = vm.documents.animation.pose.nodes[root].world_matrix[4:]
    drag(viewport, point + QPointF(11, 11), point + QPointF(46, 31))
    assert vm.documents.animation.pose.nodes[root].world_matrix[4:] == pytest.approx(
        (before[0] + 35, before[1] + 20)
    )
    pointer(viewport, QMouseEvent.Type.MouseButtonDblClick, point + QPointF(35, 20))
    assert editor.object_edit.active and editor.object_edit.key == root
    editor.object_edit.exit()
    look = AppearanceService(vm.documents)
    first = look.create_shape("rectangle", 200, 200, 100, 100)
    vm.changed.emit()
    editor.object_edit.enter(str(look.mesh(first).object_id))
    panel = editor.character_panel
    panel.show_page("motions")
    assert editor.object_edit.pages.isTabEnabled(3)
    panel.motion_name.setText("Later")
    panel.new_motion()
    assert not panel.status.text() and panel.motion_list.count() == 1
    editor.shape_workspace.toggle(True)
    drag(viewport, QPointF(250, 180), QPointF(320, 250))
    owner = CharacterService(vm.documents).object_root(first)
    assert owner and editor.object_edit.key == owner.id
    assert len(CharacterService(vm.documents).meshes_for((owner.id,))) == 2
    assert len(CharacterService(vm.documents).motions(owner.id)) == 1
    assert not vm.documents.project.scenes[0].characters
