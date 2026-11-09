"""Real template drops expose one Object with its complete editable rig and foot controls."""

import pytest
from PySide6.QtCore import QPointF
from test_roots_soft_drag_gui import editor as editor

from rigora.application_services.object_library import object_roots
from rigora.domain.geometry import transform_point

pytestmark = pytest.mark.gui


@pytest.mark.parametrize(
    "name", ("Dash · Runner", "Reed · Tall sketch", "Bolt · Stick robot", "Whisk · Stick cat")
)
def test_dropped_character_keeps_feet_and_track_controls_owned(editor, qtbot, name):
    """Use the async library drop, Object Editor and real Add Track picker offscreen."""
    vm, viewport, drop = editor.viewmodel, editor.viewport, editor.content_drop
    entry = next(e for e in vm.content.entries if e.item.name == name and e.item.kind == "scene")
    point = QPointF(360, 260)
    drop.move(entry.key, point)
    qtbot.waitUntil(lambda: viewport.drop_pose is not None, timeout=60000)
    drop.drop(entry.key, point)
    qtbot.waitUntil(lambda: not drop.placing, timeout=60000)
    doc = vm.documents
    assert doc.project.assets and not vm.scene.error
    qtbot.waitUntil(
        lambda: all(a.id in viewport.artwork.vectors for a in doc.project.assets), timeout=60000
    )
    assert all(viewport.artwork.vectors[a.id].isValid() for a in doc.project.assets)
    root = object_roots(doc.scene)[0]
    for rig in doc.scene.skeletons:
        bones = {b.id: b for b in rig.bones}
        for foot in rig.bones:
            if not (foot.name.startswith("foot.") or ".paw." in foot.name):
                continue
            parent = bones[foot.parent_id]
            pose = doc.animation.pose.for_display()
            assert pose.nodes[foot.id].world_matrix[4:] == pytest.approx(
                transform_point(pose.nodes[parent.id].world_matrix, parent.length, 0), abs=1
            )
    editor.object_edit.enter(root.id)
    editor.timeline.open_picker()
    picker = editor.timeline.picker
    assert picker.objects.topLevelItemCount() == 1
    assert picker.objects.topLevelItem(0) is picker.object_rows[root.id]
    for group in doc.scene.groups:
        if group.extra.get("studio_floor_plant"):
            row = picker.object_rows[group.id]
            assert row.parent() is picker.object_rows[root.id]
            assert "Standing foot control" in row.toolTip(0)
    for rig in doc.scene.skeletons:
        for bone in rig.bones:
            expected = picker.object_rows[bone.parent_id or root.id]
            assert picker.object_rows[bone.id].parent() is expected
