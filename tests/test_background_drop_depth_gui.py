"""Scene drops over full-frame artwork stay independent and respect editable Z priority."""

import pytest
from current_media_fixtures import background as make_background
from current_media_fixtures import ball_item
from PySide6.QtCore import QMimeData, QPointF, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication
from test_roots_soft_drag_gui import editor as editor

from rigora.application_services.characters import CharacterService
from rigora.application_services.meshes import MeshService
from rigora.application_services.object_library import ObjectLibraryService

pytestmark = pytest.mark.gui


@pytest.mark.parametrize("source", ("template", "imports", "objects"))
def test_ball_drop_over_selected_background_stays_in_scene_on_top_and_z_controls_order(
    editor, qtbot, source
):
    """Exercise all three asset shelves over a selected background, including real pick geometry."""
    vm, viewport = editor.viewmodel, editor.viewport
    doc = vm.documents
    background = make_background(doc)
    background_objects = doc.scene.objects
    item, media = ball_item()
    from rigora.application_services.content_library import LibraryEntry
    from rigora.domain.content import ContentPack

    pack = ContentPack(name="Drop fixture", author="Rigora tests", license="CC0-1.0", items=(item,))
    path = vm.preferences.path.parent / "drop-fixture.rigpack"
    from rigora.infrastructure.content_packs import write_pack

    write_pack(path, pack, media)
    vm.content.entries = (*vm.content.entries, LibraryEntry(path, pack, item))
    mime = QMimeData()
    if source == "template":
        qtbot.waitUntil(lambda: not vm.content.busy and bool(vm.content.entries), timeout=15000)
        entry = next(e for e in vm.content.entries if e.item.id == item.id)
        mime.setData("application/x-rigora-content", entry.key.encode())
    else:
        mesh_service = MeshService(doc)
        asset = mesh_service.register_image_bytes("Basketball.svg", media[item.payload["source"]])
        key = asset
        if source == "objects":
            mesh = mesh_service.instantiate_asset(asset, 1, 1)
            owner = str(mesh_service.mesh(mesh).object_id)
            library = ObjectLibraryService(doc)
            definition = library.save((owner,))[0]
            CharacterService(doc).delete_entries((owner,))
            key = "object:" + definition
        mime.setData("application/x-rigora-project-asset", key.encode())
        mime.setData("application/x-rigora-session", doc.session_id.encode())
    vm.changed.emit()
    qtbot.waitUntil(
        lambda: all(
            mesh.asset_id in viewport.artwork.images for mesh in doc.animation.pose.meshes.values()
        ),
        timeout=15000,
    )
    editor.navigate()
    editor.scene_workspace.select_entries((background,))
    vm.mesh.select_mesh(doc.scene.meshes[0].id)
    viewport.zoom, viewport.offset = 0.5, QPointF(20, 30)
    point = QPointF(330, 250)
    assert CharacterService(doc).object_root(editor.scene_workspace.pick(point)).id == background
    before = doc.project
    count = len(doc.history.undo_stack)
    old_ids = {o.id for o in doc.scene.objects}
    QApplication.sendEvent(
        viewport,
        QDragEnterEvent(
            point.toPoint(),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    qtbot.waitUntil(lambda: viewport.drop_pose is not None, timeout=15000)
    assert doc.project is before and not editor.object_edit.active
    ghost = viewport.drop_pose
    assert len(ghost.meshes) == 1
    QApplication.sendEvent(
        viewport,
        QDropEvent(
            point,
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    qtbot.waitUntil(lambda: doc.project is not before and not vm.content.busy, timeout=15000)
    qtbot.wait(10)
    assert not editor.object_edit.active and doc.animation_context is None
    assert not vm.mesh.active and not vm.rig.active
    assert len(doc.history.undo_stack) == count + 1
    assert tuple(o for o in doc.scene.objects if o.id in old_ids) == background_objects
    ball = next(o for o in doc.scene.objects if o.id not in old_ids)
    assert ball.parent_id is None and doc.animation.pose.render_order[-1] == ball.id
    assert ball.id in vm.scene.selected
    qtbot.waitUntil(lambda: len(viewport.artwork.images) >= len(doc.project.assets), timeout=15000)
    center = editor.scene_workspace.polygons()[ball.id].boundingRect().center()
    assert editor.scene_workspace.pick(center) == ball.id
    viewport.grab()
    assert viewport._artwork_layer is not None
    strip = editor.selection_properties
    assert strip.fields["depth"].value() == 0
    editor.scene_workspace.select_entries((background,))
    strip.fields["depth"].setValue(5)
    strip.fields["depth"].editingFinished.emit()
    assert CharacterService(doc).object_root(editor.scene_workspace.pick(center)).id == background
    editor.scene_workspace.select_entries((ball.id,))
    strip.fields["depth"].setValue(10)
    strip.fields["depth"].editingFinished.emit()
    assert editor.scene_workspace.pick(center) == ball.id
    vm.undo()
    assert doc.animation.pose.render_order[-1] != ball.id
    vm.redo()
    assert doc.animation.pose.render_order[-1] == ball.id
