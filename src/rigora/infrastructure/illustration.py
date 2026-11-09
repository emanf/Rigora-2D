"""Original SVG stick artwork with independent, replaceable bone-bound parts.

Artwork remains vector geometry throughout authoring and deformation. Raster
posters are disposable cache derivatives, never a character's source artwork.
"""

import re
from dataclasses import dataclass, replace

from rigora.domain.character_recipe import CharacterRecipe
from rigora.domain.creator_options import (
    CLOTHING_PAINTS,
    default_choice,
    retain_outfit_sets,
    retained_choices,
)
from rigora.domain.illustration_catalog import Design, customized_design
from rigora.infrastructure.illustration_hands import hand_placement
from rigora.infrastructure.illustration_motion import Joint, Point, offset, world_joints

VISEMES = ("Rest", "AI", "E", "O", "U", "FV", "L", "MBP", "WQ", "TH")


@dataclass(frozen=True)
class ArtPart:
    """Own vector bounds, a bind bone, draw order and optional wardrobe membership."""

    name: str
    bone: str
    markup: str
    bounds: tuple[float, float, float, float]
    layer: int
    family: str = ""
    variant: str = ""
    visible: bool = True


def svg(markup: str, bounds: tuple[float, float, float, float]) -> bytes:
    """Wrap source-space geometry without changing its anatomical coordinates."""
    x, y, w, h = bounds
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="{x} {y} {w} {h}">{markup}</svg>'
    ).encode()


def path(data: str, fill: str, ink: str = "none", width: float = 1.2) -> str:
    """Draw a closed shape or rounded stroke with no artificial joint seams."""
    return (
        f'<path d="{data}" fill="{fill}" stroke="{ink}" stroke-width="{width}" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
    )


def ellipse(
    x: float, y: float, rx: float, ry: float, fill: str, ink: str = "none", width: float = 1.2
) -> str:
    """Draw an oval using independent fill and line paints."""
    return (
        f'<ellipse cx="{x}" cy="{y}" rx="{rx}" ry="{ry}" fill="{fill}" '
        f'stroke="{ink}" stroke-width="{width}"/>'
    )


def segment(a: Point, b: Point, width: float, fill: str, ink: str = "none") -> str:
    """Overlap rounded ends at a joint without outlining the attachment edge."""
    line = f"M {a[0]} {a[1]} L {b[0]} {b[1]}"
    return (path(line, "none", ink, width + 2) if ink != "none" else "") + path(
        line, "none", fill, width
    )


def open_sleeve(
    a: Point,
    b: Point,
    width: float,
    fill: str,
    ink: str,
    *,
    open_end: bool = False,
    taper_root: bool = False,
) -> str:
    """Outline a sleeve's sides and hem while leaving its root attachment unlined."""
    from math import hypot

    dx, dy = b[0] - a[0], b[1] - a[1]
    length = max(0.001, hypot(dx, dy))
    nx, ny = -dy / length * width / 2, dx / length * width / 2
    x1, y1, x2, y2 = a[0] + nx, a[1] + ny, a[0] - nx, a[1] - ny
    x3, y3, x4, y4 = b[0] + nx, b[1] + ny, b[0] - nx, b[1] - ny
    art = path(f"M {x1} {y1} L {x3} {y3} L {x4} {y4} L {x2} {y2} Z", fill)
    if taper_root:
        blend = min(width, length * 0.3)
        cx, cy = a[0] + dx / length * blend, a[1] + dy / length * blend
        x1, y1, x2, y2 = cx + nx, cy + ny, cx - nx, cy - ny
        art = path(
            f"M {a[0]} {a[1]} Q {x1} {y1} {x1} {y1} "
            f"L {x3} {y3} L {x4} {y4} L {x2} {y2} Q {x2} {y2} {a[0]} {a[1]} Z",
            fill,
        )
    if open_end:
        art += ellipse(*b, width / 2, width / 2, fill)
    outline = f"M {x1} {y1} L {x3} {y3} M {x2} {y2} L {x4} {y4}"
    if not open_end:
        outline += f" M {x3} {y3} L {x4} {y4}"
    return art + path(outline, "none", ink, 1.2)


def mouth_art(shape: str, style: str = "Soft", ink: str = "#30363d") -> bytes:
    """Render ten compatible visemes on one common registration sheet."""
    width = 1.8 if style == "Soft" else 2.5 if style == "Graphic" else 1.2
    if shape in ("Rest", "MBP"):
        data = "M 10 18 Q 32 30 54 18" if shape == "Rest" else "M 10 21 Q 32 18 54 21"
        art = path(data, "none", ink, width)
    else:
        rx, ry = {
            "AI": (22, 16),
            "E": (24, 9),
            "O": (14, 17),
            "U": (10, 12),
            "FV": (22, 7),
            "L": (21, 12),
            "WQ": (9, 13),
            "TH": (20, 9),
        }[shape]
        art = ellipse(32, 20, rx, ry, ink)
        if shape in ("AI", "E", "FV", "L", "TH"):
            art += path(
                f"M {32 - rx * 0.8} {20 - ry * 0.55} Q 32 {20 - ry * 0.24} "
                f"{32 + rx * 0.8} {20 - ry * 0.55} L {32 + rx * 0.7} {20 - ry * 0.05} "
                f"Q 32 {20 + ry * 0.2} {32 - rx * 0.7} {20 - ry * 0.05} Z",
                "#fff9ef",
            )
        if shape in ("AI", "L", "TH"):
            art += ellipse(34, 20 + ry * 0.52, rx * 0.48, ry * 0.3, "#cc8b88")
    if style == "Ink":
        art = '<g transform="rotate(-3 32 20)">' + art + "</g>"
    elif style == "Graphic":
        art += path("M 7 16 Q 5 20 7 23 M 57 16 Q 59 20 57 23", "none", ink, 1)
    elif style == "Small":
        art = '<g transform="translate(8 5) scale(.75)">' + art + "</g>"
    elif style == "Wide":
        art = '<g transform="translate(-5 4) scale(1.16 .8)">' + art + "</g>"
    elif style == "Round" and shape == "Rest":
        art = path("M 20 17 Q 32 34 44 17", "none", ink, 2.2)
    elif style == "Toon" and shape == "Rest":
        art = path("M 8 14 Q 32 28 56 14 Q 32 50 8 14 Z", ink)
        art += path("M 16 18 Q 32 25 48 18 L 44 25 Q 32 30 20 25 Z", "#fff9ef")
    elif style == "Teeth" and shape == "Rest":
        art = path("M 8 16 Q 32 24 56 16 Q 32 43 8 16 Z", "#fff9ef", ink, 1.4)
        art += path("M 15 23 Q 32 29 49 23 M 25 21 L 25 30 M 38 21 L 38 30", "none", ink, 0.7)
    elif style == "Fangs" and shape != "MBP":
        if shape == "Rest":
            art = path("M 10 16 Q 32 25 54 16 Q 32 41 10 16 Z", ink)
        art += path("M 17 18 L 21 28 L 25 20 Z M 40 20 L 44 28 L 48 18 Z", "#fff9ef")
    return svg(art, (0, 0, 64, 40))


