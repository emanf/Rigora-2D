"""Publish observed video landmarks as ordinary editable rigs and FK animation clips."""

import math
from dataclasses import dataclass, replace
from functools import lru_cache

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.domain.entities import (
    AnimationClip,
    Bone,
    Character,
    Group,
    Keyframe,
    Skeleton,
    Timeline,
    Track,
    Transform,
)
from rigora.domain.geometry import affine, inverse, transform_point
from rigora.domain.project import ProjectError

type Point = tuple[float, float, float]


@dataclass(frozen=True)
class VideoPose:
    """One timestamped image-space observation; zero confidence denotes a missing joint."""

    seconds: float
    points: tuple[Point, ...]
    corrected: frozenset[int] = frozenset()

    def __post_init__(self) -> None:
        """Reject invalid detector data before constructing an editable project graph."""
        if not math.isfinite(self.seconds) or not 0 <= self.seconds <= 3600:
            raise ProjectError("Video samples need finite timestamps within one hour.")
        if len(self.points) != 17 or any(
            len(point) != 3
            or not all(math.isfinite(v) and abs(v) <= 16384 for v in point)
            or not 0 <= point[2] <= 1
            for point in self.points
        ):
            raise ProjectError("Video samples require 17 finite joints with confidence 0–1.")
        if any(type(joint) is not int or not 0 <= joint < 17 for joint in self.corrected):
            raise ProjectError("Corrected joint indices must be from 0 to 16.")


@dataclass(frozen=True)
class VideoAnalysis:
    """Bounded inference result with an embedded reference image, independent of source files."""

    profile: str
    width: int
    height: int
    source_fps: float
    poses: tuple[VideoPose, ...]
    reference: int
    image: bytes = b""
    warnings: tuple[str, ...] = ()
    end_seconds: float | None = None
    locked_lengths: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        """Enforce the shared human/quadruped layout, image and chronological sample limits."""
        if self.profile not in ("Human", "Quadruped"):
            raise ProjectError("Video rigging currently supports humans and quadruped mammals.")
        times = [pose.seconds for pose in self.poses]
        if (
            not 1 <= len(times) <= 3600
            or times != sorted(set(times))
            or not 0 <= self.reference < len(times)
            or not 1 <= self.width <= 1920
            or not 1 <= self.height <= 1080
            or not math.isfinite(self.source_fps)
            or not 0 < self.source_fps <= 1000
            or len(self.image) > 16 * 1024 * 1024
            or self.end_seconds is not None
            and (not math.isfinite(self.end_seconds) or not times[-1] <= self.end_seconds <= 3600)
        ):
            raise ProjectError("Video analysis has invalid timing, dimensions or sample limits.")
        if self.locked_lengths - segments(self.profile, self.poses[self.reference].points).keys():
            raise ProjectError("Length locks must name bones in this subject's topology.")


def segments(profile: str, points: tuple[Point, ...]) -> dict[str, tuple[str | None, Point, Point]]:
    """Map COCO-17 or APT-36K landmarks to anatomical parent/start/end segments.

    Midpoints use the weaker constituent confidence; unobserved feet, fingers,
    wings and tail tips are deliberately not invented.
    """

    def midpoint(a: Point, b: Point) -> Point:
        """Keep synthetic torso anchors conservative when one side is occluded."""
        return (a[0] + b[0]) / 2, (a[1] + b[1]) / 2, min(a[2], b[2])

    p = points
    result: dict[str, tuple[str | None, Point, Point]] = {}
    if profile == "Human":
        hip, shoulder = midpoint(p[11], p[12]), midpoint(p[5], p[6])
        center = midpoint(hip, shoulder)
        result.update(hips=(None, hip, center), spine=("hips", center, shoulder))
        result["head"] = ("spine", shoulder, p[0])
        for side, arm, leg in (("L", (5, 7, 9), (11, 13, 15)), ("R", (6, 8, 10), (12, 14, 16))):
            a, b, c = arm
            result["upper_arm." + side] = ("spine", p[a], p[b])
            result["forearm." + side] = ("upper_arm." + side, p[b], p[c])
            a, b, c = leg
            result["thigh." + side] = ("hips", p[a], p[b])
            result["shin." + side] = ("thigh." + side, p[b], p[c])
    elif profile == "Quadruped":
        result.update(body=(None, p[4], p[3]), head=("body", p[3], p[2]))
        for side, arm, leg in (("L", (5, 6, 7), (11, 12, 13)), ("R", (8, 9, 10), (14, 15, 16))):
            a, b, c = arm
            result["front." + side] = ("body", p[a], p[b])
            result["frontlower." + side] = ("front." + side, p[b], p[c])
            a, b, c = leg
            result["rear." + side] = ("body", p[a], p[b])
            result["rearlower." + side] = ("rear." + side, p[b], p[c])
    else:
        raise ProjectError("Choose Human or Quadruped video topology.")
    return result


