"""Real SDK trust controls, viewport commands, content integration and removable UI extensions."""

import json

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt, QTimer

from rigora.app.application import ApplicationInfo
from rigora.application_services.meshes import MeshService
from rigora.infrastructure.preferences import PreferencesStore
from rigora.presentation.viewmodels.main_window import MainWindowViewModel
from rigora.presentation.views.main_window import MainWindow
from rigora.sdk.scaffold import generate_plugin

pytestmark = pytest.mark.gui


def open_window(qtbot, tmp_path, roots):
    """Discover development metadata in a real window with isolated trust preferences."""
    preferences = PreferencesStore(tmp_path / "ui.json")
    preferences.data["plugin_development_dirs"] = [str(p) for p in roots]
    model = MainWindowViewModel(ApplicationInfo(), preferences=preferences)
    window = MainWindow(model)
    window.confirm_discard = lambda: True
    qtbot.addWidget(window)
    window.show()
    return window


def test_trust_viewport_tool_deformer_content_and_disable(qtbot, tmp_path):
    """Desktop controls run all three actual examples and remove disabled contributions."""
    roots = [
        generate_plugin(tmp_path / kind, f"org.gui.{kind}", kind)
        for kind in ("tool", "deformer", "content")
    ]
    window = open_window(qtbot, tmp_path, roots)
    vm = window.viewmodel
    window.command_actions["plugins"].trigger()
    dialog = window.plugin_dialog
    assert dialog.isVisible() and not dialog.enable_button.isEnabled()
    dialog.trust.setChecked(True)
    assert dialog.enable_button.isEnabled()
    dialog.enable_button.click()
    assert "org.gui.tool" in vm.plugins.contexts
    window.show()
    window.activateWindow()
    window.command_actions["org.gui.tool.stamp"].trigger()
    qtbot.mouseClick(window.viewport, Qt.MouseButton.LeftButton, pos=QPoint(180, 150))
    assert len(vm.documents.project.scenes[0].skeletons[0].bones) == 2
    assert len(vm.documents.history.undo_stack) == 1
    vm.undo()
    assert not vm.documents.project.scenes[0].skeletons
    window.command_actions["navigate"].trigger()
    assert window.viewport.extension_pointer is None
    from pathlib import Path

    mesh = MeshService(vm.documents).import_image(Path("assets/examples/prop.svg"), 2, 2)
    vm.changed.emit()
    vm.mesh.mesh_id = mesh
    vm.enable_plugin("org.gui.deformer", trust=True)
    baseline = vm.documents.animation.pose.meshes[mesh].positions
    window.command_actions["org.gui.deformer.wave"].trigger()
    assert vm.documents.animation.pose.meshes[mesh].positions != baseline
    vm.enable_plugin("org.gui.content", trust=True)
    vm.content.reload()
    qtbot.waitUntil(lambda: not vm.content.busy, timeout=10000)
    assert len(vm.content.entries) == 288
    vm.plugins.disable("org.gui.tool")
    assert "org.gui.tool.stamp" not in window.command_actions
    vm.plugins.disable("org.gui.content")
    qtbot.waitUntil(lambda: not vm.content.busy, timeout=10000)
    assert len(vm.content.entries) == 287
    window.close()


def test_panel_inspector_renderer_lifecycle_and_callback_failure(qtbot, tmp_path):
    """Custom docks and inspectors bind real documents; renderer failures remain optional."""
    root = generate_plugin(tmp_path / "ui", "org.gui.ui")
    manifest = root / "rigora-plugin.json"
    data = json.loads(manifest.read_text())
    data["capabilities"] = ["panels", "inspectors", "renderers", "commands"]
    manifest.write_text(json.dumps(data))
    (root / "__init__.py").write_text("""from PySide6.QtWidgets import QLabel
from rigora.application_services.rigging import RigService
class Inspector(QLabel):
    def rigora_bind(self, request):
        self.request = request
        self.setText(request.document.project.name if request.document else 'No project')
def panel(request, parent):
    return Inspector(parent)
def render(request, painter, pose):
    raise RuntimeError('optional renderer failed')
def stamp(request):
    return RigService(request.require_document()).create_bone((200, 200), (290, 200))
def register(context):
    context.register('commands', 'org.gui.ui.stamp', 'Stamp', stamp)
    context.register('panels', 'org.gui.ui.panel', 'SDK panel', panel)
    context.register('inspectors', 'org.gui.ui.inspector', 'SDK inspector', panel)
    context.register('renderers', 'org.gui.ui.overlay', 'SDK overlay', render)
""")
    window = open_window(qtbot, tmp_path, [root])
    vm = window.viewmodel
    vm.enable_plugin("org.gui.ui", trust=True)
    adapter = window.plugin_workspace
    assert len(adapter.docks) == len(adapter.inspectors) == 1
    assert adapter.inspectors[0].text() == "No project"
    vm.new_project()
    assert adapter.inspectors[0].text() == vm.documents.project.name
    adapter.inspectors[0].request.run_command("org.gui.ui.stamp")
    assert len(vm.documents.project.scenes[0].skeletons[0].bones) == 2
    assert vm.playback.session.scene is vm.documents.project.scenes[0]
    assert len(vm.documents.history.undo_stack) == 1
    window.viewport.grab()
    assert adapter.failed_renderers == {"org.gui.ui.overlay"}
    count = len(vm.plugins.diagnostics)
    window.viewport.grab()
    assert len(vm.plugins.diagnostics) == count
    vm.plugins.disable("org.gui.ui")
    assert not adapter.docks and not adapter.inspectors
    assert window.viewport.extension_overlay is None
    window.close()


def test_isolated_job_runs_off_gui_thread_and_returns_data(qtbot, tmp_path):
    """Qt continues processing timers while a child job works against a project snapshot."""
    root = generate_plugin(tmp_path / "job", "org.gui.job")
    manifest = root / "rigora-plugin.json"
    data = json.loads(manifest.read_text())
    data["capabilities"] = ["batch_jobs"]
    manifest.write_text(json.dumps(data))
    (root / "__init__.py").write_text("""import time
def job(request):
    time.sleep(0.3)
    return {'project': request.require_document().project.name}
def register(context):
    context.register('batch_jobs', 'org.gui.job.count', 'Count', job)
""")
    window = open_window(qtbot, tmp_path, [root])
    vm = window.viewmodel
    vm.new_project()
    vm.enable_plugin("org.gui.job", trust=True)
    window.show_plugins()
    dialog = window.plugin_dialog
    original = vm.documents.project
    ticks = []
    QTimer.singleShot(20, lambda: ticks.append(True))
    dialog.developer_console.setChecked(True)
    dialog.run_button.click()
    assert dialog.jobs
    qtbot.waitUntil(lambda: not dialog.jobs, timeout=10000)
    assert ticks and json.loads(dialog.output.toPlainText()) == {"project": original.name}
    assert vm.documents.project is original
    window.close()
