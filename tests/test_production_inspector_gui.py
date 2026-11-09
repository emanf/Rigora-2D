"""Actual profiler/proxy controls and background project diagnostics."""

import pytest
from test_roots_soft_drag_gui import editor as editor

from rigora.application_services.appearance import AppearanceService
from rigora.application_services.diagnostics import inspect_project
from rigora.application_services.rendering import svg_frame
from rigora.domain.entities import Constraint, SceneObject

pytestmark = pytest.mark.gui


def test_profiler_proxy_changes_viewport_pixels_but_never_originals_or_exports(editor, qtbot):
    """Half-quality tiles are genuinely smaller; the renderer and project remain full-quality."""
    vm, viewport = editor.viewmodel, editor.viewport
    doc = vm.documents
    key = AppearanceService(doc).create_shape("ellipse", 500, 300, 160, 200)
    vm.changed.emit()
    qtbot.waitUntil(lambda: bool(viewport.artwork.vectors), timeout=10000)
    original, exported = doc.project, svg_frame(doc, 0)
    editor.command_actions["production_inspector"].trigger()
    dialog = editor.production_inspector
    qtbot.addWidget(dialog)
    dialog.clear_cache()
    viewport.grab()
    assert viewport._mesh_layers
    full = {k: v.tile.width() * v.tile.height() for k, v in viewport._mesh_layers.items()}
    dialog.quality.setCurrentIndex(dialog.quality.findData(0.5))
    viewport.grab()
    half = {k: v.tile.width() * v.tile.height() for k, v in viewport._mesh_layers.items()}
    assert key in full and key in half and half[key] < full[key] * 0.4
    assert doc.project is original and svg_frame(doc, 0) == exported
    vm.playback.seek(0)
    vm.playback.seek(0)
    assert vm.playback.session.pose_cache.hits > 0
    dialog.refresh()
    assert "Evaluation:" in dialog.metrics.text() and "Frame cache:" in dialog.metrics.text()
    assert viewport.profile_paint
    dialog.close()
    assert not viewport.profile_paint and not dialog.timer.isActive()
    editor.command_actions["production_inspector"].trigger()
    assert dialog.timer.isActive()


def test_project_diagnostics_find_real_evaluation_errors_and_reject_stale_navigation(editor, qtbot):
    """Unsupported rules are surfaced by the shared evaluator rather than a hardcoded checklist."""
    vm, doc = editor.viewmodel, editor.viewmodel.documents
    obj = SceneObject(name="Broken rule owner")
    rule = Constraint(owner_id=obj.id, kind="missing_plugin_solver", name="Missing behavior")
    doc.add_entities(doc.scene.id, {"objects": (obj,), "constraints": (rule,)})
    vm.changed.emit()
    original, history = doc.project, len(doc.history.undo_stack)
    issues = inspect_project(doc)
    assert any("Missing behavior" in issue.message for issue in issues)
    assert doc.project is original and len(doc.history.undo_stack) == history
    editor.command_actions["production_inspector"].trigger()
    dialog = editor.production_inspector
    qtbot.addWidget(dialog)
    dialog.scan()
    qtbot.waitUntil(lambda: dialog.job is None, timeout=10000)
    assert dialog.issues.count() > 0 and dialog.scan_button.isEnabled()
    doc.add_entities(doc.scene.id, {"objects": (SceneObject(name="Changed"),)})
    dialog.select_issue(dialog.issues.item(0))
    assert "changed" in dialog.note.text()
