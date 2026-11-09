"""Actual headless frame compositing, encoding, queued snapshots and output publication."""

import json
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("PIL")
pytest.importorskip("resvg_py")

from PIL import Image

from rigora.api import AutomationError, RigoraAPI
from rigora.infrastructure.media_import import png_bytes


def test_deformed_atlas_uv_region_preserves_opaque_joint_seams_and_original_source():
    """Cropped render intermediates retain UV placement without internal alpha cracks."""
    from dataclasses import replace

    from rigora.application_services.documents import DocumentService
    from rigora.application_services.meshes import MeshService
    from rigora.application_services.output import OutputSettings, raster_frame
    from rigora.domain.entities import Transform
    from rigora.domain.project import SceneSettings

    doc = DocumentService()
    doc.new(settings=SceneSettings(width=80, height=80))
    service = MeshService(doc)
    original = png_bytes(Image.new("RGBA", (100, 100), (240, 120, 80, 255)))
    key = service.import_image_bytes("atlas.png", original, columns=2, rows=2)
    mesh = service.mesh(key)
    mesh = replace(
        mesh,
        vertices=tuple(
            replace(
                v,
                x=v.x * 0.5 + (10 if i == 4 else 0),
                y=v.y * 0.5,
                uv=(0.25 + 0.5 * v.uv[0], 0.25 + 0.5 * v.uv[1]),
            )
            for i, v in enumerate(mesh.vertices)
        ),
    )
    service.commit(
        "Deform atlas region",
        meshes=(mesh,),
        objects=tuple(replace(o, transform=Transform(x=10, y=10)) for o in service.scene.objects),
    )
    output = raster_frame(doc, 0, OutputSettings(width=80, height=80))
    assert all(
        output.getpixel((x, y)) == (240, 120, 80, 255) for y in range(12, 58) for x in range(12, 58)
    )
    assert doc.read_asset(mesh.asset_id) == original


def animated_api(root, **kwargs):
    """Build a small original sequence with two distinct colors and transparent outside pixels."""
    api = RigoraAPI(root, **kwargs)
    api.execute("project_create", {"width": 64, "height": 64})
    for index, color in enumerate(("red", "blue")):
        (root / f"{index}.png").write_bytes(png_bytes(Image.new("RGBA", (20, 20), color)))
    api.execute("sequence_import", {"paths": ["0.png", "1.png"], "fps": 24, "place": True})
    return api


def wait_for_job(api, key):
    """Poll a bounded owned worker while it renders outside the caller's thread."""
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        result = api.execute("render_status", {"job_id": key}).data
        if result["status"] in ("completed", "failed", "cancelled"):
            return result
        time.sleep(0.01)
    raise AssertionError("Render worker did not finish.")


def test_transparent_png_sequence_and_portable_interchange(tmp_path):
    """PNG frames use changing evaluated sources, and runtime JSON carries actual world geometry."""
    api = animated_api(tmp_path)
    baseline = api.document.project
    result = api.execute(
        "frame_render", {"path": "frames/frame.png", "frames": [0, 1], "width": 64, "height": 64}
    ).data
    first, second = [Image.open(tmp_path / p) for p in result["paths"]]
    assert first.getpixel((0, 0))[3] == 0
    assert first.getpixel((32, 32)) == (255, 0, 0, 255)
    assert second.getpixel((32, 32)) == (0, 0, 255, 255)
    api.execute(
        "frame_render", {"path": "runtime.json", "format": "runtime-json", "frames": [0, 1]}
    )
    runtime = json.loads((tmp_path / "runtime.json").read_text())
    assert runtime["format"] == "rigora.runtime-animation" and runtime["version"] == 1
    assert len(runtime["samples"]) == 2 and len(runtime["assets"]) == 2
    assert runtime["samples"][0]["meshes"][0]["vertices"][0]["x"] == 22
    assert api.document.project is baseline
    api.execute("project_export", {"path": "portable.rigora", "format": "rigora"})
    other = RigoraAPI(tmp_path)
    other.execute("project_open", {"path": "portable.rigora"})
    assert other.document.project == baseline


