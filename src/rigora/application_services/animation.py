"""Shared animation operations used by Python, CLI and GUI adapters."""

from collections.abc import Mapping
from copy import copy
from time import perf_counter

from rigora.domain.project import Scene
from rigora.engine.constraints import ConstraintSolver
from rigora.engine.deformation import DeformationPlan, DeformerSolver
from rigora.engine.evaluation import SceneEvaluator
from rigora.engine.game_events import GameEvent, crossed_events, scene_events
from rigora.engine.playback import PlaybackController
from rigora.engine.pose_cache import PoseCache
from rigora.engine.sampling import EvaluationError, TrackSampler
from rigora.engine.springs import SpringCursor
from rigora.engine.state import ScenePose


class AnimationSession:
    """Own one compiled scene and transient playback/pose state without modifying project data."""

    def __init__(
        self,
        scene: Scene,
        clip_id: str | None = None,
        *,
        solvers: Mapping[str, ConstraintSolver] | None = None,
        deformers: Mapping[str, DeformerSolver] | None = None,
        samplers: Mapping[str, TrackSampler] | None = None,
        frame: float | None = None,
        select_first_clip: bool = True,
        scope: frozenset[str] | None = None,
        local_object: str | None = None,
        deformation_plan: DeformationPlan | None = None,
    ) -> None:
        """Prepare the selected or first clip and evaluate its initial frame."""
        self.scene = scene
        self.solvers = dict(solvers or {})
        self.deformers = dict(deformers or {})
        self.samplers = dict(samplers or {})
        self.evaluator = SceneEvaluator(
            scene,
            clip_id,
            solvers=self.solvers,
            deformers=self.deformers,
            samplers=self.samplers,
            select_first_clip=select_first_clip,
            scope=scope,
            local_object=local_object,
            deformation_plan=deformation_plan,
        )
        self.playback = PlaybackController(
            self.evaluator.range, loop=self.evaluator.clip.loop if self.evaluator.clip else False
        )
        if frame is not None:
            self.playback.seek(frame)
        self.pose_cache = PoseCache()
        self.cache_enabled = False
        self.last_evaluation_ms = 0.0
        self.runtime_events = scene_events(scene, self.evaluator.clip)
        self.last_events: tuple[GameEvent, ...] = ()
        self._event_start_pending = False
        self.pose = self.evaluate(self.playback.frame, loop=self.playback.loop)

    def evaluate(
        self, frame: float, *, loop: bool = False, visible_only: bool = False
    ) -> ScenePose:
        """Evaluate a frame without changing the transport or the most recently displayed pose."""
        started = perf_counter()
        key = (id(self.evaluator), frame, loop, visible_only)
        cached = self.pose_cache.get(key) if self.cache_enabled else None
        if cached is not None:
            self.last_evaluation_ms = (perf_counter() - started) * 1000
            return cached
        pose = self.evaluator.evaluate(frame, loop=loop, visible_only=visible_only)
        if self.cache_enabled:
            self.pose_cache.put(key, pose)
        self.last_evaluation_ms = (perf_counter() - started) * 1000
        return pose

    def fork(self) -> "AnimationSession":
        """Share compiled source/pose with independent stopped transport and spring memory."""
        scratch = copy(self)
        scratch.pose_cache = PoseCache(self.pose_cache.limit)
        scratch.cache_enabled = False
        scratch.last_events = ()
        scratch._event_start_pending = False
        scratch.solvers, scratch.deformers, scratch.samplers = (
            dict(self.solvers),
            dict(self.deformers),
            dict(self.samplers),
        )
        if self.evaluator.springs:
            scratch.evaluator = copy(self.evaluator)
            scratch.evaluator.spring_cursor = SpringCursor()
        scratch.playback = PlaybackController(self.playback.range, loop=self.playback.loop)
        scratch.playback.seek(self.playback.frame)
        return scratch

    def select_clip(self, clip_id: str) -> None:
        """Switch clips only after the new evaluator and its initial pose validate successfully."""
        selected = AnimationSession(
            self.scene,
            clip_id,
            solvers=self.solvers,
            deformers=self.deformers,
            samplers=self.samplers,
            scope=self.evaluator.scope,
            local_object=self.evaluator.local_object,
        )
        self.evaluator, self.playback, self.pose = (
            selected.evaluator,
            selected.playback,
            selected.pose,
        )
        self.pose_cache.clear()
        self.runtime_events, self.last_events = selected.runtime_events, ()
        self._event_start_pending = False

    def seek(self, frame: float) -> ScenePose:
        """Publish a direct seek only after the requested pose has evaluated successfully."""
        target = self.playback.range.normalize(frame)
        pose = self.evaluate(target, loop=self.playback.loop)
        self.playback.seek(target)
        self.pose = pose
        self.last_events = ()
        self._event_start_pending = False
        return pose

    def play(self) -> None:
        """Begin or resume playback and refresh a possible end-to-start restart."""
        was_playing = self.playback.is_playing
        self.playback.play()
        if not was_playing and self.playback.frame == self.playback.range.start:
            self._event_start_pending = True
        self.pose = self.evaluate(self.playback.frame, loop=self.playback.loop)

    def pause(self) -> None:
        """Suspend playback at the current evaluated frame."""
        self.playback.pause()
        self._event_start_pending = False

    def stop(self) -> ScenePose:
        """Stop and evaluate the range start."""
        self.playback.stop()
        self.last_events = ()
        self._event_start_pending = False
        self.pose = self.evaluate(self.playback.frame, loop=self.playback.loop)
        return self.pose

    def set_loop(self, enabled: bool) -> None:
        """Change the session's loop preference without editing the stored clip default."""
        self.playback.loop = enabled

    def advance(self, seconds: float, *, visible_only: bool = False) -> ScenePose:
        """Advance time, optionally skipping hidden meshes; pause and roll back on failure."""
        previous = self.playback.frame
        candidate = previous + seconds * self.playback.range.fps
        occurrences = (
            crossed_events(
                self.runtime_events,
                previous - 1e-9 if self._event_start_pending and seconds > 0 else previous,
                candidate,
                start=self.playback.range.start,
                duration=self.playback.range.duration_frames,
                loop=self.playback.loop,
            )
            if self.playback.is_playing
            else ()
        )
        self.last_events = ()
        self.playback.advance(seconds)
        if self.playback.frame != previous:
            try:
                self.pose = self.evaluate(
                    self.playback.frame, loop=self.playback.loop, visible_only=visible_only
                )
            except EvaluationError:
                self.playback.frame = previous
                self.playback.pause()
                raise
        self.last_events = occurrences
        if seconds > 0:
            self._event_start_pending = False
        return self.pose
