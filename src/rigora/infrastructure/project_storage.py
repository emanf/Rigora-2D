"""Versioned ZIP storage with bounded assets, atomic publication, and recovery backups."""

import hashlib
import json
import os
import tempfile
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from rigora import __version__
from rigora.domain.project import Project, ProjectError, json_copy, mapping
from rigora.domain.validation import portable_relative_path
from rigora.infrastructure.migrations import CURRENT_VERSION, migrate_document
from rigora.infrastructure.project_chunks import (
    CHUNK_FEATURE,
    MAX_SCENE_BYTES,
    OBJECT_CHUNK_FEATURE,
    restore_object_data,
    restore_scene_data,
    split_object_data,
    split_scene_data,
)

MAX_SIZE = 8 * 1024 * 1024
MAX_ASSET_SIZE = 32 * 1024 * 1024
MAX_PACKAGE_SIZE = 512 * 1024 * 1024


def digest(path: Path) -> str:
    """Hash a bounded project file without loading its complete contents into memory."""
    try:
        if path.stat().st_size > MAX_PACKAGE_SIZE:
            raise ProjectError("Project package exceeds the 512 MiB limit.")
        result = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                result.update(chunk)
        return result.hexdigest()
    except OSError as error:
        raise ProjectError(f"Cannot read {path.name}: {error}") from error


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject ambiguous duplicate JSON keys before any model construction."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProjectError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def _decode(raw: bytes) -> dict[str, Any]:
    """Decode an unambiguous UTF-8 JSON object for metadata validation."""
    return mapping(json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object), "Document")


def _safe_member(name: str) -> bool:
    """Check portable archive names without ever extracting them to the filesystem."""
    try:
        portable_relative_path(name)
    except ProjectError:
        return False
    return True


def _read_member(archive: zipfile.ZipFile, name: str, limit: int) -> bytes:
    """Read at most the allowed uncompressed size of a single package member."""
    member = archive.getinfo(name)
    if member.file_size > limit:
        raise ProjectError(f"Package member exceeds its size limit: {name}")
    with archive.open(member) as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ProjectError(f"Package member exceeds its size limit: {name}")
    return data


@dataclass(frozen=True)
class StoredProject:
    """A validated model, opaque embedded bytes, and source-version provenance."""

    project: Project
    manifest: dict[str, Any]
    checksum: str
    assets: Mapping[str, bytes]
    source_version: int


