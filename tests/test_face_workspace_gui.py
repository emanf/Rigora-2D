"""Visual face authoring, offline example audio and editable cue audition through the real UI."""

import pytest
from PySide6.QtCore import QPoint, Qt
from test_roots_soft_drag_gui import editor as source_editor

from rigora.application_services.audio import AudioService
from rigora.application_services.character_creation import CharacterCreationService, build_character
from rigora.application_services.documents import DocumentService
from rigora.application_services.facial import FaceService, waveform
from rigora.domain.character_recipe import CharacterRecipe
from rigora.presentation.widgets.facial import FaceDialog
from rigora.resources import asset_path

pytestmark = pytest.mark.gui


@pytest.fixture
def editor(qtbot, tmp_path, monkeypatch):
    """Share the source application's isolated, thumbnail-free offscreen workspace setup."""
    yield from source_editor.__wrapped__(qtbot, tmp_path, monkeypatch)


@pytest.fixture
def dialog(editor, qtbot):
    """Open an isolated source-app dialog without audible playback or microphone access."""
    editor.viewmodel.playback.audio.muted = True
    widget = FaceDialog(editor)
    assert not widget.local_playback.muted and not widget.local_playback.audio.muted
    widget.local_playback.audio.muted = True
    qtbot.addWidget(widget)
    widget.show()
    yield widget
    widget.close()


def test_example_cards_are_visual_exclusive_and_never_create_scene_data(dialog, qtbot):
    doc = dialog.document
    original, steps = doc.project, len(doc.history.undo_stack)
    original_bounds = dialog.portrait.bounds
    qtbot.mouseClick(dialog.expression_cards["Angry"], Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: not dialog.preview_timer.isActive())
    assert "Example" in dialog.portrait.caption
    assert doc.project is original and len(doc.history.undo_stack) == steps
    assert dialog.portrait.bounds == original_bounds
    assert sum(b.isChecked() for b in dialog.expression_cards.values()) == 1
    qtbot.mouseClick(dialog.expression_cards["Angry"], Qt.MouseButton.LeftButton)
    assert dialog.expression_cards["Angry"].isChecked()
    qtbot.mouseClick(dialog.mouth_cards["FV"], Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: not dialog.preview_timer.isActive())
    assert sum(b.isChecked() for b in dialog.mouth_cards.values()) == 1
    assert dialog.mouth_cards["FV"].isChecked()
    descriptor = FaceService(dialog.example_document).face(dialog.example_root)
    assert dialog.portrait.pose.nodes[descriptor["mouths"]["FV"]].visible
    assert not dialog.face_buttons["Key controls"].isEnabled()


def test_default_example_plays_and_scrubs_only_locally(dialog, qtbot, monkeypatch):
    """A fresh project opens with a playable sample, without writing or seeking the scene."""
    from PySide6.QtMultimedia import QAudioBufferOutput

    vm, playback = dialog.host.viewmodel, dialog.local_playback
    original, frame = dialog.document.project, dialog.document.animation.pose.frame
    steps = len(dialog.document.history.undo_stack)
    assert dialog.audio_data == asset_path("audio/english-welcome.wav").read_bytes()
    assert dialog.audio_is_staged and dialog.audio_asset is None
    assert dialog.wave.duration > 5 and dialog.wave.cues
    assert not AudioService(dialog.document).tracks()
    assert not dialog.document.project.assets

    def unexpected(*args, **kwargs):
        raise AssertionError("Face audition accessed the scene transport")

    with monkeypatch.context() as patch:
        for name in ("play_pause", "pause", "stop", "seek"):
            patch.setattr(vm.playback, name, unexpected)
        playback.sync_audio()
        assert playback.audio.player is not None and playback.audio.output.isMuted()
        blocks = []
        monitor = QAudioBufferOutput(playback)
        monitor.audioBufferReceived.connect(
            lambda buffer: blocks.append(bytes(buffer.constData()) if buffer.isValid() else b"")
        )
        playback.audio.player.setAudioBufferOutput(monitor)
        sync_calls = []
        sync_audio = playback.sync_audio

        def explicit_sync():
            sync_calls.append(playback.seconds)
            sync_audio()

        patch.setattr(playback, "sync_audio", explicit_sync)
        qtbot.mouseClick(dialog.play_button, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda: any(any(block) for block in blocks), timeout=7000)
        assert playback.playing and playback.seconds > 0
        assert len(sync_calls) == 1
        assert playback.audio.output.volume() == 1 and not playback.audio.error
        qtbot.mouseClick(dialog.play_button, Qt.MouseButton.LeftButton)
        paused = playback.seconds
        qtbot.wait(50)
        assert not playback.playing and playback.seconds == paused
        dialog.scrub(0.4)
        assert playback.seconds == pytest.approx(dialog.cue_time.value(), abs=0.001)
        assert dialog.document.animation.pose.frame == frame
        qtbot.mouseClick(dialog.stop_button, Qt.MouseButton.LeftButton)
        assert playback.seconds == 0 and not playback.timer.isActive()
        dialog.expression_cards["Happy"].click()
        qtbot.waitUntil(lambda: not dialog.preview_timer.isActive())
        assert vm.animation_editor.preview_pose is None
    assert dialog.document.project is original and len(dialog.document.history.undo_stack) == steps
    dialog.close()
    assert not playback.playing and playback.audio.buffer is not None
    assert not playback.audio.buffer.isOpen()


