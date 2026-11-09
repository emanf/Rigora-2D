"""In-process screen keying with linear-light mattes, edge cleanup and despill.

This independent implementation uses NumPy/OpenCV color-keying mathematics.
See docs/keying-source-review.md for reviewed Blender stages and differences.
No Blender code, executable or subprocess is required.
"""

import io
import math
from collections import Counter
from dataclasses import dataclass
from threading import Event
from typing import Any

from rigora.domain.project import ProjectError


@dataclass(frozen=True)
class KeyingSettings:
    """Immutable screen and matte controls shared by preview, final art and automation."""

    method: str = "Auto"
    color: tuple[float, float, float] | None = None
    tolerance: float = 0.1
    softness: float = 0.1
    despill: float = 1.0
    balance: float = 0.5
    despill_balance: float = 0.5
    pre_blur: int = 0
    matte_blur: int = 0
    grow: int = 0
    feather: int = 0

    def __post_init__(self) -> None:
        """Reject nonfinite colors, factors and excessive pixel filters at the boundary."""
        factors = (
            self.tolerance,
            self.softness,
            self.despill,
            self.balance,
            self.despill_balance,
            *(self.color or ()),
        )
        if (
            self.method not in ("Auto", "Chroma", "Difference")
            or self.color is not None
            and len(self.color) != 3
            or any(not math.isfinite(v) or not 0 <= v <= 1 for v in factors)
            or any(type(v) is not int or not 0 <= v <= 16 for v in (self.pre_blur, self.matte_blur))
            or any(type(v) is not int or not -16 <= v <= 16 for v in (self.grow, self.feather))
        ):
            raise ProjectError(
                "Choose Auto, Chroma or Difference, factors from 0 to 1 "
                "and filters within 16 pixels."
            )


