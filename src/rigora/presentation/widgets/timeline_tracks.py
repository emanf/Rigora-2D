"""Object-first track discovery with compound property rows and session-scoped drags."""

import json
from collections.abc import Sequence
from functools import partial
from typing import TYPE_CHECKING

from PySide6.QtCore import QMimeData, QModelIndex, QSignalBlocker, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rigora.application_services.animation_editing import scalar_paths
from rigora.application_services.characters import CharacterService
from rigora.domain.entities import Bone, Camera, Entity, Group
from rigora.domain.project import ProjectError
from rigora.presentation.widgets.window_frame import CustomDialog

if TYPE_CHECKING:
    from rigora.presentation.widgets.timeline import Timeline

CHANNEL_MIME = "application/x-rigora-animation-channels"
MAX_CHANNELS = 100_000
MAX_CHANNEL_BYTES = 16 * 1024**2


def row_channels(row: QTreeWidgetItem | None) -> tuple[tuple[str, str], ...]:
    """Resolve a property or group to real canonical owner/path identities."""
    if row is None:
        return ()
    members = row.data(0, Qt.ItemDataRole.UserRole + 3)
    if members is not None:
        return tuple(members)
    channel = row.data(0, Qt.ItemDataRole.UserRole)
    if channel:
        return (channel,)
    return tuple(key for i in range(row.childCount()) for key in row_channels(row.child(i)))


def decode_channels(mime: QMimeData, session: str) -> tuple[tuple[str, str], ...]:
    """Reject stale/cross-document or oversized drags before any command is attempted."""
    raw = bytes(mime.data(CHANNEL_MIME).data())
    if not raw or len(raw) > MAX_CHANNEL_BYTES:
        raise ProjectError("Animation channel drag is missing or too large.")
    try:
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get("session") != session:
            raise ProjectError("Drag channels from the active project's track picker.")
        channels = data.get("channels")
        if not isinstance(channels, list) or not 1 <= len(channels) <= MAX_CHANNELS:
            raise ProjectError("Choose between 1 and 100,000 animation channels.")
        if any(
            not isinstance(c, list) or len(c) != 2 or any(not isinstance(p, str) for p in c)
            for c in channels
        ):
            raise ProjectError("Invalid animation channel identities.")
        return tuple(dict.fromkeys((c[0], c[1]) for c in channels))
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ProjectError(f"Cannot read animation channel drag: {error}") from error


class ChannelTree(QTreeWidget):
    """Copy supported channels or entire groups to the timeline without executing drag content."""

    def __init__(self, parent: QWidget) -> None:
        """Configure native extended selection and copy-only drag behavior."""
        super().__init__(parent)
        self.session = ""
        self.setHeaderLabels(["Property", "Status", ""])
        self.setRootIsDecorated(False)
        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setDragEnabled(True)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setAccessibleName("Animation properties · add a row or drag it onto the timeline")

    def mimeTypes(self) -> list[str]:
        """Advertise a data-only format owned by this editor."""
        return [CHANNEL_MIME]

    def mimeData(self, items: Sequence[QTreeWidgetItem]) -> QMimeData:
        """Serialize bounded channel references with the source document session identity."""
        mime = QMimeData()
        channels = tuple(dict.fromkeys(key for row in items for key in row_channels(row)))
        if 1 <= len(channels) <= MAX_CHANNELS:
            mime.setData(
                CHANNEL_MIME, json.dumps({"session": self.session, "channels": channels}).encode()
            )
        return mime


