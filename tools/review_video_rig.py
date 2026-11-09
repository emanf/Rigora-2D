"""Exercise real local inference on original Rigora animations; never opens a GUI or device."""

import io
import json
import os
from pathlib import Path
from time import perf_counter

from rigora.application_services.character_creation import build_character
from rigora.application_services.characters import CharacterService
from rigora.application_services.content_library import ContentService
from rigora.application_services.documents import DocumentService
from rigora.application_services.rendering import svg_frame
from rigora.application_services.video_rig import VideoRigService
from rigora.domain.character_recipe import CharacterRecipe
from rigora.domain.project import SceneSettings
from rigora.infrastructure.content_packs import read_pack
from rigora.infrastructure.video_models import model_directory
from rigora.infrastructure.video_rig import analyze_video, reference_cutout
from rigora.resources import asset_path


def main() -> None:
    """Render owned fixtures, decode video, run real models and save editable reviewed projects."""
    import cv2
    import numpy as np
    import resvg_py
    from PIL import Image

    if os.name == "nt":
        import ctypes

        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x40)
    directory = Path("build/video-rig-review")
    directory.mkdir(parents=True, exist_ok=True)
    human = build_character(
        CharacterRecipe(name="Video review human", view="Front", motions=("Walk · Natural",))
    )
    animal_pack, animal_files = read_pack(asset_path("library/studio-animals.rigpack"))
    animal = next(item for item in animal_pack.items if "Dog" in item.name and "Side" in item.name)
    report = []
    for name, profile, item, files in (
        ("human", "Human", human.item, human.files),
        ("dog", "Quadruped", animal, animal_files),
    ):
        doc = DocumentService()
        doc.new(settings=SceneSettings(width=640, height=640))
        doc.separated_animation = True
        ContentService(doc).place(item, files, position=(320, 320))
        root = CharacterService(doc).scene_objects()[0]
        actions = CharacterService(doc).motions(root)
        if actions:
            source = actions[0]
            CharacterService(doc).place_motion(root, source.id, 0, 2, repeat=True)
        path = directory / (name + ".mp4")
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 12, (640, 640))
        if not writer.isOpened():
            raise RuntimeError("Cannot encode the original test clip.")
        try:
            for i in range(24):
                data = resvg_py.svg_to_bytes(
                    svg_string=svg_frame(doc, i * 2, width=640, height=640).decode()
                )
                image = Image.open(io.BytesIO(data)).convert("RGBA")
                background = Image.new("RGBA", image.size, "white")
                background.alpha_composite(image)
                writer.write(cv2.cvtColor(np.array(background.convert("RGB")), cv2.COLOR_RGB2BGR))
                if i == 0:
                    background.save(directory / (name + "-source.png"))
        finally:
            writer.release()
        started = perf_counter()
        try:
            analysis = analyze_video(
                path,
                model_directory(),
                profile=profile,
                duration=2,
                sample_fps=6,
                region=(0.1, 0.1, 0.9, 0.9) if profile == "Quadruped" else None,
                progress=lambda p, m, name=name: print(name, round(p * 100), m, flush=True),
            )
            converted = DocumentService()
            converted.new(settings=SceneSettings(width=640, height=640))
            converted.separated_animation = True
            cutout = reference_cutout(analysis)
            result = VideoRigService(converted).create(analysis, artwork=cutout)
            converted.save(directory / (name + ".rigora"), overwrite=True)
            (directory / (name + "-cutout.png")).write_bytes(cutout)
            (directory / (name + "-reference.png")).write_bytes(analysis.image)
            (directory / (name + "-analysis.json")).write_text(
                json.dumps(
                    {
                        "profile": analysis.profile,
                        "width": analysis.width,
                        "height": analysis.height,
                        "source_fps": analysis.source_fps,
                        "reference": analysis.reference,
                        "end_seconds": analysis.end_seconds,
                        "poses": [
                            {"seconds": pose.seconds, "points": pose.points}
                            for pose in analysis.poses
                        ],
                        "warnings": analysis.warnings,
                    }
                ),
                encoding="utf-8",
            )
            for frame in (0, 12, 24, 36):
                preview = resvg_py.svg_to_bytes(
                    svg_string=svg_frame(
                        converted, frame, width=640, height=640, bones=True
                    ).decode()
                )
                (directory / f"{name}-rig-{frame}.png").write_bytes(preview)
            scores = [p[2] for sample in analysis.poses for p in sample.points]
            report.append(
                {
                    "subject": name,
                    "result": result,
                    "mean_joint_confidence": sum(scores) / len(scores),
                    "warnings": analysis.warnings,
                    "seconds": perf_counter() - started,
                }
            )
        except Exception as error:
            report.append(
                {"subject": name, "error": str(error), "seconds": perf_counter() - started}
            )
        print(json.dumps(report[-1]), flush=True)
    (directory / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
