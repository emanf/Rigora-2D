"""Whole-object scene gestures keep creator skins, planted feet and helper controls together."""

from dataclasses import replace

import pytest

from rigora.application_services.character_creation import CharacterCreationService, build_character
from rigora.application_services.characters import CharacterService
from rigora.application_services.documents import DocumentService
from rigora.application_services.scene_editing import SceneEditingService
from rigora.domain.character_recipe import CHARACTER_PRESETS, MOTION_CHOICES, character_preset
from rigora.domain.geometry import affine, multiply, transform_point


def world_points(pose):
    """Read actual final artwork vertices after skinning and the owner's world transform."""
    return {
        key: tuple(transform_point(pose.nodes[m.object_id].world_matrix, *p) for p in m.positions)
        for key, m in pose.meshes.items()
    }


def assert_transformed(before, after, matrix):
    """Compare every body/clothing vertex, including both feet, against one common transform."""
    old, new = world_points(before), world_points(after)
    assert old.keys() == new.keys() and not after.warnings
    for key, points in old.items():
        for actual, point in zip(new[key], points, strict=True):
            assert actual == pytest.approx(transform_point(matrix, *point), abs=1e-7), (
                before.nodes[before.meshes[key].object_id].name,
                actual,
                point,
            )


@pytest.fixture(scope="module", params=CHARACTER_PRESETS)
def premade(request):
    """Reuse the real creator preset assemblies without unrelated action-generation cost."""
    return build_character(replace(character_preset(request.param), motions=()))


@pytest.mark.parametrize("recording", (False, True))
def test_scene_whole_object_transform_moves_body_and_feet_exactly_once(premade, recording):
    """The scene's part-edit policy must not move bind-space helper bones a second time."""
    doc = DocumentService()
    doc.new()
    root = CharacterCreationService(doc).create(premade)
    source, before = doc.project, doc.animation.pose
    count = len(doc.history.undo_stack)
    service = SceneEditingService(doc)
    service.part_edit, service.auto_key = True, recording
    service.transform((root,), dx=100, dy=50)
    assert_transformed(before, doc.animation.pose, affine(100, 50, 0, 1, 1, 0, 0))
    assert doc.project.scenes[0].skeletons == source.scenes[0].skeletons
    assert len(doc.history.undo_stack) == count + 1
    if recording:
        timeline = next(
            t
            for t in doc.project.scenes[0].timelines
            if t.id == doc.animation.evaluator.clip.timeline_id
        )
        assert all(t.owner_id == root for t in timeline.tracks)
    doc.undo()
    assert doc.project == source


def test_nested_scene_folder_rotation_and_scale_keep_feet_attached(premade):
    """A parent folder carries the entire character without changing its internal armature."""
    doc = DocumentService()
    doc.new()
    root = CharacterCreationService(doc).create(premade)
    service = SceneEditingService(doc)
    folder = service.group((root,), "Scene folder")
    before, source = doc.animation.pose, doc.project
    center = before.nodes[folder].world_matrix[4:]
    delta = multiply(
        affine(center[0] + 25, center[1] - 20, 23, 1.2, 0.8, 0, 0),
        affine(-center[0], -center[1], 0, 1, 1, 0, 0),
    )
    service.part_edit = True
    service.transform(
        (folder,),
        dx=25,
        dy=-20,
        rotation=23,
        scale_x=1.2,
        scale_y=0.8,
        center_x=center[0],
        center_y=center[1],
    )
    assert_transformed(before, doc.animation.pose, delta)
    assert doc.project.scenes[0].skeletons == source.scenes[0].skeletons


@pytest.mark.parametrize("vertical", (False, True))
def test_creator_character_flip_keeps_feet_and_bone_overlays_with_the_object(premade, vertical):
    """Every creator preset mirrors its full rig placement without editing bind-space bones."""
    doc = DocumentService()
    doc.new()
    root = CharacterCreationService(doc).create(premade)
    before, source = doc.animation.pose, doc.project
    points = [p for vertices in world_points(before).values() for p in vertices]
    cx, cy = ((min(p[i] for p in points) + max(p[i] for p in points)) / 2 for i in (0, 1))
    matrix = multiply(
        affine(cx, cy, 0, 1 if vertical else -1, -1 if vertical else 1, 0, 0),
        affine(-cx, -cy, 0, 1, 1, 0, 0),
    )
    service = CharacterService(doc)
    service.part_edit, service.sprite_edit = True, True
    service.flip((root,), vertical=vertical)
    after = doc.animation.pose
    assert_transformed(before, after, matrix)
    assert doc.scene.skeletons == source.scenes[0].skeletons
    assert doc.scene.deformers == source.scenes[0].deformers
    old_display, new_display = before.for_display(), after.for_display()
    for key, node in old_display.nodes.items():
        if node.kind == "bone":
            for point in ((0, 0), (node.length, 0)):
                expected = transform_point(matrix, *transform_point(node.world_matrix, *point))
                assert transform_point(
                    new_display.nodes[key].world_matrix, *point
                ) == pytest.approx(expected)
    doc.undo()
    assert doc.project == source


@pytest.fixture(scope="module")
def animated_premade():
    """Build the normal premade action set once for action-preservation checks."""
    return build_character(character_preset("Little"))


