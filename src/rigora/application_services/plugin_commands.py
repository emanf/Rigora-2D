"""Qt-free extension command dispatch shared by desktop, Python and headless clients."""

from collections.abc import Callable
from typing import Any

from rigora.application_services.commands import ScenePatch
from rigora.application_services.documents import DocumentService
from rigora.application_services.plugins import PluginManager
from rigora.domain.entities import Constraint
from rigora.domain.project import ProjectError
from rigora.sdk.api import PluginRequest


def document_service(name: str, document: DocumentService) -> Any:
    """Construct a canonical service bound to the caller's current document, never a global tab."""
    from rigora.application_services.animation_editing import AnimationEditingService
    from rigora.application_services.appearance import AppearanceService
    from rigora.application_services.artwork_editing import ArtworkEditingService
    from rigora.application_services.audio import AudioService
    from rigora.application_services.bindings import BindingService
    from rigora.application_services.camera_shots import CameraShotService
    from rigora.application_services.cameras import CameraService
    from rigora.application_services.characters import CharacterService
    from rigora.application_services.contact_editing import ContactEditingService
    from rigora.application_services.deformation import DeformationService
    from rigora.application_services.export_preflight import ExportPreflight
    from rigora.application_services.facial import FaceService
    from rigora.application_services.game_authoring import GameAuthoringService
    from rigora.application_services.meshes import MeshService
    from rigora.application_services.path_editing import PathEditingService
    from rigora.application_services.rigging import RigService
    from rigora.application_services.scene_attachments import SceneAttachmentService
    from rigora.application_services.scene_editing import SceneEditingService
    from rigora.application_services.skinning import SkinService
    from rigora.application_services.state_machines import StateMachineService

    services: dict[str, Callable[[DocumentService], Any]] = {
        "rig": RigService,
        "scene": SceneEditingService,
        "mesh": MeshService,
        "skin": SkinService,
        "characters": CharacterService,
        "animation": AnimationEditingService,
        "appearance": AppearanceService,
        "deformation": DeformationService,
        "face": FaceService,
        "bindings": BindingService,
        "scene_attachments": SceneAttachmentService,
        "artwork": ArtworkEditingService,
        "audio": AudioService,
        "contacts": ContactEditingService,
        "paths": PathEditingService,
        "game": GameAuthoringService,
        "cameras": CameraService,
        "camera_shots": CameraShotService,
        "state_machines": StateMachineService,
        "export_preflight": ExportPreflight,
    }
    if name not in services:
        raise ProjectError(f"Unknown application service: {name}.")
    return services[name](document)


def action_enabled(contribution: Any, state: dict[str, Any]) -> bool:
    """Evaluate documented context requirements identically for UI and direct command dispatch."""
    conditions = {
        "project": bool(state.get("project_id")),
        "selection": bool(state.get("selection") or state.get("bone_ids")),
        "bones": bool(state.get("bone_ids")),
        "mesh": bool(state.get("mesh_id")),
        "object": state.get("editor") == "object",
        "scene": state.get("editor", "scene") == "scene",
        "playing": bool(state.get("playing")),
    }
    return all(conditions.get(str(key), False) for key in contribution.metadata.get("when", ()))


class PluginCommandService:
    """Apply registered commands through one failure boundary and one undo transaction."""

    def __init__(self, plugins: PluginManager) -> None:
        """Retain a registry, with no Qt state or ownership of a document."""
        self.plugins = plugins

    def execute(
        self,
        key: str,
        document: DocumentService | None,
        arguments: dict[str, Any],
        *,
        state: dict[str, Any] | None = None,
        host: Any = None,
        dispatch: Callable[[str, dict[str, Any]], Any] | None = None,
        isolated: bool = False,
    ) -> Any:
        """Resolve permissions and current context, rolling back a failed modifying callback."""
        contribution = next((c for c in self.plugins.contributions() if c.id == key), None)
        if contribution is None:
            raise ProjectError("Plugin contribution is not active.")
        state = {
            "project_id": document.project.id if document and document.project else "",
            **(state or {}),
        }
        if not action_enabled(contribution, state):
            raise ProjectError(
                "This extension action is unavailable in the current editor/selection."
            )
        permissions = self.plugins.states[contribution.plugin_id].manifest.permissions
        request = PluginRequest(
            document if "project.read" in permissions else None,
            arguments,
            dispatch,
            state,
            host if "ui" in permissions else None,
        )
        if isolated:
            from rigora.application_services.plugin_jobs import run_isolated

            return run_isolated(self.plugins, key, request)

        def apply() -> Any:
            """Adapt engine contributions to canonical records, invoking other commands directly."""
            if contribution.kind == "deformers":
                from rigora.application_services.deformation import (
                    DeformationPreset,
                    DeformationService,
                )

                target = request.require_document()
                mesh = str(arguments.get("mesh_id") or request.state.get("mesh_id", ""))
                parameters = {
                    **dict(contribution.metadata.get("parameters", {})),
                    **arguments.get("parameters", {}),
                }
                return DeformationService(target).add(
                    mesh, DeformationPreset(contribution.name, key, parameters)
                )
            if contribution.kind == "constraints":
                target = request.require_document()
                selected = request.state.get("bone_ids", ())
                owner = str(arguments.get("owner_id") or (selected[0] if selected else ""))
                rule = Constraint(
                    name=contribution.name,
                    kind=key,
                    owner_id=owner,
                    target_id=arguments.get("target_id"),
                    parameters={
                        **dict(contribution.metadata.get("parameters", {})),
                        **arguments.get("parameters", {}),
                    },
                )
                assert target.project is not None
                scene = target.scene
                target.execute(
                    ScenePatch(
                        "Add plugin constraint",
                        scene.id,
                        {"constraints": scene.constraints},
                        {"constraints": (*scene.constraints, rule)},
                    )
                )
                return rule.id
            return self.plugins.invoke(key, request)

        if document and (
            "project.write" in permissions or contribution.kind in ("deformers", "constraints")
        ):
            with document.command_group(contribution.name):
                return apply()
        return apply()
