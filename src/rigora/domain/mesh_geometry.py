"""Qt-free mesh topology, interpolation and bounded skin influence utilities."""

import math
from collections.abc import Mapping
from dataclasses import replace

from rigora.domain.entities import Mesh, Vertex
from rigora.domain.validation import ProjectError

type Point = tuple[float, float]


def normalize_weights(values: Mapping[str, float], limit: int = 4) -> dict[str, float]:
    """Normalize positive influences, retaining the largest deterministic bounded subset."""
    if type(limit) is not int or not 1 <= limit <= 16:
        raise ProjectError("Influence limit must be from 1 to 16.")
    if any(
        type(value) not in (int, float) or not math.isfinite(value) or value < 0
        for value in values.values()
    ):
        raise ProjectError("Influences must be finite nonnegative numbers.")
    ordered = sorted(
        ((key, value) for key, value in values.items() if value > 0),
        key=lambda item: (-item[1], item[0]),
    )[:limit]
    total = sum(value for _, value in ordered)
    if not math.isfinite(total):
        raise ProjectError("Influence sum exceeds the finite range.")
    return {key: value / total for key, value in ordered} if total else {}


def area(a: Point, b: Point, c: Point) -> float:
    """Return twice the oriented triangle area for topology and hit testing."""
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def barycentric(point: Point, a: Point, b: Point, c: Point) -> tuple[float, float, float]:
    """Map a point into a nondegenerate triangle without requiring it to lie inside."""
    denominator = area(a, b, c)
    if abs(denominator) < 1e-12:
        raise ProjectError("Cannot interpolate a degenerate triangle.")
    first, second = area(point, b, c) / denominator, area(a, point, c) / denominator
    return first, second, 1 - first - second


def mesh_bounds(mesh: Mesh) -> tuple[float, float, float, float]:
    """Return positive local bounds, using stored image dimensions for an empty mesh."""
    if not mesh.vertices:
        width, height = mesh.extra.get("image_width", 1), mesh.extra.get("image_height", 1)
        return (
            0,
            0,
            float(width) if type(width) in (int, float) and 0 < width <= 8192 else 1,
            float(height) if type(height) in (int, float) and 0 < height <= 8192 else 1,
        )
    xs, ys = [v.x for v in mesh.vertices], [v.y for v in mesh.vertices]
    return min(xs), min(ys), max(1e-6, max(xs) - min(xs)), max(1e-6, max(ys) - min(ys))


def grid_mesh(width: float, height: float, columns: int = 4, rows: int = 4) -> Mesh:
    """Cover image bounds with a regular UV grid; density counts cells, not vertices."""
    if (
        not all(math.isfinite(v) and v > 0 for v in (width, height))
        or type(columns) is not int
        or type(rows) is not int
        or not 1 <= columns <= 32
        or not 1 <= rows <= 32
    ):
        raise ProjectError("Grid requires positive dimensions and 1–32 cells per axis.")
    vertices = tuple(
        Vertex(
            name=f"Vertex {y * (columns + 1) + x + 1}",
            x=width * x / columns,
            y=height * y / rows,
            uv=(x / columns, y / rows),
        )
        for y in range(rows + 1)
        for x in range(columns + 1)
    )
    triangles: list[tuple[str, str, str]] = []
    for y in range(rows):
        for x in range(columns):
            a = y * (columns + 1) + x
            b, c, d = a + 1, a + columns + 1, a + columns + 2
            triangles.extend(
                (
                    (vertices[a].id, vertices[b].id, vertices[d].id),
                    (vertices[a].id, vertices[d].id, vertices[c].id),
                )
            )
    return Mesh(
        vertices=vertices,
        triangles=tuple(triangles),
        extra={"image_width": width, "image_height": height},
    )


def move_vertices(mesh: Mesh, positions: Mapping[str, Point]) -> Mesh:
    """Move editable vertices atomically while rejecting collapsed or inverted existing faces."""
    if any(v.protected for v in mesh.vertices if v.id in positions):
        raise ProjectError("Unprotect selected vertices before moving them.")
    existing = {v.id: (v.x, v.y) for v in mesh.vertices}
    if not set(positions) <= existing.keys():
        raise ProjectError("The selected vertex no longer exists.")
    changed = {**existing, **positions}
    for face in mesh.triangles:
        before, after = area(*(existing[k] for k in face)), area(*(changed[k] for k in face))
        if not math.isfinite(after) or abs(after) < 1e-10 or before * after <= 0:
            raise ProjectError("This edit would collapse or invert a triangle.")
    result = replace(
        mesh,
        vertices=tuple(
            replace(v, x=positions[v.id][0], y=positions[v.id][1]) if v.id in positions else v
            for v in mesh.vertices
        ),
    )
    validate_embedding(result)
    return result


