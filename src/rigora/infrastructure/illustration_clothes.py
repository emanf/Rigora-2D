"""Additional original vector tops with separate collars, seams and suit lapels."""

from rigora.infrastructure.illustration import ellipse, path

LONG_SLEEVES = frozenset(
    (
        "hoodie",
        "jacket",
        "overshirt",
        "suit jacket",
        "coat",
        "shirt",
        "formal suit",
        "tuxedo",
        "blazer",
        "cardigan",
        "robe",
        "raincoat",
    )
)


def extra_top(
    name: str,
    x: float,
    y: float,
    half_width: float,
    height: float,
    paint: str,
    ink: str,
    accent: str,
    *,
    back: bool = False,
) -> str | None:
    """Render named tops on a common torso sheet; return None for existing garment styles."""
    if name not in (
        "formal suit",
        "tuxedo",
        "blazer",
        "polo",
        "cropped tee",
        "tank top",
        "striped tee",
        "cardigan",
        "robe",
        "raincoat",
    ):
        return None
    hem = 48 if name == "cropped tee" else 82
    shoulder = 14 if name == "tank top" else 19
    contour = (
        f"M {-shoulder} 2 Q -21 25 -19 {hem - 5} Q -19 {hem + 3} -8 {hem + 2} "
        f"Q 8 {hem + 4} 19 {hem} Q 21 33 {shoulder} 2 Q 0 -2 {-shoulder} 2 Z"
    )
    art = path(contour, paint, ink, 1.2)
    if back:
        art += path("M -8 3 Q 0 12 8 3", "none", ink, 0.8)
        if name in ("formal suit", "tuxedo", "blazer", "cardigan", "robe", "raincoat"):
            art += path(f"M 0 15 L 0 {hem - 3}", "none", ink, 0.7)
    elif name in ("formal suit", "tuxedo", "blazer"):
        art += path("M -9 1 L 0 49 L 9 1 Q 0 -1 -9 1 Z", "#f4f1eb")
        art += path(
            "M -10 1 L -15 14 L -8 18 L -12 23 L 0 49 M 10 1 L 15 14 L 8 18 L 12 23 L 0 49",
            "none",
            "#b8b8b8",
            0.9,
        )
        art += path("M -7 2 L -3 12 L 0 7 L 3 12 L 7 2", "none", ink, 0.7)
        art += path("M 0 49 L -3 81 M 7 57 L 16 56 M -16 57 L -7 58", "none", ink, 0.8)
        art += ellipse(1, 57, 1.3, 1.3, "#c4c4c4")
        if name == "tuxedo":
            art += path("M 7 31 L 16 31 L 14 27 L 11 30 L 9 27 Z", "#f4f1eb")
            art += path("M -4 18 L -1 43 L 0 47 L 1 43 L 4 18", "none", ink, 0.6)
        elif name == "blazer":
            art += path("M 8 29 L 17 29 M 9 32 L 16 32", "none", accent, 1)
    elif name == "polo":
        art += path("M -9 2 L -5 14 L 0 6 L 5 14 L 9 2 M 0 8 L 0 25", "none", ink, 1)
        art += ellipse(2, 17, 0.9, 0.9, ink) + ellipse(2, 22, 0.9, 0.9, ink)
    elif name == "tank top":
        art += path("M -8 1 Q 0 31 8 1 M -14 3 Q -8 20 -19 31 M 14 3 Q 8 20 19 31", "none", ink, 1)
    elif name == "striped tee":
        art += "".join(path(f"M -18 {h} L 18 {h}", "none", accent, 3) for h in (27, 39, 51, 63, 75))
        art += path("M -8 1 Q 0 13 8 1", "none", ink, 1)
    elif name == "cardigan":
        art += path(
            (
                "M -8 1 L 0 30 L 8 1 M 0 30 L 0 82 M -16 57 L -6 57 L -7 69 L -15 69 Z "
                "M 6 57 L 16 57 L 15 69 L 7 69 Z"
            ),
            "none",
            ink,
            1,
        )
        art += "".join(ellipse(2, h, 1.1, 1.1, accent, ink, 0.5) for h in (39, 50, 61, 72))
    elif name == "robe":
        art += path("M -9 0 L 9 43 L -4 82 M 9 0 L -7 35", "none", ink, 1.5)
        art += path(
            "M -19 51 L 19 51 M -19 55 L 19 55 M 2 53 L 8 72 L 10 64 L 15 72", "none", accent, 2
        )
    elif name == "raincoat":
        art += path(
            "M -11 1 L -7 18 L 0 10 L 7 18 L 11 1 M 0 12 L 0 82 M -17 52 L -6 49 M 6 49 L 17 52",
            "none",
            ink,
            1,
        )
        art += "".join(ellipse(3, h, 1.5, 1.5, accent, ink, 0.6) for h in (28, 42, 56, 70))
    else:
        art += path("M -8 1 Q 0 13 8 1 M -18 45 Q 0 49 18 45", "none", ink, 1)
    return f'<g transform="translate({x} {y}) scale({half_width / 20} {height / 80})">{art}</g>'
