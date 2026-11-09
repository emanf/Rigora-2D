"""Prepare weighted and wardrobe fixtures for hidden, native Unity Editor validation."""

import argparse
import json
import shutil
import tempfile
import zipfile
from dataclasses import replace
from pathlib import Path

import resvg_py

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.appearance import AppearanceService
from rigora.application_services.cameras import CameraService
from rigora.application_services.character_creation import CharacterCreationService, build_character
from rigora.application_services.documents import DocumentService
from rigora.application_services.game_authoring import GameAuthoringService
from rigora.application_services.image_rigging import ImageRigService
from rigora.application_services.output import OutputService, OutputSettings
from rigora.application_services.rendering import svg_frame
from rigora.domain.character_recipe import character_preset
from rigora.domain.geometry import transform_point


def prepare(project: Path) -> None:
    """Write only fixture assets/scripts into an existing disposable Unity project."""
    assets = project / "Assets"
    if not (project / "ProjectSettings/ProjectVersion.txt").is_file():
        raise ValueError("Create a disposable Unity project first.")
    weighted = DocumentService()
    weighted.new()
    image = ImageRigService(weighted)
    mesh = image.import_image_bytes(
        "body.svg",
        b'<svg xmlns="http://www.w3.org/2000/svg" width="320" height="480">'
        b'<rect width="320" height="480" fill="#888888"/></svg>',
        2,
        2,
    )
    first = image.draw_bone(mesh, (850, 400), (950, 400))
    second = image.draw_bone(mesh, (950, 400), (1050, 400), first)
    edit = AnimationEditingService(weighted)
    edit.key(second, "transform.rotation", 0, 10)
    edit.key(second, "transform.rotation", 12, 70)
    stage = AppearanceService(weighted).ensure(mesh)
    edit.key(stage, "parameters.tint.amount", 0, 0, interpolation="step")
    edit.key(stage, "parameters.tint.amount", 12, 0.8, interpolation="step")
    edit.key(stage, "parameters.tint.g", 0, 0)
    edit.key(stage, "parameters.tint.b", 0, 0)
    edit.marker("Start", 0, event_type="signal", payload={"value": 1})
    edit.marker("Footstep", 6, event_type="footstep", payload={"surface": "stone"})
    edit.marker("End", 12, event_type="signal", payload={"value": 2})
    game = GameAuthoringService(weighted)
    game.emitter(x=900, y=400, settings=dict(rate=2, lifetime=2, speed=0, size=4))
    cameras = CameraService(weighted)
    second_camera = cameras.add("Close shot")
    cameras.update(second_camera, background_mode="color", background_color="#222222")
    edit.key(second_camera, "transform.x", 0, 35)
    edit.key(second_camera, "transform.rotation", 12, 15)
    cameras.activate(second_camera, frame=6)
    cameras.action(second_camera, "rain", "camera_effect", 0, 12)
    character = DocumentService()
    character.new()
    recipe = replace(character_preset("Mina"), motions=("Walk · Natural",))
    CharacterCreationService(character).create(build_character(recipe))
    for name, doc in (("EditableWeighted", weighted), ("EditableRig", character)):
        frames = (0, 6, 12)
        expected = {"frames": []}
        for frame in frames:
            pose = doc.animation.evaluate(frame)
            parts = []
            for source in pose.meshes.values():
                points = [
                    transform_point(pose.nodes[source.object_id].world_matrix, *p)
                    for p in source.positions
                ]
                parts.append(
                    {
                        "name": "rigora_part_" + source.id.replace("-", ""),
                        "vertices": [{"x": x / 100, "y": -y / 100, "z": 0} for x, y in points],
                    }
                )
            expected["frames"].append({"parts": parts})
        target = assets / name
        target.mkdir(parents=True, exist_ok=True)
        print(f"Preparing {name}", flush=True)
        with tempfile.TemporaryDirectory(prefix="rigora-validation-", dir=project) as temporary:
            package = Path(temporary) / "rig.zip"
            OutputService(Path).export(
                doc,
                str(package),
                OutputSettings(format="unity-rig", frames=frames, width=256, height=256),
            )
            with zipfile.ZipFile(package) as archive:
                for entry in archive.infolist():
                    # Compile one shared copy of the scripts, even with multiple exported rigs.
                    if not entry.filename.startswith(("Runtime/", "Editor/")):
                        archive.extract(entry, target)
        (target / "expected.json").write_text(json.dumps(expected), encoding="utf-8")
        if name == "EditableWeighted":
            (project / "expected-scene.png").write_bytes(
                resvg_py.svg_to_bytes(
                    svg_string=svg_frame(doc, 6, width=256, height=144).decode(),
                    skip_system_fonts=True,
                )
            )
    root = Path(__file__).resolve().parents[2]
    adapter = root / "assets/exporters/unity/rig"
    for directory in ("Runtime", "Editor"):
        shutil.copytree(adapter / directory, assets / "Rigora" / directory, dirs_exist_ok=True)
    for name in ("RigoraEditableValidation.cs", "RigoraSceneValidation.cs"):
        shutil.copyfile(Path(__file__).with_name(name), assets / "Rigora/Editor" / name)
    print(f"Unity native fixtures ready: {project}")


def check_render(project: Path) -> None:
    """Reject blank, misplaced or wrongly scaled native renders against canonical pixels."""
    from PIL import Image, ImageChops, ImageStat

    with (
        Image.open(project / "rendered-scene.png") as rendered,
        Image.open(project / "expected-scene.png") as expected,
    ):
        if rendered.size != expected.size:
            raise ValueError("Native render dimensions differ from the canonical image.")
        a, b = rendered.convert("RGBA"), expected.convert("RGBA")
        error = ImageStat.Stat(ImageChops.difference(a, b)).mean
        if max(error) > 1:
            raise ValueError(f"Native scene render differs from canonical pixels: {error}")
        report = {"mean_rgba_error_0_255": error, "size": a.size, "result": "passed"}
        (project / "render-validation.json").write_text(json.dumps(report), encoding="utf-8")
        print(json.dumps(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--check-render", action="store_true")
    options = parser.parse_args()
    (check_render if options.check_render else prepare)(options.project.resolve())
