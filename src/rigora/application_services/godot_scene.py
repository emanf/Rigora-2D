"""Native Godot 2D text scenes retaining authorable bones and separate polygon parts."""

import json
import math
import struct
from typing import Any

from rigora.domain.geometry import affine


def native_scene(definition: dict[str, Any], files: dict[str, bytes]) -> bytes:
    """Serialize first-pose native nodes; the attached runtime owns sampled playback.

    No engine installation is required to export. Nodes exist before scripts run,
    so artists can inspect/edit bones in Godot's local scene tree. Bone transforms
    use pixel-space X-right/Y-down, matching Polygon2D and canonical source UVs.
    """
    textures = {part["texture"]: "" for part in definition["parts"]}
    textures = {path: f"texture_{i}" for i, path in enumerate(textures)}
    lines = [
        f"[gd_scene load_steps={len(textures) + 2} format=3]",
        '[ext_resource type="Script" path="RigoraRig2D.gd" id="runtime"]',
        *(
            f'[ext_resource type="Texture2D" path={json.dumps(path)} id="{key}"]'
            for path, key in textures.items()
        ),
        '[node name="RigoraRig2D" type="Node2D"]',
        'script = ExtResource("runtime")',
        "use_authored_nodes = true",
        '[node name="SceneCamera" type="CanvasLayer" parent="."]',
        '[node name="Armature" type="Skeleton2D" parent="SceneCamera"]',
        '[node name="Background" type="Sprite2D" parent="SceneCamera"]',
        "centered = false",
        "z_index = -4096",
        '[node name="Lens" type="Sprite2D" parent="SceneCamera"]',
        "centered = false",
        "z_index = 4096",
    ]

    def numbers(values: Any) -> str:
        """Encode finite generated numeric arrays without losing useful subpixel precision."""
        return ", ".join(f"{v:.12g}" for v in values)

    paths: dict[int, str] = {}

    def node_path(index: int) -> str:
        """Resolve an already-validated native hierarchy by stable manifest indices."""
        if index not in paths:
            node = definition["nodes"][index]
            parent = node_path(node["parent"]) if node["parent"] >= 0 else "SceneCamera/Armature"
            paths[index] = parent + "/" + node["name"]
        return paths[index]

    for index, node in enumerate(definition["nodes"]):
        sample = node["samples"][0]
        x, y, _ = sample["translation"]
        _, _, z, w = sample["rotation"]
        sx, sy, _ = sample["scale"]
        matrix = affine(x * 100, -y * 100, -math.degrees(2 * math.atan2(z, w)), sx, sy, 0, 0)
        kind = "Bone2D" if node["kind"] == "bone" else "Node2D"
        lines.extend(
            (
                f'[node name={json.dumps(node["name"])} type="{kind}" '
                f"parent={json.dumps(node_path(index).rsplit('/', 1)[0])}]",
                f"transform = Transform2D({numbers(matrix)})",
                f"metadata/rigora_label = {json.dumps(node['label'], ensure_ascii=False)}",
            )
        )
        if kind == "Bone2D":
            lines.append(f"rest = Transform2D({numbers(matrix)})")
    order = definition["scene_samples"][0]["render_order"]
    for part in definition["parts"]:
        texture = files[part["texture"]]
        width, height = struct.unpack_from(">II", texture, 16)
        positions = [v for p in part["positions"] for v in (p["x"] * 100, -p["y"] * 100)]
        uv = [v for p in part["uv"] for v in (p["x"] * width, p["y"] * height)]
        triangles = ", ".join(
            "PackedInt32Array(" + numbers(part["triangles"][i : i + 3]) + ")"
            for i in range(0, len(part["triangles"]), 3)
        )
        lines.extend(
            (
                f'[node name={json.dumps(part["node"])} type="Polygon2D" '
                'parent="SceneCamera/Armature"]',
                f"polygon = PackedVector2Array({numbers(positions)})",
                f"uv = PackedVector2Array({numbers(uv)})",
                f"polygons = Array[PackedInt32Array]([{triangles}])",
                f'texture = ExtResource("{textures[part["texture"]]}")',
                f"visible = {str(part['states'][0]['visible']).lower()}",
                f"color = Color(1, 1, 1, {part['states'][0]['opacity']:.12g})",
                f"z_index = {order.index(part['object_id']) if part['object_id'] in order else 0}",
                f"metadata/rigora_label = {json.dumps(part['label'], ensure_ascii=False)}",
            )
        )
    return ("\n".join(lines) + "\n").encode()