def face_component(name: str) -> bytes:
    """Supply vector parts to the standalone facial editor without bundled bitmap art."""
    if name in VISEMES:
        return mouth_art(name)
    art = (
        ellipse(32, 20, 24, 15, "#f7f1e8")
        if name == "eye"
        else ellipse(32, 20, 6, 9, "#30363d")
        if name == "pupil"
        else path("M 9 23 Q 31 8 55 20", "none", "#30363d", 4)
    )
    return svg(art, (0, 0, 64, 40))


def hand_art(
    near: bool,
    pose: str,
    paint: str,
    width: float,
    fill: str = "#ffffff",
    *,
    palm: bool = True,
    side: str = "R",
) -> str:
    """Draw a wrist-registered glove with independent reflection and visible surface."""
    from rigora.infrastructure.illustration_hands import glove_art

    return glove_art(near, pose, paint, width, fill, palm=palm, side=side)


def stick_person(recipe: CharacterRecipe, d: Design, joints: dict[str, Joint]) -> list[ArtPart]:
    """Assemble a stick person with registered clothing, face, hair and hand choices."""
    c = {**d.colors, **recipe.colors}
    ink, skin, hair = c["Ink"], c["Skin"], c["Hair"]
    width = recipe.stroke_width
    if recipe.style == "Outline":
        width *= 0.82
    parts: list[ArtPart] = []

    def add(
        name: str,
        bone: str,
        art: str,
        bounds: tuple[float, float, float, float],
        layer: int,
        family: str = "",
        variant: str = "",
        visible: bool = True,
    ) -> None:
        """Register one bound vector layer with its variant membership and draw order."""
        if (
            recipe.style == "Sketch"
            and family != "Hands"
            and not name.startswith(("Eye", "Brow", "Mouth"))
        ):
            art = '<g opacity=".18" transform="translate(.8 -.6)">' + art + "</g>" + art
        parts.append(ArtPart(name, bone, art, bounds, layer, family, variant, visible))

    def line(
        name: str,
        bone: str,
        size: float,
        paint: str,
        layer: int,
        family: str = "",
        variant: str = "",
        visible: bool = True,
        fraction: float = 1,
        outlined: bool = False,
        open_end: bool = False,
    ) -> None:
        j = joints[bone]
        socket = bone.startswith("upper_arm.")
        root = offset(j.root, j.angle, -(width / 2 + 1.5)) if outlined and not socket else j.root
        tip = offset(j.root, j.angle, j.length * fraction)
        if outlined and open_end:
            tip = offset(tip, j.angle, width / 2)
        pad = size / 2 + 2
        bounds = (
            min(root[0], tip[0]) - pad,
            min(root[1], tip[1]) - pad,
            abs(root[0] - tip[0]) + 2 * pad,
            abs(root[1] - tip[1]) + 2 * pad,
        )
        art = (
            open_sleeve(root, tip, size, paint, ink, open_end=open_end, taper_root=socket)
            if outlined
            else segment(offset(j.root, j.angle, size / 2) if socket else j.root, tip, size, paint)
        )
        add(name, bone, art, bounds, layer, family, variant, visible)

    hips, shoulder = joints["hips"].root, joints["spine"].tip
    cx, cy = joints["head"].root[0], joints["head"].root[1] - d.head
    back = recipe.view in ("Back", "Back 3/4")
    profile = recipe.view == "Side"
    quarter = recipe.view in ("Front 3/4", "Back 3/4")
    turned = profile or quarter
    rx, ry = d.head * (0.79 if profile else 1), d.head
    if recipe.head_shape == "Oval":
        rx *= 0.85
        ry *= 1.08
    head_bounds = (cx - rx - 3, cy - ry - 3, rx * 2 + 6, ry * 2 + 6)
    for i, side in enumerate(("R", "L")):
        near = i == 0
        layer = 40 if near else 4
        for label, bone in (("Thigh", "thigh."), ("Shin", "shin.")):
            paint = c["Bottom"] if recipe.style == "Color" else ink
            line(label + " " + side, bone + side, width, paint, 12 if near else 8)
        line("Upper arm " + side, "upper_arm." + side, width, ink, layer)
        line("Forearm " + side, "forearm." + side, width * 0.86, ink, layer)
        hand = joints["hand." + side]
        for pose in retained_choices(recipe, "Hands"):
            hand_color = str(recipe.garment_colors.get("Hands/" + pose, "#ffffff"))
            source_side, orientation = hand_placement(
                recipe.view,
                pose,
                side,
                recipe.hand_flips.get(recipe.view, {}).get("left" if near else "right", False),
            )
            art = hand_art(
                orientation,
                pose,
                ink,
                width,
                hand_color,
                palm=not (turned and near),
                side=source_side,
            )
            art = (
                f'<g transform="translate({hand.root[0]} {hand.root[1]}) '
                f'rotate({hand.angle - 90})">{art}</g>'
            )
            add(
                "Hand " + side + " · " + pose,
                "hand." + side,
                art,
                (hand.root[0] - 28, hand.root[1] - 28, 56, 56),
                layer + 1,
                "Hands",
                pose,
                pose == default_choice(recipe, "Hands"),
            )
    line("Neck", "neck", width, ink, 28)
    garment = default_choice(recipe, "Clothing")
    retained = retained_choices(recipe, "Clothing")
    sx, sy = shoulder
    hw = d.width * (0.25 if profile else 0.34)
    # Broad cubic spans create a stable hand-drawn contour, without random
    # per-frame displacement or a second displaced outline.
    irregularity = 0.04 * d.phase
    torso = (
        f"M {sx - hw * 0.62} {sy + 1} "
        f"C {sx - hw * 0.95} {sy} {sx - hw * 1.04} {sy + 6} {sx - hw * 1.02} {sy + 14} "
        f"C {sx - hw * (0.9 + irregularity)} {sy + d.body * 0.36} "
        f"{sx - hw * 1.08} {sy + d.body * 0.68} {sx - hw * 0.94} {hips[1] - 2} "
        f"Q {sx - hw * 0.9} {hips[1] + 7} {sx - hw * 0.6} {hips[1] + 7} "
        f"C {sx - hw * 0.08} {hips[1] + 10} {sx + hw * 0.44} {hips[1] + 8} "
        f"{sx + hw * 0.72} {hips[1] + 6} "
        f"Q {sx + hw * 1.05} {hips[1] + 4} {sx + hw * 0.98} {hips[1] - 3} "
        f"C {sx + hw * 0.83} {sy + d.body * 0.66} {sx + hw * (1.06 - irregularity)} "
        f"{sy + d.body * 0.4} {sx + hw * 0.94} {sy + 10} "
        f"Q {sx + hw * 0.9} {sy - 1} {sx + hw * 0.57} {sy + 1} "
        f"Q {sx + hw * 0.05} {sy - 2} {sx - hw * 0.62} {sy + 1} Z"
    )
    body_bounds = (sx - hw * 1.15 - 3, sy - 4, hw * 2.3 + 6, d.body + 18)
    if recipe.body_shape == "Simple":
        line("Body", "spine", width * 1.2, ink, 20)
    else:
        add("Body", "spine", path(torso, skin, ink, max(1.6, width * 0.55)), body_bounds, 20)
    for name in sorted(retained):
        from rigora.infrastructure.illustration_clothes import LONG_SLEEVES, extra_top

        visible = name == garment
        paint = recipe.garment_colors.get(
            "Clothing/" + name,
            recipe.garment_colors.get(name, CLOTHING_PAINTS.get(name, c["Top"])),
        )
        if not isinstance(paint, str):
            paint = c["Top"]
        art = "<g/>" if name == "none" else path(torso, paint, ink, 1.2)
        if name in ("jacket", "overshirt", "suit jacket", "waistcoat", "coat"):
            art += path(
                f"M {sx - hw * 0.4} {sy + 1} L {sx} {sy + 24} L {sx + hw * 0.4} {sy + 1} Z",
                c["Accent"],
            )
            art += path(f"M {sx} {sy + 24} L {sx} {hips[1] + 2}", "none", ink, 1)
        elif name == "hoodie":
            art += path(
                f"M {sx - hw * 0.5} {sy + 8} Q {sx} {sy + 20} {sx + hw * 0.5} {sy + 8} "
                f"M {sx - 3} {sy + 14} L {sx - 4} {sy + 30} "
                f"M {sx + 3} {sy + 14} L {sx + 4} {sy + 28}",
                "none",
                c["Accent"],
                1.3,
            )
        elif name == "sport":
            art += path(
                f"M {sx - hw * 0.8} {sy + 24} L {sx + hw * 0.8} {sy + 42}", "none", c["Accent"], 4
            )
        elif name == "dungarees":
            art += path(
                f"M {sx - hw * 0.65} {sy + 5} L {sx - hw * 0.6} {sy + 32} "
                f"L {sx + hw * 0.6} {sy + 32} L {sx + hw * 0.65} {sy + 5}",
                "none",
                c["Bottom"],
                4,
            )
        if name == "shirt":
            art += path(
                f"M {sx - 8} {sy + 2} L {sx - 3} {sy + 14} L {sx} {sy + 7} "
                f"L {sx + 3} {sy + 14} L {sx + 8} {sy + 2}",
                "none",
                ink,
                0.9,
            )
            art += "".join(ellipse(sx, sy + 24 + i * 13, 1, 1, ink) for i in range(4))
        elif name == "jacket":
            art += path(
                f"M {sx - hw * 0.7} {hips[1] - 22} L {sx - hw * 0.25} {hips[1] - 19}",
                "none",
                c["Accent"],
                1.8,
            )
        elif name == "overshirt":
            for sign in (-1, 1):
                x, y = sx + sign * hw * 0.55, sy + 29
                art += path(
                    f"M {x - 4} {y} L {x + 4} {y} L {x + 4} {y + 12} "
                    f"Q {x} {y + 16} {x - 4} {y + 12} Z",
                    "none",
                    ink,
                    0.9,
                )
                art += path(f"M {x - 4} {y + 3} L {x + 4} {y + 3}", "none", ink, 0.7)
        elif name == "suit jacket":
            art += path(
                f"M {sx - hw * 0.5} {sy + 5} L {sx - hw * 0.2} {sy + 28} L {sx - 2} {sy + 35} "
                f"M {sx + hw * 0.5} {sy + 5} L {sx + hw * 0.2} {sy + 28} L {sx + 2} {sy + 35} "
                f"M {sx + hw * 0.3} {sy + 31} L {sx + hw * 0.75} {sy + 30}",
                "none",
                ink,
                0.9,
            )
            art += ellipse(sx + 3, sy + d.body * 0.65, 1.6, 1.6, c["Accent"], ink, 0.5)
        elif name == "waistcoat":
            art += path(
                f"M {sx - hw * 0.45} {sy} L {sx} {sy + 34} L {sx + hw * 0.45} {sy}",
                "none",
                ink,
                1.1,
            )
            art += "".join(
                ellipse(sx + 2, sy + 42 + i * 10, 1.2, 1.2, c["Accent"], ink, 0.5) for i in range(3)
            )
        elif name == "coat":
            art += "".join(
                ellipse(sx + sign * 5, sy + 31 + i * 14, 1.7, 1.7, c["Accent"], ink, 0.5)
                for sign in (-1, 1)
                for i in range(3)
            )
            coat_hem = path(
                f"M {hips[0] - hw * 0.9} {hips[1] - 5} L {hips[0] + hw * 0.9} {hips[1] - 5} "
                f"L {hips[0] + hw * 1.25} {hips[1] + d.leg * 0.55} "
                f"L {hips[0] + 3} {hips[1] + d.leg * 0.55 - 4} L {hips[0]} {hips[1] + 7} "
                f"L {hips[0] - 3} {hips[1] + d.leg * 0.55 - 4} "
                f"L {hips[0] - hw * 1.25} {hips[1] + d.leg * 0.55} Z",
                paint,
                ink,
                1.2,
            )
            add(
                "Coat hem",
                "cloth",
                coat_hem,
                (hips[0] - hw * 1.4, hips[1] - 8, hw * 2.8, d.leg * 0.55 + 15),
                26,
                "Clothing",
                name,
                visible,
            )
        if name == "shell":
            art = path(torso, c["Top"], ink, 2)
            art += ellipse(sx, sy + d.body * 0.5, 6, 6, c["Accent"], ink)
        additional = extra_top(name, sx, sy, hw, d.body, paint, ink, c["Accent"], back=back)
        if additional is not None:
            art = additional
        if name in ("robe", "raincoat"):
            hx, hy = hips
            length = d.leg * (0.9 if name == "robe" else 0.65)
            hem = path(
                f"M {hx - hw * 0.94} {hy - 3} L {hx + hw * 0.94} {hy - 3} "
                f"L {hx + hw * 1.4} {hy + length} Q {hx} {hy + length + 5} "
                f"{hx - hw * 1.4} {hy + length} Z",
                paint,
            )
            hem += path(
                f"M {hx - hw * 0.94} {hy} L {hx - hw * 1.4} {hy + length} "
                f"Q {hx} {hy + length + 5} {hx + hw * 1.4} {hy + length} "
                f"L {hx + hw * 0.94} {hy}",
                "none",
                ink,
                1.2,
            )
            add(
                "Hem · " + name,
                "cloth",
                hem,
                (hx - hw * 1.5, hy - 5, hw * 3, length + 12),
                24,
                "Clothing",
                name,
                visible,
            )
        add(
            "Clothing · " + name,
            "spine",
            art,
            (sx - hw - 4, sy - 6, hw * 2 + 8, d.body + 19),
            25,
            "Clothing",
            name,
            visible,
        )
        if name not in ("none", "dress", "long dress", "shell", "waistcoat", "tank top"):
            for i, side in enumerate(("R", "L")):
                line(
                    "Sleeve " + side + " · " + name,
                    "upper_arm." + side,
                    width * 1.55,
                    paint,
                    42 if i == 0 else 5,
                    "Clothing",
                    name,
                    visible,
                    1 if name in LONG_SLEEVES else 0.38,
                    outlined=True,
                    open_end=name in LONG_SLEEVES,
                )
                if name in LONG_SLEEVES:
                    line(
                        "Cuff " + side + " · " + name,
                        "forearm." + side,
                        width * 1.7,
                        paint,
                        43 if i == 0 else 6,
                        "Clothing",
                        name,
                        visible,
                        1.02,
                        outlined=True,
                    )
                    cuff = joints["forearm." + side]
                    a = offset(cuff.root, cuff.angle, cuff.length * 0.71)
                    b = offset(cuff.root, cuff.angle, cuff.length * 0.99)
                    size = max(13.5, width * 2.8)
                    pad = size / 2 + 2
                    add(
                        "Sleeve cover " + side + " · " + name,
                        "forearm." + side,
                        open_sleeve(a, b, size, paint, ink),
                        (
                            min(a[0], b[0]) - pad,
                            min(a[1], b[1]) - pad,
                            abs(a[0] - b[0]) + pad * 2,
                            abs(a[1] - b[1]) + pad * 2,
                        ),
                        43 if i == 0 else 6,
                        "Clothing",
                        name,
                        visible,
                    )
        if name in ("dress", "long dress"):
            hx, hy = hips
            length = d.leg * (1.82 if name == "long dress" else 1.4)
            art = path(
                f"M {hx - hw * 0.8} {hy - 4} Q {hx - hw * 1.3} {hy + length * 0.6} "
                f"{hx - hw * 2.0} {hy + length} Q {hx} {hy + length + 8} "
                f"{hx + hw * 2.0} {hy + length} Q {hx + hw * 1.3} {hy + length * 0.6} "
                f"{hx + hw * 0.8} {hy - 4} Z",
                paint,
                ink,
                1.2,
            )
            art += path(f"M {hx - hw * 0.8} {hy} L {hx + hw * 0.8} {hy}", "none", c["Accent"], 3)
            add(
                "Skirt · " + name,
                "cloth",
                art,
                (hx - hw * 2.2, hy - 7, hw * 4.4, length + 18),
                26,
                "Clothing",
                name,
                visible,
            )
        if name != "none" and recipe.layer_modes.get("Clothing") == "Front panels":
            panel = (
                f"M {sx - hw * 0.85} {sy + 6} L {sx - hw * 0.38} {sy + 10} "
                f"L {sx - hw * 0.23} {hips[1] + 5} L {sx - hw * 0.9} {hips[1] + 5} Z "
                f"M {sx + hw * 0.85} {sy + 6} L {sx + hw * 0.38} {sy + 10} "
                f"L {sx + hw * 0.23} {hips[1] + 5} L {sx + hw * 0.9} {hips[1] + 5} Z"
            )
            add(
                "Front panels · " + name,
                "spine",
                path(panel, paint, ink, 1),
                body_bounds,
                38,
                "Clothing",
                name,
                visible,
            )
    if recipe.head_shape == "Soft square" or d.anatomy == "robot":
        art = (
            f'<rect x="{cx - rx}" y="{cy - ry}" width="{rx * 2}" height="{ry * 2}" '
            f'rx="{rx * 0.48}" fill="{skin}" stroke="{ink}" stroke-width="2.2"/>'
        )
    else:
        art = ellipse(cx, cy, rx, ry, skin, ink, 2.2)
    add("Head", "head", art, head_bounds, 50)
    if d.anatomy == "robot" and not back:
        art = path(
            f"M {cx - rx * 0.7} {cy - 8} Q {cx} {cy - 14} {cx + rx * 0.7} {cy - 8} "
            f"L {cx + rx * 0.7} {cy + 8} Q {cx} {cy + 15} {cx - rx * 0.7} {cy + 8} Z",
            c["Hair"],
        )
        add("Visor", "head", art, (cx - rx, cy - 17, rx * 2, 36), 53)
    if not back:
        eye_shape = recipe.parts.get("Eyes", d.eye)
        for i, side in enumerate(("R", "L")):
            near = i == 1
            if profile and not near:
                continue
            ex = (
                cx
                + (0.27 if profile else -0.25 if near else 0.35) * rx
                + (0.12 * rx if quarter else 0)
            )
            ey = cy - ry * 0.05
            size = d.head * (0.065 if eye_shape == "dot" else 0.11)
            size *= 0.76 if quarter and not near else 1
            blink = recipe.poses.get("Eyes") == "Blink" or recipe.feeling == "Sleepy"
            blink |= recipe.poses.get("Eyes") == "Wink" and near
            art = (
                path(
                    f"M {ex - size * 1.3} {ey} Q {ex} {ey + size} {ex + size * 1.3} {ey}",
                    "none",
                    ink,
                    1.6,
                )
                if blink
                else ellipse(ex, ey, size, size * 1.6, c["Accent"] if d.anatomy == "robot" else ink)
            )
            if eye_shape != "dot" and not blink:
                art += ellipse(ex - size * 0.2, ey - size * 0.6, size * 0.3, size * 0.4, "#fffaf2")
            if not blink and eye_shape in (
                "anime",
                "lashes",
                "round",
                "narrow",
                "sleepy",
                "happy",
                "robot",
            ):
                if eye_shape == "happy":
                    art = path(
                        f"M {ex - size * 1.8} {ey + size * 0.5} Q {ex} {ey - size * 2} "
                        f"{ex + size * 1.8} {ey + size * 0.5}",
                        "none",
                        ink,
                        1.5,
                    )
                elif eye_shape == "robot":
                    art = (
                        f'<rect x="{ex - size}" y="{ey - size * 1.2}" width="{size * 2}" '
                        f'height="{size * 2.4}" rx="1" fill="{ink}"/>'
                    )
                    art += path(
                        f"M {ex - size * 0.4} {ey - size * 0.6} "
                        f"L {ex + size * 0.4} {ey - size * 0.6}",
                        "none",
                        c["Accent"],
                        0.8,
                    )
                else:
                    erx = size * (1.8 if eye_shape != "round" else 1.3)
                    ery = size * (0.65 if eye_shape in ("narrow", "sleepy") else 1.3)
                    art = ellipse(ex, ey, erx, ery, "#fffaf2", ink, 0.9)
                    art += ellipse(ex + size * 0.12, ey, size * 0.65, ery * 0.85, ink)
                    if eye_shape in ("anime", "lashes"):
                        art += path(
                            f"M {ex - erx} {ey} Q {ex} {ey - ery * 1.8} {ex + erx} {ey}",
                            "none",
                            ink,
                            1.5,
                        )
                    if eye_shape == "lashes":
                        art += path(
                            f"M {ex - erx * 0.6} {ey - ery} L {ex - erx * 0.9} {ey - ery * 1.7} "
                            f"M {ex + erx * 0.6} {ey - ery} L {ex + erx * 0.9} {ey - ery * 1.7}",
                            "none",
                            ink,
                            0.8,
                        )
                    if eye_shape == "sleepy":
                        art += path(
                            f"M {ex - erx} {ey - ery * 0.25} L {ex + erx} {ey - ery * 0.25}",
                            "none",
                            ink,
                            1.1,
                        )
            if not blink:
                from rigora.infrastructure.illustration_face_styles import extra_eye

                extra = extra_eye(eye_shape, ink)
                if extra is not None:
                    art = f'<g transform="translate({ex} {ey}) scale({size})">{extra}</g>'
            add(
                "Eye " + side,
                "head",
                art,
                (ex - size * 2, ey - size * 2, size * 4, size * 4),
                64 if near else 60,
            )
            slope = (
                (-3 if near else 3)
                if recipe.feeling == "Angry"
                else ((3 if near else -3) if recipe.feeling == "Sad" else 0)
            )
            by = ey - size * 3
            art = path(
                f"M {ex - size * 1.5} {by + slope} Q {ex} {by - 1} {ex + size * 1.5} {by - slope}",
                "none",
                hair,
                1.4,
            )
            add("Brow " + side, "head", art, (ex - size * 2, by - 6, size * 4, 12), 65)
        nx, ny = cx + rx * (0.60 if profile else 0.24 if quarter else 0), cy + ry * 0.18
        if (nose := recipe.parts.get("Nose", "None")) != "None":
            from rigora.infrastructure.illustration_face_styles import nose_art

            unit = ry / 29
            add(
                "Nose",
                "head",
                f'<g transform="translate({nx} {ny}) scale({unit})">'
                + nose_art(nose, ink, skin)
                + "</g>",
                (nx - 9 * unit, ny - 8 * unit, 18 * unit, 20 * unit),
                62,
            )
        for style in retained_choices(recipe, "Mouth"):
            for shape in VISEMES:
                source = (
                    mouth_art(shape, style, str(recipe.garment_colors.get("Mouth/" + style, ink)))
                    .decode()
                    .split(">", 1)[1]
                    .rsplit("</svg>", 1)[0]
                )
                mw = d.head * (0.49 if profile else 0.72)
                mx, my = nx - mw * 0.5, cy + ry * 0.37
                art = f'<g transform="translate({mx} {my}) scale({mw / 64})">{source}</g>'
                if recipe.feeling == "Sad" and shape == "Rest":
                    art = path(
                        f"M {mx + 2} {my + 6} Q {mx + mw * 0.5} {my - 2} {mx + mw - 2} {my + 6}",
                        "none",
                        ink,
                        1.2,
                    )
                selected = {"Happy": "E", "Surprised": "O", "Angry": "MBP"}.get(
                    recipe.feeling, recipe.mouth_pose
                )
                add(
                    "Mouth · " + style + " · " + shape,
                    "head",
                    art,
                    (mx - 2, my - 2, mw + 4, mw * 40 / 64 + 4),
                    66,
                    "Mouth style",
                    style,
                    style == recipe.mouth_style and shape == selected,
                )
        facial_hair(recipe, nx, cy, rx, ry, hair, add, head_center=cx)
    head_hair(recipe, d, joints, cx, cy, rx, ry, c, add)
    return parts


