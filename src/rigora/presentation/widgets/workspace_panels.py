"""Compact docked property and offline-content panels for the primary authoring workspace."""

from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QStackedWidget,
    QTabBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from rigora.domain.content import (
    CHARACTER_VIEWS,
    PROP_FAMILIES,
    content_categories,
    content_families,
    content_format,
)
from rigora.domain.project import ProjectError
from rigora.infrastructure.content_packs import read_pack
from rigora.presentation.artwork import decode_artwork
from rigora.presentation.widgets.asset_cards import CARD_CELL, label_format
from rigora.presentation.widgets.content_browser import ContentDragList

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


class ObjectProperties(QWidget):
    """Display editable properties for the actual scene selection through canonical services."""

    def __init__(self, window: "MainWindow") -> None:
        """Create bounded local-transform fields and an explicit undoable Apply action."""
        super().__init__(window)
        self.host = window
        box = QVBoxLayout(self)
        self.title = QLabel("Select an object in the viewport or Scene panel")
        self.title.setWordWrap(True)
        box.addWidget(self.title)
        form = QFormLayout()
        self.fields = {}
        for key, title in (
            ("x", "Position X"),
            ("y", "Position Y"),
            ("rotation", "Rotation °"),
            ("scale_x", "Scale X %"),
            ("scale_y", "Scale Y %"),
        ):
            field = QDoubleSpinBox()
            field.setRange(-1e7, 1e7)
            field.setDecimals(3)
            field.setKeyboardTracking(False)
            field.setAccessibleName(title)
            self.fields[key] = field
            form.addRow(title, field)
        box.addLayout(form)
        self.apply_button = QPushButton(window.icons.icon("check"), "Apply transform")
        self.apply_button.setProperty("materialIcon", "check")
        self.apply_button.clicked.connect(self.apply)
        box.addWidget(self.apply_button)
        note = QLabel(
            "Drag artwork to move · Use handles to rotate/resize\n"
            "Drag the crosshair to move its pivot · Alt: resize from pivot\n"
            "Ctrl: multiselect · Esc: cancel · F2 in Scene: rename"
        )
        note.setWordWrap(True)
        note.setObjectName("Muted")
        box.addWidget(note)
        box.addStretch()

    def refresh(self) -> None:
        """Resolve the current record afresh so tab changes and undo never leave stale controls."""
        model = self.host.viewmodel.scene
        record = (
            model.service.record(model.selected[0]) if model.service and model.selected else None
        )
        transform = getattr(record, "transform", None)
        self.title.setText(
            record.name if record else "Select an object in the viewport or Scene panel"
        )
        self.apply_button.setEnabled(
            bool(record and transform and model.service and not model.service.locked(record.id))
        )
        for key, field in self.fields.items():
            field.setEnabled(transform is not None)
            with QSignalBlocker(field):
                field.setValue(
                    getattr(transform, key) * (100 if key.startswith("scale") else 1)
                    if transform
                    else 0
                )

    def apply(self) -> None:
        """Publish explicit local property changes as one reversible command."""
        model = self.host.viewmodel.scene
        if model.selected:
            values = {
                k: f.value() / (100 if k.startswith("scale") else 1) for k, f in self.fields.items()
            }
            model.run(lambda service: service.set_transform(model.selected[0], **values))


