"""Unified Object Tree with saved skins, wardrobe variations and reusable animations."""

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rigora.application_services.appearance import AppearanceService
from rigora.application_services.characters import CharacterService
from rigora.application_services.image_rigging import ImageRigService
from rigora.domain.entities import Group, SceneObject
from rigora.domain.project import ProjectError
from rigora.engine.vector_appearance import palette
from rigora.presentation.widgets.action_buttons import compact_button
from rigora.presentation.widgets.creator_cards import configure_cards
from rigora.presentation.widgets.item_view_state import ItemViewState
from rigora.presentation.widgets.message_dialogs import ask_question
from rigora.presentation.widgets.window_frame import CustomDialog

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


class CharacterPanel(QFrame):
    """Keep one shared hierarchy beside focused appearance and animation controls."""

    def __init__(self, window: "MainWindow") -> None:
        """Build a dedicated composer sidebar with one focused page per authoring task."""
        super().__init__(window)
        self.host = window
        self.busy = False
        self.manual_actor: str | None = None
        self.motion_owner_source: object = None
        self.motion_owner_valid = False
        self.setObjectName("CharacterWorkbench")
        box = QVBoxLayout(self)
        box.setContentsMargins(12, 12, 12, 8)
        box.setSpacing(10)
        self.summary = QLabel("Solid object")
        self.summary.setObjectName("Eyebrow")
        self.summary.setWordWrap(True)
        box.addWidget(self.summary)
        self.actor = QComboBox()
        self.actor.setAccessibleName("Target character")
        self.actor.currentIndexChanged.connect(self.choose_actor)
        self.actor.hide()
        self.name = QLineEdit()
        self.name.setAccessibleName("Character name")
        self.name.setPlaceholderText("Object name")
        self.name.editingFinished.connect(self.rename_object)
        name_row = QHBoxLayout()
        self.extension_header = name_row
        name_row.setSpacing(8)
        name_row.addWidget(self.name, 1)
        box.addLayout(name_row)
        self.structure_host = QWidget()
        self.structure_layout = QVBoxLayout(self.structure_host)
        self.structure_layout.setContentsMargins(0, 0, 0, 0)
        self.structure_layout.setSpacing(6)
        self.layer_actions = QWidget()
        self.layer_actions.setAccessibleName("Layer actions")
        layer_actions = QHBoxLayout(self.layer_actions)
        layer_actions.setContentsMargins(0, 4, 0, 0)
        layer_actions.setSpacing(4)
        self.structure_layout.addWidget(self.layer_actions)
        self.workspace = QSplitter(Qt.Orientation.Vertical)
        self.workspace.setChildrenCollapsible(False)
        self.workspace.addWidget(self.structure_host)
        box.addWidget(self.workspace, 1)
        self.tabs = QTabWidget()
        self.tabs.tabBar().hide()
        self.workspace.addWidget(self.tabs)
        self.workspace.setStretchFactor(0, 3)
        self.workspace.setStretchFactor(1, 2)
        parts = self.page("Object Tree")
        self.object_views = QComboBox()
        self.object_views.setAccessibleName("Object Views")
        self.object_views.setToolTip(
            "Front → Front 3/4 → Side → Back 3/4 → Back · separate saved edits"
        )
        from rigora.domain.character_recipe import VIEWS

        self.object_views.addItems(VIEWS)
        self.object_views.currentTextChanged.connect(self.change_object_view)
        self.object_views.setMaximumWidth(135)
        name_row.addWidget(self.object_views)
        self.convert_button = self.button(
            layer_actions, "Make this a character", self.convert, "person_outline"
        )
        self.assets_button = self.button(
            layer_actions, "Open Assets", self.show_assets, "perm_media"
        )
        self.add_bone_button = self.button(
            layer_actions, "Add bone", window.draw_bone, "device_hub"
        )
        self.folder_button = self.button(
            layer_actions,
            "New folder",
            self.add_folder,
            "create_new_folder",
        )
        self.remove_part_button = self.button(
            layer_actions,
            "Remove part",
            window.scene_workspace.delete_selection
            if hasattr(window, "scene_workspace")
            else self.delete_parts,
            "delete",
        )
        parts.addStretch()
        self.binding_controls = QWidget()
        bones = QVBoxLayout(self.binding_controls)
        bones.setContentsMargins(0, 0, 0, 0)
        bones.setSpacing(6)
        binding_header = QVBoxLayout()
        binding_header.setSpacing(6)
        box.insertLayout(2, binding_header)
        self.binding_toggle = self.section(binding_header, "Binding options", self.binding_controls)
        self.binding_summary = QLabel(
            "Select image parts, then choose the bone they should follow."
        )
        self.binding_summary.setWordWrap(True)
        self.binding_summary.hide()
        self.bones = QComboBox()
        self.bones.setAccessibleName("Attach selected parts to bone")
        bones.addWidget(self.bones)
        self.rigid = QCheckBox("Rigid · follow one bone without bending")
        bones.addWidget(self.rigid)
        self.bones.setToolTip("Select image parts, then choose the bone they should follow")
        self.bind_buttons: list[QToolButton] = []
        for key in ("bind_parts", "unbind_parts"):
            button = QToolButton()
            button.setObjectName("PanelAction")
            button.setDefaultAction(window.command_actions[key])
            button.setAccessibleName(window.command_actions[key].text())
            button.setFixedSize(28, 28)
            layer_actions.addWidget(button)
            self.bind_buttons.append(button)
        layer_actions.addStretch()
        skin = self.page("Skin")
        from rigora.presentation.widgets.appearance_choices import AppearanceChoices

        self.skin_choices = AppearanceChoices(window, "skins", self.motion_owner, editable=True)
        self.skin_choices.setTitle("")
        self.all_parts = QCheckBox("Apply colors to all object parts")
        self.all_parts.setChecked(False)
        skin.addWidget(self.all_parts)
        self.color_list = QListWidget()
        configure_cards(self.color_list, compact=True)
        self.color_list.setMinimumHeight(150)
        self.color_list.setAccessibleName("Artwork color groups")
        self.color_list.currentRowChanged.connect(self.choose_paint)
        self.color_list.itemDoubleClicked.connect(self.paint_color)
        self.color_heading = QLabel("Color palette")
        skin.addWidget(self.color_heading)
        skin.addWidget(self.color_list)
        self.color_hint = QLabel("Select artwork in Object Tree, or apply colors to all parts.")
        self.color_hint.setObjectName("Muted")
        self.color_hint.setWordWrap(True)
        skin.addWidget(self.color_hint)
        self.paints = QComboBox()
        self.paints.hide()
        self.paint_button = self.button(skin, "Change selected color…", self.paint_color, "palette")
        material = QWidget()
        material_box = QVBoxLayout(material)
        material_box.setContentsMargins(0, 4, 0, 0)
        material_box.setSpacing(8)
        self.material_toggle = self.section(skin, "Material & shape", material)
        form = QFormLayout()
        material_box.addLayout(form)
        self.border = self.spin(-1, 100, -1)
        self.border.setSpecialValueText("Original")
        form.addRow("Border width", self.border)
        self.border.editingFinished.connect(
            lambda: self.edit_look({"stroke_width": self.border.value()})
        )
        self.tint_color = "#ffffff"
        self.tint_button = self.button(material_box, "Tint color…", self.pick_tint, "colorize")
        self.tint = self.spin(0, 100, 0)
        form.addRow("Tint opacity %", self.tint)
        self.tint.editingFinished.connect(self.apply_tint)
        shape = QGroupBox("Shape tween")
        shape_form = QFormLayout(shape)
        self.morph = QComboBox()
        self.morph.addItems(["ellipse", "rectangle", "triangle", "diamond", "star"])
        shape_form.addRow("Target", self.morph)
        self.morph.currentTextChanged.connect(self.choose_morph)
        self.mix = self.spin(0, 100, 0)
        shape_form.addRow("Mix %", self.mix)
        self.mix.editingFinished.connect(
            lambda: self.edit_look({"shape.mix": self.mix.value() / 100})
        )
        material_box.addWidget(shape)
        self.shape_group = shape
        self.auto = QCheckBox("Auto key changes at the playhead")
        self.auto.toggled.connect(window.viewmodel.animation_editor.set_auto_key)
        skin.addWidget(self.auto)
        self.skin_toggle = self.section(skin, "Saved skins", self.skin_choices)
        skin.addStretch()
        clothing = self.page("Clothing")
        self.saved_sets_button = QToolButton()
        self.saved_sets_button.setText("Saved outfit sets")
        self.saved_sets_button.setIcon(window.icons.icon("checkroom"))
        self.saved_sets_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.saved_sets_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.saved_sets_menu = QMenu(self.saved_sets_button)
        self.saved_sets_menu.aboutToShow.connect(self.populate_saved_sets)
        self.saved_sets_button.setMenu(self.saved_sets_menu)
        clothing.addWidget(self.saved_sets_button)
        self.outfits = QTreeWidget(self)
        self.outfits.setHeaderLabels(["Clothing groups / variations"])
        self.outfits.setMinimumHeight(200)
        self.outfits.itemChanged.connect(self.switch_outfit)
        self.outfits.itemSelectionChanged.connect(self.outfit_changed)
        self.outfits.hide()
        self.outfit_groups = QComboBox()
        self.outfit_groups.setAccessibleName("Clothing category")
        self.outfit_groups.currentIndexChanged.connect(self.populate_clothing_cards)
        clothing.addWidget(self.outfit_groups)
        self.outfit_cards = QListWidget()
        self.outfit_cards.setAccessibleName("Replaceable clothing cards")
        configure_cards(self.outfit_cards)
        self.outfit_cards.currentItemChanged.connect(self.select_clothing_card)
        self.outfit_cards.itemChanged.connect(self.check_clothing_card)
        clothing.addWidget(self.outfit_cards, 1)
        self.outfit_name = QLineEdit()
        self.outfit_name.setPlaceholderText("Group or variation name")
        clothing.addWidget(self.outfit_name)
        row = QHBoxLayout()
        clothing.addLayout(row)
        self.button(row, "New group", self.add_outfit_group, "create_new_folder")
        self.button(row, "Open Assets to add artwork", self.show_assets, "perm_media")
        row.addStretch()
        self.multiple = QCheckBox("Allow several variations at once")
        self.multiple.clicked.connect(self.set_outfit_mode)
        clothing.addWidget(self.multiple)
        self.outfit_key = QCheckBox("Key choice at playhead")
        self.outfit_key.setChecked(True)
        clothing.addWidget(self.outfit_key)
        row = QHBoxLayout()
        clothing.addLayout(row)
        self.button(row, "Use selected parts as a variation", self.add_outfit, "checkroom")
        self.button(row, "Hide this group's clothing", self.hide_outfits, "visibility_off")
        self.button(row, "Set selected as default", self.default_outfit, "check")
        row.addStretch()
        hint = QLabel(
            "A variation can contain several image layers. Turn its check on to wear it; "
            "turn every check off to wear none."
        )
        hint.setWordWrap(True)
        hint.setObjectName("Muted")
        clothing.addWidget(hint)
        motions = self.page("Animations")
        self.motion = QComboBox()
        self.motion.hide()
        self.motion_list = QListWidget()
        configure_cards(self.motion_list)
        self.motion.currentIndexChanged.connect(self.motion_list.setCurrentRow)
        self.motion_list.setMinimumHeight(180)
        self.motion_list.setAccessibleName("Object animations")
        self.motion_list.currentRowChanged.connect(self.choose_motion)
        motions.addWidget(self.motion_list)
        row = QHBoxLayout()
        motions.addLayout(row)
        self.preview_button = self.button(row, "Preview", self.preview_motion, "play_arrow")
        self.button(row, "Edit keys", self.edit_motion, "edit")
        row.addStretch()
        self.motion_name = QLineEdit()
        self.motion_name.setPlaceholderText("Animation name, e.g. Walk")
        motions.addWidget(self.motion_name)
        row = QHBoxLayout()
        motions.addLayout(row)
        self.button(row, "New empty animation", self.new_motion, "add")
        self.button(row, "Duplicate", self.duplicate_motion, "content_copy")
        self.remove_motion_button = self.button(
            row, "Remove animation", self.remove_motion, "delete"
        )
        row.addStretch()
        form = QFormLayout()
        motions.addLayout(form)
        self.motion_start = self.spin(0, 100000, 0)
        self.duration = self.spin(0.01, 3600, 2)
        self.speed = self.spin(0.01, 100, 1)
        form.addRow("Start frame", self.motion_start)
        form.addRow("Duration · seconds", self.duration)
        form.addRow("Speed ×", self.speed)
        self.repeat = QCheckBox("Loop this motion inside the block")
        self.repeat.setChecked(True)
        motions.addWidget(self.repeat)
        self.button(motions, "Add to scene timeline", self.place_motion, "add_to_queue")
        self.motion_hint = QLabel(
            "Choose a ready motion, or create a named action and author its keys. "
            "Drag block edges in the timeline to trim duration."
        )
        self.motion_hint.setWordWrap(True)
        self.motion_hint.setObjectName("Muted")
        motions.addWidget(self.motion_hint)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.hide()
        box.addWidget(self.status)
        self.tabs.currentChanged.connect(self.page_changed)
        window.viewmodel.changed.connect(self.refresh)
        window.viewmodel.scene.changed.connect(self.follow_selection)
        window.viewmodel.animation_editor.auto_key_changed.connect(self.auto.setChecked)
        window.viewmodel.playback.changed.connect(self.refresh_values)
        window.viewmodel.content.changed.connect(self.refresh)
        self.all_parts.toggled.connect(self.refresh)

    @staticmethod
    def spin(minimum: float, maximum: float, value: float) -> QDoubleSpinBox:
        """Use shared numeric styling and commit only deliberately edited values."""
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        spin.setKeyboardTracking(False)
        return spin

    def page(self, label: str) -> QVBoxLayout:
        """Create a compact named section without a second independent document state."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 4, 2, 8)
        layout.setSpacing(9)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(widget)
        self.tabs.addTab(scroll, label)
        return layout

    def button(self, layout: Any, text: str, callback: Any, icon: str = "") -> QToolButton:
        """Create compact panel commands with descriptive tooltips and accessible labels."""
        button = compact_button(self.host.icons, text, icon or "add", callback)
        layout.addWidget(button)
        return button

    def show_page(self, page: str) -> None:
        """Navigate the composer using stable page names rather than positional inspector tabs."""
        aliases = {"parts": "tree", "bones": "tree", "animations": "motions"}
        self.tabs.setCurrentIndex(
            ("tree", "skin", "clothing", "motions").index(aliases.get(page, page))
        )

    def choose_actor(self) -> None:
        """Keep explicit attachment targets independent of incoming layer selection."""
        if not self.busy:
            self.manual_actor = self.actor.currentData()
            self.refresh()

    def follow_selection(self) -> None:
        """Follow scene picks while retaining the active isolated character as the workspace."""
        self.manual_actor = None
        self.refresh()

    def page_changed(self, index: int) -> None:
        """Retain one hierarchy across tasks; give secondary controls their own scroll area."""
        self.structure_host.setVisible(True)
        self.tabs.setVisible(index > 0)
        self.binding_toggle.setVisible(index == 0)
        self.binding_controls.setVisible(index == 0 and self.binding_toggle.isChecked())
        if hasattr(self.host, "object_edit"):
            self.host.object_edit.pages.setCurrentIndex(index)
            self.host.viewport.composer_artwork_only = self.host.object_edit.active and index > 0
            if index > 0 and self.workspace.sizes()[1] < 100:
                self.workspace.setSizes([240, 420])
            self.host.viewport.update()
        self.refresh()

    def show_assets(self) -> None:
        """Reveal the shared source library without changing the current Object Editor context."""
        self.host.docks["assets"].show()
        self.host.docks["assets"].raise_()

    def section(self, layout: QVBoxLayout, title: str, body: QWidget) -> QToolButton:
        """Keep optional controls available behind a compact, keyboard-accessible disclosure."""
        toggle = QToolButton()
        toggle.setText(title)
        toggle.setAccessibleName(title)
        toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toggle.setCheckable(True)
        toggle.setProperty("materialIcon", "chevron_right")
        toggle.setIcon(self.host.icons.icon("chevron_right"))
        toggle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(toggle)
        layout.addWidget(body)
        body.hide()

        def disclose(checked: bool) -> None:
            """Reflect disclosure state without rebuilding controls or clearing their values."""
            icon = "expand_more" if checked else "chevron_right"
            toggle.setProperty("materialIcon", icon)
            toggle.setIcon(self.host.icons.icon(icon))
            body.setVisible(checked)

        toggle.toggled.connect(disclose)
        return toggle

    def delete_parts(self) -> None:
        """Remove selected editable structure through the scene's normal reversible command."""
        self.host.scene_workspace.delete_selection()

    def add_folder(self, *, empty: bool = False) -> None:
        """Make new folders part of the edited character, even before adding image layers."""

        def apply() -> None:
            """Create an owned character folder and preserve the chosen parent relationship."""
            service = CharacterService(self.host.viewmodel.documents)
            mode = self.host.object_edit
            if mode.active and isinstance(service.records().get(mode.key), Group):
                keys = (
                    ()
                    if empty
                    else tuple(
                        key
                        for key in self.host.viewmodel.scene.selected
                        if key != mode.key
                        and isinstance(service.records().get(key), (Group, SceneObject))
                    )
                )
                folder = service.group(keys, "Parts folder")
                service.move_entries((folder,), mode.key)
                return
            actor = self.actor.currentData()
            if not actor:
                actor = ImageRigService(self.host.viewmodel.documents).convert(self.scope())
            members = service.members(actor)
            keys = (
                tuple(
                    k
                    for k in self.host.viewmodel.scene.selected
                    if k in members and isinstance(service.record(k), (SceneObject, Group))
                )
                if not empty
                else ()
            )
            service.part_group(actor, keys)

        self.run(apply)

    def rename_object(self) -> None:
        """Rename the active character or solid from its clearly labelled composer header."""
        if self.busy or not self.host.object_edit.active:
            return
        mode = self.host.object_edit
        service = CharacterService(self.host.viewmodel.documents)
        actor = next((c for c in service.scene.characters if c.skeleton_id in mode.ids), None)
        name = self.name.text().strip()
        if not name:
            return
        entry = service.records().get(mode.key)
        if isinstance(entry, Group):
            if entry.name != name:
                self.run(lambda: service.rename(entry.id, name))
        elif actor:
            if actor.name != name:
                self.run(lambda: service.rename_character(actor.id, name))
        else:
            keys = service.meshes_for((mode.key,))
            if keys:
                owner = str(service.mesh(keys[0]).object_id)
                if service.record(owner).name != name:
                    self.run(lambda: service.rename(owner, name))

    def choose_paint(self, index: int) -> None:
        """Select a visual swatch without changing authored colors."""
        if not self.busy and index >= 0:
            item = self.color_list.item(index)
            if item:
                self.paints.setCurrentIndex(
                    next(
                        (
                            i
                            for i in range(self.paints.count())
                            if self.paints.itemData(i) == item.data(Qt.ItemDataRole.UserRole + 1)
                        ),
                        -1,
                    )
                )

    def choose_morph(self, kind: str) -> None:
        """Changing an enabled shape target is an explicit edit, without an extra Apply step."""
        if not self.busy and self.morph.isEnabled():
            self.set_morph()

    def choose_motion(self, index: int) -> None:
        """Play and loop a clicked action; ordinary refreshes remain signal-blocked."""
        if not self.busy and index >= 0:
            self.motion.setCurrentIndex(index)
            vm = self.host.viewmodel
            if clip := self.motion.currentData():
                if vm.documents.selected_clip_id != clip:
                    vm.playback.select_clip(clip)
                    vm.animation_editor.bind(vm.documents)
                if vm.playback.session:
                    vm.playback.session.set_loop(True)
                    if not vm.playback.session.playback.is_playing:
                        vm.playback.play_pause()

    def change_object_view(self, view: str) -> None:
        """Select saved artwork or an empty editable slot without regenerating the Object."""
        if not self.busy:
            from rigora.presentation.object_views import change_view

            change_view(self.host, self.motion_owner(), view)

    def motion_owner(self) -> str:
        """Use the compound object for actions, including objects with no images or skeleton."""
        mode = self.host.object_edit
        document = self.host.viewmodel.documents
        if mode.active and mode.document is not document:
            return ""
        key = mode.key if mode.active else str(self.actor.currentData() or "")
        signature = id(document.project), key
        if signature != self.motion_owner_source:
            self.motion_owner_source = signature
            self.motion_owner_valid = bool(
                document.project and key and key in CharacterService(document).records()
            )
        return key if self.motion_owner_valid else ""

    def preview_motion(self) -> None:
        """Preview the chosen character action with the common looping transport."""
        vm = self.host.viewmodel
        if not self.motion.currentData():
            return
        if vm.documents.selected_clip_id != self.motion.currentData():
            vm.playback.select_clip(self.motion.currentData())
            vm.animation_editor.bind(vm.documents)
        if vm.playback.session:
            vm.playback.session.set_loop(True)
        vm.playback.play_pause()

    def populate_saved_sets(self) -> None:
        """Offer complete retained Creator outfits through the same undoable appearance service."""
        self.saved_sets_menu.clear()
        owner = self.motion_owner()
        if not owner:
            return
        service = CharacterService(self.host.viewmodel.documents)
        for name in service.saved_outfit_sets(owner):
            self.saved_sets_menu.addAction(name).triggered.connect(
                lambda checked=False, key=name: self.run(
                    lambda: CharacterService(self.host.viewmodel.documents).apply_outfit_set(
                        owner, key, auto_key=self.outfit_key.isChecked()
                    )
                )
            )

    def outfit_changed(self) -> None:
        """Reflect the selected group's single/stacked clothing policy."""
        if self.busy:
            return
        try:
            group_id, _ = self.outfit_selection()
            service = CharacterService(self.host.viewmodel.documents)
            actor = service.record(self.motion_owner())
            group = next(g for g in actor.extra.get("outfits", ()) if g["id"] == group_id)
            with QSignalBlocker(self.multiple):
                self.multiple.setChecked(group["multiple"])
        except (ProjectError, StopIteration):
            pass

    def set_outfit_mode(self) -> None:
        """Apply the clothing policy to the selected group, preserving its variant images."""
        self.run(
            lambda: CharacterService(self.host.viewmodel.documents).outfit_mode(
                self.motion_owner(), self.outfit_selection()[0], self.multiple.isChecked()
            )
        )

    def import_images(self, clothing: bool) -> None:
        """Choose native multi-file import and adopt its parts directly into the edited object."""
        from rigora.presentation.widgets.file_dialogs import choose_open_files

        paths = choose_open_files(
            self.host,
            "Add clothing" if clothing else "Add image parts",
            "",
            "Artwork (*.svg *.png *.jpg *.jpeg *.ora *.psd)",
        )
        if paths:
            self.host.add_external_assets(
                paths, place=True, on_adopt=self.host.object_edit.adoption(clothing=clothing)
            )

    def scope(self) -> tuple[str, ...]:
        """Resolve actual selected images/folders, with an explicit whole-character override."""
        vm = self.host.viewmodel
        if not vm.documents.project:
            return ()
        service = CharacterService(vm.documents)
        actor = next(
            (c for c in service.scene.characters if c.id == self.actor.currentData()), None
        )
        mode = getattr(self.host, "object_edit", None)
        if self.all_parts.isChecked() and mode and mode.active and self.tabs.currentIndex() == 1:
            return tuple(m.id for m in service.scene.meshes if m.object_id in mode.ids)
        if self.all_parts.isChecked() and actor and self.tabs.currentIndex() == 1:
            return actor.mesh_ids
        selected = service.meshes_for(
            tuple(k for k in vm.scene.selected if not mode or not mode.active or k in mode.ids)
        )
        if mode and mode.active:
            selected = tuple(k for k in selected if service.mesh(k).object_id in mode.ids)
        if selected:
            return selected
        if actor:
            return tuple(
                k
                for k in actor.mesh_ids
                if not mode or not mode.active or service.mesh(k).object_id in mode.ids
            )[:1]
        return tuple(m.id for m in service.scene.meshes if m.id == vm.mesh.mesh_id)

    def run(self, operation: Any) -> None:
        """Publish one command, preserve ownership, and show useful validation messages."""
        self.host.viewmodel.playback.pause()
        try:
            with self.host.viewmodel.documents.command_group("Edit character"):
                operation()
            self.status.setText("")
            self.host.viewmodel.changed.emit()
        except (ProjectError, ValueError, KeyError) as error:
            self.status.setText(str(error))
        self.status.setVisible(bool(self.status.text()))

    def refresh(self) -> None:
        """Refresh only immutable descriptors; inspecting a palette never writes a stage."""
        if self.busy or not self.isVisible():
            return
        states = [
            (view, ItemViewState.capture(view, role))
            for view, role in (
                (self.color_list, Qt.ItemDataRole.UserRole + 1),
                (self.outfits, Qt.ItemDataRole.UserRole),
                (self.outfit_cards, Qt.ItemDataRole.UserRole),
                (self.motion_list, Qt.ItemDataRole.UserRole),
            )
        ]
        self.busy = True
        try:
            vm = self.host.viewmodel
            if not vm.documents.project:
                self.setEnabled(False)
                return
            self.setEnabled(True)
            service = CharacterService(vm.documents)
            current = self.actor.currentData()
            selected = service.meshes_for(vm.scene.selected)
            owner = service.owner(selected[0]) if selected else None
            mode = getattr(self.host, "object_edit", None)
            if mode and mode.active:
                owner = next(
                    (c for c in service.scene.characters if c.skeleton_id in mode.ids), None
                )
            if self.manual_actor is None and (owner or mode and mode.active):
                current = owner.id if owner else None
            with QSignalBlocker(self.actor):
                self.actor.clear()
                self.actor.addItem("Solid objects / choose character", None)
                for entry in service.scene.characters:
                    self.actor.addItem(entry.name, entry.id)
                self.actor.setCurrentIndex(max(0, self.actor.findData(current)))
            actor = next(
                (c for c in service.scene.characters if c.id == self.actor.currentData()), None
            )
            from rigora.application_services.object_views import ObjectViewsService

            view_key = mode.key if mode and mode.active else str(self.actor.currentData() or "")
            with QSignalBlocker(self.object_views):
                try:
                    views = ObjectViewsService(vm.documents)
                    from rigora.domain.object_views import VIEW_SLOTS

                    choices = VIEW_SLOTS
                    if (
                        tuple(
                            self.object_views.itemText(i) for i in range(self.object_views.count())
                        )
                        != choices
                    ):
                        self.object_views.clear()
                        self.object_views.addItems(choices)
                    active_view = views.edited_view(view_key)
                    if not vm.content.busy:
                        self.object_views.setCurrentText(active_view)
                    self.object_views.setEnabled(len(choices) > 1 and not vm.content.busy)
                except ProjectError:
                    self.object_views.setEnabled(False)
            scope = self.scope()
            self.summary.setText("Character" if actor else "Object")
            previous_bone = self.bones.currentData()
            self.bones.clear()
            for rig in service.scene.skeletons:
                rig_label = next(
                    (c.name for c in service.scene.characters if c.skeleton_id == rig.id), rig.name
                )
                for bone in rig.bones:
                    if mode and mode.active and bone.id not in mode.ids:
                        continue
                    self.bones.addItem(
                        bone.name if mode and mode.active else f"{rig_label} › {bone.name}", bone.id
                    )
            target = vm.rig.selected[0] if vm.rig.selected else previous_bone
            self.bones.setCurrentIndex(max(0, self.bones.findData(target)))
            self.binding_summary.setText(
                f"{len(scope)} selected image part(s). Choose a bone to bind or reattach."
                if scope
                else "Select an image part in Layers to attach it to a bone."
            )
            with QSignalBlocker(self.paints):
                paint = self.paints.currentData()
                self.paints.clear()
                found = set()
                for mesh_id in scope:
                    mesh = service.mesh(mesh_id)
                    if not mesh.asset_id:
                        continue
                    for role, color in palette(vm.documents.read_asset(mesh.asset_id)):
                        if (role, color) not in found:
                            self.paints.addItem(f"{role}: {color}", (role, color))
                            found.add((role, color))
                self.paints.setCurrentIndex(
                    next(
                        (i for i in range(self.paints.count()) if self.paints.itemData(i) == paint),
                        0,
                    )
                )
            self.color_list.clear()
            from PySide6.QtGui import QIcon, QPixmap

            for i in range(self.paints.count()):
                role, color = self.paints.itemData(i)
                swatch = QPixmap(56, 44)
                swatch.fill(QColor(color))
                color_item = QListWidgetItem(QIcon(swatch), f"{color.upper()}  ·  {role}")
                color_item.setData(Qt.ItemDataRole.UserRole + 1, (role, color))
                self.color_list.addItem(color_item)
            self.color_list.setCurrentRow(self.paints.currentIndex())
            has_colors = self.paints.count() > 0
            self.color_heading.setVisible(has_colors)
            self.color_list.setVisible(has_colors)
            self.color_hint.setVisible(not has_colors)
            self.paint_button.setVisible(has_colors)
            previous_outfit = self.outfits.currentItem()
            outfit_key = (
                previous_outfit.data(0, Qt.ItemDataRole.UserRole) if previous_outfit else None
            )
            self.outfits.clear()
            self.saved_sets_button.setVisible(
                bool(self.motion_owner() and service.saved_outfit_sets(self.motion_owner()))
            )
            for group in (
                service.appearance_groups(self.motion_owner(), "outfits")
                if self.motion_owner()
                else ()
            ):
                row = QTreeWidgetItem(self.outfits, [group["name"]])
                row.setIcon(0, self.host.icons.icon("folder"))
                row.setData(0, Qt.ItemDataRole.UserRole, (group["id"], None))
                row.setExpanded(True)
                if (group["id"], None) == outfit_key:
                    self.outfits.setCurrentItem(row)
                for variant in group["variants"]:
                    item = QTreeWidgetItem(row, [variant["name"]])
                    variant_mesh = next(
                        (m for m in service.scene.meshes if m.id in variant["meshes"]), None
                    )
                    item.setIcon(
                        0,
                        self.host.asset_icon(variant_mesh.asset_id)
                        if variant_mesh
                        else self.host.icons.icon("image"),
                    )
                    item.setData(0, Qt.ItemDataRole.UserRole, (group["id"], variant["id"]))
                    item.setCheckState(
                        0,
                        Qt.CheckState.Checked
                        if variant.get("visible")
                        else Qt.CheckState.Unchecked,
                    )
                    if (group["id"], variant["id"]) == outfit_key:
                        self.outfits.setCurrentItem(item)
            selected_group = outfit_key[0] if outfit_key else self.outfit_groups.currentData()
            with QSignalBlocker(self.outfit_groups):
                self.outfit_groups.clear()
                for i in range(self.outfits.topLevelItemCount()):
                    group_row = self.outfits.topLevelItem(i)
                    if group_row is None:
                        continue
                    self.outfit_groups.addItem(
                        group_row.text(0), group_row.data(0, Qt.ItemDataRole.UserRole)[0]
                    )
                self.outfit_groups.setCurrentIndex(
                    max(0, self.outfit_groups.findData(selected_group))
                )
            self.populate_clothing_cards()
            motion_owner = self.motion_owner()
            previous = self.motion.currentData()
            with QSignalBlocker(self.motion):
                self.motion.clear()
                clips = (
                    vm.documents.context_clips()
                    if motion_owner and vm.documents.animation_context == motion_owner
                    else service.motions(motion_owner)
                    if motion_owner
                    else ()
                )
                for clip in clips:
                    self.motion.addItem(clip.name, clip.id)
                self.motion.setCurrentIndex(max(0, self.motion.findData(previous)))
            self.remove_motion_button.setEnabled(bool(self.motion.currentData()))
            self.motion_list.clear()
            for i in range(self.motion.count()):
                title = self.motion.itemText(i)
                icon = self.host.icons.icon(
                    "directions_run"
                    if title == "Run"
                    else "directions_walk"
                    if title == "Walk"
                    else "accessibility_new"
                )
                motion_item = QListWidgetItem(icon, title.replace(" · ", "\n"))
                motion_item.setData(Qt.ItemDataRole.UserRole, self.motion.itemData(i))
                self.motion_list.addItem(motion_item)
            self.motion_list.setCurrentRow(self.motion.currentIndex())
            self.motion_hint.setText(
                "Preview or add this motion. Drag its timeline edges to trim the block."
                if self.motion.count()
                else "No motions yet. Create a named action, author its keys, then reuse it here."
            )
            self.convert_button.setVisible(actor is None and self.tabs.currentIndex() == 0)
            mode = getattr(self.host, "object_edit", None)
            if mode:
                for index in (2, 3):
                    enabled = bool(motion_owner)
                    mode.pages.setTabEnabled(index, enabled)
                    mode.pages.setTabToolTip(
                        index, "" if enabled else "Select an Object to edit its saved options."
                    )
            if actor:
                count = sum(
                    len(r.bones) for r in service.scene.skeletons if r.id == actor.skeleton_id
                )
                self.summary.setToolTip(f"{len(actor.mesh_ids)} parts · {count} bones")
            if not self.name.hasFocus():
                self.name.setText(
                    service.record(mode.key).name
                    if mode and mode.active and isinstance(service.records().get(mode.key), Group)
                    else actor.name
                    if actor
                    else service.record(str(service.mesh(scope[0]).object_id)).name
                    if scope
                    else ""
                )
            self.structure_host.setVisible(bool(mode and mode.active))
        finally:
            self.busy = False
            for view, state in states:
                state.restore(view)
            self.choose_paint(self.color_list.currentRow())
        self.refresh_values()
        self.outfit_changed()

    def refresh_values(self) -> None:
        """Reflect evaluated scalar controls without rebuilding palettes on playback frames."""
        if self.busy or not self.isVisible() or not self.host.viewmodel.documents.project:
            return
        vm = self.host.viewmodel
        scope = self.scope()
        mesh = vm.documents.animation.pose.meshes.get(scope[0]) if scope else None
        look = mesh.appearance if mesh else {}
        self.busy = True
        try:
            self.border.setValue(float(look.get("stroke_width", -1)))
            if self.tabs.currentIndex() == 2 and self.motion_owner():
                service = CharacterService(vm.documents)
                variants = {
                    (g["id"], v["id"]): v
                    for g in service.appearance_groups(self.motion_owner(), "outfits")
                    for v in g["variants"]
                }
                pose = vm.documents.animation.pose
                for i in range(self.outfits.topLevelItemCount()):
                    row = self.outfits.topLevelItem(i)
                    if row is None:
                        continue
                    for j in range(row.childCount()):
                        outfit_item = row.child(j)
                        if outfit_item is None:
                            continue
                        variant = variants.get(outfit_item.data(0, Qt.ItemDataRole.UserRole), {})
                        visible = service.variant_visible(variant, pose)
                        outfit_item.setCheckState(
                            0,
                            Qt.CheckState.Checked if visible else Qt.CheckState.Unchecked,
                        )
                with QSignalBlocker(self.outfit_cards):
                    for i in range(self.outfit_cards.count()):
                        card = self.outfit_cards.item(i)
                        variant = variants.get(card.data(Qt.ItemDataRole.UserRole), {})
                        visible = service.variant_visible(variant, pose)
                        card.setCheckState(
                            Qt.CheckState.Checked if visible else Qt.CheckState.Unchecked
                        )
            tint = look.get("tint", {})
            self.tint.setValue(float(tint.get("amount", 0)) * 100)
            self.tint_color = QColor(*(round(tint.get(c, 255)) for c in ("r", "g", "b"))).name()
            from PySide6.QtGui import QIcon, QPixmap

            tint_swatch = QPixmap(24, 20)
            tint_swatch.fill(QColor(self.tint_color))
            self.tint_button.setIcon(QIcon(tint_swatch))
            for i in range(self.paints.count()):
                role, source = self.paints.itemData(i)
                paint = next(
                    (
                        p
                        for p in look.get("palette", ())
                        if p["source"] == source and p["role"] == role
                    ),
                    None,
                )
                current = (
                    QColor(*(round(paint[c]) for c in ("r", "g", "b"))).name() if paint else source
                )
                item = self.color_list.item(i)
                if item and item.data(Qt.ItemDataRole.UserRole) != current:
                    swatch = QPixmap(56, 44)
                    swatch.fill(QColor(current))
                    item.setIcon(QIcon(swatch))
                    item.setText(f"{current.upper()}  ·  {role}")
                    item.setData(Qt.ItemDataRole.UserRole, current)
                    item.setToolTip(f"Original {source} · shared {role} color")
            playing = bool(
                vm.playback.session
                and vm.playback.session.playback.is_playing
                and vm.documents.selected_clip_id == self.motion.currentData()
            )
            self.preview_button.setText("Pause" if playing else "Preview")
            self.preview_button.setToolTip("Pause" if playing else "Preview")
            self.preview_button.setIcon(self.host.icons.icon("pause" if playing else "play_arrow"))
            shape = look.get("shape", {})
            self.shape_group.setVisible(bool(shape))
            self.mix.setEnabled(bool(shape))
            self.morph.setEnabled(bool(shape))
            self.mix.setValue(float(shape.get("mix", 0)) * 100)
            if shape:
                self.morph.setCurrentText(shape.get("end", shape["start"]))
            with QSignalBlocker(self.auto):
                self.auto.setChecked(vm.animation_editor.auto_key)
        finally:
            self.busy = False

    def convert(self) -> None:
        """Make selected solid images one actor without inventing dummy bones."""
        self.run(
            lambda: ImageRigService(self.host.viewmodel.documents).convert(
                self.scope(), self.name.text()
            )
        )

    def attach(self) -> None:
        """Use the chosen bone for deforming or rigid attachment, including reassignment."""
        from rigora.application_services.bindings import BindingService

        def apply() -> None:
            """Bind each scoped image using the selected bone and attachment mode."""
            BindingService(self.host.viewmodel.documents).bind(
                self.scope(), self.bones.currentData(), rigid=self.rigid.isChecked()
            )

        self.run(apply)

    def detach(self) -> None:
        """Release actual selection rather than silently choosing the actor's first image."""
        self.host.unbind_selection()

    def flip(self, vertical: bool) -> None:
        """Mirror facing about the actor bounds, optionally keying the common transform channels."""

        def apply() -> None:
            """Mirror scoped image owners using the current Auto key policy."""
            service = CharacterService(self.host.viewmodel.documents)
            service.auto_key = self.auto.isChecked()
            service.flip(
                tuple(
                    str(service.mesh(k).object_id)
                    for k in self.scope()
                    if service.mesh(k).object_id
                ),
                vertical=vertical,
            )

        self.run(apply)

    def pick_color(
        self, initial: str, operation: Callable[[AppearanceService, str], None]
    ) -> str | None:
        """Preview colors on scratch poses; Apply publishes one undo step, Cancel restores."""
        vm = self.host.viewmodel
        vm.playback.pause()
        scene = vm.scene
        scene.begin_preview()
        dialog = CustomDialog(self.host, "Choose color")
        box = QVBoxLayout(dialog.content)
        picker = QColorDialog(QColor(initial))
        picker.setWindowFlags(Qt.WindowType.Widget)
        picker.setOption(QColorDialog.ColorDialogOption.NoButtons)
        picker.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog)

        def preview(color: QColor) -> None:
            """Evaluate against the captured revision without changing saved artwork."""
            if color.isValid():
                scene.preview_edit(
                    lambda service: operation(AppearanceService(service.document), color.name()),
                    "Edit skin color",
                )

        picker.currentColorChanged.connect(preview)
        box.addWidget(picker)
        actions = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        actions.setObjectName("ColorDialogActions")
        actions.button(QDialogButtonBox.StandardButton.Ok).setText("Apply")
        actions.accepted.connect(dialog.accept)
        actions.rejected.connect(dialog.reject)
        box.addWidget(actions)
        try:
            if dialog.exec():
                preview(picker.currentColor())
                if scene.error:
                    self.status.setText(scene.error)
                    self.status.show()
                    return None
                scene.finish_preview()
                return picker.currentColor().name()
            return None
        finally:
            scene.cancel_preview()
            self.host.update_animation()
            dialog.deleteLater()

    def paint_color(self, item: QListWidgetItem | None = None) -> None:
        """Replace a detected role/color across the current image or explicit group scope."""
        swatch = item if isinstance(item, QListWidgetItem) else self.color_list.currentItem()
        paint = swatch.data(Qt.ItemDataRole.UserRole + 1) if swatch else self.paints.currentData()
        if not paint:
            self.status.setText(
                "This source has no editable color groups. Use Tint to recolor the whole image."
            )
            self.status.show()
            return
        initial = (swatch.data(Qt.ItemDataRole.UserRole) if swatch else None) or paint[1]
        keys, auto = self.scope(), self.auto.isChecked()
        self.pick_color(
            initial,
            lambda service, color: service.paint(keys, paint[0], paint[1], color, auto_key=auto),
        )

    def pick_tint(self) -> None:
        """Choose tint color without forcing an opaque result."""
        keys, auto, amount = self.scope(), self.auto.isChecked(), max(20, self.tint.value())

        def tint(service: AppearanceService, value: str) -> None:
            """Keep tint controls unchanged until the user accepts the live result."""
            color = QColor(value)
            service.edit(
                keys,
                {
                    "tint.r": color.red(),
                    "tint.g": color.green(),
                    "tint.b": color.blue(),
                    "tint.amount": amount / 100,
                },
                auto_key=auto,
            )

        color = self.pick_color(self.tint_color, tint)
        if color:
            self.tint_color = color
            with QSignalBlocker(self.tint):
                self.tint.setValue(amount)

    def apply_tint(self) -> None:
        """Route tint RGB and amount through the same appearance key channels."""
        color = QColor(self.tint_color)
        self.edit_look(
            {
                "tint.r": color.red(),
                "tint.g": color.green(),
                "tint.b": color.blue(),
                "tint.amount": self.tint.value() / 100,
            }
        )

    def edit_look(self, values: dict[str, float]) -> None:
        """Commit a color, border or morph control to base data or Auto key."""
        self.run(
            lambda: AppearanceService(self.host.viewmodel.documents).edit(
                self.scope(), values, auto_key=self.auto.isChecked()
            )
        )

    def set_morph(self) -> None:
        """Choose shape tween correspondence explicitly before keying its mix."""

        def apply() -> None:
            """Set explicit shape correspondence on every scoped mesh before tween keying."""
            for key in self.scope():
                AppearanceService(self.host.viewmodel.documents).morph_target(
                    key, self.morph.currentText()
                )

        self.run(apply)

    def add_outfit_group(self) -> None:
        """Create an exclusive or multi-visible wardrobe group."""
        self.run(
            lambda: CharacterService(self.host.viewmodel.documents).wardrobe_group(
                self.motion_owner(),
                self.outfit_name.text(),
                multiple=self.multiple.isChecked(),
            )
        )

    def populate_clothing_cards(self, *_: object) -> None:
        """Present the selected wardrobe category as thumbnail cards with visible wear checks."""
        state = ItemViewState.capture(self.outfit_cards)
        key = self.outfit_groups.currentData()
        row = None
        for i in range(self.outfits.topLevelItemCount()):
            candidate = self.outfits.topLevelItem(i)
            if candidate is not None and candidate.data(0, Qt.ItemDataRole.UserRole)[0] == key:
                row = candidate
                break
        current = self.outfits.currentItem()
        selected = current.data(0, Qt.ItemDataRole.UserRole) if current else None
        with QSignalBlocker(self.outfit_cards):
            self.outfit_cards.clear()
            if row is not None:
                if not selected or selected[0] != key:
                    self.outfits.setCurrentItem(row)
                for i in range(row.childCount()):
                    child = row.child(i)
                    if child is None:
                        continue
                    card = QListWidgetItem(child.icon(0), child.text(0))
                    card.setData(Qt.ItemDataRole.UserRole, child.data(0, Qt.ItemDataRole.UserRole))
                    card.setCheckState(child.checkState(0))
                    card.setToolTip(
                        "Check to wear · uncheck to hide · select to change the default"
                    )
                    self.outfit_cards.addItem(card)
                    if card.data(Qt.ItemDataRole.UserRole) == selected:
                        self.outfit_cards.setCurrentItem(card)
        state.restore(self.outfit_cards)

    def clothing_row(self, key: object) -> QTreeWidgetItem | None:
        """Resolve a card's stable group/variant identity in the shared wardrobe model."""
        for i in range(self.outfits.topLevelItemCount()):
            row = self.outfits.topLevelItem(i)
            if row is None:
                continue
            for j in range(row.childCount()):
                child = row.child(j)
                if child is not None and child.data(0, Qt.ItemDataRole.UserRole) == key:
                    return child
        return None

    def select_clothing_card(
        self, item: QListWidgetItem | None, previous: QListWidgetItem | None = None
    ) -> None:
        """Select a wardrobe variation without changing its visibility or authoring a key."""
        if not self.busy and item is not None:
            row = self.clothing_row(item.data(Qt.ItemDataRole.UserRole))
            if row is not None:
                self.outfits.setCurrentItem(row)

    def check_clothing_card(self, item: QListWidgetItem) -> None:
        """Wear/hide a checked card using the existing exclusivity and animation controls."""
        if not self.busy:
            row = self.clothing_row(item.data(Qt.ItemDataRole.UserRole))
            if row is not None:
                row.setCheckState(0, item.checkState())

    def outfit_selection(self) -> tuple[str, str | None]:
        """Resolve group and optional variant from the selected wardrobe row."""
        row = self.outfits.currentItem()
        if row is None:
            raise ProjectError("Choose an outfit group first.")
        group, variant = row.data(0, Qt.ItemDataRole.UserRole)
        return str(group), str(variant) if variant else None

    def add_outfit(self) -> None:
        """Store all currently selected scene images as one outfit option."""
        self.run(
            lambda: CharacterService(self.host.viewmodel.documents).add_variant(
                self.motion_owner(),
                self.outfit_selection()[0],
                self.scope(),
                self.outfit_name.text(),
            )
        )

    def switch_outfit(self, item: QTreeWidgetItem, column: int) -> None:
        """Capture wardrobe choices before a queued edit can rebuild their Qt item views."""
        if self.busy:
            return
        group, variant = item.data(0, Qt.ItemDataRole.UserRole)
        if variant:
            owner = self.motion_owner()
            visible = item.checkState(0) == Qt.CheckState.Checked
            auto_key = self.outfit_key.isChecked()
            document = self.host.viewmodel.documents
            context = document.animation_context

            def commit() -> None:
                """Apply stable identities only if this is still the same object workspace."""
                if (
                    self.host.viewmodel.documents is document
                    and document.animation_context == context
                    and self.motion_owner() == owner
                ):
                    self.run(
                        lambda: CharacterService(document).show_variant(
                            owner, group, variant, visible, auto_key=auto_key
                        )
                    )

            QTimer.singleShot(0, self, commit)

    def default_outfit(self) -> None:
        """Define the clothing group's default variation, or none when its group is selected."""
        self.run(
            lambda: CharacterService(self.host.viewmodel.documents).appearance_default(
                self.motion_owner(), "outfits", *self.outfit_selection()
            )
        )

    def hide_outfits(self) -> None:
        """Hide every variant in one wardrobe group."""
        self.run(
            lambda: CharacterService(self.host.viewmodel.documents).show_variant(
                self.motion_owner(),
                self.outfit_selection()[0],
                None,
                False,
                auto_key=self.outfit_key.isChecked(),
            )
        )

    def edit_motion(self) -> None:
        """Open the original named motion in the existing key/curve editor."""
        if self.motion.currentData():
            self.host.viewmodel.playback.select_clip(self.motion.currentData())
            self.host.viewmodel.animation_editor.bind(self.host.viewmodel.documents)
            self.host.timeline.pages.setCurrentIndex(0)

    def new_motion(self) -> None:
        """Start a real named clip for animation authoring."""
        self.run(
            lambda: CharacterService(self.host.viewmodel.documents).new_motion(
                self.motion_owner(), self.motion_name.text() or "Animation"
            )
        )
        self.motion.setCurrentIndex(
            max(0, self.motion.findData(self.host.viewmodel.documents.selected_clip_id))
        )

    def duplicate_motion(self) -> None:
        """Keep a source clip intact while preparing an independently editable variation."""
        self.run(
            lambda: CharacterService(self.host.viewmodel.documents).new_motion(
                self.motion_owner(),
                self.motion_name.text() or "Motion copy",
                self.motion.currentData(),
            )
        )
        self.motion.setCurrentIndex(
            max(0, self.motion.findData(self.host.viewmodel.documents.selected_clip_id))
        )

    def remove_motion(self) -> None:
        """Confirm source deletion and explain linked Scene removals before publishing one edit."""
        owner, clip_id = self.motion_owner(), self.motion.currentData()
        if not owner or not clip_id:
            return
        vm = self.host.viewmodel
        source = next(
            (c for c in CharacterService(vm.documents).motions(owner) if c.id == clip_id), None
        )
        if source is None:
            return
        placements = {
            t.extra["motion_window"]["id"]
            for timeline in vm.documents.scene.timelines
            for t in timeline.tracks
            if t.extra.get("motion_window", {}).get("source") == clip_id
        }
        message = f'Remove animation "{source.name}"?'
        if placements:
            message += f"\n\nThis also removes {len(placements)} linked Scene placement(s)."
        message += "\n\nYou can undo this change."
        vm.playback.pause()
        if (
            ask_question(
                self,
                "Remove animation?",
                message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            == QMessageBox.StandardButton.Yes
        ):
            self.run(lambda: CharacterService(vm.documents).remove_motion(owner, clip_id))

    def place_motion(self) -> None:
        """Place a named motion block and switch to the scene arrangement."""
        owner, clip = self.motion_owner(), self.motion.currentData()
        self.host.object_edit.exit()
        self.run(
            lambda: CharacterService(self.host.viewmodel.documents).place_motion(
                owner,
                clip,
                self.motion_start.value(),
                self.duration.value(),
                self.speed.value(),
                self.repeat.isChecked(),
            )
        )
        self.host.timeline.pages.setCurrentIndex(0)
