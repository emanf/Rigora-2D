"""Spring group tree commands, resizable disclosures and transient preview region ownership."""

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from test_editor_tool_lifecycle_gui import make_chain
from test_workspace_redesign_gui import editor as editor

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.documents import DocumentService
from rigora.application_services.dynamics import DynamicsService
from rigora.application_services.rigging import RigService
from rigora.engine.springs import SpringSimulation

pytestmark = pytest.mark.gui


def group_row(dialog, name):
    """Find a fresh tree node after a project command replaces its previous revision."""
    return next(
        dialog.groups.topLevelItem(i)
        for i in range(dialog.groups.topLevelItemCount())
        if dialog.groups.topLevelItem(i).text(0) == name
    )


@pytest.mark.parametrize("selected_index, include_children", [(0, True), (1, True), (0, False)])
def test_assignment_includes_selected_bone_and_optional_descendants(
    editor, selected_index, include_children
):
    """The selected root or child appears in its group; including children is additive."""
    window, vm = editor, editor.viewmodel
    bones = make_chain(window)
    window.show_spring_editor()
    dialog = window.spring_editor
    dialog.add_group_button.click()
    dialog.include_children.setChecked(include_children)
    vm.rig.select(bones[selected_index])
    before, count = vm.documents.project, len(vm.documents.history.undo_stack)
    expected = bones[selected_index:] if include_children else (bones[selected_index],)
    assert dialog.selected_bones() == expected and dialog.assign_button.isEnabled()
    dialog.assign_button.click()
    assert not vm.animation_editor.error
    assert dialog.group_members() == expected
    row = group_row(dialog, "Group 1")
    assert {
        row.child(i).data(0, Qt.ItemDataRole.UserRole + 1) for i in range(row.childCount())
    } == set(expected)
    rules = [c for c in DynamicsService(vm.documents).scene.constraints if c.kind == "spring"]
    assert {c.owner_id for c in rules} == set(expected)
    if bones[0] in expected:
        assert next(c for c in rules if c.owner_id == bones[0]).extra["spring_object_root"]
    assert len(vm.documents.history.undo_stack) == count + 1
    vm.undo()
    assert vm.documents.project == before


def test_tree_assign_rename_remove_and_undo_keep_memberships(editor, tmp_path):
    """A real group tree selects stage bones and publishes portable single-step edits."""
    window, vm = editor, editor.viewmodel
    _, child, tip = make_chain(window)
    window.show_spring_editor()
    dialog = window.spring_editor
    vm.rig.select(child)
    dialog.preset("Rubbery")
    assert group_row(dialog, "Default").childCount() == 2
    dialog.add_group_button.click()
    assert dialog.group_name() == "Group 1" and not dialog.remove_group_button.isHidden()
    dialog.include_children.setChecked(False)
    vm.rig.select(child)
    steps = len(vm.documents.history.undo_stack)
    dialog.assign_button.click()
    assert len(vm.documents.history.undo_stack) == steps + 1
    assert set(dialog.group_members()) == {child}
    assert set(dialog.group_members("Default")) == {tip}
    assert group_row(dialog, "Group 1").child(0).text(0) == vm.rig.service.bone(child).name
    group_row(dialog, "Group 1").setText(0, "Hair")
    assert dialog.group_name() == "Hair" and dialog.group_members() == (child,)
    destination = tmp_path / "spring-groups.rigora"
    vm.documents.save(destination)
    reopened = DocumentService()
    reopened.open(destination)
    assert "Hair" in DynamicsService(reopened).group_names()
    assert (
        next(c for c in reopened.project.scenes[0].constraints if c.owner_id == child).extra[
            "spring_group"
        ]
        == "Hair"
    )
    vm.undo()
    assert "Group 1" in DynamicsService(vm.documents).group_names()
    dialog.groups.setCurrentItem(group_row(dialog, "Group 1").child(0))
    group_row(dialog, "Default").child(0).setSelected(True)
    assert set(vm.rig.selected) == {child, tip}
    assert dialog.selected_groups() == {"Default", "Group 1"}
    dialog.refresh()
    assert dialog.selected_groups() == {"Default", "Group 1"}
    dialog.unassign_button.click()
    assert not any(c.kind == "spring" for c in DynamicsService(vm.documents).scene.constraints)
    vm.undo()
    assert len(DynamicsService(vm.documents).scene.constraints) == 2
    parent = group_row(dialog, "Default")
    dialog.groups.setCurrentItem(parent.child(0))
    assert vm.rig.selected == (tip,) and dialog.group_name() == "Default"
    dialog.unassign_button.click()
    assert dialog.group_members("Default") == ()
    vm.undo()
    assert dialog.group_members("Default") == (tip,)
    dialog.groups.setCurrentItem(group_row(dialog, "Group 1"))
    baseline = vm.documents.project
    dialog.remove_group_button.click()
    assert "Group 1" not in DynamicsService(vm.documents).group_names()
    assert all(c.owner_id != child for c in DynamicsService(vm.documents).scene.constraints)
    vm.undo()
    assert vm.documents.project == baseline


