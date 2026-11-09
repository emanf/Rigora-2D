"""Bounded cleanup of completed disposable catalog generations, preserving active and user data."""

import json
import re
import shutil
import time
from collections.abc import Iterable
from pathlib import Path

from rigora.application_services.illustration_cache import cached_catalog


def prune_catalogs(root: Path, protected: Iterable[Path] = (), *, keep: int = 2) -> int:
    """Remove only old completed generated siblings; return the removed generation count.

    Intended for explicit maintenance on a worker after discovery has completed.
    Current/known active generations, newest generations, unknown folders,
    staging directories and links are always retained. A seven-day grace period
    prevents recent generations from being reclaimed during ordinary upgrades.
    """
    if type(keep) is not int or keep < 1:
        raise ValueError("Retain at least one generated catalog.")
    base = root.resolve()
    guarded = {cached_catalog(root).resolve(), *(p.resolve() for p in protected)}
    candidates = []
    for path in root.glob("illustrations-*"):
        if (
            not re.fullmatch(r"illustrations-[0-9a-f]{16}", path.name)
            or path.is_symlink()
            or path.is_junction()
            or not path.is_dir()
            or path.resolve().parent != base
        ):
            continue
        marker = path / "complete.json"
        try:
            if marker.stat().st_size > 1024 * 1024:
                continue
            record = json.loads(marker.read_text(encoding="utf-8"))
            if record.get("identity") != path.name or "templates.rigpack" not in record.get(
                "pack_sha256s", {}
            ):
                continue
            candidates.append((marker.stat().st_mtime, path))
        except (OSError, ValueError, AttributeError):
            continue
    candidates.sort(key=lambda item: item[0], reverse=True)
    guarded.update(path.resolve() for _, path in candidates[:keep])
    removed = 0
    for modified, path in candidates:
        if path.resolve() in guarded or time.time() - modified < 7 * 86400:
            continue
        if path.is_symlink() or path.is_junction() or path.resolve().parent != base:
            continue
        shutil.rmtree(path)
        removed += 1
    return removed
