"""Qt-free key, curve, clip and reusable-action authoring on the canonical timeline."""

import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from rigora.application_services.animation import AnimationSession
from rigora.application_services.animation_channels import AnimationChannel, describe_channel
from rigora.application_services.foot_contacts import edited_contacts
from rigora.application_services.meshes import MeshService
from rigora.domain.entities import (
    AnimationClip,
    Bone,
    Camera,
    Constraint,
    Deformer,
    Entity,
    Group,
    Keyframe,
    Marker,
    SceneObject,
    Timeline,
    Track,
    Transform,
    Vertex,
    nested_records,
)
from rigora.domain.project import ProjectError
from rigora.engine.deformation import DeformationPlan
from rigora.engine.sampling import CompiledTrack, TrackSampler, number
from rigora.engine.state import ScenePose, TransformValues
from rigora.engine.transition_curves import TransitionCurve
from rigora.infrastructure.deformation_clips import read_motion, write_motion

KeyRef = tuple[str, str]
Interpolation = Literal["step", "linear", "bezier"]


def copied_timeline(source: Timeline) -> Timeline:
    """Clone timeline identities so duplicate clips remain independently editable."""
    return replace(
        source,
        id=str(uuid4()),
        tracks=tuple(
            replace(
                t,
                id=str(uuid4()),
                keyframes=tuple(replace(k, id=str(uuid4())) for k in t.keyframes),
            )
            for t in source.tracks
        ),
        markers=tuple(replace(m, id=str(uuid4())) for m in source.markers),
    )


def motion_source_end(clip: AnimationClip) -> float:
    """Include the continuous seam of periodic sources without displaying a duplicate frame."""
    return clip.out_frame + (1 if clip.loop and clip.extra.get("continuous_loop") else 0)


def synchronized_motion_windows(
    timelines: tuple[Timeline, ...],
    clips: tuple[AnimationClip, ...],
    members_for: Callable[[str], set[str]],
) -> tuple[Timeline, ...]:
    """Refresh placed action keys while retaining each scene window's timing and identity."""
    for clip in clips:
        timeline = next((t for t in timelines if t.id == clip.timeline_id), None)
        if timeline is None:
            continue
        synchronized = []
        for arranged in timelines:
            windows = {
                t.extra["motion_window"]["id"]: t.extra["motion_window"]
                for t in arranged.tracks
                if t.extra.get("motion_window", {}).get("source") == clip.id
            }
            if not windows or arranged.id == timeline.id:
                synchronized.append(arranged)
                continue
            output = []
            emitted = set()
            for previous in arranged.tracks:
                window = previous.extra.get("motion_window", {})
                identity = window.get("id")
                if identity not in windows:
                    output.append(previous)
                    continue
                if identity in emitted:
                    continue
                emitted.add(identity)
                members = members_for(window["character"])
                old = {
                    t.extra.get("source_track", (t.owner_id, t.property_path)): t
                    for t in arranged.tracks
                    if t.extra.get("motion_window", {}).get("id") == identity
                }
                for source in timeline.tracks:
                    if source.owner_id not in members:
                        continue
                    saved = old.get(source.id) or old.get((source.owner_id, source.property_path))
                    output.append(
                        replace(
                            source,
                            id=saved.id if saved else str(uuid4()),
                            locked=True,
                            visible=saved.visible if saved else previous.visible,
                            keyframes=tuple(replace(k, id=str(uuid4())) for k in source.keyframes),
                            extra={
                                **source.extra,
                                "source_track": source.id,
                                "source_visible": source.visible,
                                "motion_window": {
                                    **window,
                                    "source_start": clip.in_frame,
                                    "source_end": motion_source_end(clip),
                                },
                            },
                        )
                    )
            synchronized.append(replace(arranged, tracks=tuple(output)))
        timelines = tuple(synchronized)
    return timelines


