"""Effective shot boundaries, bidirectional continuous transitions and target-centered following."""

import pytest

from rigora.application_services.appearance import AppearanceService
from rigora.application_services.camera_shots import CameraShotService
from rigora.application_services.documents import DocumentService
from rigora.domain.entities import Transform
from rigora.domain.geometry import transform_point
from rigora.engine.cameras import active_camera


def test_camera_transitions_between_repeated_cameras_have_no_static_graph_cycle(tmp_path):
    """A→B→A transitions evaluate at their exact endpoints/midpoints and persist reversibly."""
    doc = DocumentService()
    doc.new()
    service = CameraShotService(doc)
    first = doc.scene.cameras[0].id
    second = service.add("Closeup")
    service.update(second, transform=Transform(x=200))
    service.shot(second, 10, duration=10, easing="linear")
    service.shot(first, 30, duration=10, easing="linear")
    for frame, camera, x in (
        (10, second, 0),
        (15, second, 100),
        (20, second, 200),
        (35, first, 100),
        (40, first, 0),
        (15, second, 100),
    ):
        pose = doc.animation.evaluate(frame)
        assert not pose.warnings
        assert active_camera(pose).id == camera
        assert pose.nodes[camera].world_matrix[4] == pytest.approx(x)
    assert len(service.shots()) == 3
    before = doc.project
    service.remove_shot(30)
    assert len(service.shots()) == 2
    doc.undo()
    assert doc.project == before
    doc.save(tmp_path / "shots.rigora")
    doc.open(doc.path)
    assert doc.animation.evaluate(35).nodes[first].world_matrix[4] == pytest.approx(100)


def test_camera_follow_centers_target_pivot_and_keeps_removal_safe():
    """Follow uses the target's visible pivot and preserves authored camera rotation/scale."""
    doc = DocumentService()
    doc.new()
    look = AppearanceService(doc)
    key = look.create_shape("ellipse", 300, 100, 100, 100)
    target = look.mesh(key).object_id
    service = CameraShotService(doc)
    camera = doc.scene.cameras[0].id
    service.follow(camera, target, offset_x=10, offset_y=-5)
    pose = doc.animation.evaluate(0)
    source, output = pose.nodes[target], pose.nodes[camera]
    x, y = transform_point(source.world_matrix, source.local.pivot_x, source.local.pivot_y)
    assert transform_point(
        output.world_matrix, output.local.pivot_x, output.local.pivot_y
    ) == pytest.approx((x + 10, y - 5))
    service.follow(camera)
    assert not any(c.kind == "camera_follow" for c in doc.scene.constraints)


def test_camera_bone_follow_uses_the_same_object_placement_as_visible_skin():
    """A follow target remains on a skinned joint after its owning Object moves and rotates."""
    from rigora.application_services.animation_editing import AnimationEditingService
    from rigora.application_services.character_creation import (
        CharacterCreationService,
        build_character,
    )
    from rigora.application_services.scene_editing import SceneEditingService
    from rigora.domain.character_recipe import CharacterRecipe

    doc = DocumentService()
    doc.new()
    root = CharacterCreationService(doc).create(build_character(CharacterRecipe(motions=())))
    bone = next(b.id for b in doc.scene.skeletons[0].bones if b.name == "head")
    assert doc.animation.evaluator.skinned_rigs[bone] == root
    SceneEditingService(doc).transform((root,), dx=250, dy=130)
    AnimationEditingService(doc).key(root, "transform.rotation", 0, 30)
    camera = doc.scene.cameras[0].id
    CameraShotService(doc).follow(camera, bone, offset_x=10, offset_y=-5)
    pose = doc.animation.evaluate(6).for_display()
    target, output = pose.nodes[bone], pose.nodes[camera]
    x, y = transform_point(target.world_matrix, target.local.pivot_x, target.local.pivot_y)
    assert not pose.warnings
    assert transform_point(output.world_matrix, output.local.pivot_x, output.local.pivot_y) == (
        pytest.approx(x + 10),
        pytest.approx(y - 5),
    )
