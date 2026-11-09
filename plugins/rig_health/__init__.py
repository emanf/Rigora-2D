"""Read-only static rig diagnostics, usable in both the desktop and isolated SDK workers."""

from collections import Counter, defaultdict
from collections.abc import Mapping
from typing import Any

from rigora.domain.project import Project
from rigora.sdk import PluginContext, PluginRequest

MAX_FINDINGS = 200


def analyze(project: Project) -> dict[str, Any]:
    """Inspect immutable authored data without evaluating poses, reading files or changing history.

    Results are JSON-compatible. Counts include every finding; only the first 200
    details are retained. The static score deducts 20 per error and 5 per warning;
    notes have no penalty. It is diagnostic guidance, not a visual quality rating.
    """
    details: dict[str, list[dict[str, str]]] = {"error": [], "warning": [], "note": []}
    counts: Counter[str] = Counter()
    totals: Counter[str] = Counter(scenes=len(project.scenes))

    def add(severity: str, code: str, scene, item, message: str, suggestion: str) -> None:
        """Count all risks while bounding display and clipboard data for large projects."""
        counts[severity] += 1
        if len(details[severity]) < MAX_FINDINGS:
            details[severity].append(
                dict(
                    severity=severity,
                    code=code,
                    scene=scene.name,
                    scene_id=scene.id,
                    item=item.name,
                    item_id=item.id,
                    message=message,
                    suggestion=suggestion,
                )
            )

    for scene in project.scenes:
        totals.update(rigs=len(scene.skeletons), meshes=len(scene.meshes))
        bones = {b.id: b for rig in scene.skeletons for b in rig.bones}
        totals["bones"] += len(bones)
        for item in (*scene.groups, *scene.objects, *bones.values()):
            if min(abs(item.transform.scale_x), abs(item.transform.scale_y)) <= 1e-8:
                add(
                    "error",
                    "collapsed_scale",
                    scene,
                    item,
                    "A rest-pose scale is zero or nearly zero; geometry can disappear.",
                    "Restore a nonzero scale in Transform, including on this item's parents. "
                    "Use Visibility to hide artwork instead of collapsing its scale.",
                )
        for rig in scene.skeletons:
            names = Counter(b.name.strip().casefold() for b in rig.bones)
            for name, amount in names.items():
                if amount > 1:
                    add(
                        "warning",
                        "duplicate_bone_names",
                        scene,
                        rig,
                        f"{amount} bones share the name '{name}' (ignoring case/spacing).",
                        "Give these bones distinct names before name-based retargeting/export.",
                    )
            roots = sum(b.parent_id is None for b in rig.bones)
            if roots > 1:
                add(
                    "note",
                    "multiple_roots",
                    scene,
                    rig,
                    f"This rig has {roots} independent root bones.",
                    "Keep intentional branches. If they should move as one chain, parent them "
                    "in Bones; moving one independent root will not move the others.",
                )

        skins = defaultdict(list)
        for stage in scene.deformers:
            if stage.kind == "skinning" and stage.enabled:
                skins[stage.owner_id].append(stage)
        for mesh in scene.meshes:
            totals["vertices"] += len(mesh.vertices)
            if not skins[mesh.id]:
                continue
            unweighted = sum(not v.weights and not v.pinned for v in mesh.vertices)
            if unweighted:
                add(
                    "warning",
                    "unweighted_vertices",
                    scene,
                    mesh,
                    f"Unpinned vertices without weights in an enabled skin: {unweighted}.",
                    "Inspect these vertices in Skin/Weights. Paint weights or bind the artwork "
                    "again if they should follow bones; intentional stationary points may stay.",
                )
            influences = {key for vertex in mesh.vertices for key in vertex.weights}
            for stage in skins[mesh.id]:
                binding = stage.parameters.get("bind_matrices")
                if not isinstance(binding, Mapping):
                    add(
                        "error",
                        "missing_bind",
                        scene,
                        mesh,
                        "An enabled skin stage has no bind matrices.",
                        "Select the artwork and its intended bones, then Bind in Object Editor.",
                    )
                elif missing := (influences - binding.keys()) | (binding.keys() - bones.keys()):
                    add(
                        "error",
                        "incomplete_bind",
                        scene,
                        mesh,
                        f"Missing/unbound bone references in an enabled skin: {len(missing)}.",
                        "Rebind with every bone used by the mesh's weights. Remove obsolete "
                        "influences before rebinding if those bones were replaced.",
                    )

        ranges = defaultdict(list)
        for clip in scene.clips:
            ranges[clip.timeline_id].append((clip.in_frame, clip.out_frame))
        for timeline in scene.timelines:
            for track in timeline.tracks:
                totals["keys"] += len(track.keyframes)
                # Shared timelines can serve several clips; their ranges form a union.
                if ranges[timeline.id]:
                    outside = sum(
                        not any(start <= key.frame <= end for start, end in ranges[timeline.id])
                        for key in track.keyframes
                    )
                    if outside:
                        add(
                            "note",
                            "keys_outside_clips",
                            scene,
                            track,
                            f"Keys outside every clip using this timeline: {outside} "
                            f"({track.property_path}).",
                            "Extend a clip's range if those keys should play. Keep keys outside "
                            "clips when they are intentional working material.",
                        )
    findings = [row for rows in details.values() for row in rows][:MAX_FINDINGS]
    errors, warnings, notes = (counts[k] for k in ("error", "warning", "note"))
    empty = not any(s.objects or s.groups or s.skeletons or s.meshes for s in project.scenes)
    return {
        "project": project.name,
        "score": None if empty else max(0, 100 - 20 * errors - 5 * warnings),
        "status": "empty" if empty else "errors" if errors else "warnings" if warnings else "clear",
        "score_criteria": "Static checks: 100 minus 20/error and 5/warning; notes deduct nothing.",
        "errors": errors,
        "warnings": warnings,
        "notes": notes,
        "totals": {
            key: totals[key] for key in ("scenes", "rigs", "bones", "meshes", "vertices", "keys")
        },
        "findings": findings,
        "omitted_findings": sum(counts.values()) - len(findings),
        "scope": "Authored transforms, rig names/roots, enabled skin bindings and clip coverage. "
        "Animated poses, artwork appearance, external assets and engine compatibility "
        "are not checked.",
    }


def scan(request: PluginRequest) -> dict[str, Any]:
    """Expose the same report through the SDK validator and separate-process job runner."""
    return analyze(request.require_document().project)


def panel(request: PluginRequest, parent):
    """Import Qt only when the desktop requests its owned dock widget."""
    from .panel import HealthPanel

    return HealthPanel(request, parent)


def register(context: PluginContext) -> None:
    """Register a desktop dock and a headless validator without reading or modifying a project."""
    context.register("panels", context.manifest.id + ".panel", "Rig Health Check", panel)
    context.register("validators", context.manifest.id + ".scan", "Scan rig health", scan)
    context.action(
        context.manifest.id + ".open",
        "Rig Health Check",
        open_panel,
        placements=("menu:Rig/Diagnostics", "surface:object.actions", "surface:timeline.actions"),
        icon="fact_check",
    )


def open_panel(request: PluginRequest) -> None:
    """Open the diagnostic dock from ordinary editor controls through the public desktop host."""
    if request.host:
        request.host.show_panel("org.rigora.rig_health.panel")