def test_attach_default_voice_is_explicit_undoable_and_restored(dialog, qtbot):
    """The default voice stays staged until Attach, then saves with ordinary clip timing."""
    original, steps = dialog.document.project, len(dialog.document.history.undo_stack)
    dialog.audio_start.setValue(36)
    dialog.attach_audio()
    assert not dialog.host.viewmodel.animation_editor.error
    assert dialog.audio_asset and not dialog.audio_is_staged
    assert len(dialog.document.history.undo_stack) == steps + 1
    assert AudioService(dialog.document).tracks()[0]["start_frame"] == 36
    again = FaceDialog(dialog.host)
    qtbot.addWidget(again)
    assert again.audio_asset == dialog.audio_asset and again.audio_start.value() == 36
    assert not again.audio_is_staged and not again.local_playback.playing
    again.close()
    dialog.document.undo()
    assert dialog.document.project == original


def test_preview_output_selection_persists_and_missing_outputs_fail_visibly(dialog, qtbot):
    """Preview audio targets a chosen physical device, with no silent fallback on disconnection."""
    assert dialog.audio_outputs.count() >= 2
    dialog.audio_outputs.setCurrentIndex(1)
    selected = dialog.audio_outputs.currentData()
    assert dialog.local_playback.device_id == selected
    again = FaceDialog(dialog.host)
    qtbot.addWidget(again)
    assert again.local_playback.device_id == selected
    assert not again.local_playback.output_device().isNull()
    again.close()
    dialog.local_playback.set_output_device("disconnected-device")
    dialog.local_playback.play_pause()
    assert not dialog.local_playback.playing and not dialog.local_playback.timer.isActive()
    assert "output" in dialog.local_playback.audio.error.lower()


def test_gui_builtin_analysis_needs_no_executable_configuration(dialog, qtbot):
    """The real worker uses shipped speech models directly from the default English audition."""
    before = dialog.document.project
    dialog.analyze()
    qtbot.waitUntil(lambda: dialog.analysis_job is None, timeout=15000)
    assert "Speech analyzed" in dialog.status.text()
    assert len({shape for _, shape in dialog.wave.cues}) >= 5
    assert dialog.document.project is before


def test_real_face_cards_preview_then_key_and_cleanup(dialog, qtbot, tmp_path):
    dialog.create_face()
    before = dialog.document.project
    qtbot.mouseClick(dialog.expression_cards["Happy"], Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: not dialog.preview_timer.isActive())
    descriptor = FaceService(dialog.document).face(dialog.faces.currentData())
    assert dialog.document.project is before
    assert dialog.portrait.pose.nodes[descriptor["mouths"]["E"]].visible
    assert dialog.blink.isEnabled()
    dialog.key_controls()
    assert not dialog.host.viewmodel.animation_editor.error
    assert dialog.document.project is not before
    assert dialog.grab().save(str(tmp_path / "face.png"))
    dialog.close()
    assert dialog.host.viewmodel.animation_editor.preview_pose is None


