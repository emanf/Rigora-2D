"""Create owned static PNG posters when publishing content, never while browsing it."""

import io
import re
import struct
import zlib
from typing import Any

from rigora.domain.content import ContentItem


def placeholder_thumbnail() -> bytes:
    """Generate a neutral transparent Object glyph without a source-tree PNG asset."""
    size = 48
    scanlines = bytearray()
    for y in range(size):
        scanlines.append(0)
        for x in range(size):
            filled = 7 <= x <= 20 and 7 <= y <= 20 or 27 <= x <= 40 and 27 <= y <= 40
            outline = (
                27 <= x <= 40 and 7 <= y <= 20 and (x in (27, 28, 39, 40) or y in (7, 8, 19, 20))
            )
            scanlines.extend((210, 210, 210, 255) if filled or outline else (0, 0, 0, 0))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(scanlines)))
        + chunk(b"IEND", b"")
    )


def _framed_preset(document: Any, frame: float, *, bones: bool) -> Any:
    """Render vectors at poster resolution after framing actual evaluated specimen geometry."""
    import resvg_py
    from PIL import Image

    from rigora.application_services.rendering import svg_frame
    from rigora.domain.geometry import transform_point
    from rigora.engine.cameras import active_camera, camera_view

    pose = document.animation.evaluate(frame).for_display()
    pose = camera_view(pose, active_camera(pose))
    points: list[tuple[float, float]] = []
    for node in pose.nodes.values():
        if node.kind == "bone" and node.visible and bones:
            points.extend(
                (
                    transform_point(node.world_matrix, 0, 0),
                    transform_point(node.world_matrix, node.length, 0),
                )
            )
    for mesh in pose.meshes.values():
        if mesh.object_id and mesh.object_id in pose.nodes and pose.nodes[mesh.object_id].visible:
            points.extend(
                transform_point(pose.nodes[mesh.object_id].world_matrix, *point)
                for point in mesh.positions
            )
    if not points:
        raise ValueError("The preset has no visible specimen geometry.")
    left, top = min(p[0] for p in points), min(p[1] for p in points)
    width = max(1, max(p[0] for p in points) - left)
    height = max(1, max(p[1] for p in points) - top)
    padding = max(width, height) * 0.09
    source = svg_frame(document, frame, width=384, height=384, bones=bones)
    view = (
        f'viewBox="{left - padding} {top - padding} {width + padding * 2} {height + padding * 2}"'
    )
    framed = re.sub(r'viewBox="[^"]*"', view, source.decode(), count=1)
    if bones:
        from rigora.infrastructure.bone_contrast import outlined_bone_uses

        framed = outlined_bone_uses(
            framed, min(384 / (width + padding * 2), 384 / (height + padding * 2))
        )
    return Image.open(
        io.BytesIO(resvg_py.svg_to_bytes(svg_string=framed, width=384, height=384))
    ).convert("RGBA")


def render_content_thumbnail(item: ContentItem, files: dict[str, bytes], size: int = 144) -> bytes:
    """Render actual source art or a specimen pose once and return a transparent PNG.

    Requires the optional render dependencies. The caller owns persistence and
    provenance; neither installed packs nor the active editor document are changed.
    """
    import resvg_py
    from PIL import Image

    from rigora.application_services.content_library import ContentService
    from rigora.application_services.documents import DocumentService
    from rigora.application_services.output import OutputSettings, raster_frame
    from rigora.infrastructure.artwork import inspect_artwork

    image: Any
    if item.thumbnail or item.kind == "artwork" and item.payload.get("source"):
        source = files[item.thumbnail or str(item.payload["source"])]
        info = inspect_artwork(source)
        if info.kind == "vector":
            scale = 384 / max(info.width, info.height)
            source = resvg_py.svg_to_bytes(
                svg_string=source.decode("utf-8"),
                skip_system_fonts=True,
                width=max(1, round(info.width * scale)),
                height=max(1, round(info.height * scale)),
            )
        image = Image.open(io.BytesIO(source)).convert("RGBA")
    else:
        document = DocumentService()
        document.new("Content poster")
        specimen = ContentService(document).preview(item, files, specimen=True)
        frame = specimen.animation.evaluator.range.end / 4
        if item.kind == "action":
            frame = (
                float(item.payload["duration"])
                * specimen.scene.settings.fps
                / float(item.payload.get("fps", 24))
                * 0.14
            )
        elif item.kind == "deformation" and "motion" in item.payload:
            motion = item.payload["motion"]
            frame = (
                float(motion["duration"])
                * specimen.scene.settings.fps
                / float(motion.get("fps", 24))
                * 0.19
            )
        if (
            item.payload.get("fallback_rig")
            or item.payload.get("fallback_mesh")
            or item.payload.get("rig_bounds")
            or item.payload.get("preview_bounds")
        ):
            image = _framed_preset(specimen, frame, bones=item.kind in ("rig", "action", "spring"))
        else:
            image = raster_frame(
                specimen,
                frame,
                OutputSettings(
                    width=640, height=360, bones=item.kind in ("rig", "pose", "action", "spring")
                ),
            )
    bounds = image.getbbox()
    if bounds:
        image = image.crop(bounds)
    image.thumbnail((size - 16, size - 16), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size))
    canvas.alpha_composite(image, ((size - image.width) // 2, (size - image.height) // 2))
    stream = io.BytesIO()
    canvas.save(stream, format="PNG", optimize=True)
    return stream.getvalue()
