"""Modular vector assembly, whole-character placement and reusable action ownership."""

import json
from dataclasses import replace

import pytest

from rigora.application_services.character_creation import CharacterCreationService, build_character
from rigora.application_services.characters import CharacterService
from rigora.application_services.documents import DocumentService
from rigora.application_services.scene_editing import SceneEditingService
from rigora.domain.character_recipe import (
    MOTION_CHOICES,
    VIEWS,
    CharacterRecipe,
)
from rigora.domain.geometry import transform_point
from rigora.resources import asset_path


@pytest.fixture(scope="module")
def specimen():
    """Build one complete specimen for independent command and animation assertions."""
    return build_character(
        CharacterRecipe(
            motions=MOTION_CHOICES,
            dress=("tee", "trousers", "sneakers"),
            alternatives={"Clothing": ("jacket",)},
        )
    )


def world_vertices(doc):
    """Read final scene-space mesh positions, including the skin deformation result."""
    pose = doc.animation.pose
    return {
        m.id: tuple(transform_point(pose.nodes[m.object_id].world_matrix, *p) for p in m.positions)
        for m in pose.meshes.values()
    }


def test_preview_preparation_cannot_replace_an_existing_scratch_project():
    """The optional preview destination must be empty, preserving any existing project."""
    doc = DocumentService()
    doc.new()
    source = doc.project
    with pytest.raises(ValueError, match="empty scratch document"):
        build_character(CharacterRecipe(), scratch=doc)
    assert doc.project is source


def test_creation_has_modular_vectors_and_real_wardrobe_choices(specimen):
    source = json.loads(specimen.files["character.json"])
    assert not source.get("object_library")
    doc = DocumentService()
    doc.new()
    baseline = doc.project
    root = CharacterCreationService(doc).create(specimen)
    from rigora.application_services.object_library import ObjectLibraryService

    assert ObjectLibraryService(doc).entries()
    scene = doc.project.scenes[0]
    assert CharacterService(doc).scene_objects() == (root,)
    assert all(a.kind == "vector" for a in doc.project.assets)
    assert {"Head", "Brow L", "Brow R"} <= {o.name for o in scene.objects}
    assert any(o.name.startswith("Eye L") for o in scene.objects)
    group = next(g for g in scene.groups if g.id == root)
    assert (
        group.transform.x + group.transform.pivot_x,
        group.transform.y + group.transform.pivot_y,
    ) == (
        scene.settings.width / 2,
        scene.settings.height / 2,
    )
    shirt = next(g for g in group.extra["outfits"] if g["name"] == "Clothing")
    assert [v["name"] for v in shirt["variants"] if v["visible"]] == ["tee"]
    assert "jacket" in {v["name"] for v in shirt["variants"]}
    CharacterService(doc).show_variant(
        root, shirt["id"], next(v["id"] for v in shirt["variants"] if v["name"] == "jacket"), True
    )
    doc.undo()
    doc.undo()
    assert doc.project == baseline


def test_every_motion_has_its_own_timeline_and_standing_feet_do_not_slide(specimen):
    doc = DocumentService()
    doc.new()
    CharacterCreationService(doc).create(specimen)
    scene = doc.project.scenes[0]
    assert {c.name for c in scene.clips} == set(MOTION_CHOICES)
    assert len({c.timeline_id for c in scene.clips}) == len(MOTION_CHOICES)
    feet = [b.id for r in scene.skeletons for b in r.bones if b.name.startswith("foot.")]
    for clip in scene.clips:
        doc.select_animation_clip(clip.id)
        start = doc.animation.evaluate(0)
        samples = [doc.animation.evaluate(clip.out_frame * i / 16) for i in range(17)]
        assert not any(p.warnings for p in samples)
        if clip.name.startswith(("Idle", "Stand")):
            # Sampled angular curves retain contacts within a quarter source pixel.
            for pose in samples:
                for key in feet:
                    assert pose.nodes[key].world_matrix == pytest.approx(
                        start.nodes[key].world_matrix, abs=0.25
                    )
        else:
            assert any(p.nodes != start.nodes for p in samples)
        if clip.loop:
            # Inclusive playback ranges wrap after the last nonduplicated frame.
            repeated = doc.animation.evaluate(clip.out_frame + 1, loop=True)
            for key, mesh in samples[0].meshes.items():
                for actual, expected in zip(
                    repeated.meshes[key].positions, mesh.positions, strict=True
                ):
                    assert actual == pytest.approx(expected, abs=1e-8)


def test_whole_character_motion_carries_feet_and_all_parts_without_overriding_actions(specimen):
    doc = DocumentService()
    doc.new()
    root = CharacterCreationService(doc).create(specimen)
    clip = next(c for c in doc.project.scenes[0].clips if c.name == "Idle")
    doc.select_animation_clip(clip.id)
    doc.animation.seek(17)
    before = world_vertices(doc)
    timelines = doc.project.scenes[0].timelines
    SceneEditingService(doc).transform((root,), dx=133, dy=-41)
    after = world_vertices(doc)
    for key, positions in before.items():
        for actual, (x, y) in zip(after[key], positions, strict=True):
            assert actual == pytest.approx((x + 133, y - 41))
    assert doc.project.scenes[0].timelines == timelines


