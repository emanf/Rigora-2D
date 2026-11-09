"""Offline content provenance, atomic installation, semantic reuse and portable sharing."""

import io
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from rigora.application_services.content_library import ContentLibrary, ContentService
from rigora.application_services.documents import DocumentService
from rigora.domain.content import ContentPack
from rigora.domain.project import ProjectError
from rigora.engine.evaluation import SceneEvaluator
from rigora.infrastructure.content_packs import read_pack, write_pack
from rigora.infrastructure.preferences import PreferencesStore


def test_refresh_discovers_bundled_packs_added_after_startup(current_pack, tmp_path, monkeypatch):
    """A running library sees newly supplied collections without replacing its service."""
    import rigora.application_services.illustration_cache as module

    starter, files = current_pack("rigs-effects")
    source = tmp_path / "templates.rigpack"
    write_pack(source, starter, files)
    monkeypatch.setattr(module, "ensure_catalog", lambda *args: tmp_path)
    library = ContentLibrary(PreferencesStore(tmp_path / "prefs.json"))
    original = len(library.entries())
    added = ContentPack(
        name="New collection",
        author="Test",
        license="CC0-1.0",
        items=(replace(starter.items[0], name="New rig"),),
    )
    write_pack(tmp_path / "studio-new.rigpack", added, files)
    assert len(library.entries()) == original + 1
    assert not library.warnings


def test_bundled_templates_poses_actions_and_presets_are_original_and_undoable(tmp_path):
    """Every advertised starter item evaluates through canonical services without network access."""
    library = ContentLibrary(PreferencesStore(tmp_path / "prefs.json"))
    entries = library.entries()
    assert len(entries) == 287 and not library.warnings
    doc = DocumentService()
    doc.new()
    service = ContentService(doc)
    rigs = {}
    for entry in entries:
        if entry.item.kind != "rig":
            continue
        _, files = read_pack(entry.path)
        baseline = doc.project
        count = len(doc.history.undo_stack)
        preview = service.preview(entry.item, files)
        assert preview.project != baseline and doc.project is baseline
        key = service.apply(entry.item, files)
        rigs.setdefault(service.skeleton(key).extra["anatomy"], key)
        assert len(doc.history.undo_stack) == count + 1
        assert not doc.animation.pose.warnings
    for entry in entries:
        if entry.item.kind not in ("pose", "action"):
            continue
        _, files = read_pack(entry.path)
        target = rigs[entry.item.payload["anatomy"]]
        baseline = doc.project
        count = len(doc.history.undo_stack)
        action_id = service.apply(entry.item, files, target=target)
        assert len(doc.history.undo_stack) == count + 1
        if entry.item.kind == "action":
            evaluator = SceneEvaluator(doc.scene, action_id)
            start_pose = evaluator.evaluate(0)
            assert any(
                evaluator.evaluate(evaluator.range.duration_frames * phase).nodes
                != start_pose.nodes
                for phase in (0.13, 0.31, 0.57, 0.83)
            ), entry.item.name
        doc.undo()
        assert doc.project == baseline
    bird_motion = next(e for e in entries if e.item.name == "Cat · Walk")
    assert "anatomy" in service.compatibility(bird_motion.item, rigs["human"])
    original = doc.project
    with pytest.raises(ProjectError, match="anatomy"):
        service.apply(bird_motion.item, {}, target=rigs["human"])
    assert doc.project is original
    art = next(e for e in entries if e.item.kind == "artwork")
    _, files = read_pack(art.path)
    mesh = service.apply(art.item, files)
    for entry in entries:
        if entry.item.kind == "deformation":
            service.apply(entry.item, {}, mesh_id=mesh)
            assert not doc.animation.pose.warnings
            doc.undo()
    assert doc.animation.pose.meshes[mesh].positions
    library.toggle_favorite(art.key)
    library.used(art.key)
    reloaded = ContentLibrary(PreferencesStore(tmp_path / "prefs.json"))
    assert reloaded.favorite(art.key)
    assert reloaded.preferences.data["content_recent"][0] == art.key


