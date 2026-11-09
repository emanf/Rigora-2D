"""Editable project-local replays retain synchronized rate/loop timing and atomic voice takes."""

import io
import struct
import wave
from dataclasses import replace

import pytest

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.asset_pipeline import AssetPipeline
from rigora.application_services.audio import AudioService
from rigora.application_services.characters import CharacterService
from rigora.application_services.documents import DocumentService
from rigora.application_services.puppet import PuppetService, PuppetSession
from rigora.domain.project import ProjectError
from rigora.engine.audio_mix import track_state, write_mix


def voice_bytes():
    """Generate bounded PCM instead of loading copyrighted recordings or opening hardware."""
    output = io.BytesIO()
    with wave.open(output, "wb") as source:
        source.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        source.writeframes(struct.pack("<h", 8192) * 4000)
    return output.getvalue()


def test_replay_uses_editable_action_curves_and_synchronized_looped_rate_audio():
    """Capture a real action and record two cycles with ordinary motion/audio timeline data."""
    doc = DocumentService()
    doc.new()
    root = CharacterService(doc).create_object(name="Actor")
    edit = AnimationEditingService(doc)
    edit.key(root, "transform.x", 0, 0)
    edit.key(root, "transform.x", 12, 120)
    asset = AssetPipeline(doc).audio_bytes("Voice.wav", voice_bytes())["asset_id"]
    AudioService(doc).attach(asset)
    edit.clip_settings(out_frame=12)
    service = PuppetService(doc)
    service.capture_replay(root)
    card = replace(service.cards()[-1], speed=2, loop=True)
    before = doc.project
    session = PuppetSession(doc, recording=True)
    session.trigger(card, 24)
    assert doc.project is before
    for frame in (27, 33):
        pose = session.pose(frame)
        assert pose.nodes[root].local.x == pytest.approx(60)
        audio = AudioService(session.scratch).positions(frame)[-1]
        assert audio.seconds == pytest.approx(0.25) and audio.rate == 2
    session.pose(36)
    session.commit()
    assert doc.animation.evaluate(33).nodes[root].local.x == pytest.approx(60)
    assert AudioService(doc).positions(33)[-1].seconds == pytest.approx(0.25)
    assert AudioService(doc).positions(36)[-1].gain == 0
    doc.undo()
    assert doc.project == before


