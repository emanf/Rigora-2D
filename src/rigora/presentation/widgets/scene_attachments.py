"""Guided Scene pickup/release tools, reusable grip editing and a searchable link overview."""

import math
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QEvent, QObject, QSignalBlocker, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rigora.domain.scene_attachments import point_matrix
from rigora.presentation.viewmodels.scene_attachments import AttachmentViewModel
from rigora.presentation.widgets.window_frame import CustomDialog

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


def coordinate(name: str, *, angle: bool = False) -> QDoubleSpinBox:
    """Use bounded, named numeric controls shared by offsets and local grip registration."""
    field = QDoubleSpinBox()
    field.setRange(-1e7, 1e7)
    field.setDecimals(2)
    field.setSuffix("°" if angle else "")
    field.setAccessibleName(name)
    return field


class AttachmentPointsDialog(CustomDialog):
    """Edit reusable local grip definitions without entering rig-binding operations."""

    def __init__(self, model: AttachmentViewModel, owner: str, parent: QWidget) -> None:
        """Keep point identity stable when renaming or moving a definition."""
        super().__init__(parent, "Attachment points")
        self.model, self.owner = model, owner
        self.resize(440, 400)
        box = QVBoxLayout(self.content)
        note = QLabel(
            "A grip marks where another object connects. Coordinates are local to this object "
            "or bone. A hand also has a ready-to-use Grip."
        )
        note.setWordWrap(True)
        box.addWidget(note)
        form = QFormLayout()
        self.points = QComboBox()
        form.addRow("Saved point", self.points)
        self.name = QLineEdit("Grip")
        form.addRow("Name", self.name)
        self.offset_x, self.offset_y, self.angle = (
            coordinate("Grip X"),
            coordinate("Grip Y"),
            coordinate("Grip angle", angle=True),
        )
        form.addRow("X", self.offset_x)
        form.addRow("Y", self.offset_y)
        form.addRow("Rotation", self.angle)
        box.addLayout(form)
        actions = QHBoxLayout()
        save = QPushButton("Save point")
        save.clicked.connect(self.save)
        remove = QPushButton("Remove point")
        remove.clicked.connect(self.remove)
        actions.addWidget(save)
        actions.addWidget(remove)
        box.addLayout(actions)
        self.status = QLabel()
        self.status.setWordWrap(True)
        box.addWidget(self.status)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        box.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        self.points.currentIndexChanged.connect(self.load)
        self.refresh()

    def refresh(self) -> None:
        """Refresh owner-local definitions without confusing built-in points with editable ones."""
        if self.owner not in self.model.service.records():
            self.close()
            return
        selected = self.points.currentData()
        with QSignalBlocker(self.points):
            self.points.clear()
            self.points.addItem("New point…", "")
            for p in self.model.service.record(self.owner).extra.get("attachment_points", ()):
                self.points.addItem(p["name"], p["id"])
            self.points.setCurrentIndex(max(0, self.points.findData(selected)))

    def load(self) -> None:
        """Inspect the actual selected point, keeping affine detail untouched until saved."""
        if self.owner not in self.model.service.records():
            self.close()
            return
        identity = self.points.currentData()
        record = self.model.service.record(self.owner)
        point = next(
            (p for p in record.extra.get("attachment_points", ()) if p["id"] == identity), None
        )
        self.name.setText(point["name"] if point else "Grip")
        matrix = point_matrix(record, identity or "")
        self.offset_x.setValue(matrix[4])
        self.offset_y.setValue(matrix[5])
        self.angle.setValue(math.degrees(math.atan2(matrix[1], matrix[0])))

    def save(self) -> None:
        """Create or update a named point as one canonical Undo step."""
        identity = self.points.currentData() or ""
        saved: list[str] = []
        self.model.run(
            lambda s: saved.append(
                s.add_point(
                    self.owner,
                    self.name.text(),
                    identity=identity,
                    x=self.offset_x.value(),
                    y=self.offset_y.value(),
                    rotation=self.angle.value(),
                )
            ),
            "Grip point saved.",
        )
        self.status.setText(self.model.status)
        self.refresh()
        if saved:
            self.points.setCurrentIndex(self.points.findData(saved[0]))

    def remove(self) -> None:
        """Refuse removal of points used by setup or animation instead of leaving broken links."""
        identity = self.points.currentData()
        if identity:
            self.model.run(lambda s: s.remove_point(self.owner, identity), "Grip point removed.")
            self.status.setText(self.model.status)
            self.refresh()


