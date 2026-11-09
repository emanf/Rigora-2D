"""Vector accessory sheets with explicit silhouettes and common attachment anchors."""

from rigora.infrastructure.illustration import ellipse, path


def cap_art(paint: str, ink: str) -> str:
    """Draw a sewn crown and a closed, outlined visor in unit head-radius coordinates."""
    return (
        path(
            "M -.94 0 C -.91 -.65 -.5 -.83 .02 -.82 C .58 -.82 .91 -.49 .95 0 Q 0 .14 -.94 0 Z",
            paint,
            ink,
            0.045,
        )
        + path(
            "M .05 .02 Q .66 -.1 1.34 .07 Q 1.53 .17 1.15 .23 Q .59 .28 .05 .13 Z",
            paint,
            ink,
            0.045,
        )
        + path("M .05 -.76 Q .34 -.49 .29 -.04 M -.86 -.05 Q -.28 .04 .06 -.02", "none", ink, 0.025)
        + ellipse(0.01, -0.83, 0.07, 0.035, paint, ink, 0.025)
    )


def glasses_art(name: str, paint: str, ink: str, view: str) -> str:
    """Fit frames to the eye centers, foreshortening the far lens and omitting it in profile."""
    if name == "none" or view in ("Back", "Back 3/4"):
        return "<g/>"
    quarter, profile = view == "Front 3/4", view == "Side"
    centers = (
        [0.27 * 0.79]
        if profile
        else [-0.25 + (0.12 if quarter else 0), 0.35 + (0.12 if quarter else 0)]
    )
    art = ""
    for index, center in enumerate(centers):
        if name == "monocle" and index:
            continue
        fill = ink if name == "sunglasses" else "none"
        if name in ("round", "monocle", "oval", "rimless"):
            lens = ellipse(
                0,
                0,
                0.22 if name != "oval" else 0.27,
                0.23 if name != "oval" else 0.16,
                fill,
                paint,
                0.025 if name == "rimless" else 0.045,
            )
        elif name == "aviator":
            lens = path(
                "M -.24 -.15 Q 0 -.24 .24 -.13 L .2 .1 Q .13 .32 -.09 .2 Q -.29 .07 -.24 -.15 Z",
                "none",
                paint,
                0.035,
            )
        elif name == "cat eye":
            lens = path(
                "M -.29 -.22 Q -.02 -.13 .23 -.17 Q .27 .19 .02 .19 Q -.22 .2 -.29 -.22 Z",
                "none",
                paint,
                0.055,
            )
        elif name == "sport":
            lens = path(
                "M -.27 -.12 Q 0 -.2 .27 -.12 L .19 .14 Q 0 .23 -.22 .09 Z", "none", paint, 0.055
            )
        elif name == "half rim":
            lens = path("M -.24 0 Q -.22 -.3 0 -.24 Q .22 -.28 .24 0", "none", paint, 0.055)
            lens += path("M -.24 0 Q -.2 .23 0 .22 Q .2 .23 .24 0", "none", paint, 0.018)
        else:
            lens = (
                '<rect x="-.24" y="-.18" width=".48" height=".36" rx=".065" fill="'
                + fill
                + '" stroke="'
                + paint
                + '" stroke-width=".045"/>'
            )
        scale = 0.76 if quarter and index else 1
        art += f'<g transform="translate({center} 0) scale({scale} 1)">{lens}</g>'
    if name == "monocle":
        art += path(f"M {centers[0] - 0.12} .2 Q -.8 .75 -.82 .18", "none", paint, 0.02)
    elif not profile:
        midpoint = (centers[0] + centers[1]) / 2
        art += path(
            f"M {centers[0] + 0.22} 0 Q {midpoint} -.1 {centers[1] - 0.17} 0", "none", paint, 0.035
        )
        if name == "aviator":
            art += path(
                f"M {centers[0] + 0.2} -.15 L {centers[1] - 0.16} -.15", "none", paint, 0.025
            )
    art += path(f"M {centers[0] - 0.22} 0 L -.83 -.06", "none", paint, 0.035)
    if not profile and name != "monocle":
        art += path(f"M {centers[-1] + 0.17} 0 L .87 -.06", "none", paint, 0.035)
    return art


