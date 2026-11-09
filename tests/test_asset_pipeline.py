"""Source-preserving sprite, layered artwork and audio import with canonical playback."""

import io
import wave
import zipfile

import pytest

pytest.importorskip("PIL")

from PIL import Image

from rigora.api import AutomationError, RigoraAPI
from rigora.infrastructure.media_import import png_bytes


def make_ora(path, *, blend="svg:src-over"):
    """Create original two-layer artwork with offsets, visibility and translucent pixels."""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "image/openraster")
        archive.writestr(
            "stack.xml",
            (
                '<image w="64" h="64"><stack name="Character">'
                '<layer name="Face" src="data/front.png" x="12" y="12" opacity="0.5" '
                f'composite-op="{blend}"/>'
                '<layer name="Body" src="data/back.png" x="8" y="8"/>'
                "</stack></image>"
            ),
        )
        archive.writestr("data/front.png", png_bytes(Image.new("RGBA", (24, 24), "white")))
        archive.writestr("data/back.png", png_bytes(Image.new("RGBA", (32, 40), "#404040")))


def test_sequences_sprites_and_original_bytes_roundtrip(tmp_path):
    """Sprite sources, independent instances and deterministic sampled frames survive save/load."""
    api = RigoraAPI(tmp_path)
    api.execute("project_create", {"width": 64, "height": 64})
    paths = []
    for index, color in enumerate(("red", "blue")):
        name = f"frame-{index}.png"
        (tmp_path / name).write_bytes(png_bytes(Image.new("RGBA", (16, 16), color)))
        paths.append(name)
    imported = api.execute("sequence_import", {"paths": paths, "fps": 24, "place": True}).data
    frames = imported["frame_asset_ids"]
    key = imported["mesh_id"]
    assert api.document.animation.evaluate(0).meshes[key].asset_id == frames[0]
    assert api.document.animation.evaluate(1).meshes[key].asset_id == frames[1]
    assert api.document.animation.evaluate(2).meshes[key].asset_id == frames[0]
    assert api.document.animation.evaluate(0).meshes[key].asset_id == frames[0]
    assert len(api.document.history.undo_stack) == 1
    clone = api.execute("sequence_place", {"asset_id": imported["asset_id"]}).data
    assert clone["mesh_id"] != key
    api.execute("project_save", {"path": "sequence.rigora"})
    reopened = RigoraAPI(tmp_path)
    reopened.execute("project_open", {"path": "sequence.rigora"})
    assert reopened.document.animation.evaluate(1).meshes[key].asset_id == frames[1]
    assert reopened.document.read_asset(frames[0]) == (tmp_path / paths[0]).read_bytes()
    api.execute("project_export", {"path": "sequence.rigpack", "format": "rigpack"})
    reopened.execute("asset_pack_install", {"path": "sequence.rigpack"})
    entry = next(e for e in reopened.library.entries() if e.item.name == "Shared scene")
    added = reopened.execute("template_apply", {"content": entry.key}).data
    assert len(added["mesh_ids"]) == 2
    assert reopened.execute("project_validate").data["valid"]
    sheet = Image.new("RGBA", (32, 16))
    sheet.paste(Image.new("RGBA", (16, 16), "red"), (0, 0))
    sheet.paste(Image.new("RGBA", (16, 16), "blue"), (16, 0))
    (tmp_path / "sheet.png").write_bytes(png_bytes(sheet))
    sprites = api.execute(
        "spritesheet_import", {"path": "sheet.png", "frame_width": 16, "frame_height": 16}
    ).data
    assert len(sprites["frame_asset_ids"]) == 2
    assert (
        api.document.read_asset(sprites["source_asset_id"]) == (tmp_path / "sheet.png").read_bytes()
    )


def test_layered_import_draw_order_diagnostics_and_undo(tmp_path):
    """ORA preserves layer names, offsets and source bytes; unsupported blends require opt-in."""
    make_ora(tmp_path / "character.ora")
    make_ora(tmp_path / "multiply.ora", blend="svg:multiply")
    api = RigoraAPI(tmp_path)
    api.execute("project_create", {"width": 64, "height": 64})
    source = api.document.project
    with pytest.raises(AutomationError, match="blend"):
        api.execute("layered_import", {"path": "multiply.ora"})
    assert api.document.project == source
    data = api.execute("layered_import", {"path": "character.ora", "place": True}).data
    scene = api.document.project.scenes[0]
    assert [o.name for o in scene.objects] == ["Body", "Face"]
    assert scene.objects[1].transform.x == 12 and scene.objects[1].extra["opacity"] == 0.5
    assert len(data["mesh_ids"]) == 2 and len(scene.groups) == 2
    assert all(mesh.extra["subdivision"]["mode"] == "full" for mesh in scene.meshes)
    container = next(g for g in scene.groups if g.name == "character.ora")
    assert all(g.parent_id == container.id for g in scene.groups if g.id != container.id)
    assert (
        api.document.read_asset(data["source_asset_id"])
        == (tmp_path / "character.ora").read_bytes()
    )
    assert len(api.document.history.undo_stack) == 1
    api.execute("undo")
    assert api.document.project == source
    approximate = api.execute("layered_import", {"path": "multiply.ora", "allow_unsupported": True})
    assert approximate.data["warnings"]


