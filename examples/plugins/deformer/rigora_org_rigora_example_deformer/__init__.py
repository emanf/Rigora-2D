"""Original sine displacement operating on immutable geometric engine inputs."""

import math

from rigora.engine.deformation import DeformationContext
from rigora.sdk import PluginContext


def wave(context: DeformationContext):
    """Return a fresh local-space mesh with a finite, animatable vertical sine displacement."""
    amount = context.scalar("amount", 12)
    return tuple((x, y + math.sin(x / 40) * amount) for x, y in context.points)


def register(context: PluginContext) -> None:
    """Publish the geometric solver and its numeric parameter defaults."""
    context.register(
        "deformers",
        context.manifest.id + ".wave",
        "Sine wave",
        wave,
        parameters={"amount": 12.0},
        icon="waves",
    )