@pytest.mark.parametrize("kind", ["gif", "webp", "spritesheet"])
def test_animated_formats_and_game_atlas(tmp_path, kind):
    """Encoded animation changes pixels; atlas metadata correctly locates each sampled frame."""
    api = animated_api(tmp_path)
    suffix = "png" if kind == "spritesheet" else kind
    result = api.execute(
        "frame_render",
        {
            "path": f"animation.{suffix}",
            "format": kind,
            "frames": [0, 1],
            "width": 64,
            "height": 64,
            "fps": 10,
            "columns": 2,
        },
    ).data
    assert result["status"] == "completed"
    image = Image.open(tmp_path / f"animation.{suffix}")
    if kind == "spritesheet":
        metadata = json.loads((tmp_path / "animation.json").read_text())
        assert image.size == (128, 64) and metadata["frames"][1]["rect"] == [64, 0, 64, 64]
        assert image.getpixel((96, 32)) == (0, 0, 255, 255)
    else:
        assert image.n_frames == 2
        image.seek(1)
        assert image.convert("RGBA").getpixel((32, 32))[:3] == (0, 0, 255)
        assert image.convert("RGBA").getpixel((0, 0))[3] == 0


def test_real_bone_and_ffd_deformation_render_at_final_resolution(tmp_path):
    """Render evaluated vector deformation at the requested output resolution."""
    api = RigoraAPI(tmp_path)
    api.execute("project_create", {"width": 800, "height": 600})
    actor = api.execute(
        "character_create", {"content": "Bolt · Stick robot", "x": 350, "y": 160}
    ).data
    api.execute("motion_apply", {"content": "Natural · Walk", "target_id": actor["rig_ids"][0]})
    api.execute("deformer_apply", {"content": "Soft breathing", "mesh_id": actor["mesh_ids"][0]})
    result = api.execute(
        "frame_render", {"path": "deformed.png", "frames": [0, 7], "width": 1200, "height": 900}
    ).data
    a, b = [Image.open(tmp_path / p).convert("RGBA") for p in result["paths"]]
    assert a.size == (1200, 900) and a.getbbox()
    assert a.tobytes() != b.tobytes()
    assert not any(asset.media_type == "image/png" for asset in api.document.project.assets)


def test_queue_snapshot_cancellation_and_overwrite_protection(tmp_path, monkeypatch):
    """Cancelling active/queued work discards staging and never replaces an existing output."""
    from rigora.application_services import output

    api = animated_api(tmp_path)
    entered, release = threading.Event(), threading.Event()
    original = output.raster_frame
    snapshots = []

    def blocked(document, frame, settings):
        """Pause the real renderer long enough to mutate the caller and request cancellation."""
        snapshots.append(document.project)
        entered.set()
        assert release.wait(10)
        return original(document, frame, settings)

    monkeypatch.setattr(output, "raster_frame", blocked)
    (tmp_path / "existing-0000.png").write_bytes(b"existing bytes")
    with pytest.raises(AutomationError, match="approval"):
        api.execute("render_submit", {"path": "existing.png", "frames": [0]})
    job = api.execute(
        "render_submit",
        {
            "path": "existing.png",
            "frames": [0, 1],
            "width": 64,
            "height": 64,
            "approve_overwrite": True,
        },
    ).data
    assert entered.wait(5)
    source = api.document.project
    api.execute("object_create", {"name": "Later change"})
    assert snapshots[0] is source and api.document.project is not source
    queued = api.execute(
        "render_submit", {"path": "queued.png", "frames": [0], "width": 64, "height": 64}
    ).data
    assert api.execute("render_cancel", {"job_id": queued["job_id"]}).data["status"] == "cancelled"
    api.execute("render_cancel", {"job_id": job["job_id"]})
    release.set()
    assert wait_for_job(api, job["job_id"])["status"] == "cancelled"
    api.close()
    assert (tmp_path / "existing-0000.png").read_bytes() == b"existing bytes"
    assert not (tmp_path / "existing-0001.png").exists()
    assert not list(tmp_path.glob(".rigora-render-*"))


