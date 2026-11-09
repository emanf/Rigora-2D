"""Original facial feature variants in head-relative coordinates, without raster dependencies."""

from rigora.infrastructure.illustration import ellipse, path


def extra_eye(name: str, ink: str) -> str | None:
    """Draw additional eyes on a common unit pupil origin, preserving blink registration."""
    if name == "almond":
        return (
            path("M -1.8 0 Q 0 -2.3 1.8 0 Q 0 1.9 -1.8 0 Z", "#ffffff", ink, 0.3)
            + ellipse(0.15, 0, 0.65, 0.96, ink)
            + ellipse(0, -0.4, 0.22, 0.27, "#ffffff")
        )
    if name == "wide":
        return (
            ellipse(0, 0, 1.45, 1.7, "#ffffff", ink, 0.3)
            + ellipse(0.12, 0.25, 0.55, 0.9, ink)
            + ellipse(-0.04, -0.1, 0.17, 0.24, "#ffffff")
        )
    if name == "half lidded":
        return path(
            "M -1.7 -.35 L 1.7 -.35 Q 1.5 1.3 0 1.3 Q -1.5 1.3 -1.7 -.35 Z", "#ffffff", ink, 0.3
        ) + path("M -.3 -.25 L .7 -.25 L .6 .8 Q .2 1 -.2 .8 Z", ink)
    if name == "sparkle":
        return ellipse(0, 0, 1.05, 1.6, ink) + path(
            "M 0 -1.1 L .2 -.35 L .65 -.1 L .2 .15 L 0 .9 L -.2 .15 L -.65 -.1 L -.2 -.35 Z",
            "#ffffff",
        )
    if name == "cross":
        return path("M -1 -1.25 L 1 1.25 M 1 -1.25 L -1 1.25", "none", ink, 0.6)
    if name == "heart":
        return path(
            "M 0 1.5 C -.3 .9 -1.5 .1 -1.45 -.7 C -1.4 -1.8 -.25 -1.85 0 -.8 "
            "C .25 -1.85 1.4 -1.8 1.45 -.7 C 1.5 .1 .3 .9 0 1.5 Z",
            ink,
        )
    return None


def nose_art(name: str, ink: str, skin: str) -> str:
    """Draw an individual nose around a common origin, sized for a 29-unit head radius."""
    if name == "Button":
        return ellipse(0, 1, 2.5, 1.7, skin, ink, 1.1)
    if name == "Round":
        return ellipse(1, 1, 3.5, 3, skin, ink, 1.1)
    data = {
        "Simple": "M -1 -3 Q 4 2 -1 3",
        "Pointed": "M -2 -4 L 5 2 Q 2 4 -2 3",
        "Long": "M -1 -6 C 1 -3 -1 4 3 4 Q 8 7 -2 7",
        "Hooked": "M -2 -5 C 5 -4 7 2 4 5 Q 1 7 0 3 L -2 3",
        "Wide": "M -6 0 Q -7 5 -3 4 M -3 3 Q 0 1 3 3 M 3 4 Q 7 5 6 0",
    }
    return path(data.get(name, data["Simple"]), "none", ink, 1.2)


def extra_mustache(name: str, width: float, radius: float, paint: str) -> str | None:
    """Return extra silhouettes centered above the upper lip; legacy styles keep their source."""
    w, h = width, radius * 0.18
    shapes = {
        "Walrus": (
            f"M {-w} {-h * 0.6} Q 0 {-h * 1.2} {w} {-h * 0.6} L {w * 1.1} {h} Q "
            f"{w * 0.4} {h * 0.8} 0 {h * 0.2} Q {-w * 0.4} {h * 0.8} {-w * 1.1} {h}"
            f" Z"
        ),
        "Horseshoe": (
            f"M {-w} 0 Q 0 {-h * 1.6} {w} 0 L {w} {h * 2.6} L {w * 0.55} {h * 2.6} "
            f"L {w * 0.55} {h * 0.1} Q 0 {-h * 0.4} {-w * 0.55} {h * 0.1} L "
            f"{-w * 0.55} {h * 2.6} L {-w} {h * 2.6} Z"
        ),
        "English": (
            f"M 0 {-h * 0.5} Q {w * 0.7} {-h * 0.3} {w * 1.5} {-h * 0.7} L "
            f"{w * 0.9} {h * 0.1} Q {w * 0.3} {h * 0.5} 0 0 Q {-w * 0.3} {h * 0.5} "
            f"{-w * 0.9} {h * 0.1} L {-w * 1.5} {-h * 0.7} Q {-w * 0.7} {-h * 0.3} "
            f"0 {-h * 0.5} Z"
        ),
        "Dali": (
            f"M 0 0 C {w * 0.6} {h * 0.2} {w * 1.2} {h * 0.2} {w * 1.3} {-h * 1.5} "
            f"M 0 0 C {-w * 0.6} {h * 0.2} {-w * 1.2} {h * 0.2} {-w * 1.3} "
            f"{-h * 1.5}"
        ),
        "Imperial": (
            f"M 0 {-h * 0.5} Q {w * 0.5} {-h} {w * 0.8} 0 Q {w * 1.4} {h * 0.4} "
            f"{w * 1.3} {-h} Q {w * 1.9} {h * 1.2} {w * 0.6} {h * 0.6} L 0 "
            f"{h * 0.2} L {-w * 0.6} {h * 0.6} Q {-w * 1.9} {h * 1.2} {-w * 1.3} "
            f"{-h} Q {-w * 1.4} {h * 0.4} {-w * 0.8} 0 Q {-w * 0.5} {-h} 0 "
            f"{-h * 0.5} Z"
        ),
        "Toothbrush": (
            f"M {-w * 0.3} {-h * 0.7} Q 0 {-h} {w * 0.3} {-h * 0.7} L {w * 0.3} "
            f"{h * 0.3} L {-w * 0.3} {h * 0.3} Z"
        ),
    }
    if name not in shapes:
        return None
    return path(
        shapes[name],
        "none" if name == "Dali" else paint,
        paint if name == "Dali" else "none",
        max(1.2, radius * 0.05),
    )


