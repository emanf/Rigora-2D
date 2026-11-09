"""Per-document scene selection and reversible live object-transform presentation."""

from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

from rigora.application_services.commands import ScenePatch
from rigora.application_services.documents import DocumentService
from rigora.application_services.scene_editing import SceneEditingService
from rigora.domain.project import Project, ProjectError
from rigora.engine.state import ScenePose


class SceneViewModel(QObject):
    """Own inspectable scene selection and transient geometry without mutating during previews."""

    changed = Signal()
    document_changed = Signal()
    preview_changed = Signal()
    editing_started = Signal()

    def __init__(self, parent: QObject) -> None:
        """Initialize empty selection, edit mode and document-specific selection memory."""
        super().__init__(parent)
        self.document: DocumentService | None = None
        self._document_key = ""
        self.service: SceneEditingService | None = None
        self.selected: tuple[str, ...] = ()
        self.tool = "select"
        self.error = ""
        self._tabs: dict[str, tuple[str, ...]] = {}
        self._source: Project | None = None
        self._command: ScenePatch | None = None
        self._transform: tuple[str | None, dict[str, float]] | None = None
        self.preview: ScenePose | None = None
        self.auto_key = False
        self.sprite_edit = False
        self.part_edit = True
        self.selection_types = {"images", "bones", "groups"}

    def bind(self, document: DocumentService | None) -> None:
        """Restore a tab's selection and discard gestures invalidated by authoring changes."""
        if document is not self.document or self._document_key != (
            document.context_key if document else ""
        ):
            if self.document:
                self._tabs[self._document_key] = self.selected
            self.selected = self._tabs.get(document.context_key if document else "", ())
            self.tool = "select"
        self._document_key = document.context_key if document else ""
        self.document = document
        self.service = SceneEditingService(document) if document else None
        keys = self.service.records() if self.service else {}
        self.selected = tuple(k for k in self.selected if k in keys)
        self.cancel_preview()

    def select(self, keys: tuple[str, ...], extend: bool = False) -> None:
        """Select stable scene identities; locked entries remain inspectable from their rows."""
        if not self.service:
            return
        valid = self.service.records()
        self.selected = tuple(
            dict.fromkeys((*(self.selected if extend else ()), *(k for k in keys if k in valid)))
        )
        self.changed.emit()

    def run(self, operation: Callable[[SceneEditingService], object]) -> None:
        """Publish one service edit and preserve actionable validation feedback on failure."""
        if self.service is None:
            return
        self.editing_started.emit()
        try:
            self.service.auto_key = self.auto_key
            self.service.sprite_edit = self.sprite_edit or "bones" not in self.selection_types
            self.service.part_edit = self.part_edit and "bones" in self.selection_types
            operation(self.service)
            self.error = ""
            self.document_changed.emit()
        except ProjectError as error:
            self.error = str(error)
            self.changed.emit()

    def begin_preview(self) -> None:
        """Capture the exact revision against which a single object drag will commit."""
        self.cancel_preview()
        self._source = self.document.project if self.document else None

    def preview_transform(self, *, space_id: str | None = None, **values: float) -> None:
        """Evaluate local overrides against the compiled scene, publishing once on release.

        Sprite rebinding and spring key histories still use authored scratch previews;
        ordinary Object movement never rebuilds or validates the project per pointer event.
        """
        document = self.document
        if document is None or self._source is None or document.project is not self._source:
            self.cancel_preview()
            return
        service = SceneEditingService(document)
        service.auto_key = self.auto_key
        service.sprite_edit = self.sprite_edit or "bones" not in self.selection_types
        service.part_edit = self.part_edit and "bones" in self.selection_types
        if document.animation.evaluator.springs or service.sprite_bindings(self.selected):
            self._transform = None
            self.preview_edit(lambda s: s.transform(self.selected, space_id=space_id, **values))
            return
        try:
            changes, _ = service.plan_transform(self.selected, space_id=space_id, **values)
            overrides = {
                (key, f"transform.{name}"): getattr(record.transform, name)
                for key, record in changes.items()
                for name in ("x", "y", "rotation", "scale_x", "scale_y")
            }
            self.preview = document.animation.evaluator.evaluate(
                document.animation.pose.frame, overrides=overrides
            )
            self._transform = space_id, values
            self._command = None
            self.error = ""
        except ProjectError as error:
            self._transform, self._command, self.preview = None, None, None
            self.error = str(error)
        self.preview_changed.emit()

    def preview_pivot(self, key: str, x: float, y: float) -> None:
        """Preview one compensated pivot relocation with the same release/Undo lifecycle."""
        self.preview_edit(lambda s: s.move_pivot(key, x, y), "Move object pivot")

    def preview_edit(
        self,
        operation: Callable[[SceneEditingService], None],
        label: str = "Transform scene selection",
    ) -> None:
        """Evaluate one authoring operation against the immutable press revision."""
        self._transform = None
        document = self.document
        if document is None or self._source is None or document.project is not self._source:
            self.cancel_preview()
            return
        scratch = document.fork()
        try:
            service = SceneEditingService(scratch)
            service.auto_key = self.auto_key
            service.sprite_edit = self.sprite_edit or "bones" not in self.selection_types
            service.part_edit = self.part_edit and "bones" in self.selection_types
            operation(service)
            assert scratch.project is not None
            before, after = (
                next(s for s in self._source.scenes if s.id == scratch.scene.id),
                scratch.scene,
            )
            fields = {
                k: getattr(after, k)
                for k in (
                    "objects",
                    "groups",
                    "cameras",
                    "skeletons",
                    "timelines",
                    "clips",
                    "deformers",
                )
                if getattr(before, k) != getattr(after, k)
            }
            self._command = (
                ScenePatch(
                    label,
                    before.id,
                    {k: getattr(before, k) for k in fields},
                    fields,
                )
                if fields
                else None
            )
            self.preview = scratch.animation.evaluate(document.animation.pose.frame)
            self.error = ""
        except ProjectError as error:
            self._command, self.preview = None, None
            self.error = str(error)
        self.preview_changed.emit()

    def finish_preview(self) -> None:
        """Commit the last complete live preview as one undo entry if its source remains current."""
        if self.document and self.document.project is self._source and self._transform:
            space_id, values = self._transform
            self.run(lambda s: s.transform(self.selected, space_id=space_id, **values))
        if self.document and self.document.project is self._source and self._command:
            self.document.execute(self._command)
            self.document_changed.emit()
        self.cancel_preview()

    def cancel_preview(self) -> None:
        """Discard transient drag geometry without changing authoring data or history."""
        self._source, self._command, self.preview = None, None, None
        self._transform = None
        self.changed.emit()
