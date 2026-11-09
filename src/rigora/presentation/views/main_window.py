"""Professional dock shell; real documents and navigation, truthful future tools."""

import base64
import contextlib
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any, cast

from PySide6.QtCore import QByteArray, QPointF, QRect, QSignalBlocker, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QIcon,
    QKeySequence,
    QPixmap,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDockWidget,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTabBar,
    QTabWidget,
    QTextBrowser,
    QToolBar,
    QToolButton,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rigora.domain.content import asset_format
from rigora.domain.entities import Group, SceneObject, nested_records
from rigora.domain.project import ProjectError
from rigora.infrastructure.migrations import CURRENT_VERSION
from rigora.presentation.animation_preview import AnimationPreview
from rigora.presentation.content_drop import ContentDropWorkspace
from rigora.presentation.icons import IconProvider
from rigora.presentation.menu_labels import display_text, menu_text
from rigora.presentation.mesh_workspace import MeshWorkspace
from rigora.presentation.plugin_workspace import PluginWorkspace
from rigora.presentation.rig_workspace import RigWorkspace
from rigora.presentation.scene_workspace import SceneWorkspace
from rigora.presentation.themes import ThemeManager
from rigora.presentation.viewmodels.main_window import MainWindowViewModel
from rigora.presentation.widgets.about_dialog import AboutDialog
from rigora.presentation.widgets.action_buttons import compact_button
from rigora.presentation.widgets.asset_cards import label_format
from rigora.presentation.widgets.automation_dialog import AutomationDialog
from rigora.presentation.widgets.content_browser import ContentBrowser
from rigora.presentation.widgets.dialogs import CommandPalette, ProjectSettingsDialog
from rigora.presentation.widgets.file_dialogs import choose_open_file, choose_save_file
from rigora.presentation.widgets.item_view_state import ItemViewState
from rigora.presentation.widgets.media_dialogs import MediaImportDialog, OutputDialog
from rigora.presentation.widgets.menus import ToggleMenu
from rigora.presentation.widgets.meshes import MeshPanel
from rigora.presentation.widgets.message_dialogs import (
    ask_question,
    show_warning,
)
from rigora.presentation.widgets.plugin_manager import PluginManagerDialog
from rigora.presentation.widgets.puppet_stage import PuppetStage
from rigora.presentation.widgets.rigging import RigPanel
from rigora.presentation.widgets.scene_tree import ProjectImageList, SceneTree
from rigora.presentation.widgets.timeline import Timeline
from rigora.presentation.widgets.titlebar import TitleBar
from rigora.presentation.widgets.toolbox import ToolboxDock
from rigora.presentation.widgets.viewport import Viewport
from rigora.presentation.widgets.welcome import WelcomeWindow
from rigora.presentation.widgets.window_frame import (
    CustomDialog,
    DockPanel,
    FramelessMainWindow,
    WindowFrameController,
)
from rigora.presentation.widgets.workspace_panels import ContentShelf, ObjectProperties


