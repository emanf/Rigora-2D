"""Actual editor background saves, recovery selection and saved-tab restoration."""

import threading

import pytest
from PySide6.QtCore import QTimer
from test_roots_soft_drag_gui import editor as editor

from rigora.app.application import ApplicationInfo
from rigora.application_services.animation_editing import AnimationEditingService
from rigora.domain.entities import SceneObject
from rigora.infrastructure.preferences import PreferencesStore
from rigora.infrastructure.project_storage import ProjectStorage
from rigora.presentation.viewmodels.main_window import MainWindowViewModel
from rigora.presentation.views.main_window import MainWindow

pytestmark = pytest.mark.gui


def test_editor_save_stays_responsive_and_preserves_edits_made_during_write(
    editor, qtbot, tmp_path, monkeypatch
):
    """A blocked disk worker cannot block Qt or mark a newer source revision clean."""
    vm, doc = editor.viewmodel, editor.viewmodel.documents
    original, storage_save = doc.project, doc.storage.save
    entered, release = threading.Event(), threading.Event()

    def blocked(*args, **kwargs):
        """Hold real disk serialization until responsiveness and concurrent editing are checked."""
        entered.set()
        assert release.wait(10)
        return storage_save(*args, **kwargs)

    monkeypatch.setattr(doc.storage, "save", blocked)
    path = tmp_path / "background.rigora"
    assert vm.project_io.save(doc, path)
    qtbot.waitUntil(entered.is_set, timeout=5000)
    ticks = []
    heartbeat = QTimer(editor)
    heartbeat.setInterval(5)
    heartbeat.timeout.connect(lambda: ticks.append(1))
    heartbeat.start()
    doc.add_entities(doc.scene.id, {"objects": (SceneObject(name="During save"),)})
    vm.changed.emit()
    qtbot.waitUntil(lambda: len(ticks) >= 3, timeout=2000)
    release.set()
    qtbot.waitUntil(lambda: "save:" + doc.session_id not in vm.project_io.jobs, timeout=10000)
    heartbeat.stop()
    assert doc.dirty and doc.scene.objects[0].name == "During save"
    assert ProjectStorage().load_document(path).project == original
    assert editor.save_project(wait=True)
    assert not doc.dirty and ProjectStorage().load_document(path).project == doc.project


def test_recovery_checkpoint_and_actual_recovery_dialog_leave_source_untouched(editor, qtbot):
    """Automatic snapshots restore through the real menu/dialog into a separate dirty tab."""
    vm, doc = editor.viewmodel, editor.viewmodel.documents
    original, history = doc.project, len(doc.history.undo_stack)
    vm.project_io.checkpoint()
    qtbot.waitUntil(lambda: not vm.project_io.jobs, timeout=10000)
    assert doc.project is original and len(doc.history.undo_stack) == history
    assert vm.project_io.store.entries()
    editor.command_actions["recover_work"].trigger()
    dialog = editor.recovery_dialog
    qtbot.addWidget(dialog)
    assert dialog.entries.count() == 1
    dialog.restore()
    qtbot.waitUntil(lambda: len(vm.workspace.documents) == 2, timeout=10000)
    recovered = vm.workspace.active
    assert recovered is not doc and recovered.path is None and recovered.dirty
    assert recovered.project == original and doc.project is original


def test_saved_tabs_restore_in_background_behind_welcome(editor, qtbot, tmp_path):
    """A new workspace reopens its saved tab and cursor without hiding Welcome."""
    vm, doc = editor.viewmodel, editor.viewmodel.documents
    camera = doc.scene.cameras[0].id
    from rigora.application_services.scene_editing import SceneEditingService

    SceneEditingService(doc).flags((camera,), locked=False)
    AnimationEditingService(doc).key(camera, "transform.x", 0, 0)
    AnimationEditingService(doc).key(camera, "transform.x", 24, 100)
    vm.changed.emit()
    vm.playback.seek(17)
    vm.save_project(tmp_path / "remember.rigora")
    vm.project_io.close()
    model = MainWindowViewModel(
        ApplicationInfo(), preferences=PreferencesStore(vm.preferences.path)
    )
    window = MainWindow(model)
    window.confirm_discard = lambda: True
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: bool(model.workspace.documents), timeout=10000)
    assert model.welcome_selected and window.welcome_window is not None
    assert model.workspace.documents[0].path == tmp_path / "remember.rigora"
    model.activate_project(0)
    assert model.documents.animation.pose.frame == 17
