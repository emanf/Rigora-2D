"""Spring playback does incremental work while retaining deterministic random seek geometry."""

from dataclasses import replace

import pytest

from rigora.application_services.animation import AnimationSession
from rigora.application_services.content_library import ContentService
from rigora.application_services.documents import DocumentService
from rigora.engine.evaluation import SceneEvaluator
from rigora.engine.springs import SpringSimulation, sample_springs
from rigora.infrastructure.effect_catalog import spring_presets


def test_template_playback_reuses_integer_ticks_without_fractional_or_seek_contamination(
    monkeypatch,
):
    """Forward work follows elapsed ticks; backward/loop/override samples retain exact geometry."""
    document = DocumentService()
    document.new()
    item = next(item for item in spring_presets() if item.name == "Long ponytail")
    ContentService(document).place(item, {}, position=(700, 450))
    scene = document.scene
    clip = replace(scene.clips[0], out_frame=240)
    scene = replace(scene, clips=(clip,))
    evaluator = SceneEvaluator(scene)
    calls = []
    advance = SpringSimulation.advance

    def counted(self, nodes, rules, dt):
        """Count integration work rather than relying on machine-specific timing assertions."""
        calls.append(dt)
        return advance(self, nodes, rules, dt)

    monkeypatch.setattr(SpringSimulation, "advance", counted)
    for frame in range(1, 91):
        evaluator.evaluate(frame)
    assert len(calls) <= 275  # 225 fixed ticks, one prime and 45 independent half ticks.
    calls.clear()
    for _ in range(20):
        evaluator.evaluate(90)
    assert not calls
    root = scene.skeletons[0].bones[0]
    overrides = {(root.id, "transform.rotation"): -65}
    evaluator.evaluate(89.9, overrides=overrides)
    for frame in (90.1, 90.4, 91, 0, 12.5, 170, 171, 90.5, 90, 0):
        pose = evaluator.evaluate(frame)
        raw = evaluator._spring_input(frame)
        expected, warnings = sample_springs(
            raw, evaluator.springs, frame, 0, scene.settings.fps, evaluator._spring_input
        )
        assert not pose.warnings and not warnings
        expected = evaluator.placed_library_rigs(evaluator.spring_output(expected, frame))
        for node in expected:
            assert pose.nodes[node.id].world_matrix == pytest.approx(node.world_matrix, abs=1e-10)
    fork = SceneEvaluator(scene)
    assert fork.spring_cursor is not evaluator.spring_cursor
    session = AnimationSession(scene)
    session.seek(90)
    scratch = session.fork()
    assert scratch.evaluator.nodes is session.evaluator.nodes
    assert scratch.evaluator.deformation is session.evaluator.deformation
    assert scratch.evaluator.spring_cursor is not session.evaluator.spring_cursor
    scratch.seek(12.5)
    assert session.playback.frame == 90
    assert session.evaluate(90.5).nodes == SceneEvaluator(scene).evaluate(90.5).nodes
