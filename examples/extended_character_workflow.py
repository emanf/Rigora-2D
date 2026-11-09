"""Create editable offline examples for retargeting, vector faces, dynamics and guided rigging."""

import argparse
import json
from pathlib import Path

from rigora.api import RigoraAPI
from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.facial import FaceService
from rigora.resources import asset_path


def run(root: Path) -> dict:
    """Write only into a fresh example folder and return stable output filenames and feature IDs."""
    root.mkdir(parents=True, exist_ok=False)
    api = RigoraAPI(root)
    try:
        api.execute(
            "project_create",
            {"name": "Retarget, face and dynamics study", "width": 1280, "height": 720},
        )
        source = api.execute(
            "character_create", {"content": "Dash · Runner", "x": 350, "y": 320}
        ).data
        target = api.execute(
            "character_create", {"content": "Scout · Explorer", "x": 850, "y": 320}
        ).data
        api.execute(
            "motion_apply", {"content": "Natural · Walk", "target_id": source["rig_ids"][0]}
        )
        clip = AnimationEditingService(api.document).clip
        assert clip is not None
        transferred = api.execute(
            "motion_retarget",
            {
                "source_clip": clip.id,
                "source_skeleton": source["rig_ids"][0],
                "target_skeleton": target["rig_ids"][0],
                "profile": "Human",
            },
        ).data
        scene = api.document.project.scenes[0]
        target_rig = next(r for r in scene.skeletons if r.id == target["rig_ids"][0])
        child = next(b for b in target_rig.bones if b.parent_id and "forearm" in b.name.casefold())
        root_bone = next(b for b in target_rig.bones if b.parent_id is None)
        api.execute(
            "dynamics_configure",
            {"bones": [child.id], "gravity": 140, "damping": 0.4, "frequency": 2},
        )
        api.execute(
            "bounce_apply",
            {"owner": root_bone.id, "preset": "Soft bounce", "height": 70, "duration": 48},
        )
        baked = api.execute("dynamics_bake").data["clip_id"]
        face = api.execute("face_create", {"x": 160, "y": 150}).data["face_id"]
        api.execute("face_controls", {"face_id": face, "frame": 0, "expression": "Happy"})
        api.execute(
            "lip_sync_set",
            {
                "face_id": face,
                "cues": [
                    {"seconds": 0, "phoneme": "Rest"},
                    {"seconds": 0.2, "phoneme": "M"},
                    {"seconds": 0.4, "phoneme": "AH"},
                    {"seconds": 0.7, "phoneme": "O"},
                    {"seconds": 1, "phoneme": "Rest"},
                ],
            },
        )
        FaceService(api.document).blink(face, 24)
        api.execute("project_save", {"path": "extended-character.rigora"})
        api.execute(
            "character_template_save",
            {
                "path": "extended-character.rigpack",
                "name": "Extended character study",
                "author": "Rigora",
                "license": "Mixed; see source asset notices",
            },
        )
        api.execute(
            "frame_render",
            {"path": "preview.svg", "frames": [0, 12, 24], "width": 960, "height": 540},
        )
        report = {
            "project": "extended-character.rigora",
            "pack": "extended-character.rigpack",
            "retargeted_clip": transferred["clip_id"],
            "baked_clip": baked,
            "face_id": face,
        }
    finally:
        api.close()
    guide = RigoraAPI(root)
    try:
        guide.execute(
            "project_create", {"name": "Guided SVG character", "width": 960, "height": 720}
        )
        meshes = list(
            guide.execute(
                "character_parts_import",
                {"paths": [str(asset_path("examples/prop.svg"))]},
            ).data["mesh_ids"]
        )
        rig = guide.execute("character_rig_generate", {"template": "Biped", "meshes": meshes}).data[
            "rig_id"
        ]
        guide.execute("character_mesh_generate", {"meshes": meshes, "columns": 8, "rows": 10})
        guide.execute("character_bind", {"rig_id": rig, "meshes": meshes})
        guide.execute("project_save", {"path": "guided-character.rigora"})
        report["guided_project"] = "guided-character.rigora"
    finally:
        guide.close()
    (root / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    """Parse a fresh destination folder and run the canonical feature examples offline."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.root.resolve()), indent=2))


if __name__ == "__main__":
    main()
