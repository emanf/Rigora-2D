"""Coverage, topology and retained rig behavior for Full/Mask/Grid subdivision."""

import io
import math
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from shapely import Polygon, box, union_all

from rigora.application_services.documents import DocumentService
from rigora.application_services.meshes import MeshService
from rigora.application_services.rigging import RigService
from rigora.application_services.skinning import SkinService
from rigora.domain.mesh_geometry import validate_embedding
from rigora.domain.project import ProjectError
from rigora.engine.subdivision import subdivide
from rigora.infrastructure.artwork_mask import artwork_mask


def coverage(mesh):
    """Return a geometric union for independent coverage and overlap checks."""
    points = {v.id: (v.x, v.y) for v in mesh.vertices}
    faces = [Polygon([points[k] for k in face]) for face in mesh.triangles]
    combined = union_all(faces)
    assert sum(f.area for f in faces) == pytest.approx(combined.area)
    validate_embedding(mesh)
    return combined


def test_full_irregular_triangles_cover_image_and_keep_normalized_uvs():
    """Interior points leave rectangular rows while every source pixel remains covered."""
    low = subdivide(200, 300, density=2)
    high = subdivide(200, 300, density=4)
    assert len(high.vertices) > len(low.vertices)
    assert coverage(high).symmetric_difference(box(0, 0, 200, 300)).area < 1e-6
    assert any(0 < v.x < 200 and not math.isclose(v.x % 25, 0) for v in high.vertices)
    for v in high.vertices:
        assert v.uv == pytest.approx((v.x / 200, v.y / 300))
    for corner in (v for v in high.vertices if v.x in (0, 200) and v.y in (0, 300)):
        neighbors = {key for face in high.triangles if corner.id in face for key in face}
        assert len(neighbors - {corner.id}) <= 3
    assert len(subdivide(200, 300, mode="grid", density=4).vertices) == 25


def test_mask_preserves_holes_islands_and_thin_parts_and_expand():
    """Constrained clipping covers a one-pixel bridge and isolated speck without filling holes."""
    image = Image.new("RGBA", (40, 60))
    image.paste("white", (3, 3, 30, 40))
    image.paste((0, 0, 0, 0), (10, 10, 20, 20))
    image.paste("white", (15, 40, 16, 58))
    image.putpixel((38, 58), (255, 255, 255, 255))
    data = io.BytesIO()
    image.save(data, format="PNG")
    mask = artwork_mask(data.getvalue())
    result = coverage(subdivide(40, 60, mode="mask", mask=mask, density=3))
    assert result.symmetric_difference(mask).area < 1e-6
    expanded = coverage(subdivide(40, 60, mode="mask", mask=mask, density=3, expand=2))
    assert expanded.area > result.area
    assert expanded.covers(result)
    with pytest.raises(ProjectError, match="visible"):
        subdivide(40, 60, mode="mask", mask=Polygon())


def test_mask_outline_reduces_pixel_steps_without_losing_holes_or_islands():
    """Raster contours stay within a subpixel tolerance without a dense border of tiny faces."""
    from shapely import get_num_coordinates

    image = Image.new("RGBA", (256, 256))
    drawing = ImageDraw.Draw(image)
    drawing.ellipse((20, 20, 220, 220), fill="white")
    drawing.ellipse((85, 85, 155, 155), fill=(0, 0, 0, 0))
    drawing.rectangle((235, 235, 236, 236), fill="white")
    data = io.BytesIO()
    image.save(data, format="PNG")
    mask = artwork_mask(data.getvalue())
    mesh = subdivide(256, 256, mode="mask", mask=mask, density=4)
    result = coverage(mesh)
    assert result.boundary.hausdorff_distance(mask.boundary) <= 0.7 + 1e-7
    assert len(result.geoms) == len(mask.geoms) == 2
    assert sum(len(p.interiors) for p in result.geoms) == 1
    assert len(mesh.vertices) < get_num_coordinates(mask) * 0.75


def test_mask_expansion_rounds_sharp_tips_instead_of_growing_large_spikes():
    """Expand adds the requested padding without mitre spikes at narrow silhouette corners."""
    mask = Polygon(((20, 20), (280, 150), (20, 21)))
    result = coverage(subdivide(320, 300, mode="mask", mask=mask, density=4, expand=10))
    assert result.covers(mask)
    assert result.bounds[2] <= 290 + 1e-7
    assert mask.buffer(10.001).covers(result)


def test_subdivision_preserves_skin_and_pins_with_atomic_undo_and_save(tmp_path):
    """New topology retains the skin stage and exact anchors; failed batches publish nothing."""
    doc = DocumentService()
    doc.open(Path("examples/image-import-example.rigora"))
    service = SkinService(doc)
    mesh = service.scene.meshes[0]
    root = service.scene.skeletons[0].bones[0].id
    point = (mesh.vertices[0].x, mesh.vertices[0].y)
    service.add_area_pin(mesh.id, point, root)
    baseline = doc.project
    bindings = tuple(d for d in service.scene.deformers if d.kind == "skinning")
    service.subdivide((mesh.id,), mode="full", density=3, discard_edits=True)
    result = service.mesh(mesh.id)
    assert tuple(d for d in service.scene.deformers if d.kind == "skinning") == bindings
    assert all(sum(v.weights.values()) == pytest.approx(1) for v in result.vertices)
    assert result.extra["area_pins"][0]["vertex_id"] in {v.id for v in result.vertices}
    assert not doc.animation.pose.warnings
    doc.save(tmp_path / "triangles.rigora")
    loaded = DocumentService()
    loaded.open(tmp_path / "triangles.rigora")
    assert loaded.project == doc.project
    doc.undo()
    assert doc.project == baseline
    with pytest.raises(ProjectError):
        MeshService(doc).subdivide((mesh.id, "missing"), mode="full", density=4, discard_edits=True)
    assert doc.project == baseline


def test_area_pin_follows_character_root_and_releases_without_reweighting():
    """A root pin resists child motion and still travels with its character, unlike world pins."""
    from dataclasses import replace

    doc = DocumentService()
    doc.open(Path("examples/image-import-example.rigora"))
    skin = SkinService(doc)
    mesh = skin.scene.meshes[0]
    root, child = skin.scene.skeletons[0].bones
    point = (mesh.vertices[-1].x, mesh.vertices[-1].y)
    key = skin.add_area_pin(mesh.id, point, root.id, radius=100)
    index = next(i for i, v in enumerate(skin.mesh(mesh.id).vertices) if v.id == key)
    rig = RigService(doc)
    before = doc.animation.pose.meshes[mesh.id].positions[index]
    rig.update(child.id, transform=replace(child.transform, rotation=45))
    assert doc.animation.pose.meshes[mesh.id].positions[index] == pytest.approx(before)
    rig.update(root.id, transform=replace(root.transform, x=root.transform.x + 25))
    assert doc.animation.pose.meshes[mesh.id].positions[index] == pytest.approx(
        (before[0] + 25, before[1])
    )
    skin.remove_area_pins(mesh.id, (key,))
    assert not skin.mesh(mesh.id).extra["area_pins"]
    assert doc.animation.pose.meshes[mesh.id].positions[index] != pytest.approx(
        (before[0] + 25, before[1])
    )