class SceneAttachmentsDialog(CustomDialog):
    """A guided attachment card beside a live, searchable list of Scene relationships."""

    def __init__(
        self, window: "MainWindow", *, owner: str = "", frame: float | None = None
    ) -> None:
        """Show readable targets and explicit setup/key timing without editing on target picks."""
        super().__init__(window, "Scene attachments")
        self.host = window
        self.model = AttachmentViewModel(window.viewmodel, self)
        initial_owner = owner or self.model.selected_object()
        self.document = window.viewmodel.documents
        self.context = self.context_key()
        window.viewmodel.playback.pause()
        self.picking = False
        self._source_revision: Any = None
        self.resize(880, 760)
        self.setMinimumSize(640, 420)
        box = QVBoxLayout(self.content)
        note = QLabel(
            "Attach a prop to a hand or object. Add keys to pick it up, pass it on, or release it."
        )
        note.setWordWrap(True)
        box.addWidget(note)
        split = QSplitter()
        box.addWidget(split, 1)
        overview = QWidget()
        left = QVBoxLayout(overview)
        left.setContentsMargins(0, 0, 8, 0)
        left.addWidget(QLabel("Scene relationships"))
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Search attachments…")
        self.filter.textChanged.connect(self.filter_rows)
        left.addWidget(self.filter)
        self.links = QTreeWidget()
        self.links.setHeaderLabels(["Object", "Follows"])
        self.links.setRootIsDecorated(False)
        self.links.setAccessibleName("Scene attachment relationships")
        self.links.itemClicked.connect(self.select_link)
        left.addWidget(self.links, 1)
        split.addWidget(overview)
        card = QWidget()
        right = QVBoxLayout(card)
        right.setContentsMargins(8, 0, 0, 0)
        form = QFormLayout()
        self.source = QComboBox()
        self.source.setAccessibleName("Object to attach")
        form.addRow("1  Object to attach", self.source)
        self.current = QLabel()
        self.current.setWordWrap(True)
        form.addRow("Currently follows", self.current)
        self.source_point = QComboBox()
        form.addRow("Object's grip", self.source_point)
        self.points_button = QPushButton("Edit grip points…")
        self.points_button.setIcon(window.icons.icon("my_location"))
        self.points_button.clicked.connect(self.edit_points)
        form.addRow("", self.points_button)
        right.addLayout(form)
        target_bar = QHBoxLayout()
        target_bar.addWidget(QLabel("2  Choose what it follows"), 1)
        self.pick = QPushButton("Pick in scene")
        self.pick.setCheckable(True)
        self.pick.setIcon(window.icons.icon("ads_click"))
        self.pick.toggled.connect(self.arm_pick)
        target_bar.addWidget(self.pick)
        right.addLayout(target_bar)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search objects, hands and grip points…")
        self.search.textChanged.connect(self.filter_targets)
        right.addWidget(self.search)
        self.targets = QTreeWidget()
        self.targets.setHeaderHidden(True)
        self.targets.setMinimumHeight(130)
        self.targets.setAccessibleName("Attachment target and grip")
        self.targets.itemSelectionChanged.connect(self.update_target_caption)
        right.addWidget(self.targets, 1)
        self.target_caption = QLabel("Choose a target above, or pick it directly in the scene.")
        self.target_caption.setWordWrap(True)
        right.addWidget(self.target_caption)
        self.target_points_button = QPushButton("Edit target's grip points…")
        self.target_points_button.setIcon(window.icons.icon("my_location"))
        self.target_points_button.clicked.connect(self.edit_target_points)
        right.addWidget(self.target_points_button)
        settings = QFormLayout()
        self.placement = QComboBox()
        self.placement.addItems(["Keep current position", "Snap grips together"])
        settings.addRow("Placement", self.placement)
        timing = QHBoxLayout()
        self.timing = QComboBox()
        self.timing.addItems(["Whole scene (setup)", "At this frame (key)"])
        self.frame_input = coordinate("Attachment frame")
        self.frame_input.setRange(0, 1e7)
        self.frame_input.setValue(self.document.animation.pose.frame if frame is None else frame)
        self.timing.setCurrentIndex(0 if frame is None else 1)
        self.frame_input.setEnabled(frame is not None)
        self.timing.currentIndexChanged.connect(
            lambda index: self.frame_input.setEnabled(index == 1)
        )
        self.timing.currentIndexChanged.connect(self.load_state)
        timing.addWidget(self.timing, 1)
        timing.addWidget(self.frame_input)
        settings.addRow("3  Apply when", timing)
        self.rotation = QCheckBox("Rotation")
        self.scale = QCheckBox("Scale")
        self.rotation.setChecked(True)
        self.scale.setChecked(True)
        inherit = QHBoxLayout()
        inherit.addWidget(self.rotation)
        inherit.addWidget(self.scale)
        settings.addRow("Follow target", inherit)
        right.addLayout(settings)
        buttons = QHBoxLayout()
        self.attach_button = QPushButton("Attach object")
        self.attach_button.setIcon(window.icons.icon("link"))
        self.attach_button.clicked.connect(self.attach)
        self.release_button = QPushButton("Release object")
        self.release_button.setIcon(window.icons.icon("link_off"))
        self.release_button.clicked.connect(self.release)
        buttons.addWidget(self.attach_button)
        buttons.addWidget(self.release_button)
        right.addLayout(buttons)
        self.fine_alignment = QCheckBox("Fine alignment")
        right.addWidget(self.fine_alignment)
        self.offsets = QWidget()
        self.fine_alignment.toggled.connect(self.offsets.setVisible)
        offset_form = QFormLayout(self.offsets)
        offset_form.setContentsMargins(0, 4, 0, 0)
        row = QHBoxLayout()
        self.offset_x, self.offset_y, self.angle = (
            coordinate("Attachment offset X"),
            coordinate("Attachment offset Y"),
            coordinate("Attachment offset rotation", angle=True),
        )
        for caption, field in (("X", self.offset_x), ("Y", self.offset_y), ("°", self.angle)):
            field.setMinimumWidth(70)
            field.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            row.addWidget(QLabel(caption))
            row.addWidget(field)
        offset_form.addRow("Grip offset", row)
        self.save_offset = QPushButton("Apply offset")
        self.save_offset.clicked.connect(self.apply_offset)
        offset_form.addRow("", self.save_offset)
        right.addWidget(self.offsets)
        self.editor_scroll = QScrollArea()
        self.editor_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.editor_scroll.setWidgetResizable(True)
        self.editor_scroll.setWidget(card)
        split.addWidget(self.editor_scroll)
        split.setSizes([285, 565])
        self.status = QLabel(
            "Use At this frame for pickups. Whole scene replaces this object's attachment keys."
        )
        self.status.setWordWrap(True)
        box.addWidget(self.status)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        box.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        self.source.currentIndexChanged.connect(self.source_changed)
        self.frame_input.valueChanged.connect(self.load_state)
        self.model.changed.connect(self.show_status)
        window.viewmodel.changed.connect(self.refresh)
        window.viewmodel.playback.changed.connect(self.load_state)
        self.refresh()
        wanted = initial_owner
        if wanted:
            self.source.setCurrentIndex(max(0, self.source.findData(wanted)))
        self.source_changed()

    def refresh(self) -> None:
        """Rebuild discovery only on a project revision, preserving the source and target choice."""
        if self.host.viewmodel.documents is not self.document or not self.document.project:
            self.close()
            return
        if self.context_key() != self.context:
            if self.model.applying:
                self.context = self.context_key()
            else:
                self.close()
                return
        if self._source_revision is self.document.project:
            self.load_state()
            return
        self._source_revision = self.document.project
        source = self.source.currentData()
        objects = self.model.objects()
        if source and source not in dict(objects):
            self.close()
            return
        with QSignalBlocker(self.source):
            self.source.clear()
            for key, name in objects:
                self.source.addItem(name, key)
            self.source.setCurrentIndex(max(0, self.source.findData(source)))
        self.links.clear()
        for key, name in self.model.objects():
            state = self.model.state(key)
            row = QTreeWidgetItem([name, self.model.service.target_label(state)])
            row.setData(0, Qt.ItemDataRole.UserRole, key)
            row.setIcon(0, self.host.icons.icon("link" if state.target_id else "widgets"))
            self.links.addTopLevelItem(row)
        self.filter_rows()
        self.source_changed()

    def context_key(self) -> tuple[str, str | None, str | None]:
        """Identify the Scene/clip/editor being edited, independently of immutable revisions."""
        return (
            self.document.scene.id,
            self.document.animation_context,
            self.document.selected_clip_id,
        )

    def refresh_icons(self) -> None:
        """Honor timeline editor artwork/theme refreshes without rebuilding pending choices."""
        for button, name in (
            (self.points_button, "my_location"),
            (self.target_points_button, "my_location"),
            (self.pick, "ads_click"),
            (self.attach_button, "link"),
            (self.release_button, "link_off"),
        ):
            button.setIcon(self.host.icons.icon(name))
        records = self.model.service.records() if self.document.project else {}
        pending = [self.targets.topLevelItem(i) for i in range(self.targets.topLevelItemCount())]
        while pending:
            row = pending.pop()
            if row is None:
                continue
            target, point = row.data(0, Qt.ItemDataRole.UserRole)
            name = (
                "my_location"
                if point
                else "device_hub"
                if hasattr(records.get(target), "length")
                else "widgets"
            )
            row.setIcon(0, self.host.icons.icon(name))
            pending.extend(row.child(i) for i in range(row.childCount()))

    def source_changed(self) -> None:
        """Offer grips and targets for the selected source without changing any relationship."""
        owner = self.source.currentData()
        if not owner:
            self.attach_button.setEnabled(False)
            self.release_button.setEnabled(False)
            return
        old = self.targets.currentItem()
        previous = old.data(0, Qt.ItemDataRole.UserRole) if old else None
        self.source_point.clear()
        for identity, name in self.model.service.point_choices(owner):
            self.source_point.addItem(name, identity)
        with QSignalBlocker(self.targets):
            self.targets.clear()
            rows = {}
            for key, name, parent in self.model.targets(owner):
                record = self.model.service.record(key)
                if self.model.service.locked(key):
                    continue
                row = rows[key] = QTreeWidgetItem([name])
                row.setData(0, Qt.ItemDataRole.UserRole, (key, ""))
                row.setIcon(
                    0,
                    self.host.icons.icon("device_hub" if hasattr(record, "length") else "widgets"),
                )
                if parent in rows:
                    rows[parent].addChild(row)
                else:
                    self.targets.addTopLevelItem(row)
                for identity, caption in self.model.service.point_choices(key):
                    if not identity:
                        continue
                    point = QTreeWidgetItem([caption])
                    point.setIcon(0, self.host.icons.icon("my_location"))
                    point.setData(0, Qt.ItemDataRole.UserRole, (key, identity))
                    row.addChild(point)
                    if (key, identity) == previous:
                        self.targets.setCurrentItem(point)
                row.setExpanded(parent == "")
                if (key, "") == previous:
                    self.targets.setCurrentItem(row)
        self.filter_targets()
        self.load_state()
        if not self.targets.currentItem():
            state = self.model.state(owner, self.when())
            if state.target_id:
                self.select_target(state.target_id, state.point)

    def load_state(self) -> None:
        """Show a readable live attachment card and its captured offset without seeking."""
        owner = self.source.currentData()
        if not owner or self.host.viewmodel.documents is not self.document:
            return
        state = self.model.state(
            owner, self.frame_input.value() if self.timing.currentIndex() else None
        )
        self.current.setText(self.model.service.target_label(state))
        for index in range(self.links.topLevelItemCount()):
            row = self.links.topLevelItem(index)
            if row:
                link_state = self.model.state(row.data(0, Qt.ItemDataRole.UserRole), self.when())
                row.setText(1, self.model.service.target_label(link_state))
        self.fine_alignment.setVisible(state.target_id is not None)
        self.offsets.setVisible(state.target_id is not None and self.fine_alignment.isChecked())
        self.release_button.setEnabled(state.target_id is not None)
        self.rotation.setChecked(state.inherit_rotation)
        self.scale.setChecked(state.inherit_scale)
        self.source_point.setCurrentIndex(max(0, self.source_point.findData(state.source_point)))
        self.offset_x.setValue(state.offset[4])
        self.offset_y.setValue(state.offset[5])
        self.angle.setValue(math.degrees(math.atan2(state.offset[1], state.offset[0])))
        self.update_target_caption()

    def update_target_caption(self) -> None:
        """Keep the exact target/grip visible even when its tree branch is scrolled away."""
        row = self.targets.currentItem()
        parts: list[str] = []
        while row:
            parts.insert(0, row.text(0))
            row = row.parent()
        self.target_caption.setText(
            " / ".join(parts) or "Choose a target above, or pick it in the scene."
        )
        self.attach_button.setEnabled(bool(parts and self.source.currentData()))
        self.target_points_button.setEnabled(bool(parts))

    def when(self) -> float | None:
        """Distinguish setup from animation explicitly, independent of the main Auto Key button."""
        return self.frame_input.value() if self.timing.currentIndex() else None

    def attach(self) -> None:
        """Commit the chosen setup or keyed relationship; target selection only inspects."""
        row = self.targets.currentItem()
        if row and self.source.currentData():
            target, point = row.data(0, Qt.ItemDataRole.UserRole)
            self.model.attach(
                self.source.currentData(),
                target,
                point=point,
                source_point=self.source_point.currentData() or "",
                snap=self.placement.currentIndex() == 1,
                frame=self.when(),
                inherit_rotation=self.rotation.isChecked(),
                inherit_scale=self.scale.isChecked(),
            )

    def release(self) -> None:
        """Release only the chosen Scene object, keeping its evaluated pose and complete rig."""
        if self.source.currentData():
            self.model.detach(self.source.currentData(), self.when())

    def apply_offset(self) -> None:
        """Save explicit offset edits using the same setup/key mode as Attach and Release."""
        owner = self.source.currentData()
        if owner:
            self.model.run(
                lambda s: s.edit_offset(
                    owner,
                    x=self.offset_x.value(),
                    y=self.offset_y.value(),
                    rotation=self.angle.value(),
                    frame=self.when(),
                ),
                "Grip offset saved.",
            )

    def edit_points(self) -> None:
        """Open local grip registration for this prop; bone grips are also available from Rig."""
        owner = self.source.currentData()
        if owner:
            self.point_editor = AttachmentPointsDialog(self.model, owner, self)
            self.point_editor.show()

    def edit_target_points(self) -> None:
        """Register a grip directly on a picked hand or target Object without changing modes."""
        row = self.targets.currentItem()
        if row:
            target, _ = row.data(0, Qt.ItemDataRole.UserRole)
            self.point_editor = AttachmentPointsDialog(self.model, target, self)
            self.point_editor.show()

    def select_link(self, row: QTreeWidgetItem, column: int) -> None:
        """Inspect a relationship without modifying Scene selection or a target's pose."""
        self.source.setCurrentIndex(self.source.findData(row.data(0, Qt.ItemDataRole.UserRole)))

    def filter_rows(self) -> None:
        """Search source and destination names in the current overview."""
        text = self.filter.text().casefold()
        for i in range(self.links.topLevelItemCount()):
            row = self.links.topLevelItem(i)
            if row:
                row.setHidden(text not in (row.text(0) + " " + row.text(1)).casefold())

    def filter_targets(self) -> None:
        """Retain matching ancestors when searching hands, props or custom named grips."""
        text = self.search.text().casefold()

        def visit(row: QTreeWidgetItem | None, path: str = "") -> bool:
            if row is None:
                return False
            path += " " + row.text(0).casefold()
            children = [visit(row.child(i), path) for i in range(row.childCount())]
            visible = text in path or any(children)
            row.setHidden(not visible)
            if text and visible:
                row.setExpanded(True)
            return visible

        for i in range(self.targets.topLevelItemCount()):
            visit(self.targets.topLevelItem(i))

    def show_status(self) -> None:
        """Expose actionable service errors and refresh only after a completed command."""
        self.status.setText(self.model.status)
        self.refresh()

    def arm_pick(self, enabled: bool) -> None:
        """Temporarily intercept one Scene click; Esc cancels without editing or selecting."""
        self.picking = enabled
        viewport = self.host.viewport
        if enabled:
            viewport.installEventFilter(self)
            viewport.setCursor(Qt.CursorShape.CrossCursor)
            self.status.setText("Click a visible bone or object in the Scene. Esc cancels.")
        else:
            viewport.removeEventFilter(self)
            viewport.refresh_cursor()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Consume target picking before transform tools can start a drag."""
        if self.picking:
            if isinstance(event, QKeyEvent) and event.key() == Qt.Key.Key_Escape:
                self.pick.setChecked(False)
                return True
            if event.type() == QEvent.Type.MouseMove:
                self.host.viewport.setCursor(Qt.CursorShape.CrossCursor)
                return True
            if (
                event.type() == QEvent.Type.MouseButtonPress
                and isinstance(event, QMouseEvent)
                and event.button() == Qt.MouseButton.LeftButton
            ):
                viewport = self.host.viewport
                point = viewport.scene_point(event.position())
                key = viewport.bone_at(event.position()) if viewport.show_bones else None
                key = key or self.host.scene_workspace.pick(point)
                if key and not self.model.service.locked(key):
                    self.choose_target(key)
                return True
            if event.type() == QEvent.Type.MouseButtonRelease:
                return True
        return super().eventFilter(watched, event)

    def choose_target(self, key: str) -> None:
        """Choose a hand's built-in grip when available; leave applying the link explicit."""
        if self.select_target(key, "@grip"):
            self.pick.setChecked(False)
            self.status.setText("Target selected. Click Attach object to apply.")
        else:
            self.status.setText(
                "Choose another object or its bone; an object cannot follow itself."
            )

    def select_target(self, key: str, point: str = "") -> bool:
        """Select an exact saved target, falling back to its Object or ordinary origin."""
        from rigora.application_services.characters import CharacterService

        rows = []
        pending = [self.targets.topLevelItem(i) for i in range(self.targets.topLevelItemCount())]
        while pending:
            row = pending.pop()
            if row is None:
                continue
            rows.append(row)
            pending.extend(row.child(i) for i in range(row.childCount()))
        found = [r for r in rows if r.data(0, Qt.ItemDataRole.UserRole)[0] == key]
        if not found:
            root = CharacterService(self.document).object_root(key)
            found = [
                r
                for r in rows
                if r.data(0, Qt.ItemDataRole.UserRole)[0] == (root.id if root else key)
            ]
        if found:
            row = next(
                (r for r in found if r.data(0, Qt.ItemDataRole.UserRole)[1] == point),
                next((r for r in found if not r.data(0, Qt.ItemDataRole.UserRole)[1]), found[0]),
            )
            self.search.clear()
            self.targets.setCurrentItem(row)
            self.targets.scrollToItem(row)
            return True
        return False

    def closeEvent(self, event: Any) -> None:
        """Always restore ordinary viewport editing when the modeless card closes."""
        self.pick.setChecked(False)
        super().closeEvent(event)

    def hideEvent(self, event: Any) -> None:
        """Cancel scene picking for Escape/reject as well as ordinary window closure."""
        self.pick.setChecked(False)
        super().hideEvent(event)
