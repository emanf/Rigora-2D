"""Portable clip audio timing shared by authoring, playback and export hosts."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.domain.entities import Timeline
from rigora.domain.project import ProjectError
from rigora.engine.audio_mix import track_state, write_mix
from rigora.engine.sampling import number


@dataclass(frozen=True)
class AudioPosition:
    """An embedded source and its elapsed source time at the current scene frame."""

    asset_id: str
    seconds: float
    duration: float
    gain: float
    muted: bool
    track_id: str = "legacy"
    start_seconds: float = 0
    rate: float = 1


class AudioService(AnimationEditingService):
    """Associate an embedded audio asset with the selected clip in one undoable edit."""

    def attach(
        self, asset_id: str, *, start: float = 0, gain: float = 1, muted: bool = False
    ) -> None:
        """Place source time zero at a nonnegative scene frame and extend the clip to fit."""
        if self.clip and "audio_tracks" in self.clip.extra:
            legacy = next((t for t in self.tracks() if t["id"] == "legacy"), None)
            with self.document.command_group("Attach clip voice"):
                key = self.put_track(
                    asset_id,
                    identity="legacy" if legacy else "",
                    name="Voice",
                    start=start,
                    gain=gain,
                    muted=muted,
                )
                if not legacy:
                    assert self.clip is not None and self.timeline is not None
                    self.publish(
                        "Identify clip voice",
                        self.timeline,
                        replace(
                            self.clip,
                            extra={
                                **self.clip.extra,
                                "audio_tracks": tuple(
                                    {**t, "id": "legacy"} if t["id"] == key else t
                                    for t in self.tracks()
                                ),
                            },
                        ),
                    )
            return
        start, gain = number(start), number(gain)
        project = self.document.project
        asset = next((a for a in project.assets if a.id == asset_id), None) if project else None
        if asset is None or asset.kind != "audio":
            raise ProjectError("Choose an imported audio asset.")
        if start < 0 or not 0 <= gain <= 1 or type(muted) is not bool:
            raise ProjectError("Audio requires a nonnegative start, volume 0–1 and boolean mute.")
        duration = number(asset.extra.get("duration_seconds", 0))
        if not 0 < duration <= 1800:
            raise ProjectError("Audio source has invalid duration metadata.")
        timeline = self.timeline or Timeline(name="Audio animation")
        clip = self.clip or self.blank_clip(timeline, "Audio animation")
        self.publish(
            "Attach clip audio",
            timeline,
            replace(
                clip,
                out_frame=max(clip.out_frame, start + duration * self.scene.settings.fps),
                extra={
                    **clip.extra,
                    "audio": {
                        "asset_id": asset_id,
                        "start_frame": start,
                        "gain": gain,
                        "muted": muted,
                    },
                },
            ),
        )

    def detach(self) -> None:
        """Remove clip playback association while retaining the reusable embedded source."""
        clip, timeline = self.clip, self.timeline
        if clip and timeline and any(k in clip.extra for k in ("audio", "audio_tracks")):
            self.publish(
                "Detach clip audio",
                timeline,
                replace(
                    clip,
                    extra={
                        k: v for k, v in clip.extra.items() if k not in ("audio", "audio_tracks")
                    },
                ),
            )

    def position(self, frame: float) -> AudioPosition | None:
        """Resolve timing without reading bytes or changing the saved model."""
        values = self.positions(frame)
        return values[0] if values else None

    def tracks(self) -> tuple[Mapping[str, Any], ...]:
        """Read multitrack settings, adapting the legacy single voice without rewriting it."""
        clip = self.clip
        if clip is None:
            return ()
        tracks = clip.extra.get("audio_tracks")
        if tracks is not None:
            if not isinstance(tracks, (tuple, list)) or len(tracks) > 32:
                raise ProjectError("Audio supports up to 32 tracks per clip.")
            identities = set()
            assets = (
                {a.id: a for a in self.document.project.assets} if self.document.project else {}
            )
            for track in tracks:
                if (
                    not isinstance(track, Mapping)
                    or not isinstance(track.get("id"), str)
                    or not track["id"]
                    or not isinstance(track.get("asset_id"), str)
                    or track["id"] in identities
                    or any(type(track.get(k, False)) is not bool for k in ("muted", "solo"))
                ):
                    raise ProjectError(
                        "Audio tracks require unique IDs, source assets and boolean Mute/Solo."
                    )
                identities.add(track["id"])
                asset = assets.get(track["asset_id"])
                if asset is None or asset.kind != "audio":
                    raise ProjectError("An audio track source is missing or is not an audio asset.")
                track_state(
                    track,
                    0,
                    self.scene.settings.fps,
                    number(asset.extra.get("duration_seconds", 0)),
                )
            return tuple(tracks)
        legacy = clip.extra.get("audio")
        return ({"id": "legacy", "name": "Voice", **legacy},) if isinstance(legacy, Mapping) else ()

    def put_track(
        self,
        asset_id: str,
        *,
        identity: str = "",
        name: str = "Audio",
        start: float = 0,
        trim_start: float = 0,
        trim_end: float | None = None,
        gain: float = 1,
        fade_in: float = 0,
        fade_out: float = 0,
        muted: bool = False,
        solo: bool = False,
        rate: float = 1,
        loop_frames: float = 0,
        end_frame: float | None = None,
        source_offset: float = 0,
        loop_start_frame: float | None = None,
    ) -> str:
        """Edit a stable track using seconds for trims/fades and scene frames for placement."""
        project = self.document.project
        asset = next((a for a in project.assets if a.id == asset_id), None) if project else None
        if asset is None or asset.kind != "audio":
            raise ProjectError("Choose an imported PCM WAV asset.")
        if number(start) < 0 or type(muted) is not bool or type(solo) is not bool:
            raise ProjectError("Audio start must be nonnegative; Mute/Solo must be boolean.")
        key = identity or str(uuid4())
        if identity and not any(t["id"] == identity for t in self.tracks()):
            raise ProjectError("The audio track was removed. Select another track.")
        data: dict[str, Any] = dict(
            id=key,
            name=name,
            asset_id=asset_id,
            start_frame=number(start),
            trim_start=number(trim_start),
            trim_end=number(trim_end if trim_end is not None else asset.extra["duration_seconds"]),
            gain=number(gain),
            fade_in=number(fade_in),
            fade_out=number(fade_out),
            muted=muted,
            solo=solo,
            rate=number(rate),
            loop_frames=number(loop_frames),
            end_frame=number(end_frame) if end_frame is not None else None,
            source_offset=number(source_offset),
            loop_start_frame=number(loop_start_frame) if loop_start_frame is not None else None,
        )
        track_state(data, start, self.scene.settings.fps, asset.extra["duration_seconds"])
        tracks = tuple(t for t in self.tracks() if t["id"] != key) + (data,)
        if len(tracks) > 32:
            raise ProjectError("Audio supports up to 32 tracks per clip.")
        timeline = self.timeline or Timeline(name="Audio animation")
        clip = self.clip or self.blank_clip(timeline, "Audio animation")
        self.publish(
            "Edit audio track",
            timeline,
            replace(
                clip,
                out_frame=max(
                    clip.out_frame,
                    end_frame
                    if end_frame is not None
                    else start
                    + (data["trim_end"] - data["trim_start"] - source_offset)
                    / rate
                    * self.scene.settings.fps,
                ),
                extra={
                    **{k: v for k, v in clip.extra.items() if k != "audio"},
                    "audio_tracks": tracks,
                },
            ),
        )
        return key

    def remove_track(self, identity: str) -> None:
        """Delete one placement, preserving source bytes and other sound/music/voice tracks."""
        clip, timeline = self.clip, self.timeline
        if clip and timeline:
            self.publish(
                "Remove audio track",
                timeline,
                replace(
                    clip,
                    extra={
                        **{k: v for k, v in clip.extra.items() if k != "audio"},
                        "audio_tracks": tuple(t for t in self.tracks() if t["id"] != identity),
                    },
                ),
            )

    def positions(self, frame: float) -> tuple[AudioPosition, ...]:
        """Resolve every source cursor with exclusive trims, fades and per-clip Solo."""
        project = self.document.project
        assets = {a.id: a for a in project.assets} if project else {}
        tracks = self.tracks()
        solo = any(t.get("solo") and not t.get("muted") for t in tracks)
        result = []
        for track in tracks:
            asset = assets.get(track["asset_id"])
            if asset is None or asset.kind != "audio":
                continue
            seconds, end, gain = track_state(
                track, number(frame), self.scene.settings.fps, asset.extra["duration_seconds"]
            )
            result.append(
                AudioPosition(
                    asset.id,
                    seconds,
                    end,
                    gain,
                    bool(track.get("muted") or solo and not track.get("solo")),
                    track["id"],
                    track.get("trim_start", 0),
                    track.get("rate", 1),
                )
            )
        return tuple(result)

    def mix(
        self, path: Path, *, start: float, seconds: float, cancelled: Any = lambda: None
    ) -> None:
        """Write the shared deterministic clip mix for rendered output without an audio device."""
        write_mix(
            path,
            tuple((t, self.document.read_asset(t["asset_id"])) for t in self.tracks()),
            start=start,
            duration=seconds,
            fps=self.scene.settings.fps,
            cancelled=cancelled,
        )
