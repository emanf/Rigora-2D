"""Video observations become connected editable rigs, reusable motion and one undo command."""

import io
from dataclasses import replace

import pytest

from rigora.application_services.characters import CharacterService
from rigora.application_services.documents import DocumentService
from rigora.application_services.scene_editing import SceneEditingService
from rigora.application_services.video_rig import (
    VideoAnalysis,
    VideoPose,
    VideoRigService,
    cleaned_poses,
    correct_pose,
    segments,
)
from rigora.domain.geometry import multiply, transform_point
from rigora.domain.project import ProjectError, SceneSettings


def specimen(profile="Human"):
    """Return a complete reference and two motions with translation and foreshortening."""
    points = (
        (
            (100, 20),
            (95, 17),
            (105, 17),
            (90, 20),
            (110, 20),
            (80, 60),
            (120, 60),
            (60, 100),
            (140, 100),
            (40, 140),
            (160, 140),
            (85, 140),
            (115, 140),
            (80, 200),
            (120, 200),
            (75, 260),
            (125, 260),
        )
        if profile == "Human"
        else (
            (55, 45),
            (65, 45),
            (45, 60),
            (75, 90),
            (220, 100),
            (80, 105),
            (65, 150),
            (65, 200),
            (90, 105),
            (95, 150),
            (105, 200),
            (205, 110),
            (220, 155),
            (210, 200),
            (225, 110),
            (235, 155),
            (245, 200),
        )
    )
    poses = tuple(
        VideoPose(
            second,
            tuple(
                (float(x + second * 12), float(y - second * (i % 3) * 4), 0.95)
                for i, (x, y) in enumerate(points)
            ),
        )
        for second in (0, 0.5, 1)
    )
    return VideoAnalysis(profile, 320, 320, 30, poses, 0)


@pytest.mark.parametrize("profile", ["Human", "Quadruped"])
@pytest.mark.parametrize("artwork", [False, True])
def test_video_rig_connected_geometry_ownership_timing_move_roundtrip_undo(
    tmp_path, profile, artwork
):
    """Both topologies retain tracked endpoints, grouped skinning and scene placement."""
    document = DocumentService()
    document.new(settings=SceneSettings(width=640, height=480))
    document.separated_animation = True
    baseline = document.project
    analysis = specimen(profile)
    image = b""
    if artwork:
        from PIL import Image

        stream = io.BytesIO()
        Image.new("RGBA", (320, 320), "#cccccc").save(stream, format="PNG")
        image = stream.getvalue()
    result = VideoRigService(document).create(analysis, smoothing=0, artwork=image)
    assert len(document.history.undo_stack) == 1
    rig = document.scene.skeletons[0]
    assert result["bones"] == len(rig.bones)
    assert len(CharacterService(document).motions(str(result["object_id"]))) == 1
    assert {
        c.extra.get("object_id") for c in document.scene.clips if c.id == result["clip_id"]
    } == {result["object_id"]}
    scale, offset = 1.2, (128, 48)
    for sample in analysis.poses:
        pose = document.animation.evaluate(sample.seconds * 24)
        assert not pose.warnings
        expected = segments(profile, sample.points)
        for bone in rig.bones:
            node = pose.nodes[bone.id]
            _, a, b = expected[bone.name]
            assert node.world_matrix[4:] == pytest.approx(
                (offset[0] + a[0] * scale, offset[1] + a[1] * scale)
            )
            assert transform_point(node.world_matrix, node.length, 0) == pytest.approx(
                (offset[0] + b[0] * scale, offset[1] + b[1] * scale)
            )
    before = document.animation.evaluate(12)
    SceneEditingService(document).transform((str(result["object_id"]),), dx=40, dy=30)
    after = document.animation.evaluate(12)
    for bone in rig.bones:
        a, b = before.nodes[bone.id], after.nodes[bone.id]
        old = (
            multiply(before.bone_placements[bone.id], a.world_matrix)
            if bone.id in before.bone_placements
            else a.world_matrix
        )
        new = (
            multiply(after.bone_placements[bone.id], b.world_matrix)
            if bone.id in after.bone_placements
            else b.world_matrix
        )
        assert new[4:] == pytest.approx((old[4] + 40, old[5] + 30))
    for key, mesh in before.meshes.items():
        moved = after.meshes[key]
        for a, b in zip(mesh.positions, moved.positions, strict=True):
            old = transform_point(before.nodes[mesh.object_id].world_matrix, *a)
            new = transform_point(after.nodes[moved.object_id].world_matrix, *b)
            assert new == pytest.approx((old[0] + 40, old[1] + 30))
    document.save(tmp_path / "video.rigora")
    reopened = DocumentService()
    reopened.open(tmp_path / "video.rigora")
    for key, node in reopened.animation.evaluate(12).nodes.items():
        assert node.world_matrix == pytest.approx(after.nodes[key].world_matrix)
    document.undo()
    document.undo()
    assert document.project == baseline


