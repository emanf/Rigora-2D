import json
import subprocess
import sys
import zipfile
from dataclasses import replace

import pytest

from rigora.application_services.documents import DocumentService
from rigora.domain.project import Project, ProjectError, SceneSettings
from rigora.infrastructure import preferences, project_storage
from rigora.infrastructure.preferences import PreferencesStore
from rigora.infrastructure.project_storage import ProjectStorage


def test_document_roundtrip_undo_and_recovery(tmp_path):
    path = tmp_path / "character.rigora"
    document = DocumentService()
    document.new("Character", SceneSettings(width=1280, height=720, fps=30))
    original = document.project
    assert document.dirty
    document.save(path)
    assert not document.dirty
    document.update_settings("Character revised", "Shot", SceneSettings())
    assert document.dirty and document.can_undo
    document.undo()
    assert document.project == original and not document.dirty
    document.redo()
    document.save()
    reopened = DocumentService()
    reopened.open(path)
    assert reopened.project == document.project and not reopened.dirty
    reopened.recover(path.with_suffix(".rigora.bak"))
    assert reopened.project == original
    assert reopened.path is None and reopened.dirty


def test_extensions_are_preserved_and_cannot_mutate_history(tmp_path):
    extensions = {"plugin.example": {"values": [1, 2]}, "compressible": "x" * 500_000}
    project = Project(extra=extensions)
    extensions["plugin.example"]["values"].append(3)
    assert project.to_dict()["plugin.example"]["values"] == [1, 2]
    with pytest.raises(TypeError):
        project.extra["plugin.example"]["values"][0] = 5
    path = tmp_path / "extensions.rigora"
    storage = ProjectStorage()
    storage.save(path, project, {"optional_note": "keep this"})
    loaded, manifest, _ = storage.load(path)
    assert loaded == project and manifest["optional_note"] == "keep this"


@pytest.mark.parametrize(
    "changes",
    [{"width": True}, {"height": 0}, {"fps": 0}, {"end_frame": -1}, {"width": 16385}],
)
def test_scene_settings_reject_invalid_values(changes):
    with pytest.raises(ProjectError):
        SceneSettings(**changes)


def test_invalid_identity_and_extensions():
    project = Project()
    with pytest.raises(ProjectError, match="unique"):
        replace(project, scenes=(replace(project.scenes[0], id=project.id),))
    with pytest.raises(ProjectError):
        Project(name=" ")
    with pytest.raises(ProjectError):
        Project(extra={"bad": float("nan")})


def test_failed_open_preserves_current_document(tmp_path):
    doc = DocumentService()
    doc.new("Unsaved work")
    original = doc.project
    path = tmp_path / "broken.rigora"
    path.write_bytes(b"not a project")
    with pytest.raises(ProjectError):
        doc.open(path)
    assert doc.project is original and doc.dirty


@pytest.mark.parametrize("kind", ["future", "path", "duplicate_json", "required_feature"])
def test_unsupported_packages_are_rejected_without_extraction(tmp_path, kind):
    project = Project()
    manifest = {
        "format": "rigora",
        "format_version": 1,
        "project_file": "project.json",
        "project_id": project.id,
    }
    if kind == "future":
        manifest["format_version"] = 999
    if kind == "required_feature":
        manifest["required_features"] = ["unsupported_animation"]
    path = tmp_path / f"{kind}.rigora"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr(
            "project.json",
            '{"id":1,"id":2}' if kind == "duplicate_json" else json.dumps(project.to_dict()),
        )
        if kind == "path":
            archive.writestr("../escape.txt", "must never be extracted")
    with pytest.raises(ProjectError):
        ProjectStorage().load(path)
    assert not (tmp_path.parent / "escape.txt").exists()


def test_overwrite_and_external_edit_protection(tmp_path):
    path = tmp_path / "safe.rigora"
    doc = DocumentService()
    doc.new("First")
    doc.save(path)
    original = path.read_bytes()
    other = DocumentService()
    other.new("Other")
    with pytest.raises(ProjectError, match="overwrite"):
        other.save(path)
    assert path.read_bytes() == original
    path.write_bytes(b"external revision")
    with pytest.raises(ProjectError, match="outside"):
        doc.save()
    assert path.read_bytes() == b"external revision"


def test_interrupted_save_preserves_original_and_backup(tmp_path, monkeypatch):
    path = tmp_path / "safe.rigora"
    doc = DocumentService()
    doc.new()
    doc.save(path)
    original = path.read_bytes()
    doc.update_settings("Revised", "Scene", SceneSettings())
    replace_file = project_storage.os.replace

    def interrupted(source, destination):
        if destination == path:
            raise OSError("injected interrupted replacement")
        return replace_file(source, destination)

    monkeypatch.setattr(project_storage.os, "replace", interrupted)
    with pytest.raises(ProjectError, match="interrupted"):
        doc.save()
    assert path.read_bytes() == original
    assert path.with_suffix(".rigora.bak").read_bytes() == original
    assert not list(tmp_path.glob(".rigora-*"))
    assert doc.dirty


def test_racing_new_destination_is_never_overwritten(tmp_path, monkeypatch):
    path = tmp_path / "race.rigora"
    link = project_storage.os.link

    def racing_link(source, destination):
        destination.write_bytes(b"another application's work")
        return link(source, destination)

    monkeypatch.setattr(project_storage.os, "link", racing_link)
    with pytest.raises(ProjectError):
        ProjectStorage().save(path, Project(), {})
    assert path.read_bytes() == b"another application's work"
    assert not list(tmp_path.glob(".rigora-*"))


def test_preferences_recovery_and_save_failure(tmp_path, monkeypatch):
    path = tmp_path / "workspace.json"
    path.write_text("invalid json", encoding="utf-8")
    store = PreferencesStore(path)
    assert store.warning and store.data["theme"] == "dark"
    store.data["theme"] = "light"
    assert store.save() is None
    assert PreferencesStore(path).data["theme"] == "light"

    def failed_write(*args):
        raise OSError("injected read-only settings")

    monkeypatch.setattr(preferences, "_atomic_bytes", failed_write)
    assert "read-only" in store.save()


def test_real_document_services_never_import_qt(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import importlib.abc
import sys
from pathlib import Path
class BlockQt(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('PySide', 'PyQt', 'shiboken')):
            raise AssertionError(fullname)
sys.meta_path.insert(0, BlockQt())
from rigora.application_services.documents import DocumentService
doc = DocumentService()
doc.new('Headless project')
doc.save(Path('headless.rigora'))
doc.open(Path('headless.rigora'))
assert not doc.dirty and doc.project.name == 'Headless project'
""",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
