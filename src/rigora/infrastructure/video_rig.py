"""Local RTMLib video inference with bounded decoding and subject identity continuity."""

import hashlib
import io
import math
import re
from collections.abc import Callable
from pathlib import Path
from threading import Event
from typing import Any

from rigora.application_services.video_rig import VideoAnalysis, VideoPose, segments
from rigora.domain.project import ProjectError
from rigora.infrastructure.video_models import MODELS, check_cancel

IMAGE_EXTENSIONS = frozenset((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"))


def ordered_images(paths: list[Path]) -> tuple[Path, ...]:
    """Sort explicitly selected images by natural filename order, without scanning folders."""
    return tuple(
        sorted(
            paths,
            key=lambda p: tuple(
                (0, int(part)) if part.isdigit() else (1, part.casefold())
                for part in re.split(r"(\d+)", str(p))
            ),
        )
    )


def image_frame(path: Path) -> bytes:
    """Decode one bounded still image, preserving transparency and applying EXIF orientation."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    if not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
        raise ProjectError("Choose an existing image up to 64 MiB.")
    try:
        with Image.open(path) as source:
            width, height = source.size
            if (
                not 1 <= width <= 8192
                or not 1 <= height <= 8192
                or width * height > 34_000_000
                or getattr(source, "n_frames", 1) != 1
            ):
                raise ProjectError(
                    "Images need one frame, dimensions up to 8192 and at most 34 megapixels. "
                    "Expand animated images into a sequence first."
                )
            image = ImageOps.exif_transpose(source).convert("RGBA")
            image.thumbnail((1280, 720), Image.Resampling.LANCZOS)
            stream = io.BytesIO()
            image.save(stream, format="PNG")
            return stream.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ProjectError("The selected image cannot be decoded safely.") from error


def overlap(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """Score bounding-box continuity without silently selecting another nearby subject."""
    area = max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - area
    return area / union if union > 0 else 0


class VideoDetector:
    """Load only explicit local models; never invoke RTMLib's automatic network downloads."""

    def __init__(self, directory: Path) -> None:
        """Validate a complete installed bundle before initializing native inference resources."""
        if any(not (directory / (key + ".onnx")).is_file() for key in MODELS):
            raise ProjectError("Install the video pose models before analyzing a clip.")
        for key, (_, checksum) in MODELS.items():
            path = directory / (key + ".onnx")
            if not 1 <= path.stat().st_size <= 512 * 1024 * 1024:
                raise ProjectError("A video model has an invalid size. Repair the local models.")
            with path.open("rb") as source:
                if hashlib.file_digest(source, "sha256").hexdigest() != checksum:
                    raise ProjectError("A video model checksum differs. Repair the local models.")
        try:
            from rtmlib import YOLOX, RTMPose, ViTPose
        except ImportError as error:
            raise ProjectError(
                "Install video support: uv sync --extra gui --extra video-rig --extra render"
            ) from error
        self.directory = directory
        self.classes: dict[str, Any] = {
            "human_detector": YOLOX,
            "animal_detector": YOLOX,
            "human_pose": RTMPose,
            "animal_pose": ViTPose,
        }
        self.models: dict[str, Any] = {}

    def model(self, key: str) -> Any:
        """Initialize a lazy CPU model using upstream pre/postprocessing and bounded threads.

        Replacing the initial session with configured ORT options keeps the published
        RTMLib constructor contract while preventing each model from occupying every
        logical CPU during offline conversion. Both sessions stay on this worker.
        """
        if key not in self.models:
            import onnxruntime as ort

            path = str(self.directory / (key + ".onnx"))
            arguments: dict[str, Any] = {"backend": "onnxruntime", "device": "cpu"}
            if key.endswith("detector"):
                arguments.update(model_input_size=(640, 640), score_thr=0.35)
                if key == "animal_detector":
                    arguments["det_mode"] = "multiclass"
            model = self.classes[key](path, **arguments)
            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            options.inter_op_num_threads = 1
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            model.session = ort.InferenceSession(
                path, sess_options=options, providers=["CPUExecutionProvider"]
            )
            self.models[key] = model
        return self.models[key]

    def candidates(self, image: Any, profile: str) -> list[tuple[str, tuple[float, ...]]]:
        """Find supported subjects, combining HumanArt people and COCO mammals in Auto mode."""
        candidates = []
        if profile in ("Auto", "Quadruped"):
            boxes, labels = self.model("animal_detector")(image)
            for box, label in zip(boxes, labels, strict=False):
                if 15 <= int(label) <= 23:
                    candidates.append(("Quadruped", tuple(float(v) for v in box[:4])))
        if profile in ("Auto", "Human"):
            for box in self.model("human_detector")(image):
                candidates.append(("Human", tuple(float(v) for v in box[:4])))
        return sorted(
            candidates,
            key=lambda item: (item[1][2] - item[1][0]) * (item[1][3] - item[1][1]),
            reverse=True,
        )

    def pose(
        self, image: Any, profile: str, box: tuple[float, ...]
    ) -> tuple[tuple[float, float, float], ...]:
        """Return the canonical COCO-17 or APT-36K layout with finite clipped confidence."""
        key = "human_pose" if profile == "Human" else "animal_pose"
        points, scores = self.model(key)(image, bboxes=[list(box)])
        if points.shape != (1, 17, 2) or scores.shape != (1, 17):
            raise ProjectError(
                "The installed pose model does not return the expected 17-joint layout."
            )
        return tuple(
            (float(p[0]), float(p[1]), min(1.0, max(0.0, float(score))))
            for p, score in zip(points[0], scores[0], strict=False)
        )

    def close(self) -> None:
        """Release native sessions on the inference worker, including cancellation paths."""
        self.models.clear()


def observe_frame(
    detector: VideoDetector,
    image: Any,
    profile: str,
    previous_box: tuple[float, ...] | None,
    subject: int,
    guided: bool,
) -> tuple[str, tuple[float, ...] | None, tuple[tuple[float, float, float], ...], bool]:
    """Share acquisition and spatial identity continuity between videos and image sequences."""
    candidates = [] if guided else detector.candidates(image, profile)
    chosen: tuple[str, tuple[float, ...]] | None
    if guided and previous_box:
        chosen = (profile, previous_box)
    elif previous_box is None:
        chosen = candidates[subject] if len(candidates) > subject else None
    else:
        candidates = [c for c in candidates if c[0] == profile]
        anchor = previous_box
        chosen = max(candidates, key=lambda c: overlap(anchor, c[1]), default=None)
        if chosen and overlap(previous_box, chosen[1]) < 0.05:
            chosen = None
    if not chosen:
        return profile, previous_box, ((0.0, 0.0, 0.0),) * 17, True
    profile, previous_box = chosen
    points = detector.pose(image, profile, previous_box)
    missing = False
    if guided:
        reliable = [p for p in points if p[2] >= 0.35]
        if len(reliable) >= 10:
            left, top = min(p[0] for p in reliable), min(p[1] for p in reliable)
            right, bottom = max(p[0] for p in reliable), max(p[1] for p in reliable)
            padding = max(right - left, bottom - top) * 0.25
            previous_box = (
                max(0, left - padding),
                max(0, top - padding),
                min(image.shape[1], right + padding),
                min(image.shape[0], bottom + padding),
            )
        else:
            missing = True
    return profile, previous_box, points, missing


def analyze_images(
    paths: tuple[Path, ...],
    directory: Path,
    *,
    profile: str = "Auto",
    sample_fps: float = 15,
    subject: int = 0,
    region: tuple[float, float, float, float] | None = None,
    cancel: Event | None = None,
    progress: Callable[[float, str], None] = lambda value, message: None,
) -> VideoAnalysis:
    """Infer one still pose or a timed image sequence while retaining one RGBA reference.

    Paths are consumed in the supplied order. Frames must share a canvas; they
    are decoded one at a time and never accumulated into a raster atlas.
    """
    import cv2
    import numpy as np
    from PIL import Image

    if (
        not 1 <= len(paths) <= 3600
        or len(set(paths)) != len(paths)
        or not math.isfinite(sample_fps)
        or not 1 <= sample_fps <= 30
        or len(paths) / sample_fps > 120
        or not 0 <= subject <= 19
        or profile not in ("Auto", "Human", "Quadruped")
    ):
        raise ProjectError(
            "Choose 1–3600 unique images, subject 1–20 and 1–30 frames/s, up to 120 seconds."
        )
    if region is not None and (
        profile == "Auto"
        or len(region) != 4
        or not all(math.isfinite(v) and 0 <= v <= 1 for v in region)
        or region[2] - region[0] < 0.01
        or region[3] - region[1] < 0.01
    ):
        raise ProjectError("Choose Human or Quadruped and a valid normalized subject region.")
    cancel = cancel or Event()
    check_cancel(cancel)
    detector = VideoDetector(directory)
    samples = []
    reference, best_score, reference_image = 0, -1.0, b""
    size: tuple[int, int] | None = None
    previous_box: tuple[float, ...] | None = None
    missed = 0
    try:
        for index, path in enumerate(paths):
            check_cancel(cancel)
            png = image_frame(path)
            with Image.open(io.BytesIO(png)) as rgba:
                if size is None:
                    size = rgba.size
                    if region:
                        previous_box = (
                            region[0] * size[0],
                            region[1] * size[1],
                            region[2] * size[0],
                            region[3] * size[1],
                        )
                elif rgba.size != size:
                    raise ProjectError(
                        "All sequence images must share the same canvas size. "
                        "Pad frames to a common canvas before import."
                    )
                background = Image.new("RGBA", rgba.size, "white")
                background.alpha_composite(rgba.convert("RGBA"))
                image = cv2.cvtColor(np.asarray(background.convert("RGB")), cv2.COLOR_RGB2BGR)
            profile, previous_box, points, missing = observe_frame(
                detector,
                image,
                profile,
                previous_box,
                subject,
                region is not None,
            )
            check_cancel(cancel)
            missed += int(missing)
            samples.append(VideoPose(index / sample_fps, points))
            if profile != "Auto" and any(p[2] > 0 for p in points):
                confidences = [min(a[2], b[2]) for _, a, b in segments(profile, points).values()]
                quality = min(confidences) + sum(confidences) / len(confidences)
                if quality > best_score:
                    best_score, reference, reference_image = quality, index, png
            progress(
                (index + 1) / len(paths),
                f"Analyzing image {index + 1} of {len(paths)} · {missed} weak subjects",
            )
        if not reference_image or size is None:
            raise ProjectError(
                "No supported subject was tracked. "
                "Draw a subject area and choose Human or Quadruped."
            )
        warnings = [
            "Only observed body joints are recovered; hidden layers and anatomy need authoring."
        ]
        if missed:
            warnings.append(f"Tracking was weak or missing in {missed} of {len(samples)} images.")
        if region:
            warnings.append(
                "A selected region guided pose tracking; subject classification was explicit."
            )
        return VideoAnalysis(
            profile,
            *size,
            sample_fps,
            tuple(samples),
            reference,
            reference_image,
            tuple(warnings),
            (len(samples) - 1) / sample_fps,
        )
    finally:
        detector.close()


def analyze_video(
    path: Path,
    directory: Path,
    *,
    profile: str = "Auto",
    start: float = 0,
    duration: float = 10,
    sample_fps: float = 15,
    subject: int = 0,
    region: tuple[float, float, float, float] | None = None,
    cancel: Event | None = None,
    progress: Callable[[float, str], None] = lambda value, message: None,
) -> VideoAnalysis:
    """Decode a selected 0.1–120 second local clip and track one subject into image-space poses.

    Presentation timestamps drive sampling when provided by the decoder; nominal FPS
    is only a fallback. Raw frames are streamed, retaining one best reference image.
    Subject identity is locked by profile and overlapping detections after acquisition.
    """
    if (
        profile not in ("Auto", "Human", "Quadruped")
        or not all(math.isfinite(v) for v in (start, duration, sample_fps))
        or not 0 <= start <= 3480
        or not 0.1 <= duration <= 120
        or not 1 <= sample_fps <= 30
        or not 0 <= subject <= 19
    ):
        raise ProjectError(
            "Choose subject 1–20, start within 58 minutes, "
            "a 0.1–120 second range and 1–30 samples/s."
        )
    if not path.is_file() or path.stat().st_size > 4 * 1024**3:
        raise ProjectError("Choose an existing local video up to 4 GiB.")
    if region is not None and (
        profile == "Auto"
        or len(region) != 4
        or not all(math.isfinite(v) and 0 <= v <= 1 for v in region)
        or region[2] - region[0] < 0.01
        or region[3] - region[1] < 0.01
    ):
        raise ProjectError("Choose Human or Quadruped and a valid normalized subject region.")
    try:
        import cv2
    except ImportError as error:
        raise ProjectError(
            "Install the optional video-rig extra before importing video."
        ) from error
    cancel = cancel or Event()
    check_cancel(cancel)
    capture = cv2.VideoCapture(str(path))
    detector: VideoDetector | None = None
    try:
        if not capture.isOpened():
            raise ProjectError(
                "The local video decoder cannot open this clip. Try an MP4, MOV, AVI or WebM file."
            )
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        width, height = (
            int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        )
        if (
            not math.isfinite(fps)
            or not 0 < fps <= 1000
            or not 1 <= width <= 8192
            or not 1 <= height <= 8192
            or width * height > 34_000_000
        ):
            raise ProjectError("Video dimensions or frame rate exceed the decoder limits.")
        detector = VideoDetector(directory)
        capture.set(cv2.CAP_PROP_POS_MSEC, start * 1000)
        scale = min(1.0, 1280 / width, 720 / height)
        size = (max(1, round(width * scale)), max(1, round(height * scale)))
        samples: list[VideoPose] = []
        best_score, reference, reference_image = -1.0, 0, b""
        next_time, last_timestamp, frame_index = start, start - 1, 0
        source_end = 0.0
        previous_box: tuple[float, ...] | None = (
            (region[0] * size[0], region[1] * size[1], region[2] * size[0], region[3] * size[1])
            if region
            else None
        )
        selected_profile = profile
        missed = 0
        while len(samples) < 3600:
            check_cancel(cancel)
            if frame_index > math.ceil((duration + 2) * fps) + 10:
                raise ProjectError("Video decoder did not advance within the requested time range.")
            ok, image = capture.read()
            if not ok:
                break
            timestamp = float(capture.get(cv2.CAP_PROP_POS_MSEC)) / 1000
            if not math.isfinite(timestamp) or timestamp <= last_timestamp:
                timestamp = start + frame_index / fps
            frame_index += 1
            last_timestamp = timestamp
            if timestamp >= start + duration - 1e-6:
                break
            source_end = max(0.0, timestamp - start)
            if timestamp + 1e-6 < next_time:
                continue
            while next_time <= timestamp + 1e-6:
                next_time += 1 / sample_fps
            image = cv2.resize(image, size)
            selected_profile, previous_box, points, missing = observe_frame(
                detector,
                image,
                selected_profile,
                previous_box,
                subject,
                region is not None,
            )
            check_cancel(cancel)
            missed += int(missing)
            samples.append(VideoPose(max(0.0, timestamp - start), points))
            if any(p[2] > 0 for p in points):
                # Prefer a reference with an entire connected skeleton, not one strong limb.
                confidences = [
                    min(a[2], b[2]) for _, a, b in segments(selected_profile, points).values()
                ]
                quality = min(confidences) + sum(confidences) / len(confidences)
                if quality > best_score:
                    best_score, reference = quality, len(samples) - 1
                    success, encoded = cv2.imencode(".png", image)
                    if not success:
                        raise ProjectError("Cannot encode the video reference image.")
                    reference_image = encoded.tobytes()
            progress(
                min(0.99, max(0, timestamp - start) / duration),
                f"Analyzing {timestamp - start:.1f}s · {len(samples)} poses · "
                f"{missed} missing subjects",
            )
        if len(samples) < 2:
            raise ProjectError(
                "The range needs at least two sampled frames. Increase its length or sample rate."
            )
        if not reference_image:
            raise ProjectError(
                "No supported subject was tracked. Choose another range or subject, "
                "or draw a subject area and choose Human/Quadruped."
            )
        warnings = [
            "Only the selected subject is converted. Hidden artwork and clothing "
            "layers cannot be recovered from RGB video."
        ]
        if region:
            warnings.append(
                "A selected region guided pose tracking; subject classification was explicit."
            )
        if missed:
            warnings.append(
                f"Tracking was weak or missing in {missed} of {len(samples)} samples; "
                "review gaps before creating the rig."
            )
        progress(1, "Analysis complete. Review tracking before creating a character.")
        end_seconds = max(samples[-1].seconds, source_end)
        return VideoAnalysis(
            selected_profile,
            *size,
            fps,
            tuple(samples),
            reference,
            reference_image,
            tuple(warnings),
            end_seconds,
        )
    finally:
        capture.release()
        if detector:
            detector.close()


def reference_cutout(analysis: VideoAnalysis) -> bytes:
    """Extract a best-effort reference cutout with pose-seeded OpenCV GrabCut.

    This is an editable raster mesh source, not recovered layered clothing or unseen
    pixels. Complex backgrounds and overlapping characters need author cleanup.
    """
    import cv2
    import numpy as np

    image = cv2.imdecode(np.frombuffer(analysis.image, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ProjectError("Video reference image is missing or invalid.")
    mask = np.full(image.shape[:2], cv2.GC_PR_BGD, dtype=np.uint8)
    points = analysis.poses[analysis.reference].points
    reliable = [p for p in points if p[2] >= 0.35]
    if len(reliable) < 5:
        raise ProjectError("Not enough reliable joints for reference extraction.")
    x0, y0 = min(p[0] for p in reliable), min(p[1] for p in reliable)
    x1, y1 = max(p[0] for p in reliable), max(p[1] for p in reliable)
    padding = max(x1 - x0, y1 - y0) * 0.2
    left, top = max(1, int(x0 - padding)), max(1, int(y0 - padding))
    right, bottom = (
        min(image.shape[1] - 1, int(x1 + padding)),
        min(image.shape[0] - 1, int(y1 + padding)),
    )
    if right <= left or bottom <= top:
        raise ProjectError("The reference subject is outside the image.")
    mask[top:bottom, left:right] = cv2.GC_PR_FGD
    thickness = max(2, int(min(right - left, bottom - top) * 0.025))
    for _, a, b in segments(analysis.profile, points).values():
        if min(a[2], b[2]) >= 0.35:
            cv2.line(mask, (int(a[0]), int(a[1])), (int(b[0]), int(b[1])), cv2.GC_PR_FGD, thickness)
    # Definite background around the full image avoids invalid GrabCut initialization.
    mask[[0, -1], :] = cv2.GC_BGD
    mask[:, [0, -1]] = cv2.GC_BGD
    cv2.grabCut(
        image, mask, (0, 0, 0, 0), np.zeros((1, 65)), np.zeros((1, 65)), 4, cv2.GC_INIT_WITH_MASK
    )
    rgba = cv2.cvtColor(image, cv2.COLOR_BGR2BGRA)
    rgba[:, :, 3] = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(
        np.uint8
    )
    ok, png = cv2.imencode(".png", rgba)
    if not ok:
        raise ProjectError("Cannot encode the extracted character reference.")
    return bytes(png)


def video_frame(path: Path, seconds: float) -> bytes:
    """Read one bounded review frame off-thread; no video handle outlives the request."""
    import cv2

    if not path.is_file() or not math.isfinite(seconds) or not 0 <= seconds <= 3600:
        raise ProjectError("Choose a local video frame within the first hour.")
    capture = cv2.VideoCapture(str(path))
    try:
        width, height = (
            capture.get(cv2.CAP_PROP_FRAME_WIDTH),
            capture.get(cv2.CAP_PROP_FRAME_HEIGHT),
        )
        if not 1 <= width <= 8192 or not 1 <= height <= 8192 or width * height > 34_000_000:
            raise ProjectError("Video dimensions exceed the review frame limit.")
        capture.set(cv2.CAP_PROP_POS_MSEC, seconds * 1000)
        ok, frame = capture.read()
        if not ok:
            raise ProjectError("The decoder cannot read this review frame.")
        ratio = min(1, 1280 / width, 720 / height)
        frame = cv2.resize(frame, (round(width * ratio), round(height * ratio)))
        ok, png = cv2.imencode(".png", frame)
        if not ok:
            raise ProjectError("Cannot encode the review frame.")
        return bytes(png)
    finally:
        capture.release()
