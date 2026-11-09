"""Coordinate rig widgets, viewport gestures and the main scene hierarchy."""

import time
from dataclasses import replace
from types import MappingProxyType
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QPointF, Qt, QTimer
from PySide6.QtWidgets import QTreeWidgetItem

from rigora.domain.entities import Skeleton
from rigora.domain.project import ProjectError
from rigora.engine.deformation import DeformationPlan
from rigora.engine.springs import SpringSimulation
from rigora.engine.state import ScenePose

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


class RigWorkspace(QObject):
    """Bind rig presentation without putting authoring rules into the window shell."""

    def __init__(self, window: "MainWindow") -> None:
        """Connect viewport and inspector events once for all project tabs."""
        super().__init__(window)
        self.window = window
        self.spring = SpringSimulation()
        self.spring_enabled = True
        self.spring_scope: frozenset[str] | None = None
        self.spring_document: object = None
        self.spring_preview_gesture = False
        self.spring_clock = time.monotonic()
        self.spring_input = self.spring_clock
        self.spring_timer = QTimer(self)
        self.spring_timer.setInterval(16)
        self.spring_timer.timeout.connect(self.tick_springs)
        model, viewport = window.viewmodel.rig, window.viewport
        viewport.bone_selected.connect(model.select)
        viewport.bone_created.connect(self.create_bone)
        viewport.bone_dragged.connect(self.finish_pose)
        viewport.bone_drag_started.connect(self.begin_pose)
        viewport.bone_drag_started.connect(self.begin_springs)
        viewport.bone_drag_preview.connect(model.preview_drag)
        viewport.bone_drag_cancelled.connect(model.cancel_preview)
        viewport.bones_selected.connect(model.select_many)
        model.preview_changed.connect(self.refresh_preview)
        model.preview_reset.connect(viewport.cancel_rig_gesture)
        window.rig_panel.mode_changed.connect(self.set_mode)
        window.rig_panel.target_changed.connect(self.set_target)
        window.rig_panel.frame_requested.connect(self.frame_rig)
        model.changed.connect(self.refresh)
        window.viewmodel.playback.changed.connect(self.sync_playback)
        window.viewmodel.mesh.changed.connect(self.mesh_springs)

    def create_bone(self, x: float, y: float, end_x: float, end_y: float) -> None:
        """Draw into the chosen image rig, or author an ordinary independent skeleton."""
        from rigora.application_services.image_rigging import ImageRigService

        vm = self.window.viewmodel
        document = vm.documents
        parent = vm.rig.selected[0] if vm.rig.selected else None
        mesh_id = vm.mesh.mesh_id
        if mesh_id and vm.rig.auto_bind_artwork:
            vm.rig.run(
                lambda _: ImageRigService(document).draw_bone(
                    mesh_id, (x, y), (end_x, end_y), parent
                )
            )
            if not vm.rig.error:
                bound = any(
                    d.kind == "skinning" and d.owner_id == mesh_id
                    for d in ImageRigService(document).scene.deformers
                )
                self.window.statusBar().showMessage(
                    "Bone added · image mesh bound automatically. Pose with Select & transform."
                    if bound
                    else "Bone added · artwork remains explicitly unbound. Use Bind to reconnect.",
                    6500,
                )
        else:
            vm.rig.run(
                lambda service: service.create_bone(
                    (x, y),
                    (end_x, end_y),
                    parent,
                )
            )

    def mesh_springs(self) -> None:
        """Keep live deformation gestures in the same transient physics preview as bone drags."""
        mesh = self.window.viewmodel.mesh
        if mesh.active and (mesh.preview_values or mesh.preview_mesh is not None):
            if not self.spring_timer.isActive():
                self.begin_springs()
            self.spring_input = time.monotonic()

    def spring_pose(self) -> ScenePose | None:
        """Resolve the current gesture pose without retaining the previous simulated output."""
        vm = self.window.viewmodel
        if vm.animation_editor.preview_pose is not None:
            return vm.animation_editor.preview_pose
        if vm.scene.preview is not None:
            return vm.scene.preview
        if vm.mesh.active:
            return vm.mesh.pose
        if vm.rig.active and vm.rig.pose is not None:
            return vm.rig.pose
        return vm.documents.animation.pose if vm.documents.project else None

    def set_mode(self, enabled: bool) -> None:
        """Activate bone tools at the displayed frame without restricting timeline access."""
        if enabled:
            selected = self.window.viewmodel.rig.selected
            self.window.ensure_object_editor(selected[0] if selected else None)
        model = self.window.viewmodel
        model.rig.cancel_preview()
        model.rig.active = enabled
        model.rig.pose = model.documents.animation.pose if model.documents.project else None
        if enabled:
            self.window.viewport.pan_tool = False
            self.window.viewport.unsetCursor()
            self.window.command_actions["navigate"].setChecked(True)
            model.mesh.active = False
            model.mesh.cancel_preview()
            model.playback.pause()
            self.window.inspector.setCurrentWidget(self.window.rig_panel)
        model.rig.changed.emit()

    def set_target(self, key: str) -> None:
        """Highlight the selected rule's editable object control in the viewport."""
        self.window.viewport.rig_target = key
        self.window.viewport.update()

    def frame_rig(self) -> None:
        """Fit all visible bones to the current viewport without changing authored geometry."""
        from rigora.domain.geometry import transform_point

        viewport, pose = self.window.viewport, self.window.viewmodel.rig.pose
        if pose is None:
            return
        pose = pose.for_display()
        points = [
            transform_point(n.world_matrix, x, 0)
            for n in pose.nodes.values()
            if n.kind == "bone" and n.visible
            for x in (0, n.length)
        ]
        if not points:
            return
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        viewport.zoom = min(
            8,
            (viewport.width() - 100) / max(1, max(xs) - min(xs)),
            (viewport.height() - 100) / max(1, max(ys) - min(ys)),
        )
        viewport.zoom = max(0.001, viewport.zoom)
        viewport.offset = QPointF(
            viewport.width() / 2 - (max(xs) + min(xs)) / 2 * viewport.zoom,
            viewport.height() / 2 - (max(ys) + min(ys)) / 2 * viewport.zoom,
        )
        viewport.zoom_changed.emit(viewport.zoom)
        viewport.update()

    def select_tree(self, item: QTreeWidgetItem) -> None:
        """Inspect bones, including locked entries that must remain unlockable from the tree."""
        key = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(key, str):
            self.set_mode(True)
            self.window.viewmodel.rig.select(key, inspect=True)

    def refresh(self) -> None:
        """Synchronize mode, editable geometry and visual selection after rig state changes."""
        window, model = self.window, self.window.viewmodel.rig
        viewport = window.viewport
        changed_tool = viewport.rig_mode != model.active or viewport.rig_tool != model.tool
        viewport.rig_mode = model.active
        viewport.rig_tool = model.tool
        if changed_tool:
            viewport.cancel_rig_gesture()
        else:
            viewport.refresh_cursor()
        viewport.selected_bones = model.selected
        viewport.bone_colors.clear()
        viewport.locked_bones.clear()
        viewport.ik_endpoints.clear()
        if model.service:
            viewport.ik_endpoints.update(
                str(c.parameters["end_bone_id"])
                for c in model.service.scene.constraints
                if c.enabled
                and c.kind == "two_bone_ik"
                and c.parameters.get("mode") != "fk"
                and c.parameters.get("end_bone_id")
            )
            for rig in model.service.scene.skeletons:
                for bone in rig.bones:
                    viewport.bone_colors[bone.id] = bone.color
                    try:
                        model.service.editable(bone.id)
                    except ProjectError:
                        viewport.locked_bones.add(bone.id)
        window.command_actions["rig_mode"].setChecked(model.active)
        window.command_actions["bone"].setChecked(model.active and model.tool == "draw")
        window.command_actions["move"].setChecked(model.active and model.tool == "move")
        if model.active:
            window.tool_status.setText(
                "Draw bones · Shift: 45° directions · Alt: free joints"
                if model.tool == "draw"
                else f"Rig · {model.tool}"
            )
        window.update_animation()

    def refresh_preview(self) -> None:
        """Publish only live geometry during pointer movement instead of rebuilding the shell."""
        model = self.window.viewmodel.rig
        if self.spring_timer.isActive():
            self.spring_input = time.monotonic()
            self.tick_springs()
        elif model.active:
            self.window.viewport.set_pose(model.pose)
        if model.error:
            self.window.statusBar().showMessage(model.error, 4000)

    def begin_pose(self) -> None:
        """Pause at the displayed frame before capturing a live bone gesture's baseline."""
        self.window.viewmodel.playback.pause()
        editor = getattr(self.window, "spring_editor", None)
        self.spring_preview_gesture = bool(
            editor
            and editor.isVisible()
            and (editor.play_button.isChecked() or editor.preview_paused)
        )
        self.window.viewmodel.rig.begin_preview()

    def finish_pose(self, key: str, tool: str, x: float, y: float) -> None:
        """Release test-only drags without publishing rest-pose or animation changes."""
        model = self.window.viewmodel.rig
        if self.spring_preview_gesture:
            self.spring_preview_gesture = False
            model.preview_drag(key, tool, x, y)
            model.cancel_preview()
        else:
            model.drag(key, tool, x, y)

    def sync_playback(self) -> None:
        """Follow the shared transport without rebuilding inspector controls on every tick."""
        vm = self.window.viewmodel
        if vm.rig.document is not vm.documents or vm.playback.session is None:
            return
        if vm.playback.session.playback.is_playing and self.spring_timer.isActive():
            self.stop_springs()
        vm.rig.sync_playback()
        if vm.playback.session and not vm.playback.session.playback.is_playing:
            self.window.rig_panel.refresh()

    def begin_springs(self) -> None:
        """Seed live secondary dynamics from the unchanged pose before a bone gesture starts."""
        model = self.window.viewmodel.rig
        self.spring_timer.stop()
        self.spring_document = None
        session = self.window.viewmodel.playback.session
        if (
            session is not None
            and session.playback.is_playing
            or self.window.viewmodel.animation_editor.preview_pose is not None
        ):
            return
        pose = self.spring_pose()
        if not self.spring_enabled or not model.document or not model.service or not pose:
            return
        rules = model.document.animation.evaluator.active_springs(pose.frame)
        if self.spring_scope is not None:
            rules = tuple(rule for rule in rules if rule.owner_id in self.spring_scope)
        if rules:
            self.spring = SpringSimulation()
            self.spring_document = model.document
            try:
                targets = pose.spring_targets if pose.spring_targets is not None else pose.nodes
                self.spring.advance(
                    model.document.animation.evaluator.spring_input_nodes(tuple(targets.values())),
                    rules,
                    1 / 60,
                )
                self.spring_clock = self.spring_input = time.monotonic()
                self.spring_timer.start()
            except ProjectError as error:
                self.window.statusBar().showMessage(str(error), 8000)

    def stop_springs(self) -> None:
        """Drop live simulation state and restore the active timeline or authoring preview."""
        self.spring_timer.stop()
        self.spring_document = None
        self.spring = SpringSimulation()
        self.window.update_animation()
        if pose := self.spring_pose():
            self.window.viewport.set_pose(pose)

    def excite_springs(self, members: tuple[str, ...], *, strain: float = 0.25) -> bool:
        """Release a visible live test on chosen members while paused, preserving authored data."""
        session = self.window.viewmodel.playback.session
        pose = self.spring_pose()
        if session is None or session.playback.is_playing or pose is None:
            return False
        if not self.spring_timer.isActive():
            self.begin_springs()
        if not self.spring_timer.isActive():
            return False
        rules = tuple(
            rule
            for rule in session.evaluator.active_springs(pose.frame)
            if rule.owner_id in members
            and (self.spring_scope is None or rule.owner_id in self.spring_scope)
        )
        targets = pose.spring_targets if pose.spring_targets is not None else pose.nodes
        self.spring.excite(
            session.evaluator.spring_input_nodes(tuple(targets.values())), rules, strain=strain
        )
        self.spring_input = time.monotonic()
        self.tick_springs()
        return bool(rules)

    def tick_springs(self) -> None:
        """Render transient spring settling and real skinning without adding authoring commands."""
        session = self.window.viewmodel.playback.session
        if (
            session is not None
            and session.playback.is_playing
            or self.window.viewmodel.animation_editor.preview_pose is not None
        ):
            # The evaluated timeline already includes springs; a second timer would alternate poses.
            self.stop_springs()
            return
        model = self.window.viewmodel.rig
        now = time.monotonic()
        pose = self.spring_pose()
        if (
            model.document is None
            or model.document is not self.spring_document
            or not model.service
            or not pose
            or now - self.spring_input > 4
            or self.window._closed
        ):
            self.stop_springs()
            return
        dt = min(0.1, max(1 / 240, now - self.spring_clock))
        self.spring_clock = now
        rules = model.document.animation.evaluator.active_springs(pose.frame)
        if self.spring_scope is not None:
            rules = tuple(rule for rule in rules if rule.owner_id in self.spring_scope)
        if not rules:
            self.stop_springs()
            return
        try:
            targets = pose.spring_targets if pose.spring_targets is not None else pose.nodes
            primary = tuple(targets.values())
            evaluator = model.document.animation.evaluator
            nodes = self.spring.advance(evaluator.spring_input_nodes(primary), rules, dt)
            nodes = evaluator.spring_output(nodes, pose.frame, primary=primary)
            nodes, joint_warnings = model.document.animation.evaluator.joint_limits.apply(nodes)
            nodes, follow_warnings = evaluator.scene_followers.apply(
                nodes,
                frame=pose.frame,
                views=evaluator.attachment_views(pose.frame),
                parameters=evaluator.constraint_values(pose.frame),
            )
            nodes = evaluator.placed_library_rigs(nodes)
            nodes = [
                replace(
                    node, visible=pose.nodes[node.id].visible, opacity=pose.nodes[node.id].opacity
                )
                for node in nodes
            ]
            mapping = MappingProxyType({n.id: n for n in nodes})
            values = model.document.animation.evaluator.mesh_values(pose.frame)
            values.update(self.window.viewmodel.mesh.preview_values)
            scene = model.service.scene
            pending_mesh = self.window.viewmodel.mesh.preview_mesh
            if pending_mesh:
                scene = replace(
                    scene,
                    meshes=tuple(
                        pending_mesh if m.id == pending_mesh.id else m for m in scene.meshes
                    ),
                )
            plan = (
                DeformationPlan(scene, model.document.deformer_solvers)
                if pending_mesh
                else model.document.animation.evaluator.deformation
            )
            meshes, warnings = plan.evaluate(mapping, values, owners=model.document.animation_scope)
            self.window.viewport.set_pose(
                replace(
                    pose,
                    nodes=mapping,
                    meshes=MappingProxyType(meshes),
                    warnings=(*pose.warnings, *joint_warnings, *follow_warnings, *warnings),
                )
            )
        except ProjectError as error:
            self.spring_timer.stop()
            self.window.statusBar().showMessage(str(error), 8000)

    @staticmethod
    def populate_bones(parent: QTreeWidgetItem, skeleton: Skeleton) -> None:
        """Build a real parent/child tree while retaining UUID-based selection identities."""
        items = {
            bone.id: QTreeWidgetItem(
                [
                    bone.name
                    + (" · locked" if bone.locked else "")
                    + (" · hidden" if not bone.visible else "")
                ]
            )
            for bone in skeleton.bones
        }
        for bone in skeleton.bones:
            item = items[bone.id]
            item.setData(0, Qt.ItemDataRole.UserRole, bone.id)
            item.setToolTip(0, f"Bone · {bone.group}\n{bone.id}")
            (items[bone.parent_id] if bone.parent_id else parent).addChild(item)
            item.setExpanded(True)
        parent.setExpanded(True)
