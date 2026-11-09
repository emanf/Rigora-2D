"""Scene followers retain complete rigs and use placed, evaluated target transforms."""

from dataclasses import replace

import pytest

from rigora.application_services.appearance import AppearanceService
from rigora.application_services.bindings import BindingService
from rigora.application_services.character_creation import CharacterCreationService, build_character
from rigora.application_services.characters import CharacterService
from rigora.application_services.documents import DocumentService
from rigora.domain.character_recipe import character_preset
from rigora.domain.geometry import inverse, multiply
from rigora.domain.validation import ProjectError


@pytest.fixture(scope="module")
def built():
    """Share immutable authored sources while every test owns its document and history."""
    return build_character(replace(character_preset("Little"), motions=()))


@pytest.fixture
def scene(built):
    doc = DocumentService()
    doc.new()
    actor = CharacterCreationService(doc).create(built)
    shapes = AppearanceService(doc)
    mesh = shapes.create_shape("rectangle", 1100, 500, 20, 100)
    axe = CharacterService(doc).create_object((str(shapes.mesh(mesh).object_id),), "Axe")
    hand = next(b.id for rig in doc.scene.skeletons for b in rig.bones if b.name == "hand.R")
    return doc, BindingService(doc), actor, axe, hand


@pytest.mark.parametrize("change", ({"dx": 100, "dy": 40}, {"rotation": 25}, {"scale_x": -1}))
def test_scene_prop_follows_placed_hand(scene, change):
    doc, service, actor, axe, hand = scene
    before = doc.animation.pose.for_display()
    offset = multiply(inverse(before.nodes[hand].world_matrix), before.nodes[axe].world_matrix)
    service.bind((axe,), hand, rigid=True)
    service.transform((actor,), **change)
    pose = doc.animation.pose.for_display()
    assert not pose.warnings
    assert pose.nodes[axe].world_matrix == pytest.approx(
        multiply(pose.nodes[hand].world_matrix, offset)
    )


def test_attaching_whole_object_preserves_internal_skins_and_undo(scene):
    doc, service, actor, axe, _ = scene
    skins = tuple(d for d in doc.scene.deformers if d.kind == "skinning")
    before, count = doc.project, len(doc.history.undo_stack)
    service.bind((actor,), axe, rigid=True)
    assert tuple(d for d in doc.scene.deformers if d.kind == "skinning") == skins
    assert len(doc.history.undo_stack) == count + 1
    doc.undo()
    assert doc.project == before


def test_named_grips_snap_and_preserve_internal_rig(scene):
    from rigora.application_services.scene_attachments import SceneAttachmentService
    from rigora.domain.geometry import affine

    doc, _, actor, axe, hand = scene
    service = SceneAttachmentService(doc)
    grip = service.add_point(axe, "Grip", x=0, y=-20)
    service.attach((axe,), hand, point="@grip", source_point=grip, snap=True)
    pose = doc.animation.pose.for_display()
    assert multiply(pose.nodes[axe].world_matrix, affine(0, -20, 0, 1, 1, 0, 0)) == pytest.approx(
        multiply(
            pose.nodes[hand].world_matrix, affine(pose.nodes[hand].length / 2, 0, 0, 1, 1, 0, 0)
        )
    )
    assert CharacterService(doc).object_root(axe).id == axe
    assert service.state(axe).target_id == hand
    before = tuple(d for d in doc.scene.deformers if d.kind == "skinning")
    with pytest.raises(ProjectError, match="cycle"):
        service.attach((actor,), axe)
    assert tuple(d for d in doc.scene.deformers if d.kind == "skinning") == before


def test_pickup_release_seeks_independently_and_keeps_world_pose(scene):
    from rigora.application_services.animation_editing import AnimationEditingService
    from rigora.application_services.scene_attachments import SceneAttachmentService

    doc, _, actor, axe, hand = scene
    editor = AnimationEditingService(doc)
    start = doc.animation.pose.nodes[actor].local.x
    editor.key(actor, "transform.x", 0, start)
    editor.key(actor, "transform.x", 119, start + 240)
    service = SceneAttachmentService(doc)
    initial = doc.animation.evaluate(0).nodes[axe].world_matrix
    before, count = doc.project, len(doc.history.undo_stack)
    service.attach((axe,), hand, frame=40)
    assert len(doc.history.undo_stack) == count + 1
    assert service.state(axe, 0).target_id is None
    assert service.state(axe, 40).target_id == hand
    doc.undo()
    assert doc.project == before
    doc.redo()
    releasing = doc.animation.evaluate(90).nodes[axe].world_matrix
    service.detach((axe,), frame=90)
    first = {frame: doc.animation.evaluate(frame) for frame in (0, 25, 40, 60, 90, 110)}
    assert first[25].nodes[axe].world_matrix == pytest.approx(initial)
    assert first[90].nodes[axe].world_matrix == pytest.approx(releasing)
    assert first[110].nodes[axe].world_matrix == pytest.approx(releasing)
    for frame in (110, 25, 90, 40, 0, 60):
        assert doc.animation.evaluate(frame) == first[frame]


