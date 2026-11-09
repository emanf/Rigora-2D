"""Original vector shape generation and non-destructive, animatable SVG palette edits."""

import io
import math
import re
from collections.abc import Mapping
from functools import lru_cache
from typing import Any
from xml.etree import ElementTree as ET

from rigora.domain.project import ProjectError
from rigora.domain.validation import json_copy
from rigora.engine.raster_artwork import editable_svg, rasterize_part
from rigora.engine.sampling import number

PAINTS = ("fill", "stroke", "stop-color")


def rgb(value: str) -> tuple[int, int, int] | None:
    """Normalize supported SVG solid paint while leaving references and transparency alone."""
    value = value.strip()
    if re.fullmatch(r"#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})", value):
        digits = value[1:]
        if len(digits) in (3, 4):
            digits = "".join(c * 2 for c in digits)
        return int(digits[:2], 16), int(digits[2:4], 16), int(digits[4:6], 16)
    if (
        not value
        or value.lower() in ("none", "transparent", "inherit", "currentcolor")
        or "url(" in value
    ):
        return None
    try:
        from PIL import ImageColor

        return ImageColor.getrgb(value)[:3]
    except (ValueError, ImportError):
        return None


@lru_cache(maxsize=128)
def palette(data: bytes) -> tuple[tuple[str, str], ...]:
    """List distinct literal SVG fill/stroke/gradient-stop paints without mutating sources."""
    data = editable_svg(data) or data
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return ()
    found: dict[tuple[str, str], None] = {}

    def visit(element: ET.Element, inherited: str = "#000000") -> None:
        """Follow inherited fill; explicit group paints must not become implicit black."""
        properties = dict(element.attrib)
        properties.update(dict(re.findall(r"([\w-]+)\s*:\s*([^;]+)", element.get("style", ""))))
        fill = properties.get("fill", inherited)
        for role in PAINTS:
            color = rgb(
                properties.get(
                    role,
                    fill
                    if role == "fill"
                    and element.tag.rsplit("}", 1)[-1]
                    in ("path", "rect", "circle", "ellipse", "polygon")
                    else "",
                )
            )
            if color:
                found[(role, "#" + "".join(f"{c:02x}" for c in color))] = None
        if element.tag.rsplit("}", 1)[-1] == "style":
            for role, value in re.findall(
                r"(fill|stroke|stop-color)\s*:\s*([^;}]+)", element.text or ""
            ):
                color = rgb(value)
                if color:
                    found[(role, "#" + "".join(f"{c:02x}" for c in color))] = None
        for child in element:
            visit(child, fill)

    visit(root)
    return tuple(found)


def shape_svg(
    width: float, height: float, start: str, end: str | None = None, mix: float = 0
) -> bytes:
    """Interpolate compatible cubic contours, including an exact ellipse-to-rectangle morph."""
    width, height, mix = number(width), number(height), min(1, max(0, number(mix)))
    if not 1 <= width <= 16384 or not 1 <= height <= 16384:
        raise ProjectError("Vector shape dimensions must be between 1 and 16384.")
    allowed = ("ellipse", "rectangle", "triangle", "diamond", "star")
    if start not in allowed or (end or start) not in allowed:
        raise ProjectError("Choose a supported vector shape.")
    cx, cy, rx, ry = width / 2, height / 2, width * 0.46, height * 0.46

    def contour(kind: str) -> list[tuple[float, float]]:
        """Use a shared winding and 120 segments; polygon corners land on segment boundaries."""
        count = {"triangle": 3, "diamond": 4, "star": 10, "rectangle": 4}.get(kind, 0)
        vertices = []
        if count:
            for i in range(count):
                a = -math.pi / 2 + 2 * math.pi * i / count
                radius = 0.45 if kind == "star" and i % 2 else 1
                vertices.append((cx + rx * math.cos(a) * radius, cy + ry * math.sin(a) * radius))
        if kind == "rectangle":
            vertices = [
                (cx, cy - ry),
                (cx + rx, cy - ry),
                (cx + rx, cy),
                (cx + rx, cy + ry),
                (cx, cy + ry),
                (cx - rx, cy + ry),
                (cx - rx, cy),
                (cx - rx, cy - ry),
            ]
            count = 8
        result: list[tuple[float, float]] = []
        for i in range(120):
            if not count:
                a, b = -math.pi / 2 + i * math.tau / 120, -math.pi / 2 + (i + 1) * math.tau / 120
                k = 4 / 3 * math.tan((b - a) / 4)
                p, q = (
                    (cx + rx * math.cos(a), cy + ry * math.sin(a)),
                    (cx + rx * math.cos(b), cy + ry * math.sin(b)),
                )
                result.extend(
                    (
                        p,
                        (p[0] - k * rx * math.sin(a), p[1] + k * ry * math.cos(a)),
                        (q[0] + k * rx * math.sin(b), q[1] - k * ry * math.cos(b)),
                    )
                )
            else:
                segment, fraction = divmod(i * count, 120)
                p, q = vertices[segment % count], vertices[(segment + 1) % count]
                t, dt = fraction / 120, count / 120
                result.extend(
                    tuple(
                        (p[0] + (q[0] - p[0]) * u, p[1] + (q[1] - p[1]) * u)
                        for u in (t, t + dt / 3, t + 2 * dt / 3)
                    )
                )
        return result

    first, second = contour(start), contour(end or start)
    points = [
        ((1 - mix) * a[0] + mix * b[0], (1 - mix) * a[1] + mix * b[1])
        for a, b in zip(first, second, strict=True)
    ]
    path = f"M{points[0][0]:.7g},{points[0][1]:.7g}"
    for i in range(120):
        controls = (points[i * 3 + 1], points[i * 3 + 2], points[((i + 1) * 3) % len(points)])
        path += "C" + " ".join(f"{x:.7g},{y:.7g}" for x, y in controls)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}"><path d="{path}Z" fill="#bcbcbc" '
        'stroke="#333333" stroke-width="2"/></svg>'
    ).encode()


