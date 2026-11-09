"""Circle deformation keys and playback caps use the same visible frame cells."""

import pytest
from PySide6.QtCore import QPointF
from test_object_workspace_redesign_gui import panel_editor as panel_editor
from test_scene_deformation_timeline_gui import motion

from rigora.application_services.appearance import AppearanceService
from rigora.application_services.characters import CharacterService
from rigora.application_services.content_library import ContentService

pytestmark = pytest.mark.gui


def test_circle_ffd_keys_ruler_and_end_cap_share_frame_cells(panel_editor, qtbot):
    """The real shape/template workflow keeps key centers and the End boundary on the grid."""
    editor = panel_editor
    doc = editor.viewmodel.documents
    mesh = AppearanceService(doc).create_shape("ellipse", 100, 100, 140, 140)
    owner = CharacterService(doc).promote_object(str(CharacterService(doc).mesh(mesh).object_id))
    editor.viewmodel.changed.emit()
    editor.object_edit.enter(owner)
    ContentService(doc).place(motion(), {}, mesh_id=mesh)
    editor.viewmodel.changed.emit()
    canvas = editor.timeline.dope
    canvas.pixels = 32
    editor.timeline.expansion_changed()
    qtbot.wait(20)
    assert canvas.keys
    assert all(k.frame == round(k.frame) for k in canvas.source.values())
    for ref, key in canvas.source.items():
        point = canvas.mapFromScene(canvas.keys[ref].pos())
        assert canvas.frame_at(point) == key.frame
    boundary = canvas.mapFromScene(QPointF((canvas.end + 0.5) * canvas.pixels, 0)).x()
    assert canvas.ruler.end_handle().contains(QPointF(boundary - 1, 30))
    editor.grab().save("build/circle-ffd-frame-grid.png")
