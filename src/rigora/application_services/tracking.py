"""Calibrated camera controls and bounded editable performance takes without Qt or a detector."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from types import MappingProxyType

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.commands import ScenePatch
from rigora.application_services.documents import DocumentService
from rigora.application_services.facial import FaceService
from rigora.domain.entities import Keyframe, Timeline, Track
from rigora.domain.object_views import VIEW_SLOTS, view_partitions
from rigora.domain.project import ProjectError
from rigora.engine.sampling import number
from rigora.engine.state import ScenePose

type Channel = tuple[str, str]


@dataclass(frozen=True)
class TrackingSample:
    """One timestamped detector result; absent channels mean tracking was lost for that region."""

    seconds: float
    face: Mapping[str, float] = field(default_factory=dict)
    angles: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Reject nonfinite or excessive detector data before any mapping or document edit."""
        if not 0 <= number(self.seconds) <= 3600:
            raise ProjectError("Camera samples must lie within one hour of their session start.")
        for values, low, limit in ((self.face, 0, 1), (self.angles, -360, 360)):
            if not isinstance(values, Mapping) or len(values) > 64:
                raise ProjectError("Tracking samples support at most 64 channels per region.")
            for key, value in values.items():
                if not isinstance(key, str) or len(key) > 80 or not low <= number(value) <= limit:
                    raise ProjectError("Tracking channels require bounded names and finite values.")
        object.__setattr__(self, "face", MappingProxyType(dict(self.face)))
        object.__setattr__(self, "angles", MappingProxyType(dict(self.angles)))


