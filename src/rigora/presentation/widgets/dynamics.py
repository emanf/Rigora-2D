"""Follow-through configuration, live loop previews and editable cartoon motion commands."""

import time
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from rigora.application_services.documents import DocumentService
from rigora.application_services.dynamics import BOUNCES, DynamicsService
from rigora.domain.project import ProjectError
from rigora.presentation.viewmodels.content_library import LibraryJob
from rigora.presentation.widgets.window_frame import CustomDialog

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


class DynamicsDialog(CustomDialog):
    """Configure child springs, preview motion and bake without changing the source clip."""

    def __init__(self, window: "MainWindow") -> None:
        """Collect explicit target controls and expose bounded physical parameters."""
        super().__init__(window, "Secondary motion & cartoon physics")
        self.host, self.document = window, window.viewmodel.documents
        self.resize(720, 760)
        box = QVBoxLayout(self.content)
        info = QLabel(
            "Child bones follow through while roots remain anchored. Preview loops on "
            "a scratch document. Bake creates a new clip with editable FK keys. "
            "Select multiple child bones to configure them together."
        )
        info.setWordWrap(True)
        box.addWidget(info)
        self.bones = QListWidget()
        self.bones.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.bones.setAccessibleName("Spring child bones")
        self.bones.setMaximumHeight(145)
        self.owner = QComboBox()
        if self.document.project:
            scene = self.document.scene
            for rig in scene.skeletons:
                for bone in rig.bones:
                    self.owner.addItem(bone.name, bone.id)
                    if bone.parent_id:
                        item = QListWidgetItem(bone.name)
                        item.setData(Qt.ItemDataRole.UserRole, bone.id)
                        self.bones.addItem(item)
                        item.setSelected(bone.id in window.viewmodel.rig.selected)
            for obj in (*scene.objects, *scene.groups):
                self.owner.addItem(obj.name, obj.id)
        box.addWidget(self.bones)
        self.fields: dict[str, QDoubleSpinBox] = {}
        form = QFormLayout()
        for key, label, low, high, initial in (
            ("frequency", "Frequency · Hz", 0.5, 12, 3),
            ("damping", "Damping ratio", 0.05, 3, 0.5),
            ("inertia", "Inertia", 0, 3, 0.6),
            ("gravity", "Gravity · px/s²", -10000, 10000, 0),
            ("strength", "Follow-through strength", 0, 1, 1),
            ("max_angle", "Maximum deflection °", 0, 170, 65),
            ("height", "Bounce height · px", 0, 100000, 100),
            ("duration", "Motion duration · frames", 1, 1000, 48),
            ("squash", "Squash (+) / stretch (−)", -0.8, 0.8, 0.25),
        ):
            field = QDoubleSpinBox()
            field.setRange(low, high)
            field.setDecimals(3)
            field.setValue(initial)
            field.setKeyboardTracking(False)
            field.setAccessibleName(label)
            self.fields[key] = field
            form.addRow(label, field)
        self.preset = QComboBox()
        self.preset.addItems(list(BOUNCES))
        form.addRow("Bounce / squash control", self.owner)
        form.addRow("Bounce preset", self.preset)
        box.addLayout(form)
        self.status = QLabel()
        self.status.setWordWrap(True)
        box.addWidget(self.status)
        for entries in (
            (
                ("Save springs", "save", self.save),
                ("Loop preview", "play_arrow", self.preview),
                ("Stop preview", "stop", self.stop),
            ),
            (
                ("Create bounce clip", "sports_basketball", self.bounce),
                ("Key squash / stretch", "aspect_ratio", self.squash),
                ("Bake dynamics", "key", self.bake),
            ),
        ):
            row = QHBoxLayout()
            for title, icon, callback in entries:
                button = QPushButton(window.icons.icon(icon), title)
                button.setProperty("materialIcon", icon)
                button.clicked.connect(callback)
                row.addWidget(button)
            box.addLayout(row)
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self.tick)
        self.scratch: DocumentService | None = None
        self.bake_job: LibraryJob | None = None
        self.cancelled = False
        self.clock = 0.0
        self.revision = self.document.project
        self.bones.currentItemChanged.connect(self.load_settings)
        self.finished.connect(self.finish)

    def finish(self) -> None:
        """Cancel publication of an unfinished background bake when the dialog closes."""
        self.cancelled = True
        self.stop()

    def check(self) -> None:
        """Reject commands from an editor whose project tab has changed."""
        if self.document is not self.host.viewmodel.documents or self.document.project is None:
            raise ProjectError("Return to the original project or reopen Secondary motion.")

    def configure(self, service: DynamicsService) -> None:
        """Collect normalized physical values for one atomic canonical configuration command."""
        self.check()
        keys = tuple(item.data(Qt.ItemDataRole.UserRole) for item in self.bones.selectedItems())
        service.configure(
            keys,
            frequency=self.fields["frequency"].value(),
            damping=self.fields["damping"].value(),
            inertia=self.fields["inertia"].value(),
            gravity=self.fields["gravity"].value(),
            strength=self.fields["strength"].value(),
            max_angle=self.fields["max_angle"].value(),
        )

    def load_settings(self) -> None:
        """Read existing spring parameters from the current bone without changing its rig."""
        item = self.bones.currentItem()
        if item and self.document.project:
            rule = next(
                (
                    c
                    for c in self.document.scene.constraints
                    if c.kind == "spring" and c.owner_id == item.data(Qt.ItemDataRole.UserRole)
                ),
                None,
            )
            if rule:
                for key in ("frequency", "damping", "inertia", "gravity", "strength", "max_angle"):
                    self.fields[key].setValue(
                        float(rule.parameters.get(key, self.fields[key].value()))
                    )

    def save(self) -> None:
        """Save validated follow-through settings as one undoable rig command."""
        self.stop()
        editor = self.host.viewmodel.animation_editor
        editor.run(lambda _: self.configure(DynamicsService(self.document)))
        self.status.setText(
            editor.error or "Spring settings saved. Use the timeline to preview motion."
        )

    def preview(self) -> None:
        """Loop configured springs on a scratch document while preserving real history."""
        try:
            self.stop()
            self.check()
            self.host.viewmodel.playback.pause()
            self.scratch = self.document.fork()
            if self.bones.selectedItems():
                self.configure(DynamicsService(self.scratch))
            self.revision = self.document.project
            self.clock = time.monotonic()
            self.timer.start()
            self.tick()
            self.status.setText("Loop preview · settings are not saved until Save springs.")
        except (ProjectError, ValueError) as error:
            self.status.setText(str(error))

    def tick(self) -> None:
        """Evaluate the canonical spring solver at elapsed time and stop on stale revisions."""
        if (
            not self.scratch
            or self.document.project is not self.revision
            or self.document is not self.host.viewmodel.documents
        ):
            self.stop()
            return
        span = self.scratch.animation.playback.range
        frame = span.start + ((time.monotonic() - self.clock) * span.fps) % max(
            1, span.end - span.start
        )
        editor = self.host.viewmodel.animation_editor
        editor.preview_pose = self.scratch.animation.evaluate(frame)
        editor.key_preview_changed.emit()

    def stop(self) -> None:
        """Release scratch simulation and restore the real scene without moving its playhead."""
        self.timer.stop()
        self.scratch = None
        self.host.viewmodel.animation_editor.clear_key_preview()

    def bounce(self) -> None:
        """Publish the chosen decaying bounce preset as a new editable clip."""
        self.stop()
        editor = self.host.viewmodel.animation_editor

        def operation(_: object) -> None:
            """Use the current frame and selected control after checking tab ownership."""
            self.check()
            DynamicsService(self.document).bounce(
                str(self.owner.currentData()),
                preset=self.preset.currentText(),
                start=self.document.animation.pose.frame,
                duration=self.fields["duration"].value(),
                height=self.fields["height"].value(),
            )

        editor.run(operation)
        self.status.setText(editor.error or "Bounce clip created; edit its keys in the dope sheet.")

    def squash(self) -> None:
        """Add an area-preserving squash/recovery to the current clip and control."""
        self.stop()
        editor = self.host.viewmodel.animation_editor

        def operation(_: object) -> None:
            """Key scale channels through the shared service at the visible frame."""
            self.check()
            DynamicsService(self.document).squash(
                str(self.owner.currentData()),
                self.document.animation.pose.frame,
                self.fields["squash"].value(),
                self.fields["duration"].value(),
            )

        editor.run(operation)
        self.status.setText(editor.error or "Squash / stretch keyed with area-preserving scales.")

    def bake(self) -> None:
        """Bake a bounded source clip into a separate editable FK clip."""
        self.stop()
        if self.bake_job:
            return
        try:
            self.check()
            scratch, baseline = self.document.fork(), self.document.project
            job = LibraryJob(lambda: (DynamicsService(scratch).bake(), scratch, baseline))
            self.bake_job = job
            job.signals.done.connect(self.finish_bake)
            job.signals.failed.connect(self.fail_bake)
            QThreadPool.globalInstance().start(job)
            self.status.setText("Baking deterministic dynamics in the background…")
        except ProjectError as error:
            self.status.setText(str(error))

    def finish_bake(self, result: tuple[str, DocumentService, object]) -> None:
        """Adopt a completed bake only when its captured source document is unchanged."""
        self.bake_job = None
        if self.cancelled:
            return
        clip, scratch, baseline = result
        editor = self.host.viewmodel.animation_editor

        def operation(_: object) -> None:
            """Publish the worker's immutable animation records through one command."""
            self.check()
            if self.document.project is not baseline or scratch.project is None:
                raise ProjectError(
                    "Project changed during baking; bake again to retain both edits."
                )
            frame = self.document.animation.pose.frame
            scene = scratch.scene
            DynamicsService(self.document).commit(
                "Bake spring dynamics", timelines=scene.timelines, clips=scene.clips
            )
            self.document.select_animation_clip(clip)
            self.document.animation.seek(frame)

        editor.run(operation)
        self.status.setText(
            editor.error or "Baked clip created. Source clip and spring configuration preserved."
        )

    def fail_bake(self, message: str) -> None:
        """Surface worker validation failures without mutating project state."""
        self.bake_job = None
        if not self.cancelled:
            self.status.setText(message)
