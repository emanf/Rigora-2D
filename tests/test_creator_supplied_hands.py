"""CC uses the owner's complete paired vectors without drawing replacement hand geometry."""

import io
from dataclasses import replace
from xml.etree import ElementTree as ET

import pytest
from PIL import Image

from rigora.application_services.character_creation import build_character, raster_source
from rigora.domain.character_recipe import CharacterRecipe
from rigora.domain.creator_options import COMPONENT_CHOICES, default_choice, retained_choices
from rigora.infrastructure.illustration import artwork, hand_art, svg
from rigora.resources import asset_path

PAIRS = {
    "Open": ("hand-01", "hand-02"),
    "Loose fist": ("hand-03", "hand-04"),
    "Relaxed": ("hand-05", "hand-06"),
    "Wave": ("hand-07", "hand-08"),
    "Curled fist": ("hand-09", "hand-10"),
    "Palm out": ("hand-11", "hand-12"),
    "Point": ("hand-13", "hand-14"),
    "Fist": ("hand-15", "hand-16"),
    "Thumbs out": ("hand-17", "hand-18"),
}


def test_only_the_nine_supplied_vector_pairs_are_available():
    assert set(COMPONENT_CHOICES["Hands"]) == set(PAIRS)
    root = ET.parse(asset_path("characters/hands/cartoon-gloves.svg")).getroot()
    groups = root.findall("{http://www.w3.org/2000/svg}g")
    assert {g.get("id") for g in groups} == {value for pair in PAIRS.values() for value in pair}
    assert all(len(g) == 3 and all(p.tag.endswith("}path") for p in g) for g in groups)
    assert {p.get("fill") for g in groups for p in g} == {"#0D0C0A", "#ffffff"}
    assert not root.findall(".//{http://www.w3.org/2000/svg}image")


@pytest.mark.parametrize("gesture", PAIRS)
@pytest.mark.parametrize("side", ("R", "L"))
def test_each_hand_preserves_its_supplied_partner_and_all_original_details(gesture, side):
    """Raster comparison permits registration/color only, on both surfaces and reflections."""
    identity = PAIRS[gesture][side == "L"]
    root = ET.parse(asset_path("characters/hands/cartoon-gloves.svg")).getroot()
    group = next(g for g in root if g.get("id") == identity)
    group.set("transform", group.attrib["data-bind-transform"])
    for path in group:
        if path.get("fill") == "#0D0C0A":
            path.set("fill", "#191919")
    reference = ET.tostring(group, encoding="unicode")
    for near in (True, False):
        expected = svg(
            f'<g transform="scale({1 if near else -1} 1)">{reference}</g>', (-28, -28, 56, 56)
        )
        expected_pixels = raster_source(expected, 280)
        for palm in (True, False):
            art = hand_art(near, gesture, "#191919", 4, palm=palm, side=side)
            assert f'data-source-hand="{identity}"' in art
            assert "clipPath" not in art
            assert art.count("<path") == 3
            assert raster_source(svg(art, (-28, -28, 56, 56)), 280) == expected_pixels


@pytest.mark.parametrize("gesture", PAIRS)
def test_both_supplied_hands_fit_the_shared_wrist_without_sheet_scale_geometry(gesture):
    pixels = []
    for side in ("R", "L"):
        source = svg(hand_art(True, gesture, "#222222", 4, side=side), (-28, -28, 56, 56))
        with Image.open(io.BytesIO(raster_source(source, 280))) as image:
            assert image.getpixel((140, 140))[3] == 255
            bounds = image.getchannel("A").getbbox()
            assert bounds and min(bounds[:2]) > 30 and max(bounds[2:]) < 260
            assert 35 <= bounds[2] - bounds[0] <= 125
            assert 40 <= bounds[3] - bounds[1] <= 125
            assert set(image.get_flattened_data()) >= {(255, 255, 255, 255), (34, 34, 34, 255)}
            pixels.append(image.tobytes())
    assert pixels[0] != pixels[1]


@pytest.mark.parametrize("palm", (True, False))
def test_supplied_hand_colors_remain_independent_even_with_white_outlines(palm):
    source = svg(hand_art(True, "Open", "#ffffff", 4, "#5599cc", palm=palm), (-28, -28, 56, 56))
    with Image.open(io.BytesIO(raster_source(source, 280))) as image:
        assert set(image.get_flattened_data()) >= {(255, 255, 255, 255), (85, 153, 204, 255)}


@pytest.mark.parametrize("view", ("Front", "Front 3/4", "Side", "Back 3/4", "Back"))
@pytest.mark.parametrize("style", ("Classic", "Color", "Outline", "Sketch"))
def test_all_supplied_pairs_stay_registered_and_replaceable_in_every_view(view, style):
    _, joints, parts = artwork(
        replace(CharacterRecipe(view=view, style=style), alternatives={"Hands": tuple(PAIRS)})
    )
    hands = [p for p in parts if p.family == "Hands"]
    assert len(hands) == len(PAIRS) * 2
    assert len([p for p in hands if p.visible]) == 2
    assert {p.variant for p in hands} == set(PAIRS)
    for hand in hands:
        assert hand.bone in joints
        identity = PAIRS[hand.variant][hand.bone == "hand.L"]
        if view == "Front" and hand.variant in ("Fist", "Open", "Point", "Thumbs out"):
            identity = PAIRS[hand.variant][0]
        elif view == "Back" and hand.variant in ("Fist", "Open", "Point", "Thumbs out"):
            identity = PAIRS[hand.variant][1]
        assert f'data-source-hand="{identity}"' in hand.markup
        assert hand.markup.count("<path") == 3


def test_retired_recipe_hands_resolve_to_supplied_art_without_blank_defaults():
    recipe = replace(
        CharacterRecipe(), poses={"Hands": "Simple fist"}, alternatives={"Hands": ("Peace", "Open")}
    )
    assert default_choice(recipe, "Hands") == "Loose fist"
    assert retained_choices(recipe, "Hands") == ("Loose fist", "Relaxed", "Open")
    _, _, parts = artwork(recipe)
    visible = [p for p in parts if p.family == "Hands" and p.visible]
    assert len(visible) == 2
    assert all(p.variant == "Loose fist" and "data-source-hand=" in p.markup for p in visible)


def test_supplied_hand_notice_travels_with_new_and_legacy_recipe_characters():
    for gesture in ("Relaxed", "Round hand"):
        built = build_character(replace(CharacterRecipe(motions=()), poses={"Hands": gesture}))
        assert built.item.license == "Mixed; see GLOVE-NOTICE.md"
        assert b"Untitled.svg" in built.files["GLOVE-NOTICE.md"]
