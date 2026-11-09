"""Optional local MediaPipe face/body detection over RGB frames; never opens a device or network."""

import math
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from rigora.application_services.tracking import TrackingSample
from rigora.domain.project import ProjectError


class LocalTracker:
    """Own optional face/pose model instances on one worker thread until explicitly closed."""

    def __init__(self, face: Path | None = None, body: Path | None = None) -> None:
        """Load host-selected local task bundles, leaving installation and model choice explicit."""
        if face is None and body is None:
            raise ProjectError("Choose a local face or body tracking model first.")
        for path in (face, body):
            if path and (not path.is_file() or not 1 <= path.stat().st_size <= 64 * 1024 * 1024):
                raise ProjectError("Tracking models must be existing local files up to 64 MiB.")
        try:
            import mediapipe as mp
        except ImportError as error:
            raise ProjectError(
                "Install the optional tracking extra to use local camera models."
            ) from error
        self.mp: Any = mp
        self.stack = ExitStack()
        self.face: Any = None
        self.body: Any = None
        self.timestamp = -1
        try:
            vision = mp.tasks.vision
            if face:
                self.face = self.stack.enter_context(
                    vision.FaceLandmarker.create_from_options(
                        vision.FaceLandmarkerOptions(
                            base_options=mp.tasks.BaseOptions(model_asset_path=str(face)),
                            running_mode=vision.RunningMode.VIDEO,
                            num_faces=1,
                            output_face_blendshapes=True,
                            output_facial_transformation_matrixes=True,
                        )
                    )
                )
            if body:
                self.body = self.stack.enter_context(
                    vision.PoseLandmarker.create_from_options(
                        vision.PoseLandmarkerOptions(
                            base_options=mp.tasks.BaseOptions(model_asset_path=str(body)),
                            running_mode=vision.RunningMode.VIDEO,
                            num_poses=1,
                        )
                    )
                )
        except Exception:
            self.close()
            raise

    def detect(self, rgb: Any, seconds: float) -> TrackingSample:
        """Detect unmirrored RGB pixels, omitting body segments with low landmark confidence."""
        import numpy as np

        if (
            rgb.dtype != np.uint8
            or rgb.ndim != 3
            or rgb.shape[2] != 3
            or not 1 <= rgb.shape[0] <= 1080
            or not 1 <= rgb.shape[1] <= 1920
        ):
            raise ProjectError("Tracking frames require RGB uint8 pixels up to 1920 × 1080.")
        timestamp = max(self.timestamp + 1, round(seconds * 1000))
        image = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        coefficients, angles = {}, {}
        if self.face:
            result = self.face.detect_for_video(image, timestamp)
            if result.face_blendshapes:
                coefficients = {c.category_name: float(c.score) for c in result.face_blendshapes[0]}
                if result.facial_transformation_matrixes:
                    matrix = result.facial_transformation_matrixes[0]
                    angles["head"] = -math.degrees(math.atan2(matrix[1][0], matrix[0][0]))
                    angles["head_yaw"] = math.degrees(
                        math.atan2(-matrix[2][0], math.hypot(matrix[0][0], matrix[1][0]))
                    )
        if self.body:
            result = self.body.detect_for_video(image, timestamp)
            if result.pose_landmarks:
                points = result.pose_landmarks[0]
                for side, indices in (
                    ("L", (11, 13, 15, 19, 23, 25, 27, 31)),
                    ("R", (12, 14, 16, 20, 24, 26, 28, 32)),
                ):
                    shoulder, elbow, wrist, hand, hip, knee, ankle, foot = indices
                    for name, a, b in (
                        ("upper_arm", shoulder, elbow),
                        ("forearm", elbow, wrist),
                        ("hand", wrist, hand),
                        ("thigh", hip, knee),
                        ("shin", knee, ankle),
                        ("foot", ankle, foot),
                    ):
                        if (
                            min(
                                points[a].visibility or 0,
                                points[b].visibility or 0,
                                points[a].presence or 0,
                                points[b].presence or 0,
                            )
                            >= 0.6
                        ):
                            dx = (points[b].x - points[a].x) * rgb.shape[1]
                            dy = (points[b].y - points[a].y) * rgb.shape[0]
                            if math.hypot(dx, dy) > 2:
                                angles[name + "." + side] = math.degrees(math.atan2(dy, dx))
                if (
                    min(
                        value
                        for i in (11, 12, 23, 24)
                        for value in (points[i].visibility or 0, points[i].presence or 0)
                    )
                    >= 0.6
                ):
                    dx = (points[11].x + points[12].x - points[23].x - points[24].x) * rgb.shape[1]
                    dy = (points[11].y + points[12].y - points[23].y - points[24].y) * rgb.shape[0]
                    if math.hypot(dx, dy) > 2:
                        angles["hips"] = angles["spine"] = math.degrees(math.atan2(dy, dx))
        self.timestamp = timestamp
        return TrackingSample(seconds, coefficients, angles)

    def close(self) -> None:
        """Release all native model resources on their owning thread."""
        self.stack.close()
