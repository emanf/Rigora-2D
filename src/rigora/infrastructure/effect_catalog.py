"""Original normalized lattice clips and physical follow-through settings, independent of art."""

import math
from typing import Any

from rigora.domain.content import ContentItem
from rigora.infrastructure.motion_catalog import item


def ffd_presets() -> tuple[ContentItem, ...]:
    """Create editable FFD clips with complete lattices and seamless periodic endpoints."""
    loops = (
        "Soft breathing",
        "Squash and stretch",
        "Jelly wobble",
        "Horizontal ripple",
        "Vertical ripple",
        "Flag wave",
        "Top sway",
        "Bottom sway",
        "Inflate pulse",
        "Twist",
        "Rubber bounce",
        "Heartbeat",
        "Shiver",
        "Pendulum sway",
    )
    gestures = (
        "Pop in",
        "Bounce in",
        "Stretch in",
        "Collapse out",
        "Anticipation",
        "Impact settle",
    )
    result = []
    for name in (*loops, *gestures):
        loop = name in loops
        frames = []
        for index in range(33):
            t = index / 32
            p = t * math.tau
            wave = math.sin(p)
            envelope = math.sin(math.pi * t) ** 2
            controls = []
            for row in range(4):
                for column in range(4):
                    x, y = column / 3 - 0.5, row / 3 - 0.5
                    dx = dy = 0.0
                    if name == "Soft breathing":
                        dx, dy = x * 0.035 * (1 - math.cos(p)), y * 0.018 * (1 - math.cos(p))
                    elif name == "Squash and stretch":
                        dx, dy = x * 0.16 * wave, -y * 0.16 * wave
                    elif name == "Jelly wobble":
                        dx, dy = (
                            0.075 * math.sin(p - row * 0.65) * math.sin(math.pi * t) ** 2,
                            y * 0.04 * wave,
                        )
                    elif name == "Horizontal ripple":
                        dx = 0.08 * math.sin(p + row * 1.3) * envelope
                    elif name == "Vertical ripple":
                        dy = 0.07 * math.sin(p + column * 1.3) * envelope
                    elif name == "Flag wave":
                        dy = 0.12 * (x + 0.5) * math.sin(p - column * 0.7) * envelope
                    elif name == "Top sway":
                        dx = 0.12 * (0.5 - y) ** 2 * wave
                    elif name == "Bottom sway":
                        dx = 0.12 * (y + 0.5) ** 2 * wave
                    elif name == "Inflate pulse":
                        dx, dy = x * 0.16 * envelope, y * 0.16 * envelope
                    elif name == "Twist":
                        dx, dy = y * 0.12 * wave, x * 0.06 * wave
                    elif name == "Rubber bounce":
                        dx, dy = (
                            x * 0.1 * math.sin(p * 2),
                            -y * 0.13 * math.sin(p * 2) - 0.05 * envelope,
                        )
                    elif name == "Heartbeat":
                        dx, dy = (
                            x * 0.07 * math.sin(p * 2) * envelope,
                            y * 0.07 * math.sin(p * 2) * envelope,
                        )
                    elif name == "Shiver":
                        dx = 0.025 * math.sin(p * 4 + row * 0.3) * envelope
                    elif name == "Pendulum sway":
                        dx = 0.15 * (y + 0.5) * wave
                    elif name == "Pop in":
                        dx, dy = (
                            x * (-0.85 * (1 - t) ** 3 + 0.12 * math.sin(p * 2) * envelope),
                            y * (-0.85 * (1 - t) ** 3 + 0.12 * math.sin(p * 2) * envelope),
                        )
                    elif name == "Bounce in":
                        dy = -((1 - t) ** 3) * 0.55 + 0.09 * math.sin(p * 2) * envelope
                    elif name == "Stretch in":
                        dx, dy = -x * 0.7 * (1 - t) ** 3, y * 0.5 * (1 - t) ** 3
                    elif name == "Collapse out":
                        dx, dy = -x * 0.9 * t**3, -y * 0.9 * t**3
                    elif name == "Anticipation":
                        dx, dy = x * 0.16 * envelope, -y * 0.2 * envelope
                    elif name == "Impact settle":
                        dx, dy = (
                            x * 0.18 * math.sin(p * 2) * math.exp(-t * 5) * envelope,
                            -y * 0.22 * math.sin(p * 2) * math.exp(-t * 5) * envelope,
                        )
                    controls.append([dx, dy])
            frames.append([t * 48, controls])
        if loop:
            frames[-1][1] = frames[0][1]
        result.append(
            item(
                name,
                "deformation",
                "FFD motions",
                {
                    "kind": "ffd",
                    "columns": 4,
                    "rows": 4,
                    "strength": 1,
                    "motion": {"fps": 30, "duration": 48, "frames": frames, "loop": loop},
                    "fallback_mesh": True,
                },
                source_format="FFD",
                tags=("ffd", "elastic", "editable", "loop" if loop else "one-shot"),
                description=(
                    "Normalized, editable lattice animation. Drop onto artwork to deform "
                    "it; empty space creates a deformable demonstration Object. Original "
                    "vectors stay sharp."
                ),
            )
        )
    for name in ("Bend left", "Bend right", "Taper top", "Taper bottom", "Pinch center", "Inflate"):
        points = []
        for row in range(4):
            for column in range(4):
                x, y = column / 3 - 0.5, row / 3 - 0.5
                dx = dy = 0.0
                if name.startswith("Bend"):
                    dx = (1 if name == "Bend right" else -1) * 0.2 * (0.5 - y) ** 2
                elif name == "Taper top":
                    dx = -x * 0.5 * (0.5 - y)
                elif name == "Taper bottom":
                    dx = -x * 0.5 * (0.5 + y)
                elif name == "Pinch center":
                    dx = -x * 0.4 * (1 - abs(y) * 2)
                else:
                    dx, dy = x * 0.15, y * 0.15
                points.append([dx, dy])
        result.append(
            item(
                name,
                "deformation",
                "FFD shapes",
                {
                    "kind": "ffd",
                    "columns": 4,
                    "rows": 4,
                    "shape": points,
                    "fallback_mesh": True,
                },
                source_format="FFD",
                tags=("ffd", "shape", "editable"),
            )
        )
    return tuple(result)


