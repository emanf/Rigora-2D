"""Named UI extension surfaces and an owned desktop bridge over application ViewModels."""

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QBoxLayout, QMenu, QToolBar, QToolButton
from shiboken6 import isValid

from rigora.domain.project import ProjectError
from rigora.presentation.widgets.menus import ToggleMenu

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


class ExtensionSurfaces(QObject):
    """Publish view-owned slots; destroying a view automatically withdraws its slots."""

    changed = Signal()

    def __init__(self, parent: QObject) -> None:
        """Retain registered Qt wrappers only for their actual native lifetime."""
        super().__init__(parent)
        self.targets: dict[str, QBoxLayout | QToolBar] = {}

    def register(self, name: str, target: QBoxLayout | QToolBar) -> None:
        """Expose a layout/toolbar under a stable ID, rejecting accidental replacement."""
        if name in self.targets and self.targets[name] is not target:
            raise ProjectError(f"Extension surface already exists: {name}.")
        if name in self.targets:
            return
        self.targets[name] = target
        target.destroyed.connect(lambda: self.unregister(name, target))
        self.changed.emit()

    def unregister(self, name: str, target: QObject | None = None) -> None:
        """Withdraw the matching owner; a late old-view signal cannot remove its replacement."""
        if name in self.targets and (target is None or self.targets[name] is target):
            del self.targets[name]
            if isValid(self):
                self.changed.emit()


class DesktopExtensionHost(QObject):
    """Mount actions on shared surfaces and expose supported navigation to trusted UI plugins."""

    def __init__(self, window: "MainWindow") -> None:
        """Own presentation-only mounts; all project commands remain routed through ViewModels."""
        super().__init__(window)
        self.window = window
        self.surfaces = window.extension_surfaces
        self.mounts: dict[str, list[tuple[Any, Any]]] = {}
        self.menus: dict[tuple[str, ...], QMenu] = {}
        self.toolbars: dict[str, QToolBar] = {}

    def execute(self, key: str, arguments: dict[str, Any] | None = None) -> Any:
        """Execute a registered extension command or trigger an existing application action."""
        if any(c.id == key for c in self.window.viewmodel.plugins.contributions()):
            return self.window.viewmodel.run_plugin(key, arguments or {})
        action = self.window.command_actions.get(key)
        if action is None or not action.isEnabled():
            raise ProjectError(f"Application command is unavailable: {key}.")
        if arguments:
            raise ProjectError(
                "Built-in UI actions do not accept arguments; use request.service()."
            )
        action.trigger()
        return None

    def available_commands(self) -> tuple[dict[str, Any], ...]:
        """Describe live application actions without exposing view internals."""
        return tuple(
            {
                "id": key,
                "name": action.text(),
                "enabled": action.isEnabled(),
                "shortcut": action.shortcut().toString(),
            }
            for key, action in self.window.command_actions.items()
        )

    def select(self, ids: tuple[str, ...], *, kind: str = "scene") -> None:
        """Navigate selection through the existing scene/bone presentation commands."""
        if kind == "bones":
            self.window.viewmodel.rig.select_many(ids)
        elif kind == "scene":
            self.window.viewmodel.scene.select(ids)
        else:
            raise ProjectError("Selection kind must be scene or bones.")

    def notify(self, message: str) -> None:
        """Display an informational status message without a modal dialog or focus change."""
        self.window.statusBar().showMessage(message, 10000)

    def show_panel(self, key: str) -> None:
        """Reveal an existing contributed dock by its stable contribution identity."""
        for dock in self.window.plugin_workspace.docks:
            if dock.objectName() == key:
                dock.show()
                dock.raise_()
                return
        raise ProjectError(f"Extension panel is unavailable: {key}.")

    def menu(self, path: str) -> QMenu:
        """Resolve or create a nested application menu while tracking only owned menus."""
        parts = tuple(part.strip() for part in path.split("/") if part.strip())
        if not parts or len(parts) > 8:
            raise ProjectError("Menu paths must have between one and eight nonempty names.")
        current = self.window.menus.get(parts[0])
        if current is None:
            current = self.menus.get(parts[:1])
        if current is None:
            current = ToggleMenu(parts[0], self.window.menu_bar)
            self.window.menu_bar.addMenu(current)
            self.menus[parts[:1]] = current
        for index, part in enumerate(parts[1:], 2):
            key = parts[:index]
            if key not in self.menus:
                child = ToggleMenu(part, current)
                current.addMenu(child)
                self.menus[key] = child
            current = self.menus[key]
        return current

    def mount(self, action: QAction, placements: tuple[str, ...]) -> None:
        """Place a shared action across menus, toolbars and editor buttons."""
        self.unmount(action.objectName())
        mounted = self.mounts.setdefault(action.objectName(), [])
        for placement in placements:
            kind, _, name = placement.partition(":")
            if kind == "menu":
                menu = self.menu(name)
                menu.addAction(action)
                mounted.append((menu, action))
            elif kind in ("toolbar", "surface"):
                target = self.surfaces.targets.get(name)
                if kind == "toolbar" and target is None:
                    if name not in self.toolbars:
                        toolbar = self.window.addToolBar(name)
                        toolbar.setObjectName("extension_toolbar." + name)
                        self.toolbars[name] = toolbar
                    target = self.toolbars[name]
                if isinstance(target, QToolBar):
                    target.addAction(action)
                    target.show()
                    mounted.append((target, action))
                elif isinstance(target, QBoxLayout):
                    button = QToolButton(target.parentWidget())
                    button.setDefaultAction(action)
                    button.setAccessibleName(action.text())
                    target.addWidget(button)
                    mounted.append((target, button))

    def unmount(self, key: str) -> None:
        """Detach only this contribution's owned controls and leave other extensions in place."""
        for owner, item in self.mounts.pop(key, []):
            if not isValid(owner):
                continue
            if isinstance(item, QAction):
                owner.removeAction(item)
            elif isValid(item):
                owner.removeWidget(item)
                item.deleteLater()

    def prune(self) -> None:
        """Release empty contributed menus/toolbars while retaining all built-in surfaces."""
        for key in sorted(tuple(self.menus), key=len, reverse=True):
            menu = self.menus[key]
            if not menu.actions():
                if len(key) == 1:
                    self.window.menu_bar.removeAction(menu.menuAction())
                else:
                    parent = self.menus.get(key[:-1]) or self.window.menus.get(key[0])
                    if parent:
                        parent.removeAction(menu.menuAction())
                menu.deleteLater()
                del self.menus[key]
        for toolbar_key, toolbar in tuple(self.toolbars.items()):
            if not toolbar.actions():
                self.window.removeToolBar(toolbar)
                toolbar.deleteLater()
                del self.toolbars[toolbar_key]
