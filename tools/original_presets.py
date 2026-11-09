"""Original CC0 motion and lattice recipes; no proprietary templates or captured animation data."""

import math
from collections.abc import Callable
from dataclasses import replace

from rigora.domain.entities import Skeleton


def extend_library(add: Callable[..., None], rigs: dict[str, Skeleton]) -> None:
    """Append explicit rig proportions, differentiated procedural gaits and normalized FFD
    recipes.
    """
    biped, quadruped = rigs["biped"], rigs["quadruped"]
    for name, source, height, body in (
        ("Tall human", biped, 1.25, 1.0),
        ("Compact human", biped, 0.8, 1.0),
        ("Fantasy long-limbed biped", biped, 1.5, 1.0),
        ("Cat structure", quadruped, 0.7, 0.8),
        ("Deer structure", quadruped, 1.5, 0.9),
        ("Lizard structure", quadruped, 0.45, 1.3),
    ):
        scale = {
            b.id: (
                height
                if any(s in b.name for s in ("thigh", "shin", "upper", "lower", "arm"))
                else body
            )
            for b in source.bones
        }
        bones = tuple(
            replace(
                b,
                length=b.length * scale[b.id],
                transform=replace(b.transform, x=b.transform.x * scale.get(b.parent_id or "", 1)),
            )
            for b in source.bones
        )
        custom = replace(source, name=name, bones=bones)
        add(
            name,
            "rig",
            "Human rigs" if source is biped else "Quadruped rigs",
            {"skeleton": custom.to_dict()},
            (source.extra["anatomy"], "original", "template"),
            "Original editable proportions with compatible semantic landmarks. "
            "Supply your own artwork.",
        )
    styles = (
        ("Natural", 24, 25, 30, 0, 3),
        ("Brisk", 20, 32, 42, -5, 4),
        ("Relaxed", 34, 18, 23, 3, 2),
        ("Heavy", 32, 23, 25, -8, 6),
        ("Happy", 22, 30, 38, -2, 8),
        ("Sneaky", 36, 22, 58, -18, 2),
        ("Zombie", 38, 15, 12, -10, 2),
        ("Robot", 26, 22, 20, 0, 0),
        ("Bouncy", 22, 32, 48, 0, 13),
        ("Heroic", 24, 35, 40, -6, 5),
        ("Tired", 40, 14, 20, -20, 2),
        ("Tiptoe", 30, 20, 55, -4, 2),
        ("Comic", 26, 48, 65, 10, 10),
        ("Angry", 20, 38, 35, -12, 6),
        ("Confident", 26, 30, 32, 5, 4),
    )
    for style, duration, stride, knee, lean, bounce in styles:
        for running in (False, True):
            length = duration * (0.65 if running else 1)
            stride_value = stride * (1.45 if running else 1)
            channels: dict[tuple[str, str], list[list[float]]] = {}
            for i in range(17):
                phase = i / 16 * math.tau
                swing = math.sin(phase)
                if style == "Robot":
                    swing = round(swing * 2) / 2
                values = {
                    ("hips", "y"): biped.bones[0].transform.y
                    - abs(math.sin(phase)) * bounce * (1.8 if running else 1),
                    ("spine", "rotation"): -90
                    + lean
                    - (8 if running else 0)
                    + math.sin(phase * 2) * 2,
                    ("thigh.L", "rotation"): 90 + swing * stride_value,
                    ("thigh.R", "rotation"): 90 - swing * stride_value,
                    ("shin.L", "rotation"): -max(0, -swing) * knee * (1.5 if running else 1),
                    ("shin.R", "rotation"): -max(0, swing) * knee * (1.5 if running else 1),
                    ("upper_arm.L", "rotation"): 180 - swing * stride_value * 0.75,
                    ("upper_arm.R", "rotation"): 180 + swing * stride_value * 0.75,
                    ("forearm.L", "rotation"): -65 if running else -15 - max(0, swing) * 15,
                    ("forearm.R", "rotation"): -65 if running else -15 - max(0, -swing) * 15,
                }
                if style == "Zombie":
                    values["upper_arm.L", "rotation"] = 90 + swing * 4
                    values["upper_arm.R", "rotation"] = 90 - swing * 4
                for channel, value in values.items():
                    channels.setdefault(channel, []).append([i / 16 * length, value])
            action = "run" if running else "walk"
            add(
                f"{style} {action}",
                "action",
                "Human runs" if running else "Human walks",
                {
                    "anatomy": "biped",
                    "fps": 24,
                    "duration": length,
                    "loop": True,
                    "channels": [
                        {"semantic": s, "path": p, "keys": keys}
                        for (s, p), keys in channels.items()
                    ],
                },
                ("human", "biped", action, style.lower(), "original", "procedural", "in-place"),
                "Original hand-designed procedural gait starting point. "
                "In-place, editable scalar keys; "
                "not motion capture. Retarget using compatible semantic names.",
            )
    for name, amount, lean in (
        ("Calm breathing", 2, 0),
        ("Alert standing", 1, -3),
        ("Restless idle", 5, 2),
        ("Exhausted idle", 7, -15),
        ("Confident standing", 2, 8),
        ("Nervous idle", 4, -5),
    ):
        add(
            name,
            "action",
            "Human idle & stand",
            {
                "anatomy": "biped",
                "fps": 24,
                "duration": 47,
                "loop": True,
                "channels": [
                    {
                        "semantic": "spine",
                        "path": "rotation",
                        "keys": [[0, -90 + lean], [23.5, -90 + lean + amount], [47, -90 + lean]],
                    },
                    {
                        "semantic": "head",
                        "path": "rotation",
                        "keys": [[0, 0], [23.5, -amount / 2], [47, 0]],
                    },
                ],
            },
            ("biped", "human", "idle", "standing", "original"),
            "Original keyed standing/idle performance.",
        )
    for name, kind, amount in (
        ("Standing jump", "jump", 100),
        ("High jump", "jump", 180),
        ("Comic hop", "jump", 65),
        ("Wall climb", "climb", 140),
        ("Ladder climb", "climb", 90),
    ):
        channels = []
        for semantic, base, swing in (
            ("thigh.L", 90, 45),
            ("thigh.R", 90, -45),
            ("shin.L", 0, -65),
            ("shin.R", 0, -45),
            ("upper_arm.L", 180, -130),
            ("upper_arm.R", 180, -100),
        ):
            values = [
                [0, base],
                [6, base + swing * 0.4],
                [12, base + swing],
                [18, base + swing * 0.3],
                [24, base],
            ]
            channels.append({"semantic": semantic, "path": "rotation", "keys": values})
        channels.append(
            {
                "semantic": "hips",
                "path": "y",
                "keys": [
                    [0, 270],
                    [6, 280],
                    [12, 270 - amount],
                    [18, 270 - amount * 0.7],
                    [24, 270 if kind == "jump" else 270 - amount],
                ],
            }
        )
        add(
            name,
            "action",
            "Jumps & climbing",
            {
                "anatomy": "biped",
                "fps": 24,
                "duration": 24,
                "loop": kind == "jump",
                "channels": channels,
            },
            ("human", "biped", kind, "original"),
            "Original editable keyed performance. Place against your scene; "
            "no automatic wall contacts or collision solving.",
        )
    for name, phase_offset, amplitude, duration in (
        ("Quadruped walk", math.pi, 23, 32),
        ("Quadruped trot", 0, 32, 22),
        ("Quadruped gallop", 0.6, 48, 16),
        ("Quadruped idle", math.pi, 2, 48),
        ("Quadruped jump", 0, 60, 24),
        ("Low stalking", math.pi, 16, 40),
        ("Excited prance", 0, 38, 20),
        ("Slow lumber", math.pi, 20, 42),
    ):
        channels = []
        for limb in ("front", "rear"):
            for side in ("L", "R"):
                semantic = f"{limb}.upper.{side}"
                original = next(b.transform.rotation for b in quadruped.bones if b.name == semantic)
                phase = (math.pi if side == "R" else 0) + (phase_offset if limb == "rear" else 0)
                keys = [
                    [i / 16 * duration, original + math.sin(i / 16 * math.tau + phase) * amplitude]
                    for i in range(17)
                ]
                channels.append({"semantic": semantic, "path": "rotation", "keys": keys})
                channels.append(
                    {
                        "semantic": f"{limb}.lower.{side}",
                        "path": "rotation",
                        "keys": [
                            [
                                i / 16 * duration,
                                -max(0, math.sin(i / 16 * math.tau + phase)) * amplitude,
                            ]
                            for i in range(17)
                        ],
                    }
                )
        add(
            name,
            "action",
            "Animal motions",
            {
                "anatomy": "quadruped",
                "fps": 24,
                "duration": duration,
                "loop": True,
                "channels": channels,
            },
            ("quadruped", "animal", "original", "procedural", "in-place"),
            "Original editable quadruped phase recipe for compatible semantic rigs.",
        )
    shapes = (
        "Squash",
        "Stretch",
        "Bulge",
        "Hourglass",
        "Lean left",
        "Lean right",
        "Wave left",
        "Wave right",
        "Twist",
        "Taper top",
        "Taper bottom",
        "Taper left",
        "Taper right",
        "Arch",
        "Bowl",
        "Perspective left",
        "Perspective right",
        "Perspective top",
        "Perspective bottom",
        "Pinch top",
        "Pinch bottom",
        "Slant",
        "Inflate",
        "Deflate",
    )
    for index, name in enumerate(shapes):
        shape = lattice_shape(index, 0.16)
        add(
            f"FFD · {name}",
            "deformation",
            "FFD shapes",
            {"kind": "ffd", "columns": 3, "rows": 3, "shape": shape},
            ("ffd", "shape", "original", name.lower()),
            "Original normalized editable 3×3 lattice shape. "
            "Adapts to the selected artwork bounds.",
        )
    motions = (
        "Breathing",
        "Panting",
        "Angry pulse",
        "Doze off",
        "Anticipation",
        "Jump bounce",
        "Squash stretch",
        "Jelly wobble",
        "Rubber recoil",
        "Heartbeat",
        "Shiver",
        "Sway",
        "Laugh",
        "Sneeze",
        "Surprised",
        "Soft landing",
        "Wave ripple",
        "Elastic pop",
    )
    for index, name in enumerate(motions):
        duration = 48 if index in (0, 3, 11) else 24
        frames = []
        for i in range(17):
            t = i / 16
            envelope = math.sin(math.pi * t) ** 2
            amount = 0.08 if index in (0, 1, 9) else 0.2
            pulse = math.sin(math.tau * t * (1 + index % 3))
            if index in (8, 17):
                pulse = math.sin(math.tau * t * 3) * math.exp(-3 * t)
            frames.append(
                [t * duration, lattice_shape(index % len(shapes), amount * pulse * envelope)]
            )
        add(
            f"FFD motion · {name}",
            "deformation",
            "FFD motions",
            {
                "kind": "ffd",
                "columns": 3,
                "rows": 3,
                "motion": {"fps": 24, "duration": duration, "frames": frames},
            },
            ("ffd", "animated", "original", name.lower()),
            "Original normalized keyed FFD motion. Layers with bone animation; "
            "adjust speed, repeats and strength before applying.",
        )


