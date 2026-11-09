"""Pointer-driven preview and editable recording through Rigora's canonical animation evaluator."""

import bisect
import math
import random
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.documents import DocumentService
from rigora.application_services.scene_editing import SceneEditingService
from rigora.domain.entities import (
    AnimationClip,
    Bone,
    Entity,
    Group,
    Keyframe,
    SceneObject,
    Timeline,
    Track,
)
from rigora.domain.geometry import inverse, transform_point
from rigora.domain.motion_pilot import MotionPilotProfile
from rigora.domain.project import ProjectError
from rigora.engine.evaluation import SceneEvaluator
from rigora.engine.sampling import number
from rigora.engine.state import ScenePose
from rigora.infrastructure.project_storage import _atomic_bytes, _decode

Channel = tuple[str, str]
Point = tuple[float, float]


class MotionPilotService(AnimationEditingService):
    """Own project-bound profiles and publish completed passes as ordinary scalar tracks."""

    def target_members(self, owner: str) -> set[str]:
        """Resolve ordinary object parts or a legacy rig's connected bone branch."""
        from rigora.application_services.characters import CharacterService

        record = SceneEditingService(self.document).record(owner)
        if not isinstance(record, Bone):
            return CharacterService(self.document).members(owner)
        records = SceneEditingService(self.document).records()
        return {owner} | {
            b.id
            for r in self.scene.skeletons
            for b in r.bones
            if SceneEditingService._has_ancestor(b.id, {owner}, records)
        }

    def profile(self, owner: str) -> MotionPilotProfile:
        """Read an object's settings without changing its saved configuration or other targets."""
        record = SceneEditingService(self.document).record(owner)
        return MotionPilotProfile.from_dict(record.extra.get("motion_pilot", {}))

    def set_profile(self, owner: str, profile: MotionPilotProfile) -> None:
        """Persist one target's validated settings as an ordinary undoable scene edit."""
        scene = SceneEditingService(self.document)
        record = scene.record(owner)
        if not isinstance(record, (Group, SceneObject, Bone)):
            raise ProjectError("Motion Pilot needs an object, group or bone target.")
        scene.update_records(
            {owner: replace(record, extra={**record.extra, "motion_pilot": profile.to_dict()})},
            "Edit Motion Pilot profile",
        )

    def export_profile(self, owner: str, path: Path) -> None:
        """Write a reusable inert JSON profile while preserving an existing destination."""
        import json

        if path.exists():
            raise ProjectError("Choose a new profile filename; existing files are preserved.")
        _atomic_bytes(
            path,
            json.dumps(
                {
                    "format": "rigora.motion-pilot",
                    "version": 1,
                    "profile": self.profile(owner).to_dict(),
                },
                indent=2,
                allow_nan=False,
            ).encode(),
        )

    def import_profile(self, owner: str, path: Path) -> None:
        """Validate bounded profile data before updating the explicitly selected target."""
        if path.stat().st_size > 1024 * 1024:
            raise ProjectError("Motion Pilot profiles must be smaller than 1 MiB.")
        data = _decode(path.read_bytes())
        if data.get("format") != "rigora.motion-pilot" or data.get("version") != 1:
            raise ProjectError("Unsupported Motion Pilot profile format/version.")
        self.set_profile(owner, MotionPilotProfile.from_dict(data.get("profile", {})))


@dataclass
class _Driver:
    """One follower's deterministic input filter, orientation, wave phase and trigger state."""

    point: Point
    time: float
    angle: float
    previous: Point
    wave_phase: float = 0
    motion_phase: float = 0
    clicks: int = 0
    triggered: bool = False
    playing: bool = False


