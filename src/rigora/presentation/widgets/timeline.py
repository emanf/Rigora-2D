"""Unified transport, hierarchical dope sheet, contextual tween graphs and reusable clips."""

from collections.abc import Callable
from functools import partial
from typing import Any, cast

from PySide6.QtCore import QSignalBlocker, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QBrush, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rigora.application_services.animation_channels import AnimationChannel
from rigora.application_services.characters import CharacterService
from rigora.application_services.timeline_structure import row_structure
from rigora.domain.entities import (
    Bone,
    Camera,
    Constraint,
    Deformer,
    Group,
    SceneObject,
    Track,
    Vertex,
    nested_records,
)
from rigora.domain.project import ProjectError
from rigora.engine.sampling import CompiledTrack
from rigora.engine.transition_curves import TransitionCurve, curve_presets
from rigora.presentation.icons import IconProvider
from rigora.presentation.menu_labels import menu_text
from rigora.presentation.viewmodels.animation_editor import AnimationEditorViewModel
from rigora.presentation.viewmodels.playback import PlaybackViewModel
from rigora.presentation.widgets.clip_editor import ClipEditor, numeric
from rigora.presentation.widgets.curve_editor import CurveEditor
from rigora.presentation.widgets.key_canvas import KeyCanvas
from rigora.presentation.widgets.timeline_ruler import RULER_HEIGHT
from rigora.presentation.widgets.timeline_tracks import TrackPicker, decode_channels
from rigora.presentation.widgets.titlebar import TitleBar
from rigora.presentation.widgets.window_frame import CustomDialog


