"""Local template directories discover portable artwork without eagerly reading source files."""

import io
import zipfile
from dataclasses import replace
from uuid import uuid4

import pytest
from PIL import Image

from rigora.application_services.content_library import ContentLibrary, ContentService
from rigora.application_services.documents import DocumentService
from rigora.domain.content import ContentItem, ContentPack
from rigora.domain.project import ProjectError
from rigora.infrastructure.content_packs import read_pack, write_pack
from rigora.infrastructure.preferences import PreferencesStore


def fixture_pack():
    """Provide an ordinary transparent raster sprite with a distinct thumbnail member."""
    buffer = io.BytesIO()
    Image.new("RGBA", (20, 40), (80, 120, 150, 180)).save(buffer, format="PNG")
    item = ContentItem(
        name="Reusable sprite",
        kind="artwork",
        category="Local sprites",
        author="Test",
        license="CC0-1.0",
        thumbnail="thumbs/sprite.png",
        payload={"source": "art/sprite.png"},
    )
    pack = ContentPack(name="Local collection", author="Test", license="CC0-1.0", items=(item,))
    return pack, {"art/sprite.png": buffer.getvalue(), "thumbs/sprite.png": buffer.getvalue()}


def test_directory_discovery_and_partial_reads_preserve_artwork_application(tmp_path, monkeypatch):
    """Only selected sprite application loads the full pack; directory refresh stays live."""
    pack, files = fixture_pack()
    bundled = tmp_path / "builtin.rigpack"
    write_pack(bundled, replace(pack, id=str(uuid4())), files)
    directory = tmp_path / "external"
    directory.mkdir()
    source = directory / "sprites.rigpack"
    write_pack(source, pack, files)
    opened = []
    original = zipfile.ZipFile.open

    def observed(archive, name, *args, **kwargs):
        opened.append(name.filename if isinstance(name, zipfile.ZipInfo) else name)
        return original(archive, name, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "open", observed)
    preferences = PreferencesStore(tmp_path / "preferences.json")
    preferences.data["template_pack_directories"] = [str(directory), 123]
    library = ContentLibrary(preferences, bundled=bundled)
    entries = library.entries()
    assert len(entries) == 2 and not library.warnings
    assert set(opened) == {"manifest.json"}
    opened.clear()
    metadata, thumbnails = read_pack(source, thumbnails_only=True)
    assert metadata == pack and thumbnails == {"thumbs/sprite.png": files["thumbs/sprite.png"]}
    assert set(opened) == {"manifest.json", "thumbs/sprite.png"}
    document = DocumentService()
    document.new()
    _, full = read_pack(source)
    baseline = document.project
    entry = next(entry for entry in entries if entry.path == source)
    ContentService(document).apply(entry.item, full)
    assert document.scene.objects and document.project != baseline
    document.undo()
    assert document.project == baseline
    source.unlink()
    assert len(library.entries()) == 1


@pytest.mark.parametrize("mode", ({"metadata_only": True}, {"thumbnails_only": True}, {}))
def test_partial_reads_reject_unsafe_archive_members(tmp_path, mode):
    """Selective loading must preserve the same portable-path checks as full loading."""
    pack, _ = fixture_pack()
    path = tmp_path / "invalid.rigpack"
    import json

    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(pack.to_dict()))
        archive.writestr("thumbs/sprite.png", b"png")
        archive.writestr("../escape.png", b"invalid")
    with pytest.raises(ProjectError, match="Invalid"):
        read_pack(path, **mode)


def test_local_directory_does_not_bypass_authorized_roots(tmp_path):
    """A registered folder still obeys restricted library roots."""
    pack, files = fixture_pack()
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    bundled = allowed / "builtin.rigpack"
    write_pack(bundled, pack, files)
    outside = tmp_path / "outside"
    outside.mkdir()
    write_pack(outside / "external.rigpack", pack, files)
    preferences = PreferencesStore(tmp_path / "preferences.json")
    preferences.data["template_pack_directories"] = [str(outside)]
    library = ContentLibrary(preferences, bundled=bundled, allowed_roots=(allowed.resolve(),))
    assert len(library.entries()) == 1
    assert len(library.warnings) == 1 and "outside authorized" in library.warnings[0]
