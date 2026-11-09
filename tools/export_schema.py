"""Export structural JSON Schemas from the canonical validated authoring dataclasses."""

import json
import types
from collections.abc import Mapping
from dataclasses import MISSING, fields, is_dataclass
from pathlib import Path
from typing import Any, Literal, get_args, get_origin, get_type_hints

from rigora.domain.entities import Entity
from rigora.domain.project import Project, Scene, SceneSettings
from rigora.infrastructure.migrations import CURRENT_VERSION


def project_schema() -> dict[str, Any]:
    """Describe JSON structure; the domain validator additionally enforces graph semantics."""
    definitions: dict[str, Any] = {}

    def describe(hint: Any) -> dict[str, Any]:
        """Translate one field annotation into a schema, registering nested record definitions."""
        origin, args = get_origin(hint), get_args(hint)
        if hint is Any:
            return {}
        if hint is type(None):
            return {"type": "null"}
        if hint in (str, int, float, bool):
            return {"type": {str: "string", int: "integer", float: "number", bool: "boolean"}[hint]}
        if origin is types.UnionType:
            return {"anyOf": [describe(kind) for kind in args]}
        if origin is Literal:
            return {"enum": list(args)}
        if origin is Mapping:
            return {"type": "object"}
        if origin is tuple:
            if len(args) == 2 and args[1] is Ellipsis:
                return {"type": "array", "items": describe(args[0]), "maxItems": 100000}
            return {
                "type": "array",
                "prefixItems": [describe(kind) for kind in args],
                "minItems": len(args),
                "maxItems": len(args),
            }
        if isinstance(hint, type) and is_dataclass(hint):
            name = hint.__name__
            if name not in definitions:
                definitions[name] = {}
                hints = get_type_hints(hint)
                properties = {
                    item.name: describe(hints[item.name])
                    for item in fields(hint)
                    if item.name != "extra"
                }
                required = [
                    item.name
                    for item in fields(hint)
                    if item.default is MISSING and item.default_factory is MISSING
                ]
                if issubclass(hint, Entity):
                    required.append("id")
                if hint in (Project, Scene):
                    required = ["id", "name", "scenes" if hint is Project else "settings"]
                if hint is SceneSettings:
                    required = ["width", "height", "fps", "start_frame", "end_frame"]
                for key, value in properties.items():
                    if key == "id":
                        value["format"] = "uuid"
                    if key == "name":
                        value.update(minLength=1, maxLength=200, pattern=r"\S")
                if hint is Project:
                    properties["scenes"].update(minItems=1, maxItems=100)
                if hint is SceneSettings:
                    for key, maximum in (("width", 16384), ("height", 16384), ("fps", 240)):
                        properties[key].update(minimum=1, maximum=maximum)
                    for key in ("start_frame", "end_frame"):
                        properties[key].update(minimum=0, maximum=10000000)
                definitions[name] = {
                    "type": "object",
                    "description": hint.__doc__,
                    "properties": properties,
                    "required": required,
                    "additionalProperties": True,
                }
            return {"$ref": f"#/$defs/{name}"}
        raise TypeError(f"Unsupported schema field annotation: {hint}")

    root = describe(Project)
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:rigora:project:v2",
        "title": "Rigora project data v2",
        "$comment": "Cross-reference, uniqueness, geometry, and range semantics are enforced "
        "by Project.from_dict; see docs/project-format.md.",
        **root,
        "$defs": definitions,
    }


def export(directory: Path) -> None:
    """Write project and manifest schemas into the requested documentation directory."""
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:rigora:manifest:v2",
        "title": "Rigora package manifest v2",
        "type": "object",
        "required": ["format", "format_version", "project_file", "project_id", "required_features"],
        "properties": {
            "format": {"const": "rigora"},
            "format_version": {"const": CURRENT_VERSION},
            "project_file": {"const": "project.json"},
            "project_id": {"type": "string", "format": "uuid"},
            "created_with": {"type": "string"},
            "required_features": {"type": "array", "maxItems": 0},
        },
        "additionalProperties": True,
    }
    for name, data in (
        ("project-v2.schema.json", project_schema()),
        ("manifest-v2.schema.json", manifest),
    ):
        (directory / name).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    export(Path(__file__).resolve().parents[1] / "docs" / "schema")
