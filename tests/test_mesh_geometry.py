"""Topology edits preserve texture coordinates and normalized bounded influences."""

from dataclasses import replace

import pytest

from rigora.domain.entities import Mesh, Vertex
from rigora.domain.mesh_geometry import (
    grid_mesh,
    insert_vertex,
    move_vertices,
    normalize_weights,
    remove_vertices,
    validate_embedding,
)
from rigora.domain.project import ProjectError


def test_grid_insertion_edge_split_and_atomic_invalid_moves():
    mesh = grid_mesh(100, 80, 1, 1)
    assert len(mesh.vertices) == 4 and len(mesh.triangles) == 2
    inserted, key = insert_vertex(mesh, 50, 40)
    assert len(inserted.vertices) == 5 and len(inserted.triangles) == 4
    vertex = next(v for v in inserted.vertices if v.id == key)
    assert vertex.uv == pytest.approx((0.5, 0.5))
    with pytest.raises(ProjectError):
        move_vertices(mesh, {mesh.vertices[0].id: (100, 80)})
    removed = remove_vertices(inserted, {key})
    assert len(removed.vertices) == 4 and not removed.triangles


def test_influence_normalization_limits_and_zero_weights():
    assert normalize_weights({"one": 2, "two": 1, "three": 0.5}, 2) == pytest.approx(
        {"one": 2 / 3, "two": 1 / 3}
    )
    assert normalize_weights({"one": 0}) == {}
    with pytest.raises(ProjectError):
        normalize_weights({"one": float("nan")})


def test_overlapping_base_faces_and_protected_regions_are_rejected():
    vertices = tuple(
        Vertex(x=x, y=y) for x, y in ((0, 0), (100, 0), (0, 100), (10, 10), (90, 10), (10, 90))
    )
    mesh = Mesh(
        vertices=vertices,
        triangles=(
            (vertices[0].id, vertices[1].id, vertices[2].id),
            (vertices[3].id, vertices[4].id, vertices[5].id),
        ),
    )
    with pytest.raises(ProjectError, match="overlapping"):
        validate_embedding(mesh)
    grid = grid_mesh(100, 100, 2, 2)
    validate_embedding(grid)
    grid = replace(grid, vertices=tuple(replace(v, protected=True) for v in grid.vertices))
    with pytest.raises(ProjectError, match="Unprotect"):
        insert_vertex(grid, 10, 15)
