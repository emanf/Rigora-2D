"""Creator additions are real, distinct SVGs with consistent attachment and replacement."""

import io

import pytest
from PIL import Image

from rigora.application_services.character_creation import raster_source
from rigora.application_services.creator_preview import option_sources
from rigora.domain.character_recipe import CharacterRecipe
from rigora.domain.creator_options import COMPONENT_CHOICES, choose
from rigora.infrastructure.illustration import artwork, svg


@pytest.mark.parametrize("category", ("Glasses", "Eyes", "Pants", "Shoes", "Ties", "Hands"))
def test_expanded_choices_have_distinct_nonempty_visual_cards(category):
    """Every selectable item has its own useful preview instead of a fallback drawing."""
    sources = dict(option_sources(CharacterRecipe(motions=())))
    names = COMPONENT_CHOICES[category]
    assert (
        len(names)
        >= {"Glasses": 11, "Eyes": 15, "Pants": 15, "Shoes": 11, "Ties": 9, "Hands": 9}[category]
    )
    pixels = []
    for name in names:
        if name in ("none", "bare"):
            continue
        img = Image.open(io.BytesIO(raster_source(sources[category, name], 128))).convert("RGBA")
        assert img.getchannel("A").getbbox(), (category, name)
        pixels.append(img.tobytes())
    assert len(set(pixels)) == len(pixels), category


@pytest.mark.parametrize("view", ("Front", "Front 3/4", "Side", "Back 3/4", "Back"))
def test_cap_crown_and_brim_are_closed_filled_outlined_shapes(view):
    _, _, parts = artwork(choose(CharacterRecipe(view=view), "Headwear", "cap"))
    cap = next(p for p in parts if p.family == "Headwear")
    assert cap.markup.count(' Z"') >= 2
    assert 'stroke="none"' not in cap.markup


@pytest.mark.parametrize("view", ("Front", "Front 3/4", "Side"))
def test_stubble_stays_within_the_face_and_under_lip_sync(view):
    """Beard pixels follow the lower jaw rather than floating outside the face or over speech."""
    from PIL import ImageChops, ImageFilter

    recipe = choose(CharacterRecipe(view=view), "Beard", "Stubble")
    _, _, parts = artwork(recipe)
    head = next(p for p in parts if p.name == "Head")
    beard = next(p for p in parts if p.family == "Beard" and p.variant == "Stubble")
    bounds = head.bounds

    def alpha(part):
        return Image.open(io.BytesIO(raster_source(svg(part.markup, bounds), 400))).getchannel("A")

    face = alpha(head).filter(ImageFilter.MaxFilter(3))
    assert ImageChops.subtract(alpha(beard), face).getbbox() is None
    assert beard.layer < min(p.layer for p in parts if p.name.startswith("Mouth ·"))


@pytest.mark.parametrize(
    "name", ("spring curl", "double curl", "curly ponytail", "high ponytail", "side curl")
)
def test_loose_curls_and_ponytails_keep_separate_animatable_hair_parts(name):
    _, joints, parts = artwork(choose(CharacterRecipe(), "Hair", name))
    hair = [p for p in parts if p.family == "Hair"]
    assert any(p.bone == "head" for p in hair)
    assert any(p.bone in ("hair.front", "hair.back") and p.markup for p in hair)
    assert all(p.bone in joints for p in hair)


@pytest.mark.parametrize("choice", ("scarf", "long scarf"))
def test_scarf_wraps_the_neck_above_clothing_panels(choice):
    """A scarf sits on the neck and outside a coat, while near arms can cross in front."""
    from dataclasses import replace

    recipe = choose(choose(CharacterRecipe(), "Clothing", "coat"), "Ties", choice)
    recipe = replace(recipe, layer_modes={"Clothing": "Front panels"})
    _, joints, parts = artwork(recipe)
    scarf = next(p for p in parts if p.family == "Ties" and p.variant == choice)
    shoulder = joints["spine"].tip
    assert scarf.bounds[1] < shoulder[1] - 10
    assert scarf.layer > max(p.layer for p in parts if p.family == "Clothing" and p.bone == "spine")
    assert scarf.layer < next(p.layer for p in parts if p.name == "Forearm R")


@pytest.mark.parametrize("view", ("Front", "Front 3/4", "Side", "Back 3/4", "Back"))
@pytest.mark.parametrize(
    "choice", ("tie", "skinny tie", "striped tie", "bow tie", "cravat", "neckerchief")
)
def test_tie_knot_is_attached_at_the_neck_body_joint(view, choice):
    """Rasterized neckwear covers its anatomical joint instead of starting down the chest."""
    recipe = choose(CharacterRecipe(design_id="dot", view=view), "Ties", choice)
    _, joints, parts = artwork(recipe)
    tie = next(p for p in parts if p.family == "Ties" and p.variant == choice)
    x, y = joints["neck"].root
    image = Image.open(
        io.BytesIO(raster_source(svg(tie.markup, (x - 3, y - 3, 6, 6)), 60))
    ).convert("RGBA")
    assert image.getpixel((30, 30))[3] > 200
