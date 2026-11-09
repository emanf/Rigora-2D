"""Common-timeline deformation keys and portable, data-only deformation clip exchange."""

from dataclasses import replace
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.deformation import DeformationPreset, DeformationService
from rigora.domain.entities import AnimationClip, Keyframe, Timeline, Track
from rigora.domain.mesh_geometry import mesh_bounds
from rigora.domain.project import ProjectError
from rigora.domain.validation import json_copy
from rigora.engine.deformation import DeformationPlan
from rigora.engine.sampling import CompiledTrack, number
from rigora.infrastructure.deformation_clips import read_motion, write_motion


class DeformationMotionService(DeformationService):
    """Edit numeric keys without introducing a second timeline or animation evaluation system."""

    def key(
        self,
        owner: str,
        path: str,
        frame: float,
        value: float,
        *,
        interpolation: Literal["step", "linear", "bezier"] = "linear",
        delete: bool = False,
    ) -> None:
        """Insert, replace or remove a key on the selected clip; create a first clip when needed."""
        DeformationPlan(self.scene).base(owner, path)
        if any(v.id == owner and v.protected for mesh in self.scene.meshes for v in mesh.vertices):
            raise ProjectError("Unprotect the selected vertex before editing its animation keys.")
        selected = self.document.animation.evaluator.clip
        timeline = next(
            (t for t in self.scene.timelines if selected and t.id == selected.timeline_id), None
        )
        timeline = timeline or Timeline(name="Deformation")
        clip = selected or AnimationClip(
            name="Deformation", timeline_id=timeline.id, out_frame=self.scene.settings.end_frame
        )
        track = next(
            (t for t in timeline.tracks if t.owner_id == owner and t.property_path == path), None
        )
        track = track or Track(name=path, owner_id=owner, property_path=path)
        AnimationEditingService(self.document).insertion_editable(track)
        previous = next((k for k in track.keyframes if k.frame == frame), None)
        key = Keyframe(
            id=previous.id if previous else str(uuid4()),
            frame=frame,
            value=value,
            interpolation=interpolation,
        )
        keys = [k for k in track.keyframes if k.frame != frame]
        if not delete:
            if not track.keyframes and frame > self.scene.settings.start_frame:
                keys.append(
                    Keyframe(
                        frame=self.scene.settings.start_frame,
                        value=DeformationPlan(self.scene).base(owner, path),
                        interpolation="linear",
                    )
                )
            keys.append(key)
        track = replace(track, keyframes=tuple(sorted(keys, key=lambda k: k.frame)))
        CompiledTrack(track, self.document.track_samplers)
        tracks = tuple(t for t in timeline.tracks if t.id != track.id)
        timeline = replace(timeline, tracks=(*tracks, track) if keys else tracks)
        clip = replace(
            clip, in_frame=min(clip.in_frame, frame), out_frame=max(clip.out_frame, frame)
        )
        self.commit(
            "Delete deformation key" if delete else "Set deformation key",
            timelines=(*(t for t in self.scene.timelines if t.id != timeline.id), timeline),
            clips=tuple(clip if c.id == clip.id else c for c in self.scene.clips)
            if selected
            else (*self.scene.clips, clip),
        )

    def clip_data(self, stage_id: str) -> dict[str, Any]:
        """Export a stage and vertex tracks using portable logical indices."""
        stage = self.stage(stage_id)
        if stage.kind == "skinning":
            raise ProjectError(
                "Bone binding is project-specific; export a geometric deformer instead."
            )
        mesh = self.mesh(stage.owner_id)
        clip = self.document.animation.evaluator.clip
        if clip is None:
            raise ProjectError("Create deformation keys before exporting a motion clip.")
        timeline = next(t for t in self.scene.timelines if t.id == clip.timeline_id)
        indices = {v.id: str(i) for i, v in enumerate(mesh.vertices)}
        params = json_copy(stage.parameters)
        for field in ("weights", "pins", "offsets"):
            if field in params:
                params[field] = {
                    indices[k]: value for k, value in params[field].items() if k in indices
                }
        tracks = []
        for track in timeline.tracks:
            if track.owner_id != stage.id and track.owner_id not in indices:
                continue
            record = track.to_dict()
            record["owner_id"] = "stage" if track.owner_id == stage.id else indices[track.owner_id]
            parts = record["property_path"].split(".")
            if len(parts) > 2 and parts[0:2] in (
                ["parameters", "pins"],
                ["parameters", "weights"],
                ["parameters", "offsets"],
            ):
                parts[2] = indices[parts[2]]
                record["property_path"] = ".".join(parts)
            tracks.append(record)
        if not tracks:
            raise ProjectError("This clip contains no keys for the selected deformer or mesh.")
        return {
            "format": "rigora.deformation-clip",
            "version": 1,
            "name": clip.name,
            "kind": stage.kind,
            "parameters": params,
            "bounds": list(mesh_bounds(mesh)),
            "vertex_count": len(mesh.vertices),
            "topology": [[indices[k] for k in face] for face in mesh.triangles],
            "fps": self.scene.settings.fps,
            "in_frame": clip.in_frame,
            "out_frame": clip.out_frame,
            "loop": clip.loop,
            "tracks": tracks,
        }

    def export_clip(self, stage_id: str, path: Path, *, overwrite: bool = False) -> None:
        """Write bounded original motion data, refusing accidental overwrite by default."""
        write_motion(path, self.clip_data(stage_id), overwrite=overwrite)

    def import_clip(self, mesh_id: str, path: Path) -> tuple[str, str]:
        """Read a bounded motion file and adapt it to compatible geometry."""
        try:
            return self.apply_clip(mesh_id, read_motion(path))
        except (ValueError, KeyError, TypeError, IndexError, OverflowError) as error:
            raise ProjectError(f"Invalid deformation clip: {error}") from error

    def apply_clip(self, mesh_id: str, data: dict[str, Any]) -> tuple[str, str]:
        """Remap identities and spatial values; publish the new stack stage and timeline
        atomically.
        """
        mesh = self.mesh(mesh_id)
        if data.get("format") != "rigora.deformation-clip" or data.get("version") != 1:
            raise ProjectError("Unsupported deformation clip format.")
        if data["vertex_count"] != len(mesh.vertices):
            raise ProjectError(
                "Reusable vertex/pin clips require the same grid vertex count and ordering."
            )
        target_indices = {v.id: str(i) for i, v in enumerate(mesh.vertices)}
        if data.get("topology") != [[target_indices[k] for k in face] for face in mesh.triangles]:
            raise ProjectError(
                "Reusable clips require matching triangle topology and vertex ordering."
            )
        sx, sy, sw, sh = (number(v, "Motion bounds") for v in data["bounds"])
        x, y, w, h = mesh_bounds(mesh)
        if min(sw, sh) <= 0:
            raise ProjectError("Invalid source motion bounds.")
        rx, ry = w / sw, h / sh
        params = json_copy(data["parameters"])
        params["bounds"] = [x, y, w, h]
        for field, factor in (("x", rx), ("y", ry), ("radius", min(rx, ry))):
            if field in params:
                params[field] *= factor
        for field, origin, source, factor in (("pivot_x", x, sx, rx), ("pivot_y", y, sy, ry)):
            if field in params:
                params[field] = origin + (params[field] - source) * factor
        if "controls" in params:
            params["controls"] = [[p[0] * rx, p[1] * ry] for p in params["controls"]]
        indices = {str(i): v.id for i, v in enumerate(mesh.vertices)}
        for field in ("pins", "weights", "offsets"):
            if field in params:
                params[field] = {indices[k]: value for k, value in params[field].items()}
        for pin in params.get("pins", {}).values():
            pin["x"], pin["y"] = x + (pin["x"] - sx) * rx, y + (pin["y"] - sy) * ry
        if "offsets" in params:
            params["offsets"] = {k: [v[0] * rx, v[1] * ry] for k, v in params["offsets"].items()}
        fps = number(data["fps"], "Motion FPS")
        if fps <= 0:
            raise ProjectError("Motion FPS must be positive.")
        time_scale = self.scene.settings.fps / fps
        with self.document.command_group("Reuse deformation clip"):
            stage_id = self.add(
                mesh.id,
                DeformationPreset(str(data["name"]), data["kind"], params),
                columns=params.get("columns", 3),
                rows=params.get("rows", 3),
            )
            tracks = []
            for raw in data["tracks"]:
                record = json_copy(raw)
                owner = record["owner_id"]
                record["id"] = str(uuid4())
                record["owner_id"] = stage_id if owner == "stage" else indices[owner]
                parts = record["property_path"].split(".")
                if len(parts) > 2 and parts[0:2] in (
                    ["parameters", "pins"],
                    ["parameters", "weights"],
                    ["parameters", "offsets"],
                ):
                    parts[2] = indices[parts[2]]
                    record["property_path"] = ".".join(parts)
                path = record["property_path"]
                DeformationPlan(self.scene).base(record["owner_id"], path)
                factor, offset = 1.0, 0.0
                if owner != "stage" and path in ("x", "y"):
                    factor, offset = (rx, x - sx * rx) if path == "x" else (ry, y - sy * ry)
                elif path.startswith("parameters.controls.") or path.startswith(
                    "parameters.offsets."
                ):
                    factor = rx if path.endswith(".0") else ry
                elif path in ("parameters.x", "parameters.y", "parameters.radius"):
                    factor = {
                        "parameters.x": rx,
                        "parameters.y": ry,
                        "parameters.radius": min(rx, ry),
                    }[path]
                elif (
                    path in ("parameters.pivot_x", "parameters.pivot_y")
                    or path.startswith("parameters.pins.")
                    and path.endswith((".x", ".y"))
                ):
                    factor, offset = (
                        (rx, x - sx * rx) if path.endswith(("_x", ".x")) else (ry, y - sy * ry)
                    )
                for key in record["keyframes"]:
                    key["id"] = str(uuid4())
                    key["frame"] *= time_scale
                    key["value"] = key["value"] * factor + (
                        offset if record.get("blend_mode", "override") == "override" else 0
                    )
                    for tangent in ("tangent_in", "tangent_out"):
                        if key.get(tangent):
                            key[tangent] = [key[tangent][0] * time_scale, key[tangent][1] * factor]
                track = Track.from_dict(record)
                CompiledTrack(track, self.document.track_samplers)
                tracks.append(track)
            timeline = Timeline(name=str(data["name"]), tracks=tuple(tracks))
            clip = AnimationClip(
                name=timeline.name,
                timeline_id=timeline.id,
                in_frame=data["in_frame"] * time_scale,
                out_frame=data["out_frame"] * time_scale,
                loop=data["loop"],
            )
            self.commit(
                "Add reusable motion",
                timelines=(*self.scene.timelines, timeline),
                clips=(*self.scene.clips, clip),
            )
        self.document.select_animation_clip(clip.id)
        return stage_id, clip.id
