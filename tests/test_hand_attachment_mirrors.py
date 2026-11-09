"""Local per-view mirrors preserve the paired source geometry, wrists and other views."""

import io
import json
from dataclasses import replace

import pytest
from PIL import Image, ImageChops

from rigora.application_services.character_creation import build_character, raster_source
from rigora.domain.character_recipe import VIEWS, CharacterRecipe
from rigora.domain.project import ProjectError
from rigora.infrastructure.illustration import artwork, svg


@pytest.mark.parametrize("side,bone", (("left", "hand.R"), ("right", "hand.L")))
@pytest.mark.parametrize("view", VIEWS)
def test_mirror_only_reflects_the_requested_hand_around_its_wrist(view, side, bone):
    base = CharacterRecipe(view=view, poses={"Hands": "Fist"}, motions=())
    flipped = replace(base, hand_flips={view: {side: True}})
    _, joints, original = artwork(base)
    _, updated_joints, changed = artwork(flipped)
    assert joints == updated_joints
    original_parts = {p.name: p for p in original}
    for part in changed:
        before = original_parts[part.name]
        if part.family != "Hands" or part.bone != bone:
            assert part == before
            continue
        joint = joints[bone]

        def pixels(markup, joint=joint):
            local = (
                f'<g transform="rotate({90 - joint.angle}) '
                f'translate({-joint.root[0]} {-joint.root[1]})">{markup}</g>'
            )
            return Image.open(io.BytesIO(raster_source(svg(local, (-28, -28, 56, 56)), 280)))

        with pixels(part.markup) as actual, pixels(before.markup) as source:
            difference = ImageChops.difference(
                actual, source.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            )
            assert sum(difference.tobytes()) < sum(source.tobytes()) * 0.002
    other = next(v for v in VIEWS if v != view)
    assert artwork(replace(base, view=other)) == artwork(replace(flipped, view=other))


def test_mirror_recipe_is_portable_and_defaults_do_not_change():
    recipe = CharacterRecipe(motions=(), hand_flips={"Front 3/4": {"right": True}})
    restored = CharacterRecipe(**json.loads(json.dumps(recipe.to_dict())))
    assert restored == recipe
    built = build_character(restored)
    project = json.loads(built.files["character.json"])
    root = next(g for g in project["scenes"][0]["groups"] if g["id"] == built.root_id)
    assert root["character_recipe"]["hand_flips"] == recipe.hand_flips
    assert CharacterRecipe(**{"motions": ()}).hand_flips == {}


@pytest.mark.parametrize(
    "flips", ({"wrong": {"right": True}}, {"Front": {"bad": True}}, {"Front": {"left": 1}})
)
def test_invalid_mirror_descriptors_are_rejected(flips):
    with pytest.raises(ProjectError):
        CharacterRecipe(hand_flips=flips)