def styled_artwork(
    data: bytes, appearance: Mapping[str, Any], *, raster_limit: int | None = None
) -> bytes:
    """Apply evaluated palette, border, tint and shape parameters to a render copy only."""
    import json

    return _styled(data, json.dumps(json_copy(appearance), sort_keys=True), raster_limit)


@lru_cache(maxsize=32)
def _styled(data: bytes, encoded: str, raster_limit: int | None = None) -> bytes:
    """Bound frame variants while preserving original embedded sources and SVG sharpness."""
    import json

    look = json.loads(encoded)
    if vector := editable_svg(data):
        if not paint_changed(look):
            return data
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            scale = min(1, raster_limit / max(image.size)) if raster_limit else 1
            return rasterize_part(
                _styled(vector, encoded),
                max(1, round(image.width * scale)),
                max(1, round(image.height * scale)),
            )
    shape = look.get("shape")
    if shape:
        data = shape_svg(
            shape["width"], shape["height"], shape["start"], shape.get("end"), shape.get("mix", 0)
        )
    tint = look.get("tint", {})
    amount = min(1, max(0, number(tint.get("amount", 0))))

    def color(value: str, role: str) -> str:
        """Resolve authored replacement first, then apply the shared whole-image tint."""
        old = rgb(value)
        if old is None:
            return value
        source = "#" + "".join(f"{c:02x}" for c in old)
        replacement = next(
            (
                p
                for p in look.get("palette", ())
                if p.get("source") == source and p.get("role", role) == role
            ),
            None,
        )
        channels = tuple(
            number(replacement.get(k, old[i])) if replacement else old[i]
            for i, k in enumerate(("r", "g", "b"))
        )
        channels = tuple(
            round(min(255, max(0, c * (1 - amount) + number(tint.get(k, 255)) * amount)))
            for c, k in zip(channels, ("r", "g", "b"), strict=True)
        )
        suffix = value.strip()[7:] if re.fullmatch(r"#[0-9a-fA-F]{8}", value.strip()) else ""
        if re.fullmatch(r"#[0-9a-fA-F]{4}", value.strip()):
            suffix = value.strip()[-1] * 2
        return "#" + "".join(f"{int(c):02x}" for c in channels) + suffix

    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        if not amount:
            return data
        from PIL import Image

        with Image.open(io.BytesIO(data)) as source_image:
            rgba_image = source_image.convert("RGBA")
            overlay = Image.new(
                "RGBA",
                rgba_image.size,
                tuple(round(min(255, max(0, tint.get(k, 255)))) for k in ("r", "g", "b")) + (255,),
            )
            tinted = Image.blend(rgba_image, overlay, amount)
            tinted.putalpha(rgba_image.getchannel("A"))
            output = io.BytesIO()
            tinted.save(output, format="PNG")
            return output.getvalue()
    # A root default follows SVG inheritance; group/stylesheet paints continue to override it.
    if "fill" not in root.attrib and not re.search(r"(?:^|;)\s*fill\s*:", root.get("style", "")):
        root.set("fill", "#000000")
    for element in root.iter():
        style = dict(re.findall(r"([\w-]+)\s*:\s*([^;]+)", element.get("style", "")))
        for role in PAINTS:
            if role in element.attrib:
                element.set(role, color(element.attrib[role], role))
            if role in style:
                style[role] = color(style[role], role)
        if element.tag.rsplit("}", 1)[-1] == "style" and element.text:
            element.text = re.sub(
                r"(fill|stroke|stop-color)\s*:\s*([^;}]+)",
                lambda match: f"{match[1]}:{color(match[2], match[1])}",
                element.text,
            )
        border = number(look.get("stroke_width", -1))
        if border >= 0 and ("stroke" in element.attrib or "stroke" in style):
            element.set("stroke-width", str(border))
            style.pop("stroke-width", None)
        if style:
            element.set("style", ";".join(f"{k}:{v}" for k, v in style.items()))
    return ET.tostring(root)


def paint_changed(look: Mapping[str, Any]) -> bool:
    """Avoid rerasterizing neutral PNG palettes during ordinary bone animation."""
    return bool(
        look.get("shape")
        or look.get("tint", {}).get("amount", 0)
        or look.get("stroke_width", -1) >= 0
        or any(
            tuple(p.get(k) for k in ("r", "g", "b")) != rgb(p.get("source", ""))
            for p in look.get("palette", ())
        )
    )
