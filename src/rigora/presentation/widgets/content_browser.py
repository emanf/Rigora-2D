"""Offline content browsing, metadata, scratch previews and explicit reusable asset sharing."""

import getpass
import hashlib
import math
import time
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from PySide6.QtCore import QMimeData, QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QDrag, QHideEvent, QIcon, QPixmap, QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from rigora.application_services.content_library import ContentService, LibraryEntry
from rigora.application_services.documents import DocumentService
from rigora.domain.content import (
    CHARACTER_VIEWS,
    PROP_FAMILIES,
    content_categories,
    content_families,
    content_format,
)
from rigora.domain.geometry import transform_point
from rigora.domain.project import ProjectError
from rigora.domain.validation import json_copy
from rigora.engine.state import ScenePose
from rigora.engine.time import FrameRange
from rigora.infrastructure.content_packs import read_pack
from rigora.presentation.artwork import decode_artwork
from rigora.presentation.viewmodels.content_library import LibraryViewModel
from rigora.presentation.widgets.asset_cards import configure_card_grid, label_format
from rigora.presentation.widgets.file_dialogs import choose_open_file, choose_save_file
from rigora.presentation.widgets.message_dialogs import ask_question
from rigora.presentation.widgets.viewport import Viewport
from rigora.presentation.widgets.window_frame import CustomDialog

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


class ContentDragList(QListWidget):
    """Drag only installed content identities; source paths never travel through drag payloads."""

    def __init__(self) -> None:
        """Enable external copy drags without allowing reordering or consuming source items."""
        super().__init__()
        configure_card_grid(self)
        self.setDragDropMode(QListWidget.DragDropMode.DragOnly)
        self.setDragEnabled(True)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

    def mimeTypes(self) -> list[str]:
        """Advertise the same internal identity format used by the native drag payload."""
        return ["application/x-rigora-content"]

    def startDrag(self, supportedActions: Qt.DropAction) -> None:
        """Use the native copy cursor; the viewport owns the placement preview."""
        item = self.currentItem()
        if item is None:
            return
        drag = QDrag(self)
        drag.setMimeData(self.mimeData([item]))
        pixmap = QPixmap(1, 1)
        pixmap.fill(Qt.GlobalColor.transparent)
        drag.setPixmap(pixmap)
        drag.exec(Qt.DropAction.CopyAction, Qt.DropAction.CopyAction)

    def mimeData(self, items: Sequence[QListWidgetItem]) -> QMimeData:
        """Encode a browser identity for the main viewport's validated application route."""
        data = QMimeData()
        if items:
            entry = items[0].data(Qt.ItemDataRole.UserRole)
            data.setData("application/x-rigora-content", entry.key.encode("utf-8"))
        return data


