"""Real visible preset releases and explicit driver clips on otherwise stationary rigs."""

import math
import time

import pytest
from test_editor_tool_lifecycle_gui import make_chain
from test_workspace_redesign_gui import editor as editor

from rigora.application_services.dynamics import SPRING_PRESETS, DynamicsService
from rigora.domain.geometry import transform_point


@pytest.mark.gui
@pytest.mark.parametrize("name", tuple(SPRING_PRESETS))
def test_preset_release_visibly_moves_static_chain_without_authored_motion(editor, name):
    """Every preset produces visible real deformation while roots and attachments stay intact."""
    window, vm = editor, editor.viewmodel
    root, child, tip = make_chain(window)
    window.show_spring_editor()
    dialog = window.spring_editor
    before = vm.documents.animation.pose
    steps = len(vm.documents.history.undo_stack)
    dialog.preset(name)
    assert not vm.animation_editor.error
    actual = window.viewport.pose
    rest_tip = transform_point(before.nodes[tip].world_matrix, before.nodes[tip].length, 0)
    moved_tip = transform_point(actual.nodes[tip].world_matrix, actual.nodes[tip].length, 0)
    assert math.dist(rest_tip, moved_tip) > 15, name
    assert DynamicsService(vm.documents).has_object_root(root)
    assert actual.nodes[root].world_matrix[4:] == before.nodes[root].world_matrix[4:]
    assert len(vm.documents.history.undo_stack) == steps + 1
    assert not vm.documents.project.scenes[0].timelines
    for key in (child, tip):
        node = actual.nodes[key]
        parent = actual.nodes[node.parent_id]
        assert node.world_matrix[4:] == pytest.approx(
            transform_point(parent.world_matrix, parent.length, 0)
        )
    for _ in range(8):
        window.rig_workspace.spring_clock = time.monotonic() - 1 / 60
        window.rig_workspace.tick_springs()
    assert window.viewport.pose.nodes[child].world_matrix != actual.nodes[child].world_matrix
    assert len(vm.documents.history.undo_stack) == steps + 1


@pytest.mark.gui
def test_motion_test_button_uses_shared_repeat_and_is_one_undo_step(editor):
    """Explicit test motion creates a real editable clip and releases the live spring timer."""
    window, vm = editor, editor.viewmodel
    root, _, tip = make_chain(window)
    window.show_spring_editor()
    dialog = window.spring_editor
    dialog.preset("Rubbery")
    before, steps = vm.documents.project, len(vm.documents.history.undo_stack)
    dialog.motion_test_button.click()
    assert not vm.animation_editor.error
    assert vm.playback.session.playback.is_playing and vm.playback.session.playback.loop
    assert not window.rig_workspace.spring_timer.isActive()
    assert len(vm.documents.history.undo_stack) == steps + 1
    assert vm.documents.animation.evaluator.clip.name == "Spring motion test"
    poses = [vm.documents.animation.evaluate(t) for t in (0, 6, 12, 24, 45)]
    driver = next(b.id for b in vm.documents.scene.skeletons[0].bones if b.extra.get("rig_root"))
    assert (
        max(p.nodes[driver].world_matrix[4] for p in poses)
        - min(p.nodes[driver].world_matrix[4] for p in poses)
        > 20
    )
    assert len({p.nodes[tip].world_matrix for p in poses}) == len(poses)
    vm.undo()
    assert vm.documents.project == before


def test_motion_test_preserves_source_clip_and_uses_real_spring_response():
    """The driver uses Bézier keys; existing clips and rest bones stay unchanged."""
    from test_dynamics import animated_chain

    doc, root, tip = animated_chain()
    service = DynamicsService(doc)
    service.configure((tip,), frequency=1.6, damping=0.14)
    before, original = doc.project, service.clip
    service.motion_test((root, tip))
    assert service.clip.id != original.id
    assert service.scene.clips[0] == original
    assert service.scene.skeletons == before.scenes[0].skeletons
    assert all(k.interpolation == "bezier" for t in service.timeline.tracks for k in t.keyframes)
    lags = []
    for frame in range(91):
        pose = doc.animation.evaluate(frame)
        node = pose.nodes[tip]
        target = pose.spring_targets[tip]
        lags.append(
            abs(
                math.degrees(
                    math.atan2(node.world_matrix[1], node.world_matrix[0])
                    - math.atan2(target.world_matrix[1], target.world_matrix[0])
                )
            )
        )
    assert max(lags) > 5
    doc.undo()
    assert doc.project == before
