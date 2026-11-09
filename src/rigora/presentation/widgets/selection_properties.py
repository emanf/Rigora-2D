"""Compact live numeric properties for the scene's current object or bone selection."""

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import QDoubleSpinBox, QHBoxLayout, QLabel, QToolButton, QWidget

from rigora.application_services.selection_properties import SelectionPropertyService
from rigora.domain.entities import Camera, Group, SceneObject
from rigora.domain.project import ProjectError
from rigora.presentation.widgets.clip_editor import numeric

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


class SelectionProperties(QWidget):
    """Mirror evaluated geometry and commit only deliberate edits through shared services."""

    def __init__(self, window: "MainWindow") -> None:
        """Build movable property groups; binding starts after the workspaces exist."""
        super().__init__(window)
        self.host = window
        self.fields: dict[str, QDoubleSpinBox] = {}
        self._service: SelectionPropertyService | None = None
        self._signature: tuple[object, ...] | None = None
        self.groups: dict[str, QWidget] = {}

        def group(key: str) -> QHBoxLayout:
            """Keep related fields together when the host toolbar wraps or reorders."""
            content = QWidget(self)
            layout = QHBoxLayout(content)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(3)
            self.groups[key] = content
            return layout

        row = group("position")
        for label, name in (
            ("X", "x"),
            ("Y", "y"),
            ("Z", "depth"),
            ("W", "width"),
            ("H", "height"),
            ("R", "rotation"),
            ("O", "opacity"),
        ):
            if name in ("width", "rotation"):
                row = group("size" if name == "width" else "appearance")
            elif name != "x":
                row.addSpacing(8)
            if name == "height":
                self.ratio = self.button(
                    "lock", "Keep width and height proportional", checkable=True
                )
                self.ratio.setChecked(True)
                self.ratio.toggled.connect(
                    lambda checked: self.ratio.setIcon(
                        window.icons.icon("lock" if checked else "lock_open")
                    )
                )
                row.addWidget(self.ratio)
            row.addWidget(QLabel(label + ":"))
            field = numeric(
                self,
                "Selected object " + name,
                minimum=0 if name in ("width", "height", "opacity") else -1e9,
                maximum=100 if name == "opacity" else 1e9,
            )
            field.setDecimals(0 if name == "depth" else 1)
            if name == "depth":
                field.setRange(-1_000_000, 1_000_000)
                field.setAccessibleName("Depth (Z)")
            field.setFixedWidth(67 if name in ("width", "height") else 62)
            field.setObjectName("selection_" + name)
            field.setToolTip(
                {
                    "x": "Pivot X in parent coordinates; selection left for multiple objects (px)",
                    "y": "Pivot Y in parent coordinates; selection top for multiple objects (px)",
                    "width": "Width before rotation (px); scene bounds for multiple objects",
                    "height": "Height before rotation (px); scene bounds for multiple objects",
                    "rotation": "Rotation (degrees)",
                    "depth": "Depth (Z) · Default 0; higher draws in front. "
                    "Equal Z uses scene layer order. Relative to parent.",
                    "opacity": "Opacity (%) · Auto key records animation",
                }[name]
            )
            field.editingFinished.connect(lambda key=name: self.change(key))
            self.fields[name] = field
            row.addWidget(field)
        row = group("flip")
        row.addWidget(QLabel("V:"))
        self.visible = self.button(
            "visibility", "Visible · Auto key records a hold key", checkable=True
        )
        self.visible.clicked.connect(
            lambda checked: self.run(lambda s, keys: s.appearance(keys, visible=checked))
        )
        row.addWidget(self.visible)
        row.addSpacing(8)
        row.addWidget(QLabel("Flip:"))
        self.horizontal = self.button("flip", "Flip horizontally")
        self.horizontal.setText("H")
        self.horizontal.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.horizontal.clicked.connect(lambda: self.run(lambda s, keys: s.flip(keys)))
        self.vertical = self.button("flip", "Flip vertically")
        self.vertical.setText("V")
        self.vertical.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.vertical.clicked.connect(lambda: self.run(lambda s, keys: s.flip(keys, vertical=True)))
        row.addWidget(self.horizontal)
        row.addWidget(self.vertical)
        row.addSpacing(8)
        self.reset = self.button(
            "restart_alt",
            "Reset selection · original size, centered pivot, rotation 0°, "
            "Depth (Z) 0, opacity 100%, visible, camera center",
        )
        self.reset.clicked.connect(lambda: self.run(lambda s, keys: s.reset(keys)))
        self.reset.setText("Reset")
        self.reset.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        row.addWidget(self.reset)
        self.setEnabled(False)
        self.hide()

    def setEnabled(self, enabled: bool) -> None:
        """Keep hosted group contents in sync while their independent grips remain usable.

        The toolbar owns each group's visual parent; this hidden controller owns
        selection state and command routing rather than geometry.
        """
        super().setEnabled(enabled)
        for group in self.groups.values():
            group.setEnabled(enabled)

    def button(self, icon: str, label: str, *, checkable: bool = False) -> QToolButton:
        """Use the same Material controls as the main toolbar with descriptive accessibility."""
        button = QToolButton(self)
        button.setIcon(self.host.icons.icon(icon))
        button.setProperty("materialIcon", icon)
        button.setAccessibleName(label)
        button.setToolTip(label)
        button.setCheckable(checkable)
        return button

    def bind(self) -> None:
        """Follow selection and every evaluated viewport pose, including live drag previews."""
        self.host.viewmodel.scene.changed.connect(self.refresh)
        self.host.viewmodel.rig.changed.connect(self.refresh)
        self.host.viewport.pose_changed.connect(self.refresh)

    def keys(self) -> tuple[str, ...]:
        """Match the scene's whole-character transform targets and rig selection."""
        vm = self.host.viewmodel
        keys = tuple(vm.rig.selected) if vm.rig.active else vm.scene.selected
        targets = self.host.scene_workspace.movement_keys(keys)
        service = vm.scene.service
        if not service:
            return ()
        records = service.records()
        order = {key: i for i, key in enumerate(records)}
        return tuple(
            k
            for k in sorted(targets, key=lambda key: order.get(key, -1))
            if k in records and not service._has_ancestor(k, set(targets), records)
        )

    def refresh(self) -> None:
        """Read live values without changing animation, history or an in-progress numeric entry."""
        vm = self.host.viewmodel
        doc = vm.scene.document
        pose = self.host.viewport.source_pose
        keys = self.keys() if doc else ()
        signature = (id(doc), id(pose), keys)
        if signature == self._signature:
            return
        self._signature = signature
        if not doc or not keys or pose is None:
            self.setEnabled(False)
            return
        if self._service is None or self._service.document is not doc:
            self._service = SelectionPropertyService(doc)
        try:
            state = self._service.metrics(keys, pose)
        except (ProjectError, ValueError):
            self.setEnabled(False)
            return
        self.setEnabled(not any(self._service.locked(k) for k in keys))
        self.horizontal.setEnabled(bool(self._service.meshes_for(keys)))
        self.vertical.setEnabled(self.horizontal.isEnabled())
        self.fields["width"].setEnabled(state.width > 1e-8)
        self.fields["height"].setEnabled(state.height > 1e-8)
        self.fields["depth"].setEnabled(
            all(
                isinstance(self._service.record(k), (Group, SceneObject))
                and not isinstance(self._service.record(k), Camera)
                for k in keys
            )
        )
        cameras = any(isinstance(self._service.record(k), Camera) for k in keys)
        self.fields["opacity"].setEnabled(not cameras)
        self.visible.setEnabled(not cameras)
        for name, field in self.fields.items():
            if not field.hasFocus() and not field.lineEdit().hasFocus():
                with QSignalBlocker(field):
                    field.setValue(getattr(state, name))
        with QSignalBlocker(self.visible):
            self.visible.setChecked(state.visible)
            self.visible.setIcon(
                self.host.icons.icon("visibility" if state.visible else "visibility_off")
            )

    def run(self, operation: Callable[[SelectionPropertyService, tuple[str, ...]], None]) -> None:
        """Commit one complete edit, preserving the scene's Auto key and binding modes."""
        keys = self.keys()
        self.host.viewmodel.playback.pause()

        def apply(source: object) -> None:
            """Use current service configuration without persisting toolbar state in the scene."""
            scene = self.host.viewmodel.scene.service
            assert scene is not None
            service = SelectionPropertyService(scene.document)
            service.auto_key, service.sprite_edit, service.part_edit = (
                scene.auto_key,
                scene.sprite_edit,
                scene.part_edit,
            )
            operation(service, keys)

        self.host.viewmodel.scene.run(apply)
        self._signature = None
        self.refresh()

    def change(self, name: str) -> None:
        """Avoid an extra undo command when a value is merely focused or submitted unchanged."""
        if not self.isEnabled() or not self._service:
            return
        value = self.fields[name].value()
        try:
            state = self._service.metrics(self.keys())
        except ProjectError:
            self.refresh()
            return
        if abs(value - getattr(state, name)) >= 0.05:
            self.run(lambda s, keys: s.edit(keys, name, value, ratio=self.ratio.isChecked()))
