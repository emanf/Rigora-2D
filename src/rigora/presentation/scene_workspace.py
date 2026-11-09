"""Scene row controls, cross-view selection and live object transforms over one ViewModel."""

import math
import time
from collections.abc import Callable
from dataclasses import replace
from functools import partial
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import (
    QEvent,
    QModelIndex,
    QObject,
    QPointF,
    QRectF,
    QSignalBlocker,
    QSizeF,
    Qt,
    QTimer,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QIcon,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QPolygonF,
    QTransform,
)
from PySide6.QtWidgets import QApplication, QTreeWidgetItem

from rigora.domain.entities import Bone, Camera, Character, Group, SceneObject, Skeleton
from rigora.domain.geometry import transform_point
from rigora.domain.project import ProjectError
from rigora.engine.cameras import active_camera
from rigora.engine.state import MeshPose, ScenePose
from rigora.presentation import transform_gizmo
from rigora.presentation.artwork import mesh_contains, mesh_polygon
from rigora.presentation.menu_labels import menu_text
from rigora.presentation.themes import PALETTES
from rigora.presentation.widgets.item_view_state import ItemViewState
from rigora.presentation.widgets.viewport import INACTIVE_CAMERA_OPACITY

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


class SceneWorkspace(QObject):
    """Keep actual selected identities synchronized between hierarchy, inspector and viewport."""

    def __init__(self, window: "MainWindow") -> None:
        """Attach focused authoring routes without replacing specialized bone/mesh gestures."""
        super().__init__(window)
        self.window, self.model = window, window.viewmodel.scene
        self.items: dict[str, QTreeWidgetItem] = {}
        self.scene_items: dict[str, QTreeWidgetItem] = {}
        self.character_nodes: dict[str, str] = {}
        self._tree_context: tuple[str, str] | None = None
        self._tree_states: dict[tuple[str, str], ItemViewState] = {}
        self.drag: QPointF | None = None
        self.marquee: tuple[QPointF, QPointF] | None = None
        self.extend = False
        self.transform: transform_gizmo.Gesture | None = None
        self.transform_owner: str | None = None
        self.pivot_offset = QPointF()
        self.last_screen = QPointF()
        self._syncing_selection = False
        self._screen_pose: ScenePose | None = None
        self._screen_view: tuple[float, ...] = ()
        self._screen_polygons: dict[str, QPolygonF] = {}
        self._screen_points: dict[str, QPolygonF] = {}
        self._screen_meshes: dict[str, list[MeshPose]] = {}
        self.window.tree.itemSelectionChanged.connect(self.select_tree)
        self.window.tree.itemClicked.connect(self.click_column)
        self.window.tree.itemActivated.connect(self.activate_tree_item)
        self.window.tree.itemChanged.connect(self.rename)
        self.window.tree.entries_moved.connect(self.move_entries)
        self.window.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.window.tree.customContextMenuRequested.connect(self.context_menu)
        self.model.changed.connect(self.refresh)
        self.model.preview_changed.connect(self.preview)
        window.viewmodel.rig.changed.connect(self.sync_bones)
        window.viewport.installEventFilter(self)
        window.viewport.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        window.viewport.customContextMenuRequested.connect(self.viewport_menu)
        window.viewport.scene_overlay = self.draw
        window.viewport.scene_cursor = self.cursor_at

    def cursor_at(self, point: QPointF) -> QCursor | None:
        """Describe scene hover/drag intent without changing selection or document state."""
        vm = self.window.viewmodel
        if not self.model.service or vm.rig.active or vm.mesh.active:
            return None
        if self.drag is not None:
            return (
                transform_gizmo.cursor(
                    self.transform.handle,
                    self.window.icons,
                    transform_gizmo.handles(self.transform.rect, self.transform.mapping),
                )
                if self.transform
                else QCursor(Qt.CursorShape.SizeAllCursor)
            )
        if self.marquee is not None:
            return QCursor(Qt.CursorShape.CrossCursor)
        frame = self.transform_frame()
        handle = (
            transform_gizmo.pick(frame[0], point, frame[1], self.pivot_point(frame))
            if frame
            else None
        )
        if handle is not None:
            assert frame is not None
            return transform_gizmo.cursor(
                handle, self.window.icons, transform_gizmo.handles(frame[0], frame[1])
            )
        key = self.pick(point)
        if key:
            return QCursor(Qt.CursorShape.SizeAllCursor)
        return QCursor(Qt.CursorShape.CrossCursor)

    def rebuild(self) -> None:
        """Display only meaningful scene entries with per-row visibility and lock state icons."""
        tree, service = self.window.tree, self.model.service
        if self._tree_context is not None:
            self._tree_states[self._tree_context] = ItemViewState.capture(tree)
        mode = getattr(self.window, "object_edit", None)
        self._tree_context = (
            (service.document.context_key, mode.key if mode and mode.active else "")
            if service
            else None
        )
        state = self._tree_states.get(self._tree_context) if self._tree_context else None
        first = state is None
        with QSignalBlocker(tree):
            tree.clear()
            tree.setRootIndex(QModelIndex())
            self.items.clear()
            self.scene_items.clear()
            if not service:
                return
            scene = service.scene
            assert service.document.project is not None
            for entry in service.document.project.scenes:
                header = QTreeWidgetItem([entry.name])
                header.setData(0, Qt.ItemDataRole.UserRole + 5, ("scene", entry.id))
                header.setFlags(
                    (header.flags() | Qt.ItemFlag.ItemIsEditable)
                    & ~Qt.ItemFlag.ItemIsDragEnabled
                    & ~Qt.ItemFlag.ItemIsDropEnabled
                )
                active = entry.id == scene.id
                if active:
                    header.setFlags(header.flags() | Qt.ItemFlag.ItemIsDropEnabled)
                if not active:
                    header.setToolTip(0, "Activate this scene before editing or dropping artwork.")
                header.setIcon(
                    1,
                    self.window.icons.icon(
                        "visibility" if active else "visibility_off",
                        color="#eeeeee"
                        if active and self.window.themes.name == "dark"
                        else "#202020"
                        if active
                        else "#777777",
                    ),
                )
                header.setToolTip(
                    1,
                    "Active scene"
                    if active
                    else "Activate scene · inactive scenes are not evaluated",
                )
                font = header.font(0)
                font.setBold(active)
                header.setFont(0, font)
                tree.addTopLevelItem(header)
                self.scene_items[entry.id] = header
            root = self.scene_items[scene.id]
            root.setExpanded(True)
            mode = getattr(self.window, "object_edit", None)
            tree.session = service.document.session_id
            if mode and not mode.active:
                from rigora.application_services.characters import CharacterService

                characters = CharacterService(service.document)
                ranks = {key: i for i, key in enumerate(scene.draw_order)}

                def depth(key: str) -> int:
                    """Order whole objects by their frontmost artwork without exposing parts."""
                    actor = next((c for c in scene.characters if c.id == key), None)
                    meshes = characters.meshes_for(actor.object_ids if actor else (key,))
                    return max(
                        (ranks.get(str(characters.mesh(k).object_id), -1) for k in meshes),
                        default=-1,
                    )

                keys = tuple(sorted(characters.scene_objects(), key=depth, reverse=True))
                self.character_nodes = {
                    key: c.id
                    for c in scene.characters
                    for key in (*c.object_ids, *c.extra.get("part_groups", ()))
                }
                for camera in scene.cameras:
                    self.add_row(camera, root)
                for key in keys:
                    self.add_row(service.record(key), root)
                for key in keys:
                    parent_id = getattr(service.record(key), "parent_id", None)
                    actor = next((c for c in scene.characters if c.id == key), None)
                    if actor and actor.object_ids:
                        parent_id = getattr(service.record(actor.object_ids[0]), "parent_id", None)
                        while parent_id and parent_id not in self.items:
                            parent_id = getattr(service.record(parent_id), "parent_id", None)
                    if parent_id in self.items:
                        item = self.items[key]
                        root.takeChild(root.indexOfChild(item))
                        self.items[parent_id].addChild(item)
                    self.items[key].setSelected(
                        key in self.model.selected
                        or bool(
                            actor
                            and actor.object_ids
                            and set(actor.object_ids) <= set(self.model.selected)
                        )
                    )
                tree.headerItem().setText(0, "Objects · front to back")
                self.refresh()
                if state:
                    state.restore(tree)
                return
            session = self.window.viewmodel.playback.session
            order = session.pose.render_order if session else scene.draw_order
            rank = {key: index for index, key in enumerate(order)}
            group_members = {}
            for group in scene.groups:
                descendants = {group.id}
                while True:
                    expanded_children = descendants | {
                        r.id
                        for r in (*scene.groups, *scene.objects)
                        if getattr(r, "parent_id", None) in descendants
                    }
                    if descendants == expanded_children:
                        break
                    descendants = expanded_children
                rank[group.id] = max((rank.get(key, -1) for key in descendants), default=-1)
                group_members[group.id] = {o.id for o in scene.objects if o.id in descendants}
            artwork = sorted(
                (
                    r
                    for r in (*scene.groups, *scene.objects)
                    if not r.extra.get("studio_floor_plant")
                ),
                key=lambda r: rank.get(r.id, -1),
                reverse=True,
            )
            for camera in scene.cameras:
                self.add_row(camera, root)
            for record in artwork:
                self.add_row(record, root)
            for record in artwork:
                parent_id = getattr(record, "parent_id", None)
                if parent_id in self.items:
                    item = self.items[record.id]
                    root.takeChild(root.indexOfChild(item))
                    self.items[parent_id].addChild(item)
            containers = {g.id for g in scene.groups if g.extra.get("object_container")}
            # Modern objects own their tree directly; legacy actors need a synthetic wrapper.
            actors = {
                c.id: c
                for c in scene.characters
                if c.object_ids and c.extra.get("object_id") not in containers
            }
            ownership = {key: c.id for c in actors.values() for key in c.object_ids}
            for group in scene.groups:
                if group.extra.get("scene_folder"):
                    continue
                for actor in actors.values():
                    members = group_members[group.id]
                    if (
                        group.id in actor.extra.get("part_groups", ())
                        or members
                        and members <= set(actor.object_ids)
                    ):
                        ownership[group.id] = actor.id
                        break
            for actor in actors.values():
                self.add_row(actor, root)
                rank[actor.id] = max((rank.get(k, -1) for k in actor.object_ids), default=-1)
            self.character_nodes = ownership
            for record in artwork:
                actor_id = ownership.get(record.id)
                parent_id = getattr(record, "parent_id", None)
                if actor_id and ownership.get(str(parent_id)) != actor_id:
                    item = self.items[record.id]
                    old_parent = item.parent()
                    if old_parent:
                        old_parent.takeChild(old_parent.indexOfChild(item))
                    self.items[actor_id].addChild(item)
            for actor in actors.values():
                parents = {
                    getattr(service.record(k), "parent_id", None)
                    for k, owner in ownership.items()
                    if owner == actor.id
                    and ownership.get(str(getattr(service.record(k), "parent_id", None)))
                    != actor.id
                }
                if len(parents) == 1 and (parent_id := next(iter(parents))) in self.items:
                    item = self.items[actor.id]
                    root.takeChild(root.indexOfChild(item))
                    self.items[parent_id].addChild(item)
            for label, records in (
                ("Layers", scene.layers),
                ("Characters / rigs", scene.skeletons),
            ):
                if not records:
                    continue
                branch = QTreeWidgetItem([label])
                branch.setData(0, Qt.ItemDataRole.UserRole + 5, ("section", label))
                root.addChild(branch)
                branch.setExpanded(True)
                for record in records:
                    owner_actor = next(
                        (
                            c
                            for c in actors.values()
                            if isinstance(record, Skeleton) and c.skeleton_id == record.id
                        ),
                        None,
                    )
                    parent = self.items[owner_actor.id] if owner_actor else branch
                    if isinstance(record, Skeleton) and not owner_actor:
                        parent = self.items.get(str(record.extra.get("object_id", "")), branch)
                    item = self.add_row(record, parent)
                    if isinstance(record, Skeleton):
                        bones = {b.id: self.add_row(b, item) for b in record.bones}
                        for bone in record.bones:
                            if bone.parent_id in bones:
                                child = bones[bone.id]
                                item.takeChild(item.indexOfChild(child))
                                bones[bone.parent_id].addChild(child)
                if branch.childCount() == 0:
                    root.takeChild(root.indexOfChild(branch))
            for rule in scene.constraints:
                if (
                    rule.enabled
                    and rule.kind == "parent"
                    and rule.owner_id in self.items
                    and rule.target_id in self.items
                    and isinstance(service.record(rule.target_id), Bone)
                    and isinstance(service.record(rule.owner_id), (SceneObject, Group))
                ):
                    child = self.items[rule.owner_id]
                    old_parent = child.parent()
                    if old_parent:
                        old_parent.takeChild(old_parent.indexOfChild(child))
                    self.items[rule.target_id].addChild(child)
            for key, item in self.items.items():
                mode = getattr(self.window, "object_edit", None)
                item.setExpanded(first and (key not in actors or bool(mode and mode.active)))
                item.setSelected(key in self.model.selected)

            def order_children(parent: QTreeWidgetItem) -> None:
                """Keep render order readable without changing skeleton sibling conventions."""
                if parent.data(0, Qt.ItemDataRole.UserRole + 1) in ("Bone", "Skeleton"):
                    return
                children = parent.takeChildren()
                for child in sorted(
                    children,
                    key=lambda row: rank.get(row.data(0, Qt.ItemDataRole.UserRole), -1),
                    reverse=True,
                ):
                    parent.addChild(child)
                    order_children(child)

            order_children(root)
            mode = getattr(self.window, "object_edit", None)
            if mode and mode.active:
                anchor = self.items.get(mode.key, root)
                # Tree roots are not rendered. Artwork itself must remain an editable row;
                # compound containers expose their children beneath the composer header.
                if anchor is not root and isinstance(service.record(mode.key), SceneObject):
                    anchor = anchor.parent() or root
                tree.setRootIndex(tree.indexFromItem(anchor))
            tree.headerItem().setText(
                0, "Layers · front to back" if mode and mode.active else "Objects · front to back"
            )
        self.refresh()
        self.window.filter_scene(self.window.filter.text())
        vm = self.window.viewmodel
        if not self.window.object_edit.active and not (vm.rig.active or vm.mesh.active):
            self.select_entries(self.model.selected)
        if state:
            state.restore(tree)

    def row_icon(self, record: Any) -> QIcon:
        """Keep stage Objects distinct from their source thumbnails and editable parts."""
        if isinstance(record, Bone) and record.extra.get("rig_root"):
            return self.window.icons.icon("control_camera")
        if isinstance(record, Camera):
            return self.window.icons.icon("videocam")
        if (
            isinstance(record, SceneObject)
            and not self.window.object_edit.active
            or isinstance(record, Group)
            and record.extra.get("object_container")
        ):
            return self.window.icons.icon("widgets")
        kind = (
            "device_hub"
            if isinstance(record, Bone)
            else "person_outline"
            if isinstance(record, (Skeleton, Character))
            else "folder"
            if isinstance(record, Group)
            else "image"
        )
        return self.window.asset_icon(getattr(record, "asset_id", None), kind)

    def add_row(self, record: Any, parent: QTreeWidgetItem) -> QTreeWidgetItem:
        """Retain stable identity separately from editable display text and row controls."""
        item = QTreeWidgetItem([record.name, "", ""])
        parent.addChild(item)
        item.setData(0, Qt.ItemDataRole.UserRole, record.id)
        item.setData(0, Qt.ItemDataRole.UserRole + 1, type(record).__name__)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        if isinstance(record, Camera):
            item.setFlags(
                item.flags() & ~Qt.ItemFlag.ItemIsDragEnabled & ~Qt.ItemFlag.ItemIsDropEnabled
            )
        elif isinstance(record, (SceneObject, Group, Bone, Character)):
            item.setFlags(
                item.flags() | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled
            )
        elif isinstance(record, Skeleton):
            item.setFlags(
                (item.flags() | Qt.ItemFlag.ItemIsDropEnabled) & ~Qt.ItemFlag.ItemIsDragEnabled
            )
        else:
            item.setFlags(
                item.flags() & ~Qt.ItemFlag.ItemIsDragEnabled & ~Qt.ItemFlag.ItemIsDropEnabled
            )
        item.setIcon(0, self.row_icon(record))
        if isinstance(record, Character):
            item.setIcon(0, self.window.icons.icon("person_outline"))
            item.setToolTip(
                0, f"Character · {len(record.mesh_ids)} parts\nDouble-click to edit · F2 to rename"
            )
        if not isinstance(record, Character):
            label = (
                "Object"
                if isinstance(record, SceneObject)
                or isinstance(record, Group)
                and record.extra.get("object_container")
                else "Folder"
                if isinstance(record, Group)
                else type(record).__name__
            )
            item.setToolTip(0, f"{label}\nDouble-click to edit · F2: rename · Ctrl: select more")
        if isinstance(record, Bone) and record.extra.get("rig_root"):
            item.setToolTip(
                0, "Rig Root · master control\nBone: reposition root · FK / Rig: carry skeleton"
            )
        if isinstance(record, Camera):
            item.setToolTip(
                0, "Camera · double-click for settings · transform or key it in the timeline"
            )
        self.items[record.id] = item
        return item

    def move_entries(self, keys: tuple[str, ...], parent: str | None, before: str | None) -> None:
        """Route row moves through the same atomic authoring service used by automation."""
        service = self.model.service
        if not service:
            return
        actors = {c.id: c for c in service.scene.characters}
        if parent in actors:
            if any(k in actors for k in keys):
                self.window.statusBar().showMessage(
                    "Keep characters separate; add image parts in Object Edit.", 6000
                )
                return
            self.model.run(lambda s: s.move_entries(keys, parent, before))
            return
        expanded = self.movement_keys(keys)
        if before in actors:
            before = min(
                actors[before].object_ids,
                key=lambda k: (
                    service.scene.draw_order.index(k) if k in service.scene.draw_order else -1
                ),
            )
        self.model.run(lambda s: s.move_entries(tuple(expanded), parent, before))

    def movement_keys(self, keys: tuple[str, ...]) -> tuple[str, ...]:
        """Keep complete character folders intact when organizing objects in Scene."""
        service = self.model.service
        if not service:
            return ()
        selected = set(keys)
        for actor in service.scene.characters:
            if actor.id in selected or (
                not self.window.object_edit.active
                and actor.object_ids
                and set(actor.object_ids) <= selected
            ):
                owned = {k for k, owner in self.character_nodes.items() if owner == actor.id}
                selected.difference_update((*actor.object_ids, actor.id))
                selected.update(
                    k for k in owned if getattr(service.record(k), "parent_id", None) not in owned
                )
        return tuple(selected)

    def group_selection(self, empty: bool = False) -> None:
        """Create a scene container or an owned character folder using the current workspace."""
        if self.window.object_edit.active:
            self.window.character_panel.add_folder(empty=empty)
            return
        keys = () if empty else self.movement_keys(self.model.selected)

        def apply(service: Any) -> None:
            """Create and mark a scene folder as one reversible organization change."""
            with service.document.command_group("Create scene folder"):
                key = service.group(keys, "Scene folder")
                group = service.record(key)
                service.update_records(
                    {key: replace(group, extra={**group.extra, "scene_folder": True})},
                    "Organize scene folder",
                )

        self.model.run(apply)

    def new_object(self) -> None:
        """Create an empty, transformable object that can be opened before importing parts."""
        from rigora.application_services.characters import CharacterService

        self.window.object_edit.exit()
        if self.window.viewmodel.documents.project is None:
            self.window.viewmodel.new_project()
        created = []
        self.model.run(
            lambda service: created.append(CharacterService(service.document).create_object())
        )
        if created and not self.model.error:
            self.window.navigate()
            self.select_entries((created[0],))

    def make_object(self) -> None:
        """Combine selected artwork into one compound object while retaining reusable animation."""
        from rigora.application_services.characters import CharacterService

        keys = self.movement_keys(self.model.selected)
        if not keys:
            return
        created = []

        def apply(service: Any) -> None:
            """Preserve a single animated object's identity; group multiple static entries."""
            objects = CharacterService(service.document)
            created.append(
                objects.promote_object(keys[0]) if len(keys) == 1 else objects.create_object(keys)
            )

        self.model.run(apply)
        if created and not self.model.error:
            self.select_entries((created[0],))

    def change_scene(self, operation: Callable[[Any], object]) -> None:
        """End transient editing before a scene switch, then bind the single active runtime."""
        vm = self.window.viewmodel
        if vm.documents.project is None:
            return
        vm.playback.pause()
        for name in (
            "bone_editor",
            "spring_editor",
            "motion_pilot",
            "camera_dialog",
            "face_dialog",
            "dynamics_dialog",
            "retarget_dialog",
        ):
            editor = getattr(self.window, name, None)
            if editor is not None and editor.isVisible():
                editor.close()
        if self.window.puppet_stage:
            self.window.puppet_stage.stop(cancel=True)
        if self.window.object_edit.active:
            self.window.object_edit.exit()
        vm.rig.active = vm.mesh.active = False
        self.window.content_drop.clear()
        try:
            operation(vm.documents)
            self.model.error = ""
        except ProjectError as error:
            self.model.error = str(error)
            self.window.statusBar().showMessage(str(error), 5000)
        vm.changed.emit()

    def activate_scene(self, scene_id: str) -> None:
        """Activate one scene; the document releases the previous scene's runtime."""
        self.change_scene(lambda document: document.select_scene(scene_id))

    def add_scene(self) -> None:
        """Create and activate an empty scene with the current canvas settings."""
        self.change_scene(lambda document: document.select_scene(document.add_scene()))

    def remove_scene(self, scene_id: str) -> None:
        """Delete the selected scene through shared Undo, retaining at least one scene."""
        self.change_scene(lambda document: document.delete_scene(scene_id))

    def context_menu(self, point: Any) -> None:
        """Expose folder creation, attachment, ordering, readable rename and undoable deletion."""
        from PySide6.QtWidgets import QMenu

        tree = self.window.tree
        item = tree.itemAt(point)
        if item and not item.isSelected():
            with QSignalBlocker(tree):
                tree.clearSelection()
                item.setSelected(True)
            self.select_tree()
        menu = QMenu(tree)
        tag = item.data(0, Qt.ItemDataRole.UserRole + 5) if item else None
        if not self.window.object_edit.active:
            menu.addAction("Add scene", self.add_scene)
            self.window.camera_workspace.menu(menu)
        if tag and tag[0] == "scene" and self.model.service:
            assert item is not None
            scene_id = tag[1]
            self.window.object_assets.add_clipboard_actions(menu, scene_id=scene_id)
            if scene_id != self.model.service.scene.id:
                menu.addAction("Activate scene", partial(self.activate_scene, scene_id))
            menu.addAction("Rename scene", lambda: tree.editItem(item, 0))
            delete = menu.addAction("Delete scene", partial(self.remove_scene, scene_id))
            project = self.model.service.document.project
            delete.setEnabled(project is not None and len(project.scenes) > 1)
            menu.addSeparator()
        if (
            item
            and self.model.service
            and isinstance(
                self.model.service.records().get(item.data(0, Qt.ItemDataRole.UserRole)), Camera
            )
        ):
            menu.addAction("Rename camera", lambda: tree.editItem(item, 0))
            menu.addAction("Delete camera", self.delete_selection)
            menu.exec(tree.viewport().mapToGlobal(point))
            return
        mode = getattr(self.window, "object_edit", None)
        if not (tag and tag[0] == "scene"):
            self.window.object_assets.add_clipboard_actions(menu)
        if mode:
            mode.menu_actions(menu, item.data(0, Qt.ItemDataRole.UserRole) if item else "")
        menu.addAction("New empty object", self.new_object)
        menu.addAction("Make object from selection", self.make_object)
        menu.addAction("New folder", lambda: self.group_selection(empty=True))
        keys = () if tag and tag[0] == "scene" else self.model.selected
        if keys:
            menu.addAction("Save as Object", self.window.object_assets.save)
            if self.pivot_point(self.transform_frame()) is not None:
                menu.addAction("Center pivot", self.center_pivot)
            parent = (
                getattr(self.model.service.record(keys[0]), "parent_id", None)
                if self.model.service
                else None
            )
            menu.addAction("Group selection", self.group_selection)
            menu.addAction("Move to scene root", lambda: self.move_entries(keys, None, None))
            menu.addAction(
                "Bring to front",
                lambda: self.move_entries(keys, parent, None),
            )
            menu.addAction("Attach object…", self.window.attach_selection)
            attach = menu.addMenu("Rig binding · attach part to bone")
            if self.model.service:
                for rig in self.model.service.scene.skeletons:
                    for bone in rig.bones:
                        attach.addAction(
                            menu_text(bone.name),
                            partial(self.attach_to, bone.id),
                        )
            menu.addSeparator()
            if item:
                menu.addAction("Rename", lambda: tree.editItem(item, 0))
            menu.addAction("Delete selection", self.delete_selection)
        self.window.plugin_workspace.populate_context(
            menu, "layers", item_id=item.data(0, Qt.ItemDataRole.UserRole) if item else ""
        )
        menu.exec(tree.viewport().mapToGlobal(point))

    def delete_selection(self) -> None:
        """Remove only the current scene selection; service validation protects references."""
        from rigora.application_services.characters import CharacterService

        selected = set(self.model.selected)
        items = self.window.tree.selectedItems()
        if (
            not self.window.object_edit.active
            and items
            and not any(item.data(0, Qt.ItemDataRole.UserRole) for item in items)
        ):
            for item in items:
                tag = item.data(0, Qt.ItemDataRole.UserRole + 5)
                if tag and tag[0] == "scene":
                    self.remove_scene(tag[1])
                    return

        def apply(service: Any) -> None:
            """Delete complete selected actors before removing their remaining scene entries."""
            with service.document.command_group("Delete scene selection"):
                if not self.window.object_edit.active:
                    characters = CharacterService(service.document)
                    deleting = {
                        characters.mesh(k).object_id for k in characters.meshes_for(tuple(selected))
                    }
                    for actor in tuple(service.scene.characters):
                        if actor.object_ids and set(actor.object_ids) <= deleting:
                            characters.delete_character(actor.id)
                    selected.intersection_update(service.records())
                service.delete_entries(tuple(selected))

        self.model.run(apply)

    def attach_to(self, bone_id: str) -> None:
        """Attach the selected artwork to a context-menu bone target."""
        self.model.run(lambda s: s.attach(self.model.selected, bone_id))

    def viewport_menu(self, point: Any) -> None:
        """Delete or group stage picks through exactly the same scene commands as the tree."""
        from PySide6.QtWidgets import QMenu

        key = self.pick(QPointF(point))
        if key and key not in self.model.selected:
            self.select_entries((key,))
        menu = QMenu(self.window.viewport)
        if self.model.service and key and isinstance(self.model.service.record(key), Camera):
            self.window.camera_workspace.menu(menu)
            menu.addAction("Center pivot", self.center_pivot)
            menu.addAction("Delete camera", self.delete_selection)
            menu.exec(self.window.viewport.mapToGlobal(point))
            return
        self.window.object_assets.add_clipboard_actions(menu)
        mode = getattr(self.window, "object_edit", None)
        if mode:
            mode.menu_actions(menu, key)
        if self.model.selected:
            menu.addAction("Save as Object", self.window.object_assets.save)
            if self.pivot_point(self.transform_frame()) is not None:
                menu.addAction("Center pivot", self.center_pivot)
            menu.addAction("Group selection", self.group_selection)
            menu.addAction("Attach object…", self.window.attach_selection)
            menu.addAction("Delete selection", self.delete_selection)
        menu.addAction("New empty object", self.new_object)
        menu.addAction("Make object from selection", self.make_object)
        menu.addAction("New folder", lambda: self.group_selection(empty=True))
        self.window.plugin_workspace.populate_context(menu, "scene", item_id=key or "")
        menu.exec(self.window.viewport.mapToGlobal(point))

    def refresh(self) -> None:
        """Refresh row state, selection outlines and context properties without losing tree
        expansion.
        """
        service, window = self.model.service, self.window
        records = service.records() if service else {}
        with QSignalBlocker(window.tree):
            for key, item in self.items.items():
                entry = records.get(key)
                if entry is None:
                    continue
                visible = getattr(entry, "visible", entry.extra.get("visible", True))
                if isinstance(entry, Camera):
                    current = (
                        active_camera(window.viewport.source_pose)
                        if window.viewport.source_pose
                        else None
                    )
                    item.setIcon(
                        0,
                        window.icons.icon(
                            "videocam" if current and current.id == key else "videocam_off"
                        ),
                    )
                locked = getattr(entry, "locked", entry.extra.get("locked", False))
                item.setIcon(
                    1,
                    window.icons.icon(
                        "visibility" if visible else "visibility_off",
                        12,
                        "#eeeeee"
                        if visible and self.window.themes.name == "dark"
                        else "#202020"
                        if visible
                        else "#777777",
                    ),
                )
                item.setIcon(
                    2,
                    window.icons.icon(
                        "lock" if locked else "lock_open", 12, "#df7272" if locked else "#70b88a"
                    ),
                )
                item.setToolTip(1, "Hide entry" if visible else "Show entry")
                item.setToolTip(2, "Unlock entry" if locked else "Lock entry")
                item.setSelected(key in self.model.selected)
                if isinstance(entry, Character) and not self.window.object_edit.active:
                    item.setSelected(
                        set(entry.object_ids) <= set(self.model.selected)
                        if entry.object_ids
                        else key in self.model.selected
                    )
        window.viewport.selected_nodes = self.model.selected
        window.viewport.update()
        if hasattr(window, "object_properties"):
            window.object_properties.refresh()
        if self.model.error:
            window.statusBar().showMessage(self.model.error, 8000)

    def select_tree(self) -> None:
        """Inspect selected rows and activate the matching editor without guessing an unrelated
        bone.
        """
        items = self.window.tree.selectedItems()
        if self.model.service and len(items) == 1:
            tag = items[0].data(0, Qt.ItemDataRole.UserRole + 5)
            if tag and tag[0] == "scene" and tag[1] != self.model.service.scene.id:
                return
        keys = tuple(
            item.data(0, Qt.ItemDataRole.UserRole)
            for item in self.window.tree.selectedItems()
            if item.data(0, Qt.ItemDataRole.UserRole)
        )
        self.select_entries(keys)
        if not keys or not self.model.service:
            return
        entry = self.model.service.record(keys[0])
        vm = self.window.viewmodel
        if isinstance(entry, Bone) and all(
            isinstance(self.model.service.record(k), Bone) for k in keys
        ):
            self.window.rig_workspace.set_mode(True)
            if vm.rig.tool == "draw":
                vm.rig.set_tool("select")
            vm.rig.select_many(keys, False)
        else:
            self.window.rig_workspace.set_mode(False)
            self.window.mesh_workspace.set_mode(False)
            mesh = next(
                (m for m in self.model.service.scene.meshes if m.object_id == keys[0]), None
            )
            if mesh:
                vm.mesh.select_mesh(mesh.id)
            if not self.window.object_edit.active:
                self.window.inspector.setCurrentIndex(0)
            self.window.command_actions["navigate"].setChecked(True)
            self.window.viewport.pan_tool = False
            self.select_entries(keys)

    def sync_bones(self) -> None:
        """Mirror bone picks into scene rows without recursively re-entering rig mode."""
        rig = self.window.viewmodel.rig
        if not self._syncing_selection and rig.active and rig.selected != self.model.selected:
            self.model.select(rig.selected)

    def click_column(self, item: QTreeWidgetItem, column: int) -> None:
        """Toggle a row's visible/locked icon through one undoable service command."""
        tag = item.data(0, Qt.ItemDataRole.UserRole + 5)
        if tag and tag[0] == "scene":
            scene_id = tag[1]
            if column in (0, 1) and self.model.service and scene_id != self.model.service.scene.id:
                QTimer.singleShot(0, self, partial(self.activate_scene, scene_id))
            return
        key = item.data(0, Qt.ItemDataRole.UserRole)
        if not key or column not in (1, 2) or not self.model.service:
            return
        name = "visible" if column == 1 else "locked"

        def toggle(service: Any) -> None:
            """Resolve the current flag after earlier queued clicks have finished."""
            entry = service.record(key)
            value = not getattr(entry, name, entry.extra.get(name, name == "visible"))
            service.flags((key,), **{name: value})

        self.defer_edit(toggle)

    def activate_tree_item(self, item: QTreeWidgetItem, column: int) -> None:
        """Support Enter on an inactive scene header without editing its object rows."""
        tag = item.data(0, Qt.ItemDataRole.UserRole + 5)
        if (
            tag
            and tag[0] == "scene"
            and self.model.service
            and tag[1] != self.model.service.scene.id
        ):
            QTimer.singleShot(0, self, partial(self.activate_scene, tag[1]))

    def defer_edit(self, operation: Callable[[Any], object]) -> None:
        """Publish a captured row edit after Qt releases its item, within its document/context."""
        document = self.model.document
        context = document.animation_context if document else None
        scene_id = document.scene.id if document and document.project else None

        def commit() -> None:
            """Ignore queued item gestures after a document or editing-context switch."""
            if (
                document is not None
                and self.model.document is document
                and document.animation_context == context
                and document.project is not None
                and document.scene.id == scene_id
            ):
                self.model.run(operation)

        QTimer.singleShot(0, self, commit)

    def rename(self, item: QTreeWidgetItem, column: int) -> None:
        """Publish edited row names while ignoring icon/selection-only updates."""
        tag = item.data(0, Qt.ItemDataRole.UserRole + 5)
        if column == 0 and self.model.service and tag and tag[0] == "scene":
            name = item.text(0)
            project = self.model.service.document.project
            scene = next((s for s in project.scenes if s.id == tag[1]), None) if project else None
            if scene and name != scene.name:
                self.defer_edit(lambda service: service.rename_scene(name, tag[1]))
            return
        key = item.data(0, Qt.ItemDataRole.UserRole)
        if (
            column == 0
            and key
            and self.model.service
            and item.text(0) != self.model.service.record(key).name
        ):
            name = item.text(0)
            self.defer_edit(lambda service: service.rename(key, name))

    def select_entries(self, keys: tuple[str, ...], extend: bool = False) -> None:
        """Keep mixed scene identities and the bone editor subset synchronized without recursion."""
        mode = getattr(self.window, "object_edit", None)
        vm = self.window.viewmodel
        if self.model.service:
            actors = {c.id: c for c in self.model.service.scene.characters}
            keys = tuple(
                k
                for key in keys
                for k in (
                    actors[key].object_ids if key in actors and actors[key].object_ids else (key,)
                )
            )
        if (
            (mode is None or not mode.active)
            and not (vm.rig.active or vm.mesh.active)
            and self.model.service
        ):
            from rigora.application_services.characters import CharacterService

            service = CharacterService(vm.documents)
            expanded = set(keys)
            for mesh_id in service.meshes_for(keys):
                actor = service.owner(mesh_id)
                if actor:
                    expanded.update(actor.object_ids)
            for actor in service.scene.characters:
                actor_bones = {
                    b.id
                    for r in service.scene.skeletons
                    if r.id == actor.skeleton_id
                    for b in r.bones
                }
                if actor.object_ids and actor_bones & expanded:
                    expanded.difference_update(actor_bones)
                    expanded.update(actor.object_ids)
            keys = tuple(expanded)
        if self.model.service and (mode is None or not mode.active):
            from rigora.application_services.characters import CharacterService

            service = CharacterService(vm.documents)
            keys = tuple(
                dict.fromkeys(
                    root.id if (root := service.object_root(key)) else key for key in keys
                )
            )
        self._syncing_selection = True
        try:
            self.model.select(keys, extend)
            if self.model.service:
                bones = tuple(
                    k for k in self.model.selected if isinstance(self.model.service.record(k), Bone)
                )
                self.window.viewmodel.rig.select_many(bones)
        finally:
            self._syncing_selection = False

    def allows(self, key: str) -> bool:
        """Apply viewport type filters to artwork, bone and group identities."""
        if not self.model.service:
            return False
        record = self.model.service.record(key)
        mode = self.window.object_edit
        if mode.active and (
            key not in mode.ids or key == mode.key and isinstance(record, (Group, Character))
        ):
            return False
        if isinstance(record, Bone) and not self.window.object_edit.active:
            return False
        kind = (
            "bones"
            if isinstance(record, Bone)
            else "groups"
            if isinstance(record, Group)
            else "images"
        )
        return kind in self.model.selection_types

    def filters_changed(self) -> None:
        """Apply checkbox selection types to subsequent picks and current editable selection."""
        self.model.selection_types = {
            kind for kind, check in self.window.selection_filters.items() if check.isChecked()
        }
        if self.window.viewmodel.mesh.active:
            self.window.mesh_workspace.set_mode(False)
        self.window.rig_workspace.set_mode(False)
        self.select_entries(tuple(k for k in self.model.selected if self.allows(k)))

    def rectangle_keys(self, rect: QRectF) -> tuple[str, ...]:
        """Select all visible unlocked types, including bone segments crossing the rectangle."""
        service = self.model.service
        if not service:
            return ()
        polygons = self.polygons()
        keys = [
            key
            for key, polygon in polygons.items()
            if self.allows(key)
            and not service.locked(key)
            and rect.intersects(polygon.boundingRect())
        ]
        if "bones" in self.model.selection_types:
            keys.extend(
                k for k in self.window.viewport.bones_in_rectangle(rect) if not service.locked(k)
            )
        if "groups" in self.model.selection_types:
            records = service.records()
            for group in service.scene.groups:
                if not self.allows(group.id):
                    continue
                bounds = QRectF()
                for key, polygon in polygons.items():
                    if service._has_ancestor(key, {group.id}, records):
                        bounds = bounds.united(polygon.boundingRect())
                if not bounds.isNull() and rect.contains(bounds) and not service.locked(group.id):
                    keys.append(group.id)
        return tuple(dict.fromkeys(keys))

    def polygons(self) -> dict[str, QPolygonF]:
        """Reuse evaluated polygons and translate them natively when only the camera pans."""
        viewport = self.window.viewport
        pose = viewport.pose
        view = (viewport.zoom, viewport.offset.x(), viewport.offset.y())
        if pose is self._screen_pose and view == self._screen_view:
            return self._screen_polygons
        if pose is self._screen_pose and self._screen_view and view[0] == self._screen_view[0]:
            delta = QPointF(view[1] - self._screen_view[1], view[2] - self._screen_view[2])
            self._screen_points = {k: p.translated(delta) for k, p in self._screen_points.items()}
            self._screen_polygons = {
                k: p.translated(delta) for k, p in self._screen_polygons.items()
            }
            self._screen_view = view
            return self._screen_polygons
        result: dict[str, QPolygonF] = {}
        self._screen_points = {}
        self._screen_meshes = {}
        if pose:
            for mesh in pose.meshes.values():
                node = pose.nodes.get(mesh.object_id or "")
                if node and node.visible:
                    points = mesh_polygon(
                        mesh.positions, node.world_matrix, viewport.zoom, viewport.offset
                    )
                    self._screen_points[mesh.id] = points
                    self._screen_meshes.setdefault(node.id, []).append(mesh)
                    result[node.id] = (
                        QPolygonF(result[node.id].boundingRect().united(points.boundingRect()))
                        if node.id in result
                        else points
                    )
            occupied = set(result)
            for key in tuple(occupied):
                node = pose.nodes[key]
                while node.parent_id and node.parent_id not in occupied:
                    occupied.add(node.parent_id)
                    node = pose.nodes[node.parent_id]
            if self.model.service:
                from rigora.application_services.characters import CharacterService

                characters = CharacterService(self.model.service.document)
                # Bare armatures have no artwork polygons. Their owning Object
                # still needs a stage hit area and transform handles.
                bare_owners: dict[str, list[QPointF]] = {}
                for rig in self.model.service.scene.skeletons:
                    owner = str(rig.extra.get("object_id", ""))
                    owner_node = pose.nodes.get(owner)
                    if owner in occupied or not owner_node or not owner_node.visible:
                        continue
                    root = characters.object_root(owner)
                    if root and root.id in occupied:
                        continue
                    key = root.id if root else owner
                    bare_owners.setdefault(key, []).extend(
                        viewport.offset
                        + QPointF(*transform_point(node.world_matrix, x, 0)) * viewport.zoom
                        for bone in rig.bones
                        if (node := pose.nodes.get(bone.id)) is not None and node.visible
                        for x in (0, node.length)
                    )
                for owner, bone_points in bare_owners.items():
                    if bounds := transform_gizmo.bounds(bone_points, padding=8):
                        result[owner] = QPolygonF(bounds)
                occupied.update(
                    str(rig.extra["object_id"])
                    for rig in self.model.service.scene.skeletons
                    if rig.bones and rig.extra.get("object_id")
                )
                for group in self.model.service.scene.groups:
                    node = pose.nodes.get(group.id)
                    if (
                        group.extra.get("object_container")
                        and group.id not in result
                        and group.id not in occupied
                        and node
                        and node.visible
                    ):
                        center = viewport.offset + QPointF(*node.world_matrix[4:]) * viewport.zoom
                        result[group.id] = QPolygonF(
                            QRectF(center - QPointF(24, 24), QSizeF(48, 48))
                        )
        if pose and not self.window.object_edit.active:
            from rigora.engine.cameras import camera_corners

            for camera in pose.cameras:
                if camera.id in pose.nodes and camera.extra.get("visible", True):
                    result[camera.id] = QPolygonF(
                        [
                            viewport.offset + QPointF(*p) * viewport.zoom
                            for p in camera_corners(camera, pose, viewport.settings)
                        ]
                    )
        if pose and self.model.service:
            from rigora.engine.game_regions import game_regions

            for region in game_regions(self.model.service.scene, pose):
                if region["enabled"]:
                    result[region["id"]] = QPolygonF(
                        [
                            viewport.offset + QPointF(*point) * viewport.zoom
                            for point in region["points"]
                        ]
                    )
            for owner in pose.particles:
                center = (
                    viewport.offset + QPointF(*pose.nodes[owner].world_matrix[4:]) * viewport.zoom
                )
                result[owner] = QPolygonF(QRectF(center - QPointF(12, 12), QSizeF(24, 24)))
        self._screen_pose, self._screen_view, self._screen_polygons = pose, view, result
        return result

    def mesh_at(self, point: QPointF, *, object_id: str = "", include_locked: bool = False) -> str:
        """Resolve frontmost painted mesh coverage for pointer selection and content targeting.

        Type filters belong to the selection caller. Content drops can inspect
        artwork under bone controls without falling back to rectangular bounds.
        """
        viewport, service = self.window.viewport, self.model.service
        pose = viewport.pose
        if pose is None or service is None:
            return ""
        polygons = self.polygons()
        order = (object_id,) if object_id else reversed(pose.render_order)
        for key in order:
            node, polygon = pose.nodes.get(key), polygons.get(key)
            if (
                node is None
                or not node.visible
                or node.opacity * 255 < 8
                or polygon is None
                or not polygon.boundingRect().contains(point)
                or not include_locked
                and service.locked(key)
            ):
                continue
            for mesh in reversed(self._screen_meshes.get(key, ())):
                image = viewport.artwork.styled(mesh.asset_id or "", mesh.appearance)
                points = self._screen_points[mesh.id]
                if image is not None and mesh_contains(
                    mesh,
                    tuple(points.at(i) for i in range(points.count())),
                    image,
                    point,
                    opacity=node.opacity,
                    pixel_ratio=viewport.devicePixelRatioF(),
                ):
                    return mesh.id
        return ""

    def pick(self, point: QPointF, *, include_locked: bool = False) -> str:
        """Pick front-to-back through transparent artwork using evaluated painted coverage."""
        viewport, service = self.window.viewport, self.model.service
        pose = viewport.pose
        if pose is None or service is None:
            return ""
        polygons = self.polygons()
        for camera in reversed(pose.cameras):
            polygon = polygons.get(camera.id)
            if (
                polygon is not None
                and self.allows(camera.id)
                and (include_locked or not service.locked(camera.id))
            ):
                for index in range(4):
                    start, end = polygon.at(index), polygon.at((index + 1) % 4)
                    delta, relative = end - start, point - start
                    squared = delta.x() ** 2 + delta.y() ** 2
                    fraction = (
                        max(
                            0.0,
                            min(
                                1.0, (relative.x() * delta.x() + relative.y() * delta.y()) / squared
                            ),
                        )
                        if squared
                        else 0.0
                    )
                    nearest = start + delta * fraction
                    if (point - nearest).manhattanLength() <= 8:
                        return camera.id
        order = (*[key for key in polygons if pose.nodes[key].kind == "group"], *pose.render_order)
        special = {
            o.id
            for o in service.scene.objects
            if "game_region" in o.extra or "particle_emitter" in o.extra
        }
        for key in reversed(order):
            node = pose.nodes[key]
            if (
                not node.visible
                or (service.locked(key) and not include_locked)
                or not self.allows(key)
            ):
                continue
            if node.kind == "bone":
                mode = getattr(self.window, "object_edit", None)
                if (
                    not self.window.viewmodel.rig.active
                    and (mode is None or not mode.active)
                    and any(
                        c.object_ids
                        and any(
                            b.id == node.id
                            for r in service.scene.skeletons
                            if r.id == c.skeleton_id
                            for b in r.bones
                        )
                        for c in service.scene.characters
                    )
                ):
                    continue
                root = (
                    viewport.offset
                    + QPointF(*transform_point(node.world_matrix, 0, 0)) * viewport.zoom
                )
                tip = (
                    viewport.offset
                    + QPointF(*transform_point(node.world_matrix, node.length, 0)) * viewport.zoom
                )
                if viewport.bone_shape.contains(point, root, tip):
                    return key
            else:
                polygon = polygons.get(key)
                if polygon is None or not polygon.boundingRect().contains(point):
                    continue
                if node.kind == "group":
                    return key
                if key in special and polygon.containsPoint(point, Qt.FillRule.OddEvenFill):
                    return key
                if self.mesh_at(point, object_id=key, include_locked=include_locked):
                    return key
        return ""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Route default selection and object dragging while preserving pan and specialized
        editors.
        """
        viewport, vm = self.window.viewport, self.window.viewmodel
        if (
            watched is not viewport
            and watched is not self.window.tree
            and not isinstance(event, QKeyEvent)
        ):
            return False
        if (
            isinstance(event, QKeyEvent)
            and self.transform
            and event.key() in (Qt.Key.Key_Shift, Qt.Key.Key_Alt)
        ):
            if event.type() == QEvent.Type.ShortcutOverride:
                event.accept()
                return True
            modifiers = transform_gizmo.modifiers_after(event)
            self.update_drag(self.last_screen, modifiers)
            return True
        if watched is self.window.tree:
            if (
                isinstance(event, QKeyEvent)
                and event.type() == QEvent.Type.KeyPress
                and event.key() == Qt.Key.Key_Delete
            ):
                self.delete_selection()
                return True
            return False
        if event.type() == QEvent.Type.FocusOut:
            dragging = self.drag is not None
            pending = dragging or self.marquee is not None
            self.drag, self.marquee = None, None
            self.transform = None
            self.release_modifiers()
            # Dialogs share scene previews; focus loss may cancel only our pointer gesture.
            if dragging:
                self.model.cancel_preview()
            if pending:
                self.window.update_animation()
        if isinstance(event, QKeyEvent) and event.key() == Qt.Key.Key_Escape:
            self.drag, self.marquee = None, None
            self.transform = None
            self.release_modifiers()
            self.model.cancel_preview()
            self.window.update_animation()
            viewport.refresh_cursor()
        if (
            isinstance(event, QKeyEvent)
            and event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Delete
            and not vm.mesh.active
        ):
            self.delete_selection()
            return True
        if (
            isinstance(event, QKeyEvent)
            and event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_A
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
            and not vm.mesh.active
        ):
            self.select_entries(self.rectangle_keys(QRectF(-1e8, -1e8, 2e8, 2e8)))
            return True
        if not self.model.service or vm.mesh.active or viewport.extension_pointer:
            return False
        if (
            not isinstance(event, QMouseEvent)
            or viewport.pan_tool
            or viewport._space
            or viewport._drag is not None
            or event.button() == Qt.MouseButton.MiddleButton
            or event.buttons() & Qt.MouseButton.MiddleButton
        ):
            return False
        viewport.refresh_cursor(event.position())
        try:
            if (
                event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
            ):
                vm.playback.pause()
                self.transform = None
                if vm.rig.active and vm.rig.tool == "select":
                    if viewport.pose and viewport.rig_target in viewport.pose.nodes:
                        target = viewport.pose.nodes[viewport.rig_target]
                        point = viewport.offset + QPointF(*target.world_matrix[4:]) * viewport.zoom
                        if (point - event.position()).manhattanLength() < 16:
                            return False
                    bone_rect = viewport.bone_transform_bounds()
                    if bone_rect and transform_gizmo.pick(bone_rect, event.position()) is not None:
                        return False
                frame = self.transform_frame() if not vm.rig.active else None
                pivot = self.pivot_point(frame)
                handle = (
                    transform_gizmo.pick(frame[0], event.position(), frame[1], pivot)
                    if frame
                    else None
                )
                if handle is not None:
                    assert frame is not None
                    rect, mapping, self.transform_owner = frame
                    local_pivot = (
                        mapping.inverted()[0].map(pivot)
                        if mapping is not None and pivot is not None
                        else pivot
                    )
                    self.transform = transform_gizmo.Gesture(
                        rect, event.position(), handle, local_pivot, mapping
                    )
                    self.drag = viewport.scene_point(event.position())
                    self.last_screen = event.position()
                    self.pivot_offset = (
                        viewport.scene_point(pivot) - self.drag if pivot is not None else QPointF()
                    )
                    self.model.begin_preview()
                    if handle != 9:
                        self.window.rig_workspace.begin_springs()
                    viewport.setFocus()
                    if app := QApplication.instance():
                        app.installEventFilter(self)
                    viewport.refresh_cursor(event.position())
                    return True
                key = self.pick(event.position())
                if vm.rig.active and (
                    vm.rig.tool != "select"
                    or (key and isinstance(self.model.service.record(key), Bone))
                ):
                    return False
                if (
                    key
                    and isinstance(self.model.service.record(key), Bone)
                    and self.model.tool != "scale"
                ):
                    self.window.rig_workspace.set_mode(True)
                    vm.rig.set_tool(
                        self.model.tool if self.model.tool in ("move", "rotate") else "select"
                    )
                    return False
                self.window.rig_workspace.set_mode(False)
                self.extend = bool(
                    event.modifiers()
                    & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
                )
                if key:
                    if key not in self.model.selected or self.extend:
                        self.select_entries((key,), self.extend)
                    self.drag = viewport.scene_point(event.position())
                    self.model.begin_preview()
                    self.window.rig_workspace.begin_springs()
                else:
                    self.marquee = event.position(), event.position()
                viewport.setFocus()
                viewport.refresh_cursor(event.position())
                return True
            if event.type() == QEvent.Type.MouseMove:
                if self.drag is not None:
                    self.update_drag(event.position(), event.modifiers())
                    return True
                if self.marquee:
                    self.marquee = self.marquee[0], event.position()
                    viewport.update()
                    return True
            if (
                event.type() == QEvent.Type.MouseButtonRelease
                and event.button() == Qt.MouseButton.LeftButton
            ):
                if self.drag is not None:
                    self.update_drag(event.position(), event.modifiers())
                    self.drag = None
                    self.model.finish_preview()
                    self.transform = None
                    self.release_modifiers()
                    self.window.update_animation()
                    viewport.refresh_cursor(event.position())
                    return True
                if self.marquee:
                    rect = QRectF(self.marquee[0], event.position()).normalized()
                    self.select_entries(self.rectangle_keys(rect), self.extend)
                    self.marquee = None
                    viewport.refresh_cursor(event.position())
                    viewport.update()
                    return True
        except ProjectError as error:
            self.drag = None
            self.transform = None
            self.release_modifiers()
            self.model.cancel_preview()
            self.window.statusBar().showMessage(str(error), 8000)
        return False

    def update_drag(
        self, screen: QPointF, modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier
    ) -> None:
        """Preview translation, relative rotation or uniform scaling from the original press."""
        assert self.drag is not None
        self.last_screen = screen
        delta = self.window.viewport.scene_point(screen) - self.drag
        if self.transform:
            if (screen - self.transform.start).manhattanLength() < 1e-6:
                self.model.preview_edit(lambda _: None)
                return
            if self.transform.handle == 9 and self.transform_owner:
                viewport = self.window.viewport
                point = viewport.scene_point(screen) + self.pivot_offset
                if not modifiers & Qt.KeyboardModifier.AltModifier:
                    mapping = self.transform.mapping
                    rect = self.transform.rect
                    targets = transform_gizmo.handles(rect, mapping)[:8]
                    targets.append(
                        mapping.map(rect.center()) if mapping is not None else rect.center()
                    )
                    current = point * viewport.zoom + viewport.offset
                    target = min(targets, key=lambda p: math.hypot(*(p - current).toTuple()))
                    if math.hypot(*(target - current).toTuple()) <= 14:
                        point = viewport.scene_point(target)
                self.model.preview_pivot(self.transform_owner, point.x(), point.y())
                return
            origin, rotation, sx, sy = self.transform.values(
                screen,
                centered=bool(modifiers & Qt.KeyboardModifier.AltModifier),
                snap=bool(modifiers & Qt.KeyboardModifier.ShiftModifier),
                proportional=self.transform.handle % 2 == 0
                or self.window.selection_properties.ratio.isChecked()
                or bool(modifiers & Qt.KeyboardModifier.ShiftModifier),
            )
            pivot = self.window.viewport.scene_point(origin)
            self.model.preview_transform(
                rotation=rotation,
                scale_x=sx,
                scale_y=sy,
                center_x=pivot.x(),
                center_y=pivot.y(),
                space_id=self.transform_owner if self.transform.handle != 8 else None,
            )
            return
        if delta.manhattanLength() < 2 / self.window.viewport.zoom:
            self.model.preview_transform(dx=0, dy=0)
            return
        if self.model.tool == "rotate":
            self.model.preview_transform(rotation=delta.x() * 0.5)
        elif self.model.tool == "scale":
            factor = max(0.01, math.exp(max(-5, min(5, delta.x() / 180))))
            self.model.preview_transform(scale_x=factor, scale_y=factor)
        else:
            self.model.preview_transform(dx=delta.x(), dy=delta.y())

    def preview(self) -> None:
        """Show transient evaluated geometry while leaving authored data untouched."""
        workspace = self.window.rig_workspace
        workspace.spring_input = time.monotonic()
        if workspace.spring_timer.isActive():
            workspace.tick_springs()
        else:
            self.window.viewport.set_pose(
                self.model.preview or self.window.viewmodel.documents.animation.pose
            )
        if self.model.error:
            self.window.statusBar().showMessage(self.model.error, 8000)

    def draw(self, painter: QPainter) -> None:
        """Outline selected deformed objects and draw a neutral scene marquee."""
        colors = PALETTES[self.window.viewport.theme]
        frame, pivot = None, None
        if not self.window.viewmodel.rig.active and not self.window.viewmodel.mesh.active:
            frame = self.transform_frame()
            if frame:
                rect, mapping, _ = frame
                pivot = self.pivot_point(frame)
                point = self.window.viewport._pointer
                handle = (
                    self.transform.handle
                    if self.transform
                    else transform_gizmo.pick(rect, point, mapping, pivot)
                    if point is not None
                    else None
                )
                painter.save()
                pose = self.window.viewport.pose
                if pose and frame[2] in {camera.id for camera in pose.cameras}:
                    camera = active_camera(pose)
                    if camera is None or camera.id != frame[2]:
                        painter.setOpacity(INACTIVE_CAMERA_OPACITY)
                transform_gizmo.draw(painter, rect, colors["text"], handle, mapping, pivot)
                painter.restore()
        painter.save()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(colors["text"]), 1, Qt.PenStyle.DashLine))
        pose = self.window.viewport.pose
        if pose:
            painter.setPen(QPen(QColor(colors["muted"]), 1))
            for key, polygon in self.polygons().items():
                if pose.nodes[key].kind == "group":
                    selected_pivot = pivot if frame and frame[2] == key else None
                    center = (
                        selected_pivot
                        if selected_pivot is not None
                        else polygon.boundingRect().center()
                    )
                    if selected_pivot is None:
                        painter.drawRect(QRectF(center - QPointF(4, 4), QSizeF(8, 8)))
                        painter.drawLine(center - QPointF(10, 0), center + QPointF(10, 0))
                        painter.drawLine(center - QPointF(0, 10), center + QPointF(0, 10))
                    painter.drawText(center + QPointF(14, -10), pose.nodes[key].name)
        painter.setPen(QPen(QColor(colors["text"]), 1, Qt.PenStyle.DashLine))
        outlined = (
            set(self.model.selected).intersection(mesh.object_id for mesh in pose.meshes.values())
            if pose
            else set()
        )
        if len(outlined) > 1:
            for key, polygon in self.polygons().items():
                if key in outlined:
                    painter.drawRect(polygon.boundingRect().adjusted(-4, -4, 4, 4))
        if self.marquee:
            painter.drawRect(QRectF(*self.marquee).normalized())
        if self.model.service:
            painter.setPen(QPen(QColor(colors["text"]), 1.5))
            from rigora.engine.game_regions import game_regions

            pose = self.window.viewport.pose
            if pose:
                for region in game_regions(self.model.service.scene, pose):
                    if not region["enabled"]:
                        continue
                    points = QPolygonF(
                        [
                            self.window.viewport.offset + QPointF(*p) * self.window.viewport.zoom
                            for p in region["points"]
                        ]
                    )
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.setPen(QPen(QColor(colors["text"]), 1, Qt.PenStyle.DashLine))
                    painter.drawPolygon(points)
                    painter.drawText(
                        points.boundingRect().topLeft() - QPointF(0, 4), region["name"]
                    )
            for pin in self.model.service.scene.constraints:
                if pin.kind == "foot_contact" and pin.enabled:
                    pose = self.window.viewport.pose
                    target = pose.nodes.get(pin.target_id or "") if pose else None
                    if target and pose:
                        weight = (
                            self.model.service.document.animation.evaluator.constraint_values(
                                pose.frame
                            )
                            .get(pin.id, {})
                            .get("weight", pin.parameters.get("weight", 0))
                        )
                        color = QColor(colors["text"])
                        color.setAlpha(255 if weight >= 0.99 else 80)
                        painter.setPen(QPen(color, 1.5))
                        point = (
                            self.window.viewport.offset
                            + QPointF(*target.world_matrix[4:]) * self.window.viewport.zoom
                        )
                        painter.drawEllipse(point, 6, 6)
                        painter.drawLine(point - QPointF(10, 0), point + QPointF(10, 0))
                    continue
                if pin.kind != "pin" or not pin.enabled or pin.target_id:
                    continue
                if "x" in pin.parameters and "y" in pin.parameters:
                    point = (
                        self.window.viewport.offset
                        + QPointF(pin.parameters["x"], pin.parameters["y"])
                        * self.window.viewport.zoom
                    )
                    painter.drawEllipse(point, 5, 5)
                    painter.drawLine(point - QPointF(8, 0), point + QPointF(8, 0))
                    painter.drawLine(point - QPointF(0, 8), point + QPointF(0, 8))
        painter.restore()

    def transform_bounds(self) -> QRectF | None:
        """Frame selected artwork and folder descendants using their evaluated geometry."""
        service = self.model.service
        if service is None:
            return None
        records = service.records()
        selected = {
            key
            for key in self.model.selected
            if isinstance(records.get(key), (Group, SceneObject)) and not service.locked(key)
        }
        if not selected:
            return None
        points: list[QPointF] = []
        for key, polygon in self.polygons().items():
            if key in records and (
                key in selected or service._has_ancestor(key, selected, records)
            ):
                rect = polygon.boundingRect()
                points.extend((rect.topLeft(), rect.bottomRight()))
        return transform_gizmo.bounds(points, padding=0)

    def transform_frame(self) -> tuple[QRectF, QTransform | None, str | None] | None:
        """Use the object's local axes for one image/folder, and scene axes for multi-selection."""
        rect = self.transform_bounds()
        if rect is None:
            return None
        service, viewport = self.model.service, self.window.viewport
        assert service is not None
        selected = set(self.model.selected)
        if len(selected) != 1 or viewport.pose is None:
            return rect, None, None
        key = next(iter(selected))
        node = viewport.pose.nodes.get(key)
        if node is None or not isinstance(service.record(key), (SceneObject, Group)):
            return rect, None, None
        a, b, c, d, x, y = node.world_matrix
        zoom, offset = viewport.zoom, viewport.offset
        mapping = QTransform(
            a * zoom, b * zoom, c * zoom, d * zoom, x * zoom + offset.x(), y * zoom + offset.y()
        )
        inv, valid = mapping.inverted()
        if not valid:
            return None
        local = QRectF()
        records = service.records()
        for owner, polygon in self.polygons().items():
            if owner == key or service._has_ancestor(owner, selected, records):
                local = local.united(inv.map(polygon).boundingRect())
        return (local, mapping, key) if local.width() > 1e-9 and local.height() > 1e-9 else None

    def pivot_point(
        self, frame: tuple[QRectF, QTransform | None, str | None] | None
    ) -> QPointF | None:
        """Return the displayed persistent pivot, or the geometric center for legacy defaults."""
        if not frame or not frame[2] or not self.window.viewport.pose or not self.model.service:
            return None
        rect, mapping, key = frame
        assert key is not None and mapping is not None
        local = self.window.viewport.pose.nodes[key].local
        point = QPointF(local.pivot_x, local.pivot_y)
        previewing_pivot = (
            self.model.preview is not None
            and self.transform is not None
            and self.transform.handle == 9
            and self.transform_owner == key
        )
        # A dragged pivot at local (0, 0) is explicit before its authored flag is committed.
        if (
            not previewing_pivot
            and not self.model.service.record(key).extra.get("pivot_edited")
            and point.isNull()
        ):
            point = rect.center()
        return mapping.map(point)

    def center_pivot(self) -> None:
        """Reset one selected artwork/folder pivot without translating its visible content."""
        frame = self.transform_frame()
        if frame and frame[1] is not None and frame[2]:
            point = self.window.viewport.scene_point(frame[1].map(frame[0].center()))
            self.model.run(lambda s: s.move_pivot(str(frame[2]), point.x(), point.y()))

    def release_modifiers(self) -> None:
        """Return Alt to the menu bar once a captured transform ends or is cancelled."""
        if app := QApplication.instance():
            app.removeEventFilter(self)
