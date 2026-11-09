"""Rigora-native Motion Pilot controls and scoped mouse/tablet input over an MVVM capture state."""

import math
from dataclasses import fields
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QElapsedTimer, QEvent, QObject, QPointF, Qt, QTimer
from PySide6.QtGui import QHideEvent, QKeyEvent, QMouseEvent, QShowEvent, QTabletEvent
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from rigora.application_services.characters import CharacterService
from rigora.application_services.motion_pilot import MotionPilotService
from rigora.domain.entities import Character
from rigora.domain.motion_pilot import MotionPilotProfile
from rigora.domain.project import ProjectError
from rigora.presentation.viewmodels.motion_pilot import MotionPilotViewModel
from rigora.presentation.widgets.file_dialogs import choose_open_file, choose_save_file
from rigora.presentation.widgets.window_frame import CustomDialog

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


class MotionPilot(CustomDialog):
    """Configure independent mappings and flock members without grabbing global pointer input."""

    def __init__(self, host: "MainWindow") -> None:
        """Build collapsible sections and register input only while the panel is visible."""
        super().__init__(host, "Motion Pilot")
        self.host = host
        self.model = MotionPilotViewModel(host.viewmodel, self)
        self.loading = True
        self.document = host.viewmodel.documents
        self.pending_profile: tuple[Any, str, MotionPilotProfile, object] | None = None
        self.resize(460, 830)
        self.setMinimumSize(390, 480)
        self.controls: dict[str, Any] = {}
        self.target_selections: dict[str, set[str]] = {}
        self.pointer = (0.0, 0.0)
        self.clock = QElapsedTimer()
        self.clock_start = 0.0
        self.last_frame = -1
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.tick)
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(120)
        self.save_timer.timeout.connect(self.save_profile)
        outer = QVBoxLayout(self.content)
        self.leader = QComboBox()
        self.leader.setAccessibleName("Motion Pilot lead object")
        outer.addWidget(self.leader)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        self.sections = QVBoxLayout(body)
        self.sections.setContentsMargins(3, 3, 3, 3)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        self.add_section(
            "Transform",
            (
                ("move", "Move"),
                ("move_x", "X sensitivity"),
                ("move_x_axis", "X input"),
                ("move_y", "Y sensitivity"),
                ("move_y_axis", "Y input"),
                ("space", "Coordinates"),
                ("rotate", "Rotate"),
                ("rotation_gain", "Degrees per pixel"),
                ("rotation_axis", "Rotation input"),
                ("scale", "Scale"),
                ("uniform", "Uniform scale"),
                ("width_gain", "Width gain / pixel"),
                ("width_axis", "Width input"),
                ("height_gain", "Height gain / pixel"),
                ("height_axis", "Height input"),
                ("face", "Face cursor"),
                ("forward_angle", "Forward angle °"),
                ("turn_smoothness", "Turn smoothing · s"),
            ),
        )
        self.add_section(
            "Wave",
            (
                ("wave_move", "Move amplitude"),
                ("wave_x", "X · px"),
                ("wave_y", "Y · px"),
                ("wave_rotate", "Rotate amplitude"),
                ("wave_angle", "Angle °"),
                ("wave_scale", "Scale amplitude"),
                ("wave_width", "Width ratio"),
                ("wave_height", "Height ratio"),
                ("wave_speed", "Cycles / second"),
                ("wave_mouse", "Use mouse movement · 100 px/cycle"),
            ),
        )
        motion = self.add_section(
            "Motion",
            (
                ("motion_enabled", "Blend native motion"),
                ("motion_speed", "Playback speed ×"),
                ("motion_reverse", "Reverse animation"),
                ("motion_in_place", "Move in place · constrain root X"),
                ("motion_trigger", "Trigger"),
            ),
        )
        self.available = QComboBox()
        self.available.setAccessibleName("Available native animation clips")
        motion.addRow(self.available)
        self.loaded = QListWidget()
        self.loaded.setAccessibleName("Loaded motion layers in blend order")
        self.loaded.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.loaded.setMaximumHeight(200)
        motion.addRow(self.loaded)
        clip_buttons = QHBoxLayout()
        for label, icon, callback in (
            ("Add clip", "add", self.add_clip),
            ("Remove selected clip", "delete", self.remove_clip),
            ("Import native action", "folder_open", self.import_action),
        ):
            clip_buttons.addWidget(self.icon_button(label, icon, callback))
        motion.addRow(clip_buttons)
        flock = self.add_section(
            "Flock Settings",
            (
                ("delay_mode", "Follower delay"),
                ("delay_frames", "Uniform interval · frames"),
                ("delay_min", "Random minimum · frames"),
                ("delay_max", "Random maximum · frames"),
                ("seed", "Random seed"),
            ),
        )
        self.followers = QListWidget()
        self.followers.setAccessibleName("Flock followers")
        self.followers.setMaximumHeight(180)
        self.followers.itemChanged.connect(self.settings_changed)
        flock.addRow(self.followers)
        add_selection = QPushButton(host.icons.icon("group_add"), "Add selected objects to flock")
        add_selection.clicked.connect(self.add_selection)
        flock.addRow(add_selection)
        self.add_section(
            "Puppet Settings",
            (
                ("lazy_mouse", "Lazy Mouse · s"),
                ("cursor_start", "Cursor reference"),
                ("blend", "Blend with current motion"),
                ("optimize", "Optimize position keys"),
                ("tolerance", "Position tolerance · px/axis"),
            ),
        )
        self.sections.addStretch()
        profile_buttons = QHBoxLayout()
        for label, icon, callback in (
            ("Import profile", "folder_open", self.import_profile),
            ("Save reusable profile", "save", self.export_profile),
        ):
            profile_buttons.addWidget(self.icon_button(label, icon, callback))
        profile_buttons.addStretch()
        outer.addLayout(profile_buttons)
        transport = QHBoxLayout()
        self.preview_button = QPushButton(host.icons.icon("play_arrow"), "Preview")
        self.record_button = QPushButton(host.icons.icon("fiber_manual_record"), "Record")
        self.pause_button = self.icon_button("Pause or resume capture", "pause", self.pause)
        self.stop_button = self.icon_button("Stop capture and keep recording", "stop", self.stop)
        self.cancel_button = self.icon_button("Cancel capture", "close", self.cancel_capture)
        self.preview_button.clicked.connect(lambda: self.arm(False))
        self.record_button.clicked.connect(lambda: self.arm(True))
        for widget in (
            self.preview_button,
            self.record_button,
            self.pause_button,
            self.stop_button,
            self.cancel_button,
        ):
            transport.addWidget(widget)
        outer.addLayout(transport)
        self.start_button = QPushButton(host.icons.icon("play_arrow"), "Start recording · Space")
        self.start_button.setAccessibleName("Start armed Motion Pilot capture")
        self.start_button.clicked.connect(self.start_capture)
        outer.addWidget(self.start_button)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(3)
        self.progress.hide()
        outer.addWidget(self.progress)
        self.status = QLabel()
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        self.leader.currentIndexChanged.connect(self.load_target)
        self.model.changed.connect(self.sync)
        host.viewmodel.changed.connect(self.source_changed)
        self.refresh_targets()
        self.loading = False
        self.load_target()
        self.sync()

    def icon_button(self, label: str, icon: str, callback: Any) -> QToolButton:
        """Create a compact, accessible Material command using shared neutral styling."""
        button = QToolButton()
        button.setIcon(self.host.icons.icon(icon))
        button.setToolTip(label)
        button.setAccessibleName(label)
        button.clicked.connect(lambda checked=False: callback())
        return button

    def add_section(self, title: str, specs: tuple[tuple[str, str], ...]) -> QFormLayout:
        """Create independent disclosure and scalar editors without nested scroll areas."""
        header = QToolButton()
        header.setText(title)
        header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        header.setCheckable(True)
        header.setChecked(title == "Transform")
        header.setIcon(
            self.host.icons.icon("expand_more" if header.isChecked() else "chevron_right")
        )
        header.setAccessibleName(f"Expand or collapse {title}")
        body = QWidget()
        form = QFormLayout(body)
        form.setContentsMargins(4, 6, 4, 10)
        body.setVisible(header.isChecked())
        header.toggled.connect(body.setVisible)
        header.toggled.connect(
            lambda checked: header.setIcon(
                self.host.icons.icon("expand_more" if checked else "chevron_right")
            )
        )
        self.sections.addWidget(header)
        self.sections.addWidget(body)
        defaults = MotionPilotProfile()
        choices = {
            "space": ("World", "Local"),
            "face": ("Off", "Flip", "Turn"),
            "motion_trigger": ("Automatic", "Mouse movement", "Click to play", "Click to loop"),
            "delay_mode": ("None", "Uniform", "Random"),
            "cursor_start": ("Object", "Viewport center"),
        }
        ranges = {
            "wave_speed": (0, 30),
            "motion_speed": (0.01, 100),
            "lazy_mouse": (0, 10),
            "turn_smoothness": (0, 10),
            "tolerance": (0.001, 100),
            "delay_frames": (0, 10000),
            "delay_min": (0, 10000),
            "delay_max": (0, 10000),
            "seed": (-100000, 100000),
        }
        for name, label in specs:
            default = getattr(defaults, name)
            if type(default) is bool:
                control: Any = QCheckBox(label)
                control.setChecked(default)
                control.toggled.connect(self.settings_changed)
                form.addRow(control)
            elif isinstance(default, str):
                control = QComboBox()
                control.addItems(list(choices.get(name, ("X", "Y", "-X", "-Y"))))
                control.setCurrentText(default)
                control.currentIndexChanged.connect(self.settings_changed)
                form.addRow(label, control)
            else:
                control = (
                    QSpinBox() if name in ("delay_min", "delay_max", "seed") else QDoubleSpinBox()
                )
                low, high = ranges.get(name, (-100000, 100000))
                control.setRange(low, high)
                if isinstance(control, QDoubleSpinBox):
                    control.setDecimals(3)
                control.setValue(default)
                control.setKeyboardTracking(False)
                control.valueChanged.connect(self.settings_changed)
                form.addRow(label, control)
            control.setAccessibleName(label)
            control.setToolTip(label)
            self.controls[name] = control
        return form

    def refresh_targets(self) -> None:
        """Retain target identities across edits, preferring the current Scene selection."""
        self.loading = True
        current = self.leader.currentData()
        self.leader.clear()
        service = CharacterService(self.host.viewmodel.documents)
        pilot = MotionPilotService(self.host.viewmodel.documents)
        selected = set(self.host.viewmodel.scene.selected)
        for owner in service.scene_objects():
            record = service.records()[owner]
            original = owner
            if isinstance(record, Character):
                roots = [
                    bone.id
                    for rig in service.scene.skeletons
                    if rig.id == record.skeleton_id
                    for bone in rig.bones
                    if bone.parent_id is None
                ]
                if len(roots) != 1:
                    continue
                owner = roots[0]
            self.target_selections[owner] = pilot.target_members(owner) | {original}
            self.leader.addItem(record.name, owner)
            if current is None and self.target_selections[owner].intersection(selected):
                current = owner
        index = self.leader.findData(current)
        self.leader.setCurrentIndex(max(0, index))
        self.loading = False

    def load_target(self) -> None:
        """Restore the selected object's settings; inspecting another target never overwrites it."""
        if self.loading or self.model.state != "Idle" or not self.leader.currentData():
            return
        self.loading = True
        try:
            profile = MotionPilotService(self.host.viewmodel.documents).profile(
                self.leader.currentData()
            )
            for field in fields(profile):
                control = self.controls.get(field.name)
                if control is None:
                    continue
                value = getattr(profile, field.name)
                if isinstance(control, QCheckBox):
                    control.setChecked(value)
                elif isinstance(control, QComboBox):
                    control.setCurrentText(value)
                else:
                    control.setValue(value)
            self.followers.clear()
            for i in range(self.leader.count()):
                owner = self.leader.itemData(i)
                if owner != self.leader.currentData():
                    item = QListWidgetItem(self.leader.itemText(i))
                    item.setData(Qt.ItemDataRole.UserRole, owner)
                    item.setCheckState(
                        Qt.CheckState.Checked
                        if owner in profile.followers
                        else Qt.CheckState.Unchecked
                    )
                    self.followers.addItem(item)
            self.available.clear()
            clips = MotionPilotService(self.host.viewmodel.documents).scene.clips
            for clip in clips:
                self.available.addItem(clip.name, clip.id)
            self.loaded.clear()
            for key in profile.motion_clips:
                loaded_clip = next((c for c in clips if c.id == key), None)
                item = QListWidgetItem(
                    loaded_clip.name if loaded_clip else "Missing motion · remove or replace"
                )
                item.setData(Qt.ItemDataRole.UserRole, key)
                self.loaded.addItem(item)
            self.loaded.setFixedHeight(max(32, 28 * self.loaded.count() + 4))
            self.model.profile = profile
        except ProjectError as error:
            self.model.status = str(error)
        finally:
            self.loading = False
        self.control_states()

    def profile(self) -> MotionPilotProfile:
        """Collect typed control values and explicit member/clip identities for validation."""
        values: dict[str, Any] = {
            name: control.isChecked()
            if isinstance(control, QCheckBox)
            else control.currentText()
            if isinstance(control, QComboBox)
            else control.value()
            for name, control in self.controls.items()
        }
        values["motion_clips"] = tuple(
            self.loaded.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.loaded.count())
        )
        values["followers"] = tuple(
            self.followers.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.followers.count())
            if self.followers.item(i).checkState() == Qt.CheckState.Checked
        )
        return MotionPilotProfile(**values)

    def control_states(self) -> None:
        """Keep Turn and independent height controls consistent with their effective mapping."""
        turning = self.controls["face"].currentText() == "Turn"
        for name in ("rotate", "rotation_gain", "rotation_axis"):
            self.controls[name].setEnabled(not turning)
        for name in ("height_gain", "height_axis"):
            self.controls[name].setEnabled(not self.controls["uniform"].isChecked())

    def settings_changed(self, *_: Any) -> None:
        """Coalesce profile edits; live changes affect subsequent samples immediately."""
        if self.loading:
            return
        self.control_states()
        try:
            profile = self.profile()
            if self.model.session:
                self.model.update_profile(profile)
            else:
                self.pending_profile = (
                    self.host.viewmodel.documents,
                    self.leader.currentData(),
                    profile,
                    self.host.viewmodel.documents.project,
                )
                self.save_timer.start()
        except ProjectError as error:
            self.status.setText(str(error))

    def save_profile(self) -> None:
        """Store only the leader's settings, leaving every follower's saved profile untouched."""
        if self.loading or not self.leader.currentData() or self.model.session:
            return
        try:
            pending = self.pending_profile
            self.pending_profile = None
            document, owner, profile, revision = pending or (
                self.host.viewmodel.documents,
                self.leader.currentData(),
                self.profile(),
                self.host.viewmodel.documents.project,
            )
            if document is not self.host.viewmodel.documents or document.project is not revision:
                return
            self.model.profile = profile
            service = MotionPilotService(document)
            if service.profile(owner) != profile:
                self.host.viewmodel.animation_editor.run(
                    lambda _: service.set_profile(owner, profile)
                )
        except ProjectError as error:
            self.status.setText(str(error))

    def add_clip(self) -> None:
        """Add an existing native clip as another ordered motion layer."""
        key = self.available.currentData()
        if key and self.loaded.count() < 8 and key not in self.profile().motion_clips:
            item = QListWidgetItem(self.available.currentText())
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.loaded.addItem(item)
            self.loaded.setFixedHeight(max(32, 28 * self.loaded.count() + 4))
            self.settings_changed()

    def remove_clip(self) -> None:
        """Remove a loaded layer reference while retaining its source animation in the project."""
        self.loaded.takeItem(self.loaded.currentRow())
        self.loaded.setFixedHeight(max(32, 28 * self.loaded.count() + 4))
        self.settings_changed()

    def add_selection(self) -> None:
        """Merge current Scene selections into the flock without resetting existing members."""
        selected = set(self.host.viewmodel.scene.selected)
        for i in range(self.followers.count()):
            item = self.followers.item(i)
            owner = item.data(Qt.ItemDataRole.UserRole)
            if self.target_selections.get(owner, {owner}).intersection(selected):
                item.setCheckState(Qt.CheckState.Checked)

    def import_action(self) -> None:
        """Use the native OS picker and existing validated Rigora action importer."""
        self.model.cancel(quiet=True)
        path, _ = choose_open_file(
            self, "Load Motion Pilot animation", "", "Rigora native actions (*.rigaction)"
        )
        if not path:
            return
        selected = self.host.viewmodel.documents.selected_clip_id
        created = []
        self.host.viewmodel.animation_editor.run(
            lambda service: created.append(service.import_action(Path(path)))
        )
        if selected:
            self.host.viewmodel.documents.select_animation_clip(selected)
        self.load_target()
        if created:
            self.available.setCurrentIndex(self.available.findData(created[0]))
            self.add_clip()

    def import_profile(self) -> None:
        """Load reusable inert settings onto the explicit leader using a native file picker."""
        path, _ = choose_open_file(
            self, "Load Motion Pilot profile", "", "Rigora Pilot profiles (*.rigpilot)"
        )
        if path and self.leader.currentData():
            self.model.cancel(quiet=True)
            self.host.viewmodel.animation_editor.run(
                lambda _: MotionPilotService(self.host.viewmodel.documents).import_profile(
                    self.leader.currentData(), Path(path)
                )
            )
            self.load_target()

    def export_profile(self) -> None:
        """Export validated saved settings without overwriting an existing profile silently."""
        self.save_profile()
        path, _ = choose_save_file(
            self, "Save Motion Pilot profile", "", "Rigora Pilot profiles (*.rigpilot)"
        )
        if path and self.leader.currentData():
            try:
                MotionPilotService(self.host.viewmodel.documents).export_profile(
                    self.leader.currentData(), Path(path)
                )
            except (ProjectError, OSError) as error:
                self.status.setText(str(error))

    def arm(self, recording: bool) -> None:
        """Arm scoped Space input without changing focus or the OS cursor position."""
        self.save_timer.stop()
        if not self.leader.currentData():
            return
        try:
            self.save_profile()
            profile = self.profile()
            self.model.arm(
                (self.leader.currentData(), *profile.followers), profile, recording=recording
            )
        except ProjectError as error:
            self.status.setText(str(error))

    def current_frame(self) -> float:
        """Read the monotonic capture clock; paused time contributes no animation frames."""
        if not self.model.session:
            return 0
        return (
            self.model.session.raw_time
            if self.model.paused
            else min(
                self.model.session.end,
                self.clock_start + self.clock.elapsed() / 1000 * self.model.session.fps,
            )
        )

    def start_capture(self) -> None:
        """Start an armed take from either the visible button or the Space shortcut."""
        if self.model.state not in ("Preview armed", "Record armed"):
            return
        self.save_timer.stop()
        self.save_profile()
        viewport = self.host.viewport
        center = (QPointF(viewport.rect().center()) - viewport.offset) / viewport.zoom
        self.model.start(self.pointer, (center.x(), center.y()))

    def tick(self) -> None:
        """Evaluate new project frames; prepare recorded keys off the UI thread."""
        session = self.model.session
        if session is None:
            return
        frame = self.current_frame()
        if math.floor(frame) > self.last_frame:
            self.last_frame = math.floor(frame)
            self.model.capture(frame, self.pointer)
        if frame >= session.end:
            self.stop()

    def pause(self) -> None:
        """Pause without losing the last sample and restart the UI clock only on resume."""
        self.model.pause()

    def cancel_capture(self) -> None:
        """Discard captured motion while retaining deliberately edited profile settings."""
        self.model.cancel()
        self.save_profile()

    def stop(self) -> None:
        """Keep the final input and publish recordings; discard ordinary previews."""
        self.model.stop(self.current_frame(), self.pointer)
        if self.model.state == "Idle":
            self.save_profile()

    def sync(self) -> None:
        """Reflect interaction state without rebuilding controls or stealing viewport focus."""
        session = self.model.session
        active = session is not None and self.model.state != "Preparing"
        if active and session is not None and not self.model.paused and not self.timer.isActive():
            self.clock_start = session.raw_time
            self.clock.restart()
            self.last_frame = math.floor(self.clock_start)
            self.timer.start()
        elif not active or self.model.paused:
            self.timer.stop()
        self.status.setText(self.model.status)
        idle = self.model.state == "Idle"
        armed = self.model.state in ("Preview armed", "Record armed")
        self.start_button.setVisible(armed)
        self.start_button.setText(
            "Start recording · Space" if self.model.recording else "Start preview · Space"
        )
        self.leader.setEnabled(idle)
        self.preview_button.setEnabled(idle)
        self.record_button.setEnabled(idle)
        self.pause_button.setEnabled(active)
        self.stop_button.setEnabled(not idle and self.model.state != "Preparing")
        self.cancel_button.setEnabled(not idle)
        self.progress.setVisible(self.model.state == "Preparing")

    def source_changed(self) -> None:
        """Retain active controls during capture and rebuild target choices after ordinary edits."""
        if self.isVisible() and self.document is not self.host.viewmodel.documents:
            self.close()
        elif self.isVisible() and self.model.state == "Idle":
            self.refresh_targets()
            self.load_target()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Scope Space and pointer/tablet capture to this tool's host; text input remains native."""
        if not self.isVisible() or self.model.state == "Idle" or self.model.state == "Preparing":
            return super().eventFilter(watched, event)
        focus = watched if isinstance(watched, QWidget) else QApplication.focusWidget()
        if isinstance(event, QKeyEvent) and (
            isinstance(focus, (QLineEdit, QAbstractSpinBox, QTextEdit, QPlainTextEdit))
            or isinstance(focus, QComboBox)
            and focus.isEditable()
        ):
            return super().eventFilter(watched, event)
        if (
            isinstance(event, QKeyEvent)
            and event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Escape)
            and isinstance(watched, QWidget)
            and (watched.window() in (self, self.host))
        ):
            if event.type() == QEvent.Type.ShortcutOverride:
                event.accept()
                return True
            if event.type() == QEvent.Type.KeyPress and not event.isAutoRepeat():
                if event.key() == Qt.Key.Key_Escape:
                    self.cancel_capture()
                elif self.model.session:
                    self.stop()
                else:
                    self.start_capture()
                return True
        if watched is self.host.viewport and isinstance(event, (QMouseEvent, QTabletEvent)):
            position = (event.position() - self.host.viewport.offset) / self.host.viewport.zoom
            self.pointer = (position.x(), position.y())
            if self.model.session is None:
                # Arming must leave selection and focus usable until capture starts.
                return super().eventFilter(watched, event)
            if self.model.session and event.type() in (
                QEvent.Type.MouseButtonPress,
                QEvent.Type.TabletPress,
            ):
                self.model.capture(self.current_frame(), self.pointer, clicked=True)
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def showEvent(self, event: QShowEvent) -> None:
        """Install a tool-scoped application filter only while the panel is available."""
        super().showEvent(event)
        app = QApplication.instance()
        if app:
            app.installEventFilter(self)

    def hideEvent(self, event: QHideEvent) -> None:
        """Remove listeners and cancel live or pending capture before releasing the panel."""
        self.save_timer.stop()
        self.model.cancel(quiet=True)
        if not self.host._closed and self.document is self.host.viewmodel.documents:
            self.save_profile()
        self.timer.stop()
        app = QApplication.instance()
        if app:
            app.removeEventFilter(self)
        super().hideEvent(event)
