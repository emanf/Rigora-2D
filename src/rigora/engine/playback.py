"""Clock-independent transport advanced by explicit elapsed time."""

from typing import Literal

from rigora.engine.sampling import EvaluationError, number
from rigora.engine.time import FrameRange


class PlaybackController:
    """Keep transient transport state without changing authoring records or counting timer ticks."""

    def __init__(self, frame_range: FrameRange, *, loop: bool = False) -> None:
        """Start stopped at the first frame with an explicit loop preference."""
        self.range = frame_range
        self.frame = frame_range.start
        self.loop = loop
        self.state: Literal["stopped", "playing", "paused"] = "stopped"

    @property
    def is_playing(self) -> bool:
        """Report whether elapsed time advances the transport."""
        return self.state == "playing"

    def play(self) -> None:
        """Begin playback, restarting a non-looping clip when positioned at its end."""
        if not self.loop and self.frame >= self.range.end:
            self.frame = self.range.start
        self.state = "playing"

    def pause(self) -> None:
        """Retain the current frame and suspend an active transport."""
        if self.is_playing:
            self.state = "paused"

    def stop(self) -> None:
        """Stop and return to the inclusive range start."""
        self.state, self.frame = "stopped", self.range.start

    def seek(self, frame: float) -> None:
        """Seek directly within displayed frame bounds without altering playback mode."""
        self.frame = self.range.normalize(frame)

    def advance(self, seconds: float) -> float:
        """Advance by nonnegative elapsed seconds, including final-frame hold and loop wrapping."""
        seconds = number(seconds, "Elapsed seconds")
        if seconds < 0:
            raise EvaluationError("Elapsed seconds cannot be negative; seek to move backwards.")
        if self.is_playing:
            candidate = number(self.frame + seconds * self.range.fps, "Playback frame")
            if self.loop:
                self.frame = self.range.normalize(candidate, loop=True)
            elif candidate >= self.range.start + self.range.duration_frames:
                self.frame, self.state = self.range.end, "stopped"
            else:
                self.frame = candidate
        return self.frame