class ContentBrowser(CustomDialog):
    """Preview prospective application in a scratch document before publishing a real command."""

    def __init__(self, parent: QWidget, model: LibraryViewModel) -> None:
        """Build searchable offline collections with standard custom window controls."""
        super().__init__(parent, "Rigora content library")
        self.host = cast("MainWindow", parent)
        self.model = model
        self.current: LibraryEntry | None = None
        self.files: dict[str, bytes] = {}
        self.preview_document: DocumentService | None = None
        self._catalog = 0
        self._loaded = False
        self._decoded: dict[str, Any] = {}
        self._thumbnail_icons: dict[str, QIcon] = {}
        self._pack_stamp: tuple[Path, int, int] | None = None
        self.pending_apply = ""
        self._document: tuple[int, int] | None = None
        self._playing = True
        self._preview_entry = ""
        self._preview_target: tuple[str, str] = ("", "")
        self.resize(1380, 850)
        self.setMinimumSize(1000, 650)
        layout = QVBoxLayout(self.content)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.setPlaceholderText("Search name, tags, description, author or license…")
        self.search.setAccessibleName("Search offline content")
        self.search.textChanged.connect(self.filter)
        top.addWidget(self.search, 1)
        top.addWidget(self.button("Refresh", "refresh", self.model.reload))
        top.addWidget(self.button("Install pack…", "file_download", self.install))
        self.collection = QComboBox()
        self.collection.setAccessibleName("Content collection")
        self.collection.addItems(["All", "Favorites", "Recent"])
        self.collection.currentTextChanged.connect(self.filter)
        top.addWidget(self.collection)
        self.prop_family = QComboBox()
        self.prop_family.setAccessibleName("Prop family")
        for label, tag in PROP_FAMILIES:
            self.prop_family.addItem(label, tag)
        self.prop_family.currentIndexChanged.connect(self.filter)
        top.addWidget(self.prop_family)
        self.character_view = QComboBox()
        self.character_view.setAccessibleName("Character view")
        for label, tag in CHARACTER_VIEWS:
            self.character_view.addItem(label, tag)
        self.character_view.currentIndexChanged.connect(self.filter)
        top.addWidget(self.character_view)
        layout.addLayout(top)
        split = QSplitter()
        self.results = ContentDragList()
        self.results.setDragEnabled(True)
        self.results.setAccessibleName("Installed reusable content")
        self.results.currentRowChanged.connect(self.select_entry)
        self.results.itemDoubleClicked.connect(lambda: self.add_to_scene())
        self.results.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.results.customContextMenuRequested.connect(self.context_menu)
        split.addWidget(self.results)
        detail = QWidget()
        right = QVBoxLayout(detail)
        right.setContentsMargins(10, 0, 0, 0)
        self.preview_title = QLabel("Choose a template")
        self.preview_title.setStyleSheet("font-size: 18px; font-weight: 600;")
        right.addWidget(self.preview_title)
        self.preview = Viewport()
        self.preview.content_dropped.connect(self.preview_drop)
        self.preview.node_labels = False
        self.preview.theme = str(model.library.preferences.data.get("theme", "dark"))
        self.preview.setMinimumHeight(320)
        self.preview.grid_visible = False
        self.preview.scene_hint = "CONTENT PREVIEW · Project unchanged"
        right.addWidget(self.preview, 1)
        self.details = QLabel("Select an asset to inspect its provenance and preview it.")
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        settings = QTabWidget()
        settings.setMinimumWidth(250)
        settings.setMaximumWidth(350)
        properties = QWidget()
        property_box = QVBoxLayout(properties)
        settings.addTab(properties, "Settings")
        metadata_scroll = QScrollArea()
        metadata_scroll.setWidgetResizable(True)
        metadata_scroll.setWidget(self.details)
        settings.addTab(metadata_scroll, "Details")
        targets = self.target_form = QFormLayout()
        self.rigs, self.meshes = QComboBox(), QComboBox()
        self.rigs.setAccessibleName("Target skeleton")
        self.meshes.setAccessibleName("Target mesh")
        for selector, label in ((self.rigs, "Target rig"), (self.meshes, "Target mesh")):
            selector.currentIndexChanged.connect(self.reload_preview)
            selector.setPlaceholderText(label)
            targets.addRow(label, selector)
        self.scene_clip = QComboBox()
        self.scene_clip.setAccessibleName("Character performance clip")
        self.scene_clip.currentIndexChanged.connect(self.select_scene_motion)
        self._clip_entry = ""
        targets.addRow("Performance", self.scene_clip)
        targets.setRowVisible(self.scene_clip, False)
        targets.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        property_box.addLayout(targets)
        self.ffd_options = QWidget()
        timing = QFormLayout(self.ffd_options)
        self.ffd_speed = QDoubleSpinBox()
        self.ffd_speed.setRange(0.05, 20)
        self.ffd_speed.setValue(1)
        self.ffd_repeats = QSpinBox()
        self.ffd_repeats.setRange(1, 32)
        self.ffd_strength = QDoubleSpinBox()
        self.ffd_strength.setRange(0, 10)
        self.ffd_strength.setValue(1)
        for label, timing_field in (
            ("Speed ×", self.ffd_speed),
            ("Loops", self.ffd_repeats),
            ("FFD strength", self.ffd_strength),
        ):
            timing_field.setAccessibleName(label)
            timing.addRow(label, timing_field)
            timing_field.valueChanged.connect(self.reload_preview)
        property_box.addWidget(self.ffd_options)
        self.mesh_overlay = QCheckBox("Show mesh overlay")
        self.mesh_overlay.toggled.connect(self.set_mesh_overlay)
        property_box.addWidget(self.mesh_overlay)
        self.compatibility = QLabel()
        self.compatibility.setWordWrap(True)
        property_box.addWidget(self.compatibility)
        hint = QLabel(
            "Drag a template onto the main stage to place it. Drop motions on a compatible "
            "character and FFD on artwork. This preview keeps your project unchanged."
        )
        hint.setWordWrap(True)
        hint.setObjectName("Muted")
        property_box.addWidget(hint)
        property_box.addStretch()
        commands = QHBoxLayout()
        self.play_button = self.button("Play preview", "play_arrow", self.play_preview)
        self.favorite_button = self.button("Favorite", "star_border", self.favorite)
        self.loop_preview = QCheckBox("Loop")
        self.loop_preview.setChecked(True)
        self.loop_preview.toggled.connect(self.set_preview_loop)
        for button in (
            self.play_button,
            self.button("Restart", "skip_previous", self.restart_preview),
            self.loop_preview,
            self.button("Fit", "fit_screen", self.fit_preview),
        ):
            commands.addWidget(button)
        right.addLayout(commands)
        scrub = QHBoxLayout()
        self.preview_scrubber = QSlider(Qt.Orientation.Horizontal)
        self.preview_scrubber.setRange(0, 10000)
        self.preview_scrubber.setAccessibleName("Template preview playhead")
        self.preview_scrubber.sliderMoved.connect(self.scrub_preview)
        scrub.addWidget(self.preview_scrubber, 1)
        self.preview_time = QLabel("0.00 s")
        scrub.addWidget(self.preview_time)
        right.addLayout(scrub)
        property_box.addWidget(self.favorite_button)
        split.addWidget(detail)
        split.addWidget(settings)
        split.setStretchFactor(1, 1)
        split.setSizes([280, 780, 280])
        layout.addWidget(split, 1)
        self.share_name = QLineEdit("My reusable asset")
        self.author = QLineEdit(getpass.getuser())
        self.license = QLineEdit("All rights reserved")
        for field, name in (
            (self.share_name, "Reusable asset name"),
            (self.author, "Asset author"),
            (self.license, "Asset license"),
        ):
            field.setAccessibleName(name)
        sharing = QWidget()
        fields = QVBoxLayout(sharing)
        for label, field in (
            ("Name", self.share_name),
            ("Author", self.author),
            ("License", self.license),
        ):
            fields.addWidget(QLabel(label))
            fields.addWidget(field)
        fields.addWidget(self.button("Save target rig…", "save", lambda: self.export(True)))
        fields.addWidget(self.button("Share scene pack…", "folder_zip", lambda: self.export(False)))
        fields.addStretch()
        settings.addTab(sharing, "Share")
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self.tick)
        self._time = time.monotonic()
        model.changed.connect(self.refresh)
        self.finished.connect(lambda: self.timer.stop())
        if not model.entries:
            model.reload()
        self.refresh()

    def button(self, text: str, icon: str, callback: Any) -> QPushButton:
        """Create a Material control with readable text and theme metadata."""
        button = QPushButton(self.icons.icon(icon), text)
        button.setProperty("materialIcon", icon)
        button.clicked.connect(callback)
        return button

    def refresh(self) -> None:
        """Update catalog and target identities without resetting filters on every preview tick."""
        self.refresh_status()
        if id(self.model.entries) != self._catalog:
            self._catalog = id(self.model.entries)
            selected = self.collection.currentText()
            with QSignalBlocker(self.collection):
                self.collection.clear()
                self.collection.addItems(
                    [
                        "All",
                        "Favorites",
                        "Recent",
                        *content_categories(e.item.category for e in self.model.entries),
                    ]
                )
                self.collection.setCurrentText(
                    selected if self.collection.findText(selected) >= 0 else "All"
                )
            self._thumbnail_icons.clear()
            self.filter()
        shelf = getattr(self.parentWidget(), "content_shelf", None)
        if shelf is not None:
            for i in range(self.results.count()):
                row = self.results.item(i)
                entry = row.data(Qt.ItemDataRole.UserRole)
                icon = shelf.icons.get(entry.key)
                if icon is not None and row.icon().cacheKey() != icon.cacheKey():
                    row.setIcon(icon)
        doc = self.model.document
        source = id(doc), id(doc.project) if doc else 0
        if source != self._document:
            self._document = source
            rig, mesh = self.rigs.currentData(), self.meshes.currentData()
            with QSignalBlocker(self.rigs), QSignalBlocker(self.meshes):
                self.rigs.clear()
                self.meshes.clear()
                if doc and doc.project:
                    scene = doc.scene
                    for item in scene.skeletons:
                        self.rigs.addItem(item.name, item.id)
                    for mesh_item in scene.meshes:
                        self.meshes.addItem(mesh_item.name, mesh_item.id)
                self.rigs.setCurrentIndex(max(0, self.rigs.findData(rig)))
                self.meshes.setCurrentIndex(max(0, self.meshes.findData(mesh)))

    def refresh_status(self) -> None:
        """Keep hidden-by-search counts visible, including empty results with no preview job."""
        self.status.setText(
            "Reading local content…"
            if self.model.busy
            else self.model.error
            or f"Showing {self.results.count()} of {len(self.model.entries)} assets"
        )

    def filter(self) -> None:
        """Search metadata locally and sort recent/favorite collections without file access."""
        previous = self.current.key if self.current else ""
        query, category = self.search.text().casefold(), self.collection.currentText()
        family_category = category in ("Props & accessories", "Environment")
        self.prop_family.setVisible(family_category)
        if family_category:
            families = content_families(category)
            if tuple(
                self.prop_family.itemData(i) for i in range(self.prop_family.count())
            ) != tuple(tag for _, tag in families):
                previous_family = self.prop_family.currentData()
                with QSignalBlocker(self.prop_family):
                    self.prop_family.clear()
                    for label, tag in families:
                        self.prop_family.addItem(label, tag)
                    self.prop_family.setCurrentIndex(
                        max(0, self.prop_family.findData(previous_family))
                    )
        family = self.prop_family.currentData() if family_category else ""
        character = category in ("Characters", "Animals", "Birds & wings", "Vehicles")
        self.character_view.setVisible(character)
        if character:
            views = tuple(
                pair
                for pair in CHARACTER_VIEWS
                if category != "Vehicles" or pair[1] in ("", "side")
            )
            if tuple(
                self.character_view.itemData(i) for i in range(self.character_view.count())
            ) != tuple(tag for _, tag in views):
                previous_view = self.character_view.currentData()
                with QSignalBlocker(self.character_view):
                    self.character_view.clear()
                    for label, tag in views:
                        self.character_view.addItem(label, tag)
                    self.character_view.setCurrentIndex(
                        max(0, self.character_view.findData(previous_view))
                    )
        view = self.character_view.currentData() if character else ""
        recent = self.model.library.preferences.data.get("content_recent", [])
        recent = recent if isinstance(recent, list) else []
        entries = [
            e
            for e in self.model.entries
            if (
                category == "All"
                or category == e.item.category
                or category == "Favorites"
                and self.model.library.favorite(e.key)
                or category == "Recent"
                and e.key in recent
            )
            and (not family or family in e.item.tags)
            and (not view or view in e.item.tags)
            and all(
                word
                in " ".join(
                    (e.item.name, e.item.description, e.item.author, e.item.license, *e.item.tags)
                ).casefold()
                for word in query.split()
            )
        ]
        if category == "Recent":
            entries.sort(key=lambda e: recent.index(e.key))
        elif query.strip():
            entries.sort(key=lambda e: e.item.name.casefold() != query.strip())
        with QSignalBlocker(self.results):
            self.results.clear()
            for entry in entries:
                shelf = getattr(self.parentWidget(), "content_shelf", None)
                thumbnail = self._thumbnail_icons.get(entry.key)
                if thumbnail is None and shelf is not None:
                    thumbnail = shelf.icons.get(entry.key)
                item = QListWidgetItem(
                    thumbnail
                    if thumbnail is not None
                    else self.icons.icon(
                        "device_hub"
                        if entry.item.kind == "rig"
                        else "movie"
                        if entry.item.kind == "action"
                        else "category"
                    ),
                    entry.item.name,
                )
                label_format(item, content_format(entry.item))
                item.setData(Qt.ItemDataRole.UserRole, entry)
                item.setToolTip(
                    f"{entry.item.description}\n{entry.item.author} · {entry.item.license}"
                )
                self.results.addItem(item)
            exact = next(
                (i for i, e in enumerate(entries) if e.item.name.casefold() == query.strip()), None
            )
            index = (
                exact
                if exact is not None
                else next((i for i, e in enumerate(entries) if e.key == previous), 0)
            )
            self.results.setCurrentRow(index if entries else -1)
        self.select_entry()
        self.refresh_status()

    def select_entry(self) -> None:
        """Read selected pack bytes and decode thumbnails/sources on the storage worker."""
        row = self.results.currentItem()
        self.current = row.data(Qt.ItemDataRole.UserRole) if row else None
        self.timer.stop()
        self.play_button.setText("Play preview")
        self.play_button.setIcon(self.icons.icon("play_arrow"))
        cached_files = self.files
        self.files, self.preview_document = {}, None
        self._loaded = False
        self.preview.set_pose(None)
        if self.current is None:
            self.details.setText("No matching installed content.")
            return
        entry = self.current
        cached, cached_stamp = dict(self._decoded), self._pack_stamp
        self.details.setText(
            f"{entry.item.name}\n{entry.item.description}\n\nAuthor: {entry.item.author} · "
            f"Version: {entry.item.version} · License: {entry.item.license}\n"
            f"Category: {entry.item.category} · Engine: {entry.item.engine_version}\n"
            f"Tags: {', '.join(entry.item.tags)}\nPack: {entry.pack.name}"
        )

        def load() -> tuple[dict[str, bytes], dict[str, Any], tuple[Path, int, int]] | None:
            """Decode only referenced image media; arbitrary pack files are never executed."""
            stat = entry.path.stat()
            stamp = entry.path, stat.st_mtime_ns, stat.st_size
            if stamp == cached_stamp and cached_files:
                files = cached_files
            else:
                pack, files = read_pack(entry.path)
                if pack != entry.pack:
                    # Scene member IDs and source maps must come from the same pack revision.
                    return None
            sources: list[str] = []
            if entry.item.kind == "scene":
                descriptors = entry.item.payload.get("sources", {})
                sources.extend(
                    name
                    for name in descriptors.values()
                    if str(name).lower().endswith((".png", ".jpg", ".jpeg", ".svg"))
                )
            if entry.item.kind == "artwork":
                sources.append(entry.item.payload["source"])
            thumbnails = {item.thumbnail for item in entry.pack.items if item.thumbnail}
            sources.extend(thumbnails)
            decoded = {}
            for name in sources:
                data = files[name]
                digest = hashlib.sha256(data).hexdigest()
                if stamp == cached_stamp and name in thumbnails and digest in cached:
                    decoded[digest] = cached[digest]
                    continue
                limit = (
                    256
                    if name in thumbnails
                    else max(1, min(2048, int(math.sqrt(96 * 1024**2 / 4 / max(1, len(sources))))))
                )
                decoded[digest] = (decode_artwork(data, limit), data)
            return files, decoded, stamp

        def complete(
            result: tuple[dict[str, bytes], dict[str, Any], tuple[Path, int, int]] | None,
        ) -> None:
            """Ignore a stale selection and build the prospective scene on the GUI thread."""
            if self.current is None or self.current.key != entry.key:
                return
            if result is None:
                self.model.reload()
                return
            self.files, decoded, self._pack_stamp = result
            self._loaded = True
            self._decoded = decoded
            for i in range(self.results.count()):
                row = self.results.item(i)
                other = row.data(Qt.ItemDataRole.UserRole) if row else None
                if other and other.pack.id == entry.pack.id and other.item.thumbnail:
                    image, _ = decoded[hashlib.sha256(self.files[other.item.thumbnail]).hexdigest()]
                    icon = QIcon(QPixmap.fromImage(image))
                    self._thumbnail_icons[other.key] = icon
                    row.setIcon(icon)
            self.reload_preview(decoded)
            if self.pending_apply == entry.key:
                self.pending_apply = ""
                self.apply()

        self.model.background(load, complete)

    def reload_preview(self, decoded: Any = None) -> None:
        """Apply to a scratch document and report incompatibility without changing live history."""
        if self.current is None or not self._loaded:
            return
        phase = 0.0
        if self.preview_document and self._preview_entry == self.current.key:
            playback = self.preview_document.animation.playback
            phase = (playback.frame - playback.range.start) / max(
                1, playback.range.end - playback.range.start
            )
        self.timer.stop()
        decoded = decoded if isinstance(decoded, dict) else self._decoded
        doc = self.model.document
        if doc is None:
            doc = DocumentService()
            doc.new("Content preview")
        try:
            service = ContentService(doc)
            target, mesh = str(self.rigs.currentData() or ""), str(self.meshes.currentData() or "")
            self.preview_document = service.preview(
                self.configured_item(), self.files, target=target, mesh_id=mesh, specimen=True
            )
            preview = self.preview_document
            self.preview.artwork.clear()
            host = self.parentWidget()
            if host and hasattr(host, "viewport"):
                self.preview.artwork.images.update(host.viewport.artwork.images)
                self.preview.artwork.vectors.update(host.viewport.artwork.vectors)
            if isinstance(decoded, dict) and preview.project:
                for asset in preview.project.assets:
                    if asset.sha256 in decoded:
                        image, data = decoded[asset.sha256]
                        self.preview.artwork.put(asset.id, image, data)
                    elif (
                        asset.kind in ("raster", "vector")
                        and asset.id not in self.preview.artwork.images
                    ):
                        data = preview.read_asset(asset.id)
                        self.preview.artwork.put(asset.id, decode_artwork(data, 512), data)
            if self.current.item.kind in ("rig", "pose"):
                pose = rest_preview_pose(preview)
            else:
                pose = preview.animation.pose
            assert preview.project is not None
            self.preview.set_scene(preview.scene.settings)
            self.preview.set_pose(pose)
            if self._preview_entry != self.current.key or self._preview_target != (target, mesh):
                self.fit_preview()
            self._preview_target = target, mesh
            self.compatibility.setText(service.compatibility(self.configured_item(), target, mesh))
            self.mesh_overlay.setVisible(self.current.item.kind == "deformation")
            self.set_mesh_overlay(self.mesh_overlay.isChecked())
            self.preview.show_bones = not bool(pose.meshes)
            self.preview_title.setText(self.current.item.name)
            self._preview_entry = self.current.key
            if "motion" in self.current.item.payload:
                motion = self.current.item.payload["motion"]
                length = (
                    float(motion["duration"])
                    * preview.animation.evaluator.range.fps
                    / float(motion.get("fps", 24))
                    / self.ffd_speed.value()
                    * self.ffd_repeats.value()
                )
                start = doc.animation.pose.frame
                preview.animation.playback.range = FrameRange(
                    start, start + length, preview.animation.evaluator.range.fps
                )
            playback = preview.animation.playback
            preview.animation.seek(
                playback.range.start + phase * (playback.range.end - playback.range.start)
            )
            self.sync_playback()
            self.preview.set_pose(preview.animation.pose)
            self.favorite_button.setText(
                "Unfavorite" if self.model.library.favorite(self.current.key) else "Favorite"
            )
            icon = "star" if self.model.library.favorite(self.current.key) else "star_border"
            self.favorite_button.setProperty("materialIcon", icon)
            self.favorite_button.setIcon(self.icons.icon(icon))
        except (ProjectError, KeyError, TypeError, ValueError) as error:
            self.preview_document = None
            self.compatibility.setText(str(error))
        self.refresh()

    def fit_preview(self) -> None:
        """Frame actual visible bones and evaluated mesh bounds inside the preview stage."""
        pose = self.preview.pose
        if pose is None:
            return
        points = [
            transform_point(n.world_matrix, x, 0)
            for n in pose.nodes.values()
            for x in (0, n.length)
            if n.visible
        ]
        for mesh_pose in pose.meshes.values():
            owner = pose.nodes.get(mesh_pose.object_id or "")
            if owner:
                points.extend(transform_point(owner.world_matrix, *p) for p in mesh_pose.positions)
        if points:
            from PySide6.QtCore import QPointF

            xs, ys = [p[0] for p in points], [p[1] for p in points]
            self.preview.zoom = min(
                4,
                (self.preview.width() - 60) / max(1, max(xs) - min(xs)),
                (self.preview.height() - 60) / max(1, max(ys) - min(ys)),
            )
            self.preview.offset = QPointF(
                self.preview.width() / 2 - (max(xs) + min(xs)) / 2 * self.preview.zoom,
                self.preview.height() / 2 - (max(ys) + min(ys)) / 2 * self.preview.zoom,
            )
        else:
            self.preview.fit_canvas()

    def set_mesh_overlay(self, enabled: bool) -> None:
        """Toggle optional deformation diagnostics without rebuilding or pausing the specimen."""
        self.preview.mesh_wireframe = bool(
            enabled and self.current and self.current.item.kind == "deformation"
        )
        self.preview.update()

    def preview_drop(self, key: str, point: Any) -> None:
        """Inspect dropped content in this scratch viewport without publishing scene edits."""
        self.search.clear()
        self.collection.setCurrentText("All")
        for index in range(self.results.count()):
            if self.results.item(index).data(Qt.ItemDataRole.UserRole).key == key:
                self.results.setCurrentRow(index)
                break

    def apply(self) -> None:
        """Publish the currently previewed compatible asset through the active document service."""
        if (
            self.current
            and self._loaded
            and self.preview_document
            and not self.model.busy
            and not self.compatibility.text()
        ):
            self.model.apply(
                replace(self.current, item=self.configured_item()),
                self.files,
                str(self.rigs.currentData() or ""),
                str(self.meshes.currentData() or ""),
            )

    def add_to_scene(self) -> None:
        """Keep standalone template insertion in the main Scene instead of opening an editor."""
        if self.current and self.current.item.kind in ("scene", "rig", "artwork"):
            self.host.content_drop.add_to_scene(self.current.key)
        else:
            self.apply()

    def context_menu(self, point: Any) -> None:
        """Share Add to Objects and Add to Scene with the docked template collections."""
        item = self.results.itemAt(point)
        if item is None:
            return
        self.results.setCurrentItem(item)
        entry = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self.results)
        objects = menu.addAction(
            "Add to Objects", lambda: self.host.object_assets.import_objects(entry)
        )
        scene = menu.addAction("Add to Scene", self.add_to_scene)
        for action in (objects, scene):
            action.setEnabled(entry.item.kind in ("scene", "rig", "artwork"))
        menu.exec(self.results.viewport().mapToGlobal(point))

    def configured_item(self) -> Any:
        """Apply timing/intensity choices to a temporary item while retaining original catalog
        data.
        """
        assert self.current is not None
        item = self.current.item
        self.target_form.setRowVisible(self.rigs, item.kind in ("pose", "action", "spring"))
        self.target_form.setRowVisible(self.meshes, item.kind == "deformation")
        scene_clips = (
            item.payload.get(
                "performance_clips",
                item.payload.get("project", {}).get("scenes", [{}])[0].get("clips", ()),
            )
            if item.kind == "scene"
            else ()
        )
        self.target_form.setRowVisible(self.scene_clip, len(scene_clips) > 1)
        clip_key = f"{self.current.key}:{tuple((clip['id'], clip['name']) for clip in scene_clips)}"
        if self._clip_entry != clip_key:
            saved = self.model.scene_performances.get(self.current.key)
            saved_clip = saved.payload.get("selected_clip") if saved else None
            choice = (
                self.scene_clip.currentText()
                if self._clip_entry.startswith(self.current.key + ":")
                else ""
            )
            self._clip_entry = clip_key
            with QSignalBlocker(self.scene_clip):
                self.scene_clip.clear()
                for clip in scene_clips:
                    self.scene_clip.addItem(clip["name"], clip["id"])
                index = (
                    self.scene_clip.findText(choice)
                    if choice
                    else self.scene_clip.findData(saved_clip)
                )
                if index >= 0:
                    self.scene_clip.setCurrentIndex(index)
        if scene_clips and self.scene_clip.currentData():
            if "project" in item.payload:
                project = json_copy(item.payload["project"])
                clips = project["scenes"][0]["clips"]
                project["scenes"][0]["clips"] = sorted(
                    clips, key=lambda clip: clip["id"] != self.scene_clip.currentData()
                )
                item = replace(item, payload={**item.payload, "project": project})
            else:
                item = replace(
                    item, payload={**item.payload, "selected_clip": self.scene_clip.currentData()}
                )
            self.model.scene_performances[self.current.key] = item
        self.ffd_options.setVisible("motion" in item.payload or "shape" in item.payload)
        if self.ffd_options.isHidden():
            return item
        return replace(
            item,
            payload={
                **item.payload,
                "speed": self.ffd_speed.value(),
                "repeats": self.ffd_repeats.value(),
                "strength": self.ffd_strength.value(),
            },
        )

    def request_apply(self, key: str) -> None:
        """Apply a dropped installed identity after its asynchronous preview validates."""
        if (
            self.current
            and self.current.key == key
            and self.preview_document
            and not self.model.busy
        ):
            self.apply()
            return
        if not any(entry.key == key for entry in self.model.entries):
            return
        self.pending_apply = key
        self.search.clear()
        self.collection.setCurrentText("All")
        for i in range(self.results.count()):
            row = self.results.item(i)
            entry = row.data(Qt.ItemDataRole.UserRole) if row else None
            if entry and entry.key == key:
                self.results.setCurrentRow(i)
                break

    def favorite(self) -> None:
        """Toggle the selected asset's local favorite status and refresh filtered membership."""
        if self.current:
            self.model.library.toggle_favorite(self.current.key)
            self.filter()

    def install(self) -> None:
        """Choose a local portable archive and validate it in the storage worker."""
        path, _ = choose_open_file(
            self, "Install content pack", "", "Rigora content packs (*.rigpack)"
        )
        if path:
            self.model.install(Path(path))

    def export(self, skeleton_only: bool) -> None:
        """Save a reusable custom rig or scene with explicit provenance and overwrite protection."""
        doc = self.model.document
        if doc is None:
            return
        if skeleton_only and not self.rigs.currentData():
            self.status.setText("Choose a target skeleton to save as a reusable rig.")
            return
        path, _ = choose_save_file(
            self, "Share reusable content", "my-content.rigpack", "Rigora content packs (*.rigpack)"
        )
        if not path:
            return
        target = Path(path)
        overwrite = target.exists()
        if (
            overwrite
            and ask_question(
                self,
                "Replace content pack?",
                f"Replace {target.name}?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            ContentService(doc).export_own(
                target,
                self.share_name.text(),
                self.author.text(),
                self.license.text(),
                rig_id=str(self.rigs.currentData() or "") if skeleton_only else "",
                overwrite=overwrite,
            )
            self.status.setText(f"Saved portable pack: {target.name}")
        except (ProjectError, OSError) as error:
            self.status.setText(str(error))

    def play_preview(self) -> None:
        """Toggle playback in the independent preview document only."""
        self._playing = not self._playing
        self.sync_playback()

    def select_scene_motion(self, *_args: object) -> None:
        """Start each deliberately selected source animation from the beginning on repeat."""
        self._playing = True
        self.loop_preview.setChecked(True)
        if self.preview_document:
            self.preview_document.animation.stop()
        self.reload_preview()

    def sync_playback(self) -> None:
        """Restore transport preferences after rebuilding property-dependent scratch geometry."""
        if self.preview_document:
            animated = bool(
                self.current
                and (
                    self.current.item.kind == "action"
                    or "motion" in self.current.item.payload
                    or self.current.item.kind == "scene"
                    and (
                        self.preview_document.animation.evaluator.timeline
                        or any(
                            "sprite_sequence" in m.extra
                            for m in self.preview_document.animation.evaluator.scene.meshes
                        )
                    )
                )
            )
            self.play_button.setEnabled(animated)
            self.preview_document.animation.set_loop(self.loop_preview.isChecked())
            self.timer.stop()
            if animated and self._playing and self.isVisible():
                self.preview_document.animation.play()
                self._time = time.monotonic()
                self.timer.start()
            self.play_button.setText(
                "Pause" if self.timer.isActive() else "Play" if animated else "Static preview"
            )
            icon = "pause" if self.timer.isActive() else "play_arrow"
            self.play_button.setProperty("materialIcon", icon)
            self.play_button.setIcon(self.icons.icon(icon))

    def set_preview_loop(self, enabled: bool) -> None:
        """Change only the scratch transport's loop mode, retaining playback and source state."""
        if self.preview_document:
            self.preview_document.animation.set_loop(enabled)

    def restart_preview(self) -> None:
        """Return the specimen to its beginning while retaining play and loop preferences."""
        if self.preview_document:
            self.preview.set_pose(self.preview_document.animation.stop())
            self.sync_playback()

    def scrub_preview(self, value: int) -> None:
        """Seek inside the specimen's actual range without pausing an ongoing preview."""
        if self.preview_document:
            playback = self.preview_document.animation.playback
            frame = playback.range.start + value / 10000 * (
                playback.range.end - playback.range.start
            )
            self.preview.set_pose(self.preview_document.animation.seek(frame))

    def showEvent(self, event: QShowEvent) -> None:
        """Resume preferred autoplay when reopening an existing nonmodal preview window."""
        super().showEvent(event)
        self.sync_playback()

    def tick(self) -> None:
        """Advance the scratch evaluator using elapsed time without moving the project playhead."""
        if not self.isVisible():
            self.timer.stop()
            return
        if self.preview_document:
            now = time.monotonic()
            try:
                pose = self.preview_document.animation.advance(now - self._time)
                self.preview.set_pose(pose)
                playback = self.preview_document.animation.playback
                with QSignalBlocker(self.preview_scrubber):
                    self.preview_scrubber.setValue(
                        round(
                            (pose.frame - playback.range.start)
                            / max(1, playback.range.end - playback.range.start)
                            * 10000
                        )
                    )
                self.preview_time.setText(
                    f"{(pose.frame - playback.range.start) / playback.range.fps:.2f} s"
                )
                if not playback.is_playing:
                    self.timer.stop()
                    self.play_button.setText("Play")
            except ProjectError as error:
                self.compatibility.setText(str(error))
                self.timer.stop()
            self._time = now

    def closeEvent(self, event: QCloseEvent) -> None:
        """Stop preview scheduling before dismissing the custom library window."""
        self.timer.stop()
        super().closeEvent(event)

    def hideEvent(self, event: QHideEvent) -> None:
        """Suspend hidden specimen animation without changing the user's autoplay preference."""
        self.timer.stop()
        if self.preview_document:
            self.preview_document.animation.pause()
        super().hideEvent(event)


def rest_preview_pose(document: DocumentService) -> ScenePose:
    """Evaluate template/rest pose previews independently of the document's animated clip."""
    from rigora.application_services.rigging import RigService

    return RigService(document).preview_pose()
