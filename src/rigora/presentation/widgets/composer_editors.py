"""Modeless bone and spring editors over the canonical rig and dynamics services."""

import time
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QElapsedTimer, QEvent, QObject, QSignalBlocker, Qt, QThreadPool, QTimer
from PySide6.QtGui import QHideEvent, QKeyEvent, QMouseEvent, QShowEvent, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rigora.application_services.documents import DocumentService
from rigora.application_services.dynamics import SPRING_PRESETS, DynamicsService
from rigora.application_services.meshes import MeshService
from rigora.application_services.rigging import RigService
from rigora.application_services.skinning import SkinService
from rigora.domain.project import ProjectError
from rigora.presentation.viewmodels.content_library import LibraryJob
from rigora.presentation.widgets.artwork_pins import ArtworkPins
from rigora.presentation.widgets.message_dialogs import ask_question
from rigora.presentation.widgets.scene_tree import NameDelegate
from rigora.presentation.widgets.spring_preset_preview import PRESET_HELP, SpringPresetPreview
from rigora.presentation.widgets.window_frame import CustomDialog

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


def slider_field(field: QSpinBox | QDoubleSpinBox) -> QWidget:
    """Pair an integer-range slider with a precise, keyboard-accessible numeric control."""
    row = QWidget()
    row.setObjectName("SliderField")
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(int(field.minimum()), int(field.maximum()))
    slider.setValue(round(field.value()))
    slider.valueChanged.connect(field.setValue)

    def update_slider(value: float) -> None:
        """Reflect precise typed values without rounding them back through the slider."""
        with QSignalBlocker(slider):
            slider.setValue(round(value))

    field.valueChanged.connect(update_slider)
    slider.setAccessibleName(field.accessibleName())
    field.setMaximumWidth(90)
    layout.addWidget(slider, 1)
    layout.addWidget(field)
    return row


