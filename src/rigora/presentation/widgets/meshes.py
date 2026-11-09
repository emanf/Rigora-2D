"""Compact mesh, deformation, weight and motion authoring controls for the shared inspector."""

from collections.abc import Callable, Mapping
from typing import Any, cast

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from rigora.application_services.deformation import deformation_presets
from rigora.application_services.skinning import SkinService
from rigora.domain.project import ProjectError
from rigora.engine.deformation import DeformationPlan, lattice_controls
from rigora.presentation.icons import IconProvider
from rigora.presentation.viewmodels.meshes import MeshViewModel
from rigora.presentation.widgets.composer_editors import slider_field


class MeshPanel(QWidget):
    """Expose context-sensitive authoring controls and persistent validation feedback."""

    import_requested = Signal()
    regenerate_requested = Signal()
    export_requested = Signal()
    reuse_requested = Signal()
    example_requested = Signal(str)
    mode_changed = Signal(bool)
    frame_requested = Signal()
    share_ffd_requested = Signal()

    def __init__(self, model: MeshViewModel, icons: IconProvider) -> None:
        """Build one scrollable inspector with common selection and four focused editing pages."""
        super().__init__()
        self.model, self.icons = model, icons
        self._refreshing = False
        self._frame_context: tuple[str, str | None, float] | None = None
        self._subdivision_context: tuple[object, ...] | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(4)
        actions = QHBoxLayout()
        outer.addLayout(actions)
        import_artwork = self.button(
            actions, "Import artwork…", "add_photo_alternate", self.import_requested.emit
        )
        frame_artwork = self.button(
            actions, "Frame artwork", "fit_screen", self.frame_requested.emit
        )
        key_pose = self.button(actions, "Key mesh pose", "add_circle_outline", model.key_pose)
        for action in (import_artwork, frame_artwork, key_pose):
            action.setText("")
            action.setFixedSize(30, 30)
        actions.addStretch()
        self.mode = QCheckBox("Mesh / deformation edit mode")
        self.mode.setToolTip(
            "Pause playback and edit the selected artwork. Ctrl adds to selection."
        )
        self.mode.toggled.connect(self.mode_changed.emit)
        outer.addWidget(self.mode)
        self.meshes = QComboBox()
        self.meshes.setAccessibleName("Selected artwork mesh")
        self.meshes.currentIndexChanged.connect(self.select_mesh)
        outer.addWidget(self.meshes)
        key_pose.setToolTip(
            "Capture this surface at the timeline playhead. "
            "Move to another frame before sculpting again."
        )
        tabs = self.tabs = QTabWidget()
        outer.addWidget(tabs, 1)
        mesh = self.page(tabs, "Mesh")
        self.tools = QComboBox()
        for name, key in (
            ("Select / move vertices", "vertex"),
            ("Soft Drag · stretch an area", "soft"),
            ("Select edges", "edge"),
            ("Select triangles", "triangle"),
            ("Insert vertex", "insert"),
            ("Add image-area pin", "area_pin"),
            ("Custom FFD / lattice / pin controls", "control"),
            ("Paint weights", "paint"),
        ):
            self.tools.addItem(name, key)
        self.tools.currentIndexChanged.connect(self.change_tool)
        mesh.addWidget(self.tools)
        self.selection = QLabel()
        self.selection.setWordWrap(True)
        mesh.addWidget(self.selection)
        self.details = QLabel()
        self.details.setWordWrap(True)
        self.details.setObjectName("Muted")
        mesh.addWidget(self.details)
        self.button(mesh, "Select all points", "select_all", self.select_all)
        self.button(mesh, "Connect triangle", "polyline", self.connect_face)
        self.button(
            mesh,
            "Delete vertices",
            "delete",
            lambda: model.run(lambda s: s.delete(model.mesh_id, set(model.selected))),
        )
        self.pinned, self.protected = (
            QCheckBox("Pinned base position"),
            QCheckBox("Protected region"),
        )
        self.pinned.setToolTip(
            "Hold selected vertices at their sampled base position after every deformer."
        )
        self.protected.setToolTip(
            "Exclude selected vertices from base movement, deletion and weight painting."
        )
        self.pinned.clicked.connect(
            lambda checked: model.run(
                lambda s: s.set_flags(model.mesh_id, set(model.selected), pinned=checked)
            )
        )
        self.protected.clicked.connect(
            lambda checked: model.run(
                lambda s: s.set_flags(model.mesh_id, set(model.selected), protected=checked)
            )
        )
        mesh.addWidget(self.pinned)
        mesh.addWidget(self.protected)
        subdivision = self.subdivision = QGroupBox("Subdivision")
        subdivision.setAccessibleName("Mesh subdivision")
        subdivision_layout = QVBoxLayout(subdivision)
        subdivision_layout.setSpacing(4)
        form = QFormLayout()
        form.setVerticalSpacing(4)
        self.division = QComboBox()
        for title, mode in (("Full", "full"), ("Mask", "mask"), ("Grid", "grid")):
            self.division.addItem(title, mode)
        form.addRow("Division type", self.division)
        self.density, self.alignment = QSpinBox(), QSpinBox()
        self.density.setRange(1, 10)
        self.density.setValue(4)
        self.alignment.setRange(0, 10)
        self.alignment.setValue(1)
        self.expand = self.spin(0, 100, 0)
        self.expand.setSuffix(" px")
        subdivision_rows = {}
        for title, field in (
            ("Density", self.density),
            ("Alignment", self.alignment),
            ("Expand", self.expand),
        ):
            field.setAccessibleName(f"Mesh subdivision {title.lower()}")
            field_row = slider_field(field)
            form.addRow(title, field_row)
            subdivision_rows[title] = field_row
        self.division.currentIndexChanged.connect(
            lambda: subdivision_rows["Expand"].setEnabled(self.division.currentData() == "mask")
        )
        self.division.currentIndexChanged.connect(
            lambda: subdivision_rows["Alignment"].setEnabled(self.division.currentData() != "grid")
        )
        subdivision_rows["Expand"].setEnabled(False)
        subdivision_layout.addLayout(form)
        self.subdivide_button = self.button(
            subdivision_layout, "Apply…", "grid_on", self.regenerate_requested.emit
        )
        self.subdivide_button.setToolTip("Apply subdivision to the selected mesh")
        self.subdivide_button.setAccessibleName("Apply mesh subdivision")
        self.subdivision_progress = QProgressBar()
        self.subdivision_progress.setRange(0, 100)
        self.subdivision_progress.setValue(0)
        self.subdivision_progress.hide()
        subdivision_layout.addWidget(self.subdivision_progress)
        mesh.insertWidget(0, subdivision)
        hint = QLabel(
            "Ctrl-click or drag a box to select points. For custom FFD, drag selected dots "
            "or their box to move them; drag box handles to resize. Ctrl+A selects all. "
            "Soft Drag grabs between points with adjustable radius and falloff. "
            "Subdivision replaces vertex keys and mesh edits; Undo restores them. "
            "Insertion splits the hit face/edge; deletion leaves "
            "holes. UVs and source artwork are preserved."
        )
        hint.setWordWrap(True)
        hint.setObjectName("Muted")
        mesh.addWidget(hint)
        mesh.addStretch()
        deform = self.page(tabs, "Deform")
        self.stages = QListWidget()
        self.stages.setMaximumHeight(136)
        self.stages.currentRowChanged.connect(self.select_stage)
        deform.addWidget(self.stages)
        self.presets = QComboBox()
        for preset in deformation_presets():
            self.presets.addItem(preset.name)
        deform.addWidget(self.presets)
        self.lattice_size = QSpinBox()
        self.lattice_size.setRange(2, 8)
        self.lattice_size.setValue(3)
        form = QFormLayout()
        form.addRow("New control grid", self.lattice_size)
        deform.addLayout(form)
        self.button(deform, "Add deformer", "add", self.add_stage)
        row = QHBoxLayout()
        self.button(
            row, "Up", "arrow_upward", lambda: model.run(lambda s: s.reorder(model.stage_id, -1))
        )
        self.button(
            row, "Down", "arrow_downward", lambda: model.run(lambda s: s.reorder(model.stage_id, 1))
        )
        self.button(row, "Remove", "delete", lambda: model.run(lambda s: s.remove(model.stage_id)))
        deform.addLayout(row)
        self.enabled = QCheckBox("Deformer enabled")
        self.enabled.clicked.connect(
            lambda checked: model.run(lambda s: s.update(model.stage_id, enabled=checked))
        )
        deform.addWidget(self.enabled)
        self.ffd_object_strength = self.spin(0, 10, 1)
        self.ffd_clip_strength = self.spin(0, 10, 1)
        strengths = QFormLayout()
        strengths.addRow("Object FFD strength ×", self.ffd_object_strength)
        strengths.addRow("Selected stage strength ×", self.ffd_clip_strength)
        deform.addLayout(strengths)
        self.button(deform, "Apply FFD strengths", "tune", self.apply_ffd_strengths)
        self.button(
            deform, "Share FFD shape / motion…", "folder_zip", self.share_ffd_requested.emit
        )
        self.control_mode = QComboBox()
        self.control_mode.addItems(["Move", "Scale", "Rotate"])
        self.control_mode.setAccessibleName("FFD selection transform tool")
        self.control_mode.currentTextChanged.connect(self.activate_controls)
        deform.addWidget(QLabel("CUSTOM FFD · SELECTED DOTS"))
        deform.addWidget(self.control_mode)
        self.control_selection = QLabel()
        deform.addWidget(self.control_selection)
        control_form = QFormLayout()
        self.control_fields = {}
        for key, title, value in (
            ("dx", "Move X", 0),
            ("dy", "Move Y", 0),
            ("rotation", "Rotation °", 0),
            ("scale_x", "Scale X %", 100),
            ("scale_y", "Scale Y %", 100),
        ):
            field = self.spin(-100000, 100000, value)
            self.control_fields[key] = field
            field.setAccessibleName(f"FFD {title}")
            control_form.addRow(title, field)
        deform.addLayout(control_form)
        self.control_ratio = QCheckBox("Keep scale proportions")
        self.control_ratio.setChecked(True)
        deform.addWidget(self.control_ratio)
        self.button(deform, "Transform selected dots", "open_with", self.transform_controls)
        self.button(deform, "Select all FFD dots", "select_all", self.select_all_controls)
        for label, icon, operation in (
            ("Mirror horizontal", "flip", "mirror_x"),
            ("Mirror vertical", "flip", "mirror_y"),
            ("Align X", "align_horizontal_center", "align_x"),
            ("Align Y", "align_vertical_center", "align_y"),
            ("Average from four corners", "grid_on", "average"),
            ("Align lattice to root", "center_focus_strong", "align_root"),
            ("Reset selected dots", "restart_alt", "reset"),
            ("Reset all dots", "restart_alt", "reset_all"),
        ):
            self.button(deform, label, icon, lambda _=False, op=operation: model.edit_controls(op))
        self.pin_button = self.button(
            deform,
            "Create pins from selection",
            "push_pin",
            lambda: model.run(lambda s: s.anchors(model.stage_id, set(model.selected))),
        )
        self.mask_weight = self.spin(0, 1, 1)
        form = QFormLayout()
        form.addRow("Selected vertex mask", self.mask_weight)
        deform.addLayout(form)
        self.button(
            deform,
            "Assign mask",
            "gradient",
            lambda: model.run(
                lambda s: s.mask(model.stage_id, set(model.selected), self.mask_weight.value())
            ),
        )
        self.button(deform, "Clear mask (affect all)", "layers_clear", self.clear_mask)
        hint = QLabel(
            "Stack evaluates top to bottom in object space. Drag field controls in the viewport; "
            "Ctrl selects several. Numeric fields and keys are in Motion."
        )
        hint.setWordWrap(True)
        deform.addWidget(hint)
        deform.addStretch()
        weights = self.page(tabs, "Weights")
        self.bones = QComboBox()
        self.bones.currentIndexChanged.connect(
            lambda: model.changed.emit() if not self._refreshing else None
        )
        weights.addWidget(self.bones)
        self.button(weights, "Bind & auto weight all bones", "device_hub", self.bind_skin)
        self.operation = QComboBox()
        self.operation.addItems(["add", "subtract", "smooth", "normalize"])
        self.radius, self.strength = self.spin(1, 2000, 100), self.spin(0, 1, 0.3)
        self.limit = QSpinBox()
        self.limit.setRange(1, 16)
        self.limit.setValue(4)
        form = QFormLayout()
        form.addRow("Brush operation", self.operation)
        form.addRow("Radius (scene px)", self.radius)
        form.addRow("Strength", self.strength)
        form.addRow("Influence cap", self.limit)
        weights.addLayout(form)
        self.heatmap = QCheckBox("Show selected bone influence")
        self.heatmap.setChecked(True)
        self.heatmap.toggled.connect(lambda: model.changed.emit())
        weights.addWidget(self.heatmap)
        self.button(
            weights,
            "Activate paint brush",
            "brush",
            lambda: self.tools.setCurrentIndex(self.tools.findData("paint")),
        )
        hint = QLabel(
            "Influence uses a neutral heatmap: dark = 0, white = 1. Strokes normalize and cap "
            "influences; protected vertices remain unchanged. Undo restores the whole stroke."
        )
        hint.setWordWrap(True)
        weights.addWidget(hint)
        weights.addStretch()
        motion = self.page(tabs, "Motion")
        self.auto_key = QCheckBox("Auto key edited values")
        self.auto_key.setToolTip(
            "Record mesh/control edits at the timeline playhead, preserving the initial pose."
        )
        self.auto_key.toggled.connect(model.set_auto_key)
        motion.addWidget(self.auto_key)
        self.properties = QComboBox()
        self.properties.currentIndexChanged.connect(self.refresh_value)
        motion.addWidget(self.properties)
        self.value = self.spin(-100000, 100000, 0)
        self.frame = self.spin(0, 1000000, 0)
        self.interpolation = QComboBox()
        self.interpolation.addItems(["linear", "step", "bezier"])
        form = QFormLayout()
        form.addRow("Value", self.value)
        form.addRow("Key frame", self.frame)
        form.addRow("Interpolation", self.interpolation)
        motion.addLayout(form)
        self.button(motion, "Apply value / auto key", "check", self.apply_value)
        self.button(motion, "Add / update key", "add", self.set_key)
        self.button(motion, "Delete key at frame", "delete", lambda: self.set_key(delete=True))
        self.keys = QListWidget()
        self.keys.setMaximumHeight(120)
        self.keys.currentRowChanged.connect(self.select_key)
        motion.addWidget(self.keys)
        self.button(motion, "Export deformation clip…", "file_upload", self.export_requested.emit)
        self.button(motion, "Reuse deformation clip…", "file_download", self.reuse_requested.emit)
        self.examples = QComboBox()
        self.examples.addItems(
            ["Bending", "Waving arm", "Character torso", "Squash and stretch", "Deforming prop"]
        )
        motion.addWidget(self.examples)
        self.button(
            motion,
            "Create example project",
            "auto_awesome",
            lambda: self.example_requested.emit(self.examples.currentText()),
        )
        motion.addStretch()
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setTextInteractionFlags(self.error.textInteractionFlags())
        self.error.setVisible(bool(model.error))
        outer.addWidget(self.error)
        for form_layout in self.findChildren(QFormLayout):
            form_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        for combo in self.findChildren(QComboBox):
            combo.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            combo.setMinimumContentsLength(4 if combo is self.division else 10)
        model.changed.connect(self.refresh)
        self.refresh()

    def button(
        self, layout: Any, label: str, icon: str, callback: Callable[..., Any]
    ) -> QPushButton:
        """Create an accessible Material button participating in shared theme icon refresh."""
        button = QPushButton(label)
        button.setIcon(self.icons.icon(icon))
        button.setProperty("materialIcon", icon)
        button.setToolTip(label)
        button.setAccessibleName(label)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    @staticmethod
    def spin(minimum: float, maximum: float, value: float) -> QDoubleSpinBox:
        """Build a bounded numeric field with subpixel precision and deferred editing."""
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(3)
        spin.setValue(value)
        spin.setKeyboardTracking(False)
        return spin

    @staticmethod
    def page(tabs: QTabWidget, title: str) -> QVBoxLayout:
        """Keep inspector forms scrollable at the application's minimum supported size."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        box = QVBoxLayout(content)
        box.setContentsMargins(8, 8, 8, 8)
        scroll.setWidget(content)
        tabs.addTab(scroll, title)
        return box

    def select_mesh(self) -> None:
        """Route artwork selection into the ViewModel without publishing model changes."""
        if not self._refreshing:
            self.model.select_mesh(self.meshes.currentData() or "")

    def change_tool(self) -> None:
        """Cancel an unfinished gesture when changing authoring tools."""
        self.model.tool = self.tools.currentData()
        self.model.transform_mode = "move"
        self.model.cancel_preview()

    def select_all(self) -> None:
        """Select the current tool's vertices or FFD/lattice/pin control points."""
        if self.model.tool == "control" and self.model.service and self.model.stage_id:
            stage = self.model.service.stage(self.model.stage_id)
            count = (
                len(lattice_controls(stage.parameters)[2])
                if stage.kind in ("ffd", "lattice")
                else len(stage.parameters.get("pins", {}))
            )
            self.model.controls = tuple(range(count))
            self.model.changed.emit()
        elif self.model.mesh:
            self.model.select(tuple(v.id for v in self.model.mesh.vertices))

    def connect_face(self) -> None:
        """Create a face only when exactly three vertices are selected."""
        if len(self.model.selected) != 3:
            self.model.error = "Select exactly three vertices to create a triangle."
            self.model.changed.emit()
        else:
            self.model.run(
                lambda s: s.connect_triangle(
                    self.model.mesh_id, cast(tuple[str, str, str], self.model.selected)
                )
            )

    def select_stage(self, index: int) -> None:
        """Choose one stable stage and reset field-control selection."""
        if not self._refreshing:
            stages = self.stack()
            self.model.stage_id = stages[index].id if 0 <= index < len(stages) else ""
            self.model.controls = ()
            self.model.changed.emit()

    def stack(self) -> list[Any]:
        """Return the currently selected mesh's ordered stage records."""
        return (
            sorted(
                (d for d in self.model.service.scene.deformers if d.owner_id == self.model.mesh_id),
                key=lambda d: d.order,
            )
            if self.model.service
            else []
        )

    def add_stage(self) -> None:
        """Append the selected preset and immediately select its editable field controls."""

        def add(service: Any) -> None:
            """Retain the created stable ID after the document refresh."""
            self.model.stage_id = service.add(
                self.model.mesh_id,
                deformation_presets()[self.presets.currentIndex()],
                columns=self.lattice_size.value(),
                rows=self.lattice_size.value(),
            )

        self.model.run(add)
        self.tools.setCurrentIndex(self.tools.findData("control"))
        self.mode_changed.emit(True)

    def activate_controls(self, *_: Any) -> None:
        """Enter the visible FFD tool when choosing Move, Scale or Rotate controls."""
        self.tabs.setCurrentIndex(1)
        self.tools.setCurrentIndex(self.tools.findData("control"))
        self.mode_changed.emit(True)
        scroll = self.tabs.widget(1)
        if isinstance(scroll, QScrollArea):
            scroll.ensureWidgetVisible(self.control_mode, 0, 8)

    def apply_ffd_strengths(self) -> None:
        """Multiply object-wide FFD strength by an independently editable stage intensity."""
        from rigora.application_services.ffd_motion import FfdMotionService

        def apply(service: Any) -> None:
            """Group the two strength updates into one reversible application command."""
            with service.document.command_group("Set FFD strengths"):
                FfdMotionService(service.document).object_strength(
                    self.model.mesh_id, self.ffd_object_strength.value()
                )
                service.parameters(self.model.stage_id, intensity=self.ffd_clip_strength.value())

        self.model.run(apply)

    def select_all_controls(self) -> None:
        """Select lattice dots independently of the previously active mesh selection mode."""
        self.activate_controls()
        self.select_all()

    def transform_controls(self) -> None:
        """Apply numeric move/rotate/scale around the selected dots' center in one undo step."""
        self.activate_controls()
        values = {
            k: field.value() / (100 if k.startswith("scale") else 1)
            for k, field in self.control_fields.items()
        }
        if self.control_ratio.isChecked():
            values["scale_y"] = values["scale_x"]
        self.model.edit_controls("transform", **values)

    def clear_mask(self) -> None:
        """Remove the optional vertex mask to restore uniform stage influence."""

        def clear(service: Any) -> None:
            """Preserve all other parameter values when removing the mask."""
            params = dict(service.stage(self.model.stage_id).parameters)
            params.pop("weights", None)
            service.update(self.model.stage_id, parameters=params)

        self.model.run(clear)

    def bind_skin(self) -> None:
        """Initialize a skin stage from all bones in the current scene."""
        self.model.run(
            lambda s: SkinService(s.document).bind(
                self.model.mesh_id,
                tuple(b.id for rig in s.scene.skeletons for b in rig.bones),
                limit=self.limit.value(),
            )
        )

    def target(self) -> tuple[str, str] | None:
        """Resolve the numeric property selected for base or key editing."""
        data = self.properties.currentData()
        return (str(data[0]), str(data[1])) if data else None

    def apply_value(self) -> None:
        """Commit the selected numeric property using the ViewModel's auto-key policy."""
        target = self.target()
        if target:
            self.model.edit_value(*target, self.value.value())

    def set_key(self, checked: bool = False, *, delete: bool = False) -> None:
        """Edit a common timeline key from explicit frame and value fields."""
        target = self.target()
        if target:
            self.model.run(
                lambda s: s.key(
                    *target,
                    self.frame.value(),
                    self.value.value(),
                    interpolation=cast(Any, self.interpolation.currentText()),
                    delete=delete,
                )
            )

    def select_key(self, index: int) -> None:
        """Load an existing key into editable fields without changing playback or authoring."""
        if not self._refreshing and 0 <= index < len(self._shown_keys):
            key = self._shown_keys[index]
            self.frame.setValue(key.frame)
            self.value.setValue(key.value)
            self.interpolation.setCurrentText(key.interpolation)

    def refresh_value(self) -> None:
        """Display numeric fields while keeping unsupported clips recoverable in the editor."""
        try:
            self._refresh_value()
        except ProjectError as error:
            self.error.setText(str(error))
            self.error.show()
            self.keys.clear()

    def _refresh_value(self) -> None:
        """Display the sampled numeric property and existing keys on the selected clip."""
        self._shown_keys = []
        target, service, document = self.target(), self.model.service, self.model.document
        if target and service and document:
            owner, path = target
            evaluator = document.animation.evaluator
            value = DeformationPlan(service.scene).base(owner, path)
            for track in evaluator.timeline.tracks if evaluator.timeline else ():
                if track.owner_id == owner and track.property_path == path:
                    self._shown_keys = list(track.keyframes)
                    from rigora.engine.sampling import CompiledTrack

                    sample = CompiledTrack(track).sample(document.animation.pose.frame)
                    if sample is not None:
                        value = sample
            self.value.setValue(value)
        with QSignalBlocker(self.keys):
            self.keys.clear()
            self.keys.addItems(
                [f"{k.frame:g}  ·  {k.value:g}  ·  {k.interpolation}" for k in self._shown_keys]
            )

    def refresh(self) -> None:
        """Rebuild stable-ID choices after selection, undo or tab activation without emitting
        edits.
        """
        self._refreshing = True
        model, service = self.model, self.model.service
        self.control_selection.setText(
            f"{len(model.controls)} dots selected · Ctrl-click / marquee"
        )
        for check, value in (
            (self.mode, model.active),
            (self.auto_key, model.auto_key),
        ):
            with QSignalBlocker(check):
                check.setChecked(value)
        self.meshes.clear()
        if service:
            for mesh in service.scene.meshes:
                self.meshes.addItem(mesh.name, mesh.id)
        self.meshes.setCurrentIndex(self.meshes.findData(model.mesh_id))
        self.selection.setText(
            f"{len(model.selected)} selected · "
            f"{len(model.mesh.vertices) if model.mesh else 0} vertices · "
            f"{len(model.mesh.triangles) if model.mesh else 0} triangles"
        )
        selected_ids = set(model.selected)
        self.subdivision.setEnabled(model.mesh is not None)
        subdivision = model.mesh.extra.get("subdivision", {}) if model.mesh else {}
        context = (model.document, model.mesh_id, tuple(sorted(subdivision.items())))
        if context != self._subdivision_context:
            self._subdivision_context = context
            self.division.setCurrentIndex(self.division.findData(subdivision.get("mode", "full")))
            self.density.setValue(subdivision.get("density", 4))
            self.alignment.setValue(subdivision.get("alignment", 1))
            self.expand.setValue(subdivision.get("expand", 0))
        vertices = [v for v in model.mesh.vertices if v.id in selected_ids] if model.mesh else []
        details = [
            f"{v.name}: ({v.x:.2f}, {v.y:.2f}), UV ({v.uv[0]:.3f}, {v.uv[1]:.3f})"
            for v in vertices[:3]
        ]
        if len(vertices) == 3:
            from rigora.domain.mesh_geometry import area

            details.append(
                f"Triangle area: {abs(area(*((v.x, v.y) for v in vertices))) / 2:.3f} px²"
            )
        self.details.setText("\n".join(details))
        self.pinned.setChecked(bool(vertices) and all(v.pinned for v in vertices))
        self.protected.setChecked(bool(vertices) and all(v.protected for v in vertices))
        self.stages.clear()
        stack = self.stack()
        for stage_item in stack:
            self.stages.addItem(
                QListWidgetItem(
                    self.icons.icon("visibility" if stage_item.enabled else "visibility_off"),
                    stage_item.name,
                )
            )
        self.stages.setCurrentRow(
            next((i for i, d in enumerate(stack) if d.id == model.stage_id), -1)
        )
        stage = next((d for d in stack if d.id == model.stage_id), None)
        self.ffd_clip_strength.setValue(stage.parameters.get("intensity", 1) if stage else 1)
        self.ffd_object_strength.setValue(
            model.mesh.extra.get("ffd_strength", 1) if model.mesh else 1
        )
        self.pin_button.setEnabled(stage is not None and stage.kind == "pin")
        self.enabled.setChecked(bool(stage and stage.enabled))
        self.enabled.setEnabled(stage is not None)
        bone = self.bones.currentData()
        self.bones.clear()
        if service:
            for rig in service.scene.skeletons:
                for item in rig.bones:
                    self.bones.addItem(item.name, item.id)
        self.bones.setCurrentIndex(max(0, self.bones.findData(bone)))
        selected = self.properties.currentData()
        self.properties.blockSignals(True)
        self.properties.clear()
        if model.selected:
            for axis in ("x", "y"):
                self.properties.addItem(f"Vertex {axis.upper()}", (model.selected[0], axis))
        if stage:
            fields: tuple[str, ...] = (
                "intensity",
                "amount",
                "x",
                "y",
                "rotation",
                "scale_x",
                "scale_y",
                "pivot_x",
                "pivot_y",
                "radius",
            )
            if stage.kind in ("ffd", "lattice", "skinning"):
                fields = ("intensity",)
            elif stage.kind == "pin":
                fields = ("intensity", "radius")
            elif stage.kind in ("bend", "bulge", "twist", "squash_stretch"):
                fields = ("intensity", "amount")
            for field in fields:
                if field in stage.parameters:
                    self.properties.addItem(
                        field.replace("_", " "), (stage.id, f"parameters.{field}")
                    )
            if stage.kind in ("ffd", "lattice"):
                try:
                    _, _, controls = lattice_controls(stage.parameters)
                except ProjectError:
                    controls = ()
                for index in model.controls or tuple(range(len(controls))):
                    for component in (0, 1):
                        self.properties.addItem(
                            f"Control {index + 1} {'XY'[component]}",
                            (stage.id, f"parameters.controls.{index}.{component}"),
                        )
            pins = stage.parameters.get("pins", {})
            for key in pins if isinstance(pins, Mapping) else ():
                for axis in ("x", "y", "strength"):
                    self.properties.addItem(
                        f"Pin {key[:5]} {axis}", (stage.id, f"parameters.pins.{key}.{axis}")
                    )
        self.properties.setCurrentIndex(
            next(
                (
                    i
                    for i in range(self.properties.count())
                    if self.properties.itemData(i) == selected
                ),
                0,
            )
        )
        self.properties.blockSignals(False)
        self.refresh_transport()
        self.error.setText(model.error)
        self.error.setVisible(bool(model.error))
        self._refreshing = False
        self.refresh_value()

    def refresh_transport(self) -> None:
        """Follow clip/frame changes without replacing a manually entered key time after an edit."""
        document = self.model.document
        if document is None:
            return
        try:
            pose = document.animation.pose
        except ProjectError:
            return
        context = (document.session_id, pose.clip_id, pose.frame)
        if context != self._frame_context:
            if not self.frame.hasFocus():
                self.frame.setValue(pose.frame)
            if not self.value.hasFocus():
                self.refresh_value()
            self._frame_context = context