def facial_hair(
    recipe: CharacterRecipe,
    cx: float,
    cy: float,
    rx: float,
    ry: float,
    paint: str,
    add: object,
    *,
    head_center: float | None = None,
) -> None:
    """Anchor facial hair to the projected mouth center and scale it with the head."""
    from typing import Any, cast

    from rigora.infrastructure.illustration_face_styles import beard_art, extra_mustache

    emit = cast(Any, add)
    unit = ry / 58
    projection = 0.58 if recipe.view == "Side" else 0.88 if recipe.view == "Front 3/4" else 1
    name = recipe.parts.get("Mustache", "None")
    if name != "None":
        x, y, w = cx, cy + ry * 0.39, rx * 0.38 * projection
        data = (
            f"M {x - w} {y} Q {x} {y - 5 * unit} {x + w} {y}"
            if name == "Pencil"
            else f"M {x - w} {y + unit} Q {x - w * 1.6} {y - 9 * unit} "
            f"{x - w * 0.5} {y - 4 * unit} Q {x} {y - 7 * unit} "
            f"{x + w * 0.5} {y - 4 * unit} Q {x + w * 1.6} {y - 9 * unit} {x + w} {y + unit}"
            if name == "Handlebar"
            else f"M {x - w} {y + 2 * unit} L {x - w * 0.4} {y - 6 * unit} "
            f"Q {x} {y - 8 * unit} {x + w * 0.4} {y - 6 * unit} "
            f"L {x + w} {y + 2 * unit} Q {x} {y - unit} {x - w} {y + 2 * unit} Z"
        )
        extra = extra_mustache(name, w, ry, paint)
        art = (
            f'<g transform="translate({x} {y})">{extra}</g>'
            if extra is not None
            else path(
                data,
                "none" if name != "Chevron" else paint,
                paint,
                (1.8 if name == "Pencil" else 3) * unit * 2,
            )
        )
        emit(
            "Mustache",
            "head",
            art,
            (x - w * 1.9, y - ry * 0.35, w * 3.8, ry * 0.95),
            61,
        )
    name = recipe.parts.get("Beard", "None")
    if name != "None":
        if name in ("Stubble", "Chinstrap") and head_center is not None:
            cx = head_center + (rx * 0.15 if recipe.view == "Side" else 0)
        y = cy + ry * 0.79
        art, w, height = beard_art(name, rx * 0.62 * projection, ry, paint)
        emit(
            "Beard",
            "head",
            f'<g transform="translate({cx} {y})">{art}</g>',
            (cx - w - 2, y - ry * 0.6, w * 2 + 4, height + ry * 0.65),
            63 if name == "Stubble" else 67,
        )


