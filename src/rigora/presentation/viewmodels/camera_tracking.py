"""Explicit Qt camera ownership with single-frame queues and an offline detector worker."""

import time
from contextlib import suppress
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event

from PySide6.QtCore import QObject, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import (
    QCamera,
    QMediaCaptureSession,
    QMediaDevices,
    QVideoFrame,
    QVideoSink,
)

from rigora.application_services.tracking import TrackingSample
from rigora.domain.project import ProjectError
from rigora.infrastructure.camera_tracking import LocalTracker
from rigora.presentation.viewmodels.content_library import LibraryJob


class CameraCapture(QObject):
    """Own explicit camera capture with bounded latency and one-frame input/result queues."""

    sample = Signal(object)
    changed = Signal()

    def __init__(self, parent: QObject) -> None:
        """Create dormant queues and a result timer without constructing a camera."""
        super().__init__(parent)
        self.camera: QCamera | None = None
        self.session: QMediaCaptureSession | None = None
        self.sink: QVideoSink | None = None
        self.job: LibraryJob | None = None
        self.cancel, self.ready = Event(), Event()
        self.inputs: Queue[tuple[QImage, float]] = Queue(1)
        self.results: Queue[TrackingSample] = Queue(1)
        self.active, self.error, self.device_id = False, "", ""
        self.clock, self.last_frame = 0.0, -1.0
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.poll)

    def start(self, face: Path | None, body: Path | None, device_id: str = "") -> None:
        """Load selected models off-thread before opening the explicitly selected camera."""
        if self.job:
            raise ProjectError("Wait for the previous camera worker to finish.")
        self.cancel, self.ready = Event(), Event()
        self.inputs, self.results = Queue(1), Queue(1)
        self.device_id, self.error, self.active = device_id, "", True
        self.clock, self.last_frame = time.monotonic(), -1

        def detect() -> None:
            """Own model creation, inference and closure on one worker thread."""
            import numpy as np

            detector = LocalTracker(face, body)
            try:
                self.ready.set()
                while not self.cancel.is_set():
                    try:
                        image, seconds = self.inputs.get(timeout=0.1)
                    except Empty:
                        continue
                    pixels = (
                        np.frombuffer(image.constBits(), dtype=np.uint8)
                        .reshape(image.height(), image.bytesPerLine())[:, : image.width() * 3]
                        .reshape(image.height(), image.width(), 3)
                    )
                    result = detector.detect(pixels, seconds)
                    if not self.cancel.is_set():
                        self.replace_latest(self.results, result)
            finally:
                detector.close()

        self.job = LibraryJob(detect)
        self.job.signals.done.connect(self.completed)
        self.job.signals.failed.connect(self.worker_failed)
        QThreadPool.globalInstance().start(self.job)
        self.timer.start()
        self.changed.emit()

    @staticmethod
    def replace_latest[T](queue: Queue[T], value: T) -> None:
        """Keep one fresh frame/result while allowing a slower consumer to skip stale input."""
        try:
            queue.put_nowait(value)
        except Full:
            with suppress(Empty):
                queue.get_nowait()
            with suppress(Full):
                queue.put_nowait(value)

    def poll(self) -> None:
        """Open hardware after model readiness and publish the latest result on the GUI thread."""
        if not self.active:
            return
        if self.ready.is_set() and self.camera is None:
            devices = QMediaDevices.videoInputs()
            device = next(
                (d for d in devices if bytes(d.id().data()).hex() == self.device_id),
                QMediaDevices.defaultVideoInput() if not self.device_id else None,
            )
            if device is None or device.isNull():
                self.failed("Selected camera is unavailable. Choose another input.")
                return
            self.camera = QCamera(device, self)
            self.camera.errorOccurred.connect(
                lambda *args: self.failed(
                    self.camera.errorString() if self.camera else "Camera stopped."
                )
            )
            self.session, self.sink = QMediaCaptureSession(self), QVideoSink(self)
            self.session.setCamera(self.camera)
            self.session.setVideoSink(self.sink)
            self.sink.videoFrameChanged.connect(self.frame_ready)
            self.camera.start()
        try:
            result = self.results.get_nowait()
        except Empty:
            return
        self.sample.emit(result)

    def frame_ready(self, frame: QVideoFrame) -> None:
        """Copy at most fifteen 640-pixel RGB frames per second into owned image bytes."""
        seconds = time.monotonic() - self.clock
        if not self.active or seconds - self.last_frame < 1 / 15:
            return
        image = frame.toImage()
        if image.isNull():
            return
        image = image.scaled(640, 480, Qt.AspectRatioMode.KeepAspectRatio).convertToFormat(
            QImage.Format.Format_RGB888
        )
        self.last_frame = seconds
        self.replace_latest(self.inputs, (image.copy(), seconds))

    def stop(self) -> None:
        """Immediately release hardware and request cooperative model shutdown."""
        self.active = False
        self.timer.stop()
        self.cancel.set()
        if self.camera:
            self.camera.stop()
            self.camera.deleteLater()
        for owned in (self.sink, self.session):
            if owned:
                owned.deleteLater()
        self.camera, self.session, self.sink = None, None, None
        self.changed.emit()

    def completed(self, _result: object) -> None:
        """Release the worker after its native models close."""
        self.job = None
        self.stop()

    def failed(self, message: str) -> None:
        """Retain an actionable failure while releasing any active hardware."""
        self.error = message
        self.stop()

    def worker_failed(self, message: str) -> None:
        """Release the completed worker separately from a camera's asynchronous error signal."""
        self.job = None
        self.failed(message)
