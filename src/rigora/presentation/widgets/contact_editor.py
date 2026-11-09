"""Editable foot-contact intervals and grounded anchors over the canonical IK service."""

from threading import Event
from typing import TYPE_CHECKING

from PySide6.QtCore import QSignalBlocker, QThreadPool
from PySide6.QtGui import QHideEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from rigora.application_services.contact_editing import ContactEditingService
from rigora.application_services.documents import DocumentService
from rigora.domain.geometry import transform_point
from rigora.domain.project import Project, ProjectError
from rigora.presentation.viewmodels.content_library import LibraryJob
from rigora.presentation.widgets.clip_editor import numeric
from rigora.presentation.widgets.window_frame import CustomDialog

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


class ContactEditor(CustomDialog):
    """Author grounded intervals, editable targets and separate baked FK actions."""

    def __init__(self, window: "MainWindow") -> None:
        """Capture the active scene/context and list only bones editable in its current view."""
        super().__init__(window, "Foot contacts")
        self.host, self.document = window, window.viewmodel.documents
        self.scene_id, self.context = self.document.scene.id, self.document.animation_context
        self.clip_id = self.document.selected_clip_id
        self.bake_job: LibraryJob | None = None
        self.cancel_bake = Event()
        self.resize(520, 600)
        box = QVBoxLayout(self.content)
        form = QFormLayout()
        box.addLayout(form)
        self.contacts, self.upper, self.lower_bone, self.foot, self.space, self.bend = (
            QComboBox() for _ in range(6)
        )
        self.contacts.addItem("New contact", "")
        for rule in self.document.scene.constraints:
            if rule.kind == "foot_contact" and (
                self.document.animation_scope is None
                or rule.owner_id in self.document.animation_scope
            ):
                self.contacts.addItem(rule.name, rule.id)
        self.upper.addItem("Choose upper leg segment", "")
        self.bones = {
            b.id: b
            for rig in self.document.scene.skeletons
            for b in rig.bones
            if self.document.animation_scope is None or b.id in self.document.animation_scope
        }
        for bone in self.bones.values():
            self.upper.addItem(bone.name, bone.id)
        for name, value in (
            ("Object · follows placement", "object"),
            ("World · fixed ground", "world"),
        ):
            self.space.addItem(name, value)
        for name, bend_value in (("Bend positive", 1), ("Bend negative", -1)):
            self.bend.addItem(name, bend_value)
        self.start = numeric(self, "Contact start", minimum=0, maximum=1e7)
        self.end = numeric(self, "Contact release", minimum=0, maximum=1e7)
        self.fade = numeric(self, "Contact fade", minimum=0, maximum=5000)
        self.anchor_x = numeric(self, "Anchor X", minimum=-1e9, maximum=1e9)
        self.anchor_y = numeric(self, "Anchor Y", minimum=-1e9, maximum=1e9)
        self.angle = numeric(self, "Foot ground angle", minimum=-360, maximum=360)
        self.start.setValue(self.document.cursor_frame)
        self.end.setValue(self.start.value() + self.document.scene.settings.fps / 2)
        self.compensate = QCheckBox("Compensate upper-joint position outside leg reach")
        self.compensate.setChecked(True)
        for label, field in (
            ("Contact", self.contacts),
            ("Upper segment", self.upper),
            ("Lower segment", self.lower_bone),
            ("Foot · optional", self.foot),
            ("Anchor space", self.space),
            ("Start", self.start),
            ("Release", self.end),
            ("Fade frames", self.fade),
            ("Anchor X", self.anchor_x),
            ("Anchor Y", self.anchor_y),
            ("Ground angle", self.angle),
            ("Knee bend", self.bend),
        ):
            form.addRow(label, field)
        box.addWidget(self.compensate)
        help_text = QLabel(
            "Choose connected thigh/shin segments. Weight keys appear in the timeline. "
            "Object anchors follow the placed character; World anchors stay on the ground. "
            "Release ends the contact. Fade blends the pose in and out."
        )
        help_text.setWordWrap(True)
        box.addWidget(help_text)
        self.note = QLabel()
        self.note.setWordWrap(True)
        box.addWidget(self.note)
        row = QHBoxLayout()
        box.addLayout(row)
        for label, callback in (
            ("Apply contact", self.apply),
            ("Remove", self.remove),
            ("Bake FK action", self.bake),
            ("Close", self.close),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            row.addWidget(button)
            if label == "Bake FK action":
                self.bake_button = button
        self.upper.currentIndexChanged.connect(self.choose_upper)
        self.lower_bone.currentIndexChanged.connect(self.choose_lower)
        self.contacts.currentIndexChanged.connect(self.load)
        self.choose_upper()

    def validate(self) -> None:
        """Reject another document, scene, private action or editable Object context."""
        if (
            self.host.viewmodel.documents is not self.document
            or self.document.scene.id != self.scene_id
            or self.document.animation_context != self.context
            or self.document.selected_clip_id != self.clip_id
        ):
            raise ProjectError("Reopen Foot contacts in the active scene/action before editing.")

    def choose_upper(self) -> None:
        """Offer connected direct children instead of guessing from anatomical names."""
        self.lower_bone.clear()
        for bone in self.bones.values():
            if bone.parent_id == self.upper.currentData():
                self.lower_bone.addItem(bone.name, bone.id)
        self.choose_lower()

    def choose_lower(self) -> None:
        """Default the ground anchor to the evaluated ankle and expose an optional child foot."""
        self.foot.clear()
        self.foot.addItem("Keep authored foot orientation", "")
        key = self.lower_bone.currentData()
        for bone in self.bones.values():
            if bone.parent_id == key:
                self.foot.addItem(bone.name, bone.id)
        if key in self.bones and key in self.document.animation.pose.nodes:
            node = self.document.animation.pose.nodes[key]
            x, y = transform_point(node.world_matrix, node.length, 0)
            self.anchor_x.setValue(x)
            self.anchor_y.setValue(y)

    def load(self) -> None:
        """Restore an existing interval by stable rule/target identity."""
        rule = next(
            (r for r in self.document.scene.constraints if r.id == self.contacts.currentData()),
            None,
        )
        if rule is None:
            return
        self.upper.setCurrentIndex(self.upper.findData(rule.owner_id))
        self.lower_bone.setCurrentIndex(self.lower_bone.findData(rule.parameters["end_bone_id"]))
        with QSignalBlocker(self.foot):
            self.foot.setCurrentIndex(
                max(0, self.foot.findData(rule.parameters.get("foot_bone_id", "")))
            )
        self.space.setCurrentIndex(
            self.space.findData(rule.parameters.get("anchor_space", "object"))
        )
        self.bend.setCurrentIndex(self.bend.findData(rule.parameters.get("bend", 1)))
        self.start.setValue(rule.extra["contact_start"])
        self.end.setValue(rule.extra["contact_end"])
        self.fade.setValue(rule.extra.get("contact_blend", 0))
        self.angle.setValue(rule.parameters.get("angle", 0))
        self.compensate.setChecked(rule.parameters.get("compensate", True))
        node = self.document.animation.pose.nodes.get(rule.target_id or "")
        if node:
            self.anchor_x.setValue(node.world_matrix[4])
            self.anchor_y.setValue(node.world_matrix[5])

    def apply(self) -> None:
        """Commit the interval through the existing scene ViewModel/history route."""

        def edit(_: object) -> None:
            self.validate()
            key = ContactEditingService(self.document).interval(
                self.upper.currentData(),
                self.lower_bone.currentData(),
                self.start.value(),
                self.end.value(),
                x=self.anchor_x.value(),
                y=self.anchor_y.value(),
                blend=self.fade.value(),
                foot=self.foot.currentData(),
                angle=self.angle.value(),
                space=self.space.currentData(),
                bend=self.bend.currentData(),
                compensate=self.compensate.isChecked(),
                identity=self.contacts.currentData(),
            )
            with QSignalBlocker(self.contacts):
                if self.contacts.findData(key) < 0:
                    self.contacts.addItem("Foot contact", key)
                self.contacts.setCurrentIndex(self.contacts.findData(key))

        self.host.viewmodel.scene.run(edit)
        self.clip_id = self.document.selected_clip_id
        self.note.setText(
            self.host.viewmodel.scene.error
            or "Contact saved · edit its weight keys in the timeline."
        )

    def remove(self) -> None:
        """Remove only the selected contact, its owned target and dependent tracks."""

        def edit(_: object) -> None:
            self.validate()
            ContactEditingService(self.document).remove_contact(self.contacts.currentData())

        self.host.viewmodel.scene.run(edit)
        self.note.setText(self.host.viewmodel.scene.error or "Contact removed.")
        if not self.host.viewmodel.scene.error:
            self.contacts.removeItem(self.contacts.currentIndex())

    def bake(self) -> None:
        """Sample an isolated revision on a worker; source state stays responsive and editable."""
        if self.bake_job:
            return
        try:
            self.validate()
            snapshot, baseline = self.document.fork(), self.document.project
            start, end = self.start.value(), self.end.value()
            self.cancel_bake.clear()
            cancelled = self.cancel_bake.is_set
            self.bake_job = LibraryJob(
                lambda: (
                    ContactEditingService(snapshot).bake_contacts(start, end, cancelled=cancelled),
                    snapshot,
                    baseline,
                )
            )
            self.bake_job.signals.done.connect(self.finish_bake)
            self.bake_job.signals.failed.connect(self.fail_bake)
            self.bake_button.setEnabled(False)
            self.note.setText("Baking foot contacts in the background…")
            QThreadPool.globalInstance().start(self.bake_job)
        except ProjectError as error:
            self.note.setText(str(error))

    def finish_bake(self, result: tuple[str, DocumentService, Project]) -> None:
        """Adopt only the completed action from an unchanged document/context as one Undo step."""
        self.bake_job = None
        self.bake_button.setEnabled(True)
        if self.cancel_bake.is_set():
            return
        clip, snapshot, baseline = result

        def edit(_: object) -> None:
            self.validate()
            if self.document.project is not baseline:
                raise ProjectError(
                    "Project changed during baking; bake again to retain both edits."
                )
            frame = self.document.cursor_frame
            ContactEditingService(self.document).commit(
                "Bake foot contacts", timelines=snapshot.scene.timelines, clips=snapshot.scene.clips
            )
            self.document.select_animation_clip(clip)
            self.document.animation.seek(frame)

        self.host.viewmodel.scene.run(edit)
        self.clip_id = self.document.selected_clip_id
        self.note.setText(
            self.host.viewmodel.scene.error
            or "Baked FK action created; original contacts retained."
        )

    def fail_bake(self, message: str) -> None:
        """Surface worker failures without publishing partial sampled tracks."""
        self.bake_job = None
        self.bake_button.setEnabled(True)
        if not self.cancel_bake.is_set():
            self.note.setText(message)

    def hideEvent(self, event: QHideEvent) -> None:
        """Cancel sampling and discard late results when this authoring window closes."""
        self.cancel_bake.set()
        super().hideEvent(event)
