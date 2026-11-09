"""Portable source assets, reversible commands, migrations, and document ownership."""

import json
import zipfile
from dataclasses import replace

import pytest

from rigora.application_services.commands import ProjectPatch
from rigora.application_services.documents import DocumentService
from rigora.application_services.workspace import WorkspaceService
from rigora.domain.entities import Character, Skeleton
from rigora.domain.project import Project, ProjectError
from rigora.infrastructure.migrations import CURRENT_VERSION, migrate_document
from rigora.infrastructure.project_storage import ProjectStorage


def test_embedded_asset_portability_undo_redo_and_recovery(tmp_path):
    source = tmp_path / "shape.svg"
    contents = b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>'
    source.write_bytes(contents)
    document = DocumentService()
    document.new("Portable")
    baseline = document.project
    asset = document.import_asset(source)
    document.undo()
    assert document.project == baseline
    document.redo()
    destination = tmp_path / "portable.rigora"
    document.save(destination)
    source.unlink()
    loaded = DocumentService()
    loaded.open(destination)
    assert not loaded.dirty and loaded.read_asset(asset.id) == contents
    assert loaded.project == document.project
    loaded.update_settings("Changed", "Scene", loaded.project.scenes[0].settings)
    loaded.save()
    recovery = DocumentService()
    recovery.recover(destination.with_suffix(".rigora.bak"))
    assert recovery.path is None and recovery.dirty
    assert recovery.project.name == "Portable"
    assert recovery.read_asset(asset.id) == contents
    recovery.save(tmp_path / "recovered.rigora")


def test_linked_assets_missing_changes_and_portable_save_as(tmp_path):
    source = tmp_path / "art.png"
    source.write_bytes(b"opaque-art")
    document = DocumentService()
    document.new()
    path = tmp_path / "linked.rigora"
    document.save(path)
    asset = document.import_asset(source, embed=False)
    document.save()
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(ProjectError, match="Embed"):
        document.save(other / "copy.rigora")
    source.write_bytes(b"changed")
    loaded = DocumentService()
    loaded.open(path)
    assert "changed" in loaded.warnings[0]
    with pytest.raises(ProjectError, match="changed"):
        loaded.read_asset(asset.id)
    source.unlink()
    loaded.open(path)
    assert "Cannot read asset" in loaded.warnings[0]
    source.write_bytes(b"opaque-art")
    loaded.embed_external_assets()
    assert loaded.project.assets[0].storage == "embedded"
    loaded.undo()
    assert loaded.project.assets[0].storage == "external"
    loaded.redo()
    loaded.save(other / "copy.rigora")
    source.unlink()
    loaded.open(other / "copy.rigora")
    assert loaded.read_asset(asset.id) == b"opaque-art"
    assert not loaded.warnings


