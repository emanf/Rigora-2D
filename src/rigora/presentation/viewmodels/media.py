"""GUI ownership of asynchronous media imports and the shared Qt-free render queue."""

from collections.abc import Callable
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, QThreadPool, QTimer, Signal

from rigora.api import RigoraAPI
from rigora.application_services.asset_pipeline import AssetPipeline
from rigora.application_services.documents import DocumentService
from rigora.application_services.output import OutputSettings
from rigora.application_services.render_queue import RenderQueue
from rigora.domain.project import ProjectError
from rigora.presentation.viewmodels.content_library import LibraryJob

if TYPE_CHECKING:
    from rigora.presentation.viewmodels.main_window import MainWindowViewModel


class OutputViewModel(QObject):
    """Keep queued render snapshots independent of the editor and marshal polled progress."""

    changed = Signal()

    def __init__(self, parent: QObject) -> None:
        """Own one serial queue and a lightweight GUI timer with no worker widget access."""
        super().__init__(parent)
        self.queue = RenderQueue()
        self.error = ""
        self.paths: dict[str, str] = {}
        self.timer = QTimer(self)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.changed.emit)
        self.check_pool = QThreadPool(self)
        self.check_pool.setMaxThreadCount(1)
        self.check_job: LibraryJob | None = None
        self.check_cancel = Event()
        self.check_result: dict[str, Any] | None = None
        self.alive = True

    def preflight(
        self, document: DocumentService, settings: OutputSettings, encoder: Path | None
    ) -> None:
        """Check a captured revision off-thread; reject stale reports after concurrent edits."""
        if self.check_job is not None:
            self.check_cancel.set()
            return
        from rigora.application_services.export_preflight import ExportPreflight

        scratch, baseline = document.fork(), document.project
        context = (document.scene.id, document.animation_context, document.selected_clip_id)
        self.check_cancel = cancel = Event()
        self.check_result, self.error = None, ""

        def complete(result: dict[str, Any]) -> None:
            """Publish diagnostics on the GUI thread only for their exact owning revision."""
            if not self.alive:
                return
            self.check_job = None
            if document.project is not baseline or context != (
                document.scene.id,
                document.animation_context,
                document.selected_clip_id,
            ):
                self.error = "Export check became stale. Run it again for the current revision."
            else:
                self.check_result = result
            self.changed.emit()

        def failed(message: str) -> None:
            """Release busy state without modifying any source or output file."""
            if self.alive:
                self.check_job, self.error = None, message
                self.changed.emit()

        job = self.check_job = LibraryJob(
            lambda: ExportPreflight(scratch).inspect(settings, encoder=encoder, cancel=cancel)
        )
        job.signals.done.connect(complete)
        job.signals.failed.connect(failed)
        self.check_pool.start(job)
        self.changed.emit()

    def submit(
        self,
        document: Any,
        path: Path,
        settings: OutputSettings,
        overwrite: bool,
        encoder: Path | None,
    ) -> str | None:
        """Authorize a user-chosen directory and queue the current document as an owned snapshot."""
        try:
            api = RigoraAPI(path.parent, document=document, encoder=encoder)
            service = api._output_service(overwrite)
            service.export(document, path.name, settings, dry_run=True)
            state = self.queue.submit(document, service, path.name, settings)
        except (ProjectError, OSError) as error:
            self.error = str(error)
            self.changed.emit()
            return None
        self.error = ""
        self.paths[state["job_id"]] = str(path)
        self.timer.start()
        self.changed.emit()
        return str(state["job_id"])

    def states(self) -> list[dict[str, Any]]:
        """Return queue progress and stop polling when no background work remains."""
        jobs: list[dict[str, Any]] = self.queue.inspect()["jobs"]
        if jobs and all(j["status"] in ("completed", "cancelled", "failed") for j in jobs):
            self.timer.stop()
        return jobs

    def cancel(self, key: str) -> None:
        """Request safe cancellation of the explicitly selected job."""
        self.queue.cancel(key)
        self.changed.emit()

    def close(self) -> None:
        """Stop GUI polling and cancel owned work during application shutdown."""
        self.timer.stop()
        self.alive = False
        self.check_cancel.set()
        self.check_pool.clear()
        self.queue.close(wait=False)


class MediaImportViewModel(QObject):
    """Decode heavy sources off-thread, then adopt validated records as one undoable import."""

    changed = Signal()
    imported = Signal(object)

    def __init__(self, host: "MainWindowViewModel") -> None:
        """Bind the active project owner and a single bounded import worker."""
        super().__init__(host)
        self.host = host
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.job: LibraryJob | None = None
        self.error = ""
        self.busy = False
        self.alive = True

    def submit(
        self,
        operation: str,
        arguments: dict[str, Any],
        root: Path,
        asset_roots: tuple[Path, ...],
        *,
        on_adopt: Callable[[DocumentService, dict[str, Any]], None] | None = None,
    ) -> None:
        """Capture source identity before decoding to preserve subsequent editor changes."""
        if self.busy:
            return
        document = self.host.documents
        baseline = document.project
        if baseline is None:
            self.error = "Create or open a project before importing media."
            self.changed.emit()
            return
        snapshot = document.fork()
        self.busy, self.error = True, ""

        def load() -> tuple[Any, Any]:
            """Use the public canonical operations against a scratch document with source roots."""
            api = RigoraAPI(root, asset_roots=asset_roots, document=snapshot)
            return snapshot, api.execute(operation, arguments).data

        def complete(result: tuple[Any, Any]) -> None:
            """Adopt the worker's assets/scene only on the owning GUI thread and source identity."""
            if not self.alive:
                return
            self.busy, self.job = False, None
            try:
                if document not in self.host.workspace.documents:
                    raise ProjectError("Import cancelled because its project tab was closed.")
                with document.command_group("Import object resources"):
                    AssetPipeline(document).adopt(result[0], baseline)
                    if on_adopt:
                        on_adopt(document, result[1])
            except ProjectError as error:
                self.error = str(error)
            else:
                self.error = ""
                self.host.changed.emit()
                self.imported.emit(result[1])
            self.changed.emit()

        def failed(message: str) -> None:
            """Keep original records untouched and expose an actionable import error."""
            if self.alive:
                self.busy, self.job, self.error = False, None, message
                self.changed.emit()

        job = self.job = LibraryJob(load)
        job.signals.done.connect(complete)
        job.signals.failed.connect(failed)
        self.pool.start(job)
        self.changed.emit()

    def close(self) -> None:
        """Prevent late worker completion from publishing into a closed application."""
        self.alive = False
        self.pool.clear()
