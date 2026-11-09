"""Measure real creator selection and vector playback before accepting responsiveness changes."""

import json
import threading
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QTimer
from test_character_wizard_gui import creator, select_design
from test_roots_soft_drag_gui import editor as editor

from rigora.domain.character_recipe import MOTION_CHOICES
from rigora.presentation.garbage_collection import GuiGarbageCollector

pytestmark = pytest.mark.gui


def test_creator_motion_selection_and_playback_responsiveness(editor, qtbot, monkeypatch):
    """Exercise actual preparation, action changes and vector paint with an event-loop heartbeat."""
    wizard = creator(editor, qtbot)
    collector = GuiGarbageCollector(wizard)
    destination = editor.viewmodel.documents.project
    gaps = []
    stamps = []
    stages = []
    from rigora.presentation.viewmodels import character_wizard

    original = character_wizard.build_character

    def build(*args, **kwargs):
        """Record actual worker affinity and wall time around canonical assembly."""
        stages.append(("build-start", time.perf_counter(), threading.get_ident()))
        result = original(*args, **kwargs)
        stages.append(("build-end", time.perf_counter(), threading.get_ident()))
        return result

    monkeypatch.setattr(character_wizard, "build_character", build)
    previous = time.perf_counter()

    def heartbeat():
        """Measure the longest interval during which GUI events could not be processed."""
        nonlocal previous
        now = time.perf_counter()
        gaps.append((now - previous) * 1000)
        stamps.append(now)
        previous = now

    timer = QTimer(wizard)
    timer.timeout.connect(heartbeat)
    timer.start(10)
    start = time.perf_counter()
    select_design(wizard, "Little")
    qtbot.waitUntil(
        lambda: wizard.model.ready == wizard.recipe and not wizard.model.busy,
        timeout=60000,
    )
    wizard.select_motion("Walk")
    wizard.play.click()
    assert not wizard.model.error
    preparation = time.perf_counter() - start
    qtbot.wait(600)
    switches, paints, evaluations = [], [], []
    for name in ("Run", "Idle", "Walk", "Walk"):
        start = time.perf_counter()
        wizard.select_motion(name)
        switches.append((time.perf_counter() - start) * 1000)
        wizard.timer.stop()
        session = wizard.model.preview.animation
        full = session.evaluate(session.playback.range.end * 0.3)
        visible = session.evaluate(session.playback.range.end * 0.3, visible_only=True)
        assert visible.nodes == full.nodes and not visible.warnings
        assert visible.meshes == {
            key: m for key, m in full.meshes.items() if full.nodes[m.object_id].visible
        }
        assert len(visible.meshes) < len(full.meshes)
        for _ in range(3):
            wizard._time = time.monotonic() - 1 / 24
            start = time.perf_counter()
            wizard.tick()
            evaluations.append((time.perf_counter() - start) * 1000)
            start = time.perf_counter()
            wizard.preview.repaint()
            paints.append((time.perf_counter() - start) * 1000)
        qtbot.wait(1)
    timer.stop()
    wizard.play.click()
    preview = wizard.model.preview
    images = wizard.model.images
    filters = []
    for included in (False, True):
        start = time.perf_counter()
        wizard.update_recipe(motions=MOTION_CHOICES if included else ())
        wizard.select_motion("Walk")
        qtbot.waitUntil(
            lambda: wizard.model.ready == wizard.model.recipe and not wizard.model.busy,
            timeout=5000,
        )
        filters.append((time.perf_counter() - start) * 1000)
        assert wizard.model.preview is preview and wizard.model.images is images
        payload = json.loads(wizard.model.built.files["character.json"])
        assert {c["name"] for c in payload["scenes"][0]["clips"]} == (
            set(MOTION_CHOICES) if included else set()
        )
        assert {c.name for c in preview.project.scenes[0].clips} == set(MOTION_CHOICES)
    assert len(stages) == 2 and stages[0][2] != threading.get_ident()
    assert editor.viewmodel.documents.project is destination
    assert 0 < wizard.timer.interval() <= round(1000 / preview.animation.playback.range.fps)
    assert wizard.preview.artwork.vectors
    assert max(gaps) < 750
    assert max(switches) < 250
    output = Path("build/creator-preview-review")
    output.mkdir(exist_ok=True)
    metrics = {
        "main_thread": threading.get_ident(),
        "stages": stages,
        "long_gaps": [(g, t) for g, t in zip(gaps, stamps, strict=True) if g > 100],
        "prepare_seconds": preparation,
        "max_heartbeat_gap_ms": max(gaps),
        "switch_ms": switches,
        "evaluation_ms": evaluations,
        "paint_ms": paints,
        "inclusion_filter_ms": filters,
    }
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(metrics)
    wizard.close()
    collector.close()
