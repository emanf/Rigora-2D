"""Timeline layout invalidation ignores values while preserving structural editing changes."""

from dataclasses import replace

from rigora.application_services.timeline_structure import row_structure
from rigora.domain.entities import Keyframe, SceneObject, Timeline, Track, Transform
from rigora.domain.project import Scene


def test_transform_and_key_values_do_not_rebuild_channel_structure():
    owner = SceneObject(name="Actor")
    track = Track(
        owner_id=owner.id, property_path="transform.x", keyframes=(Keyframe(frame=0, value=1),)
    )
    timeline = Timeline(tracks=(track,))
    scene = Scene(objects=(owner,), timelines=(timeline,))
    initial = row_structure(scene, timeline)
    moved = replace(scene, objects=(replace(owner, transform=Transform(x=20)),))
    keyed = replace(
        timeline, tracks=(replace(track, keyframes=(replace(track.keyframes[0], value=40),)),)
    )
    assert row_structure(moved, keyed) == initial
    renamed = replace(moved, objects=(replace(owner, name="Renamed"),))
    assert row_structure(renamed, keyed) != initial
    locked = replace(timeline, tracks=(replace(track, locked=True),))
    assert row_structure(scene, locked) != initial