class TrackingMapping:
    """Resolve one face/character onto ordinary scalar channels, preserving original proportions."""

    def __init__(self, document: DocumentService, target: str, *, turns: bool = False) -> None:
        """Capture the selected rest pose and membership without altering its rig or sources."""
        if document.project is None:
            raise ProjectError("Open a project before camera tracking.")
        self.document, self.target = document, target
        scene = document.scene
        root = next((g for g in scene.groups if g.id == target), None)
        self.face = FaceService(document).face(target) if root and "face" in root.extra else {}
        self.rig = next(
            (
                r
                for r in scene.skeletons
                if r.id == target
                or r.extra.get("object_id") == target
                or any(b.id == self.face.get("parent_bone") for b in r.bones)
            ),
            None,
        )
        if not self.face and self.rig is None:
            raise ProjectError("Choose a face rig or a character with a human skeleton.")
        self.pose = document.animation.pose
        self.bones = {b.name: b for b in self.rig.bones} if self.rig else {}
        if parent := next(
            (b for b in self.bones.values() if b.id == self.face.get("parent_bone")), None
        ):
            self.bones.setdefault("head", parent)
        self.bone_names = {b.id: b.name for b in self.bones.values()}
        self.view_owner, self.turn = "", 0
        if turns:
            root = root or next(
                (g for g in scene.groups if self.rig and g.id == self.rig.extra.get("object_id")),
                None,
            )
            if document.animation_context or root is None or not root.extra.get("view_slots"):
                raise ProjectError(
                    "Use turn detection in Scene with authored Front, Front 3/4 "
                    "and Side Object views."
                )
            partitions = view_partitions(scene, root)
            if not all(partitions[v] for v in ("Front", "Front 3/4", "Side")):
                raise ProjectError(
                    "Author Front, Front 3/4 and Side in Object Editor before turn detection."
                )
            self.view_owner = root.id
        self.eye_variants: dict[str, tuple[str, ...]] = {}
        meshes = {m.id: m.object_id for m in scene.meshes}
        for group in root.extra.get("outfits", ()) if root else ():
            if group.get("name") == "Eye pose":
                self.eye_variants = {
                    v["name"]: tuple(v.get("visibility_roots", ()))
                    or tuple(owner for k in v["meshes"] if (owner := meshes.get(k)))
                    for v in group["variants"]
                }

    def channels(self, sample: TrackingSample, neutral: TrackingSample) -> dict[Channel, float]:
        """Map calibrated planar angles, visible mouth shapes, eyelids, gaze and eyebrows."""
        values: dict[Channel, float] = {}
        if self.view_owner and "head_yaw" in sample.angles and "head_yaw" in neutral.angles:
            yaw = abs(sample.angles["head_yaw"] - neutral.angles["head_yaw"])
            # Hysteresis prevents camera noise from flickering between adjacent authored views.
            if self.turn == 0 and yaw > 25:
                self.turn = 2 if yaw > 65 else 1
            elif self.turn == 1:
                self.turn = 0 if yaw < 15 else 2 if yaw > 65 else 1
            elif self.turn == 2 and yaw < 55:
                self.turn = 0 if yaw < 15 else 1
            values[self.view_owner, "object.view"] = float(
                VIEW_SLOTS.index(("Front", "Front 3/4", "Side")[self.turn])
            )
        for name, angle in sample.angles.items():
            bone = self.bones.get(name)
            if bone is None or name not in neutral.angles:
                continue
            delta = (angle - neutral.angles[name] + 180) % 360 - 180
            parent = bone.parent_id
            while parent is not None and parent in self.bone_names:
                parent_name = self.bone_names[parent]
                if parent_name in sample.angles and parent_name in neutral.angles:
                    delta -= (
                        sample.angles[parent_name] - neutral.angles[parent_name] + 180
                    ) % 360 - 180
                    break
                parent = self.bones[parent_name].parent_id
            values[bone.id, "transform.rotation"] = self.pose.nodes[bone.id].local.rotation + max(
                -100, min(100, delta)
            )
        if not sample.face or not self.face:
            return values
        if not self.bones and "head" in sample.angles and "head" in neutral.angles:
            values[self.target, "transform.rotation"] = self.pose.nodes[
                self.target
            ].local.rotation + max(-45, min(45, sample.angles["head"] - neutral.angles["head"]))
        coefficients = {key: value - neutral.face.get(key, 0) for key, value in sample.face.items()}
        jaw = coefficients.get("jawOpen", 0)
        mouth = (
            "WQ"
            if coefficients.get("mouthPucker", 0) > 0.35
            else "O"
            if coefficients.get("mouthFunnel", 0) > 0.35
            else "MBP"
            if max(coefficients.get("mouthPressLeft", 0), coefficients.get("mouthPressRight", 0))
            > 0.35
            else "AI"
            if jaw > 0.14
            else "E"
            if max(coefficients.get("mouthSmileLeft", 0), coefficients.get("mouthSmileRight", 0))
            > 0.4
            else "Rest"
        )
        for name, owner in self.face["mouths"].items():
            values[owner, "visibility"] = float(name == mouth)
        blink = max(
            0,
            min(1, max(coefficients.get("eyeBlinkLeft", 0), coefficients.get("eyeBlinkRight", 0))),
        )
        for owner in (*self.face.get("eyes", ()), *self.face.get("pupils", ())):
            values[owner, "transform.scale_y"] = max(0.04, 1 - blink)
        if self.eye_variants:
            selected = "Closed" if blink > 0.55 else "Open"
            for name, owners in self.eye_variants.items():
                for owner in owners:
                    values[owner, "visibility"] = float(name == selected)
        for side, owner in enumerate(self.face.get("pupils", ())):
            suffix = "Left" if side == 0 else "Right"
            gaze = (
                coefficients.get("eyeLookOut" + suffix, 0)
                - coefficients.get("eyeLookIn" + suffix, 0)
            ) * (-1 if side == 0 else 1)
            vertical = coefficients.get("eyeLookDown" + suffix, 0) - coefficients.get(
                "eyeLookUp" + suffix, 0
            )
            node = self.pose.nodes[owner].local
            values[owner, "transform.x"] = node.x + max(-1, min(1, gaze)) * 10
            values[owner, "transform.y"] = node.y + max(-1, min(1, vertical)) * 7
        for side, owner in enumerate(self.face.get("brows", ())):
            suffix = "Left" if side == 0 else "Right"
            lift = coefficients.get("browInnerUp", 0) + coefficients.get("browOuterUp" + suffix, 0)
            down = coefficients.get("browDown" + suffix, 0)
            values[owner, "transform.rotation"] = self.pose.nodes[owner].local.rotation + (
                down - lift
            ) * 15 * (-1 if side else 1)
        return values


