"""Reusable Object cards, scene/library clipboard commands and focused keyboard routing."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from PySide6.QtCore import (
    QBuffer,
    QByteArray,
    QEvent,
    QIODevice,
    QMimeData,
    QObject,
    QPointF,
    Qt,
    QThreadPool,
    QTimer,
)
from PySide6.QtGui import (
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QIcon,
    QImage,
    QImageWriter,
    QKeyEvent,
    QKeySequence,
    QPainter,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import QApplication, QListWidgetItem, QMenu, QMessageBox

from rigora.application_services.documents import DocumentService
from rigora.application_services.object_library import ObjectLibraryService
from rigora.domain.geometry import transform_point
from rigora.domain.project import ProjectError, Scene
from rigora.domain.validation import json_copy
from rigora.engine.evaluation import SceneEvaluator
from rigora.presentation.artwork import ArtworkCache, decode_artwork, draw_mesh
from rigora.presentation.bone_shape import BoneShape
from rigora.presentation.menu_labels import menu_text
from rigora.presentation.viewmodels.content_library import LibraryJob
from rigora.presentation.widgets.asset_cards import label_format
from rigora.presentation.widgets.file_dialogs import choose_open_file, choose_save_file
from rigora.presentation.widgets.item_view_state import ItemViewState
from rigora.presentation.widgets.message_dialogs import ask_question
from rigora.presentation.widgets.object_package import ObjectPackageDialog
from rigora.presentation.widgets.scene_tree import ProjectImageList

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow

CLIPBOARD_MIME = "application/x-rigora-authoring-clipboard"


@dataclass
class ObjectDraft:
    """Link an isolated authoring tab to its owning project's saved definition."""

    owner: DocumentService
    key: str
    root: str
    expected: Mapping[str, Any]
    revision: object


