"""Qt-free staged image, animation, atlas, video and runtime-neutral export pipeline."""

import base64
import io
import json
import math
import re
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from rigora.application_services.audio import AudioPosition, AudioService
from rigora.application_services.documents import DocumentService
from rigora.application_services.rendering import svg_frame
from rigora.application_services.rig_export import RIG_FORMATS, rig_package
from rigora.domain.geometry import transform_point
from rigora.domain.project import ProjectError
from rigora.infrastructure.game_export import GAME_FORMATS, sprite_package
from rigora.infrastructure.media_import import png_bytes
from rigora.infrastructure.project_storage import _atomic_bytes

FORMATS = {
    "svg": ("SVG frames", ".svg"),
    "png": ("Transparent PNG frames", ".png"),
    "gif": ("Animated GIF", ".gif"),
    "webp": ("Animated WebP", ".webp"),
    "apng": ("Animated PNG · lossless RGBA", ".apng"),
    "webm": ("WebM · VP9 + alpha", ".webm"),
    "webm-vp8": ("WebM · VP8 + alpha", ".webm"),
    "mov": ("MOV · ProRes 4444 + alpha", ".mov"),
    "ffv1": ("MKV · FFV1 lossless RGBA", ".mkv"),
    "mp4": ("MP4 · H.264 video", ".mp4"),
    "spritesheet": ("Sprite atlas + JSON", ".png"),
    "runtime-json": ("Rigora runtime animation JSON", ".json"),
    "godot": ("Godot 4 · sprite scene package", ".zip"),
    "unity": ("Unity · sprite animation package", ".zip"),
    "unreal": ("Unreal Engine 5 · Paper2D package", ".zip"),
    "godot-rig": ("Godot · editable rig + clothing", ".zip"),
    "godot-2d": ("Godot 4 · native 2D rig + scene playback", ".zip"),
    "unity-rig": ("Unity · editable rig + clothing", ".zip"),
    "unreal-rig": ("Unreal · editable glTF rig", ".zip"),
}
# Fixed profiles retain the host-owned executable boundary shared by GUI, CLI and API.
VIDEO_OPTIONS = {
    "mp4": ("-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart"),
    "webm": (
        "-c:v",
        "libvpx-vp9",
        "-pix_fmt",
        "yuva420p",
        "-b:v",
        "0",
        "-crf",
        "18",
        "-auto-alt-ref",
        "0",
        "-deadline",
        "good",
        "-cpu-used",
        "2",
        "-row-mt",
        "1",
    ),
    "webm-vp8": (
        "-c:v",
        "libvpx",
        "-pix_fmt",
        "yuva420p",
        "-b:v",
        "4M",
        "-crf",
        "10",
        "-auto-alt-ref",
        "0",
        "-deadline",
        "good",
        "-cpu-used",
        "2",
    ),
    "mov": (
        "-c:v",
        "prores_ks",
        "-profile:v",
        "4",
        "-pix_fmt",
        "yuva444p10le",
        "-alpha_bits",
        "16",
    ),
    "ffv1": ("-c:v", "ffv1", "-level", "3", "-pix_fmt", "bgra", "-g", "1", "-slicecrc", "1"),
}
FORMAT_NOTES = {
    **dict.fromkeys(
        RIG_FORMATS,
        "Editable planar bones, skin weights, separate mesh parts and wardrobe metadata. "
        "Uses glTF 2.0 plus engine controls. Constraints and FFD are sampled into animation. "
        "Original artwork is retained; portable textures derive from original vectors. "
        "The larger Width/Height value limits each texture's longest edge; "
        "it does not crop the rig.",
    ),
    **dict.fromkeys(
        GAME_FORMATS,
        "Baked transparent sprite animation with engine resources/importer. "
        "Bones, replaceable clothes and audio remain in the original Rigora project. "
        "Export each action separately; unpack the ZIP and follow its README.",
    ),
    "godot-2d": (
        "Native Skeleton2D/Bone2D and separate Polygon2D artwork with sampled deformation, "
        "clothing/skin switches, events, camera playback and vector particles. "
        "Original vectors and source project remain included; Width/Height limit textures. "
        "Disable Use scene camera in the engine when placing under a game's Camera2D."
    ),
    "unity-rig": (
        "Editable planar glTF bones, sampled deformation, clothing, events and scene playback. "
        "The bundled shader targets Unity's built-in renderer; URP/HDRP require adaptation. "
        "Constraints and springs are sampled rather than recreated as native physics."
    ),
    "godot-rig": (
        "Editable planar glTF bones, sampled deformation, clothing and events. "
        "Scene-camera, lens and particle playback are unsupported on this 3D route. "
        "Choose native Godot 2D for sampled 2D scene playback."
    ),
    "unreal-rig": (
        "Editable planar glTF bones, sampled deformation, clothing and events. "
        "Scene-camera, lens and particle playback are unsupported on this route. "
        "The Unreal plugin's native compilation, runtime and audio have not yet been validated. "
        "Use a baked sprite package when editable rig integration is unnecessary."
    ),
    "webm": (
        "VP9 with smooth alpha, high quality and 4:2:0 color. Requires FFmpeg with libvpx-vp9. "
        "Use FFV1 or PNG for exact RGBA pixels."
    ),
    "webm-vp8": (
        "VP8 with smooth alpha and 4:2:0 color. Requires FFmpeg with libvpx. "
        "Use FFV1 or PNG for exact RGBA pixels."
    ),
    "mov": (
        "ProRes 4444 with alpha for editing/compositing. High-quality 4:4:4 color; "
        "compression is not mathematically lossless. Requires FFmpeg with prores_ks."
    ),
    "ffv1": (
        "Lossless BGRA in Matroska: preserves every rendered 8-bit RGBA pixel. "
        "Larger files; use an editor/player with FFV1 alpha support. Requires FFmpeg."
    ),
    "apng": "Lossless animated PNG with full RGBA transparency. No FFmpeg required.",
    "png": "Lossless full RGBA frames. Multiple frames produce a numbered PNG sequence.",
    "webp": "Lossless animated WebP with smooth alpha. No FFmpeg required.",
    "gif": (
        "Limited palette and binary alpha; choose PNG, APNG or WebP for smooth transparent edges."
    ),
    "mp4": (
        "H.264 has no alpha. Transparency is composited over the chosen solid background. "
        "Requires FFmpeg."
    ),
}
MAX_JOB_BYTES = 128 * 1024 * 1024


