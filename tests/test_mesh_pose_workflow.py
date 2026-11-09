"""Persistent dense surface sculpting and seeded mesh animation through shared services."""

import pytest
from PySide6.QtCore import QObject

from rigora.application_services.deformation import DeformationPreset
from rigora.application_services.deformation_motion import DeformationMotionService
from rigora.application_services.documents import DocumentService
from rigora.domain.mesh_geometry import validate_embedding
from rigora.presentation.viewmodels.meshes import MeshViewModel
from rigora.resources import asset_path


def test_dense_sculpt_commit_matches_preview_then_animates_and_roundtrips(tmp_path):
    """A folded surface retains valid rest triangles, two distinct poses and interpolated keys."""
    doc = DocumentService()
    doc.new()
    service = DeformationMotionService(doc)
    mesh_id = service.import_image(asset_path("examples/prop.svg"))
    service.subdivide((mesh_id,), mode="full", density=12, discard_edits=True)
    parent = QObject()
    model = MeshViewModel(parent)
    model.bind(doc)
    model.select_mesh(mesh_id)
    mesh = model.mesh
    vertex = min(mesh.vertices, key=lambda v: (v.x - 100) ** 2 + (v.y - 100) ** 2)
    index = next(i for i, v in enumerate(mesh.vertices) if v.id == vertex.id)
    count = len(doc.history.undo_stack)
    model.preview_values = {(vertex.id, "x"): vertex.x + 90, (vertex.id, "y"): vertex.y + 10}
    first = model.pose.meshes[mesh_id].positions
    model.finish_preview()
    assert not model.error
    assert model.pose.meshes[mesh_id].positions == first
    assert model.mesh == mesh
    validate_embedding(model.mesh)
    assert len(doc.history.undo_stack) == count + 1
    doc.undo()
    assert doc.animation.pose.meshes[mesh_id].positions != first
    doc.redo()
    assert doc.animation.pose.meshes[mesh_id].positions == first

    # Exercise a complete surface pose larger than 512 scalar channels.
    assert len(mesh.vertices) * 2 > 512
    model.key_pose()
    assert not model.error
    doc.animation.seek(20)
    model.set_auto_key(True)
    model.preview_values = {(vertex.id, "x"): vertex.x + 30}
    last = model.pose.meshes[mesh_id].positions
    model.finish_preview()
    assert not model.error
    assert model.pose.meshes[mesh_id].positions == last
    assert doc.animation.evaluate(0).meshes[mesh_id].positions == first
    middle = doc.animation.evaluate(10).meshes[mesh_id].positions
    assert middle[index][0] == pytest.approx((first[index][0] + last[index][0]) / 2)
    doc.save(tmp_path / "sculpt.rigora")
    reopened = DocumentService()
    reopened.open(tmp_path / "sculpt.rigora")
    assert reopened.animation.evaluate(10).meshes[mesh_id].positions == middle


def test_first_later_deformation_key_keeps_initial_pose():
    """Explicit numeric keys seed the initial pose just like Auto key gestures."""
    doc = DocumentService()
    doc.new()
    service = DeformationMotionService(doc)
    mesh_id = service.import_image(asset_path("examples/prop.svg"))
    v = service.mesh(mesh_id).vertices[12]
    service.key(v.id, "x", 20, v.x + 40)
    assert doc.animation.evaluate(0).meshes[mesh_id].positions[12][0] == v.x
    assert doc.animation.evaluate(10).meshes[mesh_id].positions[12][0] == v.x + 20


