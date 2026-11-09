"""Replaceable rounded gloves and directional stick feet keep their rig attachments."""

import io

import pytest
from PIL import Image, ImageChops

from rigora.application_services.character_creation import build_character, raster_source
from rigora.application_services.characters import CharacterService
from rigora.application_services.documents import DocumentService
from rigora.domain.character_recipe import CharacterRecipe
from rigora.domain.creator_options import COMPONENT_CHOICES
from rigora.infrastructure.illustration import artwork, hand_art, open_sleeve, svg


@pytest.mark.parametrize("open_end", (True, False))
def test_sleeve_attachment_has_fill_without_an_outline_across_the_root(open_end):
    """Verify the actual pixels at the shoulder, exposed sides and distal hem."""
    source = svg(
        open_sleeve((0, 0), (0, 30), 12, "#ffffff", "#222222", open_end=open_end), (-12, -5, 24, 45)
    )
    with Image.open(io.BytesIO(raster_source(source, height=450))) as image:
        assert image.getpixel((120, 51))[:3] == (255, 255, 255)
        assert max(image.getpixel((60, 180))[:3]) < 80
        tip = image.getpixel((120, 350))[:3]
        assert (max(tip) > 200) if open_end else (max(tip) < 80)


def mask(markup, bounds=(-28, -28, 56, 56)):
    """Rasterize a source vector at a shared registration for silhouette comparisons."""
    data = raster_source(svg(markup, bounds), height=280)
    with Image.open(io.BytesIO(data)) as image:
        return image.getchannel("A").point(lambda a: 255 if a > 180 else 0)


def test_glove_gestures_are_distinct_mirrored_and_keep_the_same_wrist():
    """Compare actual silhouettes, including handedness and a covered attachment socket."""
    silhouettes = []
    for name in COMPONENT_CHOICES["Hands"]:
        near = mask(hand_art(True, name, "#222222", 4))
        far = mask(hand_art(False, name, "#222222", 4))
        mirrored = far.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        intersection = ImageChops.multiply(near, mirrored).histogram()[255]
        union = ImageChops.lighter(near, mirrored).histogram()[255]
        # Subpixel curve coverage can differ at the raster boundary after reflection.
        assert intersection / union > 0.998
        assert near.getpixel((140, 140)) > 0
        bounds = near.getbbox()
        assert bounds and min(bounds[:2]) > 0 and max(bounds[2:]) < 280
        silhouettes.append(near.tobytes())
    assert len(silhouettes) == len(set(silhouettes)) == 9


@pytest.mark.parametrize("view", ("Front", "Front 3/4", "Side", "Back 3/4", "Back"))
def test_hand_view_orientation_and_visible_surface(view):
    """Compare bound hand pixels in wrist space, preserving front-facing handedness."""
    from dataclasses import replace

    from rigora.infrastructure.illustration_hands import FORWARD_THUMB_POSES

    recipe = replace(CharacterRecipe(view=view), alternatives={"Hands": COMPONENT_CHOICES["Hands"]})
    _, joints, parts = artwork(recipe)
    turned = view in ("Front 3/4", "Side", "Back 3/4")
    for part in (p for p in parts if p.family == "Hands"):
        joint = joints[part.bone]
        local = (
            f'<g transform="rotate({90 - joint.angle}) '
            f'translate({-joint.root[0]} {-joint.root[1]})">{part.markup}</g>'
        )
        near = part.bone == "hand.R"
        orientation = part.variant in FORWARD_THUMB_POSES if turned else near
        if view == "Front 3/4" and not near and part.variant in ("Loose fist", "Curled fist"):
            orientation = not orientation
        source_side = part.bone[-1]
        if view == "Front" and part.variant in ("Fist", "Open", "Point", "Thumbs out"):
            source_side = "R"
        elif view == "Back" and part.variant in ("Fist", "Open", "Point", "Thumbs out"):
            source_side = "L"
        expected = hand_art(
            orientation,
            part.variant,
            "#222222",
            recipe.stroke_width,
            palm=not (turned and near),
            side=source_side,
        )
        assert mask(local).tobytes() == mask(expected).tobytes(), (view, part.name)


