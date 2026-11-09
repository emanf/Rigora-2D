"""Exercise real vector playback and queued recipe changes through Qt's event loop."""

import gc
import time

import pytest
from PySide6.QtCore import Qt, QThread
from test_character_wizard_gui import creator
from test_object_scene_actions_gui import readable_offscreen_fonts as readable_offscreen_fonts
from test_roots_soft_drag_gui import editor as editor

from rigora.domain.character_recipe import MOTION_CHOICES
from rigora.domain.creator_options import choose
from rigora.presentation.garbage_collection import GuiGarbageCollector

pytestmark = pytest.mark.gui


def test_creator_playback_switching_and_teardown(editor, qtbot):
    """Paint consecutive source actions, edit appearance, and close during a rebuild safely."""
    wizard = creator(editor, qtbot)
    collector = GuiGarbageCollector(wizard)
    qtbot.mouseClick(
        wizard.grids["Animations"].viewport(),
        Qt.MouseButton.LeftButton,
        pos=wizard.grids["Animations"].visualItemRect(wizard.grids["Animations"].item(1)).center(),
    )
    wizard.play.click()
    qtbot.waitUntil(lambda: wizard.timer.isActive(), timeout=30000)
    for name in MOTION_CHOICES * 2:
        wizard.select_motion(name)
        assert wizard.timer.isActive() and wizard.play.isChecked()
        assert wizard.model.preview.animation.playback.loop
        session = wizard.model.preview.animation
        for _ in range(3):
            session.seek(session.playback.range.end - 0.1)
            wizard._time = time.monotonic() - 0.1
            wizard.tick()
            assert session.pose.frame < session.playback.range.end / 2
        for _ in range(8):
            wizard._time = time.monotonic() - 0.1
            wizard.tick()
            wizard.preview.repaint()
            qtbot.wait(1)
        gc.collect()
    wizard.set_recipe(choose(wizard.recipe, "Clothing", "jacket"))
    wizard.play.setChecked(True)
    wizard.toggle_play(True)
    qtbot.waitUntil(lambda: wizard.timer.isActive(), timeout=30000)
    assert QThread.currentThread() == wizard.thread()
    wizard.set_recipe(choose(wizard.recipe, "Clothing", "hoodie"))
    wizard.toggle_play(True)
    qtbot.waitUntil(lambda: wizard.model.busy, timeout=5000)
    wizard.close()
    collector.close()
    qtbot.wait(100)


def test_cyclic_wrapper_collection_stays_on_gui_thread(qapp, qtbot):
    """Worker allocations cannot trigger finalizers for unreachable Qt wrapper cycles."""
    from concurrent.futures import ThreadPoolExecutor

    collector = GuiGarbageCollector(qapp)
    finalized = []

    class Cycle:
        """Record the collection thread without retaining a reference to the specimen."""

        def __init__(self):
            self.cycle = self

        def __del__(self):
            finalized.append(QThread.currentThread())

    try:
        Cycle()
        with ThreadPoolExecutor(1) as pool:
            pool.submit(lambda: [[i] for i in range(5000)]).result()
        assert not finalized and not gc.isenabled()
        gc.collect()
        assert finalized == [qapp.thread()]
    finally:
        collector.close()