def test_scene_attachment_supports_affine_scale_and_editable_transform(scene):
    from rigora.application_services.scene_attachments import SceneAttachmentService

    doc, editing, actor, axe, hand = scene
    service = SceneAttachmentService(doc)
    service.attach((axe,), hand)
    before = doc.animation.pose.for_display()
    offset = multiply(inverse(before.nodes[hand].world_matrix), before.nodes[axe].world_matrix)
    editing.transform((actor,), scale_x=1.5, scale_y=0.7, rotation=25)
    pose = doc.animation.pose.for_display()
    assert not pose.warnings
    assert pose.nodes[axe].world_matrix == pytest.approx(
        multiply(pose.nodes[hand].world_matrix, offset)
    )
    previous = pose.nodes[axe].world_matrix
    editing.transform((axe,), dx=30, dy=15)
    assert doc.animation.pose.nodes[axe].world_matrix[4:] == pytest.approx(
        (previous[4] + 30, previous[5] + 15)
    )


@pytest.mark.parametrize("keyed", (False, True))
def test_deleting_target_releases_prop_and_undo_restores_links(scene, keyed):
    """Deleting a character repairs references in setup and pickup keys atomically."""
    from rigora.application_services.scene_attachments import SceneAttachmentService

    doc, editing, actor, axe, hand = scene
    service = SceneAttachmentService(doc)
    from rigora.application_services.animation_editing import AnimationEditingService

    editor = AnimationEditingService(doc)
    editor.key(actor, "transform.x", 0, 0)
    editor.key(actor, "transform.x", 119, 240)
    service.attach((axe,), hand, frame=40 if keyed else None)
    doc.animation.seek(60)
    before, count = doc.project, len(doc.history.undo_stack)
    pose = doc.animation.pose.nodes[axe].world_matrix
    editing.delete_entries((actor,))
    assert axe in editing.records()
    assert service.state(axe, 60).target_id is None
    assert doc.animation.pose.nodes[axe].world_matrix == pytest.approx(pose)
    doc.project.validate_references()
    assert len(doc.history.undo_stack) == count + 1
    doc.undo()
    assert doc.project == before


def test_points_and_keys_survive_serialization_and_track_mute(scene):
    """Portable held metadata keeps references; muting really stops pickup evaluation."""
    from rigora.application_services.animation_editing import AnimationEditingService
    from rigora.application_services.scene_attachments import SceneAttachmentService
    from rigora.domain.project import Project
    from rigora.domain.scene_attachments import ATTACHMENT_PATH

    doc, _, _, axe, hand = scene
    service = SceneAttachmentService(doc)
    grip = service.add_point(axe, "Handle", x=2, y=-25)
    service.attach((axe,), hand, source_point=grip, frame=20)
    assert Project.from_dict(doc.project.to_dict()) == doc.project
    with pytest.raises(ProjectError, match="used by animation"):
        service.remove_point(axe, grip)
    timeline = AnimationEditingService(doc).timeline
    track = next(t for t in timeline.tracks if t.property_path == ATTACHMENT_PATH)
    service.commit(
        "Mute pickup", timelines=(replace(timeline, tracks=(replace(track, visible=False),)),)
    )
    assert service.state(axe, 60).target_id is None
    doc.undo()
    assert service.state(axe, 60).target_id == hand


