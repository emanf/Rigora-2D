"""Real root-tree selection, master dragging and local Object Editor presentation."""

import pytest
from PySide6.QtCore import QPointF
from test_object_workspace_redesign_gui import panel_editor as panel_editor
from test_roots_soft_drag_gui import drag

from rigora.application_services.characters import CharacterService
from rigora.application_services.content_library import ContentService
from rigora.application_services.rigging import RigService
from rigora.infrastructure.effect_catalog import spring_presets

pytestmark = pytest.mark.gui


def test_rig_root_tree_control_moves_every_chain_and_has_one_undo(panel_editor, qtbot):
    window = panel_editor
    vm, doc, view = window.viewmodel, window.viewmodel.documents, window.viewport
    item = next(i for i in spring_presets() if i.name == "Long ponytail")
    rig_id = ContentService(doc).place(item, {}, position=(700, 450))
    vm.changed.emit()
    owner = CharacterService(doc).scene_objects()[0]
    window.object_edit.enter(owner)
    window.character_panel.show_page("bones")
    qtbot.wait(30)
    rig = next(r for r in doc.scene.skeletons if r.id == rig_id)
    root = next(b for b in rig.bones if b.extra.get("rig_root"))
    row = window.scene_workspace.items[root.id]
    assert row.text(0) == "Rig Root" and not row.isHidden()
    assert "master control" in row.toolTip(0)
    window.tree.setCurrentItem(row)
    window.scene_workspace.select_tree()
    assert vm.rig.selected == (root.id,)
    before, count = doc.project, len(doc.history.undo_stack)
    rest = RigService(doc).rest_pose().for_display()
    start = QPointF(*view.pose.nodes[root.id].world_matrix[4:]) * view.zoom + view.offset
    assert view.bone_at(start) == root.id
    assert view.bone_rotation_tip(start) is None
    zoom = view.zoom
    drag(view, start, start + QPointF(60, 25))
    assert not vm.rig.error
    assert len(doc.history.undo_stack) == count + 1
    after = RigService(doc).rest_pose().for_display()
    for bone in rig.bones:
        assert after.nodes[bone.id].world_matrix[4:] == pytest.approx(
            (
                rest.nodes[bone.id].world_matrix[4] + 60 / zoom,
                rest.nodes[bone.id].world_matrix[5] + 25 / zoom,
            )
        )
    vm.undo()
    assert doc.project == before


def test_object_editor_does_not_draw_a_scene_camera_rectangle(panel_editor, qtbot):
    window = panel_editor
    vm, doc, view = window.viewmodel, window.viewmodel.documents, window.viewport
    item = next(i for i in spring_presets() if i.name == "Long ponytail")
    ContentService(doc).place(item, {}, position=(700, 450))
    vm.changed.emit()
    window.object_edit.enter(CharacterService(doc).scene_objects()[0])
    window.rig_workspace.stop_springs()
    qtbot.wait(30)
    view.zoom = 0.2
    view.offset = QPointF(-500, -300)
    window.command_actions["fit"].trigger()
    point = QPointF(0, 0) * view.zoom + view.offset
    assert point.x() == pytest.approx(view.width() / 2)
    assert point.y() == pytest.approx(view.height() / 2)
    view.frame_visible = True
    visible = view.grab().toImage()
    view.frame_visible = False
    hidden = view.grab().toImage()
    assert visible == hidden


def test_legacy_drawing_origin_has_no_snap_or_pointer_target(panel_editor):
    """Old origin metadata remains readable without exposing an invisible control."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QMouseEvent
    from test_image_rigging_and_soft_drag import image_bytes
    from test_roots_soft_drag_gui import pointer

    from rigora.application_services.image_rigging import ImageRigService

    window = panel_editor
    vm, doc, view = window.viewmodel, window.viewmodel.documents, window.viewport
    images = ImageRigService(doc)
    mesh = images.import_image_bytes("Character.svg", image_bytes())
    actor = images.convert((mesh,))
    RigService(doc).move_origin(5000, 5000, actor, free=True)
    vm.changed.emit()
    window.object_edit.enter(actor)
    window.character_panel.show_page("bones")
    window.rig_workspace.stop_springs()
    assert all(not key.startswith("origin:") for key, _ in view._bone_joints())
    view.zoom = 0.5
    origin = QPointF(*RigService(doc).origin(actor))
    view.offset = QPointF(view.width() / 2, view.height() / 2) - origin * view.zoom
    baseline, count = doc.project, len(doc.history.undo_stack)
    start = QPointF(*RigService(doc).origin(actor)) * view.zoom + view.offset
    pointer(view, QMouseEvent.Type.MouseMove, start)
    assert view.cursor().shape() != Qt.CursorShape.SizeAllCursor
    drag(view, start, start + QPointF(20, 10))
    assert doc.project == baseline and len(doc.history.undo_stack) == count