def publish_frames(
    document: DocumentService, frames: Sequence[tuple[float, Mapping[Channel, float]]]
) -> None:
    """Publish one bounded take, retaining keys outside each captured channel's interval."""
    if not 1 <= len(frames) <= 600 or sum(len(v) for _, v in frames) > 30000:
        raise ProjectError("Camera takes support 600 samples and 30,000 scalar keys.")
    if any(number(f) < 0 for f, _ in frames) or any(
        a[0] >= b[0] for a, b in zip(frames, frames[1:], strict=False)
    ):
        raise ProjectError("Camera take frames must be nonnegative and strictly increasing.")
    editor = AnimationEditingService(document)
    timeline = editor.timeline or Timeline(name="Camera performance")
    clip = editor.clip or replace(
        editor.blank_clip(timeline, "Camera performance"),
        in_frame=frames[0][0],
        out_frame=frames[-1][0],
    )
    by_channel: dict[Channel, dict[float, Keyframe]] = {}
    for frame, values in frames:
        for channel, value in values.items():
            if document.animation_scope is not None and channel[0] not in document.animation_scope:
                raise ProjectError("Open this character in Object Editor or return to Scene first.")
            by_channel.setdefault(channel, {})[frame] = Keyframe(
                frame=frame,
                value=number(value),
                interpolation="step" if channel[1] in ("visibility", "object.view") else "linear",
            )
    if not by_channel:
        raise ProjectError("No compatible face/body channels were captured.")
    tracks = list(timeline.tracks)
    for (owner, path), captured in by_channel.items():
        track = next(
            (t for t in tracks if (t.owner_id, t.property_path) == (owner, path)),
            Track(
                name="Camera · " + path,
                owner_id=owner,
                property_path=path,
                extra={"view_owner": owner, "active_from_first_key": True}
                if path == "object.view"
                else {},
            ),
        )
        editor.editable(track)
        low, high = min(captured), max(captured)
        keys = {k.frame: k for k in track.keyframes if k.frame < low or k.frame > high}
        keys.update(captured)
        updated = replace(track, keyframes=tuple(keys[f] for f in sorted(keys)))
        tracks = [updated if t.id == track.id else t for t in tracks]
        if not any(t.id == updated.id for t in tracks):
            tracks.append(updated)
    editor.publish(
        "Record camera performance",
        replace(timeline, tracks=tuple(tracks)),
        replace(
            clip,
            in_frame=min(clip.in_frame, frames[0][0]),
            out_frame=max(clip.out_frame, frames[-1][0]),
        ),
    )