def test_robot_all_creator_actions_have_unique_key_times():
    """The creator's full preview catalog accepts coincident servo gait and contact beats."""
    result = build_character(replace(character_preset("Orbit"), motions=MOTION_CHOICES))
    doc = DocumentService()
    doc.new()
    CharacterCreationService(doc).create(result)
    scene = doc.project.scenes[0]
    assert {c.name for c in scene.clips} == set(MOTION_CHOICES)
    for timeline in scene.timelines:
        for track in timeline.tracks:
            frames = [k.frame for k in track.keyframes]
            assert frames == sorted(set(frames))


@pytest.mark.parametrize("motion", ("Idle", "Walk", "Run"))
def test_scene_drag_preserves_animated_foot_contacts_and_locomotion(animated_premade, motion):
    """Whole-object placement carries evaluated actions once without rewriting local motion keys."""
    doc = DocumentService()
    doc.new()
    root = CharacterCreationService(doc).create(animated_premade)
    clip = next(c for c in doc.project.scenes[0].clips if c.name == motion)
    doc.set_animation_context(None)
    CharacterService(doc).place_motion(root, clip.id, 0, 2)
    frames = (0, 7, 17)
    before = [doc.animation.evaluate(f) for f in frames]
    doc.animation.seek(7)
    source = doc.project
    service = SceneEditingService(doc)
    service.part_edit = True
    service.transform((root,), dx=133, dy=-41)
    for frame, old in zip(frames, before, strict=True):
        assert_transformed(old, doc.animation.evaluate(frame), affine(133, -41, 0, 1, 1, 0, 0))
    assert doc.project.scenes[0].skeletons == source.scenes[0].skeletons
    assert doc.project.scenes[0].timelines == source.scenes[0].timelines
    moved = [doc.animation.evaluate(f) for f in frames]
    points = [p for vertices in world_points(doc.animation.pose).values() for p in vertices]
    center_x = (min(p[0] for p in points) + max(p[0] for p in points)) / 2
    center_y = (min(p[1] for p in points) + max(p[1] for p in points)) / 2
    mirror = multiply(
        affine(center_x, center_y, 0, -1, 1, 0, 0),
        affine(-center_x, -center_y, 0, 1, 1, 0, 0),
    )
    service = CharacterService(doc)
    service.part_edit = service.sprite_edit = True
    service.flip((root,))
    for frame, old in zip(frames, moved, strict=True):
        assert_transformed(old, doc.animation.evaluate(frame), mirror)
    assert doc.scene.skeletons == source.scenes[0].skeletons
    assert doc.scene.timelines == source.scenes[0].timelines


@pytest.mark.gui
@pytest.mark.parametrize("name", ("Little", "Ribbon", "Orbit"))
def test_premade_from_creation_window_pointer_drag_keeps_feet_attached(
    editor, qtbot, name, tmp_path
):
    """Create through the real wizard and check live pointer preview, release and one-step undo."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent
    from test_character_wizard_gui import creator, select_design
    from test_roots_soft_drag_gui import pointer

    wizard = creator(editor, qtbot)
    select_design(wizard, name)
    wizard.create_character()
    qtbot.waitUntil(lambda: not wizard.isVisible() or bool(wizard.model.error), timeout=90000)
    assert not wizard.model.error, wizard.model.error
    vm, viewport = editor.viewmodel, editor.viewport
    doc = vm.documents
    assets = {a.id for a in doc.project.assets}
    qtbot.waitUntil(lambda: assets <= viewport.artwork.vectors.keys(), timeout=15000)
    before, source = doc.animation.pose, doc.project
    count = len(doc.history.undo_stack)
    mesh = next(m for m in before.meshes.values() if before.nodes[m.object_id].name == "Head")
    points = world_points(before)[mesh.id]
    center = QPointF(*(sum(p[i] for p in points) / len(points) for i in (0, 1)))
    viewport.zoom = 0.8
    viewport.offset = QPointF(viewport.width() / 2, viewport.height() / 3) - center * viewport.zoom
    start = center * viewport.zoom + viewport.offset
    delta = QPointF(96, 40)
    pointer(viewport, QMouseEvent.Type.MouseButtonPress, start)
    assert editor.scene_workspace.transform is None
    pointer(viewport, QMouseEvent.Type.MouseMove, start + delta)
    expected = affine(delta.x() / viewport.zoom, delta.y() / viewport.zoom, 0, 1, 1, 0, 0)
    assert vm.scene.preview is not None and doc.project is source
    assert_transformed(before, vm.scene.preview, expected)
    pointer(viewport, QMouseEvent.Type.MouseButtonRelease, start + delta)
    assert not vm.scene.error
    assert_transformed(before, doc.animation.pose, expected)
    assert len(doc.history.undo_stack) == count + 1
    bounds = editor.scene_workspace.transform_bounds()
    center = (bounds.center() - viewport.offset) / viewport.zoom
    viewport.zoom *= min(
        (viewport.width() - 100) / bounds.width(),
        (viewport.height() - 100) / bounds.height(),
    )
    viewport.offset = QPointF(viewport.width() / 2, viewport.height() / 2) - center * viewport.zoom
    assert viewport.grab().save(str(tmp_path / (name + "-moved.png")))
    doc.undo()
    vm.changed.emit()
    assert doc.project == source


@pytest.fixture
def editor(qtbot, tmp_path, monkeypatch):
    """Reuse the isolated real editor fixture with asynchronous shelf posters suppressed."""
    from test_roots_soft_drag_gui import editor as existing

    yield from existing.__wrapped__(qtbot, tmp_path, monkeypatch)
