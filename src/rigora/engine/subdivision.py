"""Qt-free irregular image subdivision with explicit alpha boundaries and portable UVs."""

import math
import random
from collections.abc import Callable
from typing import Any

from rigora.domain.entities import Mesh, Vertex
from rigora.domain.mesh_geometry import grid_mesh
from rigora.domain.project import ProjectError


def subdivide(
    width: float,
    height: float,
    *,
    mode: str = "full",
    density: int = 4,
    alignment: int = 1,
    expand: float = 0,
    mask: Any = None,
    progress: Callable[[int], None] | None = None,
) -> Mesh:
    """Triangulate full bounds or a polygonal mask, retaining holes and disconnected islands.

    Density controls interior spacing; alignment adds boundary samples. Mask outlines
    retain topology with at most 0.7 source-pixel simplification. Expansion uses rounded
    joins in source pixels. Mask is Qt-free Shapely geometry supplied by the artwork adapter.
    Grid retains the established cell layout. Generated topology has no authored bindings.
    """
    if (
        not all(math.isfinite(v) and v > 0 for v in (width, height))
        or type(density) is not int
        or not 1 <= density <= 32
        or type(alignment) is not int
        or not 0 <= alignment <= 10
        or not math.isfinite(expand)
        or not 0 <= expand <= 100
        or mode not in ("full", "mask", "grid")
    ):
        raise ProjectError(
            "Subdivision requires Full/Mask/Grid and valid density/alignment/expand."
        )
    if mode == "grid":
        mesh = grid_mesh(width, height, density, density)
        if progress:
            progress(100)
        return mesh
    from shapely import MultiPoint, box, constrained_delaunay_triangles, delaunay_triangles

    boundary = box(0, 0, width, height)
    if mode == "mask":
        if mask is None or mask.is_empty:
            raise ProjectError("Mask subdivision needs artwork with visible pixels.")
        # Pixel stair steps create dense chains of tiny faces along otherwise smooth edges.
        # Topology preservation retains holes and disconnected/thin artwork components.
        outline_mask = mask.simplify(0.7, preserve_topology=True)
        boundary = outline_mask.buffer(expand, quad_segs=2, join_style="round").intersection(
            boundary
        )
    spacing = max(width, height) / (density * 2)
    rng = random.Random(0)
    columns, rows = max(2, math.ceil(width / spacing)), max(2, math.ceil(height / spacing))
    outline = box(0, 0, width, height).segmentize(spacing / (1 + alignment * 0.1))
    points = list(outline.exterior.coords)[:-1]
    for row in range(1, rows):
        for column in range(1, columns):
            x = (column + (0.35 if row % 2 else -0.15)) * width / columns
            y = row * height / rows
            x += rng.uniform(-0.2, 0.2) * width / columns
            y += rng.uniform(-0.25, 0.25) * height / rows
            points.append((x, y))
    # Intersections constrain every coarse triangle to the mask, rather than testing
    # centroids, which would silently remove narrow limbs and bridge holes/islands.
    coarse_faces = delaunay_triangles(MultiPoint(points))
    faces = list(coarse_faces.geoms) if mode == "full" else []
    if mode == "mask":
        boundary = boundary.segmentize(spacing / (1 + alignment * 0.25))
        for index, coarse in enumerate(coarse_faces.geoms):
            clipped = coarse.intersection(boundary)
            faces.extend(constrained_delaunay_triangles(clipped).geoms)
            if progress and index % 32 == 0:
                progress(round(80 * (index + 1) / len(coarse_faces.geoms)))
            if len(faces) > 20000:
                raise ProjectError(
                    "Mask is too detailed; simplify the source or use Full subdivision."
                )
    vertices: dict[tuple[float, float], Vertex] = {}
    triangles = []
    for face in faces:
        if face.area < 1e-9:
            continue
        keys = []
        for x, y in list(face.exterior.coords)[:3]:
            key = round(x, 9), round(y, 9)
            if key not in vertices:
                vertices[key] = Vertex(x=x, y=y, uv=(x / width, y / height))
            keys.append(vertices[key].id)
        if len(set(keys)) == 3:
            triangles.append((keys[0], keys[1], keys[2]))
    if progress:
        progress(100)
    return Mesh(
        vertices=tuple(vertices.values()),
        triangles=tuple(triangles),
        extra={"image_width": width, "image_height": height},
    )