def optimized_keys(keys: tuple[Keyframe, ...], tolerance: float) -> tuple[Keyframe, ...]:
    """Reduce linear position samples with a bounded per-axis error, retaining timing endpoints."""
    if len(keys) < 3:
        return keys
    kept = {0, len(keys) - 1}
    pending = [(0, len(keys) - 1)]
    while pending:
        first, last = pending.pop()
        left, right = keys[first], keys[last]
        span = right.frame - left.frame
        error, chosen = 0.0, first
        for i in range(first + 1, last):
            key = keys[i]
            fraction = (key.frame - left.frame) / span
            deviation = abs(
                float(key.value)
                - (float(left.value) + fraction * (float(right.value) - float(left.value)))
            )
            if deviation > error:
                error, chosen = deviation, i
        if error > tolerance:
            kept.add(chosen)
            pending.extend(((first, chosen), (chosen, last)))
    return tuple(keys[i] for i in sorted(kept))


class MotionPilotSession:
    """Capture fixed-frame controls in isolated memory; preview never publishes project keys."""

    def __init__(
        self,
        document: DocumentService,
        owners: tuple[str, ...],
        profile: MotionPilotProfile | None = None,
        *,
        recording: bool = False,
        pointer: Point = (0, 0),
        viewport_center: Point = (0, 0),
    ) -> None:
        """Capture a stable revision, compatible targets and deterministic follower delays."""
        if document.project is None or not owners or len(owners) > 128:
            raise ProjectError("Select 1–128 Motion Pilot objects.")
        self.document, self.original = document, document.project
        self.context = document.animation_context
        self.scene_id = document.scene.id
        self.owners = tuple(dict.fromkeys(owners))
        self.profile = profile or MotionPilotService(document).profile(self.owners[0])
        self.recording = recording
        self.source = MotionPilotService(document)
        self.clip, self.timeline = self.source.clip, self.source.timeline
        self.start = document.animation.pose.frame
        self.fps = self.source.scene.settings.fps
        self.end = document.animation.evaluator.range.end
        self.frame = self.start
        self.pointer_start = self._point(pointer)
        self.center = self._point(viewport_center)
        self.pointer = self.pointer_start
        self.raw_time = self.start
        self.clicks = 0
        self.times: list[float] = []
        self.points: list[tuple[Point, int]] = []
        self.samples: list[dict[Channel, float]] = []
        self.driver: dict[str, _Driver] = {}
        self.target_for_channel: dict[Channel, str] = {}
        self.native: dict[str, SceneEvaluator] = {}
        self.sample_mesh = lru_cache(maxsize=128)(SceneEvaluator.mesh_values)
        self.mappings: dict[tuple[str, str], dict[str, str]] = {}
        self.delays: dict[str, float] = {}
        editor = SceneEditingService(document)
        for owner in self.owners:
            if not isinstance(editor.record(owner), (Group, SceneObject, Bone)):
                raise ProjectError("Select objects, groups or bones for Motion Pilot.")
            self.source.editable(Track(owner_id=owner, property_path="transform.x"))
        if any(
            editor._has_ancestor(owner, set(self.owners) - {owner}, editor.records())
            for owner in self.owners
        ):
            raise ProjectError(
                "Select either a parent object or its children, not both in one flock."
            )
        scene = self.source.scene
        if self.timeline and not self.profile.blend:
            base = replace(
                self.timeline,
                tracks=tuple(
                    t
                    for t in self.timeline.tracks
                    if t.extra.get("motion_pilot", {}).get("target") not in self.owners
                ),
            )
            scene = replace(
                scene, timelines=tuple(base if t.id == base.id else t for t in scene.timelines)
            )
        arguments: dict[str, Any] = dict(
            solvers=document.constraint_solvers,
            deformers=document.deformer_solvers,
            samplers=document.track_samplers,
            select_first_clip=False,
            scope=document.animation_scope,
            local_object=document.animation_context,
        )
        self.base = SceneEvaluator(scene, self.clip.id if self.clip else None, **arguments)
        self.evaluator = SceneEvaluator(
            scene, self.clip.id if self.clip else None, controls=self.values_at, **arguments
        )
        self.set_profile(self.profile)
        self._append(self.start, self.pointer_start, 0)

    @staticmethod
    def _point(value: Point) -> Point:
        """Validate coordinates from CLI, tablet or mouse clients before geometry arithmetic."""
        point = number(value[0], "Pointer X"), number(value[1], "Pointer Y")
        if max(abs(v) for v in point) > 10000000:
            raise ProjectError("Pointer coordinates exceed the supported workspace.")
        return point

    def set_profile(self, profile: MotionPilotProfile) -> None:
        """Update live mappings without rewriting previous samples or follower profiles."""
        self.profile = profile
        randomizer = random.Random(profile.seed)
        self.delays = {
            owner: 0
            if index == 0 or profile.delay_mode == "None"
            else index * profile.delay_frames
            if profile.delay_mode == "Uniform"
            else randomizer.randint(profile.delay_min, profile.delay_max)
            for index, owner in enumerate(self.owners)
        }
        for key in profile.motion_clips:
            if key not in self.native:
                self.native[key] = SceneEvaluator(
                    self.source.scene,
                    key,
                    solvers=self.document.constraint_solvers,
                    deformers=self.document.deformer_solvers,
                    samplers=self.document.track_samplers,
                )
            for owner in self.owners:
                if (key, owner) not in self.mappings:
                    self.mappings[key, owner] = self._motion_mapping(self.native[key], owner)

    def _motion_mapping(self, source: SceneEvaluator, owner: str) -> dict[str, str]:
        """Retarget compatible native channels by existing rig/part names, never guessed IDs."""
        from rigora.application_services.characters import CharacterService

        characters = CharacterService(self.document)
        target_members = self.source.target_members(owner)
        records: dict[str, Entity] = {n.source.id: n.source for n in self.base.nodes}
        records.update(self.base.deformation.deformers)
        records.update(self.base.deformation.vertices)
        source_owner = source.clip.extra.get("object_id") if source.clip else None
        if not source_owner and source.timeline:
            roots = {
                t.owner_id
                for t in source.timeline.tracks
                if isinstance(records.get(t.owner_id), (SceneObject, Group))
            }
            if len(roots) == 1:
                source_owner = next(iter(roots))
        source_members = characters.members(source_owner) if source_owner else set()
        mapping = {source_owner: owner} if source_owner else {}
        target_names: dict[tuple[type, str], list[str]] = {}
        for key in target_members:
            if key in records:
                record = records[key]
                target_names.setdefault((type(record), record.name), []).append(key)
        for track in source.timeline.tracks if source.timeline else ():
            key = track.owner_id
            if key in target_members:
                mapping[key] = key
            elif key in records and (not source_members or key in source_members):
                record = records[key]
                matches = target_names.get((type(record), record.name), [])
                if len(matches) == 1:
                    mapping[key] = matches[0]
        if not mapping or any(
            t.owner_id not in mapping
            for t in (source.timeline.tracks if source.timeline else ())
            if not t.property_path.startswith("spring.")
        ):
            raise ProjectError(
                "The loaded motion has incompatible bone/part names for this flock member."
            )
        for track in source.timeline.tracks if source.timeline else ():
            if not track.property_path.startswith("spring."):
                self.source.editable(
                    Track(owner_id=mapping[track.owner_id], property_path=track.property_path)
                )
        return mapping

    def feed(
        self, frame: float, pointer: Point, *, clicked: bool = False, final: bool = False
    ) -> ScenePose:
        """Sample project frames, interpolate missed input and retain a final fraction."""
        frame = min(self.end, number(frame, "Motion Pilot frame"))
        pointer = self._point(pointer)
        if frame < self.raw_time:
            raise ProjectError("Motion Pilot input time must move forward.")
        previous_clicks = self.clicks
        if clicked:
            self.clicks += 1
        next_frame = math.floor(self.frame + 1e-8) + 1
        if len(self.times) + max(0, math.floor(frame) - next_frame + 1) > 100000:
            raise ProjectError("Stop this recording before 100,000 pointer samples.")
        pending = [float(i) for i in range(next_frame, math.floor(frame) + 1)]
        if final and frame > self.frame and (not pending or pending[-1] != frame):
            pending.append(frame)
        if len(self.times) + len(pending) > 100000:
            raise ProjectError("Stop this recording before 100,000 pointer samples.")
        for time in pending:
            ratio = (time - self.raw_time) / max(1e-12, frame - self.raw_time)
            ratio = min(1.0, max(0.0, ratio))
            point = tuple(a + (b - a) * ratio for a, b in zip(self.pointer, pointer, strict=True))
            self._append(
                time,
                (point[0], point[1]),
                self.clicks if time >= math.floor(frame) else previous_clicks,
            )
        self.raw_time, self.pointer = frame, pointer
        return self.evaluator.evaluate(self.frame)

    def _input_at(self, frame: float) -> tuple[Point, int]:
        """Interpolate saved fixed-frame input for fractional follower delays."""
        i = max(0, bisect.bisect_right(self.times, frame) - 1)
        point, clicks = self.points[i]
        if i + 1 < len(self.times) and frame > self.times[i]:
            ratio = (frame - self.times[i]) / (self.times[i + 1] - self.times[i])
            other = self.points[i + 1][0]
            point = (
                point[0] + (other[0] - point[0]) * ratio,
                point[1] + (other[1] - point[1]) * ratio,
            )
        return point, clicks

    def values_at(self, frame: float) -> dict[Channel, float]:
        """Provide past controls to the canonical evaluator and its fixed Spring replay."""
        if not self.samples or frame < self.start:
            return {}
        i = max(0, bisect.bisect_right(self.times, frame) - 1)
        left = self.samples[i]
        if i + 1 >= len(self.samples) or frame == self.times[i]:
            return left
        ratio = (frame - self.times[i]) / (self.times[i + 1] - self.times[i])
        right = self.samples[i + 1]
        result = {}
        for key in left.keys() | right.keys():
            a = left.get(key, self._base_value(key, frame))
            b = right.get(key, self._base_value(key, frame))
            result[key] = (
                a
                if key[1] in ("visibility", "motion.fk", "motion.spring_baked")
                or key[1] == "transform.scale_x"
                and a * b < 0
                else a + ratio * (b - a)
            )
        return result

    def _base_value(
        self, channel: Channel, frame: float, evaluator: SceneEvaluator | None = None
    ) -> float:
        """Read one authored/evaluated scalar before secondary physics without applying it twice."""
        evaluator = evaluator or self.base
        owner, path = channel
        if path == "motion.fk":
            return float(owner in evaluator._frame_fk(frame))
        if path == "motion.spring_baked":
            return float(owner in evaluator._motion_flags(frame, path))
        if owner not in evaluator.node_indices:
            return self.sample_mesh(evaluator, frame).get(
                channel, evaluator.deformation.base(owner, path)
            )
        node = evaluator.sample_kinematic(frame)[evaluator.node_indices[owner]]
        if path.startswith("transform."):
            return float(getattr(node.local, path[10:]))
        return (
            float(node.visible)
            if path == "visibility"
            else node.opacity
            if path == "opacity"
            else node.length
        )

    def _append(self, frame: float, pointer: Point, clicks: int) -> None:
        """Advance independent fixed-frame drivers and publish controls only to session memory."""
        self.times.append(frame)
        self.points.append((pointer, clicks))
        values: dict[Channel, float] = {}
        for owner in self.owners:
            time = max(self.start, frame - self.delays[owner])
            point, count = self._input_at(time)
            primary = self.base.sample_kinematic(frame)
            node = primary[self.base.node_indices[owner]]
            state = self.driver.setdefault(
                owner,
                _Driver(
                    self.pointer_start,
                    self.start,
                    math.degrees(math.atan2(node.world_matrix[1], node.world_matrix[0])),
                    self.pointer_start,
                ),
            )
            dt = max(0.0, (time - state.time) / self.fps)
            factor = 1 - math.exp(-dt / self.profile.lazy_mouse) if self.profile.lazy_mouse else 1
            previous = state.point
            state.point = (
                previous[0] + (point[0] - previous[0]) * factor,
                previous[1] + (point[1] - previous[1]) * factor,
            )
            dx, dy = state.point[0] - self.pointer_start[0], state.point[1] - self.pointer_start[1]
            distance = math.dist(point, state.previous)
            wave_step = distance / 100 if self.profile.wave_mouse else dt
            state.wave_phase += math.tau * self.profile.wave_speed * wave_step
            wave = math.sin(state.wave_phase)

            def axis(name: str, dx: float = dx, dy: float = dy) -> float:
                """Map a signed input axis without moving the reference origin."""
                return (dx if name.endswith("X") else dy) * (-1 if name.startswith("-") else 1)

            movement = [
                axis(self.profile.move_x_axis) * self.profile.move_x if self.profile.move else 0.0,
                axis(self.profile.move_y_axis) * self.profile.move_y if self.profile.move else 0.0,
            ]
            if self.profile.wave_move:
                movement[0] += wave * self.profile.wave_x
                movement[1] += wave * self.profile.wave_y
            parent = primary[self.base.node_indices[node.parent_id]] if node.parent_id else None
            world_movement = movement.copy()
            if self.profile.space == "Local":
                angle = math.atan2(node.world_matrix[1], node.world_matrix[0])
                movement = [
                    math.cos(angle) * movement[0] - math.sin(angle) * movement[1],
                    math.sin(angle) * movement[0] + math.cos(angle) * movement[1],
                ]
                world_movement = movement.copy()
            if parent:
                a, b, c, d, _, _ = inverse(parent.world_matrix)
                movement = [a * movement[0] + c * movement[1], b * movement[0] + d * movement[1]]
            result: dict[str, float] = {}
            if self.profile.move or self.profile.wave_move:
                result.update(x=node.local.x + movement[0], y=node.local.y + movement[1])
            rotation = node.local.rotation
            if self.profile.rotate and self.profile.face != "Turn":
                rotation += axis(self.profile.rotation_axis) * self.profile.rotation_gain
            if self.profile.wave_rotate:
                rotation += wave * self.profile.wave_angle
            if self.profile.rotate or self.profile.wave_rotate:
                result["rotation"] = rotation
            sx, sy = node.local.scale_x, node.local.scale_y
            if self.profile.scale:
                width = math.exp(
                    max(-6.9, min(6.9, axis(self.profile.width_axis) * self.profile.width_gain))
                )
                height = (
                    width
                    if self.profile.uniform
                    else math.exp(
                        max(
                            -6.9,
                            min(6.9, axis(self.profile.height_axis) * self.profile.height_gain),
                        )
                    )
                )
                sx, sy = sx * width, sy * height
            if self.profile.wave_scale:
                sx *= max(0.001, 1 + wave * self.profile.wave_width)
                sy *= max(0.001, 1 + wave * self.profile.wave_height)
            if self.profile.scale or self.profile.wave_scale:
                result.update(scale_x=sx, scale_y=sy)
            if self.profile.face != "Off" and frame > self.start:
                pivot = transform_point(node.world_matrix, node.local.pivot_x, node.local.pivot_y)
                reference = self.center if self.profile.cursor_start == "Viewport center" else pivot
                vector = (
                    reference[0] + point[0] - self.pointer_start[0] - pivot[0] - world_movement[0],
                    reference[1] + point[1] - self.pointer_start[1] - pivot[1] - world_movement[1],
                )
                if math.hypot(*vector) < 1e-6:
                    vector = (state.point[0] - previous[0], state.point[1] - previous[1])
                if math.hypot(*vector) > 1e-6:
                    if self.profile.face == "Flip":
                        angle = math.radians(self.profile.forward_angle)
                        result["scale_x"] = abs(sx) * (
                            1
                            if vector[0] * math.cos(angle) + vector[1] * math.sin(angle) >= 0
                            else -1
                        )
                    else:
                        target = (
                            math.degrees(math.atan2(vector[1], vector[0]))
                            - self.profile.forward_angle
                        )
                        alpha = (
                            1 - math.exp(-dt / self.profile.turn_smoothness)
                            if self.profile.turn_smoothness
                            else 1
                        )
                        state.angle += math.remainder(target - state.angle, 360) * alpha
                        local_angle = state.angle
                        if parent:
                            a, b, c, d, _, _ = inverse(parent.world_matrix)
                            angle = math.radians(state.angle)
                            local_angle = math.degrees(
                                math.atan2(
                                    b * math.cos(angle) + d * math.sin(angle),
                                    a * math.cos(angle) + c * math.sin(angle),
                                )
                            )
                        if node.local.scale_x < 0:
                            local_angle -= 180
                        result["rotation"] = local_angle + (
                            wave * self.profile.wave_angle if self.profile.wave_rotate else 0
                        )
            for path, value in result.items():
                channel = owner, "transform." + path
                values[channel] = value
                self.target_for_channel[channel] = owner
            if self.profile.motion_enabled:
                self._motion_values(owner, state, frame, dt, distance, count, values)
            state.time, state.previous, state.clicks = time, point, count
        if (len(self.samples) + 1) * max(1, len(self.target_for_channel)) > 1000000:
            raise ProjectError("Stop this pass before one million scalar samples.")
        self.samples.append(values)
        self.frame = frame

    def _motion_values(
        self,
        owner: str,
        state: _Driver,
        frame: float,
        dt: float,
        distance: float,
        clicks: int,
        values: dict[Channel, float],
    ) -> None:
        """Blend native motion offsets after transforms using deterministic trigger clocks."""
        mode = self.profile.motion_trigger
        triggered_now = clicks != state.clicks and mode.startswith("Click")
        if triggered_now:
            state.playing = (
                state.playing != bool((clicks - state.clicks) % 2)
                if mode == "Click to loop"
                else True
            )
            state.triggered = True
            if state.playing:
                state.motion_phase = 0
        if not triggered_now and (mode == "Automatic" or mode == "Mouse movement" or state.playing):
            state.motion_phase += (
                distance / 10 if mode == "Mouse movement" else dt * self.fps
            ) * self.profile.motion_speed
        if mode.startswith("Click") and not state.triggered:
            return
        for key in self.profile.motion_clips:
            source = self.native[key]
            clip, timeline = source.clip, source.timeline
            if clip is None or timeline is None:
                continue
            span = max(1e-6, clip.out_frame - clip.in_frame)
            phase = (
                min(span, state.motion_phase)
                if mode == "Click to play"
                else state.motion_phase % span
            )
            if mode == "Click to play" and state.motion_phase >= span:
                state.playing = False
            time = clip.out_frame - phase if self.profile.motion_reverse else clip.in_frame + phase
            mapping = self.mappings[key, owner]
            for bone in clip.extra.get("fk_bones", ()):
                if bone in mapping:
                    channel = mapping[bone], "motion.fk"
                    values[channel] = 1.0
                    self.target_for_channel[channel] = owner
            baked = clip.extra.get(
                "spring_baked_bones",
                clip.extra.get("fk_bones", ()) if clip.extra.get("dynamics_bake") else (),
            )
            for bone in baked:
                if bone in mapping:
                    channel = mapping[bone], "motion.spring_baked"
                    values[channel] = 1.0
                    self.target_for_channel[channel] = owner
            for track in timeline.tracks:
                if track.property_path.startswith("spring."):
                    continue
                target = mapping[track.owner_id]
                channel = target, track.property_path
                source_node = (
                    source.nodes[source.node_indices[track.owner_id]].source
                    if track.owner_id in source.node_indices
                    else None
                )
                if (
                    self.profile.motion_in_place
                    and track.property_path == "transform.x"
                    and (
                        target == owner
                        or isinstance(source_node, Bone)
                        and not source_node.parent_id
                    )
                ):
                    continue
                value = self._base_value((track.owner_id, track.property_path), time, source)
                base = values.get(channel, self._base_value(channel, frame))
                if track.property_path.startswith("transform."):
                    rest = (
                        getattr(source_node.transform, track.property_path[10:])
                        if source_node
                        else 0
                    )
                    value = (
                        base * value / rest
                        if track.property_path in ("transform.scale_x", "transform.scale_y")
                        and rest
                        else base + value - rest
                    )
                values[channel] = value
                self.target_for_channel[channel] = owner

    def prepare_recording(self) -> tuple[Timeline, AnimationClip]:
        """Sample a pass at project frames, preserving other channels and source clips."""
        if not self.recording:
            raise ProjectError("Preview sessions cannot create recorded keys.")
        channels = set(self.target_for_channel)
        if not channels:
            raise ProjectError("Enable a Transform, Wave or Motion mapping before recording.")
        timeline = self.timeline or Timeline(name="Motion Pilot")
        clip = self.clip or self.source.blank_clip(timeline, "Motion Pilot")
        base_timeline = self.base.timeline
        tracks = list(base_timeline.tracks if base_timeline else ())
        all_frames = sorted(
            {
                clip.in_frame,
                clip.out_frame,
                self.start,
                self.frame,
                *self.times,
                *(
                    k.frame
                    for t in tracks
                    if (t.owner_id, t.property_path) in channels
                    for k in t.keyframes
                    if clip.in_frame <= k.frame <= clip.out_frame
                ),
                *(
                    float(i)
                    for i in range(math.ceil(clip.in_frame), math.floor(clip.out_frame) + 1)
                ),
            }
        )
        if len(all_frames) * len(channels) > 1000000:
            raise ProjectError(
                "Record at most one million scalar samples per pass; shorten the range."
            )
        for channel in sorted(channels):
            owner, path = channel
            prior = next(
                (
                    t
                    for t in tracks
                    if (t.owner_id, t.property_path) == channel and t.extra.get("motion_pilot")
                ),
                None,
            )
            if prior:
                self.source.editable(prior)
            has_future = any(
                (t.owner_id, t.property_path) == channel
                and any(k.frame > self.frame for k in t.keyframes)
                for t in tracks
            )
            final_value = self.values_at(self.frame).get(
                channel, self._base_value(channel, self.frame)
            )
            keys = tuple(
                Keyframe(
                    frame=frame,
                    value=self.values_at(frame).get(channel, self._base_value(channel, frame))
                    if self.start <= frame <= self.frame
                    else final_value
                    if frame > self.frame and not has_future
                    else self._base_value(channel, frame),
                    interpolation="step"
                    if path in ("visibility", "motion.fk", "motion.spring_baked")
                    else "linear",
                )
                for frame in all_frames
            )
            if path == "transform.scale_x":
                keys = tuple(
                    replace(key, interpolation="step")
                    if i + 1 < len(keys) and float(key.value) * float(keys[i + 1].value) < 0
                    else key
                    for i, key in enumerate(keys)
                )
            if self.profile.optimize and path in ("transform.x", "transform.y"):
                keys = optimized_keys(keys, self.profile.tolerance)
            target = self.target_for_channel[channel]
            track = replace(
                prior or Track(name=f"Pilot · {path}", owner_id=owner, property_path=path),
                keyframes=keys,
                extra={
                    "motion_pilot": {"target": target, "leader": self.owners[0]},
                    "appearance_owner": target,
                },
            )
            tracks = [track if t.id == track.id else t for t in tracks]
            if prior is None:
                tracks.append(track)
        return replace(timeline, tracks=tuple(tracks)), clip

    def commit(self, prepared: tuple[Timeline, AnimationClip] | None = None) -> None:
        """Publish one undoable pass only while its document and editing context still match."""
        if (
            self.document.project is not self.original
            or self.document.animation_context != self.context
            or self.document.scene.id != self.scene_id
        ):
            raise ProjectError(
                "The project changed during capture; record again to retain both edits."
            )
        prepared = prepared or self.prepare_recording()
        with self.document.command_group("Record Motion Pilot"):
            MotionPilotService(self.document).publish("Record Motion Pilot", *prepared)
            MotionPilotService(self.document).set_profile(self.owners[0], self.profile)