def test_basic_psd_pixel_layer_import(tmp_path):
    """A generated PSD keeps independent pixel layers and its complete original source."""
    psd_module = pytest.importorskip("psd_tools")
    psd = psd_module.PSDImage.new(mode="RGB", size=(64, 64))
    psd.create_pixel_layer(Image.new("RGBA", (20, 30), "gray"), name="Torso", top=10, left=12)
    psd.create_pixel_layer(Image.new("RGBA", (16, 16), "white"), name="Head", top=3, left=14)
    psd.save(tmp_path / "actor.psd")
    api = RigoraAPI(tmp_path)
    api.execute("project_create")
    result = api.execute("layered_import", {"path": "actor.psd", "place": True}).data
    assert len(result["mesh_ids"]) == 2
    assert [o.name for o in api.document.project.scenes[0].objects] == ["Torso", "Head"]
    assert (
        api.document.read_asset(result["source_asset_id"]) == (tmp_path / "actor.psd").read_bytes()
    )


def test_registered_layered_artwork_can_be_reused_and_shared(tmp_path):
    """Library-only layered imports produce fresh instances and remap source references in packs."""
    make_ora(tmp_path / "source.ora")
    api = RigoraAPI(tmp_path)
    api.execute("project_create")
    registered = api.execute("layered_import", {"path": "source.ora"}).data
    assert not api.document.project.scenes[0].objects
    first = api.execute("layered_place", {"asset_id": registered["source_asset_id"]}).data
    second = api.execute("layered_place", {"asset_id": registered["source_asset_id"]}).data
    assert set(first["mesh_ids"]).isdisjoint(second["mesh_ids"])
    api.execute("project_export", {"path": "layers.rigpack", "format": "rigpack"})
    clone = RigoraAPI(tmp_path)
    clone.execute("project_create")
    clone.execute("asset_pack_install", {"path": "layers.rigpack"})
    entry = next(e for e in clone.library.entries() if e.item.name == "Shared scene")
    clone.execute("template_apply", {"content": entry.key})
    assert len(clone.document.project.scenes[0].meshes) == 4
    assert clone.execute("project_validate").data["valid"]


def test_pcm_audio_and_bad_imports_do_not_discard_sources(tmp_path):
    """Retain PCM timing and refuse malformed audio or unsafe archives atomically."""
    stream = io.BytesIO()
    with wave.open(stream, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b"\0\0" * 2400)
    (tmp_path / "voice.wav").write_bytes(stream.getvalue())
    api = RigoraAPI(tmp_path)
    api.execute("project_create")
    imported = api.execute("audio_import", {"path": "voice.wav"}).data
    assert imported["duration_seconds"] == 0.1
    assert api.document.read_asset(imported["asset_id"]) == stream.getvalue()
    (tmp_path / "broken.wav").write_bytes(b"not wav")
    with pytest.raises(AutomationError):
        api.execute("audio_import", {"path": "broken.wav"})
    with zipfile.ZipFile(tmp_path / "unsafe.ora", "w") as archive:
        archive.writestr("../outside", b"bad")
    with pytest.raises(AutomationError):
        api.execute("layered_import", {"path": "unsafe.ora"})
    assert not (tmp_path.parent / "outside").exists()


def test_static_extended_rasters_and_animated_image_refusal(tmp_path):
    """Additional static raster formats import, while animation is never silently flattened."""
    api = RigoraAPI(tmp_path)
    api.execute("project_create")
    for suffix in ("bmp", "tiff", "webp", "gif"):
        path = tmp_path / f"image.{suffix}"
        Image.new("RGB", (16, 16), "gray").save(path)
        assert api.execute("asset_import", {"path": path.name}).data["asset_id"]
    Image.new("RGBA", (16, 16), "red").save(
        tmp_path / "animated.webp",
        save_all=True,
        append_images=[Image.new("RGBA", (16, 16), "blue")],
        duration=100,
    )
    with pytest.raises(AutomationError, match="frame"):
        api.execute("asset_import", {"path": "animated.webp"})
    Image.new("RGBA", (16, 16), "red").save(
        tmp_path / "animated.png",
        save_all=True,
        append_images=[Image.new("RGBA", (16, 16), "blue")],
        duration=100,
    )
    with pytest.raises(AutomationError, match="frame"):
        api.execute("asset_import", {"path": "animated.png"})


def test_batch_import_partial_failure_folder_placement_and_undo(tmp_path):
    """Mixed imports create sources first, retain groups, and undo the entire drop together."""
    from rigora.application_services.scene_editing import SceneEditingService

    make_ora(tmp_path / "character.ora")
    (tmp_path / "image.png").write_bytes(png_bytes(Image.new("RGBA", (20, 30), "red")))
    (tmp_path / "broken.png").write_bytes(b"invalid")
    api = RigoraAPI(tmp_path)
    api.execute("project_create")
    folder = SceneEditingService(api.document).group(name="Destination")
    baseline = api.document.project
    steps = len(api.document.history.undo_stack)
    result = api.execute(
        "assets_import",
        {
            "paths": ["image.png", "broken.png", "character.ora"],
            "place": True,
            "parent": folder,
            "position": [150, 200],
        },
    ).data
    assert result["imported"] == 2 and result["failed"] == 1
    scene = api.document.project.scenes[0]
    assert len(scene.objects) == 3
    assert any(o.parent_id == folder for o in scene.objects)
    assert any(g.parent_id == folder for g in scene.groups)
    assert len(api.document.history.undo_stack) == steps + 1
    assert api.execute("project_validate").data["valid"]
    api.document.undo()
    assert api.document.project == baseline
    api.document.redo()
    assert len(api.document.project.scenes[0].objects) == 3
