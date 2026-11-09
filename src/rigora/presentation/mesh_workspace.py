"""Coordinate asynchronous artwork import and mesh editor widgets across project tabs."""

from collections import OrderedDict
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, QPointF, Qt, QThreadPool, Slot
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QMessageBox, QScrollArea

from rigora.application_services.deformation_examples import populate_deformation_example
from rigora.application_services.documents import DocumentService
from rigora.application_services.meshes import MeshService
from rigora.domain.entities import Asset
from rigora.domain.project import Project, ProjectError
from rigora.presentation.artwork import ArtworkCache, ArtworkJob
from rigora.presentation.mesh_interaction import MeshInteraction
from rigora.presentation.viewmodels.content_library import LibraryJob
from rigora.presentation.widgets.file_dialogs import choose_open_file, choose_save_file
from rigora.presentation.widgets.message_dialogs import ask_question

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


@dataclass
class _DocumentArtwork:
    """Own decoded sources and their descriptors for one open document session."""

    cache: ArtworkCache = field(default_factory=ArtworkCache)
    assets: dict[str, Asset] = field(default_factory=dict)
    path: Path | None = None


class MeshWorkspace(QObject):
    """Connect the mesh ViewModel to the shell without putting editing rules into the window."""

    def __init__(self, window: "MainWindow") -> None:
        """Bind inspector commands, worker results and the active viewport once."""
        super().__init__(window)
        self.window = window
        self.jobs: dict[
            str, tuple[ArtworkJob, DocumentService, Project, str, bool, Path | None]
        ] = {}
        self.failed: set[tuple[str, str]] = set()
        self.document: DocumentService | None = None
        self.subdivision_job: LibraryJob | None = None
        self.subdivision_source: tuple[DocumentService, Project | None] | None = None
        self.artwork_tabs: OrderedDict[str, _DocumentArtwork] = OrderedDict()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        panel, model = window.mesh_panel, window.viewmodel.mesh
        self.interaction = MeshInteraction(window.viewport, model, panel)
        self.interaction.pin_pick = self.pin_artwork
        panel.import_requested.connect(self.import_artwork)
        panel.regenerate_requested.connect(self.regenerate)
        panel.export_requested.connect(self.export_clip)
        panel.reuse_requested.connect(self.reuse_clip)
        panel.mode_changed.connect(self.set_mode)
        panel.frame_requested.connect(self.frame_artwork)
        panel.share_ffd_requested.connect(self.share_ffd)
        panel.example_requested.connect(self.example)
        model.changed.connect(self.refresh)
        window.viewmodel.changed.connect(self.load_assets)

    def pin_artwork(self, point: QPointF) -> str:
        """Pick painted artwork beneath bone controls without using object selection filters.

        A missed click must not fall back to the previously selected part, whose
        mesh may cover transparent or locked regions of the intended target.
        Binding validation remains owned by the shared skinning service.
        """
        key = self.window.scene_workspace.mesh_at(point)
        if not key:
            raise ProjectError("Click visible, unlocked artwork to place a pin.")
        return key

    def set_mode(self, enabled: bool) -> None:
        """Enter mesh editing with paused playback and leave rest-rig mode."""
        vm = self.window.viewmodel
        if enabled:
            self.window.ensure_object_editor(vm.mesh.mesh_id or None)
            vm.rig.active = False
        vm.mesh.active = enabled
        self.window.set_viewport_wireframe(False)
        vm.mesh.cancel_preview()
        if enabled:
            self.window.command_actions["navigate"].setChecked(True)
            self.window.toggle_pan()
            vm.playback.pause()
            vm.rig.changed.emit()
            self.window.inspector.setCurrentWidget(self.window.mesh_panel)
            dock = self.window.docks["inspector"]
            revealing = dock.isHidden()
            dock.show()
            if revealing and not dock.isFloating():
                # A newly revealed dock otherwise inherits the minimum height,
                # leaving the scrollable tools almost completely clipped.
                # Qt bounds this request against the other panels' minima.
                self.window.resizeDocks([dock], [560], Qt.Orientation.Vertical)
            dock.raise_()
        self.refresh()

    def activate_tool(self, tool: str) -> None:
        """Open the mesh inspector and choose an available viewport authoring tool."""
        self.set_mode(True)
        panel = self.window.mesh_panel
        panel.tools.setCurrentIndex(panel.tools.findData(tool))
        panel.tabs.setCurrentIndex(2 if tool == "paint" else 1 if tool == "control" else 0)
        page = panel.tabs.currentWidget()
        if isinstance(page, QScrollArea):
            page.verticalScrollBar().setValue(0)

    def share_ffd(self) -> None:
        """Export selected normalized controls and keys as an installable original content pack."""
        model = self.window.viewmodel.mesh
        if not model.document or not model.stage_id:
            self.window.statusBar().showMessage(
                "Select an FFD stage to share its shape or motion.", 8000
            )
            return
        filename, _ = choose_save_file(
            self.window, "Share FFD shape / motion", "My FFD.rigpack", "Rigora packs (*.rigpack)"
        )
        if filename:
            from rigora.application_services.ffd_motion import FfdMotionService

            try:
                FfdMotionService(model.document).export(
                    Path(filename),
                    model.stage_id,
                    Path(filename).stem,
                    "eManF",
                    "All rights reserved",
                )
                self.window.statusBar().showMessage(
                    "FFD pack saved · Install it from the content browser", 8000
                )
            except ProjectError as error:
                self.window.statusBar().showMessage(str(error), 10000)

    def frame_artwork(self) -> None:
        """Fit evaluated artwork bounds without modifying the canvas or authored transforms."""
        from rigora.application_services.skinning import SkinService

        model, viewport = self.window.viewmodel.mesh, self.window.viewport
        mesh, pose = model.mesh, model.pose
        if mesh is None or pose is None or not mesh.vertices:
            return
        points = tuple(SkinService.positions(mesh, pose).values())
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
        viewport.zoom_changed.emit(viewport.zoom)
        viewport.update()

    def refresh(self) -> None:
        """Update transient geometry and action state without rebuilding the entire window."""
        window, model = self.window, self.window.viewmodel.mesh
        if model.active and window.viewmodel.rig.active:
            model.active = False
        if model.active:
            try:
                window.viewport.set_pose(model.pose)
            except ProjectError as error:
                model.error = str(error)
            window.viewport.scene_hint = (
                "MESH EDIT  ·  Ctrl: extend selection · Esc: cancel · Delete: remove"
            )
        window.update_animation()
        window.viewport.update()

    def submit(self, job: ArtworkJob, name: str, importing: bool) -> None:
        """Retain request ownership so stale completions cannot mutate a different project."""
        document = self.window.viewmodel.documents
        if document.project is None:
            return
        self.jobs[job.token] = job, document, document.project, name, importing, document.path
        job.signals.finished.connect(self.complete, Qt.ConnectionType.QueuedConnection)
        self.pool.start(job)

    def import_artwork(self) -> None:
        """Choose a supported image and fully decode it before embedding or editing the document."""
        if self.window.viewmodel.documents.project is None:
            self.window.viewmodel.new_project()
        path, _ = choose_open_file(
            self.window, "Import artwork", "", "Artwork (*.png *.jpg *.jpeg *.svg)"
        )
        if path:
            source = Path(path)
            self.window.statusBar().showMessage("Decoding artwork…")
            self.submit(
                ArtworkJob(lambda: DocumentService._read_asset_file(source)), source.name, True
            )

    @Slot(str, object, object, str)
    def complete(self, token: str, data: Any, image: Any, error: str) -> None:
        """Publish worker results on the GUI thread for their original document."""
        request = self.jobs.pop(token, None)
        if request is None or self.window._closed:
            return
        _, document, project, name, importing, source_path = request
        current = self.window.viewmodel.documents
        if document.project is None or document not in self.window.viewmodel.workspace.documents:
            self.load_assets()
            return
        original = next((a for a in project.assets if a.id == name), None)
        current_asset = next((a for a in document.project.assets if a.id == name), None)
        if not importing and (
            original is None
            or original != current_asset
            or original.storage == "external"
            and source_path != document.path
        ):
            self.load_assets()
            return
        if document is not current:
            # Passive decodes can finish for their owning tab without touching active widgets.
            state = self.artwork_tabs.get(document.session_id)
            if (
                not importing
                and not error
                and state is not None
                and original is not None
                and state.assets.get(name) == original
                and isinstance(image, QImage)
                and isinstance(data, bytes)
            ):
                state.cache.put(name, image, data)
                self.trim_artwork_tabs()
            self.load_assets()
            return
        model = self.window.viewmodel.mesh
        if importing and document.project is not project:
            model.error = (
                "Artwork import cancelled because the project changed while decoding. Import again."
            )
            model.changed.emit()
            self.load_assets()
            return
        if error:
            self.failed.add((document.session_id, name))
            model.error = f"Artwork unavailable: {error}"
            model.changed.emit()
            self.window.statusBar().showMessage(model.error, 15000)
            self.load_assets()
            return
        if not isinstance(image, QImage) or not isinstance(data, bytes):
            return
        if importing:

            def publish(service: Any) -> None:
                """Embed original bytes through the same application service used by headless
                clients.
                """
                asset_id = service.register_image_bytes(name, data)
                self.window.viewport.artwork.adapt(
                    len({m.asset_id for m in service.scene.meshes if m.asset_id})
                )
                self.window.viewport.artwork.put(asset_id, image, data)

            model.run(publish)
            if model.error:
                self.window.statusBar().showMessage(model.error, 15000)
                return
            self.set_mode(False)
            self.window.library_tabs.setCurrentWidget(self.window.project_assets_page)
            self.window.docks["assets"].raise_()
            self.window.command_actions["navigate"].setChecked(True)
            self.window.viewport.pan_tool = False
        else:
            self.window.viewport.artwork.put(name, image, data)
        self.window.refresh_asset_thumbnails(None if importing else {name})
        self.window.viewport.update()
        self.window.statusBar().showMessage("Artwork ready", 4000)
        self.load_assets()

    def load_assets(self) -> None:
        """Reuse bounded per-tab sources and decode only missing or changed descriptors."""
        if self.window._closed:
            return
        document = self.window.viewmodel.documents
        if self.document is not document:
            self.document = document
            state = self.artwork_tabs.setdefault(document.session_id, _DocumentArtwork())
            self.window.viewport.artwork = state.cache
        if document.project is None:
            self.trim_artwork_tabs()
            return
        state = self.artwork_tabs.setdefault(document.session_id, _DocumentArtwork())
        self.window.viewport.artwork = state.cache
        assets = {asset.id: asset for asset in document.project.assets}
        for key in set(state.assets) | set(assets):
            asset = assets.get(key)
            if (
                asset != state.assets.get(key)
                or asset is not None
                and asset.storage == "external"
                and state.path != document.path
            ):
                state.cache.images.pop(key, None)
                state.cache.vectors.pop(key, None)
                state.cache.originals.pop(key, None)
                for identity in tuple(state.cache.looks):
                    if identity[0] == key:
                        del state.cache.looks[identity]
                self.failed.discard((document.session_id, key))
        state.assets, state.path = assets, document.path
        self.artwork_tabs.move_to_end(document.session_id)
        placed = {m.asset_id for m in document.scene.meshes}
        used = set(placed)
        used.update(
            a.id
            for a in document.project.assets
            if a.kind in ("raster", "vector") and a.media_type.startswith("image/")
        )
        used.update(
            key
            for mesh in document.scene.meshes
            for key in mesh.extra.get("sprite_sequence", {}).get("assets", ())
        )
        for key in set(self.window.viewport.artwork.images) - used:
            self.window.viewport.artwork.images.pop(key)
        for key in set(self.window.viewport.artwork.vectors) - used:
            self.window.viewport.artwork.vectors.pop(key)
        self.window.viewport.artwork.adapt(len(used))
        pending = {
            (d.session_id, key)
            for _, d, _, key, importing, _ in self.jobs.values()
            if not importing
        }
        for asset in sorted(document.project.assets, key=lambda a: a.id not in placed):
            # Keep only two passive decodes in flight, so a new tab takes priority as
            # soon as a worker is free instead of waiting behind an inactive asset queue.
            if len(self.jobs) >= self.pool.maxThreadCount():
                break
            if (
                asset.id in used
                and self.window.viewport.artwork.get(asset.id) is None
                and (document.session_id, asset.id) not in self.failed | pending
            ):
                self.submit(
                    ArtworkJob(
                        partial(document.read_asset, asset.id), self.window.viewport.artwork.limit
                    ),
                    asset.id,
                    False,
                )
        self.trim_artwork_tabs()

    def trim_artwork_tabs(self) -> None:
        """Release closed tabs and cap inactive decoded pixels at 64 MiB / three tabs.

        Active artwork keeps its existing 128 MiB raster budget. Evicted tabs retain all
        authored data and decode again on demand; original SVGs remain the render source.
        A renderer-count cap also limits retention for vector-only tab collections.
        """
        open_ids = {doc.session_id for doc in self.window.viewmodel.workspace.documents}
        for key in tuple(self.artwork_tabs):
            if key not in open_ids:
                self.artwork_tabs.pop(key).cache.clear()
        self.failed = {key for key in self.failed if key[0] in open_ids}
        inactive = [
            key
            for key in self.artwork_tabs
            if self.document is None or key != self.document.session_id
        ]
        while inactive and (
            len(inactive) > 3
            or sum(
                image.sizeInBytes()
                for key in inactive
                for image in self.artwork_tabs[key].cache.images.values()
            )
            > 64 * 1024**2
            or sum(len(self.artwork_tabs[key].cache.vectors) for key in inactive) > 256
        ):
            self.artwork_tabs.pop(inactive.pop(0)).cache.clear()

    def shutdown(self) -> None:
        """Finish active decodes before GUI signal owners and native image caches are destroyed."""
        self.pool.clear()
        self.pool.waitForDone()
        if self.subdivision_job:
            self.subdivision_job.signals.done.disconnect(self.finish_subdivision)
            self.subdivision_job.signals.failed.disconnect(self.fail_subdivision)
            self.subdivision_job.signals.progress.disconnect()
            self.subdivision_job, self.subdivision_source = None, None
        for job, *_ in self.jobs.values():
            job.signals.finished.disconnect()
        self.jobs.clear()
        for state in self.artwork_tabs.values():
            state.cache.clear()
        self.artwork_tabs.clear()

    def regenerate(self) -> None:
        """Prepare shared Full/Mask/Grid topology off-thread after explicit replacement consent."""
        panel, model = self.window.mesh_panel, self.window.viewmodel.mesh
        if not model.document or not model.mesh or self.subdivision_job is not None:
            return
        answer = ask_question(
            self.window,
            "Regenerate mesh?",
            "Replace this mesh's topology, vertex keys and geometric deformers? "
            "Bone bindings and original artwork are preserved. Undo restores the previous mesh.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        document, baseline = model.document, model.document.project
        scratch = document.fork()
        key, mode = model.mesh_id, panel.division.currentData()
        density, alignment, expand = (
            panel.density.value(),
            panel.alignment.value(),
            panel.expand.value(),
        )

        def prepare() -> DocumentService:
            """Build topology without mutating the source document or Qt widgets."""
            MeshService(scratch).subdivide(
                (key,),
                mode=mode,
                density=density,
                alignment=alignment,
                expand=expand,
                discard_edits=True,
                progress=lambda value: job.deliver("progress", value),
            )
            return scratch

        job = LibraryJob(prepare)
        self.subdivision_job = job
        self.subdivision_source = document, baseline
        job.signals.done.connect(self.finish_subdivision)
        job.signals.failed.connect(self.fail_subdivision)
        job.signals.progress.connect(panel.subdivision_progress.setValue)
        panel.subdivide_button.setEnabled(False)
        panel.subdivision_progress.setValue(0)
        panel.subdivision_progress.show()
        self.pool.start(job)

    @Slot(object)
    def finish_subdivision(self, scratch: DocumentService) -> None:
        """Publish one undo step only while the originating tab/revision remains current."""
        source = self.subdivision_source
        self.subdivision_job, self.subdivision_source = None, None
        if self.window._closed:
            return
        panel, model = self.window.mesh_panel, self.window.viewmodel.mesh
        panel.subdivide_button.setEnabled(True)
        panel.subdivision_progress.hide()
        if not source or model.document is not source[0] or source[0].project is not source[1]:
            self.window.statusBar().showMessage(
                "Subdivision discarded because the project changed.", 5000
            )
            return
        assert scratch.project is not None
        scene = scratch.scene
        model.run(
            lambda s: s.commit(
                "Subdivide artwork",
                meshes=scene.meshes,
                deformers=scene.deformers,
                timelines=scene.timelines,
            )
        )

    @Slot(str)
    def fail_subdivision(self, error: str) -> None:
        """Restore controls and retain worker diagnostics without changing any document."""
        source = self.subdivision_source
        self.subdivision_job, self.subdivision_source = None, None
        if self.window._closed:
            return
        panel, model = self.window.mesh_panel, self.window.viewmodel.mesh
        panel.subdivide_button.setEnabled(True)
        panel.subdivision_progress.hide()
        if source and model.document is source[0]:
            model.error = error
            model.changed.emit()

    def export_clip(self) -> None:
        """Save a reusable geometric motion bundle with an explicit overwrite guard."""
        path, _ = choose_save_file(
            self.window,
            "Export deformation clip",
            "deformation.rigmotion",
            "Rigora deformation (*.rigmotion)",
        )
        if not path:
            return
        target = Path(path)
        overwrite = False
        if target.exists():
            overwrite = (
                ask_question(
                    self.window,
                    "Replace motion clip?",
                    f"Replace {target.name}?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel,
                )
                == QMessageBox.StandardButton.Yes
            )
            if not overwrite:
                return
        model = self.window.viewmodel.mesh
        model.run(lambda s: s.export_clip(model.stage_id, target, overwrite=overwrite))

    def reuse_clip(self) -> None:
        """Load a compatible motion bundle as a new stage/clip without replacing existing motion."""
        path, _ = choose_open_file(
            self.window, "Reuse deformation clip", "", "Rigora deformation (*.rigmotion)"
        )
        if path:
            model = self.window.viewmodel.mesh

            def reuse(service: Any) -> None:
                """Select the newly remapped stage and common animation clip."""
                model.stage_id, _ = service.import_clip(model.mesh_id, Path(path))

            model.run(reuse)

    def example(self, style: str = "Bending") -> None:
        """Create an independent editable study tab using original bundled artwork."""
        vm = self.window.viewmodel
        document = vm.workspace.new(style)
        vm.welcome_selected = False
        vm.welcome_open = False
        key = populate_deformation_example(document, style)
        vm.changed.emit()
        vm.mesh.mesh_id = key
        vm.mesh.stage_id = (
            next((d.id for d in document.scene.deformers if d.kind != "skinning"), "")
            if document.project
            else ""
        )
        vm.mesh.changed.emit()
        self.set_mode(True)
