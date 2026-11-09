"""Bounded, data-only decoding of raster, OpenRaster, PSD and PCM audio sources."""

import io
import math
import threading
import wave
import zipfile
from contextlib import closing
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree as ET

from rigora.domain.validation import ProjectError, portable_relative_path
from rigora.infrastructure.artwork import inspect_artwork

_PDF_LOCK = threading.Lock()


def pillow_image(data: bytes) -> Any:
    """Decode one bounded static raster using the optional render extra, never flatten animation."""
    try:
        from PIL import Image
    except ImportError:
        raise ProjectError(
            "Install the render extra for raster conversion and image output."
        ) from None
    try:
        image = Image.open(io.BytesIO(data))
        width, height = image.size
        if not 1 <= width <= 8192 or not 1 <= height <= 8192 or width * height > 16_777_216:
            raise ProjectError("Raster artwork exceeds the 8192-axis / 16-megapixel limit.")
        if getattr(image, "n_frames", 1) != 1:
            raise ProjectError(
                "Animated images need explicit frame extraction; use an image sequence."
            )
        image.load()
        return image.convert("RGBA")
    except ProjectError:
        raise
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        raise ProjectError(
            "The raster pixel data is invalid or exceeds supported bounds."
        ) from error


def png_bytes(image: Any) -> bytes:
    """Encode owned raster pixels without metadata or a filesystem side effect."""
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


@dataclass(frozen=True)
class ArtworkLayer:
    """One local-offset group or independently editable pixel layer in source draw order."""

    name: str
    parent: int | None
    x: float = 0
    y: float = 0
    opacity: float = 1
    visible: bool = True
    data: bytes | None = None


@dataclass(frozen=True)
class LayeredArtwork:
    """Validated canvas, original hierarchy and explicit unsupported-feature diagnostics."""

    width: int
    height: int
    layers: tuple[ArtworkLayer, ...]
    warnings: tuple[str, ...]
    media_type: str


def canvas_bounds(width: int, height: int) -> None:
    """Reject oversized layered canvases before allocating derived pixel buffers."""
    if not 1 <= width <= 8192 or not 1 <= height <= 8192 or width * height > 16_777_216:
        raise ProjectError("Layered artwork exceeds the 8192-axis / 16-megapixel limit.")


def read_openraster(data: bytes, *, allow_unsupported: bool = False) -> LayeredArtwork:
    """Read baseline source-over layers without extracting ZIP paths or silently flattening."""
    layers: list[ArtworkLayer] = []
    warnings: list[str] = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > 512 or len({m.filename for m in members}) != len(members):
                raise ProjectError("OpenRaster archive has excessive or duplicate members.")
            if sum(m.file_size for m in members) > 96 * 1024 * 1024:
                raise ProjectError("OpenRaster decoded source exceeds 96 MiB.")
            for member in members:
                if not member.is_dir():
                    portable_relative_path(member.filename)
                if member.file_size > 32 * 1024 * 1024 or member.flag_bits & 1:
                    raise ProjectError("OpenRaster has oversized or encrypted members.")
            if archive.read("mimetype") != b"image/openraster":
                raise ProjectError("OpenRaster mimetype is missing or invalid.")
            xml = archive.read("stack.xml")
            if len(xml) > 1024 * 1024 or b"<!" in xml:
                raise ProjectError("OpenRaster stack XML must be bounded and entity-free.")
            root = ET.fromstring(xml)
            width, height = int(root.attrib["w"]), int(root.attrib["h"])
            canvas_bounds(width, height)
            pixel_count = 0

            def visit(element: ET.Element, parent: int | None, depth: int) -> None:
                """Preserve hierarchy while reversing top-first ORA children into painter order."""
                nonlocal pixel_count
                if depth > 24 or len(layers) >= 128:
                    raise ProjectError("Layered artwork supports 128 layers and 24 group levels.")
                tag = element.tag.rsplit("}", 1)[-1]
                if tag not in ("stack", "layer"):
                    raise ProjectError(f"Unsupported OpenRaster element: {tag}.")
                opacity = float(element.get("opacity", "1"))
                x, y = float(element.get("x", "0")), float(element.get("y", "0"))
                if not all(math.isfinite(v) for v in (opacity, x, y)) or not 0 <= opacity <= 1:
                    raise ProjectError("Layer offsets/opacity are invalid.")
                issues = []
                if element.get("composite-op", "svg:src-over") != "svg:src-over":
                    issues.append("unsupported blend mode")
                if tag == "stack" and opacity != 1:
                    issues.append("isolated group opacity")
                if element.get("isolation", "auto") not in ("auto", "isolate"):
                    issues.append("unsupported group isolation")
                if issues:
                    message = f"{element.get('name', tag)}: {', '.join(issues)}."
                    if not allow_unsupported:
                        raise ProjectError(
                            message + " Use source-over layers or explicitly accept approximations."
                        )
                    warnings.append(
                        message + " Approximated as source-over; original source retained."
                    )
                content = None
                if tag == "layer":
                    source = element.attrib["src"]
                    portable_relative_path(source)
                    content = archive.read(source)
                    info = inspect_artwork(content)
                    if info.media_type != "image/png":
                        raise ProjectError("OpenRaster layer sources must be PNG.")
                    pillow_image(content)
                    pixel_count += info.width * info.height
                    if pixel_count > 64 * 1024 * 1024:
                        raise ProjectError("Layered artwork exceeds the 64-megapixel layer budget.")
                index = len(layers)
                layers.append(
                    ArtworkLayer(
                        element.get("name", "Layer")[:200] or "Layer",
                        parent,
                        x,
                        y,
                        opacity,
                        element.get("visibility", "visible") != "hidden",
                        content,
                    )
                )
                for child in reversed(list(element)):
                    visit(child, index, depth + 1)

            stack = root.find("stack")
            if stack is None:
                raise ProjectError("OpenRaster image has no layer stack.")
            visit(stack, None, 0)
            return LayeredArtwork(width, height, tuple(layers), tuple(warnings), "image/openraster")
    except ProjectError:
        raise
    except (zipfile.BadZipFile, ET.ParseError, KeyError, ValueError, OSError) as error:
        raise ProjectError("OpenRaster archive or layer data is invalid.") from error