def validate_embedding(mesh: Mesh) -> None:
    """Reject positive-area overlap of base faces using an X-axis bounding-box sweep."""
    by_id = {v.id: (v.x, v.y) for v in mesh.vertices}
    faces = [tuple(by_id[k] for k in face) for face in mesh.triangles]
    boxes = [
        (
            min(p[0] for p in face),
            max(p[0] for p in face),
            min(p[1] for p in face),
            max(p[1] for p in face),
        )
        for face in faces
    ]
    active: list[int] = []
    for index in sorted(range(len(faces)), key=lambda i: boxes[i][0]):
        left, _, top, bottom = boxes[index]
        active = [i for i in active if boxes[i][1] > left + 1e-9]
        a = faces[index]
        for other in active:
            if boxes[other][3] <= top + 1e-9 or boxes[other][2] >= bottom - 1e-9:
                continue
            b = faces[other]
            crossing = any(
                area(a[i], a[(i + 1) % 3], b[j]) * area(a[i], a[(i + 1) % 3], b[(j + 1) % 3])
                < -1e-9
                and area(b[j], b[(j + 1) % 3], a[i]) * area(b[j], b[(j + 1) % 3], a[(i + 1) % 3])
                < -1e-9
                for i in range(3)
                for j in range(3)
            )
            centers = (tuple(sum(p[k] for p in face) / 3 for k in (0, 1)) for face in (a, b))
            center_a, center_b = centers
            contained = any(
                min(barycentric(p, *b)) > 1e-9 for p in (*a, (center_a[0], center_a[1]))
            ) or any(min(barycentric(p, *a)) > 1e-9 for p in (*b, (center_b[0], center_b[1])))
            if crossing or contained:
                raise ProjectError("This edit would create overlapping base triangles.")
        active.append(index)


def remove_vertices(mesh: Mesh, selected: set[str]) -> Mesh:
    """Remove vertices and adjacent faces while preserving source artwork."""
    if any(v.protected for v in mesh.vertices if v.id in selected):
        raise ProjectError("Unprotect selected vertices before deleting them.")
    return replace(
        mesh,
        vertices=tuple(v for v in mesh.vertices if v.id not in selected),
        triangles=tuple(face for face in mesh.triangles if not selected.intersection(face)),
    )


def insert_vertex(mesh: Mesh, x: float, y: float) -> tuple[Mesh, str]:
    """Split a face/shared edge with interpolated UVs/weights, or append a standalone vertex."""
    if any(math.hypot(v.x - x, v.y - y) < 1e-7 for v in mesh.vertices):
        raise ProjectError("A vertex already exists at this position.")
    by_id = {v.id: v for v in mesh.vertices}
    container = None
    weights = (0.0, 0.0, 0.0)
    for face in mesh.triangles:
        values = barycentric((x, y), *((by_id[key].x, by_id[key].y) for key in face))
        if min(values) >= -1e-8:
            container, weights = face, values
            break
    if container:
        sources = [by_id[k] for k in container]
        if all(v.protected for v in sources):
            raise ProjectError("Unprotect this region before inserting vertices.")
        uv = tuple(sum(weights[i] * sources[i].uv[axis] for i in range(3)) for axis in (0, 1))
        influence = normalize_weights(
            {
                bone: sum(weights[i] * sources[i].weights.get(bone, 0) for i in range(3))
                for bone in {key for v in sources for key in v.weights}
            }
        )
    else:
        width, height = (
            float(mesh.extra.get("image_width", 1)),
            float(mesh.extra.get("image_height", 1)),
        )
        uv, influence = (x / width, y / height), {}
    vertex = Vertex(
        name=f"Vertex {len(mesh.vertices) + 1}", x=x, y=y, uv=(uv[0], uv[1]), weights=influence
    )
    faces = list(mesh.triangles)
    if container:
        edge = {container[i] for i in range(3) if abs(weights[i]) > 1e-8}
        if len(edge) == 2:
            faces = []
            for face in mesh.triangles:
                if edge <= set(face):
                    for i in range(3):
                        a, b, c = face[i], face[(i + 1) % 3], face[(i + 2) % 3]
                        if {a, b} == edge:
                            faces.extend(((a, vertex.id, c), (vertex.id, b, c)))
                            break
                else:
                    faces.append(face)
        else:
            faces.remove(container)
            a, b, c = container
            faces.extend(((a, b, vertex.id), (b, c, vertex.id), (c, a, vertex.id)))
    return replace(mesh, vertices=(*mesh.vertices, vertex), triangles=tuple(faces)), vertex.id
