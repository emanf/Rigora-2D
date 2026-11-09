"""Import a planar glTF rig through Unreal's native Interchange pipeline."""

import json
from pathlib import Path

import unreal


def import_rig():
    """Import skins, skeletal animation and materials into a fresh content directory."""
    root = Path(__file__).resolve().parent
    data = json.loads((root / "rig.json").read_text(encoding="utf-8"))
    if data["format"] != "rigora.editable-rig" or data["version"] != 1:
        raise ValueError("Unsupported Rigora editable rig.")
    destination = "/Game/RigoraEditable/Character"
    if unreal.EditorAssetLibrary.does_directory_exist(destination):
        raise ValueError("Destination exists. Change destination to a fresh content folder.")
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", str(root / "character.glb"))
    task.set_editor_property("destination_path", destination)
    task.set_editor_property("automated", False)
    task.set_editor_property("replace_existing", False)
    task.set_editor_property("save", True)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    textures = {}
    for source in sorted(
        {p for part in data["parts"] for p in part.get("texture_states", [part["texture"]])}
    ):
        texture_task = unreal.AssetImportTask()
        texture_task.set_editor_property("filename", str(root / source))
        texture_task.set_editor_property("destination_path", destination + "/Textures")
        texture_task.set_editor_property("automated", True)
        texture_task.set_editor_property("replace_existing", False)
        texture_task.set_editor_property("save", True)
        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([texture_task])
        paths = texture_task.get_editor_property("imported_object_paths")
        if paths:
            textures[source] = unreal.load_asset(paths[0])
    if hasattr(unreal, "RigoraDefinition"):
        factory = unreal.DataAssetFactory()
        factory.set_editor_property("data_asset_class", unreal.RigoraDefinition)
        definition = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            "RigDefinition", destination, unreal.RigoraDefinition, factory
        )
        if definition:
            definition.set_editor_property(
                "definition_json", (root / "rig.json").read_text(encoding="utf-8")
            )
            definition.set_editor_property("textures", textures)
            unreal.EditorAssetLibrary.save_loaded_asset(definition)
    unreal.log(
        "Rigora editable glTF import submitted. Keep separate skeletal mesh parts, "
        "import morph targets/animations, and retain unlit alpha materials. "
        "When the runtime plugin is enabled, assign RigDefinition to a RigoraWardrobeComponent."
    )


import_rig()
