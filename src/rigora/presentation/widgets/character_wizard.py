"""Visual independent Creator with square choices and isolated full-body playback."""

import math
import time
from dataclasses import replace
from typing import Any, cast

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from rigora.application_services.character_creation import (
    CharacterCreationService,
    character_preview_frame,
)
from rigora.application_services.creator_preview import stage_layout
from rigora.application_services.illustration_cache import cached_catalog, recipe_for
from rigora.domain.character_recipe import (
    FEELING_PRESETS,
    MOTION_CHOICES,
    STYLE_CHOICES,
    VIEWS,
    CharacterRecipe,
)
from rigora.domain.creator_options import (
    COMPONENT_CHOICES,
    OUTFIT_PRESETS,
    PLACEMENTS,
    choose,
    default_choice,
    outfit,
    outfit_values,
)
from rigora.domain.illustration_catalog import CREATOR_DESIGNS, design_by_id
from rigora.domain.project import ProjectError
from rigora.infrastructure.creator_backgrounds import background_source
from rigora.presentation.artwork import decode_artwork
from rigora.presentation.viewmodels.character_wizard import CharacterWizardModel
from rigora.presentation.widgets.asset_cards import (
    CARD_CELL,
    AssetCardDelegate,
    configure_card_grid,
    label_format,
)
from rigora.presentation.widgets.viewport import Viewport
from rigora.presentation.widgets.window_frame import CustomDialog


class CreatorCardDelegate(AssetCardDelegate):
    """Leave checkbox hit testing to the card's explicit, enlarged include target."""

    def editorEvent(self, event: Any, model: Any, option: Any, index: Any) -> bool:
        """Keep native checkbox editing out of the custom include hit target."""
        return False


class CreatorViewport(Viewport):
    """Keep the viewed scene center stable when the Creator layout changes size."""

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Retain manual zoom and pan using only a screen-space translation."""
        old, new = event.oldSize(), event.size()
        if self.has_project and old.width() > 0 and old.height() > 0:
            self.offset += QPointF(
                (new.width() - old.width()) / 2, (new.height() - old.height()) / 2
            )
        super().resizeEvent(event)


class ChoiceGrid(QListWidget):
    """A square card grid that grows to its contents inside the single outer scroller."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Own the isolated preview controls, option state and cancellable preparation worker."""
        super().__init__(parent)
        self._include_pressed: QListWidgetItem | None = None
        self.expand_to_contents = True
        configure_card_grid(self)
        self.setItemDelegate(CreatorCardDelegate(self))
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def resizeEvent(self, event: Any) -> None:
        """Keep every item reachable without introducing a nested scroll area."""
        super().resizeEvent(event)
        if not self.expand_to_contents:
            return
        columns = max(1, self.viewport().width() // CARD_CELL)
        height = math.ceil(max(1, self.count()) / columns) * CARD_CELL + self.frameWidth() * 2
        if self.height() != height:
            self.setFixedHeight(height)

    def mousePressEvent(self, event: Any) -> None:
        """Keep inclusion clicks out of the card's preview-selection route."""
        item = self.itemAt(event.position().toPoint())
        if (
            item is not None
            and item.flags() & Qt.ItemFlag.ItemIsUserCheckable
            and AssetCardDelegate.check_rect(self.visualItemRect(item)).contains(
                event.position().toPoint()
            )
        ):
            self._include_pressed = item
            event.accept()
            return
        self._include_pressed = None
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:
        """Toggle only the explicit checkbox and leave the visible default unchanged."""
        item = getattr(self, "_include_pressed", None)
        self._include_pressed = None
        if item is not None:
            if AssetCardDelegate.check_rect(self.visualItemRect(item)).contains(
                event.position().toPoint()
            ):
                item.setCheckState(
                    Qt.CheckState.Unchecked
                    if item.checkState() == Qt.CheckState.Checked
                    else Qt.CheckState.Checked
                )
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: Any) -> None:
        """Make Space toggle inclusion without treating a preview click as a check."""
        item = self.currentItem()
        if (
            event.key() == Qt.Key.Key_Space
            and item
            and item.flags() & Qt.ItemFlag.ItemIsUserCheckable
        ):
            item.setCheckState(
                Qt.CheckState.Unchecked
                if item.checkState() == Qt.CheckState.Checked
                else Qt.CheckState.Checked
            )
            event.accept()
            return
        super().keyPressEvent(event)


class OptionSection(QWidget):
    """Guarantee an owned vertical layout for disclosure content."""

    def __init__(self) -> None:
        """Own the isolated preview controls, option state and cancellable preparation worker."""
        super().__init__()
        QVBoxLayout(self)

    def layout(self) -> QLayout:
        """Return the content layout installed during construction."""
        return cast(QLayout, super().layout())


