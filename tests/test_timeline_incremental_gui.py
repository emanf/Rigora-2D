"""Value-only edits preserve native channel rows while refreshing dope-sheet data."""

import json
import statistics
import time
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from test_roots_soft_drag_gui import editor as editor

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.appearance import AppearanceService
from rigora.application_services.scene_editing import SceneEditingService

pytestmark = pytest.mark.gui


def test_value_edits_retain_rows_selection_and_refresh_keys(editor):
    doc, timeline = editor.viewmodel.documents, editor.timeline
    shapes = AppearanceService(doc)
    mesh = shapes.create_shape("rectangle", 100, 100, 80, 80)
    owner = shapes.mesh(mesh).object_id
    animation = AnimationEditingService(doc)
    animation.key(owner, "transform.x", 0, 100)
    editor.viewmodel.changed.emit()
    row = next(iter(timeline._groups.values()))
    row.setSelected(True)
    row.setExpanded(True)
    timeline.expansion_changed()
    before = row
    animation.key(owner, "transform.x", 20, 300)
    editor.viewmodel.changed.emit()
    assert next(iter(timeline._groups.values())) is before
    assert row.isSelected() and row.isExpanded()
    assert "2 keys" in row.toolTip(0)
    assert {key.frame for key in timeline.dope.source.values()} == {0, 20}
    SceneEditingService(doc).transform((owner,), dx=25)
    editor.viewmodel.changed.emit()
    assert next(iter(timeline._groups.values())) is before
    animation.track_settings(timeline.row_tracks(row)[0], locked=True, visible=True)
    editor.viewmodel.changed.emit()
    assert next(iter(timeline._groups.values())).checkState(1) == Qt.CheckState.Checked


def test_timeline_refresh_measurement(editor):
    """Compare identical edit workloads with incremental and forced structural rebuilding."""
    doc, timeline = editor.viewmodel.documents, editor.timeline
    shapes = AppearanceService(doc)
    animation = AnimationEditingService(doc)
    owners = []
    for i in range(16):
        mesh = shapes.create_shape("rectangle", 50 + i * 10, 100, 40, 60)
        owner = shapes.mesh(mesh).object_id
        owners.append(owner)
        for prop in ("transform.x", "transform.y", "transform.rotation", "opacity"):
            animation.key(owner, prop, 0, 1)
            animation.key(owner, prop, 30, 2)
    editor.viewmodel.changed.emit()
    values = {}
    for mode in ("forced_rebuild", "incremental"):
        samples = []
        for i in range(22):
            animation.key(owners[0], "transform.x", 30, i + 2)
            if mode == "forced_rebuild":
                timeline._source_key = None
            start = time.perf_counter()
            timeline.refresh()
            if i:
                samples.append((time.perf_counter() - start) * 1000)
        values[mode] = {"median_ms": statistics.median(samples), "max_ms": max(samples)}
    output = Path("build/improvements-timeline.json")
    output.write_text(json.dumps(values, indent=2), encoding="utf-8")
    print(values)