class Timeline(QWidget):
    """Bind native editing interactions to the same commands used by headless clients."""

    bake_spring_requested = Signal(object)

    objects_dropped = Signal(object, float)
    extension_context_requested = Signal(object, str, object)

    def __init__(
        self,
        model: PlaybackViewModel,
        actions: dict[str, QAction],
        editor: AnimationEditorViewModel,
        icons: IconProvider,
        artwork_icon: Callable[[str | None], QIcon] | None = None,
    ) -> None:
        """Give timing lanes the available height, with transport above and precision tools
        on demand.
        """
        super().__init__()
        self.model, self.editor, self.icons = model, editor, icons
        self.artwork_icon = artwork_icon
        self._source_key: tuple[Any, ...] | None = None
        self._structure_input: tuple[Any, Any] = (None, None)
        self._row_structure: tuple[Any, ...] = ()
        self._paint_timeline: Any = None
        self._building = False
        self._rows: list[str | None] = []
        self._groups: dict[tuple[str, str], QTreeWidgetItem] = {}
        self._catalog: dict[tuple[str, str], AnimationChannel] = {}
        self._owner_labels: dict[str, str] = {}
        self._source_session = ""
        self.edit_actions: dict[str, QAction] = {}
        self.picker: TrackPicker | None = None
        self.curve_editor: CurveEditor | None = None
        self.action_editor: Any = None
        self._filter_expansions: dict[Any, bool] | None = None
        self.setMinimumHeight(210)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 3, 6, 0)
        layout.setSpacing(6)
        self.transport = QWidget(self)
        self.transport.setObjectName("TimelineTransport")
        self.transport.setAccessibleName("Timeline playback controls")
        transport = QGridLayout(self.transport)
        transport.setContentsMargins(0, 0, 0, 0)
        transport.setHorizontalSpacing(12)
        transport.setColumnStretch(0, 1)
        transport.setColumnStretch(2, 1)
        self.clip_controls, self.timing_controls = QWidget(self.transport), QWidget(self.transport)
        clip_fields = QHBoxLayout(self.clip_controls)
        timing_fields = QHBoxLayout(self.timing_controls)
        clip_fields.setContentsMargins(0, 0, 0, 0)
        timing_fields.setContentsMargins(0, 0, 0, 0)
        clip_fields.setSpacing(8)
        timing_fields.setSpacing(8)
        self.playback_buttons = QWidget(self.transport)
        self.playback_buttons.setAccessibleName("Playback buttons")
        buttons = QHBoxLayout(self.playback_buttons)
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(4)
        for key in ("first", "previous", "play", "stop", "next", "last", "loop"):
            button = QToolButton()
            button.setFixedSize(26, 26)
            button.setDefaultAction(actions[key])
            buttons.addWidget(button)
        self.clips = QComboBox()
        self.clips.setAccessibleName("Animation clip")
        self.clips.setMinimumContentsLength(8)
        self.clips.setMaximumWidth(180)
        self.clips.currentIndexChanged.connect(self._select_clip)
        clip_fields.addWidget(self.clips)
        self.frame = numeric(self, "Current frame", minimum=0, maximum=1e7)
        self.frame.setSuffix(" fr")
        self.frame.setMaximumWidth(105)
        self.frame.valueChanged.connect(model.seek)
        clip_fields.addWidget(self.frame)
        clip_fields.addStretch()
        timing_fields.addStretch()
        timing_fields.addWidget(QLabel("End"))
        self.max_frame = numeric(self, "Maximum playback frame", minimum=1, maximum=1e7)
        self.max_frame.setValue(120)
        self.max_frame.setMaximumWidth(100)
        self.max_frame.setToolTip("Maximum playback frame · also drag the End flag on the ruler")
        self.max_frame.editingFinished.connect(lambda: self.set_end_frame(self.max_frame.value()))
        timing_fields.addWidget(self.max_frame)
        self.speed = QComboBox()
        self.speed.setAccessibleName("Playback speed")
        for value in (0.1, 0.25, 0.5, 1.0, 1.5, 2.0):
            self.speed.addItem(f"{value:g}×", value)
        self.speed.setCurrentIndex(3)
        self.speed.currentIndexChanged.connect(self.set_speed)
        timing_fields.addWidget(self.speed)
        self.range_label, self.time, self.note = QLabel(), QLabel(), QLabel()
        self.range_label.setObjectName("Muted")
        self.range_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.range_label.setFixedWidth(130)
        self.note.setObjectName("Muted")
        self.note.setMaximumWidth(300)
        self.note.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        timing_fields.addWidget(self.range_label)
        timing_fields.addWidget(self.note)
        transport.addWidget(self.clip_controls, 0, 0)
        transport.addWidget(self.playback_buttons, 0, 1)
        transport.addWidget(self.timing_controls, 0, 2)
        layout.addWidget(self.transport)
        tools = QHBoxLayout()
        self.extension_actions = tools
        tools.setSpacing(8)
        add = QToolButton()
        add.setText("Add tracks")
        add.setIcon(icons.icon("add"))
        add.setProperty("materialIcon", "add")
        add.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        add.setToolTip("Add Transform, Animation, Skin, Clothing or other property tracks")
        add.clicked.connect(self.open_picker)
        tools.addWidget(add)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter tracks…")
        self.search.setAccessibleName("Filter timeline owners and channels")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(280)
        self.search.textChanged.connect(self.apply_filter)
        tools.addWidget(self.search, 1)
        self.only_selected = QCheckBox("Selected only")
        self.only_selected.setToolTip("Show tracks related to the selected stage objects or bones")
        self.only_selected.toggled.connect(self.apply_filter)
        tools.addWidget(self.only_selected)
        tools.addSpacing(8)
        tools.addStretch()
        self.pages = QTabWidget()
        split = self.splitter = QSplitter()
        self.tracks = QTreeWidget()
        self.tracks.setAccessibleName("Animation track hierarchy")
        self.tracks.setHeaderLabels(["Channel", "", ""])
        self.tracks.headerItem().setIcon(1, icons.icon("lock", 12))
        self.tracks.headerItem().setIcon(2, icons.icon("visibility", 12))
        self.tracks.headerItem().setToolTip(1, "Lock channels")
        self.tracks.headerItem().setToolTip(2, "Show channels")
        self.tracks.header().setIconSize(QSize(12, 12))
        self.anchor_track_columns(reset=True)
        self.tracks.setUniformRowHeights(True)
        self.tracks.setStyleSheet("QTreeView::item { height: 24px; padding: 0 5px; }")
        self.tracks.header().setFixedHeight(RULER_HEIGHT)
        self.tracks.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tracks.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.tracks.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tracks.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.tracks.itemChanged.connect(self.track_settings)
        self.tracks.itemExpanded.connect(self.expansion_changed)
        self.tracks.itemCollapsed.connect(self.expansion_changed)
        self.tracks.itemClicked.connect(self.inspect_owner)
        self.tracks.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tracks.customContextMenuRequested.connect(self.track_menu)
        for label, shortcut, callback in (
            ("Remove tracks", "Delete", lambda: self.track_command("delete")),
            ("Copy tracks", "Ctrl+C", lambda: self.track_command("copy")),
            ("Cut tracks", "Ctrl+X", lambda: self.track_command("cut")),
            ("Paste tracks at playhead", "Ctrl+V", lambda: self.track_command("paste")),
        ):
            action = QAction(menu_text(label), self.tracks)
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            action.triggered.connect(callback)
            self.tracks.addAction(action)
        self.dope = KeyCanvas(self)
        self.dope.icons = icons
        self.dope.action_requested.connect(self.open_action)
        self.dope.motion_edited.connect(self.edit_motion)
        self.dope.motion_removed.connect(
            lambda identity: self.editor.run(lambda s: self.remove_motion(s.document, identity))
        )
        self.dope.verticalScrollBar().valueChanged.connect(self.tracks.verticalScrollBar().setValue)
        self.tracks.verticalScrollBar().valueChanged.connect(self.dope.verticalScrollBar().setValue)
        split.addWidget(self.tracks)
        split.addWidget(self.dope)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([260, 850])
        sheet = QWidget()
        sheet_layout = QVBoxLayout(sheet)
        sheet_layout.setContentsMargins(0, 0, 0, 0)
        sheet_layout.setSpacing(6)
        sheet_layout.addLayout(tools)
        sheet_layout.addWidget(split, 1)
        self.pages.addTab(sheet, icons.icon("view_timeline"), "Dope sheet")
        self.clip_editor = ClipEditor(editor, icons)
        self.pages.addTab(self.clip_editor, icons.icon("movie"), menu_text("Clips & markers"))
        from rigora.presentation.widgets.motion_blocks import MotionBlocks

        self.motion_blocks = MotionBlocks(editor)
        self.motion_blocks.objects_dropped.connect(self.objects_dropped)
        self.dope.objects_dropped.connect(self.objects_dropped)
        self.pages.addTab(self.motion_blocks, icons.icon("view_timeline"), "Motion blocks")
        for canvas in (self.dope,):
            canvas.selected_keys.connect(editor.select)
            canvas.edited_keys.connect(self.edit_keys)
            canvas.seek_requested.connect(model.seek)
            canvas.step_requested.connect(model.step)
            canvas.lane_selected.connect(self.select_lane)
            canvas.range_selected.connect(self.select_range)
            canvas.context_requested.connect(self.context_menu)
            canvas.insert_requested.connect(self.insert_tracks)
            canvas.inspect_requested.connect(self.show_details)
            canvas.curve_requested.connect(self.open_curve)
            canvas.curve_dropped.connect(self.drop_curve)
            canvas.preview_requested.connect(editor.preview_keys)
            canvas.preview_finished.connect(editor.clear_key_preview)
            canvas.end_frame_changed.connect(self.set_end_frame)
            canvas.channels_dropped.connect(self.drop_channels)
        for key, text, icon, shortcut, callback in (
            ("key", "Key selected channels at playhead", "add", "K", self.insert_key),
            ("tween", "Create tween", "timeline", "T", self.create_tween),
            ("curve", "Edit tween graph…", "show_chart", "G", self.open_curve),
            ("cut", "Cut keys / tween", "content_cut", "Ctrl+X", editor.cut),
            (
                "convert",
                "Convert to tween",
                "linear_scale",
                "",
                lambda: editor.run(lambda s: s.set_transition(editor.selected)),
            ),
            ("step", "Frame-by-frame / hold", "stairs", "", self.make_step),
            (
                "reverse",
                "Reverse selected animation",
                "swap_horiz",
                "",
                lambda: editor.run(lambda s: s.reverse_keys(editor.selected)),
            ),
            ("copy", "Copy keys", "content_copy", "Ctrl+C", editor.copy),
            ("paste", "Paste keys at playhead", "content_paste", "Ctrl+V", editor.paste),
            (
                "duplicate",
                "Duplicate keys",
                "file_copy",
                "Ctrl+D",
                lambda: editor.paste(duplicate=True),
            ),
            ("delete", "Delete keys", "delete_outline", "Delete", self.delete_selection),
            ("all", "Select all visible keys", "select_all", "Ctrl+A", self.select_all),
            ("fit", "Frame curves / keys", "center_focus_strong", "F", self.frame_curves),
            ("details", "Key details…", "tune", "Return", self.show_details),
        ):
            self.add_edit_action(tools, key, text, icon, shortcut, callback)
        self.auto_key = QCheckBox("Auto key")
        self.auto_key.setToolTip("Record scene transforms and FFD edits at the current frame")
        self.auto_key.toggled.connect(editor.set_auto_key)
        editor.auto_key_changed.connect(self.auto_key.setChecked)
        tools.addSpacing(8)
        tools.addWidget(self.auto_key)
        self.tween_length = QSpinBox()
        self.tween_length.setRange(1, 100000)
        self.tween_length.setValue(24)
        self.tween_length.setSuffix(" fr")
        self.tween_length.setMaximumWidth(90)
        self.tween_length.setAccessibleName("New tween duration")
        tools.addWidget(self.tween_length)
        tools.addSpacing(8)
        self.zoom_label = QLabel("100%")
        self.zoom_label.setAccessibleName("Timeline zoom percentage")
        self.zoom_label.setToolTip("Timeline zoom · 100% is 8 pixels per frame")
        self.zoom_label.setMinimumWidth(48)
        self.zoom_label.setMaximumWidth(52)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.dope.zoom_changed.connect(
            lambda zoom: self.zoom_label.setText(f"{zoom * 100:.1f}".rstrip("0").rstrip(".") + "%")
        )
        zoom_controls = QWidget()
        zoom_controls.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        zoom_row = QHBoxLayout(zoom_controls)
        zoom_row.setContentsMargins(0, 0, 0, 0)
        zoom_row.setSpacing(4)
        for label, icon, factor in (
            ("Zoom out timeline", "zoom_out", 1 / 1.25),
            ("Zoom in timeline", "zoom_in", 1.25),
        ):
            zoom = QToolButton()
            zoom.setIcon(icons.icon(icon))
            zoom.setProperty("materialIcon", icon)
            zoom.setToolTip(label + " · Ctrl+wheel over frames")
            zoom.setAccessibleName(label)
            zoom.clicked.connect(lambda checked=False, scale=factor: self.dope.zoom(scale))
            zoom_row.addWidget(zoom)
            if factor < 1:
                zoom_row.addWidget(self.zoom_label)
        tools.addWidget(zoom_controls)
        self.view_button = QToolButton()
        self.view_button.setObjectName("TimelineView")
        self.view_button.setText("View")
        self.view_button.setAccessibleName("Timeline view options")
        self.view_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        view_menu = QMenu(self.view_button)
        self.group_properties = QAction("Group property tracks", self)
        self.group_properties.setToolTip(
            "Combine all parts into one row per property in Object Editor"
        )
        self.group_properties.setCheckable(True)
        self.group_properties.setChecked(True)
        self.group_properties.toggled.connect(self.refresh)
        view_menu.addAction(self.group_properties)
        self.marker_labels = QAction("Marker labels", self)
        self.marker_labels.setToolTip(
            "Show marker names such as action and contact poses on the ruler"
        )
        self.marker_labels.setCheckable(True)
        self.marker_labels.setChecked(True)
        self.marker_labels.toggled.connect(self.set_marker_labels)
        view_menu.addAction(self.marker_labels)
        view_menu.addSeparator()
        self.snap, self.onion, self.trails, self.compare = (
            QAction(menu_text(text), self)
            for text in (
                "Snap to whole frames",
                "Onion skin",
                "Motion trails",
                "Compare retained pose",
            )
        )
        self.snap.setCheckable(True)
        self.snap.setChecked(True)
        self.snap.toggled.connect(self.set_snap)
        view_menu.addAction(self.snap)
        for action in (self.onion, self.trails, self.compare):
            action.setCheckable(True)
            action.toggled.connect(self.set_visualization)
            view_menu.addAction(action)
        self.onion.setToolTip("Show the preceding and following animation poses on stage")
        self.trails.setToolTip("Show animated movement paths on stage")
        self.compare.setToolTip("Retain this frame as a comparison pose while scrubbing")
        self.view_button.setMenu(view_menu)
        tools.addWidget(self.view_button)
        layout.addWidget(self.pages, 1)
        self.details = CustomDialog(self, "Key and curve details")
        self.details.resize(410, 540)
        details = QVBoxLayout(self.details.content)
        self.key_controls = QWidget()
        form = QFormLayout(self.key_controls)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        self.key_frame = numeric(self, "Selected key frame", minimum=0, maximum=1e7)
        self.key_value = numeric(self, "Selected key value")
        self.interpolation = QComboBox()
        self.interpolation.setAccessibleName("Key interpolation")
        self.interpolation.addItems(["linear", "step", "bezier"])
        form.addRow("Frame", self.key_frame)
        form.addRow("Value", self.key_value)
        form.addRow("Interpolation", self.interpolation)
        apply = QPushButton("Apply changes")
        apply.setIcon(icons.icon("check"))
        apply.setProperty("materialIcon", "check")
        apply.setToolTip("Apply the frame/value delta to every selected key")
        apply.setDefault(True)
        apply.clicked.connect(self.apply_numeric)
        form.addRow(apply)
        details.addWidget(self.key_controls)
        details.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.details.close)
        details.addWidget(close)
        self.pages.currentChanged.connect(self.show_edit_controls)
        model.changed.connect(self.refresh_transport)
        editor.changed.connect(self.refresh)
        editor.focus_changed.connect(self.apply_filter)
        editor.previews_changed.connect(self.refresh_view_options)
        self.refresh()

    def anchor_track_columns(self, *, reset: bool = False) -> None:
        """Fill the channel panel while keeping compact state controls at its right edge.

        Apply after restoring older header preferences as well as initial setup;
        the splitter owns the panel width, while the name column absorbs resizing.
        Preserve restored fixed-column widths. Legacy interactive state columns
        migrate to compact defaults, as does an explicit layout reset.
        """
        header = self.tracks.header()
        header.setMinimumSectionSize(24)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2):
            legacy = header.sectionResizeMode(column) != QHeaderView.ResizeMode.Fixed
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            if reset or legacy:
                header.resizeSection(column, 26)

    def attach_transport(self, titlebar: TitleBar) -> None:
        """Move the shared playback widget into dock chrome, preserving its actions and bindings."""
        title_layout = cast(QHBoxLayout, titlebar.layout())
        title_layout.insertWidget(2, self.transport, 1)
        # Playback owns flexible caption space; a second expanding spacer would clip its fields.
        for index in range(title_layout.count()):
            item = title_layout.itemAt(index)
            if item is not None and item.spacerItem() is not None:
                title_layout.setStretch(index, 0)

    def set_marker_labels(self, enabled: bool) -> None:
        """Hide ruler annotations without removing markers or changing animation data."""
        self.dope.ruler.show_marker_labels = enabled
        self.dope.ruler.update()

    def refresh_view_options(self) -> None:
        """Reflect model preferences after context switches without retriggering capture actions."""
        for action, checked in (
            (self.snap, self.editor.snap),
            (self.onion, self.editor.onion),
            (self.trails, self.editor.trails),
            (self.compare, self.editor.compare is not None),
        ):
            with QSignalBlocker(action):
                action.setChecked(checked)

    def add_edit_action(
        self,
        layout: QHBoxLayout,
        key: str,
        text: str,
        icon: str,
        shortcut: str,
        callback: Callable[..., Any],
    ) -> None:
        """Attach scoped dope-sheet shortcuts and shared Material/context-menu actions."""
        action = QAction(self.icons.icon(icon), menu_text(text), self)
        action.setProperty("materialIcon", icon)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        action.triggered.connect(lambda checked=False: callback())
        self.dope.addAction(action)
        self.edit_actions[key] = action
        button = QToolButton()
        button.setProperty("materialIcon", icon)
        button.setDefaultAction(action)
        if key not in ("cut", "convert", "step", "reverse", "all"):
            layout.addWidget(button)
        else:
            button.deleteLater()

    def _select_clip(self, index: int) -> None:
        """Select a clip by UUID and rebuild editing data through the shared binding path."""
        key = self.clips.itemData(index)
        if isinstance(key, str):
            self.model.select_clip(key)
            self.editor.bind(self.model.document)

    def show_edit_controls(self, page: int) -> None:
        """Keep precision fields contextual without reserving space below the key area."""
        if page == 1:
            self.details.hide()

    def refresh_icons(self) -> None:
        """Refresh scoped actions and tab glyphs from the shared theme-aware provider."""
        for action in self.edit_actions.values():
            action.setIcon(self.icons.icon(str(action.property("materialIcon"))))
        for index, icon in enumerate(("view_timeline", "movie")):
            self.pages.setTabIcon(index, self.icons.icon(icon))

    def refresh(self) -> None:
        """Rebuild grouped channel rows on source changes, preserving selection, expansion
        and scroll.
        """
        service = self.editor.service
        try:
            scene = service.scene if service else None
            clip = service.clip if service else None
            timeline = service.timeline if service else None
        except ProjectError:
            scene, clip, timeline = None, None, None
        document = service.document if service else None
        in_object = bool(document and document.animation_context)
        grouped = in_object and self.group_properties.isChecked()
        self.group_properties.setEnabled(in_object)
        self.refresh_view_options()
        self.pages.setTabVisible(self.pages.indexOf(self.motion_blocks), False)
        self.clips.setAccessibleName("Object animation" if in_object else "Scene animation")
        self.clips.setToolTip(
            "Each named animation has its own timeline" if in_object else "Main Scene timeline"
        )
        samplers = document.track_samplers if document else {}
        if (
            self.curve_editor
            and self.curve_editor.isVisible()
            and document
            and (
                self.curve_editor.source is not document.project
                or self.curve_editor.session != document.session_id
                or self.curve_editor.clip_id != (clip.id if clip else "")
            )
        ):
            self.curve_editor.reject()
        if scene is not self._structure_input[0] or timeline is not self._structure_input[1]:
            self._structure_input = scene, timeline
            self._row_structure = row_structure(scene, timeline)
        key = (
            document.session_id if document else None,
            self._row_structure,
            tuple((c.id, c.name, c.in_frame, c.out_frame) for c in document.context_clips())
            if document
            else (),
            clip.id if clip else None,
            document.animation_context if document else None,
            id(document.channel_metadata) if document else None,
            tuple((k, id(v)) for k, v in samplers.items()),
            grouped,
        )
        self.dope.samplers = samplers
        if key != self._source_key:
            self._source_key = key
            session = document.session_id if document else ""
            same_session = session == self._source_session
            self._source_session = session
            self._building = True
            states = {}
            chosen = set()
            vertical = self.tracks.verticalScrollBar().value() if same_session else 0

            def remember(row: QTreeWidgetItem | None) -> None:
                """Retain explicit row expansion without carrying it across unrelated
                project tabs.
                """
                if row is None:
                    return
                if same_session:
                    states[row.data(0, Qt.ItemDataRole.UserRole + 2)] = row.isExpanded()
                    if row.isSelected():
                        chosen.add(row.data(0, Qt.ItemDataRole.UserRole + 2))
                for i in range(row.childCount()):
                    remember(row.child(i))

            for i in range(self.tracks.topLevelItemCount()):
                remember(self.tracks.topLevelItem(i))
            self._catalog = (
                {
                    c.key: c
                    for c in service.channels(
                        (t.owner_id, t.property_path) for t in timeline.tracks
                    )
                }
                if service and timeline
                else {}
            )
            self._groups.clear()
            with QSignalBlocker(self.clips), QSignalBlocker(self.tracks):
                self.clips.clear()
                self.tracks.clear()
                self._owner_parent = {}
                self._selectable_owners: set[str] = set()
                self._rig_members: dict[str, set[str]] = {}
                if scene and service:
                    for item in document.context_clips() if document else scene.clips:
                        self.clips.addItem(item.name, item.id)
                    if clip:
                        self.clips.setCurrentIndex(self.clips.findData(clip.id))
                    owners = {r.id: r for r in nested_records(scene)}
                    self._owner_labels = {key: r.name for key, r in owners.items()}
                    self._selectable_owners = {
                        r.id for r in owners.values() if isinstance(r, (Bone, Group, SceneObject))
                    }
                    self._rig_members = {
                        rig.id: {b.id for b in rig.bones} for rig in scene.skeletons
                    }
                    self._owner_parent = {
                        r.id: (
                            getattr(r, "parent_id", None)
                            or getattr(r, "object_id", None)
                            or getattr(r, "owner_id", None)
                        )
                        for r in owners.values()
                    }
                    for mesh in scene.meshes:
                        self._owner_parent.update({v.id: mesh.id for v in mesh.vertices})
                    nodes: dict[str, QTreeWidgetItem] = {}
                    tracks = timeline.tracks if timeline else ()
                    lane_members: dict[tuple[str, str], list[Track]] = {}
                    from rigora.application_services.characters import CharacterService

                    allowed = (
                        (
                            set(CharacterService(document).scene_objects())
                            | {c.id for c in document.scene.cameras}
                        )
                        if document
                        else set()
                    )
                    priority = {"transform": 0, "opacity": 4, "visibility": 5}
                    tracks = tuple(
                        sorted(
                            tracks,
                            key=lambda t: (
                                2
                                if t.extra.get("camera_action", {}).get("kind") == "camera_motion"
                                else 3
                                if t.extra.get("camera_action", {}).get("kind") == "camera_effect"
                                else 1
                                if t.property_path == "camera.active"
                                else 1
                                if t.extra.get("motion_window")
                                else 2
                                if t.extra.get("appearance_kind") == "skins"
                                else 3
                                if t.extra.get("appearance_kind") == "outfits"
                                else priority.get(t.property_path.partition(".")[0], 6)
                            ),
                        )
                    )
                    for track in tracks:
                        surface = isinstance(owners.get(track.owner_id), (Deformer, Vertex))
                        window = track.extra.get("motion_window") or track.extra.get(
                            "camera_action"
                        )
                        if window and in_object:
                            continue
                        spring = bool(
                            track.extra.get("spring_motion_test")
                            or track.extra.get("spring_activation")
                            or track.property_path.startswith("spring.")
                            or clip
                            and clip.extra.get("spring_motion_test")
                            and track.name.startswith("Spring test · ")
                        )
                        if (
                            document
                            and document.separated_animation
                            and not document.animation_context
                            and track.owner_id not in allowed
                            and not track.extra.get("appearance_owner")
                            and not window
                            and not spring
                            and not surface
                            and not track.extra.get("foot_contact")
                            and not track.extra.get("motion_path")
                            and not track.extra.get("camera_transition")
                        ):
                            continue
                        vertex = isinstance(owners.get(track.owner_id), Vertex)
                        owner = (
                            self._owner_parent.get(track.owner_id) if vertex else None
                        ) or track.owner_id
                        owner = track.extra.get("appearance_owner", owner)
                        if window:
                            owner = window["character"]
                        if surface and not in_object:
                            ancestor = owner
                            visited = set()
                            while ancestor and ancestor not in allowed and ancestor not in visited:
                                visited.add(ancestor)
                                ancestor = self._owner_parent.get(ancestor)
                            if ancestor in allowed:
                                owner = ancestor
                        channel = self._catalog.get((track.owner_id, track.property_path))
                        if channel and isinstance(channel.owner, Constraint):
                            owner = channel.owner.owner_id
                            root = (
                                CharacterService(document).object_root(owner) if document else None
                            )
                            owner = root.id if root and not in_object else owner
                        camera_lane = isinstance(owners.get(owner), Camera)
                        if camera_lane:
                            owner = "__cameras__"
                        parent = None if grouped else self.owner_item(owner, owners, nodes)
                        channel = self._catalog.get((track.owner_id, track.property_path))
                        lane = (
                            "Spring"
                            if spring
                            else "Mesh deformation"
                            if vertex
                            else channel.lane
                            if channel
                            else track.property_path
                        )
                        if track.extra.get("appearance_group"):
                            lane = (
                                "Skin"
                                if track.extra.get("appearance_kind") == "skins"
                                else "Clothing"
                            )
                        if window:
                            lane = (
                                "Effect" if window.get("kind") == "camera_effect" else "Animation"
                            )
                        elif camera_lane and track.property_path == "camera.active":
                            lane = "Cut"
                        identity = "" if grouped else owner, lane
                        row = self._groups.get(identity)
                        if row is None:
                            row = QTreeWidgetItem(
                                ["VISIBILITY" if lane == "Visible" else lane.upper(), "", ""]
                            )
                            row.setData(0, Qt.ItemDataRole.UserRole + 1, "" if grouped else owner)
                            row.setData(0, Qt.ItemDataRole.UserRole + 2, ("group", *identity))
                            row.setData(0, Qt.ItemDataRole.UserRole + 3, ())
                            if lane in (
                                "Animation",
                                "Skin",
                                "Clothing",
                                "View",
                                "Cut",
                                "Effect",
                                "Attachment",
                            ):
                                kind = {
                                    "Animation": "motion",
                                    "Skin": "skins",
                                    "Clothing": "outfits",
                                    "View": "views",
                                    "Cut": "camera_cut",
                                    "Effect": "camera_effect",
                                    "Attachment": "attachment",
                                }[lane]
                                if camera_lane and lane == "Animation":
                                    kind = "camera_motion"
                                row.setData(0, Qt.ItemDataRole.UserRole + 6, (owner, kind))
                                row.setIcon(
                                    0,
                                    self.icons.icon(
                                        {
                                            "motion": "directions_run",
                                            "attachment": "link",
                                            "skins": "palette",
                                            "outfits": "dry_cleaning",
                                            "views": "360",
                                            "camera_cut": "videocam",
                                            "camera_motion": "camera_enhance",
                                            "camera_effect": "auto_awesome",
                                        }[kind],
                                        16,
                                    ),
                                )
                                row.setText(0, lane)
                            if parent is None:
                                self.tracks.addTopLevelItem(row)
                            else:
                                parent.addChild(row)
                            self._groups[identity] = row
                        lane_members.setdefault(identity, []).append(track)
                    for identity, records in lane_members.items():
                        row = self._groups[identity]
                        row.setData(0, Qt.ItemDataRole.UserRole + 4, tuple(t.id for t in records))
                        row.setData(0, Qt.ItemDataRole.UserRole + 3, tuple(t.id for t in records))
                        row.setCheckState(
                            1,
                            Qt.CheckState.Checked
                            if all(t.editing_locked for t in records)
                            else Qt.CheckState.PartiallyChecked
                            if any(t.editing_locked for t in records)
                            else Qt.CheckState.Unchecked,
                        )
                        row.setCheckState(
                            2,
                            Qt.CheckState.Checked
                            if all(t.visible for t in records)
                            else Qt.CheckState.PartiallyChecked
                            if any(t.visible for t in records)
                            else Qt.CheckState.Unchecked,
                        )
                        row.setToolTip(1, "Lock this row against editing and adding animation")
                        row.setToolTip(2, "Enable this row's animation during preview and export")
                        row.setToolTip(
                            0,
                            (f"{len(records)} channels · " if len(records) > 12 else "")
                            + "\n".join(
                                f"{t.property_path} · {len(t.keyframes)} keys" for t in records[:12]
                            ),
                        )
                        if identity[1] == "Spring":
                            multiple_owners = len({t.owner_id for t in records}) > 1
                            buckets: dict[tuple[str, str], list[Track]] = {}
                            for member in records:
                                token = (
                                    (
                                        "activation",
                                        str(member.extra.get("spring_group", member.owner_id)),
                                    )
                                    if member.property_path.startswith("spring.")
                                    else ("channel", member.id)
                                )
                                buckets.setdefault(token, []).append(member)
                            for token, members in buckets.items():
                                track = members[0]
                                channel = self._catalog.get((track.owner_id, track.property_path))
                                label = (
                                    f"{channel.group} · {channel.label}"
                                    if channel
                                    else track.property_path
                                )
                                if token[0] == "activation":
                                    label = (
                                        "Master enabled"
                                        if track.property_path == "spring.master"
                                        else f"{token[1]} · enabled"
                                    )
                                elif multiple_owners:
                                    label = f"{owners[track.owner_id].name} · {label}"
                                child = QTreeWidgetItem(row, [label, "", ""])
                                child.setData(0, Qt.ItemDataRole.UserRole + 1, track.owner_id)
                                child.setData(
                                    0, Qt.ItemDataRole.UserRole + 2, ("spring_channel", *token)
                                )
                                child.setData(
                                    0, Qt.ItemDataRole.UserRole + 3, tuple(t.id for t in members)
                                )
                                child.setData(
                                    0, Qt.ItemDataRole.UserRole + 4, tuple(t.id for t in members)
                                )
                                child.setToolTip(0, track.property_path)

                    def restore(row: QTreeWidgetItem | None) -> None:
                        """Restore owner/group disclosure and track selection after rebuilding."""
                        if row is None:
                            return
                        identity = row.data(0, Qt.ItemDataRole.UserRole + 2)
                        row.setExpanded(states.get(identity, identity[0] == "owner"))
                        row.setSelected(identity in chosen)
                        for i in range(row.childCount()):
                            restore(row.child(i))

                    for i in range(self.tracks.topLevelItemCount()):
                        restore(self.tracks.topLevelItem(i))
            self._building = False
            self.apply_filter()
            self.tracks.verticalScrollBar().setValue(vertical)
            self.dope.verticalScrollBar().setValue(vertical)
            self.clip_editor.refresh()
            if self.picker and self.picker.isVisible():
                self.picker.refresh()
        elif timeline is not self._paint_timeline:
            current_tracks = {track.id: track for track in timeline.tracks} if timeline else {}
            for row in self._groups.values():
                current_members = tuple(
                    current_tracks[key] for key in self.row_tracks(row) if key in current_tracks
                )
                row.setToolTip(
                    0,
                    (f"{len(current_members)} channels · " if len(current_members) > 12 else "")
                    + "\n".join(
                        f"{track.property_path} · {len(track.keyframes)} keys"
                        for track in current_members[:12]
                    ),
                )
            self.expansion_changed()
            self.clip_editor.refresh()
        self._paint_timeline = timeline
        self.dope.sync_selection(self.editor.selected)
        selected = [
            (t, k) for t, k in self.editor.key_records() if (t.id, k.id) in self.editor.selected
        ]
        if selected:
            first = selected[0][1]
            self.key_frame.setValue(first.frame)
            self.key_value.setValue(float(first.value))
            self.interpolation.setCurrentText(first.interpolation)
        self.refresh_transport()

    def row_tracks(self, row: QTreeWidgetItem | None) -> tuple[str, ...]:
        """Resolve a visible property or owner/group to its canonical track identities."""
        if row is None or row.isHidden():
            return ()
        members = row.data(0, Qt.ItemDataRole.UserRole + 3)
        if members is not None:
            return tuple(members)
        key = row.data(0, Qt.ItemDataRole.UserRole)
        return (
            (key,)
            if key
            else tuple(
                key for i in range(row.childCount()) for key in self.row_tracks(row.child(i))
            )
        )

    def apply_filter(self) -> None:
        """Filter by readable channel paths and stage selection while retaining matching
        ancestors.
        """
        if self._building:
            return
        selected = set(self.editor.focused_owners)
        selected.update(key for rig in tuple(selected) for key in self._rig_members.get(rig, ()))
        words = self.search.text().strip().casefold().split()
        active = bool(words) or self.only_selected.isChecked()
        service = self.editor.service
        timeline = service.timeline if service else None
        tracks = {t.id: t for t in timeline.tracks} if timeline else {}
        if active and self._filter_expansions is None:
            expansions: dict[Any, bool] = {}
            self._filter_expansions = expansions

            def remember(row: QTreeWidgetItem | None) -> None:
                """Retain disclosure states while filtering temporarily reveals matching lanes."""
                if row is None:
                    return
                expansions[row.data(0, Qt.ItemDataRole.UserRole + 2)] = row.isExpanded()
                for i in range(row.childCount()):
                    remember(row.child(i))

            for i in range(self.tracks.topLevelItemCount()):
                remember(self.tracks.topLevelItem(i))

        def related(owner: str, owners: set[str] | frozenset[str]) -> bool:
            """Test ownership ancestry without interpreting display names or modifying the rig."""
            visited = set()
            while owner and owner not in visited:
                if owner in owners:
                    return True
                visited.add(owner)
                owner = self._owner_parent.get(owner) or ""
            return False

        def visit(row: QTreeWidgetItem | None, path: str) -> bool:
            """Keep a branch only if it contains a matching real property lane."""
            if row is None:
                return False
            path = f"{path} {row.text(0)}"
            if row.childCount():
                visible = any([visit(row.child(i), path) for i in range(row.childCount())])
                # Summary lanes operate on their visible children; owner headers stay inert.
                if row.data(0, Qt.ItemDataRole.UserRole + 4):
                    row.setData(
                        0,
                        Qt.ItemDataRole.UserRole + 3,
                        tuple(
                            key
                            for i in range(row.childCount())
                            if (child := row.child(i)) is not None and not child.isHidden()
                            for key in self.row_tracks(child)
                        ),
                    )
            else:
                members = row.data(0, Qt.ItemDataRole.UserRole + 4) or ()
                matching = []
                for key in members:
                    track = tracks.get(key)
                    if track is None:
                        continue
                    owner = track.extra.get("motion_window", {}).get(
                        "character", track.extra.get("appearance_owner", track.owner_id)
                    )
                    labels, visited = [], set()
                    ancestor = owner
                    while ancestor and ancestor not in visited:
                        labels.append(self._owner_labels.get(ancestor, ""))
                        visited.add(ancestor)
                        ancestor = self._owner_parent.get(ancestor) or ""
                    channel = self._catalog.get((track.owner_id, track.property_path))
                    description = " ".join(
                        (
                            path,
                            track.name,
                            str(track.extra.get("motion_window", {}).get("name", "")),
                            " ".join(
                                str(k.extra.get("appearance_choice", {}).get("name", ""))
                                for k in track.keyframes
                            ),
                            track.property_path,
                            *labels,
                            channel.group if channel else "",
                            channel.label if channel else "",
                        )
                    ).casefold()
                    if (
                        all(word in description for word in words)
                        and (not self.only_selected.isChecked() or related(owner, selected))
                        and (
                            self.editor.composer_owners is None
                            or related(owner, self.editor.composer_owners)
                        )
                    ):
                        matching.append(track)
                row.setData(0, Qt.ItemDataRole.UserRole + 3, tuple(t.id for t in matching))
                if matching:
                    for column, values in (
                        (1, [t.editing_locked for t in matching]),
                        (2, [t.visible for t in matching]),
                    ):
                        row.setCheckState(
                            column,
                            Qt.CheckState.Checked
                            if all(values)
                            else Qt.CheckState.PartiallyChecked
                            if any(values)
                            else Qt.CheckState.Unchecked,
                        )
                visible = bool(matching)
            row.setHidden(not visible)
            if active and visible and row.childCount():
                row.setExpanded(True)
            elif not active and self._filter_expansions is not None:
                identity = row.data(0, Qt.ItemDataRole.UserRole + 2)
                if identity in self._filter_expansions:
                    row.setExpanded(self._filter_expansions[identity])
            return visible

        self._building = True
        for i in range(self.tracks.topLevelItemCount()):
            visit(self.tracks.topLevelItem(i), "")
        if not active:
            self._filter_expansions = None
        self._building = False
        self.expansion_changed()

    def inspect_owner(self, row: QTreeWidgetItem, column: int) -> None:
        """Synchronize a timeline owner pick with the existing scene selection ViewModel."""
        if column == 0 and row.flags() & Qt.ItemFlag.ItemIsSelectable:
            owner = row.data(0, Qt.ItemDataRole.UserRole + 1)
            while owner and owner not in self._selectable_owners:
                owner = self._owner_parent.get(owner)
            if owner:
                self.editor.owner_selected.emit(owner)

    def open_picker(self) -> None:
        """Open reusable discovery of compound properties and plugin numeric parameters."""
        if self.picker is None:
            self.picker = TrackPicker(self)
            self.picker.channels_chosen.connect(
                lambda channels: self.editor.run(lambda s: s.add_channels(channels))
            )
        self.picker.refresh(prefer_selection=True)
        self.picker.show()
        self.picker.raise_()

    def open_action(self, action: dict[str, Any]) -> None:
        """Inspect an icon key or choose an action for an empty semantic lane."""
        from rigora.presentation.widgets.timeline_actions import SceneActionEditor

        if self.editor.service is None:
            return
        if self.action_editor:
            self.action_editor.close()
            self.action_editor.deleteLater()
        self.model.pause()
        if action["kind"] == "attachment":
            from rigora.presentation.widgets.scene_attachments import SceneAttachmentsDialog

            window = self.window()
            from rigora.presentation.views.main_window import MainWindow

            if isinstance(window, MainWindow):
                self.action_editor = SceneAttachmentsDialog(
                    window, owner=action["owner"], frame=action["frame"]
                )
                self.action_editor.show()
            return
        if action["kind"].startswith("camera_"):
            from rigora.application_services.cameras import CameraService
            from rigora.presentation.widgets.camera_action_editor import CameraActionEditor

            if action["owner"] == "__cameras__":
                camera = CameraService(self.editor.service.document).current()
                action = {
                    **action,
                    "owner": camera.id if camera else self.editor.service.scene.cameras[0].id,
                }
            self.action_editor = CameraActionEditor(self, action)
            self.action_editor.show()
            return
        self.action_editor = SceneActionEditor(
            self,
            action["owner"],
            action["kind"],
            action["frame"],
            segment=action.get("segment", ""),
            refs=action.get("refs", ()),
        )
        self.action_editor.show()

    def edit_motion(self, window: dict[str, Any]) -> None:
        """Commit one span move/trim through the existing source-motion arrangement service."""
        if window.get("kind", "").startswith("camera_"):
            from rigora.application_services.cameras import CameraService

            self.editor.run(
                lambda s: CameraService(s.document).action(
                    window["character"],
                    window["preset"],
                    window["kind"],
                    window["start"],
                    window["end"],
                    speed=window["speed"],
                    amount=window["amount"],
                    identity=window["id"],
                )
            )
            return
        self.editor.run(
            lambda s: CharacterService(s.document).edit_segment(
                window["id"], start=window["start"], end=window["end"]
            )
        )
        if self.editor.error:
            self.expansion_changed()

    def drop_channels(self, mime: Any, frame: float) -> None:
        """Create captured keys at a drop frame using only the active session's supported
        channels.
        """
        document = self.editor.document
        if document is None:
            return
        try:
            channels = decode_channels(mime, document.session_id)
            if document.separated_animation:
                from rigora.application_services.characters import CharacterService

                allowed = (
                    document.animation_scope
                    if document.animation_context
                    else frozenset(
                        (
                            *CharacterService(document).scene_objects(),
                            *(c.id for c in document.scene.cameras),
                        )
                    )
                )
                if any(owner not in (allowed or ()) for owner, _ in channels):
                    raise ProjectError("Add bone and mesh tracks in their Object Editor.")
        except ProjectError as error:
            self.editor.error = str(error)
            self.refresh_transport()
            return
        self.editor.run(
            lambda s: s.add_channels(
                channels, frame=frame, interpolation="linear" if self.editor.auto_key else "step"
            )
        )

    def insert_tracks(self, tracks: tuple[str, ...], frame: float) -> None:
        """Capture an entire selected group or a single lane as one undoable key operation."""
        frame = round(frame) if self.editor.snap else frame
        service = self.editor.service
        timeline = service.timeline if service else None
        if timeline:
            discrete = next(
                (
                    t
                    for t in timeline.tracks
                    if t.id in tracks
                    and t.property_path in ("object.view", "camera.active", "object.attachment")
                ),
                None,
            )
            if discrete:
                self.open_action(
                    {
                        "owner": discrete.owner_id,
                        "kind": {
                            "object.view": "views",
                            "camera.active": "camera_cut",
                            "object.attachment": "attachment",
                        }[discrete.property_path],
                        "frame": frame,
                        "refs": tuple(
                            (t.id, k.id)
                            for t in timeline.tracks
                            if t.id in tracks
                            for k in t.keyframes
                            if k.frame == frame
                        ),
                    }
                )
                return
            appearance = next(
                (t for t in timeline.tracks if t.id in tracks and t.extra.get("appearance_kind")),
                None,
            )
            window = next(
                (
                    t.extra["motion_window"]
                    for t in timeline.tracks
                    if t.id in tracks and t.extra.get("motion_window")
                ),
                None,
            )
            if appearance or window:
                self.open_action(
                    {
                        "owner": appearance.extra["appearance_owner"]
                        if appearance
                        else (window or {})["character"],
                        "kind": appearance.extra["appearance_kind"] if appearance else "motion",
                        "frame": frame,
                        "refs": tuple(
                            (t.id, k.id)
                            for t in timeline.tracks
                            if t.id in tracks
                            for k in t.keyframes
                            if k.frame == frame
                        ),
                    }
                )
                return
            channels = tuple(
                (t.owner_id, t.property_path) for t in timeline.tracks if t.id in tracks
            )
            if channels:
                self.editor.run(
                    lambda s: s.add_channels(
                        channels,
                        frame=frame,
                        interpolation="linear" if self.editor.auto_key else "step",
                    )
                )

    def create_tween(self) -> None:
        """Connect selected endpoints, or capture a duration on the chosen channel rows."""
        service = self.editor.service
        if service is None or self.model.session is None:
            return
        counts: dict[str, int] = {}
        for track, _ in self.editor.selected:
            counts[track] = counts.get(track, 0) + 1
        if any(count >= 2 for count in counts.values()):
            self.editor.run(lambda s: s.set_transition(self.editor.selected))
            return
        ids = {key for row in self.tracks.selectedItems() for key in self.row_tracks(row)}
        ids.update(ref[0] for ref in self.editor.selected)
        channels = (
            tuple((t.owner_id, t.property_path) for t in service.timeline.tracks if t.id in ids)
            if service.timeline
            else ()
        )
        if not channels:
            self.open_picker()
            self.editor.error = "Add or select channels, then choose Create tween."
            self.refresh_transport()
            return
        frame = self.model.session.pose.frame
        frame = round(frame) if self.editor.snap else frame

        def create(service: Any) -> None:
            """Select the captured endpoints after the single reversible creation command."""
            self.editor.selected = service.create_tween(
                channels, frame, frame + self.tween_length.value()
            )

        self.editor.run(create)

    def make_step(self) -> None:
        """Convert selected keys to discrete holds without deleting their values."""
        self.edit_keys(
            {
                ref: {"interpolation": "step", "transition_curve": None}
                for ref in self.editor.selected
            }
        )

    def drop_curve(self, refs: tuple[tuple[str, str], ...], name: str) -> None:
        """Apply a trusted preset dropped onto a span as one undoable edit."""
        curve = curve_presets().get(name)
        if curve:
            self.editor.run(lambda s: s.set_transition(refs, curve))

    def open_curve(self, refs: tuple[tuple[str, str], ...] | None = None) -> None:
        """Open graph editing for chosen spans, importing legacy Bézier samples."""
        service = self.editor.service
        if service is None:
            return
        segments = service.selected_segments(refs or self.editor.selected)
        if not segments:
            self.editor.error = "Select a tween or two keys on a channel to edit its graph."
            self.refresh_transport()
            return
        if self.curve_editor is None:
            self.curve_editor = CurveEditor(self, self.icons)
            self.curve_editor.graph_changed.connect(self.preview_curve)
            self.curve_editor.apply_requested.connect(self.apply_curve)
            self.curve_editor.preview_ended.connect(self.editor.clear_key_preview)
        dialog = self.curve_editor
        track, left, right = segments[0]
        dialog.targets = tuple(dict.fromkeys((t.id, k.id) for t, a, b in segments for k in (a, b)))
        dialog.source = self.editor.document.project if self.editor.document else None
        dialog.session = self.editor.document.session_id if self.editor.document else ""
        dialog.clip_id = service.clip.id if service.clip else ""
        dialog.start, dialog.end = left.frame, right.frame
        if "transition_curve" in left.extra:
            curve = TransitionCurve.from_data(left.extra["transition_curve"])
        elif left.interpolation == "bezier" and left.value != right.value:
            sampler = CompiledTrack(
                track, self.editor.document.track_samplers if self.editor.document else {}
            )
            points = tuple(
                (
                    i / 64,
                    (
                        float(sampler.sample(left.frame + (right.frame - left.frame) * i / 64) or 0)
                        - float(left.value)
                    )
                    / (float(right.value) - float(left.value)),
                )
                for i in range(65)
            )
            curve = TransitionCurve(points)
        else:
            curve = TransitionCurve()
        dialog.caption.setText(
            f"{len(segments)} span(s) · {left.frame:g}–{right.frame:g} fr · "
            "Double-click: add dot · Delete: remove"
        )
        self.model.pause()
        dialog.open_curve(curve)

    def curve_edits(self, curve: TransitionCurve) -> dict[tuple[str, str], dict[str, Any]]:
        """Build outgoing-key edits for the popup's stable target identities."""
        dialog, service = self.curve_editor, self.editor.service
        if (
            dialog is None
            or service is None
            or self.editor.document is None
            or dialog.source is not self.editor.document.project
        ):
            return {}
        return {
            (t.id, a.id): {"interpolation": "linear", "transition_curve": curve.to_data()}
            for t, a, _ in service.selected_segments(dialog.targets)
        }

    def preview_curve(self, curve: TransitionCurve, frame: float) -> None:
        """Evaluate popup edits without adding history or shifting the saved playhead."""
        edits = self.curve_edits(curve)
        if edits:
            self.editor.preview_keys(edits, frame)

    def apply_curve(self, curve: TransitionCurve) -> None:
        """Commit the inspected graph once; stale document targets are never reused."""
        edits = self.curve_edits(curve)
        if edits:
            self.edit_keys(edits)
            if not self.editor.error and self.curve_editor:
                self.curve_editor.accept()
            elif self.curve_editor:
                self.curve_editor.message.setText(self.editor.error)

    def show_details(self) -> None:
        """Reveal precise endpoint values, time and interpolation without crowding the timeline."""
        if self.dope.selected_motion:
            window = next(
                (b for b in self.dope.motions if b["id"] == self.dope.selected_motion), None
            )
            if window:
                self.open_action(
                    {
                        "owner": window["character"],
                        "kind": window.get("kind", "motion"),
                        "frame": window["start"],
                        "segment": window["id"],
                    }
                )
                return
        selected = [
            (t, k)
            for t, k in self.editor.key_records()
            if (t.id, k.id) in self.editor.selected and t.extra.get("appearance_kind")
        ]
        discrete = [
            (t, k)
            for t, k in self.editor.key_records()
            if (t.id, k.id) in self.editor.selected
            and t.property_path in ("object.view", "camera.active", "object.attachment")
        ]
        if discrete:
            track, key = discrete[0]
            self.open_action(
                {
                    "owner": track.owner_id,
                    "kind": {
                        "object.view": "views",
                        "camera.active": "camera_cut",
                        "object.attachment": "attachment",
                    }[track.property_path],
                    "frame": key.frame,
                    "refs": tuple((t.id, k.id) for t, k in discrete if k.frame == key.frame),
                }
            )
            return
        if selected:
            track, key = selected[0]
            self.open_action(
                {
                    "owner": track.extra["appearance_owner"],
                    "kind": track.extra["appearance_kind"],
                    "frame": key.frame,
                    "refs": tuple((t.id, k.id) for t, k in selected if k.frame == key.frame),
                }
            )
            return
        self.details.show()
        self.details.resize(410, 290)
        self.details.raise_()

    def owner_item(
        self, key: str, records: dict[str, Any], nodes: dict[str, QTreeWidgetItem]
    ) -> QTreeWidgetItem:
        """Nest owner rows so bones and objects expand with their property tracks."""
        if key not in nodes:
            name = "Camera" if key == "__cameras__" else records[key].name
            row = QTreeWidgetItem([name])
            row.setToolTip(
                0,
                "Scene cameras"
                if key == "__cameras__"
                else f"{name} · {type(records[key]).__name__}",
            )
            row.setFlags(Qt.ItemFlag.ItemIsEnabled)
            font = row.font(0)
            font.setBold(True)
            row.setFont(0, font)
            for column in range(3):
                row.setBackground(column, QBrush(self.palette().alternateBase()))
            row.setData(0, Qt.ItemDataRole.UserRole + 1, key)
            row.setData(0, Qt.ItemDataRole.UserRole + 2, ("owner", key))
            nodes[key] = row
            parent = self._owner_parent.get(key)
            if parent and parent != key and parent in records:
                self.owner_item(parent, records, nodes).addChild(row)
            else:
                self.tracks.addTopLevelItem(row)
        return nodes[key]

    def expansion_changed(self) -> None:
        """Align visible headers with scalar or compound property lanes at identical spacing."""
        if self._building:
            return
        self._rows = []
        summaries: dict[int, tuple[str, ...]] = {}
        self.dope.action_rows = {}
        self.dope.overview_rows = {}
        motion_tracks: set[str] = set()

        def visit(row: QTreeWidgetItem | None) -> None:
            """Flatten visible properties while keeping owner headers free of editable keys."""
            if row is None or row.isHidden():
                return
            index = len(self._rows)
            members = row.data(0, Qt.ItemDataRole.UserRole + 3)
            action = row.data(0, Qt.ItemDataRole.UserRole + 6)
            if action:
                self.dope.action_rows[index] = tuple(action)
            motion = bool(action and action[1] in ("motion", "camera_motion", "camera_effect"))
            if motion and members:
                motion_tracks.update(members)
            self._rows.append(
                members[0] if members is not None and len(members) == 1 and not motion else None
            )
            if members is not None and len(members) > 1 and not motion:
                summaries[index] = tuple(members)
            identity = row.data(0, Qt.ItemDataRole.UserRole + 2)
            if identity and identity[0] == "owner":
                self.dope.overview_rows[index] = self.row_tracks(row)
            if row.isExpanded():
                for i in range(row.childCount()):
                    visit(row.child(i))

        for i in range(self.tracks.topLevelItemCount()):
            visit(self.tracks.topLevelItem(i))
        service = self.editor.service
        timeline, clip = (service.timeline, service.clip) if service else (None, None)
        self.dope.motions = (
            list(
                {
                    (t.extra.get("motion_window") or t.extra["camera_action"])["id"]: {
                        **(t.extra.get("motion_window") or t.extra["camera_action"]),
                        "locked": t.editing_locked,
                    }
                    for t in timeline.tracks
                    if t.id in motion_tracks and t.visible
                }.values()
            )
            if timeline
            else []
        )
        self.dope.rebuild(
            timeline.tracks if timeline else (),
            self._rows,
            timeline.markers if timeline else (),
            self.editor.selected,
            clip.out_frame if clip else service.scene.settings.end_frame if service else 120,
            summaries,
        )

    def refresh_transport(self) -> None:
        """Update transport fields and playheads without reconstructing key graphics."""
        session = self.model.session
        with QSignalBlocker(self.frame):
            if session:
                span, frame = session.playback.range, session.pose.frame
                self.dope.start = span.start
                self.dope.end = span.end
                self.max_frame.setMinimum(span.start + 0.001)
                self.max_frame.setValue(span.end)
                self.frame.setRange(span.start, span.end)
                self.frame.setValue(frame)
                self.time.setText(f"{span.frame_to_seconds(frame):.3f} s")
                self.range_label.setText(f"{span.start:g}–{span.end:g} · {span.fps:g} fps")
                for canvas in (self.dope,):
                    canvas.frame = frame
                    canvas.viewport().update()
                    canvas.ruler.update()
            else:
                self.range_label.setText("No playback")
                self.time.clear()
        self.note.setText(self.editor.error or self.model.error or "")
        self.note.setToolTip(self.note.text())
        self.note.setMinimumWidth(120 if self.note.text() else 0)
        self.note.setVisible(bool(self.note.text()))

    def set_end_frame(self, frame: float) -> None:
        """Commit a ruler or numeric playback cap and restore graphics after invalid edits."""
        self.editor.run(lambda service: service.set_end_frame(frame))
        self.refresh_transport()
        self.expansion_changed()

    def edit_keys(self, edits: dict[tuple[str, str], dict[str, Any]]) -> None:
        """Commit a gesture and restore source graphics after a rejected edit."""
        self.editor.run(lambda s: s.edit_keys(edits))
        if self.editor.error:
            self.expansion_changed()

    def track_settings(self, row: QTreeWidgetItem, column: int) -> None:
        """Persist locking/visibility while excluding hierarchy-only rows."""
        if not self._building and column in (1, 2):
            keys = self.row_tracks(row)
            locked = row.checkState(1) == Qt.CheckState.Checked
            visible = row.checkState(2) == Qt.CheckState.Checked

            def apply(service: Any) -> None:
                """Update a compound lane atomically, retaining untouched checkbox values."""
                with service.document.command_group("Track settings"):
                    for track in tuple(service.timeline.tracks):
                        if track.id in keys:
                            service.track_settings(
                                track.id,
                                locked=locked if column == 1 else track.editing_locked,
                                visible=visible if column == 2 else track.visible,
                            )

            if keys:
                document = self.editor.document
                source = document.project if document else None
                context = document.animation_context if document else None

                def commit() -> None:
                    """Rebuild after Qt releases the item, unless its document source changed."""
                    if (
                        self.editor.document is document
                        and document is not None
                        and document.project is source
                        and document.animation_context == context
                    ):
                        self.editor.run(apply)

                QTimer.singleShot(0, self, commit)

    def select_all(self) -> None:
        """Select keys on the active surface, respecting hidden tracks and curve filters."""
        self.editor.select(self.dope.keys)

    def select_lane(self, keys: tuple[str, ...]) -> None:
        """Target body/context commands at the clicked property without selecting owner headers."""
        candidates = [
            row for row in self._groups.values() if set(keys).intersection(self.row_tracks(row))
        ]
        if not candidates or not candidates[0].isSelected():
            self.tracks.clearSelection()
            for row in candidates:
                row.setSelected(True)

    def select_range(self, start: float, end: float) -> None:
        """Select a ruler range and offer that interval for preview or clip retiming."""
        self.editor.select(
            (t.id, k.id)
            for t, k in self.editor.key_records()
            if t.visible and start <= k.frame <= end
        )
        self.clip_editor.start.setValue(round(start) if self.editor.snap else start)
        self.clip_editor.end.setValue(round(end) if self.editor.snap else end)

    def apply_numeric(self) -> None:
        """Apply time/value deltas to preserve spacing within multi-key selections."""
        keys = [
            (t, k) for t, k in self.editor.key_records() if (t.id, k.id) in self.editor.selected
        ]
        if keys:
            dt, dv = (
                self.key_frame.value() - keys[0][1].frame,
                self.key_value.value() - float(keys[0][1].value),
            )
            self.edit_keys(
                {
                    (t.id, k.id): {
                        "frame": k.frame + dt,
                        "value": float(k.value) + dv,
                        "interpolation": self.interpolation.currentText(),
                    }
                    for t, k in keys
                }
            )

    def insert_key(self) -> None:
        """Capture selected owner/group/property lanes at the playhead, or open the channel
        catalog.
        """
        tracks = tuple(
            dict.fromkeys(
                key for row in self.tracks.selectedItems() for key in self.row_tracks(row)
            )
        )
        if not tracks:
            tracks = tuple(dict.fromkeys(ref[0] for ref in self.editor.selected))
        if tracks and self.model.session:
            self.insert_tracks(tracks, self.model.session.pose.frame)
        else:
            self.open_picker()

    def frame_curves(self) -> None:
        """Fit selected key time/value bounds or the current clip to the editing surfaces."""
        for canvas in (self.dope,):
            keys = [
                k
                for ref, k in canvas.source.items()
                if not self.editor.selected or ref in self.editor.selected
            ]
            if len(keys) < 2:
                selected_tracks = {ref[0] for ref in self.editor.selected}
                keys = [
                    k
                    for ref, k in canvas.source.items()
                    if not selected_tracks or ref[0] in selected_tracks
                ]
            first, last = (
                min((k.frame for k in keys), default=0),
                max((k.frame for k in keys), default=canvas.end),
            )
            canvas.pixels = max(
                0.05, min(200, (canvas.viewport().width() - 80) / max(1, last - first))
            )
            canvas.rebuild(
                canvas.tracks, canvas.rows, canvas.markers, self.editor.selected, canvas.end
            )
            canvas.horizontalScrollBar().setValue(round(first * canvas.pixels - 30))

    def set_snap(self, enabled: bool) -> None:
        """Share frame snapping between stopped playback, automatic keys and graphic edits."""
        self.editor.snap = enabled
        self.dope.snap = enabled
        self.model.snap = enabled

    def set_speed(self) -> None:
        """Set transient playback speed without changing stored key times."""
        self.model.speed = float(self.speed.currentData())

    def set_visualization(self) -> None:
        """Publish onion, trails and retained-frame comparison preferences."""
        self.editor.visualization(
            onion=self.onion.isChecked(),
            trails=self.trails.isChecked(),
            compare=self.compare.isChecked(),
        )

    def context_menu(self, position: Any) -> None:
        """Expose span, clipboard and precision commands beside the selected timeline keys."""
        menu = QMenu(self)
        for key in (
            "key",
            "tween",
            "convert",
            "step",
            "curve",
            "reverse",
            "cut",
            "copy",
            "paste",
            "duplicate",
            "delete",
            "all",
            "fit",
            "details",
        ):
            menu.addAction(self.edit_actions[key])
        self.add_spring_actions(
            menu, tuple(dict.fromkeys(track for track, _ in self.editor.selected))
        )
        self.extension_context_requested.emit(
            menu,
            "timeline",
            {"frame": self.model.session.playback.frame if self.model.session else 0},
        )
        menu.exec(position)

    def delete_selection(self) -> None:
        """Delete selected ordinary keys or the arranged motion, never its saved source."""
        if self.dope.selected_motion:
            self.editor.run(lambda s: self.remove_motion(s.document, self.dope.selected_motion))
        else:
            self.editor.delete()

    def remove_motion(self, document: Any, identity: str) -> None:
        """Dispatch a visible interval to its canonical character or camera authoring service."""
        from rigora.application_services.cameras import CameraService

        if any(
            b["id"] == identity and b.get("kind", "").startswith("camera_")
            for b in self.dope.motions
        ):
            CameraService(document).remove_action(identity)
        else:
            CharacterService(document).remove_segment(identity)

    def add_spring_actions(self, menu: QMenu, ids: tuple[str, ...]) -> None:
        """Expose activation and selective baking beside actual Spring keys or property rows."""
        service = self.editor.service
        tracks = (
            tuple(t for t in service.timeline.tracks if t.id in ids)
            if service and service.timeline
            else ()
        )
        spring = tuple(
            t
            for t in tracks
            if t.property_path.startswith("spring.") or t.extra.get("spring_motion_test")
        )
        if not spring:
            return
        menu.addSeparator()
        channels = {
            (t.owner_id, t.property_path) for t in spring if t.property_path.startswith("spring.")
        }
        if channels:
            for label, value in (("Spring On at playhead", 1.0), ("Spring Off at playhead", 0.0)):
                menu.addAction(
                    label,
                    partial(self.key_spring_channels, channels, value),
                )
        groups = {
            str(t.extra["spring_group"])
            for t in spring
            if t.extra.get("spring_group") not in (None, "Master")
        }
        if len(groups) == 1:
            group = next(iter(groups))
            menu.addAction(
                f"Bake Spring group · {group}…", lambda: self.bake_spring_requested.emit(group)
            )
        menu.addAction("Bake all Spring groups…", lambda: self.bake_spring_requested.emit(None))

    def key_spring_channels(self, channels: set[tuple[str, str]], value: float) -> None:
        """Key activation lanes through the same batch command as other scalar edits."""
        self.editor.run(
            lambda service: service.auto_key_values(
                {key: value for key in channels},
                self.model.session.pose.frame if self.model.session else 0,
            )
        )

    def track_command(self, command: str) -> None:
        """Scope whole-lane clipboard/removal commands to the hierarchy, not key selection."""
        import json

        ids = tuple(
            dict.fromkeys(
                key for row in self.tracks.selectedItems() for key in self.row_tracks(row)
            )
        )

        def apply(service: Any) -> None:
            """Keep copy/cut validation and track data in the shared authoring service."""
            if command in ("copy", "cut"):
                data = service.copy_tracks(ids)
                if command == "cut":
                    service.remove_tracks(ids)
                QApplication.clipboard().setText(json.dumps(data, allow_nan=False))
            elif command == "delete":
                service.remove_tracks(ids)
            elif command == "paste":
                raw = QApplication.clipboard().text()
                if len(raw) > 4 * 1024 * 1024:
                    raise ProjectError("The track clipboard exceeds the 4 MiB limit.")
                frame = self.model.session.pose.frame if self.model.session else 0
                self.editor.selected = service.paste_tracks(json.loads(raw), frame)

        self.editor.run(apply)

    def track_menu(self, position: Any) -> None:
        """Offer whole-property editing on selected rows, excluding inert object headers."""
        row = self.tracks.itemAt(position)
        if row is None or not row.flags() & Qt.ItemFlag.ItemIsSelectable:
            self.tracks.clearSelection()
        if row is not None and row.flags() & Qt.ItemFlag.ItemIsSelectable and not row.isSelected():
            self.tracks.clearSelection()
            row.setSelected(True)
        menu = QMenu(self)
        self.add_spring_actions(
            menu,
            tuple(
                dict.fromkeys(
                    key for row in self.tracks.selectedItems() for key in self.row_tracks(row)
                )
            ),
        )
        has_tracks = any(self.row_tracks(row) for row in self.tracks.selectedItems())
        menu.addAction("Key tracks at playhead", self.insert_key).setEnabled(has_tracks)
        menu.addSeparator()
        for label, command in (
            ("Cut tracks", "cut"),
            ("Copy tracks", "copy"),
            ("Paste tracks at playhead", "paste"),
            ("Remove tracks", "delete"),
        ):
            menu.addAction(label, partial(self.track_command, command)).setEnabled(
                has_tracks or command == "paste"
            )
        menu.addSeparator()
        menu.addAction("Add tracks…", self.open_picker)
        self.extension_context_requested.emit(
            menu,
            "timeline",
            {
                "track_ids": tuple(
                    key for row in self.tracks.selectedItems() for key in self.row_tracks(row)
                )
            },
        )
        menu.exec(self.tracks.viewport().mapToGlobal(position))
