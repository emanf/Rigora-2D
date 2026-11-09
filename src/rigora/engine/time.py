"""Inclusive frame ranges and explicit conversion between frame positions and elapsed seconds."""

from dataclasses import dataclass

from rigora.engine.sampling import EvaluationError, number


@dataclass(frozen=True, slots=True)
class FrameRange:
    """Frame positions including the last displayed frame and its one-frame hold interval."""

    start: float
    end: float
    fps: float

    def __post_init__(self) -> None:
        """Reject invalid range ordering, frame rates and unrepresentable duration."""
        for key in ("start", "end", "fps"):
            object.__setattr__(self, key, number(getattr(self, key), key))
        if not 0 <= self.start <= self.end or self.fps <= 0:
            raise EvaluationError(
                "Frame range requires nonnegative ordered bounds and positive fps."
            )
        number(self.end - self.start + 1, "Clip duration")

    @property
    def duration_frames(self) -> float:
        """Return the continuous playback period including the last displayed frame."""
        return self.end - self.start + 1

    @property
    def duration_seconds(self) -> float:
        """Return the playback period in seconds at this scene's frame rate."""
        return self.duration_frames / self.fps

    def seconds_to_frame(self, seconds: float) -> float:
        """Convert elapsed seconds from range start into an absolute timeline frame."""
        return number(self.start + number(seconds, "Seconds") * self.fps, "Converted frame")

    def frame_to_seconds(self, frame: float) -> float:
        """Convert an absolute frame position into elapsed seconds from range start."""
        return number((number(frame, "Frame") - self.start) / self.fps, "Converted seconds")

    def normalize(self, frame: float, *, loop: bool = False) -> float:
        """Clamp for direct seeks or wrap the inclusive playback interval for looping."""
        frame = number(frame, "Frame")
        if loop:
            return self.start + number(frame - self.start, "Frame offset") % self.duration_frames
        return min(self.end, max(self.start, frame))
