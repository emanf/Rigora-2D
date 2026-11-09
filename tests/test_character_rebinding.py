"""Authored vector parts can be rebound without canonical image-grid metadata."""

from rigora.application_services.bindings import BindingService
from rigora.application_services.character_creation import CharacterCreationService, build_character
from rigora.application_services.documents import DocumentService
from rigora.domain.character_recipe import CharacterRecipe


def test_creator_part_rebind_preserves_geometry_and_sources_and_is_undoable():
    doc = DocumentService()
    doc.new()
    CharacterCreationService(doc).create(build_character(CharacterRecipe(motions=())))
    head = next(o for o in doc.scene.objects if o.name == "Head")
    mesh = next(m for m in doc.scene.meshes if m.object_id == head.id)
    bone = next(b for r in doc.scene.skeletons for b in r.bones if b.name == "head")
    bindings = BindingService(doc)
    bindings.unbind((head.id,))
    before = doc.project
    mesh = bindings.mesh(mesh.id)
    vertices, triangles = mesh.vertices, mesh.triangles
    data = doc.read_asset(mesh.asset_id)
    count = len(doc.history.undo_stack)
    bindings.bind((head.id,), bone.id)
    changed = bindings.mesh(mesh.id)
    assert [(v.x, v.y, v.uv) for v in changed.vertices] == [(v.x, v.y, v.uv) for v in vertices]
    assert changed.triangles == triangles
    assert doc.read_asset(mesh.asset_id) == data
    assert any(d.owner_id == mesh.id and d.kind == "skinning" for d in doc.scene.deformers)
    assert len(doc.history.undo_stack) == count + 1
    doc.undo()
    assert doc.project == before