@lru_cache(maxsize=2)
def segment_coefficients(profile: str) -> dict[str, tuple[tuple[int, float], ...]]:
    """Describe each anatomical vector as a linear combination of landmark coordinates."""
    result: dict[str, list[tuple[int, float]]] = {}
    for joint in range(17):
        basis = tuple((float(i == joint), 0.0, 1.0) for i in range(17))
        for role, (_, a, b) in segments(profile, basis).items():
            if b[0] != a[0]:
                result.setdefault(role, []).append((joint, b[0] - a[0]))
    return {role: tuple(weights) for role, weights in result.items()}


def correct_pose(
    profile: str,
    pose: VideoPose,
    joint: int,
    x: float,
    y: float,
    locked_lengths: frozenset[str] = frozenset(),
) -> VideoPose:
    """Correct one sample, projecting locked lengths onto their pre-drag values.

    Locks protect reviewed proportions against accidental resizing; they do not
    erase foreshortening already observed in other frames. Adjacent landmarks can
    move to satisfy connected constraints. Every adjusted landmark becomes an
    explicit smoothing anchor so creation preserves the reviewed pose exactly.
    """
    if not 0 <= joint < 17 or not all(math.isfinite(v) and abs(v) <= 16384 for v in (x, y)):
        raise ProjectError("Choose a valid joint and finite image coordinates.")
    points = [list(point) for point in pose.points]
    points[joint] = [x, y, 1.0]
    original = segments(profile, pose.points)
    coefficients = segment_coefficients(profile)
    constraints = []
    for role in sorted(locked_lengths):
        if role not in original:
            raise ProjectError("Choose a bone in this subject's topology.")
        _, a, b = original[role]
        if min(a[2], b[2]) > 0:
            constraints.append((coefficients[role], math.dist(a[:2], b[:2])))
    for _ in range(512):
        error = 0.0
        for weights, target in constraints:
            vx = sum(points[i][0] * w for i, w in weights)
            vy = sum(points[i][1] * w for i, w in weights)
            length = math.hypot(vx, vy)
            difference = length - target
            error = max(error, abs(difference))
            if length < 1e-9:
                # A collapsed endpoint still has a well-defined original direction.
                vx = sum(pose.points[i][0] * w for i, w in weights)
                vy = sum(pose.points[i][1] * w for i, w in weights)
                length = math.hypot(vx, vy)
                if length < 1e-9:
                    continue
            denominator = sum(w * w * (1.0 if i == joint else 0.05) for i, w in weights)
            for i, weight in weights:
                delta = difference * weight * (1.0 if i == joint else 0.05) / denominator
                points[i][0] -= delta * vx / length
                points[i][1] -= delta * vy / length
        if error < 1e-7:
            break
    else:
        raise ProjectError(
            "These length locks could not converge. Move the joint less or unlock a bone."
        )
    changed = frozenset(
        i
        for i, point in enumerate(points)
        if i == joint or math.dist(point[:2], pose.points[i][:2]) > 1e-9
    )
    return replace(
        pose,
        points=tuple((p[0], p[1], 1.0 if i in changed else p[2]) for i, p in enumerate(points)),
        corrected=pose.corrected | changed,
    )


