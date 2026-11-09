"""Ordered Qt-free mesh deformation with immutable output and atomic stage diagnostics."""

import copy
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from rigora.domain.entities import Deformer, Mesh
from rigora.domain.geometry import Matrix, affine, inverse, multiply, transform_point
from rigora.domain.mesh_geometry import Point, mesh_bounds
from rigora.domain.project import Scene
from rigora.domain.validation import ProjectError, frozen_extra, json_copy
from rigora.engine.sampling import EvaluationError, number
from rigora.engine.state import MeshPose, NodePose

IDENTITY: Matrix = (1, 0, 0, 1, 0, 0)


def default_parameters(kind: str, mesh: Mesh) -> dict[str, Any]:
    """Define explicit neutral parameters for built-in kinds without changing authoring records."""
    x, y, width, height = mesh_bounds(mesh)
    parameters: dict[str, Any] = {"intensity": 1.0, "bounds": [x, y, width, height]}
    if kind in ("ffd", "lattice"):
        parameters.update(columns=3, rows=3)
    elif kind in ("transform", "vertex_offset"):
        parameters.update(
            x=0.0,
            y=0.0,
            rotation=0.0,
            scale_x=1.0,
            scale_y=1.0,
            pivot_x=x + width / 2,
            pivot_y=y + height / 2,
        )
    elif kind == "pin":
        parameters.update(radius=0.0, pins={})
    elif kind == "mesh_sculpt":
        parameters["offsets"] = {}
    elif kind in ("bend", "bulge", "twist", "squash_stretch"):
        parameters["amount"] = 1.0 if kind == "squash_stretch" else 0.0
    return parameters


@dataclass(frozen=True)
class DeformationContext:
    """Read-only stage inputs in object-local space with current evaluated skeletal transforms."""

    mesh: Mesh
    points: tuple[Point, ...]
    parameters: Mapping[str, Any]
    nodes: Mapping[str, NodePose]

    def __post_init__(self) -> None:
        """Freeze nested parameter containers before handing a stage to a solver."""
        object.__setattr__(self, "parameters", frozen_extra(self.parameters))

    def scalar(self, key: str, default: float = 0) -> float:
        """Read a finite numeric parameter with an actionable error label."""
        return number(self.parameters.get(key, default), key)

    def bounds(self) -> tuple[float, float, float, float]:
        """Validate the fixed local field rectangle independently of animated geometry."""
        raw = self.parameters.get("bounds", mesh_bounds(self.mesh))
        if not isinstance(raw, (tuple, list)) or len(raw) != 4:
            raise EvaluationError("Deformation bounds require x, y, width and height.")
        x, y, width, height = (number(v, "Field bounds") for v in raw)
        if min(width, height) <= 1e-9:
            raise EvaluationError("Deformation bounds must have positive dimensions.")
        return x, y, width, height


type DeformerSolver = Callable[[DeformationContext], tuple[Point, ...]]


def lattice_controls(parameters: Mapping[str, Any]) -> tuple[int, int, tuple[Point, ...]]:
    """Validate fixed grid dimensions and local displacement controls with bounded complexity."""
    columns, rows = parameters.get("columns", 3), parameters.get("rows", 3)
    if (
        type(columns) is not int
        or type(rows) is not int
        or not 2 <= columns <= 8
        or not 2 <= rows <= 8
    ):
        raise EvaluationError("FFD/lattice grids need 2–8 controls per axis.")
    raw = parameters.get("controls", [(0, 0)] * (columns * rows))
    if not isinstance(raw, (tuple, list)) or len(raw) != columns * rows:
        raise EvaluationError("Control count must match the lattice rows and columns.")
    controls = []
    for point in raw:
        if not isinstance(point, (tuple, list)) or len(point) != 2:
            raise EvaluationError("Each lattice control requires X/Y displacements.")
        controls.append((number(point[0], "Control X"), number(point[1], "Control Y")))
    return columns, rows, tuple(controls)