def neckwear_art(name: str, paint: str, ink: str) -> str:
    """Draw neckwear around the collar origin, separating wrapped cloth from hanging tails."""
    if name == "none":
        return "<g/>"
    if name in ("tie", "skinny tie", "striped tie"):
        w = 2.6 if name == "skinny tie" else 4.8
        art = path(f"M -1 4 L 1 4 L {w} 29 L 0 35 L {-w} 29 Z", paint, ink, 0.8)
        if name == "striped tie":
            art += "".join(
                path(f"M {-w * 0.7} {y} L {w * 0.6} {y + 3}", "none", ink, 1) for y in (14, 20, 26)
            )
        return art + path("M -3 -1 L 3 -1 L 2 4 L 0 6 L -2 4 Z", paint, ink, 0.8)
    if name == "bow tie":
        return path(
            "M -2 -3 Q -7 -8 -10 -6 L -10 6 Q -6 7 -2 2 L 2 2 Q 7 7 10 6 L 10 -6 Q 6 -8 2 -3 Z",
            paint,
            ink,
            0.9,
        ) + ellipse(0, 0, 2.4, 3.3, paint, ink, 0.8)
    if name == "cravat":
        return path(
            "M -6 -3 Q 0 0 6 -3 L 4 5 L 8 23 L 0 29 L -8 23 L -4 5 Z", paint, ink, 0.9
        ) + path("M -4 5 Q 0 9 4 5 M 0 9 L -3 22", "none", ink, 0.8)
    if name == "neckerchief":
        return path("M -12 -5 Q 0 2 12 -5 L 5 9 L 0 16 L -5 9 Z", paint, ink, 0.9) + path(
            "M -4 7 L -9 15 L -3 14 L 0 18 L 3 10", paint, ink, 0.8
        )
    length = 47 if name == "long scarf" else 31
    art = path(f"M -4 2 Q -8 15 -6 {length} L 2 {length - 1} Q 0 12 4 2 Z", paint, ink, 0.9)
    art += path(f"M 2 3 Q 5 17 9 {length - 9} L 16 {length - 12} Q 8 10 8 0 Z", paint, ink, 0.9)
    art += path("M -12 -5 Q 0 0 12 -5 L 12 2 Q 0 10 -12 2 Z", paint, ink, 0.9)
    art += path("M -10 -1 Q 0 4 10 -1 M -2 11 L -2 22", "none", ink, 0.7)
    art += "".join(path(f"M {x} {length - 1} l 0 3", "none", ink, 0.65) for x in (-5, -3, -1, 1))
    return art


def shoe_art(name: str, paint: str, ink: str, trim: str) -> str:
    """Return footwear on a shared ankle sheet; each style has its own upper and sole."""
    top = {"boots": -15, "ankle boots": -10, "rain boots": -22, "high tops": -11}.get(name, -4)
    if name == "sandals":
        return path("M -6 6 Q 7 4 22 8 Q 23 13 10 13 Q -5 13 -6 9 Z", paint, ink, 1.1) + path(
            "M -3 4 Q -1 -2 3 0 L 5 8 M 9 2 Q 15 -2 17 8", "none", paint, 3
        )
    if name == "slippers":
        return path(
            "M -7 5 Q 1 10 3 4 Q 4 -2 13 0 Q 23 1 23 9 Q 9 14 -7 9 Z", paint, ink, 1.1
        ) + path("M -5 6 Q 1 10 4 3", "none", trim, 2)
    if name == "dress shoes":
        return path(
            "M -6 8 L -5 -2 Q 1 -4 6 1 Q 10 1 15 3 Q 24 3 24 9 Q 8 12 -6 8 Z", paint, ink, 1.1
        ) + path(
            "M -5 9 L -5 12 L 2 12 L 3 10 M 12 3 Q 9 5 10 9 M 1 1 L 6 4 M 0 3 L 5 6",
            "none",
            ink,
            0.8,
        )
    art = path(
        f"M -6 8 L -5 {top} Q 2 {top - 3} 7 {top} L 8 2 Q 22 2 22 9 Q 8 13 -6 8 Z", paint, ink, 1.2
    )
    art += path("M -5 9 Q 8 13 22 9", "none", trim, 1.5)
    if name in ("sneakers", "high tops", "canvas"):
        art += path("M 6 1 L 12 3 M 5 4 L 11 6", "none", ink, 0.9)
    if name == "high tops":
        art += ellipse(0, -5, 2.2, 2.2, trim, ink, 0.7)
        art += path("M -4 -9 L 5 -9 M 5 -6 L 8 -4", "none", ink, 0.7)
    elif name == "canvas":
        art += path("M 13 3 Q 17 1 21 6 L 22 9 L 12 10 Z", trim, ink, 0.8)
    elif name == "loafers":
        art += path("M 1 1 Q 6 4 11 3 L 10 6 L 1 5 Z", trim, ink, 0.8)
    elif name == "rain boots":
        art += path("M -5 -19 L 7 -19 M -4 -17 L -4 4", "none", trim, 1.4)
    elif name == "ankle boots":
        art += path("M -2 -7 L -1 4 M 1 -6 L 5 -5 L 5 1 L 1 0 Z", "none", ink, 0.8)
    elif name == "boots":
        art += path("M -4 -12 L 6 -12 M 1 -9 L 6 -8 M 1 -5 L 7 -4", "none", ink, 0.8)
    return art
