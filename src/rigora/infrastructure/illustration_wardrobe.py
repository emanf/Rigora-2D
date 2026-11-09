"""Original replaceable SVG garments and accessories at explicit anatomical depths."""

from rigora.domain.character_recipe import CharacterRecipe
from rigora.domain.creator_options import default_choice, retained_choices
from rigora.domain.illustration_catalog import Design
from rigora.infrastructure.illustration import ArtPart, ellipse, open_sleeve, path, segment
from rigora.infrastructure.illustration_accessories import (
    cap_art,
    glasses_art,
    neckwear_art,
    shoe_art,
)
from rigora.infrastructure.illustration_motion import Joint, offset


def wardrobe_art(recipe: CharacterRecipe, d: Design, joints: dict[str, Joint]) -> list[ArtPart]:
    """Build retained wardrobe variants; occlusion follows opaque source geometry and draw order."""
    c = {**d.colors, **recipe.colors}
    ink = c["Ink"]
    width = recipe.stroke_width
    hx, hy = joints["head"].root
    cy, r = hy - d.head, d.head
    sx, sy = joints["spine"].tip
    px, py = joints["hips"].root
    parts: list[ArtPart] = []

    def add(
        category: str,
        choice: str,
        label: str,
        bone: str,
        art: str,
        bounds: tuple[float, float, float, float],
        layer: int,
    ) -> None:
        """Register one bound vector layer with its variant membership and draw order."""
        parts.append(
            ArtPart(
                category + " · " + choice + " · " + label,
                bone,
                art,
                bounds,
                layer,
                category,
                choice,
                choice == default_choice(recipe, category),
            )
        )

    for category in (
        "Pants",
        "Shoes",
        "Ties",
        "Headwear",
        "Glasses",
        "Watches",
        "Necklaces",
        "Belts",
        "Backwear",
    ):
        for choice in retained_choices(recipe, category):
            role = "Bottom" if category == "Pants" else "Shoes" if category == "Shoes" else "Accent"
            paint = str(recipe.garment_colors.get(category + "/" + choice, c[role]))
            if category == "Pants" and choice == "formal trousers":
                paint = str(recipe.garment_colors.get(category + "/" + choice, "#303338"))
            if category == "Pants":
                if choice == "skirt":
                    w, length = d.width * 0.42, d.leg * 0.75
                    art = path(
                        f"M {px - w * 0.6} {py - 3} L {px + w * 0.6} {py - 3} "
                        f"L {px + w} {py + length} Q {px} {py + length + 5} "
                        f"{px - w} {py + length} Z",
                        paint,
                        ink,
                    )
                    add(
                        category,
                        choice,
                        "Skirt",
                        "cloth",
                        art,
                        (px - w - 3, py - 6, w * 2 + 6, length + 15),
                        23,
                    )
                else:
                    for i, side in enumerate(("R", "L")):
                        for bone in ("thigh.", "shin."):
                            j = joints[bone + side]
                            fraction = (
                                0.68
                                if choice == "shorts"
                                else 0.76
                                if choice == "cargo shorts"
                                else 0.88
                                if choice == "bermuda shorts"
                                else 0.65
                                if choice == "capri" and bone == "shin."
                                else 1
                            )
                            length = j.length * fraction
                            tip = offset(j.root, j.angle, length)
                            pant_width = width * (
                                3.5
                                if choice == "wide trousers"
                                else 1.55
                                if choice == "leggings"
                                else 2.2
                            )
                            root = j.root
                            art = (
                                "<g/>"
                                if choice == "none"
                                or choice in ("shorts", "cargo shorts", "bermuda shorts")
                                and bone == "shin."
                                else open_sleeve(
                                    root,
                                    tip,
                                    pant_width,
                                    paint,
                                    ink,
                                    taper_root=bone == "thigh.",
                                    open_end=bone == "thigh." and fraction == 1,
                                )
                            )
                            if bone == "shin." and art != "<g/>":
                                # Hide crossing side strokes inside a bending knee socket.
                                radius = pant_width / 2 - 0.2
                                art += ellipse(*j.root, radius, radius, paint)
                            if choice in ("jeans", "cuffed jeans") and bone == "thigh.":
                                art += segment(
                                    offset(j.root, j.angle, 4),
                                    offset(j.root, j.angle, 12),
                                    1,
                                    c["Accent"],
                                )
                            if choice == "joggers" and bone == "shin.":
                                art += ellipse(*tip, width * 1.15, 2.5, paint, ink, 0.7)
                            if choice == "formal trousers":
                                art += segment(
                                    offset(j.root, j.angle, 5),
                                    offset(j.root, j.angle, length - 4),
                                    0.7,
                                    "#76797e",
                                )
                            if choice in ("cargo shorts", "cargo trousers") and bone == "thigh.":
                                x, y = offset(j.root, j.angle, length * 0.6)
                                art += path(
                                    f"M {x - 4} {y - 4} h 8 v 9 h -8 Z M {x - 4} {y - 1} h 8",
                                    "none",
                                    ink,
                                    0.8,
                                )
                            if choice == "track pants":
                                art += segment(
                                    offset(j.root, j.angle, 3),
                                    offset(tip, j.angle, -3),
                                    width * 0.45,
                                    c["Accent"],
                                )
                            if (choice == "bermuda shorts" and bone == "thigh.") or (
                                choice == "cuffed jeans" and bone == "shin."
                            ):
                                band = path(
                                    f"M -5 {-width * 1.2} h 6 v {width * 2.4} h -6 Z",
                                    paint,
                                    ink,
                                    0.75,
                                )
                                art += (
                                    f'<g transform="translate({tip[0]} {tip[1]}) '
                                    f'rotate({j.angle})">{band}</g>'
                                )
                            pad = width * 2 + 3
                            add(
                                category,
                                choice,
                                bone + side,
                                bone + side,
                                art,
                                (
                                    min(j.root[0], tip[0]) - pad,
                                    min(j.root[1], tip[1]) - pad,
                                    abs(j.root[0] - tip[0]) + pad * 2,
                                    abs(j.root[1] - tip[1]) + pad * 2,
                                ),
                                17 if i == 0 else 10,
                            )
            elif category == "Shoes":
                for i, side in enumerate(("R", "L")):
                    x, y = joints["foot." + side].root
                    facing = -1 if recipe.view in ("Front", "Back") and side == "R" else 1
                    if choice == "bare":
                        art = path(
                            "M -3 0 C 1 -1 6 -1 11 1 C 18 2 23 5 18 7 "
                            "C 10 10 -5 10 -7 7 Q -9 4 -3 0 Z",
                            paint,
                            ink,
                            1.2,
                        )
                    else:
                        art = shoe_art(choice, paint, ink, c["Skin"])
                    art = f'<g transform="translate({x} {y}) scale({facing} 1)">{art}</g>'
                    add(
                        category,
                        choice,
                        side,
                        "foot." + side,
                        art,
                        (x - 28, y - 29, 56, 46),
                        19 if i == 0 else 11,
                    )
            elif category == "Ties":
                scarf = choice in ("scarf", "long scarf")
                x, y = sx, sy - 6 if scarf else sy
                art = neckwear_art(choice, paint, ink)
                art = f'<g transform="translate({x} {y})">{art}</g>'
                add(
                    category,
                    choice,
                    "Tie",
                    "spine",
                    art,
                    (x - 17, y - 9, 36, 64),
                    39 if scarf else 35,
                )
            elif category == "Headwear":
                x, y = hx, cy - r * 0.75
                art = "<g/>"
                if choice == "cap":
                    art = f'<g transform="translate({x} {y}) scale({r})">{cap_art(paint, ink)}</g>'
                elif choice in ("beanie", "sun hat", "top hat"):
                    height = r * 0.85 if choice == "top hat" else r * 0.48
                    art = path(
                        f"M {x - r * 0.92} {y} Q {x - r * 0.8} {y - height} {x} {y - height} "
                        f"Q {x + r * 0.8} {y - height} {x + r * 0.92} {y} Z",
                        paint,
                        ink,
                    )
                    brim = r * 1.3 if choice in ("top hat", "sun hat") else r
                    art += path(f"M {x - brim} {y} Q {x} {y + 5} {x + brim} {y}", "none", ink, 3)
                    if choice == "beanie":
                        art += ellipse(x, y - height - 3, 5, 5, paint, ink)
                elif choice == "headphones":
                    art = path(
                        f"M {x - r} {cy + 5} C {x - r * 1.3} {cy - r * 1.5} "
                        f"{x + r * 1.3} {cy - r * 1.5} {x + r} {cy + 5}",
                        "none",
                        ink,
                        4,
                    )
                    art += ellipse(x - r, cy + 2, 5, 11, paint, ink)
                    art += ellipse(x + r, cy + 2, 5, 11, paint, ink)
                elif choice == "crown":
                    art = path(
                        f"M {x - r * 0.8} {y + 2} L {x - r} {y - r * 0.6} "
                        f"L {x - r * 0.4} {y - r * 0.3} L {x} {y - r * 0.85} "
                        f"L {x + r * 0.4} {y - r * 0.3} L {x + r} {y - r * 0.6} "
                        f"L {x + r * 0.8} {y + 2} Z",
                        paint,
                        ink,
                    )
                add(
                    category,
                    choice,
                    "Headwear",
                    "head",
                    art,
                    (x - r * 1.6, cy - r * 1.9, r * 3.2, r * 2.5),
                    76,
                )
            elif category == "Glasses":
                x, y = hx, cy - r * 0.05
                art = glasses_art(choice, paint, ink, recipe.view)
                art = f'<g transform="translate({x} {y}) scale({r})">{art}</g>'
                add(
                    category,
                    choice,
                    "Frames",
                    "head",
                    art,
                    (x - r * 1.05, y - r * 0.45, r * 2.1, r * 1.3),
                    70,
                )
            elif category == "Watches":
                for i, side in enumerate(("R", "L")):
                    if i:
                        continue
                    j = joints["forearm." + side]
                    x, y = offset(j.root, j.angle, j.length * 0.85)
                    art = "<g/>"
                    if choice != "none":
                        face = (
                            ellipse(0, 0, 4.1, 4.1, c["Skin"], ink, 1)
                            if choice == "classic"
                            else path("M -4 -3 L 4 -3 L 4 3 L -4 3 Z", c["Skin"], ink, 1)
                        )
                        art = path("M -6 -2 L 6 -2 L 6 2 L -6 2 Z", paint, ink, 0.7)
                        if choice != "bracelet":
                            art += face + path("M 0 -2 L 0 0 L 2 1", "none", ink, 0.7)
                        art = f'<g transform="translate({x} {y}) rotate({j.angle - 90})">{art}</g>'
                    layer = 46 if recipe.layer_modes.get(category) == "Over sleeves" else 42
                    add(
                        category,
                        choice,
                        side,
                        "forearm." + side,
                        art,
                        (x - 11, y - 11, 22, 22),
                        layer if i == 0 else 5,
                    )
            elif category == "Necklaces":
                x, y, w = sx, sy + 10, d.width * 0.24
                art = "<g/>"
                if choice != "none":
                    art = path(
                        f"M {x - w} {y - 3} Q {x} {y + 32} {x + w} {y - 3}", "none", paint, 1.5
                    )
                    if choice == "pendant":
                        art += path(
                            f"M {x} {y + 12} L {x + 4} {y + 17} L {x} {y + 23} "
                            f"L {x - 4} {y + 17} Z",
                            paint,
                            ink,
                            0.8,
                        )
                    elif choice == "pearls":
                        art += "".join(
                            ellipse(x + w * t, y + 12 * (1 - t * t), 2, 2, c["Skin"], paint, 0.8)
                            for t in (-0.8, -0.4, 0, 0.4, 0.8)
                        )
                add(category, choice, "Chain", "spine", art, (x - w - 6, y - 7, w * 2 + 12, 37), 34)
            elif category == "Belts":
                x, y, w = px, py - 2, d.width * 0.34
                art = "<g/>"
                if choice != "none":
                    art = path(
                        f"M {x - w} {y - 3} Q {x} {y + 1} {x + w} {y - 3} "
                        f"L {x + w} {y + 3} Q {x} {y + 7} {x - w} {y + 3} Z",
                        paint,
                        ink,
                    )
                    art += path(
                        (
                            f"M {x - 3} {y - 2} L {x + 3} {y - 2} L {x + 3} {y + 4} L {x - 3} "
                            f"{y + 4} Z"
                        ),
                        c["Accent"],
                        ink,
                    )
                    if choice == "utility":
                        art += path(
                            f"M {x - w + 1} {y + 2} L {x - w + 1} {y + 12} "
                            f"L {x - w + 9} {y + 12} L {x - w + 9} {y + 2} Z",
                            paint,
                            ink,
                        )
                    elif choice == "sash":
                        art += path(
                            f"M {x + 7} {y + 2} L {x + 15} {y + 21} L {x + 9} {y + 19} Z",
                            paint,
                            ink,
                        )
                layer = 39 if recipe.layer_modes.get(category) == "Over outerwear" else 32
                add(category, choice, "Belt", "hips", art, (x - w - 4, y - 7, w * 2 + 8, 33), layer)
            elif category == "Backwear":
                x, y, w = sx - d.width * 0.3, sy + 10, d.width * 0.42
                art = "<g/>"
                if choice == "cape":
                    art = path(
                        f"M {sx - 8} {sy + 3} Q {sx - w * 2} {py - 9} {sx - w * 2} {py + 30} "
                        f"Q {sx} {py + 40} {sx + w} {py + 28} L {sx + 7} {sy + 3} Z",
                        paint,
                        ink,
                    )
                elif choice != "none":
                    art = (
                        f'<rect x="{x - w}" y="{y}" width="{w * 1.3}" height="{d.body * 0.75}" '
                        f'rx="8" fill="{paint}" stroke="{ink}" stroke-width="1.4"/>'
                    )
                    art += path(
                        f"M {x - w * 0.8} {y + d.body * 0.4} L {x + w * 0.1} {y + d.body * 0.4}",
                        "none",
                        ink,
                        1,
                    )
                    if choice == "satchel":
                        art += path(
                            f"M {x - w} {y + 8} L {x + w * 0.3} {y + 8} "
                            f"L {x + w * 0.1} {y + 25} L {x - w * 0.8} {y + 25} Z",
                            "none",
                            ink,
                            1.2,
                        )
                        art += path(f"M {sx - 5} {sy - 2} L {sx + w} {py - 4}", "none", paint, 4)
                add(
                    category,
                    choice,
                    "Bag",
                    "spine",
                    art,
                    (sx - w * 2.2, sy - 3, w * 3.5, d.body + 50),
                    2,
                )
    return parts
