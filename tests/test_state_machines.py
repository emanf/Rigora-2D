"""Runtime state conditions and live crossfades preserve saved source actions and edit history."""

import pytest
from test_object_scene_actions import composition

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.state_machines import StateMachinePreview, StateMachineService


def machine_document():
    """Author two simple action poses and a reversible numeric-input state machine."""
    doc, chars, _, root, a, _ = composition()
    part = chars.mesh(a).object_id
    doc.set_animation_context(root, frozenset(chars.members(root)))
    idle = chars.new_motion(root, "Idle")
    edit = AnimationEditingService(doc)
    edit.key(part, "transform.rotation", 0, 20)
    active = chars.new_motion(root, "Active")
    edit.key(part, "transform.rotation", 0, 80)
    StateMachineService(doc).define(
        root,
        [dict(name="Idle", clip=idle), dict(name="Active", clip=active)],
        [
            {
                "from": "Idle",
                "to": "Active",
                "parameter": "speed",
                "operator": ">",
                "value": 0.1,
                "blend": 10,
            },
            {
                "from": "Active",
                "to": "Idle",
                "parameter": "speed",
                "operator": "<=",
                "value": 0.1,
                "blend": 10,
            },
        ],
        {"speed": 0},
        "Idle",
    )
    return doc, root, part


def test_state_conditions_live_blends_and_runtime_inputs_leave_authoring_untouched(tmp_path):
    """State changes blend in the same evaluator; resets reproduce the same output."""
    doc, root, part = machine_document()
    source, history, frame = doc.project, len(doc.history.undo_stack), doc.cursor_frame
    preview = StateMachinePreview(doc, root)
    assert preview.pose().nodes[part].local.rotation == pytest.approx(20)
    preview.set_parameter("speed", 1)
    assert preview.advance(5 / doc.scene.settings.fps).nodes[part].local.rotation == pytest.approx(
        50
    )
    assert preview.current == "Active"
    assert preview.advance(5 / doc.scene.settings.fps).nodes[part].local.rotation == pytest.approx(
        80
    )
    preview.set_parameter("speed", 0)
    preview.advance(0)
    assert preview.advance(5 / doc.scene.settings.fps).nodes[part].local.rotation == pytest.approx(
        50
    )
    assert (
        doc.project is source
        and len(doc.history.undo_stack) == history
        and doc.cursor_frame == frame
    )
    doc.save(tmp_path / "machine.rigora")
    doc.open(doc.path)
    assert StateMachinePreview(doc, root).pose().nodes[part].local.rotation == pytest.approx(20)
