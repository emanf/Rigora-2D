"""Background project persistence and periodic recovery over immutable document revisions."""

from contextlib import suppress
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QEventLoop, QObject, QThreadPool, QTimer, Signal

from rigora.application_services.documents import DocumentService
from rigora.application_services.recovery import RecoveryEntry, RecoveryStore
from rigora.domain.project import ProjectError
from rigora.presentation.viewmodels.content_library import LibraryJob

if TYPE_CHECKING:
    from rigora.presentation.viewmodels.main_window import MainWindowViewModel


class ProjectIOViewModel(QObject):
    """Serialize disk work off-thread and adopt results only on the workspace owner."""

    message = Signal(str)
    changed = Signal()
    open_error = Signal(object, str)

    def __init__(self, host: "MainWindowViewModel") -> None:
        """Own a single I/O worker, active destination guards and two-minute recovery cadence."""
        super().__init__(host)
        self.host = host
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.store = RecoveryStore(host.preferences.path.parent / "recovery")
        self.jobs: dict[str, LibraryJob] = {}
        self.destinations: set[Path] = set()
        self.errors: dict[str, str] = {}
        self.checkpointed: dict[str, object] = {}
        self.alive = True
        self.timer = QTimer(self)
        self.timer.setInterval(120000)
        self.timer.timeout.connect(self.checkpoint)
        self.timer.start()

    def save(
        self, document: DocumentService, path: Path | None, *, overwrite: bool = False
    ) -> bool:
        """Queue one revision, rejecting concurrent writes to its document or destination."""
        key = "save:" + document.session_id
        try:
            if key in self.jobs:
                raise ProjectError("This project is already being saved.")
            request = document.prepare_save(path, overwrite=overwrite)
            if request.destination in self.destinations or any(
                d is not document and d.path == request.destination
                for d in self.host.workspace.documents
            ):
                raise ProjectError(
                    "This destination is already open or being saved in another tab."
                )
        except (ProjectError, OSError) as error:
            self.errors[key] = str(error)
            self.message.emit(str(error))
            return False
        self.errors.pop(key, None)
        self.destinations.add(request.destination)
        job = LibraryJob(request.write)
        self.jobs[key] = job

        def finished(checksum: str) -> None:
            """Mark only the written revision saved, even when editing continued during I/O."""
            self.jobs.pop(key, None)
            self.destinations.discard(request.destination)
            if not self.alive:
                return
            try:
                document.complete_save(request, checksum)
                self.host.preferences.add_recent(request.destination)
                if not document.dirty:
                    self.store.remove(document.session_id)
                self.host.changed.emit()
                self.message.emit(
                    "Project saved" + (" · newer edits remain unsaved" if document.dirty else "")
                )
            except (ProjectError, OSError) as error:
                self.errors[key] = str(error)
                self.message.emit(str(error))
            self.changed.emit()

        def failed(error: str) -> None:
            """Retain dirty work and an actionable error without terminating another queued job."""
            self.jobs.pop(key, None)
            self.destinations.discard(request.destination)
            self.errors[key] = error
            if self.alive:
                self.message.emit("Save failed: " + error)
                self.changed.emit()

        job.signals.done.connect(finished)
        job.signals.failed.connect(failed)
        self.pool.start(job)
        self.message.emit("Saving project…")
        self.changed.emit()
        return True

    def wait_saved(self, document: DocumentService) -> bool:
        """Keep Qt responsive while a close/save decision waits for its captured revision."""
        key = "save:" + document.session_id
        loop = QEventLoop()
        poll = QTimer()
        poll.setInterval(15)
        poll.timeout.connect(lambda: loop.quit() if key not in self.jobs else None)
        if key in self.jobs:
            poll.start()
            loop.exec()
            poll.stop()
        return key not in self.errors and not document.dirty

    def open(
        self,
        path: Path,
        state: dict[str, Any] | None = None,
        *,
        background: bool = False,
        recovery: bool = False,
    ) -> None:
        """Load and validate independently; opening never replaces the active document's data."""
        key = "open:" + str(path.resolve())
        if key in self.jobs:
            return

        def load() -> DocumentService:
            """Deserialize project/assets and restore its cursor entirely on the worker."""
            document = DocumentService()
            if recovery:
                document.recover(path)
            else:
                document.open(path)
            assert document.project is not None
            if state:
                if state.get("scene") in {s.id for s in document.project.scenes}:
                    document.select_scene(state["scene"])
                clip = state.get("clip")
                if clip and clip in {c.id for c in document.context_clips()}:
                    document.select_animation_clip(clip)
                with suppress(ProjectError):
                    document.animation.seek(float(state.get("frame", 0)))
            return document

        def opened(document: DocumentService) -> None:
            """Adopt the loaded session through the canonical workspace on its owning thread."""
            self.jobs.pop(key, None)
            if not self.alive:
                return
            active = self.host.workspace.active
            self.host.workspace.adopt(document)
            if background and active is not None:
                self.host.workspace.activate(self.host.workspace.documents.index(active))
            if not background:
                self.host.welcome_selected = False
                self.host.welcome_open = False
            if not recovery:
                self.host.preferences.add_recent(path.resolve())
            self.host.changed.emit()
            self.message.emit("Project opened")
            self.changed.emit()

        job = LibraryJob(load)
        self.jobs[key] = job
        job.signals.done.connect(opened)
        job.signals.failed.connect(lambda error: self.failed_open(key, path, error, background))
        self.pool.start(job)
        self.message.emit("Opening project…")
        self.changed.emit()

    def open_failed(self, key: str, error: str) -> None:
        """Keep the workspace intact when a background project cannot be opened."""
        self.jobs.pop(key, None)
        if self.alive:
            self.message.emit("Open failed: " + error)
            self.changed.emit()

    def failed_open(self, key: str, path: Path, error: str, background: bool) -> None:
        """Retain the native backup-recovery choice for explicit opens without startup dialogs."""
        self.open_failed(key, error)
        if self.alive and not background:
            self.open_error.emit(path, error)

    def checkpoint(self) -> None:
        """Schedule changed dirty revisions, keeping live authoring state off the worker."""
        if not self.alive:
            return
        active_ids = {d.session_id for d in self.host.workspace.documents}
        self.checkpointed = {k: v for k, v in self.checkpointed.items() if k in active_ids}
        for document in self.host.workspace.documents:
            key = "recovery:" + document.session_id
            if (
                not document.dirty
                or key in self.jobs
                or self.checkpointed.get(document.session_id) is document.project
            ):
                continue
            try:
                scratch, path = self.store.prepare(document)
            except ProjectError:
                continue
            source = document.project
            job = LibraryJob(partial(self.store.write, scratch, path))
            self.jobs[key] = job
            job.signals.done.connect(
                lambda _, d=document, k=key, s=source: self.checkpoint_done(d, k, s)
            )
            job.signals.failed.connect(
                lambda error, k=key: self.open_failed(k, "Recovery: " + error)
            )
            self.pool.start(job)
        records = [
            {
                "path": str(d.path),
                "scene": d.scene.id,
                "frame": d.cursor_frame,
                "clip": d.selected_clip_id if not d.animation_context else None,
            }
            for d in self.host.workspace.documents
            if d.path
        ]
        if "session" not in self.jobs:
            job = LibraryJob(lambda: self.store.write_session(records))
            self.jobs["session"] = job
            job.signals.done.connect(lambda _: self.jobs.pop("session", None))
            job.signals.failed.connect(lambda error: self.open_failed("session", error))
            self.pool.start(job)

    def checkpoint_done(self, document: DocumentService, key: str, source: object) -> None:
        """Retain the captured identity; a newer edit will be checkpointed on the next cadence."""
        self.jobs.pop(key, None)
        if document in self.host.workspace.documents:
            self.checkpointed[document.session_id] = source
        if document not in self.host.workspace.documents or not document.dirty:
            self.checkpointed.pop(document.session_id, None)
            try:
                self.store.remove(document.session_id)
            except OSError as error:
                if self.alive:
                    self.message.emit("Recovery cleanup: " + str(error))
        if self.alive:
            self.changed.emit()

    def recover(self, entry: RecoveryEntry) -> None:
        """Restore a selected recovery package on the worker without overwriting its original."""
        key = "restore:" + str(entry.path)
        if key in self.jobs:
            return
        job = LibraryJob(lambda: self.store.restore(entry))
        self.jobs[key] = job

        def restored(document: DocumentService) -> None:
            """Expose the recovered project as a separate unsaved tab."""
            self.jobs.pop(key, None)
            if self.alive:
                self.host.workspace.adopt(document)
                self.host.welcome_selected = False
                self.host.welcome_open = False
                self.host.changed.emit()
                self.message.emit("Work recovered as an unsaved project · Use Save As")
                self.changed.emit()

        job.signals.done.connect(restored)
        job.signals.failed.connect(lambda error: self.open_failed(key, error))
        self.pool.start(job)
        self.changed.emit()

    def close(self) -> None:
        """Finish writes and discard this run's checkpoints after a confirmed clean exit."""
        if not self.alive:
            return
        self.timer.stop()
        self.alive = False
        self.pool.waitForDone()
        try:
            self.store.write_session(
                [
                    {
                        "path": str(d.path),
                        "scene": d.scene.id,
                        "frame": d.cursor_frame,
                        "clip": d.selected_clip_id if not d.animation_context else None,
                    }
                    for d in self.host.workspace.documents
                    if d.path
                ]
            )
            for document in self.host.workspace.documents:
                self.store.remove(document.session_id)
        except (OSError, ProjectError) as error:
            self.errors["session"] = str(error)
