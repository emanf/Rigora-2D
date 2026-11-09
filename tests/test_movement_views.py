"""Deterministic direction switching, explicit view priority and recorded head-turn hysteresis."""

from dataclasses import replace

import pytest

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.documents import DocumentService
from rigora.application_services.facial import FaceService
from rigora.application_services.game_authoring import GameAuthoringService
from rigora.application_services.meshes import MeshService
from rigora.application_services.object_views import ObjectViewsService
from rigora.application_services.tracking import TrackingSample, TrackingTake
from rigora.domain.entities import Group, SceneObject
from rigora.domain.object_views import VIEW_SLOTS
from rigora.engine.evaluation import SceneEvaluator


def scene_views(face=False, document=None):
    """Create real view-owned scene records without depending on the generated character catalog."""
    doc = document or DocumentService()
    if document is None:
        doc.new()
    key = FaceService(doc).create() if face else None
    root = next(g for g in doc.scene.groups if g.id == key) if key else Group(name="Actor")
    parts = {view: SceneObject(name=view, parent_id=root.id) for view in VIEW_SLOTS[1:]}
    front = [p.id for p in (*doc.scene.objects, *doc.scene.groups) if p.id != root.id]
    root = replace(
        root,
        extra={
            **root.extra,
            "object_container": True,
            "view_slots": True,
            "active_view": "Front",
            "view_members": {
                view: [p.id, *(front if view == "Front" else [])] for view, p in parts.items()
            },
        },
    )
    MeshService(doc).commit(
        "Author test views",
        groups=(*[g for g in doc.scene.groups if g.id != root.id], root),
        objects=(*doc.scene.objects, *parts.values()),
    )
    return doc, root.id, parts


def test_movement_views_are_seek_order_independent_and_explicit_keys_win(tmp_path):
    """The same evaluated views appear in preview, export and reopened projects without state."""
    doc, root, parts = scene_views()
    edit = AnimationEditingService(doc)
    for frame, value in ((0, 0), (5, 100), (10, 100), (15, 0)):
        edit.key(root, "transform.x", frame, value)
    service = GameAuthoringService(doc)
    service.movement_views(
        root,
        {
            "driver": root,
            "minimum_speed": 8,
            "slots": {
                "idle": "Front",
                "left": "Back",
                "right": "Side",
                "up": "Front 3/4",
                "down": "Back 3/4",
            },
        },
    )
    for frame, view in ((13, "Back"), (3, "Side"), (8, "Front"), (0, "Side"), (13, "Back")):
        pose = doc.animation.evaluate(frame)
        assert pose.nodes[parts[view].id].visible
        assert sum(pose.nodes[p.id].visible for p in parts.values()) == 1
    ObjectViewsService(doc).key_view(root, "Front 3/4", 4)
    assert doc.animation.evaluate(8).nodes[parts["Front 3/4"].id].visible
    assert doc.animation.evaluate(3).nodes[parts["Side"].id].visible
    local = SceneEvaluator(doc.scene, local_object=root)
    assert local.evaluate(8).nodes[parts["Front"].id].visible
    doc.save(tmp_path / "views.rigora")
    reopened = DocumentService()
    reopened.open(tmp_path / "views.rigora")
    assert reopened.animation.evaluate(8) == doc.animation.evaluate(8)


def test_camera_turns_use_authored_views_hysteresis_discrete_keys_and_undo():
    """Head turns hold through threshold noise and record ordinary editable View keys."""
    doc, root, parts = scene_views(face=True)
    take = TrackingTake(doc, root, 0.7, turns=True)
    original, steps = doc.project, len(doc.history.undo_stack)
    take.feed(TrackingSample(0, angles={"head_yaw": 0}))
    take.calibrate()
    take.record()
    for seconds, yaw, view in (
        (0.1, 30, "Front 3/4"),
        (0.2, 20, "Front 3/4"),
        (0.3, 70, "Side"),
        (0.4, 60, "Side"),
        (0.5, 10, "Front"),
    ):
        pose = take.feed(TrackingSample(seconds, angles={"head_yaw": yaw}))
        assert pose.nodes[parts[view].id].visible
    assert doc.project is original
    take.keep()
    track = next(
        t for t in doc.animation.evaluator.timeline.tracks if t.property_path == "object.view"
    )
    assert all(k.interpolation == "step" for k in track.keyframes)
    assert track.extra["view_owner"] == root and len(doc.history.undo_stack) == steps + 1
    assert doc.animation.evaluate(7.2).nodes[parts["Side"].id].visible
    doc.undo()
    assert doc.project == original


@pytest.mark.gui
def test_movement_mapping_dialog_saves_shared_evaluated_behavior(qtbot, tmp_path):
    """The real Apply action configures the shared engine, rather than a preview-only effect."""
    from rigora.app.application import ApplicationInfo
    from rigora.infrastructure.preferences import PreferencesStore
    from rigora.presentation.viewmodels.main_window import MainWindowViewModel
    from rigora.presentation.views.main_window import MainWindow

    vm = MainWindowViewModel(ApplicationInfo(), preferences=PreferencesStore(tmp_path / "ui.json"))
    window = MainWindow(vm)
    window.confirm_discard = lambda: True
    qtbot.addWidget(window)
    vm.new_project()
    doc, root, parts = scene_views(document=vm.documents)
    window.command_actions["movement_views"].trigger()
    dialog = window.movement_views
    qtbot.addWidget(dialog)
    dialog.enabled.setChecked(True)
    dialog.driver.setCurrentIndex(dialog.driver.findData(root))
    dialog.slots["idle"].setCurrentText("Front")
    dialog.slots["right"].setCurrentText("Side")
    dialog.apply()
    assert not vm.scene.error, dialog.note.text()
    edit = AnimationEditingService(doc)
    edit.key(root, "transform.x", 0, 0)
    edit.key(root, "transform.x", 12, 120)
    assert doc.animation.evaluate(6).nodes[parts["Side"].id].visible
    dialog.close()
