"""Local vector facial rigs, keyed expressions and editable timed mouth switching."""

import io
import wave
from collections.abc import Iterable, Mapping
from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import Any

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.domain.entities import (
    Constraint,
    Group,
    Keyframe,
    Timeline,
    Track,
    Transform,
)
from rigora.domain.geometry import affine, inverse, multiply
from rigora.domain.project import ProjectError
from rigora.engine.sampling import number
from rigora.infrastructure.media_import import audio_metadata
from rigora.infrastructure.speech import analyze_builtin_speech, analyze_speech

VISEMES = ("Rest", "AI", "E", "O", "U", "FV", "L", "MBP", "WQ", "TH")
PHONEMES = {
    **dict.fromkeys(("AA", "AE", "AH", "AY", "AW", "A", "I"), "AI"),
    **dict.fromkeys(("EH", "EY", "EE", "IH", "IY", "E"), "E"),
    **dict.fromkeys(("AO", "OW", "OY", "O"), "O"),
    **dict.fromkeys(("UH", "UW", "U"), "U"),
    **dict.fromkeys(("F", "V"), "FV"),
    **dict.fromkeys(("M", "B", "P"), "MBP"),
    **dict.fromkeys(("W", "Q"), "WQ"),
    **dict.fromkeys(("TH", "DH"), "TH"),
    **dict.fromkeys(
        (
            "L",
            "D",
            "T",
            "N",
            "S",
            "Z",
            "R",
            "SH",
            "CH",
            "JH",
            "ZH",
            "K",
            "G",
            "HH",
            "NG",
            "Y",
            "ER",
        ),
        "L",
    ),
    **dict.fromkeys(("", "SIL", "SP", "REST", "PAUSE", "+SPN+"), "Rest"),
}
EXPRESSIONS = {
    "Neutral": (0, "Rest"),
    "Happy": (-12, "E"),
    "Sad": (18, "Rest"),
    "Angry": (-25, "MBP"),
    "Surprised": (10, "O"),
    "Sleepy": (4, "Rest"),
}


def viseme(phoneme: str) -> str:
    """Map a viseme name or ARPAbet phoneme with optional stress digit to a mouth shape."""
    token = phoneme.strip().upper().rstrip("012")
    shapes = {name.upper(): name for name in VISEMES}
    if token in shapes:
        return shapes[token]
    if token not in PHONEMES:
        raise ProjectError(f"Unknown phoneme {phoneme!r}; use a mouth name or ARPAbet phoneme.")
    return PHONEMES[token]


