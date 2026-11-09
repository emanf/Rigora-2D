"""Shared Qt-free validation for the canonical project records."""

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Any
from uuid import UUID


class ProjectError(ValueError):
    """An invalid or unsupported project, with a user-facing explanation."""


def text(value: Any, label: str) -> str:
    """Require a nonblank UTF-8 display string containing at most 200 characters."""
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ProjectError(f"{label} must contain 1–200 characters.")
    try:
        value.encode("utf-8")
    except UnicodeError as error:
        raise ProjectError(f"{label} contains invalid Unicode.") from error
    return value


def identifier(value: Any) -> str:
    """Require a syntactically valid UUID without using a display name as identity."""
    try:
        if not isinstance(value, str):
            raise ValueError
        UUID(value)
    except ValueError as error:
        raise ProjectError("Every persistent entity must have a valid UUID.") from error
    return value


def portable_relative_path(value: str) -> str:
    """Require a canonical relative file path usable safely on Windows and POSIX hosts."""
    path, windows = PurePosixPath(value), PureWindowsPath(value)
    reserved = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
    if (
        not value
        or len(value) > 4096
        or not path.parts
        or value.endswith("/")
        or path.is_absolute()
        or windows.anchor
        or windows.drive
        or ".." in path.parts
        or path.as_posix() != value
        or any(ord(char) < 32 or char in '\\:*?"<>|' for char in value)
        or any(
            part.endswith((".", " ")) or part.split(".")[0].upper() in reserved
            for part in path.parts
        )
    ):
        raise ProjectError("Asset sources must be portable relative paths without traversal.")
    return value


def integer(value: Any, label: str, low: int, high: int) -> int:
    """Validate an inclusive integer range while rejecting booleans."""
    if type(value) is not int or not low <= value <= high:
        raise ProjectError(f"{label} must be an integer from {low} to {high}.")
    return value


def mapping(value: Any, label: str) -> dict[str, Any]:
    """Require a JSON object with string keys for structured metadata."""
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ProjectError(f"{label} must be a JSON object.")
    return value


def json_copy(value: Any) -> Any:
    """Return an independent finite JSON value or raise an actionable project error."""
    try:

        def thaw(item: Any) -> Any:
            """Convert immutable mappings and tuples into serializable JSON containers."""
            if isinstance(item, Mapping):
                if not all(isinstance(key, str) for key in item):
                    raise ValueError("JSON keys must be strings")
                return {key: thaw(val) for key, val in item.items()}
            if isinstance(item, (list, tuple)):
                return [thaw(val) for val in item]
            return item

        encoded = json.dumps(thaw(value), allow_nan=False, ensure_ascii=False).encode("utf-8")
        return json.loads(encoded)
    except (TypeError, ValueError, RecursionError, UnicodeError) as error:
        raise ProjectError("Extension fields must contain finite JSON values.") from error


@dataclass(frozen=True, slots=True, eq=False)
class _FrozenMetadata(Mapping[str, Any]):
    """Internally validated metadata that immutable record revisions can safely share."""

    _data: Mapping[str, Any]

    def __getitem__(self, key: str) -> Any:
        """Read a deeply immutable value without exposing its backing containers."""
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        """Iterate the validated JSON object keys."""
        return iter(self._data)

    def __len__(self) -> int:
        """Return the metadata object size."""
        return len(self._data)


_EMPTY_METADATA = _FrozenMetadata(MappingProxyType({}))


def frozen_extra(value: Any) -> Mapping[str, Any]:
    """Validate and deeply freeze optional JSON metadata against external mutation."""
    if not isinstance(value, Mapping):
        raise ProjectError("Extension fields must be a JSON object.")
    if isinstance(value, _FrozenMetadata):
        return value
    if not value:
        return _EMPTY_METADATA

    def freeze(item: Any) -> Any:
        """Recursively replace mutable JSON containers with read-only equivalents."""
        if isinstance(item, dict):
            return MappingProxyType({key: freeze(val) for key, val in item.items()})
        if isinstance(item, list):
            return tuple(freeze(val) for val in item)
        return item

    result: Mapping[str, Any] = _FrozenMetadata(freeze(json_copy(value)))
    return result
