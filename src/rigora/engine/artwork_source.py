"""Bounded Qt-free metadata inspection for portable PNG, JPEG and static SVG sources."""

import math
import re
import struct
import zlib
from dataclasses import dataclass
from typing import Literal
from xml.etree import ElementTree

from rigora.domain.validation import ProjectError


@dataclass(frozen=True)
class ArtworkInfo:
    """Validated pixel bounds and media type, independent of a GUI decoder or project mutation."""

    width: int
    height: int
    kind: Literal["raster", "vector"]
    media_type: str


def _info(
    width: float, height: float, kind: Literal["raster", "vector"], media: str
) -> ArtworkInfo:
    """Limit decoded dimensions before an optional rendering adapter allocates image memory."""
    if (
        not all(math.isfinite(v) and 0 < v <= 8192 for v in (width, height))
        or width * height > 16_777_216
    ):
        raise ProjectError("Artwork must be at most 8192 pixels per axis and 16 megapixels.")
    return ArtworkInfo(math.ceil(width), math.ceil(height), kind, media)


def inspect_artwork(data: bytes) -> ArtworkInfo:
    """Inspect image headers and reject active or externally linked SVG content."""
    if len(data) > 32 * 1024 * 1024:
        raise ProjectError("Artwork exceeds the 32 MiB source limit.")
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        if (
            len(data) < 33
            or data[8:16] != b"\x00\x00\x00\rIHDR"
            or zlib.crc32(data[12:29]) != int.from_bytes(data[29:33])
        ):
            raise ProjectError("PNG has an invalid image header.")
        width, height = struct.unpack(">II", data[16:24])
        offset = 33
        while offset + 12 <= len(data):
            size = int.from_bytes(data[offset : offset + 4])
            chunk_kind = data[offset + 4 : offset + 8]
            if chunk_kind == b"acTL":
                raise ProjectError("Animated PNG must be imported as an explicit frame sequence.")
            if chunk_kind in (b"IDAT", b"IEND"):
                break
            offset += size + 12
        return _info(width, height, "raster", "image/png")
    if data.startswith(b"\xff\xd8"):
        offset = 2
        while offset + 4 <= len(data):
            if data[offset] != 255:
                break
            while offset < len(data) and data[offset] == 255:
                offset += 1
            if offset >= len(data):
                break
            marker = data[offset]
            offset += 1
            if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                continue
            length = int.from_bytes(data[offset : offset + 2])
            if length < 2 or offset + length > len(data):
                break
            if (
                marker
                in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF)
                and length >= 7
            ):
                height, width = struct.unpack(">HH", data[offset + 3 : offset + 7])
                return _info(width, height, "raster", "image/jpeg")
            offset += length
        raise ProjectError("JPEG has no supported bounded image header.")
    if (
        data.startswith((b"GIF87a", b"GIF89a", b"BM", b"II*\x00", b"MM\x00*"))
        or data.startswith(b"RIFF")
        and data[8:12] == b"WEBP"
    ):
        try:
            from PIL import Image
        except ImportError:
            raise ProjectError(
                "Install the render extra to import GIF, BMP, TIFF or WebP artwork."
            ) from None
        import io

        try:
            with Image.open(io.BytesIO(data)) as image:
                if getattr(image, "n_frames", 1) != 1:
                    raise ProjectError(
                        "Animated/multipage images must be imported as explicit frame sequences."
                    )
                media = {
                    "GIF": "image/gif",
                    "BMP": "image/bmp",
                    "TIFF": "image/tiff",
                    "WEBP": "image/webp",
                }
                info = _info(*image.size, "raster", media[str(image.format)])
                image.verify()
                return info
        except ProjectError:
            raise
        except (OSError, ValueError, KeyError, Image.DecompressionBombError) as error:
            raise ProjectError("The raster image data is invalid or unsupported.") from error
    try:
        svg_text = data.decode("utf-8-sig")
    except UnicodeError as error:
        raise ProjectError("Static SVG sources must use UTF-8 encoding.") from error
    upper = svg_text.upper()
    if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
        raise ProjectError("SVG document types and entities are not supported.")
    try:
        root = ElementTree.fromstring(data)
        if root.tag.rsplit("}", 1)[-1] != "svg":
            raise ProjectError("Choose a PNG, JPEG or static SVG artwork file.")
        for index, item in enumerate(root.iter()):
            if index >= 100_000:
                raise ProjectError("Static SVG artwork exceeds the 100,000-element limit.")
            tag = item.tag.rsplit("}", 1)[-1].lower()
            if tag in ("script", "foreignobject", "image", "set") or tag.startswith("animate"):
                raise ProjectError("SVG must contain self-contained static vector artwork.")
            values = [*item.attrib.values(), item.text or ""]
            if any(key.rsplit("}", 1)[-1].lower().startswith("on") for key in item.attrib):
                raise ProjectError("SVG event handlers are not supported.")
            for key, value in item.attrib.items():
                if key.rsplit("}", 1)[-1] == "href" and not value.startswith("#"):
                    raise ProjectError("SVG external references are not supported.")
            for value in values:
                if "@import" in value.lower() or any(
                    not ref.strip(" \t\r\n\"'").startswith("#")
                    for ref in re.findall(r"url\(([^)]*)\)", value, flags=re.IGNORECASE)
                ):
                    raise ProjectError("SVG external style resources are not supported.")
        viewbox = [float(v) for v in root.get("viewBox", "0 0 0 0").replace(",", " ").split()]

        def dimension(key: str, fallback: float) -> float:
            """Use explicit pixel dimensions or the matching viewBox extent."""
            value = root.get(key, "")
            return (
                float(value.removesuffix("px"))
                if re.fullmatch(r"\d+(?:\.\d+)?(?:px)?", value)
                else fallback
            )

        if len(viewbox) != 4:
            raise ProjectError("SVG viewBox must contain four numeric values.")
        if "viewBox" in root.attrib and (
            not all(math.isfinite(v) for v in viewbox) or min(viewbox[2:]) <= 0
        ):
            raise ProjectError("SVG viewBox needs finite values and positive dimensions.")
        return _info(
            dimension("width", viewbox[2]),
            dimension("height", viewbox[3]),
            "vector",
            "image/svg+xml",
        )
    except (ElementTree.ParseError, ValueError, OverflowError) as error:
        raise ProjectError("Choose a valid PNG, JPEG or self-contained static SVG file.") from error
