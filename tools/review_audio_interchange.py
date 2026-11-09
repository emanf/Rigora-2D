"""Build original engine smoke-test packages and a five-character speech contact sheet."""

import io
import json
import zipfile
from dataclasses import replace
from pathlib import Path

import resvg_py
from PIL import Image, ImageDraw

from rigora.application_services.asset_pipeline import AssetPipeline
from rigora.application_services.documents import DocumentService
from rigora.application_services.output import OutputService, OutputSettings
from rigora.domain.character_recipe import CHARACTER_PRESETS, MOUTH_POSES, character_preset
from rigora.domain.project import SceneSettings
from rigora.infrastructure.character_art.assembly import design, face_parts
from rigora.infrastructure.media_import import png_bytes


def review():
    """Write disposable fixtures into build/; never touch projects or installed engines."""
    root = Path("build/audio-interchange").resolve()
    root.mkdir(parents=True, exist_ok=True)
    doc = DocumentService()
    doc.new(settings=SceneSettings(width=64, height=64))
    sources = []
    for index, color in enumerate(("#dddddd", "#777777", "#333333")):
        path = root / f"fixture-{index}.png"
        image = Image.new("RGBA", (32, 32))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((2, 2, 30, 30), radius=8, fill=color)
        path.write_bytes(png_bytes(image))
        sources.append(path)
    AssetPipeline(doc).sequence(tuple(sources), fps=12)
    for engine in ("godot", "unity", "unreal"):
        path = root / f"walk-{engine}.zip"
        OutputService(lambda value: Path(value)).export(
            doc,
            str(path),
            OutputSettings(format=engine, frames=(0, 2, 4), width=64, height=64, fps=12, columns=2),
        )
        target = root / ("unity/Assets/Rigora" if engine == "unity" else engine)
        with zipfile.ZipFile(path) as archive:
            archive.extractall(target)
        checks = Path(__file__).parent / "engine_validation"
        if engine == "godot":
            (target / "validate.gd").write_bytes((checks / "validate.gd").read_bytes())
        elif engine == "unity":
            (target / "Editor/RigoraValidation.cs").write_bytes(
                (checks / "RigoraValidation.cs").read_bytes()
            )
            packages = root / "unity/Packages"
            packages.mkdir(parents=True, exist_ok=True)
            manifest = packages / "manifest.json"
            if not manifest.exists():
                manifest.write_text(
                    json.dumps(
                        {
                            "dependencies": {
                                "com.unity.modules.animation": "1.0.0",
                                "com.unity.modules.audio": "1.0.0",
                                "com.unity.modules.imageconversion": "1.0.0",
                                "com.unity.modules.jsonserialize": "1.0.0",
                            }
                        }
                    ),
                    encoding="utf-8",
                )
    for view in ("Front", "Front 3/4", "Side", "Back 3/4", "Back"):
        speech_sheet(root, view)
    (root / "review.json").write_text(
        json.dumps({"faces": 250, "engines": ["Godot", "Unity", "Unreal"]}), encoding="utf-8"
    )
    print(root)


def speech_sheet(root: Path, view: str):
    """Render every original cast viseme in one selected direction for visual comparison."""
    width, height = 180, 205
    sheet = Image.new("RGB", (width * len(MOUTH_POSES), height * 5), "#202020")
    draw = ImageDraw.Draw(sheet)
    for row, identity in enumerate(CHARACTER_PRESETS):
        for col, mouth in enumerate(MOUTH_POSES):
            recipe = replace(character_preset(identity), view=view, mouth_pose=mouth)
            artwork = "".join(face_parts(recipe, design(recipe)).values())
            svg = (
                '<svg xmlns="http://www.w3.org/2000/svg" width="180" height="180" '
                'viewBox="-120 -170 240 240"><g transform="rotate(-90)">' + artwork + "</g></svg>"
            )
            pixels = Image.open(io.BytesIO(resvg_py.svg_to_bytes(svg_string=svg))).convert("RGBA")
            sheet.paste(pixels, (col * width, row * height), pixels)
            draw.text((col * width + 6, row * height + 184), f"{identity} · {mouth}", fill="white")
    name = {
        "Front": "front",
        "Front 3/4": "front-quarter",
        "Side": "side",
        "Back 3/4": "back-quarter",
        "Back": "back",
    }[view]
    sheet.save(root / f"creator-visemes-{name}.png")


if __name__ == "__main__":
    review()
