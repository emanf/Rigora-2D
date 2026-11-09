"""Transient object/character composer isolation with full-scene camera restoration."""

from collections.abc import Callable
from contextlib import suppress
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QEvent, QObject, QPointF, Qt, QTimer
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QTabBar,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rigora.application_services.characters import CharacterService
from rigora.application_services.documents import DocumentService
from rigora.application_services.image_rigging import ImageRigService
from rigora.domain.entities import Group, SceneObject
from rigora.domain.geometry import inverse, multiply, transform_point
from rigora.domain.project import ProjectError
from rigora.engine.state import ScenePose

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


class ObjectEditMode(QObject):
    """Keep composer focus in view state; never author visibility or camera changes."""

    def __init__(self, window: "MainWindow") -> None:
        """Bind double-click entry points, a clear exit button and document ownership."""
        super().__init__(window)
        self.host = window
        self.active = False
        self.key = ""
        self.document: object = None
        self.saved_view: tuple[float, QPointF] | None = None
        self.restore_hierarchy = False
        self.ids: frozenset[str] = frozenset()
        self.saved_docks: dict[str, bool] = {}
        self.timeline_height = 0
        self.scene_filter = ""
        self._reference_key: tuple[object, str] | None = None
        self._reference_pose: ScenePose | None = None
        self.placeholder = QWidget()
        self.context = QFrame()
        self.context.setObjectName("ObjectContext")
        self.context.setStyleSheet("#ObjectContext { border-bottom: 1px solid #343434; }")
        layout = QVBoxLayout(self.context)
        layout.setContentsMargins(12, 8, 12, 0)
        layout.setSpacing(8)
        row = QHBoxLayout()
        layout.addLayout(row)
        self.button = QPushButton("Scene")
        self.button.setIcon(window.icons.icon("arrow_back"))
        self.button.clicked.connect(self.exit)
        row.addWidget(self.button)
        self.title = QLabel("Object Editor")
        self.title.setStyleSheet("font-size: 17px; font-weight: 600; padding-left: 8px;")
        row.addWidget(self.title)
        row.addStretch()
        self.pages = QTabBar()
        self.pages.setExpanding(False)
        for name, icon in (
            ("Object Tree", "account_tree"),
            ("Skin", "palette"),
            ("Clothing", "checkroom"),
            ("Animations", "directions_run"),
        ):
            self.pages.addTab(window.icons.icon(icon), name)
        self.pages.currentChanged.connect(window.character_panel.tabs.setCurrentIndex)
        row.addWidget(self.pages)
        window.studio_layout.insertWidget(0, self.context)
        self.context.hide()
        window.viewport.installEventFilter(self)
        window.tree.setEditTriggers(QAbstractItemView.EditTrigger.EditKeyPressed)
        window.tree.itemDoubleClicked.connect(self.tree_enter)

    def resolve(self, key: str) -> tuple[frozenset[str], str]:
        """Map a part, mesh, skeleton or bone to its complete owning character."""
        service = CharacterService(self.host.viewmodel.documents)
        root = service.object_root(key)
        entry = service.records().get(key)
        from rigora.domain.entities import Camera

        if isinstance(entry, Camera):
            raise ProjectError("Edit cameras from Camera settings in the main scene.")
        if root or isinstance(entry, Group):
            container = root or entry
            assert isinstance(container, Group)
            if container.extra.get("view_slots"):
                from rigora.application_services.object_views import ObjectViewsService

                return ObjectViewsService(service.document).edit_members(
                    container.id
                ), container.name
            return frozenset(service.members(container.id)), container.name
        meshes = service.meshes_for((key,))
        actor = next(
            (
                c
                for c in service.scene.characters
                if key == c.id or key == c.skeleton_id or key in service.members(c.id)
            ),
            None,
        )
        if actor is None and meshes:
            actor = service.owner(meshes[0])
        ids = service.members(actor.id) | {actor.skeleton_id, actor.id} if actor else set()
        if not actor:
            ids.update(str(service.mesh(m).object_id) for m in meshes if service.mesh(m).object_id)
        pose = self.host.viewmodel.documents.animation.pose
        for identity in tuple(ids):
            node = pose.nodes.get(identity)
            while node and node.parent_id:
                ids.add(node.parent_id)
                node = pose.nodes.get(node.parent_id)
        if not ids:
            raise ProjectError("Double-click an object or character to edit it.")
        return frozenset(ids), actor.name if actor else service.mesh(meshes[0]).name.removesuffix(
            " mesh"
        )

    def enter(self, key: str) -> None:
        """Isolate and frame a complete object, retaining the previous full-scene navigation."""
        vm, viewport = self.host.viewmodel, self.host.viewport
        if vm.documents.project:
            mesh = next((m for m in vm.documents.scene.meshes if m.id == key), None)
            if mesh and mesh.object_id:
                key = mesh.object_id
        selected = (*vm.scene.selected, *vm.rig.selected)
        try:
            ids, name = self.resolve(key)
        except ProjectError as error:
            self.host.statusBar().showMessage(str(error), 5000)
            return
        from rigora.application_services.rigging import RigService

        with vm.documents.command_group("Add Rig Root"):
            for rig in tuple(vm.documents.scene.skeletons):
                if rig.bones and any(b.id in ids for b in rig.bones):
                    RigService(vm.documents).ensure_root(rig.id)
        ids, name = self.resolve(key)
        if self.active and self.document is vm.documents and self.ids == ids:
            self.host.character_panel.show()
            return
        data = vm.preferences.data
        width = data.get("object_editor_width", 360)
        width = width if isinstance(width, int) and 310 <= width <= 460 else 360
        if not self.active:
            self.saved_view = viewport.zoom, QPointF(viewport.offset)
            self.scene_filter = self.host.filter.text()
            self.host.filter.clear()
            self.restore_hierarchy = not self.host.docks["hierarchy"].visibleRegion().isEmpty()
            self.saved_docks = {
                k: not self.host.docks[k].isHidden() for k in ("hierarchy", "inspector", "assets")
            }
            self.timeline_height = self.host.docks["timeline"].height()
            hierarchy = self.host.hierarchy_content
            hierarchy.setParent(self.host.character_panel.structure_host)
            self.host.character_panel.structure_layout.insertWidget(1, hierarchy, 1)
            self.host.docks["hierarchy"].setWidget(self.placeholder)
            hierarchy.show()
            self.host.docks["hierarchy"].hide()
            inspector, assets = self.host.docks["inspector"], self.host.docks["assets"]
            if data.get("object_inspector_layout_version") != 1:
                if not inspector.isFloating() and not assets.isFloating():
                    self.host.splitDockWidget(assets, inspector, Qt.Orientation.Horizontal)
                data["object_inspector_layout_version"] = 1
            self.host.character_panel.show()
            self.host.studio_splitter.setSizes(
                [max(400, self.host.studio_splitter.width() - width), width]
            )
            height = data.get("object_editor_timeline_height", 280)
            height = height if isinstance(height, int) and 210 <= height <= 900 else 280
            self.host.resizeDocks([self.host.docks["timeline"]], [height], Qt.Orientation.Vertical)
        self.document = vm.documents
        root = CharacterService(vm.documents).object_root(key)
        self.key = (
            root.id
            if root
            else (
                next((c.id for c in vm.documents.scene.characters if c.id in ids), key)
                if vm.documents.project
                else key
            )
        )
        self.active = True
        self.host.tab_row.hide()
        self.host.add_scene_button.hide()
        self.host.camera_button.hide()
        self.ids = ids
        self.host.viewmodel.extensions.set_editor("object")
        vm.playback.pause()
        vm.documents.set_animation_context(self.key, ids)
        vm.playback.bind(vm.documents)
        vm.animation_editor.bind(vm.documents)
        meshes = (
            [m.id for m in vm.documents.scene.meshes if m.object_id in ids]
            if vm.documents.project
            else []
        )
        if meshes and vm.mesh.mesh_id not in meshes:
            vm.mesh.select_mesh(meshes[0])
        elif not meshes:
            vm.mesh.select_mesh("")
        selection = tuple(dict.fromkeys(k for k in selected if k in ids))
        if not selection and meshes:
            service = CharacterService(vm.documents)
            actor = next((c for c in service.scene.characters if c.id == self.key), None)
            selection = actor.object_ids if actor else (str(service.mesh(meshes[0]).object_id),)
        elif not selection:
            selection = (self.key,)
        self.host.scene_workspace.select_entries(selection)
        self.host.navigate()
        if self.host.shape_workspace.active:
            self.host.shape_workspace.deactivate()
        self.title.setText(name)
        self.context.show()
        if layout := self.host.layout():
            layout.activate()
        self.host.studio_layout.activate()
        self.host.character_panel.page_changed(self.pages.currentIndex())
        self.host.character_panel.workspace.setSizes([280, 180])
        self.host.hierarchy_note.setText("Drag layers to change order · F2 to rename")
        self.host.filter.setPlaceholderText("Filter layers…")
        viewport.isolated_ids = ids
        self.frame_contents()
        framed_view = viewport.zoom, QPointF(viewport.offset)
        document, owner = vm.documents, self.key

        def frame_after_layout() -> None:
            """Fit once after dock resizing, unless another gesture already changed the view."""
            if (
                self.active
                and self.document is document
                and self.key == owner
                and framed_view == (viewport.zoom, viewport.offset)
            ):
                self.host.studio_splitter.setSizes(
                    [max(400, self.host.studio_splitter.width() - width), width]
                )
                self.frame_contents()
                viewport.zoom_changed.emit(viewport.zoom)
                viewport.update()

        QTimer.singleShot(0, frame_after_layout)
        vm.animation_editor.composer_owners = ids
        vm.animation_editor.focus_owners(ids)
        self.host.character_panel.refresh()
        self.host.scene_workspace.rebuild()
        self.host.scene_workspace.select_entries(self.host.viewmodel.scene.selected)
        self.refresh()
        viewport.zoom_changed.emit(viewport.zoom)

    def update_reference(self) -> None:
        """Render the rest of the paused scene without adding it to editable pose/hit tests."""
        viewport = self.host.viewport
        action = self.host.command_actions["scene_context"]
        action.setVisible(self.active)
        action.setEnabled(self.active)
        if not self.active or not action.isChecked():
            if viewport.reference_pose is not None:
                viewport.update()
            viewport.reference_pose = None
            self._reference_key = self._reference_pose = None
            return
        document = self.host.viewmodel.documents
        if not document.project or self.document is not document:
            return
        key = document.scene, self.key
        try:
            if (
                self._reference_key is None
                or self._reference_key[0] is not key[0]
                or self._reference_key[1] != key[1]
            ):
                self._reference_pose = document.scene_reference_pose()
                self._reference_key = key
            reference, edited = self._reference_pose, viewport.source_pose
            if reference is None or edited is None or reference.scene_id != edited.scene_id:
                viewport.reference_pose = None
                return
            reference = reference.for_display()
            mapping = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
            if self.key in reference.nodes and self.key in edited.nodes:
                mapping = multiply(
                    edited.nodes[self.key].world_matrix,
                    inverse(reference.nodes[self.key].world_matrix),
                )
            viewport.reference_pose = replace(
                reference,
                nodes={
                    k: replace(
                        node,
                        world_matrix=multiply(mapping, node.world_matrix),
                        visible=node.visible and k not in self.ids,
                    )
                    for k, node in reference.nodes.items()
                },
            )
        except ProjectError as error:
            viewport.reference_pose = None
            self.host.statusBar().showMessage(f"Scene context unavailable: {error}", 5000)
        viewport.update()

    def fit_view(self) -> None:
        """Fit isolated content and publish its zoom without referring to the Scene camera."""
        self.frame_contents()
        self.host.viewport.zoom_changed.emit(self.host.viewport.zoom)
        self.host.viewport.update()

    def frame_contents(self) -> None:
        """Fit evaluated artwork or bare bone controls inside the current viewport size."""
        viewport = self.host.viewport
        pose = self.host.viewmodel.documents.animation.pose
        points = [
            transform_point(pose.nodes[m.object_id].world_matrix, *p)
            for m in pose.meshes.values()
            if m.object_id in self.ids
            for p in m.positions
        ]
        if not points:
            points = [
                transform_point(node.world_matrix, x, 0)
                for key, node in pose.nodes.items()
                if key in self.ids and node.kind == "bone" and node.length > 0
                for x in (0, node.length)
            ]
        if points:
            xs, ys = [p[0] for p in points], [p[1] for p in points]
            viewport.zoom = max(
                0.001,
                min(
                    8,
                    (viewport.width() - 100) / max(1, max(xs) - min(xs)),
                    (viewport.height() - 100) / max(1, max(ys) - min(ys)),
                ),
            )
            viewport.offset = QPointF(
                viewport.width() / 2 - (max(xs) + min(xs)) / 2 * viewport.zoom,
                viewport.height() / 2 - (max(ys) + min(ys)) / 2 * viewport.zoom,
            )
        elif self.key in pose.nodes:
            point = QPointF(*pose.nodes[self.key].world_matrix[4:])
            viewport.zoom = 1
            viewport.offset = QPointF(viewport.width() / 2, viewport.height() / 2) - point

    def exit(self, *, restore_view: bool = True) -> None:
        """Restore all scene geometry, hierarchy rows and the pre-composer view."""
        if not self.active:
            return
        sizes = self.host.studio_splitter.sizes()
        if len(sizes) > 1 and sizes[1] > 0:
            self.host.viewmodel.preferences.data["object_editor_width"] = sizes[1]
        self.host.viewmodel.preferences.data["object_editor_timeline_height"] = self.host.docks[
            "timeline"
        ].height()
        self.active = False
        self.host.tab_row.show()
        self.host.add_scene_button.show()
        self.host.camera_button.show()
        self.ids = frozenset()
        self.key = ""
        self.host.viewmodel.extensions.set_editor("scene")
        self.context.hide()
        self.host.character_panel.structure_layout.removeWidget(self.host.hierarchy_content)
        self.host.docks["hierarchy"].setWidget(self.host.hierarchy_content)
        self.host.character_panel.hide()
        self.host.viewport.composer_artwork_only = False
        self.host.filter.setPlaceholderText("Filter scene…")
        self.host.filter.setText(self.scene_filter)
        for key, visible in self.saved_docks.items():
            self.host.docks[key].setVisible(visible)
        self.host.resizeDocks(
            [self.host.docks["timeline"]], [self.timeline_height], Qt.Orientation.Vertical
        )
        self.host.navigate()
        self.host.rig_workspace.set_mode(False)
        self.host.mesh_workspace.set_mode(False)
        self.host.viewmodel.animation_editor.composer_owners = None
        vm = self.host.viewmodel
        if isinstance(self.document, DocumentService) and self.document is not vm.documents:
            self.document.set_animation_context(None, prepare=False)
        if self.document is vm.documents:
            vm.documents.set_animation_context(None)
            vm.playback.bind(vm.documents)
            vm.animation_editor.bind(vm.documents)
        self.host.viewmodel.animation_editor.focus_changed.emit()
        viewport = self.host.viewport
        viewport.isolated_ids = None
        if self.saved_view and restore_view:
            viewport.zoom, viewport.offset = self.saved_view
        self.saved_view = None
        for item in self.host.scene_workspace.items.values():
            item.setHidden(False)
        self.host.scene_workspace.rebuild()
        self.host.hierarchy_note.setText(
            "Double-click an object to edit its parts, skin and motions."
        )
        self.host.scene_workspace.select_entries(self.host.viewmodel.scene.selected)
        if self.restore_hierarchy:
            self.host.docks["hierarchy"].raise_()
        self.host.update_animation()
        viewport.zoom_changed.emit(viewport.zoom)

    def refresh(self) -> None:
        """Re-resolve membership after binding/part edits; a document change releases focus."""
        if not self.active:
            return
        vm = self.host.viewmodel
        if self.document is not vm.documents:
            self.exit()
            return
        try:
            if root := CharacterService(vm.documents).object_root(self.key):
                self.key = root.id
            self.ids, name = self.resolve(self.key)
        except ProjectError:
            self.exit()
            return
        self.title.setText(name)
        self.host.viewport.isolated_ids = self.ids
        self.host.viewmodel.animation_editor.composer_owners = self.ids
        vm.documents.set_animation_context(self.key, self.ids)
        vm.playback.bind(vm.documents)
        self.host.viewmodel.animation_editor.focus_changed.emit()
        for key, item in self.host.scene_workspace.items.items():
            item.setHidden(key not in self.ids)
        self.host.filter_scene(self.host.filter.text())
        self.host.update_animation()

    def adoption(
        self, *, clothing: bool = False, recenter: bool = True
    ) -> Callable[[DocumentService, dict[str, Any]], None]:
        """Capture the edited object as an asynchronous import target, independent of tab focus."""
        service = CharacterService(self.host.viewmodel.documents)
        actor_id = next((c.id for c in service.scene.characters if c.skeleton_id in self.ids), None)
        object_id = self.key if isinstance(service.records().get(self.key), Group) else None
        solid_id = self.key if isinstance(service.records().get(self.key), SceneObject) else None
        object_name = self.title.text()
        originals = service.meshes_for((self.key,))
        old_meshes = (
            next((c.mesh_ids for c in service.scene.characters if c.id == actor_id), originals)
            or originals
        )
        pose = service.document.animation.pose
        points = [
            transform_point(pose.nodes[str(m.object_id)].world_matrix, *p)
            for m in pose.meshes.values()
            if m.id in old_meshes
            for p in m.positions
        ]
        center = (
            tuple((min(p[i] for p in points) + max(p[i] for p in points)) / 2 for i in (0, 1))
            if points
            else pose.nodes[object_id].world_matrix[4:]
            if object_id is not None and object_id in pose.nodes
            else None
        )
        if not recenter:
            center = None
        name = self.host.character_panel.outfit_name.text().strip()
        group_id = None
        if clothing:
            with suppress(ProjectError):
                group_id = self.host.character_panel.outfit_selection()[0]

        def adopt(document: DocumentService, data: dict[str, Any]) -> None:
            """Attach only successful newly placed image meshes in the import transaction."""
            keys = []
            for row in data.get("files", ()):
                if row.get("status") != "added":
                    continue
                result = row["result"]
                keys.extend(result.get("mesh_ids", ()))
                if result.get("mesh_id"):
                    keys.append(result["mesh_id"])
            if not keys:
                keys.extend(data.get("mesh_ids", ()))
            if not keys:
                return
            images = ImageRigService(document)
            if center:
                pose = document.animation.pose
                evaluator = document.animation.evaluator
                incoming, _ = evaluator.deformation.evaluate(
                    pose.nodes,
                    evaluator.mesh_values(pose.frame),
                    owners=frozenset(str(images.mesh(k).object_id) for k in keys),
                )
                points = [
                    transform_point(pose.nodes[str(m.object_id)].world_matrix, *p)
                    for m in incoming.values()
                    if m.id in keys
                    for p in m.positions
                ]
                if points:
                    from rigora.application_services.scene_editing import SceneEditingService

                    objects = tuple(str(images.mesh(k).object_id) for k in keys)
                    SceneEditingService(document).transform(
                        objects,
                        dx=center[0] - (min(p[0] for p in points) + max(p[0] for p in points)) / 2,
                        dy=center[1] - (min(p[1] for p in points) + max(p[1] for p in points)) / 2,
                    )
            characters = CharacterService(document)
            if object_id or solid_id or not actor_id:
                if object_id:
                    target_object = object_id
                elif solid_id:
                    target_object = characters.promote_object(solid_id)
                else:
                    target_object = characters.create_object(
                        tuple(str(images.mesh(k).object_id) for k in originals), object_name
                    )
                characters.add_object_parts(target_object, tuple(keys))
                target = target_object
            else:
                target = actor_id or images.convert(tuple((*originals, *keys)))
                images.add_parts(target, tuple(keys))
            if clothing:
                target = object_id or solid_id or target
                assert target is not None
                group = group_id or characters.wardrobe_group(target, "Clothing")
                characters.add_variant(target, group, tuple(keys), name or "New clothing")

        return adopt

    def tree_enter(self, item: QTreeWidgetItem, column: int) -> None:
        """Double-click enters composition; F2 remains the standard rename action."""
        key = item.data(0, Qt.ItemDataRole.UserRole)
        if column == 0 and isinstance(key, str):
            if any(c.id == key for c in self.host.viewmodel.documents.scene.cameras):
                self.host.camera_workspace.settings(key)
                return
            self.enter(key)

    def menu_actions(self, menu: QMenu, key: str) -> None:
        """Share explicit composition entry and exit between the stage and hierarchy menus."""
        if key:
            try:
                self.resolve(key)
            except ProjectError:
                pass
            else:
                menu.addAction("Edit object / character", lambda: self.enter(key))
        if self.active:
            menu.addAction("Exit Object Edit", self.exit)
        menu.addSeparator()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Reserve viewport double-click entry without consuming ordinary part editing gestures."""
        if (
            isinstance(event, QMouseEvent)
            and event.type() == QEvent.Type.MouseButtonDblClick
            and event.button() == Qt.MouseButton.LeftButton
        ):
            key = self.host.scene_workspace.pick(event.position())
            if key:
                if any(c.id == key for c in self.host.viewmodel.documents.scene.cameras):
                    self.host.camera_workspace.settings(key)
                else:
                    self.enter(key)
                return True
        return False
