"""Scene placement pivots remain editable independently of reusable Object actions."""

import math

import pytest
from PySide6.QtCore import QPointF
from test_roots_soft_drag_gui import drag
from test_roots_soft_drag_gui import editor as editor

from rigora.application_services.character_creation import CharacterCreationService, build_character
from rigora.application_services.characters import CharacterService
from rigora.application_services.content_library import ContentService
from rigora.application_services.object_library import LINK, ObjectLibraryService
from rigora.domain.character_recipe import CharacterRecipe
from rigora.domain.geometry import transform_point
from rigora.presentation import transform_gizmo

pytestmark = pytest.mark.gui


@pytest.mark.parametrize("kind", ("character", "bare", "empty"))
def test_scene_object_pivot_drag_keeps_geometry_and_linked_copy_fixed_and_drives_rotation(
    current_pack, editor, kind
):
    """Drag scene pivots and rotation handles for creator art, a bare rig and an empty Object."""
    vm, viewport, work = editor.viewmodel, editor.viewport, editor.scene_workspace
    doc = vm.documents
    characters = CharacterService(doc)
    if kind == "character":
        root = CharacterCreationService(doc).create(build_character(CharacterRecipe()))
        assert any(c.extra.get("object_id") == root for c in doc.scene.clips)
    elif kind == "bare":
        pack, files = current_pack("rigs-effects")
        rig = ContentService(doc).place(
            next(i for i in pack.items if i.name == "Human · full body"), files
        )
        root = characters.object_root(rig).id
    else:
        root = characters.create_object(name="Empty")
    key = characters.record(root).extra[LINK]["definition"]
    peer = ObjectLibraryService(doc).place(key, (1200, 650))
    peer_record = characters.record(peer)
    vm.changed.emit()
    editor.navigate()
    work.select_entries((root,))
    viewport.zoom = 0.5
    node = doc.animation.pose.nodes[root]
    center = transform_point(node.world_matrix, node.local.pivot_x, node.local.pivot_y)
    viewport.offset = QPointF(350, 250) - QPointF(*center) * viewport.zoom
    pivot = work.pivot_point(work.transform_frame())
    assert pivot is not None, "The selected scene Object must expose its pivot handle."
    target = pivot + QPointF(63, 47)
    before, count = doc.project, len(doc.history.undo_stack)
    matrices = {k: n.world_matrix for k, n in doc.animation.pose.nodes.items()}
    drag(viewport, pivot, target)
    assert not vm.scene.error
    assert (work.pivot_point(work.transform_frame()) - target).manhattanLength() < 1e-6
    assert len(doc.history.undo_stack) == count + 1
    assert characters.record(peer) == peer_record
    assert doc.project.extra == before.extra
    for key, matrix in matrices.items():
        assert doc.animation.pose.nodes[key].world_matrix == pytest.approx(matrix)
    pivoted = doc.project
    vm.undo()
    assert doc.project == before
    vm.redo()
    assert doc.project == pivoted
    frame = work.transform_frame()
    start = transform_gizmo.handles(frame[0], frame[1])[8]
    vector, angle = start - target, math.radians(30)
    end = target + QPointF(
        vector.x() * math.cos(angle) - vector.y() * math.sin(angle),
        vector.x() * math.sin(angle) + vector.y() * math.cos(angle),
    )
    drag(viewport, start, end)
    assert not vm.scene.error
    assert (work.pivot_point(work.transform_frame()) - target).manhattanLength() < 1e-6
    assert doc.animation.pose.nodes[root].local.rotation == pytest.approx(30)
    assert characters.record(peer) == peer_record
