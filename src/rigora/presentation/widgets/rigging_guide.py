"""Modeless character-building guide backed by editable canonical scene records."""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rigora.application_services.rigging import RigService
from rigora.application_services.rigging_guide import PART_ROLES, RIG_TEMPLATES, RiggingGuideService
from rigora.domain.geometry import transform_point
from rigora.domain.project import ProjectError
from rigora.presentation.widgets.file_dialogs import choose_open_files, choose_save_file
from rigora.presentation.widgets.viewport import Viewport
from rigora.presentation.widgets.window_frame import CustomDialog

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


class RiggingGuideDialog(CustomDialog):
    """Guide character assembly while preserving access to ordinary stage tools."""

    def __init__(self, window: "MainWindow") -> None:
        """Build six reversible steps without storing an alternate character representation."""
        super().__init__(window, "Build a character")
        self.host, self.document = window, window.viewmodel.documents
        self.resize(930, 720)
        box = QVBoxLayout(self.content)
        info = QLabel(
            "Each step edits your real project and supports Undo. Return to earlier steps "
            "freely. Use the normal stage tools for precise adjustments, then reopen "
            "this guide from Rig → Build a character."
        )
        info.setWordWrap(True)
        box.addWidget(info)
        body = QHBoxLayout()
        box.addLayout(body, 1)
        self.steps = QListWidget()
        self.steps.addItems(
            [
                "1  Artwork & parts",
                "2  Skeleton",
                "3  Meshes",
                "4  Weights",
                "5  Test deformation",
                "6  Save template",
            ]
        )
        self.steps.setMaximumWidth(190)
        body.addWidget(self.steps)
        self.pages = QStackedWidget()
        body.addWidget(self.pages, 1)
        first = self.page(
            "Import separate PNG/SVG parts, or use existing artwork. Name the parts and "
            "choose roles. Use scene transforms to arrange separate imported parts."
        )
        first.addWidget(
            self.button("Import artwork parts…", "add_photo_alternate", self.import_parts)
        )
        self.parts = QTableWidget(0, 3)
        self.parts.setHorizontalHeaderLabels(["Use / part name", "Role", "Mesh"])
        self.parts.horizontalHeader().setStretchLastSection(True)
        first.addWidget(self.parts, 1)
        first.addWidget(self.button("Save part labels", "save", self.identify))
        second = self.page(
            "Choose a template and generate bones fitted to the selected artwork. "
            "Adjust local bone coordinates below before binding. Later rest-rig edits "
            "can affect existing skinning; use animation tools for poses."
        )
        form = QFormLayout()
        self.template, self.rigs = QComboBox(), QComboBox()
        self.template.addItems(list(RIG_TEMPLATES))
        self.size_factor = QDoubleSpinBox()
        self.size_factor.setRange(0.01, 100)
        self.size_factor.setValue(1)
        form.addRow("Template", self.template)
        form.addRow("Fit size multiplier", self.size_factor)
        form.addRow("Working skeleton", self.rigs)
        second.addLayout(form)
        second.addWidget(self.button("Generate & fit bones", "device_hub", self.generate_rig))
        self.bones = QTableWidget(0, 5)
        self.bones.setHorizontalHeaderLabels(["Bone", "Local X", "Local Y", "Rotation °", "Length"])
        self.bones.horizontalHeader().setStretchLastSection(True)
        second.addWidget(self.bones, 1)
        row = QHBoxLayout()
        row.addWidget(self.button("Save bone placement", "save", self.save_bones))
        row.addWidget(self.button("Edit bones on stage", "open_with", self.edit_bones))
        second.addLayout(row)
        third = self.page(
            "Generate an initial grid mesh for the selected artwork. Pristine guide meshes "
            "can be regenerated safely. Existing edits require the explicit replacement "
            "option; keep them to retain topology, weights and deformation keys."
        )
        self.columns, self.rows = QSpinBox(), QSpinBox()
        self.columns.setRange(1, 32)
        self.rows.setRange(1, 32)
        self.columns.setValue(6)
        self.rows.setValue(6)
        form = QFormLayout()
        form.addRow("Columns", self.columns)
        form.addRow("Rows", self.rows)
        third.addLayout(form)
        self.replace_meshes = QCheckBox("Replace existing mesh edits, weights and deformation keys")
        third.addWidget(self.replace_meshes)
        third.addWidget(self.button("Generate meshes", "grid_on", self.generate_meshes))
        third.addStretch()
        fourth = self.page(
            "Bind each artwork part to the complete rig for smooth deformation, or "
            "choose one bone for rigid parts. Afterwards paint weights on the stage "
            "with the existing brush, heatmap and normalization controls."
        )
        self.assignments = QTableWidget(0, 2)
        self.assignments.setHorizontalHeaderLabels(["Artwork part", "Bind to"])
        self.assignments.horizontalHeader().setStretchLastSection(True)
        fourth.addWidget(self.assignments, 1)
        fourth.addWidget(self.button("Bind & generate weights", "hub", self.bind_parts))
        self.paint_mesh = QComboBox()
        form = QFormLayout()
        form.addRow("Paint artwork", self.paint_mesh)
        fourth.addLayout(form)
        fourth.addWidget(self.button("Paint weights on stage", "brush", self.paint_weights))
        fifth = self.page(
            "Select a bone and change the test angle to inspect real mesh deformation. "
            "Testing adds no keys to your project. Reset preview before editing. "
            "Correct placement or weights in the earlier steps if needed."
        )
        self.test_bone = QComboBox()
        self.angle = QSlider(Qt.Orientation.Horizontal)
        self.angle.setRange(-90, 90)
        self.angle.setAccessibleName("Test bone rotation offset")
        fifth.addWidget(self.test_bone)
        fifth.addWidget(self.angle)
        fifth.addWidget(self.button("Preview deformation", "visibility", self.preview))
        fifth.addWidget(self.button("Reset preview", "restart_alt", self.reset_preview))
        self.test_viewport = Viewport()
        self.test_viewport.setAccessibleName("Character deformation test preview")
        self.test_viewport.setAcceptDrops(False)
        self.test_viewport.artwork = window.viewport.artwork
        self.test_viewport.node_labels = False
        self.test_viewport.scene_hint = "DEFORMATION TEST"
        self.test_viewport.grid_visible = False
        fifth.addWidget(self.test_viewport, 1)
        sixth = self.page(
            "Save the assembled current scene as a portable .rigpack template. It includes "
            "original embedded artwork, editable bones, meshes, weights and motions. "
            "Install it from Content → Install pack, then drag the scene template onto "
            "the stage to reuse it with fresh identities."
        )
        form = QFormLayout()
        self.name, self.author, self.license = (
            QLineEdit("My character"),
            QLineEdit("eManF"),
            QLineEdit("All rights reserved"),
        )
        for label, widget in (
            ("Template name", self.name),
            ("Author", self.author),
            ("License", self.license),
        ):
            form.addRow(label, widget)
        sixth.addLayout(form)
        self.overwrite = QCheckBox("Allow replacing the selected output file")
        sixth.addWidget(self.overwrite)
        sixth.addWidget(self.button("Save reusable scene template…", "save_alt", self.share))
        sixth.addStretch()
        self.status = QLabel()
        self.status.setWordWrap(True)
        box.addWidget(self.status)
        row = QHBoxLayout()
        row.addWidget(
            self.button(
                "Back",
                "chevron_left",
                lambda: self.steps.setCurrentRow(max(0, self.steps.currentRow() - 1)),
            )
        )
        row.addStretch()
        row.addWidget(self.button("Refresh project data", "refresh", self.refresh))
        row.addWidget(
            self.button(
                "Next",
                "chevron_right",
                lambda: self.steps.setCurrentRow(min(5, self.steps.currentRow() + 1)),
            )
        )
        box.addLayout(row)
        self.steps.currentRowChanged.connect(self.change_step)
        self.rigs.currentIndexChanged.connect(self.load_bones)
        self.angle.valueChanged.connect(self.preview)
        self.test_bone.currentIndexChanged.connect(lambda: self.angle.setValue(0))
        self.finished.connect(lambda _: window.viewmodel.animation_editor.clear_key_preview())
        self.refresh()
        self.steps.setCurrentRow(0)

    def page(self, text: str) -> QVBoxLayout:
        """Create a focused step with readable context and flexible content space."""
        widget = QWidget()
        box = QVBoxLayout(widget)
        label = QLabel(text)
        label.setWordWrap(True)
        box.addWidget(label)
        self.pages.addWidget(widget)
        return box

    def button(self, text: str, icon: str, action: Callable[[], None]) -> QPushButton:
        """Build an accessible command using the bundled Material icon system."""
        button = QPushButton(self.host.icons.icon(icon), text)
        button.setProperty("materialIcon", icon)
        button.clicked.connect(action)
        return button

    def run(self, action: Callable[[RiggingGuideService], object]) -> None:
        """Route one guide step through the shared ViewModel refresh and error handling."""

        def operation(_: object) -> None:
            """Validate document ownership before invoking a canonical guide command."""
            if self.host.viewmodel.documents is not self.document:
                raise ProjectError(
                    "Return to the original project or open a new guide for this tab."
                )
            action(RiggingGuideService(self.document))

        self.host.viewmodel.animation_editor.run(operation)
        self.status.setText(
            self.host.viewmodel.animation_editor.error
            or "Step saved. All generated data remains editable."
        )

    def mesh_ids(self) -> tuple[str, ...]:
        """Collect checked artwork identities from the part list."""
        result = []
        for row in range(self.parts.rowCount()):
            item, identity = self.parts.item(row, 0), self.parts.item(row, 2)
            if item and identity and item.checkState() == Qt.CheckState.Checked:
                result.append(str(identity.data(Qt.ItemDataRole.UserRole)))
        return tuple(result)

    def refresh(self) -> None:
        """Rebuild guide choices from actual scene content after imports, undo or stage edits."""
        scene = RiggingGuideService(self.document).scene
        selected = set(self.mesh_ids()) if self.parts.rowCount() else None
        self.parts.setRowCount(len(scene.meshes))
        self.paint_mesh.clear()
        for row, mesh in enumerate(scene.meshes):
            obj = next((o for o in scene.objects if o.id == mesh.object_id), None)
            if not obj:
                continue
            item = QTableWidgetItem(obj.name)
            item.setCheckState(
                Qt.CheckState.Checked
                if selected is None or mesh.id in selected
                else Qt.CheckState.Unchecked
            )
            item.setData(Qt.ItemDataRole.UserRole, obj.id)
            self.parts.setItem(row, 0, item)
            role = QComboBox()
            role.addItems(list(PART_ROLES))
            role.setCurrentText(str(obj.extra.get("character_part", "Artwork")))
            self.parts.setCellWidget(row, 1, role)
            identity = QTableWidgetItem(mesh.name)
            identity.setData(Qt.ItemDataRole.UserRole, mesh.id)
            identity.setFlags(identity.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.parts.setItem(row, 2, identity)
            self.paint_mesh.addItem(obj.name, mesh.id)
        previous = self.rigs.currentData()
        self.rigs.blockSignals(True)
        self.rigs.clear()
        for rig in scene.skeletons:
            self.rigs.addItem(rig.name, rig.id)
        self.rigs.setCurrentIndex(max(0, self.rigs.findData(previous)))
        self.rigs.blockSignals(False)
        self.load_bones()

    def change_step(self, index: int) -> None:
        """Show one guide step and refresh binding choices after part selection changes."""
        self.host.viewmodel.animation_editor.clear_key_preview()
        self.pages.setCurrentIndex(index)
        if index == 3:
            self.load_bones()

    def load_bones(self) -> None:
        """Populate editable local bone fields and part binding choices for the selected rig."""
        scene = RiggingGuideService(self.document).scene
        rig = next((r for r in scene.skeletons if r.id == self.rigs.currentData()), None)
        self.bones.setRowCount(len(rig.bones) if rig else 0)
        self.test_bone.clear()
        for row, bone in enumerate(rig.bones if rig else ()):
            item = QTableWidgetItem(bone.name)
            item.setData(Qt.ItemDataRole.UserRole, bone.id)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.bones.setItem(row, 0, item)
            self.test_bone.addItem(bone.name, bone.id)
            for column, value in enumerate(
                (bone.transform.x, bone.transform.y, bone.transform.rotation, bone.length), 1
            ):
                field = QDoubleSpinBox()
                field.setRange(0 if column == 4 else -1e6, 1e6)
                field.setDecimals(3)
                field.setValue(value)
                self.bones.setCellWidget(row, column, field)
        meshes = [m for m in scene.meshes if m.id in self.mesh_ids()]
        self.assignments.setRowCount(len(meshes))
        for row, mesh in enumerate(meshes):
            item = QTableWidgetItem(mesh.name)
            item.setData(Qt.ItemDataRole.UserRole, mesh.id)
            self.assignments.setItem(row, 0, item)
            combo = QComboBox()
            combo.addItem("Auto weights · complete rig", "")
            for bone in rig.bones if rig else ():
                combo.addItem(bone.name, bone.id)
            self.assignments.setCellWidget(row, 1, combo)

    def import_parts(self) -> None:
        """Import selected artwork into the project and add it to the editable parts table."""
        files = choose_open_files(
            self, "Import character parts", "", "Artwork (*.svg *.png *.jpg *.jpeg *.webp)"
        )
        if files:
            self.run(lambda s: s.import_parts(tuple(Path(path) for path in files)) and None)
            self.parts.setRowCount(0)
            self.refresh()

    def identify(self) -> None:
        """Store user part names and roles through one validated scene command."""
        values = {}
        for row in range(self.parts.rowCount()):
            item, role = self.parts.item(row, 0), self.parts.cellWidget(row, 1)
            assert item is not None and isinstance(role, QComboBox)
            values[str(item.data(Qt.ItemDataRole.UserRole))] = item.text(), role.currentText()
        self.run(lambda s: s.identify(values))

    def generate_rig(self) -> None:
        """Create a fitted rig and select it as the guide's working skeleton."""
        result = []
        self.run(
            lambda s: result.append(
                s.generate_rig(
                    self.template.currentText(), self.mesh_ids(), scale=self.size_factor.value()
                )
            )
        )
        self.refresh()
        if result:
            self.rigs.setCurrentIndex(self.rigs.findData(result[0]))
            self.host.rig_workspace.frame_rig()

    def save_bones(self) -> None:
        """Save edited local placement fields in one grouped rig command."""

        def operation(service: RiggingGuideService) -> None:
            """Apply validated local coordinates while preserving bone identities and parenting."""
            with self.document.command_group("Place character bones"):
                rig = RigService(self.document)
                for row in range(self.bones.rowCount()):
                    item = self.bones.item(row, 0)
                    assert item is not None
                    key = str(item.data(Qt.ItemDataRole.UserRole))
                    fields = [self.bones.cellWidget(row, column) for column in range(1, 5)]
                    assert all(isinstance(field, QDoubleSpinBox) for field in fields)
                    values = [
                        field.value() for field in fields if isinstance(field, QDoubleSpinBox)
                    ]
                    bone = rig.bone(key)
                    rig.update(
                        key,
                        transform=replace(
                            bone.transform, x=values[0], y=values[1], rotation=values[2]
                        ),
                        length=values[3],
                    )

        self.run(operation)

    def edit_bones(self) -> None:
        """Hand off to ordinary stage bone tools while keeping guide state available to reopen."""
        self.reset_preview()
        self.host.rig_workspace.set_mode(True)
        self.host.viewmodel.rig.tool = "move"
        if self.test_bone.currentData():
            self.host.viewmodel.rig.select(str(self.test_bone.currentData()))
        self.host.viewmodel.rig.changed.emit()
        self.hide()

    def generate_meshes(self) -> None:
        """Generate selected initial grids while retaining edits unless replacement is explicit."""
        self.run(
            lambda s: s.generate_meshes(
                self.mesh_ids(),
                self.columns.value(),
                self.rows.value(),
                replace_edits=self.replace_meshes.isChecked(),
            )
        )

    def bind_parts(self) -> None:
        """Bind each checked mesh to all rig bones or an explicit rigid part assignment."""
        assignments = {}
        for row in range(self.assignments.rowCount()):
            combo = self.assignments.cellWidget(row, 1)
            assert isinstance(combo, QComboBox)
            if key := combo.currentData():
                item = self.assignments.item(row, 0)
                assert item is not None
                assignments[str(item.data(Qt.ItemDataRole.UserRole))] = str(key)
        self.run(lambda s: s.bind_parts(str(self.rigs.currentData()), self.mesh_ids(), assignments))

    def paint_weights(self) -> None:
        """Activate the existing weight brush and heatmap for the chosen artwork on the stage."""
        self.reset_preview()
        key = self.paint_mesh.currentData()
        if not key:
            self.status.setText("Import and bind artwork before painting weights.")
            return
        self.host.viewmodel.mesh.select_mesh(str(key))
        self.host.mesh_workspace.activate_tool("paint")
        self.host.mesh_panel.tabs.setCurrentIndex(2)
        self.hide()
        self.host.statusBar().showMessage(
            "Paint weights on the stage. Reopen Rig → Build a character to continue.", 10000
        )

    def preview(self) -> None:
        """Evaluate a disposable test deflection without altering real bone poses or keys."""
        try:
            if self.host.viewmodel.documents is not self.document:
                raise ProjectError("Return to the guide's original project tab.")
            pose = RiggingGuideService(self.document).test_pose(
                str(self.test_bone.currentData()), self.angle.value()
            )
            editor = self.host.viewmodel.animation_editor
            editor.preview_pose = pose
            editor.key_preview_changed.emit()
            self.test_viewport.set_scene(RiggingGuideService(self.document).scene.settings)
            self.test_viewport.set_pose(pose)
            points = [
                transform_point(pose.nodes[m.object_id].world_matrix, *p)
                for m in pose.meshes.values()
                if m.object_id is not None and m.object_id in pose.nodes
                for p in m.positions
            ]
            if points:
                xs, ys = [p[0] for p in points], [p[1] for p in points]
                self.test_viewport.zoom = min(
                    8,
                    max(
                        0.001,
                        min(
                            (self.test_viewport.width() - 60) / max(1, max(xs) - min(xs)),
                            (self.test_viewport.height() - 60) / max(1, max(ys) - min(ys)),
                        ),
                    ),
                )
                self.test_viewport.offset = QPointF(
                    self.test_viewport.width() / 2
                    - (min(xs) + max(xs)) / 2 * self.test_viewport.zoom,
                    self.test_viewport.height() / 2
                    - (min(ys) + max(ys)) / 2 * self.test_viewport.zoom,
                )
            self.status.setText(
                f"Test angle {self.angle.value()}° · {len(pose.meshes)} meshes · "
                f"{len(pose.warnings)} warnings"
            )
        except ProjectError as error:
            self.status.setText(str(error))

    def reset_preview(self) -> None:
        """Restore the real pose in both stage previews without modifying the timeline."""
        self.host.viewmodel.animation_editor.clear_key_preview()
        if self.document.project:
            self.test_viewport.set_pose(self.document.animation.pose)

    def share(self) -> None:
        """Save a portable scene template with explicit output overwrite control."""
        path, _ = choose_save_file(
            self, "Save character template", "My character.rigpack", "Rigora packs (*.rigpack)"
        )
        if path:
            self.run(
                lambda s: s.share(
                    Path(path),
                    name=self.name.text(),
                    author=self.author.text(),
                    license=self.license.text(),
                    overwrite=self.overwrite.isChecked(),
                )
            )
