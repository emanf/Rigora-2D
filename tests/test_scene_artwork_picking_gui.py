"""Scene and Object Editor pointers select painted artwork through transparent front layers."""

import io
from dataclasses import replace

import pytest
from PySide6.QtCore import QPointF, Qt
from test_roots_soft_drag_gui import editor as editor

from rigora.application_services.characters import CharacterService
from rigora.application_services.meshes import MeshService
from rigora.domain.entities import Transform

pytestmark = pytest.mark.gui

BACK = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
    b'<rect width="100" height="100" fill="red"/></svg>'
)
FRONT = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
    b'<path fill="white" fill-rule="evenodd" '
    b'd="M10 10H90V90H10Z M35 35H65V65H35Z"/></svg>'
)


def layers(editor, qtbot, raster=False):
    """Place two overlapping rectangular meshes whose top artwork has a real transparent hole."""
    from PIL import Image, ImageDraw

    vm = editor.viewmodel
    service = MeshService(vm.documents)
    front = FRONT
    if raster:
        image = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
        brush = ImageDraw.Draw(image)
        brush.rectangle((10, 10, 89, 89), fill="white")
        brush.rectangle((35, 35, 64, 64), fill=(0, 0, 0, 0))
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        front = stream.getvalue()
    assets = [
        service.register_image_bytes("Back.svg", BACK),
        service.register_image_bytes("Front.png" if raster else "Front.svg", front),
    ]
    meshes = [service.instantiate_asset(key, 1, 1) for key in assets]
    keys = tuple(str(service.mesh(key).object_id) for key in meshes)
    service.commit(
        "Position picking fixtures",
        objects=tuple(
            replace(obj, transform=Transform(x=100, y=100)) if obj.id in keys else obj
            for obj in service.scene.objects
        ),
    )
    vm.changed.emit()
    qtbot.waitUntil(
        lambda: all(key in editor.viewport.artwork.images for key in assets), timeout=10000
    )
    editor.navigate()
    editor.viewport.zoom, editor.viewport.offset = 1, QPointF(30, 30)
    return keys, meshes


@pytest.mark.parametrize("raster", [False, True])
@pytest.mark.parametrize("object_edit", [False, True])
def test_actual_clicks_pass_through_transparent_front_art_in_scene_and_object_editor(
    editor, qtbot, raster, object_edit
):
    """Painted pixels select the appropriate whole object or editable part."""
    (back, front), meshes = layers(editor, qtbot, raster)
    vm, viewport, workspace = editor.viewmodel, editor.viewport, editor.scene_workspace
    characters = CharacterService(vm.documents)
    if object_edit:
        owner = characters.create_object((back, front), "Layered object")
        vm.changed.emit()
        editor.object_edit.enter(owner)
    else:
        characters.create_object((back,), "Back object")
        characters.create_object((front,), "Front object")
        vm.changed.emit()
    viewport.zoom, viewport.offset = 1, QPointF(30, 30)
    filled = viewport.offset + QPointF(123, 144)
    hole = viewport.offset + QPointF(139, 156)
    margin = viewport.offset + QPointF(103, 106)
    assert workspace.pick(filled) == front
    assert workspace.pick(hole) == back
    assert workspace.pick(margin) == back
    assert editor.content_drop.targets(hole)[1] == meshes[0]
    for point, key in ((filled, front), (hole, back)):
        qtbot.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=point.toPoint())
        expected = key if object_edit else characters.object_root(key).id
        assert vm.scene.selected == (expected,)
    assert editor.object_edit.active == object_edit


def test_hidden_transparent_and_locked_front_layers_do_not_steal_selection(editor, qtbot):
    """Evaluated visibility/opacity and inherited editing locks remain respected."""
    (back, front), _ = layers(editor, qtbot)
    service = MeshService(editor.viewmodel.documents)
    point = editor.viewport.offset + QPointF(123, 144)
    for name, value in (("opacity", 0), ("visible", False), ("locked", True)):
        service.commit(
            "Set front pick state",
            objects=tuple(
                (
                    replace(obj, visible=False)
                    if name == "visible"
                    else replace(obj, extra={**obj.extra, name: value})
                )
                if obj.id == front
                else obj
                for obj in service.scene.objects
            ),
        )
        editor.viewmodel.changed.emit()
        assert editor.scene_workspace.pick(point) == back
        editor.viewmodel.undo()
    assert editor.scene_workspace.pick(point) == front


def test_one_object_with_multiple_meshes_keeps_all_artwork_pickable(editor, qtbot):
    """An object's last mesh cannot replace earlier mesh bounds in the picking broad phase."""
    (back, front), meshes = layers(editor, qtbot)
    service = MeshService(editor.viewmodel.documents)
    second = service.mesh(meshes[1])
    service.commit(
        "Share mesh owner",
        meshes=tuple(
            replace(
                mesh, object_id=back, vertices=tuple(replace(v, x=v.x + 150) for v in mesh.vertices)
            )
            if mesh.id == second.id
            else mesh
            for mesh in service.scene.meshes
        ),
    )
    editor.viewmodel.changed.emit()
    first = editor.viewport.offset + QPointF(123, 144)
    second_point = editor.viewport.offset + QPointF(273, 144)
    assert editor.scene_workspace.pick(first) == back
    assert editor.scene_workspace.pick(second_point) == back
    assert editor.scene_workspace.mesh_at(second_point) == meshes[1]
