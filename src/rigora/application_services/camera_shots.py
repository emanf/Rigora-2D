"""Canonical shot listing, camera following and eased framing transitions on the scene timeline."""

from dataclasses import replace
from typing import Any

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.cameras import CameraService
from rigora.domain.entities import Constraint, Keyframe, Track
from rigora.domain.project import ProjectError
from rigora.engine.cameras import active_camera, camera_size
from rigora.engine.sampling import number


class CameraShotService(CameraService):
    """Keep camera tools on the saved cut/transform tracks used by preview and export."""

    def shots(self) -> tuple[dict[str, Any], ...]:
        """List effective cuts and their next boundary, including the opening camera."""
        editor = AnimationEditingService(self.document)
        timeline, clip = editor.timeline, editor.clip
        camera = active_camera(self.document.animation.evaluate(clip.in_frame if clip else 0))
        frames = {clip.in_frame if clip else 0: camera.id} if camera else {}
        for track in timeline.tracks if timeline else ():
            if track.property_path == "camera.active":
                for key in track.keyframes:
                    if key.value >= 0.5:
                        frames[key.frame] = track.owner_id
        ordered = sorted(frames.items())
        end = clip.out_frame if clip else self.scene.settings.end_frame
        cameras = {c.id: c for c in self.scene.cameras}
        return tuple(
            dict(
                frame=frame,
                end=ordered[i + 1][0] if i + 1 < len(ordered) else end,
                camera=key,
                name=cameras[key].name,
            )
            for i, (frame, key) in enumerate(ordered)
            if key in cameras
        )

    def shot(
        self, camera: str, frame: float, *, duration: float = 0, easing: str = "smooth"
    ) -> None:
        """Key a cut and optional continuous framing blend, preserving source camera animation."""
        frame, duration = number(frame), number(duration)
        if not 0 <= frame <= 1e7 or not 0 <= duration <= 7200 or easing not in ("smooth", "linear"):
            raise ProjectError("Choose a nonnegative cut and transition up to 7200 frames.")
        target = self.camera(camera)
        previous = active_camera(self.document.animation.evaluate(max(0, frame - 1e-5)))
        if duration and (previous is None or previous.id == camera):
            raise ProjectError("Transitions require a different camera active before the cut.")
        with self.document.command_group("Edit camera shot"):
            self.activate(camera, frame=frame)
            editor = AnimationEditingService(self.document)
            timeline, clip = editor.timeline, editor.clip
            assert timeline is not None and clip is not None
            old = {
                c.id
                for c in self.scene.constraints
                if c.kind == "shot_transition"
                and c.extra.get("shot_frame") == frame
                and c.extra.get("clip_id") == clip.id
            }
            constraints = tuple(c for c in self.scene.constraints if c.id not in old)
            tracks = tuple(t for t in timeline.tracks if t.owner_id not in old)
            if duration and previous:
                sw, sh = camera_size(previous, self.scene.settings)
                tw, th = camera_size(target, self.scene.settings)
                rule = Constraint(
                    name="Shot transition",
                    owner_id=camera,
                    target_id=previous.id,
                    kind="shot_transition",
                    order=100,
                    parameters=dict(
                        progress=1.0,
                        source_width=sw,
                        source_height=sh,
                        target_width=tw,
                        target_height=th,
                        easing=easing,
                    ),
                    extra={"shot_frame": frame, "clip_id": clip.id},
                )
                constraints += (rule,)
                tracks += (
                    Track(
                        name="Shot transition",
                        owner_id=rule.id,
                        property_path="parameters.progress",
                        keyframes=(
                            Keyframe(frame=frame, value=0),
                            Keyframe(frame=frame + duration, value=1),
                        ),
                        extra={"camera_transition": True, "active_from_first_key": True},
                    ),
                )
            self.commit("Set shot transition", constraints=constraints)
            editor.publish(
                "Key shot transition",
                replace(timeline, tracks=tracks),
                replace(clip, out_frame=max(clip.out_frame, frame + duration)),
            )

    def follow(
        self, camera: str, target: str = "", *, offset_x: float = 0, offset_y: float = 0
    ) -> None:
        """Set/remove pivot-centered follow; offsets remain ordinary animatable scalars."""
        self.camera(camera)
        if self.document.animation_context:
            raise ProjectError("Author camera follow in the main Scene.")
        old = next(
            (
                c
                for c in self.scene.constraints
                if c.kind == "camera_follow" and c.owner_id == camera
            ),
            None,
        )
        constraints = tuple(
            c
            for c in self.scene.constraints
            if not (c.kind == "camera_follow" and c.owner_id == camera)
        )
        if target:
            if target == camera or target not in self.document.animation.pose.nodes:
                raise ProjectError("Choose a different Object/bone to follow.")
            parameters: dict[str, Any] = {
                "offset_x": number(offset_x),
                "offset_y": number(offset_y),
            }
            evaluator = self.document.animation.evaluator
            placement = evaluator.skinned_rigs.get(target)
            if placement:
                parameters.update(
                    placement_owner=placement, placement_bind=evaluator.spring_bindings[placement]
                )
            constraints += (
                replace(
                    old,
                    target_id=target,
                    parameters=parameters,
                )
                if old
                else Constraint(
                    name="Camera follow",
                    kind="camera_follow",
                    owner_id=camera,
                    target_id=target,
                    order=50,
                    parameters=parameters,
                ),
            )
        changes: dict[str, Any] = {"constraints": constraints}
        if old and not target:
            changes["timelines"] = tuple(
                replace(t, tracks=tuple(c for c in t.tracks if c.owner_id != old.id))
                for t in self.scene.timelines
            )
        self.commit("Edit camera follow", **changes)

    def remove_shot(self, frame: float) -> None:
        """Remove a cut/transition, retaining cameras and their motion/effect keys."""
        editor = AnimationEditingService(self.document)
        if editor.timeline is None or editor.clip is None:
            return
        old = {
            c.id
            for c in self.scene.constraints
            if c.kind == "shot_transition"
            and c.extra.get("shot_frame") == frame
            and c.extra.get("clip_id") == editor.clip.id
        }
        refs: dict[tuple[str, str], dict[str, Any]] = {
            (t.id, k.id): {}
            for t in editor.timeline.tracks
            if t.property_path == "camera.active"
            for k in t.keyframes
            if k.frame == frame
        }
        with self.document.command_group("Remove camera shot"):
            editor.edit_keys(refs, delete=True)
            self.commit(
                "Remove shot transition",
                constraints=tuple(c for c in self.scene.constraints if c.id not in old),
                timelines=tuple(
                    replace(t, tracks=tuple(c for c in t.tracks if c.owner_id not in old))
                    for t in self.scene.timelines
                ),
            )
