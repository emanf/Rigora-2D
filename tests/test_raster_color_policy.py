"""Profile/orientation corrections keep original sources, alpha and one-step Undo."""

import io

import pytest
from PIL import Image, ImageCms

from rigora.application_services.documents import DocumentService
from rigora.application_services.meshes import MeshService
from rigora.domain.project import ProjectError
from rigora.infrastructure.raster_color import normalized_raster


def test_exif_import_corrects_bounds_and_pixels_retains_original_and_undo(tmp_path):
    source = Image.new("RGBA", (3, 2))
    source.putpixel((0, 0), (255, 0, 0, 51))
    source.putpixel((2, 1), (0, 255, 0, 204))
    exif = Image.Exif()
    exif[274] = 6
    stream = io.BytesIO()
    source.save(stream, "PNG", exif=exif)
    original = stream.getvalue()
    doc = DocumentService()
    doc.new()
    baseline = doc.project
    key = MeshService(doc).register_image_bytes("rotated.png", original)
    asset = next(a for a in doc.project.assets if a.id == key)
    assert (asset.extra["image_width"], asset.extra["image_height"]) == (2, 3)
    assert doc.read_asset(asset.extra["source_asset_id"]) == original
    with Image.open(io.BytesIO(doc.read_asset(key))) as image:
        assert image.getpixel((1, 0)) == (255, 0, 0, 51)
        assert image.getpixel((0, 2)) == (0, 255, 0, 204)
        assert image.info["icc_profile"] and image.getexif().get(274, 1) == 1
    path = tmp_path / "oriented.rigora"
    doc.save(path)
    reopened = DocumentService()
    reopened.open(path)
    assert reopened.read_asset(key) == doc.read_asset(key)
    assert reopened.read_asset(asset.extra["source_asset_id"]) == original
    doc.undo()
    assert doc.project == baseline


def test_lab_profile_converts_to_srgb_and_untagged_png_stays_byte_exact():
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("LAB")).tobytes()
    source = Image.new("LAB", (2, 2), (137, 128, 128))
    stream = io.BytesIO()
    source.save(stream, "TIFF", icc_profile=profile)
    data, metadata = normalized_raster(stream.getvalue())
    assert metadata["color_space"] == "sRGB"
    with Image.open(io.BytesIO(data)) as image:
        red, green, blue, alpha = image.getpixel((0, 0))
        assert max(red, green, blue) - min(red, green, blue) <= 1
        assert 125 <= red <= 132 and alpha == 255
    plain = io.BytesIO()
    Image.new("RGBA", (2, 2), (10, 30, 50, 100)).save(plain, "PNG")
    assert normalized_raster(plain.getvalue()) == (plain.getvalue(), {})


def test_invalid_profile_rejects_import_without_partial_assets():
    stream = io.BytesIO()
    Image.new("RGB", (2, 2)).save(stream, "PNG", icc_profile=b"broken-profile")
    doc = DocumentService()
    doc.new()
    baseline = doc.project
    with pytest.raises(ProjectError, match="profile"):
        MeshService(doc).register_image_bytes("broken.png", stream.getvalue())
    assert doc.project is baseline and not doc.can_undo