def test_disclosures_and_resizable_five_row_tree_are_view_only(editor, qtbot):
    """Collapsing sections and resizing the list preserve history and stop hidden illustrations."""
    window, vm = editor, editor.viewmodel
    make_chain(window)
    window.show_spring_editor()
    dialog = window.spring_editor
    qtbot.wait(20)
    baseline = vm.documents.project
    assert dialog.groups.height() >= dialog.groups.minimumHeight()
    assert dialog.groups.minimumHeight() >= 5 * (dialog.groups.fontMetrics().height() + 14)
    assert dialog.group_splitter.handle(1).toolTip() == "Drag to resize the group list"
    dialog.group_splitter.setSizes([280, 400])
    height = dialog.groups.height()
    assert height > 210
    dialog.presets_toggle.click()
    assert not dialog.presets_body.isVisible() and not dialog.example_timer.isActive()
    dialog.properties_toggle.click()
    assert not dialog.properties_body.isVisible()
    assert dialog.play_button.isVisible() and dialog.loop_button.isVisible()
    assert dialog.preview_region.isVisible()
    assert dialog.play_button.y() == dialog.loop_button.y()
    assert not hasattr(dialog, "progress") and not hasattr(dialog, "preview_button")
    dialog.presets_toggle.click()
    assert dialog.presets_body.isVisible() and dialog.example_timer.isActive()
    dialog.properties_toggle.click()
    assert dialog.properties_body.isVisible()
    assert vm.documents.project is baseline
    height = dialog.groups.height()
    dialog.close()
    assert vm.preferences.data["spring_group_list_height"] == height
    window.show_spring_editor()
    assert window.spring_editor.groups.height() == pytest.approx(height, abs=3)


def test_body_face_preview_filters_live_rules_and_releases_scope(editor, monkeypatch):
    """Explicit face bones have real scoped physics; closing restores normal all-rig preview."""
    window, vm = editor, editor.viewmodel
    _, body, face = make_chain(window)
    RigService(vm.documents).update(face, group="Face")
    DynamicsService(vm.documents).configure((body, face))
    vm.changed.emit()
    window.show_spring_editor()
    dialog = window.spring_editor
    baseline = vm.documents.project
    original = SpringSimulation.advance
    observed = []

    def advance(self, nodes, rules, dt):
        """Observe the real constraints passed to live simulation, without substituting physics."""
        observed.append({rule.owner_id for rule in rules})
        return original(self, nodes, rules, dt)

    monkeypatch.setattr(SpringSimulation, "advance", advance)
    dialog.preview_region.setCurrentIndex(1)
    assert window.rig_workspace.spring_scope == frozenset({face})
    assert vm.rig.selected == (face,) and observed[-1] == {face}
    dialog.preview_region.setCurrentIndex(0)
    assert face not in window.rig_workspace.spring_scope and observed[-1] == {body}
    assert vm.documents.project is baseline
    dialog.close()
    assert window.rig_workspace.spring_scope is None
    window.rig_workspace.begin_springs()
    assert observed[-1] == {body, face}
    window.rig_workspace.stop_springs()


