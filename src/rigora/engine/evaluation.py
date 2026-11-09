"""Stateless animation evaluation over an indexed scene hierarchy."""

import math
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from functools import lru_cache
from types import MappingProxyType

from rigora.domain.draw_order import scene_draw_order
from rigora.domain.entities import Bone, Camera, Constraint, Group, SceneObject
from rigora.domain.geometry import Matrix, affine, decompose, inverse, multiply, transform_point
from rigora.domain.object_views import VIEW_SLOTS, view_partitions
from rigora.domain.project import Scene
from rigora.domain.scene_attachments import ATTACHMENT_PATH
from rigora.domain.sprite_sequence import frame_asset, validate_sequence
from rigora.domain.validation import integer
from rigora.engine.constraints import ConstraintPlan, ConstraintSolver
from rigora.engine.deformation import DeformationPlan, DeformerSolver
from rigora.engine.motion_layers import influence, ordered_layers
from rigora.engine.particles import sample_particles
from rigora.engine.sampling import CompiledTrack, EvaluationError, TrackSampler, number
from rigora.engine.scene_following import SceneFollowPlan
from rigora.engine.springs import SpringCursor, sample_springs
from rigora.engine.state import NodePose, ScenePose, TransformValues
from rigora.engine.time import FrameRange
from rigora.engine.view_switching import movement_direction, movement_settings

_COMPONENTS = ("x", "y", "rotation", "scale_x", "scale_y", "pivot_x", "pivot_y")


@dataclass(frozen=True, slots=True)
class _Node:
    """Compiled immutable node metadata and rest components shared across frame evaluations."""

    source: Group | SceneObject | Bone
    parent_index: int
    kind: str
    rest: tuple[float, ...]
    visible: bool