def test_external_links_cannot_escape_project_via_symlink(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside")
    link = root / "link.png"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Creating symlinks requires Windows Developer Mode or a Unix host")
    document = DocumentService()
    document.new()
    document.save(root / "project.rigora")
    with pytest.raises(ProjectError, match="within"):
        document.import_asset(link, embed=False)


def test_transaction_is_one_undo_step_and_failure_rolls_back(tmp_path):
    document = DocumentService()
    document.new("Before")
    original = document.project
    skeleton = Skeleton(name="Rig")
    character = Character(name="Actor", skeleton_id=skeleton.id)
    with document.transaction("Create character and name project"):
        document.add_entities(
            original.scenes[0].id, {"skeletons": (skeleton,), "characters": (character,)}
        )
        document.execute(ProjectPatch("Rename", {"name": "Before"}, {"name": "After"}))
    assert len(document.history.undo_stack) == 1
    published = document.project.scenes[0].characters
    assert len(published) == 1 and replace(published[0], extra=character.extra) == character
    assert published[0].extra["linked_object"]["definition"]
    document.undo()
    assert document.project == original
    document.redo()
    committed = document.project
    with pytest.raises(RuntimeError, match="abort"), document.transaction("Abort"):
        document.execute(ProjectPatch("Rename", {"name": "After"}, {"name": "Lost"}))
        raise RuntimeError("abort")
    assert document.project is committed
    assert len(document.history.undo_stack) == 1
    with (
        pytest.raises(ProjectError, match="transaction"),
        document.transaction("No lifecycle changes"),
    ):
        document.save(tmp_path / "forbidden.rigora")
    assert not (tmp_path / "forbidden.rigora").exists()


def test_deltas_share_records_freeze_inputs_and_conflicts_do_not_change_history():
    document = DocumentService()
    document.new("Before")
    original = document.project
    after = {"name": "After"}
    command = ProjectPatch("Rename", {"name": "Before"}, after)
    after["name"] = "Mutated input"
    document.execute(command)
    assert document.project.name == "After"
    assert document.project.scenes is original.scenes
    with pytest.raises(ProjectError, match="conflicts"):
        document.execute(command)
    assert len(document.history.undo_stack) == 1
    with pytest.raises(ProjectError, match="identity"):
        ProjectPatch("Replace identity", {"id": original.id}, {"id": original.id})


def test_version_one_migration_preserves_source_extras_and_requires_explicit_save(tmp_path):
    project = Project(name="Legacy", extra={"future": {"preserve": True}})
    data = project.to_dict()
    data.pop("settings")
    manifest = {
        "format": "rigora",
        "format_version": 1,
        "project_id": project.id,
        "project_file": "project.json",
        "required_features": [],
        "future_manifest": 42,
    }
    source = tmp_path / "legacy.rigora"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("project.json", json.dumps(data))
    before = source.read_bytes()
    document = DocumentService()
    document.open(source)
    assert document.dirty and "upgraded" in document.migration_note
    assert source.read_bytes() == before
    document.save()
    assert source.with_suffix(".rigora.bak").read_bytes() == before
    assert not document.dirty and document.migration_note is None
    loaded = ProjectStorage().load_document(source)
    assert loaded.source_version == CURRENT_VERSION
    assert loaded.project.extra["future"]["preserve"] is True
    assert loaded.manifest["future_manifest"] == 42
    with pytest.raises(ProjectError):
        migrate_document(manifest | {"format_version": CURRENT_VERSION + 1}, data)
    with pytest.raises(ProjectError):
        migrate_document(manifest | {"format_version": 0}, data)


def test_multidocument_independent_history_reorder_duplicate_open_and_close_guard(tmp_path):
    workspace = WorkspaceService()
    first = workspace.new("First")
    first.save(tmp_path / "first.rigora")
    second = workspace.new("Second")
    second.update_settings("Edited", "Scene", second.project.scenes[0].settings)
    assert workspace.open(first.path) is first
    assert len(workspace.documents) == 2
    assert not first.can_undo and second.can_undo
    workspace.move(0, 1)
    assert workspace.active is first and workspace.active_index == 1
    with pytest.raises(ProjectError, match="Unsaved"):
        workspace.close(0)
    workspace.close(0, discard=True)
    assert workspace.documents == (first,) and workspace.active is first
    workspace.close(0)
    assert workspace.active is None and workspace.active_index == -1


def test_embedded_asset_checksum_failure_is_not_loaded(tmp_path):
    source = tmp_path / "data.bin"
    source.write_bytes(b"original")
    document = DocumentService()
    document.new()
    asset = document.import_asset(source)
    project = document.project
    broken = replace(project, assets=(replace(asset, sha256="0" * 64),))
    with pytest.raises(ProjectError, match="digest|checksum|hash"):
        ProjectStorage().save(
            tmp_path / "bad.rigora", broken, {}, asset_data={asset.source: b"original"}
        )


@pytest.mark.parametrize("corruption", ["missing", "modified", "unlisted"])
def test_corrupt_source_package_preserves_active_document(tmp_path, corruption):
    source = tmp_path / "data.bin"
    source.write_bytes(b"original")
    document = DocumentService()
    document.new("Original")
    asset = document.import_asset(source)
    path = tmp_path / "valid.rigora"
    document.save(path)
    with zipfile.ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    if corruption == "missing":
        entries.pop(asset.source)
    elif corruption == "modified":
        entries[asset.source] = b"tampered"
    else:
        entries["assets/unlisted.bin"] = b"undeclared"
    broken = tmp_path / "broken.rigora"
    with zipfile.ZipFile(broken, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    original = document.project
    with pytest.raises(ProjectError):
        document.open(broken)
    assert document.project is original
    assert document.path == path and not document.dirty