def test_pack_install_share_custom_rig_and_complete_skinned_scene(tmp_path, monkeypatch):
    """Shared rigs/scenes retain assets and weights with fresh identities and atomic undo."""
    source = DocumentService()
    source.open(Path("examples/image-import-example.rigora"))
    service = ContentService(source)
    rig = source.project.scenes[0].skeletons[0]
    rig_path = tmp_path / "my-rig.rigpack"
    service.export_own(rig_path, "Custom rig", "eManF", "All rights reserved", rig_id=rig.id)
    pack, files = read_pack(rig_path)
    assert pack.items[0].author == "eManF"
    library = ContentLibrary(PreferencesStore(tmp_path / "other-user/preferences.json"))
    library.install(rig_path)
    with pytest.raises(ProjectError, match="already installed"):
        library.install(rig_path)
    assert any(e.item.name == "Custom rig" for e in library.entries())
    scene_path = tmp_path / "complete.rigpack"
    service.export_own(scene_path, "My skinned character", "eManF", "All rights reserved")
    pack, files = read_pack(scene_path)
    assert pack.items[0].thumbnail == "thumbnail.png"
    assert files["thumbnail.png"].startswith(b"\x89PNG")
    target = DocumentService()
    target.new()
    before = target.project
    ContentService(target).apply(pack.items[0], files)
    assert len(target.history.undo_stack) == 1
    mesh = target.project.scenes[0].meshes[0]
    assert mesh.vertices[0].weights
    new_bones = {b.id for r in target.project.scenes[0].skeletons for b in r.bones}
    assert new_bones.isdisjoint(b.id for b in rig.bones)
    assert all(set(vertex.weights) <= new_bones for vertex in mesh.vertices)
    assert target.read_asset(mesh.asset_id) == source.read_asset(
        source.project.scenes[0].meshes[0].asset_id
    )
    target.save(tmp_path / "reused.rigora")
    reopened = DocumentService()
    reopened.open(target.path)
    assert reopened.project == target.project
    target.undo()
    assert target.project == before
    from rigora.application_services import content_thumbnails

    def missing_render(*args, **kwargs):
        """Model a valid headless installation without optional PNG rendering dependencies."""
        raise ImportError("render extras are not installed")

    monkeypatch.setattr(content_thumbnails, "render_content_thumbnail", missing_render)
    fallback_path = tmp_path / "headless-shared.rigpack"
    service.export_own(fallback_path, "Headless shared rig", "eManF", "All rights reserved")
    fallback, media = read_pack(fallback_path)
    assert media[fallback.items[0].thumbnail] == content_thumbnails.placeholder_thumbnail()


def test_pack_rejects_ambiguous_entries_traversal_and_preserves_installed_data(
    current_pack, tmp_path
):
    """No archive path is extracted and malformed local packs cannot overwrite installed content."""
    pack, files = current_pack("rigs-effects")
    with pytest.raises(ProjectError, match="IDs"):
        replace(pack, items=(pack.items[0], pack.items[0]))
    original = tmp_path / "good.rigpack"
    write_pack(original, pack, files)
    raw = original.read_bytes()
    with pytest.raises(FileExistsError):
        write_pack(original, pack, files)
    assert original.read_bytes() == raw
    bad = tmp_path / "bad.rigpack"
    with zipfile.ZipFile(bad, "w") as archive:
        archive.writestr("manifest.json", "{}")
        archive.writestr("../outside", "bad")
    with pytest.raises(ProjectError, match="entries"):
        read_pack(bad)
    assert not (tmp_path.parent / "outside").exists()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("manifest.json", '{"format":"rigora.content-pack","format":"bad"}')
    bad.write_bytes(output.getvalue())
    with pytest.raises(ProjectError, match="Duplicate"):
        read_pack(bad)
    assert ContentPack.from_dict(pack.to_dict()) == pack
