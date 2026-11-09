"""Original fitted hairstyles expressed in head-relative vector coordinates."""

from math import cos, pi, sin

from rigora.infrastructure.illustration import ellipse, path

HAIRSTYLES = (
    "pixie",
    "side part",
    "center part",
    "bowl",
    "buzz",
    "afro",
    "bun",
    "twin buns",
    "pigtails",
    "mohawk",
    "locs",
    "layered bob",
    "spring curl",
    "double curl",
    "coiled fringe",
    "curly ponytail",
    "high ponytail",
    "side curl",
)

SPRIG_STYLES = {
    "single sprig": "M -.08 -.98 Q -.02 -1.42 .38 -1.47",
    "double sprigs": "M -.1 -.99 Q -.25 -1.38 -.55 -1.4 M .02 -1 Q .26 -1.42 .58 -1.34",
    "fan sprigs": (
        "M -.12 -.99 Q -.42 -1.36 -.72 -1.32 M -.04 -1 Q -.11 -1.52 .05 -1.57 "
        "M .05 -1 Q .4 -1.49 .74 -1.38"
    ),
    "cowlick sprigs": "M -.12 -1 C -.6 -1.75 .8 -1.67 .44 -1.3 Q .29 -1.11 .03 -1.14",
    "loop sprig": "M -.08 -.99 C -.58 -1.47 .62 -1.85 .39 -1.27 Q .25 -.98 -.08 -1.08",
    "curled sprigs": (
        "M -.13 -.99 C -.67 -1.25 -.46 -1.67 -.15 -1.49 Q .04 -1.3 -.2 -1.22 "
        "M .08 -1 Q .45 -1.48 .68 -1.27 Q .85 -1.09 .57 -1.02"
    ),
    "zigzag sprigs": (
        "M -.12 -1 L -.42 -1.32 L -.14 -1.26 L -.32 -1.57 "
        "M .08 -1 L .31 -1.3 L .2 -1.29 L .54 -1.51"
    ),
}


def sprig_art(name: str, paint: str) -> str:
    """Draw sparse crown strands with rounded ends on a common unit head-radius sheet."""
    return path(SPRIG_STYLES[name], "none", paint, 0.065)


