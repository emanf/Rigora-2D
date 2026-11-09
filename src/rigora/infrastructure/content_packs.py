"""Bounded ZIP content packs with no extraction, code loading or implicit network access."""

import io
import json
import os
import tempfile
import zipfile
from pathlib import Path

from rigora.domain.content import ContentPack
from rigora.domain.validation import ProjectError
from rigora.infrastructure.project_storage import _decode, _read_member, _safe_member

MAX_PACK = 64 * 1024 * 1024


def read_pack(
    path: Path, *, metadata_only: bool = False, thumbnails_only: bool = False
) -> tuple[ContentPack, dict[str, bytes]]:
    """Validate a pack; optionally read only metadata or posters for inexpensive discovery.

    Partial reads retain archive bounds and path validation. Full asset integrity is
    checked when the selected content is loaded for application.
    """
    try:
        if path.stat().st_size > MAX_PACK:
            raise ProjectError("Content packs must be smaller than 64 MiB.")
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            names = {member.filename for member in members}
            if (
                "manifest.json" not in names
                or len(names) != len(members)
                or len(members) > 512
                or any(not _safe_member(name) for name in names)
                or any(m.flag_bits & 1 for m in members)
                or sum(m.file_size for m in members) > MAX_PACK
            ):
                raise ProjectError("Invalid, encrypted or oversized content pack entries.")
            pack = ContentPack.from_dict(
                _decode(_read_member(archive, "manifest.json", 4 * 1024 * 1024))
            )
            if any(item.thumbnail and item.thumbnail not in names for item in pack.items):
                raise ProjectError("A content thumbnail is missing from the pack.")
            if metadata_only:
                return pack, {}
            thumbnails = {item.thumbnail for item in pack.items if item.thumbnail}
            files = {
                name: _read_member(archive, name, 32 * 1024 * 1024)
                for name in names
                if name != "manifest.json" and (not thumbnails_only or name in thumbnails)
            }
            if any(item.thumbnail and item.thumbnail not in files for item in pack.items):
                raise ProjectError("A content thumbnail is missing from the pack.")
            return pack, files
    except (
        OSError,
        ValueError,
        zipfile.BadZipFile,
        KeyError,
        RuntimeError,
        NotImplementedError,
        RecursionError,
    ) as error:
        raise ProjectError(f"Cannot read content pack: {error}") from error


def write_pack(
    path: Path, pack: ContentPack, files: dict[str, bytes], *, overwrite: bool = False
) -> None:
    """Publish a bounded self-contained archive atomically, refusing overwrite by default."""
    if any(not _safe_member(name) or name == "manifest.json" for name in files):
        raise ProjectError("Content filenames must be portable relative paths.")
    manifest = json.dumps(pack.to_dict(), ensure_ascii=False, allow_nan=False).encode("utf-8")
    if (
        len(files) > 511
        or len(manifest) > 4 * 1024 * 1024
        or any(len(data) > 32 * 1024 * 1024 for data in files.values())
        or len(manifest) + sum(map(len, files.values())) > MAX_PACK
    ):
        raise ProjectError("Content pack exceeds its storage limits.")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", manifest)
        for name, data in files.items():
            archive.writestr(name, data)
    raw = buffer.getvalue()
    if len(raw) > MAX_PACK:
        raise ProjectError("Content pack exceeds 64 MiB.")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".rigpack-", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
