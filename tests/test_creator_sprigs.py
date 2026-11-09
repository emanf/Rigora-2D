"""Sparse sprig styles are distinct source vectors with fitted crown attachments."""

import io

import pytest
from PIL import Image

from rigora.application_services.character_creation import raster_source
from rigora.domain.character_recipe import CharacterRecipe
from rigora.domain.creator_options import COMPONENT_CHOICES, choose
from rigora.infrastructure.illustration import artwork, svg
from rigora.infrastructure.illustration_hair import SPRIG_STYLES


@pytest.mark.parametrize("view", ("Front", "Front 3/4", "Side", "Back 3/4", "Back"))
def test_sprigs_are_distinct_visible_and_registered_on_the_head(view):
    images = []
    for name in SPRIG_STYLES:
        assert name in COMPONENT_CHOICES["Hair"]
        _, _, parts = artwork(choose(CharacterRecipe(view=view), "Hair", name))
        hair = [p for p in parts if p.family == "Hair"]
        assert len(hair) == 1 and hair[0].bone == "head"
        part = hair[0]
        image = Image.open(
            io.BytesIO(raster_source(svg(part.markup, part.bounds), 200))
        ).getchannel("A")
        bounds = image.getbbox()
        assert (
            bounds and min(bounds[:2]) > 0 and bounds[2] < image.width and bounds[3] < image.height
        )
        images.append(image.tobytes())
    assert len(set(images)) == len(SPRIG_STYLES) == 7
