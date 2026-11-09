"""End-to-end clip audio, creator visemes, Adobe artboards and native engine packages."""

import io
import json
import shutil
import subprocess
import wave
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from rigora.api import RigoraAPI
from rigora.application_services.asset_pipeline import AssetPipeline
from rigora.application_services.audio import AudioService
from rigora.application_services.character_creation import CharacterCreationService, build_character
from rigora.application_services.documents import DocumentService
from rigora.application_services.facial import FaceService
from rigora.application_services.meshes import MeshService
from rigora.application_services.output import OutputService, OutputSettings
from rigora.domain.character_recipe import CHARACTER_PRESETS, MOUTH_POSES, character_preset
from rigora.domain.project import ProjectError, SceneSettings
from rigora.infrastructure.media_import import png_bytes, read_illustrator
from rigora.infrastructure.speech import read_speech_cues


def voice_bytes():
    """Return one second of bounded PCM with audible pulses for timing tests."""
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        audio.writeframes((b"\x00\x20" * 20 + b"\x00\xe0" * 20) * 200)
    return output.getvalue()


def test_clip_audio_timing_undo_and_save_reopen(tmp_path):
    """Public API association survives archive moves and does not depend on the original WAV."""
    (tmp_path / "voice.wav").write_bytes(voice_bytes())
    api = RigoraAPI(tmp_path)
    api.execute("project_create", {"fps": 24})
    imported = api.execute("audio_import", {"path": "voice.wav"}).data["asset_id"]
    before = api.document.project
    api.execute("audio_attach", {"asset_id": imported, "start": 48, "gain": 0.4, "muted": True})
    assert AudioService(api.document).position(60).seconds == 0.5
    api.document.undo()
    assert api.document.project == before
    api.document.redo()
    api.document.save(tmp_path / "talk.rigora")
    (tmp_path / "voice.wav").unlink()
    reopened = DocumentService()
    reopened.open(tmp_path / "talk.rigora")
    position = AudioService(reopened).position(60)
    assert position.seconds == 0.5 and position.gain == 0.4 and position.muted
    assert reopened.read_asset(position.asset_id) == voice_bytes()
    saved = reopened.project
    with pytest.raises(ProjectError):
        AudioService(reopened).attach(imported, gain=2)
    assert reopened.project is saved
    AudioService(reopened).detach()
    assert AudioService(reopened).position(60) is None


@pytest.mark.parametrize("identity", CHARACTER_PRESETS)
def test_original_creator_cast_mouths_are_usable_without_overlay_face(identity, tmp_path):
    """Creator mouth objects remap with the character and retain exactly one visible viseme."""
    recipe = replace(character_preset(identity), motions=("Stand",))
    doc = DocumentService()
    doc.new()
    root = CharacterCreationService(doc).create(build_character(recipe))
    face = FaceService(doc)
    descriptor = face.face(root)
    assert set(descriptor["mouths"]) == set(MOUTH_POSES)
    face.lip_sync(root, ((0, "Rest"), (0.25, "AI"), (0.5, "FV"), (0.75, "MBP")))
    for frame, name in ((0, "Rest"), (6, "AI"), (12, "FV"), (18, "MBP")):
        pose = doc.animation.evaluate(frame)
        assert pose.nodes[descriptor["mouths"][name]].visible
        assert sum(pose.nodes[key].visible for key in descriptor["mouths"].values()) == 1
    doc.save(tmp_path / "speaker.rigora")
    other = DocumentService()
    other.open(tmp_path / "speaker.rigora")
    assert other.animation.evaluate(12) == doc.animation.evaluate(12)


def test_speech_cue_validation_maps_shapes_and_closes_silence():
    """Ordered intervals preserve gaps as Rest, map optional shapes and reject malformed output."""
    data = {
        "mouthCues": [
            {"start": 0.1, "end": 0.3, "value": "A"},
            {"start": 0.4, "end": 0.7, "value": "G"},
            {"start": 0.7, "end": 0.9, "value": "D"},
        ]
    }
    cues = read_speech_cues(json.dumps(data).encode(), 1)
    assert cues == (
        (0, "Rest"),
        (0.1, "MBP"),
        (0.3, "Rest"),
        (0.4, "FV"),
        (0.7, "AI"),
        (0.9, "Rest"),
        (1, "Rest"),
    )
    data["mouthCues"][1]["start"] = 0.2
    with pytest.raises(ProjectError, match="invalid"):
        read_speech_cues(json.dumps(data).encode(), 1)
    with pytest.raises(ProjectError):
        read_speech_cues(b'{"mouthCues": null}', 1)


def test_incomplete_creator_face_requires_authored_parts_without_mutation():
    """Missing facial descriptors cannot silently synthesize replacements for supplied artwork."""
    doc = DocumentService()
    doc.new()
    root_id = CharacterCreationService(doc).create(
        build_character(replace(character_preset("Ribbon"), motions=("Stand",)))
    )
    MeshService(doc).commit(
        "Fixture without facial descriptor",
        groups=tuple(
            replace(g, extra={k: v for k, v in g.extra.items() if k != "face"})
            if g.id == root_id
            else g
            for g in doc.scene.groups
        ),
    )
    before = doc.project
    steps = len(doc.history.undo_stack)
    with pytest.raises(ProjectError, match="facial rig"):
        FaceService(doc).enable_character(root_id)
    assert doc.project is before and len(doc.history.undo_stack) == steps