class RenderCancelled(ProjectError):
    """Signal safe cancellation before publishing staged outputs."""


@dataclass(frozen=True)
class OutputSettings:
    """Owned immutable output settings, bounded before any expensive work or file creation."""

    format: str = "png"
    frames: tuple[float, ...] = (0,)
    width: int = 1280
    height: int = 720
    fps: float = 24
    sequence: bool = False
    bones: bool = False
    background: str | None = None
    loop: bool = True
    columns: int = 8
    include_audio: bool = True

    def __post_init__(self) -> None:
        """Reject invalid dimensions, frame ranges, frame rates and unsafe output colors."""
        if not isinstance(self.frames, tuple) or not 1 <= len(self.frames) <= 600:
            raise ProjectError("Render jobs require 1–600 explicit sample frames.")
        if any(type(f) not in (int, float) or not math.isfinite(f) or f < 0 for f in self.frames):
            raise ProjectError("Sample frames must be finite nonnegative numbers.")
        if (
            type(self.fps) not in (int, float)
            or not math.isfinite(self.fps)
            or not 1 <= self.fps <= 240
        ):
            raise ProjectError("Export FPS must be from 1 to 240.")
        if any(type(v) is not int or not 1 <= v <= 4096 for v in (self.width, self.height)):
            raise ProjectError("Output width/height must be integers from 1 to 4096.")
        if any(
            type(v) is not bool for v in (self.sequence, self.bones, self.loop, self.include_audio)
        ):
            raise ProjectError("Output toggles must be booleans.")
        if self.background is not None and not re.fullmatch(r"#[0-9a-fA-F]{6}", self.background):
            raise ProjectError("Background must be a #RRGGBB color or null for transparency.")
        if type(self.columns) is not int or not 1 <= self.columns <= 64:
            raise ProjectError("Atlas columns must be from 1 to 64.")
        if (
            self.format in ("webp", "apng", "spritesheet", *GAME_FORMATS)
            and self.width * self.height * len(self.frames) > 64 * 1024 * 1024
        ):
            raise ProjectError("Animated images/atlases exceed the 64-megapixel memory budget.")
        if self.format in ("spritesheet", *GAME_FORMATS):
            columns = min(self.columns, len(self.frames))
            rows = math.ceil(len(self.frames) / columns)
            if columns * self.width > 8192 or rows * self.height > 8192:
                raise ProjectError("Atlas dimensions must fit within 8192 pixels per side.")
        if self.format == "gif" and self.fps > 100:
            raise ProjectError("GIF supports at most 100 FPS; choose WebP or a PNG sequence.")


