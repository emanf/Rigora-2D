"""Original vector catalogs contain distinct, editable and looping specimens."""

import xml.etree.ElementTree as ET

import pytest

from rigora.application_services.character_creation import CharacterCreationService
from rigora.application_services.content_library import ContentService
from rigora.application_services.documents import DocumentService
from rigora.application_services.object_views import ObjectViewsService
from rigora.application_services.vector_creation import build_vector, vector_colors, vector_portrait
from rigora.domain.character_recipe import VIEWS
from rigora.domain.illustration_catalog import CREATOR_DESIGNS, design_by_id
from rigora.domain.vector_catalog import CATALOGS, VectorRecipe, vector_poster, vector_views


@pytest.mark.parametrize("kind,names", list(CATALOGS.items()))
def test_catalog_is_unique_renderable_and_every_action_evaluates(kind, names):
    """Exercise the packaged templates through the same content importer used by the editor."""
    assert set(names) == {
        design.id for design in CREATOR_DESIGNS if design.anatomy not in ("human", "robot")
    }
    signatures = set()
    for name in names:
        colors = vector_colors(kind, name)
        recipe = VectorRecipe(
            kind=kind,
            design_id=name,
            name=name,
            primary=colors[0],
            accent=colors[1],
            view="Front 3/4" if kind in ("Animals", "Household") else vector_views(kind)[0],
        )
        portrait = vector_portrait(recipe)
        # Remove the title so label differences cannot stand in for distinct SVG geometry.
        svg = ET.fromstring(portrait)
        for title in svg.findall("{http://www.w3.org/2000/svg}title"):
            svg.remove(title)
        geometry = ET.tostring(svg)
        signatures.add(geometry)
        assert vector_poster(kind, name) == "animal/" + name
        built = build_vector(recipe)
        doc = DocumentService()
        doc.new()
        ContentService(doc).apply(built.item, built.files)
        assert all(a.kind == "vector" for a in doc.project.assets)
        animated = False
        for clip in doc.project.scenes[0].clips:
            doc.select_animation_clip(clip.id)
            start = doc.animation.evaluate(0)
            end = doc.animation.evaluate(clip.out_frame + 1, loop=True)
            middle = doc.animation.evaluate(clip.out_frame * 0.37)
            assert not middle.warnings
            animated |= any(
                middle.nodes[k].world_matrix != n.world_matrix
                or middle.nodes[k].opacity != n.opacity
                for k, n in start.nodes.items()
            )
            for key, node in start.nodes.items():
                assert end.nodes[key].world_matrix == pytest.approx(node.world_matrix, abs=1e-7)
        assert len(doc.project.scenes[0].skeletons) == 1
        assert animated
    assert len(signatures) == len(names)


@pytest.mark.parametrize(
    "kind,name", [(kind, name) for kind, names in CATALOGS.items() for name in names]
)
def test_catalog_views_roundtrip_and_keep_one_active_rig(kind, name):
    """Turnarounds remain editable while inactive views cost no evaluated nodes."""
    recipe = VectorRecipe(kind=kind, design_id=name, name=design_by_id(name).name)
    doc = DocumentService()
    doc.new()
    root = CharacterCreationService(doc).create(build_vector(recipe))
    service = ObjectViewsService(doc)
    for view in VIEWS:
        service.apply(root, service.prepare(root, view))
        assert service.current(root) == view
        assert len(service.scene.skeletons) == 1
        assert not doc.animation.evaluate(8).warnings
    service.apply(root, service.prepare(root, "Three-quarter"))


def test_animal_idle_keeps_contact_feet_stationary():
    """Breathing moves body/head/tail while connected leg tips retain their floor contacts."""
    doc = DocumentService()
    doc.new()
    built = build_vector(VectorRecipe())
    ContentService(doc).apply(built.item, built.files)
    first = doc.animation.evaluate(0)
    feet = [
        b for r in doc.project.scenes[0].skeletons for b in r.bones if b.name.startswith("leg.")
    ]
    for frame in (7, 29, 60, 89):
        pose = doc.animation.evaluate(frame)
        for foot in feet:
            assert pose.nodes[foot.id].world_matrix == pytest.approx(
                first.nodes[foot.id].world_matrix, abs=1e-8
            )
