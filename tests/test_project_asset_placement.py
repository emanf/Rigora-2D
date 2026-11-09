"""Shared pointer placement centers artwork and pivots without changing source bytes."""

from pathlib import Path

import pytest
from test_asset_pipeline import make_ora

from rigora.application_services.asset_pipeline import AssetPipeline
from rigora.application_services.characters import CharacterService
from rigora.application_services.documents import DocumentService
from rigora.application_services.scene_editing import SceneEditingService
from rigora.domain.geometry import transform_point
from rigora.domain.project import ProjectError


@pytest.mark.parametrize("layered", (False, True))
@pytest.mark.parametrize("parented", (False, True))
def test_source_placement_centers_bounds_and_pivot_and_preserves_parent_and_undo(
    tmp_path, layered, parented
):
    """Raster layers and SVGs share the same world point under transformed destination folders."""
    doc = DocumentService()
    doc.new()
    pipeline = AssetPipeline(doc)
    if layered:
        path = tmp_path / "layers.ora"
        make_ora(path)
        key = pipeline.layered(path, place=False)["source_asset_id"]
    else:
        key = pipeline.register_image_bytes(
            "Prop.svg", Path("assets/examples/prop.svg").read_bytes()
        )
    parent = CharacterService(doc).create_object(name="Parent") if parented else None
    if parent:
        SceneEditingService(doc).transform(
            (parent,), dx=40, dy=25, rotation=17, scale_x=1.3, scale_y=0.7
        )
    before, count = doc.project, len(doc.history.undo_stack)
    result = pipeline.place_source(key, parent=parent, position=(-65.5, 145.25))
    pose = doc.animation.pose
    points = [
        transform_point(pose.nodes[mesh.object_id].world_matrix, *point)
        for key, mesh in pose.meshes.items()
        if key in result["mesh_ids"]
        for point in mesh.positions
    ]
    center = tuple((min(p[i] for p in points) + max(p[i] for p in points)) / 2 for i in (0, 1))
    assert center == pytest.approx((-65.5, 145.25))
    root = result["root_ids"][0]
    node = pose.nodes[root]
    assert transform_point(
        node.world_matrix, node.local.pivot_x, node.local.pivot_y
    ) == pytest.approx(center)
    assert SceneEditingService(doc).record(root).parent_id == parent
    assert len(doc.history.undo_stack) == count + 1
    doc.undo()
    assert doc.project == before


def test_invalid_placement_rolls_back_source_instantiation_and_parent_promotion():
    """Rejected coordinates cannot leave a partial resource or converted original Object."""
    doc = DocumentService()
    doc.new()
    pipeline = AssetPipeline(doc)
    key = pipeline.register_image_bytes("Prop.svg", Path("assets/examples/prop.svg").read_bytes())
    mesh = pipeline.instantiate_asset(key)
    root = str(pipeline.mesh(mesh).object_id)
    before, count = doc.project, len(doc.history.undo_stack)
    with pytest.raises(ProjectError):
        pipeline.place_source(key, parent=root, position=(float("nan"), 0))
    assert doc.project == before and len(doc.history.undo_stack) == count
