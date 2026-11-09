"""Encode and decode real RGBA animations, including partial alpha and lossless color."""

import shutil
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("PIL")
pytest.importorskip("resvg_py")

from PIL import Image

from rigora.api import AutomationError, RigoraAPI
from rigora.application_services.output import OutputSettings, raster_frame
from rigora.infrastructure.media_import import png_bytes


def alpha_api(root, encoder=None):
    """Own two changing frames with empty, half-transparent and opaque image regions."""
    api = RigoraAPI(root, encoder=encoder)
    api.execute("project_create", {"width": 64, "height": 64})
    for index, rgb in enumerate(((211, 83, 37), (32, 143, 209))):
        im = Image.new("RGBA", (20, 20), (*rgb, 128))
        for x in range(7, 13):
            for y in range(7, 13):
                im.putpixel((x, y), (*rgb, 255))
        (root / f"{index}.png").write_bytes(png_bytes(im))
    api.execute("sequence_import", {"paths": ["0.png", "1.png"], "fps": 24, "place": True})
    return api


@pytest.mark.parametrize(
    "kind,suffix,decoder",
    [
        ("webm", ".webm", "libvpx-vp9"),
        ("webm-vp8", ".webm", "libvpx"),
        ("mov", ".mov", None),
        ("ffv1", ".mkv", None),
    ],
)
def test_video_exports_preserve_real_alpha_and_ffv1_exact_rgba(tmp_path, kind, suffix, decoder):
    """Decode frames: container flags alone cannot prove that an alpha plane survived encoding."""
    binary = shutil.which("ffmpeg")
    if binary is None:
        pytest.skip("A host-configured FFmpeg is required for the actual encoder integration test.")
    api = alpha_api(tmp_path, Path(binary))
    path = tmp_path / f"animation{suffix}"
    args = {"path": path.name, "frames": [0, 1], "width": 64, "height": 64}
    # The standard extension selects VP9/MOV/FFV1; VP8 is an explicit WebM alternative.
    if kind == "webm-vp8":
        args["format"] = kind
    baseline = api.document.project
    result = api.execute("frame_render", args).data
    assert result["status"] == "completed" and result["format"] == kind
    command = [binary, "-v", "error"]
    if decoder:
        # FFmpeg's native VPx decoders may ignore WebM's separate alpha stream.
        command.extend(("-c:v", decoder))
    command.extend(
        ("-i", str(path), "-fps_mode", "passthrough", "-pix_fmt", "rgba", "-f", "rawvideo", "-")
    )
    decoded = subprocess.run(
        command,
        capture_output=True,
        timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert decoded.returncode == 0, decoded.stderr
    frame_bytes = 64 * 64 * 4
    assert len(decoded.stdout) == frame_bytes * 2
    for frame in range(2):
        actual = Image.frombytes(
            "RGBA", (64, 64), decoded.stdout[frame * frame_bytes : (frame + 1) * frame_bytes]
        )
        expected = raster_frame(api.document, frame, OutputSettings(width=64, height=64))
        assert actual.getpixel((0, 0))[3] == 0
        assert actual.getpixel((32, 32))[3] >= 254
        assert abs(actual.getpixel((24, 24))[3] - 128) <= 2
        if kind == "ffv1":
            assert actual.tobytes() == expected.tobytes()
    assert api.document.project is baseline
    api.close()


def test_apng_is_lossless_rgba_and_has_no_disposal_trails(tmp_path):
    """Pillow decodes both independent source frames with exact color and fractional alpha."""
    api = alpha_api(tmp_path)
    api.execute(
        "frame_render",
        {
            "path": "animation.apng",
            "frames": [0, 1],
            "width": 64,
            "height": 64,
        },
    )
    with Image.open(tmp_path / "animation.apng") as output:
        assert output.n_frames == 2
        for frame in range(2):
            output.seek(frame)
            expected = raster_frame(api.document, frame, OutputSettings(width=64, height=64))
            assert output.convert("RGBA").tobytes() == expected.tobytes()
    capabilities = {f["id"]: f for f in api.execute("output_formats").data["formats"]}
    assert capabilities["apng"]["available"]
    for kind in ("webm", "webm-vp8", "mov", "ffv1"):
        assert not capabilities[kind]["available"]
        with pytest.raises(AutomationError, match="FFmpeg"):
            api.execute(
                "frame_render",
                {
                    "path": "missing" + capabilities[kind]["extension"],
                    "format": kind,
                    "width": 64,
                    "height": 64,
                },
            )
    api.close()
