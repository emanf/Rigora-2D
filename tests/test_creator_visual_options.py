"""Visual Creator options export real layered choices and keep canonical animation behavior."""

import io
import json
from dataclasses import replace

import pytest
from PIL import Image

from rigora.application_services.character_creation import build_character, raster_source
from rigora.application_services.characters import CharacterService
from rigora.application_services.creator_preview import (
    option_sources,
    posed_portrait,
    repaint_character,
)
from rigora.application_services.documents import DocumentService
from rigora.application_services.facial import FaceService
from rigora.domain.character_recipe import MOTION_CHOICES, CharacterRecipe
from rigora.domain.creator_options import COMPONENT_CHOICES, OUTFIT_PRESETS, choose, outfit
from rigora.infrastructure.illustration import artwork
from rigora.infrastructure.illustration_motion import world_joints


def test_every_eye_and_lip_set_has_an_independent_real_preview():
    """Unselected alternatives have distinct SVG previews before a card is clicked."""
    sources = dict(option_sources(CharacterRecipe()))
    for category in ("Eyes", "Mouth"):
        values = [sources[category, name] for name in COMPONENT_CHOICES[category]]
        assert len(values) == len(COMPONENT_CHOICES[category]) >= 9
        assert len(set(values)) == len(values)
    for category in (
        "Clothing",
        "Pants",
        "Glasses",
        "Hair",
        "Backwear",
        "Nose",
        "Mustache",
        "Beard",
    ):
        values = [sources[category, name] for name in COMPONENT_CHOICES[category]]
        assert len(set(values)) == len(values), category
    assert all(
        (category, name) in sources
        for category, values in COMPONENT_CHOICES.items()
        for name in values
    )
    assert all(("Animations", action) in sources for action in MOTION_CHOICES)


def test_retained_eyes_mouths_and_accessories_switch_through_existing_outfit_controls():
    """Choice groups retain multiple eyes and complete viseme sets with the selected default."""
    recipe = replace(
        CharacterRecipe(),
        motions=(),
        mouth_style="Teeth",
        parts={"Eyes": "round"},
        alternatives={
            "Mouth": ("Soft", "Fangs"),
            "Eyes": ("soft", "lashes"),
            "Headwear": ("cap", "headphones"),
            "Glasses": ("round",),
        },
    )
    doc = DocumentService()
    built = build_character(recipe, scratch=doc)
    service = CharacterService(doc)
    groups = service.appearance_groups(built.root_id, "outfits")
    eyes = next(g for g in groups if g["name"] == "Eyes")
    assert {v["name"] for v in eyes["variants"]} == {"round", "soft", "lashes"}
    face = FaceService(doc)
    descriptor = face.face(built.root_id)
    assert set(descriptor["mouth_sets"]) == {"Teeth", "Soft", "Fangs"}
    face.lip_sync(built.root_id, ((0, "Rest"), (0.25, "AI"), (0.5, "MBP")))
    mouth = next(g for g in groups if g["name"] == "Mouth style")
    for variant in mouth["variants"]:
        service.show_variant(built.root_id, mouth["id"], variant["id"], True)
        pose = doc.animation.evaluate(8)
        visible = [
            key
            for values in descriptor["mouth_sets"].values()
            for key in values.values()
            if pose.nodes[key].visible
        ]
        assert visible == [descriptor["mouth_sets"][variant["name"]]["AI"]]


def test_saved_outfit_sets_apply_together_and_undo_as_one_edit():
    """Saved coordinated sets resolve portable category names after object placement/remapping."""
    names = ("Business", "Runner")
    choices = {}
    for name in names:
        for category, value in OUTFIT_PRESETS[name].items():
            choices[category] = (*choices.get(category, ()), value)
    recipe = replace(
        outfit(CharacterRecipe(), "Business"), motions=(), outfit_sets=names, alternatives=choices
    )
    doc = DocumentService()
    built = build_character(recipe, scratch=doc)
    service = CharacterService(doc)
    original = doc.project
    count = len(doc.history.undo_stack)
    service.apply_outfit_set(built.root_id, "Runner")
    assert len(doc.history.undo_stack) == count + 1
    groups = service.appearance_groups(built.root_id, "outfits")
    for category, value in OUTFIT_PRESETS["Runner"].items():
        group = next(g for g in groups if g["name"] == category)
        assert next(v for v in group["variants"] if v["visible"])["name"] == value
    tie = next(g for g in groups if g["name"] == "Ties")
    assert next(v for v in tie["variants"] if v["visible"])["name"] == "none"
    doc.undo()
    assert doc.project == original