def _mouth_parts(face: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    """Key every retained mouth set; its wardrobe group determines which set is visible."""
    sets = face.get("mouth_sets", {"Default": face["mouths"]})
    if not isinstance(sets, Mapping) or any(
        not isinstance(parts, Mapping) or set(parts) != set(VISEMES) for parts in sets.values()
    ):
        raise ProjectError("This facial descriptor has an incomplete mouth set.")
    return tuple((name, key) for parts in sets.values() for name, key in parts.items())


def waveform(data: bytes, bins: int = 1024) -> tuple[float, tuple[float, ...]]:
    """Read bounded PCM WAV locally and return duration plus sampled peak envelopes.

    At most 128 evenly spaced samples per bin are inspected. This lightweight
    envelope assists timing and jaw motion; it does not infer spoken phonemes.
    """
    if len(data) > 16 * 1024 * 1024 or not 16 <= bins <= 4096:
        raise ProjectError("Waveform analysis supports WAV files up to 16 MiB and 16–4096 bins.")
    info = audio_metadata(data)
    with wave.open(io.BytesIO(data)) as audio:
        raw = audio.readframes(audio.getnframes())
    frames, width, channels = info["sample_frames"], info["sample_bytes"], info["channels"]
    stride = width * channels
    peaks = []
    for index in range(bins):
        start, end = index * frames // bins, (index + 1) * frames // bins
        peak = 0.0
        for frame in range(start, end, max(1, (end - start) // 128)):
            for channel in range(channels):
                offset = frame * stride + channel * width
                value = int.from_bytes(raw[offset : offset + width], "little", signed=width != 1)
                value = value - 128 if width == 1 else value
                peak = max(peak, abs(value) / (128 if width == 1 else 2 ** (8 * width - 1)))
        peaks.append(peak)
    return float(info["duration_seconds"]), tuple(peaks)


class FaceService(AnimationEditingService):
    """Author ordinary vector objects and scalar keys usable by every renderer and client."""

    def enable_character(self, root_id: str) -> str:
        """Use authored facial controls without regenerating retired character art."""
        self.face(root_id)
        return root_id

    def face(self, group_id: str) -> Any:
        """Resolve a persisted facial control descriptor and reject missing object references."""
        group = next((g for g in self.scene.groups if g.id == group_id), None)
        if group is None or "face" not in group.extra:
            raise ProjectError("Choose a facial rig first.")
        face = group.extra["face"]
        if (
            not isinstance(face, Mapping)
            or not isinstance(face.get("mouths"), Mapping)
            or set(face["mouths"]) != set(VISEMES)
            or face.get("kind") != "character-mouth"
            and any(
                not isinstance(face.get(field), (tuple, list)) or len(face[field]) != 2
                for field in ("eyes", "pupils", "brows")
            )
        ):
            raise ProjectError(
                "This facial descriptor is incomplete; restore its parts or create a new face."
            )
        from rigora.application_services.scene_editing import SceneEditingService

        if SceneEditingService(self.document).locked(group_id):
            raise ProjectError("Unlock the face controls before editing them.")
        references = (
            *(key for _, key in _mouth_parts(face)),
            *face.get("eyes", ()),
            *face.get("pupils", ()),
            *face.get("brows", ()),
        )
        if any(not isinstance(key, str) for key in references):
            raise ProjectError("Face part references must be scene object identities.")
        ids = set(references)
        if not ids <= {o.id for o in self.scene.objects}:
            raise ProjectError(
                "This face has missing parts; undo the deletion or create a new face."
            )
        scope = self.document.animation_scope
        if scope is not None and not ids <= scope:
            raise ProjectError(
                "Open this character in Object Editor, or return to Scene, before keying its face."
            )
        return face

    def create(self, *, parent_bone: str | None = None, x: float = 600, y: float = 350) -> str:
        """Create replaceable original SVG mouth/eye parts and an optional bone-following anchor."""
        if parent_bone and parent_bone not in {b.id for s in self.scene.skeletons for b in s.bones}:
            raise ProjectError("Choose an existing head bone for attachment.")
        offset = None
        if parent_bone:
            matrix = self.document.animation.pose.nodes[parent_bone].world_matrix
            x, y = matrix[4:]
            offset = multiply(inverse(matrix), affine(x, y, 0, 1, 1, 0, 0))
        group = Group(name="Face controls", transform=Transform(x=x, y=y))
        mouths: dict[str, str] = {}
        parts: dict[str, list[str]] = {"eyes": [], "pupils": [], "brows": []}
        with self.document.command_group("Create vector facial rig"):
            self.commit("Face anchor", groups=(*self.scene.groups, group))
            for name in (*VISEMES, "eye", "pupil", "brow"):
                from rigora.infrastructure.illustration import face_component

                data = face_component(name)
                asset = self.register_image_bytes(f"Face {name}.svg", data)
                for side in range(1 if name in VISEMES else 2):
                    mesh_id = self.instantiate_asset(asset, 1, 1)
                    mesh = self.mesh(mesh_id)
                    obj = next(o for o in self.scene.objects if o.id == mesh.object_id)
                    mouth = name in VISEMES
                    transform = Transform(
                        x=-32 if mouth else (-55 if side == 0 else 15),
                        y=25 if mouth else (-42 if name != "brow" else -65),
                        pivot_x=0,
                        pivot_y=0,
                    )
                    obj = replace(
                        obj,
                        name=f"{name}" if mouth else f"{name}.{side}",
                        parent_id=group.id,
                        transform=transform,
                        visible=name == "Rest" if mouth else True,
                    )
                    self.commit(
                        "Place face part",
                        objects=tuple(obj if o.id == obj.id else o for o in self.scene.objects),
                    )
                    if mouth:
                        mouths[name] = obj.id
                    else:
                        parts[{"eye": "eyes", "pupil": "pupils", "brow": "brows"}[name]].append(
                            obj.id
                        )
            descriptor = {"mouths": mouths, **parts, "parent_bone": parent_bone}
            self.commit(
                "Configure face",
                groups=tuple(
                    replace(g, extra={**g.extra, "face": descriptor}) if g.id == group.id else g
                    for g in self.scene.groups
                ),
                constraints=(
                    *self.scene.constraints,
                    Constraint(
                        kind="parent",
                        owner_id=group.id,
                        target_id=parent_bone,
                        parameters={"offset": offset},
                    ),
                )
                if parent_bone
                else self.scene.constraints,
            )
        return group.id

    def controls(
        self,
        group_id: str,
        frame: float,
        *,
        expression: str = "Neutral",
        look_x: float = 0,
        look_y: float = 0,
        blink: float = 0,
        mouth: str | None = None,
    ) -> None:
        """Key expressions, eye direction, blink and a mutually exclusive mouth at one frame."""
        face = self.face(group_id)
        if (
            expression not in EXPRESSIONS
            or not 0 <= number(blink) <= 1
            or not -1 <= number(look_x) <= 1
            or not -1 <= number(look_y) <= 1
        ):
            raise ProjectError(
                "Choose an expression, normalized gaze and blink between zero and one."
            )
        angle, default = EXPRESSIONS[expression]
        selected = viseme(mouth or default)
        with self.document.command_group("Key face controls"):
            for name, key in _mouth_parts(face):
                self.key(key, "visibility", frame, float(name == selected), interpolation="step")
            for key in (*face.get("eyes", ()), *face.get("pupils", ())):
                self.key(key, "transform.scale_y", frame, max(0.04, 1 - blink))
            for index, key in enumerate(face.get("brows", ())):
                self.key(key, "transform.rotation", frame, angle * (-1 if index else 1))
            for key in face.get("pupils", ()):
                obj = next(o for o in self.scene.objects if o.id == key)
                self.key(key, "transform.x", frame, obj.transform.x + look_x * 10)
                self.key(key, "transform.y", frame, obj.transform.y + look_y * 7)

    def blink(self, group_id: str, frame: float, duration: float = 6) -> None:
        """Insert a three-key eyelid cycle while retaining existing gaze and mouth channels."""
        face = self.face(group_id)
        if not face.get("eyes"):
            raise ProjectError(
                "This creator character uses Eye pose variants for blinking. "
                "Choose Closed and Open in Object Editor to key those variants."
            )
        if not 0 < number(duration) <= 240:
            raise ProjectError("Blink duration must be above zero and at most 240 frames.")
        with self.document.command_group("Add blink"):
            for key in (*face["eyes"], *face["pupils"]):
                for time, scale in (
                    (frame, 1),
                    (frame + duration / 2, 0.04),
                    (frame + duration, 1),
                ):
                    self.key(key, "transform.scale_y", time, scale)

    def lip_sync(
        self,
        group_id: str,
        cues: Iterable[tuple[float, str]],
        *,
        start: float = 0,
        audio_asset: str | None = None,
    ) -> None:
        """Merge timed phoneme/viseme cues into editable step keys in one atomic command.

        Cue times are seconds relative to start (in frames). Existing mouth keys at
        other times survive. Optional audio association is stored on the clip.
        """
        face = self.face(group_id)
        values = list(cues)
        if not 1 <= len(values) <= 5000 or number(start) < 0:
            raise ProjectError("Supply 1–5000 cues and a nonnegative start frame.")
        events = {}
        for seconds, phoneme in values:
            if not 0 <= number(seconds) <= 1800:
                raise ProjectError("Cue times must lie within 30 minutes.")
            events[start + seconds * self.scene.settings.fps] = viseme(phoneme)
        project = self.document.project
        if audio_asset and (
            project is None
            or not any(a.id == audio_asset and a.kind == "audio" for a in project.assets)
        ):
            raise ProjectError("Choose an imported audio asset.")
        timeline = self.timeline or Timeline(name="Facial animation")
        clip = self.clip or self.blank_clip(timeline, "Facial animation")
        tracks = list(timeline.tracks)
        for name, key in _mouth_parts(face):
            track = next(
                (t for t in tracks if t.owner_id == key and t.property_path == "visibility"),
                Track(name=f"Mouth · {name}", owner_id=key, property_path="visibility"),
            )
            self.editable(track)
            keys = tuple(k for k in track.keyframes if k.frame not in events)
            if min(events) > 0 and not any(k.frame < min(events) for k in keys):
                keys = (*keys, Keyframe(frame=0, value=float(name == "Rest"), interpolation="step"))
            keys = (
                *keys,
                *(
                    Keyframe(frame=time, value=float(shape == name), interpolation="step")
                    for time, shape in events.items()
                ),
            )
            updated = replace(track, keyframes=tuple(sorted(keys, key=lambda k: k.frame)))
            tracks = (
                [updated if t.id == track.id else t for t in tracks]
                if track in tracks
                else [*tracks, updated]
            )
        self.publish(
            "Create lip-sync keys",
            replace(timeline, tracks=tuple(tracks)),
            replace(
                clip,
                out_frame=max(clip.out_frame, max(events)),
                extra={
                    **clip.extra,
                    "audio": {
                        **clip.extra.get("audio", {}),
                        "asset_id": audio_asset,
                        "start_frame": start,
                    },
                }
                if audio_asset
                else clip.extra,
            ),
        )

    def audio_cues(self, data: bytes, threshold: float = 0.08) -> tuple[tuple[float, str], ...]:
        """Suggest energy-driven open/rest cues locally without claiming speech recognition."""
        if not 0 < number(threshold) < 1:
            raise ProjectError("Voice threshold must be above zero and below one.")
        duration, peaks = waveform(data, 512)
        cues, previous = [], ""
        for index, peak in enumerate(peaks):
            shape = "AI" if peak > threshold else "Rest"
            if shape != previous:
                cues.append((duration * index / len(peaks), shape))
                previous = shape
        cues.append((duration, "Rest"))
        return tuple(cues)

    @staticmethod
    def speech_cues(
        data: bytes,
        executable: Path | None = None,
        *,
        transcript: str = "",
        recognizer: str = "phonetic",
        cancel: Event | None = None,
    ) -> tuple[tuple[float, str], ...]:
        """Use built-in offline phoneme recognition or an explicit legacy external tool."""
        if recognizer not in ("phonetic", "pocketSphinx") or len(transcript) > 100000:
            raise ProjectError(
                "Choose a supported recognizer and reference text below 100,000 characters."
            )
        if executable is None:
            return analyze_builtin_speech(data, cancel=cancel)
        return analyze_speech(
            data, executable, transcript=transcript, recognizer=recognizer, cancel=cancel
        )