class TrackingTake:
    """Own calibration, filtered controls and an unpublished bounded recording for one revision."""

    def __init__(
        self,
        document: DocumentService,
        target: str,
        smoothing: float = 0.35,
        *,
        turns: bool = False,
    ) -> None:
        """Capture source ownership and neutral authoring values without opening a device."""
        if not 0 <= number(smoothing) <= 0.95:
            raise ProjectError("Tracking smoothing must be from zero to 0.95.")
        self.document, self.original = document, document.project
        self.scene_id = document.scene.id
        self.context = (
            document.selected_clip_id,
            document.animation_context,
            document.animation_scope,
        )
        self.mapping = TrackingMapping(document, target, turns=turns)
        self.start = document.animation.pose.frame
        self.smoothing = smoothing
        self.neutral: TrackingSample | None = None
        self.latest: TrackingSample | None = None
        self.values: dict[Channel, float] = {}
        self.frames: list[tuple[float, Mapping[Channel, float]]] = []
        self.recording = False
        self.record_start = 0.0
        self.last_time = -1.0

    def check_ownership(self) -> None:
        """Protect clip/workspace selection as well as the immutable project revision."""
        current = (
            self.document.selected_clip_id,
            self.document.animation_context,
            self.document.animation_scope,
        )
        if (
            self.document.project is not self.original
            or current != self.context
            or self.document.scene.id != self.scene_id
        ):
            raise ProjectError(
                "Project or animation context changed. Start a fresh camera session."
            )

    def calibrate(self) -> None:
        """Use the latest pose as neutral; forbid calibration jumps during a recording."""
        if self.recording:
            raise ProjectError("Stop recording before recalibrating.")
        if self.latest is None or not (self.latest.face or self.latest.angles):
            raise ProjectError("Wait for a detected face or body before calibrating.")
        self.neutral = self.latest
        self.values = self.mapping.channels(self.latest, self.neutral)

    def feed(self, sample: TrackingSample, *, preview: bool = True) -> ScenePose | None:
        """Filter a new observation, hold missing regions and return a scratch evaluated pose."""
        self.check_ownership()
        if sample.seconds <= self.last_time:
            raise ProjectError("Tracking timestamps must increase.")
        self.last_time, self.latest = sample.seconds, sample
        if self.recording and sample.seconds < self.record_start:
            return None
        if self.neutral is None:
            if not (sample.face or sample.angles):
                return None
            self.neutral = sample
        else:
            self.neutral = TrackingSample(
                self.neutral.seconds,
                {**sample.face, **self.neutral.face},
                {**sample.angles, **self.neutral.angles},
            )
        for channel, value in self.mapping.channels(sample, self.neutral).items():
            previous = self.values.get(channel, value)
            self.values[channel] = (
                value
                if channel[1] in ("visibility", "object.view")
                else (previous * self.smoothing + value * (1 - self.smoothing))
            )
        if not self.values:
            return None
        frame = self.start + (sample.seconds - self.record_start if self.recording else 0) * (
            self.document.animation.evaluator.range.fps
        )
        frame = round(frame, 9)
        if self.recording:
            if len(self.frames) >= 600 or (len(self.frames) + 1) * len(self.values) > 30000:
                raise ProjectError("Camera take reached its sample/key limit. Stop and keep it.")
            self.frames.append((frame, dict(self.values)))
        if not preview:
            return None
        scratch = self.document.fork()
        publish_frames(scratch, [(frame, self.values)])
        return scratch.animation.evaluate(frame)

    def record(self, seconds: float | None = None) -> None:
        """Begin retaining filtered controls from the latest detector timestamp."""
        if self.frames:
            raise ProjectError("Keep or discard the previous take before recording again.")
        if self.latest is None or self.neutral is None:
            raise ProjectError("Wait for tracking and calibrate before recording.")
        if not self.values:
            raise ProjectError("No compatible channels are tracked for this target.")
        begin = self.latest.seconds if seconds is None else number(seconds)
        if begin < self.latest.seconds:
            raise ProjectError("Recording cannot start before the latest tracked observation.")
        self.recording, self.record_start = True, begin
        self.frames.append((self.start, dict(self.values)))

    def keep(self) -> None:
        """Publish ordinary editable keys once, rejecting stale revisions before any change."""
        self.recording = False
        self.check_ownership()
        publish_frames(self.document, self.frames)

    def stop(self, seconds: float) -> None:
        """Retain a final held pose up to Stop when the take still has sample/key capacity."""
        if self.recording and self.frames:
            frame = round(
                self.start
                + (number(seconds) - self.record_start)
                * self.document.animation.evaluator.range.fps,
                9,
            )
            if (
                frame > self.frames[-1][0]
                and len(self.frames) < 600
                and sum(len(v) for _, v in self.frames) + len(self.values) <= 30000
            ):
                self.frames.append((frame, dict(self.values)))
        self.recording = False

    def recorded_command(self) -> ScenePatch:
        """Prepare a take off-thread; the caller must check source revision before executing it."""
        self.check_ownership()
        assert self.original is not None
        scratch = self.document.fork()
        publish_frames(scratch, self.frames)
        assert scratch.project is not None
        before, after = (
            next(s for s in self.original.scenes if s.id == scratch.scene.id),
            scratch.scene,
        )
        fields = ("timelines", "clips")
        return ScenePatch(
            "Record camera performance",
            before.id,
            {k: getattr(before, k) for k in fields},
            {k: getattr(after, k) for k in fields},
        )