def raster_frame(document: DocumentService, frame: float, settings: OutputSettings) -> Any:
    """Rasterize original SVG and evaluated mesh geometry at final resolution without Qt."""
    try:
        import resvg_py
        from PIL import Image
    except ImportError:
        raise ProjectError(
            "Install the render extra for PNG, GIF, WebP, atlas and video output."
        ) from None
    svg = svg_frame(
        document, frame, width=settings.width, height=settings.height, bones=settings.bones
    )
    try:
        pixels = resvg_py.svg_to_bytes(
            svg_string=svg.decode("utf-8"),
            skip_system_fonts=True,
            background=settings.background,
            width=settings.width,
            height=settings.height,
        )
        image = Image.open(io.BytesIO(pixels))
        image.load()
        return image.convert("RGBA")
    except (OSError, ValueError, RuntimeError) as error:
        raise ProjectError("The headless renderer could not rasterize this scene.") from error


Exporter = Callable[
    [DocumentService, OutputSettings, Path, threading.Event, Callable[[int, int], None]],
    dict[str, Any],
]


def gif_frame(image: Any, index: int, settings: OutputSettings) -> bytes:
    """Encode one independent GIF frame with its own palette and bounded image memory.

    Pillow's public GIF block helpers avoid its multi-frame writer's retained frame
    list. Background/transparency index 255 and disposal 2 clear the entire previous
    frame, including when successive frames use different local color tables.
    """
    from PIL import GifImagePlugin

    palette = image.convert("RGB").quantize(colors=255)
    colors = list(palette.getpalette() or ())
    palette.putpalette((colors + [0] * 768)[:765] + [0, 0, 0])
    palette.paste(255, mask=image.getchannel("A").point(lambda a: 255 if a < 128 else 0))
    options: dict[str, Any] = {"background": 255, "transparency": 255, "optimize": False}
    if settings.loop:
        options["loop"] = 0
    chunks = GifImagePlugin.getheader(palette, info=options)[0] if index == 0 else []
    duration = max(
        10,
        10 * (round((index + 1) * 100 / settings.fps) - round(index * 100 / settings.fps)),
    )
    chunks.extend(
        GifImagePlugin.getdata(
            palette, duration=duration, disposal=2, transparency=255, include_color_table=True
        )
    )
    return b"".join(chunks)


