"""Current SVG catalogs retain source fidelity, ownership and editable evaluated motion."""

import io
import math
from dataclasses import replace
from xml.etree import ElementTree

import pytest
from PIL import Image

from rigora.application_services.character_creation import build_character, raster_source
from rigora.application_services.content_library import content_project
from rigora.application_services.illustration_cache import recipe_for
from rigora.application_services.object_library import object_fragment, object_roots
from rigora.domain.character_recipe import VIEWS
from rigora.domain.illustration_catalog import CREATOR_DESIGNS, TEMPLATE_DESIGNS
from rigora.engine.evaluation import SceneEvaluator
from rigora.infrastructure.illustration import artwork, portrait
from rigora.resources import asset_path


@pytest.mark.parametrize("design", TEMPLATE_DESIGNS, ids=lambda d: d.id)
def test_template_sources_ownership_and_source_actions_remain_portable(design):
    """Evaluate serialized source actions and verify all artwork survives object extraction."""
    built = build_character(recipe_for(design))
    project = content_project(built.item, built.files)
    scene = project.scenes[0]
    roots = object_roots(scene)
    assert len(roots) == 1
    fragment = object_fragment(scene, (roots[0].id,))
    for field in ("objects", "meshes", "skeletons", "constraints", "deformers"):
        assert getattr(fragment, field) == getattr(scene, field)
    assert all(built.files[name] for name in built.item.payload["sources"].values())
    for clip in scene.clips:
        evaluator = SceneEvaluator(scene, clip.id)
        poses = [evaluator.evaluate(f) for f in (0, clip.out_frame * 0.37, clip.out_frame)]
        assert all(not pose.warnings for pose in poses)
        assert all(
            math.isfinite(v)
            for pose in poses
            for node in pose.nodes.values()
            for v in node.world_matrix
        )


@pytest.mark.parametrize(
    "design",
    [d for d in CREATOR_DESIGNS if d.anatomy not in ("human", "robot")],
    ids=lambda d: d.id,
)
@pytest.mark.parametrize("view", VIEWS)
def test_animal_art_has_owned_parts_finite_rig_and_visible_vector_preview(design, view):
    """Each current species/view uses attached editable parts and renders nonempty artwork."""
    recipe = replace(recipe_for(design), view=view, motions=())
    _, joints, parts = artwork(recipe)
    assert parts and all(part.bone in joints for part in parts)
    assert all(math.isfinite(v) for j in joints.values() for v in (*j.root, *j.tip))
    source = portrait(recipe)
    assert ElementTree.fromstring(source).tag.endswith("svg")
    with Image.open(io.BytesIO(raster_source(source, height=180))) as image:
        assert image.getchannel("A").getbbox()
    eyes = [part for part in parts if part.name.startswith("Eye ")]
    assert bool(eyes) == (not view.startswith("Back"))
    if view == "Front 3/4":
        assert len(eyes) == 2 and eyes[0].layer < eyes[1].layer


def test_packaged_svg_sources_are_well_formed_and_rasters_decode():
    """Canonical assets remain independently usable without retired generated pack files."""
    root = asset_path("shapes/bone.svg").parent.parent
    for path in root.rglob("*"):
        if path.suffix.lower() == ".svg":
            assert ElementTree.parse(path).getroot().tag.endswith("svg"), path
        elif path.suffix.lower() in (".png", ".jpg", ".jpeg"):
            with Image.open(path) as image:
                image.verify()


def test_all_generated_posters_and_vector_members_decode(catalog_cache_root):
    """Validate actual published cache members rather than recreating retired pack snapshots."""
    import json

    from rigora.application_services.illustration_cache import cached_catalog
    from rigora.infrastructure.content_packs import read_pack

    target = cached_catalog(catalog_cache_root)
    record = json.loads((target / "complete.json").read_text(encoding="utf-8"))
    assert record["posters"]
    for name in record["posters"]:
        assert (target / name).is_file()
        if name.endswith(".png"):
            with Image.open(target / name) as image:
                image.verify()
    scene_count = 0
    for path in target.glob("*.rigpack"):
        pack, files = read_pack(path)
        for name, data in files.items():
            if name.endswith(".svg"):
                assert ElementTree.fromstring(data).tag.endswith("svg")
        for item in pack.items:
            if item.kind == "scene":
                project = content_project(item, files)
                scene = project.scenes[0]
                roots = object_roots(scene)
                assert len(roots) == 1
                owned = object_fragment(scene, (roots[0].id,))
                assert owned.meshes == scene.meshes and owned.skeletons == scene.skeletons
                scene_count += 1
    assert scene_count >= len(TEMPLATE_DESIGNS)
