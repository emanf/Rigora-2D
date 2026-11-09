"""Calibrated camera takes retain editable geometry and never require physical capture in tests."""

import math
from dataclasses import replace

import pytest

from rigora.application_services.character_creation import CharacterCreationService, build_character
from rigora.application_services.documents import DocumentService
from rigora.application_services.facial import FaceService
from rigora.application_services.tracking import TrackingSample, TrackingTake
from rigora.domain.character_recipe import character_preset
from rigora.domain.project import ProjectError


def test_face_take_preview_loss_keys_undo_and_existing_animation(tmp_path):
    """A stopped take keys ordinary face controls, preserves later keys and undoes in one step."""
    doc = DocumentService()
    doc.new()
    service = FaceService(doc)
    target = service.create()
    service.controls(target, 24, mouth="FV")
    doc.animation.seek(0)
    before, steps = doc.project, len(doc.history.undo_stack)
    descriptor = service.face(target)
    take = TrackingTake(doc, target, 0)
    take.feed(TrackingSample(0, {"jawOpen": 0, "eyeBlinkLeft": 0}, {"head": 0}))
    take.calibrate()
    take.record()
    pose = take.feed(TrackingSample(0.1, {"jawOpen": 1, "eyeBlinkLeft": 1}, {"head": 20}))
    assert doc.project is before and len(doc.history.undo_stack) == steps
    assert pose.nodes[target].local.rotation == pytest.approx(20)
    assert pose.nodes[descriptor["mouths"]["AI"]].visible
    assert pose.nodes[descriptor["eyes"][0]].local.scale_y == pytest.approx(0.04)
    take.feed(TrackingSample(0.2))
    assert take.frames[-1][1] == take.frames[-2][1]
    take.keep()
    assert len(doc.history.undo_stack) == steps + 1
    assert doc.animation.evaluate(24).nodes[descriptor["mouths"]["FV"]].visible
    assert doc.animation.evaluate(2.4).nodes[descriptor["mouths"]["AI"]].visible
    doc.save(tmp_path / "camera.rigora")
    reopened = DocumentService()
    reopened.open(tmp_path / "camera.rigora")
    assert reopened.animation.evaluate(2.4) == doc.animation.evaluate(2.4)
    doc.undo()
    assert doc.project == before


@pytest.mark.parametrize("identity", ("Classic", "Sport", "Ribbon", "Little", "Orbit"))
def test_creator_body_calibration_subtracts_parent_motion_and_keys_eye_variants(identity):
    """Calibrated global limb angles become local deltas without changing lengths or clothes."""
    doc = DocumentService()
    doc.new()
    root = CharacterCreationService(doc).create(
        build_character(replace(character_preset(identity), motions=()))
    )
    take = TrackingTake(doc, root, 0)
    take.feed(
        TrackingSample(
            0,
            {"jawOpen": 0, "eyeBlinkLeft": 0},
            {"hips": -90, "upper_arm.L": 90, "forearm.L": 90, "head": 0},
        )
    )
    take.record()
    before = doc.project
    pose = take.feed(
        TrackingSample(
            0.1,
            {"jawOpen": 0.8, "eyeBlinkLeft": 0.9},
            {"hips": -80, "upper_arm.L": 110, "forearm.L": 140, "head": 15},
        )
    )
    for name, delta in (("hips", 10), ("upper_arm.L", 10), ("forearm.L", 30), ("head", 5)):
        bone = take.mapping.bones[name]
        assert pose.nodes[bone.id].local.rotation == pytest.approx(
            take.mapping.pose.nodes[bone.id].local.rotation + delta
        )
        assert pose.nodes[bone.id].length == take.mapping.pose.nodes[bone.id].length
    if take.mapping.eye_variants:
        assert take.mapping.eye_variants["Closed"]
        for owner in take.mapping.eye_variants["Closed"]:
            assert pose.nodes[owner].visible
        for owner in take.mapping.eye_variants["Open"]:
            assert not pose.nodes[owner].visible
    else:
        assert take.mapping.face["eyes"]
        for owner in take.mapping.face["eyes"]:
            assert pose.nodes[owner].local.scale_y == pytest.approx(0.1)
    take.keep()
    assert doc.project.scenes[0].meshes == before.scenes[0].meshes
    assert doc.project.scenes[0].skeletons == before.scenes[0].skeletons
    doc.undo()
    assert doc.project == before


