"""Current SVG expressions preserve appearance choices and remain editable after persistence."""

import io
from dataclasses import replace

import pytest
from PIL import Image

from rigora.application_services.character_creation import (
    build_character,
    character_portrait,
    raster_source,
)
from rigora.application_services.content_library import content_project
from rigora.domain.character_recipe import FEELING_PRESETS, VIEWS, CharacterRecipe, with_feeling
from rigora.domain.creator_options import COMPONENT_CHOICES, choose
from rigora.infrastructure.illustration import artwork


@pytest.mark.parametrize("view", VIEWS[:3])
def test_wink_preserves_the_other_authored_eye_for_every_current_style(view):
    for style in COMPONENT_CHOICES["Eyes"]:
        base = choose(CharacterRecipe(view=view, motions=()), "Eyes", style)
        original = {p.name: p for p in artwork(base)[2] if p.family == "Eyes"}
        winked = {
            p.name: p
            for p in artwork(replace(base, poses={"Eyes": "Wink"}))[2]
            if p.family == "Eyes"
        }
        for name, part in original.items():
            if name.startswith("Eye R"):
                assert winked[name] == part
            else:
                assert winked[name].markup != part.markup


def test_expressions_are_visually_distinct_without_mutating_the_base_recipe():
    base = CharacterRecipe(motions=())
    before = base.to_dict()
    pixels = []
    for feeling in FEELING_PRESETS:
        varied = with_feeling(base, feeling)
        assert varied.design_id == base.design_id and varied.parts == base.parts
        with Image.open(io.BytesIO(raster_source(character_portrait(varied), height=220))) as image:
            pixels.append(image.tobytes())
    assert len(set(pixels)) == len(FEELING_PRESETS)
    assert base.to_dict() == before


def test_expression_remains_layered_and_portable():
    recipe = with_feeling(CharacterRecipe(motions=()), "Happy")
    built = build_character(recipe)
    project = content_project(built.item, built.files)
    root = next(g for g in project.scenes[0].groups if g.id == built.root_id)
    assert root.extra["character_recipe"]["feeling"] == "Happy"
    assert all(asset.kind == "vector" for asset in project.assets)
    assert root.extra["face"]["mouths"] and root.extra["face"]["eyes"]
