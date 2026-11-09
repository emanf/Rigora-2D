"""Motion Pilot interaction states, isolated preview ownership and background record preparation."""

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, QThreadPool, Signal

from rigora.application_services.motion_pilot import MotionPilotSession
from rigora.domain.motion_pilot import MotionPilotProfile
from rigora.domain.project import ProjectError
from rigora.presentation.viewmodels.content_library import LibraryJob

if TYPE_CHECKING:
    from rigora.presentation.viewmodels.main_window import MainWindowViewModel


class MotionPilotViewModel(QObject):
    """Keep pointer input and tool lifecycle separate from widgets and canonical record commands."""

    changed = Signal()

    def __init__(self, model: "MainWindowViewModel", parent: QObject) -> None:
        """Bind existing editor signals; no global listeners or project mutations are installed."""
        super().__init__(parent)
        self.model = model
        self.state = "Idle"
        self.status = "Choose a target, configure mappings, then arm Preview or Record."
        self.session: MotionPilotSession | None = None
        self.owners: tuple[str, ...] = ()
        self.profile = MotionPilotProfile()
        self.recording = False
        self.paused = False
        self.job: LibraryJob | None = None
        self.token: object = object()
        self._committing = False
        model.changed.connect(self.validate_source)
        model.animation_editor.focus_changed.connect(self.validate_source)

    def arm(self, owners: tuple[str, ...], profile: MotionPilotProfile, *, recording: bool) -> None:
        """Arm explicit capture; Space starts without warping the operating-system cursor."""
        self.cancel(quiet=True)
        self.owners, self.profile, self.recording = owners, profile, recording
        self.state = "Record armed" if recording else "Preview armed"
        self.status = "Press Space over the viewport to start; Esc cancels."
        self.changed.emit()

    def start(self, pointer: tuple[float, float], center: tuple[float, float]) -> None:
        """Create an isolated capture at the current playhead and pause normal playback."""
        try:
            self.model.playback.pause()
            self.session = MotionPilotSession(
                self.model.documents,
                self.owners,
                self.profile,
                recording=self.recording,
                pointer=pointer,
                viewport_center=center,
            )
            self.state = "Recording" if self.recording else "Previewing"
            self.paused = False
            self.status = f"{self.state} · Space stops · Esc cancels"
            self.capture(self.session.start, pointer)
        except (ProjectError, ValueError) as error:
            self.cancel(quiet=True)
            self.status = str(error)
        self.changed.emit()

    def update_profile(self, profile: MotionPilotProfile) -> None:
        """Retain past samples while live property changes affect subsequent input frames."""
        self.profile = profile
        if self.session:
            self.session.set_profile(profile)

    def capture(self, frame: float, pointer: tuple[float, float], *, clicked: bool = False) -> None:
        """Publish an isolated pose without changing normal project history."""
        if self.session is None or self.paused or self.state == "Preparing":
            return
        try:
            self.model.animation_editor.preview_pose = self.session.feed(
                frame, pointer, clicked=clicked
            )
            self.model.animation_editor.key_preview_changed.emit()
            self.status = f"{self.state} · {self.session.frame:.2f} fr · Space stops · Esc cancels"
        except (ProjectError, ValueError) as error:
            self.cancel(quiet=True)
            self.status = str(error)
        self.changed.emit()

    def pause(self) -> None:
        """Pause the input clock without adding samples or dropping the pending final pose."""
        if self.session and self.state != "Preparing":
            self.paused = not self.paused
            self.status = "Paused · resume or stop" if self.paused else f"{self.state} · resumed"
            self.changed.emit()

    def stop(self, frame: float, pointer: tuple[float, float]) -> None:
        """Discard previews or prepare a recorded pass with its final sample off-thread."""
        session = self.session
        if session is None:
            self.cancel()
            return
        if not session.recording:
            self.cancel(quiet=True)
            self.status = "Preview stopped; no animation keys were created."
            self.changed.emit()
            return
        try:
            session.feed(
                session.raw_time if self.paused else frame,
                session.pointer if self.paused else pointer,
                final=True,
            )
            self.state = "Preparing"
            self.status = "Preparing editable Motion Pilot keys in the background…"
            self.token = token = object()
            job = LibraryJob(lambda: (token, session, session.prepare_recording()))
            self.job = job
            job.signals.done.connect(self.finish)
            job.signals.failed.connect(lambda message: self.fail(token, message))
            QThreadPool.globalInstance().start(job)
        except (ProjectError, ValueError) as error:
            self.cancel(quiet=True)
            self.status = str(error)
        self.model.animation_editor.clear_key_preview()
        self.changed.emit()

    def finish(self, result: Any) -> None:
        """Adopt unchanged captures once; context switches invalidate pending tokens."""
        token, session, prepared = result
        if token is not self.token:
            return
        self.job = None
        self._committing = True
        try:
            self.model.animation_editor.run(lambda _: session.commit(prepared))
        finally:
            self._committing = False
        self.session = None
        self.state = "Idle"
        self.status = (
            self.model.animation_editor.error
            or "Motion Pilot recorded · edit its keys in the Timeline"
        )
        self.changed.emit()

    def fail(self, token: object, message: str) -> None:
        """Report preparation failures without publishing any partial animation."""
        if token is not self.token:
            return
        self.job = None
        if self.state == "Preparing":
            self.cancel(quiet=True)
            self.status = message
            self.changed.emit()

    def cancel(self, *, quiet: bool = False) -> None:
        """Release preview ownership and pending workers without changing source history."""
        self.token = object()
        if self.session:
            self.model.animation_editor.clear_key_preview()
        self.session = None
        self.state, self.paused = "Idle", False
        if not quiet:
            self.status = "Motion Pilot canceled; source animation is unchanged."
        self.changed.emit()

    def validate_source(self) -> None:
        """Stop stale capture after document edits, deletion or editing-context switches."""
        session = self.session
        if (
            session
            and not self._committing
            and (
                self.model.documents is not session.document
                or session.document.project is not session.original
                or session.document.animation_context != session.context
                or session.document.scene.id != session.scene_id
            )
        ):
            self.cancel()