def object_thumbnail(document: DocumentService, definition: Mapping[str, Any]) -> QImage:
    """Paint a saved Object's default contents on a worker using original source artwork.

    The caller supplies an isolated document snapshot for asset reads. Scene cameras,
    placement overrides and the active editor's transport never affect the poster.
    """
    scene = Scene.from_dict({**json_copy(definition["scene"]), "id": str(uuid4())})
    pose = (
        SceneEvaluator(
            scene,
            solvers=document.constraint_solvers,
            deformers=document.deformer_solvers,
            samplers=document.track_samplers,
            select_first_clip=False,
        )
        .evaluate(0)
        .for_display()
    )
    order = {key: i for i, key in enumerate(pose.render_order)}
    meshes = []
    for mesh in sorted(pose.meshes.values(), key=lambda m: order.get(m.object_id or "", 0)):
        node = pose.nodes.get(mesh.object_id or "")
        if node is not None and node.visible and node.opacity > 0 and mesh.asset_id:
            points = tuple(QPointF(*transform_point(node.world_matrix, *p)) for p in mesh.positions)
            meshes.append((mesh, node.opacity, points))
    bones = (
        []
        if meshes
        else [
            tuple(QPointF(*transform_point(node.world_matrix, x, 0)) for x in (0, node.length))
            for node in pose.nodes.values()
            if node.kind == "bone" and node.visible
        ]
    )
    bounds = QPolygonF(
        [p for _, _, points in meshes for p in points] or [p for bone in bones for p in bone]
    ).boundingRect()
    if bones:
        bounds = bounds.adjusted(-8, -8, 8, 8)
    if bounds.isEmpty():
        return QImage()
    scale = 84 / max(bounds.width(), bounds.height())
    offset = QPointF(48, 48) - bounds.center() * scale
    image = QImage(96, 96, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    cache = ArtworkCache()
    cache.adapt(len({mesh.asset_id for mesh, _, _ in meshes}))
    painter = QPainter(image)
    try:
        for mesh, opacity, points in meshes:
            key = str(mesh.asset_id)
            if cache.get(key) is None:
                data = document.read_asset(key)
                cache.put(key, decode_artwork(data, preview_limit=96), data)
            source = cache.styled(key, mesh.appearance)
            if source is not None:
                painter.setOpacity(opacity)
                draw_mesh(painter, mesh, tuple(p * scale + offset for p in points), source)
        if bones:
            shape = BoneShape()
            for root, tip in bones:
                shape.draw(painter, root * scale + offset, tip * scale + offset, "#a8a9ad")
    finally:
        painter.end()
    return image


class ObjectAssetsWorkspace(QObject):
    """Keep library controls thin; the Qt-free service owns all persistent edits."""

    def __init__(self, window: "MainWindow") -> None:
        """Create the Objects tab and attach keyboard routes only to authoring surfaces."""
        super().__init__(window)
        self.window = window
        self.cards = ProjectImageList()
        self.cards.set_empty_action(
            "Your reusable objects",
            "Create an object, or drag one here from Scene to reuse it.",
            "Create empty object",
            window.command_actions["new_object"],
        )
        self.cards.setSelectionMode(self.cards.SelectionMode.ExtendedSelection)
        self.cards.setToolTip(
            "Objects share artwork, rigs, clothing and actions. Each placement keeps its "
            "transform, visibility and opacity. Drag an Object from Scene here to save it; "
            "double-click a card to edit it. Use Add to Scene or drag to place a copy."
        )
        self.cards.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.cards.customContextMenuRequested.connect(self.context_menu)
        self.cards.itemDoubleClicked.connect(
            lambda item: self.edit(str(item.data(Qt.ItemDataRole.UserRole))[7:])
        )
        self.cards.drag_finished.connect(window.clear_asset_preview)
        self.card_viewport = self.cards.viewport()
        self.card_viewport.installEventFilter(self)
        for widget in (window.tree, window.viewport, self.cards):
            widget.installEventFilter(self)
        self._revision: Any = None
        self._thumbnail_inputs: dict[str, tuple[Any, ...]] = {}
        self._thumbnails: dict[str, tuple[tuple[Any, ...], QIcon]] = {}
        self._thumbnail_job: LibraryJob | None = None
        self._thumbnail_pool = QThreadPool(self)
        self._thumbnail_pool.setMaxThreadCount(1)
        self._thumbnail_timer = QTimer(self)
        self._thumbnail_timer.setSingleShot(True)
        self._thumbnail_timer.setInterval(150)
        self._thumbnail_timer.timeout.connect(self.load_thumbnail)
        self._drafts: dict[DocumentService, ObjectDraft] = {}
        self._card_states: dict[str, ItemViewState] = {}
        self._thumbnail_tabs: dict[str, dict[str, tuple[tuple[Any, ...], QIcon]]] = {}
        window.viewmodel.changed.connect(self.sync_drafts)

    def sync_drafts(self) -> None:
        """Publish completed asset edits before views refresh; keep failed drafts recoverable."""
        vm = self.window.viewmodel
        for snapshot, draft in tuple(self._drafts.items()):
            if snapshot not in vm.workspace.documents:
                del self._drafts[snapshot]
                continue
            if draft.owner not in vm.workspace.documents:
                snapshot._saved = None
                del self._drafts[snapshot]
                continue
            if snapshot.project is draft.revision:
                continue
            try:
                draft.expected = ObjectLibraryService(draft.owner).publish_snapshot(
                    draft.key, snapshot, draft.expected
                )
            except ProjectError as error:
                self.window.statusBar().showMessage(str(error), 8000)
            else:
                draft.revision = snapshot.project
                snapshot._saved = snapshot.project

    def persistence_document(self, document: DocumentService) -> DocumentService:
        """Save the owning project when an isolated Object authoring tab has focus."""
        self.sync_drafts()
        draft = self._drafts.get(document)
        if draft is not None:
            if document.dirty:
                raise ProjectError("Resolve the saved Object conflict before saving its project.")
            return draft.owner
        return document

    def edit(self, key: str | None = None) -> None:
        """Open a saved definition in Object Editor, including assets with no placed instances."""
        vm = self.window.viewmodel
        selected = self.selected_definitions()
        key = key or (selected[0] if len(selected) == 1 else None)
        if key is None:
            return
        try:
            owner = self.persistence_document(vm.documents)
            self.window.object_edit.exit()
            existing = next(
                (
                    (doc, state)
                    for doc, state in self._drafts.items()
                    if state.owner is owner and state.key == key
                ),
                None,
            )
            if existing:
                snapshot, draft = existing
            else:
                snapshot, root = ObjectLibraryService(owner).edit_snapshot(key)
                draft = ObjectDraft(
                    owner, key, root, ObjectLibraryService(owner).entries()[key], snapshot.project
                )
                self._drafts[snapshot] = draft
                vm.workspace.adopt(snapshot)
            vm.activate_project(vm.workspace.documents.index(snapshot))
            self.window.object_edit.enter(draft.root)
        except ProjectError as error:
            self.window.statusBar().showMessage(str(error), 8000)

    def return_to_project(self) -> None:
        """Close a published Object tab on Back and restore its owning scene document."""
        vm = self.window.viewmodel
        snapshot = vm.documents
        self.sync_drafts()
        draft = self._drafts.get(snapshot)
        if draft is None or snapshot.dirty:
            return
        self.window.object_edit.exit()
        del self._drafts[snapshot]
        vm.workspace.close(vm.workspace.documents.index(snapshot), discard=True)
        vm.activate_project(vm.workspace.documents.index(draft.owner))

    def add_to_scene(self) -> None:
        """Place selected definitions in the owning scene without treating them as editor parts."""
        keys = self.selected_definitions()
        self.return_to_project()
        self.window.object_edit.exit()
        doc = self.window.viewmodel.documents
        with doc.command_group("Add saved Objects to Scene"):
            for key in keys:
                self.window.drop_project_asset("object:" + key, doc.session_id)

    def import_objects(self, entry: Any = None) -> None:
        """Import a chosen package or catalog item into Objects on a worker, without placement."""
        from rigora.infrastructure.content_packs import read_pack

        if entry is None:
            filename, _ = choose_open_file(
                self.window, "Import Object Package", "", "Rigora Object packages (*.rigpack)"
            )
            if not filename:
                return
            path = Path(filename)
        else:
            path = entry.path
        self.return_to_project()
        vm = self.window.viewmodel
        doc, baseline = vm.documents, vm.documents.project
        if baseline is None:
            vm.new_project()
            doc, baseline = vm.documents, vm.documents.project
        snapshot = doc.fork()
        assert baseline is not None
        snapshot._link_objects = doc._link_objects

        def prepare() -> tuple[DocumentService, tuple[str, ...]]:
            """Validate all source bytes and construct saved definitions off the UI thread."""
            library = ObjectLibraryService(snapshot)
            if entry is None:
                keys = library.import_package(path)
            else:
                _, files = read_pack(path)
                keys = library.import_content(entry.item, files)
            return snapshot, keys

        def complete(result: tuple[DocumentService, tuple[str, ...]]) -> None:
            """Publish only to the original revision and reveal imported Object cards."""
            try:
                if vm.documents is not doc:
                    raise ProjectError(
                        "Object import cancelled because the active project changed."
                    )
                prepared, keys = result
                doc.adopt_prepared(prepared, baseline, "Import saved Objects")
                vm.changed.emit()
                self.window.library_tabs.setCurrentWidget(self.cards)
                for index in range(self.cards.count()):
                    item = self.cards.item(index)
                    item.setSelected(str(item.data(Qt.ItemDataRole.UserRole))[7:] in keys)
                self.window.statusBar().showMessage(
                    f"Imported {len(keys)} Object(s) into Assets", 6000
                )
            except ProjectError as error:
                self.window.statusBar().showMessage(str(error), 8000)

        vm.content.background(prepare, complete)

    def export_objects(self, *, custom: bool = False) -> None:
        """Export a portable package or install it in the shared Custom Templates library."""
        keys = self.selected_definitions()
        if not keys:
            return
        doc = self.persistence_document(self.window.viewmodel.documents)
        entries = ObjectLibraryService(doc).entries()
        name = entries[keys[0]]["name"] if len(keys) == 1 else f"{len(keys)} Objects"
        icon = (
            self.cards.currentItem().icon()
            if self.cards.currentItem()
            else self.window.icons.icon("widgets")
        )
        categories = tuple(e.item.category for e in self.window.viewmodel.content.entries)
        dialog = ObjectPackageDialog(self.window, name, icon, categories, custom=custom)
        try:
            if not dialog.exec():
                return
            metadata = dict(
                name=dialog.name.text().strip(),
                category=dialog.category.currentText().strip(),
                author=dialog.author.text().strip(),
                license=dialog.license.text().strip(),
            )
        finally:
            dialog.deleteLater()
        path = None
        if not custom:
            filename, _ = choose_save_file(
                self.window,
                "Export Object Package",
                name + ".rigpack",
                "Rigora Object packages (*.rigpack)",
            )
            if not filename:
                return
            path = Path(filename)
            if path.suffix.casefold() != ".rigpack":
                path = path.with_suffix(".rigpack")
        snapshot = doc.fork()
        model = self.window.viewmodel.content

        def write(destination: Path) -> None:
            """Render complete posters and write bounded, data-only package members."""
            thumbnails = {}
            for key in keys:
                image = object_thumbnail(snapshot, entries[key])
                if not image.isNull():
                    buffer = QBuffer()
                    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
                    writer = QImageWriter(buffer, QByteArray(b"png"))
                    if writer.write(image):
                        thumbnails[key] = bytes(buffer.data().data())
            ObjectLibraryService(snapshot).export_package(
                keys, destination, thumbnails=thumbnails, overwrite=destination.exists(), **metadata
            )

        def export() -> str:
            """Keep filesystem I/O and optional global installation off the UI thread."""
            if path is not None:
                write(path)
                return str(path)
            with TemporaryDirectory(prefix="rigora-objects-") as directory:
                package = Path(directory) / "objects.rigpack"
                write(package)
                return model.library.install(package)

        def complete(result: str) -> None:
            """Reveal the shared custom collection only after a complete package is installed."""
            if custom:
                self.window.library_tabs.setCurrentWidget(self.window.content_shelf)
                self.window.content_shelf.show_custom(metadata["category"])
            self.window.statusBar().showMessage(
                "Saved to Custom Templates" if custom else "Exported Object package: " + result,
                8000,
            )

        model.background(export, complete)

    def refresh(self) -> None:
        """Preserve selection/scroll while refreshing only changed library revisions."""
        doc = self.window.viewmodel.documents
        entries = ObjectLibraryService(doc).entries()
        assets = {a.id: a for a in doc.project.assets} if doc.project else {}
        inputs = {}
        for key, entry in entries.items():
            sources = {m.get("asset_id") for m in entry["scene"]["meshes"]}
            sources.update(
                asset
                for mesh in entry["scene"]["meshes"]
                for asset in mesh.get("sprite_sequence", {}).get("assets", ())
            )
            inputs[key] = (
                entry,
                tuple(assets[k] for k in sorted(s for s in sources if s in assets)),
                doc.path,
            )
        signature = (doc.session_id, inputs)
        if self._revision == signature:
            return
        previous_session = self.cards.property("documentSession")
        if previous_session:
            self._card_states[previous_session] = ItemViewState.capture(self.cards)
            self._thumbnail_tabs[previous_session] = self._thumbnails
        state = self._card_states.get(doc.session_id)
        if previous_session != doc.session_id:
            self._thumbnails = self._thumbnail_tabs.get(doc.session_id, {})
        sessions = {d.session_id for d in self.window.viewmodel.workspace.documents}
        self._card_states = {k: v for k, v in self._card_states.items() if k in sessions}
        self._thumbnail_tabs = {k: v for k, v in self._thumbnail_tabs.items() if k in sessions}
        self._thumbnail_inputs = inputs
        self._thumbnails = {k: v for k, v in self._thumbnails.items() if k in inputs}
        self.cards.clear()
        self.cards.setProperty("documentSession", doc.session_id)
        for key, entry in entries.items():
            scene = entry["scene"]
            source = next((o.get("asset_id") for o in scene["objects"] if o.get("asset_id")), None)
            cached = self._thumbnails.get(key)
            icon = (
                cached[1]
                if cached and cached[0] == inputs[key]
                else self.window.icons.icon("widgets")
            )
            item = QListWidgetItem(icon, entry["name"])
            item.setData(Qt.ItemDataRole.UserRole, "object:" + key)
            item.setData(Qt.ItemDataRole.UserRole + 1, source)
            item.setToolTip(entry["name"] + "\nLinked Object · shared contents and actions")
            label_format(item, "OBJECT")
            self.cards.addItem(item)
        if state:
            state.restore(self.cards, selection=True)
        self._revision = signature
        self._thumbnail_timer.start()

    def load_thumbnail(self) -> None:
        """Render one changed definition at a time, coalescing edits and rejecting stale results."""
        if self.window._closed or self._thumbnail_job is not None:
            return
        pending = next(
            (
                (key, value)
                for key, value in self._thumbnail_inputs.items()
                if key not in self._thumbnails or self._thumbnails[key][0] != value
            ),
            None,
        )
        if pending is None:
            return
        key, signature = pending
        doc = self.window.viewmodel.documents
        snapshot, session = doc.fork(), doc.session_id
        job = LibraryJob(lambda: object_thumbnail(snapshot, signature[0]))
        self._thumbnail_job = job
        job.signals.done.connect(partial(self.finish_thumbnail, session, key, signature))
        job.signals.failed.connect(
            lambda error: self.finish_thumbnail(session, key, signature, QImage(), error)
        )
        self._thumbnail_pool.start(job)

    def finish_thumbnail(
        self, session: str, key: str, signature: tuple[Any, ...], image: QImage, error: str = ""
    ) -> None:
        """Publish pixels only for the current document and exact saved-content revision."""
        self._thumbnail_job = None
        if self.window._closed:
            return
        if (
            session == self.window.viewmodel.documents.session_id
            and self._thumbnail_inputs.get(key) == signature
        ):
            icon = (
                QIcon(QPixmap.fromImage(image))
                if not image.isNull()
                else self.window.icons.icon("widgets")
            )
            self._thumbnails[key] = signature, icon
            for index in range(self.cards.count()):
                item = self.cards.item(index)
                if item.data(Qt.ItemDataRole.UserRole) == "object:" + key:
                    item.setIcon(icon)
                    if error:
                        item.setToolTip(item.toolTip() + "\nPreview unavailable: " + error)
                    break
        self._thumbnail_timer.start()

    def shutdown(self) -> None:
        """Stop scheduling posters and finish native image work before window teardown."""
        self._thumbnail_timer.stop()
        self._thumbnail_pool.waitForDone()

    def scene_target(self) -> str | None:
        """Resolve a selected scene header without changing the active scene."""
        items = self.window.tree.selectedItems()
        if len(items) == 1:
            tag = items[0].data(0, Qt.ItemDataRole.UserRole + 5)
            if tag and tag[0] == "scene":
                return str(tag[1])
        return None

    def selected_definitions(self) -> tuple[str, ...]:
        """Read selected saved Object identities from the card model."""
        return tuple(str(i.data(Qt.ItemDataRole.UserRole))[7:] for i in self.cards.selectedItems())

    def save(self, keys: tuple[str, ...] | None = None) -> None:
        """Publish stage objects and reveal their saved cards."""
        model = self.window.viewmodel.scene
        saved: list[str] = []
        model.run(
            lambda s: saved.extend(ObjectLibraryService(s.document).save(keys or model.selected))
        )
        if not model.error:
            self.window.library_tabs.setCurrentWidget(self.cards)
            selected = set(saved)
            for index in range(self.cards.count()):
                item = self.cards.item(index)
                item.setSelected(str(item.data(Qt.ItemDataRole.UserRole))[7:] in selected)

    def payload(self) -> dict[str, Any] | None:
        """Read bounded typed clipboard JSON; preserve the OS clipboard for text editors."""
        data = QApplication.clipboard().mimeData()
        if data is None or not data.hasFormat(CLIPBOARD_MIME):
            return None
        raw = bytes(data.data(CLIPBOARD_MIME).data())
        if len(raw) > 32 * 1024 * 1024:
            raise ProjectError("The clipboard selection is too large.")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ProjectError("Invalid Rigora clipboard data.")
        return value

    def command(self, action: str, *, scene_id: str | None = None, library: bool = False) -> None:
        """Execute shared clipboard commands, publishing only completed, undoable changes."""
        window, doc = self.window, self.window.viewmodel.documents
        if doc.project is None:
            return
        service = ObjectLibraryService(doc)
        try:
            if action == "paste":
                payload = self.payload()
                if payload is None:
                    return
            elif library:
                payload = service.copy_definitions(self.selected_definitions())
            elif scene_id:
                payload = service.copy_scene(scene_id)
            else:
                payload = service.copy_objects(window.viewmodel.scene.selected)
            if action in ("copy", "cut"):
                if action == "cut":
                    if library:
                        service.remove(self.selected_definitions())
                    elif scene_id:
                        self._cut_scene(scene_id)
                    else:
                        from rigora.application_services.scene_editing import SceneEditingService

                        SceneEditingService(doc).delete_entries(window.viewmodel.scene.selected)
                mime = QMimeData()
                mime.setData(CLIPBOARD_MIME, json.dumps(payload).encode())
                QApplication.clipboard().setMimeData(mime)
                window.viewmodel.changed.emit()
                return
            parent = window._asset_drop_parent() if window.object_edit.active else None
            if library and payload["kind"] == "objects":
                payload = service.objects_to_definitions(payload)
            if payload["kind"] == "scene":
                created = []

                def paste_scene(document: Any) -> None:
                    """Activate the copied scene after its complete graph has been published."""
                    created.append(service.paste(payload)[0])
                    document.select_scene(created[0])

                window.scene_workspace.change_scene(paste_scene)
                if created:
                    window.tree.clearSelection()
                    window.scene_workspace.scene_items[created[0]].setSelected(True)
                return
            roots = service.paste(payload, parent)
            window.viewmodel.changed.emit()
            if payload["kind"] == "definitions":
                window.library_tabs.setCurrentWidget(self.cards)
            else:
                window.scene_workspace.select_entries(roots)
        except (ProjectError, ValueError, KeyError, TypeError) as error:
            window.statusBar().showMessage(str(error), 10000)

    def _cut_scene(self, key: str) -> None:
        """Cut the last scene safely by leaving a fresh empty scene in the project."""

        def cut(document: Any) -> None:
            """Apply scene replacement and deletion as one reversible mutation."""
            with document.command_group("Cut scene"):
                if len(document.project.scenes) == 1:
                    document.add_scene()
                document.delete_scene(key)

        self.window.scene_workspace.change_scene(cut)

    def add_clipboard_actions(
        self, menu: QMenu, *, scene_id: str | None = None, library: bool = False
    ) -> None:
        """Use familiar labels and shortcuts consistently in Scene, viewport and Objects."""
        for action, label, shortcut in (
            ("copy", "Copy", "Ctrl+C"),
            ("cut", "Cut", "Ctrl+X"),
            ("paste", "Paste", "Ctrl+V"),
            ("duplicate", "Duplicate", "Ctrl+D"),
        ):
            item = menu.addAction(menu_text(f"{label}\t{shortcut}"))
            item.triggered.connect(
                lambda checked=False, a=action: self.command(a, scene_id=scene_id, library=library)
            )
        menu.addSeparator()

    def context_menu(self, point: Any) -> None:
        """Offer library duplication and placement without exposing scene-only controls."""
        item = self.cards.itemAt(point)
        if item and not item.isSelected():
            self.cards.clearSelection()
            item.setSelected(True)
        menu = QMenu(self.cards)
        selected = self.selected_definitions()
        edit = menu.addAction(self.window.icons.icon("edit"), "Edit", lambda: self.edit())
        edit.setEnabled(len(selected) == 1)
        add = menu.addAction(self.window.icons.icon("add"), "Add to Scene", self.add_to_scene)
        add.setEnabled(bool(selected))
        remove = menu.addAction(self.window.icons.icon("delete"), "Remove…", self.remove)
        remove.setEnabled(bool(selected))
        related = menu.addAction(
            self.window.icons.icon("delete_sweep"),
            "Remove All Related Objects in Scene…",
            self.remove_scene_instances,
        )
        related.setEnabled(bool(selected))
        menu.addSeparator()
        menu.addAction("Import Object Package…", lambda: self.import_objects())
        export = menu.addAction("Export Object Package…", lambda: self.export_objects())
        export.setEnabled(bool(selected))
        custom = menu.addAction(
            "Save to Custom Templates…", lambda: self.export_objects(custom=True)
        )
        custom.setEnabled(bool(selected))
        menu.addSeparator()
        self.add_clipboard_actions(menu, library=True)
        menu.exec(self.cards.viewport().mapToGlobal(point))

    def remove(self) -> None:
        """Confirm removal of saved definitions while leaving their placed artwork intact."""
        keys = self.selected_definitions()
        if (
            not keys
            or ask_question(
                self.window,
                "Remove saved Objects?",
                f"Remove {len(keys)} saved Object(s) from this project's Assets? "
                "Placed copies will remain and stop sharing edits. Undo restores the links.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.return_to_project()
        self.window.viewmodel.scene.run(lambda s: ObjectLibraryService(s.document).remove(keys))

    def remove_scene_instances(self) -> None:
        """Confirm deleting related placements only in the current scene, retaining the asset."""
        keys = self.selected_definitions()
        doc = self.persistence_document(self.window.viewmodel.documents)
        count = len(ObjectLibraryService(doc).scene_instances(keys))
        if (
            not count
            or ask_question(
                self.window,
                "Remove related scene Objects?",
                f"Remove {count} related Object(s) from scene '{doc.scene.name}'? "
                "Saved assets and other scenes will remain. Undo restores these placements.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.return_to_project()
        self.window.viewmodel.scene.run(
            lambda s: ObjectLibraryService(s.document).remove_scene_instances(keys)
        )

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Handle Scene→Objects drops and clipboard keys without global shortcut conflicts."""
        if watched is self.card_viewport and isinstance(
            event, (QDragEnterEvent, QDragMoveEvent, QDropEvent)
        ):
            mime = event.mimeData()
            if mime.hasFormat("application/x-rigora-scene"):
                session = bytes(mime.data("application/x-rigora-session").data()).decode(
                    errors="replace"
                )
                raw = bytes(mime.data("application/x-rigora-scene").data())
                if session != self.window.viewmodel.documents.session_id or len(raw) > 65536:
                    event.ignore()
                    return True
                if event.type() == QEvent.Type.Drop:
                    try:
                        keys = json.loads(raw)
                        if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
                            raise ValueError("Invalid Object drop.")
                        self.save(tuple(keys))
                    except ValueError:
                        event.ignore()
                        return True
                event.setDropAction(Qt.DropAction.CopyAction)
                event.accept()
                return True
        if isinstance(event, QKeyEvent) and event.type() == QEvent.Type.KeyPress:
            if self.window.viewmodel.mesh.active and watched is self.window.viewport:
                return False
            action = next(
                (
                    a
                    for a, key in (
                        ("copy", QKeySequence.StandardKey.Copy),
                        ("cut", QKeySequence.StandardKey.Cut),
                        ("paste", QKeySequence.StandardKey.Paste),
                    )
                    if event.matches(key)
                ),
                None,
            )
            if (
                event.key() == Qt.Key.Key_D
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier
            ):
                action = "duplicate"
            if watched is self.cards and event.key() == Qt.Key.Key_Delete:
                self.remove()
                return True
            if action:
                self.command(
                    action,
                    scene_id=self.scene_target() if watched is self.window.tree else None,
                    library=watched is self.cards,
                )
                return True
        return False