def spring_presets() -> tuple[ContentItem, ...]:
    """Describe live physics configurations; these are constraints, never raster animation."""
    profiles = (
        ("Soft follow", 1.8, 0.65, 0.7, 0, 0),
        ("Light bounce", 3.2, 0.24, 0.5, 0, 0),
        ("Heavy bounce", 1.3, 0.4, 1.6, 0, 0),
        ("Rubber follow", 1.6, 0.15, 1.2, 0, 0.2),
        ("Quick settle", 6, 0.9, 0.45, 0, 0),
        ("Slow settle", 0.8, 0.5, 1.1, 0, 0),
        ("Strong oscillation", 2.3, 0.12, 1.1, 0, 0),
        ("Stiff response", 7, 1, 0.35, 0, 0),
        ("Hair soft", 2.1, 0.48, 0.8, 50, 0),
        ("Hair lively", 3.6, 0.22, 0.6, 30, 0),
        ("Long ponytail", 1.5, 0.42, 1.1, 110, 0),
        ("Tail follow", 2, 0.36, 1, 0, 0),
        ("Tail lively", 3.8, 0.2, 0.7, 0, 0),
        ("Floppy ears", 2.3, 0.3, 0.65, 90, 0),
        ("Cloth hem", 2.7, 0.5, 0.8, 160, 0.04),
        ("Cape follow", 1.4, 0.52, 1.2, 220, 0.06),
        ("Leaf flutter", 5, 0.25, 0.3, -20, 0),
        ("Branch sway", 1.2, 0.28, 1, 0, 0),
        ("Hanging rope", 1.8, 0.48, 1.4, 300, 0.08),
        ("Elastic antenna", 4.3, 0.19, 0.45, 0, 0.12),
    )
    result = []
    for name, frequency, damping, inertia, gravity, stretch in profiles:
        parameters: dict[str, Any] = {
            "frequency": frequency,
            "damping": damping,
            "inertia": inertia,
            "gravity": gravity,
            "stretch": stretch,
            "squash": stretch * 0.5,
            "strength": 1,
            "max_angle": 55,
            "rotate": True,
            "translate": False,
            "enabled": True,
        }
        result.append(
            item(
                name,
                "spring",
                "Spring dynamics",
                {
                    "parameters": parameters,
                    "fallback_rig": "chain",
                },
                source_format="SPRING",
                tags=("spring", "physics", "secondary", "editable"),
                description=(
                    "Live bone follow-through. Drop onto a bone to affect its chain, or "
                    "onto a rig's secondary bones. Empty space creates an animated flexible"
                    " chain; existing motion stays editable."
                ),
            )
        )
    return tuple(result)
