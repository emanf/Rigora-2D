"""Configurable anchored follow-through and deterministic editable cartoon motion baking."""

import copy
import math
from collections.abc import Mapping
from dataclasses import replace
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.rigging import RigService
from rigora.domain.entities import AnimationClip, Constraint, Keyframe, Skeleton, Timeline, Track
from rigora.domain.geometry import transform_point
from rigora.domain.project import ProjectError
from rigora.engine.sampling import number
from rigora.engine.springs import SpringSimulation

BOUNCES = {
    "Soft bounce": (3, 0.55, 0.22),
    "Rubber ball": (5, 0.78, 0.4),
    "Heavy landing": (2, 0.28, 0.15),
}

# Original presets expressed in Rigora's documented physical units.
SPRING_PRESETS = {
    "Default": (2.4, 0.38, 0.9, 0.0, False),
    "Rubbery": (1.6, 0.14, 1.4, 0.0, False),
    "Smooth": (1.8, 0.8, 0.65, 0.0, False),
    "Fast": (5.0, 0.35, 0.85, 0.0, False),
    "Slow": (0.8, 0.3, 1.2, 0.0, False),
    "Stiff": (7.0, 1.0, 0.35, 0.0, False),
    "Weighted": (1.3, 0.45, 1.7, 1800.0, False),
    "Light": (3.2, 0.2, 0.4, -180.0, False),
    "Stretchy": (1.5, 0.3, 1.2, 0.0, True),
    "Squashy": (1.7, 0.35, 1.4, 0.0, True),
}


