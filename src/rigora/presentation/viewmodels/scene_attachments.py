"""Presentation state for directed Scene attachments and owner-local grip editing."""

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, Signal

from rigora.application_services.characters import CharacterService
from rigora.application_services.scene_attachments import SceneAttachmentService
from rigora.domain.entities import Camera, Group, SceneObject
from rigora.domain.scene_attachments import AttachmentState

if TYPE_CHECKING:
    from rigora.presentation.viewmodels.main_window import MainWindowViewModel


class AttachmentViewModel(QObject):
    """Keep document edits and target discovery independent of the dialog's widget layout."""

    changed = Signal()

    def __init__(self, host: "MainWindowViewModel", parent: QObject) -> None:
        """Follow the active document and report canonical service errors through one boundary."""
        super().__init__(parent)
        self.host = host
        self.status = ""
        self.applying = False

    @property
    def service(self) -> SceneAttachmentService:
        """Resolve the current document at command time instead of retaining a stale tab."""
        return SceneAttachmentService(self.host.documents)

    def objects(self) -> tuple[tuple[str, str], ...]:
        """Offer placed Objects, excluding artwork parts and cameras."""
        records = self.service.records()
        return tuple(
            (key, records[key].name)
            for key in CharacterService(self.host.documents).scene_objects()
            if isinstance(records.get(key), (Group, SceneObject))
            and not isinstance(records[key], Camera)
        )

    def selected_object(self) -> str:
        """Resolve a selected artwork part to its owning placed Object."""
        characters = CharacterService(self.host.documents)
        available = dict(self.objects())
        for key in self.host.scene.selected:
            root = characters.object_root(key)
            value = root.id if root else key
            if value in available:
                return value
        return ""

    def targets(self, source: str) -> tuple[tuple[str, str, str], ...]:
        """Return readable target identities and optional Object parents for a compact tree."""
        service = self.service
        characters = CharacterService(self.host.documents)
        objects = dict(self.objects())
        result = [(key, label, "") for key, label in objects.items() if key != source]
        for rig in service.scene.skeletons:
            for bone in rig.bones:
                if service.locked(bone.id):
                    continue
                root = characters.object_root(bone.id)
                owner = root.id if root else ""
                if owner == source:
                    continue
                name = bone.name
                if name.endswith((".R", ".L")):
                    side = "Right" if name.endswith(".R") else "Left"
                    name = f"{side} {name[:-2].replace('_', ' ')}"
                result.append((bone.id, name, owner))
        return tuple(result)

    def state(self, owner: str, frame: float | None = None) -> AttachmentState:
        """Read the relationship at a frame without changing the playhead."""
        return self.service.state(owner, frame)

    def run(self, operation: Callable[[SceneAttachmentService], Any], message: str) -> bool:
        """Publish through the same Scene ViewModel used by viewport editing and Undo."""
        self.applying = True
        try:
            self.host.scene.run(lambda _: operation(self.service))
        finally:
            self.applying = False
        self.status = self.host.scene.error or message
        self.changed.emit()
        return not bool(self.host.scene.error)

    def attach(self, owner: str, target: str | None, **settings: Any) -> bool:
        """Apply an explicit setup or keyed attachment without relying on global Auto Key."""
        return self.run(
            lambda service: service.attach((owner,), target, **settings),
            "Attachment saved. Move the target to see the object follow.",
        )

    def detach(self, owner: str, frame: float | None) -> bool:
        """Release the source while preserving all artwork, skeletons and physics."""
        return self.run(
            lambda service: service.detach((owner,), frame=frame),
            "Released. The object keeps its current position.",
        )
