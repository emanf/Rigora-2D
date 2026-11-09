"""Author independent Scene object following, reusable grip points and held pickup keys."""

import math
from dataclasses import replace
from typing import Any
from uuid import uuid4

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.scene_editing import SceneEditingService
from rigora.domain.entities import (
    Bone,
    Camera,
    Constraint,
    Group,
    Keyframe,
    SceneObject,
    Timeline,
    Track,
)
from rigora.domain.geometry import IDENTITY, affine, inverse, multiply
from rigora.domain.scene_attachments import (
    ATTACHMENT_PATH,
    AttachmentState,
    point_matrix,
    points,
    validate_points,
)
from rigora.domain.validation import ProjectError, json_copy
from rigora.engine.scene_following import inherited


class SceneAttachmentService(SceneEditingService):
    """Keep Scene relationships separate from skinning, object ownership and rig cleanup."""

    def state(self, owner: str, frame: float | None = None) -> AttachmentState:
        """Return the active held state or an independent state for an unattached Object."""
        at = self.document.animation.pose.frame if frame is None else frame
        return self.document.animation.evaluator.scene_followers.states(at).get(
            owner, AttachmentState()
        )

    def point_choices(self, owner: str) -> tuple[tuple[str, str], ...]:
        """Expose owner-local named grips and built-in points through all application clients."""
        return points(self.record(owner))

    def add_point(
        self,
        owner: str,
        name: str,
        *,
        x: float = 0,
        y: float = 0,
        rotation: float = 0,
        identity: str = "",
        view: str = "",
    ) -> str:
        """Create or edit a reusable local point with one Undo step and stable identity."""
        record = self.record(owner)
        if not isinstance(record, (Bone, Group, SceneObject)) or self.locked(owner):
            raise ProjectError("Choose an unlocked object or bone for its grip point.")
        if any(not math.isfinite(v) or abs(v) > 1e9 for v in (x, y, rotation)):
            raise ProjectError("Grip position and rotation must be finite values.")
        definitions = json_copy(record.extra.get("attachment_points", ()))
        key = identity or str(uuid4())
        previous = next((p for p in definitions if p["id"] == key), None)
        if identity and previous is None:
            raise ProjectError("This grip point no longer exists.")
        point = dict(previous or {"id": key, "matrix": list(IDENTITY)})
        point["name"] = name.strip()
        value = list(affine(x, y, rotation, 1, 1, 0, 0))
        if view:
            from rigora.domain.object_views import VIEW_SLOTS

            if view not in VIEW_SLOTS:
                raise ProjectError("Choose an existing Object view for this grip offset.")
            point["views"] = {**point.get("views", {}), view: value}
        else:
            point["matrix"] = value
        definitions = [p for p in definitions if p["id"] != key] + [point]
        validate_points(definitions)
        self.update_records(
            {owner: replace(record, extra={**record.extra, "attachment_points": definitions})},
            "Save grip point",
        )
        return key

    def remove_point(self, owner: str, identity: str) -> None:
        """Remove only an unused point, protecting references in setup and animation keys."""
        if self.locked(owner):
            raise ProjectError("Unlock the point's object before removing it.")
        for rule in self.scene.constraints:
            if rule.kind == "scene_attachment":
                state = AttachmentState.from_dict({**rule.parameters, "target_id": rule.target_id})
                if self._uses_point(rule.owner_id, state, owner, identity):
                    raise ProjectError(
                        "This grip is in use. Choose another grip on its attachments first."
                    )
        for timeline in self.scene.timelines:
            for track in timeline.tracks:
                for key in track.keyframes if track.property_path == ATTACHMENT_PATH else ():
                    if "scene_attachment" in key.extra and self._uses_point(
                        track.owner_id,
                        AttachmentState.from_dict(key.extra["scene_attachment"]),
                        owner,
                        identity,
                    ):
                        raise ProjectError(
                            "This grip is used by animation. Edit those attachment keys first."
                        )
        record = self.record(owner)
        definitions = [p for p in record.extra.get("attachment_points", ()) if p["id"] != identity]
        self.update_records(
            {owner: replace(record, extra={**record.extra, "attachment_points": definitions})},
            "Remove grip point",
        )

    @staticmethod
    def _uses_point(source: str, state: AttachmentState, owner: str, identity: str) -> bool:
        """Check a point's scoped identity without confusing another instance's same grip ID."""
        return (state.target_id == owner and state.point == identity) or (
            source == owner and state.source_point == identity
        )

    def attach(
        self,
        sources: tuple[str, ...],
        target: str | None,
        *,
        point: str = "",
        source_point: str = "",
        snap: bool = False,
        frame: float | None = None,
        inherit_rotation: bool = True,
        inherit_scale: bool = True,
    ) -> None:
        """Attach entire Objects without touching their meshes; optionally key the pickup here."""
        if self.document.animation_context is not None:
            raise ProjectError(
                "Return to Scene to attach placed objects. "
                "Grip points can be edited in Object Editor."
            )
        if not sources:
            raise ProjectError("Select the object you want to attach first.")
        records = self.records()
        if target is not None and (
            not isinstance(records.get(target), (Bone, Group, SceneObject))
            or isinstance(records.get(target), Camera)
            or self.locked(target)
        ):
            raise ProjectError("Choose an unlocked object, bone or grip to follow.")
        at = self.document.animation.pose.frame if frame is None else frame
        if not math.isfinite(at) or not 0 <= at <= 1e7:
            raise ProjectError("Choose an attachment frame between 0 and 10,000,000.")
        pose = self.document.animation.evaluate(at).for_display()
        from rigora.application_services.characters import CharacterService
        from rigora.application_services.object_views import ObjectViewsService

        views = ObjectViewsService(self.document)
        characters = CharacterService(self.document)

        def current_view(key: str) -> str:
            root = characters.object_root(key)
            return views.current(root.id) if root else "Default"

        for source in sources:
            if not isinstance(records.get(source), (Group, SceneObject)) or self.locked(source):
                raise ProjectError("Choose an unlocked Scene object to attach.")
            if isinstance(records[source], Camera):
                raise ProjectError("Use camera constraints to move a camera.")
            if source == target:
                raise ProjectError("An object cannot attach to itself or create a cycle.")
        with self.document.command_group(
            "Key Scene attachment" if frame is not None else "Attach Scene object"
        ):
            for source in dict.fromkeys(sources):
                node = pose.nodes[source]
                target_matrix = (
                    pose.nodes[target].world_matrix
                    if target
                    else pose.nodes[node.parent_id].world_matrix
                    if node.parent_id
                    else IDENTITY
                )
                target_matrix = multiply(
                    inherited(target_matrix, inherit_rotation, inherit_scale),
                    point_matrix(records[target], point, current_view(target))
                    if target
                    else IDENTITY,
                )
                source_matrix = point_matrix(records[source], source_point, current_view(source))
                state = AttachmentState(
                    target,
                    point,
                    source_point,
                    IDENTITY
                    if snap and target
                    else multiply(
                        multiply(inverse(target_matrix), node.world_matrix), source_matrix
                    ),
                    node.local_matrix,
                    inherit_rotation,
                    inherit_scale,
                )
                self._publish(source, state, frame, pose)

    def detach(self, sources: tuple[str, ...], *, frame: float | None = None) -> None:
        """Release only the Scene relationship, keeping the evaluated pose and all rig data."""
        self.attach(sources, None, frame=frame)

    def key_current(self, owner: str, frame: float) -> None:
        """Key the evaluated relationship without re-snapping or losing its grip offset."""
        if self.document.animation_context:
            raise ProjectError("Key Scene attachments in the Scene timeline.")
        if self.locked(owner):
            raise ProjectError("Unlock this object before keying its attachment.")
        state = self.state(owner, frame)
        with self.document.command_group("Key Scene attachment"):
            self._publish(
                owner, state, frame, self.document.animation.evaluate(frame).for_display()
            )

    def references_targets(self, removed: set[str]) -> bool:
        """Check setup and all timelines before deleting referenced Scene or rig entries."""
        return any(
            c.kind == "scene_attachment" and c.owner_id not in removed and c.target_id in removed
            for c in self.scene.constraints
        ) or any(
            t.property_path == ATTACHMENT_PATH
            and t.owner_id not in removed
            and k.extra.get("scene_attachment", {}).get("target_id") in removed
            for timeline in self.scene.timelines
            for t in timeline.tracks
            for k in t.keyframes
        )

    def release_targets(self, removed: set[str]) -> None:
        """Freeze affected setup and held keys before their targets disappear; retain Undo data."""
        if not self.references_targets(removed):
            return
        evaluation_document = self.document
        if self.document.animation_context:
            evaluation_document = self.document.fork()
            evaluation_document.set_animation_context(None)
        evaluation_service = SceneAttachmentService(evaluation_document)

        def released(owner: str, state: AttachmentState, frame: float) -> AttachmentState:
            pose = evaluation_document.animation.evaluate(frame).for_display()
            node = pose.nodes[owner]
            parent = pose.nodes.get(node.parent_id or "")
            world = (
                multiply(inverse(parent.world_matrix), node.world_matrix)
                if parent
                else node.world_matrix
            )
            return replace(
                state,
                target_id=None,
                point="",
                bind_matrix=node.local_matrix,
                offset=multiply(
                    world,
                    point_matrix(
                        self.record(owner),
                        state.source_point,
                        evaluation_document.animation.evaluator.attachment_views(frame).get(
                            owner, ""
                        ),
                    ),
                ),
                inherit_rotation=True,
                inherit_scale=True,
            )

        frame = evaluation_document.animation.pose.frame
        active_timeline = evaluation_document.animation.evaluator.timeline
        active_releases = {
            owner: released(owner, state, frame)
            for owner, state in evaluation_document.animation.evaluator.scene_followers.states(
                frame
            ).items()
            if owner not in removed and state.target_id in removed
        }
        rules = []
        for rule in self.scene.constraints:
            if (
                rule.kind == "scene_attachment"
                and rule.owner_id not in removed
                and rule.target_id in removed
            ):
                state = released(rule.owner_id, evaluation_service.state(rule.owner_id), frame)
                payload = state.to_dict()
                payload.pop("target_id")
                rule = replace(rule, target_id=None, parameters=payload)
            rules.append(rule)
        timelines = []
        for timeline in self.scene.timelines:
            tracks = []
            for track in timeline.tracks:
                keys = []
                for key in track.keyframes:
                    if (
                        track.property_path == ATTACHMENT_PATH
                        and track.owner_id not in removed
                        and key.extra.get("scene_attachment", {}).get("target_id") in removed
                    ):
                        state = released(
                            track.owner_id,
                            AttachmentState.from_dict(key.extra["scene_attachment"]),
                            key.frame,
                        )
                        key = replace(
                            key,
                            value=0,
                            extra={
                                **key.extra,
                                "scene_attachment": state.to_dict(),
                                "attachment_label": "Independent",
                            },
                        )
                    keys.append(key)
                if (
                    track.property_path == ATTACHMENT_PATH
                    and track.owner_id in active_releases
                    and active_timeline
                    and timeline.id == active_timeline.id
                ):
                    state = active_releases[track.owner_id]
                    old = next((k for k in keys if k.frame == frame), None)
                    key = Keyframe(
                        id=old.id if old else str(uuid4()),
                        frame=frame,
                        value=0,
                        interpolation="step",
                        extra={
                            "scene_attachment": state.to_dict(),
                            "attachment_label": "Independent",
                        },
                    )
                    keys = sorted(
                        [k for k in keys if k.frame != frame] + [key], key=lambda k: k.frame
                    )
                tracks.append(replace(track, keyframes=tuple(keys)))
            timelines.append(replace(timeline, tracks=tuple(tracks)))
        self.commit(
            "Release deleted attachment targets",
            constraints=tuple(rules),
            timelines=tuple(timelines),
        )

    def _publish(self, owner: str, state: AttachmentState, frame: float | None, pose: Any) -> None:
        """Store one canonical setup constraint and, when requested, an ordinary held key."""
        prior = next(
            (
                c
                for c in self.scene.constraints
                if c.owner_id == owner and c.kind == "scene_attachment"
            ),
            None,
        )
        conflicting = [
            c
            for c in self.scene.constraints
            if c.owner_id == owner and c.kind not in ("scene_attachment", "parent", "space_switch")
        ]
        if conflicting:
            raise ProjectError(
                "This object has another driving constraint. Remove it before attaching."
            )
        node = pose.nodes[owner]
        parent = pose.nodes.get(node.parent_id or "")
        independent = AttachmentState(
            offset=multiply(inverse(parent.world_matrix), node.world_matrix)
            if parent
            else node.world_matrix,
            bind_matrix=node.local_matrix,
        )
        default = (
            state
            if frame is None
            else AttachmentState.from_dict({**prior.parameters, "target_id": prior.target_id})
            if prior
            else independent
        )
        payload = default.to_dict()
        payload.pop("target_id")
        rule = Constraint(
            id=prior.id if prior else str(uuid4()),
            name="Scene attachment",
            kind="scene_attachment",
            owner_id=owner,
            target_id=default.target_id,
            parameters=payload,
        )
        rules = tuple(
            c
            for c in self.scene.constraints
            if c.owner_id != owner or c.kind not in ("parent", "space_switch", "scene_attachment")
        ) + (rule,)
        timelines = self.scene.timelines
        if frame is None:
            for timeline in timelines:
                for track in timeline.tracks:
                    if (track.owner_id, track.property_path) == (owner, ATTACHMENT_PATH):
                        AnimationEditingService(self.document).editable(track)
            timelines = tuple(
                replace(
                    t,
                    tracks=tuple(
                        v
                        for v in t.tracks
                        if (v.owner_id, v.property_path) != (owner, ATTACHMENT_PATH)
                    ),
                )
                for t in timelines
            )
        self.commit("Set Scene attachment", constraints=rules, timelines=timelines)
        if frame is not None:
            editor = AnimationEditingService(self.document)
            timeline = editor.timeline or Timeline(name="Scene animation")
            clip = editor.clip or editor.blank_clip(timeline)
            track = next(
                (
                    t
                    for t in timeline.tracks
                    if (t.owner_id, t.property_path) == (owner, ATTACHMENT_PATH)
                ),
                Track(name="Attachment", owner_id=owner, property_path=ATTACHMENT_PATH),
            )
            editor.insertion_editable(track)
            keys = list(track.keyframes)
            if not keys and frame > clip.in_frame:
                keys.append(
                    Keyframe(
                        frame=clip.in_frame,
                        value=float(default.target_id is not None),
                        interpolation="step",
                        extra={
                            "scene_attachment": default.to_dict(),
                            "attachment_label": self.target_label(default),
                        },
                    )
                )
            previous = next((key for key in keys if key.frame == frame), None)
            key = Keyframe(
                id=previous.id if previous else str(uuid4()),
                frame=frame,
                value=float(state.target_id is not None),
                interpolation="step",
                extra={
                    "scene_attachment": state.to_dict(),
                    "attachment_label": self.target_label(state),
                },
            )
            track = replace(
                track,
                keyframes=tuple(
                    sorted([k for k in keys if k.frame != frame] + [key], key=lambda k: k.frame)
                ),
            )
            tracks = tuple(t for t in timeline.tracks if t.id != track.id) + (track,)
            editor.publish(
                "Key Scene attachment",
                replace(timeline, tracks=tracks),
                replace(
                    clip, in_frame=min(frame, clip.in_frame), out_frame=max(frame, clip.out_frame)
                ),
            )
        warnings = self.document.animation.evaluator.scene_followers.warnings
        if warnings:
            raise ProjectError(
                "Attachment would create a dependency cycle or missing target. " + warnings[0]
            )

    def target_label(self, state: AttachmentState) -> str:
        """Describe the placed object and grip using user names rather than database suffixes."""
        if state.target_id is None:
            return "Independent"
        record = self.records().get(state.target_id)
        if record is None:
            return "Missing target"
        from rigora.application_services.characters import CharacterService

        root = CharacterService(self.document).object_root(state.target_id)
        labels = [root.name] if root and root.id != state.target_id else []
        labels.append({"hand.R": "Right hand", "hand.L": "Left hand"}.get(record.name, record.name))
        if state.point:
            labels.append(dict(points(record)).get(state.point, "Missing grip"))
        return " / ".join(labels)

    def edit_offset(
        self, owner: str, *, x: float, y: float, rotation: float, frame: float | None = None
    ) -> None:
        """Change a grip offset without discarding shear or other affine source detail."""
        if self.document.animation_context:
            raise ProjectError("Edit Scene attachment offsets in Scene mode.")
        if self.locked(owner):
            raise ProjectError("Unlock this object before editing its attachment.")
        state = self.state(owner, frame)
        current = math.degrees(math.atan2(state.offset[1], state.offset[0]))
        linear = multiply(affine(0, 0, rotation - current, 1, 1, 0, 0), state.offset)
        state = replace(state, offset=(*linear[:4], x, y))
        AttachmentState.from_dict(state.to_dict())
        with self.document.command_group("Edit attachment offset"):
            self._publish(owner, state, frame, self.document.animation.pose.for_display())
