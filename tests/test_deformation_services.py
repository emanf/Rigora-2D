"""Undoable authored geometry, normalized brushes and portable motion round trips."""

from dataclasses import replace

import pytest

from rigora.application_services.commands import ProjectPatch
from rigora.application_services.deformation_examples import (
    EXAMPLE_STYLES,
    populate_deformation_example,
)
from rigora.application_services.deformation_motion import DeformationMotionService
from rigora.application_services.documents import DocumentService
from rigora.application_services.skinning import weight_brush
from rigora.domain.entities import Bone
from rigora.domain.mesh_geometry import grid_mesh
from rigora.domain.project import ProjectError
from rigora.infrastructure.deformation_clips import read_motion


def document():
    """Create an independent unsaved document for each example and authoring test."""
    doc = DocumentService()
    doc.new()
    return doc


@pytest.mark.parametrize("style", EXAMPLE_STYLES)
def test_original_example_changes_real_geometry_and_roundtrips(style, tmp_path):
    doc = document()
    mesh_id = populate_deformation_example(doc, style)
    first = doc.animation.evaluate(0)
    changed = doc.animation.evaluate(24)
    assert not first.warnings and not changed.warnings
    assert first.meshes[mesh_id].positions != changed.meshes[mesh_id].positions
    original = doc.read_asset(first.meshes[mesh_id].asset_id)
    target = tmp_path / "study.rigora"
    doc.save(target)
    reopened = DocumentService()
    reopened.open(target)
    assert reopened.animation.evaluate(24).to_dict() == changed.to_dict()
    assert reopened.read_asset(first.meshes[mesh_id].asset_id) == original
    doc.undo()
    assert not doc.project.assets and not doc.project.scenes[0].meshes
    doc.redo()
    assert doc.animation.evaluate(24).meshes[mesh_id].positions == changed.meshes[mesh_id].positions


def test_stack_controls_keys_reuse_density_and_history(tmp_path):
    doc = document()
    mesh_id = populate_deformation_example(doc, "Character torso")
    service = DeformationMotionService(doc)
    stage = service.scene.deformers[0]
    controls = stage.parameters["controls"]
    service.controls(stage.id, {0: (25, -10), 1: (12, 5)})
    assert service.stage(stage.id).parameters["controls"][0] == (25, -10)
    doc.undo()
    assert service.stage(stage.id).parameters["controls"] == controls
    service.key(stage.id, "parameters.controls.4.0", 12, 35)
    assert (
        doc.animation.evaluate(12).meshes[mesh_id].positions
        != doc.animation.evaluate(0).meshes[mesh_id].positions
    )
    service.key(stage.id, "parameters.controls.4.0", 12, 0, delete=True)
    assert len(service.scene.timelines[0].tracks[0].keyframes) == 4
    bundle = tmp_path / "motion.rigmotion"
    service.export_clip(stage.id, bundle)
    with pytest.raises(FileExistsError):
        service.export_clip(stage.id, bundle)
    expected = doc.animation.evaluate(24).meshes[mesh_id].positions
    second = service.import_image_bytes(
        "other.svg", doc.read_asset(service.mesh(mesh_id).asset_id), 6, 10
    )
    new_stage, clip = service.import_clip(second, bundle)
    assert new_stage != stage.id and doc.animation.evaluator.clip.id == clip
    assert doc.animation.evaluate(24).meshes[second].positions == expected
    snapshot = doc.project
    with pytest.raises(ProjectError, match="confirm"):
        service.regenerate(second, 2, 2)
    assert doc.project is snapshot
    service.regenerate(second, 2, 2, discard_edits=True)
    assert len(service.mesh(second).vertices) == 9
    assert not any(d.id == new_stage for d in service.scene.deformers)
    doc.undo()
    assert len(service.mesh(second).vertices) == 77
    service.reorder(new_stage, -1)
    service.update(new_stage, enabled=False)
    assert not service.stage(new_stage).enabled
    service.remove(new_stage)
    assert not any(t.owner_id == new_stage for tl in service.scene.timelines for t in tl.tracks)


def test_motion_import_rolls_back_on_invalid_channels():
    doc = document()
    key = populate_deformation_example(doc)
    service = DeformationMotionService(doc)
    data = service.clip_data(service.scene.deformers[0].id)
    data["tracks"][0]["property_path"] = "parameters.no_such_value"
    before = doc.project
    with pytest.raises(ProjectError):
        service.apply_clip(key, data)
    assert doc.project is before


def test_brush_add_subtract_smooth_normalize_and_protection():
    a, b = Bone(), Bone()
    mesh = grid_mesh(100, 100, 1, 1)
    mesh = replace(
        mesh,
        vertices=tuple(
            replace(v, weights={a.id: 0.6, b.id: 0.4}, protected=i == 3)
            for i, v in enumerate(mesh.vertices)
        ),
    )
    points = {v.id: (v.x, v.y) for v in mesh.vertices}
    added = weight_brush(mesh, points, (0, 0), b.id, 200, 0.3, "add")
    assert added.vertices[0].weights[b.id] == pytest.approx(0.7)
    assert added.vertices[3] == mesh.vertices[3]
    sub = weight_brush(added, points, (0, 0), b.id, 200, 0.2, "subtract")
    assert sub.vertices[0].weights[b.id] == pytest.approx(0.5)
    smooth = weight_brush(sub, points, (0, 0), b.id, 200, 1, "smooth")
    assert smooth.vertices[0].weights != sub.vertices[0].weights
    limited = weight_brush(smooth, points, (0, 0), b.id, 200, 1, "normalize", 1)
    assert len(limited.vertices[0].weights) == 1
    assert all(sum(v.weights.values()) == pytest.approx(1) for v in limited.vertices)


def test_nested_command_group_savepoint_preserves_outer_commands():
    doc = document()
    original = doc.project
    with doc.transaction("Compound service operation"):
        doc.execute(ProjectPatch("Outer rename", {"name": original.name}, {"name": "Outer"}))
        with pytest.raises(RuntimeError), doc.command_group("Failed sub-operation"):
            doc.execute(ProjectPatch("Inner rename", {"name": "Outer"}, {"name": "Lost"}))
            raise RuntimeError("abort")
        assert doc.project.name == "Outer"
    assert len(doc.history.undo_stack) == 1
    doc.undo()
    assert doc.project == original


def test_motion_rejects_ambiguous_json_and_incompatible_topology(tmp_path):
    target = tmp_path / "bad.rigmotion"
    target.write_text('{"version":1,"version":2}', encoding="utf-8")
    with pytest.raises(ProjectError, match="Duplicate"):
        read_motion(target)
    doc = document()
    mesh_id = populate_deformation_example(doc, "Bending")
    service = DeformationMotionService(doc)
    data = service.clip_data(service.scene.deformers[0].id)
    data["topology"] = []
    with pytest.raises(ProjectError, match="topology"):
        service.apply_clip(mesh_id, data)


def test_unknown_deformer_can_be_disabled_without_losing_its_data():
    doc = document()
    populate_deformation_example(doc)
    service = DeformationMotionService(doc)
    original = service.scene.deformers[0]
    unknown = replace(original, kind="future.extension")
    service.commit("Retain extension", deformers=(unknown,))
    assert doc.animation.pose.warnings
    service.update(unknown.id, enabled=False)
    assert not doc.animation.pose.warnings
    assert service.stage(unknown.id).parameters == unknown.parameters
    doc.undo()
    assert service.stage(unknown.id).enabled
