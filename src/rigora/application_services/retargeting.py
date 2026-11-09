"""Editable anatomical motion transfer between independently proportioned skeletons."""

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.documents import DocumentService
from rigora.domain.entities import AnimationClip, Bone, Keyframe, Marker, Skeleton, Timeline, Track
from rigora.domain.project import ProjectError
from rigora.engine.evaluation import SceneEvaluator
from rigora.engine.sampling import number

PROFILES: dict[str, tuple[tuple[str, ...], ...]] = {
    "Human": (
        ("hips", "pelvis", "root"),
        ("spine", "torso", "body"),
        ("head",),
        ("arm", "upperarm"),
        ("forearm", "lowerarm"),
        ("hand",),
        ("leg", "thigh", "upperleg"),
        ("shin", "calf", "lowerleg"),
        ("foot",),
    ),
    "Quadruped": (
        ("body", "spine", "torso", "root"),
        ("neck",),
        ("head",),
        ("front", "frontupper", "frontleg"),
        ("frontlower", "frontshin"),
        ("rear", "rearupper", "hindleg"),
        ("rearlower", "hindlower"),
        ("tail",),
    ),
    "Winged": (
        ("body", "torso", "root"),
        ("neck",),
        ("head",),
        ("wing", "upperwing"),
        ("wingtip", "lowerwing"),
        ("leg",),
        ("foot",),
        ("tail",),
    ),
    "Flexible spine": (("root", "body", "base"), ("tip", "tailtip", "head")),
}


def role(bone: Bone, profile: str) -> str:
    """Normalize explicit anatomical roles or familiar names without guessing arbitrary labels."""
    name = str(bone.extra.get("role", bone.name)).casefold()
    side = (
        "l"
        if re.search(r"(?:[._ -]l$|left)", name)
        else "r"
        if re.search(r"(?:[._ -]r$|right)", name)
        else ""
    )
    name = re.sub(r"left|right|[._ -][lr]$", "", name)
    normalized = re.sub(r"[^a-z0-9]", "", name)
    for aliases in PROFILES[profile]:
        if normalized in aliases:
            return aliases[0] + side
    return normalized + side


def suggest_mapping(source: Skeleton, target: Skeleton, profile: str) -> dict[str, str]:
    """Suggest unique role matches; flexible chains also align their relative bone order."""
    if profile not in PROFILES:
        raise ProjectError("Choose a supported retarget mapping profile.")
    target_roles: dict[str, list[str]] = {}
    for bone in target.bones:
        target_roles.setdefault(role(bone, profile), []).append(bone.id)
    result = {}
    used = set()
    for bone in source.bones:
        matches = target_roles.get(role(bone, profile), [])
        if len(matches) == 1 and matches[0] not in used:
            result[bone.id] = matches[0]
            used.add(matches[0])
    if profile == "Flexible spine":
        for i, bone in enumerate(target.bones):
            index = round(i * (len(source.bones) - 1) / max(1, len(target.bones) - 1))
            if source.bones and source.bones[index].id not in result and bone.id not in used:
                result[source.bones[index].id] = bone.id
                used.add(bone.id)
    return result


@dataclass(frozen=True)
class RetargetResult:
    """Published clip identity and explicit mapping omissions retained for user correction."""

    clip_id: str
    mapped: tuple[tuple[str, str], ...]
    missing: tuple[str, ...]
    samples: int


