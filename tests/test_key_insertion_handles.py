"""Inserting pose keys into dense authored curves keeps Bézier segments evaluable."""

import math

import pytest

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.domain.entities import Bone, Keyframe, Track
from rigora.engine.sampling import CompiledTrack


@pytest.mark.parametrize("frame", (0.1, 1, 7, 9.9))
def test_insert_contracts_overlapping_time_handles_and_preserves_other_keys(frame):
    left = Keyframe(frame=0, value=0, interpolation="bezier", tangent_out=(8, 4))
    right = Keyframe(frame=10, value=10, interpolation="bezier", tangent_in=(-1, -2))
    source = Track(owner_id=Bone().id, property_path="transform.rotation", keyframes=(left, right))
    changed = AnimationEditingService.keyed_track(source, frame, 5, "bezier")
    compiled = CompiledTrack(changed)
    assert compiled.sample(frame) == pytest.approx(5)
    assert compiled.sample(0) == 0 and compiled.sample(10) == 10
    assert all(math.isfinite(compiled.sample(i / 100)) for i in range(1001))
    first, _, last = changed.keyframes
    assert first.id == left.id and last.id == right.id
    assert source.keyframes == (left, right)
    assert first.tangent_out[1] / first.tangent_out[0] == pytest.approx(0.5)
    assert last.tangent_in[1] / last.tangent_in[0] == pytest.approx(2)