def test_queue_complete_dry_run_limits_and_fixed_encoder(tmp_path):
    """Queued progress completes, dry runs publish nothing, and video uses an explicit encoder."""
    encoder = shutil.which("ffmpeg")
    api = animated_api(tmp_path, encoder=Path(encoder) if encoder else None)
    plan = api.execute(
        "render_submit",
        {"path": "planned.png", "frames": [0, 1], "width": 64, "height": 64},
        dry_run=True,
    )
    assert plan.data["status"] == "planned" and not list(tmp_path.glob("planned*"))
    job = api.execute(
        "render_submit", {"path": "queue.png", "frames": [0, 1], "width": 64, "height": 64}
    ).data
    result = wait_for_job(api, job["job_id"])
    assert result["status"] == "completed" and result["completed"] == 2
    api.close()
    if encoder:
        api.execute(
            "frame_render", {"path": "video.mp4", "frames": [0, 1], "width": 64, "height": 64}
        )
        assert (tmp_path / "video.mp4").stat().st_size > 100
        decoded = subprocess.run(
            [encoder, "-v", "error", "-i", str(tmp_path / "video.mp4"), "-f", "null", "-"],
            capture_output=True,
            timeout=15,
        )
        assert decoded.returncode == 0, decoded.stderr
    with pytest.raises(AutomationError):
        api.execute(
            "frame_render",
            {"path": "huge.webp", "frames": list(range(60)), "width": 4096, "height": 4096},
        )
    assert not (tmp_path / "huge.webp").exists()


def test_streamed_hd_gif_exceeds_old_budget_with_correct_palettes_timing_and_alpha(tmp_path):
    """A real 70-megapixel animation decodes every frame without retaining RGBA frames."""
    api = animated_api(tmp_path)
    baseline = api.document.project
    result = api.execute(
        "frame_render",
        {
            "path": "hd.gif",
            "format": "gif",
            "frames": [0, 1] * 17,
            "width": 1920,
            "height": 1080,
            "fps": 24,
        },
    ).data
    assert result["status"] == "completed" and result["frame_count"] == 34
    with Image.open(tmp_path / "hd.gif") as image:
        assert image.size == (1920, 1080) and image.n_frames == 34
        assert image.info["loop"] == 0
        duration = 0
        for index in range(34):
            image.seek(index)
            rgba = image.convert("RGBA")
            assert rgba.getpixel((0, 0))[3] == 0
            assert rgba.getpixel((960, 540)) == (
                (255, 0, 0, 255) if index % 2 == 0 else (0, 0, 255, 255)
            )
            duration += image.info["duration"]
        assert abs(duration - 34 * 1000 / 24) <= 5
    assert api.document.project is baseline
    assert not list(tmp_path.glob(".rigora-render-*"))
    api.close()


def test_streamed_gif_clears_previous_artwork_and_supports_play_once(tmp_path):
    """Independent local palettes and disposal clear moving sprites instead of leaving trails."""
    api = RigoraAPI(tmp_path)
    api.execute("project_create", {"width": 64, "height": 64})
    for index, (start, color) in enumerate(((8, "red"), (32, "blue"))):
        image = Image.new("RGBA", (64, 64))
        image.paste(color, (start, 8, start + 12, 20))
        (tmp_path / f"{index}.png").write_bytes(png_bytes(image))
    api.execute("sequence_import", {"paths": ["0.png", "1.png"], "fps": 24, "place": True})
    api.execute(
        "frame_render",
        {
            "path": "once.gif",
            "frames": [0, 1],
            "width": 64,
            "height": 64,
            "loop": False,
        },
    )
    with Image.open(tmp_path / "once.gif") as result:
        assert result.n_frames == 2 and "loop" not in result.info
        first = result.convert("RGBA")
        left, top, right, bottom = first.getbbox()
        old_center = ((left + right) // 2, (top + bottom) // 2)
        assert first.getpixel(old_center) == (255, 0, 0, 255)
        result.seek(1)
        second = result.convert("RGBA")
        assert second.getpixel(old_center)[3] == 0
        left, top, right, bottom = second.getbbox()
        assert second.getpixel(((left + right) // 2, (top + bottom) // 2)) == (0, 0, 255, 255)
    api.close()


def test_cancelled_streamed_gif_preserves_destination_and_discards_partial_file(tmp_path):
    """Partial GIF blocks stay private and never replace an existing output on cancellation."""
    from rigora.application_services.output import OutputService, OutputSettings, RenderCancelled

    api = animated_api(tmp_path)
    destination = tmp_path / "existing.gif"
    destination.write_bytes(b"keep original")
    cancel = threading.Event()
    with pytest.raises(RenderCancelled):
        OutputService(lambda path: tmp_path / path).export(
            api.document,
            "existing.gif",
            OutputSettings(format="gif", frames=(0, 1), width=64, height=64),
            cancel=cancel,
            progress=lambda done, total: cancel.set(),
        )
    assert destination.read_bytes() == b"keep original"
    assert not list(tmp_path.glob(".rigora-render-*"))
    api.close()