def test_track_discovery_and_generic_keying_preserve_attachment_state(scene):
    """Add Track and generic key commands retain held relationship metadata."""
    from rigora.application_services.animation_editing import AnimationEditingService
    from rigora.application_services.scene_attachments import SceneAttachmentService
    from rigora.domain.scene_attachments import ATTACHMENT_PATH

    doc, _, _, axe, hand = scene
    editor = AnimationEditingService(doc)
    editor.add_channels(((axe, ATTACHMENT_PATH),))
    assert not editor.timeline.tracks[-1].keyframes
    service = SceneAttachmentService(doc)
    service.attach((axe,), hand, frame=15)
    editor.key(axe, ATTACHMENT_PATH, 40, 1)
    editor.auto_key_values({(axe, ATTACHMENT_PATH): 1}, 60)
    keys = next(t for t in editor.timeline.tracks if t.property_path == ATTACHMENT_PATH).keyframes
    assert [k.frame for k in keys] == [0, 15, 40, 60]
    assert all(k.interpolation == "step" and "scene_attachment" in k.extra for k in keys)


def test_transfer_and_inheritance_options_are_deterministic(scene):
    """A prop can pass between hands and opt out of its target's rotation and scale."""
    from rigora.application_services.scene_attachments import SceneAttachmentService

    doc, editing, actor, axe, hand = scene
    other = next(b.id for r in doc.scene.skeletons for b in r.bones if b.name == "hand.L")
    service = SceneAttachmentService(doc)
    service.attach((axe,), hand, inherit_rotation=False, inherit_scale=False, frame=10)
    before = doc.animation.evaluate(30).nodes[axe].world_matrix
    editing.transform((actor,), scale_x=1.4, scale_y=0.6, rotation=20)
    after = doc.animation.evaluate(30).nodes[axe].world_matrix
    assert after[:4] == pytest.approx(before[:4])
    service.attach((axe,), other, frame=50)
    assert service.state(axe, 30).target_id == hand
    assert service.state(axe, 50).target_id == other
    expected = doc.animation.evaluate(70)
    doc.animation.evaluate(20)
    assert doc.animation.evaluate(70) == expected


def test_shared_object_grips_do_not_share_scene_links_and_scene_copy_remaps_keys(scene):
    """Grips belong to reusable content; placed links and held target IDs belong to each Scene."""
    from rigora.application_services.object_library import (
        LINK,
        ObjectLibraryService,
        object_fragment,
    )
    from rigora.application_services.scene_attachments import SceneAttachmentService
    from rigora.domain.entities import nested_records

    doc, _, _, axe, hand = scene
    library = ObjectLibraryService(doc)
    key = CharacterService(doc).record(axe).extra[LINK]["definition"]
    peer = library.place(key, (1400, 600))
    service = SceneAttachmentService(doc)
    service.attach((axe,), hand, frame=20)
    grip = service.add_point(axe, "Handle", x=0, y=-30)
    assert grip in dict(service.point_choices(peer))
    assert service.state(peer, 40).target_id is None
    assert service.state(axe, 40).target_id == hand
    assert not any(
        c.kind == "scene_attachment" for c in object_fragment(doc.scene, (axe,)).constraints
    )
    original = doc.scene
    library.paste(library.copy_scene(original.id))
    copied = next(s for s in doc.project.scenes if s.id != original.id)
    copied_ids = {r.id for r in nested_records(copied)}
    original_ids = {r.id for r in nested_records(original)}
    assert not original_ids.intersection(copied_ids)
    target = next(c.target_id for c in copied.constraints if c.kind == "scene_attachment")
    assert target is None
    keyed = [
        k.extra["scene_attachment"]["target_id"]
        for t in copied.timelines
        for tr in t.tracks
        for k in tr.keyframes
        if "scene_attachment" in k.extra
    ]
    assert any(key in copied_ids for key in keyed)
    assert not any(key in original_ids for key in keyed if key)


def test_attachment_rejects_invalid_point_and_locked_or_self_targets_atomically(scene):
    """Invalid grip references and locked targets cannot leave half-created setup constraints."""
    from rigora.application_services.scene_attachments import SceneAttachmentService

    doc, editing, actor, axe, hand = scene
    service = SceneAttachmentService(doc)
    before = doc.project
    for target, point in ((hand, "missing"), (axe, "")):
        with pytest.raises(ProjectError):
            service.attach((axe,), target, point=point)
        assert doc.project == before
    editing.flags((actor,), locked=True)
    before = doc.project
    with pytest.raises(ProjectError, match="unlocked"):
        service.attach((axe,), hand)
    assert doc.project == before