class ContentShelf(QWidget):
    """Browse original and installed templates beside the stage without obscuring the viewport."""

    DEFAULT_WIDTH = 2 * CARD_CELL + 64

    def __init__(self, window: "MainWindow") -> None:
        """Bind shared catalog state, source/custom collections and independently loaded
        thumbnails.
        """
        super().__init__(window)
        self.host, self.model = window, window.viewmodel.content
        self._catalog = 0
        self.pending_category = ""
        self.icons: dict[str, QIcon] = {}
        self.loading: set[Path] = set()
        box = QVBoxLayout(self)
        box.setContentsMargins(8, 8, 8, 8)
        self.tabs = QTabBar()
        self.tabs.addTab("Templates")
        self.tabs.addTab("Custom")
        self.tabs.currentChanged.connect(self.filter)
        box.addWidget(self.tabs)
        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.setPlaceholderText("Search motion, style, anatomy…")
        self.search.setAccessibleName("Search docked content library")
        self.search.textChanged.connect(self.filter)
        search_row = QHBoxLayout()
        search_row.addWidget(self.search, 1)
        self.clear_filters = QToolButton()
        self.clear_filters.setIcon(window.icons.icon("filter_alt_off"))
        self.clear_filters.setAccessibleName("Clear template filters")
        self.clear_filters.setToolTip("Clear search, category, view and family filters")
        self.clear_filters.clicked.connect(self.reset_filters)
        search_row.addWidget(self.clear_filters)
        box.addLayout(search_row)
        self.collection = QComboBox()
        self.collection.addItems(["All", "Favorites", "Recent"])
        self.collection.currentTextChanged.connect(self.filter)
        box.addWidget(self.collection)
        self.character_view = QComboBox()
        self.character_view.setAccessibleName("Character view")
        for label, tag in CHARACTER_VIEWS:
            self.character_view.addItem(label, tag)
        self.character_view.currentIndexChanged.connect(self.filter)
        box.addWidget(self.character_view)
        self.prop_family = QComboBox()
        self.prop_family.setAccessibleName("Docked prop family")
        for label, tag in PROP_FAMILIES:
            self.prop_family.addItem(label, tag)
        self.prop_family.currentIndexChanged.connect(self.filter)
        box.addWidget(self.prop_family)
        self.results = ContentDragList()
        self.results.setDragEnabled(True)

        self.results.setAccessibleName("Reusable templates and motions")
        self.results.itemDoubleClicked.connect(self.apply)
        self.results.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.results.customContextMenuRequested.connect(self.context_menu)
        self.result_pages = QStackedWidget()
        self.result_pages.addWidget(self.results)
        self.empty = QWidget()
        empty_layout = QVBoxLayout(self.empty)
        empty_layout.addStretch()
        self.empty_message = QLabel()
        self.empty_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_message.setWordWrap(True)
        empty_layout.addWidget(self.empty_message)
        self.recover = QPushButton()
        self.recover.clicked.connect(self.recover_results)
        empty_layout.addWidget(self.recover)
        empty_layout.addStretch()
        self.result_pages.addWidget(self.empty)
        box.addWidget(self.result_pages, 1)
        row = QHBoxLayout()
        preview = QPushButton(window.icons.icon("visibility"), "Preview / share…")
        preview.setProperty("materialIcon", "visibility")
        preview.clicked.connect(self.preview)
        row.addWidget(preview)
        self.refresh_button = QPushButton(window.icons.icon("refresh"), "Refresh")
        self.refresh_button.setProperty("materialIcon", "refresh")
        self.refresh_button.setToolTip("Reload bundled and installed content packs")
        self.refresh_button.clicked.connect(self.model.reload)
        row.addWidget(self.refresh_button)
        box.addLayout(row)
        self.status = QLabel()
        self.status.setWordWrap(True)
        box.addWidget(self.status)
        self.model.changed.connect(self.refresh)

    def refresh(self) -> None:
        """Update the catalog only on actual discovery changes, retaining browsing context."""
        self.refresh_button.setEnabled(not self.model.busy)
        if id(self.model.entries) != self._catalog:
            self._catalog = id(self.model.entries)
            if self.model.entries:
                valid = {e.key for e in self.model.entries}
                self.icons = {key: icon for key, icon in self.icons.items() if key in valid}
            self.filter()
            if self.pending_category and self.collection.findText(self.pending_category) >= 0:
                category, self.pending_category = self.pending_category, ""
                self.collection.setCurrentText(category)
            for path in dict.fromkeys(e.path for e in self.model.entries):
                if path not in self.loading:
                    self.load_thumbnails(path)
        self.refresh_status()

    def refresh_status(self) -> None:
        """Distinguish filtered results from missing content and keep recovery visible."""
        count, total = self.results.count(), len(self.model.entries)
        self.status.setText(
            self.model.error
            or (
                "Reading content…"
                if self.model.busy and not total
                else f"{count} shown · {total} available"
            )
        )
        self.result_pages.setCurrentWidget(self.results if count else self.empty)
        custom = self.tabs.currentIndex() == 1
        if not total:
            self.empty_message.setText(
                self.model.error
                or ("Reading content…" if self.model.busy else "No content was loaded.")
            )
            self.recover.setText("Retry loading")
            self.recover.setEnabled(not self.model.busy)
        else:
            installed = any(e.path.parent == self.model.library.root for e in self.model.entries)
            self.empty_message.setText(
                "No custom packs installed."
                if custom and not installed
                else "No templates match the current filters."
            )
            self.recover.setText("Browse templates" if custom else "Clear filters")
            self.recover.setEnabled(True)

    def reset_filters(self) -> None:
        """Clear explicit browse restrictions without altering content, favorites or the project."""
        with (
            QSignalBlocker(self.search),
            QSignalBlocker(self.collection),
            QSignalBlocker(self.character_view),
            QSignalBlocker(self.prop_family),
        ):
            self.search.clear()
            self.collection.setCurrentText("All")
            self.character_view.setCurrentIndex(0)
            self.prop_family.setCurrentIndex(0)
        self.filter()

    def recover_results(self) -> None:
        """Retry a failed catalog load or explicitly return to unfiltered bundled templates."""
        if not self.model.entries:
            self.model.reload()
        else:
            with QSignalBlocker(self.tabs):
                self.tabs.setCurrentIndex(0)
            self.reset_filters()

    def load_thumbnails(self, path: Path) -> None:
        """Decode bounded pack thumbnails on the existing serialized worker pool."""
        self.loading.add(path)

        def load() -> dict[str, Any]:
            """Read one pack once and return owned preview images without touching widgets."""
            pack, files = read_pack(path, thumbnails_only=True)
            images = {}
            for item in pack.items:
                if item.thumbnail:
                    try:
                        images[f"{pack.id}/{item.id}"] = decode_artwork(files[item.thumbnail], 144)
                    except ProjectError:
                        continue
            return images

        def complete(images: dict[str, Any]) -> None:
            """Adopt worker-owned image copies as GUI-thread icons, preserving selected item."""
            self.loading.discard(path)
            if self.host._closed:
                return
            self.icons.update(
                {key: QIcon(QPixmap.fromImage(image)) for key, image in images.items()}
            )
            for index in range(self.results.count()):
                item = self.results.item(index)
                if (
                    item is not None
                    and (entry := item.data(Qt.ItemDataRole.UserRole))
                    and entry.key in images
                ):
                    item.setIcon(self.icons[entry.key])

        self.model.background(load, complete, failed=lambda _: self.loading.discard(path))

    def filter(self, *_: Any) -> None:
        """Search metadata and category without I/O or changing the active project."""
        previous = self.results.currentItem()
        key = previous.data(Qt.ItemDataRole.UserRole).key if previous else ""
        scoped = tuple(
            entry
            for entry in self.model.entries
            if (entry.path.parent == self.model.library.root) == (self.tabs.currentIndex() == 1)
        )
        recent = self.model.library.preferences.data.get("content_recent", [])
        categories = (
            "All",
            *(("Favorites",) if any(self.model.library.favorite(e.key) for e in scoped) else ()),
            *(("Recent",) if any(e.key in recent for e in scoped) else ()),
            *content_categories(e.item.category for e in scoped),
        )
        if tuple(self.collection.itemText(i) for i in range(self.collection.count())) != categories:
            selected = self.collection.currentText()
            with QSignalBlocker(self.collection):
                self.collection.clear()
                self.collection.addItems(categories)
                self.collection.setCurrentText(selected if selected in categories else "All")
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
        self.results.clear()
        for entry in scoped:
            if category not in ("All", entry.item.category):
                if (
                    category == "Favorites"
                    and self.model.library.favorite(entry.key)
                    or category == "Recent"
                    and entry.key in self.model.library.preferences.data.get("content_recent", [])
                ):
                    pass
                else:
                    continue
            metadata = " ".join(
                (entry.item.name, entry.item.description, *entry.item.tags)
            ).casefold()
            if family and family not in entry.item.tags:
                continue
            if view and view not in entry.item.tags:
                continue
            if not all(word in metadata for word in query.split()):
                continue
            item = QListWidgetItem(
                self.icons.get(entry.key, self.host.icons.icon("category")), entry.item.name
            )
            label_format(item, content_format(entry.item))
            item.setData(Qt.ItemDataRole.UserRole, entry)
            item.setToolTip(
                f"{entry.item.category}\n{entry.item.description}\n"
                f"{entry.item.author} · {entry.item.license}"
            )
            self.results.addItem(item)
            if entry.key == key:
                self.results.setCurrentItem(item)
        # Rebuild icon rectangles while hidden too; category changes and thumbnail
        # arrivals must not retain an obsolete scroll range until a manual resize.
        self.results.doItemsLayout()
        self.refresh_status()

    def preview(self) -> None:
        """Open the shared scratch preview and sharing controls for the current collection."""
        self.host.open_content_library(self.collection.currentText())
        current = self.results.currentItem()
        if current and self.host.content_browser:
            entry = current.data(Qt.ItemDataRole.UserRole)
            browser = self.host.content_browser
            browser.character_view.setCurrentIndex(
                browser.character_view.findData(self.character_view.currentData())
            )
            browser.prop_family.setCurrentIndex(
                browser.prop_family.findData(self.prop_family.currentData())
            )
            browser.search.clear()
            for index in range(browser.results.count()):
                row = browser.results.item(index)
                if row.data(Qt.ItemDataRole.UserRole).key == entry.key:
                    browser.results.setCurrentRow(index)
                    browser.results.scrollToItem(row)
                    break

    def apply(self, item: QListWidgetItem | None) -> None:
        """Use the shared asynchronous compatibility/preview gate before applying any content."""
        if item:
            entry = item.data(Qt.ItemDataRole.UserRole)
            if entry.item.kind in ("action", "spring", "deformation") and (
                entry.item.payload.get("fallback_rig") or entry.item.payload.get("fallback_mesh")
            ):
                self.host.content_drop.apply_to_selection(entry.key)
                return
            if entry.item.kind in ("scene", "rig", "artwork") or (
                not self.host.viewmodel.scene.selected
                and (
                    entry.item.payload.get("fallback_rig")
                    or entry.item.payload.get("fallback_mesh")
                )
            ):
                self.host.content_drop.add_to_scene(entry.key)
                return
            from rigora.presentation.widgets.content_browser import ContentBrowser

            if self.host.content_browser is None:
                self.host.content_browser = ContentBrowser(self.host, self.model)
            self.host.content_browser.request_apply(item.data(Qt.ItemDataRole.UserRole).key)

    def show_custom(self, category: str) -> None:
        """Reveal a newly installed category after asynchronous catalog discovery finishes."""
        self.pending_category = category
        self.tabs.setCurrentIndex(1)
        self.search.clear()
        self.model.reload()

    def context_menu(self, point: Any) -> None:
        """Expose library-only import separately from actual scene placement."""
        item = self.results.itemAt(point)
        if item is None:
            return
        self.results.setCurrentItem(item)
        entry = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self.results)
        objects = menu.addAction(
            "Add to Objects", lambda: self.host.object_assets.import_objects(entry)
        )
        scene = menu.addAction(
            "Add to Scene", lambda: self.host.content_drop.add_to_scene(entry.key)
        )
        objects.setEnabled(entry.item.kind in ("scene", "rig", "artwork"))
        scene.setEnabled(
            entry.item.kind in ("scene", "rig", "artwork")
            or bool(
                entry.item.payload.get("fallback_rig") or entry.item.payload.get("fallback_mesh")
            )
        )
        for action in (objects, scene):
            if not action.isEnabled():
                action.setToolTip("This template requires an existing rig or mesh target.")
        menu.exec(self.results.viewport().mapToGlobal(point))