def free_form(context: DeformationContext) -> tuple[Point, ...]:
    """Evaluate a tensor-product Bernstein displacement field over normalized mesh bounds."""
    columns, rows, controls = lattice_controls(context.parameters)
    x0, y0, width, height = context.bounds()
    active = [
        (index % columns, index // columns, dx, dy)
        for index, (dx, dy) in enumerate(controls)
        if dx != 0 or dy != 0
    ]
    if not active:
        return context.points
    coefficients_x = tuple(math.comb(columns - 1, i) for i in range(columns))
    coefficients_y = tuple(math.comb(rows - 1, i) for i in range(rows))
    result = []
    for x, y in context.points:
        u, v = min(1.0, max(0.0, (x - x0) / width)), min(1.0, max(0.0, (y - y0) / height))
        bx = [coefficients_x[i] * u**i * (1 - u) ** (columns - 1 - i) for i in range(columns)]
        by = [coefficients_y[i] * v**i * (1 - v) ** (rows - 1 - i) for i in range(rows)]
        dx = dy = 0.0
        for column, row, offset_x, offset_y in active:
            weight = bx[column] * by[row]
            dx += offset_x * weight
            dy += offset_y * weight
        result.append((x + dx, y + dy))
    return tuple(result)


def lattice(context: DeformationContext) -> tuple[Point, ...]:
    """Evaluate piecewise bilinear displacement, keeping each control locally editable."""
    columns, rows, controls = lattice_controls(context.parameters)
    x0, y0, width, height = context.bounds()
    result = []
    for x, y in context.points:
        u = min(columns - 1.0, max(0.0, (x - x0) / width * (columns - 1)))
        v = min(rows - 1.0, max(0.0, (y - y0) / height * (rows - 1)))
        column, row = min(columns - 2, int(u)), min(rows - 2, int(v))
        a, b = u - column, v - row
        offsets = [
            controls[row * columns + column],
            controls[row * columns + column + 1],
            controls[(row + 1) * columns + column],
            controls[(row + 1) * columns + column + 1],
        ]
        weights = ((1 - a) * (1 - b), a * (1 - b), (1 - a) * b, a * b)
        result.append(
            (
                x + sum(p[0] * w for p, w in zip(offsets, weights, strict=True)),
                y + sum(p[1] * w for p, w in zip(offsets, weights, strict=True)),
            )
        )
    return tuple(result)


def transform(context: DeformationContext) -> tuple[Point, ...]:
    """Apply a local affine deformer, including vertex-weighted translation through masks."""
    p = context.scalar
    matrix = affine(
        p("x"), p("y"), p("rotation"), p("scale_x", 1), p("scale_y", 1), p("pivot_x"), p("pivot_y")
    )
    return tuple(transform_point(matrix, *point) for point in context.points)


def sculpt(context: DeformationContext) -> tuple[Point, ...]:
    """Evaluate bend, bulge, twist or area-preserving squash/stretch from explicit parameters."""
    kind = context.parameters.get("_kind")
    x0, y0, width, height = context.bounds()
    cx, cy = x0 + width / 2, y0 + height / 2
    amount = context.scalar("amount", 1 if kind == "squash_stretch" else 0)
    result = []
    for x, y in context.points:
        dx, dy = x - cx, y - cy
        if kind == "bend":
            angle = math.radians(amount)
            if abs(angle) < 1e-6:
                result.append((x, y))
                continue
            radius, theta = height / angle, angle * dy / height
            point = (
                cx + (radius + dx) * math.cos(theta) - radius,
                cy + (radius + dx) * math.sin(theta),
            )
        elif kind == "bulge":
            point = (
                cx + dx * (1 + amount * math.sin(math.pi * min(1, max(0, (y - y0) / height)))),
                y,
            )
        elif kind == "twist":
            angle = math.radians(amount) * dy / height
            point = (
                cx + dx * math.cos(angle) - dy * math.sin(angle),
                cy + dx * math.sin(angle) + dy * math.cos(angle),
            )
        else:
            if not 0.05 <= amount <= 20:
                raise EvaluationError("Squash/stretch scale must be from 0.05 to 20.")
            point = (cx + dx / amount, cy + dy * amount)
        result.append(point)
    return tuple(result)


def pins(context: DeformationContext) -> tuple[Point, ...]:
    """Move selected local anchors with optional smooth radial falloff onto nearby vertices."""
    raw = context.parameters.get("pins", {})
    if not isinstance(raw, Mapping):
        raise EvaluationError("Pins must be a vertex-to-position mapping.")
    indices = {v.id: i for i, v in enumerate(context.mesh.vertices)}
    radius = context.scalar("radius")
    if radius < 0:
        raise EvaluationError("Pin radius cannot be negative.")
    result = list(context.points)
    anchors: dict[int, Point] = {}
    for key, value in raw.items():
        if key not in indices or not isinstance(value, Mapping):
            raise EvaluationError("Pin references a missing vertex or invalid anchor.")
        index = indices[key]
        source = context.points[index]
        x, y = number(value.get("x"), "Pin X"), number(value.get("y"), "Pin Y")
        strength = number(value.get("strength", 1), "Pin strength")
        if not 0 <= strength <= 1:
            raise EvaluationError("Pin strength must be between zero and one.")
        anchors[index] = (
            source[0] + (x - source[0]) * strength,
            source[1] + (y - source[1]) * strength,
        )
        for i, point in enumerate(context.points):
            distance = math.hypot(point[0] - source[0], point[1] - source[1])
            influence = (
                1.0 if i == index else max(0.0, 1 - distance / radius) ** 2 if radius else 0.0
            )
            current = result[i]
            result[i] = (
                current[0] + (x - source[0]) * influence * strength,
                current[1] + (y - source[1]) * influence * strength,
            )
    for index, target in anchors.items():
        result[index] = target
    return tuple(result)


def skinning(context: DeformationContext) -> tuple[Point, ...]:
    """Blend explicit current-bone/inverse-bind transforms, returning object-local geometry."""
    raw = context.parameters.get("bind_matrices")
    if not isinstance(raw, Mapping):
        raise EvaluationError("Bind this mesh to bones before evaluating skinning.")

    def matrix(value: Any) -> Matrix:
        """Require a finite six-component affine binding matrix."""
        if not isinstance(value, (tuple, list)) or len(value) != 6:
            raise EvaluationError("Skin binding needs six-component affine matrices.")
        a, b, c, d, x, y = (number(v, "Bind matrix") for v in value)
        return a, b, c, d, x, y

    object_bind = matrix(context.parameters.get("object_bind", IDENTITY))
    owner = context.nodes.get(context.mesh.object_id or "")
    object_inverse = inverse(owner.world_matrix) if owner else IDENTITY
    group_delta = IDENTITY
    group_id = context.parameters.get("object_group")
    if group_id:
        if group_id not in context.nodes:
            raise EvaluationError("The skin's owning Object no longer exists.")
        group_delta = multiply(
            context.nodes[group_id].world_matrix,
            inverse(matrix(context.parameters["object_group_bind"])),
        )
    transforms = {}
    for key, binding in raw.items():
        if key not in context.nodes or context.nodes[key].kind != "bone":
            raise EvaluationError("Skin binding references a missing bone.")
        transforms[key] = multiply(
            object_inverse,
            multiply(
                multiply(group_delta, context.nodes[key].world_matrix),
                multiply(inverse(matrix(binding)), object_bind),
            ),
        )
        if context.parameters.get("local_controls") and owner is not None:
            # Authored face parts retain their own pivoted blink/expression controls
            # inside the bone's space, while the outer Object still carries the rig.
            transforms[key] = multiply(transforms[key], owner.local_matrix)
    result = []
    for vertex, point in zip(context.mesh.vertices, context.points, strict=True):
        if not vertex.weights:
            result.append(point)
            continue
        x = y = 0.0
        for key, weight in vertex.weights.items():
            if key not in transforms:
                raise EvaluationError("Rebind after adding a bone influence outside the bind set.")
            px, py = transform_point(transforms[key], *point)
            x += px * weight
            y += py * weight
        result.append((x, y))
    anchors = context.mesh.extra.get("area_pins", ())
    if not isinstance(anchors, (tuple, list)):
        raise EvaluationError("Image-area pins must be a list of anchors.")
    if not anchors:
        return tuple(result)
    prepared = []
    for pin in anchors:
        target = context.nodes.get(pin["bone_id"])
        if target is None:
            continue
        radius = number(pin["radius"], "Pin radius")
        strength = number(pin.get("strength", 1), "Pin strength")
        if radius <= 0 or not 0 <= strength <= 1:
            raise EvaluationError(
                "Image-area pins need a positive radius and strength from zero to one."
            )
        current = (
            target.world_matrix
            if pin.get("target_kind") == "object"
            else multiply(group_delta, target.world_matrix)
        )
        anchor_matrix = multiply(
            object_inverse,
            multiply(
                current, multiply(inverse(matrix(pin["bone_bind"])), matrix(pin["object_bind"]))
            ),
        )
        prepared.append(((pin["x"], pin["y"]), radius, strength, anchor_matrix))
    for index, (vertex, point) in enumerate(
        zip(context.mesh.vertices, context.points, strict=True)
    ):
        targets = []
        for center, radius, strength, anchor_matrix in prepared:
            distance = math.dist((vertex.x, vertex.y), center)
            weight = strength * max(0, 1 - distance / radius) ** 2
            if not weight:
                continue
            target_point = transform_point(anchor_matrix, *point)
            if distance < 1e-7 and strength == 1:
                targets = [(target_point, 1.0)]
                break
            targets.append((target_point, weight))
        total = sum(weight for _, weight in targets)
        if total:
            amount = min(1, total)
            blended = tuple(
                result[index][axis] * (1 - amount)
                + sum(p[axis] * w for p, w in targets) / total * amount
                for axis in (0, 1)
            )
            result[index] = (blended[0], blended[1])
    return tuple(result)


def mesh_sculpt(context: DeformationContext) -> tuple[Point, ...]:
    """Apply authored vertex displacements while preserving rest topology and UVs."""
    offsets = context.parameters.get("offsets", {})
    if not isinstance(offsets, Mapping) or not set(offsets) <= {
        v.id for v in context.mesh.vertices
    }:
        raise EvaluationError("Mesh offsets require existing vertex identities.")
    result = []
    for vertex, point in zip(context.mesh.vertices, context.points, strict=True):
        delta = offsets.get(vertex.id, (0, 0))
        if not isinstance(delta, (tuple, list)) or len(delta) != 2:
            raise EvaluationError("Each mesh offset requires X/Y displacements.")
        result.append((point[0] + number(delta[0]), point[1] + number(delta[1])))
    return tuple(result)


def builtin_deformers() -> dict[str, DeformerSolver]:
    """Return an owned callable registry for built-ins and later explicitly injected plugins."""
    return {
        "ffd": free_form,
        "lattice": lattice,
        "transform": transform,
        "vertex_offset": transform,
        "pin": pins,
        "mesh_sculpt": mesh_sculpt,
        "skinning": skinning,
        "appearance": lambda context: context.points,
        "bend": sculpt,
        "bulge": sculpt,
        "twist": sculpt,
        "squash_stretch": sculpt,
    }


class DeformationPlan:
    """Compile topology once and memoize one immutable built-in result per mesh.

    Memo entries depend on sampled values and relevant bone/object matrices, never on time
    or transport state. Shared scratch sessions may replace entries without changing results.
    Custom solvers always evaluate, preserving their full node context and plugin behavior.
    """

    def __init__(self, scene: Scene, solvers: Mapping[str, DeformerSolver] | None = None) -> None:
        """Index stable mesh/vertex identities and deterministic ordered deformation stages."""
        self.source_deformers = scene.deformers
        self.custom_solvers = dict(solvers or {})
        self.meshes = scene.meshes
        self.vertices = {v.id: v for m in scene.meshes for v in m.vertices}
        self.base_positions = {m.id: tuple((v.x, v.y) for v in m.vertices) for m in scene.meshes}
        self.vertex_ids = {m.id: tuple(v.id for v in m.vertices) for m in scene.meshes}
        self.uv = {m.id: tuple(v.uv for v in m.vertices) for m in scene.meshes}
        self.pinned = {
            m.id: tuple(i for i, v in enumerate(m.vertices) if v.pinned) for m in scene.meshes
        }
        self.deformers = {d.id: d for d in scene.deformers}
        self.solvers = builtin_deformers()
        self._builtins = dict(self.solvers)
        self.solvers.update(solvers or {})
        self.stages: dict[str, tuple[Deformer, ...]] = {}
        self.parameters: dict[str, dict[str, Any]] = {}
        self._frozen_parameters: dict[str, Mapping[str, Any]] = {}
        self.faces = {}
        self._value_meshes: dict[str, tuple[str, ...]] = {
            v.id: (m.id,) for m in scene.meshes for v in m.vertices
        }
        self._node_dependencies: dict[str, tuple[str, ...]] = {}
        self._skin_spaces: dict[str, tuple[tuple[str, str], ...]] = {}
        self._binding_references: dict[str, tuple[str, ...]] = {}
        self._mesh_cache: dict[str, tuple[tuple[object, ...], MeshPose]] = {}
        used = set()
        for mesh in scene.meshes:
            indices = {v.id: i for i, v in enumerate(mesh.vertices)}
            self.faces[mesh.id] = tuple(tuple(indices[k] for k in face) for face in mesh.triangles)
            stages = tuple(
                sorted(
                    (
                        d
                        for d in scene.deformers
                        if d.owner_id == mesh.id or d.owner_id == mesh.object_id
                    ),
                    key=lambda d: d.order,
                )
            )
            self.stages[mesh.id] = stages
            dependencies = set()
            spaces = []
            bindings: set[str] = set()
            for stage in stages:
                self._value_meshes[stage.id] = (*self._value_meshes.get(stage.id, ()), mesh.id)
                used.add(stage.id)
                params = {**default_parameters(stage.kind, mesh), **json_copy(stage.parameters)}
                if stage.kind in ("ffd", "lattice") and "controls" not in params:
                    try:
                        _, _, controls = lattice_controls(params)
                        params["controls"] = [list(p) for p in controls]
                    except EvaluationError:
                        # Evaluation diagnoses malformed stages while retaining usable geometry.
                        pass
                params["_kind"] = stage.kind
                self.parameters.setdefault(stage.id, params)
                self._frozen_parameters.setdefault(stage.id, frozen_extra(params))
                if stage.enabled and stage.kind == "skinning":
                    if mesh.object_id:
                        dependencies.add(mesh.object_id)
                    if isinstance(params.get("object_group"), str):
                        dependencies.add(params["object_group"])
                        if mesh.object_id:
                            spaces.append((mesh.object_id, params["object_group"]))
                    raw = params.get("bind_matrices", {})
                    if isinstance(raw, Mapping):
                        bindings.update(k for k in raw if isinstance(k, str))
                    dependencies.update(k for vertex in mesh.vertices for k in vertex.weights)
                    anchors = mesh.extra.get("area_pins", ())
                    if isinstance(anchors, (tuple, list)):
                        dependencies.update(
                            pin["bone_id"]
                            for pin in anchors
                            if isinstance(pin, Mapping) and isinstance(pin.get("bone_id"), str)
                        )
            # A complete Object's world transform cancels out of its local skin.
            # Track the artwork-to-Object matrix instead, retaining bone dependencies.
            if spaces and all(
                s.parameters.get("object_group")
                for s in stages
                if s.enabled and s.kind == "skinning"
            ):
                for owner, group in spaces:
                    dependencies.discard(owner)
                    dependencies.discard(group)
                self._skin_spaces[mesh.id] = tuple(spaces)
            self._node_dependencies[mesh.id] = tuple(sorted(dependencies))
            self._binding_references[mesh.id] = tuple(sorted(bindings))
        self.warnings = tuple(
            f"Deformer '{d.name}' is not evaluated; attach valid mesh geometry to its owner."
            for d in scene.deformers
            if d.enabled and d.id not in used
        )

    def matches(self, scene: Scene, solvers: Mapping[str, DeformerSolver] | None) -> bool:
        """Allow transform-only revisions to share compiled geometry and memoized local poses."""
        return (
            self.meshes is scene.meshes
            and self.source_deformers is scene.deformers
            and self.custom_solvers == (solvers or {})
        )

    def base(self, owner: str, path: str) -> float:
        """Resolve supported numeric vertex/parameter leaves for the common track compiler."""
        if owner in self.vertices and path in ("x", "y"):
            return number(getattr(self.vertices[owner], path))
        if owner not in self.parameters or not path.startswith("parameters."):
            raise EvaluationError(f"unsupported animated mesh property {path!r}.")
        parts = path.split(".")[1:]
        if not parts or parts[0] in (
            "bind_matrices",
            "object_bind",
            "object_group",
            "object_group_bind",
            "rows",
            "columns",
            "_kind",
            "bounds",
        ):
            raise EvaluationError("unsupported animation of mesh bindings or lattice topology.")
        value: Any = self.parameters[owner]
        try:
            for part in parts:
                value = value[int(part)] if isinstance(value, list) else value[part]
            return number(value, "Animated deformer parameter")
        except (KeyError, IndexError, ValueError, TypeError) as error:
            raise EvaluationError(f"unsupported animated mesh property {path!r}.") from error

    @staticmethod
    def override_parameter(params: dict[str, Any], path: str, value: float) -> None:
        """Replace a previously validated parameter leaf inside an owned per-frame copy."""
        parts = path.split(".")[1:]
        cursor: Any = params
        for part in parts[:-1]:
            cursor = cursor[int(part)] if isinstance(cursor, list) else cursor[part]
        cursor[int(parts[-1]) if isinstance(cursor, list) else parts[-1]] = value

    def vertex_drag_frames(
        self, mesh: Mesh, nodes: Mapping[str, NodePose], values: Mapping[tuple[str, str], float]
    ) -> dict[str, Matrix]:
        """Invert displayed vertex derivatives once for pointer-aligned sculpting.

        Two bounded finite-difference samples cover the existing deformation stack,
        including blended skinning. The returned linear maps convert displayed local
        displacement into authored displacement; singular folds stay fixed.
        """
        step = 0.01
        baseline = self.evaluate(nodes, values)[0][mesh.id].positions
        samples = []
        for axis in ("x", "y"):
            shifted = dict(values)
            shifted.update(
                {
                    (v.id, axis): values.get((v.id, axis), getattr(v, axis)) + step
                    for v in mesh.vertices
                }
            )
            samples.append(self.evaluate(nodes, shifted)[0][mesh.id].positions)
        frames = {}
        for vertex, point, xpoint, ypoint in zip(mesh.vertices, baseline, *samples, strict=True):
            matrix = (
                (xpoint[0] - point[0]) / step,
                (xpoint[1] - point[1]) / step,
                (ypoint[0] - point[0]) / step,
                (ypoint[1] - point[1]) / step,
                0.0,
                0.0,
            )
            try:
                frame = inverse(matrix)
                if max(abs(value) for value in frame[:4]) > 1000:
                    raise EvaluationError("The displayed vertex is too close to a singular fold.")
                frames[vertex.id] = frame
            except ProjectError:
                frames[vertex.id] = (0, 0, 0, 0, 0, 0)
        return frames

    def evaluate(
        self,
        nodes: Mapping[str, NodePose],
        values: Mapping[tuple[str, str], float],
        *,
        owners: frozenset[str] | None = None,
    ) -> tuple[dict[str, MeshPose], tuple[str, ...]]:
        """Apply stages with explicit blend masks, atomic rollback and pinned sampled-base
        vertices.
        """
        output = {}
        warnings = list(self.warnings)
        vertex_values = {key: value for key, value in values.items() if key[0] in self.vertices}
        sampled: dict[str, list[tuple[tuple[str, str], float]]] = {}
        for key, value in values.items():
            for mesh_id in self._value_meshes.get(key[0], ()):
                sampled.setdefault(mesh_id, []).append((key, value))
        for mesh in self.meshes:
            if owners is not None and mesh.object_id not in owners:
                continue
            cacheable = all(
                not stage.enabled
                or stage.kind in self._builtins
                and self.solvers.get(stage.kind) is self._builtins[stage.kind]
                for stage in self.stages[mesh.id]
            )
            signature = (
                tuple(sampled.get(mesh.id, ())),
                tuple(
                    multiply(inverse(nodes[owner].world_matrix), nodes[group].world_matrix)
                    if owner in nodes and group in nodes
                    else None
                    for owner, group in self._skin_spaces.get(mesh.id, ())
                ),
                tuple(
                    nodes[key].world_matrix if key in nodes else None
                    for key in self._node_dependencies[mesh.id]
                ),
                tuple(
                    nodes[key].kind if key in nodes else None
                    for key in self._binding_references[mesh.id]
                ),
            )
            cached = self._mesh_cache.get(mesh.id) if cacheable else None
            if cached is not None and cached[0] == signature:
                output[mesh.id] = cached[1]
                warnings.extend(cached[1].warnings)
                continue
            base = (
                tuple(
                    (vertex_values.get((v.id, "x"), v.x), vertex_values.get((v.id, "y"), v.y))
                    for v in mesh.vertices
                )
                if vertex_values
                else self.base_positions[mesh.id]
            )
            points = base
            diagnostics = []
            appearance = {}
            for stage in self.stages[mesh.id]:
                if not stage.enabled:
                    continue
                try:
                    if stage.kind not in self.solvers:
                        raise EvaluationError(f"unknown deformer kind {stage.kind!r}.")
                    params: Mapping[str, Any] = self._frozen_parameters[stage.id]
                    changes = [
                        (path, value) for (key, path), value in values.items() if key == stage.id
                    ]
                    if changes:
                        mutable = copy.deepcopy(self.parameters[stage.id])
                        for path, value in changes:
                            self.override_parameter(mutable, path, value)
                        params = frozen_extra(mutable)
                    if stage.kind == "appearance":
                        appearance = {
                            k: v for k, v in params.items() if k not in ("bounds", "_kind")
                        }
                        continue
                    intensity = number(params.get("intensity", 1), "Intensity")
                    if not 0 <= intensity <= 10:
                        raise EvaluationError("Deformation intensity must be from 0 to 10.")
                    if stage.kind in ("ffd", "lattice"):
                        strength = number(mesh.extra.get("ffd_strength", 1), "Object FFD strength")
                        if not 0 <= strength <= 10:
                            raise EvaluationError("Object FFD strength must be from 0 to 10.")
                        intensity *= strength
                    if intensity == 0:
                        continue
                    changed = self.solvers[stage.kind](
                        DeformationContext(mesh, points, params, nodes)
                    )
                    if not isinstance(changed, (tuple, list)) or len(changed) != len(points):
                        raise EvaluationError("A deformer must preserve the vertex count.")
                    weights = params.get("weights")
                    if weights is not None and not isinstance(weights, Mapping):
                        raise EvaluationError(
                            "Vertex masks must map vertex IDs to scalar influence."
                        )
                    blended = []
                    for v, current, target in zip(mesh.vertices, points, changed, strict=True):
                        if not isinstance(target, (tuple, list)) or len(target) != 2:
                            raise EvaluationError("Deformer output requires finite X/Y pairs.")
                        target = (number(target[0], "Deformer X"), number(target[1], "Deformer Y"))
                        weight = (
                            number(weights.get(v.id, 0), "Vertex mask")
                            if weights is not None
                            else 1.0
                        )
                        if not 0 <= weight <= 1:
                            raise EvaluationError("Vertex masks must be between zero and one.")
                        factor = intensity * weight
                        if factor == 1:
                            blended.append(target)
                            continue
                        blended.append(
                            (
                                number(
                                    current[0] + (target[0] - current[0]) * factor, "Deformed X"
                                ),
                                number(
                                    current[1] + (target[1] - current[1]) * factor, "Deformed Y"
                                ),
                            )
                        )
                    points = tuple(blended)
                except (ProjectError, ValueError, OverflowError, ZeroDivisionError) as error:
                    diagnostics.append(f"{mesh.name} / {stage.name}: {error}")
            if self.pinned[mesh.id]:
                pinned_points = list(points)
                for index in self.pinned[mesh.id]:
                    pinned_points[index] = base[index]
                points = tuple(pinned_points)
            output[mesh.id] = MeshPose(
                mesh.id,
                mesh.name,
                mesh.object_id,
                mesh.asset_id,
                self.vertex_ids[mesh.id],
                points,
                self.uv[mesh.id],
                self.faces[mesh.id],
                tuple(diagnostics),
                frozen_extra(appearance),
            )
            if cacheable:
                self._mesh_cache[mesh.id] = signature, output[mesh.id]
            warnings.extend(diagnostics)
        return output, tuple(warnings)
