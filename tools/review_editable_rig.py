"""Generate a canonical character and native editor fixtures for editable export review."""

import json
import zipfile
from dataclasses import replace
from pathlib import Path

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.character_creation import CharacterCreationService, build_character
from rigora.application_services.documents import DocumentService
from rigora.application_services.image_rigging import ImageRigService
from rigora.application_services.output import OutputService, OutputSettings
from rigora.domain.character_recipe import character_preset
from rigora.domain.geometry import transform_point


def fixture(doc, frames, root, engines):
    """Export canonical expected vertices beside each engine's unmodified package."""
    root.mkdir(parents=True, exist_ok=True)
    expected = {"frames": []}
    for frame in frames:
        pose = doc.animation.evaluate(frame)
        parts = []
        for mesh in pose.meshes.values():
            points = [
                transform_point(pose.nodes[mesh.object_id].world_matrix, *point)
                for point in mesh.positions
            ]
            parts.append(
                {
                    "name": "rigora_part_" + mesh.id.replace("-", ""),
                    "vertices": [{"x": x / 100, "y": -y / 100, "z": 0} for x, y in points],
                }
            )
        expected["frames"].append({"parts": parts})
    for engine in engines:
        path = root / (engine + ".zip")
        result = OutputService(lambda value: Path(value)).export(
            doc,
            str(path),
            OutputSettings(format=engine + "-rig", frames=frames, width=1024, height=1024),
        )
        target = root / engine
        with zipfile.ZipFile(path) as archive:
            archive.extractall(target)
        (target / "expected.json").write_text(json.dumps(expected), encoding="utf-8")
        print(engine, result["bytes"])


def review():
    """Keep a complete character and a true multi-influence skin fixture under build/."""
    root = Path("build/editable-rig-review").resolve()
    doc = DocumentService()
    doc.new()
    recipe = replace(character_preset("Mina"), motions=("Walk · Natural",))
    CharacterCreationService(doc).create(build_character(recipe))
    fixture(doc, (0, 12, 24), root, ("godot", "unity", "unreal"))
    weighted = DocumentService()
    weighted.new()
    service = ImageRigService(weighted)
    mesh = service.import_image_bytes(
        "original.svg",
        b'<svg xmlns="http://www.w3.org/2000/svg" width="320" height="480">'
        b'<rect width="320" height="480" fill="#888"/></svg>',
        2,
        2,
    )
    first = service.draw_bone(mesh, (850, 400), (950, 400))
    second = service.draw_bone(mesh, (950, 400), (1050, 400), first)
    editor = AnimationEditingService(weighted)
    editor.key(second, "transform.rotation", 0, 10)
    editor.key(second, "transform.rotation", 12, 70)
    fixture(weighted, (0, 6, 12), root / "weighted", ("unity", "godot"))
    checks = Path(__file__).parent / "engine_validation"
    (root / "godot/validate.gd").write_bytes((checks / "editable_rig.gd").read_bytes())


if __name__ == "__main__":
    review()