class BoneEditor(CustomDialog):
    """Expose rig operations, image-area pins and source-aware triangular subdivision."""

    status: QLabel

    def __init__(self, window: "MainWindow") -> None:
        """Use existing undoable rig commands and the existing mesh regeneration confirmation."""
        super().__init__(window, "Bone Editor")
        self.host, self.document = window, window.viewmodel.documents
        self.subdivision_job: LibraryJob | None = None
        self.prepared: tuple[DocumentService, object, tuple[object, ...]] | None = None
        self.apply_result = False
        self.resize(380, 820)
        outer = QVBoxLayout(self.content)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        box = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll)
        self.selection_label = QLabel("Select bones on the stage or in Scene.")
        box.addWidget(self.selection_label)
        self.artwork = QComboBox()
        self.artwork.setAccessibleName("Artwork to rig")
        self.artwork.currentIndexChanged.connect(self.select_artwork)
        box.addWidget(self.artwork)
        self.auto_bind = QCheckBox("Auto bind artwork while drawing")
        self.auto_bind.setChecked(window.viewmodel.rig.auto_bind_artwork)
        self.auto_bind.setToolTip(
            "Draw bones over the chosen image to build a deformable image rig automatically. "
            "Explicitly unbound parts stay unbound until you use Bind."
        )
        self.auto_bind.toggled.connect(
            lambda enabled: setattr(window.viewmodel.rig, "auto_bind_artwork", enabled)
        )
        box.addWidget(self.auto_bind)
        bind = QPushButton("Attach / reattach image to selected rig")
        bind.clicked.connect(self.bind_artwork)
        box.addWidget(bind)
        self.rigid_attachment = QCheckBox("Rigid attachment to selected bone")
        box.addWidget(self.rigid_attachment)
        self.bone_buttons: dict[str, QPushButton] = {}
        tools = QGroupBox("Bone tools")
        grid = QGridLayout(tools)
        for index, (label, callback) in enumerate(
            (
                ("Add bone", self.draw_bone),
                ("Add pin", self.add_pin),
                ("Release pin", self.release_pin),
                ("Insert joint", lambda: self.selected_action("insert")),
                ("Delete bones", lambda: self.selected_action("delete")),
                ("Mirror branch", lambda: self.selected_action("mirror")),
                ("Duplicate branch", self.duplicate),
                ("Reset preview", window.viewmodel.rig.cancel_preview),
                ("Preview / pose", self.preview),
            )
        ):
            button = QPushButton(label)
            button.setCheckable(label in ("Add bone", "Add pin"))
            button.clicked.connect(callback)
            self.bone_buttons[label] = button
            grid.addWidget(button, index // 2, index % 2)
        box.addWidget(tools)
        form = QFormLayout()
        self.parent_bone = QComboBox()
        self.parent_bone.setAccessibleName("Connect selected bone to parent")
        form.addRow("Connect to", self.parent_bone)
        connect = QPushButton("Connect / reparent")
        connect.clicked.connect(self.connect_bone)
        self.bone_buttons["Connect / reparent"] = connect
        form.addRow(connect)
        box.addLayout(form)
        self.pins = ArtworkPins(window, self)
        self.pin_radius = self.pins.radius
        self.pin_radius.valueChanged.connect(
            lambda value: setattr(window.mesh_workspace.interaction, "pin_radius", value)
        )
        box.addWidget(self.pins)
        subdivision = QGroupBox("Subdivision")
        sub = QFormLayout(subdivision)
        self.wireframe = QCheckBox("Show wireframe")
        self.wireframe.setChecked(window.viewport.mesh_wireframe)
        self.wireframe.toggled.connect(self.show_wireframe)
        sub.addRow(self.wireframe)
        self.subdivision_controls = QWidget()
        sub.addRow(self.subdivision_controls)
        sub = QFormLayout(self.subdivision_controls)
        sub.setContentsMargins(0, 0, 0, 0)
        self.subdivision_controls.setEnabled(self.wireframe.isChecked())
        self.division_type = QComboBox()
        for label in ("Full", "Mask", "Grid"):
            self.division_type.addItem(label, label.lower())
        sub.addRow("Division type", self.division_type)
        self.density = QSpinBox()
        self.density.setRange(1, 10)
        self.density.setValue(4)
        sub.addRow("Density", slider_field(self.density))
        self.alignment = QSpinBox()
        self.alignment.setRange(0, 10)
        self.alignment.setValue(1)
        sub.addRow("Alignment", slider_field(self.alignment))
        self.expand = QDoubleSpinBox()
        self.expand.setRange(0, 100)
        self.expand.setSuffix(" px")
        sub.addRow("Expand", slider_field(self.expand))
        self.all_layers = QCheckBox("Affect all artwork layers")
        sub.addRow(self.all_layers)
        self.division_type.currentIndexChanged.connect(self.subdivision_state)
        self.subdivision_state()
        self.preview_subdivision = QCheckBox("Live subdivision preview")
        self.preview_subdivision.setChecked(True)
        sub.addRow(self.preview_subdivision)
        regenerate = QPushButton("Apply subdivision…")
        regenerate.clicked.connect(self.regenerate)
        sub.addRow(regenerate)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setAccessibleName("Subdivision generation progress")
        sub.addRow(self.progress)
        box.addWidget(subdivision)
        self.status = QLabel(
            "Add pin: click bound artwork. Select a bone to attach the region; "
            "Object root holds the region while bones pose and follows the whole Object."
        )
        self.status.setWordWrap(True)
        box.addWidget(self.status)
        box.addStretch()
        mesh = window.viewmodel.mesh.mesh
        if mesh:
            subdivision = mesh.extra.get("subdivision", {})
            mode_index = self.division_type.findData(subdivision.get("mode", "full"))
            self.division_type.setCurrentIndex(max(0, mode_index))
            self.density.setValue(subdivision.get("density", subdivision.get("columns", 4)))
            self.alignment.setValue(subdivision.get("alignment", 1))
            self.expand.setValue(subdivision.get("expand", 0))
        window.viewmodel.rig.changed.connect(self.refresh)
        window.viewmodel.mesh.changed.connect(self.refresh_tools)
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(160)
        self.preview_timer.timeout.connect(lambda: self.generate_subdivision(False))
        self.preview_subdivision.toggled.connect(self.queue_preview)
        for field in (self.density, self.alignment, self.expand):
            field.setKeyboardTracking(False)
            field.valueChanged.connect(self.queue_preview)
        self.division_type.currentIndexChanged.connect(self.queue_preview)
        self.all_layers.toggled.connect(self.queue_preview)
        window.viewmodel.changed.connect(self.invalidate_preview)
        window.viewport.installEventFilter(self)
        self.refresh()

    def check(self) -> None:
        """Prevent a modeless editor from mutating a different project tab."""
        if self.document is not self.host.viewmodel.documents or self.document.project is None:
            raise ProjectError("Reopen Bone Editor for the active project.")

    def refresh(self) -> None:
        """Keep parent candidates current without losing the user's chosen target."""
        if self.document is not self.host.viewmodel.documents:
            return
        self.refresh_tools()
        selected_bones = self.host.viewmodel.rig.selected
        mesh_id = self.host.viewmodel.mesh.mesh_id
        with QSignalBlocker(self.artwork):
            self.artwork.clear()
            if self.document.project:
                for mesh in self.document.scene.meshes:
                    self.artwork.addItem(mesh.name, mesh.id)
                self.artwork.setCurrentIndex(max(0, self.artwork.findData(mesh_id)))
        self.selection_label.setText(
            f"{len(selected_bones)} bones selected"
            if selected_bones
            else "Select bones on the stage or in Scene."
        )
        for label, button in self.bone_buttons.items():
            if label not in (
                "Add bone",
                "Add pin",
                "Release pin",
                "Reset preview",
                "Preview / pose",
            ):
                button.setEnabled(bool(selected_bones))
        selected = self.parent_bone.currentData()
        with QSignalBlocker(self.parent_bone):
            self.parent_bone.clear()
            self.parent_bone.addItem("Scene root", None)
            if self.document.project:
                for rig in DynamicsService(self.document).scene.skeletons:
                    for bone in rig.bones:
                        self.parent_bone.addItem(bone.name, bone.id)
            self.parent_bone.setCurrentIndex(max(0, self.parent_bone.findData(selected)))

    def refresh_tools(self) -> None:
        """Synchronize mode buttons without rebuilding bone/image lists during mesh gestures."""
        if self.document is not self.host.viewmodel.documents:
            return
        rig_model, mesh_model = self.host.viewmodel.rig, self.host.viewmodel.mesh
        if mesh_model.error:
            self.status.setText(mesh_model.error)
        self.bone_buttons["Add bone"].setChecked(rig_model.active and rig_model.tool == "draw")
        self.bone_buttons["Add pin"].setChecked(mesh_model.active and mesh_model.tool == "area_pin")
        index = self.artwork.findData(mesh_model.mesh_id)
        if index >= 0 and index != self.artwork.currentIndex():
            with QSignalBlocker(self.artwork):
                self.artwork.setCurrentIndex(index)

    def select_artwork(self) -> None:
        """Keep the image picker and the shared mesh inspector on the same artwork instance."""
        key = self.artwork.currentData()
        if key:
            self.clear_preview()
            self.host.viewmodel.mesh.select_mesh(key)

    def draw_bone(self) -> None:
        """Toggle bone creation independently of the editor's visibility."""
        self.check()
        self.preview_subdivision.setChecked(False)
        self.clear_preview()
        self.pins.editable = False
        self.host.toggle_bone_tool()

    def bind_artwork(self) -> None:
        """Auto-weight the current image to the selected skeleton through the shared service."""
        self.check()
        assert self.document.project is not None
        self.preview_subdivision.setChecked(False)
        rigs = self.document.scene.skeletons
        selected = set(self.host.viewmodel.rig.selected)
        candidates = [rig for rig in rigs if any(b.id in selected for b in rig.bones)]
        if not selected and len(rigs) == 1:
            candidates = list(rigs)
        if len(candidates) != 1 or not candidates[0].bones or not self.host.viewmodel.mesh.mesh_id:
            self.status.setText("Choose an image and select a bone from one skeleton first.")
            return
        self.clear_preview()
        model = self.host.viewmodel.mesh
        from rigora.application_services.image_rigging import ImageRigService

        bone = next((b for b in candidates[0].bones if b.id in selected), candidates[0].bones[0])
        model.run(
            lambda _: ImageRigService(self.document).bind_image(
                model.mesh_id, bone.id, rigid=self.rigid_attachment.isChecked()
            )
        )
        self.status.setText(
            model.error
            or "Image bound. Use Select & transform to pose; Chain (FK) carries children."
        )

    def add_pin(self) -> None:
        """Enter an image click tool with an explicit selected-bone or character-root anchor."""
        self.check()
        self.preview_subdivision.setChecked(False)
        self.clear_preview()
        if self.host.viewmodel.mesh.active and self.host.viewmodel.mesh.tool == "area_pin":
            self.host.navigate()
            return
        selected = self.host.viewmodel.rig.selected
        key = self.artwork.currentData()
        if key:
            self.host.viewmodel.mesh.select_mesh(key)
        if self.host.viewmodel.mesh.mesh is None:
            self.refresh_tools()
            self.status.setText(
                "Pins anchor artwork. Add an image or shape, then attach it to bones "
                "before placing pins."
            )
            return
        interaction = self.host.mesh_workspace.interaction
        interaction.pin_bone = selected[0] if selected else None
        interaction.pin_radius = self.pin_radius.value()
        self.pins.editable = True
        self.pins.setEnabled(True)
        self.pins.selected = ()
        self.pins.target.setCurrentIndex(
            max(0, self.pins.target.findData(selected[0] if selected else None))
        )
        self.host.mesh_workspace.activate_tool("area_pin")
        self.host.viewport.pan_tool = False
        self.status.setText(
            "Click bound artwork to place pins. Click a pin to select, Ctrl-click to "
            "select several, drag to reposition, or press Delete to release."
        )

    def release_pin(self) -> None:
        """Release image-area anchors without deleting their vertices or skinning weights."""
        self.check()
        if self.pins.selected:
            self.pins.remove()
            return
        model = self.host.viewmodel.mesh
        model.run(
            lambda _: SkinService(self.document).remove_area_pins(model.mesh_id, model.selected)
        )
        self.status.setText(model.error or "Image anchors released.")

    def selected_action(self, name: str) -> None:
        """Route existing insert/reduce operations through their validated implementation."""
        self.check()
        self.host.rig_panel.selected_action(name)
        self.status.setText(
            self.host.viewmodel.rig.error or "Bone edit complete. Undo is available."
        )

    def duplicate(self) -> None:
        """Copy selected outermost branches; sources and skin bindings remain independent."""
        self.check()
        model = self.host.viewmodel.rig
        if not model.selected:
            self.status.setText("Select a branch to duplicate.")
            return

        def apply(service: RigService) -> None:
            """Copy selected outermost branches together without duplicating nested selections."""
            selected = set(model.selected)
            roots = []
            for key in model.selected:
                parent = service.bone(key).parent_id
                while parent and parent not in selected:
                    parent = service.bone(parent).parent_id
                if parent is None:
                    roots.append(key)
            with self.document.command_group("Duplicate selected branches"):
                for key in roots:
                    service.duplicate(key)

        model.run(apply)
        self.status.setText(
            model.error or "Branches copied at the same position. Move to separate."
        )

    def connect_bone(self) -> None:
        """Connect selected bones using the existing keep-world hierarchy operation."""
        self.check()
        model = self.host.viewmodel.rig

        def apply(service: RigService) -> None:
            """Reparent selected bones to the chosen parent within one reversible command."""
            with self.document.command_group("Connect selected bones"):
                for key in model.selected:
                    service.reparent(key, self.parent_bone.currentData())

        model.run(apply)
        self.status.setText(model.error or "Connection updated; Undo is available.")

    def preview(self) -> None:
        """Activate root-anchored posing while leaving the timeline visible."""
        self.check()
        self.preview_subdivision.setChecked(False)
        self.clear_preview()
        self.pins.editable = False
        self.pins.setEnabled(False)
        self.pins.drag = None
        self.host.set_composer_target("bone_only")
        self.host.viewmodel.rig.set_tool("select")

    def show_wireframe(self, enabled: bool) -> None:
        """Toggle a transient mesh overlay without changing authoring data."""
        self.host.set_viewport_wireframe(enabled)
        self.sync_subdivision_controls()

    def sync_subdivision_controls(self) -> None:
        """Gate subdivision editing and live previews with the shared wireframe toggle."""
        self.subdivision_controls.setEnabled(self.wireframe.isChecked())
        self.queue_preview()

    def regenerate(self) -> None:
        """Prepare selected/all source topology with explicit loss disclosure and one undo step."""
        self.check()
        model = self.host.viewmodel.mesh
        if not model.mesh:
            self.status.setText("Select artwork before subdividing.")
            return
        assert model.service is not None
        if (
            ask_question(
                self,
                "Subdivide artwork?",
                "Replace mesh edits, vertex keys and topology-dependent deformers? "
                "Skin bindings and interpolated weights are preserved. Undo is available.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.generate_subdivision(True)

    def subdivision_signature(self) -> tuple[object, ...]:
        """Identify target layers and controls without capturing mutable GUI widgets."""
        model = self.host.viewmodel.mesh
        assert model.service is not None
        keys = (
            tuple(m.id for m in model.service.scene.meshes)
            if self.all_layers.isChecked()
            else (model.mesh_id,)
        )
        return (
            keys,
            self.division_type.currentData(),
            self.density.value(),
            self.alignment.value(),
            self.expand.value(),
        )

    def queue_preview(self) -> None:
        """Coalesce slider drags; preview never creates authored edits or history entries."""
        if self.wireframe.isChecked() and self.preview_subdivision.isChecked():
            if not self.preview_timer.isActive():
                self.preview_timer.start()
        else:
            self.preview_timer.stop()
            self.clear_preview()

    def clear_preview(self) -> None:
        """Restore normal rendering while retaining a reusable prepared result when valid."""
        self.host.viewport.subdivision_pose = None
        self.host.viewport.update()

    def invalidate_preview(self) -> None:
        """Discard a preview after an authoring edit or project-tab change."""
        if self.prepared and (
            self.document.project is not self.prepared[1]
            or self.document is not self.host.viewmodel.documents
        ):
            self.prepared = None
            self.clear_preview()

    def generate_subdivision(self, apply: bool) -> None:
        """Reuse prepared topology or run one background generation at the latest settings."""
        if not apply and not self.wireframe.isChecked():
            return
        if self.subdivision_job is not None:
            self.apply_result |= apply
            return
        if not self.host.viewmodel.mesh.mesh or self.document is not self.host.viewmodel.documents:
            return
        signature = self.subdivision_signature()
        self.apply_result = apply
        if (
            self.prepared
            and self.prepared[1] is self.document.project
            and self.prepared[2] == signature
        ):
            self.finish_subdivision(self.prepared)
            return
        keys, mode, density, alignment, expand = signature
        assert isinstance(keys, tuple) and isinstance(mode, str) and isinstance(density, int)
        assert isinstance(alignment, int) and isinstance(expand, float)
        scratch, baseline = self.document.fork(), self.document.project
        job: LibraryJob

        def prepare() -> tuple[DocumentService, object, tuple[object, ...]]:
            """Compute alpha contours and topology on a scratch document in the worker."""
            MeshService(scratch).subdivide(
                keys,
                mode=mode,
                density=density,
                alignment=alignment,
                expand=expand,
                discard_edits=True,
                progress=lambda value: job.deliver("progress", value),
            )
            return scratch, baseline, signature

        job = LibraryJob(prepare)
        self.subdivision_job = job
        job.signals.done.connect(self.finish_subdivision)
        job.signals.failed.connect(self.fail_subdivision)
        job.signals.progress.connect(self.progress.setValue)
        self.progress.setValue(0)
        QThreadPool.globalInstance().start(job)
        self.status.setText("Generating subdivision in the background…")

    def finish_subdivision(
        self, result: tuple[DocumentService, object, tuple[object, ...]]
    ) -> None:
        """Adopt worker geometry once only if the originating tab and revision still match."""
        self.subdivision_job = None
        if not self.isVisible():
            return
        scratch, baseline, signature = result
        assert scratch.project is not None
        model = self.host.viewmodel.mesh
        if self.document.project is baseline and self.document is self.host.viewmodel.documents:
            if signature != self.subdivision_signature():
                self.generate_subdivision(self.apply_result)
                return
            if not self.apply_result:
                self.prepared = result
                if self.wireframe.isChecked() and self.preview_subdivision.isChecked():
                    self.host.viewport.subdivision_pose = scratch.animation.pose
                    self.host.viewport.update()
                    mesh = next(m for m in scratch.scene.meshes if m.id == model.mesh_id)
                    self.status.setText(
                        f"Preview: {len(mesh.vertices)} vertices, "
                        f"{len(mesh.triangles)} triangles. Apply to keep it."
                    )
                return
        self.prepared = None
        self.clear_preview()

        def publish(service: MeshService) -> None:
            """Commit the prepared immutable collections through normal undo history."""
            self.check()
            if self.document.project is not baseline or scratch.project is None:
                raise ProjectError("Project changed during subdivision; regenerate again.")
            scene = scratch.scene
            service.commit(
                "Subdivide artwork",
                meshes=scene.meshes,
                deformers=scene.deformers,
                timelines=scene.timelines,
            )

        model.run(publish)
        self.status.setText(model.error or "Subdivision updated. Undo restores the previous mesh.")

    def hideEvent(self, event: QHideEvent) -> None:
        """Release authoring modes and previews owned by this project's visible editor."""
        self.preview_timer.stop()
        self.pins.detach()
        self.clear_preview()
        if getattr(self.host, "bone_editor", None) is self:
            self.host.command_actions["bone_editor"].setChecked(False)
            self.host.viewmodel.reset_background_tools(self.document)
            if (
                not self.host._closed
                and self.document is self.host.viewmodel.documents
                and self.document.project is not None
            ):
                self.host.navigate()
        super().hideEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Keep preview geometry read-only while retaining pan and zoom navigation."""
        viewport = self.host.viewport
        if (
            self.isVisible()
            and self.document is self.host.viewmodel.documents
            and viewport.subdivision_pose is not None
        ):
            if isinstance(event, QKeyEvent) and event.type() == QEvent.Type.KeyPress:
                if event.key() == Qt.Key.Key_Escape:
                    self.preview_subdivision.setChecked(False)
                    return True
                if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                    return True
            if (
                isinstance(event, QMouseEvent)
                and event.button() == Qt.MouseButton.LeftButton
                and not viewport._space
                and not viewport.pan_tool
            ):
                self.status.setText("Apply or turn off Preview to edit artwork.")
                return True
        return super().eventFilter(watched, event)

    def fail_subdivision(self, message: str) -> None:
        """Report worker failures while retaining the untouched original document."""
        self.subdivision_job = None
        self.status.setText(message)

    def subdivision_state(self) -> None:
        """Limit contour controls to modes that consume them."""
        alignment_row, expand_row = self.alignment.parentWidget(), self.expand.parentWidget()
        assert alignment_row is not None and expand_row is not None
        alignment_row.setEnabled(self.division_type.currentData() != "grid")
        expand_row.setEnabled(self.division_type.currentData() == "mask")


class SpringEditor(CustomDialog):
    """Named spring groups, original presets and bounded properties with live stage preview."""

    def __init__(self, window: "MainWindow") -> None:
        """Keep simulation controls modeless so bone and object drags remain interactive."""
        super().__init__(window, "Spring Editor")
        self.host, self.document = window, window.viewmodel.documents
        self._loading = False
        self._applying = False
        self._started_timeline_playback = False
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self.finish_preview_cycle)
        self.preview_remaining = 3000
        self.preview_paused = False
        self.preview_source = self.document.project
        self.preview_frame = 0.0
        self.settings_source = self.document.project
        self.loaded_group = "Default"
        self.bake_job: LibraryJob | None = None
        self.bake_token: object = object()
        self.apply_timer = QTimer(self)
        self.apply_timer.setSingleShot(True)
        self.apply_timer.setInterval(160)
        self.apply_timer.timeout.connect(self.apply_group)
        self.resize(460, 940)
        self.setMinimumSize(440, 650)
        outer = QVBoxLayout(self.content)
        heading = QHBoxLayout()
        heading.addWidget(QLabel("Groups"))
        heading.addStretch()
        self.add_group_button = QToolButton()
        self.remove_group_button = QToolButton()
        for tool_button, icon, label, callback in (
            (self.add_group_button, "add", "Add spring group", self.new_group),
            (self.remove_group_button, "remove", "Remove spring group", self.remove_group),
        ):
            tool_button.setIcon(window.icons.icon(icon))
            tool_button.setAccessibleName(label)
            tool_button.setToolTip(label)
            tool_button.clicked.connect(callback)
            heading.addWidget(tool_button)
        outer.addLayout(heading)
        controls = QHBoxLayout()
        self.master_key = QCheckBox("Key master")
        self.master_key.setToolTip(
            "Key the owning object's master Spring state instead of one group"
        )
        controls.addWidget(self.master_key)
        self.activation_buttons: dict[bool, QToolButton] = {}
        for label, enabled in (("Key On", True), ("Key Off", False)):
            activation_button = QToolButton()
            activation_button.setText(label)
            activation_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            activation_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            activation_button.setCheckable(True)
            activation_button.clicked.connect(
                lambda checked=False, value=enabled: self.key_activation(value)
            )
            self.activation_buttons[enabled] = activation_button
            controls.addWidget(activation_button)
        color = QToolButton()
        color.setIcon(window.icons.icon("palette"))
        color.setToolTip("Spring group display color")
        color.setAccessibleName("Spring group display color")
        color.clicked.connect(self.choose_group_color)
        controls.addWidget(color)
        outer.addLayout(controls)
        self.activation_state = QLabel()
        self.activation_state.setAccessibleName("Effective Spring state at playhead")
        self.activation_state.setStyleSheet("font-weight: 600;")
        self.activation_details = QLabel()
        self.activation_details.setAccessibleName("Spring group and master activation at playhead")
        self.activation_details.setWordWrap(True)
        outer.addWidget(self.activation_state)
        outer.addWidget(self.activation_details)
        self.group_splitter = QSplitter(Qt.Orientation.Vertical)
        self.group_splitter.setChildrenCollapsible(False)
        self.group_splitter.setHandleWidth(1)
        self.groups = QTreeWidget()
        self.groups.setHeaderHidden(True)
        self.groups.setItemDelegate(NameDelegate(self.groups))
        self.groups.setUniformRowHeights(True)
        self.groups.ensurePolished()
        self.groups.setMinimumHeight(5 * (self.groups.fontMetrics().height() + 14) + 4)
        self.groups.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.groups.setAccessibleName("Spring groups and bones")
        self.groups.currentItemChanged.connect(self.load_group)
        self.groups.itemSelectionChanged.connect(self.select_tree_bones)
        self.groups.itemChanged.connect(self.rename_group)
        self.group_splitter.addWidget(self.groups)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(160)
        body = QWidget()
        box = QVBoxLayout(body)
        box.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(body)
        self.group_splitter.addWidget(scroll)
        self.group_splitter.setStretchFactor(0, 0)
        self.group_splitter.setStretchFactor(1, 1)
        self.group_splitter.handle(1).setToolTip("Drag to resize the group list")
        outer.addWidget(self.group_splitter, 1)
        row = QHBoxLayout()
        self.assign_button = QPushButton("Assign to Group")
        self.unassign_button = QPushButton("Remove from Group")
        for button, callback in (
            (self.assign_button, self.assign),
            (self.unassign_button, self.unassign),
        ):
            button.clicked.connect(callback)
            row.addWidget(button)
        box.addLayout(row)
        self.include_children = QCheckBox("Include child bones")
        self.include_children.setChecked(True)
        self.include_children.toggled.connect(self.refresh_actions)
        box.addWidget(self.include_children)
        presets = QWidget()
        grid = QGridLayout(presets)
        grid.setContentsMargins(4, 4, 4, 4)
        grid.setSpacing(4)
        self.preset_examples: list[SpringPresetPreview] = []
        self.example_clock = QElapsedTimer()
        self.example_timer = QTimer(self)
        self.example_timer.setInterval(33)
        self.example_timer.timeout.connect(self.tick_examples)
        for index, name in enumerate(SPRING_PRESETS):
            cell = QWidget()
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setSpacing(0)
            button = QPushButton(name)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            button.setMinimumWidth(0)
            button.setToolTip(PRESET_HELP[name])
            button.clicked.connect(lambda checked=False, value=name: self.preset(value))
            example = SpringPresetPreview(name)
            self.preset_examples.append(example)
            cell_layout.addWidget(example, 0, Qt.AlignmentFlag.AlignHCenter)
            cell_layout.addWidget(button)
            grid.addWidget(cell, index // 5, index % 5)
        self.presets_toggle = self.section(box, "Presets", presets)
        self.presets_body = presets
        self.motion_test_button = QPushButton(
            window.icons.icon("animation"), "Create timeline motion test"
        )
        self.motion_test_button.setToolTip(
            "Create a separate editable clip that moves the rig to show spring follow-through."
        )
        self.motion_test_button.clicked.connect(self.create_motion_test)
        grid.addWidget(self.motion_test_button, 2, 0, 1, 5)
        self.custom_presets = QComboBox()
        self.custom_presets.setEditable(True)
        self.custom_presets.setAccessibleName("Project custom Spring preset")
        preset_name = self.custom_presets.lineEdit()
        assert preset_name is not None
        preset_name.setMaxLength(100)
        self.custom_presets.addItems(
            list(DynamicsService(self.document).scene.extra.get("spring_presets", {}))
        )
        grid.addWidget(self.custom_presets, 3, 0, 1, 3)
        for column, label, callback in (
            (3, "Save custom", self.save_custom_preset),
            (4, "Apply", self.apply_custom_preset),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            grid.addWidget(button, 3, column)
        properties = QWidget()
        form = QFormLayout(properties)
        advanced = QGroupBox("Physical solver values")
        advanced_form = QFormLayout(advanced)
        self.speed = QSpinBox()
        self.bounciness = QSpinBox()
        for label, control in (("Bounciness", self.bounciness), ("Speed", self.speed)):
            control.setRange(0, 100)
            control.setAccessibleName(label)
            control.setToolTip("Rigora control range: 0–100. Physical values are shown below.")
            control.setKeyboardTracking(False)
            form.addRow(label, slider_field(control))
        self.fields: dict[str, QDoubleSpinBox] = {}
        for key, label, low, high, default in (
            ("frequency", "Speed · Hz", 0.5, 12, 3),
            ("damping", "Damping ratio", 0.05, 3, 0.5),
            ("inertia", "Inertia", 0, 3, 0.6),
            ("gravity", "Gravity · px/s²", -10000, 10000, 0),
            ("strength", "Strength", 0, 1, 1),
            ("clockwise", "Clockwise limit · °", 0, 180, 65),
            ("counterclockwise", "Counterclockwise limit · °", 0, 180, 65),
            ("stretch", "Stretch · %", 0, 300, 0),
            ("squash", "Squash · %", 0, 100, 0),
        ):
            field = QDoubleSpinBox()
            field.setRange(low, high)
            field.setDecimals(2)
            field.setValue(default)
            field.setKeyboardTracking(False)
            field.setAccessibleName(label)
            self.fields[key] = field
            target = (
                advanced_form if key in ("frequency", "damping", "inertia", "strength") else form
            )
            target.addRow(label, slider_field(field) if key == "gravity" else field)
        self.translate = QCheckBox("Translate / stretch and squash")
        self.rotate = QCheckBox("Rotate")
        self.rotate.setChecked(True)
        form.addRow(self.rotate)
        form.addRow(self.translate)
        advanced_toggle = QPushButton("Physical solver values…")
        advanced_toggle.setCheckable(True)
        advanced_toggle.toggled.connect(advanced.setVisible)
        form.addRow(advanced_toggle)
        form.addRow(advanced)
        advanced.hide()
        self.speed.valueChanged.connect(self.apply_controls)
        self.bounciness.valueChanged.connect(self.apply_controls)
        self.fields["frequency"].valueChanged.connect(self.sync_controls)
        self.fields["damping"].valueChanged.connect(self.sync_controls)
        self.translate.toggled.connect(self.translation_controls)
        self.sync_controls()
        self.translation_controls()
        self.properties_toggle = self.section(box, "Property", properties)
        self.properties_body = properties
        display = QWidget()
        display_form = QFormLayout(display)
        self.display_bones = QCheckBox("Show bones")
        self.display_bones.setChecked(window.viewport.show_bones)
        self.display_connections = QCheckBox("Connection silhouettes")
        self.display_connections.setChecked(True)
        self.display_size = QDoubleSpinBox()
        self.display_size.setRange(25, 300)
        self.display_size.setValue(100)
        self.display_size.setSuffix("%")
        self.display_opacity = QDoubleSpinBox()
        self.display_opacity.setRange(0, 100)
        self.display_opacity.setValue(100)
        self.display_opacity.setSuffix("%")
        for label, display_control in (
            ("", self.display_bones),
            ("Width", self.display_size),
            ("Opacity", self.display_opacity),
            ("", self.display_connections),
        ):
            display_form.addRow(label, display_control)
            display_control.setAccessibleName(label or display_control.text())
        self.display_bones.toggled.connect(self.update_display)
        window.command_actions["bone_overlay"].toggled.connect(self.display_bones.setChecked)
        self.display_connections.toggled.connect(self.update_display)
        self.display_size.valueChanged.connect(self.update_display)
        self.display_opacity.valueChanged.connect(self.update_display)
        self.section(box, "Bone display", display)
        baking = QWidget()
        bake_form = QFormLayout(baking)
        self.bake_scope = QComboBox()
        self.bake_scope.addItems(["All groups", "Selected group"])
        self.bake_tail = QDoubleSpinBox()
        self.bake_tail.setRange(0, 30)
        self.bake_tail.setValue(3)
        self.bake_tail.setSuffix(" s")
        self.bake_tail.setToolTip("Minimum settling tail; slow springs extend it automatically")
        self.bake_select = QCheckBox("Use baked result (bypass live springs)")
        self.bake_select.setChecked(True)
        self.bake_button = QPushButton(window.icons.icon("key"), "Bake Spring to Keys")
        self.bake_button.clicked.connect(self.bake_springs)
        for label, bake_control in (
            ("Scope", self.bake_scope),
            ("Settling tail", self.bake_tail),
            ("", self.bake_select),
            ("", self.bake_button),
        ):
            bake_form.addRow(label, bake_control)
        self.section(box, "Bake to editable keys", baking)
        box.addStretch()
        preview_row = QHBoxLayout()
        self.preview_region = QComboBox()
        self.preview_region.setAccessibleName("Spring preview region")
        self.preview_region.addItem("Body", "body")
        self.preview_region.addItem("Face", "face")
        self.preview_region.setToolTip(
            "Choose live preview bones. Face is available for bones in the Face bone group."
        )
        self.preview_region.currentIndexChanged.connect(self.region_changed)
        preview_row.addWidget(self.preview_region, 1)
        self.play_button = QToolButton()
        self.play_button.setIcon(window.icons.icon("play_arrow"))
        self.play_button.setCheckable(True)
        self.play_button.setAccessibleName("Play or pause spring animation")
        self.play_button.setToolTip("Play the spring release test without advancing the timeline")
        self.play_button.toggled.connect(self.toggle_preview)
        preview_row.addWidget(self.play_button)
        self.loop_button = QToolButton()
        self.loop_button.setIcon(window.icons.icon("repeat"))
        self.loop_button.setCheckable(True)
        self.loop_button.setChecked(True)
        self.loop_button.setAccessibleName("Repeat spring animation")
        self.loop_button.setToolTip("Repeat the spring release test; timeline looping is unchanged")
        preview_row.addWidget(self.loop_button)
        self.status = QLabel(
            "Assign child bones, then move their parent or character on the stage."
        )
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        outer.addLayout(preview_row)
        examples = QPushButton("Open SVG spring examples…")
        examples.clicked.connect(self.open_examples)
        box.insertWidget(box.count() - 1, examples)
        first_group = next(
            (
                c.extra.get("spring_group", "Default")
                for c in DynamicsService(self.document).scene.constraints
                if c.kind == "spring"
            ),
            "Default",
        )
        self.refresh(str(first_group))
        for field in self.fields.values():
            field.valueChanged.connect(self.queue_settings)
        for control in (self.speed, self.bounciness):
            control.valueChanged.connect(self.queue_settings)
        self.rotate.toggled.connect(self.queue_settings)
        self.translate.toggled.connect(self.queue_settings)
        window.viewmodel.changed.connect(self.document_changed)
        window.viewmodel.rig.changed.connect(self.refresh_actions)
        window.viewmodel.playback.changed.connect(self.sync_preview_transport)
        window.viewmodel.playback.changed.connect(self.sync_activation)
        self.master_key.toggled.connect(self.sync_activation)

    def sync_activation(self) -> None:
        """Show sampled keys and effective physics separately, including mixed/overridden states."""
        if self.document is not self.host.viewmodel.documents or self.document.project is None:
            return
        service = DynamicsService(self.document)
        name = self.group_name()
        frame = self.document.animation.pose.frame
        group = service.activation_values(name, frame)
        master = service.activation_values(name, frame, master=True)

        def label(values: tuple[bool, ...]) -> str:
            """Summarize a multi-bone/multi-object gate without guessing a mixed value."""
            return "—" if not values else "ON" if all(values) else "MIXED" if any(values) else "OFF"

        members = set(service.group_members(name))
        rules = {
            c.owner_id
            for c in service.scene.constraints
            if c.kind == "spring" and c.owner_id in members
        }
        active = {c.owner_id for c in self.document.animation.evaluator.active_springs(frame)}
        effective = label(tuple(key in active for key in sorted(rules)))
        self.activation_state.setText(
            f"Spring: {effective}" if rules else "Spring: No simulated bones"
        )
        self.activation_details.setText(
            f"Group: {label(group)}  ·  Master: {label(master)}  ·  Frame {frame:g}"
        )
        self.activation_state.setToolTip(
            "Effective simulation at the playhead. Master keys, pins, locks and baked motion "
            "can override an enabled group."
        )
        values = master if self.master_key.isChecked() else group
        for enabled, button in self.activation_buttons.items():
            checked = bool(values) and all(value == enabled for value in values)
            with QSignalBlocker(button):
                button.setChecked(checked)
            button.setIcon(self.host.icons.icon("check" if checked else "radio_button_unchecked"))
            button.setEnabled(bool(members))
            button.setToolTip(
                f"Key {'master' if self.master_key.isChecked() else 'group'} "
                f"{'ON' if enabled else 'OFF'} at frame {frame:g}. "
                "The check mark shows the sampled state, including held keys."
            )

    def section(self, layout: QVBoxLayout, title: str, body: QWidget) -> QToolButton:
        """Add a full-width accessible disclosure header without disabling its child controls."""
        button = QToolButton()
        button.setText(title)
        button.setAccessibleName(f"Expand or collapse {title}")
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button.setCheckable(True)
        button.setChecked(True)
        button.setIcon(self.host.icons.icon("remove"))

        def expand(checked: bool) -> None:
            """Collapse only presentation; saved settings and group memberships stay untouched."""
            body.setVisible(checked)
            button.setIcon(self.host.icons.icon("remove" if checked else "add"))
            if body is self.presets_body:
                if checked and self.isVisible():
                    self.example_timer.start()
                else:
                    self.example_timer.stop()

        button.toggled.connect(expand)
        layout.addWidget(button)
        layout.addWidget(body)
        return button

    def toggle_preview(self, playing: bool) -> None:
        """Play or hold the preset release test using the existing live spring solver."""
        workspace = self.host.rig_workspace
        if playing:
            self.check()
            if self.apply_timer.isActive():
                self.apply_group()
            playback = self.host.viewmodel.playback
            session = playback.session
            self.preview_frame = session.pose.frame if session else 0
            if session and session.playback.is_playing:
                playback.pause(snap=False)
            if (
                self.preview_paused
                and self.preview_source is self.document.project
                and workspace.spring_document is self.document
            ):
                workspace.spring_clock = workspace.spring_input = time.monotonic()
                workspace.spring_timer.start()
            else:
                scope = workspace.spring_scope
                members = tuple(
                    key for key in self.group_members() if scope is None or key in scope
                )
                strain = (
                    -0.25
                    if self.translate.isChecked() and not self.fields["stretch"].value()
                    else 0.25
                )
                if not workspace.excite_springs(members, strain=strain):
                    self.stop_preview()
                    self.status.setText(
                        "Assign a spring preset to child bones in this preview region."
                    )
                    return
                self.preview_remaining = 3000
            self.preview_source = self.document.project
            self.preview_paused = False
            self.preview_timer.start(self.preview_remaining)
            self.status.setText(f"{self.group_name()} · spring release preview")
        else:
            self.preview_remaining = max(1, self.preview_timer.remainingTime())
            self.preview_timer.stop()
            if workspace.spring_document is self.document:
                workspace.spring_timer.stop()
            self.preview_paused = True
        self.play_button.setIcon(self.host.icons.icon("pause" if playing else "play_arrow"))

    def finish_preview_cycle(self) -> None:
        """Repeat only the spring release, or restore the held timeline pose after one cycle."""
        if not self.play_button.isChecked():
            return
        if self.loop_button.isChecked() and self.isVisible():
            self.preview_paused = False
            self.toggle_preview(True)
        else:
            self.stop_preview()

    def stop_preview(self) -> None:
        """Release local preview ownership without seeking or editing the project transport."""
        self.preview_timer.stop()
        self.preview_paused = False
        self.preview_remaining = 3000
        with QSignalBlocker(self.play_button):
            self.play_button.setChecked(False)
        self.play_button.setIcon(self.host.icons.icon("play_arrow"))
        workspace = self.host.rig_workspace
        if (
            workspace.spring_document is self.document
            and getattr(self.host, "spring_editor", None) is self
        ):
            workspace.spring_timer.stop()
            if not self.host._closed:
                workspace.stop_springs()

    def sync_preview_transport(self) -> None:
        """Give explicitly started timeline playback priority over a local spring preview."""
        session = self.host.viewmodel.playback.session
        if (
            session
            and (session.playback.is_playing or session.pose.frame != self.preview_frame)
            and (self.play_button.isChecked() or self.preview_paused)
        ):
            self.stop_preview()

    def showEvent(self, event: QShowEvent) -> None:
        """Restore the group list height and animate visible preset illustrations."""
        super().showEvent(event)
        self.update_display()
        height = self.host.viewmodel.preferences.data.get("spring_group_list_height", 190)
        height = max(self.groups.minimumHeight(), min(600, height)) if type(height) is int else 190
        self.group_splitter.setSizes([height, max(160, self.group_splitter.height() - height)])
        self.example_clock.start()
        if self.presets_toggle.isChecked():
            self.example_timer.start()

    def tick_examples(self) -> None:
        """Animate all preset illustrations with one cheap clock while this panel is visible."""
        if not self.isVisible() or not self.presets_toggle.isChecked():
            self.example_timer.stop()
            return
        frame = int(self.example_clock.elapsed() * 30 / 1000)
        for example in self.preset_examples:
            example.advance(frame)

    def open_examples(self) -> None:
        """Browse portable spring studies without replacing the current scene or its history."""
        self.host.open_content_library("Plants & springs")
        assert self.host.content_browser is not None
        self.host.content_browser.search.setText("spring-example")

    def document_changed(self) -> None:
        """Cancel stale pending controls after undo, deletion or another external document edit."""
        if (
            self.isVisible()
            and self.document is self.host.viewmodel.documents
            and self.document.project is not None
            and not self._applying
        ):
            if self.apply_timer.isActive() and self.document.project is self.settings_source:
                return
            if self.document.project is self.settings_source:
                self.refresh_actions()
                return
            self.stop_preview()
            self.apply_timer.stop()
            self.refresh()

    def queue_settings(self) -> None:
        """Coalesce slider changes into an undoable live update of the current group."""
        if not self._loading and self.group_members():
            self.settings_source = self.document.project
            self.apply_timer.start()

    def sync_controls(self) -> None:
        """Display the inverse of Rigora's documented monotonic speed/damping mapping."""
        with QSignalBlocker(self.speed), QSignalBlocker(self.bounciness):
            self.speed.setValue(round((self.fields["frequency"].value() - 0.5) / 11.5 * 100))
            self.bounciness.setValue(round((1.2 - self.fields["damping"].value()) / 1.15 * 100))
        for control in (self.speed, self.bounciness):
            parent = control.parentWidget()
            assert parent is not None
            slider = parent.findChild(QSlider)
            assert slider is not None
            with QSignalBlocker(slider):
                slider.setValue(control.value())

    def apply_controls(self) -> None:
        """Map intuitive controls to frequency and damping without altering group membership."""
        with QSignalBlocker(self.fields["frequency"]), QSignalBlocker(self.fields["damping"]):
            self.fields["frequency"].setValue(0.5 + 11.5 * self.speed.value() / 100)
            self.fields["damping"].setValue(1.2 - 1.15 * self.bounciness.value() / 100)

    def translation_controls(self) -> None:
        """Keep distance limits editable only when positional spring motion is enabled."""
        for key in ("stretch", "squash"):
            self.fields[key].setEnabled(self.translate.isChecked())

    def check(self) -> None:
        """Guard modeless commands against closed or changed project tabs."""
        if self.document is not self.host.viewmodel.documents or self.document.project is None:
            raise ProjectError("Reopen Spring Editor for the active project.")

    def refresh(self, name: str = "") -> None:
        """Read group definitions and existing rule memberships from the saved scene."""
        self.check()
        scene = DynamicsService(self.document).scene
        with QSignalBlocker(self.custom_presets):
            preset_name = self.custom_presets.currentText()
            self.custom_presets.clear()
            self.custom_presets.addItems(sorted(scene.extra.get("spring_presets", {})))
            self.custom_presets.setCurrentText(preset_name)
        current = name or self.group_name()
        prior = self.groups.currentItem()
        bone_id = prior.data(0, Qt.ItemDataRole.UserRole + 1) if prior else None
        selection = (
            {
                (item.data(0, Qt.ItemDataRole.UserRole), item.data(0, Qt.ItemDataRole.UserRole + 1))
                for item in self.groups.selectedItems()
            }
            if not name
            else set()
        )
        expanded = {}
        for i in range(self.groups.topLevelItemCount()):
            item = self.groups.topLevelItem(i)
            if item is not None:
                expanded[item.data(0, Qt.ItemDataRole.UserRole)] = item.isExpanded()
        bones = {b.id: b for rig in scene.skeletons for b in rig.bones}
        self.refresh_regions()
        with QSignalBlocker(self.groups):
            self.groups.clear()
            selected = None
            for group in DynamicsService(self.document).group_names():
                members = self.group_members(group)
                item = QTreeWidgetItem([group])
                item.setData(0, Qt.ItemDataRole.UserRole, group)
                item.setIcon(0, self.host.icons.icon("folder_open"))
                item.setToolTip(
                    0,
                    f"{len(members)} spring bones. Select to assign stage bones; "
                    "double-click to rename.",
                )
                if group != "Default":
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                self.groups.addTopLevelItem(item)
                item.setExpanded(expanded.get(group, True))
                if group == current:
                    selected = item
                for key in members:
                    if key not in bones:
                        continue
                    child = QTreeWidgetItem(item, [bones[key].name])
                    child.setData(0, Qt.ItemDataRole.UserRole, group)
                    child.setData(0, Qt.ItemDataRole.UserRole + 1, key)
                    anchor = not bones[key].parent_id and not any(
                        rule.kind == "spring" and rule.owner_id == key for rule in scene.constraints
                    )
                    child.setIcon(0, self.host.icons.icon("anchor" if anchor else "account_tree"))
                    child.setToolTip(
                        0, f"{bones[key].name} · {group}" + (" · Anchored root" if anchor else "")
                    )
                    if group == current and key == bone_id and not name:
                        selected = child
            selected = selected or self.groups.topLevelItem(0)
            assert selected is not None
            self.groups.setCurrentItem(selected)
            for i in range(self.groups.topLevelItemCount()):
                parent = self.groups.topLevelItem(i)
                assert parent is not None
                for row in (parent, *(parent.child(j) for j in range(parent.childCount()))):
                    assert row is not None
                    token = (
                        row.data(0, Qt.ItemDataRole.UserRole),
                        row.data(0, Qt.ItemDataRole.UserRole + 1),
                    )
                    if token in selection:
                        row.setSelected(True)
        self.settings_source = self.document.project
        self.load_group()
        self.refresh_actions()
        self.update_display()

    def update_display(self) -> None:
        """Apply temporary bone-only overlays without changing artwork or authored bone colors."""
        if not self.isVisible():
            return
        viewport = self.host.viewport
        viewport.show_bones = self.display_bones.isChecked()
        self.host.command_actions["bone_overlay"].setChecked(viewport.show_bones)
        viewport.bone_display_size = self.display_size.value() / 100
        viewport.bone_display_opacity = self.display_opacity.value() / 100
        viewport.bone_connections = self.display_connections.isChecked()
        service = DynamicsService(self.document)
        viewport.spring_colors = {
            key: service.group_metadata(name)["color"]
            for name in service.group_names()
            for key in service.group_members(name)
        }
        viewport.spring_highlight = set(self.group_members())
        viewport.update()

    def save_custom_preset(self) -> None:
        """Persist the group's actual physical settings under an editable project-local name."""
        if self.apply_timer.isActive():
            self.apply_group()
        name = self.custom_presets.currentText().strip() or f"{self.group_name()} custom"
        self.host.viewmodel.animation_editor.run(
            lambda _: DynamicsService(self.document).save_custom_preset(name, self.group_name())
        )
        if not self.host.viewmodel.animation_editor.error:
            if self.custom_presets.findText(name) < 0:
                self.custom_presets.addItem(name)
            self.custom_presets.setCurrentText(name)
        self.status.setText(
            self.host.viewmodel.animation_editor.error or f"Saved custom preset · {name}"
        )

    def apply_custom_preset(self) -> None:
        """Apply stored settings through the same validated group configuration command."""
        name = self.custom_presets.currentText()
        settings = DynamicsService(self.document).scene.extra.get("spring_presets", {}).get(name)
        if not settings:
            self.status.setText("Choose a saved custom preset first.")
            return
        self.host.viewmodel.animation_editor.run(
            lambda _: DynamicsService(self.document).assign_group(
                self.group_members() or self.selected_bones(), group=self.group_name(), **settings
            )
        )
        self.refresh()
        self.status.setText(
            self.host.viewmodel.animation_editor.error or f"Applied custom preset · {name}"
        )

    def choose_group_color(self) -> None:
        """Reuse the shared Apply/Cancel color dialog for an undoable group display edit."""
        name = self.group_name()
        self.host.character_panel.pick_color(
            DynamicsService(self.document).group_metadata(name)["color"],
            lambda service, color: DynamicsService(service.document).group_color(name, color),
        )
        self.refresh()

    def key_activation(self, enabled: bool) -> None:
        """Publish an activation key and reveal the ordinary Spring timeline rows."""
        self.stop_preview()
        self.host.viewmodel.animation_editor.run(
            lambda _: DynamicsService(self.document).activation(
                self.group_name(),
                enabled,
                self.document.animation.pose.frame,
                master=self.master_key.isChecked(),
            )
        )
        self.host.timeline.search.clear()
        self.host.timeline.only_selected.setChecked(False)
        self.host.timeline.refresh()
        for (_, lane), row in self.host.timeline._groups.items():
            if lane == "Spring":
                row.setExpanded(True)
                self.host.timeline.tracks.scrollToItem(row)
        self.status.setText(self.host.viewmodel.animation_editor.error or "Spring activation keyed")

    def bake_springs(self) -> None:
        """Evaluate physics on an isolated worker; adopt only an unchanged source revision."""
        if self.bake_job:
            return
        self.stop_preview()
        self.check()
        document, baseline = self.document, self.document.project
        scratch = document.fork()
        group = self.group_name() if self.bake_scope.currentIndex() else None
        tail, activate = self.bake_tail.value(), self.bake_select.isChecked()
        self.bake_token = token = object()
        self.bake_button.setEnabled(False)
        self.status.setText("Baking Spring motion in the background…")
        job = LibraryJob(
            lambda: (
                DynamicsService(scratch).bake(group, tail_seconds=tail, activate_baked=activate),
                scratch,
                baseline,
                document,
                token,
                activate,
            )
        )
        self.bake_job = job
        job.signals.done.connect(self.finish_spring_bake)
        job.signals.failed.connect(self.fail_spring_bake)
        QThreadPool.globalInstance().start(job)

    def finish_spring_bake(self, result: Any) -> None:
        """Commit completed animation as one undo step and discard stale or canceled jobs."""
        clip, scratch, baseline, document, token, activate = result
        self.bake_job = None
        self.bake_button.setEnabled(True)
        if token is not self.bake_token or self.host._closed:
            return

        def commit(_: Any) -> None:
            """Revalidate ownership before publishing the worker's immutable timeline records."""
            self.check()
            if document is not self.document or baseline is not document.project:
                raise ProjectError("Project changed while baking; bake again to retain both edits.")
            scene = scratch.scene
            DynamicsService(document).commit(
                "Bake Spring to Keys", timelines=scene.timelines, clips=scene.clips
            )
            if activate:
                document.select_animation_clip(clip)

        self.host.viewmodel.animation_editor.run(commit)
        self.status.setText(
            self.host.viewmodel.animation_editor.error
            or "Baked keys created; the procedural source clip is preserved"
        )

    def fail_spring_bake(self, message: str) -> None:
        """Restore controls after a failed worker without changing the source project."""
        self.bake_job = None
        self.bake_button.setEnabled(True)
        if not self.host._closed:
            self.status.setText(message)

    def group_name(self) -> str:
        """Resolve a selected group even before it has any assigned bones."""
        item = self.groups.currentItem()
        return str(item.data(0, Qt.ItemDataRole.UserRole)) if item else "Default"

    def select_tree_bones(self) -> None:
        """Select tree members on the stage; group headers retain the existing stage selection."""
        keys = tuple(
            key
            for item in self.groups.selectedItems()
            if (key := item.data(0, Qt.ItemDataRole.UserRole + 1))
        )
        if keys:
            self.host.viewmodel.rig.select_many(keys)
        self.refresh_actions()

    def refresh_actions(self) -> None:
        """Keep membership actions truthful without rebuilding the tree during selection changes."""
        if self.document is not self.host.viewmodel.documents or self.document.project is None:
            return
        selected = set(self.selected_bones())
        members = set(self.group_members())
        self.assign_button.setEnabled(bool(selected - members))
        groups = self.selected_groups()
        removable = {
            key for group in groups for key in DynamicsService(self.document).group_members(group)
        }
        self.unassign_button.setEnabled(bool(selected & removable))
        self.remove_group_button.setEnabled(self.group_name() != "Default" or bool(members))
        self.motion_test_button.setEnabled(
            any(
                c.kind == "spring" and c.enabled and c.owner_id in members
                for c in DynamicsService(self.document).scene.constraints
            )
        )
        scope = self.host.rig_workspace.spring_scope
        self.play_button.setEnabled(
            any(
                c.kind == "spring"
                and c.enabled
                and c.owner_id in members
                and (scope is None or c.owner_id in scope)
                for c in DynamicsService(self.document).scene.constraints
            )
        )

    def refresh_regions(self) -> None:
        """Resolve explicitly grouped facial bones and their descendants for live preview."""
        scene = DynamicsService(self.document).scene
        bones = [bone for rig in scene.skeletons for bone in rig.bones]
        face = {
            bone.id
            for bone in bones
            if bone.group.casefold() == "face" or bone.extra.get("region") == "face"
        }
        while True:
            expanded = face | {bone.id for bone in bones if bone.parent_id in face}
            if expanded == face:
                break
            face = expanded
        self.region_bones = {"face": face, "body": {bone.id for bone in bones} - face}
        model = self.preview_region.model()
        assert isinstance(model, QStandardItemModel)
        model.item(1).setEnabled(bool(face))
        model.item(1).setToolTip(
            "Preview facial bones and their children."
            if face
            else "This rig has no facial bones. Put facial bones in the Face bone group first."
        )
        if not face:
            with QSignalBlocker(self.preview_region):
                self.preview_region.setCurrentIndex(0)
        self.host.rig_workspace.spring_scope = (
            frozenset(self.region_bones[self.preview_region.currentData()]) if face else None
        )

    def region_changed(self) -> None:
        """Change transient preview scope and selection without rewriting spring constraints."""
        self.check()
        self.stop_preview()
        self.refresh_regions()
        allowed = self.region_bones[self.preview_region.currentData()]
        self.host.viewmodel.rig.select_many(
            tuple(key for key in self.group_members() if key in allowed)
        )
        self.refresh_actions()
        if self.host.rig_workspace.spring_enabled:
            self.host.rig_workspace.begin_springs()

    def rename_group(self, item: QTreeWidgetItem, column: int) -> None:
        """Commit an inline group name edit while preserving memberships and one-step Undo."""
        if column != 0 or item.parent() is not None:
            return
        old = str(item.data(0, Qt.ItemDataRole.UserRole))
        name = item.text(0).strip()
        editor = self.host.viewmodel.animation_editor
        editor.run(lambda _: DynamicsService(self.document).rename_group(old, name), snap=False)
        self.status.setText(editor.error or f"Renamed spring group to {name}.")
        self.refresh(old if editor.error else name)

    def load_group(self) -> None:
        """Show stored settings without mutating or rebinding the group's bones."""
        if self.apply_timer.isActive():
            self.apply_timer.stop()
            self.configure(
                self.group_members(self.loaded_group), group=self.loaded_group, refresh=False
            )
        if not self.document.project:
            return
        if self.loaded_group != self.group_name():
            self.stop_preview()
        self.loaded_group = self.group_name()
        self.update_display()
        rule = next(
            (
                c
                for c in DynamicsService(self.document).scene.constraints
                if c.kind == "spring"
                and c.extra.get("spring_group", "Default") == self.group_name()
            ),
            None,
        )
        if rule:
            self._loading = True
            for key, field in self.fields.items():
                field.setValue(
                    rule.parameters.get(
                        key,
                        rule.parameters.get("max_angle", 65)
                        if key in ("clockwise", "counterclockwise")
                        else field.value(),
                    )
                )
            self.translate.setChecked(rule.parameters.get("translate", False))
            self.rotate.setChecked(rule.parameters.get("rotate", True))
            self._loading = False
        self.refresh_actions()
        self.sync_activation()

    def selected_bones(self) -> tuple[str, ...]:
        """Include the selected bones themselves and optionally all their descendants."""
        self.check()
        scene = DynamicsService(self.document).scene
        selected = set(self.host.viewmodel.rig.selected)
        bones = [bone for rig in scene.skeletons for bone in rig.bones]
        if self.include_children.isChecked():
            while True:
                expanded = selected | {bone.id for bone in bones if bone.parent_id in selected}
                if expanded == selected:
                    break
                selected = expanded
        return tuple(bone.id for bone in bones if bone.id in selected)

    def selected_groups(self) -> set[str]:
        """Resolve selected member rows' groups, falling back to the active assignment target."""
        return {
            str(item.data(0, Qt.ItemDataRole.UserRole))
            for item in self.groups.selectedItems()
            if item.data(0, Qt.ItemDataRole.UserRole + 1)
        } or {self.group_name()}

    def configure(
        self, bones: tuple[str, ...], *, group: str | None = None, refresh: bool = True
    ) -> None:
        """Publish validated group properties once through the shared animation ViewModel."""
        self.apply_timer.stop()
        self.check()
        if not bones:
            self.status.setText("Select a bone or branch on the stage.")
            return
        editor = self.host.viewmodel.animation_editor
        playback = self.host.viewmodel.playback
        session = playback.session
        resume = session is not None and session.playback.is_playing
        frame, loop = (session.playback.frame, session.playback.loop) if session else (0.0, True)
        self._applying = True
        try:
            editor.run(
                lambda _: DynamicsService(self.document).assign_group(
                    bones,
                    **self.settings(),
                    translate=self.translate.isChecked(),
                    rotate=self.rotate.isChecked(),
                    group=group or self.group_name(),
                ),
                snap=False,
            )
        finally:
            self._applying = False
        self.status.setText(
            editor.error or f"{len(bones)} bones configured. Move the character to test."
        )
        if not editor.error:
            if refresh:
                self.refresh()
            self.host.rig_workspace.begin_springs()
            if self.play_button.isChecked():
                self.preview_paused = False
                self.toggle_preview(True)
            if resume and playback.session is not None:
                playback.seek(frame)
                if playback.session.playback.loop != loop:
                    playback.toggle_loop()
                playback.play_pause()

    def settings(self) -> dict[str, Any]:
        """Return numeric settings for the validated shared configuration entry point."""
        return {key: field.value() for key, field in self.fields.items()}

    def assign(self) -> None:
        """Assign selected eligible bones to this group with the displayed properties."""
        self.configure(self.selected_bones())

    def unassign(self) -> None:
        """Remove spring rules from selected bones without touching animation keys."""
        self.apply_timer.stop()
        selected = self.selected_bones()
        groups = self.selected_groups()
        self.host.viewmodel.animation_editor.run(
            lambda _: DynamicsService(self.document).unassign_group(selected, groups), snap=False
        )

    def new_group(self) -> None:
        """Persist an empty named group independently of spring membership."""
        self.check()
        if self.apply_timer.isActive():
            self.apply_group()
        created = []
        self.host.viewmodel.animation_editor.run(
            lambda _: created.append(DynamicsService(self.document).create_group()), snap=False
        )
        self.refresh(created[0] if created else "")

    def remove_group(self) -> None:
        """Remove a group's rules and definition as one undoable scene edit."""
        self.check()
        self.apply_timer.stop()
        name = self.group_name()
        self.host.viewmodel.animation_editor.run(
            lambda _: DynamicsService(self.document).remove_group(name), snap=False
        )
        self.refresh()

    def apply_group(self) -> None:
        """Apply settings to existing members without relying on the viewport's selection."""
        self.check()
        self.configure(self.group_members() or self.selected_bones())

    def group_members(self, name: str | None = None) -> tuple[str, ...]:
        """Return persisted members; empty groups may accept the current eligible selection."""
        return DynamicsService(self.document).group_members(name or self.group_name())

    def preset(self, name: str) -> None:
        """Apply a complete preset to group members, or assign the eligible selected branch."""
        self.check()
        frequency, damping, inertia, gravity, translate = SPRING_PRESETS[name]
        self._loading = True
        for key, value in (
            ("frequency", frequency),
            ("damping", damping),
            ("inertia", inertia),
            ("gravity", gravity),
            ("strength", 1),
            ("clockwise", 65),
            ("counterclockwise", 65),
            ("stretch", 75 if name == "Stretchy" else 0),
            ("squash", 50 if name == "Squashy" else 0),
        ):
            self.fields[key].setValue(value)
        self.translate.setChecked(translate)
        self.rotate.setChecked(not translate)
        self._loading = False
        self.apply_group()
        if not self.host.viewmodel.animation_editor.error and self.group_members():
            moved = self.host.rig_workspace.excite_springs(
                self.group_members(), strain=-0.25 if name == "Squashy" else 0.25
            )
            if moved:
                self.status.setText(
                    f"{name} · spring release. Play previews this test; Repeat loops it."
                )
                if self.play_button.isChecked():
                    self.preview_remaining = 3000
                    self.preview_timer.start(self.preview_remaining)

    def create_motion_test(self) -> None:
        """Create an editable project clip and explicitly start the main timeline transport."""
        self.check()
        self.stop_preview()
        if self.apply_timer.isActive():
            self.apply_group()
        editor = self.host.viewmodel.animation_editor
        editor.run(lambda _: DynamicsService(self.document).motion_test(self.group_members()))
        if not editor.error:
            timeline = self.host.timeline
            timeline.pages.setCurrentIndex(0)
            timeline.search.clear()
            timeline.only_selected.setChecked(False)
            timeline.refresh()
            for (_, lane), row in timeline._groups.items():
                if lane == "Spring":
                    row.setExpanded(True)
                    timeline.tracks.scrollToItem(row)
            playback = self.host.viewmodel.playback
            playback.seek_start()
            if playback.session and not playback.session.playback.loop:
                playback.toggle_loop()
            if playback.session and not playback.session.playback.is_playing:
                playback.play_pause()
            self._started_timeline_playback = True
        self.status.setText(
            editor.error or "Timeline motion test created · Use the timeline controls to play it."
        )

    def hideEvent(self, event: QHideEvent) -> None:
        """Finish pending edits and release this editor's transient preview on close."""
        self.bake_token = object()
        viewport = self.host.viewport
        viewport.spring_colors.clear()
        viewport.spring_highlight.clear()
        viewport.bone_display_size = viewport.bone_display_opacity = 1.0
        viewport.bone_connections = True
        self.stop_preview()
        self.example_timer.stop()
        self.host.viewmodel.preferences.data["spring_group_list_height"] = self.groups.height()
        current = (
            self.document is self.host.viewmodel.documents
            and self.document.project is not None
            and not self.host._closed
        )
        if self.apply_timer.isActive():
            self.apply_timer.stop()
            if current:
                self.apply_group()
        if getattr(self.host, "spring_editor", None) is self:
            self.host.rig_workspace.spring_scope = None
            if current and self._started_timeline_playback:
                self.host.viewmodel.playback.pause()
            self.host.command_actions["spring_editor"].setChecked(False)
            self.host.viewmodel.reset_background_tools(self.document)
            if not self.host._closed and self.host.rig_workspace.spring_document is self.document:
                self.host.rig_workspace.stop_springs()
            if current:
                self.host.navigate()
        super().hideEvent(event)
