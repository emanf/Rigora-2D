"""Raster preview caching and honest creator availability after collection withdrawal."""

import pytest
from test_object_scene_actions_gui import readable_offscreen_fonts as readable_offscreen_fonts
from test_roots_soft_drag_gui import editor as editor

pytestmark = pytest.mark.gui


def test_png_palette_preview_uses_cached_resolution(qapp):
    """Neutral playback reuses pixels; palette edits render only the displayed preview size."""
    from rigora.engine.raster_artwork import rasterize_part
    from rigora.presentation.artwork import ArtworkCache, decode_artwork

    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="80" height="90" viewBox="0 0 80 90">'
        b'<rect x="10" y="10" width="60" height="70" fill="#ff0000"/></svg>'
    )
    source = rasterize_part(svg, 320, 360)
    cache = ArtworkCache()
    image = decode_artwork(source, 128)
    cache.put("part", image, source)
    neutral = {"palette": [{"role": "fill", "source": "#ff0000", "r": 255, "g": 0, "b": 0}]}
    assert cache.styled("part", neutral) is image
    changed = {"palette": [{"role": "fill", "source": "#ff0000", "r": 0, "g": 0, "b": 255}]}
    preview = cache.styled("part", changed)
    assert preview.width() <= 128 and preview.height() <= 128
    assert preview.pixelColor(preview.width() // 2, preview.height() // 2).name() == "#0000ff"
    assert cache.styled("part", changed) is preview


def test_creators_have_no_png_creation_mode(editor):
    """Canceled PNG creation leaves the SVG inventories and raster import support intact."""
    from rigora.domain.project import ProjectError

    editor.show_character_wizard()
    wizard = editor.character_wizard
    assert wizard.recipe.source_format == "SVG"
    assert "PNG characters" not in wizard.sections
    wizard.close()
    with pytest.raises(ProjectError, match="editable SVG"):
        editor.show_character_wizard(source_format="PNG")
    editor.show_vector_creator("Animals")
    creator = editor.vector_creator
    assert creator.recipe.source_format == "SVG"
    creator.close()
    with pytest.raises(ProjectError, match="editable SVG"):
        editor.show_vector_creator("Animals", "PNG")
