"""Independent portable audio timing and actual deterministic PCM mixing."""

import io
import struct
import wave

import pytest

from rigora.application_services.asset_pipeline import AssetPipeline
from rigora.application_services.audio import AudioService
from rigora.application_services.documents import DocumentService
from rigora.domain.project import ProjectError


def constant_wav():
    """Return a quarter-amplitude mono source for exact mix/envelope comparisons."""
    output = io.BytesIO()
    with wave.open(output, "wb") as source:
        source.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        source.writeframes(struct.pack("<8000h", *([8192] * 8000)))
    return output.getvalue()


def test_tracks_trim_fade_solo_mix_undo_and_roundtrip(tmp_path):
    """One quarter-amplitude source can be placed twice with independent timing and gain."""
    doc = DocumentService()
    doc.new()
    asset = AssetPipeline(doc).audio_bytes("tone.wav", constant_wav())["asset_id"]
    service = AudioService(doc)
    a = service.put_track(
        asset, name="Voice", trim_start=0.2, trim_end=0.8, gain=0.5, fade_in=0.2, fade_out=0.2
    )
    b = service.put_track(asset, name="Music", gain=0.25)
    frame = 0.1 * doc.scene.settings.fps
    positions = service.positions(frame)
    assert positions[0].seconds == pytest.approx(0.3)
    assert positions[0].gain == pytest.approx(0.25)
    service.mix(tmp_path / "mixed.wav", start=0, seconds=0.5)
    with wave.open(str(tmp_path / "mixed.wav")) as mixed:
        mixed.setpos(4800)
        left, right = struct.unpack("<hh", mixed.readframes(1))
        assert left == right == pytest.approx(4096, abs=1)
    revision = doc.project
    service.put_track(asset, identity=b, solo=True)
    assert service.positions(frame)[0].muted
    doc.undo()
    assert doc.project == revision
    with pytest.raises(ProjectError):
        service.put_track(asset, trim_start=0.8, trim_end=0.2)
    service.remove_track(a)
    assert len(service.tracks()) == 1
    doc.undo()
    doc.save(tmp_path / "audio.rigora")
    doc.open(doc.path)
    assert [t["id"] for t in service.tracks()] == [a, b]


def test_attaching_clip_voice_to_a_mix_updates_one_stable_track():
    """Repeated face-editor attachment replaces its voice without duplicating or removing music."""
    doc = DocumentService()
    doc.new()
    asset = AssetPipeline(doc).audio_bytes("voice.wav", constant_wav())["asset_id"]
    service = AudioService(doc)
    music = service.put_track(asset, name="Music", gain=0.25)
    original, steps = doc.project, len(doc.history.undo_stack)
    service.attach(asset, start=12, gain=0.5)
    assert len(doc.history.undo_stack) == steps + 1
    assert [t["id"] for t in service.tracks()] == [music, "legacy"]
    service.attach(asset, start=24, gain=0.7)
    tracks = service.tracks()
    assert len(tracks) == 2 and tracks[0]["gain"] == 0.25
    assert tracks[1]["start_frame"] == 24 and tracks[1]["gain"] == 0.7
    doc.undo()
    doc.undo()
    assert doc.project == original