def test_tracking_limits_invalid_samples_and_stale_publication_are_atomic():
    """Bad detector input and exhausted takes fail before a project edit."""
    for sample in ((math.nan, {}, {}), (0, {"jawOpen": -1}, {}), (0, {}, {"head": math.inf})):
        with pytest.raises(ProjectError):
            TrackingSample(*sample)
    doc = DocumentService()
    doc.new()
    target = FaceService(doc).create()
    take = TrackingTake(doc, target)
    take.feed(TrackingSample(0, {"jawOpen": 0}))
    take.record()
    before = doc.project
    for i in range(1, 600):
        take.feed(TrackingSample(i / 15, {"jawOpen": 0.4}), preview=False)
    with pytest.raises(ProjectError, match="limit"):
        take.feed(TrackingSample(40, {"jawOpen": 0.4}), preview=False)
    assert len(take.frames) == 600 and doc.project is before
    with pytest.raises(ProjectError, match="increase"):
        take.feed(TrackingSample(0))
    FaceService(doc).controls(target, 10, mouth="O")
    changed = doc.project
    with pytest.raises(ProjectError, match="changed"):
        take.keep()
    assert doc.project is changed


def test_headless_tracking_operation_uses_the_same_keys(tmp_path):
    """Python/CLI/MCP observations use the shared retargeter with no camera/model dependency."""
    from rigora.api import RigoraAPI

    api = RigoraAPI(tmp_path)
    api.document.new()
    face = FaceService(api.document).create()
    before = api.document.project
    result = api.execute(
        "tracking_apply",
        {
            "target_id": face,
            "smoothing": 0,
            "samples": [
                {"seconds": 0, "face": {"jawOpen": 0}},
                {"seconds": 0.2, "face": {"jawOpen": 0.9}},
            ],
        },
    )
    assert result.data["samples"] == 2 and result.data["channels"] >= 10
    assert (
        api.document.animation.evaluate(4.8)
        .nodes[FaceService(api.document).face(face)["mouths"]["AI"]]
        .visible
    )
    api.document.undo()
    assert api.document.project == before
    result = api.execute(
        "tracking_apply",
        {"target_id": face, "start": 1000, "samples": [{"seconds": 0, "face": {"jawOpen": 0}}]},
    )
    assert result.data["start"] == 1000
    assert api.document.animation.evaluator.clip.out_frame >= 1000


def test_clip_switch_and_stale_inflight_frames_cannot_redirect_a_recording():
    """Reject context changes and observations captured before the recording's start."""
    from rigora.application_services.animation_editing import AnimationEditingService

    doc = DocumentService()
    doc.new()
    target = FaceService(doc).create()
    editor = AnimationEditingService(doc)
    first = editor.new_clip("First")
    second = editor.new_clip("Second")
    doc.select_animation_clip(first)
    take = TrackingTake(doc, target)
    take.feed(TrackingSample(0.1, {"jawOpen": 0}))
    take.record(0.3)
    take.feed(TrackingSample(0.2, {"jawOpen": 1}), preview=False)
    assert len(take.frames) == 1
    take.feed(TrackingSample(0.4, {"jawOpen": 1}), preview=False)
    take.stop(0.5)
    assert take.frames[-1][0] == pytest.approx(take.start + 0.2 * 24)
    before = doc.project
    doc.select_animation_clip(second)
    with pytest.raises(ProjectError, match="context changed"):
        take.recorded_command()
    assert doc.project is before