def lattice_shape(kind: int, amount: float) -> list[list[float]]:
    """Compute an original shape in normalized lattice space without any proprietary data."""
    result = []
    for row in range(3):
        for column in range(3):
            x, y = column / 2 - 0.5, row / 2 - 0.5
            modes = (
                (x * amount, -y * amount),
                (-x * amount, y * amount),
                (x * amount * (1 - 4 * y * y), 0),
                (-x * amount * (1 - 4 * y * y), 0),
                (-amount * (0.5 - y), 0),
                (amount * (0.5 - y), 0),
                (amount * math.sin((y + 0.5) * math.pi), 0),
                (-amount * math.sin((y + 0.5) * math.pi), 0),
                (-y * amount, x * amount),
                (-x * amount * (0.5 - y), 0),
                (-x * amount * (0.5 + y), 0),
                (0, -y * amount * (0.5 - x)),
                (0, -y * amount * (0.5 + x)),
                (0, -amount * (1 - 4 * x * x)),
                (0, amount * (1 - 4 * x * x)),
                (0, y * amount * x * 2),
                (0, -y * amount * x * 2),
                (x * amount * y * 2, 0),
                (-x * amount * y * 2, 0),
                (-x * amount * (0.5 - y) ** 2, 0),
                (-x * amount * (0.5 + y) ** 2, 0),
                (y * amount, 0),
                (x * amount, y * amount),
                (-x * amount, -y * amount),
            )
            result.append(list(modes[kind % len(modes)]))
    return result