class OutputService:
    """Stage complete output jobs and publish only after evaluation and encoding succeed.

    The host supplies the same authorized-path policy used by the Python API. Custom
    exporters are explicitly injected by trusted Python hosts; remote tools cannot load code.
    """

    def __init__(
        self,
        authorize: Callable[[str], Path],
        *,
        encoder: Path | None = None,
        exporters: Mapping[str, Exporter] | None = None,
    ) -> None:
        """Retain a per-job output policy, optional host-owned encoder and explicit extensions."""
        self.authorize, self.encoder = authorize, encoder
        self.exporters = dict(exporters or {})

    def export(
        self,
        document: DocumentService,
        path: str,
        settings: OutputSettings,
        *,
        cancel: threading.Event | None = None,
        progress: Callable[[int, int], None] | None = None,
        phase: Callable[[str], None] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Preflight all destinations, render/encode privately and report safe cancellation.

        Cancellation takes effect between frames or during video encoding. Publication is
        an uninterruptible short phase; individual files are atomic, not a filesystem-wide
        transaction. A publication I/O failure may leave earlier completed outputs.
        """
        if document.project is None:
            raise ProjectError("Create or open a project before exporting.")
        kind = settings.format
        if kind not in FORMATS and kind not in self.exporters:
            raise ProjectError("Choose a supported output format from output_formats.")
        suffix = FORMATS[kind][1] if kind in FORMATS else Path(path).suffix
        if Path(path).suffix.lower() != suffix or not suffix:
            raise ProjectError("Output extension must match the selected exporter.")
        paths = [path]
        if kind in ("png", "svg") and (settings.sequence or len(settings.frames) > 1):
            paths = [
                str(Path(path).with_name(f"{Path(path).stem}-{i:04d}{suffix}"))
                for i in range(len(settings.frames))
            ]
        elif kind == "spritesheet":
            paths.append(str(Path(path).with_suffix(".json")))
        destinations = [self.authorize(value) for value in paths]
        if kind not in ("svg", "runtime-json") and kind not in self.exporters:
            import importlib.util

            if any(importlib.util.find_spec(name) is None for name in ("PIL", "resvg_py")):
                raise ProjectError("Install the render extra for image, atlas and video output.")
        if kind in VIDEO_OPTIONS:
            if self.encoder is None or not self.encoder.is_file():
                raise ProjectError(
                    "Video export requires a local FFmpeg executable configured by the host."
                )
            if kind == "mp4" and (settings.width % 2 or settings.height % 2):
                raise ProjectError("H.264 video requires even output dimensions.")
        if kind in FORMATS:
            from rigora.application_services.export_preflight import ExportPreflight

            preflight = ExportPreflight(document).inspect(
                settings, encoder=self.encoder, deep=False
            )
            errors = [f["message"] for f in preflight["findings"] if f["severity"] == "error"]
            if errors:
                raise ProjectError("Export preflight: " + " ".join(errors))
        cancelled = cancel or threading.Event()

        def check() -> None:
            """Refuse further work before publication once cancellation is requested."""
            if cancelled.is_set():
                raise RenderCancelled("Render cancelled; staged output was discarded.")

        def report(done: int) -> None:
            """Deliver bounded per-frame progress without modifying the source document."""
            if progress:
                progress(done, len(settings.frames))

        def stage(value: str) -> None:
            """Report job phases; queued publication uses an atomic cancellation gate."""
            check()
            if phase:
                phase(value)

        stage("rendering")
        if dry_run:
            document.animation.evaluate(settings.frames[0])
            return {
                "status": "planned",
                "paths": paths,
                "frame_count": len(settings.frames),
                "format": kind,
                "bytes": 0,
                "warnings": [],
            }
        destinations[0].parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".rigora-render-", dir=destinations[0].parent
        ) as temporary:
            root = Path(temporary)
            staged = [root / f"output-{i}{p.suffix}" for i, p in enumerate(destinations)]
            warnings: list[str] = []
            images = []
            samples = []
            byte_count = 0
            for index, frame in enumerate(settings.frames):
                check()
                if kind in self.exporters or kind in RIG_FORMATS:
                    break
                if kind == "runtime-json":
                    pose = document.animation.evaluate(frame)
                    if pose.warnings:
                        raise ProjectError(
                            "Cannot export incomplete evaluation: " + "; ".join(pose.warnings)
                        )
                    sample = pose.to_dict()
                    from rigora.engine.game_regions import game_regions

                    sample["regions"] = game_regions(document.scene, pose)
                    from rigora.engine.cameras import active_camera

                    camera = active_camera(pose)
                    sample["active_camera"] = camera.id if camera else None
                    sample["cameras"] = [c.to_dict() for c in pose.cameras]
                    for mesh in sample["meshes"]:
                        owner = pose.nodes.get(mesh["object_id"] or "")
                        for vertex in mesh["vertices"]:
                            if owner:
                                vertex["x"], vertex["y"] = transform_point(
                                    owner.world_matrix, vertex["x"], vertex["y"]
                                )
                    byte_count += len(json.dumps(sample, allow_nan=False))
                    if byte_count > 64 * 1024 * 1024:
                        raise ProjectError("Runtime samples exceed the 64 MiB geometry budget.")
                    samples.append(sample)
                elif kind == "svg":
                    blob = svg_frame(
                        document,
                        frame,
                        width=settings.width,
                        height=settings.height,
                        bones=settings.bones,
                    )
                    if settings.background:
                        raise ProjectError(
                            "SVG frame output keeps transparency; use PNG for a background color."
                        )
                    staged[index if len(staged) > 1 else 0].write_bytes(blob)
                    byte_count += len(blob)
                else:
                    image = raster_frame(document, frame, settings)
                    if kind == "mp4":
                        from PIL import Image

                        backdrop = Image.new("RGBA", image.size, settings.background or "#000000")
                        backdrop.alpha_composite(image)
                        image = backdrop.convert("RGB")
                    if kind == "gif":
                        blob = gif_frame(image, index, settings)
                        with staged[0].open("ab") as gif_output:
                            gif_output.write(blob)
                        byte_count += len(blob)
                    elif kind == "png" or kind in VIDEO_OPTIONS:
                        output = (
                            staged[index if len(staged) > 1 else 0]
                            if kind == "png"
                            else root / f"frame-{index:04d}.png"
                        )
                        blob = png_bytes(image)
                        output.write_bytes(blob)
                        byte_count += len(blob)
                    else:
                        images.append(image)
                if byte_count > MAX_JOB_BYTES:
                    raise ProjectError("Render job exceeds the 128 MiB staging budget.")
                report(index + 1)
            stage("encoding")
            if kind in RIG_FORMATS:
                package, notes = rig_package(
                    document,
                    kind,
                    settings.frames,
                    fps=settings.fps,
                    loop=settings.loop,
                    texture_limit=max(settings.width, settings.height),
                    check=check,
                    report=report,
                    include_audio=settings.include_audio,
                )
                staged[0].write_bytes(package)
                warnings.extend(notes)
            elif kind in self.exporters:
                result = self.exporters[kind](
                    document, settings, staged[0], cancelled, progress or (lambda a, b: None)
                )
                warnings.extend(result.get("warnings", []))
            elif kind == "runtime-json":
                assets = []
                source_bytes = 0
                for asset in document.project.assets:
                    if asset.kind not in ("raster", "vector"):
                        continue
                    data = document.read_asset(asset.id)
                    source_bytes += len(data)
                    if source_bytes > 32 * 1024 * 1024:
                        raise ProjectError("Runtime interchange source assets exceed 32 MiB.")
                    assets.append(
                        {
                            "id": asset.id,
                            "name": asset.name,
                            "media_type": asset.media_type,
                            "sha256": asset.sha256,
                            "base64": base64.b64encode(data).decode(),
                        }
                    )
                payload = {
                    "format": "rigora.runtime-animation",
                    "version": 1,
                    "fps": settings.fps,
                    "coordinates": "pixels, x right, y down; mesh positions in world space",
                    "canvas": document.scene.settings.to_dict(),
                    "assets": assets,
                    "samples": samples,
                    "events": self.event_metadata(document, settings),
                }
                staged[0].write_text(json.dumps(payload, allow_nan=False), encoding="utf-8")
            elif kind in GAME_FORMATS:
                staged[0].write_bytes(
                    sprite_package(
                        kind,
                        destinations[0].stem,
                        images,
                        fps=settings.fps,
                        loop=settings.loop,
                        columns=settings.columns,
                        source_frames=settings.frames,
                        events=self.event_metadata(document, settings),
                        regions=self.region_metadata(document, settings),
                    )
                )
                warnings.append(
                    "Game animation is baked to sprites; runtime bones, clothing swaps "
                    "and audio are not included."
                )
            elif kind == "gif":
                with staged[0].open("ab") as gif_output:
                    gif_output.write(b";")
                warnings.append(
                    "GIF uses 255 colors, binary transparency and 10 ms timing precision."
                )
            elif kind in ("webp", "apng"):
                stream = io.BytesIO()
                durations = [
                    max(
                        1,
                        round((i + 1) * 1000 / settings.fps) - round(i * 1000 / settings.fps),
                    )
                    for i in range(len(images))
                ]
                options: dict[str, Any] = {"save_all": True, "duration": durations}
                if settings.loop:
                    options["loop"] = 0
                elif kind in ("webp", "apng"):
                    options["loop"] = 1
                if kind == "webp":
                    from PIL import features

                    if not features.check("webp"):
                        raise ProjectError("This Pillow build does not support WebP encoding.")
                    # Full keyframes preserve a transparent canvas through libwebp optimization.
                    options.update(lossless=True, exact=True, kmin=0, kmax=1)
                else:
                    # Replacement frames preserve smooth alpha without accumulating trails.
                    options.update(disposal=0, blend=0)
                images[0].save(
                    stream,
                    format="PNG" if kind == "apng" else kind.upper(),
                    append_images=images[1:],
                    **options,
                )
                staged[0].write_bytes(stream.getvalue())
            elif kind == "spritesheet":
                from PIL import Image

                columns = min(settings.columns, len(images))
                rows = math.ceil(len(images) / columns)
                atlas = Image.new("RGBA", (columns * settings.width, rows * settings.height))
                frames = []
                for index, image in enumerate(images):
                    x, y = index % columns * settings.width, index // columns * settings.height
                    atlas.paste(image, (x, y))
                    frames.append(
                        {
                            "index": index,
                            "source_frame": settings.frames[index],
                            "rect": [x, y, settings.width, settings.height],
                            "duration_ms": 1000 / settings.fps,
                            "pivot": [0, 0],
                        }
                    )
                staged[0].write_bytes(png_bytes(atlas))
                staged[1].write_text(
                    json.dumps(
                        {
                            "format": "rigora.sprite-atlas",
                            "version": 1,
                            "image": destinations[0].name,
                            "size": list(atlas.size),
                            "fps": settings.fps,
                            "loop": settings.loop,
                            "frames": frames,
                        }
                    ),
                    encoding="utf-8",
                )
            elif kind in VIDEO_OPTIONS:
                audio_service = AudioService(document)
                multitrack = bool(audio_service.clip and "audio_tracks" in audio_service.clip.extra)
                audio = (
                    AudioService(document).position(settings.frames[0])
                    if settings.include_audio
                    else None
                )
                if audio and audio.seconds < 0 and not multitrack:
                    # Transport silences a voice before its start; the encoder applies
                    # that delay itself and needs the source's authored playback gain.
                    audio = replace(audio, gain=audio_service.tracks()[0].get("gain", 1))
                if settings.include_audio and multitrack and audio_service.tracks():
                    audio_service.mix(
                        root / "voice.wav",
                        start=settings.frames[0],
                        seconds=len(settings.frames) / settings.fps,
                        cancelled=check,
                    )
                    audio = AudioPosition("mix", 0, len(settings.frames) / settings.fps, 1, False)
                if audio and (
                    audio.seconds >= audio.duration
                    or audio.seconds <= -len(settings.frames) / settings.fps
                ):
                    audio = None
                if audio and not audio.muted:
                    scene_fps = document.scene.settings.fps
                    if any(
                        not math.isclose(
                            frame, settings.frames[0] + i * scene_fps / settings.fps, abs_tol=1e-6
                        )
                        for i, frame in enumerate(settings.frames)
                    ):
                        raise ProjectError(
                            "Video audio requires consecutive samples at output FPS. "
                            "Disable audio for arbitrary frame sampling."
                        )
                    if audio.asset_id != "mix":
                        (root / "voice.wav").write_bytes(document.read_asset(audio.asset_id))
                else:
                    audio = None
                self._video(root, staged[0], settings, cancelled, audio=audio)
                if kind == "mp4":
                    warnings.append(
                        "MP4 has no alpha channel. Transparency is composited "
                        "over the chosen background."
                    )
            check()
            total = sum(p.stat().st_size for p in staged)
            if total > MAX_JOB_BYTES:
                raise ProjectError("Encoded output exceeds the 128 MiB job budget.")
            stage("publishing")
            for source, destination, requested in zip(staged, destinations, paths, strict=True):
                self.authorize(requested)
                _atomic_bytes(destination, source.read_bytes())
        return {
            "status": "completed",
            "paths": paths,
            "format": kind,
            "frame_count": len(settings.frames),
            "bytes": total,
            "warnings": warnings,
        }

    @staticmethod
    def region_metadata(
        document: DocumentService, settings: OutputSettings
    ) -> list[dict[str, Any]]:
        """Export region geometry/activation beside baked frames in source coordinates."""
        from rigora.engine.game_regions import game_regions

        if not any(o.extra.get("game_region") for o in document.scene.objects):
            return []
        return [
            {
                "source_frame": frame,
                "seconds": i / settings.fps,
                "regions": game_regions(document.scene, document.animation.evaluate(frame)),
            }
            for i, frame in enumerate(settings.frames)
        ]

    @staticmethod
    def event_metadata(document: DocumentService, settings: OutputSettings) -> list[dict[str, Any]]:
        """Export typed occurrences within the sampled source range, in output-relative seconds."""
        from rigora.application_services.export_metadata import exported_events

        return exported_events(document, settings.frames, settings.fps)

    def _video(
        self,
        root: Path,
        output: Path,
        settings: OutputSettings,
        cancel: threading.Event,
        *,
        audio: AudioPosition | None = None,
    ) -> None:
        """Run only a host-configured FFmpeg binary with fixed arguments and bounded lifetime."""
        assert self.encoder is not None
        args = [
            str(self.encoder),
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-framerate",
            str(settings.fps),
            "-i",
            str(root / "frame-%04d.png"),
        ]
        if audio:
            duration = len(settings.frames) / settings.fps
            args.extend(
                (
                    "-ss",
                    str(max(0, audio.seconds)),
                    "-i",
                    str(root / "voice.wav"),
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a:0",
                    "-af",
                    f"adelay={round(max(0, -audio.seconds) * 1000)}:all=1,apad,volume={audio.gain}",
                    "-t",
                    str(duration),
                    "-c:a",
                    "libopus"
                    if settings.format.startswith("webm")
                    else "aac"
                    if settings.format == "mp4"
                    else "pcm_s16le",
                )
            )
        else:
            args.append("-an")
        args.extend((*VIDEO_OPTIONS[settings.format], str(output)))
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=errors,
                creationflags=subprocess.CREATE_NO_WINDOW
                if hasattr(subprocess, "CREATE_NO_WINDOW")
                else 0,
            )
            deadline = time.monotonic() + 120
            try:
                while process.poll() is None:
                    if cancel.wait(0.05):
                        raise RenderCancelled(
                            "Video encoding cancelled; staged output was discarded."
                        )
                    if time.monotonic() > deadline:
                        raise ProjectError("Video encoder exceeded its 120-second time limit.")
                if process.returncode:
                    errors.seek(0)
                    detail = errors.read(2048).decode("utf-8", errors="replace")
                    raise ProjectError(
                        f"Configured FFmpeg could not encode {FORMATS[settings.format][0]}: "
                        + detail
                    )
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()
