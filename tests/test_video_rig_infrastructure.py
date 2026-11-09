"""Actual video decoding, subject continuity and atomic optional model installation."""

import hashlib
import io
import zipfile
from threading import Event

import pytest
from test_video_rig import specimen

from rigora.domain.project import ProjectError
from rigora.infrastructure import video_models, video_rig


@pytest.fixture
def clip(tmp_path):
    """Encode one original second at 24 FPS through the installed optional local codec."""
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    path = tmp_path / "clip.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 24, (320, 320))
    assert writer.isOpened()
    for _ in range(24):
        writer.write(np.full((320, 320, 3), 220, dtype=np.uint8))
    writer.release()
    return path


def test_native_decode_sampling_uses_time_grid_and_releases_worker_models(clip, monkeypatch):
    """24 FPS footage sampled at 15 Hz yields 15 timestamps, with no growing frame drift."""
    closed = []

    class Detector:
        """Substitute neural inference while retaining real decode and result validation."""

        def __init__(self, directory):
            pass

        def candidates(self, image, profile):
            return [("Human", (20.0, 10.0, 190.0, 290.0))]

        def pose(self, image, profile, box):
            return specimen().poses[0].points

        def close(self):
            closed.append(True)

    monkeypatch.setattr(video_rig, "VideoDetector", Detector)
    result = video_rig.analyze_video(clip, clip.parent, duration=1, sample_fps=15)
    assert len(result.poses) == 15 and result.profile == "Human"
    assert result.poses[-1].seconds == pytest.approx(23 / 24, abs=0.001)
    assert closed == [True]
    slower = video_rig.analyze_video(clip, clip.parent, duration=1, sample_fps=6)
    assert slower.end_seconds == pytest.approx(23 / 24, abs=0.001)
    from rigora.application_services.documents import DocumentService
    from rigora.application_services.video_rig import VideoRigService

    doc = DocumentService()
    doc.new()
    result = VideoRigService(doc).create(slower)
    source = next(c for c in doc.scene.clips if c.id == result["clip_id"])
    assert source.out_frame == pytest.approx(23, abs=0.001)
    assert video_rig.video_frame(clip, 0.5).startswith(b"\x89PNG")
    token = Event()
    with pytest.raises(ProjectError, match="cancelled"):
        video_rig.analyze_video(
            clip, clip.parent, duration=1, cancel=token, progress=lambda p, m: token.set()
        )
    assert closed == [True, True, True]


def test_subject_continuity_does_not_jump_to_a_nonoverlapping_detection(clip, monkeypatch):
    """A disappearing subject produces confidence gaps instead of another subject's motion."""

    class Detector:
        """Return a new distant detection after initial subject acquisition."""

        def __init__(self, directory):
            self.count = 0

        def candidates(self, image, profile):
            self.count += 1
            return [
                (
                    "Human",
                    (10.0, 10.0, 150.0, 200.0) if self.count == 1 else (200.0, 20.0, 310.0, 300.0),
                )
            ]

        def pose(self, image, profile, box):
            return specimen().poses[0].points

        def close(self):
            pass

    monkeypatch.setattr(video_rig, "VideoDetector", Detector)
    result = video_rig.analyze_video(clip, clip.parent, duration=1, sample_fps=6)
    assert all(point[2] == 0 for pose in result.poses[1:] for point in pose.points)
    assert any("missing" in warning for warning in result.warnings)