def head_hair(
    recipe: CharacterRecipe,
    d: Design,
    joints: dict[str, Joint],
    cx: float,
    cy: float,
    rx: float,
    ry: float,
    c: dict[str, str],
    add: object,
) -> None:
    """Keep the fitted cap on the head; only loose locks use secondary-motion bones."""
    from typing import Any, cast

    emit = cast(Any, add)
    name = recipe.parts.get("Hair", d.hair)
    if name == "none":
        return
    from rigora.infrastructure.illustration_hair import (
        HAIRSTYLES,
        SPRIG_STYLES,
        hair_shapes,
        sprig_art,
    )

    if name in SPRIG_STYLES:
        art = sprig_art(name, c["Hair"])
        emit(
            "Hair sprigs",
            "head",
            f'<g transform="translate({cx} {cy}) scale({rx} {ry})">{art}</g>',
            (cx - rx, cy - ry * 1.9, rx * 2, ry * 1.1),
            72,
            "Hair",
            name,
        )
        return

    if name in HAIRSTYLES:
        cap, loose = hair_shapes(name, c["Hair"], c["Accent"], recipe.view in ("Back", "Back 3/4"))
        for label, bone, art, layer in (
            ("Hair cap", "head", cap, 71),
            (
                "Hair loose",
                "hair.front"
                if name in ("spring curl", "double curl", "side curl")
                else "hair.back",
                loose,
                72 if name in ("spring curl", "double curl", "side curl") else 17,
            ),
        ):
            if art:
                emit(
                    label,
                    bone,
                    f'<g transform="translate({cx} {cy}) scale({rx} {ry})">{art}</g>',
                    (cx - rx * 1.9, cy - ry * 2, rx * 3.8, ry * 3.6),
                    layer,
                    "Hair",
                    name,
                )
        return
    if name == "sprigs":
        art = path(
            f"M {cx - rx * 0.22} {cy - ry * 0.94} Q {cx - rx * 0.3} {cy - ry * 1.3} "
            f"{cx - rx * 0.52} {cy - ry * 1.32} "
            f"M {cx - rx * 0.1} {cy - ry} Q {cx + rx * 0.08} {cy - ry * 1.35} "
            f"{cx + rx * 0.35} {cy - ry * 1.4} "
            f"M {cx + rx * 0.09} {cy - ry * 0.98} Q {cx + rx * 0.4} {cy - ry * 1.3} "
            f"{cx + rx * 0.63} {cy - ry * 1.24}",
            "none",
            c["Hair"],
            1.5,
        )
        emit(
            "Hair sprigs",
            "head",
            art,
            (cx - rx * 0.7, cy - ry * 1.55, rx * 1.5, ry * 0.7),
            72,
            "Hair",
            name,
        )
        return
    if name in ("antenna", "orbit"):
        art = segment((cx, cy - ry), (cx + 4, cy - ry - 15), 3, c["Ink"])
        art += ellipse(cx + 4, cy - ry - 18, 4, 4, c["Accent"], c["Ink"])
        if name == "orbit":
            art = ellipse(cx, cy - ry * 1.15, rx * 1.15, ry * 0.16, "none", c["Accent"], 2.5)
            emit("Orbit halo", "head", art, (cx - rx * 1.4, cy - ry * 1.55, rx * 2.8, ry * 0.8), 72)
            return
        emit("Antenna", "head", art, (cx - 6, cy - ry - 25, 17, 30), 72)
        return
    cap = (
        f"M {cx - rx} {cy - ry * 0.15} C {cx - rx * 1.2} {cy - ry * 1.4} "
        f"{cx + rx * 1.2} {cy - ry * 1.4} {cx + rx} {cy - ry * 0.15} "
        f"Q {cx + rx * 0.7} {cy - ry * 0.8} {cx + rx * 0.5} {cy - ry * 0.65} "
        f"Q {cx - rx * 0.2} {cy - ry * 0.25} {cx - rx * 0.3} {cy - ry * 0.65} "
        f"Q {cx - rx * 0.6} {cy - ry * 0.25} {cx - rx} {cy - ry * 0.15} Z"
    )
    if name in ("sweep", "spikes", "quiff", "tuft"):
        cap = (
            f"M {cx - rx} {cy - ry * 0.2} Q {cx - rx * 1.1} {cy - ry} "
            f"{cx - rx * 0.45} {cy - ry * 1.2} "
            f"L {cx - rx * 0.12} {cy - ry * 1.5} L {cx + rx * 0.05} {cy - ry * 1.15} "
            f"Q {cx + rx * 0.8} {cy - ry * 1.4} {cx + rx} {cy - ry * 0.25} "
            f"L {cx + rx * 0.5} {cy - ry * 0.55} L {cx - rx * 0.4} {cy - ry * 0.65} Z"
        )
    if name == "spikes":
        cap = (
            f"M {cx - rx} {cy - ry * 0.15} L {cx - rx * 1.2} {cy - ry * 0.8} "
            f"L {cx - rx * 0.7} {cy - ry * 0.7} L {cx - rx * 0.5} {cy - ry * 1.4} "
            f"L {cx - rx * 0.1} {cy - ry} L {cx + rx * 0.25} {cy - ry * 1.4} "
            f"L {cx + rx * 0.5} {cy - ry * 0.9} L {cx + rx} {cy - ry * 1.1} "
            f"L {cx + rx * 0.9} {cy - ry * 0.15} Q {cx} {cy - ry * 0.7} "
            f"{cx - rx} {cy - ry * 0.15} Z"
        )
    elif name == "tuft":
        cap = (
            f"M {cx - rx * 0.7} {cy - ry * 0.75} Q {cx - rx * 0.4} {cy - ry * 1.1} "
            f"{cx - rx * 0.2} {cy - ry} "
            f"L {cx - rx * 0.1} {cy - ry * 1.45} L {cx + rx * 0.14} {cy - ry * 1.08} "
            f"Q {cx + rx * 0.6} {cy - ry * 1.32} {cx + rx * 0.7} {cy - ry * 0.8} "
            f"Q {cx} {cy - ry * 0.67} {cx - rx * 0.7} {cy - ry * 0.75} Z"
        )
    elif name == "sweep":
        cap = (
            f"M {cx - rx} {cy - ry * 0.2} C {cx - rx * 1.2} {cy - ry * 1.5} "
            f"{cx + rx * 0.8} {cy - ry * 1.3} {cx + rx} {cy - ry * 0.3} "
            f"Q {cx + rx * 0.25} {cy - ry * 0.95} {cx - rx * 0.4} {cy - ry * 0.4} Z"
        )
    elif name == "curls":
        import math

        cap = "".join(
            ellipse(
                cx + math.cos(i * math.pi / 9) * rx * 0.85,
                cy - ry * 0.2 - math.sin(i * math.pi / 9) * ry * 0.75,
                rx * 0.26,
                ry * 0.28,
                c["Hair"],
            )
            for i in range(10)
        )
    if recipe.view in ("Back", "Back 3/4"):
        cap = ""
        cap += ellipse(cx, cy, rx + 1, ry + 1, c["Hair"])
    emit(
        "Hair cap",
        "head",
        path(cap, c["Hair"]) if cap.startswith("M") else cap,
        (cx - rx * 1.25, cy - ry * 1.6, rx * 2.5, ry * 2.8),
        71,
        "Hair",
        name,
    )
    if name in ("ponytail", "braids", "bob", "waves", "curls"):
        end = (cx - rx * 1.2, cy + ry * (1.4 if name in ("ponytail", "braids", "waves") else 0.7))
        art = path(
            f"M {cx - rx * 0.85} {cy - ry * 0.6} Q {cx - rx * 1.6} {cy + ry * 0.2} "
            f"{end[0]} {end[1]}",
            "none",
            c["Hair"],
            rx * (0.5 if name == "braids" else 0.65),
        )
        if name == "ponytail":
            art = path(
                f"M {cx - rx * 0.85} {cy - ry * 0.45} C {cx - rx * 2} {cy - ry * 0.4} "
                f"{cx - rx * 1.2} {cy + ry} {cx - rx * 1.8} {cy + ry * 1.5} "
                f"Q {cx - rx * 2.4} {cy + ry * 0.1} {cx - rx * 0.85} {cy - ry * 0.45} Z",
                c["Hair"],
            )
            art += segment(
                (cx - rx * 0.98, cy - ry * 0.4), (cx - rx * 1.25, cy - ry * 0.48), 4, c["Accent"]
            )
        elif name == "waves":
            art = path(
                f"M {cx - rx * 0.85} {cy - ry * 0.6} Q {cx - rx * 1.8} {cy - ry * 0.2} "
                f"{cx - rx * 1.2} {cy + ry * 0.3} Q {cx - rx * 0.7} {cy + ry * 0.8} "
                f"{cx - rx * 1.5} {cy + ry * 1.2}",
                "none",
                c["Hair"],
                rx * 0.7,
            )
        emit(
            "Hair loose",
            "hair.back",
            art,
            (cx - rx * 2.6, cy - ry, rx * 2.3, ry * 3),
            17,
            "Hair",
            name,
        )