@pytest.mark.parametrize("gesture", ("Fist", "Loose fist", "Curled fist"))
@pytest.mark.parametrize("style", ("Classic", "Color", "Outline", "Sketch"))
def test_front_quarter_fists_keep_their_registered_orientation_at_each_wrist(gesture, style):
    """Check complete painted artwork on both wrists, retaining each original source partner."""
    _, joints, parts = artwork(
        CharacterRecipe(view="Front 3/4", style=style, poses={"Hands": gesture})
    )
    for side in ("R", "L"):
        part = next(p for p in parts if p.family == "Hands" and p.bone == "hand." + side)
        joint = joints[part.bone]
        local = (
            f'<g transform="rotate({90 - joint.angle}) '
            f'translate({-joint.root[0]} {-joint.root[1]})">{part.markup}</g>'
        )
        expected = hand_art(side == "R" or gesture == "Fist", gesture, "#191919", 4, side=side)
        with (
            Image.open(io.BytesIO(raster_source(svg(local, (-28, -28, 56, 56)), 280))) as actual,
            Image.open(
                io.BytesIO(raster_source(svg(expected, (-28, -28, 56, 56)), 280))
            ) as reference,
        ):
            difference = ImageChops.difference(actual, reference)
            assert sum(difference.tobytes()) < sum(reference.tobytes()) * 0.002


@pytest.mark.parametrize("gesture", ("Fist", "Open", "Point", "Thumbs out"))
@pytest.mark.parametrize("style", ("Classic", "Color", "Outline", "Sketch"))
@pytest.mark.parametrize("view,source_side", (("Front", "R"), ("Back", "L")))
def test_straight_view_hand_pair_mirrors_the_correct_source(gesture, style, view, source_side):
    """Compare complete rasterized artwork in wrist space, including original surface details."""
    from dataclasses import replace

    _, joints, parts = artwork(
        replace(CharacterRecipe(view=view, style=style), poses={"Hands": gesture})
    )
    images = []
    for side in ("R", "L"):
        part = next(p for p in parts if p.family == "Hands" and p.bone == "hand." + side)
        joint = joints[part.bone]
        identity = {
            "Fist": ("hand-15", "hand-16"),
            "Open": ("hand-01", "hand-02"),
            "Point": ("hand-13", "hand-14"),
            "Thumbs out": ("hand-17", "hand-18"),
        }[gesture][source_side == "L"]
        assert f'data-source-hand="{identity}"' in part.markup
        local = (
            f'<g transform="rotate({90 - joint.angle}) '
            f'translate({-joint.root[0]} {-joint.root[1]})">{part.markup}</g>'
        )
        with Image.open(io.BytesIO(raster_source(svg(local, (-28, -28, 56, 56)), 280))) as image:
            images.append(image.copy())
    mirrored = images[1].transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    difference = ImageChops.difference(images[0], mirrored)
    assert sum(difference.tobytes()) < sum(images[0].tobytes()) * 0.002


@pytest.mark.parametrize("gesture", COMPONENT_CHOICES["Hands"])
def test_surface_hints_preserve_all_details_from_the_supplied_hand(gesture):
    """The owner's paired surface drawings must not be replaced by synthesized fills."""
    palm = hand_art(False, gesture, "#222222", 4)
    dorsal = hand_art(False, gesture, "#222222", 4, palm=False)
    assert mask(palm).tobytes() == mask(dorsal).tobytes()
    assert mask(dorsal).getpixel((140, 140)) == 255
    with (
        Image.open(io.BytesIO(raster_source(svg(palm, (-28, -28, 56, 56)), 280))) as front,
        Image.open(io.BytesIO(raster_source(svg(dorsal, (-28, -28, 56, 56)), 280))) as back,
    ):
        assert front.tobytes() == back.tobytes()


@pytest.mark.parametrize("view", ("Front 3/4", "Side", "Back 3/4"))
@pytest.mark.parametrize(
    "gesture,unmirrored", (("Relaxed", True), ("Open", True), ("Loose fist", True))
)
def test_hanging_hands_follow_the_forward_thumb_reference(view, gesture, unmirrored):
    """Both thumb silhouettes face forward despite differently authored source contours."""
    from dataclasses import replace

    _, joints, parts = artwork(replace(CharacterRecipe(view=view), poses={"Hands": gesture}))
    for part in (p for p in parts if p.family == "Hands"):
        joint = joints[part.bone]
        local = (
            f'<g transform="rotate({90 - joint.angle}) '
            f'translate({-joint.root[0]} {-joint.root[1]})">{part.markup}</g>'
        )
        expected = hand_art(
            not unmirrored
            if view == "Front 3/4" and gesture == "Loose fist" and part.bone == "hand.L"
            else unmirrored,
            gesture,
            "#222222",
            4,
            palm=part.bone != "hand.R",
            side=part.bone[-1],
        )
        assert mask(local).tobytes() == mask(expected).tobytes()


