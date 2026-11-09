"""Bounded, checksummed scene collection chunks for large format-2 project packages."""

import hashlib
import json
from collections.abc import Callable
from typing import Any

from rigora.domain.entities import ENTITY_COLLECTIONS
from rigora.domain.project import ProjectError

CHUNK_FEATURE = "scene-chunks-v1"
OBJECT_CHUNK_FEATURE = "object-chunks-v1"
MAX_CHUNK_BYTES = 8 * 1024 * 1024
MAX_SCENE_BYTES = 256 * 1024 * 1024
TARGET_CHUNK_BYTES = 2 * 1024 * 1024


def split_object_data(data: dict[str, Any]) -> dict[str, bytes]:
    """Move large linked-Object definitions out of root metadata without truncating views.

    A single definition may contain several authored view snapshots. Byte segments
    avoid imposing a per-definition JSON limit; only their verified concatenation
    is decoded, preserving Unicode even across a multibyte segment boundary.
    """
    library = data.get("object_library")
    if not library:
        return {}
    raw = json.dumps(library, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    if len(raw) <= TARGET_CHUNK_BYTES:
        return {}
    if len(raw) > MAX_SCENE_BYTES:
        raise ProjectError("Object definitions exceed the 256 MiB chunk budget.")
    chunks, refs = {}, []
    for index, offset in enumerate(range(0, len(raw), TARGET_CHUNK_BYTES)):
        name = f"data/object-library/{index:04d}.part"
        chunk = raw[offset : offset + TARGET_CHUNK_BYTES]
        chunks[name] = chunk
        refs.append({"path": name, "sha256": hashlib.sha256(chunk).hexdigest()})
    data["object_library"] = {"$rigora_object_chunks": refs}
    return chunks


def restore_object_data(
    data: dict[str, Any], read: Callable[[str, int], bytes], decode: Callable[[bytes], Any]
) -> set[str]:
    """Reassemble only exact checksummed Object-definition segments, bounded before joining."""
    refs = data.get("object_library")
    if not isinstance(refs, dict) or set(refs) != {"$rigora_object_chunks"}:
        raise ProjectError("Invalid Object chunk reference.")
    refs = refs["$rigora_object_chunks"]
    if not isinstance(refs, list) or not 1 <= len(refs) <= 4096:
        raise ProjectError("Invalid Object chunk count.")
    chunks, names, total = [], set(), 0
    for index, ref in enumerate(refs):
        name = f"data/object-library/{index:04d}.part"
        if not isinstance(ref, dict) or set(ref) != {"path", "sha256"} or ref["path"] != name:
            raise ProjectError("Invalid Object chunk identity.")
        raw = read(name, MAX_CHUNK_BYTES)
        total += len(raw)
        if total > MAX_SCENE_BYTES:
            raise ProjectError("Object definitions exceed the 256 MiB chunk budget.")
        if hashlib.sha256(raw).hexdigest() != ref["sha256"]:
            raise ProjectError("Object chunk checksum does not match.")
        chunks.append(raw)
        names.add(name)
    library = decode(b"".join(chunks))
    if not isinstance(library, dict):
        raise ProjectError("Object chunks must contain a definition map.")
    data["object_library"] = library
    return names


def split_scene_data(data: dict[str, Any]) -> dict[str, bytes]:
    """Replace owned scene collection lists with references; return private encoded chunks."""
    chunks = {}
    total = 0
    for scene_index, scene in enumerate(data["scenes"]):
        for field in ENTITY_COLLECTIONS:
            records = scene.get(field, [])
            if not records:
                continue
            groups: list[list[bytes]] = [[]]
            size = 2
            for record in records:
                raw = json.dumps(
                    record, ensure_ascii=False, separators=(",", ":"), allow_nan=False
                ).encode()
                if len(raw) + 2 > MAX_CHUNK_BYTES:
                    raise ProjectError("One scene record exceeds the 8 MiB chunk limit.")
                if groups[-1] and size + len(raw) + 1 > TARGET_CHUNK_BYTES:
                    groups.append([])
                    size = 2
                groups[-1].append(raw)
                size += len(raw) + 1
            refs = []
            for index, group in enumerate(groups):
                raw = b"[" + b",".join(group) + b"]"
                total += len(raw)
                if total > MAX_SCENE_BYTES:
                    raise ProjectError("Scene data exceeds the 256 MiB limit.")
                name = f"data/{scene_index}/{field}/{index:04d}.json"
                chunks[name] = raw
                refs.append({"path": name, "sha256": hashlib.sha256(raw).hexdigest()})
            scene[field] = {"$rigora_chunks": refs}
    return chunks


def restore_scene_data(
    data: dict[str, Any], read: Callable[[str, int], bytes], decode: Callable[[bytes], Any]
) -> set[str]:
    """Restore recognized collection references and reject reused, altered or oversized chunks."""
    names: set[str] = set()
    total = 0
    scenes = data.get("scenes")
    if not isinstance(scenes, list) or any(not isinstance(scene, dict) for scene in scenes):
        raise ProjectError("Chunked projects must contain a scene list.")
    for scene_index, scene in enumerate(scenes):
        for field in ENTITY_COLLECTIONS:
            value = scene.get(field, [])
            if not isinstance(value, dict):
                continue
            if set(value) != {"$rigora_chunks"} or not isinstance(value["$rigora_chunks"], list):
                raise ProjectError("Invalid scene chunk reference.")
            refs = value["$rigora_chunks"]
            if not 1 <= len(refs) <= 4096:
                raise ProjectError("Scene collection has an invalid chunk count.")
            records = []
            for index, ref in enumerate(refs):
                name = f"data/{scene_index}/{field}/{index:04d}.json"
                if (
                    not isinstance(ref, dict)
                    or set(ref) != {"path", "sha256"}
                    or ref["path"] != name
                ):
                    raise ProjectError("Invalid scene chunk identity.")
                raw = read(name, MAX_CHUNK_BYTES)
                total += len(raw)
                if total > MAX_SCENE_BYTES:
                    raise ProjectError("Scene data exceeds the 256 MiB limit.")
                if hashlib.sha256(raw).hexdigest() != ref["sha256"]:
                    raise ProjectError("Scene chunk checksum does not match.")
                values = decode(raw)
                if not isinstance(values, list):
                    raise ProjectError("Scene chunks must contain record lists.")
                records.extend(values)
                names.add(name)
            scene[field] = records
    if not names:
        raise ProjectError("Chunked projects must reference scene data chunks.")
    return names
