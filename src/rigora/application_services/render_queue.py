"""Bounded single-worker render queue with owned snapshots, progress and safe cancellation."""

import copy
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from rigora.application_services.documents import DocumentService
from rigora.application_services.output import OutputService, OutputSettings, RenderCancelled
from rigora.domain.project import ProjectError


@dataclass
class RenderJob:
    """Worker state guarded by the queue lock, independent of source documents."""

    id: str = field(default_factory=lambda: str(uuid4()))
    status: str = "queued"
    completed: int = 0
    total: int = 0
    project_name: str = ""
    format: str = ""
    error: str = ""
    result: dict[str, Any] | None = None
    cancel: threading.Event = field(default_factory=threading.Event)
    future: Future[None] | None = None


class RenderQueue:
    """Serialize expensive output jobs while allowing nonblocking inspection and cancellation."""

    def __init__(self) -> None:
        """Create one lazy executor and a bounded history with no GUI or cloud dependency."""
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rigora-render")
        self.jobs: dict[str, RenderJob] = {}
        self.closed = False

    def submit(
        self, document: DocumentService, service: OutputService, path: str, settings: OutputSettings
    ) -> dict[str, Any]:
        """Fork on the owning caller thread so later editor changes cannot alter queued output."""
        with self.lock:
            if self.closed:
                raise ProjectError("The render queue has been closed.")
            active = {"queued", "rendering", "encoding", "publishing"}
            if sum(j.status in active for j in self.jobs.values()) >= 16:
                raise ProjectError("The render queue supports at most 16 active jobs.")
            for key in tuple(self.jobs):
                if len(self.jobs) < 32:
                    break
                if self.jobs[key].status not in active:
                    del self.jobs[key]
            snapshot = document.fork()
            job = RenderJob(
                total=len(settings.frames),
                project_name=document.project.name if document.project else "Project",
                format=settings.format,
            )
            self.jobs[job.id] = job

            def progress(completed: int, total: int) -> None:
                """Publish counters under the queue lock after each fully rendered frame."""
                with self.lock:
                    job.completed, job.total = completed, total

            def phase(status: str) -> None:
                """Commit to publication atomically with the cancellation decision."""
                with self.lock:
                    if job.cancel.is_set():
                        raise RenderCancelled("Render cancelled before output publication.")
                    job.status = status

            def run() -> None:
                """Keep errors and completion owned by one job without touching GUI objects."""
                try:
                    result = service.export(
                        snapshot, path, settings, cancel=job.cancel, progress=progress, phase=phase
                    )
                except RenderCancelled as error:
                    with self.lock:
                        job.status, job.error = "cancelled", str(error)
                except Exception as error:
                    with self.lock:
                        job.status = "failed"
                        job.error = (
                            str(error)
                            if isinstance(error, ProjectError)
                            else "Render failed; check output permissions and supported formats."
                        )
                else:
                    with self.lock:
                        job.status, job.result = "completed", result

            job.future = self.executor.submit(run)
            return self.inspect(job.id)

    def inspect(self, job_id: str | None = None) -> dict[str, Any]:
        """Return owned JSON-safe state for one job or the bounded queue history."""
        with self.lock:
            if job_id is None:
                return {"jobs": [self.inspect(key) for key in self.jobs]}
            if job_id not in self.jobs:
                raise ProjectError("Render job is not part of this session.")
            job = self.jobs[job_id]
            return {
                "job_id": job.id,
                "project_name": job.project_name,
                "format": job.format,
                "status": job.status,
                "completed": job.completed,
                "total": job.total,
                "error": job.error,
                "result": copy.deepcopy(job.result),
                "can_cancel": job.status in ("queued", "rendering", "encoding"),
            }

    def cancel(self, job_id: str) -> dict[str, Any]:
        """Cancel queued or rendering work; publication and completed outputs remain intact."""
        with self.lock:
            state = self.inspect(job_id)
            if state["can_cancel"]:
                job = self.jobs[job_id]
                job.cancel.set()
                if job.future and job.future.cancel():
                    job.status = "cancelled"
            return self.inspect(job_id)

    def close(self, *, wait: bool = True) -> None:
        """Cancel unfinished work and release the owned worker without holding its state lock."""
        with self.lock:
            if self.closed:
                return
            self.closed = True
            for key in self.jobs:
                self.cancel(key)
        self.executor.shutdown(wait=wait, cancel_futures=True)
