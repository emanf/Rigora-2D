"""Canonical back-to-front artwork order before independent depth offsets are applied."""

from rigora.domain.project import Scene


def scene_draw_order(scene: Scene) -> tuple[str, ...]:
    """Resolve layers and optional explicit ranks, preserving insertion order for ties.

    Importers use this base order before appending new artwork so existing
    arrangements stay intact and new entries appear in front at equal depth.
    """
    layers = {layer.id: layer.order for layer in scene.layers}
    explicit = {key: index for index, key in enumerate(scene.draw_order)}
    complete = {obj.id for obj in scene.objects} <= explicit.keys()
    return tuple(
        obj.id
        for obj in sorted(
            scene.objects,
            key=lambda obj: (
                0 if complete else layers.get(obj.layer_id or "", 0),
                obj.id in explicit,
                explicit.get(obj.id, 0),
            ),
        )
    )