class TrackPicker(CustomDialog):
    """Choose a scene object, then add its complete animation properties in one click."""

    channels_chosen = Signal(object)

    def __init__(self, timeline: "Timeline") -> None:
        """Use the shared window chrome and canonical catalog, never a separate animation schema."""
        super().__init__(timeline, "Add animation tracks")
        self.timeline = timeline
        self.records: dict[str, Entity] = {}
        self.object_rows: dict[str, QTreeWidgetItem] = {}
        self.resize(740, 520)
        layout = QVBoxLayout(self.content)
        layout.addWidget(
            QLabel("Choose an object, then click + beside a property to add its track.")
        )
        help_text = QLabel(
            "Add properties or drag them onto a frame. "
            "Animations and appearance choices start at the playhead."
        )
        help_text.setObjectName("Muted")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        split = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(split, 1)
        objects = QWidget()
        object_layout = QVBoxLayout(objects)
        object_layout.setContentsMargins(0, 0, 0, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search objects…")
        self.search.setAccessibleName("Search objects for animation tracks")
        self.search.textChanged.connect(self.filter)
        object_layout.addWidget(self.search)
        self.objects = QTreeWidget()
        self.objects.setHeaderLabels(["Objects"])
        self.objects.setAccessibleName("Objects available for animation tracks")
        self.objects.currentItemChanged.connect(self.populate)
        object_layout.addWidget(self.objects, 1)
        split.addWidget(objects)
        properties = QWidget()
        property_layout = QVBoxLayout(properties)
        property_layout.setContentsMargins(0, 0, 0, 0)
        self.caption = QLabel("Select an object")
        self.caption.setTextFormat(Qt.TextFormat.PlainText)
        self.caption.setWordWrap(True)
        property_layout.addWidget(self.caption)
        self.tree = ChannelTree(self)
        self.tree.itemDoubleClicked.connect(lambda row, column: self.add((row,)))
        self.tree.itemSelectionChanged.connect(self.update_count)
        property_layout.addWidget(self.tree, 1)
        split.addWidget(properties)
        split.setSizes([270, 430])
        self.count = QLabel("Select properties to add")
        self.count.setWordWrap(True)
        self.count.setObjectName("Muted")
        layout.addWidget(self.count)
        footer = QHBoxLayout()
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        footer.addWidget(close)
        footer.addStretch()
        self.add_button = QPushButton("Add selected")
        self.add_button.clicked.connect(lambda: self.add(self.tree.selectedItems()))
        footer.addWidget(self.add_button)
        layout.addLayout(footer)

    def refresh(self, *, prefer_selection: bool = False) -> None:
        """Rebuild actual scene owners, retaining the chosen object after adding a property."""
        service = self.timeline.editor.service
        previous = self.objects.currentItem()
        target = previous.data(0, Qt.ItemDataRole.UserRole) if previous else None
        expanded = {key for key, row in self.object_rows.items() if row.isExpanded()}
        scene = service.scene if service else None
        self.records = {
            record.id: record
            for record in (
                (
                    *scene.groups,
                    *scene.cameras,
                    *scene.objects,
                    *scene.characters,
                    *(b for rig in scene.skeletons for b in rig.bones),
                )
                if scene
                else ()
            )
        }
        if service and service.document.separated_animation:
            document = service.document
            allowed = (
                document.animation_scope
                if document.animation_context
                else (
                    *CharacterService(document).scene_objects(),
                    *(c.id for c in document.scene.cameras),
                )
            )
            self.records = {k: r for k, r in self.records.items() if k in (allowed or ())}
        if prefer_selection or target not in self.records:
            target = next(
                (key for key in self.timeline.editor.focused_owners if key in self.records),
                target,
            )
        if prefer_selection:
            with QSignalBlocker(self.search):
                self.search.clear()
        with QSignalBlocker(self.objects):
            self.objects.clear()
            self.object_rows = {}
            for key, record in self.records.items():
                row = self.object_rows[key] = QTreeWidgetItem([record.name])
                row.setSizeHint(0, QSize(0, 28))
                icon = (
                    "device_hub"
                    if isinstance(record, Bone)
                    else "folder"
                    if isinstance(record, Group)
                    else "image"
                )
                row.setIcon(0, self.timeline.icons.icon(icon))
                row.setData(0, Qt.ItemDataRole.UserRole, key)
                row.setToolTip(0, record.name)
            bone_owners = (
                {b.id: r.extra.get("object_id") for r in scene.skeletons for b in r.bones}
                if scene
                else {}
            )
            contact_owners = (
                {
                    c.target_id: bone_owners.get(c.owner_id)
                    for c in scene.constraints
                    if c.target_id in self.records
                    and self.records[c.target_id].extra.get("studio_floor_plant")
                }
                if scene
                else {}
            )
            for key, row in self.object_rows.items():
                parent = getattr(self.records[key], "parent_id", None)
                if parent is None:
                    parent = (
                        self.records[key].extra.get("object_id")
                        or bone_owners.get(key)
                        or contact_owners.get(key)
                    )
                if self.records[key].extra.get("studio_floor_plant"):
                    row.setToolTip(
                        0,
                        "Standing foot control · follows bone edits; released by walk/run actions",
                    )
                if parent in self.object_rows:
                    self.object_rows[parent].addChild(row)
                else:
                    self.objects.addTopLevelItem(row)
                row.setExpanded(key in expanded)
            chosen = self.object_rows.get(target or "") or self.objects.topLevelItem(0)
            if chosen is not None:
                self.objects.setCurrentItem(chosen)
            parent = chosen.parent() if chosen else None
            while parent:
                parent.setExpanded(True)
                parent = parent.parent()
        self.tree.session = service.document.session_id if service else ""
        self.filter(self.search.text())
        self.populate()

    def populate(self) -> None:
        """Offer complete properties without exposing vertex owners or internal binding data."""
        self.tree.clear()
        self.tree.setRootIsDecorated(False)
        service = self.timeline.editor.service
        selected = self.objects.currentItem()
        owner = self.records.get(selected.data(0, Qt.ItemDataRole.UserRole)) if selected else None
        self.caption.setText(
            owner.name if owner else "Select an object" if self.records else "No objects available"
        )
        if not service or owner is None:
            self.update_count()
            return
        paths = [
            f"transform.{p}"
            for p in ("x", "y", "rotation", "scale_x", "scale_y", "pivot_x", "pivot_y")
        ]
        paths.extend(() if isinstance(owner, Camera) else ("visibility", "opacity"))
        if isinstance(owner, Bone):
            paths.append("length")
        groups: dict[str, list[tuple[str, str]]] = {}
        for channel in service.channels((owner.id, path) for path in paths):
            groups.setdefault(channel.lane, []).append(channel.key)
        local = (
            not service.document.separated_animation
            or service.document.animation_context is not None
        )
        mesh_ids = set(CharacterService(service.document).meshes_for((owner.id,)))
        meshes = [mesh for mesh in service.scene.meshes if mesh.id in mesh_ids]
        if local and any(not vertex.protected for mesh in meshes for vertex in mesh.vertices):
            groups["Mesh Deformation"] = [
                (vertex.id, axis)
                for mesh in meshes
                for vertex in mesh.vertices
                if not vertex.protected
                for axis in ("x", "y")
            ]
        try:
            parameters = service.document.animation.evaluator.deformation.parameters
        except ProjectError:
            parameters = {stage.id: dict(stage.parameters) for stage in service.scene.deformers}
        for stage in service.scene.deformers:
            if stage.owner_id not in mesh_ids or stage.kind in ("skinning", "mesh_sculpt"):
                continue
            values = parameters.get(stage.id, {})
            if stage.kind == "appearance":
                colors = {key: value for key, value in values.items() if key in ("palette", "tint")}
                sections = {"Color": colors}
                if "stroke_width" in values:
                    sections["Outline"] = {"stroke_width": values["stroke_width"]}
            else:
                sections = {
                    f"Deformation · {stage.name}": {
                        key: value
                        for key, value in values.items()
                        if key not in ("bounds", "columns", "rows", "weights", "bind_matrices")
                    }
                }
            for label, values in sections.items():
                for channel in service.channels(
                    (stage.id, path) for path in scalar_paths(values, "parameters")
                ):
                    groups.setdefault(label, []).append(channel.key)
        existing = (
            {(t.owner_id, t.property_path) for t in service.timeline.tracks}
            if service and service.timeline
            else set()
        )
        for label, channels in groups.items():
            row = QTreeWidgetItem([label])
            row.setSizeHint(0, QSize(0, 32))
            self.tree.addTopLevelItem(row)
            members = tuple(dict.fromkeys(channels))
            row.setData(0, Qt.ItemDataRole.UserRole + 3, members)
            row.setToolTip(0, f"Add {label.lower()} animation for {owner.name}")
            count = sum(key in existing for key in members)
            row.setText(
                1, "Added" if count == len(members) else "Partly added" if count else "Available"
            )
            button = QToolButton()
            button.setIconSize(QSize(18, 18))
            button.setIcon(self.timeline.icons.icon("done" if count == len(members) else "add"))
            button.setAccessibleName(f"Add {label} track")
            button.setToolTip("Already added" if count == len(members) else f"Add {label} track")
            button.setEnabled(count < len(members))
            button.clicked.connect(partial(self.add, (row,)))
            self.tree.setItemWidget(row, 2, button)
        self.tree.setColumnWidth(0, 210)
        self.tree.setColumnWidth(1, 100)
        self.tree.setColumnWidth(2, 32)
        if service.document.animation_context is None and not isinstance(owner, Bone):
            self.scene_options(owner)
        self.update_count()

    def scene_options(self, owner: Entity) -> None:
        """Offer three flat action rows; their saved choices open in a separate card grid."""
        from rigora.presentation.widgets.timeline_actions import ACTION_ICONS, ACTION_LABELS

        document = self.timeline.editor.document
        if document is None:
            return
        kinds = (
            ("camera_cut", "camera_motion", "camera_effect")
            if isinstance(owner, Camera)
            else ("motion", "skins", "outfits", "views", "attachment")
        )
        for kind in kinds:
            from rigora.engine.camera_actions import EFFECT_PRESETS, MOTION_PRESETS

            count = (
                len(document.scene.cameras)
                if kind == "camera_cut"
                else len(MOTION_PRESETS)
                if kind == "camera_motion"
                else len(EFFECT_PRESETS)
                if kind == "camera_effect"
                else len(CharacterService(document).motions(owner.id))
                if kind == "motion"
                else 6
                if kind == "views"
                else sum(len(g["variants"]) for g in owner.extra.get(kind, ()))
            )
            row = QTreeWidgetItem(
                [
                    ACTION_LABELS[kind],
                    "Pick up / release"
                    if kind == "attachment"
                    else f"{count} saved"
                    if count
                    else "Create in Object Editor",
                ]
            )
            row.setSizeHint(0, QSize(0, 36))
            row.setFlags(row.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)
            row.setIcon(0, self.timeline.icons.icon(ACTION_ICONS[kind]))
            row.setData(0, Qt.ItemDataRole.UserRole + 6, (owner.id, kind))
            row.setToolTip(
                0, "Choose a saved action from a card grid. No nested tracks are created."
            )
            self.tree.addTopLevelItem(row)
            button = QToolButton()
            button.setIcon(self.timeline.icons.icon("add"))
            button.setAccessibleName(f"Add {ACTION_LABELS[kind]} action")
            button.clicked.connect(partial(self.add, (row,)))
            self.tree.setItemWidget(row, 2, button)

    def update_count(self) -> None:
        """Explain the selected logical properties without exposing scalar implementation rows."""
        count = len(self.tree.selectedItems())
        self.count.setText(f"{count} selected" if count else "Select properties or choices to add")
        self.add_button.setEnabled(bool(count))

    def filter(self, text: str) -> None:
        """Search scene names while retaining matching objects' folder and bone ancestry."""

        def visit(row: QTreeWidgetItem | None, path: str) -> bool:
            """Keep matching branches visible without exposing implementation owners."""
            if row is None:
                return False
            path = f"{path} {row.text(0)}"
            children = [visit(row.child(i), path) for i in range(row.childCount())]
            visible = text.casefold() in path.casefold() or any(children)
            row.setHidden(not visible)
            if text and visible:
                row.setExpanded(True)
            return visible

        for i in range(self.objects.topLevelItemCount()):
            visit(self.objects.topLevelItem(i), "")
        selected = self.objects.currentItem()
        if selected is not None and selected.isHidden():
            self.objects.setCurrentIndex(QModelIndex())

    def add(self, rows: Sequence[QTreeWidgetItem]) -> None:
        """Add actual selected lanes without closing the picker or generating unwanted keys."""
        channels = tuple(dict.fromkeys(key for row in rows for key in row_channels(row)))
        actions = [
            row.data(0, Qt.ItemDataRole.UserRole + 6)
            for row in rows
            if row.data(0, Qt.ItemDataRole.UserRole + 6)
        ]
        if len(actions) > 1:
            self.count.setText(
                "Choose one action type, then select its saved choices in the card grid."
            )
            return
        if channels:
            self.channels_chosen.emit(channels)
        if actions:
            owner, kind = actions[0]
            document = self.timeline.editor.document
            self.timeline.open_action(
                {
                    "owner": owner,
                    "kind": kind,
                    "frame": document.animation.pose.frame if document else 0,
                }
            )
        if self.timeline.editor.error:
            self.count.setText(self.timeline.editor.error)
