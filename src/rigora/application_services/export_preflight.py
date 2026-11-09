"""Read-only export capability, resource and sampled-pose checks shared by every host."""

import math
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rigora.application_services.documents import DocumentService
from rigora.application_services.export_metadata import exported_events
from rigora.application_services.rig_export import MAX_PARTICLE_SAMPLES, RIG_FORMATS
from rigora.domain.project import ProjectError
from rigora.infrastructure.game_export import GAME_FORMATS

if TYPE_CHECKING:
    from rigora.application_services.output import OutputSettings


class ExportPreflight:
    """Inspect an isolated document revision without writing output or invoking an engine."""

    def __init__(self, document: DocumentService) -> None:
        """Retain a caller-owned snapshot; GUI callers must fork before worker inspection."""
        self.document = document

    def inspect(
        self,
        settings: "OutputSettings",
        *,
        encoder: Path | None = None,
        deep: bool = True,
        cancel: threading.Event | None = None,
    ) -> dict[str, Any]:
        """Return deduplicated findings and measured budgets; deep checks sample every frame.

        Native camera/lens/particle support is explicit rather than inferred from a
        manifest field. Collision regions remain metadata for game-owned behavior.
        Toolchain execution is separately validated and never claimed by this scan.
        """
        from rigora.application_services.output import (
            FORMATS,
            VIDEO_OPTIONS,
            RenderCancelled,
        )

        findings: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()

        def add(severity: str, code: str, message: str, owner: str = "") -> None:
            """Bound repeated per-frame failures to one actionable finding per owner."""
            key = severity, code, owner
            if key not in seen:
                seen.add(key)
                findings.append(dict(severity=severity, code=code, message=message, owner=owner))

        def check() -> None:
            """Cancel between bounded source reads and evaluated samples."""
            if cancel and cancel.is_set():
                raise RenderCancelled("Export check cancelled.")

        doc, kind = self.document, settings.format
        if doc.project is None:
            raise ProjectError("Create or open a project before checking export.")
        if kind not in FORMATS:
            raise ProjectError("Choose a built-in export format for capability inspection.")
        if kind in VIDEO_OPTIONS:
            if encoder is None or not encoder.is_file():
                add("error", "encoder", "Choose an installed FFmpeg executable for video output.")
            if kind == "mp4" and (settings.width % 2 or settings.height % 2):
                add("error", "dimensions", "H.264 requires even output dimensions.")
        native = kind in RIG_FORMATS
        attachment_owners = {
            c.owner_id for c in doc.scene.constraints if c.kind == "scene_attachment"
        }
        scoped = doc.animation_scope
        objects = tuple(o for o in doc.scene.objects if scoped is None or o.id in scoped)
        if native and kind not in ("godot-2d", "unity-rig"):
            if any("particle_emitter" in o.extra for o in objects):
                add(
                    "error",
                    "native_particles",
                    "This planar 3D adapter does not render particles. "
                    "Use Godot native 2D, Unity editable rigs or baked sprites/video.",
                )
            camera_ids = {c.id for c in doc.scene.cameras}
            camera_drivers = set(camera_ids)
            parents = {group.id: group.parent_id for group in doc.scene.groups}
            for camera in doc.scene.cameras:
                parent = camera.parent_id
                while parent is not None and parent not in camera_drivers:
                    camera_drivers.add(parent)
                    parent = parents.get(parent)
            animated = (
                any(t.owner_id in camera_drivers for t in doc.animation.evaluator.timeline.tracks)
                if doc.animation.evaluator.timeline
                else False
            )
            constrained = any(
                rule.enabled and rule.owner_id in camera_drivers for rule in doc.scene.constraints
            )
            if (
                animated
                or constrained
                or any(c.background_mode != "transparent" for c in doc.scene.cameras)
            ):
                add(
                    "error",
                    "native_camera",
                    "Camera cuts/motion/lens/background playback needs Godot native 2D, Unity "
                    "or baked output; this adapter retains camera metadata only.",
                )
        if native:
            add(
                "info",
                "sampled_rig",
                "Constraints/springs/FFD are sampled; native engine solvers are not recreated.",
            )
            if any("game_region" in o.extra for o in objects):
                add(
                    "info",
                    "regions",
                    "Collision polygons are exported data; game code owns colliders "
                    "and damage policy.",
                )
        if kind in ("godot", "unity", "unreal", "spritesheet"):
            add(
                "info",
                "baked",
                "Artwork/camera/particles are baked into pixels; replaceable clothing "
                "remains in the source project.",
            )
        has_audio = bool(
            doc.animation.evaluator.clip
            and (
                doc.animation.evaluator.clip.extra.get("audio")
                or doc.animation.evaluator.clip.extra.get("audio_tracks")
            )
        )
        if settings.include_audio and has_audio and kind not in (*VIDEO_OPTIONS, *RIG_FORMATS):
            add(
                "warning",
                "audio_omitted",
                "This format does not package audio; export WAV/video or an editable rig.",
            )
        if settings.include_audio and has_audio and (native or kind in VIDEO_OPTIONS):
            step = doc.scene.settings.fps / settings.fps
            if any(
                not math.isclose(b - a, step, abs_tol=1e-6)
                for a, b in zip(settings.frames, settings.frames[1:], strict=False)
            ):
                add(
                    "error",
                    "audio_timing",
                    "Audio requires consecutive samples at the selected FPS; "
                    "disable audio for retimed sparse samples.",
                )
        metrics: dict[str, Any] = dict(
            frames=len(settings.frames),
            evaluated=0,
            triangles=0,
            sampled_vertices=0,
            sampled_particles=0,
            source_bytes=0,
        )
        if kind in ("runtime-json", "spritesheet", *GAME_FORMATS, *RIG_FORMATS):
            check()
            try:
                metrics["event_occurrences"] = len(
                    exported_events(doc, settings.frames, settings.fps)
                )
            except ProjectError as error:
                add("error", "events", str(error))
        if deep:
            assets: set[str] = set()
            try:
                if settings.include_audio and has_audio:
                    from rigora.application_services.audio import AudioService

                    assets.update(t["asset_id"] for t in AudioService(doc).tracks())
                for frame in settings.frames:
                    check()
                    pose = doc.animation.evaluate(frame)
                    if native and attachment_owners:
                        from rigora.application_services.rig_export import trs
                        from rigora.domain.geometry import inverse, multiply

                        for owner in attachment_owners:
                            if owner not in pose.nodes:
                                continue
                            node = pose.nodes[owner]
                            attachment_parent = pose.nodes.get(node.parent_id or "")
                            local = (
                                multiply(inverse(attachment_parent.world_matrix), node.world_matrix)
                                if attachment_parent
                                else node.world_matrix
                            )
                            try:
                                trs(local)
                            except ProjectError:
                                add(
                                    "error",
                                    "attachment_shear",
                                    "An attachment produces affine shear that native TRS animation "
                                    "cannot represent. Disable Follow Scale, use uniform target "
                                    "scale, or export baked sprites/video.",
                                    owner,
                                )
                    metrics["evaluated"] += 1
                    for warning in pose.warnings:
                        add("error", "evaluation", warning)
                    triangles = sum(len(m.triangles) for m in pose.meshes.values())
                    metrics["triangles"] = max(metrics["triangles"], triangles)
                    metrics["sampled_vertices"] += sum(
                        len(m.positions) for m in pose.meshes.values()
                    )
                    metrics["sampled_particles"] += sum(len(p) for p in pose.particles.values())
                    for mesh in pose.meshes.values():
                        for warning in mesh.warnings:
                            add("error", "mesh", warning, mesh.id)
                        if mesh.asset_id:
                            assets.add(mesh.asset_id)
                    assets.update(c.asset_id for c in pose.cameras if c.asset_id)
                if metrics["triangles"] > 20000 and not native:
                    add(
                        "error",
                        "triangles",
                        "Rendered output supports at most 20,000 triangles per frame.",
                    )
                if native and metrics["sampled_vertices"] > 1_000_000:
                    add(
                        "error",
                        "vertices",
                        "Editable rigs support at most one million sampled vertices.",
                    )
                if native and metrics["sampled_particles"] > MAX_PARTICLE_SAMPLES:
                    add("error", "particles", "Editable scenes support 250,000 particle samples.")
                if native and metrics["sampled_vertices"] == 0:
                    add(
                        "error",
                        "artwork",
                        "Editable rigs require mesh artwork in the current scope.",
                    )
                for key in sorted(assets):
                    check()
                    try:
                        metrics["source_bytes"] += len(doc.read_asset(key))
                    except (OSError, ProjectError) as error:
                        add("error", "source", str(error), key)
            except RenderCancelled:
                raise
            except (ProjectError, OSError) as error:
                add("error", "evaluation", str(error))
        return dict(
            format=kind,
            ready=not any(f["severity"] == "error" for f in findings),
            coverage="all requested samples" if deep else "settings and adapter capabilities",
            findings=findings,
            metrics=metrics,
        )
