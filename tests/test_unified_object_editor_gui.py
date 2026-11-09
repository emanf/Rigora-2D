"""Unified object hierarchy, immediate root controls and task-specific detail panels."""

import pytest
from PySide6.QtCore import QPointF, Qt
from test_object_workspace_redesign_gui import panel_editor as panel_editor
from test_roots_soft_drag_gui import drag

from rigora.application_services.appearance import AppearanceService
from rigora.application_services.characters import CharacterService
from rigora.application_services.rigging import RigService
from rigora.domain.project import ProjectError

pytestmark = pytest.mark.gui


def test_add_bone_prepares_visible_root_before_any_segment(panel_editor, qtbot):
    window = panel_editor
    vm, doc, view = window.viewmodel, window.viewmodel.documents, window.viewport
    owner = CharacterService(doc).create_object()
    vm.changed.emit()
    window.object_edit.enter(owner)
    window.character_panel.add_bone_button.click()
    qtbot.wait(20)
    assert not vm.rig.error
    rig = next(r for r in doc.scene.skeletons if r.extra.get("object_id") == owner)
    assert len(rig.bones) == 1
    root = rig.bones[0]
    row = window.scene_workspace.items[root.id]
    assert row.parent() is window.scene_workspace.items[rig.id]
    assert row.parent().isExpanded() and not window.tree.visualItemRect(row).isEmpty()
    assert root.id in view.pose.nodes
    window.navigate()
    vm.rig.select(root.id)
    before = RigService(doc).rest_pose().nodes[root.id].world_matrix[4:]
    start = QPointF(*before) * view.zoom + view.offset
    drag(view, start, start + QPointF(30, 20))
    after = RigService(doc).rest_pose().nodes[root.id].world_matrix[4:]
    assert after == pytest.approx((before[0] + 30 / view.zoom, before[1] + 20 / view.zoom))
    with pytest.raises(ProjectError, match="protected"):
        RigService(doc).delete(root.id)


def test_four_tasks_share_one_tree_and_assets_do_not_change_editor(panel_editor):
    window = panel_editor
    vm, doc, panel = window.viewmodel, window.viewmodel.documents, window.character_panel
    first = AppearanceService(doc).create_shape("ellipse", 100, 100, 100, 180)
    owner = CharacterService(doc).create_object((str(CharacterService(doc).mesh(first).object_id),))
    vm.changed.emit()
    window.object_edit.enter(owner)
    window.draw_bone()
    rig = doc.scene.skeletons[0]
    root = rig.bones[0]
    assert [
        window.object_edit.pages.tabText(i) for i in range(window.object_edit.pages.count())
    ] == ["Object Tree", "Skin", "Clothing", "Animations"]
    assert first in window.object_edit.ids and root.id in window.object_edit.ids
    root_row = window.scene_workspace.items[root.id]
    root_row.setExpanded(True)
    window.tree.setCurrentItem(root_row)
    for page in ("tree", "skin", "clothing", "animations", "tree"):
        panel.show_page(page)
        assert panel.structure_host.isVisible() and window.tree.isVisible()
        assert window.hierarchy_content.parent() is panel.structure_host
        assert window.scene_workspace.items[root.id].isExpanded()
    baseline = doc.project
    window.docks["assets"].hide()
    panel.assets_button.click()
    assert window.docks["assets"].isVisible() and window.object_edit.key == owner
    assert doc.project is baseline
    panel.binding_toggle.click()
    assert panel.binding_controls.isVisible()
    panel.show_page("skin")
    assert not panel.material_toggle.isChecked()
    panel.material_toggle.click()
    assert panel.border.isVisible()
    assert panel.tabs.currentIndex() == 1


def test_bone_mode_root_pointer_drag_preserves_child_world_pose(panel_editor):
    window = panel_editor
    vm, doc, view = window.viewmodel, window.viewmodel.documents, window.viewport
    owner = CharacterService(doc).create_object()
    vm.changed.emit()
    window.object_edit.enter(owner)
    window.draw_bone()
    root = doc.scene.skeletons[0].bones[0]
    child = RigService(doc).create_bone((20, 30), (80, 30))
    vm.changed.emit()
    window.navigate()
    vm.rig.select(root.id)
    window.bone_mode_buttons["selection_move"].click()
    window.rig_workspace.stop_springs()
    before = RigService(doc).rest_pose()
    start = QPointF(*before.nodes[root.id].world_matrix[4:]) * view.zoom + view.offset
    drag(view, start, start + QPointF(40, 20), Qt.KeyboardModifier.AltModifier)
    assert not vm.rig.error
    after = RigService(doc).rest_pose()
    assert after.nodes[root.id].world_matrix != before.nodes[root.id].world_matrix
    assert after.nodes[child].world_matrix == pytest.approx(before.nodes[child].world_matrix)


@pytest.mark.parametrize("converted", (False, True))
def test_image_root_is_visible_and_follows_scene_object_before_binding(panel_editor, converted):
    """Fresh and converted images expose a centered master that follows their scene placement."""
    from test_image_rigging_and_soft_drag import image_bytes

    from rigora.application_services.image_rigging import ImageRigService
    from rigora.application_services.scene_editing import SceneEditingService
    from rigora.domain.geometry import transform_point

    window = panel_editor
    vm, doc, view = window.viewmodel, window.viewmodel.documents, window.viewport
    images = ImageRigService(doc)
    mesh = images.import_image_bytes("Art.svg", image_bytes())
    object_id = str(images.mesh(mesh).object_id)
    owner = images.convert((mesh,)) if converted else object_id
    vm.changed.emit()
    window.object_edit.enter(owner)
    window.draw_bone()
    assert not vm.rig.error
    assert len(doc.scene.skeletons) == 1
    root = doc.scene.skeletons[0].bones[0]
    pose = doc.animation.pose.for_display()
    point = QPointF(*pose.nodes[root.id].world_matrix[4:]) * view.zoom + view.offset
    assert view.rect().contains(point.toPoint())
    expected = transform_point(pose.nodes[object_id].world_matrix, 160, 240)
    assert pose.nodes[root.id].world_matrix[4:] == pytest.approx(expected)
    drag(view, point + QPointF(25, 25), point + QPointF(75, 25), Qt.KeyboardModifier.AltModifier)
    assert not vm.rig.error
    assert len(doc.scene.skeletons) == 1
    assert len(doc.scene.skeletons[0].bones) == 2
    assert doc.scene.skeletons[0].bones[0].id == root.id
    window.object_edit.exit()
    before = doc.animation.pose.for_display().nodes[root.id].world_matrix[4:]
    scene = SceneEditingService(doc)
    scene.transform((object_id,), dx=40)
    after = doc.animation.pose.for_display().nodes[root.id].world_matrix[4:]
    assert after == pytest.approx((before[0] + 40, before[1]))
