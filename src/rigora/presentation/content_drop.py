"""Target-aware template drags with scratch placement feedback and atomic scene drops."""

import hashlib
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QEvent, QObject, QPointF, Qt, QTimer
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent

from rigora.application_services.content_library import ContentService
from rigora.application_services.documents import DocumentService
from rigora.domain.entities import nested_records
from rigora.domain.project import ProjectError
from rigora.infrastructure.content_packs import read_pack
from rigora.presentation.artwork import decode_artwork

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


class ContentDropWorkspace(QObject):
    """Own bounded pack caches and transient previews without mutating source during a drag."""

    def __init__(self, window: "MainWindow") -> None:
        """Bind viewport drag events and keep preview animation on the shared evaluator."""
        super().__init__(window)
        self.window, self.model = window, window.viewmodel.content
        self.cache: dict[Any, tuple[dict[str, bytes], dict[str, Any]]] = {}
        self.loading: set[Any] = set()
        self.hover: tuple[str, QPointF] | None = None
        self.pending: tuple[str, QPointF, Any, Any, str] | None = None
        self.document: Any = None
        self.preview_key: Any = None
        self.preview_nodes: set[str] = set()
        self.generation = 0
        self.preparing: Any = None
        self.preview_base: Any = None
        self.placing = False
        self.scene_work: tuple[Any, list[tuple[DocumentService, str]]] | None = None
        self.timer = QTimer(window)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self.tick)
        window.viewport.content_hovered.connect(self.move)
        window.viewport.content_left.connect(self.clear)
        window.viewport.content_dropped.connect(self.drop)
        window.empty_workspace.setAcceptDrops(True)
        window.empty_workspace.installEventFilter(self)

    def add_to_scene(self, key: str) -> None:
        """Place standalone catalog content at viewport center and retain main-scene editing."""
        entry = self.model.entry(key)
        if entry is None or not (
            entry.item.kind in ("scene", "rig", "artwork")
            or entry.item.payload.get("fallback_rig")
            or entry.item.payload.get("fallback_mesh")
        ):
            return
        self.window.object_assets.return_to_project()
        self.window.object_edit.exit()
        vm = self.window.viewmodel
        if vm.documents.project is None:
            vm.new_project()
        doc, baseline = vm.documents, vm.documents.project
        scene_id = doc.scene.id
        point = QPointF(self.window.viewport.rect().center())

        def place() -> None:
            """Keep delayed pack reads from placing into another project or scene."""
            if vm.documents is doc and doc.project is baseline and doc.scene.id == scene_id:
                self.drop_scene(entry, doc, point)

        if entry.path in self.cache:
            place()
        else:

            def loaded(result: Any) -> None:
                """Retain validated pack bytes; artwork decode follows normal scene adoption."""
                if len(self.cache) >= 4:
                    self.cache.pop(next(iter(self.cache)))
                self.cache[entry.path] = result[1], {}
                place()

            self.model.background(lambda: read_pack(entry.path), loaded)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Accept placeable templates on startup surfaces and create a project on drop."""
        if isinstance(event, (QDropEvent, QDragEnterEvent, QDragMoveEvent)):
            raw = bytes(event.mimeData().data("application/x-rigora-content").data())
            if len(raw) > 128:
                return False
            key = raw.decode("utf-8", errors="replace")
            entry = self.model.entry(key)
            if (
                not entry
                or entry.item.kind in ("action", "pose", "deformation", "spring")
                and not (
                    entry.item.payload.get("fallback_rig")
                    or entry.item.payload.get("fallback_mesh")
                )
            ):
                event.ignore()
                return True
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            if event.type() == QEvent.Type.Drop:
                self.window.viewmodel.new_project()
                self.drop(key, QPointF(self.window.viewport.rect().center()))
            return True
        return False

    def apply_to_selection(self, key: str) -> None:
        """Apply targeted creative content in one command; empty selection creates a specimen."""
        entry = self.model.entry(key)
        doc = self.model.document
        selected = self.window.viewmodel.scene.selected
        if entry is None:
            return
        if not selected or doc is None or doc.project is None:
            self.add_to_scene(key)
            return
        from rigora.application_services.characters import CharacterService

        characters = CharacterService(doc)
        members = set(selected)
        for owner in selected:
            root = characters.object_root(owner)
            members.update(characters.members(root.id if root else owner))
        rigs = [
            r
            for r in doc.scene.skeletons
            if r.id in members or any(b.id in members for b in r.bones)
        ]
        meshes = [m for m in doc.scene.meshes if m.id in selected or m.object_id in selected]
        if not meshes:
            meshes = [m for m in doc.scene.meshes if m.id in members or m.object_id in members]
        target = rigs[0].id if len(rigs) == 1 else ""
        if (
            entry.item.kind == "spring"
            and len(selected) == 1
            and rigs
            and any(b.id == selected[0] for b in rigs[0].bones)
        ):
            target = selected[0]
        mesh = meshes[0].id if len(meshes) == 1 else ""
        if (
            entry.item.kind in ("action", "spring")
            and not target
            or entry.item.kind == "deformation"
            and not mesh
        ):
            self.window.statusBar().showMessage(
                "Select one compatible rig, bone chain or artwork part first.", 6000
            )
            return
        baseline = doc.project
        context = doc.context_key

        def apply() -> None:
            """Reject a delayed operation after its selected project or editor context changed."""
            if doc.project is not baseline or doc.context_key != context:
                return
            try:
                ContentService(doc).place(
                    entry.item, self.cache[entry.path][0], target=target, mesh_id=mesh
                )
                self.model.library.used(key)
                self.model.document_changed.emit()
                self.window.statusBar().showMessage("Preset applied · Undo is available", 4000)
            except ProjectError as error:
                self.model.error = str(error)
                self.window.statusBar().showMessage(str(error), 6000)
            self.model.changed.emit()

        if entry.path in self.cache:
            apply()
        else:

            def loaded(result: Any) -> None:
                """Retain bounded source bytes and apply only into the originating document."""
                if len(self.cache) >= 4:
                    self.cache.pop(next(iter(self.cache)))
                self.cache[entry.path] = result[1], {}
                apply()

            self.model.background(lambda: read_pack(entry.path), loaded)

    def clear(self) -> None:
        """Release scratch state while retaining only the bounded reusable pack cache."""
        self.generation += 1
        self.preparing = self.preview_base = self.scene_work = None
        self.hover = self.preview_key = self.document = None
        self.timer.stop()
        self.window.viewport.drop_pose = None
        self.window.viewport.drop_translation = QPointF()
        self.window.viewport.drop_message = ""
        self.window.viewport.update()

    def load(self, entry: Any) -> None:
        """Read and decode original pack images on the existing serialized worker pool."""
        if entry.path in self.loading:
            return
        self.loading.add(entry.path)

        def read() -> tuple[dict[str, bytes], dict[str, Any]]:
            """Decode referenced artwork independently of main-window image ownership."""
            pack, files = read_pack(entry.path)
            names = set()
            item = entry.item
            if item.kind == "artwork":
                names.add(item.payload["source"])
            elif item.kind == "scene":
                names.update(item.payload.get("sources", {}).values())
            return files, {
                name: decode_artwork(files[name], 512)
                for name in names
                if str(name).lower().endswith((".png", ".jpg", ".jpeg", ".svg"))
            }

        def complete(result: Any) -> None:
            """Adopt media on the GUI thread, then resume only the latest hover or drop."""
            self.loading.discard(entry.path)
            if self.window._closed:
                return
            if len(self.cache) >= 4:
                self.cache.pop(next(iter(self.cache)))
            self.cache[entry.path] = result
            pending = self.pending
            self.pending = None
            if pending:
                key, point, document, project, scene_id = pending
                if (
                    document is not None
                    and document.project is project
                    and document.scene.id == scene_id
                    and self.model.document is document
                ):
                    self.drop(key, point)
            elif self.hover:
                self.move(*self.hover)

        def failed(message: str) -> None:
            """Allow a failed or cancelled pack load to be retried normally."""
            self.loading.discard(entry.path)
            self.pending = None
            self.window.viewport.drop_message = message
            self.window.viewport.update()

        self.model.background(read, complete, failed=failed)

    def targets(self, point: QPointF) -> tuple[str, str, str]:
        """Resolve the unlocked artwork or rig under the pointer, without selection guesses."""
        key = self.window.scene_workspace.pick(point)
        doc = self.model.document
        if doc is None or doc.project is None:
            return "", "", ""
        if not key and self.window.object_edit.active:
            key = doc.animation_context or ""
        from rigora.application_services.characters import CharacterService
        from rigora.domain.entities import SceneObject

        characters = CharacterService(doc)
        root = characters.object_root(key)
        object_id = (
            root.id
            if root
            else key
            if isinstance(characters.records().get(key), SceneObject)
            else ""
        )
        scene = doc.scene
        rig = next((r.id for r in scene.skeletons if any(b.id == key for b in r.bones)), "")
        if object_id and not rig:
            members = characters.members(object_id)
            candidates = [r.id for r in scene.skeletons if r.id in members]
            rig = candidates[0] if len(candidates) == 1 else ""
        mesh = self.window.scene_workspace.mesh_at(point, object_id=key) if key else ""
        if not mesh:
            mesh = self.window.scene_workspace.mesh_at(point)
        if mesh and not rig:
            character = next((c for c in scene.characters if key in c.object_ids), None)
            if character:
                rig = character.skeleton_id or ""
            else:
                influences = {
                    bone
                    for stage in scene.deformers
                    if stage.owner_id == mesh and stage.kind == "skinning"
                    for bone in stage.parameters.get("bind_matrices", {})
                }
                candidates = [
                    r.id for r in scene.skeletons if any(b.id in influences for b in r.bones)
                ]
                rig = candidates[0] if len(candidates) == 1 else ""
        return rig, mesh, object_id

    def move(self, key: str, point: QPointF) -> None:
        """Show translucent content at its actual drop location or an actionable target hint."""
        self.hover = key, QPointF(point)
        entry = self.model.entry(key)
        doc, viewport = self.model.document, self.window.viewport
        if entry is None or doc is None or doc.project is None:
            return
        if entry.path not in self.cache:
            viewport.drop_message = "Loading template preview…"
            self.load(entry)
            viewport.update()
            return
        if entry.item.kind == "scene":
            self.move_scene(entry, doc, point)
            return
        target, mesh, object_id = self.targets(point)
        if entry.item.kind == "spring":
            picked = self.window.scene_workspace.pick(point)
            if any(b.id == picked for r in doc.scene.skeletons for b in r.bones):
                target = picked
        position = viewport.scene_point(point)
        positioned = entry.item.kind not in ("pose", "action", "deformation", "spring") or (
            not target
            and bool(entry.item.payload.get("fallback_rig"))
            or not mesh
            and bool(entry.item.payload.get("fallback_mesh"))
        )
        viewport.drop_translation = position * viewport.zoom if positioned else QPointF()
        signature = (
            key,
            id(entry.item),
            id(doc.project),
            target,
            mesh,
            object_id,
        )
        if signature == self.preview_key:
            viewport.update()
            return
        self.preview_key = signature
        self.timer.stop()
        viewport.drop_pose = None
        try:
            service = ContentService(doc)
            reason = service.compatibility(entry.item, target, mesh)
            if reason:
                raise ProjectError(f"Drop on a compatible target · {reason}")
            files, images = self.cache[entry.path]
            if positioned:
                # Position through the same canonical operation used on release.
                scratch = doc.fork()
                ContentService(scratch).place(
                    entry.item, files, position=(0, 0), object_id=object_id
                )
            else:
                scratch = service.preview(
                    entry.item,
                    files,
                    target=target,
                    mesh_id=mesh,
                    demonstrate=entry.item.kind == "spring",
                )
            source_ids = set(doc.animation.pose.nodes)
            assert scratch.project is not None
            self.preview_nodes = set(scratch.animation.pose.nodes) - source_ids
            if entry.item.kind == "deformation" and mesh:
                owner = next(m.object_id for m in scratch.scene.meshes if m.id == mesh)
                self.preview_nodes = {owner} if owner else set()
            elif entry.item.kind in ("pose", "action", "spring") and target:
                rig_id = service.skeleton(target).id
                self.preview_nodes = {
                    b.id for r in scratch.scene.skeletons if r.id == rig_id for b in r.bones
                }
                self.preview_nodes.update(
                    o
                    for c in scratch.scene.characters
                    if c.skeleton_id == rig_id
                    for o in c.object_ids
                )
                self.preview_nodes.update(
                    m.object_id
                    for m in scratch.scene.meshes
                    if m.object_id
                    and any(
                        stage.owner_id == m.id
                        and stage.kind == "skinning"
                        and any(
                            b in self.preview_nodes
                            for b in stage.parameters.get("bind_matrices", {})
                        )
                        for stage in scratch.scene.deformers
                    )
                )
            for asset in scratch.project.assets:
                source = next(
                    (name for name in images if files[name] == scratch.read_asset(asset.id)), None
                )
                if source:
                    viewport.artwork.put(asset.id, images[source], files[source])
                elif asset.id not in {a.id for a in doc.project.assets}:
                    data = scratch.read_asset(asset.id)
                    viewport.artwork.put(asset.id, decode_artwork(data, 512), data)
            self.document = scratch
            viewport.drop_message = f"Drop {entry.item.name} · Esc to cancel"
            self.show_pose(scratch.animation.pose)
            if entry.item.kind in ("action", "spring") or "motion" in entry.item.payload:
                scratch.animation.set_loop(True)
                scratch.animation.play()
                self.timer.start()
        except (ProjectError, KeyError, ValueError, TypeError) as error:
            self.document = None
            viewport.drop_message = str(error)
            viewport.update()

    def move_scene(self, entry: Any, doc: DocumentService, point: QPointF) -> None:
        """Queue one scene preparation; pointer movement only changes the display translation."""
        viewport = self.window.viewport
        viewport.drop_translation = viewport.scene_point(point) * viewport.zoom
        signature = (entry.key, id(entry.item), id(doc.project), doc.context_key)
        if signature == self.preview_key or signature == self.preparing:
            viewport.update()
            return
        self.generation += 1
        generation, baseline = self.generation, doc.project
        assert baseline is not None
        ready: list[tuple[DocumentService, str]] = []
        self.scene_work = signature, ready
        self.preparing, self.preview_key, self.document = signature, None, None
        self.timer.stop()
        viewport.drop_pose = None
        viewport.drop_message = (
            "Preparing character preview…"
            if entry.item.category == "Characters"
            else "Preparing template preview…"
        )
        viewport.update()
        snapshot = doc.fork()
        files, images = self.cache[entry.path]
        source_ids = set(doc.animation.pose.nodes)

        def prepare() -> tuple[Any, dict[str, Any]]:
            """Build validated authoring data and image values without touching widgets."""
            placed = ContentService(snapshot).place(entry.item, files, position=(0, 0))
            assert snapshot.project is not None
            sources = {
                hashlib.sha256(data).hexdigest(): name
                for name, data in files.items()
                if name in images
            }
            artwork = {}
            old_assets = {a.id for a in baseline.assets}
            for asset in snapshot.project.assets:
                if asset.id in old_assets or asset.kind not in ("raster", "vector"):
                    continue
                data = snapshot.read_asset(asset.id)
                source = sources.get(asset.sha256 or "")
                image = images[source] if source else decode_artwork(data, 512)
                artwork[asset.id] = image, data
            # Compile and evaluate once on the worker, even when the template has many actions.
            _ = snapshot.animation.pose
            ready.append((snapshot, placed))
            return snapshot, artwork

        def complete(result: tuple[Any, dict[str, Any]]) -> None:
            """Adopt only the latest hover from its exact document and scene revision."""
            if (
                self.window._closed
                or generation != self.generation
                or self.model.document is not doc
                or doc.project is not baseline
                or doc.context_key != signature[3]
            ):
                return
            self.preparing, self.preview_key, self.preview_base = None, signature, baseline
            self.document, artwork = result
            self.preview_nodes = set(self.document.animation.pose.nodes) - source_ids
            for asset, (image, data) in artwork.items():
                viewport.artwork.put(asset, image, data)
            viewport.drop_message = f"Drop {entry.item.name} · Esc to cancel"
            self.show_pose(self.document.animation.pose)
            # No clip means no animation: do not reskin an unchanged character 25 times a second.
            clip = self.document.animation.evaluator.clip
            timeline = next(
                (t for t in self.document.scene.timelines if clip and t.id == clip.timeline_id),
                None,
            )
            if timeline and any(
                t.owner_id in self.preview_nodes and t.keyframes for t in timeline.tracks
            ):
                self.document.animation.set_loop(True)
                self.document.animation.play()
                self.timer.start()

        def failed(message: str) -> None:
            """Release failed preparation so the next drag can retry."""
            if generation == self.generation:
                self.preparing = None
                viewport.drop_message = message
                viewport.update()

        self.model.background(prepare, complete, failed=failed)

    def drop_scene(self, entry: Any, doc: DocumentService, point: QPointF) -> None:
        """Prepare/link a placement off-thread and publish one validated revision on completion."""
        if self.placing:
            self.window.statusBar().showMessage("Finishing template placement…", 3000)
            return
        baseline, context = doc.project, doc.context_key
        assert baseline is not None
        work = self.scene_work
        ready = (
            work[1]
            if work and work[0] == (entry.key, id(entry.item), id(baseline), context)
            else []
        )
        position = self.window.viewport.scene_point(point)
        snapshot = doc.fork()
        snapshot.animation_scope = doc.animation_scope
        files = self.cache[entry.path][0]
        original = {r.id for r in (*doc.scene.objects, *doc.scene.groups)}
        original_records = {r.id for r in nested_records(doc.scene)}
        frame = doc.animation.pose.frame
        scope = doc.animation_scope
        linking = doc._link_objects
        main_scene = not self.window.object_edit.active
        zoom, offset = self.window.viewport.zoom, QPointF(self.window.viewport.offset)
        self.clear()
        self.placing = True
        self.window.viewport.drop_message = "Placing template…"
        self.window.viewport.update()

        def prepare() -> tuple[Any, str]:
            """Reuse the hover graph and link the result before returning to the UI."""
            nonlocal snapshot
            reuse = ready[0] if ready else None
            if reuse:
                snapshot = reuse[0].fork()
                snapshot.animation_scope = scope
            service = ContentService(snapshot)
            if reuse:
                with snapshot.command_group(f"Place {entry.item.name}"):
                    service.position_created(
                        entry.item, original_records, (position.x(), position.y())
                    )
                result = reuse[1]
            else:
                result = service.place(entry.item, files, position=(position.x(), position.y()))
            if linking:
                from rigora.application_services.object_library import synchronize_objects

                assert snapshot.project is not None
                snapshot.project = synchronize_objects(baseline, snapshot.project)
            snapshot._link_objects = linking
            snapshot.animation.pause()
            snapshot.animation.seek(frame)
            return snapshot, result

        def complete(result: tuple[Any, str]) -> None:
            """Commit only into the original, unmodified document and retain ordinary Undo."""
            self.placing = False
            if self.window._closed:
                return
            self.window.viewport.drop_message = ""
            try:
                if self.model.document is not doc or doc.context_key != context:
                    raise ProjectError("Placement cancelled because the active scene changed.")
                snapshot, key = result
                doc.adopt_prepared(snapshot, baseline, f"Place {entry.item.name}")
                self.model.library.used(entry.key)
                self.model.document_changed.emit()
                if main_scene:
                    created = [
                        r for r in (*doc.scene.objects, *doc.scene.groups) if r.id not in original
                    ]
                    ids = {r.id for r in created}
                    self.window.navigate()
                    self.window.scene_workspace.select_entries(
                        tuple(r.id for r in created if getattr(r, "parent_id", None) not in ids)
                    )
                    if entry.item.kind in ("rig", "action", "spring"):
                        self.window.viewport.show_bones = True
                else:
                    self.model.applied.emit(entry.item.kind, key)
                self.window.viewport.zoom, self.window.viewport.offset = zoom, offset
                self.window.viewport.update()
                self.model.error = ""
            except ProjectError as error:
                self.model.error = str(error)
                self.window.statusBar().showMessage(str(error), 6000)
            self.model.changed.emit()

        def failed(message: str) -> None:
            """Leave the original project untouched after preparation failure."""
            self.placing = False
            self.window.viewport.drop_message = message
            self.window.viewport.update()

        self.model.background(prepare, complete, failed=failed)

    def show_pose(self, pose: Any) -> None:
        """Display only prospective nodes so existing scene content is not duplicated."""
        self.window.viewport.drop_pose = replace(
            pose,
            nodes={k: n for k, n in pose.nodes.items() if k in self.preview_nodes},
            meshes={k: m for k, m in pose.meshes.items() if m.object_id in self.preview_nodes},
            render_order=tuple(k for k in pose.render_order if k in self.preview_nodes),
        )
        self.window.viewport.update()

    def tick(self) -> None:
        """Animate the translucent scratch result independently of the source playhead."""
        if self.document:
            self.show_pose(self.document.animation.advance(0.04))

    def drop(self, key: str, point: QPointF) -> None:
        """Validate current targets and publish exactly one positioned template command."""
        entry = self.model.entry(key)
        doc = self.model.document
        if entry is None or doc is None or doc.project is None:
            self.clear()
            return
        if entry.path not in self.cache:
            self.pending = key, QPointF(point), doc, doc.project, doc.scene.id
            self.load(entry)
            self.clear()
            return
        if entry.item.kind == "scene":
            self.drop_scene(entry, doc, point)
            return
        target, mesh, object_id = self.targets(point)
        if entry.item.kind == "spring":
            picked = self.window.scene_workspace.pick(point)
            if any(b.id == picked for r in doc.scene.skeletons for b in r.bones):
                target = picked
        position = self.window.viewport.scene_point(point)
        zoom, offset = self.window.viewport.zoom, QPointF(self.window.viewport.offset)
        main_scene = not self.window.object_edit.active
        existing = {r.id for r in (*doc.scene.objects, *doc.scene.groups)}
        self.clear()
        try:
            result = ContentService(doc).place(
                entry.item,
                self.cache[entry.path][0],
                target=target,
                mesh_id=mesh,
                position=(position.x(), position.y()),
                object_id=object_id,
            )
            self.model.library.used(key)
            self.model.document_changed.emit()
            if main_scene and any(
                r.id not in existing for r in (*doc.scene.objects, *doc.scene.groups)
            ):
                created = [
                    r for r in (*doc.scene.objects, *doc.scene.groups) if r.id not in existing
                ]
                ids = {r.id for r in created}
                self.window.navigate()
                roots = tuple(r.id for r in created if getattr(r, "parent_id", None) not in ids)
                if entry.item.kind == "rig":
                    from rigora.application_services.characters import CharacterService

                    owner = CharacterService(doc).object_root(result)
                    roots = (owner.id,) if owner else roots
                self.window.scene_workspace.select_entries(roots)
                if entry.item.kind in ("rig", "action", "spring"):
                    self.window.viewport.show_bones = True
            else:
                self.model.applied.emit(entry.item.kind, result)
            self.window.viewport.zoom, self.window.viewport.offset = zoom, offset
            self.window.viewport.update()
            self.model.error = ""
        except (ProjectError, KeyError, TypeError, ValueError) as error:
            self.model.error = str(error)
            self.window.statusBar().showMessage(str(error), 6000)
        self.model.changed.emit()