class MainWindow(FramelessMainWindow):
    """Dockable multi-project editor shell wiring Qt widgets to application ViewModel commands."""

    plugin_workspace: PluginWorkspace

    def __init__(self, viewmodel: MainWindowViewModel) -> None:
        """Build themed chrome and panels, restore workspace preferences, and bind state signals."""
        super().__init__()
        self.viewmodel = viewmodel
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowMinMaxButtonsHint
        )
        self.setAccessibleName("Rigora 2D main window")
        self.setMinimumSize(960, 620)
        self.resize(1440, 900)
        self.setDockOptions(
            QMainWindow.DockOption.AllowNestedDocks | QMainWindow.DockOption.AnimatedDocks
        )
        self.icons = IconProvider()
        app = cast(QApplication, QApplication.instance())
        self.themes = ThemeManager(app, self.icons)
        self.themes.apply(str(viewmodel.preferences.data["theme"]))
        self.command_actions: dict[str, QAction] = {}
        from rigora.presentation.extension_surfaces import ExtensionSurfaces

        self.extension_surfaces = ExtensionSurfaces(self)
        self.docks: dict[str, QDockWidget] = {}
        self._project_id: str | None = None
        self._active_view_id: str | None = None
        self._view_states: dict[str, tuple[float, QPointF]] = {}
        self._viewport_generation = 0
        self._closed = False
        self.welcome_window: WelcomeWindow | None = None
        self.composer_target = "part"
        self.content_browser: ContentBrowser | None = None
        self.plugin_dialog: PluginManagerDialog | None = None
        self.automation_dialog: AutomationDialog | None = None
        self.output_dialog: OutputDialog | None = None
        self.media_dialog: MediaImportDialog | None = None
        self.puppet_stage: PuppetStage | None = None
        self._scene_timeline_height: int | None = None
        self._build_chrome()
        self._build_actions()
        self._build_toolbar()
        self._build_center()
        self._build_docks()
        self._build_status()
        self.rig_workspace = RigWorkspace(self)
        self.mesh_workspace = MeshWorkspace(self)
        self.scene_workspace = SceneWorkspace(self)
        from rigora.presentation.object_assets import ObjectAssetsWorkspace

        self.object_assets = ObjectAssetsWorkspace(self)
        self.library_tabs.insertTab(0, self.object_assets.cards, "Objects")
        from rigora.presentation.shape_workspace import ShapeWorkspace

        self.shape_workspace = ShapeWorkspace(self)
        from rigora.presentation.object_edit import ObjectEditMode

        self.object_edit = ObjectEditMode(self)
        self.object_edit.button.clicked.connect(self.object_assets.return_to_project)
        from rigora.presentation.camera_workspace import CameraWorkspace

        self.camera_workspace = CameraWorkspace(self)
        self.selection_properties.bind()
        self.tree.installEventFilter(self.scene_workspace)
        self._asset_hover_signature: tuple[object, ...] | None = None
        self.viewport.asset_hovered.connect(self.preview_project_asset)
        self.viewport.content_left.connect(self.clear_asset_preview)
        self.viewport.asset_dropped.connect(self.drop_project_asset)
        self.viewport.files_dropped.connect(self.drop_external_on_stage)
        self.viewmodel.media.imported.connect(self.assets_added)
        self.viewmodel.media.changed.connect(self.asset_import_status)
        self.setAcceptDrops(True)
        self.animation_preview = AnimationPreview(self)
        viewmodel.content.applied.connect(self.content_applied)
        self.content_drop = ContentDropWorkspace(self)
        self._populate_menus()
        self.extension_surfaces.register("main", self.toolbox)
        self.extension_surfaces.register(
            "object.actions", cast(QHBoxLayout, self.character_panel.layer_actions.layout())
        )
        self.extension_surfaces.register("object.header", self.character_panel.extension_header)
        self.extension_surfaces.register("timeline.actions", self.timeline.extension_actions)
        self.plugin_workspace = PluginWorkspace(self)
        self.timeline.extension_context_requested.connect(
            lambda menu, surface, arguments: self.plugin_workspace.populate_context(
                menu, surface, **arguments
            )
        )
        self.viewmodel.extensions.emit_event("app.ready")
        self._default_layout = self.saveState(1).data()
        self._restore_workspace()
        self.viewport.theme = self.themes.name
        self.command_actions["theme"].setChecked(self.themes.name == "light")
        self.command_actions["theme"].setText("Light theme")
        viewmodel.changed.connect(self.refresh_document)
        viewmodel.welcome_requested.connect(self.raise_welcome_window)
        viewmodel.project_io.message.connect(lambda text: self.statusBar().showMessage(text, 15000))
        viewmodel.project_io.open_error.connect(self.offer_backup)
        from PySide6.QtWidgets import QProgressBar

        self.io_progress = QProgressBar(self)
        self.io_progress.setRange(0, 0)
        self.io_progress.setFixedSize(96, 4)
        self.io_progress.setTextVisible(False)
        self.io_progress.setAccessibleName("Project disk operation in progress")
        self.io_progress.hide()
        self.statusBar().addPermanentWidget(self.io_progress)
        viewmodel.project_io.changed.connect(
            lambda: self.io_progress.setVisible(
                any(
                    key.startswith(("save:", "open:", "restore:"))
                    for key in viewmodel.project_io.jobs
                )
            )
        )
        QTimer.singleShot(0, self.restore_previous_session)
        viewmodel.theme_changed.connect(self.apply_theme)
        viewmodel.playback.changed.connect(self.update_animation)
        viewmodel.animation_editor.key_preview_changed.connect(self.update_animation)
        viewmodel.playback.changed.connect(self.mesh_panel.refresh_transport)
        self.refresh_document()
        self.refresh_icons()
        self.mesh_workspace.load_assets()
        from rigora.presentation.widgets.content_setup import connect_content_setup

        connect_content_setup(self)
        self.viewmodel.content.reload()
        if viewmodel.preferences.warning:
            self.statusBar().showMessage(viewmodel.preferences.warning, 15000)

    def tabifyDockWidget(self, first: QDockWidget, second: QDockWidget) -> None:
        """Keep Tools independent when a saved layout or an extension requests panel tabs."""
        tools = self.docks.get("tools")
        if tools is not None and tools in (first, second):
            cast(ToolboxDock, tools).reset_position()
            return
        super().tabifyDockWidget(first, second)

    def _build_chrome(self) -> None:
        """Create the custom caption and its integrated application menu bar."""
        chrome = QWidget(self)
        box = QVBoxLayout(chrome)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        self.titlebar = TitleBar(self, self.icons)
        box.addWidget(self.titlebar)
        self.menu_bar = QMenuBar(self.titlebar)
        self.menu_bar.setNativeMenuBar(False)
        self.menu_bar.setObjectName("TitleMenus")
        self.menu_bar.setFixedHeight(32)
        cast(QHBoxLayout, self.titlebar.layout()).insertWidget(
            2, self.menu_bar, 0, Qt.AlignmentFlag.AlignVCenter
        )
        self.frame = WindowFrameController(self, self.titlebar)
        self.titlebar.caption.setMinimumWidth(0)
        self.titlebar.caption.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.setMenuWidget(chrome)
        self.menus: dict[str, QMenu] = {}
        for name in (
            "File",
            "Edit",
            "Object",
            "Rig",
            "Deform",
            "Animation",
            "View",
            "Assets",
            "Plugins",
            "AI / Automation",
            "Help",
        ):
            menu = ToggleMenu(menu_text(name), self.menu_bar)
            self.menu_bar.addMenu(menu)
            self.menus[name] = menu

    def _action(
        self,
        key: str,
        text: str,
        icon: str,
        callback: Callable[[], object] | None = None,
        shortcut: str = "",
        reason: str = "",
        checkable: bool = False,
    ) -> QAction:
        """Register a searchable action with its icon, shortcut, availability, and callback."""
        action = QAction(menu_text(text), self)
        action.setObjectName(key)
        action.setProperty("materialIcon", icon)
        action.setProperty("futureFeature", callback is None)
        action.setIcon(self.icons.icon(icon))
        action.setCheckable(checkable)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.setToolTip(reason or text)
        action.setStatusTip(reason or text)
        if callback is not None:
            action.triggered.connect(lambda _checked=False: callback())
        else:
            action.setEnabled(False)
        self.addAction(action)
        self.command_actions[key] = action
        return action

    def _build_actions(self) -> None:
        """Declare working workspace commands and explanatory disabled future actions."""
        for key, text, icon, callback, shortcut in (
            ("new", "New project…", "add", self.new_project, "Ctrl+N"),
            (
                "library",
                "Browse content library…",
                "collections_bookmark",
                self.open_content_library,
                "Ctrl+Shift+B",
            ),
            (
                "play",
                "Play / pause",
                "play_arrow",
                self.viewmodel.playback.play_pause,
                "Ctrl+Space",
            ),
            ("stop", "Stop playback", "stop", self.viewmodel.playback.stop, ""),
            ("first", "First frame", "first_page", self.viewmodel.playback.seek_start, ""),
            (
                "previous",
                "Previous frame",
                "skip_previous",
                lambda: self.viewmodel.playback.step(-1),
                "",
            ),
            ("next", "Next frame", "skip_next", lambda: self.viewmodel.playback.step(1), ""),
            ("last", "Last frame", "last_page", self.viewmodel.playback.seek_end, ""),
            ("open", "Open project…", "folder_open", self.open_project, "Ctrl+O"),
            ("recover_work", "Recover unsaved work…", "restore", self.show_recovery, ""),
            ("foot_contacts", "Foot contacts…", "link", self.show_foot_contacts, ""),
            ("audio_tracks", "Audio tracks…", "volume_up", self.show_audio_tracks, ""),
            ("game_tools", "Game regions & particles…", "crop_free", self.show_game_tools, ""),
            ("movement_views", "Movement-driven views…", "360", self.show_movement_views, ""),
            ("broadcast", "Local broadcast output…", "cast", self.show_broadcast, ""),
            ("video_rig", "Media to Rig…", "video_file", self.show_video_rig, ""),
            ("camera_shots", "Camera shots…", "videocam", self.show_camera_shots, ""),
            (
                "state_machine",
                "Animation state machine…",
                "account_tree",
                self.show_state_machine,
                "",
            ),
            (
                "production_inspector",
                "Performance & project diagnostics…",
                "timeline",
                self.show_production_inspector,
                "",
            ),
            ("save", "Save", "save", self.save_project, "Ctrl+S"),
            (
                "save_as",
                "Save as…",
                "save_as",
                lambda: self.save_project(save_as=True),
                "Ctrl+Shift+S",
            ),
            ("settings", "Project settings…", "tune", self.project_settings, "Ctrl+,"),
            (
                "register_asset",
                "Register project asset…",
                "add_photo_alternate",
                self.register_asset,
                "",
            ),
            ("embed_assets", "Embed linked assets", "inventory_2", self.embed_linked_assets, ""),
            ("quit", "Quit Rigora", "close", self.close, "Alt+F4"),
            ("close_project", "Close tab", "close", self.close_current_project, "Ctrl+W"),
            (
                "next_project",
                "Next project tab",
                "chevron_right",
                lambda: self.cycle_project(1),
                "Ctrl+Tab",
            ),
            (
                "previous_project",
                "Previous project tab",
                "chevron_left",
                lambda: self.cycle_project(-1),
                "Ctrl+Shift+Tab",
            ),
            ("save_all", "Save all projects", "save", self.save_all_projects, "Ctrl+Alt+S"),
            ("undo", "Undo", "undo", self.viewmodel.undo, "Ctrl+Z"),
            ("redo", "Redo", "redo", self.viewmodel.redo, "Ctrl+Shift+Z"),
            (
                "fit",
                "Fit canvas",
                "fit_screen",
                lambda: (
                    self.object_edit.fit_view()
                    if self.object_edit.active
                    else self.viewport.fit_canvas()
                ),
                "F",
            ),
            ("actual", "Actual size · 100%", "center_focus_strong", self.actual_size, "1"),
            ("zoom_in", "Zoom in", "zoom_in", lambda: self.viewport.zoom_at(1.2), "+"),
            ("zoom_out", "Zoom out", "zoom_out", lambda: self.viewport.zoom_at(1 / 1.2), "-"),
            ("restore", "Reset Workspace Layout", "dashboard_customize", self.restore_layout, ""),
            ("palette", "Command palette…", "search", self.command_palette, "Ctrl+Shift+P"),
            ("welcome", "Welcome", "home", self.viewmodel.show_welcome, ""),
            ("learn", "Quick start & shortcuts", "menu_book", self.show_help, "F1"),
            ("about", "About Rigora 2D", "info", self.show_about, ""),
            (
                "maximize",
                "Maximize / restore window",
                "crop_square",
                self.titlebar.toggle_maximized,
                "F11",
            ),
            ("window_menu", "Window menu", "menu", self.titlebar.show_system_menu, "Alt+Space"),
        ):
            self._action(key, text, icon, callback, shortcut)
        self._action(
            "grid", "Show grid", "grid_on", self.toggle_grid, "G", checkable=True
        ).setChecked(True)
        self._action(
            "scene_context",
            "Show scene context",
            "visibility",
            lambda: self.object_edit.update_reference(),
            checkable=True,
        ).setVisible(False)
        self.command_actions["scene_context"].setToolTip(
            "Show other scene objects as a reference in Object Editor. "
            "References cannot be selected or moved."
        )
        self._action(
            "bone_overlay", "Show bones", "device_hub", self.toggle_bone_overlay, checkable=True
        ).setChecked(True)
        self.command_actions["bone_overlay"].setToolTip(
            "Show bone shapes and labels. Picking, selection and transforms "
            "stay active when hidden."
        )
        self._action(
            "checker",
            "Transparency checkerboard",
            "texture",
            self.toggle_checker,
            "Shift+G",
            checkable=True,
        ).setChecked(True)
        self._action(
            "theme", "Light theme", "light_mode", self.toggle_theme, "Ctrl+Shift+L", checkable=True
        )
        self._action(
            "loop", "Loop playback", "repeat", self.viewmodel.playback.toggle_loop, checkable=True
        )
        self._action("pan", "Pan canvas", "pan_tool", self.toggle_pan, "H", checkable=True)
        self._action(
            "navigate", "Select & transform", "near_me", self.navigate, "V", checkable=True
        ).setChecked(True)
        self._tool_group = QActionGroup(self)
        self._tool_group.addAction(self.command_actions["pan"])
        self._tool_group.addAction(self.command_actions["navigate"])
        self._action(
            "rig_mode",
            "Rig rest mode",
            "device_hub",
            lambda: self.rig_workspace.set_mode(not self.viewmodel.rig.active),
            "R",
            checkable=True,
        )
        self._action("bone", "Draw bone", "device_hub", self.toggle_bone_tool, "B", checkable=True)
        self.command_actions["bone"].setToolTip(
            "Draw bone (B) · Snap to joint circles · Hold Alt for free placement"
        )
        self._action(
            "mesh",
            "Edit mesh",
            "grid_4x4",
            lambda: self.toggle_mesh_tool("vertex"),
            "M",
            checkable=True,
        )
        self._action(
            "weights",
            "Paint weights",
            "brush",
            lambda: self.toggle_mesh_tool("paint"),
            checkable=True,
        )
        self._action(
            "deform",
            "Deformation tools",
            "waves",
            lambda: self.toggle_mesh_tool("control"),
            checkable=True,
        )
        self._action(
            "import",
            "Add assets…",
            "add_photo_alternate",
            self.show_media_import,
            "Ctrl+I",
        )
        self._action(
            "deform_demo", "New deformation example", "waves", lambda: self.mesh_workspace.example()
        )
        self._action("move", "Move bones", "open_with", self.move_bones, checkable=True)
        self.command_actions["move"].setToolTip(
            "Move selected bones/branches live · Select a root to move the whole rig"
        )
        self._tool_group.addAction(self.command_actions["move"])
        self._action("path", "Bezier artwork & motion paths…", "route", self.show_curve_editor)
        self._action("plugins", "Manage plugins…", "extension", self.show_plugins)
        self._action("retarget", "Retarget motion…", "swap_horiz", self.show_retarget)
        self._action("facial", "Face & Lip Sync…", "face", self.show_facial)
        self._action(
            "camera_tracking", "Camera performance…", "videocam", self.show_camera_tracking
        )
        self._action("dynamics", "Secondary motion & physics…", "waves", self.show_dynamics)
        self._action(
            "rigging_guide", "Rig imported artwork…", "auto_fix_high", self.show_rigging_guide
        )
        self._action(
            "character_wizard", "Create character…", "person_add", self.show_character_wizard
        )
        self._action("automation", "Automation & MCP…", "terminal", self.show_automation)
        self._action("export", "Export SVG preview…", "ios_share", self.export_preview)
        self._action("render_output", "Render & export…", "movie", self.show_output, "Ctrl+Shift+E")
        self._action("import_media", "Add assets…", "perm_media", self.show_media_import)
        self._action("spring", "Add spring follow-through", "waves", self.add_springs)
        self._action(
            "draw_shape",
            "Draw vector shape",
            "category",
            lambda: self.shape_workspace.toggle(),
            checkable=True,
        )
        self._action(
            "bone_editor", "Bone Editor…", "device_hub", self.show_bone_editor, checkable=True
        )
        self._action(
            "spring_editor", "Spring Editor…", "waves", self.show_spring_editor, checkable=True
        )
        for key, label, icon in (
            ("part", "Transform parts", "near_me"),
            ("sprite", "Transform sprite", "image"),
            ("bone_only", "Transform bone", "device_hub"),
        ):
            self._action(key, label, icon, partial(self.set_composer_target, key), checkable=True)
        self.composer_group = QActionGroup(self)
        for key in ("part", "sprite", "bone_only"):
            self.composer_group.addAction(self.command_actions[key])
        self.command_actions["part"].setChecked(True)
        self._action(
            "object_move",
            "Move selection",
            "open_with",
            partial(self.transform_tool, "move"),
            checkable=True,
        )
        self._tool_group.addAction(self.command_actions["object_move"])
        self._action(
            "new_object", "New empty object", "add_box", lambda: self.scene_workspace.new_object()
        )
        self._action(
            "make_object",
            "Make object from selection",
            "widgets",
            lambda: self.scene_workspace.make_object(),
        )
        self._action("attach", "Attach object…", "link", self.attach_selection)
        self._action("scene_attachments", "Scene attachments…", "hub", self.attach_selection)
        self._action(
            "attachment_points", "Attachment points…", "my_location", self.show_attachment_points
        )
        self._action("bind_parts", "Rig binding…", "link", self.show_bindings)
        self._action("unbind_parts", "Unbind selection", "link_off", self.unbind_selection)
        self._action("bindings", "Rig bindings…", "hub", self.show_bindings)
        self._action(
            "isolate",
            "Object Edit Mode",
            "filter_center_focus",
            self.isolate_selection,
            checkable=True,
        )
        self._action(
            "scene_visible", "Show / hide selection", "visibility", self.toggle_selection_visibility
        )
        self._action("puppet", "Puppet Stage…", "view_module", self.show_puppet)
        self._action("motion_pilot", "Motion Pilot…", "control_camera", self.show_motion_pilot)
        for key, label, icon in (
            ("rotate", "Rotate", "rotate_right"),
            ("scale", "Scale", "aspect_ratio"),
        ):
            self._action(key, label, icon, partial(self.transform_tool, key), checkable=True)
            self._tool_group.addAction(self.command_actions[key])

    def _build_toolbar(self) -> None:
        """Arrange persistent command groups in a wrapping, scroll-free primary toolbar."""
        from rigora.presentation.widgets.wrapping_toolbar import WrappingToolbar

        bar = WrappingToolbar(self.icons, self)
        self.main_tools = bar
        bar.setObjectName("main_tools")
        self.main_tool_buttons: dict[str, QToolButton] = {}

        def group(key: str, label: str) -> QHBoxLayout:
            """Create an intact row of related commands with an independent drag handle."""
            content = QWidget()
            layout = QHBoxLayout(content)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(4)
            bar.add_group(key, label, content)
            return layout

        def add_button(row: QHBoxLayout, key: str) -> None:
            """Display a shared action without registering a restorable QMainWindow toolbar."""
            button = QToolButton(bar)
            button.setDefaultAction(self.command_actions[key])
            self.main_tool_buttons[key] = button
            row.addWidget(button)

        chrome = self.menuWidget()
        assert chrome is not None
        cast(QVBoxLayout, chrome.layout()).addWidget(bar)
        bar.height_changed.connect(
            lambda height: chrome.setFixedHeight(self.titlebar.height() + height)
        )
        row = group("files", "File commands")
        for key in ("new", "open", "save", "import"):
            add_button(row, key)
        row = group("targets", "Selection and binding")
        self.transform_target = QComboBox()
        self.transform_target.setAccessibleName("Transform target")
        for label, key in (("Parts", "part"), ("Images", "sprite"), ("Bones", "bone_only")):
            self.transform_target.addItem(label, key)
        self.transform_target.currentIndexChanged.connect(
            lambda: self.set_composer_target(self.transform_target.currentData())
        )
        row.addWidget(self.transform_target)
        for key in ("bind_parts", "unbind_parts", "isolate", "scene_visible"):
            add_button(row, key)
        from rigora.presentation.widgets.selection_properties import SelectionProperties

        self.selection_properties = SelectionProperties(self)
        for key, content in self.selection_properties.groups.items():
            bar.add_group(key, key.title(), content)
        row = group("history", "Undo and redo")
        add_button(row, "undo")
        add_button(row, "redo")
        row = group("commands", "Command palette")
        hint = QLabel("Commands")
        hint.setToolTip("Command palette · Ctrl+Shift+P")
        hint.setObjectName("Muted")
        row.addWidget(hint)
        add_button(row, "palette")
        bar.restore_order(self.viewmodel.preferences.data.get("main_toolbar_order"))

        def remember_order(order: list[str]) -> None:
            """Save completed group moves as workspace preferences, outside project history."""
            self.viewmodel.preferences.data["main_toolbar_order"] = order
            warning = self.viewmodel.preferences.save()
            if warning:
                self.statusBar().showMessage(warning, 15000)

        bar.order_changed.connect(remember_order)
        bar.ensurePolished()
        bar.reflow()
        chrome.setFixedHeight(self.titlebar.height() + bar.height())
        self.toolbox = QToolBar("Toolbox", self)
        self.toolbox.setObjectName("toolbox")
        self.toolbox.setMovable(False)
        self.toolbox.setFloatable(False)
        self.toolbox.setOrientation(Qt.Orientation.Vertical)
        tools_dock = ToolboxDock(self)
        tools_dock.setWidget(self.toolbox)
        self.docks["tools"] = tools_dock
        for key in (
            "navigate",
            "pan",
            "draw_shape",
            "character_wizard",
            "|",
            "bone_editor",
            "spring_editor",
            "motion_pilot",
            "|",
            "mesh",
        ):
            if key == "|":
                self.toolbox.addSeparator()
            else:
                self.toolbox.addAction(self.command_actions[key])

    def _build_center(self) -> None:
        """Build project-only tabs, an empty workspace and the navigable scene preview."""
        self.stack = QStackedWidget(self)
        center = QWidget(self)
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)
        self.tab_row = QWidget(center)
        tab_layout = QHBoxLayout(self.tab_row)
        tab_layout.setContentsMargins(0, 0, 4, 0)
        self.project_tabs = QTabBar(self.tab_row)
        self.project_tabs.setDocumentMode(True)
        self.project_tabs.setExpanding(False)
        self.project_tabs.setMovable(True)
        self.project_tabs.setElideMode(Qt.TextElideMode.ElideRight)
        self.project_tabs.setAccessibleName("Open project tabs")
        self.project_tabs.currentChanged.connect(self.select_project_tab)
        self.project_tabs.tabMoved.connect(self.move_project_tab)
        tab_layout.addWidget(self.project_tabs, 1)
        add_tab = QToolButton(self.tab_row)
        add_tab.setDefaultAction(self.command_actions["new"])
        tab_layout.addWidget(add_tab)
        center_layout.addWidget(self.tab_row)
        center_layout.addWidget(self.stack, 1)
        self.empty_workspace = QWidget()
        empty_layout = QVBoxLayout(self.empty_workspace)
        empty_layout.addStretch()
        empty_hint = QLabel("Create or open a project to begin.")
        empty_hint.setObjectName("Muted")
        empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_hint)
        empty_layout.addStretch()
        self.stack.addWidget(self.empty_workspace)
        workspace = QWidget()
        box = QVBoxLayout(workspace)
        self.studio_layout = box
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        header = QFrame()
        header.setObjectName("ViewportHeader")
        header.setFixedHeight(38)
        header_box = QHBoxLayout(header)
        self.viewport_header_layout: QHBoxLayout = header_box
        header_box.setContentsMargins(12, 0, 7, 0)
        self.canvas_label = QLabel()
        self.canvas_label.setObjectName("Muted")
        self.selection_options = QWidget()
        selection_box = QHBoxLayout(self.selection_options)
        selection_box.setContentsMargins(0, 0, 0, 0)
        self.selection_filters: dict[str, QCheckBox] = {}
        selection_box.addWidget(QLabel("Select:"))
        for kind, label in (("images", "Images"), ("bones", "Bones"), ("groups", "Groups")):
            check = QCheckBox(label)
            check.setChecked(True)
            check.setAccessibleName(f"Select {kind} in preview")
            check.setToolTip(f"Include {kind} in preview click and rectangle selection")
            check.toggled.connect(lambda _checked: self.scene_workspace.filters_changed())
            self.selection_filters[kind] = check
            selection_box.addWidget(check)
        header_box.addWidget(self.selection_options)
        self.bone_options = QWidget()
        bone_options = QHBoxLayout(self.bone_options)
        bone_options.setContentsMargins(0, 0, 0, 0)
        self.bone_movement = QFrame()
        self.bone_movement.setObjectName("SegmentedControl")
        modes = QHBoxLayout(self.bone_movement)
        modes.setContentsMargins(0, 0, 0, 0)
        modes.setSpacing(0)
        self.bone_modes = QButtonGroup(self.bone_movement)
        self.bone_modes.setExclusive(True)
        self.bone_mode_buttons: dict[str, QToolButton] = {}
        for index, (label, value, tooltip) in enumerate(
            (
                (
                    "Bone",
                    "selection_move",
                    "Transform selected bones only; children keep their world poses.",
                ),
                (
                    "Chain (FK)",
                    "chain_move",
                    "Drag to rotate each selected bone at its own base joint. "
                    "Child bones follow; use Bone or Rig mode for translation.",
                ),
                ("Rig", "rig_move", "Transform the entire connected rig, including its root."),
                (
                    "IK",
                    "pull",
                    "Inverse kinematics: pull the tip to pose the ancestor chain; "
                    "its root stays anchored.",
                ),
            )
        ):
            mode_button = QToolButton()
            mode_button.setText(label)
            mode_button.setCheckable(True)
            mode_button.setAccessibleName(f"Bone transform scope: {label}")
            mode_button.setToolTip(tooltip)
            mode_button.setProperty(
                "segment", "first" if index == 0 else "last" if index == 3 else "middle"
            )
            self.bone_modes.addButton(mode_button)
            self.bone_mode_buttons[value] = mode_button
            mode_button.clicked.connect(
                lambda _checked=False, scope=value: self.change_bone_movement(scope)
            )
            modes.addWidget(mode_button)
        self.bone_mode_buttons["chain_move"].setChecked(True)
        bone_options.addWidget(self.bone_movement)
        bone_options.addWidget(QLabel("Min joint:"))
        self.minimum_joint_angle = QDoubleSpinBox()
        self.minimum_joint_angle.setRange(0, 180)
        self.minimum_joint_angle.setDecimals(0)
        self.minimum_joint_angle.setSuffix("°")
        self.minimum_joint_angle.setSpecialValueText("Off")
        self.minimum_joint_angle.setValue(30)
        self.minimum_joint_angle.setFixedWidth(78)
        self.minimum_joint_angle.setKeyboardTracking(False)
        self.minimum_joint_angle.setAccessibleName("Minimum connected bone joint angle")
        self.minimum_joint_angle.setToolTip(
            "Apply to selected bones relative to each direct parent. Straight = 180°, "
            "right angle = 90°. Zero disables the limit. New joints default to 30°."
        )
        self.minimum_joint_angle.valueChanged.connect(self.change_joint_angle)
        self.minimum_joint_angle.editingFinished.connect(
            lambda: self.change_joint_angle(self.minimum_joint_angle.value())
        )
        bone_options.addWidget(self.minimum_joint_angle)
        header_box.addWidget(self.bone_options)
        self.mesh_drag_options = QWidget()
        mesh_options = QHBoxLayout(self.mesh_drag_options)
        mesh_options.setContentsMargins(0, 0, 0, 0)
        self.soft_drag_button = QToolButton()
        self.soft_drag_button.setText("Soft Drag")
        self.soft_drag_button.setCheckable(True)
        self.soft_drag_button.setAccessibleName("Soft area deformation")
        self.soft_drag_button.setToolTip(
            "Drag near mesh or FFD points with a smooth radius. "
            "Toggle off for direct point selection."
        )
        self.soft_drag_button.clicked.connect(self.toggle_soft_drag)
        mesh_options.addWidget(self.soft_drag_button)
        mesh_options.addWidget(QLabel("Radius:"))
        self.soft_drag_radius = QDoubleSpinBox()
        self.soft_drag_radius.setRange(10, 1000)
        self.soft_drag_radius.setDecimals(0)
        self.soft_drag_radius.setValue(100)
        self.soft_drag_radius.setSuffix(" px")
        self.soft_drag_radius.setFixedWidth(86)
        self.soft_drag_radius.setAccessibleName("Soft Drag radius in screen pixels")
        self.soft_drag_radius.valueChanged.connect(
            lambda value: setattr(self.mesh_workspace.interaction, "soft_radius", value)
        )
        mesh_options.addWidget(self.soft_drag_radius)
        mesh_options.addWidget(QLabel("Strength:"))
        self.soft_drag_strength = QDoubleSpinBox()
        self.soft_drag_strength.setRange(1, 100)
        self.soft_drag_strength.setDecimals(0)
        self.soft_drag_strength.setValue(100)
        self.soft_drag_strength.setSuffix("%")
        self.soft_drag_strength.setFixedWidth(76)
        self.soft_drag_strength.setAccessibleName("Soft Drag strength")
        self.soft_drag_strength.valueChanged.connect(
            lambda value: setattr(self.mesh_workspace.interaction, "soft_strength", value / 100)
        )
        mesh_options.addWidget(self.soft_drag_strength)
        mesh_options.addWidget(QLabel("Falloff:"))
        self.soft_drag_falloff = QDoubleSpinBox()
        self.soft_drag_falloff.setRange(0, 100)
        self.soft_drag_falloff.setDecimals(0)
        self.soft_drag_falloff.setValue(100)
        self.soft_drag_falloff.setSuffix("%")
        self.soft_drag_falloff.setFixedWidth(76)
        self.soft_drag_falloff.setAccessibleName("Soft Drag falloff")
        self.soft_drag_falloff.setToolTip(
            "100% smoothly fades toward the brush edge. 0% moves the whole area equally."
        )
        self.soft_drag_falloff.valueChanged.connect(
            lambda value: setattr(self.mesh_workspace.interaction, "soft_falloff", value / 100)
        )
        mesh_options.addWidget(self.soft_drag_falloff)
        header_box.addWidget(self.mesh_drag_options)
        self.context_hint = QLabel()
        self.context_hint.setObjectName("Muted")
        header_box.addWidget(self.context_hint)
        self.wireframe_option = QCheckBox("Wireframe")
        self.wireframe_option.setToolTip("Show triangle edges over artwork")
        self.wireframe_option.toggled.connect(self.set_viewport_wireframe)
        header_box.addWidget(self.wireframe_option)
        header_box.addStretch()
        self.canvas_zoom = QLabel("100%")
        self.canvas_zoom.setAccessibleName("Canvas zoom percentage")
        self.canvas_zoom.setToolTip("Scene / Object Editor zoom")
        self.canvas_zoom.setMinimumWidth(46)
        self.canvas_zoom.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for key in (
            "scene_context",
            "bone_overlay",
            "grid",
            "checker",
            "zoom_out",
            "zoom_in",
            "fit",
        ):
            tool_button = QToolButton()
            tool_button.setDefaultAction(self.command_actions[key])
            header_box.addWidget(tool_button)
            if key == "zoom_out":
                header_box.addWidget(self.canvas_zoom)
        header_box.addWidget(self.canvas_label)
        # Tool options must overflow inside their row, rather than impose their
        # combined minimum width on every dock in the main-window layout.
        self.viewport_header = QScrollArea()
        self.viewport_header.setFrameShape(QFrame.Shape.NoFrame)
        self.viewport_header.setWidget(header)
        self.viewport_header.setWidgetResizable(True)
        self.viewport_header.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.viewport_header.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        header_scrollbar = self.viewport_header.horizontalScrollBar()
        header_scrollbar.rangeChanged.connect(
            lambda minimum, maximum: self.viewport_header.setFixedHeight(
                header.height() + (header_scrollbar.sizeHint().height() if maximum > minimum else 0)
            )
        )
        self.viewport_header.setFixedHeight(header.height())
        box.addWidget(self.viewport_header)
        self.viewport: Viewport = Viewport(icons=self.icons)
        preview_workspace = cast(ToolboxDock, self.docks["tools"]).attach_preview(self.viewport)
        for key in ("fit", "actual", "zoom_in", "zoom_out", "grid", "checker", "pan", "navigate"):
            viewport_action = self.command_actions[key]
            self.removeAction(viewport_action)
            self.viewport.addAction(viewport_action)
            viewport_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.viewport.zoom_changed.connect(self.update_zoom)
        self.studio_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.studio_splitter.setChildrenCollapsible(False)
        self.studio_splitter.setHandleWidth(1)
        self.studio_splitter.addWidget(preview_workspace)
        self.studio_splitter.setStretchFactor(0, 1)
        box.addWidget(self.studio_splitter, 1)
        self.stack.addWidget(workspace)
        self.setCentralWidget(center)

    @staticmethod
    def _eyebrow(text: str) -> QLabel:
        """Return a small section label styled by the shared theme."""
        label = QLabel(text)
        label.setObjectName("Eyebrow")
        return label

    def _dock(self, key: str, title: str, widget: QWidget, area: Qt.DockWidgetArea) -> None:
        """Wrap a panel in a named dock whose placement and visibility can be persisted."""
        dock = DockPanel(title, self, self.icons)
        dock.setObjectName(f"dock_{key}")
        dock.setMinimumWidth(280 if key in ("hierarchy", "assets", "inspector") else 180)
        dock.setWidget(widget)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.addDockWidget(area, dock)
        toggle = dock.toggleViewAction()
        toggle.setProperty("materialIcon", "view_sidebar")
        toggle.setIcon(self.icons.icon("view_sidebar"))
        self.docks[key] = dock

    def _build_docks(self) -> None:
        """Create the hierarchy, source browser, inspector and working animation timeline."""
        hierarchy = QWidget()
        self.hierarchy_content = hierarchy
        box = QVBoxLayout(hierarchy)
        box.setContentsMargins(8, 8, 8, 8)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter scene…")
        self.filter.addAction(self.icons.icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.filter.textChanged.connect(self.filter_scene)
        scene_header = QHBoxLayout()
        scene_header.addWidget(self.filter, 1)
        self.add_scene_button = QToolButton()
        self.add_scene_button.setIcon(self.icons.icon("add"))
        self.add_scene_button.setToolTip("Add scene")
        self.add_scene_button.setAccessibleName("Add scene")
        self.add_scene_button.clicked.connect(lambda: self.scene_workspace.add_scene())
        scene_header.addWidget(self.add_scene_button)
        self.camera_button = QToolButton()
        self.camera_button.setIcon(self.icons.icon("videocam"))
        self.camera_button.setToolTip("Cameras · add, edit, animate and preview")
        self.camera_button.setAccessibleName("Cameras")
        scene_header.addWidget(self.camera_button)
        box.addLayout(scene_header)
        self.tree = SceneTree()
        self.tree.source_dropped.connect(self.drop_asset_in_tree)
        self.tree.source_hovered.connect(self.preview_project_asset)
        self.tree.source_left.connect(self.clear_asset_preview)
        self.tree.files_dropped.connect(self.drop_external_in_tree)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        box.addWidget(self.tree, 1)
        self.hierarchy_note = QLabel("No objects yet.\nObject creation is a later milestone.")
        self.hierarchy_note.setWordWrap(True)
        self.hierarchy_note.setObjectName("Muted")
        self.hierarchy_note.hide()
        self._dock("hierarchy", "Scene", hierarchy, Qt.DockWidgetArea.LeftDockWidgetArea)
        assets = self.project_assets_page = QWidget()
        asset_box = QVBoxLayout(assets)
        asset_box.setContentsMargins(8, 10, 8, 10)
        categories = QListWidget()
        for name, icon in (
            ("Human rigs", "person_outline"),
            ("Skeleton templates", "device_hub"),
            ("Animation clips", "directions_run"),
            ("Meshes & deformation", "waves"),
            ("Props & accessories", "category"),
        ):
            item = QListWidgetItem(self.icons.icon(icon), name)
            item.setData(Qt.ItemDataRole.UserRole, icon)
            item.setToolTip("Browse this installed offline collection.")
            categories.addItem(item)
        categories.setMaximumHeight(160)
        categories.itemClicked.connect(lambda item: self.open_content_library(item.text()))
        categories.hide()
        library_button = QPushButton("Browse & install packs…")
        library_button.setProperty("materialIcon", "collections_bookmark")
        library_button.clicked.connect(lambda: self.open_content_library())
        library_button.hide()
        asset_actions = QHBoxLayout()
        asset_box.addLayout(asset_actions)
        self.extension_surfaces.register("assets.actions", asset_actions)
        self.project_assets = ProjectImageList()
        self.project_assets.set_empty_action(
            "Bring in your artwork",
            "Import files or drop them here. Reuse them anywhere in your project.",
            "Import assets…",
            self.command_actions["import"],
        )
        self.project_assets.drag_finished.connect(self.clear_asset_preview)
        self.project_assets.files_dropped.connect(self.add_external_assets)
        self.project_assets.itemDoubleClicked.connect(self.place_asset)
        self.project_assets.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.project_assets.customContextMenuRequested.connect(self.asset_context_menu)
        delete_asset = QAction("Remove source", self.project_assets)
        delete_asset.setShortcut(QKeySequence("Delete"))
        delete_asset.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        delete_asset.triggered.connect(self.remove_project_asset)
        self.project_assets.addAction(delete_asset)
        asset_box.addWidget(self.project_assets, 1)
        self.import_artwork_button = compact_button(
            self.icons, "Add assets…", "add_photo_alternate", self.command_actions["import"].trigger
        )
        self.import_artwork_button.setToolTip(
            "Add multiple images, layered artwork or other supported sources (Ctrl+I)."
        )
        asset_box.addWidget(self.import_artwork_button)
        self.project_assets.empty_changed.connect(self.import_artwork_button.setHidden)
        self.import_artwork_button.hide()
        empty = QLabel(
            "Import stores the original image here. Double-click it to place an independent "
            "instance in the scene; reuse the same image as often as needed."
        )
        empty.setObjectName("Muted")
        empty.setWordWrap(True)
        self.project_assets.setToolTip(empty.text())
        self.asset_categories = categories
        self.content_shelf = ContentShelf(self)
        self.library_tabs = QTabWidget()
        self.library_tabs.setMinimumHeight(160)
        self.library_tabs.addTab(assets, "Imports")
        self.library_tabs.addTab(self.content_shelf, "Content")
        self._dock("assets", "Assets", self.library_tabs, Qt.DockWidgetArea.RightDockWidgetArea)
        self.inspector = QTabWidget()
        self.inspector.setMinimumHeight(160)
        from rigora.presentation.widgets.character_panel import CharacterPanel

        self.character_panel = CharacterPanel(self)
        transform = QWidget()
        transform_box = QVBoxLayout(transform)
        transform_box.setContentsMargins(14, 16, 14, 16)
        transform_box.setSpacing(14)
        transform_box.addWidget(self._eyebrow("SCENE PROPERTIES"))
        self.inspector_title = QLabel("No project open")
        self.inspector_title.setStyleSheet("font-size: 15px; font-weight: 600;")
        transform_box.addWidget(self.inspector_title)
        self.scene_properties = QLabel()
        self.scene_properties.setObjectName("Muted")
        self.scene_properties.setWordWrap(True)
        transform_box.addWidget(self.scene_properties)
        settings_button = QPushButton("Project settings")
        settings_button.setProperty("materialIcon", "tune")
        settings_button.clicked.connect(self.project_settings)
        transform_box.addWidget(settings_button)
        transform_box.addStretch()
        self.object_properties = ObjectProperties(self)
        transform_box.addWidget(self.object_properties)
        from rigora.presentation.widgets.object_scene_controls import ObjectSceneControls

        self.object_controls = ObjectSceneControls(self)
        transform_box.insertWidget(0, self.object_controls)
        transform_scroll = QScrollArea()
        transform_scroll.setWidgetResizable(True)
        transform_scroll.setWidget(transform)
        self.inspector.addTab(transform_scroll, "Transform")
        self.rig_panel = RigPanel(self.viewmodel.rig, self.icons)
        self.inspector.addTab(self.rig_panel, "Rig")
        self.mesh_panel = MeshPanel(self.viewmodel.mesh, self.icons)
        self.inspector.addTab(self.mesh_panel, "Mesh / Deform")
        self.studio_splitter.addWidget(self.character_panel)
        self.studio_splitter.setStretchFactor(1, 0)
        self.character_panel.setMinimumWidth(310)
        self.character_panel.setMaximumWidth(460)
        self.character_panel.hide()
        self.metadata = QLabel()
        self.metadata.setMargin(14)
        self.metadata.setWordWrap(True)
        self.metadata.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.inspector.addTab(self.metadata, "Metadata")
        self._dock("inspector", "Inspector", self.inspector, Qt.DockWidgetArea.RightDockWidgetArea)
        self.splitDockWidget(
            self.docks["assets"], self.docks["inspector"], Qt.Orientation.Horizontal
        )
        self.docks["inspector"].hide()
        self.docks["hierarchy"].raise_()
        self.timeline = Timeline(
            self.viewmodel.playback,
            self.command_actions,
            self.viewmodel.animation_editor,
            self.icons,
            lambda key: self.asset_icon(key, "dry_cleaning"),
        )
        self.range_label = self.timeline.range_label
        self.timeline.objects_dropped.connect(self.object_controls.drop_object)
        self.timeline.bake_spring_requested.connect(self.bake_spring_keys)
        self.timeline_note = self.timeline.note
        self._dock("timeline", "Timeline", self.timeline, Qt.DockWidgetArea.BottomDockWidgetArea)
        self.timeline.attach_transport(cast(DockPanel, self.docks["timeline"]).titlebar)
        self.setCorner(Qt.Corner.BottomLeftCorner, Qt.DockWidgetArea.BottomDockWidgetArea)
        self.setCorner(Qt.Corner.BottomRightCorner, Qt.DockWidgetArea.BottomDockWidgetArea)
        self.resizeDocks(
            [self.docks["hierarchy"], self.docks["assets"]],
            [280, ContentShelf.DEFAULT_WIDTH],
            Qt.Orientation.Horizontal,
        )
        self.resizeDocks([self.docks["timeline"]], [280], Qt.Orientation.Vertical)

    def _build_status(self) -> None:
        """Create persistent tool, file, zoom, and readiness status fields."""
        self.tool_status = QLabel("Navigate")
        self.statusBar().addWidget(self.tool_status)
        self.statusBar().addWidget(QLabel("   |   No selection"))
        self.file_status = QLabel("No project open")
        self.statusBar().addWidget(self.file_status, 1)
        self.frame_status = QLabel("")
        self.statusBar().addPermanentWidget(self.frame_status)
        self.zoom_status = QLabel("100%")
        self.statusBar().addPermanentWidget(self.zoom_status)
        ready = QLabel("   Ready   ")
        ready.setObjectName("Muted")
        self.statusBar().addPermanentWidget(ready)

    def _populate_menus(self) -> None:
        """Group registered actions and dock toggles into the caption menus."""
        groups = {
            "File": (
                "new",
                "open",
                "recover_work",
                "recent",
                "|",
                "save",
                "save_as",
                "save_all",
                "close_project",
                "settings",
                "|",
                "import",
                "export",
                "render_output",
                "|",
                "quit",
            ),
            "Edit": ("undo", "redo", "|", "palette", "next_project", "previous_project"),
            "Object": (
                "new_object",
                "make_object",
                "navigate",
                "draw_shape",
                "attach",
                "scene_attachments",
                "attachment_points",
                "bind_parts",
                "unbind_parts",
                "bindings",
                "isolate",
                "scene_visible",
            ),
            "Rig": (
                "rigging_guide",
                "|",
                "bone_editor",
                "spring_editor",
                "|",
                "rig_mode",
                "bone",
                "spring",
                "attach",
                "bind_parts",
                "unbind_parts",
                "bindings",
            ),
            "Deform": ("mesh", "weights", "deform", "|", "deform_demo"),
            "Animation": (
                "foot_contacts",
                "audio_tracks",
                "game_tools",
                "movement_views",
                "broadcast",
                "camera_shots",
                "state_machine",
                "path",
                "retarget",
                "facial",
                "camera_tracking",
                "video_rig",
                "dynamics",
                "puppet",
                "motion_pilot",
                "play",
                "stop",
                "loop",
                "first",
                "previous",
                "next",
                "last",
                "|",
                "path",
            ),
            "View": (
                "fit",
                "actual",
                "zoom_in",
                "zoom_out",
                "|",
                "grid",
                "bone_overlay",
                "checker",
                "theme",
                "|",
                "restore",
                "welcome",
                "production_inspector",
            ),
            "Assets": (
                "library",
                "|",
                "register_asset",
                "embed_assets",
                "|",
                "import",
            ),
            "Plugins": ("plugins",),
            "AI / Automation": ("automation",),
            "Help": ("learn", "palette", "about"),
        }
        self.recent_menu = QMenu("Recent projects", self)
        self.recent_menu.setIcon(self.icons.icon("history"))
        for name, keys in groups.items():
            for key in keys:
                if key == "|":
                    self.menus[name].addSeparator()
                elif key == "recent":
                    self.menus[name].addMenu(self.recent_menu)
                else:
                    self.menus[name].addAction(self.command_actions[key])
        self.menus["View"].addSeparator()
        for dock in self.docks.values():
            self.menus["View"].addAction(dock.toggleViewAction())

    def refresh_icons(self) -> None:
        """Recolor interface icons and app branding for the active theme."""
        self.timeline.refresh_icons()
        for action in self.command_actions.values():
            action.setIcon(self.icons.icon(str(action.property("materialIcon"))))
        for button in self.findChildren(QAbstractButton):
            name = button.property("materialIcon")
            if name:
                button.setIcon(self.icons.icon(str(name)))
        for row in range(self.asset_categories.count()):
            item = self.asset_categories.item(row)
            item.setIcon(self.icons.icon(item.data(Qt.ItemDataRole.UserRole)))
        for dock in self.docks.values():
            if isinstance(dock, DockPanel):
                dock.titlebar.refresh()
                dock.update_chrome(dock.isFloating())
            dock.toggleViewAction().setIcon(self.icons.icon("view_sidebar"))
        for action in self.filter.actions():
            action.setIcon(self.icons.icon("search"))
        for row in range(self.tree.topLevelItemCount()):
            tree_item = self.tree.topLevelItem(row)
            if tree_item is not None:
                tree_item.setIcon(0, self.icons.icon("layers"))
        if hasattr(self, "object_edit"):
            for index, name in enumerate(
                ("account_tree", "palette", "checkroom", "directions_run")
            ):
                self.object_edit.pages.setTabIcon(index, self.icons.icon(name))
            if self.viewmodel.scene.service:
                records = self.viewmodel.scene.service.records()
                for key, tree_row in self.scene_workspace.items.items():
                    if key in records:
                        tree_row.setIcon(0, self.scene_workspace.row_icon(records[key]))
        self.recent_menu.setIcon(self.icons.icon("history"))
        self.refresh_recent()
        for titlebar in self.findChildren(TitleBar):
            titlebar.refresh()
        self.mesh_panel.refresh()
        self.setWindowIcon(self.icons.branding(boxed=True))

    def showEvent(self, event: QShowEvent) -> None:
        """Open the startup window after the editor has its final visible geometry."""
        super().showEvent(event)
        QTimer.singleShot(0, self, self.sync_welcome_window)

    def sync_welcome_window(self) -> None:
        """Create or dispose the startup window from presentation state, never as a tab."""
        if self._closed or not self.isVisible():
            return
        if self.viewmodel.welcome_open:
            if self.welcome_window is None:
                start = WelcomeWindow(self)
                self.welcome_window = start
                start.finished.connect(self.welcome_finished)
                start.content.setAcceptDrops(True)
                start.content.installEventFilter(self.content_drop)
                start.move(self.geometry().center() - start.rect().center())
                start.show()
            else:
                self.welcome_window.refresh_recent()
        elif self.welcome_window is not None:
            start, self.welcome_window = self.welcome_window, None
            start.close()

    def welcome_finished(self, _result: int) -> None:
        """Release the disposable window and publish explicit user dismissal once."""
        self.welcome_window = None
        if not self._closed and self.viewmodel.welcome_open:
            self.viewmodel.close_welcome()

    def raise_welcome_window(self) -> None:
        """Bring an explicitly requested startup window forward without raising on refreshes."""
        self.sync_welcome_window()
        if self.welcome_window is not None:
            self.welcome_window.raise_()
            self.welcome_window.activateWindow()

    def refresh_document(self) -> None:
        """Synchronize document panels, tabs, warnings, and independent canvas views."""
        doc = self.viewmodel.documents
        if self.object_edit.active and self.object_edit.document is not doc:
            self.object_edit.exit()
        project = doc.project
        if project and doc.animation_context and not self.object_edit.active:
            self.object_edit.enter(doc.animation_context)
        if project and not doc.separated_animation:
            doc.set_animation_context(None, prepare=False)
            self.viewmodel.playback.bind(doc)
        for name in ("bone_editor", "spring_editor"):
            if (editor := getattr(self, name, None)) and (
                editor.document is not doc or project is None
            ):
                editor.close()
        view_id = doc.context_key if project else None
        reset = view_id != self._active_view_id
        if reset and self._active_view_id is not None:
            self._view_states[self._active_view_id] = (
                self.viewport.zoom,
                QPointF(self.viewport.offset),
            )
        self._active_view_id = view_id
        if reset:
            self._viewport_generation += 1
            self.clear_asset_preview()
            if hasattr(self, "content_drop"):
                self.content_drop.clear()
        open_ids = {
            f"{document.session_id}:{scene.id}"
            for document in self.viewmodel.workspace.documents
            if document.project
            for scene in document.project.scenes
        }
        self._view_states = {
            key: value for key, value in self._view_states.items() if key in open_ids
        }
        self.add_scene_button.setEnabled(project is not None)
        self.camera_button.setEnabled(project is not None)
        self.refresh_tabs()
        self.setWindowTitle(self.viewmodel.title)
        self.stack.setCurrentIndex(1 if project else 0)
        for key in (
            "save",
            "export",
            "render_output",
            "import_media",
            "save_as",
            "settings",
            "fit",
            "actual",
            "zoom_in",
            "zoom_out",
            "grid",
            "checker",
            "close_project",
            "register_asset",
            "embed_assets",
            "retarget",
            "facial",
            "camera_tracking",
            "dynamics",
            "motion_pilot",
            "bone_editor",
            "spring_editor",
            "part",
            "sprite",
            "bone_only",
            "attach",
            "bind_parts",
            "unbind_parts",
            "bindings",
            "scene_visible",
            "scene_attachments",
            "attachment_points",
            "object_move",
            "rig_mode",
            "bone",
            "move",
            "rotate",
            "scale",
            "mesh",
            "weights",
            "deform",
        ):
            self.command_actions[key].setEnabled(project is not None)
        self.command_actions["close_project"].setEnabled(
            project is not None or self.viewmodel.welcome_open
        )
        self.command_actions["save_all"].setEnabled(bool(self.viewmodel.workspace.documents))
        self.command_actions["undo"].setEnabled(doc.can_undo)
        self.command_actions["redo"].setEnabled(doc.can_redo)
        self.command_actions["undo"].setText(
            menu_text(f"Undo {doc.history.undo_stack[-1].label}" if doc.can_undo else "Undo")
        )
        self.command_actions["redo"].setText(
            menu_text(f"Redo {doc.history.redo_stack[-1].label}" if doc.can_redo else "Redo")
        )
        for key in ("next_project", "previous_project"):
            self.command_actions[key].setEnabled(len(self.viewmodel.workspace.documents) > 1)
        if project:
            scene = doc.scene
            self.viewport.set_scene(scene.settings)
            self._project_id = project.id
            self.canvas_label.setText(f"  {scene.settings.width} × {scene.settings.height} px")
            count = len(nested_records(scene))
            self.hierarchy_note.setText(
                "Drag layers to change order · F2 to rename"
                if self.object_edit.active
                else "Double-click an object to edit its parts, skin and motions."
                if count
                else "Add artwork or drag a character from Templates to begin."
            )
            self.viewport.scene_hint = (
                "SELECT · Ctrl: multiselect · Drag: move · Space/middle-drag: pan"
                if count
                else "EMPTY SCENE  ·  B to draw bones · R for rig mode"
            )
            assets_state = (
                ItemViewState.capture(self.project_assets)
                if self.project_assets.property("documentSession") == doc.session_id
                else None
            )
            self.project_assets.clear()
            for asset in project.assets:
                icon = (
                    "audiotrack"
                    if asset.kind == "audio"
                    else "collections"
                    if "layered_layout" in asset.extra
                    else "movie"
                    if "sprite_sequence" in asset.extra
                    else "description"
                )
                item = QListWidgetItem(self.asset_icon(asset.id, icon), asset.name)
                label_format(item, asset_format(asset))
                item.setData(Qt.ItemDataRole.UserRole, asset.id)
                item.setToolTip(f"{asset.kind} · {asset.storage}\n{asset.source}\n{asset.id}")
                self.project_assets.addItem(item)
            self.project_assets.setProperty("documentSession", doc.session_id)
            if assets_state:
                assets_state.restore(self.project_assets, selection=True)
            self.inspector_title.setText(scene.name)
            s = scene.settings
            self.scene_properties.setText(
                f"Canvas    {s.width} × {s.height} px\n\nFrame rate    {s.fps} "
                f"fps\n\nRange    {s.start_frame} – {s.end_frame}\n\nOrigin    Top left · "
                f"pixels"
            )
            self.metadata.setText(
                f"Project\n{project.name}\n\nProject ID\n{project.id}\n\nScene "
                f"ID\n{scene.id}\n\nFormat\nRigora package · version {CURRENT_VERSION}"
            )
            self.file_status.setText(
                f"   |   {doc.path.name if doc.path else 'Not saved'}{'  •' if doc.dirty else ''}"
            )
            self.file_status.setToolTip(str(doc.path or "Choose Save As to save this project."))
            if reset:
                state = self._view_states.get(doc.context_key)
                if state is not None:
                    self.viewport.zoom, saved_offset = state
                    self.viewport.offset = QPointF(saved_offset)
                    self.viewport.zoom_changed.emit(self.viewport.zoom)
                else:
                    generation = self._viewport_generation
                    QTimer.singleShot(0, lambda: self.fit_active_document(generation))
                self.viewport.setFocus()
        else:
            self.project_assets.clear()
            self.file_status.setText(
                "Welcome" if self.viewmodel.welcome_open else "No project open"
            )
            self.file_status.setToolTip("Create or open a project to begin.")
            self.zoom_status.setText("")
            self.viewport.has_project = False
        if project and (doc.migration_note or doc.warnings):
            self.statusBar().showMessage(
                " · ".join(filter(None, (doc.migration_note, *doc.warnings))), 20000
            )
        self.object_assets.refresh()
        self.refresh_recent()
        self.filter_scene(self.filter.text())
        if hasattr(self, "scene_workspace"):
            self.scene_workspace.rebuild()
        self.timeline.refresh()
        self.object_edit.refresh()
        self.update_animation()
        self.sync_welcome_window()

    def update_animation(self) -> None:
        """Refresh only transport controls and evaluated geometry during playback."""
        playback = self.viewmodel.playback
        session = playback.session
        rig = self.viewmodel.rig
        self.viewport.mesh_editing = self.viewmodel.mesh.active
        if not self.object_edit.active:
            self.viewport.composer_artwork_only = True
        self.refresh_tool_options()
        self.timeline.setEnabled(session is not None)
        self.timeline.transport.setEnabled(session is not None)
        for key in ("play", "stop", "first", "previous", "next", "last", "loop"):
            self.command_actions[key].setEnabled(session is not None)
        playing = session is not None and session.playback.is_playing
        play = self.command_actions["play"]
        play.setProperty("materialIcon", "pause" if playing else "play_arrow")
        play.setIcon(self.icons.icon("pause" if playing else "play_arrow"))
        play.setText("Pause playback" if playing else "Play / pause")
        self.command_actions["loop"].setChecked(session is not None and session.playback.loop)
        self.viewport.set_pose(session.pose if session else None)
        if rig.active:
            self.viewport.set_pose(rig.pose)
        elif self.viewmodel.mesh.active and session is not None:
            self.viewport.set_pose(self.viewmodel.mesh.pose)
        if self.viewmodel.animation_editor.preview_pose is not None:
            self.viewport.set_pose(self.viewmodel.animation_editor.preview_pose)
        self.object_edit.update_reference()
        self.command_actions["isolate"].setChecked(self.viewport.isolated_ids is not None)
        if session is not None:
            frame = session.pose.frame
            seconds = session.playback.range.frame_to_seconds(frame)
            self.frame_status.setText(f"Frame {frame:g} · {seconds:.3f} s   ")
            self.viewport.scene_hint = (
                "ARTWORK / DEFORMATION PREVIEW"
                if session.pose.meshes
                else "TRANSFORM PREVIEW  ·  Object axes and bones"
                if session.pose.nodes
                else "EMPTY SCENE"
            )
        else:
            self.frame_status.setText("")
            if playback.error:
                self.viewport.scene_hint = "Animation preview unavailable · See Timeline"
        warning = playback.error or (" · ".join(session.pose.warnings) if session else "")
        if rig.active:
            self.viewport.scene_hint = (
                "DRAW BONES  ·  B draw · Alt: free placement · Right-click: cancel"
                if rig.tool == "draw"
                else "MOVE BONES  ·  Drag selected branches · Esc: cancel"
                if rig.tool == "move"
                else "POSE · Chain: drag to rotate · Bone: drag to move · Ctrl: multi-select"
                if rig.tool == "select" and rig.animating
                else "BONES · Chain: drag to rotate · Bone: drag to move · Ctrl: multi-select"
                if rig.tool == "select"
                else "RIG REST MODE  ·  B draw · Right-click clears selection"
            )
            warning = rig.error or (" · ".join(rig.pose.warnings) if rig.pose else "")
        elif self.viewmodel.mesh.active:
            self.viewport.scene_hint = (
                "CUSTOM FFD  ·  Box: select · Handles: resize · Ctrl: multi-select · Esc: cancel"
                if self.viewmodel.mesh.tool == "control"
                else "MESH EDIT  ·  Ctrl: extend selection · Esc: cancel"
            )
        if warning != getattr(self, "_playback_warning", ""):
            self._playback_warning = warning
            if warning:
                self.statusBar().showMessage(warning, 15000)

    def fit_active_document(self, generation: int) -> None:
        """Fit a newly displayed canvas only while its activation is still current."""
        if generation == self._viewport_generation:
            self.viewport.fit_canvas()

    def draw_bone(self) -> None:
        """Enter the rest-rig editor and activate world-space bone drawing."""
        self.ensure_object_editor()
        if self.object_edit.active:
            self.viewmodel.rig.run(lambda service: service.prepare_object_rig(self.object_edit.key))
            if self.viewmodel.rig.error:
                return
            self.character_panel.show_page("tree")
            if self.viewmodel.rig.selected:
                row = self.scene_workspace.items.get(self.viewmodel.rig.selected[0])
                if row:
                    parent = row.parent()
                    while parent:
                        parent.setExpanded(True)
                        parent = parent.parent()
                    self.tree.scrollToItem(row)
        self.end_subdivision_preview()
        self.rig_workspace.set_mode(True)
        self.viewmodel.rig.set_tool("draw")

    def toggle_bone_tool(self) -> None:
        """Switch bone drawing off on repeated activation, retaining ordinary selection."""
        if self.viewmodel.rig.active and self.viewmodel.rig.tool == "draw":
            self.navigate()
        else:
            self.draw_bone()

    def toggle_mesh_tool(self, tool: str) -> None:
        """Toggle a mesh authoring tool without trapping the shared selection action."""
        model = self.viewmodel.mesh
        matching = (
            model.tool in ("vertex", "edge", "triangle", "insert", "soft")
            if tool == "vertex"
            else model.tool == tool
        )
        if model.active and matching:
            self.navigate()
        else:
            self.ensure_object_editor()
            self.end_subdivision_preview()
            if tool == "vertex":
                model.stage_id, model.controls = "", ()
            self.mesh_workspace.activate_tool("soft" if tool == "vertex" else tool)

    def end_subdivision_preview(self) -> None:
        """Release read-only topology previews before a stage authoring tool takes input."""
        if editor := getattr(self, "bone_editor", None):
            editor.preview_subdivision.setChecked(False)
            editor.clear_preview()

    def refresh_tabs(self) -> None:
        """Synchronize project-only tabs and independent document dirty states."""
        previous = self.project_tabs.blockSignals(True)
        entries = [
            (
                document.session_id,
                document.project.name + (" *" if document.dirty else ""),
                str(document.path or "Unsaved project"),
            )
            for document in self.viewmodel.workspace.documents
            if document.project is not None
        ]
        current_ids = [self.project_tabs.tabData(i) for i in range(self.project_tabs.count())]
        rebuild = current_ids != [key for key, _, _ in entries]
        if rebuild:
            while self.project_tabs.count():
                self.project_tabs.removeTab(0)
        for index, (key, title, tooltip) in enumerate(entries):
            if rebuild:
                self.project_tabs.addTab("")
                self.project_tabs.setTabData(index, key)
                button = QToolButton(self.project_tabs)
                button.setFixedSize(24, 24)
                button.setAutoRaise(True)
                button.clicked.connect(
                    lambda checked=False, tab_id=key: self.close_tab_by_id(tab_id)
                )
                self.project_tabs.setTabButton(index, QTabBar.ButtonPosition.RightSide, button)
            self.project_tabs.setTabText(index, title)
            self.project_tabs.setTabToolTip(index, tooltip)
            close_button = self.project_tabs.tabButton(index, QTabBar.ButtonPosition.RightSide)
            if isinstance(close_button, QToolButton):
                close_button.setIcon(self.icons.icon("close", 14))
                close_button.setToolTip(f"Close {title.rstrip(' *')}")
                close_button.setAccessibleName(f"Close tab {title.rstrip(' *')}")
        self.project_tabs.setCurrentIndex(self.viewmodel.workspace.active_index)
        self.project_tabs.blockSignals(previous)

    def select_project_tab(self, index: int) -> None:
        """Resolve tab selection by identity so dragging tabs never selects the wrong document."""
        key = self.project_tabs.tabData(index)
        for position, document in enumerate(self.viewmodel.workspace.documents):
            if document.session_id == key:
                self.viewmodel.activate_project(position)
                break

    def move_project_tab(self, source: int, destination: int) -> None:
        """Reorder document sessions directly; every tab now represents a project."""
        self.viewmodel.move_project(source, destination)

    def cycle_project(self, direction: int) -> None:
        """Cycle through open project tabs with wraparound."""
        count = self.project_tabs.count()
        if count:
            self.project_tabs.setCurrentIndex(
                (self.project_tabs.currentIndex() + direction) % count
            )

    def restore_selection(self, session_id: str | None, welcome: bool) -> None:
        """Restore a prior page after a guarded operation using stable document identity."""
        if not self.viewmodel.workspace.documents:
            self.refresh_document()
        else:
            for index, document in enumerate(self.viewmodel.workspace.documents):
                if document.session_id == session_id:
                    self.viewmodel.activate_project(index)
                    break
        if welcome:
            self.viewmodel.show_welcome()

    def close_tab_by_id(self, session_id: str) -> None:
        """Resolve a project close guard and restore the previously selected page."""
        documents = self.viewmodel.workspace.documents
        index = next((i for i, doc in enumerate(documents) if doc.session_id == session_id), -1)
        if index < 0:
            return
        previous = self.viewmodel.workspace.active
        welcome = self.viewmodel.welcome_selected
        self.viewmodel.activate_project(index)
        if self.confirm_discard():
            self.viewmodel.close_project(index, discard=True)
            self._view_states = {
                key: value
                for key, value in self._view_states.items()
                if not key.startswith(f"{session_id}:")
            }
        self.restore_selection(previous.session_id if previous else None, welcome)

    def close_current_project(self) -> None:
        """Close the selected tab, guarding project edits and leaving other sessions intact."""
        if self.viewmodel.welcome_selected:
            self.viewmodel.close_welcome()
        elif not self.viewmodel.welcome_selected and self.viewmodel.workspace.active is not None:
            self.close_tab_by_id(self.viewmodel.documents.session_id)

    def save_all_projects(self) -> None:
        """Save dirty documents until cancellation, then return to the originally selected page."""
        previous = self.viewmodel.workspace.active
        welcome = self.viewmodel.welcome_selected
        try:
            for index, document in enumerate(self.viewmodel.workspace.documents):
                if document.dirty:
                    self.viewmodel.activate_project(index)
                    if not self.save_project(wait=True):
                        break
        finally:
            self.restore_selection(previous.session_id if previous else None, welcome)

    def refresh_recent(self) -> None:
        """Rebuild welcome and menu shortcuts from persisted recent project paths."""
        self.recent_menu.clear()
        for path in self.viewmodel.preferences.recent:
            self.recent_menu.addAction(
                self.icons.icon("description"),
                menu_text(Path(path).stem),
                lambda p=path: self.open_project(Path(p)),
            )
        if not self.viewmodel.preferences.recent:
            self.recent_menu.addAction("No recent projects").setEnabled(False)
        if self.welcome_window is not None:
            self.welcome_window.refresh_recent()

    def filter_scene(self, text: str) -> None:
        """Show matching names and their ancestors throughout the stored entity hierarchy."""

        def match(item: QTreeWidgetItem | None) -> bool:
            """Retain an ancestor whenever one of its descendants matches the query."""
            if item is None:
                return False
            children = [match(item.child(i)) for i in range(item.childCount())]
            visible = text.casefold() in item.text(0).casefold() or any(children)
            key = item.data(0, Qt.ItemDataRole.UserRole)
            mode = getattr(self, "object_edit", None)
            if mode and mode.active and key and key not in mode.ids:
                visible = False
            item.setHidden(not visible)
            return visible

        with QSignalBlocker(self.tree):
            for row in range(self.tree.topLevelItemCount()):
                match(self.tree.topLevelItem(row))

    def open_content_library(self, category: str = "All") -> None:
        """Open the offline browser with independent previews and the shared custom title bar."""
        self.viewmodel.playback.pause()
        if self.content_browser is None:
            self.content_browser = ContentBrowser(self, self.viewmodel.content)
        self.content_browser.collection.setCurrentText(
            category if isinstance(category, str) else "All"
        )
        self.content_browser.show()
        self.content_browser.raise_()
        self.content_browser.activateWindow()

    def content_applied(self, kind: str, key: str) -> None:
        """Frame newly applied content and enter its existing rig/mesh/animation workflow."""
        if kind in ("rig", "pose"):
            service = self.viewmodel.rig.service
            if service:
                rig = next((r for r in service.scene.skeletons if r.id == key), None)
                if rig and rig.bones:
                    self.viewmodel.rig.select(rig.bones[0].id)
                    from rigora.application_services.characters import CharacterService

                    owner = CharacterService(self.viewmodel.documents).object_root(rig.id)
                    self.viewmodel.scene.select((owner.id if owner else rig.id,))
            self.rig_workspace.set_mode(True)
            self.rig_workspace.frame_rig()
        elif kind in ("artwork", "deformation"):
            if kind == "artwork":
                self.viewmodel.mesh.select_mesh(key)
            if kind == "deformation" and self.viewmodel.mesh.service:
                stage = self.viewmodel.mesh.service.stage(key)
                self.viewmodel.mesh.select_mesh(stage.owner_id)
                self.viewmodel.mesh.stage_id = key
                self.mesh_panel.tools.setCurrentIndex(self.mesh_panel.tools.findData("control"))
            self.mesh_workspace.set_mode(True)
            self.mesh_workspace.load_assets()
            QTimer.singleShot(0, self.mesh_workspace.frame_artwork)
        else:
            self.rig_workspace.set_mode(False)
            self.mesh_workspace.set_mode(False)
            self.viewport.fit_canvas()
        self.statusBar().showMessage("Content applied · Undo is available", 5000)

    def show_retarget(self) -> None:
        """Open anatomical motion mapping for the active target document."""
        from rigora.presentation.widgets.retargeting import RetargetDialog

        self.retarget_dialog = RetargetDialog(self)
        self.retarget_dialog.open()

    def show_video_rig(self) -> None:
        """Open the local video-to-rig review workspace without starting downloads or inference."""
        from rigora.presentation.widgets.video_rig import VideoRigDialog

        prior = getattr(self, "video_rig_dialog", None)
        if prior:
            prior.close()
        self.video_rig_dialog = VideoRigDialog(self)
        self.video_rig_dialog.open()

    def show_facial(self) -> None:
        """Open vector expression controls and the local phoneme cue editor."""
        from rigora.presentation.widgets.facial import FaceDialog

        self.face_dialog = FaceDialog(self)
        self.face_dialog.open()

    def show_camera_tracking(self) -> None:
        """Open explicit local camera preview, calibration and editable take recording."""
        from rigora.presentation.widgets.camera_tracking import CameraTrackingDialog

        prior = getattr(self, "camera_dialog", None)
        if prior:
            prior.close()
        self.camera_dialog = CameraTrackingDialog(self)
        self.camera_dialog.open()

    def show_dynamics(self) -> None:
        """Open spring follow-through, cartoon motion helpers and simulation baking."""
        from rigora.presentation.widgets.dynamics import DynamicsDialog

        self.dynamics_dialog = DynamicsDialog(self)
        self.dynamics_dialog.open()

    def show_bone_editor(self) -> None:
        """Toggle the active project's modeless bone editor and its authoring tools."""
        from rigora.presentation.widgets.composer_editors import BoneEditor

        prior = getattr(self, "bone_editor", None)
        if prior:
            visible = prior.isVisible() and prior.document is self.viewmodel.documents
            prior.close()
            if visible:
                return
            prior.deleteLater()
        self.navigate()
        self.ensure_object_editor()
        if not self.object_edit.active and self.viewmodel.mesh.mesh_id:
            from rigora.application_services.characters import CharacterService

            actor = CharacterService(self.viewmodel.documents).owner(self.viewmodel.mesh.mesh_id)
            if actor:
                self.object_edit.enter(actor.id)
            elif not self.viewmodel.rig.selected:
                self.object_edit.enter(self.viewmodel.mesh.mesh_id)
        self.bone_editor = BoneEditor(self)
        self.bone_editor.show()
        self.command_actions["bone_editor"].setChecked(True)

    def show_character_wizard(self, _checked: bool = False, *, source_format: str = "SVG") -> None:
        """Open the modular character builder without starting any authoring operation."""
        if not self.viewmodel.documents.project:
            self.new_project()
        from rigora.presentation.widgets.character_wizard import CharacterWizard

        prior = getattr(self, "character_wizard", None)
        if prior is not None:
            prior.close()
            prior.deleteLater()
        self.character_wizard = CharacterWizard(self, source_format)
        self.character_wizard.show()
        self.viewmodel.extensions.emit_event("creator.opened")

    def show_vector_creator(self, kind: str = "Animals", source_format: str = "SVG") -> None:
        """Open the layered animal/object catalog with its own scratch transport."""
        from rigora.presentation.widgets.vector_creator import VectorCreator

        if prior := getattr(self, "vector_creator", None):
            prior.close()
            prior.deleteLater()
        self.vector_creator = VectorCreator(self, kind, source_format)
        self.vector_creator.show()

    def show_spring_editor(self) -> None:
        """Toggle spring editing while keeping the stage in ordinary selection mode."""
        from rigora.presentation.widgets.composer_editors import SpringEditor

        prior = getattr(self, "spring_editor", None)
        if prior:
            visible = prior.isVisible() and prior.document is self.viewmodel.documents
            prior.close()
            if visible:
                return
            prior.deleteLater()
        self.navigate()
        self.ensure_object_editor()
        self.spring_editor = SpringEditor(self)
        self.spring_editor.show()
        self.command_actions["spring_editor"].setChecked(True)

    def set_composer_target(self, target: str) -> None:
        """Choose sprite-only selection, part selection or bone-only manipulation."""
        self.composer_target = target
        if hasattr(self, "transform_target"):
            with QSignalBlocker(self.transform_target):
                self.transform_target.setCurrentIndex(self.transform_target.findData(target))
        enabled = (
            {"images", "bones", "groups"}
            if target == "part"
            else ({"bones"} if target == "bone_only" else {"images", "groups"})
        )
        for kind, check in self.selection_filters.items():
            check.setChecked(kind in enabled)
        self.viewmodel.scene.sprite_edit = target == "sprite"
        self.viewmodel.scene.part_edit = target == "part"
        if target == "bone_only":
            self.rig_workspace.set_mode(True)
            self.viewmodel.rig.set_tool("select")
        else:
            self.rig_workspace.set_mode(False)
            self.mesh_workspace.set_mode(False)
            self.viewmodel.scene.tool = "select"
        self.tool_status.setText(display_text(self.command_actions[target].text()))

    def toggle_selection_visibility(self) -> None:
        """Toggle authored visibility using the same scene command as the row icons."""
        model = self.viewmodel.scene
        if model.service and model.selected:
            record = model.service.record(model.selected[0])
            visible = getattr(record, "visible", record.extra.get("visible", True))
            model.run(lambda s: s.flags(model.selected, visible=not visible))

    def isolate_selection(self) -> None:
        """Toggle whole-object composition without authoring visibility or camera changes."""
        if self.object_edit.active:
            self.object_edit.exit()
            return
        selected = (*self.viewmodel.scene.selected, *self.viewmodel.rig.selected)
        if selected:
            self.object_edit.enter(selected[0])
        self.command_actions["isolate"].setChecked(self.object_edit.active)

    def attach_selection(self) -> None:
        """Open the Scene attachment card with the selected whole Object as its source."""
        from rigora.presentation.widgets.scene_attachments import SceneAttachmentsDialog

        if not self.viewmodel.documents.project:
            return
        if self.viewmodel.documents.animation_context:
            self.statusBar().showMessage(
                "Return to Scene to attach placed objects. "
                "Use Attachment points here to add grips.",
                8000,
            )
            return
        prior = getattr(self, "scene_attachments_dialog", None)
        if prior:
            prior.close()
            prior.deleteLater()
        self.scene_attachments_dialog = SceneAttachmentsDialog(self)
        self.scene_attachments_dialog.show()

    def show_attachment_points(self) -> None:
        """Edit reusable grips on the selected Object or bone in either editing context."""
        from rigora.presentation.viewmodels.scene_attachments import AttachmentViewModel
        from rigora.presentation.widgets.scene_attachments import AttachmentPointsDialog

        if not self.viewmodel.documents.project:
            return
        keys = self.viewmodel.rig.selected or self.viewmodel.scene.selected
        if not keys:
            self.statusBar().showMessage("Select an object or bone to edit its grip points.", 8000)
            return
        self.grip_model = AttachmentViewModel(self.viewmodel, self)
        self.grip_dialog = AttachmentPointsDialog(self.grip_model, keys[0], self)
        self.grip_dialog.show()

    def show_bindings(self) -> None:
        """Open the live scene relationship inspector with the current editor selection."""
        from rigora.presentation.widgets.bindings import BindingsDialog

        if not self.viewmodel.documents.project:
            return
        prior = getattr(self, "bindings_dialog", None)
        if prior:
            prior.close()
            prior.deleteLater()
        self.bindings_dialog = BindingsDialog(self)
        target = self.character_panel.bones.currentData()
        selected = self.viewmodel.scene.selected or self.viewmodel.rig.selected
        if target and target not in selected:
            index = self.bindings_dialog.target.findData(target)
            if index >= 0:
                self.bindings_dialog.target.setCurrentIndex(index)
        self.bindings_dialog.show()

    def unbind_selection(self) -> None:
        """Release selected connections and their bone physics without deleting any endpoint."""
        from rigora.application_services.bindings import BindingService

        vm = self.viewmodel
        keys = vm.scene.selected or vm.rig.selected
        vm.scene.run(lambda _: BindingService(vm.documents).unbind(keys))
        self.character_panel.status.setText(vm.scene.error)
        self.character_panel.status.setVisible(bool(vm.scene.error))
        if vm.scene.error:
            self.statusBar().showMessage(vm.scene.error, 8000)

    def asset_icon(self, key: str | None, fallback: str = "image") -> QIcon:
        """Use asynchronously decoded originals for source/scene thumbnails."""
        image = self.viewport.artwork.images.get(key or "")
        return QIcon(QPixmap.fromImage(image)) if image is not None else self.icons.icon(fallback)

    def refresh_asset_thumbnails(self, ready: set[str] | None = None) -> None:
        """Update decoded icons in place, indexing scene records once for the whole batch."""
        if hasattr(self, "timeline") and self.timeline.action_editor:
            self.timeline.action_editor.refresh_icons()
        for index in range(self.project_assets.count()):
            item = self.project_assets.item(index)
            key = item.data(Qt.ItemDataRole.UserRole)
            if key in self.viewport.artwork.images and (ready is None or key in ready):
                item.setIcon(self.asset_icon(key))
        if hasattr(self, "scene_workspace"):
            service = self.viewmodel.scene.service
            records = service.records() if service else {}
            for key, row in self.scene_workspace.items.items():
                if key in records:
                    asset = getattr(records[key], "asset_id", None)
                    if asset in self.viewport.artwork.images and (ready is None or asset in ready):
                        row.setIcon(0, self.scene_workspace.row_icon(records[key]))

    def remove_project_asset(self) -> None:
        """Remove the focused unused source through ordinary reversible project history."""
        item = self.project_assets.currentItem()
        if item and (key := item.data(Qt.ItemDataRole.UserRole)):
            self.viewmodel.scene.run(lambda s: s.remove_asset(key))

    def asset_context_menu(self, point: Any) -> None:
        """Offer placement and deletion on registered source thumbnails."""
        item = self.project_assets.itemAt(point)
        if item:
            self.project_assets.setCurrentItem(item)
            menu = QMenu(self.project_assets)
            menu.addAction("Place in scene", lambda: self.place_asset(item))
            menu.addAction("Replace artwork…", self.replace_project_artwork)
            menu.addAction("Remove source", self.remove_project_asset)
            self.plugin_workspace.populate_context(
                menu, "assets", asset_id=item.data(Qt.ItemDataRole.UserRole)
            )
            menu.exec(self.project_assets.viewport().mapToGlobal(point))

    def replace_project_artwork(self) -> None:
        """Choose a source revision and validate it on the existing import worker."""
        item = self.project_assets.currentItem()
        if not item:
            return
        filename, _ = choose_open_file(
            self, "Replace shared artwork", "", "Artwork (*.svg *.png *.jpg *.jpeg *.webp *.bmp)"
        )
        if filename:
            source = Path(filename)
            self.viewmodel.media.submit(
                "asset_replace",
                {"asset_id": item.data(Qt.ItemDataRole.UserRole), "path": str(source)},
                source.parent,
                (source.parent,),
            )

    def drop_asset_in_tree(
        self, key: str, session: str, parent: str | None, before: str | None
    ) -> None:
        """Place reusable sources directly into a scene folder or a chosen render position."""
        self.drop_project_asset(
            key, session, QPointF(self.viewport.rect().center()), parent, before, True
        )

    def add_external_assets(
        self,
        paths: list[str],
        *,
        place: bool = False,
        parent: str | None = None,
        before: str | None = None,
        position: QPointF | None = None,
        on_adopt: Callable[[Any, dict[str, Any]], None] | None = None,
    ) -> None:
        """Decode a bounded external file drop on the existing worker, then adopt it atomically."""
        if self.viewmodel.media.busy:
            self.statusBar().showMessage(
                "An asset import is running. Drop the next batch when it finishes.", 8000
            )
            return
        if self.viewmodel.documents.project is None:
            self.viewmodel.new_project()
        arguments: dict[str, Any] = {
            "paths": paths,
            "place": place,
            "center": place,
            "parent": parent,
            "before": before,
        }
        if position is not None:
            arguments["position"] = [position.x(), position.y()]
        roots = tuple(dict.fromkeys(Path(path).absolute().parent for path in paths))
        if on_adopt is None and place and self.object_edit.active:
            on_adopt = self.object_edit.adoption()
        self.viewmodel.media.submit(
            "assets_import", arguments, Path.cwd(), roots, on_adopt=on_adopt
        )
        self.statusBar().showMessage(f"Adding {len(paths)} source files…")

    def drop_external_on_stage(self, paths: list[str], point: QPointF) -> None:
        """Import original sources and center their artwork in the camera view."""
        self.add_external_assets(paths, place=True, position=self.viewport.scene_point(point))

    def drop_external_in_tree(
        self, paths: list[str], parent: str | None, before: str | None
    ) -> None:
        """Import and instantiate external files inside the hovered folder with explicit order."""
        self.add_external_assets(
            paths,
            place=True,
            parent=parent,
            before=before,
            position=self.viewport.scene_point(QPointF(self.viewport.rect().center())),
        )

    def asset_import_status(self) -> None:
        """Expose rejected or stale external imports even when the import dialog is closed."""
        if self.viewmodel.media.error:
            self.statusBar().showMessage(self.viewmodel.media.error, 15000)

    def assets_added(self, data: dict[str, Any]) -> None:
        """Report per-file failures after worker adoption instead of claiming a complete import."""
        self.library_tabs.setCurrentWidget(self.project_assets_page)
        if "files" in data:
            failures = [
                f"{row['name']}: {row['error']}"
                for row in data["files"]
                if row["status"] == "failed"
            ]
            self.statusBar().showMessage(
                f"Added {data['imported']} assets · {data['failed']} failed"
                + (" · " + "; ".join(failures) if failures else ""),
                15000,
            )

    def dragEnterEvent(self, event: Any) -> None:
        """Accept file drops over otherwise unhandled application surfaces."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event: Any) -> None:
        """Treat drops outside the stage/Scene tree as source-only imports."""
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if 0 < len(paths) <= 128:
            self.add_external_assets(paths)
            event.acceptProposedAction()
        else:
            event.ignore()

    def clear_asset_preview(self) -> None:
        """Discard temporary asset geometry without changing source assets or history."""
        self.project_assets.set_scene_preview_active(False)
        if hasattr(self, "object_assets"):
            self.object_assets.cards.set_scene_preview_active(False)
        if self._asset_hover_signature is not None:
            self._asset_hover_signature = None
            self.viewport.drop_pose = None
            self.viewport.drop_translation = QPointF()
            self.viewport.drop_message = ""
            self.viewport.update()

    def _asset_drop_parent(self) -> str | None:
        """Resolve a transform container for pointer placement inside Object Editor."""
        service = self.viewmodel.scene.service
        key = self.object_edit.key
        return (
            key
            if self.object_edit.active
            and service
            and isinstance(service.records().get(key), (Group, SceneObject))
            else None
        )

    def preview_project_asset(self, key: str, session: str, point: QPointF | None = None) -> None:
        """Reuse one centered source preview while translating it with the pointer."""
        from dataclasses import replace

        from rigora.application_services.asset_pipeline import AssetPipeline
        from rigora.application_services.characters import CharacterService

        doc = self.viewmodel.documents
        signature = (doc.context_key, doc.project, key, doc.animation_context, point is not None)
        if doc.project is None or session != doc.session_id:
            self.clear_asset_preview()
            return
        translation = point - self.viewport.offset if point is not None else QPointF()
        if self._asset_hover_signature == signature:
            self.project_assets.set_scene_preview_active(point is not None)
            self.object_assets.cards.set_scene_preview_active(point is not None)
            self.viewport.drop_translation = translation
            self.viewport.update()
            return
        self.clear_asset_preview()
        self.project_assets.set_scene_preview_active(point is not None)
        self.object_assets.cards.set_scene_preview_active(point is not None)
        try:
            scratch = doc.fork()
            scratch.set_animation_context(doc.animation_context, None, prepare=False)
            if key.startswith("object:"):
                from rigora.application_services.object_library import ObjectLibraryService

                root = ObjectLibraryService(scratch).place(
                    key[7:], (0, 0) if point is not None else None
                )
                ids = CharacterService(scratch).members(root)
                result = {
                    "object_ids": tuple(ids),
                    "mesh_ids": CharacterService(scratch).meshes_for((root,)),
                }
            else:
                result = AssetPipeline(scratch).place_source(
                    key,
                    position=(0, 0) if point is not None else None,
                    parent=self._asset_drop_parent() if point is not None else None,
                )
            if self.object_edit.active:
                self.object_edit.adoption(recenter=point is None)(scratch, result)
            pose = scratch.animation.pose
            ids = set(result["object_ids"])
            self.viewport.drop_pose = replace(
                pose,
                nodes={k: n for k, n in pose.nodes.items() if k in ids},
                meshes={k: m for k, m in pose.meshes.items() if m.object_id in ids},
                render_order=tuple(k for k in pose.render_order if k in ids),
            )
            self.viewport.drop_translation = translation
            self.viewport.drop_message = (
                "Drop to place here" if point is not None else "Drop to place at camera center"
            )
            self._asset_hover_signature = signature
            self.viewport.update()
        except ProjectError as error:
            self.viewport.drop_message = str(error)
            self.viewport.update()

    def drop_project_asset(
        self,
        key: str,
        session: str,
        point: QPointF | None = None,
        parent: str | None = None,
        before_id: str | None = None,
        into_tree: bool = False,
    ) -> None:
        """Place artwork centered at the drop point; tree/menu placement keeps its default."""
        from rigora.application_services.asset_pipeline import AssetPipeline
        from rigora.application_services.characters import CharacterService

        self.clear_asset_preview()
        doc = self.viewmodel.documents
        if session != doc.session_id or doc.project is None:
            self.statusBar().showMessage("Drag an asset from the active project.", 6000)
            return
        try:
            with doc.command_group("Place object resource"):
                if key.startswith("object:"):
                    from rigora.application_services.object_library import ObjectLibraryService

                    root = ObjectLibraryService(doc).place(
                        key[7:],
                        self.viewport.scene_point(point).toTuple()
                        if point is not None and not into_tree
                        else None,
                        parent if into_tree else self._asset_drop_parent(),
                    )
                    result = {
                        "object_ids": (root,),
                        "mesh_ids": CharacterService(doc).meshes_for((root,)),
                    }
                else:
                    result = AssetPipeline(doc).place_source(
                        key,
                        parent=parent
                        if into_tree
                        else self._asset_drop_parent()
                        if point is not None
                        else None,
                        before=before_id if into_tree else None,
                        position=self.viewport.scene_point(point).toTuple()
                        if point is not None and not into_tree
                        else None,
                    )
                if self.object_edit.active:
                    self.object_edit.adoption(recenter=point is None or into_tree)(doc, result)
            self.viewmodel.changed.emit()
            if result["mesh_ids"]:
                self.viewmodel.mesh.select_mesh(result["mesh_ids"][0])
            self.rig_workspace.set_mode(False)
            self.mesh_workspace.set_mode(False)
            self.scene_workspace.select_entries(tuple(result["object_ids"]))
        except ProjectError as error:
            self.statusBar().showMessage(str(error), 10000)

    def show_rigging_guide(self) -> None:
        """Open or resume the modeless guide for the active project tab."""
        from rigora.presentation.widgets.rigging_guide import RiggingGuideDialog

        if self.viewmodel.documents.project is None:
            self.viewmodel.new_project()
        guide = getattr(self, "rigging_guide", None)
        if guide is None or guide.document is not self.viewmodel.documents:
            if guide:
                guide.close()
            self.rigging_guide = guide = RiggingGuideDialog(self)
        else:
            guide.refresh()
        guide.show()
        guide.raise_()

    def show_automation(self) -> None:
        """Open project inspection and local MCP connection settings."""
        if self.automation_dialog is None:
            self.automation_dialog = AutomationDialog(self)
        self.automation_dialog.refresh()
        self.automation_dialog.show()
        self.automation_dialog.raise_()

    def show_output(self) -> None:
        """Open reusable output settings and the application's owned render queue."""
        if self.output_dialog is None:
            self.output_dialog = OutputDialog(self)
        self.output_dialog.show()
        self.output_dialog.raise_()

    def show_media_import(self) -> None:
        """Open source-preserving sequence, sheet, layered-art and audio import controls."""
        if self.media_dialog is None:
            self.media_dialog = MediaImportDialog(self)
        self.media_dialog.show()
        self.media_dialog.raise_()

    def export_preview(self) -> None:
        """Render an actual SVG frame through the public API on the existing bounded worker pool."""
        from rigora.api import RigoraAPI

        document = self.viewmodel.documents
        if document.project is None:
            return
        filename, _ = choose_save_file(
            self, "Export SVG preview", "preview.svg", "SVG preview (*.svg)"
        )
        if not filename:
            return
        path = Path(filename)
        if (
            path.exists()
            and ask_question(
                self,
                "Replace preview?",
                "Replace the selected existing SVG preview?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        snapshot = document.fork()
        frame = document.animation.pose.frame

        def render() -> str:
            """Keep evaluated geometry and file output independent of subsequent GUI edits."""
            api = RigoraAPI(path.parent, document=snapshot)
            result = api.execute(
                "frame_render", {"path": path.name, "frame": frame, "approve_overwrite": True}
            )
            return str(result.data["frames"][0]["path"])

        def complete(name: str) -> None:
            """Report a complete atomic preview after worker rendering and writing finish."""
            if not self._closed:
                self.statusBar().showMessage(f"Exported SVG preview: {name}", 8000)

        self.statusBar().showMessage("Rendering SVG preview…")
        self.viewmodel.content.background(render, complete)

    def register_asset(self) -> None:
        """Register opaque source bytes in the active project without claiming to render them."""
        if self.viewmodel.documents.project is None:
            return
        filename, _ = choose_open_file(
            self,
            "Register project source",
            "",
            "All files (*)",
        )
        if filename:
            try:
                self.viewmodel.register_asset(Path(filename))
                self.statusBar().showMessage(
                    "Source embedded. Use Import artwork to create a visible mesh.", 8000
                )
            except ProjectError as error:
                self._error(error)

    def embed_linked_assets(self) -> None:
        """Convert every resolvable linked asset into a portable embedded project source."""
        try:
            self.viewmodel.embed_linked_assets()
        except ProjectError as error:
            self._error(error)

    def open_recent(self, item: QListWidgetItem) -> None:
        """Resolve a recent-project item and open it through the guarded document flow."""
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.open_project(Path(path))

    def _error(self, error: Exception) -> None:
        """Present an actionable application error without discarding the active document."""
        show_warning(self, "Rigora could not complete the action", str(error))

    def confirm_discard(self) -> bool:
        """Resolve the active document's unsaved work through Save, Discard, or Cancel."""
        document = self.viewmodel.documents
        if "save:" + document.session_id in self.viewmodel.project_io.jobs:
            self.viewmodel.project_io.wait_saved(document)
        if not document.dirty:
            return True
        result = ask_question(
            self,
            "Save changes?",
            "This project has unsaved changes. Save them before continuing?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if result == QMessageBox.StandardButton.Save:
            return self.save_project(wait=True)
        return result == QMessageBox.StandardButton.Discard

    def new_project(self) -> None:
        """Collect valid project settings and create a separate unsaved tab."""
        dialog = ProjectSettingsDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            name, scene_name, settings = dialog.values()
            from rigora.domain.project import Project, Scene

            Project(name=name, scenes=(Scene(name=scene_name, settings=settings),))
            self.viewmodel.new_project(name, settings)
            self.viewmodel.edit_settings(name, scene_name, settings)
        except ProjectError as error:
            self._error(error)

    def show_recovery(self) -> None:
        """Inspect recovery packages without replacing a live project or its original file."""
        from rigora.presentation.widgets.recovery_dialog import RecoveryDialog

        self.recovery_dialog = RecoveryDialog(self, self.viewmodel.project_io)
        self.recovery_dialog.show()

    def show_state_machine(self) -> None:
        """Author/preview parameter-driven transitions between an Object's source actions."""
        from rigora.presentation.widgets.state_machine_editor import StateMachineEditor

        if self.viewmodel.documents.project is not None:
            self.state_machine = StateMachineEditor(self)
            self.state_machine.show()

    def show_camera_shots(self) -> None:
        """Inspect/author camera shots, continuous framing transitions and follow targets."""
        from rigora.presentation.widgets.camera_shots import CameraShots

        if self.viewmodel.documents.project is not None:
            self.camera_shots = CameraShots(self)
            self.camera_shots.show()

    def show_game_tools(self) -> None:
        """Author gameplay regions and deterministic rendered particle emitters."""
        from rigora.presentation.widgets.game_tools import GameTools

        if self.viewmodel.documents.project is not None:
            self.game_tools = GameTools(self)
            self.game_tools.show()

    def show_movement_views(self) -> None:
        """Configure movement-driven authored views through shared animation services."""
        from rigora.presentation.widgets.movement_views import MovementViews

        if self.viewmodel.documents.project is not None:
            self.movement_views = MovementViews(self)
            self.movement_views.show()

    def show_broadcast(self) -> None:
        """Open explicit local browser-source output without starting a remote stream."""
        from rigora.presentation.widgets.broadcast import BroadcastOutput

        if self.viewmodel.documents.project is not None:
            if prior := getattr(self, "broadcast_output", None):
                prior.close()
            self.broadcast_output = BroadcastOutput(self)
            self.broadcast_output.show()

    def show_curve_editor(self) -> None:
        """Edit cubic vector artwork and motion paths through original source controls."""
        from rigora.presentation.widgets.path_editor import PathEditor

        if self.viewmodel.documents.project is not None:
            self.path_editor = PathEditor(self)
            self.path_editor.show()

    def show_audio_tracks(self) -> None:
        """Author independent sound/music/voice placements in the current action."""
        from rigora.presentation.widgets.audio_mixer import AudioMixer

        if self.viewmodel.documents.project is not None:
            self.audio_mixer = AudioMixer(self)
            self.audio_mixer.show()

    def show_foot_contacts(self) -> None:
        """Author support intervals for the active scene or edited Object."""
        from rigora.presentation.widgets.contact_editor import ContactEditor

        if self.viewmodel.documents.project is None:
            return
        self.contact_editor = ContactEditor(self)
        self.contact_editor.show()

    def show_production_inspector(self) -> None:
        """Open live performance counters and explicit background health checks."""
        from rigora.presentation.widgets.production_inspector import ProductionInspector

        if not hasattr(self, "production_inspector"):
            self.production_inspector = ProductionInspector(self)
        self.production_inspector.show()

    def restore_previous_session(self) -> None:
        """Reopen saved tabs behind Welcome; dirty snapshots require explicit recovery selection."""
        if self.viewmodel.workspace.documents:
            return
        for state in self.viewmodel.project_io.store.session():
            path = Path(state["path"])
            if path.is_file():
                self.viewmodel.project_io.open(path, state, background=True)

    def open_project(self, path: Path | None = None) -> None:
        """Open a package or backup and offer recovery when a valid predecessor exists."""
        if path is None:
            filename, _ = choose_open_file(
                self,
                "Open Rigora project",
                "",
                "Rigora projects (*.rigora);;Project backups (*.rigora.bak)",
            )
            if not filename:
                return
            path = Path(filename)
        try:
            if path.name.endswith(".rigora.bak"):
                self.viewmodel.project_io.open(path, recovery=True)
            else:
                self.viewmodel.project_io.open(path)
        except ProjectError as error:
            self.offer_backup(path, str(error))

    def offer_backup(self, path: Path, error: str) -> None:
        """Keep failed background opens recoverable through the existing explicit backup choice."""
        backup = path.with_suffix(".rigora.bak")
        if (
            backup != path
            and backup.exists()
            and ask_question(
                self,
                "Project could not be opened",
                f"{error}\n\nOpen the last backup as an unsaved recovery?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        ):
            self.viewmodel.project_io.open(backup, recovery=True)
        else:
            self._error(ProjectError(error))

    def save_project(self, *, save_as: bool = False, wait: bool = False) -> bool:
        """Collect a destination when needed and publish after explicit overwrite resolution."""
        try:
            doc = self.object_assets.persistence_document(self.viewmodel.documents)
        except ProjectError as error:
            self._error(error)
            return False
        if doc.project is None:
            return False
        path: Path | None = None
        overwrite = False
        if save_as or doc.path is None:
            filename, _ = choose_save_file(
                self,
                "Save Rigora project",
                str(doc.path or Path.home() / f"{doc.project.name}.rigora"),
                "Rigora projects (*.rigora)",
            )
            if not filename:
                return False
            path = Path(filename)
            if not path.suffix:
                path = path.with_suffix(".rigora")
            if path.exists() and path.resolve() != doc.path:
                if (
                    ask_question(
                        self,
                        "Replace existing project?",
                        f"Replace {path.name}? Its previous contents will be kept in a "
                        f".rigora.bak backup.",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No,
                    )
                    != QMessageBox.StandardButton.Yes
                ):
                    return False
                overwrite = True
        try:
            accepted = self.viewmodel.project_io.save(doc, path, overwrite=overwrite)
            if not accepted or not wait:
                return accepted
            self._waiting_for_save = True
            try:
                return self.viewmodel.project_io.wait_saved(doc)
            finally:
                self._waiting_for_save = False
        except ProjectError as error:
            self._error(error)
            return False

    def project_settings(self) -> None:
        """Apply validated settings to the active document through its undoable service."""
        project = self.viewmodel.documents.project
        if project is None:
            return
        dialog = ProjectSettingsDialog(self, project, self.viewmodel.documents.scene)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                self.viewmodel.edit_settings(*dialog.values())
            except ProjectError as error:
                self._error(error)

    def actual_size(self) -> None:
        """Set canvas zoom to one device-independent pixel per scene pixel."""
        self.viewport.zoom_at(1 / self.viewport.zoom)

    def update_zoom(self, zoom: float) -> None:
        """Display the current canvas zoom percentage in the status bar."""
        text = f"{zoom * 100:.1f}".rstrip("0").rstrip(".") + "%"
        if hasattr(self, "zoom_status"):
            self.zoom_status.setText(text)
        self.canvas_zoom.setText(text)

    def toggle_grid(self) -> None:
        """Apply the grid action's checked state to the current viewport."""
        self.viewport.grid_visible = self.command_actions["grid"].isChecked()
        self.viewport.update()

    def toggle_bone_overlay(self) -> None:
        """Toggle armature rendering while retaining editable geometry and hit testing."""
        self.viewport.show_bones = self.command_actions["bone_overlay"].isChecked()
        self.viewport.update()

    def toggle_checker(self) -> None:
        """Apply the transparency action's checked state to the current viewport."""
        self.viewport.checker_visible = self.command_actions["checker"].isChecked()
        self.viewport.update()

    def set_viewport_wireframe(self, enabled: bool) -> None:
        """Keep the preview header and floating Bone Editor's mesh overlay in sync."""
        self.viewport.mesh_wireframe = enabled
        with QSignalBlocker(self.wireframe_option):
            self.wireframe_option.setChecked(enabled)
        editor = getattr(self, "bone_editor", None)
        if editor:
            with QSignalBlocker(editor.wireframe):
                editor.wireframe.setChecked(enabled)
            editor.sync_subdivision_controls()
        self.viewport.update()

    def change_bone_movement(self, scope: str) -> None:
        """Choose an explicit drag scope without changing geometry or selection."""
        self.viewport.cancel_rig_gesture()
        self.viewport.bone_movement = scope
        self.viewport.refresh_cursor()

    def change_joint_angle(self, angle: float) -> None:
        """Commit the selected joints' fold limit through the shared rig service."""
        model = self.viewmodel.rig
        model.run(lambda service: service.set_minimum_joint_angle(model.selected, angle))

    def refresh_tool_options(self) -> None:
        """Expose only options relevant to the current viewport interaction context."""
        if not hasattr(self, "bone_options"):
            return
        rig, mesh = self.viewmodel.rig, self.viewmodel.mesh
        self.selection_filters["bones"].setVisible(self.object_edit.active)
        pan = self.viewport.pan_tool
        for key, tools in (
            ("mesh", ("vertex", "edge", "triangle", "insert", "soft")),
            ("weights", ("paint",)),
            ("deform", ("control",)),
        ):
            self.command_actions[key].setChecked(mesh.active and mesh.tool in tools)
        selecting_bones = rig.active and rig.tool == "select" and not pan
        self.bone_options.setVisible(selecting_bones)
        self.mesh_drag_options.setVisible(
            mesh.active
            and mesh.tool in ("vertex", "edge", "triangle", "control", "soft")
            and not pan
        )
        self.soft_drag_button.setChecked(mesh.tool == "soft")
        self.soft_drag_radius.setEnabled(mesh.tool == "soft")
        self.soft_drag_strength.setEnabled(mesh.tool == "soft")
        self.soft_drag_falloff.setEnabled(mesh.tool == "soft")
        self.wireframe_option.setVisible(not pan and rig.active)
        self.selection_options.setVisible(not (rig.active or mesh.active or pan))
        hint = (
            "Drag to pan · Wheel to zoom"
            if pan
            else "Snap to joints · Alt: free placement"
            if rig.active and rig.tool == "draw"
            else "Drag an area"
            if mesh.active and mesh.tool == "soft"
            else "Ctrl: multi-select · Handles: transform"
            if mesh.active
            else ""
        )
        self.context_hint.setText(hint)
        self.context_hint.setVisible(bool(hint))
        project = self.viewmodel.documents.project
        joints = [
            bone
            for skeleton in (self.viewmodel.documents.scene.skeletons if project else ())
            for bone in skeleton.bones
            if bone.id in rig.selected and bone.parent_id
        ]
        self.minimum_joint_angle.setEnabled(bool(joints))
        if joints and not self.minimum_joint_angle.hasFocus():
            values = {float(b.extra.get("minimum_joint_angle", 0)) for b in joints}
            with QSignalBlocker(self.minimum_joint_angle):
                self.minimum_joint_angle.setValue(next(iter(values)) if len(values) == 1 else 30)
            self.minimum_joint_angle.setPrefix("" if len(values) == 1 else "≈")

    def toggle_soft_drag(self, enabled: bool) -> None:
        """Switch area deformation and point editing without changing the selected artwork."""
        mesh = self.viewmodel.mesh
        tool = "soft" if enabled else "control" if mesh.stage_id else "vertex"
        self.mesh_panel.tools.setCurrentIndex(self.mesh_panel.tools.findData(tool))

    def toggle_pan(self) -> None:
        """Select the drag-to-pan tool and update its cursor and status text."""
        self.viewport.pan_tool = self.command_actions["pan"].isChecked()
        self.viewport.setCursor(
            Qt.CursorShape.OpenHandCursor if self.viewport.pan_tool else Qt.CursorShape.ArrowCursor
        )
        self.tool_status.setText("Pan canvas" if self.viewport.pan_tool else "Navigate")
        self.refresh_tool_options()

    def navigate(self) -> None:
        """Leave specialized authoring tools and restore scene/bone selection and transforms."""
        self.end_subdivision_preview()
        if hasattr(self, "shape_workspace") and self.shape_workspace.active:
            self.shape_workspace.deactivate()
        self.command_actions["navigate"].setChecked(True)
        self.viewport.pan_tool = False
        self.viewport.unsetCursor()
        self.tool_status.setText("Select & transform · Drag to move · Handles to scale/rotate")
        self.viewmodel.scene.tool = "select"
        if self.viewmodel.mesh.active:
            self.mesh_workspace.set_mode(False)
        if self.viewmodel.rig.active:
            self.viewmodel.rig.cancel_preview()
            self.viewmodel.rig.set_tool("select")
        self.refresh_tool_options()
        self.viewport.refresh_cursor()

    def ensure_object_editor(self, key: str | None = None) -> None:
        """Route part, mesh and rig tools to the selected object's isolated workspace."""
        vm = self.viewmodel
        key = key or next(iter((*vm.scene.selected, *vm.rig.selected)), vm.mesh.mesh_id)
        if self.object_edit.active and (not key or key in self.object_edit.ids):
            return
        if not key:
            scene = vm.documents.scene if vm.documents.project else None
            if (
                scene is not None
                and not scene.objects
                and any(rig.bones for rig in scene.skeletons)
            ):
                # Bare rig studies retain their scene timelines without inserting an empty Object.
                return
            self.scene_workspace.new_object()
            key = vm.scene.selected[0]
        self.object_edit.enter(key)

    def move_bones(self) -> None:
        """Activate live translation of selected bones or complete selected root branches."""
        if self.viewmodel.rig.active or self.viewmodel.rig.selected:
            self.rig_workspace.set_mode(True)
            self.viewmodel.rig.set_tool("move")
        else:
            self.viewmodel.scene.tool = "move"
            self.viewport.pan_tool = False
            self.tool_status.setText("Move scene selection")

    def transform_tool(self, mode: str) -> None:
        """Activate object transforms, bone rotation or selected FFD control scaling in context."""
        if self.viewmodel.mesh.active and self.viewmodel.mesh.tool in (
            "vertex",
            "edge",
            "triangle",
        ):
            self.viewmodel.mesh.cancel_preview()
            self.viewmodel.mesh.transform_mode = mode
            self.viewport.update()
        elif (
            self.viewmodel.mesh.active
            and self.viewmodel.mesh.stage_id
            and mode in ("move", "rotate", "scale")
        ):
            self.mesh_workspace.activate_tool("control")
            self.mesh_panel.control_mode.setCurrentText(mode.title())
        elif self.viewmodel.rig.active and mode == "rotate":
            self.viewmodel.rig.set_tool("rotate")
        else:
            self.rig_workspace.set_mode(False)
            self.mesh_workspace.set_mode(False)
            self.viewmodel.scene.tool = mode
        self.viewport.pan_tool = False
        self.tool_status.setText(f"{mode.title()} selection")

    def add_springs(self) -> None:
        """Apply real secondary-motion constraints to selected child bones or a selected root's
        chain.
        """
        model = self.viewmodel.rig
        if not model.service or not model.selected:
            self.statusBar().showMessage(
                "Select a child bone or chain root, then add spring follow-through.", 10000
            )
            return

        def add(service: Any) -> None:
            """Group new spring constraints while keeping existing owners and fixed roots intact."""
            selected = set(model.selected)
            bones = [b for rig in service.scene.skeletons for b in rig.bones]
            for bone in bones:
                if bone.parent_id in selected:
                    selected.add(bone.id)
            existing = {c.owner_id for c in service.scene.constraints if c.kind == "spring"}
            with service.document.command_group("Add spring follow-through"):
                for bone in bones:
                    if bone.id in selected and bone.parent_id and bone.id not in existing:
                        service.add_constraint(bone.id, "spring")

        model.run(add)
        self.statusBar().showMessage(
            "Spring follow-through enabled · Adjust it in Rig → Constraints; "
            "drag a bone or play animation.",
            10000,
        )

    def place_asset(self, item: QListWidgetItem) -> None:
        """Instantiate one library image without copying its original source or other instances."""
        key = item.data(Qt.ItemDataRole.UserRole)
        if not key:
            return
        try:
            document = self.viewmodel.documents
            asset = (
                next((a for a in document.project.assets if a.id == key), None)
                if document.project
                else None
            )
            if asset is None:
                return
            if self.object_edit.active and asset.kind in ("raster", "vector", "sequence"):
                self.drop_project_asset(key, document.session_id)
                return
            if asset.kind == "audio":
                self.statusBar().showMessage(
                    f"Audio · {asset.extra.get('duration_seconds', 0):.2f} seconds "
                    "· Original WAV retained",
                    10000,
                )
                return
            elif asset.kind == "sequence" and not any(
                key in asset.extra for key in ("sprite_sequence", "layered_layout")
            ):
                self.statusBar().showMessage(
                    "Original source retained. Choose its sequence or layered layout "
                    "to place editable content.",
                    10000,
                )
                return
            mesh_id = self.viewmodel.place_registered_asset(key)
            if mesh_id is None:
                return
            self.rig_workspace.set_mode(False)
            self.mesh_workspace.set_mode(False)
            self.command_actions["navigate"].setChecked(True)
            self.viewport.pan_tool = False
            self.mesh_workspace.frame_artwork()
        except ProjectError as error:
            self._error(error)

    def toggle_theme(self) -> None:
        """Request the opposite supported workspace palette from the ViewModel."""
        self.viewmodel.set_theme("light" if self.themes.name == "dark" else "dark")

    def apply_theme(self, name: str) -> None:
        """Apply and persist a palette, refreshing icons and canvas colors."""
        self.themes.apply(name)
        self.viewmodel.preferences.data["theme"] = self.themes.name
        self.viewport.theme = self.themes.name
        self.viewport.update()
        if self.content_browser:
            self.content_browser.preview.theme = self.themes.name
            self.content_browser.preview.update()
        self.command_actions["theme"].setChecked(name == "light")
        self.command_actions["theme"].setText("Light theme")
        self.command_actions["theme"].setToolTip(
            "Switch to light theme" if name == "dark" else "Switch to dark theme"
        )
        self.refresh_icons()
        self.refresh_document()
        warning = self.viewmodel.preferences.save()
        if warning:
            self.statusBar().showMessage(warning, 15000)

    def command_palette(self) -> None:
        """Open the searchable launcher over the shared action registry."""
        aliases = {"move", "object_move", "rotate", "scale"}
        palette = CommandPalette(
            self,
            [action for key, action in self.command_actions.items() if key not in aliases],
            self.icons,
        )
        palette.exec()

    def restore_layout(self) -> None:
        """Reset panel placement and dividers without changing projects or other preferences."""
        self.object_edit.exit()
        self.main_tools.restore_order(())
        for dock in self.docks.values():
            dock.setFloating(False)
        self.restoreState(QByteArray(self._default_layout), 1)
        cast(ToolboxDock, self.docks["tools"]).reset_position()
        self.docks["tools"].show()
        self.resizeDocks(
            [self.docks["hierarchy"], self.docks["assets"]],
            [280, ContentShelf.DEFAULT_WIDTH],
            Qt.Orientation.Horizontal,
        )
        self.resizeDocks([self.docks["timeline"]], [280], Qt.Orientation.Vertical)
        self._scene_timeline_height = 280
        self.timeline.splitter.setSizes([260, 850])
        self.timeline.anchor_track_columns(reset=True)
        self.library_tabs.setCurrentIndex(0)
        self.inspector.setCurrentIndex(0)
        self.timeline.pages.setCurrentIndex(0)
        data = self.viewmodel.preferences.data
        for key in (
            "panel_state",
            "floating_panels",
            "object_editor_width",
            "object_editor_timeline_height",
            "toolbox_placement",
            "toolbox_visible",
        ):
            data.pop(key, None)
        self._save_workspace()

    def _save_workspace(self, *, timeline_height: int | None = None) -> None:
        """Persist the Scene dock arrangement and UI state independently of project data."""
        store = self.viewmodel.preferences
        store.data["main_toolbar_order"] = self.main_tools.order()
        store.data["toolbox_placement"] = cast(ToolboxDock, self.docks["tools"]).placement()
        store.data["toolbox_visible"] = not self.docks["tools"].isHidden()
        store.data["layout_version"] = 2
        store.data["geometry"] = base64.b64encode(self.saveGeometry().data()).decode("ascii")
        store.data["layout"] = base64.b64encode(self.saveState(1).data()).decode("ascii")
        self._remember_floating_panels()
        self._scene_timeline_height = timeline_height or self.docks["timeline"].height()
        store.data["panel_state"] = {
            "timeline_height": self._scene_timeline_height,
            "timeline_splitter": base64.b64encode(self.timeline.splitter.saveState().data()).decode(
                "ascii"
            ),
            "timeline_channels": base64.b64encode(
                self.timeline.tracks.header().saveState().data()
            ).decode("ascii"),
            "assets_tab": self.library_tabs.currentIndex(),
            "inspector_tab": self.inspector.currentIndex(),
            "timeline_tab": self.timeline.pages.currentIndex(),
        }
        warning = store.save()
        if warning:
            self.statusBar().showMessage(warning, 15000)

    def _remember_floating_panels(self) -> None:
        """Retain explicit frameless geometry, avoiding native dock caption offsets on restore."""
        panels = {}
        for key, dock in self.docks.items():
            if key == "tools":
                continue
            if dock.isFloating():
                rect = dock.normalGeometry() if dock.isMaximized() else dock.geometry()
                panels[key] = {
                    "rect": [rect.x(), rect.y(), rect.width(), rect.height()],
                    "maximized": dock.isMaximized(),
                }
        self.viewmodel.preferences.data["floating_panels"] = panels

    def _restore_timeline_height(self) -> None:
        """Retain the chosen pixel height after Qt adjusts restored main-window geometry."""
        height = self._scene_timeline_height
        dock = self.docks["timeline"]
        if (
            type(height) is int
            and 180 <= height <= 2000
            and not self.object_edit.active
            and not dock.isFloating()
            and not dock.isHidden()
        ):
            self.resizeDocks(
                [dock], [min(height, max(180, self.height() - 240))], Qt.Orientation.Vertical
            )

    def _restore_floating_panels(self) -> None:
        """Restore known floating panels on an available display after Qt restores dock state."""
        saved = self.viewmodel.preferences.data.get("floating_panels", {})
        if not isinstance(saved, dict):
            return
        for key, value in saved.items():
            if key == "tools":
                continue
            dock = self.docks.get(key)
            if dock is None or not dock.isFloating() or not isinstance(value, dict):
                continue
            rect = value.get("rect")
            if (
                not isinstance(rect, list)
                or len(rect) != 4
                or any(type(n) is not int or abs(n) > 100000 for n in rect)
                or not 1 <= rect[2] <= 20000
                or not 1 <= rect[3] <= 20000
            ):
                continue
            bounds = QRect(*rect)
            screens = QApplication.screens()
            screen = next(
                (s for s in screens if s.availableGeometry().intersects(bounds)), self.screen()
            )
            available = screen.availableGeometry()
            bounds.setSize(bounds.size().boundedTo(available.size()))
            if not available.intersects(bounds):
                bounds.moveCenter(available.center())
            dock.setGeometry(bounds)
            if value.get("maximized") is True and not dock.isHidden():
                dock.showMaximized()

    def _restore_workspace(self) -> None:
        """Restore bounded, valid serialized geometry and dock-layout preferences."""
        data = self.viewmodel.preferences.data
        for key, restore in (
            ("geometry", self.restoreGeometry),
            ("layout", lambda value: self.restoreState(value, 1)),
        ):
            value = data.get(key)
            if key == "layout" and (
                data.get("layout_version") != 2 or data.get("workspace_panels_version") != 1
            ):
                continue
            if isinstance(value, str) and len(value) < 200000:
                with contextlib.suppress(ValueError):
                    restore(QByteArray(base64.b64decode(value, validate=True)))
        placement = data.get("toolbox_placement")
        if isinstance(placement, dict) and placement.get("space") != "preview":
            # Consume the retired native slot so its placeholder cannot leave an
            # empty column or remain the active tab in a restored panel group.
            retired = QDockWidget(self)
            retired.setObjectName("dock_tools")
            if self.restoreDockWidget(retired):
                siblings = self.tabifiedDockWidgets(retired)
                self.removeDockWidget(retired)
                for sibling in siblings:
                    if not sibling.isHidden():
                        sibling.raise_()
                        break
            retired.hide()
            retired.deleteLater()
            scene_panel = self.docks["hierarchy"]
            if (
                not scene_panel.isHidden()
                and scene_panel.geometry().right() < 0
                and not any(not p.isHidden() for p in self.tabifiedDockWidgets(scene_panel))
            ):
                # Reinsert a panel stranded in the inactive geometry of a
                # retired slot, preserving valid, visible panel tab groups.
                self.addDockWidget(self.dockWidgetArea(scene_panel), scene_panel)
        if data.get("workspace_panels_version") != 1:
            # Old panel trees can retain offscreen slots even for shown docks.
            # Start from the new default once, then preserve future View choices.
            for key in ("hierarchy", "tools", "assets", "timeline"):
                self.docks[key].show()
            data["workspace_panels_version"] = 1
        else:
            self._restore_floating_panels()
            cast(ToolboxDock, self.docks["tools"]).restore_placement(data.get("toolbox_placement"))
            cast(ToolboxDock, self.docks["tools"]).check_layout()
            self.docks["tools"].setVisible(data.get("toolbox_visible", True) is not False)
        panels = data.get("panel_state", {})
        if isinstance(panels, dict):
            height = panels.get("timeline_height")
            if type(height) is int and 180 <= height <= 2000:
                self._scene_timeline_height = height
            splitter = panels.get("timeline_splitter")
            if isinstance(splitter, str) and len(splitter) < 200000:
                with contextlib.suppress(ValueError):
                    self.timeline.splitter.restoreState(
                        QByteArray(base64.b64decode(splitter, validate=True))
                    )
            channels = panels.get("timeline_channels")
            if isinstance(channels, str) and len(channels) < 200000:
                with contextlib.suppress(ValueError):
                    self.timeline.tracks.header().restoreState(
                        QByteArray(base64.b64decode(channels, validate=True))
                    )
            for key, tabs in (
                ("assets_tab", self.library_tabs),
                ("inspector_tab", self.inspector),
                ("timeline_tab", self.timeline.pages),
            ):
                index = panels.get(key)
                if isinstance(index, int) and 0 <= index < tabs.count():
                    tabs.setCurrentIndex(index)
        self.timeline.anchor_track_columns()
        self.plugin_workspace.toolbar.setVisible(bool(self.plugin_workspace.toolbar.actions()))
        QTimer.singleShot(0, self._restore_timeline_height)

    def show_help(self) -> None:
        """Present local navigation shortcuts and the current authoring feature boundaries."""
        dialog = CustomDialog(self, "Rigora quick start")
        dialog.resize(560, 440)
        layout = QVBoxLayout(dialog.content)
        browser = QTextBrowser()
        browser.setHtml(
            "<h3>Start with a real project</h3><p>Use File → New project, set a canvas "
            "size and frame rate, then Save. Rigora writes a versioned .rigora package. A"
            " previous save is retained as .rigora.bak.</p><h3>Navigate your "
            "canvas</h3><p>Wheel: zoom at cursor<br>Middle-drag or Space + drag: "
            "pan<br>F: fit canvas · 1: actual size<br>G: grid · Shift+G: "
            "checkerboard<br>H: pan tool · V: navigate</p><h3>Make the workspace "
            "yours</h3><p>Drag dock headers to move or detach panels. Restore them from "
            "View. Ctrl+Shift+L changes theme; Ctrl+Shift+P searches "
            "commands.</p><h3>Preview animation</h3><p>Open a project or create a character. "
            "Ctrl+Space plays or pauses; Stop returns "
            "to the first frame. Scrub the Timeline slider or type a fractional frame. "
            "Select either clip and toggle Loop. Switching tabs pauses playback and "
            "retains each project's frame. Playback never changes saved data.</p>"
            "<h3>Build a rig</h3><p>Press R for rest-rig mode or B to draw a bone. "
            "The circle cursor snaps to root/tip joints; hold Alt for free placement. "
            "Right-click cancels drawing and clears selection. Choose a Chain, Biped or Quadruped "
            "template in the Rig inspector, then Frame rig. Select bones in the hierarchy "
            "or viewport; use Move, Rotate or Endpoint tools and Apply properties. "
            "Constraints provides two-bone IK, FK switching, editable targets and other "
            "transform rules. Exit R mode to preview animation tracks.</p>"
            "<h3>Deform artwork</h3><p>Ctrl+I imports PNG, JPEG or static SVG into a "
            "textured grid. M opens mesh editing; Frame artwork fits your selection. "
            "Use the Mesh / Deform inspector to edit topology, add FFD/lattice fields, "
            "bind bones and paint weights. Motion edits numeric values and deformation "
            "keys, with optional Auto key and reusable .rigmotion clips. Deform → New "
            "deformation example opens an editable study.</p>"
            "<h3>Animate and reuse</h3><p>Use the timeline dope sheet and graph editor for "
            "keys, curves and tangents. Clips supports retiming, transitions and reusable actions. "
            "Assets → Browse content opens original offline rigs, poses, motions and deformers. "
            "Plugins → Manage plugins loads explicitly trusted SDK extensions.</p>"
            "<p>Authoring edits support Undo/Redo. Export SVG previews from File, or open "
            "AI / Automation for project inspection and local MCP connection settings. Disabled "
            "controls explain their status in tooltips.</p>"
        )
        layout.addWidget(browser)
        close = QPushButton("Close")
        close.setIcon(self.icons.icon("close"))
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()

    def show_about(self) -> None:
        """Present app branding, creator contacts and runtime details in the About window."""
        dialog = AboutDialog(self, self.viewmodel.info)
        dialog.exec()
        dialog.deleteLater()

    def show_plugins(self) -> None:
        """Open nonmodal SDK trust, lifecycle and diagnostic controls."""
        if self.plugin_dialog is None:
            self.plugin_dialog = PluginManagerDialog(self, self.viewmodel)
        self.plugin_dialog.show()
        self.plugin_dialog.raise_()
        self.plugin_dialog.activateWindow()

    def show_puppet(self) -> None:
        """Open motion-card authoring, live preview and atomic performance recording controls."""
        if self.puppet_stage is None:
            self.puppet_stage = PuppetStage(self)
        self.puppet_stage.refresh()
        self.puppet_stage.show()
        self.puppet_stage.raise_()
        self.puppet_stage.activateWindow()

    def show_motion_pilot(self) -> None:
        """Open Scene-space puppeteering while preserving the selected character's identity."""
        from rigora.presentation.widgets.motion_pilot import MotionPilot

        owner = self.object_edit.key if self.object_edit.active else None
        for name in ("bone_editor", "spring_editor"):
            if editor := getattr(self, name, None):
                editor.close()
        self.object_edit.exit()
        self.navigate()
        if owner:
            self.viewmodel.scene.select((owner,))
        if prior := getattr(self, "motion_pilot", None):
            prior.close()
            prior.deleteLater()
        self.motion_pilot = MotionPilot(self)
        self.motion_pilot.show()

    def bake_spring_keys(self, group: str | None = None) -> None:
        """Expose the existing Spring Editor's worker bake without switching timeline contexts."""
        from rigora.presentation.widgets.composer_editors import SpringEditor

        prior = getattr(self, "spring_editor", None)
        if prior and prior.document is not self.viewmodel.documents:
            prior.close()
            prior.deleteLater()
            prior = None
        self.spring_editor = prior or SpringEditor(self)
        self.spring_editor.show()
        self.spring_editor.bake_scope.setCurrentIndex(1 if group else 0)
        if group:
            for index in range(self.spring_editor.groups.topLevelItemCount()):
                item = self.spring_editor.groups.topLevelItem(index)
                if item is not None and item.data(0, Qt.ItemDataRole.UserRole) == group:
                    self.spring_editor.groups.setCurrentItem(item)
                    break
        self.spring_editor.bake_springs()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Resolve every dirty tab before saving workspace state and accepting shutdown."""
        if getattr(self, "_waiting_for_save", False):
            event.ignore()
            return
        if self._closed:
            event.accept()
            return
        self.viewmodel.playback.pause()
        self.viewmodel.extensions.emit_event("app.closing")
        previous = self.viewmodel.workspace.active
        welcome = self.viewmodel.welcome_selected
        for index in range(len(self.viewmodel.workspace.documents)):
            self.viewmodel.activate_project(index)
            if not self.confirm_discard():
                self.restore_selection(previous.session_id if previous else None, welcome)
                event.ignore()
                return
        self.restore_selection(previous.session_id if previous else None, welcome)
        timeline_height = self.object_edit.timeline_height if self.object_edit.active else None
        self.object_edit.exit(restore_view=False)
        self._save_workspace(timeline_height=timeline_height)
        self._closed = True
        if self.welcome_window is not None:
            self.welcome_window.close()
        for name in (
            "bone_editor",
            "spring_editor",
            "motion_pilot",
            "character_wizard",
            "vector_creator",
            "camera_dialog",
            "video_rig_dialog",
            "face_dialog",
            "contact_editor",
            "audio_mixer",
            "path_editor",
            "game_tools",
            "movement_views",
            "broadcast_output",
            "camera_shots",
            "state_machine",
            "production_inspector",
        ):
            if editor := getattr(self, name, None):
                editor.close()
        self.viewmodel.project_io.close()
        self.viewmodel.output.close()
        self.viewmodel.media.close()
        if self.puppet_stage:
            self.puppet_stage.stop(cancel=True)
        self.viewmodel.content.shutdown()
        self.mesh_workspace.shutdown()
        self.object_assets.shutdown()
        self.content_drop.clear()
        self.plugin_workspace.clear()
        if self.viewmodel.owns_plugins:
            self.viewmodel.plugins.shutdown()
        event.accept()
