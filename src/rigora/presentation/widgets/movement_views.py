"""Compact authoring of deterministic movement-to-view mappings for existing Object views."""

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QLabel, QPushButton, QVBoxLayout

from rigora.application_services.game_authoring import GameAuthoringService
from rigora.domain.object_views import view_partitions
from rigora.domain.project import ProjectError
from rigora.engine.view_switching import DIRECTIONS
from rigora.presentation.widgets.clip_editor import numeric
from rigora.presentation.widgets.window_frame import CustomDialog

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


class MovementViews(CustomDialog):
    """Map world-space motion to authored slots while retaining explicit timeline overrides."""

    def __init__(self, host: "MainWindow") -> None:
        """Capture one workspace without modifying any views until Apply is pressed."""
        super().__init__(host, "Movement-driven views")
        self.host, self.document = host, host.viewmodel.documents
        self.scene_id = self.document.scene.id
        self.resize(460, 440)
        box = QVBoxLayout(self.content)
        form = QFormLayout()
        box.addLayout(form)
        self.target, self.driver = QComboBox(), QComboBox()
        for group in self.document.scene.groups:
            if group.extra.get("view_slots"):
                self.target.addItem(group.name, group.id)
        for node in self.document.animation.pose.nodes.values():
            self.driver.addItem(node.name, node.id)
        self.enabled = QCheckBox("Switch automatically from movement")
        self.speed = numeric(self, "Minimum movement speed", minimum=0, maximum=1e6)
        self.speed.setValue(8)
        self.speed.setSuffix(" px/s")
        form.addRow("Object", self.target)
        form.addRow(self.enabled)
        form.addRow("Movement driver", self.driver)
        form.addRow("Idle below", self.speed)
        self.slots = {key: QComboBox() for key in DIRECTIONS}
        for key, field in self.slots.items():
            field.setAccessibleName(key.title() + " movement view")
            form.addRow(key.title(), field)
        self.note = QLabel(
            "Author views in Object Editor first. World movement chooses the dominant "
            "direction; stopped objects use Idle. Explicit View keys override this behavior. "
            "Object Editor keeps the view you select manually."
        )
        self.note.setWordWrap(True)
        box.addWidget(self.note)
        apply = QPushButton("Apply")
        apply.clicked.connect(self.apply)
        box.addWidget(apply)
        self.target.currentIndexChanged.connect(self.load)
        self.load()

    def load(self) -> None:
        """Expose nonempty authored slots and restore the selected Object's saved mapping."""
        root = next(
            (g for g in self.document.scene.groups if g.id == self.target.currentData()), None
        )
        for field in self.slots.values():
            field.clear()
        if root is None:
            return
        views = [
            name for name, members in view_partitions(self.document.scene, root).items() if members
        ]
        data = root.extra.get("movement_views", {})
        self.enabled.setChecked(bool(data))
        self.speed.setValue(data.get("minimum_speed", 8))
        driver = data.get("driver", root.id)
        index = self.driver.findData(driver)
        if index < 0:
            self.driver.addItem("Missing driver · choose a replacement", driver)
            index = self.driver.count() - 1
        self.driver.setCurrentIndex(index)
        for key, field in self.slots.items():
            field.addItems(views)
            field.setCurrentText(data.get("slots", {}).get(key, views[0] if views else ""))

    def apply(self) -> None:
        """Save one undoable configuration against the original scene workspace."""

        def edit(_service: object) -> None:
            if (
                self.host.viewmodel.documents is not self.document
                or self.document.scene.id != self.scene_id
            ):
                raise ProjectError("Return to the original scene or reopen Movement-driven views.")
            GameAuthoringService(self.document).movement_views(
                str(self.target.currentData()),
                {
                    "driver": self.driver.currentData(),
                    "minimum_speed": self.speed.value(),
                    "slots": {k: f.currentText() for k, f in self.slots.items()},
                }
                if self.enabled.isChecked()
                else None,
            )

        self.host.viewmodel.scene.run(edit)
        self.note.setText(
            self.host.viewmodel.scene.error or "Movement-driven views saved · Undo available."
        )