def test_point_gesture_extends_along_the_hand_bone_without_a_card_only_rotation():
    """The authored index follows +Y so wrist animation rotates the same source geometry."""
    point = mask(hand_art(True, "Point", "#222222", 4)).getbbox()
    fist = mask(hand_art(True, "Fist", "#222222", 4)).getbbox()
    assert point[1] > 110
    assert point[3] > fist[3]


@pytest.mark.parametrize("view", ("Front", "Front 3/4", "Side", "Back 3/4", "Back"))
def test_sleeves_cover_limb_caps_without_a_backward_shoulder_stub(view):
    """The shoulder cap starts inside its socket; cuffs still cover the elbow overlap."""
    from dataclasses import replace

    from rigora.domain.creator_options import choose
    from rigora.infrastructure.illustration_motion import offset

    recipe = replace(
        choose(CharacterRecipe(view=view), "Clothing", "shirt"),
        garment_colors={"Clothing/shirt": "#ee5522"},
    )
    _, joints, parts = artwork(recipe)
    for label, bone in (("Sleeve", "upper_arm"), ("Cuff", "forearm")):
        for side in ("R", "L"):
            joint = joints[bone + "." + side]
            probe = offset(
                joint.root, joint.angle, recipe.stroke_width / 2 * (1 if label == "Sleeve" else -1)
            )
            part = next(p for p in parts if p.name == f"{label} {side} · shirt")
            source = svg(part.markup, (probe[0] - 1, probe[1] - 1, 2, 2))
            with Image.open(io.BytesIO(raster_source(source, height=20))) as image:
                assert image.getpixel((10, 10)) == (238, 85, 34, 255)


@pytest.mark.parametrize("view", ("Front", "Front 3/4", "Side", "Back 3/4", "Back"))
def test_added_hair_has_distinct_fitted_shapes_and_valid_bone_attachments(view):
    """Render actual source parts and detect fallback silhouettes or clipped empty geometry."""
    from dataclasses import replace

    from rigora.infrastructure.illustration_hair import HAIRSTYLES

    silhouettes = []
    for name in HAIRSTYLES:
        recipe = replace(CharacterRecipe(view=view), parts={"Hair": name})
        design, joints, parts = artwork(recipe)
        hair = [p for p in parts if p.family == "Hair"]
        assert hair and all(p.variant == name and p.bone in joints for p in hair)
        head = joints["head"].root
        bounds = (
            head[0] - design.head * 2,
            head[1] - design.head * 3.1,
            design.head * 4,
            design.head * 3.7,
        )
        image = mask("".join(p.markup for p in hair), bounds)
        assert image.getbbox()
        silhouettes.append(image.tobytes())
    assert len(silhouettes) == len(set(silhouettes)) == len(HAIRSTYLES) >= 18


@pytest.mark.parametrize("view", ("Front", "Front 3/4", "Side"))
def test_switching_retained_gloves_replaces_both_hands_instead_of_overlaying_defaults(view):
    """The actual wardrobe service exposes exactly one bound hand per side after each swap."""
    document = DocumentService()
    built = build_character(
        CharacterRecipe(
            view=view, motions=("Run",), alternatives={"Hands": COMPONENT_CHOICES["Hands"]}
        ),
        scratch=document,
    )
    service = CharacterService(document)
    group = next(
        g for g in service.appearance_groups(built.root_id, "outfits") if g["name"] == "Hands"
    )
    hand_nodes = {o.id for o in document.scene.objects if o.name.startswith("Hand ")}
    for variant in group["variants"]:
        service.show_variant(built.root_id, group["id"], variant["id"], True)
        pose = document.animation.evaluate(7)
        visible = [pose.nodes[key] for key in hand_nodes if pose.nodes[key].visible]
        assert len(visible) == 2
        assert all(node.name.endswith(" · " + variant["name"]) for node in visible)


@pytest.mark.parametrize("view", ("Front", "Front 3/4", "Side", "Back 3/4", "Back"))
def test_stick_feet_have_rounded_toes_and_consistent_directional_attachment(view):
    """Bare soles overlap each ankle; front/rear feet splay out, right-facing views point right."""
    _, rest, parts = artwork(CharacterRecipe(view=view))
    for side in ("R", "L"):
        piece = next(p for p in parts if p.family == "Shoes" and p.name.endswith(" · " + side))
        ankle = rest["foot." + side].root
        assert " C " in piece.markup and " Q " in piece.markup
        source = mask(piece.markup, (ankle[0] - 28, ankle[1] - 28, 56, 56))
        assert source.getpixel((140, 140)) > 0
        bounds = source.getbbox()
        center = (bounds[0] + bounds[2]) / 2
        assert (center < 140) == (view in ("Front", "Back") and side == "R")
