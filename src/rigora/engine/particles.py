"""Stateless seeded particles whose world-space birth transforms are sampled at emission time."""

import math
import random
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from rigora.domain.geometry import Matrix, transform_point
from rigora.domain.project import ProjectError, Scene
from rigora.engine.sampling import number
from rigora.engine.state import NodePose


@dataclass(frozen=True, slots=True)
class Particle:
    """One original vector primitive in world space, ready for every renderer/output adapter."""

    matrix: Matrix
    color: str
    opacity: float
    shape: str = "circle"


def emitter_settings(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Validate bounded authoring parameters before simulation or package evaluation."""
    if not isinstance(raw, Mapping) or type(raw.get("world_space", True)) is not bool:
        raise ProjectError("Particle metadata must be an object with a boolean World space toggle.")
    values = {
        k: number(raw.get(k, default))
        for k, default in dict(
            start=0,
            end=240,
            rate=20,
            lifetime=1,
            speed=80,
            spread=35,
            angle=-90,
            gravity=100,
            size=5,
            seed=0,
            burst=0,
            ground_y=1080,
            bounce=0.5,
            friction=0.1,
            magnet_x=960,
            magnet_y=540,
            magnet_radius=300,
            magnet_strength=200,
        ).items()
    }
    if not (
        0 <= values["start"] <= values["end"] <= 1e7
        and 0 <= values["rate"] <= 1000
        and 0.01 <= values["lifetime"] <= 60
        and 0 <= values["speed"] <= 10000
        and 0 <= values["spread"] <= 360
        and abs(values["gravity"]) <= 10000
        and 0 < values["size"] <= 1000
        and 0 <= values["burst"] <= 2048
        and values["burst"] == int(values["burst"])
        and abs(values["seed"]) <= 2**31
        and values["seed"] == int(values["seed"])
        and abs(values["ground_y"]) <= 1e6
        and 0 <= values["bounce"] <= 1
        and 0 <= values["friction"] <= 1
        and abs(values["magnet_x"]) <= 1e6
        and abs(values["magnet_y"]) <= 1e6
        and 0 < values["magnet_radius"] <= 1e6
        and abs(values["magnet_strength"]) <= 10000
    ):
        raise ProjectError(
            "Particle settings exceed supported emission, lifetime or motion bounds."
        )
    if values["rate"] * values["lifetime"] + values["burst"] > 2048:
        raise ProjectError("Each emitter supports at most 2048 simultaneously alive particles.")
    color = raw.get("color", "#ffffff")
    shape = raw.get("shape", "circle")
    physics = {k: raw.get(k, False) for k in ("ground_enabled", "magnet_enabled")}
    if any(type(v) is not bool for v in physics.values()):
        raise ProjectError("Particle ground and magnet toggles must be booleans.")
    if any(physics.values()) and not raw.get("world_space", True):
        raise ProjectError("Enable World space before using ground collision or magnets.")
    if (
        not isinstance(color, str)
        or re.fullmatch(r"#[a-fA-F0-9]{6}", color) is None
        or shape not in ("circle", "square")
    ):
        raise ProjectError("Particles need a #RRGGBB color and Circle/Square primitive.")
    return {
        **values,
        "color": color,
        "shape": shape,
        "world_space": raw.get("world_space", True),
        **physics,
    }


def particle_physics(
    x: float,
    y: float,
    vx: float,
    vy: float,
    age: float,
    radius: float,
    settings: Mapping[str, Any],
) -> tuple[float, float]:
    """Reconstruct one trajectory with 120 Hz fixed steps and a final fractional step.

    The static world-space ground plane includes particle radius; magnets use bounded
    linear falloff, avoiding a singular force at their center. No seek history is kept.
    """
    floor = settings["ground_y"] - radius
    if settings["ground_enabled"]:
        y = min(y, floor)
    steps = math.ceil(age * 120)
    for index in range(steps):
        dt = min(1 / 120, max(0, age - index / 120))
        ax, ay = 0.0, settings["gravity"]
        if settings["magnet_enabled"]:
            dx, dy = settings["magnet_x"] - x, settings["magnet_y"] - y
            distance = math.hypot(dx, dy)
            if 1e-9 < distance < settings["magnet_radius"]:
                force = settings["magnet_strength"] * (1 - distance / settings["magnet_radius"])
                ax, ay = force * dx / distance, ay + force * dy / distance
        vx, vy = vx + ax * dt, vy + ay * dt
        x, y = x + vx * dt, y + vy * dt
        if settings["ground_enabled"] and y > floor:
            y = floor
            if vy > 0:
                vy = -vy * settings["bounce"]
                vx *= 1 - settings["friction"]
    return x, y


def sample_particles(
    scene: Scene,
    frame: float,
    nodes: Mapping[str, NodePose],
    sample: Callable[[float], Sequence[NodePose]],
    *,
    scope: frozenset[str] | None = None,
) -> dict[str, tuple[Particle, ...]]:
    """Reconstruct living particles independently of seek and output order."""
    result = {}
    total = 0
    physics_steps = 0
    for obj in scene.objects:
        if (
            "particle_emitter" not in obj.extra
            or obj.id not in nodes
            or scope is not None
            and obj.id not in scope
        ):
            continue
        settings = emitter_settings(obj.extra["particle_emitter"])
        fps, node = scene.settings.fps, nodes[obj.id]
        start, end, life, rate = (settings[k] for k in ("start", "end", "lifetime", "rate"))
        births = [(i, start) for i in range(int(settings["burst"]))]
        if rate and frame >= start:
            first = max(0, math.floor((frame - life * fps - start) * rate / fps))
            last = math.floor((min(frame, end) - start) * rate / fps)
            births.extend((i + 2048, start + i * fps / rate) for i in range(first, last + 1))
        particles = []
        for identity, birth in births:
            age = (frame - birth) / fps
            if not 0 <= age < life:
                continue
            born = (
                next((n for n in sample(birth) if n.id == obj.id), None)
                if settings["world_space"]
                else node
            )
            if born is None or not born.visible:
                continue
            rng = random.Random(int(settings["seed"]) * 1000003 + identity)
            angle = math.radians(settings["angle"] + (rng.random() - 0.5) * settings["spread"])
            speed = settings["speed"] * (0.75 + 0.5 * rng.random())
            dx, dy = math.cos(angle) * speed * age, math.sin(angle) * speed * age
            origin = born.world_matrix
            x, y = transform_point(origin, dx, dy)
            y += 0.5 * settings["gravity"] * age * age
            size = settings["size"]
            if settings["ground_enabled"] or settings["magnet_enabled"]:
                physics_steps += math.ceil(age * 120)
                if physics_steps > 200000:
                    raise ProjectError(
                        "Particle physics exceeds its frame budget. "
                        "Reduce particle count or lifetime."
                    )
                radius = size * (
                    math.hypot(origin[1], origin[3])
                    if settings["shape"] == "circle"
                    else abs(origin[1]) + abs(origin[3])
                )
                vx, vy = math.cos(angle) * speed, math.sin(angle) * speed
                x, y = particle_physics(
                    origin[4],
                    origin[5],
                    origin[0] * vx + origin[2] * vy,
                    origin[1] * vx + origin[3] * vy,
                    age,
                    radius,
                    settings,
                )
            matrix = (*[v * size for v in origin[:4]], x, y)
            particles.append(
                Particle(matrix, settings["color"], max(0, 1 - age / life), settings["shape"])
            )
        total += len(particles)
        if total > 8192:
            raise ProjectError("Scene particles exceed the 8192 live-primitive evaluation budget.")
        result[obj.id] = tuple(particles)
    return result