def test_long_sleeves_occlude_under_watch_but_over_watch_remains_visible():
    """Test actual composite pixels, rather than relying only on declared depth numbers."""
    recipe = choose(choose(CharacterRecipe(), "Clothing", "shirt"), "Watches", "classic")
    recipe = replace(recipe, garment_colors={"Watches/classic": "#ff0000"}, outline_width=0)

    def red_pixels(mode):
        image = Image.open(
            io.BytesIO(
                raster_source(posed_portrait(replace(recipe, layer_modes={"Watches": mode})), 640)
            )
        ).convert("RGBA")
        return sum(
            r > 200 and g < 40 and b < 40 and a > 200 for r, g, b, a in image.get_flattened_data()
        )

    assert red_pixels("Under sleeves") == 0
    assert red_pixels("Over sleeves") > 20


@pytest.mark.parametrize("action", ("Jump", "Wave", "Bow", "Cheer", "Point"))
@pytest.mark.parametrize("design_id", ("nova", "bean"))
def test_gestures_move_and_return_continuously_without_resizing_bones(action, design_id):
    """Human and quadruped gestures have changing poses, fixed lengths and matched end poses."""
    design, rest, _ = artwork(CharacterRecipe(design_id=design_id))
    first = world_joints(design, "Front 3/4", action, 0)
    middle = world_joints(design, "Front 3/4", action, 0.4)
    last = world_joints(design, "Front 3/4", action, 1)
    assert first != middle
    for name in first:
        assert first[name].root == pytest.approx(last[name].root)
        assert first[name].tip == pytest.approx(last[name].tip)
    for index in range(51):
        pose = world_joints(design, "Front 3/4", action, index / 50)
        assert all(j.length == pytest.approx(rest[name].length) for name, j in pose.items())


def test_palette_replacement_preserves_bones_meshes_and_all_animation_keys():
    """The live recolor path must reuse topology and choreography rather than rebake actions."""
    recipe = CharacterRecipe(alternatives={"Clothing": ("jacket", "dress"), "Mouth": ("Fangs",)})
    built = build_character(recipe)
    colored = replace(
        recipe,
        colors={"Skin": "#c8a17b", "Ink": "#333333"},
        garment_colors={"Clothing/jacket": "#123456"},
    )
    changed = repaint_character(built, colored)
    before, after = (json.loads(b.files["character.json"]) for b in (built, changed))
    for field in ("skeletons", "meshes", "deformers", "timelines", "clips"):
        assert before["scenes"][0][field] == after["scenes"][0][field]
    assert built.root_id == changed.root_id
    assert set(built.files) == set(changed.files)
    assert before["assets"] != after["assets"]