def cleaned_poses(
    analysis: VideoAnalysis, confidence: float, smoothing: float
) -> tuple[VideoPose, ...]:
    """Interpolate gaps up to 0.25 seconds, then smooth each contiguous reliable run.

    Forward/backward exponential filtering avoids a causal timing delay. Long gaps
    retain zero confidence so publishing can hide affected branches explicitly.
    """
    if not 0.05 <= confidence <= 0.95 or not 0 <= smoothing <= 0.9:
        raise ProjectError("Confidence must be 0.05–0.95 and smoothing 0–0.9.")
    samples = [list(pose.points) for pose in analysis.poses]
    for joint in range(17):
        known = [i for i, pose in enumerate(samples) if pose[joint][2] >= confidence]
        for a, b in zip(known, known[1:], strict=False):
            if b > a + 1 and analysis.poses[b].seconds - analysis.poses[a].seconds <= 0.25:
                for index in range(a + 1, b):
                    t = (analysis.poses[index].seconds - analysis.poses[a].seconds) / (
                        analysis.poses[b].seconds - analysis.poses[a].seconds
                    )
                    x, y, score = samples[a][joint]
                    u, v, other = samples[b][joint]
                    samples[index][joint] = (x + (u - x) * t, y + (v - y) * t, min(score, other))
        for order in (range(len(samples)), range(len(samples) - 1, -1, -1)):
            last: Point | None = None
            for index in order:
                point = samples[index][joint]
                if point[2] < confidence:
                    last = None
                    continue
                if last is not None and joint not in analysis.poses[index].corrected:
                    point = (
                        point[0] * (1 - smoothing) + last[0] * smoothing,
                        point[1] * (1 - smoothing) + last[1] * smoothing,
                        point[2],
                    )
                    samples[index][joint] = point
                last = point
    return tuple(
        replace(pose, points=tuple(points))
        for pose, points in zip(analysis.poses, samples, strict=False)
    )


