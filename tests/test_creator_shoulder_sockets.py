"""Upper arms and sleeves blend into the torso without rotating a backward root stub."""

import io

import pytest
from PIL import Image

from rigora.application_services.character_creation import raster_source
from rigora.domain.character_recipe import CharacterRecipe
from rigora.domain.geometry import affine, inverse, multiply
from rigora.infrastructure.illustration import artwork, svg


@pytest.mark.parametrize("style", ("Classic", "Sketch", "Color", "Outline"))
@pytest.mark.parametrize("view", ("Front", "Front 3/4", "Side", "Back 3/4", "Back"))
def test_little_upper_arm_socket_has_no_backward_cap_when_crossing_the_body(style, view):
    recipe = CharacterRecipe(design_id="dot", view=view, style=style, worn={"Clothing": "tee"})
    _, joints, parts = artwork(recipe)
    for side in ("R", "L"):
        joint = joints["upper_arm." + side]
        transform = multiply(
            affine(0, 0, 0, 1, 1, 0, 0),
            inverse(affine(*joint.root, joint.angle, 1, 1, 0, 0)),
        )
        for name in ("Upper arm " + side, "Sleeve " + side + " · tee"):
            part = next(p for p in parts if p.name == name)
            markup = (
                '<g transform="matrix('
                + " ".join(map(str, transform))
                + ')">'
                + part.markup
                + "</g>"
            )
            source = svg(markup, (-8, -8, 32, 16))
            image = Image.open(io.BytesIO(raster_source(source, height=160))).convert("RGBA")
            assert image.getchannel("A").crop((0, 0, 60, 160)).getbbox() is None
            assert image.getchannel("A").crop((100, 50, 200, 110)).getbbox() is not None