def test_face_keys_cannot_be_authored_into_another_objects_animation_scope():
    """Wrong-object editing fails visibly instead of creating facial keys that never evaluate."""
    doc = DocumentService()
    doc.new()
    service = FaceService(doc)
    face = service.create()
    before = doc.project
    doc.set_animation_context(None, scope=frozenset())
    with pytest.raises(ProjectError, match="Object Editor"):
        service.lip_sync(face, ((0, "AI"),))
    assert doc.project == before


def pdf_artboards():
    """Build an original two-artboard PDF-compatible AI fixture without external artwork."""
    pdfium = pytest.importorskip("pypdfium2")
    document = pdfium.PdfDocument.new()
    for width in (40, 60):
        document.new_page(width, 50)
    output = io.BytesIO()
    document.save(output)
    document.close()
    return output.getvalue()


def test_pdf_compatible_illustrator_preserves_original_and_explicit_artboards(tmp_path):
    """AI import requires flattening acknowledgement and retains independent reusable artboards."""
    data = pdf_artboards()
    with pytest.raises(ProjectError, match="approximation"):
        read_illustrator(data)
    with pytest.raises(ProjectError, match="PDF Compatible"):
        read_illustrator(b"%!PS-Adobe", allow_unsupported=True)
    (tmp_path / "actor.ai").write_bytes(data)
    doc = DocumentService()
    doc.new()
    baseline = doc.project
    result = AssetPipeline(doc).layered(tmp_path / "actor.ai", allow_unsupported=True, place=True)
    assert len(result["object_ids"]) == 2 and result["warnings"]
    assert doc.read_asset(result["source_asset_id"]) == data
    assert [obj.visible for obj in doc.project.scenes[0].objects] == [True, False]
    doc.undo()
    assert doc.project == baseline
    doc.redo()
    doc.save(tmp_path / "artboards.rigora")
    other = DocumentService()
    other.open(tmp_path / "artboards.rigora")
    assert len(other.project.scenes[0].objects) == 2


@pytest.mark.parametrize("engine", ("godot", "unity", "unreal"))
def test_native_game_packages_preserve_order_timing_alpha_and_importer(engine, tmp_path):
    """Baked packages carry actual rendered pixels and an engine-specific import workflow."""
    api = RigoraAPI(tmp_path)
    api.execute("project_create", {"width": 32, "height": 32})
    for index, color in enumerate(("red", "blue")):
        (tmp_path / f"{index}.png").write_bytes(png_bytes(Image.new("RGBA", (10, 10), color)))
    api.execute("sequence_import", {"paths": ["0.png", "1.png"], "fps": 12, "place": True})
    before = api.document.project
    result = api.execute(
        "frame_render",
        {
            "path": "walk.zip",
            "format": engine,
            "frames": [0, 2],
            "width": 32,
            "height": 32,
            "fps": 12,
            "loop": False,
            "columns": 2,
        },
    ).data
    assert result["paths"] == ["walk.zip"] and api.document.project is before
    with zipfile.ZipFile(tmp_path / "walk.zip") as archive:
        manifest = json.loads(archive.read("animation.json"))
        assert manifest["fps"] == 12 and not manifest["loop"]
        assert manifest["duration_seconds"] == pytest.approx(1 / 6)
        for index, color in enumerate(((255, 0, 0, 255), (0, 0, 255, 255))):
            image = Image.open(io.BytesIO(archive.read(manifest["frames"][index]["path"])))
            assert image.getpixel((0, 0))[3] == 0 and image.getpixel((16, 16)) == color
        if engine == "godot":
            scene = archive.read("animation.tscn").decode()
            assert "Rect2(32, 0, 32, 32)" in scene and '"loop": false' in scene
        elif engine == "unity":
            assert "Editor/RigoraSpriteImporter.cs" in archive.namelist()
        else:
            compile(archive.read("import_rigora.py"), "import_rigora.py", "exec")
    with pytest.raises(ProjectError):
        OutputService(lambda p: Path(p)).export(
            api.document, str(tmp_path / "bad.png"), OutputSettings(format=engine)
        )


