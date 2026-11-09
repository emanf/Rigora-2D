"""Portable image source import and topology commands work without a Qt dependency."""

from dataclasses import replace
from pathlib import Path

import pytest

from rigora.application_services.documents import DocumentService
from rigora.application_services.meshes import MeshService
from rigora.application_services.rigging import RigService
from rigora.domain.mesh_geometry import validate_embedding
from rigora.domain.project import ProjectError
from rigora.infrastructure.artwork import inspect_artwork

SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="80">'
    b'<rect width="100" height="80" fill="#ddd"/></svg>'
)


def test_png_import_example_has_connected_skinned_bones_and_roundtrips(tmp_path):
    example = Path(__file__).resolve().parents[1] / "examples/image-import-example.rigora"
    document = DocumentService()
    document.open(example)
    scene = document.project.scenes[0]
    mesh = scene.meshes[0]
    root, child = scene.skeletons[0].bones
    assert child.parent_id == root.id and child.transform.x == pytest.approx(root.length)
    data = document.read_asset(mesh.asset_id)
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    original = document.animation.pose.meshes[mesh.id].positions
    assert not document.animation.pose.warnings
    RigService(document).update(child.id, transform=replace(child.transform, rotation=25))
    assert document.animation.pose.meshes[mesh.id].positions != original
    document.undo()
    assert document.animation.pose.meshes[mesh.id].positions == original
    document.save(tmp_path / "image-study.rigora")
    reopened = DocumentService()
    reopened.open(tmp_path / "image-study.rigora")
    assert reopened.read_asset(mesh.asset_id) == data


def test_import_mesh_atomic_undo_and_embedded_source_roundtrip(tmp_path):
    document = DocumentService()
    document.new()
    service = MeshService(document)
    key = service.import_image_bytes("Original.svg", SVG, 2, 3)
    assert len(service.mesh(key).vertices) == 12
    assert len(service.mesh(key).triangles) == 12
    assert service.mesh(key).extra["subdivision"]["mode"] == "grid"
    asset = document.project.assets[0]
    assert document.read_asset(asset.id) == SVG
    document.undo()
    assert not document.project.assets and not service.scene.meshes
    document.redo()
    document.save(tmp_path / "mesh.rigora")
    document.open(tmp_path / "mesh.rigora")
    assert document.read_asset(asset.id) == SVG and service.mesh(key).object_id


def test_default_artwork_uses_full_triangles_and_retains_them_on_reopen(tmp_path):
    """File, byte and registered-asset placement share a real, serialized Full default."""
    document = DocumentService()
    document.new()
    service = MeshService(document)
    source = tmp_path / "Artwork.svg"
    source.write_bytes(SVG)
    first = service.import_image(source)
    second = service.import_image_bytes("Other.svg", SVG)
    third = service.instantiate_asset(service.mesh(first).asset_id)
    for key in (first, second, third):
        mesh = service.mesh(key)
        validate_embedding(mesh)
        assert mesh.extra["subdivision"] == {
            "mode": "full",
            "density": 4,
            "alignment": 1,
            "expand": 0,
        }
        assert len({round(v.x, 6) for v in mesh.vertices}) > 5
        assert document.read_asset(mesh.asset_id) == SVG
    document.save(tmp_path / "Full.rigora")
    document.open(tmp_path / "Full.rigora")
    assert all(
        service.mesh(k).extra["subdivision"]["mode"] == "full" for k in (first, second, third)
    )


@pytest.mark.parametrize(
    "data",
    [
        b"not an image",
        b'<svg width="999999" height="1"/>',
        b'<svg width="20" height="20"><image href="file:///private.png"/></svg>',
        b"<!DOCTYPE svg><svg/>",
    ],
)
def test_invalid_or_external_artwork_is_rejected_before_mutation(data):
    with pytest.raises(ProjectError):
        inspect_artwork(data)
