"""Evaluated editor/game collision regions, separate from rendered artwork geometry."""

import math
from collections.abc import Mapping
from typing import Any

from rigora.domain.geometry import transform_point
from rigora.domain.project import ProjectError, Scene
from rigora.engine.sampling import number
from rigora.engine.state import ScenePose


def game_regions(scene: Scene, pose: ScenePose) -> list[dict[str, Any]]:
    """Return enabled hit/hurt regions in world space at the exact sampled timeline frame."""
    result = []
    for obj in scene.objects:
        data = obj.extra.get("game_region")
        node = pose.nodes.get(obj.id)
        if not data or node is None or obj.id not in pose.region_owners:
            continue
        if not isinstance(data, Mapping) or not {"width", "height", "shape", "type"} <= data.keys():
            raise ProjectError("Game regions require typed shape and dimension metadata.")
        width, height = number(data["width"]), number(data["height"])
        if (
            not 0 < width <= 1e6
            or not 0 < height <= 1e6
            or data["shape"] not in ("rectangle", "ellipse")
            or data["type"] not in ("hitbox", "hurtbox")
            or not isinstance(data.get("payload", {}), Mapping)
        ):
            raise ProjectError("Game region metadata contains unsupported bounds or shape data.")
        points = (
            tuple(
                (width * math.cos(i * math.tau / 32) / 2, height * math.sin(i * math.tau / 32) / 2)
                for i in range(32)
            )
            if data["shape"] == "ellipse"
            else (
                (-width / 2, -height / 2),
                (width / 2, -height / 2),
                (width / 2, height / 2),
                (-width / 2, height / 2),
            )
        )
        result.append(
            {
                "id": obj.id,
                "name": obj.name,
                "type": data["type"],
                "shape": data["shape"],
                "group": data.get("group", ""),
                "enabled": node.visible and node.opacity > 0,
                "points": [transform_point(node.world_matrix, *p) for p in points],
                "payload": dict(data.get("payload", {})),
            }
        )
    return result
