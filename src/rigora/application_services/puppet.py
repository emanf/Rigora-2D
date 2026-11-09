"""Data-only motion cards, non-destructive live sessions and atomic recorded performance
commands.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

from rigora.application_services.animation_editing import AnimationEditingService, copied_timeline
from rigora.application_services.audio import AudioService
from rigora.application_services.characters import CharacterService
from rigora.application_services.commands import ScenePatch
from rigora.application_services.content_library import ContentService
from rigora.application_services.documents import DocumentService
from rigora.application_services.ffd_motion import FfdMotionService
from rigora.domain.content import ContentItem
from rigora.domain.entities import AnimationClip, Entity, Keyframe, Timeline, Track
from rigora.domain.project import ProjectError
from rigora.domain.validation import json_copy
from rigora.engine.sampling import number
from rigora.engine.state import ScenePose
from rigora.engine.time import FrameRange
from rigora.infrastructure.project_storage import _atomic_bytes, _decode


@dataclass(frozen=True, slots=True, kw_only=True)
class MotionCard(Entity):
    """Portable trigger settings and an embedded original data-only content recipe."""

    target_id: str
    hotkey: str = "1"
    kind: Literal["motion", "replay", "flip_x", "flip_y", "visibility", "opacity"] = "motion"
    content: Mapping[str, Any] = field(default_factory=dict)
    speed: float = 1
    loop: bool = True
    pinned: bool = False

    def __post_init__(self) -> None:
        """Validate bounded trigger settings without executing or importing any external content."""
        Entity.__post_init__(self)
        if len(self.hotkey) != 1 or not self.hotkey.isascii() or not self.hotkey.isalnum():
            raise ProjectError("Motion card hotkeys must be one ASCII letter or digit.")
        if not 0.05 <= self.speed <= 20:
            raise ProjectError("Motion card speed must be between 0.05 and 20.")
        if self.kind not in ("motion", "replay", "flip_x", "flip_y", "visibility", "opacity"):
            raise ProjectError("Choose a supported Puppet card kind.")
        if self.kind == "replay" and not isinstance(self.content.get("clip_id"), str):
            raise ProjectError("Replay cards require an existing project action ID.")
        if self.kind == "motion":
            item = ContentItem.from_dict(json_copy(self.content))
            if item.kind != "action" and not (
                item.kind == "deformation" and "motion" in item.payload
            ):
                raise ProjectError("Motion cards accept body actions or normalized FFD motions.")


class PuppetService(ContentService):
    """Persist a bounded scene-owned card profile and validate every trigger through shared
    services.
    """

    def cards(self) -> tuple[MotionCard, ...]:
        """Decode the current scene profile with stable targets and inert content metadata."""
        cards = self.scene.extra.get("puppet_cards", ())
        if not isinstance(cards, (tuple, list)) or len(cards) > 64:
            raise ProjectError("A Puppet profile supports at most 64 cards.")
        return tuple(MotionCard.from_dict(json_copy(card)) for card in cards)

    def set_cards(self, cards: tuple[MotionCard, ...]) -> None:
        """Publish a profile edit without changing any animation track or other scene metadata."""
        if len(cards) > 64 or len({c.id for c in cards}) != len(cards):
            raise ProjectError("Motion card profiles require up to 64 unique identities.")
        self.commit(
            "Edit motion cards",
            extra={
                **json_copy(self.scene.extra),
                "puppet_cards": [card.to_dict() for card in cards],
            },
        )

    def add(
        self,
        target: str,
        item: ContentItem | None = None,
        *,
        hotkey: str = "1",
        kind: Literal["motion", "flip_x", "flip_y", "visibility", "opacity"] = "motion",
    ) -> str:
        """Create a target-bound content or object-effect card after checking compatibility."""
        if item:
            reason = self.compatibility(item, target, target)
            if reason:
                raise ProjectError(reason)
        elif not any(o.id == target for o in (*self.scene.objects, *self.scene.groups)):
            raise ProjectError("Object effect cards require a scene object target.")
        card = MotionCard(
            name=item.name if item else kind.replace("_", " ").title(),
            target_id=target,
            hotkey=hotkey.upper(),
            kind=kind,
            content=item.to_dict() if item else {},
        )
        self.set_cards((*self.cards(), card))
        return card.id

    def export_profile(self, path: Path) -> None:
        """Write a bounded portable JSON profile with embedded recipes and explicit target
        identities.
        """
        import json

        if path.exists():
            raise ProjectError("Choose a new profile filename; existing profiles are preserved.")
        payload = {
            "format": "rigora.puppet-profile",
            "version": 1,
            "cards": [c.to_dict() for c in self.cards()],
        }
        _atomic_bytes(path, json.dumps(payload, indent=2, allow_nan=False).encode("utf-8"))

    def add_replay(self, target: str, source: str, *, hotkey: str = "1") -> str:
        """Reference an existing Object action without copying its artwork or curve data."""
        clip = next(
            (c for c in CharacterService(self.document).motions(target) if c.id == source), None
        )
        if clip is None:
            raise ProjectError("Choose an existing action belonging to this Object.")
        card = MotionCard(
            name=clip.name,
            target_id=target,
            kind="replay",
            hotkey=hotkey.upper(),
            content={"clip_id": clip.id},
        )
        self.set_cards((*self.cards(), card))
        return card.id

    def capture_replay(self, target: str, *, hotkey: str = "1") -> str:
        """Retain owned tracks and synchronized audio as an editable project-local replay action."""
        editor = AnimationEditingService(self.document)
        if editor.timeline is None or editor.clip is None:
            raise ProjectError("Record or select an action before capturing a replay.")
        owners = CharacterService(self.document).members(target)
        timeline = copied_timeline(editor.timeline)
        timeline = replace(
            timeline, tracks=tuple(t for t in timeline.tracks if t.owner_id in owners)
        )
        if not timeline.tracks:
            raise ProjectError("This action has no animation for the selected Object.")
        original = editor.clip
        clip = AnimationClip(
            name="Replay · " + original.name,
            timeline_id=timeline.id,
            in_frame=original.in_frame,
            out_frame=original.out_frame,
            extra={
                "object_id": target,
                "puppet_replay": True,
                **{k: v for k, v in original.extra.items() if k in ("audio", "audio_tracks")},
            },
        )
        with self.document.command_group("Capture Puppet replay"):
            self.commit(
                "Create replay action",
                timelines=(*self.scene.timelines, timeline),
                clips=(*self.scene.clips, clip),
            )
            return self.add_replay(target, clip.id, hotkey=hotkey)

    def import_profile(self, path: Path, target: str = "") -> None:
        """Load inert JSON; optionally remap every imported card onto an explicitly chosen
        target.
        """
        if path.stat().st_size > 4 * 1024 * 1024:
            raise ProjectError("Puppet profiles must be smaller than 4 MiB.")
        payload = _decode(path.read_bytes())
        if payload.get("format") != "rigora.puppet-profile" or payload.get("version") != 1:
            raise ProjectError("Unsupported Puppet profile format/version.")
        raw = payload.get("cards", [])
        if not isinstance(raw, list) or len(raw) > 64:
            raise ProjectError("Puppet profiles support at most 64 cards.")
        cards = tuple(MotionCard.from_dict(c) for c in raw)
        if target:
            cards = tuple(replace(card, target_id=target) for card in cards)
        self.set_cards(cards)


class PuppetSession:
    """Own scratch project state for preview or recording; publish only on explicit successful
    stop.
    """

    def __init__(self, document: DocumentService, *, recording: bool = False) -> None:
        """Capture a revision and canonical extension registries without changing source history."""
        if document.project is None:
            raise ProjectError("Open a project before puppeteering.")
        self.document, self.original, self.recording = document, document.project, recording
        self.scratch = document.fork()
        self.start_frame = document.animation.pose.frame
        self.frame = self.start_frame
        self.active: dict[str, MotionCard] = {}
        self.ranges: dict[str, tuple[float, float]] = {}
        self.triggered: dict[str, str] = {}
        self.events: list[tuple[MotionCard, float, float]] = []
        self.base_clip = document.selected_clip_id
        self.context = document.animation_context, document.animation_scope, self.base_clip
        self.recorded_clip = self.base_clip
        self.replay_audio: dict[str, set[str]] = {}

    def trigger(self, card: MotionCard, frame: float) -> None:
        """Apply one scratch trigger atomically, preserving the prior cue if validation fails."""
        context = self.scratch.animation_context, self.scratch.animation_scope
        selected, separated = self.scratch.selected_clip_id, self.scratch.separated_animation
        state = (
            dict(self.active),
            dict(self.ranges),
            dict(self.triggered),
            {key: set(value) for key, value in self.replay_audio.items()},
        )
        previous_frame, count = self.frame, len(self.events)
        try:
            with self.scratch.command_group("Trigger Puppet card"):
                self._trigger(card, frame)
        except BaseException:
            self.active, self.ranges, self.triggered, self.replay_audio = state
            self.frame = previous_frame
            del self.events[count:]
            if (self.scratch.animation_context, self.scratch.animation_scope) != context:
                self.scratch.set_animation_context(*context, prepare=False)
            self.scratch.separated_animation = separated
            if selected:
                self.scratch.select_animation_clip(selected)
            self.scratch.animation.seek(previous_frame)
            raise

    def _trigger(self, card: MotionCard, frame: float) -> None:
        """Trigger real canonical motion/effect keys in the scratch document, never the open
        project.
        """
        frame = number(frame, "Puppet trigger frame")
        if frame < self.start_frame:
            raise ProjectError("Puppet events cannot precede the recording start frame.")
        self.frame = frame
        editor = AnimationEditingService(self.scratch)
        if editor.clip and frame > editor.clip.out_frame:
            editor.clip_settings(out_frame=frame)
        self.scratch.animation.seek(frame)
        duration = 0.0
        if (
            card.kind in ("motion", "replay")
            and self.active.get(card.target_id, card).kind == "replay"
        ):
            timeline, clip = editor.timeline, editor.clip
            prior = self.replay_audio.get(card.target_id, set())
            if timeline and clip:
                editor.publish(
                    "End previous replay",
                    replace(
                        timeline,
                        tracks=tuple(
                            replace(
                                t,
                                extra={
                                    **t.extra,
                                    "motion_window": {
                                        **t.extra["motion_window"],
                                        "end": min(frame, t.extra["motion_window"]["end"]),
                                    },
                                },
                            )
                            if t.extra.get("motion_window", {}).get("character") == card.target_id
                            and t.extra["motion_window"]["start"] < frame
                            else t
                            for t in timeline.tracks
                        ),
                    ),
                    replace(
                        clip,
                        extra={
                            **clip.extra,
                            "audio_tracks": tuple(
                                {**t, "end_frame": frame} if t["id"] in prior else t
                                for t in clip.extra["audio_tracks"]
                            ),
                        }
                        if "audio_tracks" in clip.extra
                        else clip.extra,
                    ),
                )
        if card.kind == "replay":
            if self.scratch.animation_context:
                raise ProjectError("Play replay cards in the main Scene.")
            source = next(
                (c for c in self.scratch.scene.clips if c.id == card.content["clip_id"]), None
            )
            if source is None:
                raise ProjectError("Replay action is missing. Capture an action in this project.")
            audio_source = self.scratch.fork()
            audio_source.separated_animation = False
            audio_source.select_animation_clip(source.id)
            source_audio = AudioService(audio_source).tracks()
            if any(t.get("loop_frames") for t in source_audio):
                raise ProjectError(
                    "Mix nested looping audio to WAV before capturing another replay."
                )
            if any(
                t.get("end_frame") is not None and t["end_frame"] < source.out_frame
                for t in source_audio
            ):
                raise ProjectError("Mix replay audio with an early end limit to WAV first.")
            if any(not 0.05 <= card.speed * t.get("rate", 1) <= 20 for t in source_audio):
                raise ProjectError("Combined replay/audio rate must remain between 0.05 and 20.")
            duration = max(1, source.out_frame - source.in_frame) / card.speed
            CharacterService(self.scratch).place_motion(
                card.target_id,
                source.id,
                frame,
                3600 if card.loop else duration / self.scratch.scene.settings.fps,
                speed=card.speed,
                repeat=card.loop,
            )
            sound = AudioService(self.scratch)
            prior = self.replay_audio.get(card.target_id, set())
            if prior and sound.clip and sound.timeline:
                sound.publish(
                    "Stop previous replay audio",
                    sound.timeline,
                    replace(
                        sound.clip,
                        extra={
                            **sound.clip.extra,
                            "audio_tracks": tuple(
                                {**t, "end_frame": frame} if t["id"] in prior else t
                                for t in sound.tracks()
                            ),
                        },
                    ),
                )
            self.replay_audio[card.target_id] = set()
            fps = number(self.scratch.scene.settings.fps)
            assert self.scratch.project is not None
            for audio_track in source_audio:
                delay = audio_track.get("start_frame", 0) - source.in_frame
                start = frame + max(0, delay) / card.speed
                trim = audio_track.get("trim_start", 0)
                advance = audio_track.get("source_offset", 0) + max(
                    0, -delay
                ) / fps * audio_track.get("rate", 1)
                asset = next(
                    a for a in self.scratch.project.assets if a.id == audio_track["asset_id"]
                )
                end = audio_track.get("trim_end", asset.extra["duration_seconds"])
                if trim + advance >= end:
                    continue
                identity = sound.put_track(
                    audio_track["asset_id"],
                    name="Replay · " + audio_track.get("name", "Voice"),
                    start=max(0, start),
                    trim_start=trim,
                    trim_end=end,
                    gain=audio_track.get("gain", 1),
                    muted=audio_track.get("muted", False)
                    or any(t.get("solo") for t in source_audio)
                    and not audio_track.get("solo", False),
                    fade_in=min(audio_track.get("fade_in", 0), end - trim),
                    fade_out=min(audio_track.get("fade_out", 0), end - trim),
                    rate=card.speed * audio_track.get("rate", 1),
                    loop_frames=duration if card.loop else 0,
                    source_offset=advance,
                    loop_start_frame=frame,
                    end_frame=frame + (3600 * fps if card.loop else duration),
                )
                self.replay_audio[card.target_id].add(identity)
            self.active[card.target_id] = card
            self.ranges[card.target_id] = frame, frame + duration
        elif card.kind == "motion":
            item = ContentItem.from_dict(json_copy(card.content))
            if item.kind == "deformation":
                if card.target_id in self.triggered:
                    previous = self.triggered[card.target_id]
                    begin = editor.clip.in_frame if editor.clip else self.start_frame
                    previous_stage = FfdMotionService(self.scratch).stage(previous)
                    editor.key(
                        previous,
                        "parameters.intensity",
                        begin,
                        number(previous_stage.parameters.get("intensity", 1)),
                        interpolation="step",
                    )
                    editor.key(previous, "parameters.intensity", frame, 0, interpolation="step")
                motion = replace(item, payload={**item.payload, "speed": card.speed})
                stage = FfdMotionService(self.scratch).apply_item(motion, card.target_id)
                self.triggered[card.target_id] = stage
                duration = (
                    number(item.payload["motion"]["duration"])
                    * self.scratch.animation.evaluator.scene.settings.fps
                    / number(item.payload["motion"].get("fps", 24))
                    / card.speed
                )
            else:
                service = ContentService(self.scratch)
                reason = service.compatibility(item, card.target_id)
                if reason:
                    raise ProjectError(reason)
                mapping = service.mapping(service.skeleton(card.target_id))
                fps = number(item.payload.get("fps", 24))
                if fps <= 0 or number(item.payload["duration"]) <= 0:
                    raise ProjectError("Motion frame rate and duration must be positive.")
                factor = self.scratch.animation.evaluator.scene.settings.fps / fps / card.speed
                duration = number(item.payload["duration"]) * factor
                timeline = editor.timeline or Timeline(name="Puppet performance")
                clip = editor.clip or AnimationClip(
                    name="Puppet performance", timeline_id=timeline.id, out_frame=frame
                )
                tracks = list(timeline.tracks)
                for channel in item.payload["channels"]:
                    owner, path = mapping[channel["semantic"]], f"transform.{channel['path']}"
                    track = next(
                        (
                            t
                            for t in reversed(tracks)
                            if t.owner_id == owner
                            and t.property_path == path
                            and t.blend_mode == "override"
                            and t.weight == 1
                            and not t.extra.get("motion_window")
                        ),
                        None,
                    )
                    track = track or Track(
                        name=f"Puppet · {channel['semantic']} · {channel['path']}",
                        owner_id=owner,
                        property_path=path,
                    )
                    editor.editable(track)
                    keys = [k for k in track.keyframes if k.frame < frame]
                    if not keys and frame > clip.in_frame:
                        base = getattr(
                            self.scratch.animation.pose.nodes[owner].local, channel["path"]
                        )
                        keys.append(Keyframe(frame=clip.in_frame, value=base, interpolation="step"))
                    keys.extend(
                        Keyframe(frame=frame + time * factor, value=value)
                        for time, value in channel["keys"]
                    )
                    metadata = {k: v for k, v in track.extra.items() if k != "cycle"}
                    if card.loop:
                        metadata["cycle"] = [frame, frame + duration]
                    updated = replace(track, keyframes=tuple(keys), extra=metadata)
                    tracks = [updated if t.id == track.id else t for t in tracks]
                    if not any(t.id == updated.id for t in tracks):
                        tracks.append(updated)
                editor.publish(
                    "Trigger body motion",
                    replace(timeline, tracks=tuple(tracks)),
                    replace(clip, out_frame=max(clip.out_frame, frame + duration)),
                )
            self.active[card.target_id] = card
            self.ranges[card.target_id] = frame, frame + duration
            if item.kind == "deformation" and card.loop:
                cycle_timeline, cycle_clip = editor.timeline, editor.clip
                assert cycle_timeline and cycle_clip
                cycle_tracks = tuple(
                    replace(t, extra={**t.extra, "cycle": [frame, frame + duration]})
                    if t.owner_id == self.triggered[card.target_id]
                    else t
                    for t in cycle_timeline.tracks
                )
                editor.publish(
                    "Loop Puppet FFD motion",
                    replace(cycle_timeline, tracks=cycle_tracks),
                    cycle_clip,
                )
        else:
            pose = self.scratch.animation.evaluate(frame)
            node = pose.nodes.get(card.target_id)
            if node is None:
                raise ProjectError("The motion card's target is missing from this scene.")
            if card.kind in ("flip_x", "flip_y"):
                component = "scale_x" if card.kind == "flip_x" else "scale_y"
                path, value = f"transform.{component}", -getattr(node.local, component)
            elif card.kind == "visibility":
                path, value = "visibility", float(not node.visible)
            else:
                path, value = "opacity", 0.25 if node.opacity > 0.5 else 1.0
            begin = editor.clip.in_frame if editor.clip else self.start_frame
            existing = editor.timeline
            has_track = existing is not None and any(
                t.owner_id == card.target_id and t.property_path == path for t in existing.tracks
            )
            if frame > begin and not has_track:
                base = (
                    getattr(node.local, component)
                    if card.kind in ("flip_x", "flip_y")
                    else float(node.visible)
                    if path == "visibility"
                    else node.opacity
                )
                editor.key(card.target_id, path, begin, base, interpolation="step")
            editor.key(card.target_id, path, frame, value, interpolation="step")
        self.events.append((card, frame, duration))

    def pose(self, frame: float) -> ScenePose:
        """Evaluate active looping triggers without changing source state or relying on seek
        order.
        """
        self.frame = number(frame)
        evaluator = self.scratch.animation.evaluator
        evaluator.range = FrameRange(
            evaluator.range.start, max(frame, evaluator.range.end), evaluator.range.fps
        )
        return evaluator.evaluate(frame)

    def recorded_command(self) -> ScenePatch | None:
        """Build looped recording data independently; the GUI can run this preparation in a
        worker.
        """
        if not self.recording or not self.events:
            return None
        captured = DocumentService(
            constraint_solvers=self.document.constraint_solvers,
            deformer_solvers=self.document.deformer_solvers,
            track_samplers=self.document.track_samplers,
        )
        captured.project = self.original
        captured.select_scene(self.scratch.scene.id)
        if self.base_clip:
            captured.select_animation_clip(self.base_clip)
        captured.animation.seek(self.start_frame)
        replay = PuppetSession(captured)
        events: list[tuple[float, int, MotionCard]] = []
        for index, (card, begin, duration) in enumerate(self.events):
            limit = next(
                (
                    t
                    for c, t, _ in self.events[index + 1 :]
                    if c.target_id == card.target_id and c.kind in ("motion", "replay")
                ),
                self.frame,
            )
            limit = min(limit, self.frame)
            time = begin
            while time <= limit:
                events.append((time, index, card))
                if len(events) > 10000:
                    raise ProjectError(
                        "A Puppet recording supports at most 10,000 repeated trigger events."
                    )
                if card.kind == "replay" or not card.loop or duration <= 0:
                    break
                time += duration
                if time >= limit - 1e-9:
                    break
        for time, _, card in sorted(events, key=lambda event: (event[0], event[1])):
            replay.trigger(card if card.kind == "replay" else replace(card, loop=False), time)
        assert replay.scratch.project is not None
        self.recorded_clip = replay.scratch.selected_clip_id
        before, after = (
            next(s for s in self.original.scenes if s.id == self.scratch.scene.id),
            replay.scratch.scene,
        )
        from rigora.engine.sampling import CompiledTrack

        original_tracks = {
            track.id: track for timeline in before.timelines for track in timeline.tracks
        }
        timelines = []
        for timeline in after.timelines:
            tracks = []
            for track in timeline.tracks:
                previous = original_tracks.get(track.id)
                if track != previous and track.extra.get("motion_window"):
                    window = track.extra["motion_window"]
                    track = replace(
                        track,
                        extra={
                            **track.extra,
                            "motion_window": {**window, "end": min(window["end"], self.frame)},
                        },
                    )
                elif track != previous:
                    value = CompiledTrack(track, self.document.track_samplers).sample(self.frame)
                    keys = {key.frame: key for key in track.keyframes if key.frame <= self.frame}
                    if value is not None:
                        keys[self.frame] = Keyframe(frame=self.frame, value=value)
                    if previous:
                        keys.update(
                            {key.frame: key for key in previous.keyframes if key.frame > self.frame}
                        )
                    track = replace(track, keyframes=tuple(keys[frame] for frame in sorted(keys)))
                tracks.append(track)
            timelines.append(replace(timeline, tracks=tuple(tracks)))
        original_clips = {clip.id: clip for clip in before.clips}
        after = replace(
            after,
            timelines=tuple(timelines),
            clips=tuple(
                replace(
                    clip,
                    extra={
                        **clip.extra,
                        "audio_tracks": tuple(
                            {**t, "end_frame": min(t.get("end_frame") or self.frame, self.frame)}
                            if t["id"] in {k for ids in replay.replay_audio.values() for k in ids}
                            else t
                            for t in clip.extra["audio_tracks"]
                        ),
                    }
                    if "audio_tracks" in clip.extra
                    else clip.extra,
                    out_frame=max(
                        self.frame,
                        original_clips[clip.id].out_frame
                        if clip.id in original_clips
                        else clip.in_frame,
                    ),
                )
                if clip != original_clips.get(clip.id)
                else clip
                for clip in after.clips
            ),
        )
        fields = {
            name: getattr(after, name)
            for name in ("objects", "deformers", "timelines", "clips")
            if getattr(before, name) != getattr(after, name)
        }
        return (
            ScenePatch(
                "Record Puppet performance",
                before.id,
                {name: getattr(before, name) for name in fields},
                fields,
            )
            if fields
            else None
        )

    def commit(self) -> None:
        """Publish one complete prepared performance only against its unchanged source revision."""
        if not self.recording:
            return
        command = self.recorded_command()
        self.apply_recorded(command)

    def apply_recorded(self, command: ScenePatch | None) -> None:
        """Publish a prepared take and select its resulting Scene timeline on the caller thread."""
        if (
            self.document.project is not self.original
            or self.document.scene.id != self.scratch.scene.id
            or (
                self.document.animation_context,
                self.document.animation_scope,
                self.document.selected_clip_id,
            )
            != self.context
        ):
            raise ProjectError(
                "The project changed during recording; the performance was not applied."
            )
        if command:
            self.document.execute(command)
            if self.recorded_clip:
                self.document.select_animation_clip(self.recorded_clip)
