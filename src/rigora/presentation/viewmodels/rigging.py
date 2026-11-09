"""Selection and rest-rig presentation over shared undoable authoring services."""

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Signal

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.bone_animation import BoneAnimationService
from rigora.application_services.commands import ScenePatch
from rigora.application_services.documents import DocumentService
from rigora.application_services.rigging import RigService
from rigora.domain.entities import Bone
from rigora.domain.project import Project, ProjectError
from rigora.engine.state import ScenePose


class RigViewModel(QObject):
    """Own transient rig mode/selection and report validated command failures to the view."""

    changed = Signal()
    document_changed = Signal()
    preview_changed = Signal()
    preview_reset = Signal()
    editing_started = Signal()

    def __init__(self, parent: QObject) -> None:
        """Initialize an empty editor without creating or changing any document."""
        super().__init__(parent)
        self.document: DocumentService | None = None
        self._document_key = ""
        self.service: RigService | None = None
        self.selected: tuple[str, ...] = ()
        self.active = False
        self.tool = "select"
        self.error = ""
        self.pose: ScenePose | None = None
        self.auto_key = False
        self.auto_bind_artwork = True
        self._preview_frame = 0.0
        self._preview_source: Project | None = None
        self._preview_command: ScenePatch | None = None
        self._preview_values: dict[tuple[str, str], float] | None = None
        self._tab_states: dict[str, tuple[bool, str, tuple[str, ...]]] = {}

    def bind(self, document: DocumentService | None) -> None:
        """Refresh rest evaluation after document edits, undo or tab switches."""
        self._preview_source, self._preview_command = None, None
        self._preview_values = None
        self.preview_reset.emit()
        if document is not self.document or self._document_key != (
            document.context_key if document else ""
        ):
            if self.document:
                self._tab_states[self._document_key] = (self.active, self.tool, self.selected)
            self.active, self.tool, self.selected = self._tab_states.get(
                document.context_key if document else "", (False, "select", ())
            )
            self.error = ""
        self._document_key = document.context_key if document else ""
        self.document = document
        self.service = RigService(document) if document else None
        self.pose = None
        if self.service:
            keys = {b.id for r in self.service.scene.skeletons for b in r.bones}
            self.selected = tuple(key for key in self.selected if key in keys)
            try:
                self.pose = document.animation.pose if document else None
            except ProjectError as error:
                self.error = str(error)
        self.changed.emit()

    @property
    def animating(self) -> bool:
        """Record pose gestures when auto-keying or an existing clip supplies animation context."""
        return self.document is not None and (
            self.auto_key or self.document.selected_clip_id is not None
        )

    @property
    def bone(self) -> Bone | None:
        """Resolve the primary selected bone against the current document revision."""
        try:
            return self.service.bone(self.selected[0]) if self.service and self.selected else None
        except ProjectError:
            return None

    def select(self, key: str, extend: bool = False, *, inspect: bool = False) -> None:
        """Select an unlocked bone, optionally toggling membership for group operations."""
        if self.service is None:
            return
        if not key:
            self.selected = ()
            self.changed.emit()
            return
        try:
            self.service.bone(key) if inspect else self.service.editable(key)
        except ProjectError as error:
            self.error = str(error)
            self.changed.emit()
            return
        self.selected = (
            tuple(k for k in self.selected if k != key)
            if extend and key in self.selected
            else (*self.selected, key)
            if extend
            else (key,)
        )
        self.error = ""
        self.changed.emit()

    def select_group(self, name: str) -> None:
        """Select every visible, unlocked member of a named bone group."""
        if self.service:
            keys = []
            for rig in self.service.scene.skeletons:
                for bone in rig.bones:
                    if bone.group != name or not self.pose or not self.pose.nodes[bone.id].visible:
                        continue
                    try:
                        self.service.editable(bone.id)
                    except ProjectError:
                        continue
                    keys.append(bone.id)
            self.selected = tuple(keys)
            self.changed.emit()

    def select_many(self, keys: tuple[str, ...], extend: bool = False) -> None:
        """Select visible editable marquee results, optionally adding to the current selection."""
        if not self.service:
            return
        accepted = []
        for key in keys:
            try:
                self.service.editable(key)
            except ProjectError:
                continue
            accepted.append(key)
        self.selected = tuple(dict.fromkeys((*(self.selected if extend else ()), *accepted)))
        self.changed.emit()

    def run(self, operation: Callable[[RigService], Any]) -> None:
        """Run a command and publish document changes only after successful validation."""
        if self.service is None:
            return
        self.editing_started.emit()
        try:
            result = operation(self.service)
            if isinstance(result, str) and any(
                result == b.id for r in self.service.scene.skeletons for b in r.bones
            ):
                self.selected = (result,)
            self.error = ""
            self.active = True
            self.document_changed.emit()
        except ProjectError as error:
            self.error = str(error)
        self.changed.emit()

    def set_tool(self, tool: str) -> None:
        """Activate a rig interaction tool while keeping authoring and transport separate."""
        self.active, self.tool = True, tool
        self.changed.emit()

    def create(self, x: float, y: float, end_x: float, end_y: float) -> None:
        """Create a drawn world-space bone using the current selected parent."""
        parent = self.selected[0] if self.selected else None
        self.run(lambda service: service.create_bone((x, y), (end_x, end_y), parent))

    def drag(self, key: str, tool: str, x: float, y: float) -> None:
        """Commit the final live preview as one command, retaining atomic undo/redo."""
        if self._preview_source is None:
            self.begin_preview()
        self.preview_drag(key, tool, x, y)
        command = self._preview_command
        values = self._preview_values
        self._preview_source, self._preview_command = None, None
        self._preview_values = None
        if values:
            frame = self._preview_frame
            self.run(
                lambda service: AnimationEditingService(service.document).auto_key_values(
                    values, frame
                )
            )
        elif command is not None and command.after:
            self.run(lambda service: service.document.execute(command))

    def begin_preview(self) -> None:
        """Retain the immutable gesture baseline so stale authoring changes cancel safely."""
        self._preview_source = self.document.project if self.document else None
        self._preview_command = None
        self._preview_values = None
        self._preview_frame = self.document.animation.pose.frame if self.document else 0.0

    def preview_drag(self, key: str, tool: str, x: float, y: float) -> None:
        """Evaluate the actual rig and skinned artwork without dirtying the document on movement."""
        if not self.service or not self.document:
            return
        if (
            self.document.project is not self._preview_source
            or self.document.animation.pose.frame != self._preview_frame
        ):
            self.cancel_preview()
            self.preview_reset.emit()
            return
        try:
            session = self.document.animation
            timeline = session.evaluator.timeline
            fast = (
                self.animating
                and not session.evaluator.springs
                and all(
                    t.blend_mode == "override" and t.weight == 1 and not t.extra.get("sampler")
                    for t in (timeline.tracks if timeline else ())
                )
            )
            if fast:
                service = BoneAnimationService(self.document)
                self._preview_values = service.solve_drag(key, tool, x, y, self.selected)
                self._preview_command = None
                self.pose = session.evaluator.evaluate(
                    self._preview_frame, loop=session.playback.loop, overrides=self._preview_values
                )
            else:
                self._preview_values = None
                pose_service = (
                    BoneAnimationService(self.document) if self.animating else self.service
                )
                self._preview_command, self.pose = pose_service.plan_drag(
                    key, tool, x, y, self.selected
                )
            self.error = ""
        except ProjectError as error:
            self._preview_command = None
            self._preview_values = None
            self.pose = self.document.animation.pose
            self.error = str(error)
        self.preview_changed.emit()

    def cancel_preview(self) -> None:
        """Restore the canonical evaluated pose after Escape, focus loss or a cancelled gesture."""
        if self._preview_source is not None:
            self._preview_source, self._preview_command = None, None
            self._preview_values = None
            self.pose = self.document.animation.pose if self.document else None
            self.preview_changed.emit()

    def sync_playback(self) -> None:
        """Follow scrubbing/playback and cancel a gesture whose frame changed before release."""
        if self.document is None:
            return
        if (
            self._preview_source is not None
            and self.document.animation.pose.frame != self._preview_frame
        ):
            self.cancel_preview()
            self.preview_reset.emit()
        if self._preview_source is None:
            self.pose = self.document.animation.pose
            self.preview_changed.emit()

    def edit_pose(self, values: dict[str, float], details: dict[str, Any] | None = None) -> None:
        """Record numeric bone fields at the displayed frame while preserving rest data."""
        if self.document and self.selected:
            document, owner = self.document, self.selected[0]

            def record(service: RigService) -> None:
                """Group numeric keys and any simultaneous identity-preserving inspector edits."""
                with document.command_group("Edit bone pose"):
                    if details:
                        service.update(owner, **details)
                    AnimationEditingService(document).auto_key_values(
                        {(owner, path): value for path, value in values.items()},
                        document.animation.pose.frame,
                    )

            self.run(record)
