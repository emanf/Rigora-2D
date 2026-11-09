"""Shared artwork revisions retain geometry, source bytes, persistence and reversible history."""

import pytest

from rigora.application_services.artwork_editing import ArtworkEditingService
from rigora.application_services.documents import DocumentService
from rigora.application_services.meshes import MeshService
from rigora.domain.project import ProjectError


def test_replacement_preserves_meshes_and_undo_bytes_and_rejects_invalid_sources(tmp_path):
    """Replacement fits new dimensions into authored UVs; source revisions never alias in Undo."""
    doc = DocumentService()
    doc.new()
    mesh = MeshService(doc)
    original = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="40" height="60">'
        b'<rect width="40" height="60" fill="red"/></svg>'
    )
    updated = original.replace(b'width="40"', b'width="80"').replace(b"red", b"blue")
    key = mesh.register_image_bytes("art.svg", original)
    mesh.instantiate_asset(key)
    mesh.instantiate_asset(key)
    geometry = doc.scene
    service = ArtworkEditingService(doc)
    result = service.replace_bytes(key, updated)
    assert result["size_changed"]
    assert doc.scene == geometry
    assert doc.read_asset(key) == updated
    revision = doc.project
    with pytest.raises(ProjectError):
        service.replace_bytes(key, b"not artwork")
    assert doc.project is revision
    doc.undo()
    assert doc.read_asset(key) == original
    doc.redo()
    assert doc.read_asset(key) == updated
    doc.save(tmp_path / "updated.rigora")
    doc.open(doc.path)
    assert doc.read_asset(key) == updated
    assert doc.scene == geometry
