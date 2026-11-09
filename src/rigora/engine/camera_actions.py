"""Deterministic 2D camera motion curves and original screen-space lens overlays."""

import math
import random

MOTION_PRESETS = {
    "pan_left": "Pan left",
    "pan_right": "Pan right",
    "rise": "Rise",
    "descend": "Descend",
    "push_in": "Push in",
    "pull_out": "Pull out",
    "handheld": "Handheld drift",
    "earthquake": "Earthquake",
    "impact": "Impact shake",
    "recoil": "Recoil",
    "zoom_pulse": "Zoom pulse",
    "sway": "Gentle sway",
    "dutch": "Dutch tilt",
    "whip": "Whip pan",
}
EFFECT_PRESETS = {
    "rain": "Rain on lens",
    "blood": "Blood at edges",
    "vignette": "Vignette",
    "dust": "Dust specks",
    "snow": "Snow flurries",
    "fog": "Fog wash",
    "letterbox": "Cinematic bars",
    "flash": "White flash",
    "blackout": "Blackout pulse",
    "whiteout": "Whiteout pulse",
    "scanlines": "Scanlines",
    "grain": "Film grain",
    "damage": "Damage pulse",
    "warm": "Warm wash",
    "cool": "Cool wash",
}


def motion_values(preset: str, t: float, speed: float, amount: float) -> dict[str, float]:
    """Return additive translation/rotation and multiplicative scale at normalized source time."""
    phase = min(1, t * speed)
    ease = phase * phase * (3 - 2 * phase)
    wave = math.sin(t * math.tau * speed * 3)
    envelope = math.sin(math.pi * t) ** 2
    x = y = rotation = 0.0
    zoom = 1.0
    if preset in ("pan_left", "pan_right", "rise", "descend", "whip"):
        distance = amount * 160 * ease
        if preset == "whip":
            distance = amount * 320 * (0.5 + 0.5 * math.tanh((phase - 0.5) * 12))
        x = (
            -distance
            if preset == "pan_left"
            else distance
            if preset in ("pan_right", "whip")
            else 0
        )
        y = -distance if preset == "rise" else distance if preset == "descend" else 0
    elif preset in ("push_in", "pull_out"):
        zoom = 1 + (0.3 if preset == "pull_out" else -0.25) * min(amount, 2) * ease
    elif preset == "dutch":
        rotation = amount * 12 * ease
    elif preset in ("handheld", "earthquake", "impact", "recoil"):
        frequency = 17 if preset in ("earthquake", "impact") else 4
        decay = (1 - t) ** 2 if preset in ("impact", "recoil") else envelope
        strength = 22 if preset == "earthquake" else 12 if preset == "impact" else 3
        x = amount * strength * math.sin(t * frequency * math.tau * speed) * decay
        y = amount * strength * 0.6 * math.sin(t * frequency * 1.37 * math.tau * speed) * decay
        rotation = amount * 1.2 * math.sin(t * frequency * 0.7 * math.tau * speed) * decay
        if preset == "recoil":
            y = -amount * 35 * math.sin(math.pi * min(1, t * 4)) * decay
    elif preset == "zoom_pulse":
        zoom = 1 - amount * 0.12 * envelope * (0.5 + 0.5 * wave)
    elif preset == "sway":
        x, rotation = amount * 10 * wave * envelope, amount * 2 * wave * envelope
    return {"x": x, "y": y, "rotation": rotation, "scale_x": zoom, "scale_y": zoom}


def lens_svg(
    effects: dict[str, float],
    seconds: float,
    width: float,
    height: float,
    speeds: dict[str, float] | None = None,
) -> str:
    """Generate bounded original vector overlays shared by camera preview and image export."""
    shapes: list[str] = []
    rng = random.Random(417)
    for kind, raw in effects.items():
        amount = min(1.0, max(0.0, raw))
        time = seconds * (speeds or {}).get(kind, 1)
        if amount <= 0 or kind not in EFFECT_PRESETS:
            continue
        items = []
        if kind in ("fog", "flash", "blackout", "whiteout", "warm", "cool", "damage"):
            color = {
                "fog": "#d4d8dc",
                "flash": "white",
                "blackout": "black",
                "whiteout": "white",
                "warm": "#e6a050",
                "cool": "#5088d8",
                "damage": "#a80000",
            }[kind]
            opacity = 0.35 if kind in ("fog", "warm", "cool") else 0.45 if kind == "damage" else 1
            if kind == "damage":
                opacity *= 0.5 + 0.5 * math.sin(time * math.tau * 2)
            items.append(
                f'<rect width="{width:g}" height="{height:g}" '
                f'fill="{color}" opacity="{opacity:g}"/>'
            )
        elif kind == "letterbox":
            bar = height * 0.12
            items.append(
                f'<path d="M0 0H{width:g}V{bar:g}H0Z '
                f'M0 {height - bar:g}H{width:g}V{height:g}H0Z" fill="black"/>'
            )
        elif kind == "vignette":
            items.append(
                '<defs><radialGradient id="rigora-camera-vignette" r=".7">'
                '<stop offset=".28" stop-color="black" stop-opacity="0"/>'
                '<stop offset="1" stop-color="black" stop-opacity=".85"/>'
                "</radialGradient></defs>"
                f'<rect width="{width:g}" height="{height:g}" '
                'fill="url(#rigora-camera-vignette)"/>'
            )
        elif kind == "scanlines":
            for i in range(80):
                y = height * i / 80
                items.append(
                    f'<path d="M0 {y:g}H{width:g}" stroke="black" '
                    f'stroke-width="{height / 240:g}" opacity=".28"/>'
                )
        else:
            for _ in range(192 if kind == "grain" else 24):
                x, y, size = (
                    rng.random() * width,
                    rng.random() * height,
                    (1 + rng.random() * 4) * min(width, height) / 400,
                )
                if kind == "rain":
                    y = (y + time * height * 0.07) % height
                    items.append(
                        f'<ellipse cx="{x:g}" cy="{y:g}" rx="{size:g}" ry="{size * 2:g}" '
                        'fill="#b9d9eb" fill-opacity=".18" stroke="#dae9f4" stroke-opacity=".4"/>'
                    )
                elif kind == "blood":
                    edge = rng.randrange(4)
                    x = x if edge < 2 else width * rng.choice((0.02, 0.98))
                    y = height * (0.025 if edge == 0 else 0.975) if edge < 2 else y
                    items.append(
                        f'<ellipse cx="{x:g}" cy="{y:g}" rx="{size * 5:g}" ry="{size * 3:g}" '
                        'fill="#940b16" opacity=".65"/>'
                    )
                else:
                    if kind == "snow":
                        y = (y + time * height * 0.12) % height
                    if kind == "grain":
                        x = (x + int(time * 12) * 17) % width
                    items.append(
                        f'<circle cx="{x:g}" cy="{y:g}" '
                        f'r="{size * (0.3 if kind == "grain" else 1):g}" '
                        f'fill="{"#c6bda7" if kind == "dust" else "white"}" opacity=".4"/>'
                    )
        shapes.append(f'<g opacity="{amount:g}">{"".join(items)}</g>')
    return "".join(shapes)
