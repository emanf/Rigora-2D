"""Validate optional local detectors on official fixtures without accessing camera hardware."""

import argparse
import json
import urllib.request
from pathlib import Path


def review(download: bool = False) -> None:
    """Report real detection on test images/models kept outside packaged runtime assets."""
    root = Path("build/camera-review").resolve()
    root.mkdir(parents=True, exist_ok=True)
    sources = {
        "face.task": "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task",
        "body.task": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task",
        "portrait.jpg": "https://storage.googleapis.com/mediapipe-assets/portrait.jpg",
        "pose.jpg": "https://storage.googleapis.com/mediapipe-assets/pose.jpg",
    }
    for name, url in sources.items():
        path = root / name
        if not path.exists() and download:
            with urllib.request.urlopen(url, timeout=60) as response:
                data = response.read(64 * 1024 * 1024 + 1)
            if len(data) > 64 * 1024 * 1024:
                raise ValueError("Fixture exceeds 64 MiB")
            path.write_bytes(data)
        if not path.is_file():
            raise ValueError("Missing fixture. Run with --download once: " + name)
    import numpy as np
    from PIL import Image

    from rigora.infrastructure.camera_tracking import LocalTracker

    report = {}
    for region, filename in (("face", "portrait.jpg"), ("body", "pose.jpg")):
        image = Image.open(root / filename).convert("RGB")
        image.thumbnail((960, 720))
        tracker = LocalTracker(**{region: root / (region + ".task")})
        try:
            first = tracker.detect(np.asarray(image), 0)
            tilted = tracker.detect(np.asarray(image.rotate(12)), 0.1)
            if region == "face":
                assert len(first.face) >= 40 and "head" in first.angles
                assert abs(tilted.angles["head"] - first.angles["head"]) > 5
            else:
                assert len(first.angles) >= 6
                assert any(abs(tilted.angles.get(k, v) - v) > 5 for k, v in first.angles.items())
            report[region] = {
                "coefficients": len(first.face),
                "angles": dict(first.angles),
                "tilted_angles": dict(tilted.angles),
            }
        finally:
            tracker.close()
    (root / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    review(parser.parse_args().download)
