"""Named clip management, reusable actions, ranges, transitions and marker annotations."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QWidget,
)

from rigora.engine.time import FrameRange
from rigora.presentation.icons import IconProvider
from rigora.presentation.viewmodels.animation_editor import AnimationEditorViewModel
from rigora.presentation.widgets.file_dialogs import choose_open_file, choose_save_file
from rigora.presentation.widgets.message_dialogs import ask_question


def numeric(
    parent: QWidget, label: str, *, minimum: float = -1e9, maximum: float = 1e9
) -> QDoubleSpinBox:
    """Create an accessible finite scalar editor that commits only on deliberate input."""
    from PySide6.QtWidgets import QDoubleSpinBox

    field = QDoubleSpinBox(parent)
    field.setAccessibleName(label)
    field.setRange(minimum, maximum)
    field.setDecimals(3)
    field.setKeyboardTracking(False)
    return field


class ClipEditor(QScrollArea):
    """Edit clip records through commands and retain preview ranges as transport-only state."""

    def __init__(self, model: AnimationEditorViewModel, icons: IconProvider) -> None:
        """Build explicit clip operations and data-only import/export with standard safeguards."""
        super().__init__()
        self.model, self.icons = model, icons
        self._source: tuple[int, str | None] | None = None
        self.setWidgetResizable(True)
        body = QWidget()
        self.setWidget(body)
        layout = QHBoxLayout(body)
        layout.setSpacing(24)
        left, right = QFormLayout(), QFormLayout()
        for form in (left, right):
            form.setHorizontalSpacing(12)
            form.setVerticalSpacing(8)
        layout.addLayout(left, 1)
        layout.addLayout(right, 1)
        self.name = QLineEdit()
        self.name.setAccessibleName("Clip name")
        self.annotation = QLineEdit()
        self.annotation.setAccessibleName("Clip annotation")
        self.start = numeric(self, "Clip in frame", minimum=0, maximum=1e7)
        self.end = numeric(self, "Clip out frame", minimum=0, maximum=1e7)
        self.loop = QCheckBox("Loop clip by default")
        left.addRow("Name", self.name)
        left.addRow("Annotation", self.annotation)
        spans = QHBoxLayout()
        spans.addWidget(self.start)
        spans.addWidget(self.end)
        left.addRow("In / out", spans)
        left.addRow(self.loop)
        commands = QHBoxLayout()
        commands.addWidget(self.button("Save settings", "save", self.save_settings))
        commands.addWidget(self.button("Preview range", "play_arrow", self.preview_range))
        left.addRow(commands)
        self.offset_x = numeric(self, "Clip root X offset")
        self.offset_y = numeric(self, "Clip root Y offset")
        self.offset_rotation = numeric(self, "Clip root rotation offset")
        offsets = QHBoxLayout()
        for field in (self.offset_x, self.offset_y, self.offset_rotation):
            offsets.addWidget(field)
        left.addRow("Root offsets X / Y / °", offsets)
        transforms = QHBoxLayout()
        transforms.addWidget(self.button("Retime / offset", "schedule", lambda: self.retime(False)))
        transforms.addWidget(
            self.button("Reverse / retime", "swap_horiz", lambda: self.retime(True))
        )
        left.addRow(transforms)
        actions = QHBoxLayout()
        actions.addWidget(
            self.button(
                "New clip",
                "add",
                lambda: model.run(lambda s: s.new_clip(self.name.text() or "Animation")),
            )
        )
        actions.addWidget(
            self.button(
                "Duplicate clip",
                "content_copy",
                lambda: model.run(
                    lambda s: s.new_clip(
                        (self.name.text() or "Animation") + " copy", duplicate=True
                    )
                ),
            )
        )
        actions.addWidget(self.button("Export action", "file_upload", self.export_action))
        actions.addWidget(self.button("Reuse action", "file_download", self.import_action))
        left.addRow(actions)
        self.other = QComboBox()
        self.other.setAccessibleName("Blend source clip")
        self.weight = numeric(self, "Blend weight", minimum=0, maximum=1)
        self.weight.setValue(0.5)
        self.transition = numeric(self, "Transition length in frames", minimum=0, maximum=10000)
        right.addRow("Blend with", self.other)
        right.addRow("Weight", self.weight)
        right.addRow("End transition (frames)", self.transition)
        right.addRow(
            self.button(
                "Create blended clip",
                "merge_type",
                lambda: model.run(
                    lambda s: s.blend(
                        str(self.other.currentData()), self.weight.value(), self.transition.value()
                    )
                ),
            )
        )
        self.markers = QComboBox()
        self.markers.setAccessibleName("Timeline markers")
        self.markers.currentIndexChanged.connect(self.select_marker)
        self.marker_name = QLineEdit("Marker")
        self.marker_name.setAccessibleName("Marker label")
        self.marker_note = QLineEdit()
        self.marker_note.setAccessibleName("Marker annotation")
        self.marker_frame = numeric(self, "Marker frame", minimum=0, maximum=1e7)
        right.addRow("Markers", self.markers)
        marker_fields = QHBoxLayout()
        marker_fields.addWidget(self.marker_name)
        marker_fields.addWidget(self.marker_frame)
        right.addRow("Label / frame", marker_fields)
        right.addRow("Marker note", self.marker_note)
        self.event_type = QComboBox()
        self.event_type.addItem("Annotation", "")
        from rigora.engine.game_events import EVENT_TYPES

        for kind in EVENT_TYPES:
            self.event_type.addItem(f"Game event · {kind}", kind)
        self.event_payload = QLineEdit("{}")
        self.event_payload.setAccessibleName("Game event JSON payload")
        right.addRow("Marker type", self.event_type)
        right.addRow("Event data · JSON", self.event_payload)
        marker_commands = QHBoxLayout()
        marker_commands.addWidget(self.button("Add", "add", lambda: self.marker(new=True)))
        marker_commands.addWidget(self.button("Update", "save", self.marker))
        marker_commands.addWidget(
            self.button("Delete", "delete_outline", lambda: self.marker(delete=True))
        )
        marker_commands.addWidget(
            self.button(
                "Go to", "arrow_forward", lambda: model.playback.seek(self.marker_frame.value())
            )
        )
        right.addRow(marker_commands)
        for row in (spans, commands, offsets, transforms, actions, marker_fields, marker_commands):
            row.setSpacing(8)
        note = QLabel(
            "Blends and transitions create independent frame-sampled clips. "
            "Retiming edits source keys and Bézier timing; duplicate first to keep another version."
        )
        note.setWordWrap(True)
        note.setObjectName("Muted")
        right.addRow(note)

    def button(self, text: str, icon: str, callback: Callable[..., Any]) -> QPushButton:
        """Create a shared Material control with accessible text and theme metadata."""
        button = QPushButton(self.icons.icon(icon), text)
        button.setProperty("materialIcon", icon)
        button.clicked.connect(callback)
        return button

    def refresh(self) -> None:
        """Refresh authored clip fields only when their immutable source changes."""
        service = self.model.service
        if service is None:
            self.setEnabled(False)
            return
        self.setEnabled(True)
        try:
            clip, timeline = service.clip, service.timeline
        except ValueError:
            return
        source = id(service.scene), clip.id if clip else None
        if source == self._source:
            return
        self._source = source
        for field in (self.offset_x, self.offset_y, self.offset_rotation):
            field.setValue(0)
        if clip:
            self.name.setText(clip.name)
            self.annotation.setText(clip.annotation)
            self.start.setValue(clip.in_frame)
            self.end.setValue(clip.out_frame)
            self.loop.setChecked(clip.loop)
        else:
            self.name.setText("Animation")
            self.annotation.clear()
            self.start.setValue(service.scene.settings.start_frame)
            self.end.setValue(service.scene.settings.end_frame)
        with QSignalBlocker(self.other), QSignalBlocker(self.markers):
            self.other.clear()
            self.markers.clear()
            for item in service.document.context_clips():
                if not clip or item.id != clip.id:
                    self.other.addItem(item.name, item.id)
            for marker in timeline.markers if timeline else ():
                self.markers.addItem(f"{marker.frame:g} · {marker.name}", marker.id)
        self.select_marker()

    def select_marker(self) -> None:
        """Load the selected annotation without changing playback or persisted data."""
        service = self.model.service
        timeline = service.timeline if service else None
        marker = (
            next((m for m in timeline.markers if m.id == self.markers.currentData()), None)
            if timeline
            else None
        )
        if marker:
            self.marker_name.setText(marker.name)
            self.marker_frame.setValue(marker.frame)
            self.marker_note.setText(marker.annotation)
            data = marker.extra.get("game_event", {})
            self.event_type.setCurrentIndex(max(0, self.event_type.findData(data.get("type", ""))))
            from rigora.domain.validation import json_copy

            self.event_payload.setText(json.dumps(json_copy(data.get("payload", {}))))

    def marker(self, *, new: bool = False, delete: bool = False) -> None:
        """Commit marker text and frame together with undo support."""
        try:
            payload = json.loads(self.event_payload.text()) if self.event_type.currentData() else {}
        except ValueError:
            self.model.error = "Enter a valid JSON object for the game event payload."
            self.model.changed.emit()
            return
        self.model.run(
            lambda s: s.marker(
                self.marker_name.text(),
                self.marker_frame.value(),
                self.marker_note.text(),
                key="" if new else str(self.markers.currentData() or ""),
                delete=delete,
                event_type=self.event_type.currentData(),
                payload=payload,
            )
        )

    def save_settings(self) -> None:
        """Store clip display, inclusive playback range and default loop policy."""
        self.model.run(
            lambda s: s.clip_settings(
                name=self.name.text(),
                annotation=self.annotation.text(),
                in_frame=self.start.value(),
                out_frame=self.end.value(),
                loop=self.loop.isChecked(),
            )
        )

    def preview_range(self) -> None:
        """Temporarily restrict transport to the entered range without trimming source keys."""
        session = self.model.playback.session
        if session:
            from rigora.domain.project import ProjectError

            try:
                span = FrameRange(self.start.value(), self.end.value(), session.scene.settings.fps)
                if (
                    span.start < session.evaluator.range.start
                    or span.end > session.evaluator.range.end
                ):
                    raise ProjectError(
                        "Preview ranges must be inside the clip's saved in/out points."
                    )
                self.model.playback.pause()
                session.playback.range = span
                self.model.playback.seek(span.start)
                self.model.error = ""
            except ProjectError as error:
                self.model.error = str(error)
            self.model.changed.emit()

    def retime(self, reverse: bool) -> None:
        """Apply entered destination times and root offsets through one service command."""
        self.model.run(
            lambda s: s.retime(
                self.start.value(),
                self.end.value(),
                reverse=reverse,
                offset_x=self.offset_x.value(),
                offset_y=self.offset_y.value(),
                rotation=self.offset_rotation.value(),
            )
        )

    def export_action(self) -> None:
        """Save portable motion with an explicit overwrite decision for existing files."""
        path, _ = choose_save_file(
            self, "Export reusable animation", "animation.rigaction", "Rigora actions (*.rigaction)"
        )
        if not path:
            return
        target = Path(path)
        overwrite = False
        if target.exists():
            overwrite = (
                ask_question(
                    self,
                    "Replace action?",
                    f"Replace {target.name}?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                == QMessageBox.StandardButton.Yes
            )
            if not overwrite:
                return
        self.model.run(lambda s: s.export_action(target, overwrite=overwrite))

    def import_action(self) -> None:
        """Load bounded JSON through the shared action mapper, reporting incompatible owners."""
        path, _ = choose_open_file(
            self, "Reuse animation action", "", "Rigora actions (*.rigaction)"
        )
        if path:
            self.model.run(lambda s: s.import_action(Path(path)))
