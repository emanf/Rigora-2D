"""Live physics and canonical animation publish one consistent object pose per interaction."""

import time

import pytest
from test_character_objects_gui import editor as editor
from test_timeline_title_gui import add_animal

from rigora.application_services.dynamics import DynamicsService

pytestmark = pytest.mark.gui


def spring_character(editor, qtbot):
    """Use a real premade rig, original artwork and the first-bone Spring workflow."""
    owner = add_animal(editor)
    vm = editor.viewmodel
    vm.documents.set_animation_context(None)
    service = DynamicsService(vm.documents)
    bones = service.scene.skeletons[0].bones
    root = next(b.id for b in bones if b.parent_id is None)
    tail = next(b.id for b in bones if b.name == "tail")
    service.assign_group((root, tail), group="Body", frequency=2, damping=0.3, gravity=400)
    vm.changed.emit()
    qtbot.waitUntil(
        lambda: len(editor.viewport.artwork.images) >= len(vm.documents.project.assets),
        timeout=15000,
    )
    vm.scene.select((owner,))
    editor.viewport.fit_canvas()
    return owner, root, tail


def test_pilot_pose_takes_over_live_springs_without_alternating_to_rest(editor, qtbot):
    """A live solver left by stage selection cannot overwrite an in-progress Pilot take."""
    owner, _, _ = spring_character(editor, qtbot)
    editor.show_motion_pilot()
    tool, workspace = editor.motion_pilot, editor.rig_workspace
    tool.arm(False)
    workspace.begin_springs()
    assert workspace.spring_timer.isActive()
    tool.model.start((0, 0), (0, 0))
    tool.timer.stop()
    tool.model.capture(8, (100, 50))
    expected = editor.viewmodel.animation_editor.preview_pose
    assert expected is not None and not expected.warnings
    for _ in range(4):
        workspace.tick_springs()
        assert editor.viewport.pose.nodes[owner] == expected.nodes[owner]
        assert editor.viewport.pose.meshes == expected.meshes
        assert not workspace.spring_timer.isActive()
    workspace.begin_springs()
    assert not workspace.spring_timer.isActive()
    assert editor.viewport.pose.nodes[owner] == expected.nodes[owner]
    editor.viewport.grab()
    assert editor.viewport._artwork_layer is not None
    assert not editor.viewport._artwork_layer.toImage().isNull()
    tool.close()


def test_scene_movement_keeps_one_live_pose_in_scene_space_and_preserves_visible_parts(
    editor, qtbot, monkeypatch
):
    """Drag updates feed one solver, retain placement/occlusion and keep real artwork renderable."""
    owner, root, _ = spring_character(editor, qtbot)
    vm, workspace = editor.viewmodel, editor.rig_workspace
    vm.scene.begin_preview()
    workspace.begin_springs()
    published = []
    original = editor.viewport.set_pose

    def capture(pose):
        """Observe actual presentation snapshots rather than replacing evaluation or rendering."""
        published.append(pose)
        original(pose)

    monkeypatch.setattr(editor.viewport, "set_pose", capture)
    for x, y in ((80, 40), (-60, 80), (150, -30)):
        published.clear()
        workspace.spring_clock = time.monotonic() - 1 / 60
        vm.scene.preview_transform(dx=x, dy=y)
        primary = vm.scene.preview
        assert not vm.scene.error and primary is not None
        assert len(published) == 1
        live = editor.viewport.pose
        assert not live.warnings and live.meshes
        assert live.nodes[owner] == primary.nodes[owner]
        assert live.nodes[root].world_matrix[4:] == pytest.approx(
            primary.for_display().nodes[root].world_matrix[4:]
        )
        assert {k for k, n in live.nodes.items() if n.visible} == {
            k for k, n in primary.nodes.items() if n.visible
        }
        assert all(mesh.positions for mesh in live.meshes.values())
    editor.viewport.grab()
    assert editor.viewport._artwork_layer is not None
    workspace.stop_springs()
    vm.scene.cancel_preview()
