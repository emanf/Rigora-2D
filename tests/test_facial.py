"""Vector viseme rendering, timed speech controls and optional local PCM analysis."""

import io
import struct
import wave

import pytest

from rigora.application_services.documents import DocumentService
from rigora.application_services.facial import VISEMES, FaceService, viseme, waveform
from rigora.application_services.rigging import RigService
from rigora.domain.project import ProjectError


def audio_bytes():
    """Produce a small deterministic silent/voiced/silent PCM waveform."""
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\0\0" * 2000 + struct.pack("<h", 16000) * 4000 + b"\0\0" * 2000)
    return output.getvalue()


def test_vector_face_visemes_blink_gaze_and_archive(tmp_path):
    """Step keys reveal originally hidden vector mouths and editable eye channels survive save."""
    doc = DocumentService()
    doc.new()
    face = FaceService(doc)
    original = doc.project
    key = face.create()
    assert len(doc.history.undo_stack) == 1
    descriptor = face.face(key)
    assert set(descriptor["mouths"]) == set(VISEMES)
    assert all(doc.read_asset(m.asset_id).startswith(b"<svg") for m in face.scene.meshes)
    face.lip_sync(key, ((0, "Rest"), (0.25, "AH1"), (0.5, "M"), (0.75, "O"), (1, "SIL")))
    pose = doc.animation.evaluate(6)
    assert pose.nodes[descriptor["mouths"]["AI"]].visible
    assert sum(pose.nodes[n].visible for n in descriptor["mouths"].values()) == 1
    face.controls(key, 12, expression="Angry", look_x=1, look_y=-1, blink=0.5, mouth="FV")
    face.blink(key, 18, 6)
    pose = doc.animation.evaluate(21)
    assert pose.nodes[descriptor["eyes"][0]].local.scale_y == pytest.approx(0.04)
    assert pose.nodes[descriptor["pupils"][0]].local.x == pytest.approx(-45)
    doc.save(tmp_path / "face.rigora")
    reopened = DocumentService()
    reopened.open(tmp_path / "face.rigora")
    assert reopened.animation.evaluate(21) == pose
    while doc.history.undo_stack:
        doc.undo()
    assert doc.project == original


def test_face_attachment_and_invalid_cues_are_atomic():
    """A bone-following face uses the canonical constraint graph and rejects unknown phonemes."""
    doc = DocumentService()
    doc.new()
    bone = RigService(doc).create_bone((200, 200), (200, 100))
    face = FaceService(doc)
    key = face.create(parent_bone=bone)
    assert doc.animation.pose.nodes[key].world_matrix == pytest.approx((1, 0, 0, 1, 200, 200))
    before = doc.project
    with pytest.raises(ProjectError, match="Unknown phoneme"):
        face.lip_sync(key, ((0, "AH"), (0.5, "invalid")))
    assert doc.project is before
    assert viseme("AH0") == "AI"
    assert viseme("+SPN+") == "Rest"


def test_pcm_waveform_and_energy_suggestions_are_local_and_explicit():
    """Optional stdlib analysis creates real timing cues without a speech recognition model."""
    data = audio_bytes()
    duration, peaks = waveform(data, 128)
    assert duration == 1 and peaks[0] == 0 and peaks[64] > 0.4 and peaks[-1] == 0
    doc = DocumentService()
    doc.new()
    cues = FaceService(doc).audio_cues(data)
    assert cues[0][1] == "Rest" and any(shape == "AI" for _, shape in cues)
    assert cues[-1] == (1, "Rest")
    with pytest.raises(ProjectError):
        waveform(b"bad audio")


@pytest.mark.gui
def test_face_dialog_preview_keys_and_cue_errors(qtbot, tmp_path):
    """The real face editor previews without writes and publishes valid cue rows atomically."""
    pytest.importorskip("PySide6")
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
    dialog.show()
    dialog.create_face()
    assert dialog.faces.count() == 1 and not vm.animation_editor.error
    before = vm.documents.project
    dialog.expression.setCurrentText("Happy")
    dialog.preview()
    assert vm.documents.project is before and vm.animation_editor.preview_pose is None
    assert dialog.portrait.pose is not vm.documents.animation.pose
    dialog.key_controls()
    assert vm.documents.project is not before and not vm.animation_editor.error
    before = vm.documents.project
    dialog.cues.setPlainText("bad row")
    dialog.key_cues()
    assert vm.documents.project is before and "Cue row" in dialog.status.text()
    dialog.cues.setPlainText("0, Rest\n.25, AH\n.5, M")
    dialog.key_cues()
    assert not vm.animation_editor.error
    dialog.wave.duration, dialog.wave.peaks = waveform(audio_bytes(), 128)
    dialog.wave.update()
    qtbot.wait(20)
    assert dialog.grab().save(str(tmp_path / "face-dialog.png"))
    dialog.close()
