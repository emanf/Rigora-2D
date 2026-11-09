"""Owned Qt adapters for active SDK tools, panels, inspectors and viewport renderers."""

from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QPainter
from PySide6.QtWidgets import QBoxLayout, QMenu, QToolBar, QWidget
from shiboken6 import isValid

from rigora.domain.project import ProjectError
from rigora.presentation.extension_surfaces import DesktopExtensionHost
from rigora.presentation.menu_labels import menu_text
from rigora.presentation.widgets.window_frame import DockPanel
from rigora.sdk.api import Contribution, PluginRequest

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


class PluginWorkspace(QObject):
    """Translate activated SDK registrations into removable, themed workspace controls."""

    def __init__(self, window: "MainWindow") -> None:
        """Bind lifecycle and document signals without granting trust to discovered plugins."""
        super().__init__(window)
        self.window = window
        self.model = window.viewmodel
        self.manager = self.model.plugins
        self.actions: dict[str, QAction] = {}
        self.docks: list[DockPanel] = []
        self.inspectors: list[QWidget] = []
        self.bindings: list[tuple[Contribution, QWidget]] = []
        self.signature: tuple[int, ...] = ()
        self._installed: dict[str, Contribution] = {}
        self._widget_mounts: dict[str, tuple[Any, QWidget, QAction | None]] = {}
        self._refreshing = self._pending = False
        self._binding_context: object = None
        self.host = DesktopExtensionHost(window)
        self.model.extensions.host = self.host
        self.active_tool = ""
        self.failed_renderers: set[str] = set()
        self.menu = window.menus["Plugins"].addMenu("Active extensions")
        self.menu.setIcon(window.icons.icon("extension"))
        self.toolbar = window.addToolBar("Plugin tools")
        self.toolbar.setObjectName("plugin_tools")
        self.toolbar.setMovable(False)
        self.toolbar.hide()
        for key in ("navigate", "pan", "move", "bone", "mesh", "weights", "deform", "rig_mode"):
            window.command_actions[key].triggered.connect(self.deactivate_tool)
        self.model.plugins_changed.connect(self.refresh)
        self.model.extensions.state_changed.connect(self.update_context)
        window.extension_surfaces.changed.connect(self.refresh_surfaces)
        self.model.changed.connect(self.bind)
        self.refresh()

    def request(
        self, contribution: Contribution, arguments: dict[str, Any] | None = None
    ) -> PluginRequest:
        """Build the current request with document access only when explicitly declared."""
        return self.model.extensions.request(contribution, arguments)

    def report(self, contribution: Contribution, error: Exception) -> None:
        """Surface optional extension failures without propagating exceptions through Qt slots."""
        self.manager.report(contribution.plugin_id, str(error))
        self.window.statusBar().showMessage(str(error), 15000)

    def uninstall(self, key: str) -> None:
        """Withdraw only one contribution, preserving unrelated panel state and selections."""
        self.host.unmount(key)
        self.failed_renderers.discard(key)
        action = self.actions.pop(key, None)
        if action:
            if self.active_tool == key:
                self.deactivate_tool()
            self.window.command_actions.pop(key, None)
            self.window._tool_group.removeAction(action)
            self.toolbar.removeAction(action)
            self.menu.removeAction(action)
            self.window.removeAction(action)
            action.deleteLater()
        for contribution, widget in tuple(self.bindings):
            if contribution.id != key:
                continue
            self.bindings.remove((contribution, widget))
            for dock in tuple(self.docks):
                if dock.widget() is widget:
                    self.menu.removeAction(dock.toggleViewAction())
                    self.window.removeDockWidget(dock)
                    self.docks.remove(dock)
                    dock.deleteLater()
            if widget in self.inspectors:
                self.window.inspector.removeTab(self.window.inspector.indexOf(widget))
                self.inspectors.remove(widget)
                widget.deleteLater()
        mounted = self._widget_mounts.pop(key, None)
        if mounted:
            target, widget, wrapper = mounted
            if isValid(target):
                if wrapper and isValid(wrapper):
                    target.removeAction(wrapper)
                    wrapper.deleteLater()
                elif isinstance(target, QBoxLayout) and isValid(widget):
                    target.removeWidget(widget)
            if isValid(widget):
                widget.close()
                widget.deleteLater()
        self._installed.pop(key, None)

    def clear(self) -> None:
        """Detach owned UI before shutdown, retaining built-in controls."""
        self.deactivate_tool()
        self.window.viewport.extension_overlay = None
        for key in tuple(self._installed):
            self.uninstall(key)
        self.host.prune()

    def refresh(self) -> None:
        """Diff the registry by identity; late/live additions do not rebuild existing widgets."""
        if self._refreshing:
            self._pending = True
            return
        self._refreshing = True
        try:
            contributions = self.manager.contributions()
            current = {c.id: c for c in contributions}
            for key, old in tuple(self._installed.items()):
                if current.get(key) is not old:
                    self.uninstall(key)
            for contribution in contributions:
                key, kind = contribution.id, contribution.kind
                if key in self._installed:
                    continue
                self._installed[key] = contribution
                if kind in ("panels", "inspectors"):
                    self.install_widget(contribution)
                elif kind not in (
                    "asset_packs",
                    "renderers",
                    "track_types",
                    "batch_jobs",
                    "validators",
                    "services",
                    "hooks",
                    "widgets",
                ) and not (kind == "templates" and contribution.metadata.get("template_type")):
                    self.install_action(contribution)
            paths = []
            for contribution in self.manager.contributions("asset_packs"):
                try:
                    path = self.manager.invoke(contribution.id, self.request(contribution))
                    if not isinstance(path, Path) or not path.is_file():
                        raise ProjectError(
                            "Asset pack callbacks must return an existing pathlib.Path."
                        )
                    paths.append(path)
                except ProjectError as error:
                    self.report(contribution, error)
            packs = tuple(dict.fromkeys(paths))
            if packs != self.model.content.library.additional_packs:
                self.model.content.library.additional_packs = packs
                self.model.content.reload()
            self.refresh_surfaces()
            self.toolbar.setVisible(bool(self.toolbar.actions()))
            self.menu.setEnabled(bool(self.actions or self.docks or self.inspectors))
            self.window.viewport.extension_overlay = (
                self.paint if self.manager.contributions("renderers") else None
            )
            self.bind()
        finally:
            self._refreshing = False
            if self._pending:
                self._pending = False
                QTimer.singleShot(0, self.refresh)

    def install_action(self, contribution: Contribution) -> None:
        """Build a shared action with normal shortcuts and tool selection."""
        try:
            action = QAction(menu_text(contribution.name), self.window)
            action.setObjectName(contribution.id)
            icon = str(contribution.metadata.get("icon", "extension"))
            action.setProperty("materialIcon", icon)
            action.setIcon(self.window.icons.icon(icon))
            action.setToolTip(f"{contribution.name} · {contribution.id}")
            shortcut = str(contribution.metadata.get("shortcut", ""))
            if shortcut:
                sequence = QKeySequence(shortcut)
                if any(sequence in a.shortcuts() for a in self.window.command_actions.values()):
                    self.manager.report(
                        contribution.plugin_id, f"Shortcut already in use: {shortcut}."
                    )
                else:
                    action.setShortcut(sequence)
                    self.window.addAction(action)
            if contribution.kind == "tools":
                action.setCheckable(True)
                self.window._tool_group.addAction(action)
                action.triggered.connect(lambda _=False, c=contribution: self.activate_tool(c))
            else:
                action.triggered.connect(lambda _=False, c=contribution: self.run(c))
            self.actions[contribution.id] = action
            self.window.command_actions[contribution.id] = action
            if not contribution.metadata.get("placements"):
                self.menu.addAction(action)
                if contribution.kind == "tools":
                    self.toolbar.addAction(action)
        except (ProjectError, ValueError) as error:
            self.report(contribution, ProjectError(str(error)))

    def refresh_surfaces(self) -> None:
        """Mount controls when their editor surfaces appear and withdraw them on close."""
        if self.window._closed:
            return
        for key, action in self.actions.items():
            self.host.mount(action, tuple(self._installed[key].metadata.get("placements", ())))
        for contribution in self.manager.contributions("widgets"):
            target = self.window.extension_surfaces.targets.get(
                str(contribution.metadata.get("surface"))
            )
            previous = self._widget_mounts.get(contribution.id)
            if previous and previous[0] is target and isValid(previous[1]):
                continue
            if previous:
                self.bindings[:] = [(c, w) for c, w in self.bindings if c.id != contribution.id]
                if previous[2] and isValid(previous[2]):
                    if isValid(previous[0]):
                        previous[0].removeAction(previous[2])
                    previous[2].deleteLater()
                if isValid(previous[1]):
                    previous[1].close()
                    previous[1].deleteLater()
                self._widget_mounts.pop(contribution.id, None)
            if target is None:
                continue
            try:
                parent = target.parentWidget() if isinstance(target, QBoxLayout) else target
                widget = self.manager.call_raw(contribution.id, self.request(contribution), parent)
                if not isinstance(widget, QWidget):
                    raise ProjectError("Surface factories must return a QWidget.")
                wrapper = target.addWidget(widget) if isinstance(target, QToolBar) else None
                if not isinstance(target, QToolBar):
                    target.addWidget(widget)
                self._widget_mounts[contribution.id] = (target, widget, wrapper)
                self.bindings.append((contribution, widget))
                self._binding_context = None
            except ProjectError as error:
                self.report(contribution, error)
        self.host.prune()
        self.update_context()

    def update_context(self) -> None:
        """Update enabled state without rebuilding actions during selection or playback."""
        active = {c.id: c for c in self.manager.contributions()}
        for key, action in self.actions.items():
            action.setEnabled(
                active.get(key) is self._installed[key]
                and self.model.extensions.enabled(self._installed[key])
            )
        state = self.model.extensions.state()
        context = (
            id(self.model.documents.project),
            state["document_id"],
            state["selection"],
            state["bone_ids"],
            state["mesh_id"],
            state["editor"],
        )
        if context != self._binding_context:
            self._binding_context = context
            self.bind_widgets()

    def populate_context(self, menu: QMenu, surface: str, **arguments: Any) -> None:
        """Create transient proxies carrying the clicked item context into ordinary commands."""
        for key, action in self.actions.items():
            contribution = self._installed[key]
            if "context:" + surface in contribution.metadata.get("placements", ()):
                proxy = menu.addAction(action.icon(), action.text())
                proxy.setEnabled(action.isEnabled())
                proxy.triggered.connect(lambda _=False, c=contribution, a=arguments: self.run(c, a))

    def install_widget(self, contribution: Contribution) -> None:
        """Adopt one plugin-created widget into a custom dock or property-inspector tab."""
        try:
            widget = self.manager.call_raw(contribution.id, self.request(contribution), self.window)
            if not isinstance(widget, QWidget):
                raise ProjectError("Panel and inspector factories must return a QWidget.")
            if contribution.kind == "panels":
                dock = DockPanel(contribution.name, self.window, self.window.icons)
                dock.setObjectName(contribution.id)
                dock.setWidget(widget)
                self.window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
                self.docks.append(dock)
                self.menu.addAction(dock.toggleViewAction())
            else:
                self.window.inspector.addTab(widget, menu_text(contribution.name))
                self.inspectors.append(widget)
            self.bindings.append((contribution, widget))
            self._binding_context = None
        except ProjectError as error:
            self.report(contribution, error)

    def bind(self) -> None:
        """Notify optional read-only widget bind hooks when the active project or pose changes."""
        self.model.extensions.set_editor("object" if self.window.object_edit.active else "scene")
        self.update_context()
        self.window.viewport.update()

    def bind_widgets(self) -> None:
        """Update context-dependent widgets only when authored data or navigation changes."""
        active = {c.id: c for c in self.manager.contributions()}
        for contribution, widget in tuple(self.bindings):
            if not isValid(widget) or active.get(contribution.id) is not contribution:
                continue
            callback = getattr(widget, "rigora_bind", None)
            if callback and widget.isEnabled():
                try:
                    callback(self.request(contribution))
                except (Exception, SystemExit) as error:
                    widget.setEnabled(False)
                    self.report(contribution, ProjectError(f"Panel refresh failed: {error}"))

    def run(self, contribution: Contribution, arguments: dict[str, Any] | None = None) -> Any:
        """Run an ordinary UI command through the ViewModel's shared undo/failure boundary."""
        try:
            return self.model.run_plugin(contribution.id, arguments or {})
        except (ProjectError, TypeError, ValueError, KeyError) as error:
            self.report(contribution, error)
            return None

    def activate_tool(self, contribution: Contribution) -> None:
        """Select a scene-coordinate pointer tool with normal viewport navigation."""
        self.deactivate_tool()
        if self.model.documents.project is None:
            self.model.new_project()
        self.window.rig_workspace.set_mode(False)
        self.window.mesh_workspace.set_mode(False)
        self.window.viewport.pan_tool = False
        self.active_tool = contribution.id
        self.actions[contribution.id].setChecked(True)
        self.window.viewport.extension_pointer = self.pointer
        self.window.viewport.setFocus()

    def deactivate_tool(self, *_: Any) -> None:
        """Cancel an in-progress extension gesture before returning to standard authoring tools."""
        viewport = self.window.viewport
        if viewport._extension_drag and viewport.extension_pointer:
            viewport._extension_drag = False
            viewport.extension_pointer("cancel", 0, 0, False)
        viewport.extension_pointer = None
        if self.active_tool in self.actions:
            self.actions[self.active_tool].setChecked(False)
        self.active_tool = ""

    def pointer(self, phase: str, x: float, y: float, ctrl: bool) -> None:
        """Forward pointer phases with scene coordinates and a Control-key free-placement hint."""
        contribution = next(
            (c for c in self.manager.contributions("tools") if c.id == self.active_tool), None
        )
        if contribution:
            self.run(contribution, {"phase": phase, "x": x, "y": y, "ctrl": ctrl})

    def paint(self, painter: QPainter) -> None:
        """Contain renderer exceptions and restore painter state between optional overlays."""
        viewport = self.window.viewport
        for contribution in self.manager.contributions("renderers"):
            if contribution.id in self.failed_renderers:
                continue
            painter.save()
            try:
                request = self.request(
                    contribution,
                    {
                        "frame": viewport.pose.frame if viewport.pose else 0,
                        "zoom": viewport.zoom,
                        "offset_x": viewport.offset.x(),
                        "offset_y": viewport.offset.y(),
                    },
                )
                self.manager.call_raw(
                    contribution.id,
                    request,
                    painter,
                    viewport.pose if request.document else None,
                )
            except ProjectError as error:
                self.failed_renderers.add(contribution.id)
                self.report(contribution, error)
            finally:
                painter.restore()
