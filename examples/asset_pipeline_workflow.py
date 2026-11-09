"""Import original sources, animate vectors and export transparent frames without a GUI."""

import argparse
import json
import wave
from pathlib import Path

from rigora.api import RigoraAPI
from rigora.resources import asset_path


def run(root: Path) -> dict:
    """Create a portable original study and verify exact source bytes after reopening it."""
    root.mkdir(parents=True, exist_ok=True)
    voice = root / "sample.wav"
    if voice.exists() or (root / "editable.rigora").exists():
        raise ValueError("Choose a fresh output directory; example files are never overwritten.")
    with wave.open(str(voice), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b"\0\0" * 2400)
    api = RigoraAPI(root)
    api.execute(
        "project_create", {"name": "Original vector output study", "width": 800, "height": 600}
    )
    actor = api.execute(
        "character_create", {"content": "Bolt · Stick robot", "x": 340, "y": 160}
    ).data
    source = api.execute(
        "asset_import", {"path": str(asset_path("examples/prop.svg")), "place": True}
    ).data
    api.execute("audio_import", {"path": "sample.wav"})
    api.execute(
        "object_edit",
        {
            "object_id": source["object_id"],
            "transform": {"x": 80, "y": 360, "scale_x": 0.6, "scale_y": 0.6},
        },
    )
    api.execute("motion_apply", {"content": "Natural · Walk", "target_id": actor["rig_ids"][0]})
    api.execute("deformer_apply", {"content": "Soft breathing", "mesh_id": actor["mesh_ids"][0]})
    original = {a.id: api.document.read_asset(a.id) for a in api.document.project.assets}
    frames = [0, 3, 6, 9]
    png = api.execute(
        "frame_render", {"path": "frames/study.png", "frames": frames, "width": 800, "height": 600}
    ).data
    atlas = api.execute(
        "frame_render",
        {
            "path": "atlas.png",
            "format": "spritesheet",
            "frames": frames,
            "width": 400,
            "height": 300,
            "columns": 2,
        },
    ).data
    runtime = api.execute(
        "frame_render", {"path": "animation.json", "format": "runtime-json", "frames": frames}
    ).data
    api.execute("project_export", {"path": "scene.rigpack", "format": "rigpack"})
    selected_clip = api.document.selected_clip_id
    api.execute("project_save", {"path": "editable.rigora"})
    copy = RigoraAPI(root)
    copy.execute("project_open", {"path": "editable.rigora"})
    copy.document.select_animation_clip(selected_clip)
    assert all(copy.document.read_asset(key) == data for key, data in original.items())
    assert copy.document.animation.evaluate(6).meshes == api.document.animation.evaluate(6).meshes
    assert copy.execute("project_validate").data["valid"]
    assert (
        copy.document.read_asset(source["asset_id"]) == asset_path("examples/prop.svg").read_bytes()
    )
    import sys

    assert not any(name.startswith("PySide6") for name in sys.modules)
    return {
        "project": str(root / "editable.rigora"),
        "png": png["paths"],
        "atlas": atlas["paths"],
        "runtime": runtime["paths"],
        "source_roundtrip": True,
    }


def main() -> None:
    """Run the offline acceptance study in a caller-chosen new directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("build/asset-pipeline-example"))
    args = parser.parse_args()
    print(json.dumps(run(args.output.resolve()), indent=2))


if __name__ == "__main__":
    main()
