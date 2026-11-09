"""Presentation state and commands over the shared document service."""

from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal

from rigora.app.application import ApplicationInfo
from rigora.application_services.content_library import ContentLibrary
from rigora.application_services.documents import DocumentService
from rigora.application_services.plugins import PluginManager
from rigora.application_services.workspace import WorkspaceService
from rigora.domain.project import ProjectError, SceneSettings
from rigora.infrastructure.preferences import PreferencesStore
from rigora.presentation.viewmodels.animation_editor import AnimationEditorViewModel
from rigora.presentation.viewmodels.content_library import LibraryViewModel
from rigora.presentation.viewmodels.media import MediaImportViewModel, OutputViewModel
from rigora.presentation.viewmodels.meshes import MeshViewModel
from rigora.presentation.viewmodels.playback import PlaybackViewModel
from rigora.presentation.viewmodels.project_io import ProjectIOViewModel
from rigora.presentation.viewmodels.rigging import RigViewModel
from rigora.presentation.viewmodels.scene import SceneViewModel


class MainWindowViewModel(QObject):
    """Expose workspace state and application commands through Qt presentation signals."""

    changed = Signal()
    theme_changed = Signal(str)
    plugins_changed = Signal()
    welcome_requested = Signal()

    def __init__(
        self,
        info: ApplicationInfo,
        documents: DocumentService | None = None,
        preferences: PreferencesStore | None = None,
        plugins: PluginManager | None = None,
    ) -> None:
        """Inject application identity and preferences and adopt an optional document session."""
        super().__init__()
        self.info = info
        self.workspace = WorkspaceService(documents)
        self._empty_document = DocumentService()
        self.welcome_selected = self.workspace.active is None
        self.welcome_open = self.welcome_selected
        self.preferences = preferences or PreferencesStore()
        self.playback = PlaybackViewModel(self)
        self.animation_editor = AnimationEditorViewModel(self, self.playback)
        self.rig = RigViewModel(self)
        self.scene = SceneViewModel(self)
        self.scene.changed.connect(lambda: self.animation_editor.focus_owners(self.scene.selected))
        self.animation_editor.owner_selected.connect(lambda key: self.scene.select((key,)))
        self.mesh = MeshViewModel(self)
        for editor in (self.scene, self.rig, self.mesh):
            editor.editing_started.connect(self.playback.pause)
        self.animation_editor.auto_key_changed.connect(self.set_auto_key)
        self.mesh.auto_key_changed.connect(self.animation_editor.set_auto_key)
        self.output = OutputViewModel(self)
        self.media = MediaImportViewModel(self)
        self.project_io = ProjectIOViewModel(self)
        self.content = LibraryViewModel(self, ContentLibrary(self.preferences))
        self.content.create_requested.connect(self.new_project)
        self.content.document_changed.connect(self.changed.emit)
        self.plugins = plugins or PluginManager(self.preferences)
        self.owns_plugins = plugins is None
        self.plugins.on_changed = self._plugins_changed
        self.plugin_error = ""
        from rigora.presentation.viewmodels.extensions import ExtensionViewModel

        self.extensions = ExtensionViewModel(self)
        self.playback.event_fired.connect(
            lambda data: self.extensions.emit_event("animation.event", data=data)
        )
        self.rig.document_changed.connect(self.changed.emit)
        self.scene.document_changed.connect(self.changed.emit)
        self.mesh.document_changed.connect(self.changed.emit)
        self.animation_editor.document_changed.connect(self.changed.emit)
        self.changed.connect(self._sync_playback)
        if plugins is None:
            self.plugins.discover()
            self.plugins.restore()
        self._sync_playback()

    def _sync_playback(self) -> None:
        """Bind transport presentation to the selected document after authoring or tab changes."""
        for document in self.workspace.documents:
            document.history.set_limit(self.preferences.data["undo_limit"])
        if self.documents.project is not None:
            self.plugins.attach(self.documents)
        self.playback.bind(self.documents if self.documents.project is not None else None)
        self.rig.bind(self.documents if self.documents.project is not None else None)
        self.scene.bind(self.documents if self.documents.project is not None else None)
        self.mesh.bind(self.documents if self.documents.project is not None else None)
        self.animation_editor.bind(self.documents if self.documents.project is not None else None)
        self.content.bind(self.documents if self.documents.project is not None else None)
        open_ids = {
            f"{document.session_id}:{scene.id}"
            for document in self.workspace.documents
            if document.project
            for scene in document.project.scenes
        }
        for states in (self.rig._tab_states, self.mesh._tabs, self.scene._tabs):
            for key in tuple(states):
                if key not in open_ids:
                    del states[key]

    def set_auto_key(self, enabled: bool) -> None:
        """Share explicit recording intent between scene transforms and mesh/FFD editing."""
        self.scene.auto_key = enabled
        self.rig.auto_key = enabled
        self.mesh.set_auto_key(enabled)

    def set_undo_limit(self, limit: int) -> None:
        """Apply an application-wide history budget without changing authored project data."""
        if type(limit) is not int or not 1 <= limit <= 10000:
            raise ProjectError("Undo history must retain between 1 and 10,000 edits.")
        self.preferences.data["undo_limit"] = limit
        for document in self.workspace.documents:
            document.history.set_limit(limit)
        self.preferences.save()

    def place_registered_asset(self, asset_id: str) -> str | None:
        """Place image/sequence/layered media through shared services and publish selection once."""
        from rigora.application_services.asset_pipeline import AssetPipeline

        document = self.documents
        asset = (
            next((a for a in document.project.assets if a.id == asset_id), None)
            if document.project
            else None
        )
        if asset is None:
            raise ProjectError("Choose an asset from the current project.")
        service = AssetPipeline(document)
        mesh_id: str | None
        if "sprite_sequence" in asset.extra:
            mesh_id = service.place_sequence(asset_id)
        elif "layered_layout" in asset.extra:
            result = service.place_layered(asset_id)
            mesh_id = result["mesh_ids"][0] if result["mesh_ids"] else None
        elif asset.kind in ("raster", "vector"):
            mesh_id = service.instantiate_asset(asset_id)
        else:
            raise ProjectError("Choose a placeable image, sequence or layered layout.")
        self.changed.emit()
        if mesh_id:
            self.mesh.select_mesh(mesh_id)
            mesh = service.mesh(mesh_id)
            self.scene.select((mesh.object_id,) if mesh.object_id else ())
        return mesh_id

    def reset_background_tools(self, document: DocumentService) -> None:
        """End a background tab's editor tools without changing the active tab's input state."""
        if document is self.documents:
            return
        key = document.context_key
        if rig_state := self.rig._tab_states.get(key):
            active, _, selected = rig_state
            self.rig._tab_states[key] = active, "select", selected
        if mesh_state := self.mesh._tabs.get(key):
            _, mesh, stage, selected, controls = mesh_state
            self.mesh._tabs[key] = False, mesh, stage, selected, controls

    def _plugins_changed(self) -> None:
        """Refresh every open runtime after extension activation without changing authored data."""
        for document in self.workspace.documents:
            self.plugins.attach(document)
        self.changed.emit()
        self.plugins_changed.emit()

    def enable_plugin(self, key: str, *, trust: bool = False) -> None:
        """Apply explicit trust/enable choices while keeping activation failures optional."""
        try:
            if trust:
                self.plugins.trust(key)
            self.plugins.enable(key)
            self.plugin_error = ""
        except (ProjectError, KeyError, OSError) as error:
            self.plugin_error = str(error)
        self.plugins_changed.emit()

    def run_plugin(self, key: str, arguments: dict[str, Any], *, isolated: bool = False) -> Any:
        """Dispatch extension commands through the shared service and current context adapter."""
        return self.extensions.execute(key, arguments, isolated=isolated)

    @property
    def documents(self) -> DocumentService:
        """Return the active project independently of the startup window's visibility."""
        return self.workspace.active or self._empty_document

    def activate_project(self, index: int) -> None:
        """Select an existing document without replacing or discarding its siblings."""
        self.welcome_selected = False
        self.welcome_open = False
        self.workspace.activate(index)
        self.changed.emit()

    def show_welcome(self) -> None:
        """Request the startup window without changing the active project or its pose."""
        self.playback.pause()
        self.welcome_open = True
        self.welcome_selected = True
        self.changed.emit()
        self.welcome_requested.emit()

    def close_welcome(self) -> None:
        """Dismiss the startup window while retaining the active project selection."""
        self.welcome_open = False
        self.welcome_selected = False
        self.changed.emit()

    def close_project(self, index: int, *, discard: bool = False) -> None:
        """Remove a tab after the presentation has resolved its unsaved-change guard."""
        self.workspace.close(index, discard=discard)
        self.changed.emit()

    def move_project(self, source: int, destination: int) -> None:
        """Reorder open documents while retaining the active document identity."""
        self.workspace.move(source, destination)
        self.changed.emit()

    @property
    def title(self) -> str:
        """Compose the operating-system window title from active identity and dirty state."""
        project = self.documents.project
        prefix = f"{project.name}{' *' if self.documents.dirty else ''} — " if project else ""
        return f"{prefix}{self.info.name} — {self.info.version}"

    @property
    def message(self) -> str:
        """Describe the currently available workspace capabilities."""
        return (
            "Import artwork to build a textured mesh, rig it and customize deformation."
            " Try the deformation studies for editable controls and motion keys."
        )

    def new_project(
        self, name: str = "Untitled project", settings: SceneSettings | None = None
    ) -> None:
        """Append an independent project session and notify presentation subscribers."""
        self.workspace.new(name, settings)
        self.welcome_selected = False
        self.welcome_open = False
        self.changed.emit()

    def open_project(self, path: Path) -> None:
        """Open or select a project, update recents, and publish the new active state."""
        self.workspace.open(path)
        self.welcome_selected = False
        self.welcome_open = False
        self.preferences.add_recent(path.resolve())
        self.changed.emit()

    def save_project(self, path: Path | None = None, *, overwrite: bool = False) -> None:
        """Reject conflicting open destinations and save through the document service."""
        if path is not None and any(
            doc is not self.documents and doc.path == path.resolve()
            for doc in self.workspace.documents
        ):
            raise ProjectError("This destination is already open in another project tab.")
        self.documents.save(path, overwrite=overwrite)
        if self.documents.path is not None:
            self.preferences.add_recent(self.documents.path)
        self.changed.emit()

    def recover_project(self, path: Path) -> None:
        """Append a backup recovery as a separate unsaved tab."""
        self.workspace.recover(path)
        self.welcome_selected = False
        self.welcome_open = False
        self.changed.emit()

    def edit_settings(self, name: str, scene_name: str, settings: SceneSettings) -> None:
        """Commit a reversible settings action and notify bound widgets."""
        self.documents.update_settings(name, scene_name, settings)
        self.changed.emit()

    def undo(self) -> None:
        """Revert one action in the active session and refresh presentation state."""
        self.documents.undo()
        self.changed.emit()

    def register_asset(self, source: Path) -> None:
        """Embed an opaque source file through the shared document command service."""
        self.documents.import_asset(source)
        self.changed.emit()

    def embed_linked_assets(self) -> None:
        """Make linked assets portable as one reversible document mutation."""
        self.documents.embed_external_assets()
        self.changed.emit()

    def redo(self) -> None:
        """Reapply one active-session action and refresh presentation state."""
        self.documents.redo()
        self.changed.emit()

    def set_theme(self, name: str) -> None:
        """Validate the requested theme and signal the presentation to apply it."""
        if name not in ("dark", "light"):
            raise ValueError("Unknown theme")
        self.preferences.data["theme"] = name
        self.theme_changed.emit(name)
