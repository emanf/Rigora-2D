"""Offline streaming phonemes, nonmutating previews and atomic editable speech takes."""

import os
from pathlib import Path

import pytest

from rigora.application_services.documents import DocumentService
from rigora.application_services.facial import FaceService
from rigora.application_services.speech_performance import SpeechTake
from rigora.domain.project import ProjectError
from rigora.infrastructure.live_speech import LivePhonemes, SpeechSample


def test_speech_take_preview_and_voice_keys_undo_together():
    """Preview is transient, while kept voice and editable step keys share one undo step."""
    from rigora.application_services.recording import PcmRecording

    doc = DocumentService()
    doc.new()
    face = FaceService(doc)
    target = face.create()
    face.lip_sync(target, ((2, "FV"),))
    doc.animation.seek(6)
    take = SpeechTake(doc, target, gestures=True)
    before, steps = doc.project, len(doc.history.undo_stack)
    sample = SpeechSample(0.25, "AI", ((0, "Rest"), (0.1, "AI"), (0.5, "Rest")), 0.1)
    preview = take.preview(sample)
    mouths = face.face(target)["mouths"]
    assert preview.nodes[mouths["AI"]].visible and doc.project is before
    assert preview.nodes[target].local.rotation != doc.animation.pose.nodes[target].local.rotation
    pcm = PcmRecording()
    pcm.append(bytes(16000))
    asset = take.keep(SpeechSample(0.5, "Rest", sample.cues), pcm.wav())
    assert len(doc.history.undo_stack) == steps + 1
    assert doc.read_asset(asset).startswith(b"RIFF")
    assert doc.animation.evaluate(9).nodes[mouths["AI"]].visible
    assert doc.animation.evaluate(18).nodes[target].local.rotation == 0
    assert doc.animation.evaluate(48).nodes[mouths["FV"]].visible
    doc.undo()
    assert doc.project == before
    doc.redo()
    assert doc.animation.evaluate(9).nodes[mouths["AI"]].visible
    with pytest.raises(ProjectError, match="context changed"):
        take.keep(sample, pcm.wav())


def test_live_native_decoder_silence_chunk_boundaries_reset_and_optional_voice():
    """The actual optional decoder works offline across ten-second utterance resets."""
    pytest.importorskip("pocketsphinx")
    decoder = LivePhonemes(16000)
    for _ in range(110):
        sample = decoder.feed(bytes(3201))
    assert sample.seconds == pytest.approx(110 * 3201 / 32000)
    assert sample.mouth == "Rest"
    final = decoder.close()
    assert final.cues[-1] == (sample.seconds, "Rest")
    assert decoder.close() == final
    with pytest.raises(ProjectError, match="open speech decoder"):
        decoder.feed(b"\0\0")
    source = Path(os.environ.get("RIGORA_SPEECH_SAMPLE", "build/live-speech-reference.raw"))
    if source.is_file():
        raw = source.read_bytes()
        decoder = LivePhonemes(16000)
        preview = set()
        for index in range(0, len(raw), 1600):
            preview.add(decoder.feed(raw[index : index + 1600]).mouth)
        final = decoder.close()
        assert len(preview - {"Rest"}) >= 3
        assert len({shape for _, shape in final.cues} - {"Rest"}) >= 3


@pytest.mark.gui
def test_speech_worker_drains_stops_and_releases_without_opening_a_device(qtbot):
    """Real background decoding delivers final cues, can restart, and never starts hardware."""
    pytest.importorskip("pocketsphinx")
    from PySide6.QtCore import QObject

    from rigora.presentation.viewmodels.live_speech import LiveSpeech

    parent = QObject()
    worker = LiveSpeech(parent)
    results, errors = [], []
    worker.finished.connect(results.append)
    worker.failed.connect(errors.append)
    worker.start(16000)
    for _ in range(10):
        worker.feed(bytes(3200), 16000)
    worker.stop(keep=True)
    qtbot.waitUntil(lambda: worker.job is None, timeout=5000)
    assert not errors and len(results) == 1 and results[0].seconds == 1
    worker.start(16000)
    worker.stop()
    qtbot.waitUntil(lambda: worker.job is None, timeout=5000)
    assert len(results) == 1 and not worker.timer.isActive()
    worker.start(123)
    qtbot.waitUntil(lambda: worker.job is None, timeout=5000)
    assert errors and not worker.accepting


@pytest.mark.gui
def test_face_dialog_live_keep_creates_one_editable_audio_take(qtbot, tmp_path, monkeypatch):
    """Drive the actual dialog through Record/Keep using PCM injection instead of hardware."""
    pytest.importorskip("pocketsphinx")
    from rigora.app.application import ApplicationInfo
    from rigora.application_services.recording import PcmRecording
    from rigora.infrastructure.preferences import PreferencesStore
    from rigora.presentation.viewmodels.main_window import MainWindowViewModel
    from rigora.presentation.viewmodels.microphone import MicrophoneCapture
    from rigora.presentation.views.main_window import MainWindow
    from rigora.presentation.widgets.facial import FaceDialog

    def start(capture, device_id=""):
        capture.recording, capture.active = PcmRecording(), True

    monkeypatch.setattr(MicrophoneCapture, "start", start)
    vm = MainWindowViewModel(ApplicationInfo(), preferences=PreferencesStore(tmp_path / "ui.json"))
    window = MainWindow(vm)
    window.confirm_discard = lambda: True
    qtbot.addWidget(window)
    vm.new_project()
    dialog = FaceDialog(window)
    qtbot.addWidget(dialog)
    dialog.create_face()
    dialog.live_speech.setChecked(True)
    dialog.speech_gestures.setChecked(True)
    before, steps = vm.documents.project, len(vm.documents.history.undo_stack)
    dialog.start_recording()
    for _ in range(10):
        data = bytes(3200)
        dialog.capture.recording.append(data)
        dialog.capture.samples.emit(data, 16000)
    qtbot.waitUntil(lambda: dialog.speech_take.last >= 0, timeout=5000)
    assert vm.documents.project is before
    dialog.keep_recording()
    qtbot.waitUntil(lambda: dialog.speech_take is None, timeout=5000)
    assert len(vm.documents.history.undo_stack) == steps + 1
    assert dialog.audio_asset and not dialog.capture.active and dialog.speech.job is None
    assert vm.documents.animation.evaluator.clip.extra["audio"]["asset_id"] == dialog.audio_asset
    vm.documents.undo()
    assert vm.documents.project == before
    dialog.close()