def stick_animal(recipe: CharacterRecipe, d: Design, joints: dict[str, Joint]) -> list[ArtPart]:
    """Use a spare stick skeleton with a species-specific head, ears and tail."""
    c = {**d.colors, **recipe.colors}
    ink, accent, width = c["Ink"], c["Accent"], recipe.stroke_width * 0.8
    parts = []
    for name, j in joints.items():
        if name in ("hips", "head", "neck") or name.startswith("ear."):
            continue
        size = width * 0.6 if name.startswith("tail") else width
        pad = size + 2
        bounds = (
            min(j.root[0], j.tip[0]) - pad,
            min(j.root[1], j.tip[1]) - pad,
            abs(j.root[0] - j.tip[0]) + pad * 2,
            abs(j.root[1] - j.tip[1]) + pad * 2,
        )
        layer = 28 if name.endswith(".L") else 5
        parts.append(ArtPart(name, name, segment(j.root, j.tip, size, ink), bounds, layer))
    hx, hy = joints["head"].root
    hx += d.head * 0.22
    hy -= d.head * 0.12
    h = d.head
    head = ellipse(hx, hy, h, h * 0.85, c["Skin"], ink, 2)
    parts.append(ArtPart("Head", "head", head, (hx - h - 3, hy - h, h * 2 + 6, h * 2), 45))
    for side in ("R", "L"):
        j = joints["ear." + side]
        if d.anatomy == "rabbit":
            art = segment(j.root, j.tip, h * 0.32, c["Skin"], ink)
            art += segment(j.root, offset(j.root, j.angle, j.length * 0.8), h * 0.12, accent)
        else:
            art = path(
                f"M {j.root[0] - h * 0.25} {j.root[1] + 3} L {j.tip[0]} {j.tip[1]} "
                f"L {j.root[0] + h * 0.25} {j.root[1] + 3} Z",
                c["Skin"],
                ink,
                1.5,
            )
        pad = h * 0.4
        bounds = (
            min(j.root[0], j.tip[0]) - pad,
            min(j.root[1], j.tip[1]) - pad,
            abs(j.tip[0] - j.root[0]) + pad * 2,
            abs(j.tip[1] - j.root[1]) + pad * 2,
        )
        parts.append(ArtPart("Ear " + side, "ear." + side, art, bounds, 42))
    if recipe.view not in ("Back", "Back 3/4"):
        for i, ex in enumerate((hx + h * 0.48, hx - h * 0.17)):
            if recipe.view == "Side" and i == 0:
                continue
            size = h * (0.065 if i == 0 else 0.085)
            parts.append(
                ArtPart(
                    "Eye " + str(i),
                    "head",
                    ellipse(ex, hy, size, size * 1.5, ink),
                    (ex - size * 2, hy - size * 2, size * 4, size * 4),
                    50 if i == 0 else 54,
                )
            )
        x, y = hx + h * 0.25, hy + h * 0.33
        art = ellipse(x, y, h * 0.13, h * 0.08, ink)
        art += path(
            f"M {x} {y + 1} L {x} {y + 5} Q {x - h * 0.2} {y + 9} {x - h * 0.3} {y + 4}",
            "none",
            ink,
            1.2,
        )
        if d.anatomy == "fox":
            art = (
                path(
                    f"M {hx + h * 0.08} {hy + h * 0.1} L {hx + h * 1.08} {hy + h * 0.28} "
                    f"Q {hx + h * 0.5} {hy + h * 0.7} {hx} {hy + h * 0.35} Z",
                    accent,
                    ink,
                    1.3,
                )
                + art
            )
        parts.append(ArtPart("Muzzle", "head", art, (hx - h * 0.2, hy, h * 1.4, h * 0.85), 52))
    return parts


