"""Undoable camera creation, background authoring and keyed scene cuts for every client."""

import math
from dataclasses import replace
from typing import Any
from uuid import uuid4

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.meshes import MeshService
from rigora.domain.entities import Camera, Keyframe, Timeline, Track, Transform
from rigora.domain.geometry import decompose
from rigora.domain.project import ProjectError, Scene
from rigora.engine.camera_actions import EFFECT_PRESETS, MOTION_PRESETS, motion_values
from rigora.engine.cameras import active_camera, camera_size


def with_main_camera(scene: Scene) -> Scene:
    """Initialize a new scene without inserting cameras into imported artwork fragments."""
    if scene.cameras:
        return scene
    camera = Camera(
        name="Main Camera",
        active=True,
        extra={"locked": True},
        width=float(scene.settings.width),
        height=float(scene.settings.height),
        transform=Transform(pivot_x=scene.settings.width / 2, pivot_y=scene.settings.height / 2),
    )
    return replace(scene, cameras=(camera,))


class CameraService(MeshService):
    """Author cameras through the same scene history and animation services as artwork."""

    def camera(self, key: str) -> Camera:
        """Resolve a camera only in the active scene, rejecting stale identities."""
        camera = next((c for c in self.scene.cameras if c.id == key), None)
        if camera is None:
            raise ProjectError("Choose a camera in the active scene.")
        return camera

    def add(self, name: str = "") -> str:
        """Add an identity camera, preserving the current active view and output."""
        created = with_main_camera(replace(self.scene, cameras=())).cameras[0]
        created = replace(
            created,
            name=name.strip()
            or (
                "Main Camera"
                if not self.scene.cameras
                else f"Camera {len(self.scene.cameras) + 1:02}"
            ),
            active=not self.scene.cameras,
            extra={**created.extra, "locked": not bool(self.scene.cameras)},
        )
        self.commit("Add camera", cameras=(*self.scene.cameras, created))
        return created.id

    def update(self, key: str, **fields: Any) -> None:
        """Validate complete camera settings before committing one reversible change."""
        allowed = {
            "name",
            "transform",
            "width",
            "height",
            "match_scene",
            "enabled",
            "asset_id",
            "background_mode",
            "background_color",
            "background_fit",
            "background_opacity",
        }
        if set(fields) - allowed:
            raise ProjectError("Unsupported camera setting.")
        camera = replace(self.camera(key), **fields)
        animated = any(
            t.owner_id == key and t.property_path.startswith("transform.")
            for timeline in self.scene.timelines
            for t in timeline.tracks
        )
        if (
            not camera.extra.get("pivot_edited")
            and not animated
            and {"width", "height", "match_scene"}.intersection(fields)
        ):
            width, height = camera_size(camera, self.scene.settings)
            values = decompose(camera.transform.matrix(), width / 2, height / 2)
            camera = replace(
                camera,
                transform=Transform.from_dict(
                    dict(
                        zip(
                            ("x", "y", "rotation", "scale_x", "scale_y", "pivot_x", "pivot_y"),
                            values,
                            strict=True,
                        )
                    )
                ),
            )
        self.commit(
            "Edit camera", cameras=tuple(camera if c.id == key else c for c in self.scene.cameras)
        )

    def duplicate(self, key: str) -> str:
        """Copy frame and background with a fresh identity and no inherited animation keys."""
        from uuid import uuid4

        copy = replace(
            self.camera(key), id=str(uuid4()), name=self.camera(key).name + " copy", active=False
        )
        self.commit("Duplicate camera", cameras=(*self.scene.cameras, copy))
        return copy.id

    def activate(self, key: str, *, frame: float | None = None) -> None:
        """Set the default camera, or record an exclusive stepped cut at the requested frame."""
        camera = self.camera(key)
        if not camera.enabled:
            raise ProjectError("Enable the camera before making it active.")
        if self.document.animation_context:
            raise ProjectError("Switch cameras in the main scene, outside Object Editor.")
        if frame is None:
            self.commit(
                "Set default camera",
                cameras=tuple(replace(c, active=c.id == key) for c in self.scene.cameras),
            )
            return
        editor = AnimationEditingService(self.document)
        editor.auto_key_values(
            {(c.id, "camera.active"): float(c.id == key) for c in self.scene.cameras}, frame
        )

    def current(self) -> Camera | None:
        """Return the enabled camera selected by the evaluated playhead cuts."""
        return active_camera(self.document.animation.pose)

    def action(
        self,
        key: str,
        preset: str,
        kind: str,
        start: float,
        end: float,
        *,
        speed: float = 1,
        amount: float = 1,
        identity: str = "",
    ) -> str:
        """Bake deterministic camera moves or key lens intensity as one portable scene action."""
        self.camera(key)
        catalog = MOTION_PRESETS if kind == "camera_motion" else EFFECT_PRESETS
        if (
            self.document.animation_context
            or kind not in ("camera_motion", "camera_effect")
            or preset not in catalog
            or not all(math.isfinite(v) for v in (start, end, speed, amount))
            or not 0 <= start < end
            or end - start > 7200
            or not 0.01 <= speed <= 100
            or not 0 <= amount <= 2
        ):
            raise ProjectError(
                "Choose a camera preset, duration up to 7,200 frames, and valid speed/amount."
            )
        editor = AnimationEditingService(self.document)
        timeline = editor.timeline or Timeline(name="Scene actions")
        clip = editor.clip or editor.blank_clip(timeline)
        if any(
            t.locked and t.extra.get("camera_action", {}).get("kind") == kind
            for t in timeline.tracks
        ):
            raise ProjectError("Unlock the camera action row before adding or editing actions.")
        editing = bool(identity)
        identity = identity or str(uuid4())
        old = [t for t in timeline.tracks if t.extra.get("camera_action", {}).get("id") == identity]
        if editing and not old:
            raise ProjectError("The camera action no longer exists. Choose an existing action.")
        for track in old:
            editor.editable(track)
        metadata = {
            "id": identity,
            "character": key,
            "name": catalog[preset],
            "preset": preset,
            "start": start,
            "end": end,
            "speed": speed,
            "amount": amount,
            "kind": kind,
        }
        channels: dict[str, list[Keyframe]] = {}
        if kind == "camera_motion":
            samples = max(2, math.ceil(end - start))
            for i in range(samples + 1):
                t = i / samples
                for path, value in motion_values(preset, t, speed, amount).items():
                    channels.setdefault("transform." + path, []).append(
                        Keyframe(frame=start + t * (end - start), value=value)
                    )
        else:
            fade = min(6, (end - start) / 3)
            channels["camera.effect." + preset] = [
                Keyframe(frame=f, value=value)
                for f, value in (
                    (start, 0),
                    (start + fade, min(1, amount)),
                    (end - fade, min(1, amount)),
                    (end, 0),
                )
            ]
        tracks = tuple(
            Track(
                name=catalog[preset],
                owner_id=key,
                property_path=path,
                blend_mode="additive" if kind == "camera_motion" else "override",
                keyframes=tuple(keys),
                extra={"camera_action": metadata, "active_from_first_key": True},
            )
            for path, keys in channels.items()
        )
        editor.publish(
            "Edit camera action",
            replace(timeline, tracks=(*(t for t in timeline.tracks if t not in old), *tracks)),
            replace(clip, out_frame=max(clip.out_frame, end)),
        )
        return identity

    def remove_action(self, identity: str) -> None:
        """Delete only one camera preset instance, retaining camera transforms and other effects."""
        editor = AnimationEditingService(self.document)
        if editor.timeline and editor.clip:
            removed = [
                t
                for t in editor.timeline.tracks
                if t.extra.get("camera_action", {}).get("id") == identity
            ]
            for track in removed:
                editor.editable(track)
            editor.publish(
                "Remove camera action",
                replace(
                    editor.timeline,
                    tracks=tuple(t for t in editor.timeline.tracks if t not in removed),
                ),
                editor.clip,
            )