def test_activation_custom_presets_display_and_background_group_bake(editor, qtbot):
    """Actual editor controls key groups, retain presets through Undo and bake on a worker."""
    window, vm = editor, editor.viewmodel
    root, child, tip = make_chain(window)
    animation = AnimationEditingService(vm.documents)
    animation.key(root, "transform.rotation", 0, 0)
    animation.key(root, "transform.rotation", 12, 50)
    animation.clip_settings(out_frame=24)
    window.show_spring_editor()
    dialog = window.spring_editor
    vm.rig.select(root)
    dialog.preset("Smooth")
    service = DynamicsService(vm.documents)
    baseline = vm.documents.project
    dialog.display_size.setValue(150)
    dialog.display_opacity.setValue(40)
    dialog.display_connections.setChecked(False)
    assert window.viewport.bone_display_size == 1.5
    assert window.viewport.bone_display_opacity == 0.4
    assert not window.viewport.bone_connections
    assert window.viewport.spring_highlight == {root, child, tip}
    assert vm.documents.project is baseline
    dialog.custom_presets.setCurrentText("Gentle test")
    dialog.save_custom_preset()
    assert "Gentle test" in service.scene.extra["spring_presets"]
    vm.undo()
    assert dialog.custom_presets.findText("Gentle test") == -1
    vm.redo()
    assert dialog.custom_presets.findText("Gentle test") >= 0
    vm.playback.seek(12)
    dialog.key_activation(False)
    assert not vm.documents.animation.evaluator.active_springs(12)
    dialog.master_key.setChecked(True)
    dialog.key_activation(True)
    assert any(t.property_path == "spring.master" for t in service.timeline.tracks)
    dialog.master_key.setChecked(False)
    dialog.key_activation(True)
    assert vm.documents.animation.evaluator.active_springs(12)
    source, before = service.clip.id, vm.documents.project
    dialog.bake_scope.setCurrentIndex(1)
    dialog.bake_tail.setValue(0)
    dialog.bake_button.click()
    assert dialog.bake_job is not None and not dialog.bake_button.isEnabled()
    qtbot.waitUntil(lambda: dialog.bake_job is None, timeout=15000)
    assert not vm.animation_editor.error
    assert service.clip.id != source and service.clip.extra["dynamics_bake"]
    assert not vm.documents.animation.evaluator.springs
    vm.undo()
    assert vm.documents.project == before
    output = Path("build/prompt-17-review")
    output.mkdir(parents=True, exist_ok=True)
    dialog.grab().save(str(output / "spring-editor.png"))
    dialog.close()
    assert not window.viewport.spring_colors and not window.viewport.spring_highlight
    assert window.viewport.bone_display_size == window.viewport.bone_display_opacity == 1


def test_activation_indicator_tracks_scrub_master_override_mixed_keys_and_undo(editor):
    """Visible checks separate sampled gates from effective physics at the current frame."""
    root, _, tip = make_chain(editor)
    vm = editor.viewmodel
    editor.show_spring_editor()
    dialog = editor.spring_editor
    vm.rig.select(root)
    dialog.preset("Smooth")
    assert dialog.activation_state.text() == "Spring: ON"
    assert dialog.activation_buttons[True].isChecked()
    vm.playback.seek(12)
    dialog.activation_buttons[False].click()
    assert dialog.activation_state.text() == "Spring: OFF"
    assert dialog.activation_buttons[False].isChecked()
    vm.playback.seek(6)
    assert dialog.activation_state.text() == "Spring: ON"
    assert dialog.activation_buttons[True].isChecked()
    vm.playback.seek(12)
    dialog.master_key.setChecked(True)
    assert dialog.activation_buttons[True].isChecked()
    dialog.activation_buttons[False].click()
    dialog.master_key.setChecked(False)
    dialog.activation_buttons[True].click()
    assert dialog.activation_buttons[True].isChecked()
    assert dialog.activation_state.text() == "Spring: OFF"
    assert "Group: ON" in dialog.activation_details.text()
    assert "Master: OFF" in dialog.activation_details.text()
    vm.undo()
    assert dialog.activation_buttons[False].isChecked()
    vm.redo()
    assert dialog.activation_buttons[True].isChecked()
    dialog.master_key.setChecked(True)
    dialog.activation_buttons[True].click()
    AnimationEditingService(vm.documents).key(tip, "spring.enabled", 12, 0)
    vm.changed.emit()
    dialog.master_key.setChecked(False)
    assert "Group: MIXED" in dialog.activation_details.text()
    assert dialog.activation_state.text() == "Spring: MIXED"
    assert not any(b.isChecked() for b in dialog.activation_buttons.values())
    before = vm.documents.project
    vm.playback.seek(6)
    dialog.master_key.setChecked(True)
    assert vm.documents.project is before
    output = Path("build/spring-state-review")
    output.mkdir(parents=True, exist_ok=True)
    dialog.grab().save(str(output / "activation.png"))