def test_english_audio_cues_audition_and_one_step_keyed_archive(dialog, qtbot, tmp_path):
    dialog.create_face()
    dialog.load_example()
    assert not dialog.host.viewmodel.animation_editor.error
    duration, peaks = waveform(dialog.audio_data)
    assert 5 < duration < 15 and max(peaks) > 0.1
    assert dialog.wave.cues[-1][0] == pytest.approx(duration, abs=0.001)
    assert len({s for _, s in dialog.wave.cues}) >= 5
    count = len(dialog.document.project.assets)
    assert dialog.audio_asset is None
    dialog.load_example()
    assert dialog.audio_asset is None and len(dialog.document.project.assets) == count
    dialog.audio_start.setValue(12)
    before = dialog.document.project
    time, shape = next((t, s) for t, s in dialog.wave.cues if s != "Rest")
    dialog.scrub(time)
    descriptor = FaceService(dialog.document).face(dialog.faces.currentData())
    assert dialog.portrait.pose.nodes[descriptor["mouths"][shape]].visible
    assert dialog.document.project is before
    dialog.transport()
    assert dialog.portrait.pose.nodes[descriptor["mouths"][shape]].visible
    dialog.preview_cues.setChecked(False)
    assert dialog.portrait.pose is dialog.document.animation.pose
    dialog.preview_cues.setChecked(True)
    assert dialog.portrait.pose.nodes[descriptor["mouths"][shape]].visible
    dialog.tabs.setCurrentIndex(1)
    qtbot.wait(20)
    assert dialog.grab().save(str(tmp_path / "audio.png"))
    dialog.tabs.setCurrentIndex(2)
    qtbot.wait(20)
    assert dialog.grab().save(str(tmp_path / "cues.png"))
    dialog.resize(870, 650)
    qtbot.wait(20)
    assert dialog.width() == 870 and dialog.portrait.width() >= 300
    play_top = dialog.play_button.mapTo(dialog.portrait.parentWidget(), QPoint()).y()
    assert play_top > dialog.portrait.geometry().bottom()
    assert dialog.grab().save(str(tmp_path / "compact.png"))
    steps = len(dialog.document.history.undo_stack)
    dialog.key_cues()
    assert not dialog.host.viewmodel.animation_editor.error
    assert len(dialog.document.history.undo_stack) == steps + 1
    asset = dialog.audio_asset
    assert asset is not None
    position = AudioService(dialog.document).position(24)
    assert position.asset_id == asset and position.seconds == pytest.approx(0.5)
    archive = tmp_path / "english.rigora"
    dialog.document.save(archive)
    reopened = DocumentService()
    reopened.open(archive)
    assert reopened.read_asset(asset) == asset_path("audio/english-welcome.wav").read_bytes()
    assert AudioService(reopened).tracks()[0]["start_frame"] == 12
    dialog.document.undo()
    assert dialog.document.project == before
    assert dialog.grab().save(str(tmp_path / "english.png"))


def test_visual_cue_editing_preserves_decoder_precision_and_invalid_text(dialog):
    before = dialog.document.project
    dialog.cues.setPlainText("0, Rest\n0.12345, AI\n0.5, Rest")
    dialog.cue_time.setValue(0.123)
    dialog.cue_shape.setCurrentIndex(dialog.cue_shape.findData("FV"))
    dialog.set_cue()
    assert (0.12345, "FV") in dialog.wave.cues
    dialog.remove_cue()
    assert len(dialog.wave.cues) == 2
    dialog.cues.setPlainText("invalid")
    dialog.set_cue()
    assert dialog.cues.toPlainText() == "invalid" and "Check cue text" in dialog.status.text()
    assert dialog.document.project is before


def test_creator_portrait_uses_real_head_and_bound_mouth(editor, qtbot, tmp_path):
    root = CharacterCreationService(editor.viewmodel.documents).create(
        build_character(CharacterRecipe(motions=()))
    )
    editor.viewmodel.changed.emit()
    widget = FaceDialog(editor)
    qtbot.addWidget(widget)
    widget.show()
    widget.faces.setCurrentIndex(widget.faces.findData(root))
    assert not widget.portrait.backing and widget.portrait.root == root
    assert not widget.expression_cards["Angry"].isEnabled()
    before = widget.document.project
    qtbot.mouseClick(widget.mouth_cards["O"], Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: not widget.preview_timer.isActive())
    descriptor = FaceService(widget.document).face(root)
    assert widget.portrait.pose.nodes[descriptor["mouths"]["O"]].visible
    assert widget.document.project is before and not widget.portrait.bounds.isEmpty()
    assert widget.grab().save(str(tmp_path / "creator.png"))
    widget.close()


def test_analysis_shows_progress_and_keeps_results_uncommitted(dialog, qtbot, monkeypatch):
    dialog.load_example()
    before = dialog.document.project
    monkeypatch.setattr(FaceService, "speech_cues", lambda *a, **k: ((0, "Rest"), (0.2, "AI")))
    dialog.analyze()
    assert dialog.progress.isVisible() and not dialog.analyze_button.isEnabled()
    qtbot.waitUntil(lambda: dialog.analysis_job is None)
    assert not dialog.progress.isVisible() and dialog.analyze_button.isEnabled()
    assert dialog.wave.cues == ((0, "Rest"), (0.2, "AI"))
    assert dialog.document.project is before
