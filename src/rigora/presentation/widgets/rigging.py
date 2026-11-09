"""Contextual bone authoring and editable constraint settings in the shared dark/light shell."""

from dataclasses import replace
from typing import Any

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from rigora.domain.entities import Constraint
from rigora.presentation.icons import IconProvider
from rigora.presentation.viewmodels.rigging import RigViewModel


class RigPanel(QWidget):
    """Expose validated rig operations with ordinary controls and persistent error feedback."""

    mode_changed = Signal(bool)
    target_changed = Signal(str)
    frame_requested = Signal()

    def __init__(self, model: RigViewModel, icons: IconProvider) -> None:
        """Build scrollable authoring forms and bind them to one rig ViewModel."""
        super().__init__()
        self.model, self.icons = model, icons
        self._refreshing = False
        self._shown: dict[str, float] = {}
        self._param_shown: dict[str, float] = {}
        self.tool_buttons: dict[str, QToolButton] = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        self.mode = QCheckBox("Bone tools")
        self.mode.setToolTip(
            "Pose at the current frame, or draw and configure bones. The timeline stays available."
        )
        self.mode.toggled.connect(self.mode_changed.emit)
        outer.addWidget(self.mode)
        tools = QHBoxLayout()
        for tool, icon, label in (
            (
                "select",
                "near_me",
                "Select & transform · Shift adds bones · Ctrl-drag pulls the chain",
            ),
            ("draw", "device_hub", "Draw bone"),
            ("length", "straighten", "Edit endpoint"),
        ):
            button = QToolButton()
            button.setIcon(icons.icon(icon))
            button.setProperty("materialIcon", icon)
            button.setToolTip(
                "Draw bone · Snap to joint circles · Hold Alt for free placement"
                if tool == "draw"
                else label
            )
            button.setAccessibleName(label)
            button.clicked.connect(lambda checked=False, key=tool: model.set_tool(key))
            button.setCheckable(True)
            self.tool_buttons[tool] = button
            tools.addWidget(button)
        outer.addLayout(tools)
        frame = QPushButton("Frame rig")
        frame.setIcon(icons.icon("fit_screen"))
        frame.setProperty("materialIcon", "fit_screen")
        frame.clicked.connect(self.frame_requested.emit)
        outer.addWidget(frame)
        tabs = QTabWidget()
        outer.addWidget(tabs, 1)
        bones, bone_box = self.page(tabs, "Bones")
        template_row = QHBoxLayout()
        self.templates = QComboBox()
        self.templates.addItems(["Chain", "Biped", "Quadruped"])
        template_row.addWidget(self.templates, 1)
        self.button(
            template_row,
            "Add template",
            "add",
            self.add_template,
        )
        bone_box.addLayout(template_row)
        self.selection = QLabel("Select a bone in the hierarchy or viewport")
        self.selection.setWordWrap(True)
        bone_box.addWidget(self.selection)
        self.form = QFormLayout()
        self.name = QLineEdit()
        self.name.setAccessibleName("Bone name")
        self.form.addRow("Name", self.name)
        self.fields = {}
        for key, label in (
            ("length", "Length"),
            ("x", "Position X"),
            ("y", "Position Y"),
            ("rotation", "Rotation °"),
            ("pivot_x", "Pivot X"),
            ("pivot_y", "Pivot Y"),
            ("scale_x", "Scale X"),
            ("scale_y", "Scale Y"),
        ):
            spin = self.numeric(label, 0 if key == "length" else -1e300)
            self.fields[key] = spin
            self.form.addRow(label, spin)
        self.group = QLineEdit()
        self.form.addRow("Group", self.group)
        self.color = QLineEdit()
        self.color.setPlaceholderText("#RRGGBB")
        self.form.addRow("Bone color", self.color)
        self.parent_combo = QComboBox()
        self.parent_combo.setAccessibleName("Bone parent")
        self.parent_combo.currentIndexChanged.connect(self.reparent)
        self.form.addRow("Parent", self.parent_combo)
        self.visible, self.locked = QCheckBox("Visible"), QCheckBox("Locked")
        self.visible.toggled.connect(lambda state: self.toggle_property("visible", state))
        self.locked.toggled.connect(lambda state: self.toggle_property("locked", state))
        self.form.addRow(self.visible, self.locked)
        bone_box.addLayout(self.form)
        apply = QPushButton("Apply bone properties")
        apply.setIcon(icons.icon("check"))
        apply.setProperty("materialIcon", "check")
        apply.clicked.connect(self.apply_bone)
        bone_box.addWidget(apply)
        row = QHBoxLayout()
        self.button(row, "Insert joint", "add", lambda: self.selected_action("insert"))
        self.button(row, "Delete bone", "delete_outline", lambda: self.selected_action("delete"))
        bone_box.addLayout(row)
        self.axis = self.numeric("Mirror axis X")
        self.axis.setValue(450)
        mirror = QFormLayout()
        mirror.addRow("Mirror axis X", self.axis)
        bone_box.addLayout(mirror)
        mirror_button = QPushButton("Mirror selected branch")
        mirror_button.setIcon(icons.icon("flip"))
        mirror_button.setProperty("materialIcon", "flip")
        mirror_button.clicked.connect(lambda: self.selected_action("mirror"))
        bone_box.addWidget(mirror_button)
        self.groups = QComboBox()
        self.groups.setAccessibleName("Bone group")
        bone_box.addWidget(self.groups)
        group_row = QHBoxLayout()
        for label, icon, callback in (
            ("Select group", "select_all", lambda: model.select_group(self.groups.currentText())),
            ("Hide group", "visibility_off", lambda: self.group_state(visible=False)),
            ("Show group", "visibility", lambda: self.group_state(visible=True)),
            ("Lock group", "lock", lambda: self.group_state(locked=True)),
            ("Unlock group", "lock_open", lambda: self.group_state(locked=False)),
        ):
            self.button(group_row, label, icon, callback)
        bone_box.addLayout(group_row)
        bone_box.addStretch()
        rules, rule_box = self.page(tabs, "Constraints")
        self.constraints = QComboBox()
        self.constraints.setAccessibleName("Rig constraint")
        self.constraints.currentIndexChanged.connect(self.load_constraint)
        rule_box.addWidget(self.constraints)
        setup = QFormLayout()
        self.owner, self.target = QComboBox(), QComboBox()
        self.kind = QComboBox()
        for key, label in (
            ("two_bone_ik", "Two-bone IK"),
            ("aim", "Aim / look at"),
            ("copy_transform", "Copy transform"),
            ("limits", "Position / rotation limits"),
            ("parent", "Parent space"),
            ("space_switch", "Space switching"),
            ("pin", "Pin local point"),
            ("track", "Track target position"),
            ("spring", "Spring follow-through physics"),
        ):
            self.kind.addItem(label, key)
        self.kind.currentIndexChanged.connect(self.show_parameters)
        setup.addRow("Owner", self.owner)
        setup.addRow("Solver", self.kind)
        setup.addRow("Target", self.target)
        self.target.currentIndexChanged.connect(
            lambda: self.target_changed.emit(self.target.currentData() or "")
        )
        rule_box.addLayout(setup)
        add = QPushButton("Add constraint")
        add.setIcon(icons.icon("add_link"))
        add.setProperty("materialIcon", "add_link")
        add.clicked.connect(self.add_constraint)
        rule_box.addWidget(add)
        self.enabled = QCheckBox("Constraint enabled")
        self.enabled.setChecked(True)
        rule_box.addWidget(self.enabled)
        self.parameters = QFormLayout()
        self.parameters.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.param_widgets: dict[str, QWidget] = {}
        self.param_labels: dict[str, QLabel] = {}
        self.ik_mode = QComboBox()
        self.ik_mode.addItems(["ik", "fk"])
        self.add_parameter("mode", "IK / FK", self.ik_mode)
        self.bend = QComboBox()
        self.bend.addItem("Clockwise", 1)
        self.bend.addItem("Counterclockwise", -1)
        self.add_parameter("bend", "Bend direction", self.bend)
        self.stretch = QCheckBox("Allow stretch")
        self.add_parameter("stretch", "Stretch", self.stretch)
        self.end_bone = QComboBox()
        self.add_parameter("end_bone_id", "Second bone", self.end_bone)
        self.param_numbers = {}
        for key, label, default in (
            ("max_stretch", "Maximum stretch", 1.5),
            ("min_reach", "Minimum reach", 0),
            ("max_reach", "Maximum reach (0 = auto)", 0),
            ("offset", "Angle offset °", 0),
            ("offset_x", "Follow offset X", 0),
            ("offset_y", "Follow offset Y", 0),
            ("min_x", "Minimum X", -1e9),
            ("max_x", "Maximum X", 1e9),
            ("min_y", "Minimum Y", -1e9),
            ("max_y", "Maximum Y", 1e9),
            ("min_rotation", "Minimum rotation °", -360),
            ("max_rotation", "Maximum rotation °", 360),
            ("point_x", "Pinned local X", 0),
            ("point_y", "Pinned local Y", 0),
            ("x", "Pin scene X", 0),
            ("y", "Pin scene Y", 0),
            ("frequency", "Spring frequency · Hz", 3),
            ("damping", "Spring damping ratio", 0.5),
            ("strength", "Spring strength · 0–1", 1),
            ("gravity", "Spring gravity · px/s²", 0),
            ("inertia", "Spring inertia · 0–3", 0.6),
            ("max_angle", "Spring limit · degrees", 65),
        ):
            spin = self.numeric(label)
            spin.setValue(default)
            spin.setProperty("default", default)
            self.param_numbers[key] = spin
            self.add_parameter(key, label, spin)
        self.order = self.numeric("Constraint order")
        self.order.setDecimals(0)
        self.add_parameter("order", "Evaluation order", self.order)
        self.maintain = QCheckBox("Keep pose on space switch")
        self.maintain.setChecked(True)
        rule_box.addWidget(self.maintain)
        rule_box.addLayout(self.parameters)
        row = QHBoxLayout()
        self.button(row, "Apply constraint", "check", self.apply_constraint)
        self.button(row, "Remove constraint", "delete_outline", self.remove_constraint)
        rule_box.addLayout(row)
        target_form = QFormLayout()
        self.target_x, self.target_y = (
            self.numeric("Target scene X"),
            self.numeric("Target scene Y"),
        )
        target_form.addRow("Target X", self.target_x)
        target_form.addRow("Target Y", self.target_y)
        rule_box.addLayout(target_form)
        move = QPushButton("Move target")
        move.setIcon(icons.icon("open_with"))
        move.setProperty("materialIcon", "open_with")
        move.clicked.connect(
            lambda: model.run(
                lambda service: service.move_target(
                    self.target.currentData(), self.target_x.value(), self.target_y.value()
                )
            )
        )
        rule_box.addWidget(move)
        rule_box.addStretch()
        self.feedback = QLabel()
        self.feedback.setWordWrap(True)
        outer.addWidget(self.feedback)
        model.changed.connect(self.refresh)
        self.show_parameters()
        self.refresh()

    @staticmethod
    def numeric(label: str, minimum: float = -1e300) -> QDoubleSpinBox:
        """Create a precision-limited editor without constraining stored geometry values."""
        spin = QDoubleSpinBox()
        spin.setRange(minimum, 1e300)
        spin.setDecimals(3)
        spin.setKeyboardTracking(False)
        spin.setAccessibleName(label)
        spin.setFixedWidth(125)
        return spin

    @staticmethod
    def page(tabs: QTabWidget, title: str) -> tuple[QWidget, QVBoxLayout]:
        """Add a scrollable form page so all controls remain reachable at compact heights."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        scroll.setWidget(content)
        tabs.addTab(scroll, title)
        return content, layout

    def button(self, row: QHBoxLayout, label: str, icon: str, callback: Any) -> None:
        """Add a compact Material action with accessible text and a descriptive tooltip."""
        button = QToolButton()
        button.setIcon(self.icons.icon(icon))
        button.setProperty("materialIcon", icon)
        button.setToolTip(label)
        button.setAccessibleName(label)
        button.clicked.connect(callback)
        row.addWidget(button)

    def add_parameter(self, key: str, label: str, widget: QWidget) -> None:
        """Register one ordinary solver control and its dynamically visible label."""
        text = QLabel(label)
        self.param_widgets[key], self.param_labels[key] = widget, text
        self.parameters.addRow(text, widget)

    def parameter_keys(self) -> set[str]:
        """List controls relevant to the selected solver without exposing implementation JSON."""
        return {
            "two_bone_ik": {
                "mode",
                "bend",
                "stretch",
                "max_stretch",
                "min_reach",
                "max_reach",
                "end_bone_id",
            },
            "aim": {"offset"},
            "limits": {"min_x", "max_x", "min_y", "max_y", "min_rotation", "max_rotation"},
            "pin": {"point_x", "point_y", "x", "y"},
            "track": {"offset_x", "offset_y"},
            "spring": {"frequency", "damping", "strength", "gravity", "inertia", "max_angle"},
        }.get(self.kind.currentData(), set())

    def show_parameters(self) -> None:
        """Keep the form focused on settings supported by the current solver."""
        if not hasattr(self, "param_widgets"):
            return
        keys = self.parameter_keys() | {"order"}
        for key, widget in self.param_widgets.items():
            widget.setVisible(key in keys)
            self.param_labels[key].setVisible(key in keys)

    def selected_action(self, action: str) -> None:
        """Apply one topology operation to the primary selected bone."""
        key = self.model.selected[0] if self.model.selected else None
        if key:
            self.model.run(
                lambda service: (
                    service.mirror(key, self.axis.value())
                    if action == "mirror"
                    else service.insert(key)
                    if action == "insert"
                    else service.delete_many(self.model.selected)
                )
            )

    def add_template(self) -> None:
        """Create a reusable skeleton and frame its evaluated geometry for immediate editing."""
        self.model.run(lambda service: service.template(self.templates.currentText()))
        self.frame_requested.emit()

    def toggle_property(self, key: str, state: bool) -> None:
        """Commit visibility/locking independently so unlocking never rewrites other fields."""
        if not self._refreshing and self.model.selected:
            self.model.run(lambda service: service.update(self.model.selected[0], **{key: state}))

    def group_state(self, **changes: bool) -> None:
        """Apply a named group's visibility or lock state through an undoable command."""
        self.model.run(lambda service: service.set_group(self.groups.currentText(), **changes))

    def reparent(self) -> None:
        """Commit an explicit parent selection while preserving rest-world transforms."""
        if not self._refreshing and self.model.selected:
            self.model.run(
                lambda service: service.reparent(
                    self.model.selected[0], self.parent_combo.currentData()
                )
            )

    def apply_bone(self) -> None:
        """Apply edited fields only, preserving full precision in untouched authoring values."""
        bone = self.model.bone
        if bone is None:
            return
        changes: dict[str, Any] = {}
        transform: dict[str, Any] = {
            key: spin.value()
            for key, spin in self.fields.items()
            if key != "length" and spin.value() != self._shown.get(key)
        }
        if transform:
            changes["transform"] = replace(bone.transform, **transform)
        if self.fields["length"].value() != self._shown.get("length"):
            changes["length"] = self.fields["length"].value()
        for key, field in (("name", self.name), ("group", self.group), ("color", self.color)):
            if field.text() != getattr(bone, key):
                changes[key] = field.text()
        if changes:
            if self.model.animating and (transform or "length" in changes):
                values = {f"transform.{key}": float(value) for key, value in transform.items()}
                if "length" in changes:
                    values["length"] = changes.pop("length")
                changes.pop("transform", None)
                self.model.edit_pose(values, changes)
            else:
                self.model.run(lambda service: service.update(bone.id, **changes))

    def rule(self) -> Constraint | None:
        """Resolve the selected stored constraint without retaining stale model records."""
        return (
            next(
                (
                    c
                    for c in self.model.service.scene.constraints
                    if c.id == self.constraints.currentData()
                ),
                None,
            )
            if self.model.service
            else None
        )

    def add_constraint(self) -> None:
        """Create a default constraint for the chosen owner and optional target."""
        self.model.run(
            lambda service: service.add_constraint(
                self.owner.currentData(), self.kind.currentData(), self.target.currentData()
            )
        )

    def remove_constraint(self) -> None:
        """Remove the selected solver while preserving its reusable control object."""
        key = self.constraints.currentData()
        if key:
            self.model.run(lambda service: service.remove_constraint(key))

    def load_constraint(self) -> None:
        """Load a selected rule's settings and target coordinates without changing the model."""
        if self._refreshing:
            return
        rule = self.rule()
        if rule is None:
            return
        self.owner.setCurrentIndex(self.owner.findData(rule.owner_id))
        self.target.setCurrentIndex(self.target.findData(rule.target_id))
        self.kind.setCurrentIndex(self.kind.findData(rule.kind))
        self.enabled.setChecked(rule.enabled)
        self.order.setValue(rule.order)
        self.ik_mode.setCurrentText(str(rule.parameters.get("mode", "ik")))
        self.bend.setCurrentIndex(self.bend.findData(rule.parameters.get("bend", 1)))
        self.stretch.setChecked(bool(rule.parameters.get("stretch", False)))
        self.end_bone.setCurrentIndex(self.end_bone.findData(rule.parameters.get("end_bone_id")))
        for key, spin in self.param_numbers.items():
            value = rule.parameters.get(key, spin.property("default"))
            spin.setValue(
                float(value) if type(value) in (int, float) else float(spin.property("default"))
            )
            self._param_shown[key] = spin.value()
        if (
            self.model.pose
            and rule.target_id is not None
            and rule.target_id in self.model.pose.nodes
        ):
            x, y = self.model.pose.nodes[rule.target_id].world_matrix[4:]
            self.target_x.setValue(x)
            self.target_y.setValue(y)
        self.target_changed.emit(rule.target_id or "")

    def apply_constraint(self) -> None:
        """Persist visible settings, preserving unknown parameters and optional space offsets."""
        rule = self.rule()
        if rule is None:
            return
        params = dict(rule.parameters)
        if self.kind.currentData() != rule.kind or self.owner.currentData() != rule.owner_id:
            self.feedback.setText("Use Add constraint to create a different solver or owner.")
            return
        for key in self.parameter_keys():
            if key in self.param_numbers:
                value = self.param_numbers[key].value()
                if value == self._param_shown.get(key):
                    continue
                if key == "max_reach" and value == 0:
                    params.pop(key, None)
                else:
                    params[key] = value
        if rule.kind == "two_bone_ik":
            params.update(
                mode=self.ik_mode.currentText(),
                bend=self.bend.currentData(),
                stretch=self.stretch.isChecked(),
                end_bone_id=self.end_bone.currentData(),
            )
        target = self.target.currentData()
        self.model.run(
            lambda service: service.update_constraint(
                rule.id,
                parameters=params,
                target_id=target,
                enabled=self.enabled.isChecked(),
                order=int(self.order.value()),
                keep_world=self.maintain.isChecked(),
            )
        )

    def refresh(self) -> None:
        """Refresh context after commands without feeding programmatic values back into services."""
        self._refreshing = True
        with QSignalBlocker(self.mode):
            self.mode.setChecked(self.model.active)
        for key, button in self.tool_buttons.items():
            button.setChecked(self.model.active and self.model.tool == key)
        bone, service = self.model.bone, self.model.service
        self.fields["length"].setEnabled(not bone or not bone.extra.get("rig_root"))
        self.parent_combo.setEnabled(not bone or not bone.extra.get("rig_root"))
        self.selection.setText(
            f"{len(self.model.selected)} selected · {bone.name}"
            if bone
            else "Select a bone or draw a new one"
        )
        self.parent_combo.clear()
        self.parent_combo.addItem("Scene space", None)
        previous_group = self.groups.currentText()
        previous_rule = self.constraints.currentData()
        self.groups.clear()
        self.owner.clear()
        self.target.clear()
        self.end_bone.clear()
        self.target.addItem("None / fixed point", None)
        self.constraints.clear()
        if service:
            for rig in service.scene.skeletons:
                for item in rig.bones:
                    self.owner.addItem(item.name, item.id)
                    self.target.addItem(item.name, item.id)
                    self.end_bone.addItem(item.name, item.id)
                    if bone and item.id != bone.id and any(b.id == bone.id for b in rig.bones):
                        self.parent_combo.addItem(item.name, item.id)
            for obj in service.scene.objects:
                self.owner.addItem(obj.name, obj.id)
                self.target.addItem(obj.name, obj.id)
            self.groups.addItems(
                sorted({b.group for r in service.scene.skeletons for b in r.bones})
            )
            self.groups.setCurrentText(previous_group)
            for rule in service.scene.constraints:
                self.constraints.addItem(rule.name, rule.id)
            index = self.constraints.findData(previous_rule)
            self.constraints.setCurrentIndex(index if index >= 0 else self.constraints.count() - 1)
        if bone:
            self.name.setText(bone.name)
            self.group.setText(bone.group)
            self.color.setText(bone.color)
            for key, spin in self.fields.items():
                node = self.model.pose.nodes.get(bone.id) if self.model.pose else None
                source = node.local if self.model.animating and node else bone.transform
                length = node.length if self.model.animating and node else bone.length
                spin.setValue(length if key == "length" else getattr(source, key))
                self._shown[key] = spin.value()
            self.visible.setChecked(bone.visible)
            self.locked.setChecked(bone.locked)
            self.parent_combo.setCurrentIndex(self.parent_combo.findData(bone.parent_id))
            self.owner.setCurrentIndex(self.owner.findData(bone.id))
        self.feedback.setText(
            self.model.error or ("\n".join(self.model.pose.warnings) if self.model.pose else "")
        )
        self._refreshing = False
        self.load_constraint()
