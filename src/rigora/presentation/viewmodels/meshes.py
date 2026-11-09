"""Transient mesh selection and gesture previews over shared deformation authoring services."""

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from PySide6.QtCore import QObject, Signal

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.deformation_motion import DeformationMotionService
from rigora.application_services.documents import DocumentService
from rigora.domain.entities import Mesh
from rigora.domain.project import ProjectError, Scene
from rigora.engine.deformation import DeformationPlan
from rigora.engine.ffd_controls import edit_controls
from rigora.engine.state import ScenePose


class MeshViewModel(QObject):
    """Keep editor state outside authoring records, with one undo command per finished gesture."""

    changed = Signal()
    document_changed = Signal()
    auto_key_changed = Signal(bool)
    editing_started = Signal()

    def __init__(self, parent: QObject) -> None:
        """Create an unbound editor with independent selection and nonpersistent preview state."""
        super().__init__(parent)
        self.document: DocumentService | None = None
        self._document_key = ""
        self.service: DeformationMotionService | None = None
        self.active = False
        self.tool = "vertex"
        self.transform_mode = "move"
        self.mesh_id = ""
        self.stage_id = ""
        self.selected: tuple[str, ...] = ()
        self.controls: tuple[int, ...] = ()
        self.auto_key = False
        self.error = ""
        self.preview_values: dict[tuple[str, str], float] = {}
        self.preview_mesh: Mesh | None = None
        self._pose_cache: (
            tuple[Scene, ScenePose, Mesh | None, dict[tuple[str, str], float], ScenePose] | None
        ) = None
        self._tabs: dict[str, tuple[bool, str, str, tuple[str, ...], tuple[int, ...]]] = {}

    def bind(self, document: DocumentService | None) -> None:
        """Restore per-tab selections, cancel previews, and remove stale stable-ID references."""
        if self.document is not document or self._document_key != (
            document.context_key if document else ""
        ):
            self._pose_cache = None
            if self.document:
                self._tabs[self._document_key] = (
                    self.active,
                    self.mesh_id,
                    self.stage_id,
                    self.selected,
                    self.controls,
                )
            self.active, self.mesh_id, self.stage_id, self.selected, self.controls = self._tabs.get(
                document.context_key if document else "", (False, "", "", (), ())
            )
            self.error = ""
        self._document_key = document.context_key if document else ""
        self.document = document
        self.service = DeformationMotionService(document) if document else None
        self.preview_values.clear()
        self.preview_mesh = None
        if self.service:
            meshes = self.service.scene.meshes
            if self.mesh_id not in {m.id for m in meshes}:
                self.mesh_id = meshes[0].id if meshes else ""
            if self.mesh:
                self.selected = tuple(
                    k for k in self.selected if k in {v.id for v in self.mesh.vertices}
                )
            if self.stage_id not in {
                d.id for d in self.service.scene.deformers if d.owner_id == self.mesh_id
            }:
                self.stage_id = ""
                self.controls = ()
        self.changed.emit()

    @property
    def mesh(self) -> Mesh | None:
        """Resolve selected base geometry without depending on a renderer cache."""
        return (
            next((m for m in self.service.scene.meshes if m.id == self.mesh_id), None)
            if self.service and self.mesh_id
            else None
        )

    @property
    def pose(self) -> ScenePose | None:
        """Evaluate transient geometry/parameter overrides while retaining the common sampled
        timeline.
        """
        if not self.document or not self.service:
            return None
        session = self.document.animation
        if not self.preview_values and self.preview_mesh is None:
            return session.pose
        scene = self.service.scene
        cache = self._pose_cache
        if (
            cache is not None
            and cache[0] is scene
            and cache[1] is session.pose
            and cache[2] is self.preview_mesh
            and cache[3] == self.preview_values
        ):
            return cache[4]
        source = scene
        if self.preview_mesh:
            scene = replace(
                scene,
                meshes=tuple(
                    self.preview_mesh if m.id == self.preview_mesh.id else m for m in scene.meshes
                ),
            )
        values = session.evaluator.mesh_values(session.pose.frame)
        values.update(self.preview_values)
        plan = (
            DeformationPlan(scene, self.document.deformer_solvers)
            if self.preview_mesh
            else session.evaluator.deformation
        )
        meshes, warnings = plan.evaluate(
            session.pose.nodes, values, owners=self.document.animation_scope
        )
        pose = replace(session.pose, meshes=meshes, warnings=warnings)
        self._pose_cache = source, session.pose, self.preview_mesh, dict(self.preview_values), pose
        return pose

    def run(self, action: Callable[[DeformationMotionService], Any]) -> None:
        """Publish successful commands once and retain useful validation feedback on failure."""
        if not self.service:
            return
        self.editing_started.emit()
        try:
            action(self.service)
        except (ProjectError, OSError, ValueError) as error:
            self.error = str(error)
            self.cancel_preview()
        else:
            self.error = ""
            self.document_changed.emit()
        self.changed.emit()

    def set_auto_key(self, enabled: bool) -> None:
        """Synchronize explicit recording intent across timeline and deformation controls."""
        if self.auto_key != enabled:
            self.auto_key = enabled
            self.auto_key_changed.emit(enabled)
            self.changed.emit()

    def select_mesh(self, key: str) -> None:
        """Switch artwork selection and clear incompatible vertex, stage and control selections."""
        self.mesh_id, self.stage_id, self.selected, self.controls = key, "", (), ()
        self.cancel_preview()

    def select(self, vertices: tuple[str, ...], extend: bool = False) -> None:
        """Select vertices directly or as the endpoints of a picked edge/triangle."""
        self.selected = tuple(dict.fromkeys((*self.selected, *vertices))) if extend else vertices
        self.changed.emit()

    def cancel_preview(self) -> None:
        """Discard a pending gesture without adding a history entry."""
        self.preview_values.clear()
        self.preview_mesh = None
        self._pose_cache = None
        self.changed.emit()

    def finish_preview(self) -> None:
        """Commit one brush, vertex or control gesture, optionally writing keys."""
        values, mesh = dict(self.preview_values), self.preview_mesh
        if not self.service or not self.document:
            return

        def commit(service: DeformationMotionService) -> None:
            """Group all selected numeric leaves into one reversible gesture."""
            with service.document.transaction("Edit mesh gesture"):
                if mesh:
                    service.replace_mesh(mesh, "Paint vertex weights")
                timeline = AnimationEditingService(service.document).timeline
                animated = (
                    {(t.owner_id, t.property_path) for t in timeline.tracks if t.keyframes}
                    if timeline
                    else set()
                )
                deformation_owners = {
                    *(v.id for v in service.mesh(self.mesh_id).vertices),
                    *(
                        d.id
                        for d in service.scene.deformers
                        if d.owner_id == self.mesh_id and d.kind != "appearance"
                    ),
                }
                recording = self.auto_key or any(
                    owner in deformation_owners for owner, _ in animated
                )
                keyed = values if recording else {}
                if keyed:
                    AnimationEditingService(service.document).auto_key_values(
                        keyed, service.document.animation.pose.frame
                    )
                remaining = {key: value for key, value in values.items() if key not in keyed}
                if remaining:
                    positions = {
                        v.id: (remaining.get((v.id, "x"), v.x), remaining.get((v.id, "y"), v.y))
                        for v in service.mesh(self.mesh_id).vertices
                        if (v.id, "x") in remaining or (v.id, "y") in remaining
                    }
                    if positions:
                        service.sculpt_vertices(self.mesh_id, positions)
                    for stage in service.scene.deformers:
                        edits = [
                            (path, value)
                            for (owner, path), value in remaining.items()
                            if owner == stage.id
                        ]
                        if edits:
                            from rigora.domain.validation import json_copy

                            params = json_copy(stage.parameters)
                            for path, value in edits:
                                DeformationPlan.override_parameter(params, path, value)
                            service.update(stage.id, parameters=params)

        self.run(commit)
        self.cancel_preview()

    def edit_value(self, owner: str, path: str, value: float) -> None:
        """Apply one inspector field through the same preview/commit path as viewport gestures."""
        self.preview_values = {(owner, path): value}
        self.finish_preview()

    def key_pose(self) -> None:
        """Capture the selected mesh's current vertex pose on the common timeline.

        Keying the complete surface lets later gestures update the current frame even
        with Auto key off; protected vertices retain their authored values.
        """
        if not self.document or not self.mesh:
            return
        self.editing_started.emit()
        session = self.document.animation
        sampled = session.evaluator.mesh_values(session.pose.frame)
        values = {
            (v.id, axis): sampled.get((v.id, axis), getattr(v, axis))
            for v in self.mesh.vertices
            if not v.protected
            for axis in ("x", "y")
        }
        self.run(
            lambda s: AnimationEditingService(s.document).auto_key_values(
                values, session.pose.frame
            )
        )

    def edit_controls(self, operation: str = "transform", **values: float) -> None:
        """Transform sampled FFD dots through the same one-command, optional-auto-key gesture
        path.
        """
        if not self.service or not self.document or not self.stage_id:
            self.error = "Select an FFD stage first."
            self.changed.emit()
            return
        self.editing_started.emit()
        try:
            from rigora.domain.validation import json_copy

            stage = self.service.stage(self.stage_id)
            if stage.kind not in ("ffd", "lattice"):
                raise ProjectError("This control operation requires an FFD or lattice stage.")
            session = self.document.animation
            params = json_copy(session.evaluator.deformation.parameters[stage.id])
            for (owner, path), value in session.evaluator.mesh_values(session.pose.frame).items():
                if owner == stage.id:
                    DeformationPlan.override_parameter(params, path, value)
            offsets = edit_controls(params, self.controls, operation=operation, **values)
            self.preview_values = {
                (stage.id, f"parameters.controls.{i}.{axis}"): coordinate
                for i, point in offsets.items()
                for axis, coordinate in enumerate(point)
            }
            self.finish_preview()
        except ProjectError as error:
            self.error = str(error)
            self.changed.emit()
