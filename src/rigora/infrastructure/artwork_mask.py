"""Decode original artwork alpha into bounded polygonal geometry without importing Qt."""

import io
from functools import lru_cache
from typing import Any

from rigora.domain.project import ProjectError
from rigora.infrastructure.artwork import inspect_artwork


@lru_cache(maxsize=2)
def artwork_mask(data: bytes) -> Any:
    """Union visible pixel runs, preserving holes and even single-pixel disconnected parts.

    SVG is rasterized solely to extract its mask; rendering continues to use the original
    vector asset. Complexity is bounded before invoking the polygon union backend.
    """
    try:
        from PIL import Image
    except ImportError:
        raise ProjectError("Install the render extra to generate artwork masks.") from None
    from shapely import box, union_all

    info = inspect_artwork(data)
    if info.kind == "vector":
        try:
            import resvg_py
        except ImportError:
            raise ProjectError("Install the render extra to generate SVG masks.") from None

        data = resvg_py.svg_to_bytes(
            svg_string=data.decode("utf-8"),
            skip_system_fonts=True,
            width=info.width,
            height=info.height,
        )
    with Image.open(io.BytesIO(data)) as image:
        alpha = image.convert("RGBA").getchannel("A")
        width, height = alpha.size
        pixels = alpha.tobytes()
    runs = []
    for y in range(height):
        x = 0
        while x < width:
            if not pixels[y * width + x]:
                x += 1
                continue
            start = x
            while x < width and pixels[y * width + x]:
                x += 1
            runs.append(box(start, y, x, y + 1))
            if len(runs) > 65536:
                raise ProjectError("Alpha mask is too complex; simplify it or choose Full.")
    return union_all(runs).simplify(0)
