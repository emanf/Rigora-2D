"""Actual mixer, typed-marker and background artwork authoring without native focus/input."""

import pytest
from test_audio_mixer import constant_wav
from test_roots_soft_drag_gui import editor as editor

from rigora.application_services.asset_pipeline import AssetPipeline
from rigora.application_services.audio import AudioService
from rigora.application_services.meshes import MeshService

pytestmark = pytest.mark.gui


def test_export_preflight_runs_off_thread_and_rejects_stale_revision(
    editor, qtbot, monkeypatch, tmp_path
):
    """The actual export dialog remains responsive and refuses a report for edited artwork."""
    from threading import Event

    from rigora.application_services.export_preflight import ExportPreflight
    from rigora.presentation.widgets.media_dialogs import OutputDialog

    gate, entered = Event(), Event()
    original = ExportPreflight.inspect

    def inspect(service, *args, **kwargs):
        entered.set()
        gate.wait(5)
        return original(service, *args, **kwargs)

    monkeypatch.setattr(ExportPreflight, "inspect", inspect)
    dialog = OutputDialog(editor)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.start.setValue(0)
    dialog.end.setValue(0)
    dialog.enqueue(check_only=True)
    qtbot.waitUntil(entered.is_set)
    assert dialog.check_progress.isVisible()
    assert editor.viewmodel.output.check_job is not None
    doc = editor.viewmodel.documents
    camera = doc.scene.cameras[0]
    from rigora.application_services.cameras import CameraService

    CameraService(doc).update(camera.id, name="Revised during export check")
    gate.set()
    qtbot.waitUntil(lambda: editor.viewmodel.output.check_job is None)
    assert "stale" in editor.viewmodel.output.error
    assert not dialog.check_report.isVisible()
    dialog.enqueue(check_only=True)
    qtbot.waitUntil(lambda: editor.viewmodel.output.check_job is None)
    assert editor.viewmodel.output.check_result["ready"]
    assert "PNG" in dialog.check_report.toPlainText()
    assert not dialog.check_progress.isVisible()
    assert dialog.grab().save(str(tmp_path / "export-preflight.png"))


def test_audio_mixer_owns_independent_placements(editor, qtbot):
    """UI operations create real mixer data; removing one track leaves its source and peer."""
    doc = editor.viewmodel.documents
    key = AssetPipeline(doc).audio_bytes("voice.wav", constant_wav())["asset_id"]
    editor.viewmodel.changed.emit()
    editor.command_actions["audio_tracks"].trigger()
    dialog = editor.audio_mixer
    qtbot.addWidget(dialog)
    assert dialog.sources.currentData() == key
    dialog.track_name.setText("Voice")
    dialog.fade_in.setValue(0.1)
    dialog.apply()
    assert not editor.viewmodel.scene.error, dialog.note.text()
    dialog.tracks.setCurrentIndex(0)
    dialog.track_name.setText("Music")
    dialog.gain.setValue(0.3)
    dialog.apply()
    assert len(AudioService(doc).tracks()) == 2
    dialog.remove()
    assert len(AudioService(doc).tracks()) == 1
    assert doc.read_asset(key)


def test_artwork_worker_uses_stable_asset_identity(editor, qtbot, tmp_path, monkeypatch):
    """The native-picker route validates a revision on a worker and preserves geometry."""
    doc = editor.viewmodel.documents
    original = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40">'
        b'<rect width="40" height="40" fill="red"/></svg>'
    )
    mesh = MeshService(doc)
    key = mesh.register_image_bytes("art.svg", original)
    mesh.instantiate_asset(key)
    editor.viewmodel.changed.emit()
    editor.project_assets.setCurrentRow(0)
    source = tmp_path / "replacement.svg"
    source.write_bytes(original.replace(b"red", b"blue"))
    monkeypatch.setattr(
        "rigora.presentation.views.main_window.choose_open_file", lambda *_: (str(source), "")
    )
    geometry = doc.scene.meshes
    editor.replace_project_artwork()
    qtbot.waitUntil(lambda: not editor.viewmodel.media.busy)
    assert not editor.viewmodel.media.error
    assert doc.read_asset(key) == source.read_bytes()
    assert doc.scene.meshes == geometry
    doc.undo()
    assert doc.read_asset(key) == original


def test_path_window_authors_camera_motion_and_editable_artwork(editor, qtbot):
    """Path handles preview independently and Apply creates genuine constraints/vector sources."""
    doc = editor.viewmodel.documents
    editor.command_actions["path"].trigger()
    dialog = editor.path_editor
    qtbot.addWidget(dialog)
    camera = doc.scene.cameras[0]
    dialog.owner.setCurrentIndex(dialog.owner.findData(camera.id))
    dialog.apply()
    assert not editor.viewmodel.scene.error, dialog.note.text()
    assert any(c.kind == "motion_path" for c in doc.scene.constraints)
    dialog.mode.setCurrentIndex(1)
    dialog.closed.setChecked(True)
    dialog.apply()
    assert not editor.viewmodel.scene.error, dialog.note.text()
    assert any(m.extra.get("bezier_art") for m in doc.scene.meshes)