class AnimationEditingService(MeshService):
    """Validate all edits before publishing one reversible scene command per operation."""

    @property
    def clip(self) -> AnimationClip | None:
        """Return the selected runtime clip, retaining document-level clip selection."""
        return next((c for c in self.scene.clips if c.id == self.document.selected_clip_id), None)

    @property
    def timeline(self) -> Timeline | None:
        """Resolve the selected clip's data after edits, undo or clip switches."""
        clip = self.clip
        return next((t for t in self.scene.timelines if clip and t.id == clip.timeline_id), None)

    def blank_clip(self, timeline: Timeline, name: str = "Animation") -> AnimationClip:
        """Create a first clip in the active workspace without borrowing another object's keys."""
        context = self.document.animation_context
        extra: dict[str, Any] = {}
        if self.document.separated_animation:
            extra = {"object_id": context} if context else {"main_scene": True}
        return AnimationClip(
            name=name,
            timeline_id=timeline.id,
            in_frame=self.scene.settings.start_frame,
            out_frame=self.scene.settings.end_frame,
            extra=extra,
        )

    def publish(self, label: str, timeline: Timeline, clip: AnimationClip) -> None:
        """Compile edited tracks and validate the clip graph before mutating document history."""
        timelines = tuple(timeline if t.id == timeline.id else t for t in self.scene.timelines)
        clips = tuple(clip if c.id == clip.id else c for c in self.scene.clips)
        if not any(t.id == timeline.id for t in timelines):
            timelines = (*timelines, timeline)
        if not any(c.id == clip.id for c in clips):
            clips = (*clips, clip)
        # Placed windows retain their timing, but source edits must appear in every instance.
        from rigora.application_services.characters import CharacterService

        characters = CharacterService(self.document)
        timelines = synchronized_motion_windows(timelines, (clip,), characters.members)
        scene = replace(self.scene, timelines=timelines, clips=clips)
        session = AnimationSession(
            scene,
            clip.id,
            solvers=self.document.constraint_solvers,
            deformers=self.document.deformer_solvers,
            samplers=self.document.track_samplers,
            frame=self.document.animation.pose.frame,
            scope=self.document.animation_scope,
            local_object=self.document.animation_context,
        )
        self.commit(label, timelines=timelines, clips=clips)
        self.document.use_prepared_animation(session)

    def editable(self, track: Track) -> None:
        """Protect locked tracks, locked bones and protected vertices across every editor."""
        if track.locked:
            raise ProjectError("Unlock the track before editing its keys.")
        from rigora.application_services.scene_editing import SceneEditingService

        # Camera cuts choose scene output; they must also deactivate locked cameras.
        camera_cut = track.property_path == "camera.active" and any(
            camera.id == track.owner_id for camera in self.scene.cameras
        )
        if not camera_cut and SceneEditingService(self.document).locked(track.owner_id):
            raise ProjectError("Unlock the animated owner and its ancestors before editing keys.")
        evaluator = self.document.animation.evaluator
        index = evaluator.node_indices.get(track.owner_id)
        owner = (
            evaluator.nodes[index].source
            if index is not None
            else evaluator.deformation.vertices.get(track.owner_id)
            or evaluator.deformation.deformers.get(track.owner_id)
        )
        if getattr(owner, "locked", False) or getattr(owner, "protected", False):
            raise ProjectError("Unlock or unprotect the animated owner before editing its keys.")

    def insertion_editable(self, track: Track) -> None:
        """Protect newly added channels when their grouped editing lane is locked."""
        self.editable(track)
        timeline = self.timeline
        if timeline is None or any(t.id == track.id for t in timeline.tracks):
            return
        peers = [
            t
            for t in timeline.tracks
            if not t.extra.get("motion_window")
            and not t.extra.get("camera_action")
            and not t.extra.get("appearance_kind")
            and (
                self.document.animation_context
                or t.extra.get("appearance_owner", t.owner_id)
                == track.extra.get("appearance_owner", track.owner_id)
            )
        ]
        descriptions = {
            c.key: c.lane
            for c in self.channels(
                ((t.owner_id, t.property_path) for t in (*peers, track)),
                include_vertices=False,
            )
        }
        lane = descriptions.get((track.owner_id, track.property_path))
        matching = [
            t
            for t in peers
            if lane is not None and descriptions.get((t.owner_id, t.property_path)) == lane
        ]
        if matching and all(t.editing_locked for t in matching):
            raise ProjectError("Unlock the timeline row before adding keys or channels.")

    def properties(self, *, include_vertices: bool = True) -> tuple[tuple[Entity, str, float], ...]:
        """Enumerate supported scalars, visiting dense vertex records only when requested."""
        channels: list[tuple[Entity, str, float]] = []
        scene = self.scene
        try:
            plan = self.document.animation.evaluator.deformation
        except ProjectError:
            plan = DeformationPlan(scene, self.document.deformer_solvers)
        owners = (
            nested_records(scene)
            if include_vertices
            else (
                *scene.groups,
                *scene.cameras,
                *scene.objects,
                *(bone for rig in scene.skeletons for bone in rig.bones),
                *scene.deformers,
                *scene.constraints,
            )
        )
        for owner in owners:
            if isinstance(owner, (Bone, Group, SceneObject)):
                for path in ("x", "y", "rotation", "scale_x", "scale_y", "pivot_x", "pivot_y"):
                    channels.append((owner, f"transform.{path}", getattr(owner.transform, path)))
                if isinstance(owner, Camera):
                    channels.append((owner, "camera.active", float(owner.active)))
                    from rigora.engine.camera_actions import EFFECT_PRESETS

                    channels.extend(
                        (owner, "camera.effect." + preset, 0.0) for preset in EFFECT_PRESETS
                    )
                    continue
                if isinstance(owner, Bone):
                    channels.append((owner, "length", owner.length))
                elif self.document.animation_context is None:
                    channels.append((owner, "object.attachment", 0.0))
                if isinstance(owner, Group) and owner.extra.get("view_slots"):
                    from rigora.domain.object_views import VIEW_SLOTS

                    channels.append(
                        (
                            owner,
                            "object.view",
                            float(VIEW_SLOTS.index(str(owner.extra.get("active_view", "Default")))),
                        )
                    )
                channels.extend(
                    (
                        (
                            owner,
                            "visibility",
                            float(getattr(owner, "visible", owner.extra.get("visible", True))),
                        ),
                        (owner, "opacity", float(owner.extra.get("opacity", 1))),
                    )
                )
                if isinstance(owner, Bone):
                    channels.append((owner, "spring.enabled", 1.0))
                    channels.append((owner, "motion.fk", 0.0))
                    channels.append((owner, "motion.spring_baked", 0.0))
                channels.append((owner, "spring.master", 1.0))
            elif isinstance(owner, Vertex):
                channels.extend(((owner, "x", owner.x), (owner, "y", owner.y)))
            elif isinstance(owner, Constraint) and owner.kind != "scene_attachment":
                channels.extend(
                    (owner, "parameters." + name, float(value))
                    for name, value in owner.parameters.items()
                    if type(value) in (int, float)
                )
            elif isinstance(owner, Deformer) and owner.id in plan.parameters:
                for path in scalar_paths(plan.parameters[owner.id], "parameters"):
                    try:
                        channels.append((owner, path, plan.base(owner.id, path)))
                    except ProjectError:
                        continue
        return tuple(channels)

    def channels(
        self, requested: Iterable[tuple[str, str]] | None = None, *, include_vertices: bool = True
    ) -> tuple[AnimationChannel, ...]:
        """Describe all scalar properties, or only requested lanes without scanning mesh vertices.

        Unknown requested lanes are omitted, allowing readers to retain custom fallback labels.
        Full enumeration remains available to explicit channel pickers and API clients.
        """
        if requested is not None:
            requested = tuple(dict.fromkeys(requested))
            try:
                evaluator = self.document.animation.evaluator
            except ProjectError:
                # Channel labels must remain usable when an unsupported clip prevents
                # playback, so the user can select or repair a different clip.
                wanted = set(requested)
                return tuple(
                    channel
                    for channel in self.channels(include_vertices=include_vertices)
                    if channel.key in wanted
                )
            records: dict[str, Entity] = {node.source.id: node.source for node in evaluator.nodes}
            records.update(evaluator.deformation.vertices)
            records.update(evaluator.deformation.deformers)
            records.update({rule.id: rule for rule in self.scene.constraints})
            result = []
            for owner, path in dict.fromkeys(requested):
                if owner not in records:
                    continue
                try:
                    base = self.channel_bases(((owner, path),))[owner, path]
                except ProjectError:
                    continue
                result.append(
                    describe_channel(records[owner], path, base, self.document.channel_metadata)
                )
            return tuple(result)
        return tuple(
            describe_channel(owner, path, base, self.document.channel_metadata)
            for owner, path, base in self.properties(include_vertices=include_vertices)
        )

    def capture_values(
        self, channels: Iterable[tuple[str, str]], frame: float
    ) -> dict[tuple[str, str], float]:
        """Capture raw samples or authored defaults without applying blend weights twice."""
        wanted = tuple(dict.fromkeys(channels))
        if not wanted or len(wanted) > 100_000:
            raise ProjectError("Choose between 1 and 100,000 supported animation channels.")
        known = self.channel_bases(wanted)
        evaluator = self.document.animation.evaluator
        frame = evaluator.range.normalize(number(frame, "Key frame"), loop=False)
        tracks = self.timeline.tracks if self.timeline else ()
        indexed = {(t.owner_id, t.property_path): t for t in tracks}
        values = {}
        for key in wanted:
            track = indexed.get(key)
            value = (
                CompiledTrack(track, self.document.track_samplers).sample(frame) if track else None
            )
            values[key] = value if value is not None else known[key]
        return values

    def channel_bases(self, channels: Iterable[tuple[str, str]]) -> dict[tuple[str, str], float]:
        """Resolve only requested defaults instead of describing every mesh vertex channel."""
        evaluator = self.document.animation.evaluator
        values = {}
        for owner, path in channels:
            index = evaluator.node_indices.get(owner)
            record = evaluator.nodes[index].source if index is not None else None
            if record is None:
                value = (
                    evaluator.constraint_bases[owner][path]
                    if owner in evaluator.constraint_bases
                    and path.startswith("parameters.")
                    and path in evaluator.constraint_bases[owner]
                    else evaluator.deformation.base(owner, path)
                )
            elif path.startswith("transform.") and path[10:] in (
                "x",
                "y",
                "rotation",
                "scale_x",
                "scale_y",
                "pivot_x",
                "pivot_y",
            ):
                value = getattr(record.transform, path[10:])
            elif path == "length" and isinstance(record, Bone):
                value = record.length
            elif path in ("spring.enabled", "spring.master") and record is not None:
                value = 1.0
            elif path in ("motion.fk", "motion.spring_baked") and isinstance(record, Bone):
                value = 0.0
            elif path == "camera.active" and isinstance(record, Camera):
                value = float(record.active)
            elif (
                path == "object.attachment"
                and isinstance(record, (Group, SceneObject))
                and not isinstance(record, Camera)
                and self.document.animation_context is None
            ):
                value = 0.0
            elif path.startswith("camera.effect.") and isinstance(record, Camera):
                from rigora.engine.camera_actions import EFFECT_PRESETS

                if path[14:] not in EFFECT_PRESETS:
                    raise ProjectError("Choose an existing camera effect.")
                value = 0.0
            elif (
                path == "object.view"
                and isinstance(record, Group)
                and record.extra.get("view_slots")
            ):
                from rigora.domain.object_views import VIEW_SLOTS

                value = float(VIEW_SLOTS.index(str(record.extra.get("active_view", "Default"))))
            elif path in ("visibility", "opacity") and not isinstance(record, Camera):
                value = (
                    float(getattr(record, "visible", record.extra.get("visible", True)))
                    if path == "visibility"
                    else float(record.extra.get("opacity", 1))
                )
            else:
                raise ProjectError(f"Unsupported animation channel {path!r}.")
            values[owner, path] = value
        return values

    def add_channels(
        self,
        channels: Iterable[tuple[str, str]],
        *,
        frame: float | None = None,
        interpolation: Interpolation | None = None,
    ) -> None:
        """Add empty lanes or captured keys as one validated undo step without duplicating
        tracks.
        """
        wanted = tuple(dict.fromkeys(channels))
        attachments = tuple(owner for owner, path in wanted if path == "object.attachment")
        if frame is not None and attachments:
            from rigora.application_services.scene_attachments import SceneAttachmentService

            with self.document.command_group("Key animation channels"):
                other = tuple(pair for pair in wanted if pair[1] != "object.attachment")
                if other:
                    self.add_channels(other, frame=frame, interpolation=interpolation)
                for owner in attachments:
                    SceneAttachmentService(self.document).key_current(owner, frame)
            return
        values = self.capture_values(
            wanted, self.document.animation.pose.frame if frame is None else frame
        )
        timeline = self.timeline or Timeline(name="Animation")
        clip = self.clip or self.blank_clip(timeline)
        tracks = list(timeline.tracks)
        changed = False
        for owner, path in wanted:
            track = next(
                (t for t in tracks if (t.owner_id, t.property_path) == (owner, path)), None
            )
            if track is None:
                track = Track(name=path, owner_id=owner, property_path=path)
                self.insertion_editable(track)
                tracks.append(track)
                changed = True
            elif frame is None:
                continue
            self.editable(track)
            if frame is not None:
                previous = next((k for k in track.keyframes if k.frame == frame), None)
                key = (
                    replace(
                        previous,
                        value=values[owner, path],
                        interpolation=interpolation or previous.interpolation,
                    )
                    if previous
                    else Keyframe(
                        frame=frame,
                        value=values[owner, path],
                        interpolation="step"
                        if path in ("visibility", "camera.active", "object.view")
                        or path.startswith(("spring.", "motion."))
                        else interpolation or "linear",
                    )
                )
                tracks[tracks.index(track)] = replace(
                    track,
                    keyframes=tuple(
                        sorted(
                            (*(k for k in track.keyframes if k.frame != frame), key),
                            key=lambda k: k.frame,
                        )
                    ),
                )
                changed = True
        if changed:
            if frame is not None:
                clip = replace(
                    clip, in_frame=min(clip.in_frame, frame), out_frame=max(clip.out_frame, frame)
                )
            self.publish(
                "Add animation tracks" if frame is None else "Key animation channels",
                replace(timeline, tracks=tuple(tracks)),
                clip,
            )

    def key(
        self,
        owner: str,
        path: str,
        frame: float,
        value: float,
        *,
        interpolation: Interpolation = "linear",
        delete: bool = False,
    ) -> None:
        """Insert or replace a scalar channel key; create a first clip when necessary."""
        if path == "object.attachment" and not delete:
            from rigora.application_services.scene_attachments import SceneAttachmentService

            SceneAttachmentService(self.document).key_current(owner, frame)
            return
        timeline = self.timeline or Timeline(name="Animation")
        clip = self.clip or self.blank_clip(timeline)
        track = next(
            (t for t in timeline.tracks if (t.owner_id, t.property_path) == (owner, path)),
            Track(name=path, owner_id=owner, property_path=path),
        )
        self.insertion_editable(track)
        track = self.keyed_track(track, frame, value, interpolation, delete=delete)
        tracks = tuple(track if t.id == track.id else t for t in timeline.tracks)
        if not any(t.id == track.id for t in tracks):
            tracks = (*tracks, track)
        timeline = replace(timeline, tracks=tracks)
        self.publish(
            "Delete key" if delete else "Set key",
            timeline,
            replace(clip, in_frame=min(clip.in_frame, frame), out_frame=max(clip.out_frame, frame)),
        )

    @staticmethod
    def keyed_track(
        track: Track,
        frame: float,
        value: float,
        interpolation: Interpolation = "linear",
        *,
        delete: bool = False,
    ) -> Track:
        """Build an edited immutable track without compiling or publishing a project."""
        previous = next((k for k in track.keyframes if k.frame == frame), None)
        keys = tuple(k for k in track.keyframes if k.frame != frame)
        if not delete:
            key = (
                replace(previous, value=value, interpolation=interpolation)
                if previous
                else Keyframe(frame=frame, value=value, interpolation=interpolation)
            )
            keys = (*keys, key)
        ordered = sorted(keys, key=lambda k: k.frame)
        if previous is None and not delete:
            for index in range(len(ordered) - 1):
                left, right = ordered[index : index + 2]
                if left.interpolation != "bezier":
                    continue
                span = right.frame - left.frame
                outgoing = left.tangent_out or (span / 3, 0.0)
                incoming = right.tangent_in or (-span / 3, 0.0)
                reach = outgoing[0] - incoming[0]
                if outgoing[0] >= 0 and incoming[0] <= 0 and reach > span:
                    # A new key shortens its neighboring segments. Contract both
                    # control vectors together to retain their slopes and ordered time.
                    factor = span / reach
                    ordered[index] = replace(
                        left, tangent_out=(outgoing[0] * factor, outgoing[1] * factor)
                    )
                    ordered[index + 1] = replace(
                        right, tangent_in=(incoming[0] * factor, incoming[1] * factor)
                    )
        return replace(track, keyframes=tuple(ordered))

    def edit_keys(self, edits: Mapping[KeyRef, Mapping[str, Any]], *, delete: bool = False) -> None:
        """Atomically move, numerically edit or delete selected keys; reject collisions."""
        timeline, clip = self.timeline, self.clip
        if timeline is None or clip is None or not edits:
            return
        known = {(t.id, k.id) for t in timeline.tracks for k in t.keyframes}
        if not set(edits) <= known:
            raise ProjectError("The selected keys no longer belong to this clip.")
        tracks = []
        for track in timeline.tracks:
            if any(t == track.id for t, _ in edits):
                self.editable(track)
            keys = []
            for key in track.keyframes:
                changes = edits.get((track.id, key.id))
                if changes is None:
                    keys.append(key)
                elif not delete:
                    if not set(changes) <= {
                        "frame",
                        "value",
                        "interpolation",
                        "tangent_in",
                        "tangent_out",
                        "transition_curve",
                    }:
                        raise ProjectError("Unsupported key field.")
                    values = dict(changes)
                    if "transition_curve" in values:
                        raw = values.pop("transition_curve")
                        if raw is not None and track.extra.get("sampler"):
                            raise ProjectError("Bake the plugin sampler before editing its graph.")
                        extra = dict(key.extra)
                        extra.pop("transition_curve", None)
                        if raw is not None:
                            extra["transition_curve"] = TransitionCurve.from_data(raw).to_data()
                        values["extra"] = extra
                    keys.append(replace(key, **values))
            # Existing Bézier controls are stored in frame units; preserve their normalized
            # shape when either endpoint is retimed without an explicit tangent edit.
            positions = {k.id: k.frame for k in keys}
            scaled = {k.id: k for k in keys}
            for left, right in zip(track.keyframes, track.keyframes[1:], strict=False):
                if left.id not in positions or right.id not in positions:
                    continue
                duration = positions[right.id] - positions[left.id]
                if duration <= 0:
                    continue
                factor = duration / (right.frame - left.frame)
                for source, side in ((left, "tangent_out"), (right, "tangent_in")):
                    tangent = getattr(source, side)
                    if tangent and side not in edits.get((track.id, source.id), {}):
                        handle_edit: dict[str, Any] = {side: (tangent[0] * factor, tangent[1])}
                        scaled[source.id] = replace(scaled[source.id], **handle_edit)
            keys = list(scaled.values())
            tracks.append(replace(track, keyframes=tuple(sorted(keys, key=lambda k: k.frame))))
        changed_frames = [number(change["frame"]) for change in edits.values() if "frame" in change]
        if changed_frames and not delete:
            clip = replace(
                clip,
                in_frame=min(clip.in_frame, *changed_frames),
                out_frame=max(clip.out_frame, *changed_frames),
            )
        self.publish(
            "Delete keys" if delete else "Edit keys", replace(timeline, tracks=tuple(tracks)), clip
        )

    def preview_keys(self, edits: Mapping[KeyRef, Mapping[str, Any]], frame: float) -> ScenePose:
        """Evaluate the exact edit in an isolated document, leaving source history untouched."""
        scratch = self.document.fork()
        AnimationEditingService(scratch).edit_keys(edits)
        return scratch.animation.evaluate(frame)

    def selected_segments(
        self, selected: Iterable[KeyRef]
    ) -> tuple[tuple[Track, Keyframe, Keyframe], ...]:
        """Resolve pairs within each selected range; a lone key targets its adjoining span."""
        wanted = set(selected)
        records: list[tuple[Track, Keyframe, Keyframe]] = []
        known = (
            {(t.id, k.id) for t in self.timeline.tracks for k in t.keyframes}
            if self.timeline
            else set()
        )
        if not wanted <= known:
            raise ProjectError("The selected keys no longer belong to this clip.")
        for track in self.timeline.tracks if self.timeline else ():
            indices = [i for i, k in enumerate(track.keyframes) if (track.id, k.id) in wanted]
            if not indices or len(track.keyframes) < 2:
                continue
            first, last = min(indices), max(indices)
            if first == last:
                first, last = (
                    (first, first + 1) if first + 1 < len(track.keyframes) else (first - 1, first)
                )
            records.extend(
                (track, track.keyframes[i], track.keyframes[i + 1]) for i in range(first, last)
            )
        return tuple(records)

    def set_transition(
        self, selected: Iterable[KeyRef], curve: TransitionCurve | None = None
    ) -> None:
        """Convert selected intervals to real interpolated spans using normalized graph data."""
        segments = self.selected_segments(selected)
        if not segments:
            raise ProjectError("Choose two keys on a channel, or create a tween first.")
        if any(track.extra.get("sampler") for track, _, _ in segments):
            raise ProjectError(
                "This plugin supplies its own sampling; bake it before graph editing."
            )
        self.edit_keys(
            {
                (track.id, left.id): {
                    "interpolation": "linear",
                    "transition_curve": curve.to_data() if curve else None,
                    "tangent_out": None,
                }
                for track, left, _ in segments
            }
        )

    def create_tween(
        self, channels: Iterable[tuple[str, str]], start: float, end: float
    ) -> tuple[KeyRef, ...]:
        """Capture start/end poses and connect their intervals in one reversible operation."""
        start, end = number(start), number(end)
        if start < 0 or end <= start:
            raise ProjectError("A tween needs a nonnegative start and a later end.")
        wanted = tuple(dict.fromkeys(channels))
        with self.document.command_group("Create tween"):
            self.add_channels(wanted, frame=start)
            self.add_channels(wanted, frame=end)
            refs = (
                tuple(
                    (t.id, k.id)
                    for t in self.timeline.tracks
                    if (t.owner_id, t.property_path) in wanted
                    for k in t.keyframes
                    if start <= k.frame <= end
                )
                if self.timeline
                else ()
            )
            self.set_transition(refs)
        return refs

    def reverse_keys(self, selected: Iterable[KeyRef]) -> None:
        """Reverse each chosen channel range, including normalized graphs and Bézier handles."""
        segments = self.selected_segments(selected)
        by_track: dict[str, set[str]] = {}
        for track, left, right in segments:
            by_track.setdefault(track.id, set()).update((left.id, right.id))
        edits: dict[KeyRef, dict[str, Any]] = {}
        for track in self.timeline.tracks if self.timeline else ():
            keys = [k for k in track.keyframes if k.id in by_track.get(track.id, set())]
            if len(keys) < 2:
                continue
            first, last = keys[0].frame, keys[-1].frame
            for i, key in enumerate(keys):
                outgoing = keys[i - 1] if i else keys[-1]
                graph = outgoing.extra.get("transition_curve")
                edits[track.id, key.id] = {
                    "frame": first + last - key.frame,
                    "interpolation": outgoing.interpolation,
                    "tangent_in": (-key.tangent_out[0], key.tangent_out[1])
                    if key.tangent_out
                    else None,
                    "tangent_out": (-key.tangent_in[0], key.tangent_in[1])
                    if key.tangent_in
                    else None,
                    "transition_curve": TransitionCurve.from_data(graph).reversed().to_data()
                    if graph
                    else None,
                }
        if not edits:
            raise ProjectError("Select a tween or at least two keys to reverse.")
        self.edit_keys(edits)

    def auto_key_values(self, values: Mapping[tuple[str, str], float], frame: float) -> None:
        """Record changed scalar channels, seeding their initial pose before the first later key."""
        attachments = tuple(owner for owner, path in values if path == "object.attachment")
        if attachments:
            from rigora.application_services.scene_attachments import SceneAttachmentService

            with self.document.command_group("Key animation channels"):
                other = {
                    key: value for key, value in values.items() if key[1] != "object.attachment"
                }
                if other:
                    self.auto_key_values(other, frame)
                for owner in attachments:
                    SceneAttachmentService(self.document).key_current(owner, frame)
            return
        pose = self.document.animation.evaluate(frame)
        transforms: dict[str, Transform] = {}
        for (owner, path), value in values.items():
            if (
                owner in pose.nodes
                and path.startswith("transform.")
                and path[10:] in TransformValues._fields
            ):
                source = transforms.get(owner, Transform(**pose.nodes[owner].local._asdict()))
                change: dict[str, Any] = {path[10:]: number(value)}
                transforms[owner] = replace(source, **change)
        contacts = edited_contacts(
            self.scene, pose, transforms, self.document.animation.evaluator.rules
        )
        values = dict(values)
        for owner, transform in contacts.items():
            for name in TransformValues._fields:
                value = getattr(transform, name)
                if not math.isclose(value, getattr(pose.nodes[owner].local, name), abs_tol=1e-9):
                    values[owner, f"transform.{name}"] = value
        baseline = self.capture_values(values, self.scene.settings.start_frame)
        tracks = self.timeline.tracks if self.timeline else ()
        defaults = self.channel_bases(values)
        groups: dict[tuple[str, str], list[Track]] = {}
        for existing_track in tracks:
            groups.setdefault((existing_track.owner_id, existing_track.property_path), []).append(
                existing_track
            )
        targets = {}
        for channel in values:
            group = groups.setdefault(channel, [])
            target = next((t for t in group if not t.extra.get("motion_window")), None)
            if target is None:
                target = Track(name=channel[1], owner_id=channel[0], property_path=channel[1])
                group.append(target)
            targets[channel] = target

        def raw_value(channel: tuple[str, str], desired: float, time: float) -> float:
            """Invert layered scalar influence so recorded values match the displayed pose."""
            group = groups.get(channel, [])
            if not group:
                return desired
            target = targets[channel]

            def outcome(raw: float) -> float:
                """Sample the stack with the keyed track replaced by a constant raw scalar."""
                keyed = replace(target, keyframes=(Keyframe(frame=time, value=raw),), extra={})
                return sample_channel(
                    tuple(
                        CompiledTrack(
                            keyed if t.id == target.id else t, self.document.track_samplers
                        )
                        for t in group
                    ),
                    time,
                    defaults[channel],
                    channel[1],
                )

            if target.extra.get("sampler"):
                raise ProjectError("Bake the plugin sampler before recording keys on this channel.")
            offset, at_one = outcome(0), outcome(1)
            if abs(at_one - offset) < 1e-12:
                raise ProjectError(
                    "The selected channel has no influence; adjust its track weights."
                )
            return number((number(desired) - offset) / (at_one - offset))

        timeline = self.timeline or Timeline(name="Animation")
        clip = self.clip or self.blank_clip(timeline)
        changed = {t.id: t for t in tracks}
        for (owner, path), value in values.items():
            group = groups.get((owner, path), [])
            track = targets[owner, path]
            self.insertion_editable(track)
            if frame > self.scene.settings.start_frame and not track.keyframes:
                channel_tracks = tuple(
                    CompiledTrack(t, self.document.track_samplers) for t in group
                )
                initial = sample_channel(
                    channel_tracks, self.scene.settings.start_frame, baseline[owner, path], path
                )
                track = self.keyed_track(
                    track,
                    self.scene.settings.start_frame,
                    raw_value((owner, path), initial, self.scene.settings.start_frame),
                    "step"
                    if path in ("visibility", "camera.active", "object.view")
                    or path.startswith(("spring.", "motion."))
                    else "linear",
                )
            changed[track.id] = self.keyed_track(
                track,
                frame,
                raw_value((owner, path), value, frame),
                "step"
                if path in ("visibility", "camera.active", "object.view")
                or path.startswith(("spring.", "motion."))
                else "linear",
            )
        self.publish(
            "Auto key pose",
            replace(timeline, tracks=tuple(changed.values())),
            replace(clip, in_frame=min(clip.in_frame, frame), out_frame=max(clip.out_frame, frame)),
        )

    def copy_keys(self, selected: Iterable[KeyRef]) -> dict[str, Any]:
        """Encode selected keys as bounded JSON data, retaining source property identities."""
        selected = set(selected)
        timeline = self.timeline
        records = []
        for track in timeline.tracks if timeline else ():
            keys = [k.to_dict() for k in track.keyframes if (track.id, k.id) in selected]
            if keys:
                records.append(
                    {
                        "owner_id": track.owner_id,
                        "property_path": track.property_path,
                        "name": track.name,
                        "source_track": track.id,
                        "blend_mode": track.blend_mode,
                        "weight": track.weight,
                        "keyframes": keys,
                    }
                )
        if not records:
            raise ProjectError("Select keys to copy.")
        return {"format": "rigora.keys", "version": 1, "tracks": records}

    def paste_keys(self, data: dict[str, Any], frame: float) -> tuple[KeyRef, ...]:
        """Paste relative to the earliest copied frame, preserving spacing and curve handles."""
        if data.get("format") != "rigora.keys" or data.get("version") != 1:
            raise ProjectError("The clipboard does not contain Rigora keys.")
        frame = number(frame, "Paste frame")
        timeline, clip = self.timeline, self.clip
        if timeline is None or clip is None:
            raise ProjectError("Select an animation clip before pasting keys.")
        sources = [Track.from_dict({**raw, "id": str(uuid4())}) for raw in data["tracks"]]
        start = min(k.frame for t in sources for k in t.keyframes)
        tracks, selected = list(timeline.tracks), []
        for source in sources:
            track = next(
                (t for t in tracks if t.id == source.extra.get("source_track")),
                next(
                    (
                        t
                        for t in tracks
                        if (t.owner_id, t.property_path) == (source.owner_id, source.property_path)
                    ),
                    replace(source, keyframes=(), extra={}),
                ),
            )
            self.insertion_editable(track)
            keys = list(track.keyframes)
            for key in source.keyframes:
                key = replace(key, id=str(uuid4()), frame=frame + key.frame - start)
                if any(k.frame == key.frame for k in keys):
                    raise ProjectError("Pasted keys overlap existing keys; choose another frame.")
                keys.append(key)
                selected.append((track.id, key.id))
            changed = replace(track, keyframes=tuple(sorted(keys, key=lambda k: k.frame)))
            if any(t.id == track.id for t in tracks):
                tracks = [changed if t.id == track.id else t for t in tracks]
            else:
                tracks.append(changed)
        self.publish(
            "Paste keys",
            replace(timeline, tracks=tuple(tracks)),
            replace(
                clip,
                in_frame=min(clip.in_frame, frame),
                out_frame=max((clip.out_frame, *(k.frame for t in tracks for k in t.keyframes))),
            ),
        )
        return tuple(selected)

    def remove_tracks(self, selected: Iterable[str]) -> None:
        """Remove complete channels as one undo step, validating every owner's lock first."""
        ids = set(selected)
        timeline, clip = self.timeline, self.clip
        tracks = tuple(t for t in timeline.tracks if t.id in ids) if timeline else ()
        if not tracks or not timeline or not clip:
            raise ProjectError("Select property tracks to remove.")
        for track in tracks:
            self.editable(track)
        self.publish(
            "Remove animation tracks",
            replace(timeline, tracks=tuple(t for t in timeline.tracks if t.id not in ids)),
            clip,
        )

    def copy_tracks(self, selected: Iterable[str]) -> dict[str, Any]:
        """Encode whole tracks, including empty lanes, using the portable track schema."""
        ids = set(selected)
        tracks = [t.to_dict() for t in self.timeline.tracks if t.id in ids] if self.timeline else []
        if not tracks:
            raise ProjectError("Select property tracks to copy.")
        return {"format": "rigora.tracks", "version": 1, "tracks": tracks}

    def paste_tracks(self, data: dict[str, Any], frame: float) -> tuple[KeyRef, ...]:
        """Merge copied lanes at the playhead, preserving blank lanes and rejecting key collisions.

        Ownership stays with the original object. All destinations and collisions are validated
        before one scene command is published, including absent or locked targets.
        """
        if (
            not isinstance(data, dict)
            or data.get("format") != "rigora.tracks"
            or data.get("version") != 1
        ):
            raise ProjectError("The clipboard does not contain Rigora tracks.")
        raw = data.get("tracks")
        if not isinstance(raw, list) or not 1 <= len(raw) <= 512:
            raise ProjectError("Choose between 1 and 512 tracks to paste.")
        if any(not isinstance(t, dict) for t in raw):
            raise ProjectError("Invalid track clipboard records.")
        sources = [Track.from_dict(t) for t in raw]
        wanted = tuple((t.owner_id, t.property_path) for t in sources)
        self.capture_values(wanted, self.document.animation.pose.frame)
        frame = number(frame, "Paste frame")
        if frame < 0:
            raise ProjectError("Paste frame must be nonnegative.")
        timeline = self.timeline or Timeline(name="Animation")
        clip = self.clip or self.blank_clip(timeline)
        start = min((k.frame for t in sources for k in t.keyframes), default=0)
        tracks, selected, used = list(timeline.tracks), [], set()
        for source in sources:
            target = next((t for t in tracks if t.id not in used and t.id == source.id), None)
            if target is None:
                target = next(
                    (
                        t
                        for t in tracks
                        if t.id not in used
                        and (t.owner_id, t.property_path) == (source.owner_id, source.property_path)
                    ),
                    None,
                )
            if target is not None:
                self.editable(target)
                keys = list(target.keyframes)
            else:
                self.editable(replace(source, locked=False))
                target = replace(source, id=str(uuid4()), keyframes=())
                keys = []
            used.add(target.id)
            for old in source.keyframes:
                key = replace(old, id=str(uuid4()), frame=frame + old.frame - start)
                if any(existing.frame == key.frame for existing in keys):
                    raise ProjectError("Pasted keys overlap existing keys; choose another frame.")
                keys.append(key)
                selected.append((target.id, key.id))
            changed = replace(target, keyframes=tuple(sorted(keys, key=lambda k: k.frame)))
            if any(t.id == target.id for t in tracks):
                tracks = [changed if t.id == target.id else t for t in tracks]
            else:
                tracks.append(changed)
        self.publish(
            "Paste animation tracks",
            replace(timeline, tracks=tuple(tracks)),
            replace(
                clip,
                in_frame=min(clip.in_frame, frame),
                out_frame=max((clip.out_frame, *(k.frame for t in tracks for k in t.keyframes))),
            ),
        )
        return tuple(selected)

    def track_settings(self, key: str, *, locked: bool, visible: bool) -> None:
        """Persist evaluation muting and editing locks, retaining linked source protection."""
        timeline, clip = self.timeline, self.clip
        if timeline and clip:
            self.publish(
                "Track settings",
                replace(
                    timeline,
                    tracks=tuple(
                        replace(
                            t,
                            locked=t.locked if t.extra.get("motion_window") else locked,
                            visible=visible,
                            extra={
                                **t.extra,
                                "motion_window": {**t.extra["motion_window"], "locked": locked},
                            }
                            if t.extra.get("motion_window")
                            else t.extra,
                        )
                        if t.id == key
                        else t
                        for t in timeline.tracks
                    ),
                ),
                clip,
            )

    def tangents(self, selected: Iterable[KeyRef], mode: str) -> None:
        """Generate flat, linear or smooth automatic handles using adjacent scalar slopes."""
        if mode not in ("flat", "linear", "auto"):
            raise ProjectError("Unknown tangent mode.")
        selected = set(selected)
        edits: dict[KeyRef, dict[str, Any]] = {}
        for track in self.timeline.tracks if self.timeline else ():
            keys = track.keyframes
            for i, key in enumerate(keys):
                if (track.id, key.id) not in selected:
                    continue
                left, right = keys[max(0, i - 1)], keys[min(len(keys) - 1, i + 1)]
                before, after = key.frame - left.frame, right.frame - key.frame
                slope = (
                    (number(right.value) - number(left.value)) / (right.frame - left.frame)
                    if right.frame != left.frame
                    else 0.0
                )
                incoming = (number(key.value) - number(left.value)) / before if before else slope
                outgoing = (number(right.value) - number(key.value)) / after if after else slope
                if mode == "flat":
                    incoming = outgoing = 0.0
                elif mode == "auto":
                    incoming = outgoing = slope
                edits[track.id, key.id] = {
                    "interpolation": "bezier",
                    "tangent_in": (-before / 3, -before / 3 * incoming),
                    "tangent_out": (after / 3, after / 3 * outgoing),
                }
        self.edit_keys(edits)

    def new_clip(self, name: str = "Animation", *, duplicate: bool = False) -> str:
        """Create an independent blank or copied timeline and select its named clip."""
        source = self.timeline
        timeline = copied_timeline(source) if duplicate and source else Timeline(name=name)
        clip = (
            replace(self.clip, id=str(uuid4()), name=name, timeline_id=timeline.id)
            if duplicate and self.clip
            else self.blank_clip(timeline, name)
        )
        self.publish("Duplicate clip" if duplicate else "New clip", timeline, clip)
        return clip.id

    def set_end_frame(self, frame: float) -> None:
        """Cap the active clip or unkeyed scene without deleting keys beyond the playback end."""
        frame = number(frame, "Maximum frame")
        if frame == self.document.animation.playback.range.end:
            return
        start = self.clip.in_frame if self.clip else self.scene.settings.start_frame
        if frame <= start or frame > 10_000_000:
            raise ProjectError(
                "The maximum frame must follow the start and stay within 10,000,000."
            )
        if self.clip:
            self.clip_settings(out_frame=frame)
        else:
            if not frame.is_integer():
                raise ProjectError("An unkeyed scene's maximum frame must be a whole number.")
            self.commit(
                "Set maximum frame", settings=replace(self.scene.settings, end_frame=int(frame))
            )

    def clip_settings(self, **changes: Any) -> None:
        """Edit names, in/out, loop and annotations without resampling curve data."""
        if not set(changes) <= {"name", "in_frame", "out_frame", "loop", "annotation"}:
            raise ProjectError("Unsupported clip setting.")
        if self.timeline and self.clip:
            self.publish("Clip settings", self.timeline, replace(self.clip, **changes))

    def retime(
        self,
        start: float,
        end: float,
        *,
        reverse: bool = False,
        offset_x: float = 0,
        offset_y: float = 0,
        rotation: float = 0,
    ) -> None:
        """Remap key/marker times and handles; offset root transforms without double transforms."""
        timeline, clip = self.timeline, self.clip
        if timeline is None or clip is None:
            return
        start, end = number(start), number(end)
        duration = clip.out_frame - clip.in_frame
        if start < 0 or end <= start or duration <= 0:
            raise ProjectError("Retiming requires positive source and destination durations.")
        factor = (end - start) / duration * (-1 if reverse else 1)

        def mapped(frame: float) -> float:
            """Map absolute source time into the requested destination interval."""
            return (end if reverse else start) + (frame - clip.in_frame) * factor

        owners = {r.id: r for r in nested_records(self.scene)}
        tracks = []
        for track in timeline.tracks:
            self.editable(track)
            keys = []
            for i, key in enumerate(track.keyframes):
                if mapped(key.frame) < 0:
                    raise ProjectError(
                        "Retiming would create negative keys. Expand the source clip range "
                        "to include its keys, or choose a later destination start."
                    )
                incoming, outgoing = key.tangent_in, key.tangent_out
                interpolation = key.interpolation
                extra = dict(key.extra)
                if reverse:
                    incoming, outgoing = outgoing, incoming
                    interpolation = track.keyframes[i - 1].interpolation if i else key.interpolation
                    source = track.keyframes[i - 1] if i else key
                    extra.pop("transition_curve", None)
                    if "transition_curve" in source.extra:
                        extra["transition_curve"] = (
                            TransitionCurve.from_data(source.extra["transition_curve"])
                            .reversed()
                            .to_data()
                        )
                keys.append(
                    replace(
                        key,
                        frame=mapped(key.frame),
                        extra=extra,
                        interpolation=interpolation,
                        tangent_in=(incoming[0] * factor, incoming[1]) if incoming else None,
                        tangent_out=(outgoing[0] * factor, outgoing[1]) if outgoing else None,
                    )
                )
                if reverse and i and track.keyframes[i - 1].interpolation == "step":
                    previous = track.keyframes[i - 1]
                    if previous.value != key.value:
                        keys.append(
                            Keyframe(
                                frame=math.nextafter(mapped(key.frame), math.inf),
                                value=previous.value,
                                interpolation="step",
                            )
                        )
            tracks.append(replace(track, keyframes=tuple(sorted(keys, key=lambda k: k.frame))))
        offset_roots = set()
        for owner_id in {track.owner_id for track in timeline.tracks}:
            owner = owners[owner_id]
            if isinstance(owner, Bone):
                parent = owners.get(owner.parent_id or "")
                while isinstance(parent, Bone):
                    owner = parent
                    parent = owners.get(parent.parent_id or "")
            if isinstance(owner, (Bone, Group, SceneObject)) and owner.parent_id is None:
                offset_roots.add(owner.id)
        for rig in self.scene.skeletons:
            container = str(rig.extra.get("object_id", ""))
            while container and container not in offset_roots:
                container = getattr(owners.get(container), "parent_id", None) or ""
            if container:
                offset_roots.difference_update(b.id for b in rig.bones)
        for owner_id in sorted(offset_roots):
            for path, offset in (
                ("transform.x", number(offset_x)),
                ("transform.y", number(offset_y)),
                ("transform.rotation", number(rotation)),
            ):
                if offset:
                    tracks.append(
                        Track(
                            name=f"Clip offset · {path}",
                            owner_id=owner_id,
                            property_path=path,
                            blend_mode="additive",
                            keyframes=(Keyframe(frame=start, value=offset),),
                        )
                    )
        markers = tuple(replace(m, frame=mapped(m.frame)) for m in timeline.markers)
        self.publish(
            "Reverse / retime clip" if reverse else "Retime / offset clip",
            replace(timeline, tracks=tuple(tracks), markers=markers),
            replace(clip, in_frame=start, out_frame=end),
        )

    def marker(
        self,
        name: str,
        frame: float,
        annotation: str = "",
        *,
        key: str = "",
        delete: bool = False,
        event_type: str = "",
        payload: Any = None,
    ) -> None:
        """Insert, edit or remove a persistent marker in the active timeline."""
        timeline, clip = self.timeline, self.clip
        if timeline is None or clip is None:
            raise ProjectError("Create an animation clip before adding markers.")
        markers = tuple(m for m in timeline.markers if m.id != key)
        if not delete:
            from rigora.engine.game_events import event_data

            previous = next((m for m in timeline.markers if m.id == key), None)
            extra = {
                k: v for k, v in (previous.extra.items() if previous else ()) if k != "game_event"
            }
            if event_type:
                extra["game_event"] = event_data(event_type, payload if payload is not None else {})
            markers = (
                *markers,
                Marker(
                    id=key or str(uuid4()),
                    name=name,
                    frame=frame,
                    annotation=annotation,
                    extra=extra,
                ),
            )
        self.publish("Edit marker", replace(timeline, markers=markers), clip)

    def blend(self, other_id: str, weight: float = 0.5, transition: float = 0) -> str:
        """Bake a reusable frame-sampled blend or end transition with the same scalar sampler."""
        timeline, clip = self.timeline, self.clip
        other = next((c for c in self.scene.clips if c.id == other_id), None)
        weight, transition = number(weight), number(transition)
        if (
            timeline is None
            or clip is None
            or other is None
            or not 0 <= weight <= 1
            or transition < 0
        ):
            raise ProjectError("Choose two clips and a weight from zero to one.")
        if clip.out_frame - clip.in_frame > 10000:
            raise ProjectError("Bake a range of at most 10,000 frames at a time.")
        second = next(t for t in self.scene.timelines if t.id == other.timeline_id)
        a = compiled_channels(timeline, self.document.track_samplers)
        b = compiled_channels(second, self.document.track_samplers)
        defaults = {(o.id, p): v for o, p, v in self.properties()}
        plan = DeformationPlan(self.scene, self.document.deformer_solvers)
        times = sorted(
            {
                clip.in_frame,
                clip.out_frame,
                *(float(t) for t in range(int(clip.in_frame) + 1, int(clip.out_frame) + 1)),
            }
        )
        tracks = []
        if len(times) * len(a.keys() | b.keys()) > 20000:
            raise ProjectError(
                "Bake at most 20,000 channel samples per operation; shorten the range."
            )
        for channel in sorted(a.keys() | b.keys()):
            baseline = defaults.get(channel)
            if baseline is None:
                baseline = plan.base(*channel)

            keys = []
            for frame in times:
                progress = (frame - clip.in_frame) / max(1e-12, clip.out_frame - clip.in_frame)
                mix = (
                    weight
                    if not transition
                    else max(0.0, 1 - (clip.out_frame - frame) / transition) * weight
                )
                other_frame = other.in_frame + progress * (other.out_frame - other.in_frame)
                value = (1 - mix) * sample_channel(
                    a.get(channel, ()), frame, baseline, channel[1]
                ) + mix * sample_channel(b.get(channel, ()), other_frame, baseline, channel[1])
                keys.append(Keyframe(frame=frame, value=value))
            tracks.append(
                Track(
                    name=channel[1],
                    owner_id=channel[0],
                    property_path=channel[1],
                    keyframes=tuple(keys),
                )
            )
        result = Timeline(
            name=f"{clip.name} blend",
            tracks=tuple(tracks),
            markers=tuple(replace(m, id=str(uuid4())) for m in timeline.markers),
        )
        output = replace(
            clip,
            id=str(uuid4()),
            name=result.name,
            timeline_id=result.id,
            annotation="Frame-sampled blend; source clips remain editable.",
        )
        self.publish("Bake clip transition" if transition else "Bake clip blend", result, output)
        return output.id

    def export_action(self, path: Path, *, overwrite: bool = False) -> None:
        """Save a data-only reusable clip with owner descriptors and original key precision."""
        timeline, clip = self.timeline, self.clip
        if timeline is None or clip is None:
            raise ProjectError("Select a clip to export.")
        records = {r.id: r for r in nested_records(self.scene)}
        references = {t.owner_id for t in timeline.tracks}
        references.update(clip.extra.get("fk_bones", ()))
        references.update(clip.extra.get("spring_baked_bones", ()))
        references.update(
            part for t in timeline.tracks for part in t.property_path.split(".") if part in records
        )
        owners = {
            owner: {
                "name": records[owner].name,
                "type": type(records[owner]).__name__,
            }
            for owner in references
        }
        write_motion(
            path,
            {
                "format": "rigora.action",
                "version": 1,
                "fps": self.scene.settings.fps,
                "owners": owners,
                "clip": clip.to_dict(),
                "timeline": timeline.to_dict(),
            },
            overwrite=overwrite,
        )

    def import_action(self, path: Path) -> str:
        """Map original IDs or unambiguous owner names/types, refusing partial motion imports."""
        try:
            data = read_motion(path)
            if data.get("format") != "rigora.action" or data.get("version") != 1:
                raise ProjectError("Unsupported reusable action format.")
            source = Timeline.from_dict(data["timeline"])
            clip = AnimationClip.from_dict(data["clip"])
            fps = number(data["fps"])
            if fps <= 0:
                raise ProjectError("Action frame rate must be positive.")
            factor = self.scene.settings.fps / fps
            records = {r.id: r for r in nested_records(self.scene)}
            mapping = {}
            for key, descriptor in data["owners"].items():
                candidates = [
                    r.id
                    for r in records.values()
                    if r.name == descriptor["name"] and type(r).__name__ == descriptor["type"]
                ]
                if key in records and type(records[key]).__name__ == descriptor["type"]:
                    mapping[key] = key
                elif len(candidates) == 1:
                    mapping[key] = candidates[0]
                else:
                    raise ProjectError(
                        f"Action owner {descriptor['name']!r} has no unique compatible match."
                    )
            tracks = []
            for track in source.tracks:
                path_parts = track.property_path.split(".")
                path_parts = [mapping.get(part, part) for part in path_parts]
                keys = tuple(
                    replace(
                        k,
                        id=str(uuid4()),
                        frame=k.frame * factor,
                        tangent_in=(k.tangent_in[0] * factor, k.tangent_in[1])
                        if k.tangent_in
                        else None,
                        tangent_out=(k.tangent_out[0] * factor, k.tangent_out[1])
                        if k.tangent_out
                        else None,
                    )
                    for k in track.keyframes
                )
                tracks.append(
                    replace(
                        track,
                        id=str(uuid4()),
                        owner_id=mapping[track.owner_id],
                        property_path=".".join(path_parts),
                        keyframes=keys,
                    )
                )
            timeline = replace(
                source,
                id=str(uuid4()),
                tracks=tuple(tracks),
                markers=tuple(
                    replace(m, id=str(uuid4()), frame=m.frame * factor) for m in source.markers
                ),
            )
            clip = replace(
                clip,
                id=str(uuid4()),
                timeline_id=timeline.id,
                in_frame=clip.in_frame * factor,
                out_frame=clip.out_frame * factor,
                extra={
                    **clip.extra,
                    "fk_bones": tuple(mapping[k] for k in clip.extra.get("fk_bones", ())),
                    **(
                        {
                            "spring_baked_bones": tuple(
                                mapping[k] for k in clip.extra["spring_baked_bones"]
                            )
                        }
                        if "spring_baked_bones" in clip.extra
                        else {}
                    ),
                },
            )
            self.publish("Import reusable action", timeline, clip)
            return clip.id
        except (KeyError, ValueError, TypeError, IndexError, OverflowError) as error:
            raise ProjectError(f"Invalid reusable action: {error}") from error