@pytest.mark.gui
def test_audio_backend_follows_transport_seek_pause_loop_and_tab_switch(qtbot):
    """The real buffered backend receives exact source time and pauses on document switches."""
    from PySide6.QtCore import QObject

    from rigora.presentation.viewmodels.playback import PlaybackViewModel

    doc = DocumentService()
    doc.new(settings=SceneSettings(fps=24, end_frame=72))
    asset = doc.register_asset_bytes(
        "voice.wav",
        voice_bytes(),
        kind="audio",
        media_type="audio/wav",
        metadata={"duration_seconds": 1},
    )
    AudioService(doc).attach(asset.id, start=24, gain=0.4)
    owner = QObject()
    transport = PlaybackViewModel(owner)
    transport.bind(doc)
    assert transport.audio.source == (id(doc), asset.id)
    transport.seek(36)
    qtbot.waitUntil(lambda: transport.audio.player.position() == 500, timeout=3000)
    transport.play_pause()
    assert transport.timer.isActive()
    transport.pause()
    assert not transport.timer.isActive()
    assert transport.audio.output.volume() == pytest.approx(0.4)
    other = DocumentService()
    other.new()
    transport.bind(other)
    assert transport.audio.source is None


def test_video_mux_includes_delayed_clip_audio_and_supports_silent_export(tmp_path):
    """The real encoder muxes clip audio at its scene offset and honors the disable switch."""
    encoder, probe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not encoder or not probe:
        pytest.skip("Local FFmpeg and FFprobe are required for mux verification.")
    api = RigoraAPI(tmp_path, encoder=Path(encoder))
    api.execute("project_create", {"width": 32, "height": 32, "fps": 24})
    (tmp_path / "voice.wav").write_bytes(voice_bytes())
    asset = api.execute("audio_import", {"path": "voice.wav"}).data["asset_id"]
    api.execute("audio_attach", {"asset_id": asset, "start": 6, "gain": 0.5})
    for enabled in (True, False):
        name = "voice.mp4" if enabled else "silent.mp4"
        api.execute(
            "frame_render",
            {
                "path": name,
                "frames": list(range(24)),
                "width": 32,
                "height": 32,
                "include_audio": enabled,
            },
        )
        result = subprocess.run(
            [probe, "-v", "error", "-show_streams", "-of", "json", str(tmp_path / name)],
            capture_output=True,
            check=True,
        )
        streams = json.loads(result.stdout)["streams"]
        assert any(stream["codec_type"] == "audio" for stream in streams) == enabled
    decoded = subprocess.run(
        [
            encoder,
            "-v",
            "error",
            "-i",
            str(tmp_path / "voice.mp4"),
            "-f",
            "s16le",
            "-ac",
            "1",
            "-ar",
            "8000",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    samples = memoryview(decoded).cast("h")
    assert max(map(abs, samples[:1500])) < 50
    assert max(map(abs, samples[2500:4500])) > 1000


@pytest.mark.gui
def test_face_audio_ui_reuses_source_keys_once_and_restores_saved_clip(
    qtbot, tmp_path, monkeypatch
):
    """The visible audio workflow uses embedded sources and commits cues/timing in one undo item."""
    from rigora.app.application import ApplicationInfo
    from rigora.infrastructure.preferences import PreferencesStore
    from rigora.presentation.viewmodels.main_window import MainWindowViewModel
    from rigora.presentation.views.main_window import MainWindow
    from rigora.presentation.widgets.facial import FaceDialog

    vm = MainWindowViewModel(ApplicationInfo(), preferences=PreferencesStore(tmp_path / "ui.json"))
    window = MainWindow(vm)
    window.confirm_discard = lambda: True
    qtbot.addWidget(window)
    vm.new_project()
    vm.content.pool.waitForDone(3000)
    (tmp_path / "voice.wav").write_bytes(voice_bytes())
    asset = AssetPipeline(vm.documents).audio(tmp_path / "voice.wav")["asset_id"]
    dialog = FaceDialog(window)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.create_face()
    dialog.audio_sources.setCurrentIndex(dialog.audio_sources.findData(asset))
    assert dialog.wave.duration == 1 and dialog.audio_data == voice_bytes()
    dialog.audio_start.setValue(6)
    dialog.volume.setValue(0.5)
    dialog.cues.setPlainText("0, Rest\n0.25, AH\n0.5, FV\n1, Rest")
    steps = len(vm.documents.history.undo_stack)
    dialog.key_cues()
    assert not vm.animation_editor.error
    assert len(vm.documents.history.undo_stack) == steps + 1
    assert AudioService(vm.documents).position(18).seconds == 0.5
    assert AudioService(vm.documents).position(18).gain == 0.5
    vm.documents.save(tmp_path / "speaker.rigora")
    again = FaceDialog(window)
    qtbot.addWidget(again)
    assert again.audio_asset == asset and again.audio_start.value() == 6
    assert again.volume.value() == 0.5
    before = vm.documents.project
    monkeypatch.setattr(
        FaceService,
        "speech_cues",
        staticmethod(lambda *a, **k: ((0, "MBP"), (0.5, "O"), (1, "Rest"))),
    )
    again.analyze()
    qtbot.waitUntil(lambda: again.analysis_job is None, timeout=3000)
    assert "MBP" in again.cues.toPlainText() and vm.documents.project is before
    assert again.grab().save(str(tmp_path / "face-audio-dialog.png"))
    from PySide6.QtWidgets import QScrollArea

    scroll = again.findChild(QScrollArea)
    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
    assert again.grab().save(str(tmp_path / "speech-analysis-dialog.png"))
    dialog.close()
    again.close()