def artwork(recipe: CharacterRecipe) -> tuple[Design, dict[str, Joint], list[ArtPart]]:
    """Evaluate the customized rest skeleton and its registered original vector parts."""
    recipe = retain_outfit_sets(recipe)
    d = customized_design(
        recipe.design_id, recipe.style, dict(recipe.proportions), recipe.body_shape
    )
    joints = world_joints(d, recipe.view, rest=True)
    if d.anatomy in ("cat", "fox", "rabbit"):
        parts = stick_animal(recipe, d, joints)
    else:
        from rigora.domain.creator_options import choose
        from rigora.infrastructure.illustration_wardrobe import wardrobe_art

        parts = stick_person(recipe, d, joints)
        for category in ("Hair", "Eyes", "Nose", "Mustache", "Beard"):

            def belongs(p: ArtPart, category: str = category) -> bool:
                """Identify the source component family before creating retained variants."""
                return (
                    p.name.startswith(("Hair ", "Antenna", "Orbit halo"))
                    if category == "Hair"
                    else p.name.startswith("Eye ")
                    if category == "Eyes"
                    else p.name == category
                )

            parts = [p for p in parts if not belongs(p)]
            selected = default_choice(recipe, category)
            for value in retained_choices(recipe, category):
                variant_recipe = choose(recipe, category, value)
                paint = recipe.garment_colors.get(category + "/" + value)
                if paint:
                    role = "Ink" if category in ("Eyes", "Nose") else "Hair"
                    variant_recipe = replace(
                        variant_recipe, colors={**recipe.colors, role: str(paint)}
                    )
                candidates = [p for p in stick_person(variant_recipe, d, joints) if belongs(p)]
                if not candidates:
                    x, y = joints["head"].root
                    candidates = [ArtPart(category, "head", "<g/>", (x - 1, y - 1, 2, 2), 72)]
                parts.extend(
                    replace(
                        p,
                        name=p.name + " · " + value,
                        family=category,
                        variant=value,
                        visible=value == selected,
                    )
                    for p in candidates
                )
        parts.extend(wardrobe_art(recipe, d, joints))
    if recipe.outline_width != 1.6:

        def contour(match: re.Match[str]) -> str:
            """Adjust filled-shape outlines while preserving intentional open limb strokes."""
            tag = match.group()
            if 'fill="none"' in tag or 'stroke="none"' in tag:
                return tag
            if recipe.outline_width == 0:
                return re.sub(r'stroke="[^"]*"', 'stroke="none"', tag)
            return re.sub(
                r'stroke-width="([\d.]+)"',
                lambda m: f'stroke-width="{float(m[1]) * recipe.outline_width / 1.6}"',
                tag,
            )

        parts = [
            replace(p, markup=re.sub(r"<(?:path|ellipse|rect)\b[^>]*>", contour, p.markup))
            for p in parts
        ]
    return d, joints, sorted(parts, key=lambda p: p.layer)


def portrait(recipe: CharacterRecipe) -> bytes:
    """Compose a vector poster from visible parts without using thumbnail textures."""
    _, _, parts = artwork(recipe)
    visible = [p for p in parts if p.visible]
    x = min(p.bounds[0] for p in visible) - 8
    y = min(p.bounds[1] for p in visible) - 8
    right = max(p.bounds[0] + p.bounds[2] for p in visible) + 8
    bottom = max(p.bounds[1] + p.bounds[3] for p in visible) + 8
    return svg("".join(p.markup for p in visible), (x, y, right - x, bottom - y))