def test_object_editor_uses_bind_space_after_whole_character_transform(specimen):
    """Stage transforms must not detach source bones from skin while editing the Object."""
    doc = DocumentService()
    doc.new()
    root = CharacterCreationService(doc).create(specimen)
    service = CharacterService(doc)
    doc.set_animation_context(root, frozenset(service.members(root)))
    before = world_vertices(doc)
    doc.set_animation_context(None)
    SceneEditingService(doc).transform(
        (root,), dx=133, dy=-41, rotation=27, scale_x=1.3, scale_y=1.3
    )
    canonical = doc.project
    doc.set_animation_context(root, frozenset(service.members(root)))
    after = world_vertices(doc)
    for key, positions in before.items():
        for actual, expected in zip(after[key], positions, strict=True):
            assert actual == pytest.approx(expected, abs=1e-8)
    assert doc.project is canonical
    doc.undo()
    doc.undo()
    assert not doc.context_clips()
    assert doc.animation_context is None and doc.animation_scope is None
    assert not doc.animation.pose.meshes


def test_scene_motion_keeps_action_contacts_and_import_duration(specimen):
    """Preserve action duration, release running contacts and restore them during idle."""
    doc = DocumentService()
    doc.new()
    root = CharacterCreationService(doc).create(specimen)
    service = CharacterService(doc)
    scene = doc.project.scenes[0]
    run = next(c for c in scene.clips if c.name == "Run")
    idle = next(c for c in scene.clips if c.name == "Idle")
    from rigora.domain.project import Project

    source = Project.from_dict(json.loads(specimen.files["character.json"].decode("utf-8"))).scenes[
        0
    ]
    original = next(c for c in source.clips if c.name == run.name)
    assert (run.out_frame + 1) / scene.settings.fps == pytest.approx(
        (original.out_frame + 1) / source.settings.fps
    )
    feet = [b.id for r in scene.skeletons for b in r.bones if b.name.startswith("foot.")]
    doc.select_animation_clip(run.id)
    expected = doc.animation.evaluate(7)
    doc.set_animation_context(None)
    service.place_motion(root, run.id, 0, 2)
    actual = doc.animation.evaluate(7)
    for key in feet:
        assert actual.nodes[key].world_matrix == pytest.approx(expected.nodes[key].world_matrix)
    service.place_motion(root, idle.id, 12, 2)
    first = doc.animation.evaluate(12)
    for frame in (18, 25, 40, 55, 65):
        pose = doc.animation.evaluate(frame)
        for key in feet:
            assert pose.nodes[key].world_matrix == pytest.approx(
                first.nodes[key].world_matrix, abs=0.25
            )


@pytest.mark.parametrize("view", VIEWS)
def test_views_are_real_separate_vector_projections(view):
    """Face projections have two eyes in front, one in profile, and no rear pupils."""
    from rigora.infrastructure.illustration import artwork

    _, _, parts = artwork(CharacterRecipe(view=view, motions=(), dress=()))
    eyes = [p for p in parts if p.family == "Eyes"]
    assert len(eyes) == (2 if view in ("Front", "Front 3/4") else 1)
    assert any("ellipse" in p.markup for p in eyes) == (view not in ("Back", "Back 3/4"))


def test_legacy_floor_contacts_follow_whole_rig_transforms():
    from rigora.application_services.rigging import RigService, from_matrix
    from rigora.application_services.skinning import SkinService
    from rigora.domain.entities import Constraint, Group

    doc = DocumentService()
    doc.new()
    service = SceneEditingService(doc)
    mesh = service.import_image(asset_path("examples/prop.svg"), 2, 2)
    bone = RigService(doc).create_bone((60, 50), (110, 50))
    SkinService(doc).bind(mesh, (bone,))
    floor = Group(
        name="Legacy floor contact",
        transform=from_matrix(doc.animation.pose.nodes[bone].world_matrix),
        extra={"studio_floor_plant": True},
    )
    service.commit(
        "Legacy world-space contact",
        groups=(floor,),
        constraints=(
            Constraint(name="Contact", kind="copy_transform", owner_id=bone, target_id=floor.id),
        ),
    )
    before = world_vertices(doc)
    service.part_edit = True
    service.transform((service.mesh(mesh).object_id,), dx=120, dy=40)
    after = world_vertices(doc)
    for key, positions in before.items():
        for actual, (x, y) in zip(after[key], positions, strict=True):
            assert actual == pytest.approx((x + 120, y + 40))


def test_recipe_rejects_unsafe_svg_colors():
    with pytest.raises(ValueError):
        replace(CharacterRecipe(), colors={"Skin": "url(file:///private)"})


def test_right_facing_three_quarter_near_arm_is_on_screen_left():
    """The viewer-left arm draws above the torso, with the far arm behind it."""
    from rigora.infrastructure.illustration import artwork

    _, joints, parts = artwork(CharacterRecipe(view="Front 3/4", motions=()))
    assert joints["hand.R"].root[0] < joints["hand.L"].root[0]
    layers = {p.bone: p.layer for p in parts if p.visible and not p.family}
    assert layers["upper_arm.L"] < layers["spine"] < layers["upper_arm.R"]


def test_worn_choice_is_independent_of_saved_alternatives():
    """Retaining a previous shirt must not prevent a new visible default."""
    from rigora.domain.creator_options import choose

    recipe = choose(
        CharacterRecipe(motions=(), alternatives={"Clothing": ("tee",)}), "Clothing", "jacket"
    )
    doc = DocumentService()
    doc.new()
    root = CharacterCreationService(doc).create(build_character(recipe))
    shirt = next(
        g for g in CharacterService(doc).record(root).extra["outfits"] if g["name"] == "Clothing"
    )
    assert [v["name"] for v in shirt["variants"] if v["visible"]] == ["jacket"]
    assert next(v["name"] for v in shirt["variants"] if v["id"] == shirt["default"]) == "jacket"
