"""Artist-authored support intervals using ordinary IK constraints, targets and scalar tracks."""

import math
from collections.abc import Callable
from concurrent.futures import CancelledError
from dataclasses import replace
from uuid import uuid4

from rigora.application_services.animation_editing import AnimationEditingService, copied_timeline
from rigora.application_services.characters import CharacterService
from rigora.application_services.rigging import RigService
from rigora.domain.entities import (
    AnimationClip,
    Constraint,
    Keyframe,
    SceneObject,
    Timeline,
    Track,
    Transform,
)
from rigora.domain.geometry import inverse, transform_point
from rigora.domain.project import ProjectError
from rigora.engine.sampling import number


class ContactEditingService(RigService):
    """Create/edit/bake grounded two-segment contacts without changing authored bone rest poses."""

    def interval(
        self,
        upper: str,
        lower: str,
        start: float,
        end: float,
        *,
        x: float | None = None,
        y: float | None = None,
        blend: float = 0,
        bend: float = 1,
        foot: str = "",
        angle: float = 0,
        space: str = "object",
        compensate: bool = True,
        identity: str = "",
    ) -> str:
        """Publish one contact target/rule and weight envelope as one reversible command.

        Object-space anchors follow the placed Object but resist internal hip motion.
        World anchors stay fixed in the scene. Compensation translates the upper
        segment's joint when its target lies beyond the two-segment reach.
        """
        start, end, blend, bend, angle = (number(v) for v in (start, end, blend, bend, angle))
        if not 0 <= start < end or end - start > 10000 or not 0 <= blend <= (end - start) / 2:
            raise ProjectError(
                "Choose an increasing contact interval and a fade up to half its duration."
            )
        if space not in ("object", "world") or bend not in (-1, 1):
            raise ProjectError("Choose Object/World anchor space and bend direction -1 or 1.")
        upper_bone, lower_bone = self.editable(upper), self.editable(lower)
        scope = self.document.animation_scope
        if scope is not None and not {upper, lower, *([foot] if foot else [])} <= scope:
            raise ProjectError("Choose leg segments in the currently editable Object view.")
        if lower_bone.parent_id != upper or min(upper_bone.length, lower_bone.length) <= 1e-8:
            raise ProjectError("Choose connected positive-length upper and lower leg bones.")
        if foot and self.editable(foot).parent_id != lower:
            raise ProjectError("The foot must be a direct child of the lower leg.")
        pose = self.document.animation.pose
        root = CharacterService(self.document).object_root(upper)
        if root is None:
            rig = next(r for r in self.scene.skeletons if any(b.id == upper for b in r.bones))
            root = CharacterService(self.document).object_root(str(rig.extra.get("object_id", "")))
        parent = root.id if root and space == "object" else None
        px, py = transform_point(pose.nodes[lower].world_matrix, lower_bone.length, 0)
        px, py = px if x is None else number(x), py if y is None else number(y)
        local = (
            transform_point(inverse(pose.nodes[parent].world_matrix), px, py)
            if parent
            else (px, py)
        )
        existing = next((r for r in self.scene.constraints if r.id == identity), None)
        if identity and (existing is None or existing.kind != "foot_contact"):
            raise ProjectError("This foot contact no longer exists.")
        key = identity or str(uuid4())
        target = next(
            (o for o in self.scene.objects if existing and o.id == existing.target_id), None
        )
        target = (
            replace(target, parent_id=parent, transform=Transform(x=local[0], y=local[1]))
            if target
            else SceneObject(
                name=f"Contact anchor · {lower_bone.name}"[:200],
                parent_id=parent,
                transform=Transform(x=local[0], y=local[1]),
                extra={"contact_owner": key},
            )
        )
        rule = replace(
            existing
            or Constraint(
                id=key,
                name=f"Foot contact · {lower_bone.name}"[:200],
                owner_id=upper,
                kind="foot_contact",
            ),
            owner_id=upper,
            target_id=target.id,
            kind="foot_contact",
            parameters={
                "end_bone_id": lower,
                "foot_bone_id": foot,
                "bend": bend,
                "weight": 0.0,
                "angle": angle,
                "anchor_space": space,
                "compensate": compensate,
                "minimum_angle": lower_bone.extra.get("minimum_joint_angle", 0),
                "placement_owner": root.id if root else "",
                "placement_bind": (
                    self.document.animation.evaluator.spring_bindings.get(
                        root.id, pose.nodes[root.id].world_matrix
                    )
                    if root
                    else (1, 0, 0, 1, 0, 0)
                ),
            },
            extra={
                **(existing.extra if existing else {}),
                "contact_start": start,
                "contact_end": end,
                "contact_blend": blend,
            },
        )
        editor = AnimationEditingService(self.document)
        timeline = editor.timeline or Timeline(name="Contact animation")
        clip = editor.clip or editor.blank_clip(timeline)
        for track in timeline.tracks:
            if track.owner_id == key:
                editor.editable(track)
        values: tuple[tuple[float, int], ...] = (
            ((start, 0), (start + blend, 1), (end - blend, 1), (end, 0))
            if blend
            else ((start, 1), (end, 0))
        )
        values = tuple(dict(values).items())
        track = Track(
            name=rule.name,
            owner_id=key,
            property_path="parameters.weight",
            keyframes=tuple(
                Keyframe(frame=f, value=v, interpolation="linear" if blend else "step")
                for f, v in values
            ),
            extra={
                "active_from_first_key": True,
                "foot_contact": {"id": key, "start": start, "end": end},
            },
        )
        with self.document.command_group("Edit foot contact"):
            self.commit(
                "Edit contact anchor and rule",
                objects=tuple(o for o in self.scene.objects if o.id != target.id) + (target,),
                constraints=tuple(r for r in self.scene.constraints if r.id != key) + (rule,),
            )
            editor.publish(
                "Key foot contact",
                replace(
                    timeline,
                    tracks=tuple(
                        t
                        for t in timeline.tracks
                        if t.owner_id != key or t.property_path != "parameters.weight"
                    )
                    + (track,),
                ),
                replace(clip, out_frame=max(clip.out_frame, end)),
            )
            pose = self.document.animation.evaluate(start + blend)
            if any(f"Constraint '{rule.name}':" in warning for warning in pose.warnings):
                raise ProjectError("The chosen leg cannot solve IK. " + " ".join(pose.warnings))
        return key

    def remove_contact(self, key: str) -> None:
        """Remove the owned anchor and its channels with the rule, preserving artwork and bones."""
        rule = next(
            (r for r in self.scene.constraints if r.id == key and r.kind == "foot_contact"), None
        )
        if rule is None:
            raise ProjectError("Choose an existing foot contact.")
        if (
            self.document.animation_scope is not None
            and rule.owner_id not in self.document.animation_scope
        ):
            raise ProjectError("This contact belongs to another Object view.")
        discarded = {
            key,
            *(
                o.id
                for o in self.scene.objects
                if o.id == rule.target_id and o.extra.get("contact_owner") == key
            ),
        }
        self.commit(
            "Remove foot contact",
            constraints=tuple(r for r in self.scene.constraints if r.id != key),
            objects=tuple(o for o in self.scene.objects if o.id not in discarded),
            draw_order=tuple(k for k in self.scene.draw_order if k not in discarded),
            timelines=tuple(
                replace(t, tracks=tuple(c for c in t.tracks if c.owner_id not in discarded))
                for t in self.scene.timelines
            ),
        )

    def bake_contacts(
        self, start: float, end: float, *, cancelled: Callable[[], bool] = lambda: False
    ) -> str:
        """Bake connected rigs into a new FK action, retaining original constraints and clips."""
        start, end = number(start), number(end)
        contacts = {c.owner_id for c in self.scene.constraints if c.kind == "foot_contact"}
        bones = {
            b.id
            for rig in self.scene.skeletons
            if contacts.intersection(b.id for b in rig.bones)
            for b in rig.bones
            if self.document.animation_scope is None or b.id in self.document.animation_scope
        }
        if not 0 <= start < end or (end - start + 2) * len(bones) > 100000:
            raise ProjectError("Contact baking is limited to 100,000 bone samples.")
        editor = AnimationEditingService(self.document)
        source, timeline = editor.clip, editor.timeline
        if (
            source is None
            or timeline is None
            or not any(c.kind == "foot_contact" for c in self.scene.constraints)
        ):
            raise ProjectError("Select a clip with foot contacts before baking.")
        channels: dict[tuple[str, str], list[Keyframe]] = {}
        for frame in sorted(
            {start, end, *(float(i) for i in range(math.ceil(start), math.floor(end) + 1))}
        ):
            if cancelled():
                raise CancelledError()
            pose = self.document.animation.evaluate(frame)
            if pose.warnings:
                raise ProjectError("Resolve pose warnings before baking contacts.")
            for key in bones:
                node = pose.nodes.get(key)
                if node is None:
                    continue
                for field in node.local._fields:
                    channels.setdefault((key, "transform." + field), []).append(
                        Keyframe(frame=frame, value=getattr(node.local, field))
                    )
                channels.setdefault((key, "length"), []).append(
                    Keyframe(frame=frame, value=node.length)
                )
        copied = copied_timeline(timeline)
        tracks = tuple(t for t in copied.tracks if t.owner_id not in bones) + tuple(
            Track(name=path, owner_id=owner, property_path=path, keyframes=tuple(keys))
            for (owner, path), keys in channels.items()
        )
        result = AnimationClip(
            name=source.name + " · contacts baked",
            timeline_id=copied.id,
            in_frame=start,
            out_frame=end,
            loop=source.loop,
            extra={**source.extra, "fk_bones": sorted(bones), "contact_bake": True},
        )
        editor.publish("Bake foot contacts", replace(copied, tracks=tracks), result)
        return result.id