def read_psd(data: bytes, *, allow_unsupported: bool = False) -> LayeredArtwork:
    """Extract basic PSD pixel layers with explicit refusal of masks, effects and smart content."""
    try:
        from psd_tools import PSDImage
        from psd_tools.constants import BlendMode
    except ImportError:
        raise ProjectError("Install the psd extra to import Photoshop pixel layers.") from None
    try:
        psd = PSDImage.open(io.BytesIO(data))
        canvas_bounds(psd.width, psd.height)
        if psd.depth != 8 or psd.color_mode.name != "RGB":
            raise ProjectError(
                "PSD import supports 8-bit RGB pixels. "
                "The original source can be registered separately."
            )
        layers: list[ArtworkLayer] = []
        warnings: list[str] = []
        pixels = 0

        def visit(layer: Any, parent: int | None, depth: int) -> None:
            """Extract raw pixels; retain PSD groups and separate authored opacity/visibility."""
            nonlocal pixels
            if depth > 24 or len(layers) >= 128:
                raise ProjectError("PSD import supports 128 layers and 24 group levels.")
            group = layer.is_group()
            issues = []
            if layer.kind not in ("pixel", "group"):
                issues.append(f"unsupported {layer.kind} layer")
            if layer.blend_mode not in (BlendMode.NORMAL, BlendMode.PASS_THROUGH):
                issues.append("unsupported blend mode")
            if (
                (group and layer.has_mask())
                or layer.has_vector_mask()
                or layer.clipping
                or layer.has_effects()
            ):
                issues.append("group/vector mask, clipping or layer effects")
            if group and layer.opacity != 255:
                issues.append("isolated group opacity")
            if issues:
                message = f"{layer.name}: {', '.join(issues)}."
                if not allow_unsupported:
                    raise ProjectError(
                        message + " Use basic pixel layers or explicitly accept approximations."
                    )
                warnings.append(message + " Raw pixels only; original PSD retained.")
            content = None
            if not group:
                if layer.width <= 0 or layer.height <= 0:
                    warnings.append(f"{layer.name}: empty layer retained only in the original PSD.")
                    return
                canvas_bounds(layer.width, layer.height)
                pixels += layer.width * layer.height
                if pixels > 64 * 1024 * 1024:
                    raise ProjectError("PSD layers exceed the 64-megapixel pixel budget.")
                image = layer.topil()
                if image is None:
                    raise ProjectError(f"{layer.name}: this layer has no extractable pixel data.")
                image = image.convert("RGBA")
                mask = layer.mask
                if mask is not None and not mask.disabled:
                    from PIL import Image, ImageChops

                    mask_pixels = mask.topil()
                    if mask_pixels is None:
                        raise ProjectError(f"{layer.name}: raster mask pixels are unavailable.")
                    coverage = Image.new("L", image.size, mask.background_color)
                    coverage.paste(mask_pixels, (mask.left - layer.left, mask.top - layer.top))
                    image.putalpha(ImageChops.multiply(image.getchannel("A"), coverage))
                    warnings.append(
                        f"{layer.name}: raster mask preserved in PNG alpha; original PSD retained."
                    )
                content = png_bytes(image)
            index = len(layers)
            layers.append(
                ArtworkLayer(
                    layer.name[:200] or "Layer",
                    parent,
                    0 if group else layer.left,
                    0 if group else layer.top,
                    layer.opacity / 255,
                    layer.visible,
                    content,
                )
            )
            if group:
                for child in layer:
                    visit(child, index, depth + 1)

        for layer in psd:
            visit(layer, None, 0)
        return LayeredArtwork(
            psd.width, psd.height, tuple(layers), tuple(warnings), "image/vnd.adobe.photoshop"
        )
    except ProjectError:
        raise
    except (OSError, ValueError, OverflowError) as error:
        raise ProjectError("PSD data is corrupt or uses an unsupported encoding.") from error


