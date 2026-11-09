"""Display-only vector outlines for the replaceable bone silhouette, independent of Qt."""

import base64
import math
import re
from functools import lru_cache
from xml.etree import ElementTree

from rigora.resources import asset_path

_GRAPHICS = {"path", "circle", "ellipse", "rect", "polygon", "polyline", "line", "use"}
_BONE_USE = re.compile(r'<use href="#bone-source" transform="matrix\(([^)]+)\)"([^>]*)/>')


@lru_cache(maxsize=128)
def outline_svg(data: bytes, color: str, width: float) -> bytes:
    """Trace original SVG geometry, expanding its viewport so cosmetic strokes cannot clip."""
    tree = ElementTree.fromstring(data)
    box = tree.get("viewBox", "0 0 1024 1536")
    x, y, w, h = (float(value) for value in box.replace(",", " ").split())
    padding = width / 2 + 2
    tree.set("viewBox", f"{x - padding} {y - padding} {w + padding * 2} {h + padding * 2}")
    tree.set("width", str(w + padding * 2))
    tree.set("height", str(h + padding * 2))
    for element in tree.iter():
        if element.tag.rsplit("}", 1)[-1] in _GRAPHICS:
            element.set("fill", "none")
            element.set("stroke", color)
            element.set("stroke-width", str(width))
            element.set("stroke-linejoin", "round")
            element.set("stroke-linecap", "round")
    return ElementTree.tostring(tree)


def outlined_bone_uses(source: str, pixels_per_unit: float) -> str:
    """Give generated poster bones legible outlines at their actual final vector resolution."""
    definitions: list[str] = []
    original = asset_path("shapes/bone.svg").read_bytes()

    def replace_use(match: re.Match[str]) -> str:
        """Trace each placed silhouette using a constant output-pixel border thickness."""
        values = [float(value) for value in match[1].split()]
        scale = max(1e-6, min(math.hypot(*values[:2]), math.hypot(*values[2:4])) * pixels_per_unit)
        outlines = []
        for color, pixels in (("#eeeeee", 8.0), ("#202020", 5.0)):
            data = outline_svg(original, color, round(pixels / scale, 1))
            box = ElementTree.fromstring(data).attrib["viewBox"].split()
            key = f"bone-outline-{len(definitions)}"
            encoded = base64.b64encode(data).decode("ascii")
            definitions.append(
                f'<image id="{key}" x="{box[0]}" y="{box[1]}" '
                f'width="{box[2]}" height="{box[3]}" '
                f'href="data:image/svg+xml;base64,{encoded}"/>'
            )
            outlines.append(f'<use href="#{key}" transform="matrix({match[1]})"{match[2]}/>')
        return "".join(outlines) + match[0]

    result = _BONE_USE.sub(replace_use, source)
    return result.replace("</defs>", "".join(definitions) + "</defs>", 1)
