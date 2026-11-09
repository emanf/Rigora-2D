"""Validate real image inference and built-in keying using original, ignored review fixtures."""

import io
import json
import os
from dataclasses import replace
from pathlib import Path

from rigora.application_services.documents import DocumentService
from rigora.application_services.video_rig import VideoRigService, correct_pose
from rigora.infrastructure.video_keying import KeyingSettings, key_cutout
from rigora.infrastructure.video_models import model_directory
from rigora.infrastructure.video_rig import analyze_images, video_frame


def main() -> None:
    """Run CPU backends without a window and verify keyed pixels and edited poses."""
    from PIL import Image

    if os.name == "nt":
        import ctypes

        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x40)
    root = Path("build/video-rig-review")
    if not (root / "human-cutout.png").is_file():
        raise SystemExit("Run tools/review_video_rig.py first to generate original review footage.")
    still = analyze_images((root / "human-cutout.png",), model_directory(), profile="Human")
    assert len(still.poses) == 1
    source = still.poses[0]
    x, y, _ = source.points[9]
    corrected = correct_pose("Human", source, 9, x + 5, y - 7)
    still = replace(still, poses=(corrected,))
    document = DocumentService()
    document.new()
    alpha = key_cutout(still.image, KeyingSettings())
    output = VideoRigService(document).create(still, artwork=alpha, smoothing=0.9)
    assert not output["clip_id"] and len(document.scene.meshes) == 1
    document.save(root / "human-still.rigora", overwrite=True)
    animal = analyze_images(
        (root / "dog-cutout.png",),
        model_directory(),
        profile="Quadruped",
        region=(0.1, 0.1, 0.9, 0.9),
    )
    animal_document = DocumentService()
    animal_document.new()
    animal_output = VideoRigService(animal_document).create(animal)
    assert not animal_output["clip_id"] and animal_output["bones"] == 10
    animal_document.save(root / "dog-still.rigora", overwrite=True)
    paths = []
    for index in range(3):
        path = root / f"sequence-{index + 1}.png"
        path.write_bytes(video_frame(root / "human.mp4", index / 6))
        paths.append(path)
    sequence = analyze_images(tuple(paths), model_directory(), profile="Human", sample_fps=6)
    document = DocumentService()
    document.new()
    animated = VideoRigService(document).create(sequence)
    assert animated["clip_id"] and len(sequence.poses) == 3
    document.save(root / "human-sequence.rigora", overwrite=True)
    # A genuinely chromatic fixture exercises the built-in keying pipeline.
    image = Image.open(io.BytesIO(alpha)).convert("RGBA")
    screen = Image.new("RGBA", image.size, "#00ff00")
    screen.alpha_composite(image)
    data = io.BytesIO()
    screen.convert("RGB").save(data, format="PNG")
    keyed = key_cutout(data.getvalue(), KeyingSettings(method="Chroma", color=(0, 1, 0)))
    (root / "human-keyed.png").write_bytes(keyed)
    result = Image.open(io.BytesIO(keyed))
    assert result.getpixel((0, 0))[3] == 0
    assert result.getchannel("A").getextrema() == (0, 255)
    report = {
        "keyer": "Rigora in-process CPU",
        "still": output,
        "animal_still": animal_output,
        "sequence": animated,
        "sequence_seconds": [pose.seconds for pose in sequence.poses],
        "alpha_range": result.getchannel("A").getextrema(),
    }
    (root / "media-native-review.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
