"""Large editable scenes use bounded members without bloating discovery metadata."""

from rigora.application_services.content_library import ContentService, content_project
from rigora.application_services.documents import DocumentService
from rigora.infrastructure.content_packs import read_pack


def test_current_character_scene_exports_with_lightweight_metadata(current_pack, tmp_path):
    """A real action-rich Template remains portable without relaxing archive limits."""
    pack, sources = current_pack("templates")
    item = next(i for i in pack.items if i.name == "Bolt · Stick robot")
    doc = DocumentService()
    doc.new()
    service = ContentService(doc)
    service.place(item, sources)
    original, edits = doc.project, len(doc.history.undo_stack)
    path = tmp_path / "editable-scene.rigpack"
    service.export_own(path, "Editable scene", "Test", "Mixed; see source asset notices")
    assert doc.project is original and len(doc.history.undo_stack) == edits
    metadata, empty = read_pack(path, metadata_only=True)
    assert not empty and "project" not in metadata.items[0].payload
    exported, files = read_pack(path)
    scene_item = exported.items[0]
    assert scene_item.payload["project_source"] in files
    restored = content_project(scene_item, files)
    assert restored.scenes == (doc.scene,) and restored.assets == doc.project.assets
    assert restored.extra == doc.project.extra
    for asset in doc.project.assets:
        assert files[scene_item.payload["sources"][asset.id]] == doc.read_asset(asset.id)
