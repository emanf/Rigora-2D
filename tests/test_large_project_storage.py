"""Chunked scene persistence and revision-safe background save adoption."""

import json
import zipfile

import pytest

from rigora.application_services.documents import DocumentService
from rigora.domain.entities import SceneObject
from rigora.domain.project import Project, ProjectError, Scene
from rigora.infrastructure.project_storage import ProjectStorage


def test_large_scene_roundtrip_uses_checksummed_chunks_and_rejects_tampering(tmp_path):
    """Authoring data beyond the old root-metadata cap roundtrips with exact entity identities."""
    project = Project(
        scenes=(
            Scene(
                objects=tuple(
                    SceneObject(name=f"Part {i}", extra={"notes": "a" * 24000}) for i in range(400)
                )
            ),
        )
    )
    path = tmp_path / "large.rigora"
    storage = ProjectStorage()
    storage.save(path, project, {})
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["required_features"] == ["scene-chunks-v1"]
        assert len(archive.read("project.json")) < 8 * 1024 * 1024
        contents = {name: archive.read(name) for name in archive.namelist()}
    assert storage.load_document(path).project == project
    name = next(name for name in contents if name.startswith("data/"))
    contents[name] = contents[name].replace(b"aaaa", b"bbbb", 1)
    with zipfile.ZipFile(path, "w") as archive:
        for name, raw in contents.items():
            archive.writestr(name, raw)
    with pytest.raises(ProjectError, match="checksum"):
        storage.load_document(path)


def test_small_projects_retain_legacy_layout_and_unknown_features_are_rejected(tmp_path):
    """New storage keeps ordinary format-2 packages readable by previous releases."""
    doc = DocumentService()
    doc.new()
    path = tmp_path / "small.rigora"
    doc.save(path)
    with zipfile.ZipFile(path) as archive:
        assert set(archive.namelist()) == {"manifest.json", "project.json"}
        assert json.loads(archive.read("manifest.json"))["required_features"] == []
    assert ProjectStorage().load_document(path).project == doc.project
    with pytest.raises(ProjectError, match="unsupported"):
        ProjectStorage().save(
            tmp_path / "unknown.rigora", doc.project, {"required_features": ["future"]}
        )


def test_background_save_marks_only_captured_revision_saved(tmp_path):
    """A worker's completed older revision cannot erase the dirty state of newer edits."""
    doc = DocumentService()
    doc.new()
    original = doc.project
    request = doc.prepare_save(tmp_path / "snapshot.rigora")
    doc.add_entities(doc.scene.id, {"objects": (SceneObject(name="Newer edit"),)})
    checksum = request.write()
    doc.complete_save(request, checksum)
    assert doc.dirty and ProjectStorage().load_document(doc.path).project == original
    assert doc.scene.objects[0].name == "Newer edit"
    doc.save()
    assert not doc.dirty


def test_large_object_definition_roundtrip_uses_required_checked_unicode_chunks(tmp_path):
    """A single large view-bearing definition no longer exhausts root metadata or loses UTF-8."""
    project = Project(extra={"object_library": {"definition": {"notes": "猫" * 3_000_000}}})
    path = tmp_path / "large-definition.rigora"
    storage = ProjectStorage()
    storage.save(path, project, {})
    with zipfile.ZipFile(path) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
        assert "object-chunks-v1" in json.loads(contents["manifest.json"])["required_features"]
        assert len(contents["project.json"]) < 8 * 1024 * 1024
    assert storage.load_document(path).project == project
    chunk = next(name for name in contents if name.startswith("data/object-library/"))
    contents[chunk] = b"!" + contents[chunk][1:]
    with zipfile.ZipFile(path, "w") as archive:
        for name, raw in contents.items():
            archive.writestr(name, raw)
    with pytest.raises(ProjectError, match="checksum"):
        storage.load_document(path)
