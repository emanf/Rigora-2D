"""Imported editable raster palettes remain supported independently of SVG-only creation."""

from dataclasses import replace
from io import BytesIO

import pytest
from PIL import Image

from rigora.application_services.appearance import AppearanceService
from rigora.application_services.documents import DocumentService
from rigora.domain.character_recipe import default_character
from rigora.engine.vector_appearance import styled_artwork


@pytest.mark.parametrize("source_format", ("PNG", "JPEG"))
def test_creator_format_validation(source_format):
    """Reject unsupported Creator source formats before producing any assets."""
    with pytest.raises(ValueError, match="SVG"):
        replace(default_character("Boy"), source_format=source_format)


def test_png_palette_animation_changes_pixels_smoothly():
    """Sample real PNG color keys without mutating the original portable part."""
    from rigora.application_services.meshes import MeshService
    from rigora.engine.raster_artwork import rasterize_part

    source = rasterize_part(
        b'<svg xmlns="http://www.w3.org/2000/svg" width="80" height="90" viewBox="0 0 80 90">'
        b'<rect width="80" height="90" fill="#ff0000"/></svg>',
        320,
        360,
    )
    doc = DocumentService()
    doc.new()
    service = MeshService(doc)
    key = service.import_image_bytes("Part.png", source, 1, 1)
    doc.animation.seek(60)
    AppearanceService(doc).paint((key,), "fill", "#ff0000", "#0000ff", auto_key=True)
    colors = []
    for frame in (0, 30, 60):
        look = doc.animation.evaluate(frame).meshes[key].appearance
        with Image.open(BytesIO(styled_artwork(source, look))) as image:
            colors.append(image.getpixel((160, 180)))
    assert colors == [(255, 0, 0, 255), (128, 0, 128, 255), (0, 0, 255, 255)]
    assert doc.read_asset(service.mesh(key).asset_id) == source
