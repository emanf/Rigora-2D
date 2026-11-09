"""Main-scene access to object-authored actions and appearance choices."""

import json
from typing import TYPE_CHECKING

from PySide6.QtCore import QMimeData, QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from rigora.application_services.characters import CharacterService
from rigora.domain.entities import Camera, Group, SceneObject
from rigora.domain.project import ProjectError
from rigora.presentation.viewmodels.scene_attachments import AttachmentViewModel
from rigora.presentation.widgets.appearance_choices import AppearanceChoices
from rigora.presentation.widgets.clip_editor import numeric
from rigora.presentation.widgets.window_frame import CustomDialog

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


class ObjectSceneControls(QGroupBox):
    """Show only whole-object actions in Scene; internals remain in Object Editor."""

    def __init__(self, host: "MainWindow") -> None:
        """Bind saved options to the selected object and reuse ordinary timeline commands."""
        super().__init__("Object")
        self.host = host
        self.owner_key: object = None
        self.owner_id = ""
        box = QVBoxLayout(self)
        self.animation = QComboBox()
        self.animation.setAccessibleName("Object animation to place")
        box.addWidget(self.animation)
        from rigora.domain.character_recipe import VIEWS

        self.views = QComboBox()
        self.views.addItems(VIEWS)
        self.views.setAccessibleName("Object Views")
        self.views.currentTextChanged.connect(self.change_view)
        box.addWidget(QLabel("Object Views"))
        box.addWidget(self.views)
        row = QHBoxLayout()
        box.addLayout(row)
        self.place = QPushButton("Add animation…")
        self.place.clicked.connect(lambda: self.choose_motion(self.owner()))
        row.addWidget(self.place)
        edit = QPushButton("Edit object")
        edit.clicked.connect(lambda: host.object_edit.enter(self.owner()) if self.owner() else None)
        row.addWidget(edit)
        self.attachment_model = AttachmentViewModel(host.viewmodel, self)
        self.attachment_card = QGroupBox("Scene attachment")
        attachment_box = QVBoxLayout(self.attachment_card)
        self.attachment_label = QLabel("Independent")
        self.attachment_label.setTextFormat(Qt.TextFormat.PlainText)
        self.attachment_label.setWordWrap(True)
        attachment_box.addWidget(self.attachment_label)
        attachment_row = QHBoxLayout()
        self.attach_edit = QPushButton("Edit…")
        self.attach_edit.setIcon(host.icons.icon("link"))
        self.attach_edit.clicked.connect(host.attach_selection)
        self.attach_key = QPushButton("Key here…")
        self.attach_key.setIcon(host.icons.icon("add_link"))
        self.attach_key.setToolTip("Choose a pickup, transfer or release at the playhead.")
        self.attach_key.clicked.connect(self.key_attachment)
        attachment_row.addWidget(self.attach_edit)
        attachment_row.addWidget(self.attach_key)
        attachment_box.addLayout(attachment_row)
        box.addWidget(self.attachment_card)
        self.skins = AppearanceChoices(host, "skins", self.owner)
        self.outfits = AppearanceChoices(host, "outfits", self.owner)
        box.addWidget(self.skins)
        box.addWidget(self.outfits)
        self.note = QLabel("Drag an Object from Scene onto the timeline to place an animation.")
        self.note.setWordWrap(True)
        self.note.setObjectName("Muted")
        box.addWidget(self.note)
        host.viewmodel.changed.connect(self.refresh)
        host.viewmodel.scene.changed.connect(self.refresh)
        host.viewmodel.content.changed.connect(self.refresh)
        host.viewmodel.playback.changed.connect(self.refresh_playback_attachment)

    def refresh_playback_attachment(self) -> None:
        """Avoid hidden Inspector work on the playback hot path."""
        if self.isVisible():
            self.refresh_attachment()

    def key_attachment(self) -> None:
        """Open the guided card in explicit key mode at the current Scene playhead."""
        if owner := self.owner():
            self.host.timeline.open_action(
                {
                    "owner": owner,
                    "kind": "attachment",
                    "frame": self.host.viewmodel.documents.animation.pose.frame,
                }
            )

    def refresh_attachment(self) -> None:
        """Keep the selected Object's following state readable during seeking and playback."""
        owner = self.owner()
        doc = self.host.viewmodel.documents
        if not owner or doc.animation_context:
            self.attachment_card.hide()
            return
        record = self.attachment_model.service.record(owner)
        visible = isinstance(record, (Group, SceneObject)) and not isinstance(record, Camera)
        self.attachment_card.setVisible(visible)
        if visible:
            state = self.attachment_model.state(owner)
            self.attachment_label.setText(self.attachment_model.service.target_label(state))
            editable = not self.attachment_model.service.locked(owner)
            self.attach_edit.setEnabled(editable)
            self.attach_key.setEnabled(editable)

    def change_view(self, view: str) -> None:
        """Use the same background turnaround command as Object Editor."""
        from rigora.presentation.object_views import change_view

        change_view(self.host, self.owner(), view)
        self.views.setEnabled(False)

    def owner(self) -> str:
        """Resolve selection to its whole object, including older character containers."""
        vm = self.host.viewmodel
        signature = id(vm.documents.project), vm.scene.selected
        if signature == self.owner_key:
            return self.owner_id
        self.owner_key = signature
        self.owner_id = ""
        if not vm.documents.project or not vm.scene.selected:
            return ""
        service = CharacterService(vm.documents)
        key = vm.scene.selected[0]
        if root := service.object_root(key):
            self.owner_id = root.id
            return self.owner_id
        actor = next(
            (c for c in service.scene.characters if key == c.id or key in c.object_ids), None
        )
        self.owner_id = actor.id if actor else key if key in service.scene_objects() else ""
        return self.owner_id

    def refresh(self) -> None:
        """Retain selected actions while rebuilding lists after actual document edits."""
        owner = self.owner()
        mode = getattr(self.host, "object_edit", None)
        self.setVisible(bool(owner) and not (mode and mode.active))
        self.setEnabled(bool(owner))
        if not owner:
            return
        service = CharacterService(self.host.viewmodel.documents)
        from rigora.application_services.object_views import ObjectViewsService

        with QSignalBlocker(self.views):
            try:
                views = ObjectViewsService(service.document)
                from rigora.domain.object_views import VIEW_SLOTS

                choices = VIEW_SLOTS
                if tuple(self.views.itemText(i) for i in range(self.views.count())) != choices:
                    self.views.clear()
                    self.views.addItems(choices)
                if not self.host.viewmodel.content.busy:
                    self.views.setCurrentText(views.edited_view(owner))
                self.views.setEnabled(len(choices) > 1 and not self.host.viewmodel.content.busy)
            except ProjectError:
                self.views.setEnabled(False)
        self.setTitle(service.record(owner).name)
        selected = self.animation.currentData()
        with QSignalBlocker(self.animation):
            self.animation.clear()
            for clip in service.motions(owner):
                self.animation.addItem(clip.name, clip.id)
            self.animation.setCurrentIndex(max(0, self.animation.findData(selected)))
        self.place.setEnabled(self.animation.count() > 0)
        self.refresh_attachment()
        self.skins.refresh()
        self.outfits.refresh()

    def drop_object(self, mime: QMimeData, frame: float) -> None:
        """Validate same-document object identities before showing an animation picker."""
        document = self.host.viewmodel.documents
        try:
            if self.host.object_edit.active:
                raise ProjectError("Place object animations in Main Scene.")
            session = bytes(mime.data("application/x-rigora-session").data())
            raw = bytes(mime.data("application/x-rigora-scene").data())
            if session.decode() != document.session_id or not 0 < len(raw) <= 65536:
                raise ProjectError("Drag an Object from the active project's Scene list.")
            keys = json.loads(raw)
            service = CharacterService(document)
            if (
                not isinstance(keys, list)
                or not keys
                or any(not isinstance(k, str) or k not in service.scene_objects() for k in keys)
            ):
                raise ProjectError("Choose whole Objects from the Scene list.")
            for key in dict.fromkeys(keys):
                self.choose_motion(key, frame)
        except (ProjectError, ValueError, UnicodeError) as error:
            self.host.statusBar().showMessage(str(error), 6000)

    def choose_motion(self, owner: str, frame: float | None = None) -> None:
        """Place a source action with duration, repeat and speed chosen before committing."""
        document = self.host.viewmodel.documents
        if not owner or not document.project:
            return
        service = CharacterService(document)
        clips = service.motions(owner)
        if not clips:
            self.host.statusBar().showMessage(
                "Open Object Editor and create an animation first.", 6000
            )
            return
        self.host.viewmodel.playback.pause()
        dialog = CustomDialog(self.host, f"Add animation · {service.record(owner).name}")
        dialog.setObjectName("ObjectAnimationPicker")
        box = QVBoxLayout(dialog.content)
        form = QFormLayout()
        box.addLayout(form)
        choice = QComboBox()
        choice.setAccessibleName("Animation to place")
        for clip in clips:
            choice.addItem(clip.name, clip.id)
        choice.setCurrentIndex(max(0, choice.findData(self.animation.currentData())))
        start = numeric(dialog, "Start frame", minimum=0, maximum=1e7)
        start.setValue(document.animation.pose.frame if frame is None else frame)
        speed = numeric(dialog, "Animation speed", minimum=0.01, maximum=100)
        speed.setValue(1)
        duration = numeric(dialog, "Duration seconds", minimum=0.01, maximum=3600)

        def source_length() -> None:
            """Offer one complete cycle at the requested source speed."""
            source = clips[choice.currentIndex()]
            duration.setValue(
                (source.out_frame - source.in_frame) / service.scene.settings.fps / speed.value()
            )

        choice.currentIndexChanged.connect(source_length)
        speed.valueChanged.connect(source_length)
        source_length()
        repeat = QCheckBox("Repeat animation")
        repeat.setChecked(True)
        for label, widget in (
            ("Animation", choice),
            ("Start frame", start),
            ("Duration · seconds", duration),
            ("Speed ×", speed),
        ):
            form.addRow(label, widget)
        form.addRow(repeat)
        box.addWidget(
            QLabel("Trim the Animation span or right-click its running icon to change speed.")
        )
        row = QHBoxLayout()
        box.addLayout(row)
        cancel, add = QPushButton("Cancel"), QPushButton("Add animation")
        cancel.clicked.connect(dialog.reject)
        add.clicked.connect(dialog.accept)
        row.addWidget(cancel)
        row.addWidget(add)
        if not dialog.exec():
            return
        try:
            segment = service.place_motion(
                owner,
                choice.currentData(),
                start.value(),
                duration.value(),
                speed.value(),
                repeat.isChecked(),
            )
            self.host.viewmodel.changed.emit()
            blocks = self.host.timeline.motion_blocks
            blocks.selected = segment
            blocks.refresh()
            self.host.timeline.pages.setCurrentIndex(0)
        except ProjectError as error:
            self.host.statusBar().showMessage(str(error), 6000)
