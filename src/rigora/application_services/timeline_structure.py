"""Describe row structure without including sampled values, mesh coordinates or key arrays."""

from typing import Any

from rigora.domain.entities import ENTITY_COLLECTIONS, Timeline, nested_records
from rigora.domain.project import Scene


def row_structure(scene: Scene | None, timeline: Timeline | None) -> tuple[Any, ...]:
    """Return immutable descriptors for hierarchy/channel layout, not per-frame values."""
    if scene is None:
        return ()
    owners = nested_records(
        tuple(
            getattr(scene, field)
            for field in ENTITY_COLLECTIONS
            if field not in ("timelines", "clips")
        )
    )
    return (
        scene.id,
        tuple(
            (
                type(record),
                record.id,
                record.name,
                *(
                    getattr(record, field, None)
                    for field in (
                        "parent_id",
                        "owner_id",
                        "object_id",
                        "asset_id",
                        "kind",
                        "visible",
                        "locked",
                    )
                ),
                record.extra,
            )
            for record in owners
        ),
        tuple(
            (
                track.id,
                track.name,
                track.owner_id,
                track.property_path,
                track.blend_mode,
                track.visible,
                track.locked,
                track.extra,
            )
            for track in timeline.tracks
        )
        if timeline
        else (),
    )
