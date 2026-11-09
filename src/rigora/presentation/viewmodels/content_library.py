"""Asynchronous local content discovery and transient preview/selection presentation."""

import logging
from collections.abc import Callable
from concurrent.futures import CancelledError
from dataclasses import replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import QCoreApplication, QObject, QRunnable, QThreadPool, Signal
from shiboken6 import isValid

from rigora.application_services.content_library import ContentLibrary, ContentService, LibraryEntry
from rigora.application_services.documents import DocumentService
from rigora.domain.content import ContentItem
from rigora.domain.project import ProjectError


class LibrarySignals(QObject):
    """Marshal bounded background storage results back to GUI-owned presentation state."""

    done = Signal(object)
    failed = Signal(str)
    progress = Signal(int)


class LibraryJob(QRunnable):
    """Run one data-only discovery or install operation without blocking the interface."""

    def __init__(self, operation: Callable[[], Any]) -> None:
        """Retain one callable and its completion/error signal owner until the worker finishes."""
        super().__init__()
        self.operation = operation
        # Application ownership keeps queued callbacks and their widget captures
        # alive until the GUI processes the result and deferred signal deletion.
        self.signals = LibrarySignals(QCoreApplication.instance())

    def run(self) -> None:
        """Deliver storage results or actionable errors without mutating a project."""
        try:
            self.deliver("done", self.operation())
        except CancelledError:
            self.deliver("failed", "")
        except (ProjectError, OSError, ValueError, KeyError, TypeError, IndexError) as error:
            self.deliver("failed", str(error))
        except Exception as error:
            logging.getLogger(__name__).exception("Background content operation failed")
            self.deliver("failed", str(error))
        finally:
            if isValid(self.signals):
                self.signals.deleteLater()

    def deliver(self, signal: str, value: Any) -> None:
        """Discard late results after Qt application teardown has destroyed the signal owner."""
        try:
            getattr(self.signals, signal).emit(value)
        except RuntimeError:
            if isValid(self.signals):
                raise


class LibraryViewModel(QObject):
    """Keep pack lists and scratch previews separate from active document commands."""

    changed = Signal()
    document_changed = Signal()
    create_requested = Signal()
    applied = Signal(str, str)
    generation_progress = Signal(int, int, str)

    def __init__(self, parent: QObject, library: ContentLibrary) -> None:
        """Own a bounded worker pool and no automatically installed user content."""
        super().__init__(parent)
        self.library = library
        self.library.isolate_preparation = True
        self.document: DocumentService | None = None
        self.entries: tuple[LibraryEntry, ...] = ()
        self.scene_performances: dict[str, ContentItem] = {}
        self.error = ""
        self.busy = False
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.jobs: list[LibraryJob] = []
        self.alive = True
        self.cancel_generation = False
        self.library.generation_progress = self.generation_progress.emit
        self.library.generation_cancelled = lambda: not self.alive or self.cancel_generation

    def bind(self, document: DocumentService | None) -> None:
        """Publish the current target document without altering installed or favorite state."""
        self.document = document
        self.changed.emit()

    def entry(self, key: str) -> LibraryEntry | None:
        """Resolve catalog identity with its transient character performance choice for drags."""
        source = next((entry for entry in self.entries if entry.key == key), None)
        if source is None:
            return None
        return replace(source, item=self.scene_performances.get(key, source.item))

    def background(
        self,
        operation: Callable[[], Any],
        complete: Callable[[Any], None],
        *,
        failed: Callable[[str], None] | None = None,
    ) -> None:
        """Schedule one serialized storage operation and keep its signal owner alive."""
        if not self.alive:
            return
        self.busy = True
        self.error = ""
        job = LibraryJob(operation)
        self.jobs.append(job)

        def success(value: Any) -> None:
            """Publish a worker result after returning to the GUI thread."""
            if not self.alive:
                return
            self.jobs.remove(job)
            self.busy = bool(self.jobs)
            self.error = ""
            complete(value)
            self.changed.emit()

        def failure(message: str) -> None:
            """Restore controls after a failed read without discarding installed content."""
            if not self.alive:
                return
            self.jobs.remove(job)
            self.busy = bool(self.jobs)
            self.error = message
            if failed:
                failed(message)
            self.changed.emit()

        job.signals.done.connect(success)
        job.signals.failed.connect(failure)
        self.pool.start(job)
        self.changed.emit()

    def shutdown(self) -> None:
        """Drain workers before releasing their GUI-owned signal connections at shutdown."""
        self.alive = False
        self.pool.clear()
        self.pool.waitForDone()
        for job in self.jobs:
            job.signals.done.disconnect()
            job.signals.failed.disconnect()
        self.jobs.clear()
        self.busy = False

    def reload(self) -> None:
        """Discover installed content off the GUI thread and surface malformed-pack diagnostics."""
        self.cancel_generation = False

        def complete(entries: tuple[LibraryEntry, ...]) -> None:
            """Replace search records only after a complete bounded scan."""
            previous = {entry.key: entry.item for entry in self.entries}
            self.entries = entries
            unchanged = {entry.key for entry in entries if previous.get(entry.key) == entry.item}
            self.scene_performances = {
                key: item for key, item in self.scene_performances.items() if key in unchanged
            }
            self.error = " · ".join(self.library.warnings)

        self.background(self.library.entries, complete)

    def install(self, path: Path) -> None:
        """Install a user-chosen pack atomically, then refresh the offline catalog."""
        self.background(lambda: self.library.install(path), lambda name: self.reload())

    def apply(
        self, entry: LibraryEntry, files: dict[str, bytes], target: str, mesh_id: str
    ) -> None:
        """Apply a loaded asset through canonical services and notify all document adapters."""
        if self.document is None:
            self.create_requested.emit()
        if self.document is None:
            return
        try:
            result = ContentService(self.document).apply(
                entry.item, files, target=target, mesh_id=mesh_id
            )
            self.error = ""
            self.library.used(entry.key)
            self.document_changed.emit()
            self.applied.emit(entry.item.kind, result)
        except (ProjectError, OSError, ValueError) as error:
            self.error = str(error)
        self.changed.emit()