def test_dense_auto_key_after_static_first_pose_and_repeated_sculpt():
    """Auto key can start at a later frame and record every dot in one undo command."""
    doc = DocumentService()
    doc.new()
    service = DeformationMotionService(doc)
    mesh_id = service.import_image(asset_path("examples/prop.svg"), 20, 20)
    parent = QObject()
    model = MeshViewModel(parent)
    model.bind(doc)
    model.select_mesh(mesh_id)
    initial = model.pose.meshes[mesh_id].positions
    doc.animation.seek(20)
    model.set_auto_key(True)
    count = len(doc.history.undo_stack)
    model.preview_values = {(v.id, "x"): v.x + 15 for v in model.mesh.vertices}
    model.preview_values.update({(v.id, "y"): v.y + 10 for v in model.mesh.vertices})
    model.finish_preview()
    assert not model.error
    assert len(doc.history.undo_stack) == count + 1
    assert doc.animation.evaluate(0).meshes[mesh_id].positions == initial
    assert doc.animation.evaluate(10).meshes[mesh_id].positions[0] == (7.5, 5)
    assert doc.animation.evaluate(20).meshes[mesh_id].positions[0] == (15, 10)


def test_existing_mesh_animation_records_new_vertices_without_rewriting_first_pose():
    """Continuing an animated mesh keys newly touched dots and axes at the playhead."""
    doc = DocumentService()
    doc.new()
    service = DeformationMotionService(doc)
    mesh_id = service.import_image(asset_path("examples/prop.svg"))
    parent = QObject()
    model = MeshViewModel(parent)
    model.bind(doc)
    model.select_mesh(mesh_id)
    first, second = model.mesh.vertices[:2]
    service.key(first.id, "x", 0, first.x)
    initial = model.pose.meshes[mesh_id].positions
    doc.animation.seek(20)
    assert not model.auto_key
    model.preview_values = {(second.id, "y"): second.y + 30}
    model.finish_preview()
    assert not model.error
    assert doc.animation.evaluate(0).meshes[mesh_id].positions == initial
    assert doc.animation.evaluate(10).meshes[mesh_id].positions[1][1] == second.y + 15
    assert doc.animation.evaluate(20).meshes[mesh_id].positions[1][1] == second.y + 30


def test_sculpt_layer_accumulates_second_edit_and_reusable_motion_remaps_offsets(tmp_path):
    """Static sculpt deltas accumulate, and portable clips never retain source vertex UUIDs."""
    doc = DocumentService()
    doc.new()
    service = DeformationMotionService(doc)
    mesh_id = service.import_image(asset_path("examples/prop.svg"))
    v = service.mesh(mesh_id).vertices[12]
    service.sculpt_vertices(mesh_id, {v.id: (v.x + 200, v.y)})
    first = doc.animation.pose.meshes[mesh_id].positions[12]
    service.sculpt_vertices(mesh_id, {v.id: (v.x + 10, v.y + 5)})
    assert doc.animation.pose.meshes[mesh_id].positions[12] == (first[0] + 10, first[1] + 5)
    stage = next(d for d in service.scene.deformers if d.kind == "mesh_sculpt")
    service.key(v.id, "x", 20, v.x + 30)
    path = tmp_path / "sculpt.rigmotion"
    service.export_clip(stage.id, path)
    expected = doc.animation.evaluate(10).meshes[mesh_id].positions
    target = service.import_image(asset_path("examples/prop.svg"))
    service.import_clip(target, path)
    assert doc.animation.evaluate(10).meshes[target].positions == expected


def test_sculpt_after_reordering_stages_still_matches_preview():
    """Reordered displacements must not turn a pre-stack gesture into a post-stack jump."""
    doc = DocumentService()
    doc.new()
    service = DeformationMotionService(doc)
    mesh_id = service.import_image(asset_path("examples/prop.svg"))
    vertex = service.mesh(mesh_id).vertices[12]
    service.sculpt_vertices(mesh_id, {vertex.id: (vertex.x + 200, vertex.y)})
    shape = next(d for d in service.scene.deformers if d.kind == "mesh_sculpt")
    service.add(mesh_id, DeformationPreset("Turn", "transform", {"rotation": 90}))
    service.reorder(shape.id, 1)
    parent = QObject()
    model = MeshViewModel(parent)
    model.bind(doc)
    model.select_mesh(mesh_id)
    model.preview_values = {(vertex.id, "x"): vertex.x + 10}
    preview = model.pose.meshes[mesh_id].positions
    model.finish_preview()
    assert not model.error
    for expected, actual in zip(preview, model.pose.meshes[mesh_id].positions, strict=True):
        assert actual == pytest.approx(expected)