def test_attachment_is_sampled_into_native_export(tmp_path):
    """Native engine samples retain evaluated following rather than the source's authored pose."""
    import io
    import json
    import zipfile

    from rigora.application_services.animation_editing import AnimationEditingService
    from rigora.application_services.rig_export import rig_package
    from rigora.application_services.scene_attachments import SceneAttachmentService

    doc = DocumentService()
    doc.new()
    shapes = AppearanceService(doc)
    target = str(shapes.mesh(shapes.create_shape("rectangle", 100, 100, 50, 50)).object_id)
    prop = str(shapes.mesh(shapes.create_shape("ellipse", 400, 100, 20, 20)).object_id)
    editor = AnimationEditingService(doc)
    editor.key(target, "transform.x", 0, 0)
    editor.key(target, "transform.x", 30, 100)
    SceneAttachmentService(doc).attach((prop,), target)
    frames = (0, 15, 30)
    data, _ = rig_package(
        doc,
        "unity-rig",
        frames,
        fps=30,
        loop=False,
        texture_limit=64,
        check=lambda: None,
        report=lambda _: None,
    )
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        runtime = json.loads(archive.read("rig.json"))
    node = next(n for n in runtime["nodes"] if n["id"] == prop)
    for sample, frame in zip(node["samples"], frames, strict=True):
        world = doc.animation.evaluate(frame).nodes[prop].world_matrix
        assert sample["translation"][:2] == pytest.approx((world[4] / 100, -world[5] / 100))


def test_attachment_tracks_a_sprung_hand_at_its_final_placed_pose(scene):
    """Rigid Scene props follow the evaluated spring result rather than an earlier bone pose."""
    from rigora.application_services.animation_editing import AnimationEditingService
    from rigora.application_services.dynamics import DynamicsService
    from rigora.application_services.scene_attachments import SceneAttachmentService

    doc, _, actor, axe, hand = scene
    DynamicsService(doc).assign_group((hand,), group="Hand", frequency=2, damping=0.3, gravity=500)
    editor = AnimationEditingService(doc)
    editor.key(actor, "transform.x", 0, 0)
    editor.key(actor, "transform.x", 8, 150)
    service = SceneAttachmentService(doc)
    service.attach((axe,), hand)
    state = service.state(axe)
    for frame in (12, 25, 4, 12):
        pose = doc.animation.evaluate(frame).for_display()
        assert not pose.warnings
        assert pose.nodes[axe].world_matrix == pytest.approx(
            multiply(pose.nodes[hand].world_matrix, state.offset)
        )


def test_attached_character_springs_receive_the_same_world_acceleration(scene):
    """Moving a driver's Scene transform excites attached rigs like moving their Object directly."""
    from rigora.application_services.animation_editing import AnimationEditingService
    from rigora.application_services.dynamics import DynamicsService
    from rigora.application_services.scene_attachments import SceneAttachmentService

    doc, _, actor, axe, _ = scene
    first = next(b.id for r in doc.scene.skeletons for b in r.bones if not b.extra.get("rig_root"))
    DynamicsService(doc).assign_group((first,), group="Body", frequency=2, damping=0.3, gravity=400)
    direct = doc.fork()
    SceneAttachmentService(doc).attach((actor,), axe)
    for target, owner in ((doc, axe), (direct, actor)):
        editor = AnimationEditingService(target)
        base = target.animation.pose.nodes[owner].local.x
        editor.key(owner, "transform.x", 0, base)
        editor.key(owner, "transform.x", 8, base + 120)
        editor.clip_settings(out_frame=30)
    for frame in (12, 25, 4, 12):
        attached_pose = doc.animation.evaluate(frame).for_display()
        direct_pose = direct.animation.evaluate(frame).for_display()
        assert not attached_pose.warnings
        assert attached_pose.nodes[first].world_matrix == pytest.approx(
            direct_pose.nodes[first].world_matrix
        )


def test_object_editor_bone_deletion_repairs_scene_links_in_scene_space(scene):
    """Editing a rig in local space must not capture that view as an outside prop's release pose."""
    from rigora.application_services.rigging import RigService
    from rigora.application_services.scene_attachments import SceneAttachmentService

    doc, editing, actor, axe, hand = scene
    editing.transform((actor,), dx=350, dy=200, rotation=15)
    service = SceneAttachmentService(doc)
    service.attach((axe,), hand)
    editing.transform((actor,), dx=80, dy=50)
    before = doc.animation.pose.nodes[axe].world_matrix
    members = frozenset(CharacterService(doc).members(actor))
    doc.set_animation_context(actor, members)
    local = doc.animation.pose.nodes[actor].world_matrix
    assert local != before
    with pytest.raises(ProjectError, match="Scene timeline"):
        service.key_current(axe, 20)
    RigService(doc).delete(hand)
    doc.set_animation_context(None)
    assert service.state(axe).target_id is None
    assert doc.animation.pose.nodes[axe].world_matrix == pytest.approx(before)


