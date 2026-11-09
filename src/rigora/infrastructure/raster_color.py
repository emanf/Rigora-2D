"""Normalize tagged raster imports to oriented sRGB while leaving ordinary sources byte-exact."""

import io
from functools import lru_cache
from typing import Any

from rigora.domain.project import ProjectError


@lru_cache(maxsize=1)
def srgb_profile() -> bytes:
    """Return a small standard output ICC profile, created once by the optional imaging codec."""
    from PIL import ImageCms

    return bytes(ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes())


def normalized_raster(data: bytes) -> tuple[bytes, dict[str, Any]]:
    """Return canonical PNG pixels and provenance when orientation/profile correction is needed.

    Untagged images are interpreted as sRGB. The caller retains original bytes
    separately for corrected imports. No display/mesh dimensions change later
    during playback, and existing project sources are never rewritten on load.
    """
    if not any(
        marker in data for marker in (b"iCCP", b"ICC_PROFILE", b"Exif", b"eXIf")
    ) and not data.startswith((b"II*\x00", b"MM\x00*")):
        return data, {}
    try:
        from PIL import Image, ImageCms, ImageOps
    except ImportError as error:
        raise ProjectError(
            "Install the render extra to import color-profiled or oriented images."
        ) from error
    try:
        with Image.open(io.BytesIO(data)) as source:
            width, height = source.size
            if width * height > 16_777_216 or max(width, height) > 8192:
                raise ProjectError("Raster artwork exceeds the 8192-axis / 16-megapixel limit.")
            if getattr(source, "n_frames", 1) != 1:
                raise ProjectError("Animated images require explicit frame extraction.")
            orientation = source.getexif().get(274, 1)
            profile = source.info.get("icc_profile")
            target = srgb_profile() if profile else None
            if orientation in (None, 1) and (not profile or profile == target):
                return data, {}
            image = ImageOps.exif_transpose(source)
            if profile:
                assert target is not None
                if not isinstance(profile, bytes) or len(profile) > 4 * 1024 * 1024:
                    raise ProjectError("Image color profile is invalid or exceeds 4 MiB.")
                converted = ImageCms.profileToProfile(
                    image,
                    ImageCms.ImageCmsProfile(io.BytesIO(profile)),
                    ImageCms.ImageCmsProfile(io.BytesIO(target)),
                    outputMode="RGB",
                )
                if converted is None:
                    raise ProjectError("The image color transform did not produce pixels.")
                converted.putalpha(image.convert("RGBA").getchannel("A"))
                image = converted
            else:
                image = image.convert("RGBA")
            stream = io.BytesIO()
            image.save(stream, format="PNG", icc_profile=target or srgb_profile(), exif=b"")
            return stream.getvalue(), {
                "color_space": "sRGB",
                "orientation_applied": orientation,
                "source_dimensions": [width, height],
            }
    except ProjectError:
        raise
    except (OSError, ValueError, ImageCms.PyCMSError, Image.DecompressionBombError) as error:
        raise ProjectError("Cannot normalize the image color profile or orientation.") from error
