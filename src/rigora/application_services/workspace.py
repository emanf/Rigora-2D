"""Qt-free multi-document ownership. Closing requires caller confirmation."""

from pathlib import Path

from rigora.application_services.documents import DocumentService
from rigora.domain.project import ProjectError, SceneSettings


class WorkspaceService:
    """Own multiple document sessions and selection independently of Qt presentation."""

    def __init__(self, initial: DocumentService | None = None) -> None:
        """Adopt an optional populated document as the first active session."""
        self._documents = [initial] if initial is not None and initial.project is not None else []
        self.active_index = 0 if self._documents else -1

    @property
    def documents(self) -> tuple[DocumentService, ...]:
        """Expose an immutable view of open sessions in tab order."""
        return tuple(self._documents)

    @property
    def active(self) -> DocumentService | None:
        """Return the selected session or None for the welcome workspace."""
        return self._documents[self.active_index] if self.active_index >= 0 else None

    def activate(self, index: int) -> None:
        """Select a valid tab without changing any document contents."""
        if not 0 <= index < len(self._documents):
            raise ProjectError("Invalid project tab.")
        self.active_index = index

    def new(self, name: str, settings: SceneSettings | None = None) -> DocumentService:
        """Create and select an independent unsaved document session."""
        document = DocumentService()
        document.new(name, settings)
        self._documents.append(document)
        self.active_index = len(self._documents) - 1
        return document

    def open(self, path: Path) -> DocumentService:
        """Select an already-open path or append a successfully loaded document."""
        resolved = path.resolve()
        for index, document in enumerate(self._documents):
            if document.path == resolved:
                self.activate(index)
                return document
        document = DocumentService()
        document.open(resolved)
        self._documents.append(document)
        self.active_index = len(self._documents) - 1
        return document

    def recover(self, path: Path) -> DocumentService:
        """Append an unsaved recovery session retaining the backup's source assets."""
        document = DocumentService()
        document.recover(path)
        self._documents.append(document)
        self.active_index = len(self._documents) - 1
        return document

    def adopt(self, document: DocumentService) -> DocumentService:
        """Adopt a worker-loaded document on the workspace owner without re-reading its package."""
        if document.project is None:
            raise ProjectError("Cannot adopt an empty document.")
        for index, existing in enumerate(self._documents):
            if document.path is not None and existing.path == document.path:
                self.activate(index)
                return existing
        self._documents.append(document)
        self.active_index = len(self._documents) - 1
        return document

    def close(self, index: int, *, discard: bool = False) -> None:
        """Remove a session only after its dirty-state guard has been explicitly resolved."""
        if not 0 <= index < len(self._documents):
            raise ProjectError("Invalid project tab.")
        if self._documents[index].dirty and not discard:
            raise ProjectError("Unsaved changes require explicit save or discard before closing.")
        active = self.active
        self._documents.pop(index)
        if not self._documents:
            self.active_index = -1
        elif active in self._documents:
            self.active_index = self._documents.index(active)
        else:
            self.active_index = min(index, len(self._documents) - 1)

    def move(self, source: int, destination: int) -> None:
        """Reorder sessions while preserving which document is active."""
        if not (0 <= source < len(self._documents) and 0 <= destination < len(self._documents)):
            raise ProjectError("Invalid project tab move.")
        active = self.active
        self._documents.insert(destination, self._documents.pop(source))
        self.active_index = self._documents.index(active) if active is not None else -1
