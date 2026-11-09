"""Background video conversion and review ownership, with stale-result and close guards."""

import contextlib
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, QThreadPool, QTimer, Signal

from rigora.application_services.video_rig import VideoAnalysis, VideoRigService
from rigora.domain.project import ProjectError
from rigora.infrastructure.video_keying import KeyingSettings, key_cutout
from rigora.infrastructure.video_models import check_cancel, install_models, model_directory
from rigora.infrastructure.video_rig import analyze_images, analyze_video, image_frame, video_frame
from rigora.presentation.viewmodels.content_library import LibraryJob

if TYPE_CHECKING:
    from rigora.presentation.viewmodels.main_window import MainWindowViewModel


class VideoRigViewModel(QObject):
    """Keep native model/decoder work off the GUI and publish only explicitly reviewed results."""

    changed = Signal()
    frame_ready = Signal(object, int)
    created = Signal(object)

    def __init__(self, host: "MainWindowViewModel") -> None:
        """Capture the owning workspace, leaving all devices, downloads and decoders dormant."""
        super().__init__(host)
        self.host = host
        self.directory = model_directory()
        self.path: Path | None = None
        self.images: tuple[Path, ...] = ()
        self.start = 0.0
        self.analysis: VideoAnalysis | None = None
        self.output: dict[str, Any] | None = None
        self.keyed_reference: tuple[tuple[str, KeyingSettings], bytes] | None = None
        self.busy, self.alive, self.error = False, True, ""
        self.progress, self.message = 0.0, "Choose a clip to begin."
        self.cancel = Event()
        self.job: LibraryJob | None = None
        self.frame_job: LibraryJob | None = None
        self.frame_index, self.frame_requested = -1, -1
        self.frame_generation = 0
        self.updates: Queue[tuple[float, str]] = Queue(1)
        self.timer = QTimer(self)
        self.timer.setInterval(80)
        self.timer.timeout.connect(self.poll)

    def report(self, value: float, message: str) -> None:
        """Retain one fresh progress message instead of flooding the GUI event queue."""
        with contextlib.suppress(Empty):
            self.updates.get_nowait()
        with contextlib.suppress(Full):
            self.updates.put_nowait((value, message))

    def poll(self) -> None:
        """Marshal the latest worker progress into GUI-owned presentation fields."""
        try:
            self.progress, self.message = self.updates.get_nowait()
        except Empty:
            return
        self.changed.emit()

    def run(self, operation: Callable[[], Any], complete: Callable[[Any], None]) -> None:
        """Run one cancellable operation, ignoring late completions after dialog teardown."""
        if self.busy or not self.alive:
            return
        self.cancel = Event()
        self.updates = Queue(1)
        self.busy, self.error, self.progress = True, "", 0

        def done(value: Any) -> None:
            """Complete on the GUI thread only when the owning operation is still accepted."""
            if not self.alive:
                return
            self.busy, self.job = False, None
            self.timer.stop()
            self.poll()
            try:
                check_cancel(self.cancel)
                complete(value)
            except (ProjectError, ValueError, OSError) as error:
                self.error = str(error)
            self.changed.emit()

        def failed(message: str) -> None:
            """Release worker state without committing any partially analyzed project."""
            if self.alive:
                self.busy, self.job, self.error = False, None, message
                self.timer.stop()
                self.changed.emit()

        self.job = job = LibraryJob(operation)
        job.signals.done.connect(done)
        job.signals.failed.connect(failed)
        QThreadPool.globalInstance().start(job)
        self.timer.start()
        self.changed.emit()

    def install(self) -> None:
        """Download verified model files only after the explicit Install models action."""
        self.message = "Installing local human and animal models…"

        def installed(_: Any) -> None:
            """Report readiness without automatically analyzing or mutating a project."""
            self.progress, self.message = 1, "Models ready. Analysis now works offline."

        self.run(
            lambda: install_models(self.directory, cancel=self.cancel, progress=self.report),
            installed,
        )

    def analyze(self, path: Path, **settings: Any) -> None:
        """Analyze explicit source settings and retain the immutable result for review."""
        if self.busy:
            return
        self.path, self.start, self.analysis = path, float(settings.get("start", 0)), None
        self.frame_generation += 1
        self.frame_requested = -1
        self.message = "Loading local pose models…"

        def analyzed(result: VideoAnalysis) -> None:
            """Select the strongest connected reference pose for the initial review."""
            self.analysis = result
            self.output = None
            self.progress = 1
            self.message = (
                f"{result.profile} · {len(result.poses)} poses · {result.poses[-1].seconds:.2f}s"
            )
            self.frame_index = result.reference
            self.frame_ready.emit(result.image, result.reference)

        images = self.images
        if images:
            settings = {k: v for k, v in settings.items() if k not in ("start", "duration")}
        self.run(
            lambda: (
                analyze_images(
                    images, self.directory, cancel=self.cancel, progress=self.report, **settings
                )
                if images
                else analyze_video(
                    path, self.directory, cancel=self.cancel, progress=self.report, **settings
                )
            ),
            analyzed,
        )

    def open_source(self, path: Path) -> None:
        """Decode the initial source frame off-thread without loading any pose models."""
        if self.busy:
            return
        self.path, self.analysis, self.output = path, None, None
        self.images = ()
        self.frame_generation += 1
        self.frame_requested = -1
        self.message = "Reading source preview…"

        def ready(png: bytes) -> None:
            """Show source pixels while keeping analysis an explicit separate action."""
            self.frame_ready.emit(png, -1)
            self.message = "Choose a range and subject, then analyze movement."

        self.run(lambda: video_frame(path, 0), ready)

    def open_images(self, paths: tuple[Path, ...]) -> None:
        """Retain explicit sequence ordering and decode only its first frame for source review."""
        if self.busy or not paths:
            return
        if len(paths) > 3600:
            self.error = "Choose at most 3600 images."
            self.changed.emit()
            return
        self.path, self.images = paths[0], paths
        self.analysis, self.output, self.start = None, None, 0
        self.frame_generation += 1
        self.frame_requested = -1
        self.message = "Reading image preview…"

        def ready(png: bytes) -> None:
            """Keep inference explicit for single images and image sequences alike."""
            self.frame_ready.emit(png, -1)
            self.message = f"{len(paths)} image(s) ready. Choose a subject, then analyze."

        self.run(lambda: image_frame(paths[0]), ready)

    def request_frame(self, index: int) -> None:
        """Coalesce scrubbing to one native decoder job and one latest requested frame."""
        if not self.analysis or not self.path or not self.alive:
            return
        self.frame_requested = min(len(self.analysis.poses) - 1, max(0, index))
        if self.frame_job or self.busy:
            return
        target, generation = self.frame_requested, self.frame_generation
        path, seconds = self.path, self.start + self.analysis.poses[target].seconds
        image_path = self.images[target] if self.images else None

        def done(png: bytes) -> None:
            """Discard superseded frame decodes and immediately serve the newest scrub position."""
            if not self.alive:
                return
            self.frame_job = None
            if generation == self.frame_generation and target == self.frame_requested:
                self.frame_index = target
                self.frame_ready.emit(png, target)
            elif self.analysis and self.frame_requested >= 0:
                self.request_frame(self.frame_requested)

        def failed(message: str) -> None:
            """Expose a broken source link without invalidating already embedded pose data."""
            if self.alive:
                self.frame_job, self.error = None, message
                self.changed.emit()

        self.frame_job = job = LibraryJob(
            lambda: image_frame(image_path) if image_path else video_frame(path, seconds)
        )
        job.signals.done.connect(done)
        job.signals.failed.connect(failed)
        QThreadPool.globalInstance().start(job)

    def key_reference(self, analysis: VideoAnalysis, settings: KeyingSettings) -> bytes:
        """Reuse the exact reviewed keyed PNG when the source, settings and backend match.

        Called only by the serialized operation worker. A single bounded entry
        avoids retaining video frames or keyed variants throughout a long review.
        """
        check_cancel(self.cancel)
        key = (sha256(analysis.image).hexdigest(), settings)
        if self.keyed_reference and self.keyed_reference[0] == key:
            return self.keyed_reference[1]
        image = key_cutout(analysis.image, settings, cancel=self.cancel)
        check_cancel(self.cancel)
        self.keyed_reference = (key, image)
        return image

    def create(
        self,
        name: str,
        confidence: float,
        smoothing: float,
        cutout: bool,
        keying: KeyingSettings | None = None,
    ) -> None:
        """Build off-thread and adopt once if the source scene and revision still match."""
        if not self.analysis or self.busy:
            return
        document = self.host.documents
        if document.project is None:
            self.error = "Create or open a project before converting a video."
            self.changed.emit()
            return
        baseline, context = document.project, document.context_key
        snapshot, analysis = document.fork(), self.analysis
        linking = document._link_objects
        self.message = "Creating editable rig, artwork and keyframes…"

        def build() -> tuple[Any, Any]:
            """Prepare segmentation, skinning, animation and linked-object records off-thread."""
            check_cancel(self.cancel)
            image = self.key_reference(analysis, keying or KeyingSettings()) if cutout else b""
            self.report(0.3, "Building editable bones and motion…")
            check_cancel(self.cancel)
            result = VideoRigService(snapshot).create(
                analysis, name=name, confidence=confidence, smoothing=smoothing, artwork=image
            )
            if linking:
                from rigora.application_services.object_library import synchronize_objects

                assert snapshot.project is not None
                snapshot.project = synchronize_objects(baseline, snapshot.project)
            snapshot._link_objects = linking
            snapshot.animation.seek(0)
            check_cancel(self.cancel)
            return snapshot, result

        def adopt(value: tuple[Any, Any]) -> None:
            """Publish into the original active workspace with a single ordinary Undo entry."""
            if self.host.documents is not document or document.context_key != context:
                raise ProjectError(
                    "The active project or scene changed. Create the reviewed rig again."
                )
            prepared, result = value
            document.adopt_prepared(prepared, baseline, "Convert media to rig")
            self.host.changed.emit()
            self.host.scene.select((str(result["object_id"]),))
            self.progress = 1
            self.output = result
            self.message = (
                f"Created {result['bones']} editable bones and {result['samples']} poses. "
                "Undo is available."
            )
            self.created.emit(result)

        self.run(build, adopt)

    def close(self) -> None:
        """Cancel at the next safe boundary and prohibit late publication into a closed dialog."""
        self.alive = False
        self.cancel.set()
        self.keyed_reference = None
        self.timer.stop()
        self.frame_generation += 1
