"""Real custom-chrome import/output controls and responsive shared-service workflows."""

import threading

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("PIL")
pytest.importorskip("resvg_py")

from PIL import Image
from PySide6.QtCore import Qt, QThread

from rigora.app.application import ApplicationInfo
from rigora.infrastructure.media_import import png_bytes
from rigora.infrastructure.preferences import PreferencesStore
from rigora.presentation.viewmodels.main_window import MainWindowViewModel
from rigora.presentation.views.main_window import MainWindow


@pytest.fixture
def editor(qtbot, tmp_path):
    """Own a visible isolated editor whose teardown never opens save confirmation."""
    vm = MainWindowViewModel(ApplicationInfo(), preferences=PreferencesStore(tmp_path / "ui.json"))
    window = MainWindow(vm)
    window.confirm_discard = lambda: True
    qtbot.addWidget(window)
    window.show()
    vm.new_project()
    return window


def test_media_import_registers_before_placement_and_sprite_playback(editor, qtbot, tmp_path, qapp):
    """Sequence import adopts records on the GUI thread and double-click creates live instances."""
    for index, color in enumerate(("red", "blue")):
        (tmp_path / f"frame-{index}.png").write_bytes(png_bytes(Image.new("RGBA", (20, 20), color)))
    editor.command_actions["import_media"].trigger()
    dialog = editor.media_dialog
    qtbot.addWidget(dialog)
    assert dialog.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert not dialog.place.isChecked()
    dialog.kind.setCurrentIndex(dialog.kind.findData("sequence_import"))
    dialog.paths.setPlainText("\n".join(str(tmp_path / f"frame-{i}.png") for i in range(2)))
    threads = []
    editor.viewmodel.media.imported.connect(lambda data: threads.append(QThread.currentThread()))
    dialog.import_button.click()
    qtbot.waitUntil(lambda: not editor.viewmodel.media.busy, timeout=10000)
    assert not editor.viewmodel.media.error
    assert threads == [qapp.thread()]
    project = editor.viewmodel.documents.project
    assert len(project.assets) == 3 and not project.scenes[0].meshes
    assert len(editor.viewmodel.documents.history.undo_stack) == 1
    sequence = next(a for a in project.assets if "sprite_sequence" in a.extra)
    row = next(
        editor.project_assets.item(i)
        for i in range(editor.project_assets.count())
        if editor.project_assets.item(i).data(Qt.ItemDataRole.UserRole) == sequence.id
    )
    editor.place_asset(row)
    editor.place_asset(
        next(
            editor.project_assets.item(i)
            for i in range(editor.project_assets.count())
            if editor.project_assets.item(i).data(Qt.ItemDataRole.UserRole) == sequence.id
        )
    )
    assert len(editor.viewmodel.documents.project.scenes[0].meshes) == 2
    qtbot.waitUntil(lambda: not editor.mesh_workspace.jobs, timeout=10000)
    mesh = editor.viewmodel.documents.project.scenes[0].meshes[0]
    assert (
        editor.viewmodel.documents.animation.evaluate(1).meshes[mesh.id].asset_id
        == sequence.extra["sprite_sequence"]["assets"][1]
    )


def test_render_dialog_queue_is_responsive_and_preserves_settings(
    editor, qtbot, tmp_path, monkeypatch
):
    """Queue settings render actual PNGs off-thread and retain snapshot history in the dialog."""
    from rigora.api import RigoraAPI
    from rigora.application_services import output

    api = RigoraAPI(tmp_path, document=editor.viewmodel.documents)
    api.execute("character_create", {"x": 800, "y": 300})
    editor.viewmodel.changed.emit()
    editor.command_actions["render_output"].trigger()
    dialog = editor.output_dialog
    qtbot.addWidget(dialog)
    assert dialog.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert dialog.transparent.isChecked()
    dialog.path.setText(str(tmp_path / "frame.png"))
    dialog.output_width.setValue(320)
    dialog.output_height.setValue(180)
    dialog.start.setValue(0)
    dialog.end.setValue(1)
    entered, release = threading.Event(), threading.Event()
    original = output.raster_frame

    def paused(document, frame, settings):
        """Hold actual rasterization briefly to verify that Qt remains free to process input."""
        entered.set()
        assert release.wait(10)
        return original(document, frame, settings)

    monkeypatch.setattr(output, "raster_frame", paused)
    dialog.queue_button.click()
    qtbot.waitUntil(entered.is_set, timeout=10000)
    assert dialog.jobs.topLevelItemCount() == 1
    dialog.jobs.setCurrentItem(dialog.jobs.topLevelItem(0))
    qtbot.wait(20)
    assert dialog.cancel_button.isEnabled()
    dialog.close()
    editor.command_actions["render_output"].trigger()
    assert dialog.output_width.value() == 320
    release.set()
    qtbot.waitUntil(
        lambda: editor.viewmodel.output.states()[0]["status"] == "completed", timeout=10000
    )
    assert Image.open(tmp_path / "frame-0000.png").size == (320, 180)
    assert editor.viewmodel.documents.project.name == "Untitled project"


