"""Extension presentation state and lifecycle events, independent of concrete Qt widgets."""

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, Signal

from rigora.application_services.plugin_commands import PluginCommandService, action_enabled
from rigora.domain.character_recipe import CharacterRecipe
from rigora.domain.project import Project, ProjectError
from rigora.sdk.api import Contribution, PluginRequest

if TYPE_CHECKING:
    from rigora.presentation.viewmodels.main_window import MainWindowViewModel


class ExtensionViewModel(QObject):
    """Own current extension context, command dispatch and nonrecursive application hooks."""

    state_changed = Signal()

    def __init__(self, owner: "MainWindowViewModel") -> None:
        """Bind application signals without retaining a view or importing desktop widgets."""
        super().__init__(owner)
        self.owner = owner
        self.commands = PluginCommandService(owner.plugins)
        self.host: Any = None
        self.editor = "scene"
        self._emitting: set[str] = set()
        self._documents: dict[str, Project] = {}
        self._active = ""
        self._project: object = None
        self._selection: object = None
        owner.changed.connect(self.update)
        owner.scene.changed.connect(self.selection_changed)
        owner.rig.changed.connect(self.selection_changed)
        owner.mesh.changed.connect(self.selection_changed)
        owner.playback.changed.connect(self.frame_changed)

    def state(self) -> dict[str, Any]:
        """Snapshot selection, active editor and transport without exposing a mutable ViewModel."""
        model = self.owner
        session = model.playback.session
        document = model.documents
        return {
            "project_id": document.project.id if document.project else "",
            "document_id": document.session_id if document.project else "",
            "selection": tuple(model.scene.selected),
            "bone_ids": tuple(model.rig.selected),
            "mesh_id": model.mesh.mesh_id or "",
            "editor": self.editor,
            "frame": session.playback.frame if session else 0,
            "playing": bool(session and session.playback.is_playing),
        }

    def request(
        self, contribution: Contribution, arguments: dict[str, Any] | None = None
    ) -> PluginRequest:
        """Build permission-scoped current-tab requests for every UI adapter and event hook."""
        model = self.owner
        permissions = model.plugins.states[contribution.plugin_id].manifest.permissions
        document = model.documents
        return PluginRequest(
            document if document.project and "project.read" in permissions else None,
            arguments or {},
            model.run_plugin,
            self.state(),
            self.host if "ui" in permissions else None,
        )

    def enabled(self, contribution: Contribution) -> bool:
        """Expose command state to views while keeping condition logic in the shared service."""
        return action_enabled(contribution, self.state())

    def execute(self, key: str, arguments: dict[str, Any], *, isolated: bool = False) -> Any:
        """Adapt current presentation state to the shared service and publish authored changes."""
        model = self.owner
        document = model.documents if model.documents.project else None
        previous = document.project if document else None
        contribution = next((c for c in model.plugins.contributions() if c.id == key), None)
        if contribution and (
            "project.write" in model.plugins.states[contribution.plugin_id].manifest.permissions
            or contribution.kind in ("deformers", "constraints")
        ):
            model.playback.pause()
        result = self.commands.execute(
            key,
            document,
            arguments,
            state=self.state(),
            host=self.host,
            dispatch=model.run_plugin,
            isolated=isolated,
        )
        if document and document.project is not previous:
            model.changed.emit()
        return result

    def emit_event(self, event: str, **arguments: Any) -> None:
        """Dispatch owned hooks with undo/failure handling, suppressing recursive event cycles."""
        if event in self._emitting:
            return
        self._emitting.add(event)
        try:
            for hook in tuple(self.owner.plugins.contributions("hooks")):
                if hook.metadata.get("event") == event:
                    try:
                        self.execute(hook.id, {"event": event, **arguments})
                    except ProjectError as error:
                        self.owner.plugins.report(hook.plugin_id, str(error))
        finally:
            self._emitting.remove(event)

    def update(self) -> None:
        """Derive open/close/activation/edit events from canonical workspace identities."""
        current = {d.session_id: d.project for d in self.owner.workspace.documents if d.project}
        previous = self._documents
        self._documents = current
        for key in previous.keys() - current.keys():
            self.emit_event("project.closed", document_id=key)
        for key in current.keys() - previous.keys():
            self.emit_event("project.opened", document_id=key)
        state = self.state()
        if state["document_id"] != self._active:
            self._active = state["document_id"]
            self.emit_event("project.activated")
        project = self.owner.documents.project
        if project is not self._project:
            self._project = project
            self.emit_event("project.changed")
        self.state_changed.emit()

    def selection_changed(self) -> None:
        """Notify only on actual selection changes, avoiding per-frame hierarchy churn."""
        state = self.state()
        signature = (state["selection"], state["bone_ids"], state["mesh_id"])
        if signature != self._selection:
            self._selection = signature
            self.emit_event("selection.changed")
            self.state_changed.emit()

    def frame_changed(self) -> None:
        """Publish frame state without rebinding widgets or rebuilding extension contributions."""
        self.emit_event("timeline.frame_changed", frame=self.state()["frame"])
        self.state_changed.emit()

    def set_editor(self, editor: str) -> None:
        """Accept editor navigation from the view and publish context-sensitive command state."""
        if self.editor != editor:
            self.editor = editor
            self.emit_event("editor.changed", editor=editor)
            self.state_changed.emit()

    def character_presets(self) -> dict[str, CharacterRecipe]:
        """Resolve live providers into validated creator recipes, containing optional failures."""
        result = {}
        for contribution in self.owner.plugins.contributions("templates"):
            if contribution.metadata.get("template_type") == "character_recipe":
                try:
                    recipe = self.owner.plugins.invoke(contribution.id, self.request(contribution))
                    if not isinstance(recipe, CharacterRecipe):
                        raise ProjectError(
                            "Character preset providers must return a CharacterRecipe."
                        )
                    result[f"{contribution.name} · {contribution.plugin_id}"] = recipe
                except ProjectError as error:
                    self.owner.plugins.report(contribution.plugin_id, str(error))
        return result