def test_short_gaps_interpolate_long_gaps_remain_visible_in_quality_data():
    """Missing tracking cannot silently stretch into invented long motions or zero-valued joints."""
    analysis = specimen()
    good = analysis.poses[0].points
    missing = tuple((x, y, 0) for x, y, _ in good)
    analysis = replace(
        analysis,
        poses=tuple(
            VideoPose(t, points)
            for t, points in ((0, good), (0.1, missing), (0.2, good), (0.5, missing), (1, good))
        ),
    )
    result = cleaned_poses(analysis, 0.35, 0)
    assert result[1].points == good
    assert all(point[2] == 0 for point in result[3].points)
    document = DocumentService()
    document.new()
    VideoRigService(document).create(analysis, smoothing=0)
    assert all(
        not document.animation.evaluate(12).nodes[b.id].visible
        for b in document.scene.skeletons[0].bones
    )


def test_video_rig_invalid_data_and_weak_reference_leave_document_untouched():
    """Malformed detector output and untrackable subjects cannot publish partial Objects."""
    document = DocumentService()
    document.new()
    baseline = document.project
    with pytest.raises(ProjectError, match="17 finite"):
        VideoPose(0, ((float("nan"), 0, 1),) * 17)
    analysis = specimen()
    weak = replace(
        analysis,
        poses=tuple(
            replace(pose, points=tuple((x, y, 0) for x, y, _ in pose.points))
            for pose in analysis.poses
        ),
    )
    with pytest.raises(ProjectError, match="Too few reliable"):
        VideoRigService(document).create(weak)
    assert document.project is baseline


@pytest.mark.parametrize("profile", ["Human", "Quadruped"])
def test_manual_corrections_are_exact_anchors_in_created_animation(profile):
    """Filtering never rewrites reviewed body endpoints on any sampled frame."""
    analysis = specimen(profile)
    joint, role = (9, "forearm.L") if profile == "Human" else (7, "frontlower.L")
    poses = tuple(
        correct_pose(profile, pose, joint, 45 + i * 19, 160 - i * 23)
        for i, pose in enumerate(analysis.poses)
    )
    analysis = replace(analysis, poses=poses)
    filtered = cleaned_poses(analysis, 0.35, 0.9)
    assert [p.points[joint] for p in filtered] == [p.points[joint] for p in poses]
    document = DocumentService()
    document.new(settings=SceneSettings(width=640, height=480))
    VideoRigService(document).create(analysis, smoothing=0.9)
    bone = next(b for b in document.scene.skeletons[0].bones if b.name == role)
    for pose in poses:
        node = document.animation.evaluate(pose.seconds * 24).nodes[bone.id]
        x, y, _ = pose.points[joint]
        assert transform_point(node.world_matrix, node.length, 0) == pytest.approx(
            (128 + x * 1.2, 48 + y * 1.2)
        )


@pytest.mark.parametrize("profile", ["Human", "Quadruped"])
def test_length_locks_protect_connected_bones_and_preserve_other_frames(profile):
    """Corrections can pose a chain without resizing any protected anatomical segment."""
    import math

    analysis = specimen(profile)
    before = analysis.poses[0]
    original = segments(profile, before.points)
    locks = frozenset(original)
    joint = 7
    corrected = correct_pose(
        profile, before, joint, before.points[joint][0] + 20, before.points[joint][1] - 18, locks
    )
    after = segments(profile, corrected.points)
    assert corrected.points != before.points
    for role, (_, a, b) in original.items():
        _, c, d = after[role]
        assert math.dist(c[:2], d[:2]) == pytest.approx(math.dist(a[:2], b[:2]), abs=1e-6)
    reviewed = replace(analysis, poses=(corrected, *analysis.poses[1:]), locked_lengths=locks)
    assert reviewed.poses[1:] == analysis.poses[1:]
    cleaned = cleaned_poses(reviewed, 0.35, 0.9)[0]
    for joint in corrected.corrected:
        assert cleaned.points[joint] == corrected.points[joint]
    unlocked = correct_pose(profile, before, 7, 10, 20)
    assert unlocked.points[7] == (10, 20, 1)


@pytest.mark.parametrize("profile", ["Human", "Quadruped"])
@pytest.mark.parametrize("artwork", [False, True])
def test_single_image_creates_posed_rig_without_invented_animation(profile, artwork):
    """Stills produce rest bones and optional artwork in one reversible command."""
    from PIL import Image

    analysis = specimen(profile)
    analysis = replace(analysis, poses=(analysis.poses[0],))
    image = io.BytesIO()
    Image.new("RGBA", (320, 320), (100, 100, 100, 120)).save(image, format="PNG")
    document = DocumentService()
    document.new()
    baseline = document.project
    result = VideoRigService(document).create(
        analysis, artwork=image.getvalue() if artwork else b""
    )
    assert not result["clip_id"] and not result["scene_clip_id"]
    assert not document.scene.clips and not document.scene.timelines
    assert len(document.scene.skeletons[0].bones) == (11 if profile == "Human" else 10)
    assert bool(document.scene.meshes) == artwork
    assert len(document.history.undo_stack) == 1
    document.undo()
    assert document.project == baseline