@pytest.mark.parametrize("action", ("Walk", "Run"))
@pytest.mark.parametrize(
    "design_id", ("nova", "kai", "mabel", "luca", "dot", "orbit", "tansy", "bean", "clover")
)
def test_forward_gaits_recover_feet_forward_and_keep_torso_lean_restrained(action, design_id):
    """Ground strokes travel backward; airborne strokes recover toward the facing direction."""
    design, _, _ = artwork(CharacterRecipe(design_id=design_id, view="Side"))

    def joints(phase):
        # Walking forelegs alternate with hind legs; running leads on the forelegs.
        offset = 0.5 if design.anatomy not in ("human", "robot") and action == "Walk" else 0
        return world_joints(design, "Side", action, (phase + offset) % 1)

    before, after = joints(0.2), joints(0.3)
    recovery_before, recovery_after = joints(0.7), joints(0.8)
    foot = "foot.R" if design.anatomy in ("human", "robot") else "hand.R"
    assert before[foot].root[0] > after[foot].root[0]
    assert recovery_before[foot].root[0] < recovery_after[foot].root[0]
    if design.anatomy in ("human", "robot"):
        lean = [joints(i / 60)["spine"].angle + 90 for i in range(61)]
        assert 0 < min(lean) <= max(lean) <= (0.36 if action == "Walk" else 3.2)
        support_bend = []
        for i in range(61):
            pose = joints(i / 60)
            thigh, shin = pose["thigh.R"], pose["shin.R"]
            bend = abs((thigh.angle - shin.angle + 180) % 360 - 180)
            # A run includes toe-off and folded recovery within the first half-cycle.
            # Bound the knee only during actual ground contact, not airborne recovery.
            grounded = pose[foot].root[1] >= -13
            if (action == "Walk" and i / 60 <= 0.5) or (action == "Run" and grounded):
                support_bend.append(bend)
            assert pose["hips"].root[1] < -design.leg * 1.85
        assert max(support_bend) < (34 if action == "Walk" else 46)
    first, last = joints(0), joints(1)
    for name in first:
        assert first[name].root == pytest.approx(last[name].root)
        assert first[name].tip == pytest.approx(last[name].tip)


def test_character_can_be_created_without_retaining_source_animations():
    """Unchecking every action still creates an editable rig through scene placement."""
    from rigora.application_services.character_creation import CharacterCreationService

    document = DocumentService()
    document.new()
    built = build_character(CharacterRecipe(motions=()))
    root = CharacterCreationService(document).create(built)
    assert any(g.id == root for g in document.scene.groups)
    assert document.scene.skeletons
    assert not document.scene.clips


@pytest.mark.parametrize("action", ("Walk", "Run"))
def test_baked_gaits_play_forward_through_the_scene_evaluator(action):
    """Editable Bezier keys preserve stance and recovery direction after engine evaluation."""
    document = DocumentService()
    build_character(CharacterRecipe(view="Side", motions=(action,)), scratch=document)
    document.select_animation_clip(document.scene.clips[0].id)
    bone = next(b for b in document.scene.skeletons[0].bones if b.name == "foot.R")
    length = document.scene.clips[0].out_frame + 1

    def x(phase):
        return document.animation.evaluate(length * phase).nodes[bone.id].world_matrix[4]

    assert x(0.2) > x(0.3)
    assert x(0.7) < x(0.8)


@pytest.mark.parametrize("head_shape", ("Round", "Oval", "Soft square"))
@pytest.mark.parametrize("scale", (0.65, 1.0, 1.6))
def test_mustaches_follow_the_projected_mouth_and_fit_the_head(head_shape, scale):
    """Compare actual painted facial hair with the head mask at all editable view angles."""
    from PIL import ImageChops

    from rigora.domain.character_recipe import VIEWS
    from rigora.infrastructure.illustration import svg

    for view in VIEWS:
        for style in ("Pencil", "Chevron", "Handlebar"):
            _, _, parts = artwork(
                CharacterRecipe(
                    view=view,
                    head_shape=head_shape,
                    proportions={"head": scale},
                    parts={"Mustache": style, "Nose": "Simple"},
                )
            )
            facial_hair = [p for p in parts if p.family == "Mustache" and p.markup != "<g/>"]
            if view.startswith("Back"):
                assert not facial_hair
                continue
            piece = facial_hair[0]
            mouth = next(p for p in parts if p.name == "Mouth · Soft · Rest")
            assert piece.bounds[0] + piece.bounds[2] / 2 == pytest.approx(
                mouth.bounds[0] + mouth.bounds[2] / 2
            )
            head = next(p for p in parts if p.name == "Head")

            def mask(part, head=head):
                source = raster_source(svg(part.markup, head.bounds), height=180)
                with Image.open(io.BytesIO(source)) as image:
                    return image.getchannel("A").point(lambda a: 255 if a > 180 else 0)

            hair_mask, head_mask, mouth_mask = mask(piece), mask(head), mask(mouth)
            assert hair_mask.getbbox()
            assert not ImageChops.subtract(hair_mask, head_mask).getbbox()
            assert hair_mask.getbbox()[3] <= mouth_mask.getbbox()[1]
