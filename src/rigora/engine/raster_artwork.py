"""Portable PNG parts with optional original contours for non-destructive palette edits."""

from io import BytesIO
from math import ceil
from xml.etree import ElementTree as ET

from rigora.domain.project import ProjectError

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def editable_svg(data: bytes) -> bytes | None:
    """Read bounded PNG text metadata without decoding its pixel buffer.

    Ordinary imported PNGs have no contours and continue to support whole-image tint.
    Creator PNGs retain their original local contours inside the portable image itself.
    """
    if not data.startswith(PNG_SIGNATURE):
        return None
    from PIL import Image

    with Image.open(BytesIO(data)) as image:
        source = image.info.get("rigora.svg")
        if not isinstance(source, str):
            return None
        from rigora.engine.artwork_source import inspect_artwork

        vector = source.encode("utf-8")
        if inspect_artwork(vector).kind != "vector":
            raise ProjectError("Editable PNG contours must be a self-contained SVG.")
        return vector


def rasterize_part(data: bytes, width: int, height: int) -> bytes:
    """Render transparent pixels at explicit resolution and preserve editable local contours."""
    import resvg_py
    from PIL import Image, PngImagePlugin

    if not 1 <= width <= 4096 or not 1 <= height <= 4096:
        raise ProjectError("Creator PNG parts must be between 1 and 4096 pixels per side.")
    root = ET.fromstring(data)
    root.set("width", str(width))
    root.set("height", str(height))
    root.set("preserveAspectRatio", "none")
    raw = resvg_py.svg_to_bytes(svg_string=ET.tostring(root).decode(), skip_system_fonts=True)
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("rigora.svg", data.decode("utf-8"), zip=True)
    with Image.open(BytesIO(raw)) as image:
        output = BytesIO()
        image.save(output, format="PNG", pnginfo=metadata)
        return output.getvalue()


def component_source(
    data: bytes, width: float, height: float, source_format: str
) -> tuple[bytes, float, float]:
    """Return source bytes and pixel-to-local scales without changing authored rig geometry.

    PNG parts use four pixels per logical unit, bounded to 2048 pixels per side.
    Independent axis scales absorb integer rounding, keeping joints exactly aligned.
    """
    if source_format == "SVG":
        return data, 1.0, 1.0
    width, height = ceil(width), ceil(height)
    factor = min(4.0, 2048 / max(width, height))
    pixels_x, pixels_y = max(1, round(width * factor)), max(1, round(height * factor))
    return rasterize_part(data, pixels_x, pixels_y), width / pixels_x, height / pixels_y