class DynamicsService(AnimationEditingService):
    """Keep simulation configuration and baked output in the ordinary command/clip system."""

    def group_metadata(self, name: str) -> dict[str, Any]:
        """Read stable identities and display settings without dirtying legacy files."""
        metadata = self.scene.extra.get("spring_group_metadata", {})
        if not isinstance(metadata, Mapping) or not isinstance(metadata.get(name, {}), Mapping):
            raise ProjectError("Spring group display settings must be an object.")
        result = {
            "id": str(uuid5(NAMESPACE_URL, f"rigora:spring:{self.scene.id}:{name}")),
            "color": "#bcbcbc",
            **metadata.get(name, {}),
        }
        try:
            UUID(result["id"])
            color = result["color"]
            if not isinstance(color, str) or len(color) != 7 or color[0] != "#":
                raise ValueError("color")
            int(color[1:], 16)
        except (ValueError, TypeError, AttributeError) as error:
            raise ProjectError(
                "Spring groups need valid identities and #RRGGBB display colors."
            ) from error
        return result

    def save_custom_preset(self, name: str, group: str) -> None:
        """Store a project-local physical preset without copying bone-specific rest poses."""
        name = name.strip()
        if not name or len(name) > 100:
            raise ProjectError("Name the custom preset using 1–100 characters.")
        rule = next(
            (
                c
                for c in self.scene.constraints
                if c.kind == "spring" and c.owner_id in self.group_members(group)
            ),
            None,
        )
        if rule is None:
            raise ProjectError("Assign and configure this group before saving a custom preset.")
        presets = self.scene.extra.get("spring_presets", {})
        if not isinstance(presets, Mapping) or len(presets) >= 128 and name not in presets:
            raise ProjectError("A project supports up to 128 custom Spring presets.")
        self.commit(
            "Save custom Spring preset",
            extra={
                **self.scene.extra,
                "spring_presets": {
                    **presets,
                    name: {
                        key: value
                        for key, value in rule.parameters.items()
                        if key != "rest_rotation"
                    },
                },
            },
        )

    def group_color(self, name: str, color: str) -> None:
        """Change only the group's overlay color; artwork and individual bone colors stay intact."""
        if name not in self.group_names() or len(color) != 7 or color[0] != "#":
            raise ProjectError("Choose an existing group and a #RRGGBB color.")
        try:
            int(color[1:], 16)
        except ValueError as error:
            raise ProjectError("Choose a #RRGGBB color.") from error
        self.commit(
            "Change spring group color",
            extra={
                **self.scene.extra,
                "spring_group_metadata": {
                    **self.scene.extra.get("spring_group_metadata", {}),
                    name: {**self.group_metadata(name), "color": color},
                },
            },
        )

    def activation_owners(self, name: str, *, master: bool = False) -> set[str]:
        """Resolve the existing bones or object roots targeted by a group's activation command."""
        members = set(self.group_members(name))
        if not master:
            return members
        return {
            str(r.extra.get("object_id") or next(b.id for b in r.bones if not b.parent_id))
            for r in self.scene.skeletons
            if members.intersection(b.id for b in r.bones)
        }

    def activation_values(
        self, name: str, frame: float, *, master: bool = False
    ) -> tuple[bool, ...]:
        """Read keyed state at a frame without creating keys or changing transport/history."""
        path = "spring.master" if master else "spring.enabled"
        values = {}
        for owner, channel, compiled in self.document.animation.evaluator.spring_controls:
            if channel == path and (value := compiled.sample(frame)) is not None:
                values[owner] = value >= 0.5
        defaults = (
            {c.owner_id: c.enabled for c in self.scene.constraints if c.kind == "spring"}
            if not master
            else {}
        )
        return tuple(
            values.get(owner, defaults.get(owner, True))
            for owner in sorted(self.activation_owners(name, master=master))
        )

    def activation(self, name: str, enabled: bool, frame: float, *, master: bool = False) -> None:
        """Key an entire group or its owning objects with stepped, ordinary editable channels."""
        if type(enabled) is not bool:
            raise ProjectError("Spring activation must be on or off.")
        owners = self.activation_owners(name, master=master)
        if not owners:
            raise ProjectError("Assign bones to this spring group first.")
        path = "spring.master" if master else "spring.enabled"
        frame = number(frame, "Spring key frame")
        if frame < 0:
            raise ProjectError("Spring keys need nonnegative frames.")
        timeline = self.timeline or Timeline(name="Spring activation")
        clip = self.clip or self.blank_clip(timeline, "Spring activation")
        tracks = list(timeline.tracks)
        metadata = self.group_metadata(name)
        for owner in sorted(owners):
            prior = next(
                (t for t in tracks if (t.owner_id, t.property_path) == (owner, path)), None
            )
            track = prior or Track(
                name="Spring master" if master else f"Spring · {name}",
                owner_id=owner,
                property_path=path,
            )
            self.editable(track)
            if not track.keyframes and frame > clip.in_frame:
                track = self.keyed_track(track, clip.in_frame, 1, "step")
            track = self.keyed_track(track, frame, float(enabled), "step")
            track = replace(
                track,
                extra={
                    **track.extra,
                    "spring_activation": True,
                    "spring_group": "Master" if master else name,
                    "spring_group_id": metadata["id"],
                    "appearance_owner": next(
                        (
                            str(
                                r.extra.get("object_id")
                                or next(b.id for b in r.bones if not b.parent_id)
                            )
                            for r in self.scene.skeletons
                            if owner in {b.id for b in r.bones}
                        ),
                        owner,
                    ),
                },
            )
            self.insertion_editable(track)
            tracks = [track if t.id == track.id else t for t in tracks]
            if prior is None:
                tracks.append(track)
        self.publish(
            "Key spring activation",
            replace(timeline, tracks=tuple(tracks)),
            replace(clip, out_frame=max(clip.out_frame, frame)),
        )

    def motion_test(self, members: tuple[str, ...]) -> str:
        """Add a separate three-second driver clip to demonstrate real spring follow-through.

        Existing clips and rest poses stay intact. The new Bézier keys move the
        selected groups' kinematic roots; spring and skin evaluation remain canonical.
        """
        owners = {
            c.owner_id
            for c in self.scene.constraints
            if c.kind == "spring" and c.enabled and c.owner_id in members
        }
        if not owners:
            raise ProjectError("Assign a spring preset to child bones before creating test motion.")
        bones = {b.id: b for rig in self.scene.skeletons for b in rig.bones}
        roots: dict[str, list[str]] = {}
        for key in owners:
            root = bones[key]
            while root.parent_id:
                root = bones[root.parent_id]
            roots.setdefault(root.id, []).append(key)
        pose = RigService(self.document).rest_pose()
        duration = self.scene.settings.fps * 3
        start = self.scene.settings.start_frame
        phases = ((0, 0), (0.12, 1), (0.26, -1), (0.4, 0.65), (0.55, 0), (1, 0))
        tracks = []
        for key, children in roots.items():
            RigService(self.document).editable(key)
            node = pose.nodes[key]
            reach = max(
                math.dist(
                    node.world_matrix[4:],
                    transform_point(pose.nodes[c].world_matrix, bones[c].length, 0),
                )
                for c in children
            )
            distance = min(80.0, max(18.0, reach * 0.16))
            for component, base, amount in (
                ("x", node.local.x, distance),
                ("y", node.local.y, -distance * 0.35),
                ("rotation", node.local.rotation, 24.0),
            ):
                tracks.append(
                    Track(
                        name=f"Spring test · {node.name} · {component}",
                        owner_id=key,
                        property_path=f"transform.{component}",
                        extra={"spring_motion_test": True},
                        keyframes=tuple(
                            Keyframe(
                                frame=start + t * duration,
                                value=base + amount * v,
                                interpolation="bezier",
                            )
                            for t, v in phases
                        ),
                    )
                )
        timeline = Timeline(name="Spring motion test", tracks=tuple(tracks))
        clip = self.blank_clip(timeline, "Spring motion test")
        clip = replace(
            clip,
            out_frame=start + duration,
            loop=True,
            extra={**clip.extra, "spring_motion_test": True},
        )
        self.publish("Create spring motion test", timeline, clip)
        return clip.id

    def group_names(self) -> tuple[str, ...]:
        """Return named and legacy rule-derived groups, retaining the default assignment target."""
        return tuple(
            dict.fromkeys(
                (
                    "Default",
                    *self.scene.extra.get("spring_groups", ()),
                    *(
                        str(c.extra.get("spring_group", "Default"))
                        for c in self.scene.constraints
                        if c.kind == "spring"
                    ),
                    *(
                        str(bone.extra["spring_group"])
                        for rig in self.scene.skeletons
                        for bone in rig.bones
                        if isinstance(bone.extra.get("spring_group"), str)
                    ),
                )
            )
        )

    def group_members(self, name: str) -> tuple[str, ...]:
        """Return configured springs and explicit kinematic members in stable bone order."""
        rules = {
            c.owner_id: c.extra.get("spring_group", "Default")
            for c in self.scene.constraints
            if c.kind == "spring"
        }
        return tuple(
            bone.id
            for rig in self.scene.skeletons
            for bone in rig.bones
            if rules.get(bone.id, bone.extra.get("spring_group")) == name
            and (self.document.animation_scope is None or bone.id in self.document.animation_scope)
        )

    def grouped_skeletons(self, assignments: Mapping[str, str | None]) -> tuple[Skeleton, ...]:
        """Prepare immutable membership metadata; None removes a member without moving its bone."""
        skeletons = []
        for rig in self.scene.skeletons:
            bones = []
            for bone in rig.bones:
                if bone.id in assignments:
                    extra = dict(bone.extra)
                    name = assignments[bone.id]
                    if name is None:
                        extra.pop("spring_group", None)
                    else:
                        extra["spring_group"] = name
                    bone = replace(bone, extra=extra)
                bones.append(bone)
            skeletons.append(replace(rig, bones=tuple(bones)) if tuple(bones) != rig.bones else rig)
        return tuple(skeletons)

    def can_spring(self, bone_id: str) -> bool:
        """Keep the master controller kinematic while allowing anchored deforming segments."""
        bone = RigService(self.document).bone(bone_id)
        return not bone.extra.get("rig_root") and bool(
            bone.parent_id or self.has_object_root(bone_id)
        )

    def has_object_root(self, bone_id: str) -> bool:
        """Identify a separate object/character anchor without inserting dummy skeletal bones."""
        rig = next(r for r in self.scene.skeletons if any(b.id == bone_id for b in r.bones))
        transforms = {record.id for record in (*self.scene.groups, *self.scene.objects)}
        if rig.extra.get("object_id") in transforms:
            return True
        return any(
            actor.skeleton_id == rig.id
            and (
                actor.extra.get("root_object_id") in transforms
                or self.document.animation_context == actor.id
            )
            for actor in self.scene.characters
        )

    def assign_group(
        self, bones: tuple[str, ...], *, group: str, **settings: Any
    ) -> tuple[str, ...]:
        """Assign members in one undo step, using an object's separate root as its anchor.

        Object-owned first bones can oscillate around their fixed base joint.
        Standalone roots without a separate object anchor retain kinematic membership.
        Returns configured rule IDs, empty for an anchor-only assignment.
        """
        if not bones or len(set(bones)) != len(bones):
            raise ProjectError("Select distinct bones for the spring group.")
        if not group.strip() or len(group) > 100:
            raise ProjectError("Spring groups need a name of 1–100 characters.")
        selected = tuple(RigService(self.document).editable(key) for key in bones)
        children = tuple(b.id for b in selected if self.can_spring(b.id))
        anchors = {b.id: group.strip() for b in selected if b.id not in children}
        with self.document.command_group("Assign spring group"):
            rules = self.configure(children, group=group, **settings) if children else ()
            if anchors:
                self.commit("Assign spring anchors", skeletons=self.grouped_skeletons(anchors))
        return rules

    def unassign_group(self, bones: tuple[str, ...], groups: set[str]) -> None:
        """Remove selected spring and anchor memberships, retaining bone poses and animation."""
        selected = set(bones)
        anchors = {
            b.id: None
            for rig in self.scene.skeletons
            for b in rig.bones
            if b.id in selected and b.extra.get("spring_group") in groups
        }
        self.commit(
            "Remove bones from spring group",
            skeletons=self.grouped_skeletons(anchors),
            constraints=tuple(
                c
                for c in self.scene.constraints
                if not (
                    c.kind == "spring"
                    and c.owner_id in selected
                    and c.extra.get("spring_group", "Default") in groups
                )
            ),
            timelines=tuple(
                replace(
                    timeline,
                    tracks=tuple(
                        track
                        for track in timeline.tracks
                        if not (
                            track.owner_id in selected
                            and track.extra.get("spring_activation")
                            and track.extra.get("spring_group") in groups
                        )
                    ),
                )
                for timeline in self.scene.timelines
            ),
        )

    def create_group(self) -> str:
        """Create the next unused Group N as one undoable edit without assigning any bones."""
        names = self.group_names()
        index = 1
        while f"Group {index}" in names:
            index += 1
        name = f"Group {index}"
        self.commit(
            "Create spring group",
            extra={
                **self.scene.extra,
                "spring_groups": (*names, name),
                "spring_group_metadata": {
                    **self.scene.extra.get("spring_group_metadata", {}),
                    name: self.group_metadata(name),
                },
            },
        )
        return name

    def rename_group(self, old: str, new: str) -> None:
        """Rename a group and all its spring references atomically, preserving rule identities."""
        new = new.strip()
        names = self.group_names()
        if old == "Default" or old not in names:
            raise ProjectError("Choose a custom spring group to rename.")
        if not new or len(new) > 100 or new != old and new in names:
            raise ProjectError("Use a unique spring group name of 1–100 characters.")
        if new == old:
            return
        self.commit(
            "Rename spring group",
            skeletons=self.grouped_skeletons(
                {
                    b.id: new
                    for rig in self.scene.skeletons
                    for b in rig.bones
                    if b.extra.get("spring_group") == old
                }
            ),
            extra={
                **self.scene.extra,
                "spring_groups": tuple(new if n == old else n for n in names),
                "spring_group_metadata": {
                    **{n: self.group_metadata(n) for n in names if n != old},
                    new: self.group_metadata(old),
                },
            },
            constraints=tuple(
                replace(c, extra={**c.extra, "spring_group": new})
                if c.kind == "spring" and c.extra.get("spring_group", "Default") == old
                else c
                for c in self.scene.constraints
            ),
            timelines=tuple(
                replace(
                    timeline,
                    tracks=tuple(
                        replace(
                            track,
                            name=f"Spring · {new}",
                            extra={**track.extra, "spring_group": new},
                        )
                        if track.extra.get("spring_activation")
                        and track.extra.get("spring_group") == old
                        else track
                        for track in timeline.tracks
                    ),
                )
                for timeline in self.scene.timelines
            ),
        )

    def remove_group(self, name: str) -> None:
        """Remove a group and its spring rules in one undo step; animation keys stay intact."""
        self.commit(
            "Remove spring group",
            skeletons=self.grouped_skeletons(
                {
                    b.id: None
                    for rig in self.scene.skeletons
                    for b in rig.bones
                    if b.extra.get("spring_group") == name
                }
            ),
            extra={
                **self.scene.extra,
                "spring_groups": tuple(n for n in self.group_names() if n != name),
                "spring_group_metadata": {
                    n: self.group_metadata(n) for n in self.group_names() if n != name
                },
            },
            constraints=tuple(
                c
                for c in self.scene.constraints
                if not (c.kind == "spring" and c.extra.get("spring_group", "Default") == name)
            ),
            timelines=tuple(
                replace(
                    timeline,
                    tracks=tuple(
                        track
                        for track in timeline.tracks
                        if not (
                            track.extra.get("spring_activation")
                            and track.extra.get("spring_group") == name
                        )
                    ),
                )
                for timeline in self.scene.timelines
            ),
        )

    def configure(
        self,
        bones: tuple[str, ...],
        *,
        frequency: float = 3,
        damping: float = 0.5,
        inertia: float = 0.6,
        gravity: float = 0,
        strength: float = 1,
        max_angle: float = 65,
        enabled: bool = True,
        clockwise: float | None = None,
        counterclockwise: float | None = None,
        translate: bool = False,
        rotate: bool = True,
        stretch: float = 0,
        squash: float = 0,
        group: str = "Default",
    ) -> tuple[str, ...]:
        """Validate and upsert one spring per editable child bone in a single undo step."""
        if not bones or len(set(bones)) != len(bones):
            raise ProjectError("Select distinct child bones for spring follow-through.")
        if type(enabled) is not bool or type(translate) is not bool or type(rotate) is not bool:
            raise ProjectError("Spring enabled must be a boolean.")
        parameters = {
            key: number(value, key)
            for key, value in {
                "frequency": frequency,
                "damping": damping,
                "inertia": inertia,
                "gravity": gravity,
                "strength": strength,
                "max_angle": max_angle,
            }.items()
        }
        parameters.update(
            translate=translate, rotate=rotate, stretch=number(stretch), squash=number(squash)
        )
        if clockwise is not None:
            parameters["clockwise"] = number(clockwise)
        if counterclockwise is not None:
            parameters["counterclockwise"] = number(counterclockwise)
        if not group.strip() or len(group) > 100:
            raise ProjectError("Spring groups need a name of 1–100 characters.")
        rules = list(self.scene.constraints)
        changed = []
        reassigned = set()
        anchors: dict[str, None] = {}
        for key in bones:
            bone = RigService(self.document).editable(key)
            if not self.can_spring(key):
                raise ProjectError(
                    "Rig Root is the kinematic anchor. Choose a deforming bone with an anchor."
                )
            if "spring_group" in bone.extra:
                anchors[key] = None
            prior = next((c for c in rules if c.kind == "spring" and c.owner_id == key), None)
            if prior is None or prior.extra.get("spring_group", "Default") != group:
                reassigned.add(key)
            rule = (
                replace(
                    prior,
                    parameters={
                        **parameters,
                        **(
                            {"rest_rotation": bone.transform.rotation}
                            if clockwise is not None or counterclockwise is not None
                            else {}
                        ),
                    },
                    enabled=enabled,
                    extra={
                        **prior.extra,
                        "spring_group": group.strip(),
                        "spring_object_root": self.has_object_root(key),
                    },
                )
                if prior
                else Constraint(
                    name=f"Spring · {bone.name}"[:200],
                    kind="spring",
                    owner_id=key,
                    parameters={
                        **parameters,
                        **(
                            {"rest_rotation": bone.transform.rotation}
                            if clockwise is not None or counterclockwise is not None
                            else {}
                        ),
                    },
                    enabled=enabled,
                    extra={
                        "spring_group": group.strip(),
                        "spring_object_root": self.has_object_root(key),
                    },
                )
            )
            rules = [rule if c.id == rule.id else c for c in rules] if prior else [*rules, rule]
            changed.append(rule)
        # Validate disabled settings too, so re-enabling cannot reveal invalid physics.
        SpringSimulation().advance(
            tuple(self.document.animation.pose.nodes.values()),
            tuple(replace(c, enabled=True) for c in changed),
            1 / 60,
        )
        self.commit(
            "Configure spring follow-through",
            constraints=tuple(rules),
            timelines=self.reassigned_activation_tracks(reassigned, group),
            extra={
                **self.scene.extra,
                "spring_group_metadata": {
                    **self.scene.extra.get("spring_group_metadata", {}),
                    group: self.group_metadata(group),
                },
            },
            **({"skeletons": self.grouped_skeletons(anchors)} if anchors else {}),
        )
        return tuple(c.id for c in changed)

    def reassigned_activation_tracks(self, bones: set[str], group: str) -> tuple[Timeline, ...]:
        """Move activation ownership with membership, adopting the destination's keyed state."""
        owners = {
            bone.id: str(
                rig.extra.get("object_id") or next(b.id for b in rig.bones if not b.parent_id)
            )
            for rig in self.scene.skeletons
            for bone in rig.bones
        }
        output = []
        for timeline in self.scene.timelines:
            templates = {
                str(t.extra.get("appearance_owner", "")): t
                for t in timeline.tracks
                if t.extra.get("spring_activation")
                and t.property_path == "spring.enabled"
                and t.extra.get("spring_group") == group
                and t.owner_id not in bones
            }
            tracks = [
                t
                for t in timeline.tracks
                if not (
                    t.owner_id in bones
                    and t.extra.get("spring_activation")
                    and t.property_path == "spring.enabled"
                )
            ]
            for key in sorted(bones):
                template = templates.get(owners.get(key, ""))
                if template:
                    tracks.append(
                        replace(
                            template,
                            id=str(uuid4()),
                            owner_id=key,
                            keyframes=tuple(
                                replace(k, id=str(uuid4())) for k in template.keyframes
                            ),
                        )
                    )
            output.append(replace(timeline, tracks=tuple(tracks)))
        return tuple(output)

    def squash(self, owner: str, frame: float, amount: float, duration: float = 8) -> None:
        """Key an area-preserving squash/recovery around the current evaluated scale."""
        if not -0.8 <= number(amount) <= 0.8 or not 0 < number(duration) <= 1000:
            raise ProjectError("Squash amount must be −0.8 to 0.8 and duration 0–1000 frames.")
        node = self.document.animation.evaluate(frame).nodes.get(owner)
        if node is None:
            raise ProjectError("Choose a transform control for squash and stretch.")
        with self.document.command_group("Squash and stretch"):
            for time, factor in (
                (frame, 1),
                (frame + duration / 2, 1 + amount),
                (frame + duration, 1),
            ):
                self.key(owner, "transform.scale_x", time, node.local.scale_x * factor)
                self.key(owner, "transform.scale_y", time, node.local.scale_y / factor)

    def bounce(
        self,
        owner: str,
        *,
        preset: str = "Soft bounce",
        start: float = 0,
        duration: float = 48,
        height: float = 100,
    ) -> None:
        """Create a fresh original bounce clip with decaying arcs and volume-preserving impacts."""
        if (
            preset not in BOUNCES
            or not 1 <= number(duration) <= 10000
            or not number(start) >= 0
            or not 0 <= number(height) <= 100000
        ):
            raise ProjectError(
                "Choose a bounce preset, positive duration, start and bounded height."
            )
        node = self.document.animation.evaluate(start).nodes.get(owner)
        if node is None:
            raise ProjectError("Select a bone, object or group to bounce.")
        self.editable(Track(owner_id=owner, property_path="transform.y"))
        cycles, decay, squash = BOUNCES[preset]
        frames = sorted(
            {
                start,
                start + duration,
                *(float(i) for i in range(math.ceil(start), math.floor(start + duration) + 1)),
            }
        )
        channels: dict[str, list[Keyframe]] = {"y": [], "scale_x": [], "scale_y": []}
        for frame in frames:
            phase = (frame - start) / duration * cycles
            arc = abs(math.sin(math.pi * phase)) * decay ** int(phase)
            impact = max(0, 1 - abs(math.sin(math.pi * phase)) * 8) * squash * decay ** int(phase)
            if frame in (start, start + duration):
                arc, impact = 0, 0
            for component, value in (
                ("y", node.local.y - height * arc),
                ("scale_x", node.local.scale_x * (1 + impact)),
                ("scale_y", node.local.scale_y / (1 + impact)),
            ):
                channels[component].append(Keyframe(frame=frame, value=value))
        timeline = Timeline(
            name=preset,
            tracks=tuple(
                Track(
                    name=f"Bounce · {key}",
                    owner_id=owner,
                    property_path=f"transform.{key}",
                    keyframes=tuple(values),
                )
                for key, values in channels.items()
            ),
        )
        clip = AnimationClip(
            name=preset,
            timeline_id=timeline.id,
            in_frame=start,
            out_frame=start + duration,
            extra={"bounce": {"preset": preset, "height": height}},
        )
        self.publish("Create bounce motion", timeline, clip)

    def bake(
        self, group: str | None = None, *, tail_seconds: float = 3, activate_baked: bool = True
    ) -> str:
        """Simulate from clip start at fixed 60 Hz and publish frame-sampled FK keys.

        Baking retains the entire simulation history. Fractional output samples
        clone the last fixed state, so output
        sampling cannot perturb subsequent integration. Existing non-bone tracks
        and markers survive in the new clip; the source clip and rig are untouched.
        """
        evaluator = self.document.animation.evaluator
        clip, timeline = evaluator.clip, evaluator.timeline
        if clip is None or timeline is None or not evaluator.springs:
            raise ProjectError("Select an animated clip with enabled spring bones to bake.")
        fps = self.scene.settings.fps
        tail_seconds = number(tail_seconds, "Spring settling tail")
        if not 0 <= tail_seconds <= 30:
            raise ProjectError("Spring settling tails range from 0 to 30 seconds.")
        selected = set(self.group_members(group)) if group is not None else None
        group_rules = tuple(
            r for r in evaluator.springs if selected is None or r.owner_id in selected
        )
        if not group_rules:
            raise ProjectError("This group has no live spring motion left to bake.")
        # Bound the residual transient to approximately 0.01% for either damping regime.
        settling = max(
            math.log(10000)
            / (
                math.tau
                * float(r.parameters.get("frequency", 3))
                * (
                    float(r.parameters.get("damping", 0.5))
                    if float(r.parameters.get("damping", 0.5)) <= 1
                    else float(r.parameters["damping"])
                    - math.sqrt(float(r.parameters["damping"]) ** 2 - 1)
                )
            )
            for r in group_rules
        )
        tail_seconds = max(tail_seconds, settling)
        end = clip.out_frame + tail_seconds * fps
        if (end - clip.in_frame) / fps > 120:
            raise ProjectError("Bake at most 120 seconds per clip.")
        bones = tuple(
            b.id
            for rig in self.scene.skeletons
            for b in rig.bones
            if selected is None or b.id in selected
            if self.document.animation_scope is None or b.id in self.document.animation_scope
        )
        if not bones:
            raise ProjectError("Choose a spring group with assigned bones to bake.")
        frames = sorted(
            {
                clip.in_frame,
                end,
                *(float(i) for i in range(math.ceil(clip.in_frame), math.floor(end) + 1)),
                *(
                    k.frame
                    for t in timeline.tracks
                    for k in t.keyframes
                    if clip.in_frame <= k.frame <= clip.out_frame
                ),
            }
        )
        if len(frames) * len(bones) > 100000:
            raise ProjectError("Bake at most 100,000 bone samples; shorten the clip.")
        for key in bones:
            self.editable(Track(owner_id=key, property_path="transform.rotation"))
        simulation = SpringSimulation()
        tick = 0
        result = list(evaluator.sample_spring_input(clip.in_frame))
        simulation.advance(result, evaluator.active_springs(clip.in_frame), 1 / 60)
        channels: dict[tuple[str, str], list[Keyframe]] = {}
        for frame in frames:
            goal = math.floor((frame - clip.in_frame) / fps * 60 + 1e-9)
            while tick < goal:
                tick += 1
                result = simulation.advance(
                    evaluator.sample_spring_input(clip.in_frame + tick * fps / 60),
                    evaluator.active_springs(clip.in_frame + tick * fps / 60),
                    1 / 60,
                )
            remainder = (frame - clip.in_frame) / fps - tick / 60
            pose = (
                copy.deepcopy(simulation).advance(
                    evaluator.sample_spring_input(frame), evaluator.active_springs(frame), remainder
                )
                if remainder > 1e-9
                else result
            )
            resolved, _ = evaluator.joint_limits.apply(evaluator.spring_output(pose, frame))
            for node in resolved:
                if node.id not in bones:
                    continue
                for path in (
                    "x",
                    "y",
                    "rotation",
                    "scale_x",
                    "scale_y",
                    "pivot_x",
                    "pivot_y",
                    "length",
                ):
                    value = node.length if path == "length" else getattr(node.local, path)
                    channel = path if path == "length" else f"transform.{path}"
                    channels.setdefault((node.id, channel), []).append(
                        Keyframe(frame=frame, value=value)
                    )
        tracks = [
            replace(
                t,
                id=str(uuid4()),
                keyframes=tuple(replace(k, id=str(uuid4())) for k in t.keyframes),
            )
            for t in timeline.tracks
            if (t.owner_id, t.property_path) not in channels
        ]
        tracks.extend(
            Track(name=f"Baked · {path}", owner_id=key, property_path=path, keyframes=tuple(values))
            for (key, path), values in channels.items()
        )
        output = replace(
            timeline,
            id=str(uuid4()),
            name=f"{timeline.name[:175]} · baked",
            tracks=tuple(tracks),
            markers=tuple(replace(m, id=str(uuid4())) for m in timeline.markers),
        )
        baked = replace(
            clip,
            id=str(uuid4()),
            name=f"{clip.name[:175]} · baked",
            timeline_id=output.id,
            out_frame=end,
            extra={
                **clip.extra,
                "fk_bones": tuple(dict.fromkeys((*clip.extra.get("fk_bones", ()), *bones))),
                "spring_baked_bones": tuple(
                    dict.fromkeys((*clip.extra.get("spring_baked_bones", ()), *bones))
                ),
                "dynamics_bake": {
                    "source_clip": clip.id,
                    "hz": 60,
                    "group": group,
                    "tail_seconds": tail_seconds,
                },
            },
        )
        self.publish("Bake spring dynamics", output, baked)
        if not activate_baked:
            self.document.select_animation_clip(clip.id)
        return baked.id
