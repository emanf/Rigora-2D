"""Cards report real source formats; rejected PNG artwork is absent from bundled content."""

import pytest

from rigora.application_services.vector_creation import build_vector
from rigora.domain.content import ContentItem, asset_format, content_families, content_format
from rigora.domain.entities import Asset
from rigora.domain.project import ProjectError
from rigora.domain.vector_catalog import VectorRecipe
from rigora.resources import asset_path


@pytest.mark.parametrize(
    "sources,expected",
    [
        ({"a": "body.svg"}, "SVG"),
        ({"a": "body.png"}, "PNG"),
        ({"a": "body.svg", "b": "face.png"}, "MIXED"),
    ],
)
def test_format_ignores_the_raster_poster(sources, expected):
    """An SVG template with a pre-rendered PNG icon must still be labelled SVG."""
    item = ContentItem(
        name="Card",
        kind="scene",
        category="Characters",
        author="Test",
        license="Test",
        thumbnail="poster.png",
        payload={"sources": sources},
    )
    assert content_format(item) == expected
    assert (
        asset_format(
            Asset(name="Imported", source="data/source.bin", kind="raster", media_type="image/png")
        )
        == "PNG"
    )
    assert "trees" in dict(content_families("Environment")).values()
    assert "hats" not in dict(content_families("Environment")).values()


def test_rejected_png_collection_is_not_shipped():
    """No failed atlas, pack, or cached PNG card can reappear in the library."""
    from dataclasses import replace

    from rigora.domain.character_recipe import default_character

    asset_root = asset_path("shapes/bone.svg").parent.parent
    assert not list((asset_root / "library").glob("creator-png-*.rigpack"))
    assert not list((asset_root / "thumbnails").glob("rigora-png-creator-*"))
    assert not (asset_root / "characters/painted").exists()
    assert not (asset_root / "library/illustrated-png-characters.rigpack").exists()
    assert not (asset_root / "characters/png/man-casual.png").exists()
    assert not (asset_root / "characters/png/woman-explorer.png").exists()
    with pytest.raises(ProjectError, match="SVG"):
        replace(default_character("Boy"), source_format="PNG", artwork_collection="painted")
    with pytest.raises(ProjectError, match="SVG"):
        build_vector(VectorRecipe(source_format="PNG", artwork_collection="painted"))


def test_retired_transport_catalog_is_not_advertised_as_authored_art():
    """Removed resource identities are rejected instead of synthesizing misleading views."""
    with pytest.raises(ProjectError, match="retired"):
        VectorRecipe(kind="Vehicles", design_id="City bicycle", name="Bike", view="Side")
