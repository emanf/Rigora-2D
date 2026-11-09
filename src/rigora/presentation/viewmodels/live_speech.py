"""Bounded PCM delivery and offline speech worker lifecycle on the GUI thread."""

from contextlib import suppress
from queue import Empty, Full, Queue
from threading import Event

from PySide6.QtCore import QObject, QThreadPool, QTimer, Signal

from rigora.domain.project import ProjectError
from rigora.infrastructure.live_speech import LivePhonemes, SpeechSample
from rigora.presentation.viewmodels.content_library import LibraryJob


class LiveSpeech(QObject):
    """Decode microphone copies asynchronously; the caller owns device and document changes."""

    sample = Signal(object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, parent: QObject) -> None:
        """Create a dormant recognizer and no device/model resources."""
        super().__init__(parent)
        self.job: LibraryJob | None = None
        self.inputs: Queue[bytes | None] = Queue(20)
        self.outputs: Queue[SpeechSample] = Queue(1)
        self.cancel = Event()
        self.accepting = False
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.poll)

    def start(self, rate: int) -> None:
        """Begin loading/decoding on one worker after an explicit Record action."""
        if self.job:
            raise ProjectError("Wait for the previous speech worker to finish.")
        self.inputs, self.outputs, self.cancel = Queue(20), Queue(1), Event()
        self.accepting = True
        inputs, outputs, cancel = self.inputs, self.outputs, self.cancel

        def decode() -> SpeechSample | None:
            """Keep all decoder operations on one thread and close it on every exit path."""
            decoder = LivePhonemes(rate)
            try:
                while not cancel.is_set():
                    try:
                        data = inputs.get(timeout=0.1)
                    except Empty:
                        continue
                    if data is None:
                        return decoder.close()
                    result = decoder.feed(data)
                    if outputs.full():
                        with suppress(Empty):
                            outputs.get_nowait()
                    outputs.put_nowait(result)
            finally:
                decoder.close()
            return None

        self.job = LibraryJob(decode)
        self.job.signals.done.connect(self.completed)
        self.job.signals.failed.connect(self.worker_failed)
        QThreadPool.globalInstance().start(self.job)
        self.timer.start()

    def feed(self, data: bytes, rate: int) -> None:
        """Retain at most two seconds of PCM; overload stops instead of corrupting cue timing."""
        if not self.accepting:
            return
        try:
            for offset in range(0, len(data), rate // 10 * 2):
                self.inputs.put_nowait(data[offset : offset + rate // 10 * 2])
        except Full:
            self.error("Live phoneme recognition fell behind. Audio is retained; stop and keep it.")

    def poll(self) -> None:
        """Publish only the latest provisional result without backlogging preview frames."""
        try:
            result = self.outputs.get_nowait()
        except Empty:
            return
        if not self.cancel.is_set():
            self.sample.emit(result)

    def stop(self, *, keep: bool = False) -> None:
        """Drain queued PCM for a kept take, or cooperatively cancel discarded inference."""
        self.accepting = False
        if not keep:
            self.cancel.set()
            self.timer.stop()
        elif self.job:
            try:
                self.inputs.put_nowait(None)
            except Full:
                self.error(
                    "Live phoneme queue is full. Audio remains available to keep separately."
                )

    def completed(self, result: object) -> None:
        """Release the worker and deliver final cues only for a retained, uncancelled take."""
        self.job = None
        self.timer.stop()
        self.accepting = False
        if not self.cancel.is_set() and isinstance(result, SpeechSample):
            self.finished.emit(result)

    def error(self, message: str) -> None:
        """Cancel recognition and surface an error without discarding captured audio."""
        self.stop()
        self.failed.emit(message)

    def worker_failed(self, message: str) -> None:
        """Permit a fresh session only after the failed model worker has actually closed."""
        self.job = None
        self.error(message)
