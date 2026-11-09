"""Trouser outlines remain visible while anatomical attachment edges stay open."""

import io

import pytest
from PIL import Image

from rigora.application_services.character_creation import raster_source
from rigora.domain.character_recipe import CharacterRecipe
from rigora.domain.creator_options import COMPONENT_CHOICES, choose
from rigora.domain.geometry import affine, inverse
from rigora.infrastructure.illustration import artwork, svg


@pytest.mark.parametrize(
    "choice", [n for n in COMPONENT_CHOICES["Pants"] if n not in ("none", "skirt")]
)
def test_pants_have_dark_side_outlines_without_a_border_behind_the_hip(choice):
    recipe = choose(
        CharacterRecipe(colors={"Ink": "#101010", "Bottom": "#eeeeee"}), "Pants", choice
    )
    _, joints, parts = artwork(recipe)
    part = next(
        p for p in parts if p.family == "Pants" and p.variant == choice and p.bone == "thigh.R"
    )
    joint = joints[part.bone]
    matrix = inverse(affine(*joint.root, joint.angle, 1, 1, 0, 0))
    markup = '<g transform="matrix(' + " ".join(map(str, matrix)) + ')">' + part.markup + "</g>"
    image = Image.open(io.BytesIO(raster_source(svg(markup, (-10, -20, 70, 40)), 400))).convert(
        "RGBA"
    )
    # A transverse slice through the thigh must contain a dark outlined side.
    column = [image.getpixel((250, y)) for y in range(400)]
    assert any(a > 200 and max(r, g, b) < 60 for r, g, b, a in column)
    assert image.getchannel("A").crop((0, 0, 75, 400)).getbbox() is None
