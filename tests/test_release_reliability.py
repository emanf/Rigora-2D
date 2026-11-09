"""Release regressions for plugin geometry, persistence races and dependency boundaries."""

import ast
import math
from dataclasses import replace
from pathlib import Path

import pytest

from rigora.application_services.documents import DocumentService
from rigora.domain.entities import Deformer
from rigora.domain.mesh_geometry import grid_mesh
from rigora.domain.project import ProjectError, Scene, SceneSettings
from rigora.engine.deformation import DeformationContext, free_form
from rigora.engine.evaluation import SceneEvaluator
from rigora.infrastructure import project_storage


@pytest.mark.parametrize("invalid", [None, [(1,)], [("x", 2)], [(float("nan"), 2)]])
def test_malformed_extension_geometry_retains_last_valid_stage(invalid):
    """Malformed solver returns warn without losing valid preceding deformation or source data."""
    mesh = grid_mesh(100, 100, 1, 1)
    valid = Deformer(owner_id=mesh.id, kind="transform", parameters={"x": 12})
    broken = Deformer(owner_id=mesh.id, kind="custom", order=1)
    scene = Scene(meshes=(mesh,), deformers=(valid, broken))
    output = invalid if invalid is None else invalid * len(mesh.vertices)
    pose = SceneEvaluator(scene, deformers={"custom": lambda context: output}).evaluate(0)
    assert pose.warnings and broken.name in pose.warnings[0]
    assert pose.meshes[mesh.id].positions == tuple((v.x + 12, v.y) for v in mesh.vertices)
    assert scene.meshes[0] is mesh


@pytest.mark.parametrize("size", [2, 4, 8])
def test_sparse_and_dense_ffd_match_full_bernstein_reference(size):
    """Optimization retains tensor-product weights, clamped bounds and immutable inputs."""
    mesh = grid_mesh(100, 80, 3, 3)
    points = tuple((v.x, v.y) for v in mesh.vertices) + ((-10, 100), (120, -20))
    for sparse in (False, True):
        controls = tuple(
            (math.sin(i) * 20, math.cos(i) * 10) if not sparse or i % 7 == 0 else (0, 0)
            for i in range(size * size)
        )
        context = DeformationContext(
            mesh,
            points,
            {"bounds": [0, 0, 100, 80], "columns": size, "rows": size, "controls": controls},
            {},
        )
        expected = []
        for x, y in points:
            u, v = min(1, max(0, x / 100)), min(1, max(0, y / 80))
            weights = [
                math.comb(size - 1, col)
                * u**col
                * (1 - u) ** (size - 1 - col)
                * math.comb(size - 1, row)
                * v**row
                * (1 - v) ** (size - 1 - row)
                for row in range(size)
                for col in range(size)
            ]
            expected.append(
                (
                    x
                    + sum(
                        offset[0] * weight for offset, weight in zip(controls, weights, strict=True)
                    ),
                    y
                    + sum(
                        offset[1] * weight for offset, weight in zip(controls, weights, strict=True)
                    ),
                )
            )
        for result, reference in zip(free_form(context), expected, strict=True):
            assert result == pytest.approx(reference, abs=1e-10)
    neutral = replace(
        context, parameters={**context.parameters, "controls": [(0, 0)] * (size * size)}
    )
    assert free_form(neutral) == points


def test_file_removed_during_save_preserves_unsaved_edits(tmp_path, monkeypatch):
    """External deletion during compression requires Save As rather than recreating a stale path."""
    path = tmp_path / "removed.rigora"
    doc = DocumentService()
    doc.new()
    doc.save(path)
    doc.update_settings("Work to retain", "Scene", SceneSettings())
    fsync = project_storage.os.fsync

    def remove_before_publication(descriptor):
        """Simulate an external writer deleting the source while the temporary ZIP is flushed."""
        fsync(descriptor)
        path.unlink(missing_ok=True)

    monkeypatch.setattr(project_storage.os, "fsync", remove_before_publication)
    with pytest.raises(ProjectError, match="removed while saving"):
        doc.save()
    assert not path.exists() and not list(tmp_path.glob(".rigora-*"))
    assert doc.dirty and doc.project.name == "Work to retain"
    doc.save(tmp_path / "recovered.rigora")
    assert not doc.dirty


def test_core_dependency_direction():
    """Core model/evaluator stay independent of Qt and adapters as integrations expand."""
    root = Path(__file__).resolve().parents[1] / "src" / "rigora"
    for layer in ("domain", "engine", "application_services", "infrastructure", "sdk"):
        for path in (root / layer).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                names = (
                    [alias.name for alias in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                    if isinstance(node, ast.ImportFrom)
                    else []
                )
                forbidden = ("PySide", "PyQt", "rigora.presentation", "rigora.interfaces")
                if layer in ("domain", "engine"):
                    forbidden += (
                        "rigora.application_services",
                        "rigora.infrastructure",
                        "rigora.sdk",
                    )
                assert not any(name.startswith(forbidden) for name in names), str(path)
