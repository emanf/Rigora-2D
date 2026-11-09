"""Qt transport presentation over the same animation service used by headless evaluation."""

import time
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from rigora.application_services.animation import AnimationSession
from rigora.application_services.documents import DocumentService
from rigora.domain.project import ProjectError
from rigora.presentation.viewmodels.audio_playback import AudioPlayback


class PlaybackViewModel(QObject):
    """Refresh playback from elapsed time without rebuilding document widgets per frame."""

    changed = Signal()
    event_fired = Signal(object)

    def __init__(self, parent: QObject, clock: Callable[[], float] = time.monotonic) -> None:
        """Own a display timer and injectable monotonic clock."""
        super().__init__(parent)
        self.clock = clock
        self.document: DocumentService | None = None
        self.session: AnimationSession | None = None
        self.error = ""
        self.speed = 1.0
        self.snap = True
        self.cache_enabled = True
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.tick)
        self._last_time = clock()
        self.audio = AudioPlayback(self)
        self.changed.connect(self.sync_audio)

    def sync_audio(self) -> None:
        """Keep audible clip playback aligned with every transport operation."""
        self.audio.sync_frame(
            self.document if self.session else None,
            self.session.playback.frame if self.session else 0,
            bool(self.session and self.session.playback.is_playing),
            self.speed,
        )

    def bind(self, document: DocumentService | None) -> None:
        """Select a document runtime, pausing its predecessor while retaining each tab's frame."""
        try:
            session = document.animation if document is not None else None
            error = ""
        except ProjectError as failure:
            session, error = None, str(failure)
        if document is self.document and session is self.session and error == self.error:
            return
        self.timer.stop()
        if self.session is not None:
            self.session.pause()
            self.session.pose_cache.clear()
        self.document, self.session, self.error = document, session, error
        if session is not None:
            session.cache_enabled = self.cache_enabled
        self.changed.emit()

    def _apply(self, operation: Callable[[AnimationSession], object]) -> None:
        """Publish a transport operation or retain an actionable evaluation error."""
        if self.session is None:
            return
        try:
            operation(self.session)
            self.error = ""
        except ProjectError as failure:
            self.timer.stop()
            self.session.pause()
            self.error = str(failure)
        self.changed.emit()

    def play_pause(self) -> None:
        """Toggle playback and sample elapsed monotonic time independently of timer jitter."""
        if self.session is not None and self.session.playback.is_playing:
            self.pause()
            return
        self._apply(lambda session: session.play())
        if self.session is not None and self.session.playback.is_playing:
            self._last_time = self.clock()
            self.timer.start()
        else:
            self.timer.stop()

    def pause(self, *, snap: bool | None = None) -> None:
        """Hold an editable frame; use ``snap=False`` for previews that must retain exact time."""
        self.timer.stop()

        def hold(session: AnimationSession) -> None:
            """Snap only the stopped cursor; continuous playback keeps subframe precision."""
            session.pause()
            frame = session.playback.frame
            if (self.snap if snap is None else snap) and frame != round(frame):
                session.seek(round(frame))

        self._apply(hold)

    def stop(self) -> None:
        """Stop the timer and return the active clip to its first frame."""
        self.timer.stop()
        self._apply(lambda session: session.stop())

    def seek(self, frame: float) -> None:
        """Pause and seek from a frame field, slider or navigation control."""
        self.timer.stop()
        if self.session is not None:
            self.session.pause()
        self._apply(lambda session: session.seek(frame))

    def step(self, offset: int) -> None:
        """Move a whole-frame interval relative to the displayed position."""
        if self.session is not None:
            self.seek(self.session.playback.frame + offset)

    def seek_start(self) -> None:
        """Pause on the first displayed frame."""
        if self.session is not None:
            self.seek(self.session.playback.range.start)

    def seek_end(self) -> None:
        """Pause on the inclusive last displayed frame."""
        if self.session is not None:
            self.seek(self.session.playback.range.end)

    def toggle_loop(self) -> None:
        """Toggle the active session's loop preference without dirtying the project."""
        self._apply(lambda session: session.set_loop(not session.playback.loop))

    def select_clip(self, clip_id: str) -> None:
        """Switch to an independently validated clip and allow recovery from an unsupported clip."""
        if self.document is None:
            return
        self.timer.stop()
        if self.session is not None:
            self.session.pause()
        try:
            self.document.select_animation_clip(clip_id)
            self.bind(self.document)
        except ProjectError as failure:
            self.error = str(failure)
            self.changed.emit()

    def tick(self) -> None:
        """Advance by measured elapsed seconds and stop scheduling when playback finishes."""
        now = self.clock()
        elapsed, self._last_time = max(0.0, now - self._last_time), now
        self._apply(lambda session: session.advance(elapsed * self.speed))
        session = self.session
        if session:
            for event in session.last_events:
                self.event_fired.emit(event.to_dict(fps=session.playback.range.fps))
        if self.session is None or not self.session.playback.is_playing:
            self.timer.stop()
