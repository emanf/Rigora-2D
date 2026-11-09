"""Gameplay region and deterministic particle authoring using ordinary scene objects/channels."""

import json
from typing import TYPE_CHECKING

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from rigora.application_services.game_authoring import GameAuthoringService
from rigora.domain.project import ProjectError
from rigora.domain.validation import json_copy
from rigora.presentation.widgets.clip_editor import numeric
from rigora.presentation.widgets.window_frame import CustomDialog

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


class GameTools(CustomDialog):
    """Author non-rendered collision regions or actual deterministic rendered particle emitters."""

    def __init__(self, host: "MainWindow") -> None:
        """Capture the active workspace and preserve field edits until explicit Apply."""
        super().__init__(host, "Game regions & particles")
        self.host, self.document = host, host.viewmodel.documents
        self.scene_id, self.context = self.document.scene.id, self.document.animation_context
        self.resize(650, 710)
        box = QVBoxLayout(self.content)
        common = QFormLayout()
        box.addLayout(common)
        self.items, self.parent_object = QComboBox(), QComboBox()
        self.parent_object.addItem("Scene", None)
        for obj in (*self.document.scene.groups, *self.document.scene.objects):
            self.parent_object.addItem(obj.name, obj.id)
        self.item_name = QLineEdit("Hitbox")
        self.pos_x = numeric(self, "Region/emitter X")
        self.pos_y = numeric(self, "Region/emitter Y")
        for label, field in (
            ("Saved item", self.items),
            ("Name", self.item_name),
            ("Parent for new item", self.parent_object),
            ("X", self.pos_x),
            ("Y", self.pos_y),
        ):
            common.addRow(label, field)
        self.tabs = QTabWidget()
        box.addWidget(self.tabs, 1)
        region, emitter, physics = QWidget(), QWidget(), QWidget()
        self.tabs.addTab(region, "Hitboxes / Hurtboxes")
        self.tabs.addTab(emitter, "Particles")
        self.tabs.addTab(physics, "Particle physics")
        rform = QFormLayout(region)
        self.region_type, self.region_shape = QComboBox(), QComboBox()
        self.region_type.addItems(("hitbox", "hurtbox"))
        self.region_shape.addItems(("rectangle", "ellipse"))
        self.region_width = numeric(self, "Region width", minimum=0.01, maximum=1e6)
        self.region_height = numeric(self, "Region height", minimum=0.01, maximum=1e6)
        self.region_width.setValue(100)
        self.region_height.setValue(100)
        self.region_group = QLineEdit()
        self.region_payload = QPlainTextEdit("{}")
        self.region_payload.setMaximumHeight(100)
        self.region_payload.setAccessibleName("Region payload as a JSON object")
        for label, region_field in (
            ("Type", self.region_type),
            ("Shape", self.region_shape),
            ("Width", self.region_width),
            ("Height", self.region_height),
            ("Collision group", self.region_group),
            ("Payload · JSON", self.region_payload),
        ):
            rform.addRow(label, region_field)
        ebox = QHBoxLayout(emitter)
        left, right = QFormLayout(), QFormLayout()
        ebox.addLayout(left)
        ebox.addLayout(right)
        self.parameters = {}
        defaults = dict(
            start=0,
            end=240,
            rate=20,
            lifetime=1,
            speed=80,
            spread=35,
            angle=-90,
            gravity=100,
            size=5,
            seed=0,
            burst=0,
        )
        for index, (name, value) in enumerate(defaults.items()):
            field = numeric(self, "Particle " + name, minimum=-1e7, maximum=1e7)
            field.setValue(value)
            self.parameters[name] = field
            (left if index < 6 else right).addRow(name.replace("_", " ").title(), field)
        self.world_space = QCheckBox("World space · leave emitted particles behind")
        self.world_space.setChecked(True)
        self.color = QLineEdit("#ffffff")
        self.primitive = QComboBox()
        self.primitive.addItems(("circle", "square"))
        right.addRow("Color #RRGGBB", self.color)
        right.addRow("Primitive", self.primitive)
        right.addRow(self.world_space)
        pform = QFormLayout(physics)
        self.ground = QCheckBox("Collide with world ground plane")
        self.magnet = QCheckBox("Use world magnet")
        pform.addRow(self.ground)
        for name, default, minimum, maximum in (
            ("ground_y", self.document.scene.settings.height, -1e6, 1e6),
            ("bounce", 0.5, 0, 1),
            ("friction", 0.1, 0, 1),
            ("magnet_x", 960, -1e6, 1e6),
            ("magnet_y", 540, -1e6, 1e6),
            ("magnet_radius", 300, 0.01, 1e6),
            ("magnet_strength", 200, -10000, 10000),
        ):
            if name == "magnet_x":
                pform.addRow(self.magnet)
            field = numeric(self, "Particle " + name, minimum=minimum, maximum=maximum)
            field.setValue(default)
            self.parameters[name] = field
            pform.addRow(name.replace("_", " ").title(), field)
        hint = QLabel(
            "Physics requires World space. Ground Y uses scene pixels. Magnets use "
            "linear falloff inside their radius; negative strength repels particles. "
            "The ground is a static horizontal plane, not arbitrary artwork collision."
        )
        hint.setWordWrap(True)
        pform.addRow(hint)
        self.note = QLabel(
            "Regions are editor/game metadata. Particles render in preview and output. "
            "Move/rotate/scale and key visibility in the normal timeline."
        )
        self.note.setWordWrap(True)
        box.addWidget(self.note)
        row = QHBoxLayout()
        box.addLayout(row)
        for label, callback in (("Apply", self.apply), ("Close", self.close)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            row.addWidget(button)
        self.tabs.currentChanged.connect(self.refresh)
        self.items.currentIndexChanged.connect(self.load)
        self.refresh()

    def refresh(self) -> None:
        """List only saved items belonging to the selected tool and editable view."""
        field = "particle_emitter" if self.tabs.currentIndex() else "game_region"
        previous = self.items.currentData()
        with QSignalBlocker(self.items):
            self.items.clear()
            self.items.addItem("New item", "")
            for obj in self.document.scene.objects:
                if field in obj.extra and (
                    self.document.animation_scope is None or obj.id in self.document.animation_scope
                ):
                    self.items.addItem(obj.name, obj.id)
            self.items.setCurrentIndex(max(0, self.items.findData(previous)))
        self.load()

    def load(self) -> None:
        """Load authored parameters by stable identity without changing the scene."""
        obj = next(
            (o for o in self.document.scene.objects if o.id == self.items.currentData()), None
        )
        if obj is None:
            if self.item_name.text() in ("Hitbox", "Particles"):
                self.item_name.setText("Particles" if self.tabs.currentIndex() else "Hitbox")
            return
        self.item_name.setText(obj.name)
        self.pos_x.setValue(obj.transform.x)
        self.pos_y.setValue(obj.transform.y)
        if self.tabs.currentIndex():
            data = obj.extra["particle_emitter"]
            for name, value in self.parameters.items():
                value.setValue(data.get(name, value.value()))
            self.color.setText(data["color"])
            self.primitive.setCurrentText(data["shape"])
            self.world_space.setChecked(data["world_space"])
            self.ground.setChecked(data.get("ground_enabled", False))
            self.magnet.setChecked(data.get("magnet_enabled", False))
        else:
            data = obj.extra["game_region"]
            self.region_type.setCurrentText(data["type"])
            self.region_shape.setCurrentText(data["shape"])
            self.region_width.setValue(data["width"])
            self.region_height.setValue(data["height"])
            self.region_group.setText(data.get("group", ""))
            self.region_payload.setPlainText(json.dumps(json_copy(data.get("payload", {}))))

    def apply(self) -> None:
        """Commit one reversible service operation; source/workspace changes reject stale edits."""
        identity = self.items.currentData()

        def edit(_: object) -> None:
            nonlocal identity
            if (
                self.host.viewmodel.documents is not self.document
                or self.document.scene.id != self.scene_id
                or self.document.animation_context != self.context
            ):
                raise ProjectError("Reopen Game regions & particles in the active workspace.")
            service = GameAuthoringService(self.document)
            fields = dict(
                identity=identity,
                name=self.item_name.text(),
                x=self.pos_x.value(),
                y=self.pos_y.value(),
                parent=self.parent_object.currentData(),
            )
            if self.tabs.currentIndex():
                identity = service.emitter(
                    **fields,
                    settings={
                        **{k: v.value() for k, v in self.parameters.items()},
                        "color": self.color.text(),
                        "shape": self.primitive.currentText(),
                        "world_space": self.world_space.isChecked(),
                        "ground_enabled": self.ground.isChecked(),
                        "magnet_enabled": self.magnet.isChecked(),
                    },
                )
            else:
                try:
                    payload = json.loads(self.region_payload.toPlainText())
                except json.JSONDecodeError:
                    raise ProjectError("Region payload must be a valid JSON object.") from None
                identity = service.region(
                    **fields,
                    kind=self.region_type.currentText(),
                    shape=self.region_shape.currentText(),
                    width=self.region_width.value(),
                    height=self.region_height.value(),
                    group=self.region_group.text(),
                    payload=payload,
                )

        self.host.viewmodel.scene.run(edit)
        self.note.setText(
            self.host.viewmodel.scene.error or "Saved. Animate it through normal scene channels."
        )
        if not self.host.viewmodel.scene.error:
            self.refresh()
            self.items.setCurrentIndex(self.items.findData(identity))
