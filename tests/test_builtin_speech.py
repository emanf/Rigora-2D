"""Bundled offline lip-sync, source-format conversion and executable-free API analysis."""

import io
import math
import struct
import subprocess
import threading
import wave

import pytest

from rigora.api import RigoraAPI
from rigora.application_services.facial import FaceService
from rigora.domain.project import ProjectError
from rigora.infrastructure.speech import mono_pcm_chunks
from rigora.resources import asset_path


@pytest.mark.parametrize(
    "rate,width,channels", [(8000, 1, 1), (44100, 2, 2), (48000, 3, 2), (192000, 4, 1)]
)
def test_native_wav_formats_downmix_and_resample_in_bounded_blocks(rate, width, channels):
    frames = math.ceil(rate * 0.55)
    raw = bytearray()
    for i in range(frames):
        amplitude = round(math.sin(2 * math.pi * 220 * i / rate) * (2 ** (width * 8 - 2) - 1))
        value = amplitude + 128 if width == 1 else amplitude
        raw.extend(value.to_bytes(width, "little", signed=width != 1) * channels)
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setparams((channels, width, rate, frames, "NONE", "not compressed"))
        target.writeframes(raw)
    blocks = tuple(mono_pcm_chunks(output.getvalue()))
    assert len(blocks) == 3 and max(map(len, blocks)) <= 8000
    samples = struct.unpack("<" + "h" * (sum(map(len, blocks)) // 2), b"".join(blocks))
    assert len(samples) == math.ceil(frames * 16000 / rate)
    assert max(samples) == pytest.approx(16384, abs=300)
    assert min(samples) == pytest.approx(-16384, abs=300)
    assert abs(samples[4000] - samples[3999]) < 1600


def test_builtin_english_speech_uses_installed_model_without_processes(monkeypatch, tmp_path):
    """Real English phoneme inference and the public API need no executable or network setup."""

    def external(*args, **kwargs):
        raise AssertionError("Built-in speech must not start an external executable")

    monkeypatch.setattr(subprocess, "Popen", external)
    data = asset_path("audio/english-welcome.wav").read_bytes()
    cues = FaceService.speech_cues(data)
    with wave.open(io.BytesIO(data)) as source:
        duration = source.getnframes() / source.getframerate()
    assert cues[-1] == (duration, "Rest")
    assert all(0 <= t <= duration for t, _ in cues)
    assert len({s for _, s in cues}) >= 5
    (tmp_path / "voice.wav").write_bytes(data)
    api = RigoraAPI(tmp_path)
    api.execute("project_create", {})
    asset = api.execute("audio_import", {"path": "voice.wav"}).data["asset_id"]
    before = api.document.project
    result = api.execute("speech_analyze", {"asset_id": asset})
    assert result.data["cues"] and api.document.project is before


def test_builtin_analysis_cancellation_precedes_native_model_loading():
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(ProjectError, match="cancelled"):
        FaceService.speech_cues(
            asset_path("audio/english-welcome.wav").read_bytes(), cancel=cancelled
        )
