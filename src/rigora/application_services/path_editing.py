"""Reversible cubic motion paths and original SVG artwork sharing one control-point model."""

import re
from dataclasses import replace
from typing import Any

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.artwork_editing import ArtworkEditingService
from rigora.application_services.meshes import MeshService
from rigora.domain.entities import Constraint, Keyframe, Timeline, Track
from rigora.domain.project import ProjectError
from rigora.engine.bezier_paths import control_points
from rigora.engine.sampling import number


class PathEditingService(MeshService):
    """Author vector curves and animate owner pivots without baking point samples."""

    def motion(
        self,
        owner: str,
        points: Any,
        start: float,
        end: float,
        *,
        orient: bool = False,
        space: str = "world",
    ) -> str:
        """Create/update one owner path and an ordinary progress channel as one Undo command."""
        controls = control_points(points)
        start, end = number(start), number(end)
        if not 0 <= start < end or space not in ("world", "parent") or type(orient) is not bool:
            raise ProjectError(
                "Choose an increasing frame range, World/Parent space and orientation."
            )
        if owner not in self.document.animation.pose.nodes:
            raise ProjectError("Choose a transformable owner in this scene.")
        if any(b.id == owner for rig in self.scene.skeletons for b in rig.bones):
            raise ProjectError("Motion paths animate Objects/cameras; use IK targets for bones.")
        if self.document.animation_scope is not None and owner not in self.document.animation_scope:
            raise ProjectError("Choose an owner in the editable Object view.")
        existing = next(
            (c for c in self.scene.constraints if c.owner_id == owner and c.kind == "motion_path"),
            None,
        )
        rule = (
            replace(
                existing,
                parameters={
                    **existing.parameters,
                    "points": controls,
                    "orient": orient,
                    "space": space,
                },
            )
            if existing
            else Constraint(
                name="Motion path",
                kind="motion_path",
                owner_id=owner,
                parameters={"points": controls, "progress": 0.0, "orient": orient, "space": space},
            )
        )
        editor = AnimationEditingService(self.document)
        timeline = editor.timeline or Timeline(name="Path animation")
        clip = editor.clip or editor.blank_clip(timeline)
        track = next(
            (
                t
                for t in timeline.tracks
                if t.owner_id == rule.id
                and t.property_path == "parameters.progress"
                and not t.extra.get("motion_window")
            ),
            None,
        )
        track = (
            replace(track, keyframes=(Keyframe(frame=start, value=0), Keyframe(frame=end, value=1)))
            if track
            else Track(
                name="Path progress",
                owner_id=rule.id,
                property_path="parameters.progress",
                keyframes=(Keyframe(frame=start, value=0), Keyframe(frame=end, value=1)),
                extra={"motion_path": owner},
            )
        )
        with self.document.command_group("Edit motion path"):
            self.commit(
                "Set curve controls",
                constraints=tuple(c for c in self.scene.constraints if c.id != rule.id) + (rule,),
            )
            editor.publish(
                "Key path progress",
                replace(
                    timeline,
                    tracks=tuple(t for t in timeline.tracks if t.id != track.id) + (track,),
                ),
                replace(clip, out_frame=max(clip.out_frame, end)),
            )
        return rule.id

    def artwork(
        self,
        points: Any,
        *,
        mesh_id: str = "",
        closed: bool = False,
        fill: str = "#bcbcbc",
        stroke: str = "#ffffff",
        stroke_width: float = 2,
        width: float = 512,
        height: float = 512,
    ) -> str:
        """Create/edit original cubic SVG controls fitted to a stable mesh/UV canvas."""
        points = control_points(points)
        if any(re.fullmatch(r"#[a-fA-F0-9]{6}", color) is None for color in (fill, stroke)):
            raise ProjectError("Curve colors require #RRGGBB values.")
        width, height, stroke_width = number(width), number(height), number(stroke_width)
        if not 1 <= width <= 8192 or not 1 <= height <= 8192 or not 0 <= stroke_width <= 1000:
            raise ProjectError("Curve canvas must be 1–8192 pixels; outline width 0–1000.")
        data = {
            "points": points,
            "closed": bool(closed),
            "fill": fill,
            "stroke": stroke,
            "stroke_width": stroke_width,
            "width": width,
            "height": height,
        }
        commands = (
            f"M {points[0][0]:g} {points[0][1]:g} "
            + " ".join(
                "C " + " ".join(f"{v:g}" for p in points[i : i + 3] for v in p)
                for i in range(1, len(points), 3)
            )
            + (" Z" if closed else "")
        )
        source = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:g}" height="{height:g}" '
            f'viewBox="0 0 {width:g} {height:g}"><path d="{commands}" '
            f'fill="{fill if closed else "none"}" stroke="{stroke}" '
            f'stroke-width="{stroke_width:g}" '
            'stroke-linecap="round" stroke-linejoin="round"/></svg>'
        ).encode()
        with self.document.command_group("Edit vector curve"):
            if mesh_id:
                mesh = self.mesh(mesh_id)
                ArtworkEditingService(self.document).replace_bytes(str(mesh.asset_id), source)
            else:
                mesh_id = self.import_image_bytes("Bezier curve.svg", source)
                mesh = self.mesh(mesh_id)
            self.commit(
                "Store editable curve controls",
                meshes=tuple(
                    replace(m, extra={**m.extra, "bezier_art": data}) if m.id == mesh_id else m
                    for m in self.scene.meshes
                ),
            )
        return mesh_id
