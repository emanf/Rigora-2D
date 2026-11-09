"""Self-contained baked sprite packages with native Godot resources and editor import tools."""

import io
import json
import math
import re
import zipfile
from collections.abc import Sequence
from typing import Any

from rigora.domain.project import ProjectError
from rigora.infrastructure.media_import import png_bytes
from rigora.resources import asset_path

GAME_FORMATS = ("godot", "unity", "unreal")


def sprite_package(
    kind: str,
    name: str,
    images: Sequence[Any],
    *,
    fps: float,
    loop: bool,
    columns: int,
    source_frames: tuple[float, ...],
    events: list[dict[str, Any]] | None = None,
    regions: list[dict[str, Any]] | None = None,
) -> bytes:
    """Encode rendered samples, timing, native adapter and usage notes as one atomic ZIP.

    Poses are baked: no engine-side bones, constraints or wardrobe swapping are implied.
    The ordered PNGs are retained for adapters that do not support atlas subresources.
    """
    from PIL import Image

    if kind not in GAME_FORMATS or not images:
        raise ProjectError("Choose a supported game engine and at least one frame.")
    name = re.sub(r"[^A-Za-z0-9_]", "_", name)[:64].strip("_") or "Animation"
    width, height = images[0].size
    columns = min(columns, len(images))
    atlas = Image.new("RGBA", (columns * width, math.ceil(len(images) / columns) * height))
    files: dict[str, bytes] = {}
    frames = []
    for index, image in enumerate(images):
        x, y = index % columns * width, index // columns * height
        atlas.paste(image, (x, y))
        path = f"frames/frame_{index:04d}.png"
        files[path] = png_bytes(image)
        frames.append(
            {"path": path, "rect": [x, y, width, height], "source_frame": source_frames[index]}
        )
    files["atlas.png"] = png_bytes(atlas)
    manifest = {
        "format": "rigora.baked-sprites",
        "version": 1,
        "engine": kind,
        "name": name,
        "fps": fps,
        "loop": loop,
        "width": width,
        "height": height,
        "frames": frames,
        "pivot": "bottom-center",
        "duration_seconds": len(images) / fps,
        "events": events or [],
        "regions": regions or [],
        "region_coordinates": "source scene pixels; independent of baked camera projection",
    }
    files["animation.json"] = json.dumps(manifest, indent=2).encode()
    if kind == "godot":
        files["animation.tscn"] = godot_scene(frames, name, fps, loop, width, height).encode()
        files["project.godot"] = (
            'config_version=5\n[application]\nconfig/name="Rigora animation"\n'
            'run/main_scene="res://animation.tscn"\n[display]\n'
            f"window/size/viewport_width={width}\nwindow/size/viewport_height={height}\n"
            '[rendering]\nrenderer/rendering_method="gl_compatibility"\n'
            "environment/defaults/default_clear_color=Color(0.12, 0.12, 0.12, 1)\n"
        ).encode()
        instructions = (
            "Godot 4: open project.godot to preview, or copy this folder into your project "
            "and instantiate animation.tscn. Its SpriteFrames and AtlasTexture resources are "
            "editable. Keep atlas.png beside animation.tscn. Frames use a bottom-center pivot."
        )
    elif kind == "unity":
        files["Editor/RigoraSpriteImporter.cs"] = asset_path(
            "exporters/unity/RigoraSpriteImporter.cs"
        ).read_bytes()
        instructions = (
            "Unity 2022.3 / 6: extract this folder under Assets. Wait for scripts to compile, "
            "then choose Tools > Rigora > Import sprite animation and select this folder. "
            "The importer creates an AnimationClip, AnimatorController and SpriteRenderer prefab "
            "in a new Generated folder. No existing assets are overwritten. 100 pixels = 1 unit."
        )
    else:
        files["import_rigora.py"] = asset_path("exporters/unreal/import_rigora.py").read_bytes()
        instructions = (
            "Unreal Engine 5: enable Paper 2D, Python Editor Script Plugin and Editor Scripting "
            "Utilities. Extract the ZIP, then run import_rigora.py using Tools > Execute Python "
            "Script. It imports textures, creates PaperSprites and a PaperFlipbook under a new "
            "/Game/Rigora folder. Place the flipbook in your level; set Looping on its component "
            "according to animation.json. 100 pixels = 1 Unreal unit."
        )
    files["README.txt"] = (
        instructions
        + "\n\nTransparent baked visual animation only. Bones, editable meshes, clothing "
        "variants, triggers and audio are not engine runtime data in this package. Retain the "
        "original .rigora project for further edits. Resample/export each action separately.\n"
    ).encode()
    if sum(map(len, files.values())) > 128 * 1024 * 1024:
        raise ProjectError("Game package exceeds the 128 MiB decoded file budget.")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, data in files.items():
            archive.writestr(path, data)
    return output.getvalue()


def godot_scene(
    frames: list[dict[str, Any]],
    name: str,
    fps: float,
    loop: bool,
    width: int,
    height: int,
) -> str:
    """Build a relocatable Godot 4 scene with explicit atlas regions and ordered frames."""
    lines = [
        f"[gd_scene load_steps={len(frames) + 3} format=3]",
        '[ext_resource type="Texture2D" path="atlas.png" id="1"]',
    ]
    for index, frame in enumerate(frames):
        x, y, w, h = frame["rect"]
        lines.extend(
            (
                f'[sub_resource type="AtlasTexture" id="Frame_{index}"]',
                'atlas = ExtResource("1")',
                f"region = Rect2({x}, {y}, {w}, {h})",
            )
        )
    entries = ",\n".join(
        f'{{"duration": 1.0, "texture": SubResource("Frame_{i}")}}' for i in range(len(frames))
    )
    lines.extend(
        (
            '[sub_resource type="SpriteFrames" id="Frames"]',
            f'animations = [{{"frames": [{entries}], "loop": {str(loop).lower()}, '
            f'"name": &"{name}", "speed": {fps}}}]',
            '[node name="Animation" type="AnimatedSprite2D"]',
            f"position = Vector2({width / 2}, {height})",
            f"offset = Vector2(0, {-height / 2})",
            'sprite_frames = SubResource("Frames")',
            f'animation = &"{name}"',
            f'autoplay = "{name}"',
        )
    )
    return "\n\n".join(lines) + "\n"