class CharacterWizard(CustomDialog):
    """Visual SVG authoring with independent preview, defaults and retained alternatives."""

    def __init__(self, parent: Any, source_format: str = "SVG", *, kind: str = "People") -> None:
        """Own the isolated preview controls, option state and cancellable preparation worker."""
        super().__init__(parent, "SVG Character Creation")
        if source_format != "SVG":
            raise ProjectError("Character Creation uses editable SVG artwork.")
        self.host = parent
        self.extension_presets: dict[str, CharacterRecipe] = {}
        self.document = parent.viewmodel.documents
        self.model = CharacterWizardModel(
            self, cache_root=cached_catalog(parent.viewmodel.content.library.cache_root)
        )
        self.recipe = recipe_for(
            next(
                d
                for d in CREATOR_DESIGNS
                if (d.anatomy not in ("human", "robot")) == (kind == "Animals")
            )
        )
        self.updating = True
        self.pending = ""
        self.motion_name = "Stand"
        self._preview_id = 0
        self._resume_frame = 0.0
        self._has_rig_preview = False
        self._frame_key: Any = None
        self._icon_id = 0
        self._time = time.monotonic()
        self._paint_pending: Any = None
        self._paint_timer = QTimer(self)
        self._paint_timer.setSingleShot(True)
        self._paint_timer.setInterval(40)
        self._paint_timer.timeout.connect(self.flush_paint)
        self.resize(1400, 920)
        self.setMinimumSize(900, 560)
        outer = QVBoxLayout(self.content)
        header = QHBoxLayout()
        title = QLabel("Character Creation")
        title.setStyleSheet("font-size:22px;font-weight:600;")
        header.addWidget(title)
        header.addStretch()
        header.addWidget(QLabel("Name"))
        self.name = QLineEdit(self.recipe.name)
        self.name.setAccessibleName("Character name")
        self.name.setMaximumWidth(230)
        self.name.editingFinished.connect(
            lambda: self.update_recipe(name=self.name.text().strip() or self.recipe.name)
        )
        header.addWidget(self.name)
        outer.addLayout(header)
        split = QSplitter()
        outer.addWidget(split, 1)
        stage = QWidget()
        stage_layout = QVBoxLayout(stage)
        stage_layout.setContentsMargins(0, 0, 0, 0)
        stage_layout.setSpacing(0)
        bar = QFrame()
        bar.setObjectName("CreatorPreviewBar")
        controls = QHBoxLayout(bar)
        controls.setContentsMargins(6, 4, 6, 4)
        controls.setSpacing(6)
        self.preview = CreatorViewport()
        self.preview.show_bones = False
        self.preview.composer_artwork_only = True
        self.preview.grid_visible = False
        self.preview.scene_hint = ""
        self.preview.setMinimumSize(300, 260)
        self.view = QComboBox()
        self.view.addItems(VIEWS)
        self.view.setAccessibleName("Character view")
        self.view.currentTextChanged.connect(lambda v: self.update_recipe(view=v))
        controls.addWidget(self.view)
        self.view_button = self.tool("visibility", "View options", lambda: None)
        self.view_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        view_menu = QMenu(self.view_button)
        for label, attribute in (
            ("Grid", "grid_visible"),
            ("Transparency", "checker_visible"),
            ("Camera border", "frame_visible"),
        ):
            action = view_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(bool(getattr(self.preview, attribute)))
            action.toggled.connect(
                lambda checked, key=attribute: self.set_view_option(key, checked)
            )
        view_menu.addSeparator()
        view_menu.addAction("Fit camera · F").triggered.connect(self.fit_preview)
        view_menu.addAction("Actual size · 100% · 1").triggered.connect(
            lambda: self.preview.zoom_at(1 / self.preview.zoom)
        )
        self.view_button.setMenu(view_menu)
        view_menu.addSeparator()
        self.adaptive_previews = view_menu.addAction("Preview choices on current character")
        self.adaptive_previews.setCheckable(True)
        self.adaptive_previews.setToolTip(
            "Off: fixed cached PNG previews. On: previews follow this character's "
            "proportions, view and colors."
        )
        self.adaptive_previews.toggled.connect(self.model.set_adaptive_cards)
        controls.addWidget(self.view_button)
        backgrounds = self.tool("wallpaper", "Preview background", lambda: None)
        backgrounds.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        background_menu = QMenu(backgrounds)
        for label in ("Transparent", "White", "Gray", "Black", "Studio", "Park", "Street"):
            background_menu.addAction(label).triggered.connect(
                lambda checked=False, name=label: self.set_background(name)
            )
        background_menu.addSeparator()
        background_menu.addAction("Custom color…").triggered.connect(self.choose_background)
        backgrounds.setMenu(background_menu)
        controls.addWidget(backgrounds)
        controls.addStretch()
        self.zoom_out = self.tool("zoom_out", "Zoom out", lambda: self.preview.zoom_at(1 / 1.2))
        self.zoom_in = self.tool("zoom_in", "Zoom in", lambda: self.preview.zoom_at(1.2))
        controls.addWidget(self.zoom_out)
        self.zoom_percent = QDoubleSpinBox()
        self.zoom_percent.setRange(0.1, 800)
        self.zoom_percent.setDecimals(1)
        self.zoom_percent.setSuffix(" %")
        self.zoom_percent.setSingleStep(10)
        self.zoom_percent.setKeyboardTracking(False)
        self.zoom_percent.setFixedWidth(91)
        self.zoom_percent.setAccessibleName("Preview zoom percent")
        self.zoom_percent.valueChanged.connect(
            lambda value: self.preview.zoom_at(value / 100 / self.preview.zoom)
        )
        self.preview.zoom_changed.connect(self.show_zoom)
        controls.addWidget(self.zoom_percent)
        controls.addWidget(self.zoom_in)
        controls.addWidget(self.tool("fit_screen", "Fit character", self.fit_character))
        stage_layout.addWidget(bar)
        stage_layout.addWidget(self.preview, 1)
        self.transport = QFrame(self.preview)
        self.transport.setObjectName("CreatorTransport")
        transport = QHBoxLayout(self.transport)
        transport.setContentsMargins(9, 3, 9, 3)
        self.play = self.tool("play_arrow", "Play / pause preview", self.toggle_play)
        self.play.setCheckable(True)
        self.repeat = self.tool("repeat", "Repeat preview", self.toggle_repeat)
        self.repeat.setCheckable(True)
        self.repeat.setChecked(True)
        transport.addWidget(self.play)
        self.action_label = QLabel("Stand")
        transport.addWidget(self.action_label)
        transport.addWidget(self.repeat)
        self.loading = QProgressBar()
        self.loading.setTextVisible(False)
        self.loading.setFixedHeight(3)
        self.loading.setObjectName("CreatorProgress")
        stage_layout.addWidget(self.loading)
        self.message = QLabel()
        self.message.setWordWrap(True)
        stage_layout.addWidget(self.message)
        split.addWidget(stage)
        self.options_scroll = QScrollArea()
        self.options_scroll.setWidgetResizable(True)
        self.options_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        options = QWidget()
        self.options = QVBoxLayout(options)
        hint = QLabel(
            "Click a card to set the default. Check cards to keep alternatives. The"
            " default is always included."
        )
        hint.setWordWrap(True)
        self.options.addWidget(hint)
        preset_section = self.section("Preset characters")
        self.kind = QComboBox()
        self.kind.addItems(("People", "Animals"))
        self.kind.setCurrentText(kind)
        self.kind.currentTextChanged.connect(self.fill_designs)
        preset_section.layout().addWidget(self.kind)
        self.presets = ChoiceGrid()
        self.presets.itemClicked.connect(self.choose_design)
        preset_section.layout().addWidget(self.presets)
        self.grids: dict[str, ChoiceGrid] = {}
        self.sections: dict[str, OptionSection] = {}
        self.placements: dict[str, QComboBox] = {}
        self._outfit_name = ""
        self.add_grid(
            "Outfit sets", tuple(OUTFIT_PRESETS), "Coordinated outfit sets", checkable=True
        )
        self.add_grid("Mouth", COMPONENT_CHOICES["Mouth"], "Lips · complete lip-sync sets")
        self.add_grid("Eyes", COMPONENT_CHOICES["Eyes"], "Eyes")
        self.add_grid("Eye poses", ("Open", "Blink", "Wink"), "Eye poses", checkable=False)
        self.add_grid("Expression", FEELING_PRESETS, "Expressions", checkable=False)
        for category in (
            "Clothing",
            "Pants",
            "Shoes",
            "Ties",
            "Headwear",
            "Glasses",
            "Watches",
            "Necklaces",
            "Belts",
            "Backwear",
            "Hair",
            "Hands",
            "Nose",
            "Mustache",
            "Beard",
        ):
            self.add_grid(category, COMPONENT_CHOICES[category], category)
        self.add_grid("Animations", MOTION_CHOICES, "Source animations")
        self.clothes, self.mouth, self.hands, self.motions = (
            self.grids[k] for k in ("Clothing", "Mouth", "Hands", "Animations")
        )
        mirror_tools = QHBoxLayout()
        self.hand_flips: dict[str, QCheckBox] = {}
        for side in ("left", "right"):
            check = QCheckBox(f"Mirror {side} hand")
            check.setAccessibleName(f"Mirror viewer-{side} hand in current view")
            check.setToolTip(
                "Flip around the wrist in this view; original vector paths stay unchanged"
            )
            check.toggled.connect(lambda checked, side=side: self.set_hand_flip(side, checked))
            self.hand_flips[side] = check
            mirror_tools.addWidget(check)
        cast(QVBoxLayout, self.sections["Hands"].layout()).addLayout(mirror_tools)
        views_button = QPushButton("Compare all views")
        views_button.clicked.connect(self.compare_views)
        self.sections["Hands"].layout().addWidget(views_button)
        shape = self.section("Shape and proportions")
        self.line_style = QComboBox()
        self.line_style.addItems(STYLE_CHOICES)
        self.line_style.currentTextChanged.connect(lambda v: self.update_recipe(style=v))
        self.head_shape = QComboBox()
        self.head_shape.addItems(("Round", "Oval", "Soft square"))
        self.head_shape.currentTextChanged.connect(lambda v: self.update_recipe(head_shape=v))
        self.body_shape = QComboBox()
        self.body_shape.addItems(("Simple", "Rounded rectangle"))
        self.body_shape.setToolTip("Simple line torso or an uneven hand-drawn rounded torso")
        self.body_shape.currentTextChanged.connect(lambda v: self.update_recipe(body_shape=v))
        for label, geometry_control in (
            ("Line style", self.line_style),
            ("Head shape", self.head_shape),
            ("Body shape", self.body_shape),
        ):
            geometry_control.setAccessibleName(label)
            shape.layout().addWidget(QLabel(label))
            shape.layout().addWidget(geometry_control)
        self.proportions: dict[str, QSpinBox] = {}
        for field, label in (
            ("head", "Head size"),
            ("body", "Body length"),
            ("width", "Body width"),
            ("arm", "Arm length"),
            ("leg", "Leg length"),
        ):
            row = QHBoxLayout()
            row.addWidget(QLabel(label), 1)
            control = QSpinBox()
            control.setRange(65, 160)
            control.setValue(100)
            control.setSuffix(" %")
            control.setKeyboardTracking(False)
            control.setAccessibleName(label)
            control.valueChanged.connect(
                lambda value, key=field: self.update_recipe(
                    proportions={**self.recipe.proportions, key: value / 100}
                )
            )
            self.proportions[field] = control
            row.addWidget(control)
            shape.layout().addItem(row)
        self.stroke = QSpinBox()
        self.stroke.setRange(3, 16)
        self.stroke.setSuffix(" px")
        self.stroke.setKeyboardTracking(False)
        self.stroke.valueChanged.connect(lambda v: self.update_recipe(stroke_width=v))
        shape.layout().addWidget(QLabel("Limb line width"))
        shape.layout().addWidget(self.stroke)
        self.outline = QDoubleSpinBox()
        self.outline.setRange(0, 5)
        self.outline.setSingleStep(0.2)
        self.outline.setKeyboardTracking(False)
        self.outline.setAccessibleName("Outline weight")
        self.outline.valueChanged.connect(lambda value: self.update_recipe(outline_width=value))
        shape.layout().addWidget(QLabel("Outline weight · 0 hides contours"))
        shape.layout().addWidget(self.outline)
        self.color_section = self.section("Palette · live preview")
        self.color_buttons: dict[str, QPushButton] = {}
        for role in ("Ink", "Skin", "Hair", "Top", "Bottom", "Accent", "Shoes"):
            button = QPushButton(role)
            button.setProperty("paintSwatch", True)
            button.clicked.connect(lambda checked=False, key=role: self.choose_color(key))
            self.color_section.layout().addWidget(button)
            self.color_buttons[role] = button
        self.options.addStretch()
        self.options_scroll.setWidget(options)
        split.addWidget(self.options_scroll)
        options_margins = self.options.contentsMargins()
        section_margins = preset_section.layout().contentsMargins()
        options_width = (
            3 * CARD_CELL
            + options_margins.left()
            + options_margins.right()
            + section_margins.left()
            + section_margins.right()
            + 2 * (self.presets.frameWidth() + self.options_scroll.frameWidth())
            + self.options_scroll.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent)
        )
        self.options_scroll.setMinimumWidth(options_width)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.setSizes((870, options_width))
        footer = QHBoxLayout()
        footer.addWidget(QLabel("SVG artwork · replaceable parts · editable bone actions"))
        footer.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        self.add = QPushButton("Add to Scene")
        self.add.clicked.connect(self.create_character)
        footer.addWidget(self.add)
        outer.addLayout(footer)
        self.model.changed.connect(self.refresh)
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self.refresh_extensions()
        self.updating = False
        self.set_recipe(self.recipe)
        QTimer.singleShot(0, self.fit_preview)
        self.host.viewmodel.theme_changed.connect(self.refresh_theme_icons)
        self.host.viewmodel.plugins_changed.connect(self.refresh_extensions)

    def refresh_extensions(self) -> None:
        """Refresh live recipe providers when plugins are enabled or disabled."""
        self.extension_presets = self.host.viewmodel.extensions.character_presets()
        self.fill_designs()
        self.sync_controls()

    def refresh_theme_icons(self, *_: Any) -> None:
        """Keep open Creator controls on the host's bundled icon palette."""
        for button in self.findChildren(QToolButton):
            if name := button.property("materialIcon"):
                button.setIcon(self.host.icons.icon(str(name)))

    def tool(self, icon: str, hint: str, callback: Any) -> QToolButton:
        """Create an accessible bundled-icon button for one preview command."""
        button = QToolButton()
        button.setProperty("materialIcon", icon)
        button.setIcon(self.host.icons.icon(icon))
        button.setToolTip(hint)
        button.setAccessibleName(hint)
        button.clicked.connect(callback)
        return button

    def section(self, title: str) -> OptionSection:
        """Own a disclosure header and non-scrolling content section."""
        toggle = QToolButton()
        toggle.setText(title)
        toggle.setCheckable(True)
        toggle.setChecked(True)
        toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toggle.setIcon(self.host.icons.icon("expand_more"))
        toggle.setProperty("materialIcon", "expand_more")
        self.options.addWidget(toggle)
        body = OptionSection()
        body.setProperty("sectionHeader", toggle)
        self.options.addWidget(body)

        def changed(on: bool) -> None:
            """Change disclosure visibility without rebuilding its cards."""
            body.setVisible(on)
            toggle.setProperty("materialIcon", "expand_more" if on else "chevron_right")
            toggle.setIcon(self.host.icons.icon("expand_more" if on else "chevron_right"))

        toggle.toggled.connect(changed)
        return body

    def add_grid(
        self, category: str, values: tuple[str, ...], title: str, *, checkable: bool = True
    ) -> None:
        """Create genuine option cards with separate default and retention commands."""
        section = self.section(title)
        grid = ChoiceGrid()
        grid.setAccessibleName(title + " preview cards")
        for value in values:
            item = QListWidgetItem(value.title() if value.islower() else value)
            item.setData(Qt.ItemDataRole.UserRole, value)
            item.setToolTip(
                "Click to set the default. Use the checkbox to retain this alternative."
                if checkable
                else "Preview " + value
            )
            if checkable:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
            else:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            grid.addItem(item)
        grid.itemClicked.connect(lambda item, key=category: self.choose_card(key, item))
        grid.itemActivated.connect(lambda item, key=category: self.choose_card(key, item))
        grid.itemChanged.connect(lambda item, key=category: self.include_card(key))
        section.layout().addWidget(grid)
        self.grids[category], self.sections[category] = grid, section
        if category in COMPONENT_CHOICES:
            row = QHBoxLayout()
            paint = QPushButton("Color…")
            paint.clicked.connect(
                lambda checked=False, key=category: self.choose_component_color(key)
            )
            row.addWidget(paint)
            if category in PLACEMENTS:
                placement = QComboBox()
                placement.addItems(PLACEMENTS[category])
                placement.setAccessibleName(category + " layer placement")
                placement.currentTextChanged.connect(
                    lambda value, key=category: self.update_recipe(
                        layer_modes={**self.recipe.layer_modes, key: value}
                    )
                )
                row.addWidget(placement, 1)
                self.placements[category] = placement
            section.layout().addItem(row)

    def fill_designs(self, *_: Any) -> None:
        """Populate the independent Creator catalog for the selected anatomy."""
        self.presets.clear()
        cache = cached_catalog(self.host.viewmodel.content.library.cache_root)
        for d in CREATOR_DESIGNS:
            if (d.anatomy not in ("human", "robot")) != (self.kind.currentText() == "Animals"):
                continue
            item = QListWidgetItem(QIcon(str(cache / "posters" / (d.id + ".png"))), d.name)
            item.setData(Qt.ItemDataRole.UserRole, d.id)
            self.presets.addItem(item)
        for key, recipe in self.extension_presets.items():
            design = design_by_id(recipe.design_id)
            if (design.anatomy not in ("human", "robot")) != (self.kind.currentText() == "Animals"):
                continue
            item = QListWidgetItem(
                QIcon(str(cache / "posters" / (design.id + ".png"))), recipe.name
            )
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setToolTip(key)
            self.presets.addItem(item)
        if not any(
            d.id == self.recipe.design_id
            and (d.anatomy not in ("human", "robot")) == (self.kind.currentText() == "Animals")
            for d in CREATOR_DESIGNS
        ):
            self.choose_design(self.presets.item(0))

    def choose_design(self, item: QListWidgetItem) -> None:
        """Load the complete silhouette, colors and outfit of a Creator preset."""
        self._outfit_name = ""
        key = str(item.data(Qt.ItemDataRole.UserRole))
        recipe = self.extension_presets.get(key)
        self.set_recipe(recipe if recipe is not None else recipe_for(design_by_id(key)))

    def set_recipe(self, recipe: CharacterRecipe) -> None:
        """Keep disclosure/scroll state and avoid rebuilding an unchanged appearance."""
        if recipe == self.recipe and self.model.preview is not None:
            return
        self.recipe = recipe
        self.sync_controls()
        self.request()

    def sync_controls(self) -> None:
        """Reflect recipe defaults without resetting disclosure, scroll or inclusion state."""
        self.updating = True
        self.name.setText(self.recipe.name)
        self.view.setCurrentText(self.recipe.view)
        for side, check in self.hand_flips.items():
            check.setChecked(self.recipe.hand_flips.get(self.recipe.view, {}).get(side, False))
        self.line_style.setCurrentText(self.recipe.style)
        self.head_shape.setCurrentText(self.recipe.head_shape)
        self.body_shape.setCurrentText(self.recipe.body_shape)
        self.stroke.setValue(round(self.recipe.stroke_width))
        self.outline.setValue(self.recipe.outline_width)
        selected_key = next(
            (
                key
                for key, recipe in self.extension_presets.items()
                if recipe.design_id == self.recipe.design_id and recipe.name == self.recipe.name
            ),
            self.recipe.design_id,
        )
        for i in range(self.presets.count()):
            item = self.presets.item(i)
            selected = item.data(Qt.ItemDataRole.UserRole) == selected_key
            item.setSelected(selected)
            label_format(item, "Default" if selected else "")
        for field, control in self.proportions.items():
            control.setValue(round(self.recipe.proportions.get(field, 1) * 100))
        for key, placement_control in self.placements.items():
            placement_control.setCurrentText(self.recipe.layer_modes.get(key, PLACEMENTS[key][0]))
        animal = design_by_id(self.recipe.design_id).anatomy not in ("human", "robot")
        for category, grid in self.grids.items():
            if category == "Animations":
                default, included = self.motion_name, self.recipe.motions
            elif category == "Outfit sets":
                default, included = self._outfit_name, self.recipe.outfit_sets
            elif category == "Expression":
                default, included = self.recipe.feeling, ()
            elif category == "Eye poses":
                default, included = str(self.recipe.poses.get("Eyes", "Open")), ()
            else:
                default, included = (
                    default_choice(self.recipe, category),
                    self.recipe.alternatives.get(category, ()),
                )
            grid.blockSignals(True)
            for i in range(grid.count()):
                item = grid.item(i)
                value = str(item.data(Qt.ItemDataRole.UserRole))
                item.setSelected(value == default)
                if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                    item.setCheckState(
                        Qt.CheckState.Checked if value in included else Qt.CheckState.Unchecked
                    )
                label_format(
                    item, "Default" if value == default and category != "Animations" else ""
                )
            grid.blockSignals(False)
            header = self.sections[category].property("sectionHeader")
            visible = not animal or category == "Animations"
            header.setVisible(visible)
            self.sections[category].setVisible(visible and header.isChecked())
        self.updating = False

    def choose_card(self, category: str, item: QListWidgetItem) -> None:
        """Apply a visible default while leaving retained-alternative checks independent."""
        value = str(item.data(Qt.ItemDataRole.UserRole))
        if category == "Animations":
            self.select_motion(value)
            return
        if category == "Outfit sets":
            self._outfit_name = value
            self.set_recipe(outfit(self.recipe, value))
        elif category == "Expression":
            self.update_recipe(feeling=value)
        elif category == "Eye poses":
            self.update_recipe(poses={**self.recipe.poses, "Eyes": value})
        else:
            self.set_recipe(choose(self.recipe, category, value))

    def include_card(self, category: str) -> None:
        """Save checked alternatives or exported actions without replacing the visible default."""
        if self.updating:
            return
        grid = self.grids[category]
        values = tuple(
            str(grid.item(i).data(Qt.ItemDataRole.UserRole))
            for i in range(grid.count())
            if grid.item(i).checkState() == Qt.CheckState.Checked
        )
        if category == "Animations":
            self.update_recipe(motions=values)
        elif category == "Outfit sets":
            alternatives = dict(self.recipe.alternatives)
            for name in values:
                for key, value in outfit_values(name).items():
                    alternatives[key] = tuple(dict.fromkeys((*alternatives.get(key, ()), value)))
            self.update_recipe(outfit_sets=values, alternatives=alternatives)
        else:
            self.update_recipe(alternatives={**self.recipe.alternatives, category: values})

    def update_recipe(self, **changes: Any) -> None:
        """Apply a deliberate control edit outside guarded programmatic synchronization."""
        if not self.updating:
            self.set_recipe(replace(self.recipe, **changes))

    def set_hand_flip(self, side: str, flipped: bool) -> None:
        """Persist a local mirror for one viewer-side hand in the active authored view."""
        if self.updating:
            return
        hands = {**self.recipe.hand_flips.get(self.recipe.view, {}), side: flipped}
        self.update_recipe(hand_flips={**self.recipe.hand_flips, self.recipe.view: hands})

    def compare_views(self) -> None:
        """Inspect all current view registrations without replacing the main preview."""
        from rigora.presentation.widgets.turnaround_preview import TurnaroundPreview

        if previous := getattr(self, "turnaround", None):
            previous.close()
            previous.deleteLater()
        self.turnaround = TurnaroundPreview(self, self.recipe)
        self.turnaround.show()

    def request(self) -> None:
        """Request an isolated appearance update and debounce its portable preparation."""
        self.model.request(self.recipe)
        self.model.ensure_prepared()
        self.refresh()

    def set_view_option(self, attribute: str, value: bool) -> None:
        """Update a Creator-only viewport overlay flag."""
        setattr(self.preview, attribute, value)
        self.preview.update()

    def set_background(self, name: str, color: str = "") -> None:
        """Render a preview-only swatch or backdrop across the full viewport."""
        self.preview.preview_background = None
        self.preview.checker_visible = name == "Transparent"
        if name != "Transparent":
            source = background_source(name, color)
            self.preview.preview_background = decode_artwork(source, 640)
        self.preview.update()

    def choose_background(self) -> None:
        """Preview custom background paint live and restore it on cancellation."""
        previous = self.preview.preview_background
        checker = self.preview.checker_visible
        if (
            self.pick_paint(
                "Preview background", "#303030", lambda color: self.set_background("Custom", color)
            )
            is None
        ):
            self.preview.preview_background, self.preview.checker_visible = previous, checker
            self.preview.update()

    def show_zoom(self, zoom: float) -> None:
        """Reflect wheel, fit and button zoom changes without a signal feedback loop."""
        self.zoom_percent.blockSignals(True)
        self.zoom_percent.setValue(zoom * 100)
        self.zoom_percent.blockSignals(False)

    def fit_preview(self, *_: Any) -> None:
        """Fit the dedicated Creator camera using the shared viewport navigation."""
        self.preview.fit_canvas()

    def fit_character(self) -> None:
        """Frame the figure while retaining its center in the preview stage."""
        settings, anchor = stage_layout(self.recipe)
        _, _, width, height = character_preview_frame(self.recipe)
        zoom = max(
            0.1, min((self.preview.width() - 90) / width, (self.preview.height() - 90) / height)
        )
        self.preview.zoom = zoom
        self.preview.offset = QPointF(
            self.preview.width() / 2 - settings.width / 2 * zoom,
            self.preview.height() / 2 - settings.height / 2 * zoom,
        )
        self.preview.zoom_changed.emit(zoom)
        self.preview.update()

    def choose_color(self, role: str) -> None:
        """Preview a shared palette paint live and restore the recipe on Cancel."""
        original = self.recipe
        color = {**design_by_id(self.recipe.design_id).colors, **self.recipe.colors}[role]
        selected = self.pick_paint(
            role + " paint", color, lambda value: self.queue_paint("palette", role, value)
        )
        self.flush_paint()
        if selected is None:
            self.set_recipe(original)

    def choose_component_color(self, category: str) -> None:
        """Edit the selected variant paint independently of other retained variants."""
        value = default_choice(self.recipe, category)
        if value.lower() in ("none", "bare"):
            return
        original = self.recipe
        key = category + "/" + value
        role = {
            "Clothing": "Top",
            "Pants": "Bottom",
            "Shoes": "Shoes",
            "Hair": "Hair",
            "Mustache": "Hair",
            "Beard": "Hair",
            "Hands": "Skin",
            "Eyes": "Ink",
            "Nose": "Ink",
            "Mouth": "Ink",
        }.get(category, "Accent")
        from rigora.domain.creator_options import CLOTHING_PAINTS

        fallback = {**design_by_id(self.recipe.design_id).colors, **self.recipe.colors}[role]
        if category == "Clothing":
            fallback = self.recipe.garment_colors.get(value, CLOTHING_PAINTS.get(value, fallback))
        elif category == "Pants" and value == "formal trousers":
            fallback = "#303338"
        elif category == "Hands":
            fallback = "#ffffff"
        color = self.recipe.garment_colors.get(key, fallback)
        selected = self.pick_paint(
            category + " · " + value,
            str(color),
            lambda paint: self.queue_paint("component", key, paint),
        )
        self.flush_paint()
        if selected is None:
            self.set_recipe(original)

    def queue_paint(self, mode: str, key: str, color: str) -> None:
        """Coalesce color-picker events into a bounded-rate live SVG repaint."""
        self._paint_pending = mode, key, color
        if not self._paint_timer.isActive():
            self._paint_timer.start()

    def flush_paint(self) -> None:
        """Apply the latest queued RGB paint before confirmation or creation."""
        self._paint_timer.stop()
        if self._paint_pending:
            mode, key, color = self._paint_pending
            self._paint_pending = None
            self.update_recipe(
                **(
                    {"colors": {**self.recipe.colors, key: color}}
                    if mode == "palette"
                    else {"garment_colors": {**self.recipe.garment_colors, key: color}}
                )
            )

    def pick_paint(self, title: str, original: str, live: Any) -> str | None:
        """Return an applied RGB paint from a shared dialog with live preview callbacks."""
        dialog = CustomDialog(self, title)
        box = QVBoxLayout(dialog.content)
        picker = QColorDialog(QColor(original))
        picker.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog)
        picker.setOption(QColorDialog.ColorDialogOption.NoButtons)
        picker.setWindowFlags(Qt.WindowType.Widget)
        picker.currentColorChanged.connect(lambda color: live(color.name()))
        box.addWidget(picker)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        box.addWidget(buttons)
        selected = picker.currentColor().name() if dialog.exec() else None
        dialog.deleteLater()
        return selected

    def refresh(self) -> None:
        """Adopt ready snapshots, progress and card images without resetting navigation."""
        model = self.model
        waiting = model.ready != self.recipe or model.busy
        self.loading.setVisible(waiting)
        self.loading.setRange(0, 100 if model.busy else 0)
        self.loading.setValue(model.progress)
        self.message.setText(
            model.error or (model.status or "Preparing preview…" if waiting else "")
        )
        self.add.setEnabled(model.ready == self.recipe and not model.error)
        for role, button in self.color_buttons.items():
            paint = {**design_by_id(self.recipe.design_id).colors, **self.recipe.colors}[role]
            button.setStyleSheet("QPushButton{border-left:12px solid " + paint + ";}")
        if model.preview and id(model.preview) != self._preview_id:
            if self._has_rig_preview and self.preview.pose:
                self._resume_frame = self.preview.pose.frame
            frame = self._resume_frame
            self._preview_id = id(model.preview)
            if not set(model.images) <= set(self.preview.artwork.images):
                self.preview.artwork.clear()
            for key, (image, data) in model.images.items():
                self.preview.artwork.put(key, image, data)
            self.preview.set_scene(model.preview.scene.settings)
            self.preview.set_pose(model.preview.animation.pose)
            if model.ready == self.recipe:
                self.select_motion(self.motion_name, frame=frame)
            self._has_rig_preview = model.ready == self.recipe
            framing = (self.recipe.design_id, self.recipe.view)
            if framing != self._frame_key:
                self._frame_key = framing
                self.fit_preview()
        if id(model.option_images) != self._icon_id:
            self._icon_id = id(model.option_images)
            for category, grid in self.grids.items():
                grid.blockSignals(True)
                for i in range(grid.count()):
                    item = grid.item(i)
                    icon_key = category, str(item.data(Qt.ItemDataRole.UserRole))
                    if icon_key in model.option_images:
                        item.setIcon(QIcon(QPixmap.fromImage(model.option_images[icon_key][0])))
                grid.blockSignals(False)
            for i in range(self.presets.count()):
                item = self.presets.item(i)
                icon_key = "Presets", str(item.data(Qt.ItemDataRole.UserRole))
                if icon_key in model.option_images:
                    item.setIcon(QIcon(QPixmap.fromImage(model.option_images[icon_key][0])))
        if model.ready == self.recipe and self.pending == "create" and not model.error:
            self.pending = ""
            self.create_character()

    def select_motion(self, name: str, *, frame: float = 0) -> None:
        """Switch an isolated action, retaining time when only appearance is replaced."""
        self.motion_name = name
        self._resume_frame = frame
        self.action_label.setText(name)
        if (doc := self.model.preview) and self.model.ready == self.recipe:
            clip = next((c for c in doc.scene.clips if c.name == name), None)
            if clip:
                doc.select_animation_clip(clip.id)
                doc.animation.seek(min(frame, clip.out_frame))
                doc.animation.playback.loop = self.repeat.isChecked()
                if self.play.isChecked():
                    doc.animation.play()
                self.preview.set_pose(doc.animation.pose)

    def toggle_play(self, checked: bool) -> None:
        """Play or pause only the isolated Creator animation session."""
        self.play.setIcon(self.host.icons.icon("pause" if checked else "play_arrow"))
        self.play.setProperty("materialIcon", "pause" if checked else "play_arrow")
        self._time = time.monotonic()
        if doc := self.model.preview:
            doc.animation.play() if checked else doc.animation.pause()

    def toggle_repeat(self, checked: bool) -> None:
        """Change preview looping without altering exported source-action definitions."""
        if doc := self.model.preview:
            doc.animation.playback.loop = checked

    def tick(self) -> None:
        """Advance the isolated transport and anchor its fixed floating controls."""
        now = time.monotonic()
        dt, self._time = min(0.05, now - self._time), now
        self.transport.adjustSize()
        self.transport.move(
            max(4, (self.preview.width() - self.transport.width()) // 2),
            max(4, self.preview.height() - self.transport.height() - 12),
        )
        self.transport.raise_()
        if (
            self.play.isChecked()
            and self.model.ready == self.recipe
            and (doc := self.model.preview)
        ):
            self.preview.set_pose(doc.animation.advance(dt, visible_only=True))

    def create_character(self) -> None:
        """Publish a fully prepared portable character as one destination Undo step."""
        self.flush_paint()
        if self.model.ready != self.recipe or not self.model.built:
            self.pending = "create"
            self.model.ensure_prepared(immediate=True)
            return
        try:
            if self.host.viewmodel.documents is not self.document:
                raise ProjectError("Return to the project where Character Creation was opened.")
            root = CharacterCreationService(self.document).create(self.model.built)
            self.host.object_edit.exit()
            self.host.viewmodel.changed.emit()
            self.host.scene_workspace.select_entries((root,))
            self.accept()
        except ProjectError as error:
            self.message.setText(str(error))

    def done(self, result: int) -> None:
        """Cancel pending paints and drain workers before the dialog releases Qt objects."""
        self._paint_timer.stop()
        self.timer.stop()
        self.model.shutdown()
        super().done(result)

    def closeEvent(self, event: Any) -> None:
        """Drain preparation before the preview widgets can be destroyed."""
        self._paint_timer.stop()
        self.timer.stop()
        self.model.shutdown()
        super().closeEvent(event)
