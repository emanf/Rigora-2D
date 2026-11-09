"""Modeless relationship inspection and shared binding commands for scene and object editing."""

from typing import TYPE_CHECKING

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from rigora.application_services.bindings import BindingService
from rigora.domain.entities import Bone, Group, SceneObject
from rigora.presentation.widgets.window_frame import CustomDialog

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


class BindingsDialog(CustomDialog):
    """Keep all connections visible while dispatching edits through the scene view model."""

    def __init__(self, window: "MainWindow") -> None:
        """Build target selection and a searchable, live list without changing the project."""
        super().__init__(window, "Bindings")
        self.host = window
        self.document = window.viewmodel.documents
        self.sources: tuple[str, ...] = ()
        self.resize(800, 620)
        box = QVBoxLayout(self.content)
        note = QLabel(
            "Bind bones to parent bones, skin artwork to bones, or make artwork follow another "
            "image, shape or folder. Unbinding keeps the parts and bones."
        )
        note.setWordWrap(True)
        box.addWidget(note)
        form = QFormLayout()
        self.source = QComboBox()
        self.source.setAccessibleName("Binding source")
        self.use_selection = QPushButton("Use scene selection")
        self.use_selection.setIcon(window.icons.icon("checklist"))
        self.use_selection.clicked.connect(self.capture_selection)
        row = QHBoxLayout()
        row.addWidget(self.source, 1)
        row.addWidget(self.use_selection)
        form.addRow("Source", row)
        self.target = QComboBox()
        self.target.setAccessibleName("Binding target")
        form.addRow("Target", self.target)
        self.rigid = QCheckBox("Rigid follow · keep artwork solid")
        self.rigid.setChecked(window.character_panel.rigid.isChecked())
        self.rigid.setToolTip(
            "Artwork targets always use rigid follow. Bones use skinning unless checked."
        )
        form.addRow(self.rigid)
        box.addLayout(form)
        actions = QHBoxLayout()
        self.bind_button = QPushButton("Bind")
        self.bind_button.setIcon(window.icons.icon("link"))
        self.bind_button.clicked.connect(self.bind_sources)
        self.unbind_button = QPushButton("Unbind sources")
        self.unbind_button.setIcon(window.icons.icon("link_off"))
        self.unbind_button.clicked.connect(self.unbind_sources)
        actions.addWidget(self.bind_button)
        actions.addWidget(self.unbind_button)
        actions.addStretch()
        box.addLayout(actions)
        self.auto_bind = QCheckBox("Auto bind artwork while drawing bones")
        self.auto_bind.setToolTip("Explicitly unbound parts stay unbound until you use Bind.")
        self.auto_bind.toggled.connect(
            lambda enabled: setattr(window.viewmodel.rig, "auto_bind_artwork", enabled)
        )
        box.addWidget(self.auto_bind)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter connections…")
        self.search.setAccessibleName("Filter bindings")
        self.search.textChanged.connect(self.filter_rows)
        box.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Source", "Connection", "Target", "Enabled / group"])
        self.tree.setRootIsDecorated(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setAlternatingRowColors(True)
        self.tree.header().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.setAccessibleName("Grouped bindings")
        self.tree.itemSelectionChanged.connect(self.update_buttons)
        box.addWidget(self.tree, 1)
        footer = QHBoxLayout()
        self.remove_button = QPushButton("Unbind selected connections")
        self.remove_button.setIcon(window.icons.icon("link_off"))
        self.remove_button.clicked.connect(self.remove_rows)
        footer.addWidget(self.remove_button)
        footer.addStretch()
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        footer.addWidget(self.close_button)
        box.addLayout(footer)
        self.status = QLabel()
        self.status.setWordWrap(True)
        box.addWidget(self.status)
        window.viewmodel.changed.connect(self.refresh)
        window.viewmodel.scene.changed.connect(self.selection_changed)
        window.viewmodel.rig.changed.connect(self.selection_changed)
        self.source.currentIndexChanged.connect(self.update_buttons)
        self.target.currentIndexChanged.connect(self.update_buttons)
        self.refresh(force=True)
        self.capture_selection()

    def selection_changed(self) -> None:
        """Show current selectable sources without replacing explicit source choices."""
        if self.isVisible():
            self.update_buttons()

    def capture_selection(self) -> None:
        """Capture actual scene selection, never a hidden first-part fallback."""
        vm = self.host.viewmodel
        service = BindingService(vm.documents)
        records = service.records() if vm.documents.project else {}
        keys = vm.scene.selected or vm.rig.selected
        self.sources = tuple(
            k for k in keys if isinstance(records.get(k), (Bone, Group, SceneObject))
        )
        bones = [k for k in self.sources if isinstance(records[k], Bone)]
        artwork = [k for k in self.sources if k not in bones]
        if artwork and bones:
            self.sources = tuple(artwork)
            self.target.setCurrentIndex(max(0, self.target.findData(bones[0])))
        self.refresh(force=True)
        self.source.setCurrentIndex(0)
        self.update_buttons()

    def source_ids(self) -> tuple[str, ...]:
        """Return captured multi-selection or the explicitly chosen single source."""
        key = self.source.currentData()
        return (str(key),) if key else self.sources

    def refresh(self, *, force: bool = False) -> None:
        """Refresh relationships while preserving filter, selection and scroll position."""
        if not force and not self.isVisible():
            return
        vm = self.host.viewmodel
        if self.document is not vm.documents:
            self.document, self.sources = vm.documents, ()
        selected = {item.data(0, Qt.ItemDataRole.UserRole) for item in self.tree.selectedItems()}
        selected_groups = {
            tuple(item.data(0, Qt.ItemDataRole.UserRole + 1))
            for item in self.tree.selectedItems()
            if item.data(0, Qt.ItemDataRole.UserRole + 1)
        }
        expanded = {}
        for i in range(self.tree.topLevelItemCount()):
            folder = self.tree.topLevelItem(i)
            assert folder is not None
            expanded[tuple(folder.data(0, Qt.ItemDataRole.UserRole + 1))] = folder.isExpanded()
        scroll = self.tree.verticalScrollBar().value()
        service = BindingService(vm.documents)
        scope = self.host.object_edit.ids if self.host.object_edit.active else None
        records = (
            {k: value for k, value in service.records().items() if scope is None or k in scope}
            if vm.documents.project
            else {}
        )
        names = {k: record.name for k, record in records.items()}
        if vm.documents.project:
            names.update({m.id: m.name for m in service.scene.meshes})
        self.sources = tuple(k for k in self.sources if k in records)
        for combo, is_source in ((self.source, True), (self.target, False)):
            current = combo.currentData()
            with QSignalBlocker(combo):
                combo.clear()
                if is_source:
                    label = ", ".join(names[k] for k in self.sources) or "Select parts in the scene"
                    combo.addItem(f"Scene selection · {label}", None)
                for key, entry in records.items():
                    if isinstance(entry, (Bone, Group, SceneObject)):
                        kind = (
                            "Bone"
                            if isinstance(entry, Bone)
                            else "Folder"
                            if isinstance(entry, Group)
                            else "Artwork"
                        )
                        combo.addItem(f"{entry.name} · {kind} · {key[:8]}", key)
                index = combo.findData(current)
                combo.setCurrentIndex(max(0, index))
        with QSignalBlocker(self.tree):
            self.tree.clear()
            rules = {c.id: c for c in service.scene.constraints} if vm.documents.project else {}
            stages = {d.id: d for d in service.scene.deformers} if vm.documents.project else {}
            folders = {}
            for group in service.groups(scope) if vm.documents.project else ():
                endpoints = tuple(
                    dict.fromkeys(key for row in group for key in (row.target, row.source) if key)
                )
                identity = tuple(sorted(row.id for row in group))
                labels = tuple(dict.fromkeys(names.get(key, key[:8]) for key in endpoints))
                label = " + ".join(labels[:2])
                if len(labels) > 2:
                    label += f" + {len(labels) - 2} more"
                folder = QTreeWidgetItem([label, f"{len(group)} connections", "", ""])
                folder.setToolTip(0, "\n".join(labels))
                folder.setIcon(0, self.host.icons.icon("folder"))
                folder.setData(0, Qt.ItemDataRole.UserRole + 1, identity)
                self.tree.addTopLevelItem(folder)
                folder.setExpanded(expanded.get(identity, True))
                folder.setSelected(identity in selected_groups)
                for row in group:
                    folders[row.id] = folder
            for binding in service.relationships(scope) if vm.documents.project else ():
                rule = rules.get(binding.id.removeprefix("constraint:"))
                state = "Enabled"
                if rule:
                    state = "Enabled" if rule.enabled else "Disabled"
                    if rule.kind == "spring":
                        state += f" · {rule.extra.get('spring_group', 'Default')}"
                elif binding.kind == "Spring anchor":
                    state = str(records[binding.source].extra.get("spring_group", "Default"))
                elif binding.kind == "Skin":
                    stage = stages[binding.id.split(":")[1]]
                    state = "Enabled" if stage.enabled else "Disabled"
                item = QTreeWidgetItem(
                    [
                        names.get(binding.source, binding.source[:8]),
                        binding.kind,
                        names.get(
                            binding.target or "", binding.target[:8] if binding.target else "World"
                        ),
                        state,
                    ]
                )
                item.setData(0, Qt.ItemDataRole.UserRole, binding.id)
                item.setToolTip(0, binding.source)
                item.setToolTip(2, binding.target or "World")
                folders[binding.id].addChild(item)
                item.setSelected(binding.id in selected)
        self.tree.verticalScrollBar().setValue(scroll)
        with QSignalBlocker(self.auto_bind):
            self.auto_bind.setChecked(vm.rig.auto_bind_artwork)
        self.filter_rows()
        self.update_buttons()

    def filter_rows(self) -> None:
        """Filter the complete scene list without deleting or collapsing hidden connections."""
        query = self.search.text().casefold().strip()
        for i in range(self.tree.topLevelItemCount()):
            folder = self.tree.topLevelItem(i)
            assert folder is not None
            group_match = bool(query) and query in folder.text(0).casefold()
            matches = False
            for j in range(folder.childCount()):
                item = folder.child(j)
                assert item is not None
                visible = (
                    not query
                    or group_match
                    or any(query in item.text(c).casefold() for c in range(4))
                )
                item.setHidden(not visible)
                matches |= visible
            folder.setHidden(not matches)
            if query and matches:
                folder.setExpanded(True)

    def update_buttons(self) -> None:
        """Keep missing-source and no-document operations visibly unavailable."""
        available = bool(self.host.viewmodel.documents.project)
        self.bind_button.setEnabled(
            available and bool(self.source_ids()) and bool(self.target.currentData())
        )
        self.unbind_button.setEnabled(available and bool(self.source_ids()))
        self.remove_button.setEnabled(available and bool(self.tree.selectedItems()))

    def bind_sources(self) -> None:
        """Use the canonical transaction for all supported endpoint types."""
        keys, target, rigid = (
            self.source_ids(),
            str(self.target.currentData() or ""),
            self.rigid.isChecked(),
        )
        self.host.viewmodel.scene.run(
            lambda _: BindingService(self.document).bind(keys, target, rigid=rigid)
        )
        self.status.setText(self.host.viewmodel.scene.error)

    def unbind_sources(self) -> None:
        """Release captured sources with bone physics cleanup and one undo transaction."""
        keys = self.source_ids()
        self.host.viewmodel.scene.run(lambda _: BindingService(self.document).unbind(keys))
        self.status.setText(self.host.viewmodel.scene.error)

    def remove_rows(self) -> None:
        """Capture stable relationship IDs before the ensuing model refresh destroys Qt items."""
        keys = tuple(
            dict.fromkeys(
                key
                for item in self.tree.selectedItems()
                for key in (
                    (item.data(0, Qt.ItemDataRole.UserRole),)
                    if item.data(0, Qt.ItemDataRole.UserRole)
                    else item.data(0, Qt.ItemDataRole.UserRole + 1) or ()
                )
            )
        )
        self.host.viewmodel.scene.run(
            lambda _: BindingService(self.document).remove_relationships(keys)
        )
        self.status.setText(self.host.viewmodel.scene.error)
