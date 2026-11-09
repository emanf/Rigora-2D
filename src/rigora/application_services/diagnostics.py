"""Read-only project health checks shared by the editor, scripts and export preflight."""

import json
from dataclasses import dataclass

from rigora.application_services.documents import DocumentService
from rigora.domain.project import ProjectError


@dataclass(frozen=True)
class Diagnostic:
    """A stable category, severity and navigable record; inspection never repairs implicitly."""

    code: str
    severity: str
    message: str
    scene_id: str = ""
    owner_id: str = ""


def inspect_project(document: DocumentService) -> tuple[Diagnostic, ...]:
    """Inspect all sources and scenes, evaluating one representative frame in isolated copies.

    This checks current sample warnings, not every frame of every action. Blocking
    format-specific checks remain the exporter's responsibility.
    """
    if document.project is None:
        return ()
    issues = []
    for asset in document.project.assets:
        try:
            document.read_asset(asset.id)
        except ProjectError as error:
            owner = next(
                (
                    (scene.id, mesh.object_id or "")
                    for scene in document.project.scenes
                    for mesh in scene.meshes
                    if mesh.asset_id == asset.id
                ),
                ("", ""),
            )
            issues.append(Diagnostic("asset-source", "Error", f"{asset.name}: {error}", *owner))
        for warning in asset.extra.get("import_warnings", ()):
            issues.append(Diagnostic("import-approximation", "Warning", f"{asset.name}: {warning}"))
    for scene in document.project.scenes:
        for rig in scene.skeletons:
            for bone in rig.bones:
                if bone.length <= 1e-6:
                    issues.append(
                        Diagnostic(
                            "zero-bone",
                            "Warning",
                            f"{bone.name}: zero-length bone cannot drive an IK chain.",
                            scene.id,
                            bone.id,
                        )
                    )
        for mesh in scene.meshes:
            for warning in mesh.extra.get("import_warnings", ()):
                issues.append(
                    Diagnostic(
                        "mesh-import",
                        "Warning",
                        f"{mesh.name}: {warning}",
                        scene.id,
                        mesh.object_id or "",
                    )
                )
        try:
            sample = document.persistence_copy()
            sample.select_scene(scene.id)
            pose = sample.animation.evaluate(sample.cursor_frame)
            for warning in pose.warnings:
                issues.append(Diagnostic("evaluation", "Error", warning, scene.id))
            for evaluated in pose.meshes.values():
                for warning in evaluated.warnings:
                    issues.append(
                        Diagnostic(
                            "deformation",
                            "Error",
                            f"{evaluated.name}: {warning}",
                            scene.id,
                            evaluated.object_id or "",
                        )
                    )
            visible = sum(
                len(part.triangles)
                for part in pose.meshes.values()
                if part.object_id is not None
                and part.object_id in pose.nodes
                and pose.nodes[part.object_id].visible
            )
            if visible > 20000:
                issues.append(
                    Diagnostic(
                        "render-budget",
                        "Warning",
                        f"{scene.name}: {visible:,} visible triangles; "
                        "SVG output is bounded to 20,000 triangles.",
                        scene.id,
                    )
                )
        except ProjectError as error:
            issues.append(
                Diagnostic("scene-evaluation", "Error", f"{scene.name}: {error}", scene.id)
            )
    metadata = len(
        json.dumps(document.project.to_dict(), ensure_ascii=False, separators=(",", ":")).encode()
    )
    if metadata > 8 * 1024 * 1024:
        issues.append(
            Diagnostic(
                "chunked-storage",
                "Info",
                f"{metadata / 1024**2:.1f} MiB authoring data: chunked storage required. "
                "Older Rigora releases cannot open it.",
            )
        )
    return tuple(dict.fromkeys(issues))