def test_model_download_checksums_and_existing_cache_are_atomic(tmp_path, monkeypatch):
    """Only a verified archive member replaces a model; valid cached files require no network."""
    raw = b"original ONNX fixture bytes"
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr("nested/model.onnx", raw)
        archive.writestr("../../escape.txt", b"must never be extracted")
    calls = []

    def request(url, **kwargs):
        """Provide a finite official-source response without accessing the network."""
        calls.append(url)
        response = io.BytesIO(content.getvalue())
        response.headers = {"Content-Length": str(len(content.getvalue()))}
        return response

    monkeypatch.setattr(
        video_models,
        "MODELS",
        {"tiny": ("https://example.test/model.zip", hashlib.sha256(raw).hexdigest())},
    )
    monkeypatch.setattr(video_models.urllib.request, "urlopen", request)
    video_models.install_models(tmp_path)
    assert (tmp_path / "tiny.onnx").read_bytes() == raw
    video_models.install_models(tmp_path)
    assert len(calls) == 1 and not (tmp_path.parent / "escape.txt").exists()
    monkeypatch.setattr(
        video_models, "MODELS", {"tiny": ("https://example.test/model.zip", "0" * 64)}
    )
    with pytest.raises(ProjectError, match="checksum"):
        video_models.install_models(tmp_path)
    assert (tmp_path / "tiny.onnx").read_bytes() == raw
    assert not list(tmp_path.glob("*.download"))


def test_cutout_preserves_unobserved_hair_outside_the_landmark_seed_box():
    """Segmentation may grow beyond sparse landmarks and never hard-paints skeleton strokes."""
    from dataclasses import replace

    from PIL import Image, ImageDraw

    analysis = specimen()
    poses = tuple(
        replace(pose, points=tuple((x, y + 100, score) for x, y, score in pose.points))
        for pose in analysis.poses
    )
    image = Image.new("RGB", (320, 480), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((55, 10, 145, 140), fill="#333333")
    draw.rectangle((75, 130, 125, 260), fill="#333333")
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    analysis = replace(analysis, height=480, poses=poses, image=stream.getvalue())
    output = Image.open(io.BytesIO(video_rig.reference_cutout(analysis)))
    assert output.getpixel((100, 20))[3] == 255
    assert output.getpixel((0, 479))[3] == 0


def test_image_sequence_natural_order_timing_transparency_and_cancel(tmp_path, monkeypatch):
    """Explicit stills stream through the same tracker without losing alpha or timing."""
    from PIL import Image

    paths = []
    for frame in (10, 2, 1):
        path = tmp_path / f"frame{frame}.png"
        image = Image.new("RGBA", (320, 320), (frame, frame, frame, 255))
        image.putpixel((0, 0), (0, 0, 0, 0))
        image.save(path)
        paths.append(path)
    closed, observed = [], []

    class Detector:
        def __init__(self, directory):
            pass

        def candidates(self, image, profile):
            observed.append(int(image[100, 100, 0]))
            assert tuple(image[0, 0]) == (255, 255, 255)
            return [("Human", (20.0, 10.0, 190.0, 290.0))]

        def pose(self, image, profile, box):
            return specimen().poses[0].points

        def close(self):
            closed.append(True)

    monkeypatch.setattr(video_rig, "VideoDetector", Detector)
    paths = video_rig.ordered_images(paths)
    assert [path.name for path in paths] == ["frame1.png", "frame2.png", "frame10.png"]
    result = video_rig.analyze_images(paths, tmp_path, sample_fps=12)
    assert [p.seconds for p in result.poses] == pytest.approx([0, 1 / 12, 2 / 12])
    assert result.source_fps == 12 and observed == [1, 2, 10] and closed == [True]
    rgba = Image.open(io.BytesIO(result.image))
    assert rgba.mode == "RGBA" and rgba.getpixel((0, 0))[3] == 0
    single = video_rig.analyze_images(paths[:1], tmp_path)
    assert len(single.poses) == 1 and single.end_seconds == 0
    token = Event()
    with pytest.raises(ProjectError, match="cancelled"):
        video_rig.analyze_images(paths, tmp_path, cancel=token, progress=lambda p, m: token.set())
    assert len(closed) == 3
    Image.new("RGB", (400, 320), "gray").save(paths[1])
    with pytest.raises(ProjectError, match="same canvas"):
        video_rig.analyze_images(paths, tmp_path)
    assert len(closed) == 4