def test_path_window_preserves_existing_timing_and_artwork_outline(editor, qtbot):
    """Reopening controls preserves authored timing and stroke properties on Apply."""
    from rigora.application_services.path_editing import PathEditingService
    from rigora.presentation.widgets.path_editor import PathEditor

    doc = editor.viewmodel.documents
    service = PathEditingService(doc)
    points = ((0, 0), (0, 100), (100, 100), (100, 0))
    camera = doc.scene.cameras[0].id
    service.motion(camera, points, 50, 80)
    mesh = service.artwork(points, stroke_width=7)
    dialog = PathEditor(editor)
    qtbot.addWidget(dialog)
    dialog.owner.setCurrentIndex(dialog.owner.findData(camera))
    assert (dialog.start.value(), dialog.end.value()) == (50, 80)
    dialog.apply()
    assert not editor.viewmodel.scene.error
    dialog.owner.setCurrentIndex(dialog.owner.findData(service.mesh(mesh).object_id))
    dialog.mode.setCurrentIndex(1)
    assert dialog.stroke_width == 7
    dialog.apply()
    assert not editor.viewmodel.scene.error
    assert service.mesh(mesh).extra["bezier_art"]["stroke_width"] == 7


def test_game_tools_create_selectable_regions_and_rendered_particles(editor, qtbot):
    """Actual UI creates owned metadata objects and live evaluated primitives."""
    doc = editor.viewmodel.documents
    editor.command_actions["game_tools"].trigger()
    dialog = editor.game_tools
    qtbot.addWidget(dialog)
    dialog.region_payload.setPlainText('{"damage": 5}')
    dialog.apply()
    assert not editor.viewmodel.scene.error, dialog.note.text()
    region = dialog.items.currentData()
    assert region in editor.scene_workspace.polygons()
    assert next(o for o in doc.scene.objects if o.id == region).extra["game_region"]["payload"] == {
        "damage": 5
    }
    assert '"damage": 5' in dialog.region_payload.toPlainText()
    revision = doc.project
    dialog.region_payload.setPlainText("[]")
    dialog.apply()
    assert "JSON object" in editor.viewmodel.scene.error and doc.project is revision
    dialog.tabs.setCurrentIndex(1)
    dialog.item_name.setText("Sparks")
    dialog.apply()
    assert not editor.viewmodel.scene.error, dialog.note.text()
    emitter = dialog.items.currentData()
    assert emitter in doc.animation.pose.particles
    assert doc.animation.pose.particles[emitter]
    assert emitter in editor.scene_workspace.polygons()
    dialog.tabs.setCurrentIndex(2)
    assert dialog.items.currentData() == emitter
    dialog.ground.setChecked(True)
    dialog.parameters["ground_y"].setValue(500)
    dialog.apply()
    assert not editor.viewmodel.scene.error
    metadata = next(o.extra["particle_emitter"] for o in doc.scene.objects if o.id == emitter)
    assert metadata["ground_enabled"] and metadata["ground_y"] == 500


def test_camera_shot_cards_guides_transitions_and_background_thumbnails(editor, qtbot):
    """Shot cards create real cuts/transitions and background-rendered thumbnails."""
    from rigora.application_services.camera_shots import CameraShotService

    editor.object_edit.exit()
    doc = editor.viewmodel.documents
    service = CameraShotService(doc)
    second = service.add("Closeup")
    editor.viewmodel.changed.emit()
    editor.show_camera_shots()
    dialog = editor.camera_shots
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog.job is None)
    assert dialog.cards.count() == 1
    dialog.camera.setCurrentIndex(dialog.camera.findData(second))
    dialog.at_frame.setValue(10)
    dialog.duration.setValue(10)
    dialog.apply()
    assert not editor.viewmodel.scene.error, dialog.note.text()
    assert dialog.cards.count() == 2
    dialog.guides.setCurrentText("Thirds + safe")
    assert editor.viewport.camera_guides == "Thirds + safe"
    dialog.thumbnails()
    qtbot.waitUntil(lambda: dialog.job is None)
    assert not dialog.cards.item(1).icon().isNull()
    assert any(lane == "Transition" for _, lane in editor.timeline._groups)


def test_state_machine_live_inputs_and_close_restore_source(editor, qtbot):
    """The real state editor previews input changes and releases only its own display snapshot."""
    from test_state_machines import machine_document

    doc, root, part = machine_document()
    editor.viewmodel.workspace.adopt(doc)
    editor.viewmodel.activate_project(editor.viewmodel.workspace.documents.index(doc))
    editor.show_state_machine()
    dialog = editor.state_machine
    qtbot.addWidget(dialog)
    dialog.owner.setCurrentIndex(dialog.owner.findData(root))
    assert dialog.states.rowCount() == 2 and dialog.transitions.rowCount() == 2
    revision, frame = doc.project, doc.cursor_frame
    dialog.start_preview()
    assert dialog.timer.isActive()
    dialog.input_value.setText("1")
    dialog.set_input()
    qtbot.waitUntil(lambda: dialog.machine is not None and dialog.machine.current == "Active")
    assert editor.viewmodel.animation_editor.preview_pose is not None
    assert doc.project is revision and doc.cursor_frame == frame
    dialog.close()
    assert not dialog.timer.isActive()
    assert editor.viewmodel.animation_editor.preview_pose is None
