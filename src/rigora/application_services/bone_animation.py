"""Plan bone animation against the displayed pose using the canonical rig solvers and keys."""

import math
from dataclasses import replace
from typing import cast

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.commands import ScenePatch
from rigora.application_services.documents import DocumentService
from rigora.application_services.rigging import RigService
from rigora.application_services.scene_editing import SceneEditingService
from rigora.domain.entities import Bone, Group, SceneObject, Transform, nested_records
from rigora.domain.project import Project, ProjectError
from rigora.engine.state import ScenePose


class BoneAnimationService(AnimationEditingService):
    """Convert solved pose gestures into timeline channels without changing bind/rest geometry."""

    def solve_drag(
        self, key: str, tool: str, x: float, y: float, selected: tuple[str, ...] = ()
    ) -> dict[tuple[str, str], float]:
        """Solve desired local controls without creating keys or validating artwork payloads."""
        pose = self.document.animation.pose
        scene = self.scene

        def posed[R: Bone | Group | SceneObject](record: R) -> R:
            """Seed rig solving with evaluated local transforms rather than authored rest values."""
            node = pose.nodes[record.id]
            transform = Transform(**node.local._asdict())
            return cast(
                R,
                (
                    replace(record, transform=transform, length=node.length)
                    if isinstance(record, Bone)
                    else replace(record, transform=transform)
                ),
            )

        solver = DocumentService(constraint_solvers=self.document.constraint_solvers)
        solver._link_objects = False
        # The rig solver needs transform controls, not thousands of vertices and keys.
        # The final keyed preview still evaluates the complete original scene below.
        staged = replace(
            RigService.control_scene(scene),
            skeletons=tuple(
                replace(r, bones=tuple(posed(b) for b in r.bones)) for r in scene.skeletons
            ),
            objects=tuple(posed(o) for o in scene.objects),
            groups=tuple(posed(g) for g in scene.groups),
            constraints=tuple(
                c for c in self.document.animation.evaluator.rules if c.owner_id in pose.nodes
            ),
        )
        assert self.document.project is not None
        solver.project = Project(scenes=(staged,), assets=self.document.project.assets)
        solver.set_animation_context(
            self.document.animation_context, self.document.animation_scope, prepare=False
        )
        rig = RigService(solver)
        command, _ = rig.plan_drag(key, tool, x, y, selected)
        solver.execute(command)
        before = {r.id: r for r in nested_records(staged)}
        values: dict[tuple[str, str], float] = {}
        scene_editor = SceneEditingService(self.document)
        for record in nested_records(rig.scene):
            if not isinstance(record, (Bone, Group, SceneObject)):
                continue
            source = before[record.id]
            assert isinstance(source, (Bone, Group, SceneObject))
            for name in ("x", "y", "rotation", "scale_x", "scale_y", "pivot_x", "pivot_y"):
                original, value = getattr(source.transform, name), getattr(record.transform, name)
                if name == "rotation":
                    value = original + (value - original + 180) % 360 - 180
                if not math.isclose(original, value, rel_tol=1e-9, abs_tol=1e-7):
                    values[record.id, f"transform.{name}"] = value
            if (
                isinstance(record, Bone)
                and isinstance(source, Bone)
                and not math.isclose(record.length, source.length)
            ):
                values[record.id, "length"] = record.length
            if any(owner == record.id for owner, _ in values) and scene_editor.locked(record.id):
                raise ProjectError(
                    "Unlock the animated bone or control and its ancestors before posing."
                )
        for track in self.timeline.tracks if self.timeline else ():
            if (track.owner_id, track.property_path) in values:
                self.editable(track)
        return values

    def plan_drag(
        self, key: str, tool: str, x: float, y: float, selected: tuple[str, ...] = ()
    ) -> tuple[ScenePatch, ScenePose]:
        """Record a solved drag in scratch keys and return one validated reversible patch."""
        values = self.solve_drag(key, tool, x, y, selected)
        frame, scene = self.document.animation.pose.frame, self.scene
        preview = self.document.fork()
        if values:
            AnimationEditingService(preview).auto_key_values(values, frame)
        assert preview.project is not None
        changed = preview.scene
        fields = tuple(
            field
            for field in ("timelines", "clips")
            if getattr(scene, field) != getattr(changed, field)
        )
        return ScenePatch(
            "Key bone pose",
            scene.id,
            {field: getattr(scene, field) for field in fields},
            {field: getattr(changed, field) for field in fields},
        ), preview.animation.pose
