"""Bounded, portable plugin ZIP inspection with no code execution or implicit extraction."""

import stat
import zipfile
from pathlib import Path, PurePosixPath

from rigora.domain.validation import ProjectError
from rigora.infrastructure.project_storage import _read_member, _safe_member

MAX_PLUGIN = 128 * 1024 * 1024


def read_plugin_archive(path: Path) -> tuple[str, dict[str, bytes]]:
    """Read one package folder containing a manifest, rejecting links, aliases and path escapes."""
    try:
        if path.stat().st_size > MAX_PLUGIN:
            raise ProjectError("Plugin archives must be smaller than 128 MiB.")
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > 2048 or sum(m.file_size for m in members) > MAX_PLUGIN:
                raise ProjectError("Plugin archive exceeds its file count or expanded size limit.")
            seen = set()
            for member in members:
                name = member.filename.rstrip("/")
                if (
                    not _safe_member(name)
                    or name.casefold() in seen
                    or member.flag_bits & 1
                    or stat.S_ISLNK(member.external_attr >> 16)
                ):
                    raise ProjectError(
                        "Plugin ZIP contains unsafe, duplicate, linked or encrypted entries."
                    )
                seen.add(name.casefold())
            manifests = [
                m.filename
                for m in members
                if PurePosixPath(m.filename).name == "rigora-plugin.json"
            ]
            if len(manifests) != 1 or len(PurePosixPath(manifests[0]).parts) != 2:
                raise ProjectError(
                    "ZIP one plugin folder with rigora-plugin.json directly inside it."
                )
            folder = PurePosixPath(manifests[0]).parts[0]
            files = {}
            for member in members:
                parts = PurePosixPath(member.filename).parts
                if parts[0] != folder:
                    raise ProjectError("A plugin ZIP must contain exactly one package folder.")
                if (
                    not member.is_dir()
                    and "__pycache__" not in parts
                    and not member.filename.endswith((".pyc", ".pyo"))
                ):
                    files[PurePosixPath(*parts[1:]).as_posix()] = _read_member(
                        archive, member.filename, MAX_PLUGIN
                    )
            return folder, files
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError, NotImplementedError) as error:
        raise ProjectError(f"Cannot install plugin archive: {error}") from error
