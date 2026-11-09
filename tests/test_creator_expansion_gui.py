"""Expanded cards and source actions remain usable in the production Creator window."""

import json
import statistics
import time
from dataclasses import replace
from pathlib import Path

import pytest
from test_object_workspace_redesign_gui import panel_editor as panel_editor

from rigora.domain.character_recipe import MOTION_CHOICES, RUN_ACTIONS
from rigora.domain.creator_options import COMPONENT_CHOICES, choose
from rigora.presentation.widgets.character_wizard import CharacterWizard

pytestmark = pytest.mark.gui


def test_expanded_creator_cards_build_and_play_without_changing_the_scene(panel_editor, qtbot):
    window = panel_editor
    baseline = window.viewmodel.documents.project
    wizard = CharacterWizard(window)
    qtbot.addWidget(wizard)
    wizard.show()

    def ready():
        return (
            wizard.model.ready == wizard.recipe
            and not wizard.model.busy
            and wizard.model.cards_current()
        )

    qtbot.waitUntil(ready, timeout=90000)
    for category in ("Hands", "Eyes", "Pants", "Shoes", "Ties", "Glasses", "Hair"):
        grid = wizard.grids[category]
        assert grid.count() == len(COMPONENT_CHOICES[category])
        assert all(not grid.item(i).icon().isNull() for i in range(grid.count()))
    recipe = wizard.recipe
    for category, name in (
        ("Headwear", "cap"),
        ("Glasses", "cat eye"),
        ("Hands", "Fist"),
        ("Eyes", "almond"),
        ("Pants", "cargo trousers"),
        ("Shoes", "high tops"),
        ("Ties", "long scarf"),
        ("Hair", "double curl"),
    ):
        recipe = choose(recipe, category, name)
    wizard.set_recipe(replace(recipe, alternatives={"Hands": ("Open", "Fist"), "Eyes": ("wide",)}))
    qtbot.waitUntil(ready, timeout=90000)
    for action in MOTION_CHOICES:
        wizard.select_motion(action)
        session = wizard.model.preview.animation
        assert session.evaluator.clip.name == action
        pose = session.evaluate(session.playback.range.end * 0.45)
        assert not pose.warnings
        wizard.preview.set_pose(pose)
        wizard.preview.repaint()
    assert window.viewmodel.documents.project is baseline
    output = Path("build/creator-review")
    output.mkdir(exist_ok=True)
    wizard.grab().save(str(output / "creator-expanded-window.png"))
    wizard.close()


def test_creator_action_preview_frame_times(panel_editor, qtbot):
    """Measure actual playback plus vector repaint for each changed performance, offscreen."""
    wizard = CharacterWizard(panel_editor)
    qtbot.addWidget(wizard)
    wizard.show()
    qtbot.waitUntil(
        lambda: wizard.model.ready == wizard.recipe and not wizard.model.busy, timeout=90000
    )
    timings = {}
    for action in ("Walk", *RUN_ACTIONS, "Jump"):
        wizard.select_motion(action)
        wizard.play.setChecked(True)
        wizard.model.preview.animation.play()
        values = []
        for i in range(49):
            wizard._time = time.monotonic() - 1 / 30
            start = time.perf_counter()
            wizard.tick()
            wizard.preview.repaint()
            if i:
                values.append((time.perf_counter() - start) * 1000)
        timings[action] = {
            "samples": len(values),
            "median_ms": statistics.median(values),
            "p95_ms": sorted(values)[45],
            "max_ms": max(values),
        }
        wizard.play.setChecked(False)
    output = Path("build/creator-review")
    output.mkdir(exist_ok=True)
    (output / "run-variant-playback.json").write_text(
        json.dumps(timings, indent=2), encoding="utf-8"
    )
    print(json.dumps(timings))
    wizard.close()