class VideoRigService(AnimationEditingService):
    """Create a reusable object, anatomical skeleton and sampled clip in one undo step."""

    def create(
        self,
        analysis: VideoAnalysis,
        *,
        name: str = "Video character",
        confidence: float = 0.35,
        smoothing: float = 0.25,
        artwork: bytes = b"",
    ) -> dict[str, str | int | list[str]]:
        """Preserve image-space motion as local FK channels at the destination scene FPS.

        Rest lengths come from the reference pose; editable length keys retain
        foreshortening so observed elbows/knees remain connected to their children.
        Missing branches are hidden until tracking recovers; nothing is keyed on the
        new object's scene placement, which remains independently editable.
        """
        if self.document.animation_context:
            raise ProjectError("Return to the main Scene before importing a video character.")
        if artwork:
            from rigora.infrastructure.artwork import inspect_artwork

            info = inspect_artwork(artwork)
            if info.kind != "raster" or (info.width, info.height) != (
                analysis.width,
                analysis.height,
            ):
                raise ProjectError("Reference artwork dimensions must match the analyzed video.")
        poses = cleaned_poses(analysis, confidence, smoothing)
        rest = segments(analysis.profile, poses[analysis.reference].points)
        scale = (
            min(
                self.scene.settings.width / analysis.width,
                self.scene.settings.height / analysis.height,
            )
            * 0.8
        )
        offset = (
            (self.scene.settings.width - analysis.width * scale) / 2,
            (self.scene.settings.height - analysis.height * scale) / 2,
        )

        def position(p: Point) -> tuple[float, float]:
            """Fit source image coordinates once; later object transforms carry the full rig."""
            return offset[0] + p[0] * scale, offset[1] + p[1] * scale

        group = Group(
            name=name[:200],
            transform=Transform(
                pivot_x=self.scene.settings.width / 2, pivot_y=self.scene.settings.height / 2
            ),
            extra={"object_container": True, "video_rig_profile": analysis.profile},
        )
        bones: dict[str, Bone] = {}
        matrices = {}
        skipped = []
        for role, (parent, a, b) in rest.items():
            start, end = position(a), position(b)
            length = math.dist(start, end)
            if min(a[2], b[2]) < confidence or length < 0.5 or parent and parent not in bones:
                skipped.append(role)
                continue
            angle = math.degrees(math.atan2(end[1] - start[1], end[0] - start[0]))
            matrices[role] = affine(*start, angle, 1, 1, 0, 0)
            local = transform_point(inverse(matrices[parent]), *start) if parent else start
            parent_angle = bones[parent].extra["video_world_angle"] if parent else 0
            bones[role] = Bone(
                name=role,
                parent_id=bones[parent].id if parent else None,
                length=length,
                transform=Transform(x=local[0], y=local[1], rotation=angle - parent_angle),
                extra={"role": role, "minimum_joint_angle": 0, "video_world_angle": angle},
            )
        if len(bones) < 5:
            raise ProjectError(
                "Too few reliable reference joints. Lower confidence or choose clearer footage."
            )
        rig = Skeleton(
            name=name[:190] + " rig",
            bones=tuple(bones.values()),
            extra={"object_id": group.id, "library_bind": (1, 0, 0, 1, 0, 0)},
        )
        actor = Character(name=name[:200], skeleton_id=rig.id, extra={"object_id": group.id})
        values: dict[tuple[str, str], list[float]] = {}
        previous: dict[str, tuple[float, float, float, float]] = {}
        missing = 0
        for pose in poses:
            observed = segments(analysis.profile, pose.points)
            world = {}
            visible: dict[str, bool] = {}
            for role, bone in bones.items():
                parent, a, b = observed[role]
                valid = min(a[2], b[2]) >= confidence and math.dist(a[:2], b[:2]) > 0.5
                visible[role] = valid and (parent is None or visible[parent])
                start, end = position(a), position(b)
                angle = math.degrees(math.atan2(end[1] - start[1], end[0] - start[0]))
                if valid:
                    if role in previous:
                        old = previous[role][2]
                        angle = old + (angle - old + 180) % 360 - 180
                    previous[role] = (*start, angle, math.dist(start, end))
                else:
                    missing += 1
                x, y, angle, length = previous.get(
                    role,
                    (
                        *transform_point(matrices[role], 0, 0),
                        bone.extra["video_world_angle"],
                        bone.length,
                    ),
                )
                world[role] = affine(x, y, angle, 1, 1, 0, 0)
                local = transform_point(inverse(world[parent]), x, y) if parent else (x, y)
                local_angle = (
                    angle - math.degrees(math.atan2(world[parent][1], world[parent][0]))
                    if parent
                    else angle
                )
                channel = (bone.id, "transform.rotation")
                if channel in values:
                    old = values[channel][-1]
                    local_angle = old + (local_angle - old + 180) % 360 - 180
                for path, value in (
                    ("transform.x", local[0]),
                    ("transform.y", local[1]),
                    ("transform.rotation", local_angle),
                    ("length", length),
                    ("visibility", float(visible[role])),
                ):
                    values.setdefault((bone.id, path), []).append(value)
        fps = self.scene.settings.fps
        times = [(pose.seconds - poses[0].seconds) * fps for pose in poses]
        end_frame = ((analysis.end_seconds or poses[-1].seconds) - poses[0].seconds) * fps
        tracks = tuple(
            Track(
                name=path,
                owner_id=owner,
                property_path=path,
                keyframes=tuple(
                    Keyframe(
                        frame=time,
                        value=value,
                        interpolation="step" if path == "visibility" else "linear",
                    )
                    for time, value in zip(
                        times[:1] if len(set(data)) == 1 else times,
                        data[:1] if len(set(data)) == 1 else data,
                        strict=False,
                    )
                ),
            )
            for (owner, path), data in values.items()
        )
        timeline = Timeline(name=name[:180] + " motion", tracks=tracks)
        clip = AnimationClip(
            name=name[:180] + " motion",
            timeline_id=timeline.id,
            out_frame=end_frame,
            extra={
                "object_id": group.id,
                "fk_bones": tuple(b.id for b in bones.values()),
                "video_rig": {
                    "profile": analysis.profile,
                    "source_fps": analysis.source_fps,
                    "reference_seconds": poses[analysis.reference].seconds,
                    "missing_segment_samples": missing,
                    "skipped_bones": skipped,
                },
            },
        )
        animated = len(poses) > 1
        with self.document.command_group(
            "Convert media to rig" + (" and animation" if animated else "")
        ):
            self.commit(
                "Create video rig",
                groups=(group, *self.scene.groups),
                skeletons=(*self.scene.skeletons, rig),
                characters=(*self.scene.characters, actor),
            )
            if artwork:
                from rigora.application_services.image_rigging import ImageRigService

                art = ImageRigService(self.document)
                mesh_id = art.import_image_bytes(name[:180] + ".png", artwork)
                mesh = art.mesh(mesh_id)
                art.commit(
                    "Place video artwork",
                    objects=tuple(
                        replace(
                            obj,
                            parent_id=group.id,
                            transform=Transform(
                                x=offset[0], y=offset[1], scale_x=scale, scale_y=scale
                            ),
                        )
                        if obj.id == mesh.object_id
                        else obj
                        for obj in self.scene.objects
                    ),
                )
                art.bind_image(mesh_id, next(iter(bones.values())).id)
            if animated:
                self.publish("Create media animation", timeline, clip)
                from rigora.application_services.characters import CharacterService

                CharacterService(self.document).place_motion(
                    group.id, clip.id, 0, max(0.01, end_frame / fps), repeat=False
                )
        return {
            "object_id": group.id,
            "skeleton_id": rig.id,
            "clip_id": clip.id if animated else "",
            "scene_clip_id": self.clip.id if animated and self.clip else "",
            "samples": len(poses),
            "bones": len(bones),
            "missing_segment_samples": missing,
            "skipped_bones": skipped,
        }