def test_setup_cannot_replace_locked_attachment_keys(scene):
    """Whole-scene setup edits respect the same lock as ordinary frame insertion."""
    from rigora.application_services.animation_editing import AnimationEditingService
    from rigora.application_services.scene_attachments import SceneAttachmentService

    doc, _, _, axe, hand = scene
    service = SceneAttachmentService(doc)
    service.attach((axe,), hand, frame=20)
    editor = AnimationEditingService(doc)
    track = editor.timeline.tracks[0]
    editor.track_settings(track.id, locked=True, visible=True)
    before = doc.project
    with pytest.raises(ProjectError, match="[Ll]ock"):
        service.detach((axe,))
    assert doc.project == before
    with pytest.raises(ProjectError, match="[Ll]ock"):
        service.detach((axe,), frame=30)
    assert doc.project == before


def test_attachment_api_dry_run_and_plugin_services_use_canonical_state(scene, tmp_path):
    """Automation and plugins share the desktop implementation and its atomic dry-run boundary."""
    from rigora.api import RigoraAPI
    from rigora.application_services.plugin_commands import document_service

    doc, _, _, axe, hand = scene
    api = RigoraAPI(tmp_path, document=doc)
    before = doc.project
    api.execute("scene_attach", {"sources": [axe], "target": hand, "frame": 20}, dry_run=True)
    assert doc.project == before
    result = api.execute("scene_attach", {"sources": [axe], "target": hand, "frame": 20})
    assert result.data["attachments"][0]["state"]["target_id"] is None
    service = document_service("scene_attachments", doc)
    assert service.state(axe, 20).target_id == hand
    api.execute("scene_detach", {"sources": [axe], "frame": 60})
    assert service.state(axe, 60).target_id is None
    assert service.state(axe, 40).target_id == hand


@pytest.mark.gui
def test_guided_attachment_window_and_timeline_use_same_service(scene, qtbot):
    """Real clicks attach/release and a timeline icon reopens the guided editor at its key."""
    from PySide6.QtCore import Qt

    from rigora.app.application import ApplicationInfo
    from rigora.presentation.viewmodels.main_window import MainWindowViewModel
    from rigora.presentation.views.main_window import MainWindow
    from rigora.presentation.widgets.scene_attachments import SceneAttachmentsDialog

    doc, _, actor, axe, hand = scene
    model = MainWindowViewModel(ApplicationInfo(), documents=doc)
    model.welcome_selected = False
    window = MainWindow(model)
    window.confirm_discard = lambda: True
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(10)
    model.scene.select((axe,))
    assert model.scene.selected == (axe,)
    window.attach_selection()
    dialog = window.scene_attachments_dialog
    qtbot.addWidget(dialog)
    assert dialog.source.currentData() == axe
    assert not dialog.attach_button.isEnabled()
    before = doc.project
    dialog.choose_target(hand)
    assert doc.project is before
    qtbot.mouseClick(dialog.attach_button, Qt.MouseButton.LeftButton)
    assert dialog.model.state(axe).target_id == hand
    assert "Right hand" in dialog.current.text()
    dialog.timing.setCurrentIndex(1)
    dialog.frame_input.setValue(60)
    qtbot.mouseClick(dialog.release_button, Qt.MouseButton.LeftButton)
    assert dialog.isVisible()
    assert dialog.model.state(axe, 60).target_id is None
    assert dialog.model.state(axe, 30).target_id == hand
    window.timeline.open_action({"owner": axe, "kind": "attachment", "frame": 60})
    assert isinstance(window.timeline.action_editor, SceneAttachmentsDialog)
    qtbot.addWidget(window.timeline.action_editor)
    assert window.timeline.action_editor.frame_input.value() == 60
    before = doc.project
    window.refresh_asset_thumbnails()
    assert doc.project is before
    dialog.resize(720, 520)
    dialog.fine_alignment.setChecked(True)
    qtbot.wait(1)
    assert dialog.height() == 520
    assert dialog.editor_scroll.verticalScrollBar().maximum() > 0
    assert not dialog.editor_scroll.horizontalScrollBar().isVisible()
    doc.set_animation_context(actor, frozenset(CharacterService(doc).members(actor)))
    model.changed.emit()
    assert not dialog.isVisible()
    assert not window.timeline.action_editor.isVisible()
    doc.set_animation_context(None)
    window.close()
