"""Local PCM capture is bounded, explicit, source-preserving and independent of physical devices."""

import io
import wave

import pytest

from rigora.application_services.recording import PcmRecording
from rigora.domain.project import ProjectError


def test_pcm_fragments_pause_bounds_and_portable_wave():
    """Arbitrary capture chunks retain exact samples and overflow leaves a valid recording."""
    capture = PcmRecording(16000)
    capture.limit = 16
    capture.append(b"\x01")
    capture.append(b"\x02\x03\x04")
    capture.paused = True
    capture.append(b"\x05\x06")
    capture.paused = False
    before = bytes(capture.data)
    with pytest.raises(ProjectError, match="limit"):
        capture.append(b"x" * 20)
    assert bytes(capture.data) == before and capture.seconds == 2 / 16000
    with wave.open(io.BytesIO(capture.wav()), "rb") as audio:
        assert audio.getframerate() == 16000 and audio.getnchannels() == 1
        assert audio.readframes(2) == before
    assert capture.wav() == capture.wav()
    with pytest.raises(ProjectError):
        PcmRecording(16000, True)
    with pytest.raises(ProjectError):
        PcmRecording().wav()


@pytest.mark.gui
def test_capture_device_start_stop_retention_and_discard(qtbot, fake_microphone):
    """Nothing opens until Start; finish releases input and keeps retryable samples."""
    from PySide6.QtCore import QObject

    owner = QObject()
    capture = fake_microphone.MicrophoneCapture(owner)
    assert capture.source is None and capture.recording is None
    with pytest.raises(ProjectError, match="unavailable"):
        capture.start("missing-device")
    assert capture.source is None
    capture.start()
    capture.read()
    assert capture.active and capture.recording.seconds == 0.1
    data = capture.finish()
    assert not capture.active and capture.source is None
    assert data == capture.recording.wav()
    with pytest.raises(ProjectError, match="Keep or discard"):
        capture.start()
    capture.discard()
    assert capture.recording is None


@pytest.mark.gui
def test_recording_ui_imports_one_undoable_embedded_source(qtbot, tmp_path, fake_microphone):
    """The visible recording controls retain WAV data through the canonical asset importer."""
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
    dialog = FaceDialog(window)
    qtbot.addWidget(dialog)
    before = vm.documents.project
    steps = len(vm.documents.history.undo_stack)
    dialog.start_recording()
    dialog.capture.read()
    assert not dialog.record_button.isEnabled() and dialog.keep_recording_button.isEnabled()
    dialog.keep_recording()
    assert not dialog.capture.active and dialog.capture.recording is None
    assert dialog.audio_asset and dialog.wave.duration == 0.1
    assert vm.documents.project.assets[-1].kind == "audio"
    assert len(vm.documents.history.undo_stack) == steps + 1
    vm.documents.undo()
    assert vm.documents.project == before
    dialog.close()