@pytest.fixture
def fake_camera(monkeypatch):
    """Replace only device/detector boundaries while preserving Qt frames, worker and queues."""
    import threading

    from PySide6.QtCore import QByteArray, QObject, Signal

    from rigora.presentation.viewmodels import camera_tracking as backend

    events = []

    class Device:
        """Expose one inert camera identity."""

        def id(self):
            return QByteArray(b"fake-camera")

        def isNull(self):
            return False

    class Devices:
        """Return devices without enumerating the host's hardware."""

        @staticmethod
        def videoInputs():
            return [Device()]

        @staticmethod
        def defaultVideoInput():
            return Device()

    class Camera(QObject):
        """Observe explicit start/stop calls without accessing an OS device."""

        errorOccurred = Signal(object, str)

        def __init__(self, device, parent):
            super().__init__(parent)
            events.append("create camera")

        def start(self):
            events.append("start camera")

        def stop(self):
            events.append("stop camera")

        def errorString(self):
            return "fake camera error"

    class Session(QObject):
        """Keep fake camera/sink bindings in the real Qt ownership tree."""

        def setCamera(self, camera):
            self.camera = camera

        def setVideoSink(self, sink):
            self.sink = sink

    class Detector:
        """Read actual queued RGB bytes on the worker and emit calibrated test observations."""

        def __init__(self, face, body):
            if face.name == "bad":
                raise ProjectError("Fixture model is invalid")
            self.index = 0
            events.append(("model", threading.get_ident()))

        def detect(self, rgb, seconds):
            assert rgb.ndim == 3 and rgb.shape[2] == 3
            self.index += 1
            return TrackingSample(seconds, {"jawOpen": 0 if self.index == 1 else 0.9})

        def close(self):
            events.append("close model")

    monkeypatch.setattr(backend, "QMediaDevices", Devices)
    monkeypatch.setattr(backend, "QCamera", Camera)
    monkeypatch.setattr(backend, "QMediaCaptureSession", Session)
    monkeypatch.setattr(backend, "LocalTracker", Detector)
    return backend, events


@pytest.mark.gui
def test_camera_ui_explicit_start_preview_record_stop_and_discard(
    qtbot, tmp_path, fake_camera, fake_microphone
):
    """Real visible controls record one undoable take through an asynchronous fake device."""
    from types import SimpleNamespace

    from PySide6.QtGui import QImage

    from rigora.app.application import ApplicationInfo
    from rigora.infrastructure.preferences import PreferencesStore
    from rigora.presentation.viewmodels.main_window import MainWindowViewModel
    from rigora.presentation.views.main_window import MainWindow

    backend, events = fake_camera
    vm = MainWindowViewModel(ApplicationInfo(), preferences=PreferencesStore(tmp_path / "ui.json"))
    window = MainWindow(vm)
    window.confirm_discard = lambda: True
    qtbot.addWidget(window)
    vm.new_project()
    vm.content.pool.waitForDone(3000)
    FaceService(vm.documents).create()
    window.command_actions["camera_tracking"].trigger()
    dialog = window.camera_dialog
    qtbot.addWidget(dialog)
    dialog.show()
    assert not events
    before, steps = vm.documents.project, len(vm.documents.history.undo_stack)
    dialog.start()
    qtbot.waitUntil(lambda: "start camera" in events, timeout=5000)
    image = QImage(64, 64, QImage.Format.Format_RGB888)
    image.fill(0)
    frame = SimpleNamespace(toImage=lambda: image)
    dialog.capture.frame_ready(frame)
    qtbot.waitUntil(lambda: dialog.take and dialog.take.latest is not None, timeout=5000)
    dialog.calibrate()
    dialog.record_voice.setChecked(True)
    dialog.record()
    dialog.microphone.read()
    qtbot.wait(80)
    dialog.capture.frame_ready(frame)
    qtbot.waitUntil(lambda: len(dialog.take.frames) == 2, timeout=5000)
    assert vm.documents.project is before
    dialog.microphone.error = "Simulated input disconnected"
    dialog.microphone.changed.emit()
    assert not dialog.capture.active and not dialog.microphone.active
    assert not dialog.take.recording and len(dialog.take.frames) == 2
    dialog.keep()
    assert "stop camera" in events
    qtbot.waitUntil(lambda: not dialog.busy and dialog.take is None, timeout=10000)
    qtbot.waitUntil(lambda: dialog.capture.job is None, timeout=5000)
    assert len(vm.documents.history.undo_stack) == steps + 1
    assert vm.documents.project.assets[-1].kind == "audio"
    clip = FaceService(vm.documents).clip
    assert clip.extra["audio"]["start_frame"] == 0
    assert clip.extra["audio"]["asset_id"] == vm.documents.project.assets[-1].id
    assert dialog.microphone.recording is None and not dialog.microphone.active
    assert "recorded" in dialog.status.text()
    assert "close model" in events
    assert dialog.grab().save(str(tmp_path / "camera-dialog.png"))
    vm.documents.undo()
    assert vm.documents.project == before
    dialog.face_model.setText("bad")
    dialog.start()
    qtbot.waitUntil(lambda: dialog.capture.job is None, timeout=5000)
    assert events.count("start camera") == 1
    assert "invalid" in dialog.status.text()
    assert dialog.buttons["Start preview"].isEnabled()
    dialog.close()
    assert not dialog.capture.active