def hair_shapes(name: str, paint: str, accent: str, back: bool) -> tuple[str, str]:
    """Return a fitted cap and optional swinging silhouette in unit head coordinates."""
    cap = "M -1 -.2 C -1.15 -1.35 1.15 -1.35 1 -.2 Q .4 -.8 0 -.6 Q -.6 -.4 -1 -.2 Z"
    loose = ""
    if name in (
        "spring curl",
        "double curl",
        "coiled fringe",
        "curly ponytail",
        "high ponytail",
        "side curl",
    ):
        cap = path("M -.99 -.18 C -.94 -1.3 .94 -1.3 .99 -.18 L .84 -.4 Q 0 -.78 -.84 -.4 Z", paint)
        coil = path(
            "M 0 0 C -.35 -.18 -.4 -.65 -.07 -.72 C .23 -.78 .32 -.45 .13 -.32 "
            "C -.07 -.2 -.22 -.41 -.09 -.5",
            "none",
            paint,
            0.09,
        )
        if name == "coiled fringe":
            cap += "".join(
                f'<g transform="translate({x} -.35) scale(.6)">{coil}</g>'
                for x in (-0.64, -0.32, 0, 0.32, 0.64)
            )
        elif name in ("spring curl", "double curl", "side curl"):
            x, y = (-0.75, -0.4) if name == "side curl" else (-0.1, -1.03)
            loose = f'<g transform="translate({x} {y})">{coil}</g>'
            if name == "double curl":
                loose += f'<g transform="translate(.34 -1.01) scale(-.8 .8)">{coil}</g>'
        else:
            loose = path(
                "M -.77 -.7 C -1.7 -.93 -1.77 -.13 -1.5 .45 Q -1.7 1.2 -.91 1.17 "
                "Q -1.13 .7 -.94 .38 Q -1.27 -.2 -.63 -.34 Z",
                paint,
            )
            if name == "curly ponytail":
                loose += "".join(
                    f'<g transform="translate(-1.4 {y}) scale(.72)">{coil}</g>'
                    for y in (-0.03, 0.43, 0.86)
                )
            else:
                loose += path("M -1.43 -.3 Q -1.24 .2 -1.18 .84", "none", accent, 0.035)
            cap += ellipse(-0.78, -0.67, 0.11, 0.15, accent)
    elif name == "pixie":
        cap = (
            "M -1 .05 C -1.2 -.6 -.95 -1.08 -.45 -1.12 L -.2 -1.3 L -.1 -1.13 "
            "Q .6 -1.27 1 -.38 Q .45 -.72 .15 -.55 L -.1 -.7 "
            "Q -.6 -.25 -.9 .1 L -.84 -.35 Z"
        )
    elif name == "side part":
        cap = (
            "M -1 .1 C -1.25 -.7 -.7 -1.22 .25 -1.13 C .9 -1.13 1.13 -.65 1 -.06 "
            "Q .75 -.4 .62 -.75 Q .1 -.23 -.65 -.35 L -.9 .1 Z"
        )
    elif name == "center part":
        cap = (
            "M -1 .22 C -1.2 -.8 -.6 -1.3 0 -1.08 C .6 -1.3 1.2 -.8 1 .22 "
            "Q .68 -.12 .43 -.65 Q .15 -.78 0 -.96 Q -.15 -.78 -.43 -.65 "
            "Q -.68 -.12 -1 .22 Z"
        )
    elif name == "bowl":
        cap = (
            "M -1.05 .03 C -1.2 -1.48 1.2 -1.48 1.05 .03 L .86 -.42 Q .2 -.25 -.65 -.4 L -.9 -.34 Z"
        )
    elif name == "buzz":
        cap = "M -.97 -.24 C -.85 -1.28 .85 -1.28 .97 -.24 L .78 -.43 Q 0 -1.08 -.78 -.43 Z"
    elif name == "afro":
        cap = "".join(
            ellipse(cos(i * pi / 10) * 1.03, -0.2 - sin(i * pi / 10) * 0.98, 0.29, 0.3, paint)
            for i in range(11)
        )
        cap += path("M -.94 -.2 C -1.04 -1.38 1.04 -1.38 .94 -.2 Q 0 -.68 -.94 -.2 Z", paint)
    elif name in ("bun", "twin buns", "pigtails"):
        cap = "M -1 -.06 C -1.15 -1.32 1.15 -1.32 1 -.06 L .83 -.42 Q 0 -.75 -.83 -.42 Z"
        if name == "bun":
            cap = ellipse(-0.25, -1.24, 0.42, 0.35, paint) + path(cap, paint)
            cap += path("M -.59 -1.15 Q -.28 -1.3 .04 -1.14", "none", accent, 0.06)
        else:
            for sign in (-1, 1):
                if name == "twin buns":
                    cap = ellipse(sign * 0.91, -0.91, 0.35, 0.35, paint) + (
                        path(cap, paint) if cap.startswith("M") else cap
                    )
                    cap += ellipse(sign * 0.91, -0.91, 0.21, 0.21, "none", accent, 0.035)
                else:
                    tail = path(
                        "M .92 -.42 C 1.6 -.72 1.72 .5 1.38 .83 Q 1.6 .31 1.01 .12 Z",
                        paint,
                    )
                    loose += f'<g transform="scale({sign} 1)">{tail}</g>'
                    loose += ellipse(sign * 1.03, -0.2, 0.07, 0.18, accent)
    elif name == "mohawk":
        cap = (
            "M -.32 -.78 L -.45 -1.14 L -.2 -1.06 L -.1 -1.51 L .1 -1.25 "
            "L .26 -1.52 L .4 -1.16 L .67 -1.25 L .62 -.76 Q .1 -.92 -.32 -.78 Z"
        )
    elif name == "locs":
        cap = "".join(
            path(f"M {x} -.93 Q {x - 0.12} -.65 {x - 0.06} -.4", "none", paint, 0.19)
            for x in (-0.76, -0.5, -0.24, 0.02, 0.28, 0.54, 0.8)
        )
        cap += path(
            "M -.85 -.7 Q -.7 -1.24 .1 -1.1 Q .87 -1.1 .9 -.5 L .7 -.56 Q 0 -.9 -.85 -.7 Z", paint
        )
        loose = "".join(
            path(f"M {x} -.5 Q {x * 1.5} .2 {x * 1.2} .95", "none", paint, 0.2)
            for x in (-0.91, -0.74, 0.74, 0.91)
        )
    elif name == "layered bob":
        cap = (
            "M -1 .4 C -1.2 -.8 -.62 -1.18 .18 -1.12 C .95 -1.09 1.12 -.4 1 .38 "
            "L .86 .1 L .76 .27 L .7 -.5 Q .38 -.72 .1 -.82 "
            "Q -.25 -.18 -.79 -.22 L -.8 .2 Z"
        )
        loose = path(
            "M -.9 -.5 Q -1.3 .28 -.97 .86 L -.68 .68 L -.8 .98 "
            "Q -.45 .8 -.5 .45 L .5 .45 Q .45 .8 .8 .98 L .68 .68 "
            "L .97 .86 Q 1.3 .28 .9 -.5 Z",
            paint,
        )
    if cap.startswith("M"):
        cap = path(cap, paint)
    if back:
        # Keep the chosen outer hairstyle, with a filled rear cap covering the face.
        rear = ellipse(0, -0.02, 0.99, 0.98, paint)
        if name in ("buzz", "mohawk"):
            rear = path("M -.95 -.27 Q 0 -1.23 .95 -.27 L .89 .38 Q 0 .13 -.89 .38 Z", paint)
        cap = rear + cap
        if name in ("side part", "center part", "bun", "twin buns", "pigtails"):
            cap += path("M 0 -.85 Q -.15 -.45 0 .2", "none", accent, 0.025)
    return cap, loose
