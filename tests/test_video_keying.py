"""Exercise real in-process matte/color math while prohibiting external programs."""

import io
import subprocess
from dataclasses import replace
from threading import Event

import numpy as np
import pytest
from PIL import Image, ImageDraw

from rigora.domain.project import ProjectError
from rigora.infrastructure import video_keying
from rigora.infrastructure.video_keying import KeyingSettings, border_color, key_cutout


def png(image):
    """Encode original bounded fixtures as media-review PNGs."""
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


@pytest.fixture(autouse=True)
def no_external_program(monkeypatch):
    """Any attempt to launch Blender or another executable fails these native pixel tests."""

    def fail(*args, **kwargs):
        raise AssertionError("Keying must run entirely inside Rigora")

    monkeypatch.setattr(subprocess, "Popen", fail)


@pytest.mark.parametrize("screen", ["#00ff00", "#0000ff", "white", "black"])
def test_auto_screen_keying_preserves_opaque_foreground(screen):
    """Colored and neutral screens disappear while distinct foreground pixels stay exact."""
    image = Image.new("RGB", (32, 32), screen)
    foreground = (210, 30, 40)
    ImageDraw.Draw(image).rectangle((8, 8, 23, 23), fill=foreground)
    output = Image.open(io.BytesIO(key_cutout(png(image), KeyingSettings())))
    assert output.mode == "RGBA" and output.size == image.size
    assert output.getpixel((0, 0)) == (0, 0, 0, 0)
    assert output.getpixel((16, 16)) == (*foreground, 255)


def test_linear_light_chroma_matte_and_despill_have_independent_controls():
    """Matte coverage follows screen dominance; despill changes RGB without changing alpha."""
    image = Image.new("RGB", (16, 16), (128, 180, 128))
    settings = KeyingSettings("Chroma", (0, 1, 0), tolerance=0, softness=0, despill=0)
    result = Image.open(io.BytesIO(key_cutout(png(image), settings)))
    red, green = [((v / 255 + 0.055) / 1.055) ** 2.4 for v in (128, 180)]
    expected = round((1 - (green - red) * (1 - red)) * 255)
    assert result.getpixel((8, 8)) == (128, 180, 128, expected)
    cleaned = Image.open(io.BytesIO(key_cutout(png(image), replace(settings, despill=1))))
    assert cleaned.getpixel((8, 8)) == (128, 128, 128, expected)


def test_neutral_soft_matte_retains_continuous_alpha_and_foreground_rgb():
    """Soft edges remain fractional, deterministic, and free of premultiplied darkening."""
    ramp = np.broadcast_to(np.arange(256, dtype=np.uint8)[None, :, None], (8, 256, 3)).copy()
    data = png(Image.fromarray(ramp))
    settings = KeyingSettings("Difference", (1, 1, 1), tolerance=0.1, softness=0.4)
    result = np.asarray(Image.open(io.BytesIO(key_cutout(data, settings))))
    assert len(np.unique(result[..., 3])) > 30
    assert np.all(np.diff(result[0, :, 3].astype(int)) <= 0)
    assert result[0, 0, 3] == 255 and result[0, 255, 3] == 0
    assert np.array_equal(result[result[..., 3] > 0, :3], ramp[result[..., 3] > 0])
    assert key_cutout(data, settings) == key_cutout(data, settings)


def test_matte_cleanup_grows_shrinks_blurs_and_feathers_real_edges():
    """All exposed cleanup controls affect matte geometry without shifting source pixels."""
    image = Image.new("RGB", (32, 32), "#00ff00")
    ImageDraw.Draw(image).rectangle((8, 8, 23, 23), fill="red")
    data = png(image)
    settings = KeyingSettings("Chroma", (0, 1, 0), despill=0)

    def alpha(**options):
        return np.asarray(Image.open(io.BytesIO(key_cutout(data, replace(settings, **options)))))[
            :, :, 3
        ]

    base = alpha()
    assert alpha(grow=2).sum() > base.sum() > alpha(grow=-2).sum()
    assert alpha(feather=3).sum() > base.sum() > alpha(feather=-3).sum()
    blurred = alpha(matte_blur=2)
    assert np.any((blurred > 0) & (blurred < 255))
    preprocessed = alpha(pre_blur=2)
    assert preprocessed.shape == base.shape and not np.array_equal(preprocessed, base)


def test_existing_transparency_passes_through_exactly():
    """Source alpha and matching foreground colors are kept byte-for-byte for PNG inputs."""
    image = Image.new("RGBA", (32, 32), "white")
    image.putpixel((0, 0), (12, 34, 56, 0))
    image.putpixel((16, 16), (255, 255, 255, 128))
    data = png(image)
    assert key_cutout(data, KeyingSettings()) == data


def test_indexed_png_transparency_keeps_matching_foreground_colors():
    """Palette transparency is source alpha even when the image has no explicit A band."""
    image = Image.new("P", (16, 16), 0)
    image.putpalette([0, 255, 0, 255, 255, 255] + [0] * 762)
    image.info["transparency"] = 0
    ImageDraw.Draw(image).rectangle((4, 4, 11, 11), fill=1)
    data = png(image)
    assert key_cutout(data, KeyingSettings("Difference", (1, 1, 1))) == data


def test_keying_cancellation_before_and_between_native_stages(monkeypatch):
    """Cancellation never returns a partial image, even after native matte computation."""
    data = png(Image.new("RGB", (16, 16), "#00ff00"))
    cancel = Event()
    cancel.set()
    with pytest.raises(ProjectError, match="cancelled"):
        key_cutout(data, KeyingSettings(), cancel=cancel)
    cancel.clear()
    original = video_keying._edge_pixels

    def edge(matte):
        result = original(matte)
        cancel.set()
        return result

    monkeypatch.setattr(video_keying, "_edge_pixels", edge)
    with pytest.raises(ProjectError, match="cancelled"):
        key_cutout(data, KeyingSettings(), cancel=cancel)


def test_keying_rejects_invalid_settings_images_and_neutral_chroma():
    """Invalid inputs fail explicitly without NaNs or unbounded allocations."""
    for options in (
        {"method": "script"},
        {"color": (0, 1)},
        {"softness": float("nan")},
        {"pre_blur": 1.5},
        {"grow": 17},
        {"balance": -1},
    ):
        with pytest.raises(ProjectError):
            KeyingSettings(**options)
    with pytest.raises(ProjectError, match="colored screen"):
        key_cutout(png(Image.new("RGB", (16, 16), "white")), KeyingSettings("Chroma", (1, 1, 1)))
    with pytest.raises(ProjectError, match="dimensions"):
        key_cutout(png(Image.new("RGB", (1921, 1), "white")), KeyingSettings())
    with pytest.raises(ProjectError, match="decoded"):
        key_cutout(b"invalid image", KeyingSettings())
    assert border_color(png(Image.new("RGB", (16, 16), "#00ff00"))) == (0, 1, 0)