class SceneEvaluator:
    """Compile indices once and derive every requested pose independently of playback history."""

    def __init__(
        self,
        scene: Scene,
        clip_id: str | None = None,
        *,
        solvers: Mapping[str, ConstraintSolver] | None = None,
        deformers: Mapping[str, DeformerSolver] | None = None,
        samplers: Mapping[str, TrackSampler] | None = None,
        apply_joint_limits: bool = True,
        select_first_clip: bool = True,
        scope: frozenset[str] | None = None,
        local_object: str | None = None,
        deformation_plan: DeformationPlan | None = None,
        controls: Callable[[float], Mapping[tuple[str, str], float]] | None = None,
    ) -> None:
        """Index one clip's tracks and an acyclic parent-first scene graph."""
        self.scene = scene
        self.scope = scope
        self.local_object = local_object
        self.controls = controls
        clip = (
            next((clip for clip in scene.clips if clip.id == clip_id), None)
            if clip_id is not None
            else next(iter(scene.clips), None)
            if select_first_clip
            else None
        )
        if clip_id is not None and clip is None:
            raise EvaluationError("The animation clip is not part of this scene.")
        self.clip = clip
        self.range = FrameRange(
            clip.in_frame if clip else scene.settings.start_frame,
            clip.out_frame if clip else scene.settings.end_frame,
            scene.settings.fps,
        )
        self.nodes = self._compile_nodes(scene)
        mesh_owners = {mesh.id: mesh.object_id for mesh in scene.meshes}
        self.occlusions = tuple(
            (
                tuple(mesh_owners[k] for k in variant["meshes"] if k in mesh_owners),
                tuple(mesh_owners[k] for k in variant["occludes"] if k in mesh_owners),
            )
            for owner in (*scene.groups, *scene.characters, *scene.objects)
            for group in owner.extra.get("outfits", ())
            for variant in group["variants"]
            if variant.get("occludes")
        )
        if local_object:
            self.nodes = self._object_space_nodes(local_object)
        self.deformation = (
            deformation_plan
            if deformation_plan is not None and deformation_plan.matches(scene, deformers)
            else DeformationPlan(scene, deformers)
        )
        self.sprite_sequences = {
            mesh.id: validate_sequence(mesh.extra["sprite_sequence"])
            for mesh in scene.meshes
            if "sprite_sequence" in mesh.extra
        }
        fk = clip.extra.get("fk_bones", ()) if clip else ()
        spring_baked = (
            clip.extra.get("spring_baked_bones", fk if clip.extra.get("dynamics_bake") else ())
            if clip
            else ()
        )
        bone_ids = {n.source.id for n in self.nodes if n.kind == "bone"}
        if not isinstance(fk, (tuple, list)) or any(
            not isinstance(key, str) or key not in bone_ids for key in fk
        ):
            raise EvaluationError("Baked FK controls must reference existing bones.")
        if not isinstance(spring_baked, (tuple, list)) or any(
            not isinstance(key, str) or key not in bone_ids for key in spring_baked
        ):
            raise EvaluationError("Baked Spring controls must reference existing bones.")
        # Baked local poses already contain constraint and dynamics results. Other
        # clips continue to use the rig's constraints without global rig mutations.
        rules = tuple(
            c
            for c in scene.constraints
            if (
                c.owner_id not in (spring_baked if c.kind == "spring" else fk)
                and c.parameters.get("end_bone_id") not in fk
            )
            and (scope is None or c.owner_id in scope)
            and not (
                local_object
                and (
                    c.kind == "scene_attachment"
                    or c.owner_id == local_object
                    and c.kind in ("parent", "space_switch")
                )
            )
        )
        self.rules = rules
        scene_owners = {n.source.id for n in self.nodes if n.kind != "bone"}
        followers = tuple(
            c
            for c in rules
            if c.kind in ("parent", "space_switch", "scene_attachment")
            and c.owner_id in scene_owners
        )
        self.constraints = ConstraintPlan(
            tuple(
                c
                for c in rules
                if c.kind not in ("spring", "shot_transition") and c not in followers
            ),
            {n.source.id: n.source.parent_id for n in self.nodes},
            solvers,
        )
        self.springs = tuple(c for c in rules if c.kind == "spring")
        self.shot_transitions = tuple(
            (
                c,
                ConstraintPlan(
                    (c,), {n.source.id: n.source.parent_id for n in self.nodes}, solvers
                ),
            )
            for c in rules
            if c.kind == "shot_transition" and c.enabled
        )
        self.spring_controls: list[tuple[str, str, CompiledTrack]] = []
        self.motion_controls: list[tuple[str, str, CompiledTrack]] = []
        self.spring_owners = {
            b.id: str(r.extra.get("object_id", "")) for r in scene.skeletons for b in r.bones
        }
        self.spring_bindings = {
            str(stage.parameters["object_group"]): tuple(stage.parameters["object_group_bind"])
            for stage in scene.deformers
            if stage.kind == "skinning"
            and stage.parameters.get("object_group")
            and stage.parameters.get("object_group_bind")
        }
        self.library_rigs = {
            bone.id: str(rig.extra["object_id"])
            for rig in scene.skeletons
            if rig.extra.get("library_bind")
            and rig.extra.get("object_id")
            and rig.extra["object_id"] not in self.spring_bindings
            for bone in rig.bones
        }
        self.skinned_rigs = {
            bone: owner
            for bone, owner in self.spring_owners.items()
            if owner in self.spring_bindings
        }
        self.skinned_rigs.update(
            (bone, str(stage.parameters["object_group"]))
            for stage in scene.deformers
            if stage.kind == "skinning" and stage.parameters.get("object_group")
            for bone in stage.parameters.get("bind_matrices", {})
        )
        for rig in scene.skeletons:
            if rig.extra.get("library_bind") and rig.extra.get("object_id"):
                self.spring_bindings.setdefault(
                    str(rig.extra["object_id"]), tuple(rig.extra["library_bind"])
                )
        rest_world: list[Matrix] = []
        for node in self.nodes:
            local = affine(*node.rest[:7])
            world = (
                multiply(rest_world[node.parent_index], local) if node.parent_index >= 0 else local
            )
            rest_world.append(world)
            if node.source.id in self.spring_owners.values():
                self.spring_bindings.setdefault(node.source.id, world)
        self.spring_cursor = SpringCursor()
        self.joint_limits = ConstraintPlan(
            tuple(
                Constraint(
                    name=f"{n.source.name} joint angle",
                    kind="minimum_joint_angle",
                    owner_id=n.source.id,
                    parameters={"angle": n.source.extra["minimum_joint_angle"]},
                )
                for n in self.nodes
                if apply_joint_limits
                and n.kind == "bone"
                and n.source.parent_id
                and n.source.extra.get("minimum_joint_angle", 0)
            ),
            {n.source.id: n.source.parent_id for n in self.nodes},
        )
        self.sample_kinematic = lru_cache(
            maxsize=min(512, max(2, 20000 // max(1, len(self.nodes))))
        )(self._kinematic)
        self.sample_spring_input = lru_cache(
            maxsize=min(512, max(2, 20000 // max(1, len(self.nodes))))
        )(self._spring_input)
        indices = {node.source.id: index for index, node in enumerate(self.nodes)}
        self.node_indices = indices
        timeline = next(
            (item for item in scene.timelines if clip and item.id == clip.timeline_id), None
        )
        if clip and timeline is None:
            raise EvaluationError("The animation clip references a missing timeline.")
        self.timeline = timeline
        self.view_tracks = (
            {
                t.owner_id: CompiledTrack(t, samplers)
                for t in timeline.tracks
                if t.property_path == "object.view"
            }
            if timeline
            else {}
        )
        self.view_nodes: dict[str, tuple[str, frozenset[int]]] = {}
        self.view_defaults: dict[str, int] = {}
        self.movement_views = {
            root.id: movement_settings(root.extra["movement_views"])
            for root in scene.groups
            if root.extra.get("movement_views")
        }
        # Deleted/out-of-scope drivers leave a dormant mapping that Undo can restore.
        self.movement_views = {
            owner: settings
            for owner, settings in self.movement_views.items()
            if settings["driver"] in indices
        }
        self.movement_choices = lru_cache(maxsize=256)(self._movement_choices)
        for root in scene.groups:
            if root.extra.get("view_slots"):
                active = str(root.extra.get("active_view", "Default"))
                self.view_defaults[root.id] = (
                    VIEW_SLOTS.index(active) if active in VIEW_SLOTS else 0
                )
                for view, members in view_partitions(scene, root).items():
                    for key in members:
                        if key not in indices:
                            continue
                        previous = self.view_nodes.get(key, (root.id, frozenset()))[1]
                        self.view_nodes[key] = root.id, previous | {VIEW_SLOTS.index(view)}
        rigs = {r.id: frozenset(b.id for b in r.bones) for r in scene.skeletons}
        owners = {str(r.extra.get("object_id", r.id)): rigs[r.id] for r in scene.skeletons}
        for actor in scene.characters:
            owners[actor.id] = rigs[actor.skeleton_id]
            if actor.extra.get("object_id"):
                owners[str(actor.extra["object_id"])] = rigs[actor.skeleton_id]
        sources = {c.id: c for c in scene.clips}
        windows = {}
        layered_tracks = ordered_layers(timeline.tracks) if timeline else ()
        for track in layered_tracks:
            window = track.extra.get("motion_window")
            if not isinstance(window, Mapping):
                continue
            source = sources.get(str(window.get("source")))
            raw = source.extra.get("fk_bones", ()) if source else ()
            if not isinstance(raw, (tuple, list)) or any(k not in bone_ids for k in raw):
                raise EvaluationError("Motion FK controls must reference existing bones.")
            windows[str(window.get("id"))] = (
                window,
                owners.get(str(window.get("character")), frozenset()),
                frozenset(raw),
            )
        self.fk_windows = tuple(windows.values())
        self.spring_bypass_windows = tuple(
            (
                window,
                frozenset(sources[str(window["source"])].extra.get("spring_baked_bones", baked)),
            )
            for window, _, baked in self.fk_windows
            if sources.get(str(window.get("source")))
            and sources[str(window["source"])].extra.get("dynamics_bake")
        )
        tracks: list[tuple[int, int, CompiledTrack]] = []
        self.mesh_tracks: list[tuple[str, str, CompiledTrack]] = []
        self.camera_effect_tracks: list[tuple[str, str, CompiledTrack]] = []
        self.constraint_bases = {
            rule.id: {
                "parameters." + name: float(value)
                for name, value in rule.parameters.items()
                if type(value) in (int, float)
            }
            for rule in scene.constraints
        }
        self.constraint_tracks: list[tuple[str, str, CompiledTrack]] = []
        for track in layered_tracks:
            if track.property_path == ATTACHMENT_PATH:
                continue
            if track.owner_id in self.constraint_bases:
                if track.property_path not in self.constraint_bases[track.owner_id]:
                    raise EvaluationError("Choose an existing numeric constraint parameter.")
                self.constraint_tracks.append(
                    (track.owner_id, track.property_path, CompiledTrack(track, samplers))
                )
                continue
            if track.property_path.startswith("camera.effect."):
                if track.owner_id not in {c.id for c in scene.cameras}:
                    raise EvaluationError("Camera effects need a camera owner.")
                self.camera_effect_tracks.append(
                    (track.owner_id, track.property_path[14:], CompiledTrack(track, samplers))
                )
                continue
            if track.property_path == "object.view":
                if track.owner_id not in self.view_defaults:
                    raise EvaluationError(
                        "Object View tracks need an Object with editable view slots."
                    )
                if any(
                    k.interpolation != "step"
                    or not 0 <= number(k.value) < len(VIEW_SLOTS)
                    or number(k.value) != round(number(k.value))
                    for k in track.keyframes
                ):
                    raise EvaluationError("Object Views require held keys with a valid view index.")
                continue
            owner_index = indices.get(track.owner_id)
            if track.property_path in ("motion.fk", "motion.spring_baked"):
                if owner_index is None or self.nodes[owner_index].kind != "bone":
                    raise EvaluationError("FK activation needs a bone owner.")
                self.motion_controls.append(
                    (track.owner_id, track.property_path, CompiledTrack(track, samplers))
                )
                continue
            if track.property_path in ("spring.enabled", "spring.master"):
                if owner_index is None:
                    raise EvaluationError("Spring activation needs a bone or object owner.")
                self.spring_controls.append(
                    (track.owner_id, track.property_path, CompiledTrack(track, samplers))
                )
                continue
            if owner_index is None:
                self.deformation.base(track.owner_id, track.property_path)
                self.mesh_tracks.append(
                    (track.owner_id, track.property_path, CompiledTrack(track, samplers))
                )
                continue
            if (
                track.property_path.startswith("transform.")
                and track.property_path[10:] in _COMPONENTS
            ):
                component = _COMPONENTS.index(track.property_path[10:])
            elif track.property_path == "length" and self.nodes[owner_index].kind == "bone":
                component = 7
            elif track.property_path == "camera.active" and isinstance(
                self.nodes[owner_index].source, Camera
            ):
                component = 8
            elif track.property_path in ("visibility", "opacity") and not isinstance(
                self.nodes[owner_index].source, Camera
            ):
                component = 8 if track.property_path == "visibility" else 9
            else:
                raise EvaluationError(
                    f"{track.name}: unsupported animated property {track.property_path!r}."
                )
            tracks.append((owner_index, component, CompiledTrack(track, samplers)))
        self.tracks = tuple(tracks)
        self.scene_followers = SceneFollowPlan(
            followers,
            {n.source.id: n.source.parent_id for n in self.nodes},
            {**self.skinned_rigs, **self.library_rigs},
            self.spring_bindings,
            records={n.source.id: n.source for n in self.nodes},
            tracks=tuple(
                t for t in layered_tracks if t.property_path == ATTACHMENT_PATH and not local_object
            ),
            dependencies=tuple(c for c in rules if c not in followers and c.kind != "spring"),
        )
        depths: dict[str, int] = {}
        for node in self.nodes:
            depth = integer(node.source.extra.get("depth", 0), "Depth (Z)", -1_000_000, 1_000_000)
            depths[node.source.id] = depth + depths.get(node.source.parent_id or "", 0)
        self.render_order = tuple(sorted(scene_draw_order(scene), key=depths.__getitem__)) + tuple(
            node.source.id for node in self.nodes if node.kind == "bone"
        )

    def _object_space_nodes(self, owner: str) -> tuple[_Node, ...]:
        """Edit a skinned Object in its bind space while retaining canonical stage transforms.

        Parts inherit the bind-space container and bones already use that same source
        coordinate system. Main-scene translation, rotation and scale therefore cannot
        separate the editable armature from its rendered skin inside Object Editor.
        """
        bind = next(
            (
                d.parameters.get("object_group_bind")
                for d in self.scene.deformers
                if d.kind == "skinning" and d.parameters.get("object_group") == owner
            ),
            None,
        )
        if bind is None:
            bind = next(
                (
                    r.extra["library_bind"]
                    for r in self.scene.skeletons
                    if r.extra.get("object_id") == owner and r.extra.get("library_bind")
                ),
                None,
            )
        if not isinstance(bind, (tuple, list)) or len(bind) != 6:
            return self.nodes
        a, b, c, d, x, y = (number(v, "Object bind matrix") for v in bind)
        binding = (a, b, c, d, x, y)
        world: list[Matrix] = []
        nodes = []
        for node in self.nodes:
            parent = (
                world[node.parent_index]
                if node.parent_index >= 0
                else (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
            )
            if node.source.id == owner:
                local = multiply(inverse(parent), binding)
                node = replace(node, rest=(*decompose(local), *node.rest[7:]))
            world.append(multiply(parent, affine(*node.rest[:7])))
            nodes.append(node)
        return tuple(nodes)

    @staticmethod
    def _compile_nodes(scene: Scene) -> tuple[_Node, ...]:
        """Index transforms without recursion, rejecting missing parents and cycles."""
        sources: tuple[Group | SceneObject | Bone, ...] = (
            *scene.groups,
            *scene.cameras,
            *scene.objects,
            *(bone for rig in scene.skeletons for bone in rig.bones),
        )
        by_id = {source.id: source for source in sources}
        if len(by_id) != len(sources):
            raise EvaluationError("Transform node IDs must be unique.")
        rigs = {bone.id: rig.id for rig in scene.skeletons for bone in rig.bones}
        hidden_characters = {c.id for c in scene.characters if not c.extra.get("visible", True)}
        hidden_objects = {
            key for c in scene.characters if c.id in hidden_characters for key in c.object_ids
        }
        hidden_rigs = {c.skeleton_id for c in scene.characters if c.id in hidden_characters}
        children: dict[str, list[str]] = {}
        queue = deque[str]()
        for source in sources:
            if source.parent_id is None:
                queue.append(source.id)
            elif source.parent_id not in by_id:
                raise EvaluationError(f"{source.name} references a missing transform parent.")
            else:
                parent_source = by_id[source.parent_id]
                valid_parent = (
                    isinstance(parent_source, Bone) and rigs[source.id] == rigs[parent_source.id]
                    if isinstance(source, Bone)
                    else isinstance(parent_source, Group)
                    if isinstance(source, Group)
                    else isinstance(parent_source, (Group, SceneObject))
                )
                if not valid_parent:
                    raise EvaluationError("Transform parent has an incompatible type or skeleton.")
                children.setdefault(source.parent_id, []).append(source.id)
        result: list[_Node] = []
        indices: dict[str, int] = {}
        layers = {layer.id: layer.visible for layer in scene.layers}
        while queue:
            key = queue.popleft()
            source = by_id[key]
            parent = indices[source.parent_id] if source.parent_id is not None else -1
            kind = (
                "camera"
                if isinstance(source, Camera)
                else "bone"
                if isinstance(source, Bone)
                else "object"
                if isinstance(source, SceneObject)
                else "group"
            )
            rest = tuple(getattr(source.transform, component) for component in _COMPONENTS)
            visible = layers.get(getattr(source, "layer_id", None) or "", True)
            visible = visible and key not in hidden_objects and rigs.get(key) not in hidden_rigs
            indices[key] = len(result)
            result.append(
                _Node(
                    source,
                    parent,
                    kind,
                    (
                        *rest,
                        source.length if isinstance(source, Bone) else 0.0,
                        float(source.active)
                        if isinstance(source, Camera)
                        else float(getattr(source, "visible", source.extra.get("visible", True))),
                        number(source.extra.get("opacity", 1), "Object opacity"),
                    ),
                    visible,
                )
            )
            queue.extend(children.get(key, ()))
        if len(result) != len(sources):
            raise EvaluationError("Transform hierarchy contains a parent cycle.")
        return tuple(result)

    def evaluate(
        self,
        frame: float,
        *,
        loop: bool = False,
        overrides: Mapping[tuple[str, str], float] | None = None,
        visible_only: bool = False,
    ) -> ScenePose:
        """Evaluate a frame with optional transient absolute local control overrides.

        Overrides do not alter tracks or transport. Spring history uses the same
        constant overrides; key-recording previews with springs use authored scratch keys.
        Visible-only previews skip hidden mesh deformation after sampling visibility;
        nodes and tracks remain complete so blinking and garment switches still evaluate.
        The default retains all geometry for editing and export.
        """
        requested = number(frame, "Frame")
        frame = self.range.normalize(requested, loop=loop)
        inactive = self.inactive_view_nodes(frame)
        disabled = self._frame_fk(frame) | inactive
        ordered, constraint_warnings = self._apply_constraints(
            list(self._compose(frame, overrides)), frame, disabled
        )
        spring_targets = None
        if self.springs:
            targets, _ = self.joint_limits.apply(ordered)
            targets, _ = self.scene_followers.apply(
                targets,
                frame=frame,
                views=self.attachment_views(frame),
                parameters=self.constraint_values(frame),
                skip_owners=disabled,
            )
            spring_targets = MappingProxyType({node.id: node for node in targets})
        ordered, spring_warnings = sample_springs(
            self._spring_input(frame, overrides) if self.springs else ordered,
            self.springs,
            frame,
            self.range.start,
            self.scene.settings.fps,
            (lambda sample: self._spring_input(sample, overrides))
            if overrides
            else self.sample_spring_input,
            cursor=None if overrides else self.spring_cursor,
            rules_at=self.active_springs,
        )
        if self.springs:
            ordered = self.spring_output(ordered, frame, overrides)
        ordered, joint_warnings = self.joint_limits.apply(ordered)
        ordered, follow_warnings = self.scene_followers.apply(
            ordered,
            frame=frame,
            skip_owners=disabled,
            parameters=self.constraint_values(frame),
            views=self.attachment_views(frame),
        )
        ordered = self.placed_library_rigs(ordered)
        # Coverage follows evaluated garments so keyed hand/eye poses cannot
        # reveal covered artwork beneath a visible replacement.
        if self.occlusions:
            visible = {node.id for node in ordered if node.visible}
            covered = {
                key
                for parts, targets in self.occlusions
                if visible.intersection(parts)
                for key in targets
            }
            for i, node in enumerate(ordered):
                if node.id in covered or node.parent_id in covered:
                    covered.add(node.id)
                    ordered[i] = replace(node, visible=False)
        nodes = MappingProxyType({node.id: node for node in ordered})
        owners = self.scope
        if inactive:
            owners = frozenset(
                k for k in nodes if k not in inactive and (owners is None or k in owners)
            )
        if visible_only:
            owners = frozenset(
                key
                for key, node in nodes.items()
                if node.visible and (owners is None or key in owners)
            )
        meshes, deformation_warnings = self.deformation.evaluate(
            nodes, self.mesh_values(frame), owners=owners
        )
        for key, sequence in self.sprite_sequences.items():
            if key not in meshes:
                continue
            meshes[key] = replace(
                meshes[key], asset_id=frame_asset(sequence, frame, self.scene.settings.fps)
            )
        return ScenePose(
            self.scene.id,
            self.clip.id if self.clip else None,
            requested,
            frame,
            nodes,
            self.render_order,
            (
                *constraint_warnings,
                *spring_warnings,
                *joint_warnings,
                *follow_warnings,
                *deformation_warnings,
            ),
            MappingProxyType(meshes),
            spring_targets,
            MappingProxyType(
                {
                    key: multiply(nodes[owner].world_matrix, inverse(self.spring_bindings[owner]))
                    for key, owner in self.skinned_rigs.items()
                    if owner in nodes
                }
            ),
            cameras=self.evaluated_cameras(frame),
            region_owners=frozenset(
                o.id
                for o in self.scene.objects
                if "game_region" in o.extra and (self.scope is None or o.id in self.scope)
            ),
            particles=MappingProxyType(
                sample_particles(self.scene, frame, nodes, self.sample_kinematic, scope=self.scope)
            ),
        )

    def attachment_views(self, frame: float) -> dict[str, str]:
        """Resolve grip registration from the same held views as the owning Object artwork."""
        if not self.scene_followers.defaults:
            return {}
        result = {}
        for node in self.nodes:
            owner = self.scene_followers.bone_owners.get(node.source.id, node.source.id)
            index = self.view_defaults.get(owner, 0)
            if track := self.view_tracks.get(owner):
                value = track.sample(frame)
                if value is not None:
                    index = round(value)
            elif owner in self.movement_views and self.local_object != owner:
                index = self.movement_choices(frame)[owner]
            result[node.source.id] = VIEW_SLOTS[max(0, min(len(VIEW_SLOTS) - 1, index))]
        return result

    def placed_library_rigs(self, nodes: list[NodePose]) -> list[NodePose]:
        """Apply rig-only Object placement once after simulation, including live previews.

        Physics uses authored bone coordinates. Rig-only display geometry must inherit
        the current Object matrix, just as skinned geometry does during deformation.
        """
        if not self.library_rigs:
            return nodes
        indexed = {n.id: n for n in nodes}
        return [
            replace(
                n,
                world_matrix=multiply(
                    multiply(indexed[owner].world_matrix, inverse(self.spring_bindings[owner])),
                    n.world_matrix,
                ),
                visible=n.visible and indexed[owner].visible,
                opacity=n.opacity * indexed[owner].opacity,
            )
            if (owner := self.library_rigs.get(n.id)) in indexed
            else n
            for n in nodes
        ]

    def evaluated_cameras(self, frame: float) -> tuple[Camera, ...]:
        """Combine lens strengths, retaining the strongest overlapping preset per camera."""
        if not self.camera_effect_tracks:
            return self.scene.cameras
        result = []
        for camera in self.scene.cameras:
            effects: dict[str, float] = {}
            speeds: dict[str, float] = {}
            for owner, name, compiled in self.camera_effect_tracks:
                if owner != camera.id:
                    continue
                value = compiled.sample(frame)
                if value is not None and value * compiled.weight_at(frame) >= effects.get(name, 0):
                    effects[name] = value * compiled.weight_at(frame)
                    speeds[name] = float(
                        compiled.source.extra.get("camera_action", {}).get("speed", 1)
                    )
            result.append(
                replace(
                    camera, extra={**camera.extra, "lens_effects": effects, "lens_speeds": speeds}
                )
            )
        return tuple(result)

    def active_springs(self, frame: float) -> tuple[Constraint, ...]:
        """Sample stepped activation before each physics tick, respecting pins and locked bones."""
        values = {}
        for owner, path, compiled in self.spring_controls:
            value = compiled.sample(frame)
            if value is not None:
                values[owner, path] = value >= 0.5
        manual_fk = self._frame_fk(frame)
        pinned = {
            c.owner_id
            for c in self.rules
            if c.enabled and c.kind == "pin" and c.owner_id not in manual_fk
        }
        disabled = frozenset(
            key
            for window, bones in self.spring_bypass_windows
            if number(window["start"]) <= frame <= number(window["end"])
            for key in bones
        ) | self._motion_flags(frame, "motion.spring_baked")
        result = []
        for rule in self.springs:
            if (
                rule.owner_id in pinned
                or rule.owner_id in disabled
                or not self.view_visible(rule.owner_id, frame)
            ):
                continue
            node = self.nodes[self.node_indices[rule.owner_id]]
            enabled = values.get((rule.owner_id, "spring.enabled"), rule.enabled)
            owner = self.spring_owners.get(rule.owner_id, "")
            enabled = enabled and values.get((owner, "spring.master"), True)
            owner_index = self.node_indices.get(owner)
            if owner_index is not None:
                object_node = self.nodes[owner_index]
                while enabled:
                    enabled = not getattr(
                        object_node.source, "locked", False
                    ) and not object_node.source.extra.get("locked", False)
                    if object_node.parent_index < 0:
                        break
                    object_node = self.nodes[object_node.parent_index]
            while enabled:
                enabled = (
                    not getattr(node.source, "locked", False)
                    and not node.source.extra.get("locked", False)
                    and values.get((node.source.id, "spring.master"), True)
                )
                if node.parent_index < 0:
                    break
                node = self.nodes[node.parent_index]
            if enabled:
                result.append(rule if rule.enabled else replace(rule, enabled=True))
        return tuple(result)

    def _spring_input(
        self, frame: float, overrides: Mapping[tuple[str, str], float] | None = None
    ) -> tuple[NodePose, ...]:
        """Drive physics in Scene space while skinning retains its canonical object bind space."""
        nodes = self._kinematic(frame, overrides)
        return self.spring_input_nodes(nodes)

    def spring_input_nodes(self, nodes: Sequence[NodePose]) -> tuple[NodePose, ...]:
        """Map an authored or transient primary pose into the solver's Scene coordinate space."""
        indexed = {node.id: node for node in nodes}
        changes = {
            owner: multiply(indexed[owner].world_matrix, inverse(binding))
            for owner, binding in self.spring_bindings.items()
            if owner in indexed
        }
        output = []
        for node in nodes:
            delta = changes.get(self.spring_owners.get(node.id, ""))
            if delta is not None:
                world = multiply(delta, node.world_matrix)
                node = replace(node, world_matrix=world)
            output.append(node)
        return tuple(output)

    def spring_output(
        self,
        nodes: list[NodePose],
        frame: float,
        overrides: Mapping[tuple[str, str], float] | None = None,
        *,
        primary: Sequence[NodePose] | None = None,
    ) -> list[NodePose]:
        """Remove only the Scene-space driving transform; skinning applies object placement once."""
        original = {
            node.id: node
            for node in (primary if primary is not None else self._kinematic(frame, overrides))
        }
        changes = {
            owner: multiply(binding, inverse(original[owner].world_matrix))
            for owner, binding in self.spring_bindings.items()
            if owner in original
        }
        output = []
        for node in nodes:
            delta = changes.get(self.spring_owners.get(node.id, ""))
            if delta is not None:
                node = replace(node, world_matrix=multiply(delta, node.world_matrix))
            output.append(node)
        return output

    def _kinematic(
        self, frame: float, overrides: Mapping[tuple[str, str], float] | None = None
    ) -> tuple[NodePose, ...]:
        """Sample ordinary animation/constraints without secondary springs or mesh evaluation."""
        nodes, _ = self._apply_constraints(
            list(self._compose(frame, overrides)),
            frame,
            self._frame_fk(frame) | self.inactive_view_nodes(frame),
        )
        nodes, _ = self.joint_limits.apply(nodes)
        nodes, _ = self.scene_followers.apply(
            nodes,
            frame=frame,
            views=self.attachment_views(frame),
            parameters=self.constraint_values(frame),
            skip_owners=self._frame_fk(frame) | self.inactive_view_nodes(frame),
        )
        return tuple(nodes)

    def _apply_constraints(
        self, nodes: list[NodePose], frame: float, disabled: frozenset[str]
    ) -> tuple[list[NodePose], tuple[str, ...]]:
        """Solve primary rules, then the latest active shot without temporal graph cycles."""
        parameters = self.constraint_values(frame)
        nodes, warnings = self.constraints.apply(nodes, skip_owners=disabled, parameters=parameters)
        active = [
            (rule, plan)
            for rule, plan in self.shot_transitions
            if parameters.get(rule.id, {}).get("progress", 1) < 1
        ]
        if active:
            _, plan = max(active, key=lambda pair: pair[0].extra.get("shot_frame", 0))
            nodes, transition_warnings = plan.apply(nodes, parameters=parameters)
            warnings += transition_warnings
        return nodes, warnings

    def constraint_values(self, frame: float) -> dict[str, dict[str, float]]:
        """Sample root numeric rule parameters through ordinary scalar-track blending."""
        result: dict[str, dict[str, float]] = {}
        for owner, path, compiled in self.constraint_tracks:
            sampled = compiled.sample(frame)
            if sampled is None:
                continue
            values = result.setdefault(owner, {})
            name = path[11:]
            current = values.get(name, self.constraint_bases[owner][path])
            changed = compiled.blend(current, sampled, self.constraint_bases[owner][path], frame)
            values[name] = number(changed, "Constraint parameter")
        return result

    def _frame_fk(self, frame: float) -> frozenset[str]:
        """Respect source action contact rules only while their arranged block is active.

        Later overlapping blocks take precedence for their character, including
        restoring idle foot locks after an earlier run or jump has finished.
        """
        disabled: set[str] = set()
        for window, owners, baked in self.fk_windows:
            if influence(window, frame) > 0:
                mask = window.get("mask", ())
                active = owners.intersection(mask) if mask else owners
                disabled.difference_update(active)
                disabled.update(baked.intersection(active))
        disabled.update(self._motion_flags(frame, "motion.fk"))
        return frozenset(disabled)

    def _motion_flags(self, frame: float, path: str) -> frozenset[str]:
        """Resolve editable native-motion constraint bypasses separately from Spring activation."""
        disabled: set[str] = set()
        for owner, channel, compiled in self.motion_controls:
            if channel != path:
                continue
            value = compiled.sample(frame)
            if value is not None and value >= 0.5:
                disabled.add(owner)
        if self.controls:
            disabled.update(
                owner
                for (owner, channel), value in self.controls(frame).items()
                if channel == path and value >= 0.5
            )
        return frozenset(disabled)

    def _compose(
        self,
        frame: float,
        overrides: Mapping[tuple[str, str], float] | None = None,
        *,
        ignore_views: bool = False,
    ) -> tuple[NodePose, ...]:
        """Compose the parent-first hierarchy from canonical transform track samples."""
        values = [list(node.rest) for node in self.nodes]
        for owner, component, compiled in self.tracks:
            sampled = compiled.sample(frame)
            if sampled is None:
                continue
            current = values[owner][component]
            changed = compiled.blend(
                current,
                sampled,
                self.nodes[owner].rest[component],
                frame,
                scale=component in (3, 4),
                angle=component == 2,
            )
            values[owner][component] = number(changed, "Blended component")
        transient = {**(self.controls(frame) if self.controls else {}), **(overrides or {})}
        for (key, path), value in transient.items():
            if path in ("motion.fk", "motion.spring_baked"):
                continue
            owner_index = self.node_indices.get(key)
            if owner_index is None:
                if self.controls and (
                    key in self.deformation.deformers or key in self.deformation.vertices
                ):
                    self.deformation.base(key, path)
                    continue
                raise EvaluationError("Transient controls must reference existing transform nodes.")
            if path.startswith("transform.") and path[10:] in _COMPONENTS:
                component = _COMPONENTS.index(path[10:])
            elif path == "length" and self.nodes[owner_index].kind == "bone":
                component = 7
            elif path == "camera.active" and isinstance(self.nodes[owner_index].source, Camera):
                component = 8
            elif path in ("visibility", "opacity") and not isinstance(
                self.nodes[owner_index].source, Camera
            ):
                component = 8 if path == "visibility" else 9
            else:
                raise EvaluationError(f"Unsupported transient control {path!r}.")
            values[owner_index][component] = number(value, "Transient control")
        ordered: list[NodePose] = []
        for index, node in enumerate(self.nodes):
            parts = values[index]
            if parts[7] < 0:
                raise EvaluationError("Evaluated bone length cannot be negative.")
            local = TransformValues(*parts[:7])
            local_matrix = affine(*local)
            parent = ordered[node.parent_index] if node.parent_index >= 0 else None
            world = multiply(parent.world_matrix, local_matrix) if parent else local_matrix
            if not all(math.isfinite(value) for value in (*local_matrix, *world)):
                raise EvaluationError("Transform composition exceeds the finite numeric range.")
            if node.kind == "bone" and not all(
                math.isfinite(value) for value in transform_point(world, parts[7], 0)
            ):
                raise EvaluationError("Bone endpoint exceeds the finite numeric range.")
            ordered.append(
                NodePose(
                    node.source.id,
                    node.source.name,
                    node.kind,
                    node.source.parent_id,
                    local,
                    local_matrix,
                    world,
                    parts[7],
                    node.visible
                    and parts[8] >= 0.5
                    and (parent.visible if parent else True)
                    and (ignore_views or self.view_visible(node.source.id, frame)),
                    min(1, max(0, parts[9])) * (parent.opacity if parent else 1),
                )
            )
        return tuple(ordered)

    def view_visible(self, key: str, frame: float) -> bool:
        """Resolve visibility from a scene key, or the edited slot inside Object Editor."""
        membership = self.view_nodes.get(key)
        if membership is None:
            return True
        owner, indices = membership
        active = self.view_defaults[owner]
        if self.local_object != owner and owner in self.view_tracks:
            value = self.view_tracks[owner].sample(frame)
            if value is not None:
                active = round(value)
                return active in indices
        if self.local_object != owner and owner in self.movement_views:
            active = self.movement_choices(frame)[owner]
        return active in indices

    def _movement_choices(self, frame: float) -> dict[str, int]:
        """Sample primary motion twice without view filtering or history-dependent recursion."""
        if not self.movement_views:
            return {}
        low, high = max(self.range.start, frame - 1), frame
        if low == high:
            high = min(self.range.end, frame + 1)
        positions = []
        for sample in (low, high):
            nodes, _ = self._apply_constraints(
                list(self._compose(sample, ignore_views=True)), sample, self._frame_fk(sample)
            )
            positions.append({n.id: n.world_matrix[4:] for n in nodes})
        result = {}
        for owner, settings in self.movement_views.items():
            before, after = (p[settings["driver"]] for p in positions)
            direction = movement_direction(
                after[0] - before[0],
                after[1] - before[1],
                (high - low) / self.range.fps,
                settings["minimum_speed"],
            )
            result[owner] = VIEW_SLOTS.index(settings["slots"][direction])
        return result

    def inactive_view_nodes(self, frame: float) -> frozenset[str]:
        """Exclude inactive turnaround geometry and constraint owners from frame evaluation."""
        return frozenset(key for key in self.view_nodes if not self.view_visible(key, frame))

    def mesh_values(self, frame: float) -> dict[tuple[str, str], float]:
        """Sample mesh channels for deterministic evaluation and editor previews."""
        mesh_values: dict[tuple[str, str], float] = {}
        for mesh_owner, path, compiled in self.mesh_tracks:
            sampled = compiled.sample(frame)
            if sampled is None:
                continue
            key = (mesh_owner, path)
            current = mesh_values.get(key, self.deformation.base(mesh_owner, path))
            changed = compiled.blend(
                current,
                sampled,
                self.deformation.base(mesh_owner, path),
                frame,
                scale=path in ("parameters.scale_x", "parameters.scale_y"),
            )
            mesh_values[key] = number(changed, "Blended mesh parameter")
        if self.controls:
            for (owner, path), value in self.controls(frame).items():
                if owner not in self.node_indices:
                    self.deformation.base(owner, path)
                    mesh_values[owner, path] = number(value, "Transient deformation")
        return mesh_values
