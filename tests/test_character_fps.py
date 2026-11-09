"""Reusable recipe cycles retain their period across scene frame-rate conversion."""

import json
from dataclasses import replace

import pytest

from rigora.application_services.character_creation import CharacterCreationService, build_character
from rigora.application_services.documents import DocumentService
from rigora.domain.character_recipe import CharacterRecipe
from rigora.domain.project import SceneSettings
from rigora.engine.time import FrameRange


@pytest.fixture(scope="module")
def cycle():
    return build_character(CharacterRecipe(motions=("Walk", "Run", "Sprint")))


@pytest.mark.parametrize("fps", (24, 60))
@pytest.mark.parametrize("legacy_metadata", (False, True))
def test_import_preserves_period_and_repeating_pose(cycle, fps, legacy_metadata):
    payload = json.loads(cycle.files["character.json"])
    source = payload["scenes"][0]
    expected = {
        c["name"]: FrameRange(
            c["in_frame"], c["out_frame"], source["settings"]["fps"]
        ).duration_seconds
        for c in source["clips"]
    }
    if legacy_metadata:
        for clip in source["clips"]:
            clip.pop("continuous_loop", None)
    built = replace(cycle, files={**cycle.files, "character.json": json.dumps(payload).encode()})
    doc = DocumentService()
    doc.new(settings=SceneSettings(fps=fps))
    CharacterCreationService(doc).create(built)
    for clip in doc.scene.clips:
        doc.select_animation_clip(clip.id)
        assert clip.extra["continuous_loop"]
        assert doc.animation.playback.range.duration_seconds == pytest.approx(expected[clip.name])
        middle = doc.animation.evaluate(
            doc.animation.playback.range.duration_frames * 0.37, loop=True
        )
        repeated = doc.animation.evaluate(
            doc.animation.playback.range.duration_frames * 1.37, loop=True
        )
        for key in middle.nodes:
            assert repeated.nodes[key].world_matrix == pytest.approx(
                middle.nodes[key].world_matrix, abs=1e-8
            )
