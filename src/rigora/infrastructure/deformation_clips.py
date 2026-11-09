"""Bounded, unambiguous motion JSON and atomic publication without executable deserialization."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from rigora.domain.validation import ProjectError

MAX_MOTION_SIZE = 4 * 1024 * 1024


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate field names rather than choosing an ambiguous interpretation."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProjectError(f"Duplicate motion field: {key}.")
        result[key] = value
    return result


def read_motion(path: Path) -> dict[str, Any]:
    """Read bounded UTF-8 JSON; the application service validates motion semantics."""
    with path.open("rb") as stream:
        raw = stream.read(MAX_MOTION_SIZE + 1)
    if len(raw) > MAX_MOTION_SIZE:
        raise ProjectError("Deformation clips must be smaller than 4 MiB.")
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique)
        if not isinstance(data, dict):
            raise ProjectError("Deformation motion must contain a JSON object.")
        return data
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ProjectError(f"Invalid deformation motion JSON: {error}") from error


def write_motion(path: Path, data: dict[str, Any], *, overwrite: bool = False) -> None:
    """Flush a temporary sibling and atomically replace or publish without clobbering a file."""
    payload = (json.dumps(data, indent=2, allow_nan=False) + "\n").encode("utf-8")
    if len(payload) > MAX_MOTION_SIZE:
        raise ProjectError("Deformation clips must be smaller than 4 MiB.")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
