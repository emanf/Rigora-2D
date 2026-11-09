"""Explicit additive migrations for supported project package versions."""

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from rigora.domain.entities import ENTITY_COLLECTIONS, ProjectSettings
from rigora.domain.validation import ProjectError, json_copy

CURRENT_VERSION = 2
Migration = Callable[[dict[str, Any], dict[str, Any]], tuple[dict[str, Any], dict[str, Any]]]


def _v1_to_v2(
    manifest: dict[str, Any], project: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Add authoring collections while retaining original identities and optional fields."""
    project.setdefault("settings", ProjectSettings().to_dict())
    for key in ("assets", "asset_references", "extensions"):
        project.setdefault(key, [])
    scenes = project.get("scenes")
    if not isinstance(scenes, list):
        raise ProjectError("Legacy project scenes must be a list.")
    for scene in scenes:
        if not isinstance(scene, dict):
            raise ProjectError("Legacy scene must be an object.")
        for key in (*ENTITY_COLLECTIONS, "draw_order"):
            scene.setdefault(key, [])
    manifest["format_version"] = 2
    manifest["migrated_from"] = 1
    return manifest, project


MIGRATIONS: Mapping[int, Migration] = MappingProxyType({1: _v1_to_v2})


def migrate_document(
    manifest: dict[str, Any], project: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Upgrade copies through registered versions without mutating loaded source data."""
    metadata, data = json_copy(manifest), json_copy(project)
    version = metadata.get("format_version")
    if type(version) is not int or version < 1 or version > CURRENT_VERSION:
        raise ProjectError("Unsupported project format version; use a compatible Rigora release.")
    while version < CURRENT_VERSION:
        migration = MIGRATIONS.get(version)
        if migration is None:
            raise ProjectError(f"No migration is available from project version {version}.")
        metadata, data = migration(metadata, data)
        next_version = metadata["format_version"]
        if next_version != version + 1:
            raise ProjectError("Project migration did not advance exactly one version.")
        version = next_version
    _upgrade_spring_metadata(data)
    return metadata, data


def _upgrade_spring_metadata(project: dict[str, Any]) -> None:
    """Add stable display identities to legacy named Springs without altering motion or settings.

    This additive version-2 upgrade changes only the decoded copy; older files
    and unknown fields remain untouched until an explicit save.
    """
    scenes = project.get("scenes", [])
    if not isinstance(scenes, list):
        return
    for scene in scenes:
        if not isinstance(scene, dict) or "spring_group_metadata" in scene:
            continue
        constraints = scene.get("constraints", [])
        if not isinstance(constraints, list):
            continue
        names = [
            c.get("spring_group", "Default")
            for c in constraints
            if isinstance(c, dict) and c.get("kind") == "spring"
        ]
        if not names:
            continue
        names.extend(
            scene.get("spring_groups", [])
            if isinstance(scene.get("spring_groups", []), list)
            else []
        )
        if any(not isinstance(name, str) or not 1 <= len(name) <= 100 for name in names):
            raise ProjectError("Legacy Spring groups need names of 1–100 characters.")
        scene["spring_group_metadata"] = {
            name: {
                "id": str(uuid5(NAMESPACE_URL, f"rigora:spring:{scene.get('id')}:{name}")),
                "color": "#bcbcbc",
            }
            for name in dict.fromkeys(names)
        }
