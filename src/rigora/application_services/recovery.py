"""Independent recovery packages and bounded workspace-session records; originals stay untouched."""

import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from rigora.application_services.documents import DocumentService
from rigora.domain.project import ProjectError
from rigora.infrastructure.project_storage import _atomic_bytes


@dataclass(frozen=True)
class RecoveryEntry:
    """One recoverable snapshot with display-only metadata and its private package path."""

    path: Path
    name: str
    source: str
    updated: float


class RecoveryStore:
    """Own one run's checkpoints without deleting another running instance's snapshots."""

    def __init__(self, root: Path) -> None:
        """Select the local recovery directory; defer filesystem creation until writing."""
        self.root = root.resolve()
        self.run = self.root / str(uuid4())

    def prepare(self, document: DocumentService) -> tuple[DocumentService, Path]:
        """Capture immutable records/bytes on the owner thread without reading external assets."""
        scratch = document.persistence_copy()
        scratch.manifest["recovery"] = {
            "source": str(document.path or ""),
            "name": document.project.name if document.project else "",
            "scene": document.scene.id,
            "frame": document.cursor_frame,
        }
        return scratch, self.run / f"{document.session_id}.rigora"

    def write(self, scratch: DocumentService, path: Path) -> None:
        """Embed originals on a worker, retaining the previous private snapshot."""
        if path.parent != self.run:
            raise ProjectError("Recovery destination must belong to this application session.")
        path.parent.mkdir(parents=True, exist_ok=True)
        scratch.embed_external_assets()
        scratch.save(path, overwrite=True)

    def remove(self, session_id: str) -> None:
        """Discard only this run's explicitly resolved document checkpoint and its predecessor."""
        key = str(UUID(session_id))
        path = self.run / f"{key}.rigora"
        path.unlink(missing_ok=True)
        path.with_suffix(".rigora.bak").unlink(missing_ok=True)

    def entries(self) -> tuple[RecoveryEntry, ...]:
        """Inspect headers, including valid predecessors of corrupt snapshots."""
        result = []
        for index, path in enumerate(self.root.glob("*/*.rigora*")):
            if index >= 4096:
                break
            if path.is_symlink() or not path.resolve().is_relative_to(self.root):
                continue
            try:
                with zipfile.ZipFile(path) as archive:
                    info = archive.getinfo("manifest.json")
                    if info.file_size > 262144:
                        continue
                    metadata = json.loads(archive.read(info))
                if not isinstance(metadata, dict):
                    continue
                data = metadata.get("recovery")
                if not isinstance(data, dict):
                    continue
                result.append(
                    RecoveryEntry(
                        path,
                        str(data.get("name", "Recovered project")),
                        str(data.get("source", "")),
                        path.stat().st_mtime,
                    )
                )
            except (OSError, ValueError, KeyError, zipfile.BadZipFile):
                continue
        return tuple(sorted(result, key=lambda entry: entry.updated, reverse=True)[:128])

    def restore(self, entry: RecoveryEntry) -> DocumentService:
        """Open a snapshot as unsaved work, preserving the source file until an explicit Save As."""
        if not entry.path.resolve().is_relative_to(self.root):
            raise ProjectError("Choose a snapshot from the recovery directory.")
        doc = DocumentService()
        doc.recover(entry.path)
        assert doc.project is not None
        data = doc.manifest.pop("recovery", {})
        if data.get("scene") in {scene.id for scene in doc.project.scenes}:
            doc.select_scene(data["scene"])
        try:
            doc.animation.seek(float(data.get("frame", 0)))
        except ProjectError:
            doc.migration_note = (
                "Recovery opened; its stored playback position needs a supported clip."
            )
        return doc

    def write_session(self, records: list[dict[str, Any]]) -> None:
        """Retain saved-project paths and cursors without writing to those project files."""
        self.root.mkdir(parents=True, exist_ok=True)
        _atomic_bytes(
            self.root / "workspace.json", json.dumps(records[:32], allow_nan=False).encode()
        )

    def session(self) -> tuple[dict[str, Any], ...]:
        """Read a bounded session list; malformed or missing state leaves Welcome usable."""
        path = self.root / "workspace.json"
        try:
            if path.stat().st_size > 262144:
                return ()
            data = json.loads(path.read_text(encoding="utf-8"))
            return (
                tuple(
                    r for r in data[:32] if isinstance(r, dict) and isinstance(r.get("path"), str)
                )
                if isinstance(data, list)
                else ()
            )
        except (OSError, ValueError):
            return ()
