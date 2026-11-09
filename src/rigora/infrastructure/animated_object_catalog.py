"""Original layered fire, water, weather and mechanical vector-effect compositions."""

import math
from dataclasses import dataclass

from rigora.infrastructure.object_catalog import ellipse, path, radial, rect


@dataclass(frozen=True)
class EffectLayer:
    """Retain independently editable SVG art and a small analytic animation recipe."""

    name: str
    body: str
    motion: str = ""
    phase: float = 0
    pivot: tuple[float, float] = (128, 128)


@dataclass(frozen=True)
class AnimatedObject:
    """Describe a layered reusable Object with one smooth source animation."""

    name: str
    category: str
    layers: tuple[EffectLayer, ...]
    frames: int = 90


def animated_objects() -> tuple[AnimatedObject, ...]:
    """Build fire, liquid, atmosphere and moving mechanisms from original vector layers."""
    flame = path(
        (
            "M128 194 C78 193 67 160 92 119 C102 148 121 108 128 38 C189 102 188 "
            "166 152 188 Q141 196 128 194Z"
        ),
        "#df8d4c",
    )
    core = path(
        "M130 189 C105 180 103 157 122 129 C121 151 136 147 142 118 C166 157 160 182 130 189Z",
        "#eecb72",
    )
    result = []
    bases = {
        "Torch": rect(117, 163, 23, 77, "#886143") + rect(107, 153, 43, 30, "#655349"),
        "Campfire": path("M62 211 L196 232 M64 233 L193 207", "none", "#886143", 22),
        "Bonfire": path(
            "M33 218 L222 237 M37 240 L219 214 M77 231 L179 201", "none", "#77563f", 25
        ),
        "Candle": rect(94, 145, 68, 86, "#e4d7b2", 10) + ellipse(128, 233, 60, 9, "#88949a"),
        "Lantern": rect(79, 91, 98, 137, "#47515b", 9)
        + rect(91, 105, 74, 103, "#e1cf94", 4)
        + path("M100 86 V64 A28 28 0 0 1 156 64 V86", "none", "#47515b", 10),
        "Brazier": path("M61 174 H195 L180 211 H76Z", "#59636b")
        + rect(84, 206, 15, 34, "#59636b")
        + rect(157, 206, 15, 34, "#59636b"),
    }
    for name, base in bases.items():
        scale = 0.48 if name in ("Candle", "Lantern") else 1
        shift = 143 if name == "Candle" else 191

        def wrap(body: str, origin: int = shift, size: float = scale) -> str:
            """Fit flame art to the fuel/support socket before authoring its motion."""
            return (
                f'<g transform="translate(128 {origin}) scale({size}) translate(-128 '
                f'-194)">{body}</g>'
            )

        layers = [EffectLayer("Support", base)]
        layers.extend(
            (
                EffectLayer("Outer flame", wrap(flame), "flame", 0, (128, shift)),
                EffectLayer("Flame core", wrap(core), "flame", 0.27, (128, shift)),
            )
        )
        for i in range(3):
            layers.append(
                EffectLayer(
                    f"Ember {i + 1}",
                    ellipse(111 + i * 17, 166, 3, 5, "#e3b66a"),
                    "rise",
                    i / 3,
                    (128, 194),
                )
            )
        if name == "Lantern":
            layers.append(
                EffectLayer(
                    "Lantern frame",
                    path("M79 91 H177 V228 H79Z M128 95 V225", "none", "#47515b", 10),
                )
            )
        result.append(AnimatedObject(name, "Fire & smoke", tuple(layers), 72))
    water = "#719eae"
    wave = path("M14 119 Q43 85 74 119 T134 119 T194 119 T254 119 V219 H14Z", water)
    result.append(
        AnimatedObject(
            "Water surface",
            "Water & weather",
            (
                EffectLayer("Water body", rect(14, 143, 228, 76, "#567c91")),
                EffectLayer("Wave crest", wave, "wave"),
                EffectLayer(
                    "Foam",
                    path("M16 119 Q44 86 74 119 T134 119 T194 119 T254 119", "none", "#c0d8d9", 7),
                    "bob",
                    0.2,
                ),
            ),
            120,
        )
    )
    result.append(
        AnimatedObject(
            "Ocean waves",
            "Water & weather",
            tuple(
                EffectLayer(
                    f"Wave {i + 1}",
                    (
                        f'<g transform="translate(0 {i * 22 - 27})">'
                        f"{wave.replace(water, ('#88b4bf', '#6a9aa9', '#4d7e96')[i])}</g>"
                    ),
                    "wave",
                    i / 3,
                )
                for i in range(3)
            ),
            120,
        )
    )
    falls = [
        EffectLayer("Waterfall", path("M73 19 Q128 32 183 19 L196 222 Q128 244 60 222Z", water))
    ]
    falls.extend(
        EffectLayer(
            f"Falling strand {i + 1}", rect(83 + i * 27, 53, 9, 72, "#c3dfe0", 4), "fall", i / 3
        )
        for i in range(3)
    )
    falls.append(EffectLayer("Foam pool", ellipse(128, 230, 95, 15, "#b5d3d7"), "pulse"))
    result.append(AnimatedObject("Waterfall", "Water & weather", tuple(falls), 60))
    fountain = [
        EffectLayer("Basin", path("M34 190 H222 Q211 236 128 236 Q45 236 34 190Z", "#9da8ad"))
    ]
    fountain.extend(
        EffectLayer(
            f"Jet {i + 1}",
            path(f"M128 205 Q{68 + i * 30} {12 + i * 7} {43 + i * 42} 187", "none", water, 9),
            "bob",
            i / 4,
        )
        for i in range(4)
    )
    result.append(AnimatedObject("Fountain", "Water & weather", tuple(fountain), 90))
    splash = [EffectLayer("Splash pool", ellipse(128, 207, 89, 18, water), "pulse")]
    splash.extend(
        EffectLayer(
            f"Droplet {i + 1}",
            ellipse(54 + i * 29, 150 - 25 * math.sin(i), 7, 11, water),
            "splash",
            i / 5,
        )
        for i in range(6)
    )
    result.append(AnimatedObject("Water splash", "Water & weather", tuple(splash), 60))
    tap = [
        EffectLayer(
            "Tap",
            path("M58 46 H149 Q180 46 180 77 V113 H144 V85 H58Z", "#a1acb2")
            + rect(97, 22, 54, 12, "#697781"),
        )
    ]
    tap.extend(
        EffectLayer(
            f"Drip {i + 1}",
            path("M161 123 Q141 154 161 161 Q181 154 161 123Z", water),
            "drip",
            i / 3,
        )
        for i in range(3)
    )
    result.append(AnimatedObject("Dripping tap", "Water & weather", tuple(tap), 90))
    for name, body, motion, category, count in (
        ("Rain", path("M0 0 L-5 18", "none", water, 4), "rain", "Water & weather", 16),
        ("Snow", ellipse(0, 0, 4, 4, "#d6e3e3"), "snow", "Water & weather", 16),
        (
            "Bubbles",
            ellipse(0, 0, 10, 10, "none").replace("/>", ' stroke="#9bc6d0" stroke-width="3"/>'),
            "rise",
            "Water & weather",
            8,
        ),
        ("Steam", ellipse(0, 0, 19, 13, "#d5dad8"), "rise", "Fire & smoke", 8),
        ("Smoke", ellipse(0, 0, 23, 17, "#929b9f"), "rise", "Fire & smoke", 8),
        ("Dust puff", ellipse(0, 0, 20, 14, "#bcb09b"), "splash", "Atmosphere & magic", 8),
        (
            "Sparkle burst",
            radial(4, 28).replace("#acb7c0", "#d4c78a"),
            "sparkle",
            "Atmosphere & magic",
            5,
        ),
    ):
        layers = []
        for i in range(count):
            x, y = 32 + (i * 67) % 194, 33 + (i * 41) % 170
            if name == "Sparkle burst":
                art = (
                    f'<g transform="translate({x} {y}) scale(.18) translate(-128 -128)">{body}</g>'
                )
            else:
                art = f'<g transform="translate({x} {y})">{body}</g>'
            layers.append(EffectLayer(f"{name} {i + 1}", art, motion, i / count, (x, y)))
        result.append(AnimatedObject(name, category, tuple(layers), 120))
    portal = ellipse(128, 128, 68, 99, "none").replace(
        "/>", ' stroke="#a49abc" stroke-width="13"/>'
    )
    result.append(
        AnimatedObject(
            "Magic portal",
            "Atmosphere & magic",
            (
                EffectLayer("Portal ring", portal, "pulse"),
                EffectLayer(
                    "Inner ring", portal.replace("68", "52").replace("99", "82"), "pulse", 0.5
                ),
            ),
            120,
        )
    )
    arcs = []
    for i in range(3):
        arcs.append(
            EffectLayer(
                f"Arc {i + 1}",
                path(
                    (
                        f"M{48 + i * 64} 26 L{25 + i * 64} 88 {61 + i * 64} 116 {27 + i * 64} "
                        f"183 {47 + i * 64} 233"
                    ),
                    "none",
                    "#a3bfca",
                    6,
                ),
                "sparkle",
                i / 3,
            )
        )
    result.append(AnimatedObject("Electric arcs", "Atmosphere & magic", tuple(arcs), 30))
    blades = "".join(
        (
            f'<g transform="rotate({i * 90} 128 100)">'
            f"{path('M128 99 L139 31 167 31 158 98Z', '#c6c6b4')}</g>"
        )
        for i in range(4)
    )
    result.append(
        AnimatedObject(
            "Windmill",
            "Moving mechanisms",
            (
                EffectLayer("Tower", path("M104 86 H152 L176 236 H80Z", "#a9aaa0")),
                EffectLayer("Blades", blades, "spin", pivot=(128, 100)),
                EffectLayer("Hub", ellipse(128, 100, 9, 9, "#666f72")),
            ),
            180,
        )
    )
    gear = radial(12, 76).replace("#acb7c0", "#88969d") + ellipse(128, 128, 30, 30, "#d7ddda")
    result.append(
        AnimatedObject(
            "Turning gear", "Moving mechanisms", (EffectLayer("Gear", gear, "spin"),), 120
        )
    )
    pendulum = path("M128 23 V191", "none", "#6a7781", 8) + ellipse(128, 195, 31, 31, "#b8a27a")
    result.append(
        AnimatedObject(
            "Pendulum",
            "Moving mechanisms",
            (
                EffectLayer("Pivot", ellipse(128, 23, 10, 10, "#a4aeb3")),
                EffectLayer("Bob and rod", pendulum, "swing", pivot=(128, 23)),
            ),
            120,
        )
    )
    flag = path("M74 31 Q118 7 160 31 T234 31 V122 Q194 98 160 122 T74 122Z", "#ad806d")
    result.append(
        AnimatedObject(
            "Flag in wind",
            "Moving mechanisms",
            (
                EffectLayer("Pole", rect(62, 22, 12, 213, "#89939b")),
                EffectLayer("Flag", flag, "wave"),
            ),
            90,
        )
    )
    return tuple(result)


