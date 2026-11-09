"""Dropped spring specimens retain Scene placement throughout live object movement."""

import time
from dataclasses import replace

import pytest
from test_object_workspace_redesign_gui import panel_editor as panel_editor

from rigora.application_services.characters import CharacterService
from rigora.application_services.content_library import ContentService
from rigora.application_services.scene_editing import SceneEditingService
from rigora.infrastructure.effect_catalog import spring_presets

pytestmark = pytest.mark.gui


@pytest.mark.parametrize("item", spring_presets(), ids=lambda item: item.name)
def test_spring_specimen_stays_at_dragged_scene_position_during_settling(panel_editor, item):
    """Compare actual live display geometry with the canonical pose before/after settling."""
    editor = panel_editor
    vm, doc = editor.viewmodel, editor.viewmodel.documents
    rig_id = ContentService(doc).place(item, {}, position=(700, 450))
    vm.changed.emit()
    owner = CharacterService(doc).scene_objects()[0]
    scene = SceneEditingService(doc)
    record = scene.record(owner)
    scene.update_records(
        {owner: replace(record, extra={**record.extra, "opacity": 0.5})}, "Set opacity"
    )
    vm.changed.emit()
    rig = next(r for r in doc.scene.skeletons if r.id == rig_id)
    root = next(b.id for b in rig.bones if not b.parent_id)
    vm.scene.select((owner,))
    baseline = doc.animation.pose.for_display().nodes[root].world_matrix[4:]
    vm.scene.begin_preview()
    workspace = editor.rig_workspace
    workspace.begin_springs()
    assert workspace.spring_timer.isActive()
    for dx, dy in ((60, 30), (120, 80), (-40, 50)):
        workspace.spring_clock = time.monotonic() - 1 / 60
        vm.scene.preview_transform(dx=dx, dy=dy)
        assert not vm.scene.error and vm.scene.preview is not None
        primary = vm.scene.preview.for_display()
        live = editor.viewport.pose
        assert live.nodes[root].world_matrix[4:] == pytest.approx(
            primary.nodes[root].world_matrix[4:], abs=1e-5
        )
        assert live.nodes[root].opacity == primary.nodes[root].opacity == 0.5
        assert live.nodes[root].world_matrix[4:] == pytest.approx(
            (baseline[0] + dx, baseline[1] + dy), abs=1e-5
        )
    vm.scene.finish_preview()
    expected = doc.animation.pose.for_display().nodes[root].world_matrix[4:]
    for _ in range(4):
        workspace.spring_clock = time.monotonic() - 1 / 60
        workspace.tick_springs()
        assert editor.viewport.pose.nodes[root].world_matrix[4:] == pytest.approx(expected)
    workspace.spring_input = time.monotonic() - 5
    workspace.tick_springs()
    assert editor.viewport.pose.nodes[root].world_matrix[4:] == pytest.approx(expected)


def test_skinned_character_keeps_one_placement_during_live_spring_drag(panel_editor):
    """The rig-only placement fix must preserve skinning's separate bind-space handling."""
    from rigora.application_services.character_creation import (
        CharacterCreationService,
        build_character,
    )
    from rigora.application_services.dynamics import DynamicsService
    from rigora.domain.character_recipe import CharacterRecipe

    editor = panel_editor
    vm, doc = editor.viewmodel, editor.viewmodel.documents
    owner = CharacterCreationService(doc).create(
        build_character(CharacterRecipe(design_id="sumi", name="Sumi", motions=()))
    )
    doc.set_animation_context(None)
    bones = doc.scene.skeletons[0].bones
    tail = next(b.id for b in bones if b.name == "tail")
    root = next(b.id for b in bones if b.parent_id is None)
    DynamicsService(doc).configure((tail,), gravity=100)
    vm.changed.emit()
    vm.scene.select((owner,))
    vm.scene.begin_preview()
    workspace = editor.rig_workspace
    workspace.begin_springs()
    for dx, dy in ((80, 40), (-60, 80)):
        workspace.spring_clock = time.monotonic() - 1 / 60
        vm.scene.preview_transform(dx=dx, dy=dy)
        assert not vm.scene.error
        primary = vm.scene.preview.for_display()
        live = editor.viewport.pose
        assert live.nodes[root].world_matrix[4:] == pytest.approx(
            primary.nodes[root].world_matrix[4:]
        )
        assert live.nodes[owner] == primary.nodes[owner]
        assert live.meshes and all(mesh.positions for mesh in live.meshes.values())
    workspace.stop_springs()
    vm.scene.cancel_preview()