def test_audio_rate_loop_and_end_limit_match_rendered_pcm():
    """Portable mixing and transport use the same rate, exclusive loop/end and source trims."""
    source = voice_bytes()
    track = {
        "rate": 2,
        "loop_frames": 12,
        "end_frame": 24,
        "start_frame": 0,
        "trim_start": 0,
        "trim_end": 0.5,
    }
    assert track_state(track, 3, 24, 0.5)[0] == pytest.approx(0.25)
    assert track_state(track, 12, 24, 0.5)[0] == 0
    assert track_state(track, 24, 24, 0.5)[2] == 0
    mixed = io.BytesIO()
    write_mix(mixed, ((track, source),), start=0, duration=1.5, fps=24, rate=8000)
    with wave.open(io.BytesIO(mixed.getvalue()), "rb") as audio:
        raw = audio.readframes(audio.getnframes())
    samples = struct.unpack("<" + "h" * (len(raw) // 2), raw)
    assert samples[800] > 7000 and samples[6000] == 0 and samples[9000] > 7000
    assert all(value == 0 for value in samples[16000:])


def test_audio_phase_controls_are_available_through_the_public_api(tmp_path):
    """Automation validates and saves the same timing data used by the desktop mixer."""
    from rigora.api import RigoraAPI

    (tmp_path / "voice.wav").write_bytes(voice_bytes())
    api = RigoraAPI(tmp_path)
    api.execute("project_create", {"fps": 24})
    asset = api.execute("audio_import", {"path": "voice.wav"}).data["asset_id"]
    api.execute(
        "audio_track_edit",
        {
            "asset_id": asset,
            "start": 24,
            "rate": 2,
            "loop_frames": 6,
            "loop_start_frame": 24,
            "source_offset": 0.1,
            "end_frame": 48,
        },
    )
    at = AudioService(api.document).positions(26)[0]
    assert at.seconds == pytest.approx(0.1 + 2 / 24 * 2)
    assert AudioService(api.document).positions(48)[0].gain == 0


def test_trimmed_replay_keeps_original_audio_phase_and_failed_cues_are_atomic():
    """A clipped-in voice starts at the trigger, retains fades and loops around the action."""
    doc = DocumentService()
    doc.new()
    root = CharacterService(doc).create_object(name="Actor")
    edit = AnimationEditingService(doc)
    edit.key(root, "transform.x", 0, 0)
    edit.key(root, "transform.x", 12, 120)
    asset = AssetPipeline(doc).audio_bytes("Voice.wav", voice_bytes())["asset_id"]
    AudioService(doc).put_track(asset, fade_in=0.4)
    edit.clip_settings(in_frame=6, out_frame=12)
    service = PuppetService(doc)
    service.capture_replay(root)
    card = service.cards()[-1]
    session = PuppetSession(doc)
    session.trigger(card, 24)
    sound = AudioService(session.scratch)
    assert sound.positions(23)[-1].gain == 0
    for frame in (24, 30):
        at = sound.positions(frame)[-1]
        assert at.seconds == pytest.approx(0.25) and at.gain == pytest.approx(0.25 / 0.4)
    before = session.scratch.project
    with pytest.raises(ProjectError, match="missing"):
        session.trigger(replace(card, content={"clip_id": "missing"}), 27)
    assert session.scratch.project is before and len(session.events) == 1
    assert session.pose(27).nodes[root].local.x == pytest.approx(90)
    delayed = {"start_frame": 28, "loop_start_frame": 24, "loop_frames": 12, "trim_end": 0.5}
    assert track_state(delayed, 36, 24, 0.5)[2] == 0
    assert track_state(delayed, 40, 24, 0.5)[0] == 0


@pytest.mark.gui
def test_puppet_stage_voice_only_keep_is_atomic_and_discard_cancels(qtbot, tmp_path, monkeypatch):
    """Real Stage controls keep voice without requiring a motion trigger or real devices."""
    from rigora.app.application import ApplicationInfo
    from rigora.application_services.recording import PcmRecording
    from rigora.infrastructure.preferences import PreferencesStore
    from rigora.presentation.viewmodels.audio_playback import AudioPlayback
    from rigora.presentation.viewmodels.main_window import MainWindowViewModel
    from rigora.presentation.viewmodels.microphone import MicrophoneCapture
    from rigora.presentation.views.main_window import MainWindow
    from rigora.presentation.widgets.puppet_stage import PuppetStage

    def start(capture, device_id=""):
        capture.recording, capture.active = PcmRecording(), True
        capture.recording.append(bytes(16000))

    monkeypatch.setattr(MicrophoneCapture, "start", start)
    monkeypatch.setattr(AudioPlayback, "sync_frame", lambda *args: None)
    vm = MainWindowViewModel(ApplicationInfo(), preferences=PreferencesStore(tmp_path / "ui.json"))
    host = MainWindow(vm)
    host.confirm_discard = lambda: True
    qtbot.addWidget(host)
    vm.new_project()
    stage = PuppetStage(host)
    qtbot.addWidget(stage)
    original, steps = vm.documents.project, len(vm.documents.history.undo_stack)
    stage.start(False)
    stage.stop()
    assert stage.stopped_take is None and vm.documents.project is original
    stage.start(False)
    assert stage.session is not None
    stage.stop()
    stage.record_voice.setChecked(True)
    stage.start(True)
    assert stage.microphone.active
    stage.stop()
    qtbot.waitUntil(lambda: not stage.busy, timeout=5000)
    assert len(vm.documents.history.undo_stack) == steps + 1
    assert vm.documents.project.assets[-1].kind == "audio"
    assert not stage.microphone.active and stage.stopped_take is None
    vm.documents.undo()
    assert vm.documents.project == original
    stage.start(True)
    stage.stop()
    stage.stop(cancel=True)
    qtbot.waitUntil(lambda: not vm.content.jobs, timeout=5000)
    assert vm.documents.project == original and stage.microphone.recording is None
    stage.close()


@pytest.mark.gui
def test_replay_card_reads_private_object_action_in_scene_workspace(qtbot, tmp_path, monkeypatch):
    """The GUI's separated action contexts do not block replay source audio lookup."""
    from rigora.app.application import ApplicationInfo
    from rigora.infrastructure.preferences import PreferencesStore
    from rigora.presentation.viewmodels.main_window import MainWindowViewModel
    from rigora.presentation.views.main_window import MainWindow

    vm = MainWindowViewModel(ApplicationInfo(), preferences=PreferencesStore(tmp_path / "ui.json"))
    host = MainWindow(vm)
    host.confirm_discard = lambda: True
    qtbot.addWidget(host)
    vm.new_project()
    doc = vm.documents
    assert doc.separated_animation
    root = CharacterService(doc).create_object(name="Actor")
    edit = AnimationEditingService(doc)
    edit.key(root, "transform.x", 0, 0)
    edit.key(root, "transform.x", 12, 120)
    asset = AssetPipeline(doc).audio_bytes("Voice.wav", voice_bytes())["asset_id"]
    AudioService(doc).attach(asset)
    service = PuppetService(doc)
    service.capture_replay(root)
    session = PuppetSession(doc)
    session.trigger(service.cards()[-1], 0)
    assert session.pose(6).nodes[root].local.x == pytest.approx(60)
    assert doc.animation_context is None