class RetargetService(AnimationEditingService):
    """Bake evaluated source poses into a fresh target clip with editable scalar channels."""

    def apply(
        self,
        source: DocumentService,
        source_clip: str,
        source_skeleton: str,
        target_skeleton: str,
        mapping: Mapping[str, str],
        *,
        profile: str = "Human",
        rotation_offsets: Mapping[str, float] | None = None,
        rotation_gains: Mapping[str, float] | None = None,
        root_scale: float | None = None,
        name: str = "Retargeted motion",
    ) -> RetargetResult:
        """Preserve seconds/FPS and proportions, skip unmapped bones, and publish once.

        Samples include source integer frames, authored subframes and endpoints. Source
        constraints are evaluated before mapping. The resulting target clip uses FK for
        mapped bones, while other clips retain the original constraint behavior.
        """
        if source.project is None or profile not in PROFILES:
            raise ProjectError("Open a source project and choose a supported profile.")
        scene = source.scene
        src = next((r for r in scene.skeletons if r.id == source_skeleton), None)
        dst = next((r for r in self.scene.skeletons if r.id == target_skeleton), None)
        if src is None or dst is None:
            raise ProjectError("Choose existing source and target skeletons.")
        a, b = {n.id: n for n in src.bones}, {n.id: n for n in dst.bones}
        pairs = dict(mapping)
        if (
            not pairs
            or not set(pairs) <= a.keys()
            or not set(pairs.values()) <= b.keys()
            or len(set(pairs.values())) != len(pairs)
        ):
            raise ProjectError("Map at least one source bone to a distinct existing target bone.")
        for target_key in pairs.values():
            self.editable(Track(owner_id=target_key, property_path="transform.rotation"))
        evaluator = SceneEvaluator(
            scene,
            source_clip,
            solvers=source.constraint_solvers,
            deformers=source.deformer_solvers,
            samplers=source.track_samplers,
        )
        clip = evaluator.clip
        if clip is None:
            raise ProjectError("Choose a source animation clip.")
        assert evaluator.timeline is not None
        if clip.out_frame - clip.in_frame > 10000:
            raise ProjectError("Retarget at most 10,000 source frames at a time.")
        times = (
            sorted(
                {
                    clip.in_frame,
                    clip.out_frame,
                    *(
                        float(i)
                        for i in range(math.ceil(clip.in_frame), math.floor(clip.out_frame) + 1)
                    ),
                    *(
                        k.frame
                        for t in evaluator.timeline.tracks
                        for k in t.keyframes
                        if clip.in_frame <= k.frame <= clip.out_frame
                    ),
                }
            )
            if evaluator.timeline
            else []
        )
        if len(times) * len(pairs) > 100000:
            raise ProjectError(
                "Retarget at most 100,000 bone samples; shorten the clip or mapping."
            )
        ratio = (
            number(root_scale, "Root scale")
            if root_scale is not None
            else sum(b[target].length for target in pairs.values())
            / max(1e-9, sum(a[key].length for key in pairs))
        )
        if not 0.001 <= ratio <= 1000:
            raise ProjectError("Root motion scale must be between 0.001 and 1000.")
        offsets = {k: number(v, "Rotation correction") for k, v in (rotation_offsets or {}).items()}
        gains = {k: number(v, "Rotation gain") for k, v in (rotation_gains or {}).items()}
        if not set(offsets) <= b.keys() or not set(gains) <= b.keys():
            raise ProjectError("Corrections must identify target bones.")
        fps = self.scene.settings.fps / scene.settings.fps
        channels: dict[tuple[str, str], list[float]] = {}
        for time in times:
            pose = evaluator.evaluate(time)
            for source_id, target_id in pairs.items():
                old, target, node = a[source_id], b[target_id], pose.nodes[source_id]
                parent_ratio = (
                    b[target.parent_id].length / max(1e-9, a[old.parent_id].length)
                    if old.parent_id in a and target.parent_id in b
                    else ratio
                )
                for component in ("x", "y", "rotation", "scale_x", "scale_y"):
                    baseline = getattr(old.transform, component)
                    value = getattr(node.local, component)
                    rest = getattr(target.transform, component)
                    if component == "rotation":
                        value = (
                            rest
                            + (value - baseline) * gains.get(target_id, 1)
                            + offsets.get(target_id, 0)
                        )
                    elif component.startswith("scale"):
                        if abs(baseline) < 1e-9:
                            raise ProjectError(
                                "Restore nonzero source rest scales before retargeting."
                            )
                        value = rest * value / baseline
                    else:
                        value = rest + (value - baseline) * parent_ratio
                    channels.setdefault((target_id, f"transform.{component}"), []).append(
                        number(value)
                    )
        tracks = []
        for (owner, path), values in channels.items():
            rest = getattr(b[owner].transform, path.split(".")[1])
            if all(math.isclose(v, rest, abs_tol=1e-8) for v in values):
                continue
            constant = all(math.isclose(v, values[0], abs_tol=1e-8) for v in values)
            tracks.append(
                Track(
                    name=f"{b[owner].name} · {path[10:]}",
                    owner_id=owner,
                    property_path=path,
                    keyframes=tuple(
                        Keyframe(frame=time * fps, value=value)
                        for time, value in zip(
                            times[:1] if constant else times,
                            values[:1] if constant else values,
                            strict=True,
                        )
                    ),
                )
            )
        if not tracks:
            raise ProjectError("The mapped source motion does not change these target bones.")
        timeline = Timeline(
            name=name,
            tracks=tuple(tracks),
            markers=tuple(
                Marker(name=m.name, frame=m.frame * fps, annotation=m.annotation)
                for m in evaluator.timeline.markers
            ),
        )
        missing = tuple(n.name for n in src.bones if n.id not in pairs)
        output = AnimationClip(
            name=name,
            timeline_id=timeline.id,
            in_frame=clip.in_frame * fps,
            out_frame=clip.out_frame * fps,
            loop=clip.loop,
            annotation="Editable sampled retarget; source motion and rest rig are preserved.",
            extra={
                "fk_bones": tuple(pairs.values()),
                "retarget": {
                    "profile": profile,
                    "source_clip": clip.id,
                    "mapping": pairs,
                    "missing": missing,
                    "rotation_offsets": offsets,
                    "rotation_gains": gains,
                    "root_scale": ratio,
                },
            },
        )
        self.publish("Retarget motion", timeline, output)
        return RetargetResult(output.id, tuple(pairs.items()), missing, len(times))
