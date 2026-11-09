"""Run in Unreal Editor to create native Paper2D assets from this adjacent sprite package."""

import json
from pathlib import Path

import unreal


def import_package():
    """Import into a fresh destination and retain ordered flipbook frames and export FPS."""
    root = Path(__file__).resolve().parent
    data = json.loads((root / "animation.json").read_text(encoding="utf-8"))
    if data["format"] != "rigora.baked-sprites" or data["version"] != 1:
        raise ValueError("Unsupported Rigora package.")
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    _, unique_name = tools.create_unique_asset_name("/Game/Rigora/" + data["name"], "")
    destination = "/Game/Rigora/" + unique_name
    if unreal.EditorAssetLibrary.does_directory_exist(destination):
        raise ValueError("Destination already exists; choose a new export name.")
    unreal.EditorAssetLibrary.make_directory(destination)
    sprites = []
    for index, frame in enumerate(data["frames"]):
        task = unreal.AssetImportTask()
        task.set_editor_property("filename", str(root / frame["path"]))
        task.set_editor_property("destination_path", destination + "/Textures")
        task.set_editor_property("automated", True)
        task.set_editor_property("save", True)
        task.set_editor_property("replace_existing", False)
        tools.import_asset_tasks([task])
        paths = task.get_editor_property("imported_object_paths")
        if not paths:
            raise RuntimeError("Texture import failed: " + frame["path"])
        texture = unreal.load_asset(paths[0])
        sprite = tools.create_asset(
            f"Frame_{index:04d}",
            destination + "/Sprites",
            unreal.PaperSprite,
            unreal.PaperSpriteFactory(),
        )
        if sprite is None:
            raise RuntimeError("PaperSprite creation failed. Enable Paper 2D.")
        sprite.set_editor_property("source_texture", texture)
        sprite.set_editor_property("source_uv", unreal.Vector2D(0, 0))
        sprite.set_editor_property(
            "source_dimension", unreal.Vector2D(data["width"], data["height"])
        )
        sprite.set_editor_property(
            "source_texture_dimension", unreal.Vector2D(data["width"], data["height"])
        )
        sprite.set_editor_property("pixels_per_unreal_unit", 100.0)
        sprite.set_editor_property("pivot_mode", unreal.SpritePivotMode.BOTTOM_CENTER)
        unreal.EditorAssetLibrary.save_loaded_asset(sprite)
        key = unreal.PaperFlipbookKeyFrame()
        key.set_editor_property("sprite", sprite)
        key.set_editor_property("frame_run", 1)
        sprites.append(key)
    flipbook = tools.create_asset(
        "Animation", destination, unreal.PaperFlipbook, unreal.PaperFlipbookFactory()
    )
    flipbook.set_editor_property("frames_per_second", data["fps"])
    flipbook.set_editor_property("key_frames", sprites)
    unreal.EditorAssetLibrary.save_loaded_asset(flipbook)
    unreal.log("Rigora flipbook imported: " + flipbook.get_path_name())
    return flipbook


import_package()