def border_color(data: bytes) -> tuple[float, float, float]:
    """Estimate a solid-screen key from the most common quantized perimeter color."""
    from PIL import Image

    with Image.open(io.BytesIO(data)) as source:
        image = source.convert("RGB")
        width, height = image.size
        points = [(x, y) for x in range(0, width, max(1, width // 128)) for y in (0, height - 1)]
        points += [(x, y) for y in range(0, height, max(1, height // 128)) for x in (0, width - 1)]
        pixels = image.tobytes()
        colors = [tuple(pixels[(y * width + x) * 3 : (y * width + x) * 3 + 3]) for x, y in points]
        bucket = Counter(tuple(v // 8 for v in color) for color in colors).most_common(1)[0][0]
        selected = [color for color in colors if tuple(v // 8 for v in color) == bucket]
        channels = [sum(color[i] for color in selected) / len(selected) / 255 for i in range(3)]
        return channels[0], channels[1], channels[2]


def _linear(values: Any) -> Any:
    """Convert normalized sRGB to linear light without changing alpha."""
    import numpy as np

    return np.where(values <= 0.04045, values / 12.92, ((values + 0.055) / 1.055) ** 2.4)


def _edge_pixels(matte: Any) -> Any:
    """Protect detail where more than a tenth of a 7×7 neighborhood differs by 0.1."""
    import numpy as np

    height, width = matte.shape
    padded = np.pad(matte, 3, mode="edge")
    matches = np.zeros(matte.shape, dtype=np.uint8)
    for y in range(7):
        for x in range(7):
            matches += np.abs(padded[y : y + height, x : x + width] - matte) < 0.1
    return matches < 45


def key_cutout(data: bytes, settings: KeyingSettings, *, cancel: Event | None = None) -> bytes:
    """Return a bounded RGBA PNG through the same local pipeline for review and creation.

    Existing transparency passes through unchanged. Opaque images are processed
    in linear light; screen dominance creates chroma mattes, while neutral screens
    use mean RGB difference. Filters run between cancellation checks and retain
    only the reference image, never a video-sized raster atlas.
    """
    import cv2
    import numpy as np
    from PIL import Image, UnidentifiedImageError

    cancelled = cancel or Event()

    def checkpoint() -> None:
        """Stop at stage boundaries without returning partially processed artwork."""
        if cancelled.is_set():
            raise ProjectError("Background keying cancelled.")

    checkpoint()
    if not data or len(data) > 16 * 1024 * 1024:
        raise ProjectError("Reference image is empty or exceeds 16 MiB.")
    try:
        with Image.open(io.BytesIO(data)) as source:
            width, height = source.size
            if not 1 <= width <= 1920 or not 1 <= height <= 1080:
                raise ProjectError("Reference image exceeds the media review dimensions.")
            source.load()
            has_alpha = "A" in source.getbands() or "transparency" in source.info
            if has_alpha and source.convert("RGBA").getchannel("A").getextrema() != (255, 255):
                checkpoint()
                if source.format == "PNG":
                    return data
                output = io.BytesIO()
                source.convert("RGBA").save(output, format="PNG")
                return output.getvalue()
            pixels = np.asarray(source.convert("RGB"), dtype=np.float32) / 255
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ProjectError("The reference image cannot be decoded safely.") from error
    checkpoint()
    screen = settings.color or border_color(data)
    method = settings.method
    if method == "Auto":
        method = "Chroma" if max(screen) - min(screen) > 0.1 else "Difference"
    rgb = _linear(pixels)
    key = _linear(np.asarray(screen, dtype=np.float32))
    primary = int(np.argmax(key))
    others = [i for i in range(3) if i != primary]
    working = rgb
    if settings.pre_blur:
        # Color residuals can be smoothed without blurring per-pixel luminance.
        luminance = np.sum(
            rgb * np.asarray((0.2126, 0.7152, 0.0722), dtype=np.float32), axis=2, keepdims=True
        )
        size = settings.pre_blur * 2 + 1
        working = luminance + cv2.blur(
            rgb - luminance, (size, size), borderType=cv2.BORDER_REPLICATE
        )
    if method == "Chroma":
        weights = np.asarray((settings.balance, 1 - settings.balance), dtype=np.float32)
        key_side = float(np.sum(key[others] * weights))
        contrast = float((key[primary] - key_side) * (1 - key_side))
        if contrast < 1e-6:
            raise ProjectError(
                "Chroma needs a colored screen. Use Difference for a neutral key color."
            )
        side = np.sum(working[..., others] * weights, axis=2)
        matte = 1 - np.clip((working[..., primary] - side) * (1 - side) / contrast, 0, 1)
        edge = _edge_pixels(matte)
        upper = max(settings.tolerance + 1e-6, 1 - settings.softness)
        levels = np.clip((matte - settings.tolerance) / max(upper - settings.tolerance, 1e-6), 0, 1)
        matte = np.where(edge, matte, levels)
    else:
        difference = np.mean(np.abs(working - key), axis=2)
        matte = np.clip((difference - settings.tolerance) / max(settings.softness, 1e-6), 0, 1)
    checkpoint()
    if settings.matte_blur:
        size = settings.matte_blur * 2 + 1
        matte = cv2.blur(matte, (size, size), borderType=cv2.BORDER_REPLICATE)
    if settings.grow:
        radius = abs(settings.grow)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius * 2 + 1, radius * 2 + 1))
        matte = (cv2.dilate if settings.grow > 0 else cv2.erode)(
            matte, kernel, borderType=cv2.BORDER_REPLICATE
        )
    checkpoint()
    if settings.feather:
        foreground = (matte >= 0.5).astype(np.uint8)
        inside = settings.feather < 0
        distance = cv2.distanceTransform(
            foreground if inside else 1 - foreground, cv2.DIST_L2, cv2.DIST_MASK_PRECISE
        )
        transition = np.clip(distance / abs(settings.feather), 0, 1)
        transition = transition * transition * (3 - 2 * transition)
        matte = np.minimum(matte, transition) if inside else np.maximum(matte, 1 - transition)
    if method == "Chroma" and settings.despill:
        limit = rgb[..., others[0]] * settings.despill_balance + rgb[..., others[1]] * (
            1 - settings.despill_balance
        )
        rgb[..., primary] -= settings.despill * np.maximum(rgb[..., primary] - limit, 0)
        rgb = np.clip(rgb, 0, 1)
        pixels = np.where(rgb <= 0.0031308, rgb * 12.92, 1.055 * rgb ** (1 / 2.4) - 0.055)
    checkpoint()
    rgba = np.empty((height, width, 4), dtype=np.uint8)
    rgba[..., :3] = np.rint(np.clip(pixels, 0, 1) * 255).astype(np.uint8)
    rgba[..., 3] = np.rint(np.clip(matte, 0, 1) * 255).astype(np.uint8)
    rgba[rgba[..., 3] == 0, :3] = 0
    output = io.BytesIO()
    Image.fromarray(rgba).save(output, format="PNG")
    checkpoint()
    return output.getvalue()