def test_alpha_export_profiles_route_encoder_and_transparency_settings(
    editor, qtbot, tmp_path, monkeypatch
):
    """The real dialog exposes each profile and passes its alpha/background choice to the queue."""
    from pathlib import Path

    from rigora.application_services.output import FORMATS, VIDEO_OPTIONS

    editor.command_actions["render_output"].trigger()
    dialog = editor.output_dialog
    qtbot.addWidget(dialog)
    submitted = []
    monkeypatch.setattr(dialog.model, "submit", lambda *args: submitted.append(args))
    encoder = tmp_path / "ffmpeg"
    monkeypatch.setattr(
        "rigora.presentation.widgets.media_dialogs.shutil.which", lambda name: str(encoder)
    )
    dialog.use_installed_encoder()
    assert dialog.encoder.text() == str(encoder)
    dialog.encoder.setText(str(encoder))
    dialog.format.setCurrentIndex(dialog.format.findData("mp4"))
    assert not dialog.transparent.isChecked()
    for kind in ("webm", "webm-vp8", "mov", "ffv1", "apng"):
        dialog.format.setCurrentIndex(dialog.format.findData(kind))
        assert dialog.transparent.isChecked() and dialog.transparent.isEnabled()
        assert dialog.encoder.isEnabled() == (kind in VIDEO_OPTIONS)
        assert Path(dialog.path.text()).suffix == FORMATS[kind][1]
        assert dialog.format_note.text()
        dialog.path.setText(str(tmp_path / (kind + FORMATS[kind][1])))
        dialog.enqueue()
        _, _, settings, _, actual_encoder = submitted[-1]
        assert settings.format == kind and settings.background is None
        assert actual_encoder == (encoder if kind in VIDEO_OPTIONS else None)


def test_video_export_autodetects_installed_encoder_and_completes(editor, qtbot, tmp_path):
    """Video is immediately usable from the actual dialog without choosing an encoder first."""
    import shutil
    from pathlib import Path

    binary = shutil.which("ffmpeg")
    if binary is None:
        pytest.skip("Local FFmpeg is needed for the real video export integration check.")
    editor.viewmodel.preferences.data["video_encoder_path"] = str(tmp_path / "removed-ffmpeg")
    editor.command_actions["render_output"].trigger()
    dialog = editor.output_dialog
    qtbot.addWidget(dialog)
    assert dialog.encoder.text() == binary
    dialog.format.setCurrentIndex(dialog.format.findData("mp4"))
    dialog.output_width.setValue(64)
    dialog.output_height.setValue(64)
    dialog.start.setValue(0)
    dialog.end.setValue(1)
    dialog.path.setText(str(tmp_path / "auto-video.mp4"))
    dialog.enqueue()
    qtbot.waitUntil(
        lambda: (
            editor.viewmodel.output.states()
            and editor.viewmodel.output.states()[-1]["status"] in ("completed", "failed")
        ),
        timeout=30000,
    )
    state = editor.viewmodel.output.states()[-1]
    assert state["status"] == "completed", state["error"]
    assert Path(dialog.path.text()).stat().st_size > 100
    assert editor.viewmodel.preferences.data["video_encoder_path"] == binary