class ProjectStorage:
    """Read and publish portable authoring packages without executing their contents."""

    def load(self, path: Path) -> tuple[Project, dict[str, Any], str]:
        """Return the metadata view; full document loading also retains embedded bytes."""
        loaded = self.load_document(path)
        return loaded.project, loaded.manifest, loaded.checksum

    def load_document(self, path: Path) -> StoredProject:
        """Validate package structure, migrate supported metadata, and retain embedded assets."""
        checksum = digest(path)
        try:
            with zipfile.ZipFile(path) as archive:
                members = archive.infolist()
                names = {member.filename for member in members}
                if (
                    not {"manifest.json", "project.json"} <= names
                    or len(names) != len(members)
                    or len(members) > 4096
                    or any(not _safe_member(name) for name in names)
                ):
                    raise ProjectError(
                        "Invalid or unsupported package entries; no data was extracted."
                    )
                if any(member.flag_bits & 1 for member in members):
                    raise ProjectError("Encrypted projects are not supported.")
                if sum(member.file_size for member in members) > MAX_PACKAGE_SIZE:
                    raise ProjectError("Project contents exceed the 512 MiB limit.")
                raw_manifest = _read_member(archive, "manifest.json", MAX_SIZE)
                raw_project = _read_member(archive, "project.json", MAX_SIZE)
                if len(raw_manifest) + len(raw_project) > MAX_SIZE:
                    raise ProjectError("Project metadata exceeds the 8 MiB limit.")
                manifest = _decode(raw_manifest)
                if manifest.get("format") != "rigora":
                    raise ProjectError("This is not a Rigora project manifest.")
                if manifest.get("project_file") != "project.json":
                    raise ProjectError("Manifest project_file must be project.json.")
                if not isinstance(manifest.get("required_features", []), list) or any(
                    feature not in (CHUNK_FEATURE, OBJECT_CHUNK_FEATURE)
                    for feature in manifest.get("required_features", [])
                ):
                    raise ProjectError("This project requires unsupported features.")
                source_version = manifest.get("format_version")
                if type(source_version) is not int:
                    raise ProjectError("Project format version must be an integer.")
                data = _decode(raw_project)
                chunk_bytes = 0

                def read_chunk(name: str, limit: int) -> bytes:
                    """Enforce the shared scene/definition budget before retaining decoded data."""
                    nonlocal chunk_bytes
                    raw = _read_member(archive, name, limit)
                    chunk_bytes += len(raw)
                    if chunk_bytes > MAX_SCENE_BYTES:
                        raise ProjectError("Scene/Object data exceeds the 256 MiB chunk budget.")
                    return raw

                chunk_names = (
                    restore_scene_data(
                        data,
                        read_chunk,
                        lambda raw: json.loads(
                            raw.decode("utf-8"), object_pairs_hook=_unique_object
                        ),
                    )
                    if CHUNK_FEATURE in manifest.get("required_features", [])
                    else set()
                )
                if OBJECT_CHUNK_FEATURE in manifest.get("required_features", []):
                    chunk_names.update(restore_object_data(data, read_chunk, _decode))
                if sum(archive.getinfo(name).file_size for name in chunk_names) > MAX_SCENE_BYTES:
                    raise ProjectError("Scene/Object data exceeds the 256 MiB chunk budget.")
                manifest, data = migrate_document(manifest, data)
                project = Project.from_dict(data)
                if manifest.get("project_id") != project.id:
                    raise ProjectError("Manifest and project IDs do not match.")
                descriptors = {
                    asset.source: asset for asset in project.assets if asset.storage == "embedded"
                }
                if names != {"manifest.json", "project.json", *descriptors, *chunk_names}:
                    raise ProjectError(
                        "Unsupported package entries; no data was extracted or discarded."
                    )
                assets: dict[str, bytes] = {}
                for name, descriptor in descriptors.items():
                    content = _read_member(archive, name, MAX_ASSET_SIZE)
                    if (
                        descriptor.sha256 is not None
                        and hashlib.sha256(content).hexdigest() != descriptor.sha256
                    ):
                        raise ProjectError(f"Asset checksum does not match: {descriptor.name}")
                    assets[name] = content
                return StoredProject(
                    project, manifest, checksum, MappingProxyType(assets), source_version
                )
        except ProjectError:
            raise
        except (
            OSError,
            ValueError,
            UnicodeError,
            zipfile.BadZipFile,
            RuntimeError,
            NotImplementedError,
            RecursionError,
            KeyError,
        ) as error:
            raise ProjectError(f"Cannot open {path.name}: {error}") from error

    def save(
        self,
        path: Path,
        project: Project,
        manifest: dict[str, Any],
        *,
        expected_digest: str | None = None,
        overwrite: bool = False,
        asset_data: Mapping[str, bytes] | None = None,
    ) -> str:
        """Publish a complete package and preserve the predecessor before approved replacement."""
        if path.suffix.lower() != ".rigora":
            raise ProjectError("Project files must use the .rigora extension.")
        existed = path.exists()
        if existed:
            if expected_digest is not None:
                if digest(path) != expected_digest:
                    raise ProjectError(
                        "This file changed outside Rigora. Use Save As to preserve both versions."
                    )
            elif not overwrite:
                raise ProjectError(
                    "The destination exists; explicit overwrite approval is required."
                )
        elif expected_digest is not None:
            raise ProjectError("The file was removed outside Rigora. Use Save As.")
        if any(
            feature not in (CHUNK_FEATURE, OBJECT_CHUNK_FEATURE)
            for feature in manifest.get("required_features", [])
        ):
            raise ProjectError("Cannot discard unsupported required project features.")
        validated = Project.from_dict(project.to_dict())
        embedded: dict[str, bytes] = {}
        for asset in validated.assets:
            if asset.storage != "embedded":
                continue
            content = (asset_data or {}).get(asset.source)
            if not isinstance(content, bytes) or len(content) > MAX_ASSET_SIZE:
                raise ProjectError(f"Embedded asset is missing or too large: {asset.name}")
            if asset.sha256 is not None and hashlib.sha256(content).hexdigest() != asset.sha256:
                raise ProjectError(f"Embedded asset checksum is invalid: {asset.name}")
            embedded[asset.source] = content
        if len(embedded) + 2 > 4096:
            raise ProjectError("Project package exceeds the 4096-member limit.")
        metadata = {
            **json_copy(manifest),
            "format": "rigora",
            "format_version": CURRENT_VERSION,
            "project_file": "project.json",
            "project_id": project.id,
            "created_with": __version__,
            "required_features": [],
        }
        data = validated.to_dict()
        payload = json.dumps(
            data, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        chunks = {}
        if len(payload) > 2 * 1024 * 1024:
            chunks = split_scene_data(data)
            if chunks:
                metadata["required_features"] = [CHUNK_FEATURE]
            object_chunks = split_object_data(data)
            if object_chunks:
                metadata["required_features"].append(OBJECT_CHUNK_FEATURE)
                chunks.update(object_chunks)
            if sum(map(len, chunks.values())) > MAX_SCENE_BYTES:
                raise ProjectError("Scene/Object data exceeds the 256 MiB chunk budget.")
            payload = json.dumps(
                data, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
        header = json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
        if len(payload) + len(header) > MAX_SIZE:
            raise ProjectError("Project metadata exceeds the 8 MiB limit.")
        if len(embedded) + len(chunks) + 2 > 4096:
            raise ProjectError("Project package exceeds the 4096-member limit.")
        if (
            len(payload)
            + len(header)
            + sum(map(len, chunks.values()))
            + sum(map(len, embedded.values()))
            > MAX_PACKAGE_SIZE
        ):
            raise ProjectError("Project contents exceed the 512 MiB limit.")
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=path.parent, prefix=".rigora-", delete=False
            ) as handle:
                temporary = Path(handle.name)
                with zipfile.ZipFile(handle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr("manifest.json", header)
                    archive.writestr("project.json", payload)
                    for name, content in chunks.items():
                        archive.writestr(name, content)
                    for name, content in embedded.items():
                        archive.writestr(name, content)
                if handle.tell() > MAX_PACKAGE_SIZE:
                    raise ProjectError("Project package exceeds the 512 MiB limit.")
                handle.flush()
                os.fsync(handle.fileno())
            if path.exists():
                if not existed and not overwrite:
                    raise ProjectError(
                        "The destination appeared while saving; choose another file."
                    )
                if expected_digest is not None and digest(path) != expected_digest:
                    raise ProjectError(
                        "This file changed while saving. Original data was preserved."
                    )
                _atomic_bytes(path.with_suffix(".rigora.bak"), path.read_bytes())
            elif expected_digest is not None:
                raise ProjectError(
                    "The file was removed while saving. Use Save As to retain edits."
                )
            checksum = digest(temporary)
            if not existed and not overwrite:
                os.link(temporary, path)
                temporary.unlink()
            else:
                os.replace(temporary, path)
            temporary = None
            return checksum
        except OSError as error:
            raise ProjectError(f"Cannot save {path.name}: {error}") from error
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def _atomic_bytes(path: Path, data: bytes) -> None:
    """Atomically replace a small local file after flushing a temporary sibling."""
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".rigora-", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