def layer_values(layer: EffectLayer, phase: float) -> dict[str, float]:
    """Evaluate a bounded analytic pose; resetting travel is hidden at zero opacity."""
    t = (phase + layer.phase) % 1
    p = math.tau * (phase + layer.phase)
    if layer.motion == "flame":
        return {
            "transform.scale_x": 1 + 0.1 * math.sin(p * 3),
            "transform.scale_y": 1 + 0.13 * math.sin(p * 4 + 0.3),
            "transform.rotation": 4 * math.sin(p * 2),
        }
    if layer.motion in ("rise", "fall", "drip", "rain", "snow", "splash"):
        envelope = math.sin(math.pi * t) ** 2
        direction = -1 if layer.motion == "rise" else 1
        distance = 90 if layer.motion in ("rise", "fall", "drip") else 150
        x = 12 * math.sin(p) if layer.motion != "rain" else -25 * t
        y = direction * distance * (t - 0.5)
        if layer.motion == "splash":
            y = -65 * envelope
        return {"transform.x": x, "transform.y": y, "opacity": envelope}
    if layer.motion == "pulse":
        return {
            "transform.scale_x": 1 + 0.05 * math.sin(p),
            "transform.scale_y": 1 + 0.08 * math.sin(p),
        }
    if layer.motion == "sparkle":
        return {
            "opacity": 0.15 + 0.85 * math.sin(p / 2) ** 2,
            "transform.scale_x": 0.8 + 0.2 * math.sin(p / 2) ** 2,
            "transform.scale_y": 0.8 + 0.2 * math.sin(p / 2) ** 2,
        }
    if layer.motion == "spin":
        return {"transform.rotation": 360 * phase}
    if layer.motion == "swing":
        return {"transform.rotation": 24 * math.sin(p)}
    if layer.motion == "bob":
        return {"transform.y": 4 * math.sin(p), "transform.x": 5 * math.cos(p)}
    return {}