def scalar_paths(value: Any, prefix: str) -> Iterable[str]:
    """Walk finite numeric leaves; topology exclusions are enforced by the common evaluator."""
    if type(value) in (int, float):
        yield prefix
    elif isinstance(value, Mapping):
        for key, child in value.items():
            yield from scalar_paths(child, f"{prefix}.{key}")
    elif isinstance(value, (tuple, list)):
        for index, child in enumerate(value):
            yield from scalar_paths(child, f"{prefix}.{index}")


def compiled_channels(
    timeline: Timeline, samplers: Mapping[str, TrackSampler] | None = None
) -> dict[tuple[str, str], tuple[CompiledTrack, ...]]:
    """Preserve ordered layered tracks when compiling channels for reusable clip baking."""
    result: dict[tuple[str, str], tuple[CompiledTrack, ...]] = {}
    for track in timeline.tracks:
        channel = track.owner_id, track.property_path
        result[channel] = (*result.get(channel, ()), CompiledTrack(track, samplers))
    return result


def sample_channel(
    tracks: tuple[CompiledTrack, ...], frame: float, baseline: float, path: str
) -> float:
    """Sample layered scalar values using the evaluator's override/additive policies."""
    value = baseline
    for compiled in tracks:
        sampled = compiled.sample(frame)
        if sampled is None:
            continue
        track = compiled.source
        if track.blend_mode == "override":
            value = value * (1 - track.weight) + sampled * track.weight
        elif path.endswith(("scale_x", "scale_y")):
            value *= 1 - track.weight + sampled * track.weight
        else:
            value += sampled * track.weight
    return number(value)