def audio_metadata(data: bytes) -> dict[str, Any]:
    """Inspect bounded PCM WAV audio for future lip-sync without decoding or playing samples."""
    try:
        with wave.open(io.BytesIO(data)) as audio:
            channels, rate = audio.getnchannels(), audio.getframerate()
            frames, sample_bytes = audio.getnframes(), audio.getsampwidth()
            if not 1 <= channels <= 8 or not 8000 <= rate <= 192000 or not 1 <= sample_bytes <= 4:
                raise ProjectError("WAV requires 1–8 channels, 8–192 kHz and 8–32-bit PCM samples.")
            if (
                frames > rate * 1800
                or len(audio.readframes(frames)) != frames * channels * sample_bytes
            ):
                raise ProjectError("WAV audio is truncated or exceeds 30 minutes.")
            return {
                "channels": channels,
                "sample_rate": rate,
                "sample_bytes": sample_bytes,
                "sample_frames": frames,
                "duration_seconds": frames / rate,
            }
    except (wave.Error, EOFError) as error:
        raise ProjectError(
            "Audio import currently supports valid uncompressed PCM WAV files."
        ) from error


def read_illustrator(data: bytes, *, allow_unsupported: bool = False) -> LayeredArtwork:
    """Import PDF-compatible AI artboards as transparent pixels, preserving source bytes.

    Illustrator's private editing data is not a public layered interchange format.
    Flattening is explicit; SVG remains the vector-preserving interchange route.
    PDFium is serialized because its native API is not thread safe.
    """
    if not data.startswith(b"%PDF-"):
        raise ProjectError(
            "Save Illustrator artwork with Create PDF Compatible File enabled, "
            "or export SVG to retain vectors. Legacy PostScript AI is unsupported."
        )
    if not allow_unsupported:
        raise ProjectError(
            "Illustrator import renders each artboard as transparent pixels. "
            "Enable the approximation option to accept this, or import SVG for vectors."
        )
    try:
        import pypdfium2 as pdfium
    except ImportError:
        raise ProjectError("Install the illustrator extra for PDF-compatible AI import.") from None
    layers: list[ArtworkLayer] = []
    width = height = total = 0
    try:
        with _PDF_LOCK, pdfium.PdfDocument(data) as document:
            if not 1 <= len(document) <= 32:
                raise ProjectError("Illustrator import supports 1–32 artboards.")
            for index in range(len(document)):
                with closing(document[index]) as page:
                    w, h = (math.ceil(value) for value in page.get_size())
                    canvas_bounds(w, h)
                    total += w * h
                    if total > 16_777_216:
                        raise ProjectError("Illustrator artboards exceed 16 megapixels in total.")
                    with closing(page.render(scale=1, fill_color=(0, 0, 0, 0))) as bitmap:
                        pixels = png_bytes(bitmap.to_pil())
                    layers.append(
                        ArtworkLayer(f"Artboard {index + 1}", None, visible=index == 0, data=pixels)
                    )
                    width, height = max(width, w), max(height, h)
        return LayeredArtwork(
            width,
            height,
            tuple(layers),
            (
                "AI artboards are flattened at 72 pixels/inch; private layers, vectors "
                "and live text "
                "are preserved only in the embedded original. Only the first artboard is visible. "
                "Import Illustrator-exported SVG for editable vector artwork.",
            ),
            "application/illustrator",
        )
    except ProjectError:
        raise
    except (pdfium.PdfiumError, OSError, ValueError, OverflowError) as error:
        raise ProjectError("Illustrator PDF data is corrupt, encrypted or unsupported.") from error