def beard_art(name: str, width: float, radius: float, paint: str) -> tuple[str, float, float]:
    """Create chin/cheek beards below the mouth and return their half-width and lower extent."""
    w = width * (0.34 if name in ("Goatee", "Long", "Braided") else 1)
    h = radius * {
        "Goatee": 0.24,
        "Short": 0.22,
        "Full": 0.43,
        "Stubble": 0.20,
        "Chinstrap": 0.26,
        "Long": 0.9,
        "Long full": 1.0,
        "Pointed": 0.72,
        "Forked": 0.88,
        "Braided": 1.18,
    }.get(name, 0.22)
    top = -radius * 0.18
    if name == "Stubble":
        art = "".join(
            path(
                f"M {x * w} {y * radius} l {x * radius * 0.012} {radius * 0.026}",
                "none",
                paint,
                radius * 0.024,
            )
            for row, y in enumerate((-0.10, -0.03, 0.04, 0.11, 0.17))
            for col in range(-4, 5)
            if (x := col * 0.18 + (row % 2) * 0.05) ** 2 + ((y + 0.79) / 1.03) ** 2 < 0.97
        )
    elif name == "Chinstrap":
        w *= 1.5
        art = path(
            f"M {-w} {-radius * 0.5} Q {-w * 0.9} {radius * 0.13} 0 {radius * 0.24} "
            f"Q {w * 0.9} {radius * 0.13} {w} {-radius * 0.5} L {w * 0.86} {-radius * 0.5} "
            f"Q {w * 0.77} {radius * 0.02} 0 {radius * 0.12} "
            f"Q {-w * 0.77} {radius * 0.02} {-w * 0.86} {-radius * 0.5} Z",
            paint,
        )
    elif name == "Forked":
        art = path(
            (
                f"M {-w} {top} Q 0 {radius * 0.12} {w} {top} Q {w} {h * 0.7} {w * 0.55}"
                f" {h} L 0 {h * 0.65} L {-w * 0.55} {h} Q {-w} {h * 0.7} {-w} {top} Z"
            ),
            paint,
        )
    elif name == "Pointed":
        art = path(
            (
                f"M {-w} {top} Q 0 {radius * 0.12} {w} {top} Q {w * 0.8} {h * 0.55} 0 "
                f"{h} Q {-w * 0.8} {h * 0.55} {-w} {top} Z"
            ),
            paint,
        )
    elif name == "Braided":
        art = path(
            (
                f"M {-w} {top} Q 0 {radius * 0.08} {w} {top} Q {w * 1.4} {h * 0.25} "
                f"{w * 0.65} {h * 0.4} Q {w * 1.4} {h * 0.6} {w * 0.4} {h} L {-w * 0.4}"
                f" {h} Q {-w * 1.4} {h * 0.6} {-w * 0.65} {h * 0.4} Q {-w * 1.4} "
                f"{h * 0.25} {-w} {top} Z"
            ),
            paint,
        )
        art += "".join(
            path(
                f"M {-w * 0.6} {h * t} Q 0 {h * (t + 0.1)} {w * 0.6} {h * t}",
                "none",
                "#999999",
                radius * 0.035,
            )
            for t in (0.28, 0.48, 0.68, 0.84)
        )
    else:
        art = path(
            (
                f"M {-w} {top} Q 0 {radius * 0.12} {w} {top} C {w * 1.1} {h * 0.4} "
                f"{w * 0.7} {h} 0 {h} C {-w * 0.7} {h} {-w * 1.1} {h * 0.4} {-w} {top} "
                f"Z"
            ),
            paint,
        )
    return art, w * 1.5, max(h, radius * 0.3)
