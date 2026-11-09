"""Portable normalized FFD shapes and keyed motions layered onto canonical animation clips."""

from dataclasses import replace
from pathlib import Path
from typing import Any

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.deformation import DeformationPreset, DeformationService
from rigora.domain.content import ContentItem, ContentPack
from rigora.domain.entities import AnimationClip, Timeline, Track
from rigora.domain.project import ProjectError
from rigora.domain.validation import json_copy
from rigora.engine.deformation import lattice_controls
from rigora.engine.sampling import CompiledTrack, number
from rigora.infrastructure.content_packs import write_pack


class FfdMotionService(DeformationService):
    """Adapt normalized offsets to any mesh and retain bone motion on the same selected timeline."""

    def apply_item(self, item: ContentItem, mesh_id: str) -> str:
        """Add FFD atomically, retaining Scene drops as named Object actions with linked timing.

        Object Editor and legacy unseparated clients layer keys into the selected clip.
        Static shapes add only a deformation stage, without creating an action.
        New preset applications default to whole project frames; snap_to_frames=False
        preserves exact source timing for precision retiming and exported custom clips.
        """
        payload = item.payload
        snap_frames = payload.get("snap_to_frames", True)
        if type(snap_frames) is not bool:
            raise ProjectError("FFD frame snapping must be enabled or disabled.")
        columns, rows = payload.get("columns", 3), payload.get("rows", 3)
        if (
            type(columns) is not int
            or type(rows) is not int
            or not (2 <= columns <= 8 and 2 <= rows <= 8)
        ):
            raise ProjectError("FFD presets require a 2–8 control grid in each direction.")
        with self.document.command_group(f"Apply {item.name}"):
            start = self.document.animation.pose.frame
            if snap_frames:
                start = round(start)
            stage_id = self.add(
                mesh_id, DeformationPreset(item.name, "ffd", {}), columns=columns, rows=rows
            )
            params = json_copy(self.stage(stage_id).parameters)
            width, height = params["bounds"][2:]

            def offsets(values: Any) -> list[list[float]]:
                """Validate a complete normalized lattice frame and convert offsets to local
                pixels.
                """
                if not isinstance(values, (list, tuple)) or len(values) != columns * rows:
                    raise ProjectError("FFD preset frame has the wrong number of control points.")
                result = []
                for point in values:
                    if not isinstance(point, (list, tuple)) or len(point) != 2:
                        raise ProjectError("FFD offsets need numeric X/Y pairs.")
                    x, y = number(point[0]), number(point[1])
                    if abs(x) > 10 or abs(y) > 10:
                        raise ProjectError("Normalized FFD offsets exceed their supported range.")
                    result.append([x * width, y * height])
                return result

            if "shape" in payload:
                params["controls"] = offsets(payload["shape"])
            params["intensity"] = number(payload.get("strength", 1), "FFD clip strength")
            self.update(stage_id, parameters=params)
            motion = payload.get("motion")
            if not motion:
                return stage_id
            frames = motion["frames"]
            if not isinstance(frames, (tuple, list)) or not 2 <= len(frames) <= 256:
                raise ProjectError("FFD motion requires 2–256 complete lattice keyframes.")
            fps, duration = number(motion.get("fps", 24)), number(motion["duration"])
            speed = number(payload.get("speed", 1))
            repeats = payload.get("repeats", 1)
            if (
                fps <= 0
                or duration <= 0
                or not 0.05 <= speed <= 20
                or type(repeats) is not int
                or not 1 <= repeats <= 32
            ):
                raise ProjectError(
                    "FFD timing needs positive FPS/duration, speed 0.05–20 and 1–32 loops."
                )
            times = [number(frame[0]) for frame in frames]
            if (
                times[0] != 0
                or times[-1] != duration
                or any(a >= b for a, b in zip(times, times[1:], strict=False))
            ):
                raise ProjectError(
                    "FFD frames must increase strictly from zero through the duration."
                )
            sampled = [(time, offsets(frame[1])) for time, frame in zip(times, frames, strict=True)]
            factor = self.scene.settings.fps / fps / speed
            period = duration * repeats * factor
            if snap_frames:
                period = max(1, round(period))
            editor = AnimationEditingService(self.document)
            from rigora.application_services.characters import CharacterService

            characters = CharacterService(self.document)
            root = characters.object_root(mesh_id)
            owner = root.id if root else self.mesh(mesh_id).object_id
            reusable = bool(
                owner and self.document.separated_animation and not self.document.animation_context
            )
            scene_start = start
            if reusable:
                start = 0
                timeline = Timeline(name=item.name)
                clip = AnimationClip(
                    name=item.name,
                    timeline_id=timeline.id,
                    out_frame=0,
                    loop=bool(motion.get("loop", False)),
                    extra={
                        "object_id": owner,
                        "template_motion": item.id,
                        "continuous_loop": bool(motion.get("loop", False)),
                    },
                )
            else:
                timeline = editor.timeline or Timeline(name="FFD animation")
                clip = editor.clip or replace(
                    editor.blank_clip(timeline, item.name),
                    out_frame=start,
                    loop=bool(motion.get("loop", False)),
                )
            tracks = []
            for i in range(columns * rows):
                for axis in range(2):
                    values = {}
                    if start > clip.in_frame:
                        values[clip.in_frame] = 0.0
                    for repeat in range(repeats):
                        for time, points in sampled:
                            frame = start + (repeat * duration + time) * factor
                            values[round(frame) if snap_frames else frame] = points[i][axis]
                    # Quantized samples can collide at high speeds. Keep the
                    # exact opening and closing poses even when nearby keys merge.
                    if snap_frames:
                        values[start] = sampled[0][1][i][axis]
                        values[start + period] = sampled[-1][1][i][axis]
                    from rigora.application_services.template_effects import smooth_keys

                    keys = smooth_keys(
                        sorted(values.items()), loop=bool(motion.get("loop", False)) and start == 0
                    )
                    tracks.append(
                        Track(
                            name=f"FFD · {item.name} · dot {i} {'XY'[axis]}",
                            owner_id=stage_id,
                            property_path=f"parameters.controls.{i}.{axis}",
                            keyframes=keys,
                        )
                    )
            editor.publish(
                "Layer FFD motion",
                replace(timeline, tracks=(*timeline.tracks, *tracks)),
                replace(
                    clip,
                    out_frame=max(
                        clip.out_frame,
                        start + period - (1 if motion.get("loop", False) else 0),
                    ),
                ),
            )
            if reusable and owner:
                characters.place_motion(
                    owner,
                    clip.id,
                    scene_start,
                    period / self.scene.settings.fps,
                    repeat=clip.loop,
                )
            return stage_id

    def object_strength(self, mesh_id: str, strength: float) -> None:
        """Set the mesh-wide FFD multiplier independently of any individual stage's intensity."""
        value = number(strength, "Object FFD strength")
        if not 0 <= value <= 10:
            raise ProjectError("Object FFD strength must be between 0 and 10.")
        mesh = self.mesh(mesh_id)
        self.replace_mesh(
            replace(mesh, extra={**mesh.extra, "ffd_strength": value}), "Set object FFD strength"
        )

    def export(
        self,
        path: Path,
        stage_id: str,
        name: str,
        author: str,
        license: str,
        *,
        animated: bool = True,
        overwrite: bool = False,
    ) -> None:
        """Share normalized controls and optional selected-clip keys in an artwork-independent
        pack.
        """
        stage = self.stage(stage_id)
        if stage.kind not in ("ffd", "lattice"):
            raise ProjectError("Choose an FFD/lattice stage to share.")
        columns, rows, controls = lattice_controls(stage.parameters)
        width, height = stage.parameters["bounds"][2:]
        payload: dict[str, Any] = {
            "kind": "ffd",
            "columns": columns,
            "rows": rows,
            "shape": [[x / width, y / height] for x, y in controls],
            "strength": stage.parameters.get("intensity", 1),
        }
        editor = AnimationEditingService(self.document)
        tracks = (
            [t for t in editor.timeline.tracks if t.owner_id == stage_id] if editor.timeline else []
        )
        if animated and tracks and editor.clip:
            begin, end = editor.clip.in_frame, editor.clip.out_frame
            if end <= begin:
                raise ProjectError("FFD motion sharing requires a nonzero clip duration.")
            times = sorted(
                {
                    begin,
                    end,
                    *(k.frame for t in tracks for k in t.keyframes if begin <= k.frame <= end),
                }
            )
            if len(times) > 256:
                raise ProjectError("FFD sharing supports at most 256 distinct control key times.")
            samplers = {
                t.property_path: CompiledTrack(t, self.document.track_samplers) for t in tracks
            }
            frames = []
            for time in times:
                points = [list(p) for p in controls]
                for i in range(len(points)):
                    for axis in range(2):
                        sampler = samplers.get(f"parameters.controls.{i}.{axis}")
                        value = sampler.sample(time) if sampler else None
                        points[i][axis] = (value if value is not None else points[i][axis]) / (
                            width if axis == 0 else height
                        )
                frames.append([time - begin, points])
            payload["motion"] = {
                "fps": self.scene.settings.fps,
                "duration": end - begin,
                "frames": frames,
            }
        item = ContentItem(
            name=name,
            kind="deformation",
            category="FFD motions" if "motion" in payload else "FFD shapes",
            author=author,
            license=license,
            tags=("ffd", "custom"),
            payload={**payload, "snap_to_frames": False},
        )
        write_pack(
            path,
            ContentPack(name=name, author=author, license=license, items=(item,)),
            {},
            overwrite=overwrite,
        )
