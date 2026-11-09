"""Parameter-driven animation state machines using the existing live action-layer evaluator."""

import operator
from collections.abc import Mapping
from dataclasses import replace
from typing import Any
from uuid import uuid4

from rigora.application_services.animation_editing import motion_source_end
from rigora.application_services.characters import CharacterService
from rigora.application_services.documents import DocumentService
from rigora.domain.entities import AnimationClip, Timeline, Track
from rigora.domain.project import ProjectError
from rigora.domain.validation import json_copy
from rigora.engine.evaluation import SceneEvaluator
from rigora.engine.sampling import number
from rigora.engine.state import ScenePose

OPERATORS = {
    "==": operator.eq,
    "!=": operator.ne,
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
}


class StateMachineService(CharacterService):
    """Persist finite states/conditions on their Object; preview never rewrites authored actions."""

    def define(
        self,
        owner: str,
        states: list[dict[str, Any]],
        transitions: list[dict[str, Any]],
        parameters: dict[str, Any],
        initial: str,
    ) -> None:
        """Validate finite states, parameters and ordered conditions, then publish one Undo step."""
        motions = {c.id for c in self.motions(owner)}
        if not 1 <= len(states) <= 32 or len(parameters) > 32 or len(transitions) > 128:
            raise ProjectError(
                "State machines support 1–32 states, 32 parameters and 128 transitions."
            )
        names = set()
        for state in states:
            name = state.get("name")
            if (
                not isinstance(name, str)
                or not 1 <= len(name) <= 64
                or name in names
                or name == "*"
                or state.get("clip") not in motions
            ):
                raise ProjectError(
                    "Each state needs a unique name and an action belonging to this Object."
                )
            names.add(name)
            if (
                not 0.01 <= number(state.get("speed", 1)) <= 100
                or type(state.get("loop", True)) is not bool
            ):
                raise ProjectError("State speed must be 0.01–100 and Loop must be boolean.")
        if initial not in names:
            raise ProjectError("Choose an existing initial state.")
        for key, value in parameters.items():
            if not isinstance(key, str) or not 1 <= len(key) <= 64:
                raise ProjectError("Parameters need bounded names.")
            if type(value) is not bool:
                number(value, "State parameter")
        for rule in transitions:
            if (
                rule.get("from") not in names | {"*"}
                or rule.get("to") not in names
                or rule.get("parameter") not in parameters
                or rule.get("operator") not in OPERATORS
            ):
                raise ProjectError(
                    "Transitions need existing states/parameters and a supported comparison."
                )
            if type(parameters[rule["parameter"]]) is bool:
                if type(rule.get("value")) is not bool or rule["operator"] not in ("==", "!="):
                    raise ProjectError("Boolean parameters support ==/!= with boolean values.")
            else:
                number(rule.get("value"), "Transition threshold")
            if not 0 <= number(rule.get("blend", 0)) <= 7200:
                raise ProjectError("Transition blends must be 0–7200 frames.")
        data = json_copy(
            dict(states=states, transitions=transitions, parameters=parameters, initial=initial)
        )
        self.commit(
            "Edit animation state machine", **self._extra_patch(owner, "state_machine", data)
        )


class StateMachinePreview:
    """Own transient parameters/time and reuse canonical source motion windows."""

    def __init__(self, document: DocumentService, owner: str) -> None:
        """Capture original source records; public setters cannot change the authoring document."""
        self.snapshot = document.fork()
        self.owner = owner
        service = CharacterService(self.snapshot)
        definition = service.record(owner).extra.get("state_machine")
        if not isinstance(definition, Mapping) or not definition:
            raise ProjectError("Save a state machine on this Object before previewing.")
        self.definition: Mapping[str, Any] = definition
        self.states = {s["name"]: s for s in self.definition["states"]}
        self.motions = {c.id: c for c in service.motions(owner)}
        self.members = service.members(owner)
        self.parameters = dict(self.definition["parameters"])
        self.current = str(self.definition["initial"])
        self.frame = self.entered = self.blend_end = 0.0
        self.previous: tuple[str, float] | None = None
        self.evaluator: SceneEvaluator | None = None

    def set_parameter(self, name: str, value: float | bool) -> None:
        """Change one runtime input using its saved numeric/boolean type."""
        if name not in self.parameters:
            raise ProjectError("Choose an existing state-machine parameter.")
        if type(self.definition["parameters"][name]) is bool:
            if type(value) is not bool:
                raise ProjectError("This parameter needs a boolean value.")
        else:
            value = number(value)
        self.parameters[name] = value

    def advance(self, seconds: float) -> ScenePose:
        """Evaluate ordered conditions once per step; transitions complete before another starts."""
        seconds = number(seconds)
        if not 0 <= seconds <= 10 or self.frame + seconds * self.snapshot.scene.settings.fps > 1e7:
            raise ProjectError("State preview steps must be 0–10 seconds within the frame budget.")
        if self.previous and self.frame >= self.blend_end:
            self.previous, self.evaluator = None, None
        if self.previous is None:
            for rule in self.definition["transitions"]:
                if (
                    rule["from"] in (self.current, "*")
                    and rule["to"] != self.current
                    and OPERATORS[rule["operator"]](
                        self.parameters[rule["parameter"]], rule["value"]
                    )
                ):
                    self.previous = (self.current, self.entered) if rule.get("blend", 0) else None
                    self.current, self.entered = rule["to"], self.frame
                    self.blend_end = self.frame + rule.get("blend", 0)
                    self.evaluator = None
                    break
        self.frame += seconds * self.snapshot.scene.settings.fps
        return self.pose()

    def pose(self) -> ScenePose:
        """Evaluate live layered actions without executing events or changing authored data."""
        if self.evaluator is None:
            scene = self.snapshot.scene
            timelines = {t.id: t for t in scene.timelines}
            tracks: list[Track] = []
            states = [self.previous] if self.previous else []
            states.append((self.current, self.entered))
            for layer, item in enumerate(states):
                assert item is not None
                name, entered = item
                state = self.states[name]
                source = self.motions[state["clip"]]
                window = dict(
                    id=f"state:{layer}:{name}",
                    character=self.owner,
                    name=name,
                    source=source.id,
                    start=entered,
                    end=1e7,
                    source_start=source.in_frame,
                    source_end=motion_source_end(source),
                    speed=state.get("speed", 1),
                    repeat=state.get("loop", True),
                    layer=layer,
                    fade_in=self.blend_end - self.entered if layer and self.previous else 0,
                )
                tracks.extend(
                    replace(
                        t,
                        id=str(uuid4()),
                        keyframes=tuple(replace(k, id=str(uuid4())) for k in t.keyframes),
                        extra={**t.extra, "motion_window": window},
                    )
                    for t in timelines[source.timeline_id].tracks
                    if t.owner_id in self.members
                )
            timeline = Timeline(name="State machine preview", tracks=tuple(tracks))
            clip = AnimationClip(
                name="State machine preview", timeline_id=timeline.id, out_frame=1e7
            )
            scene = replace(
                scene, timelines=(*scene.timelines, timeline), clips=(*scene.clips, clip)
            )
            self.evaluator = SceneEvaluator(
                scene,
                clip.id,
                solvers=self.snapshot.constraint_solvers,
                deformers=self.snapshot.deformer_solvers,
                samplers=self.snapshot.track_samplers,
                scope=self.snapshot.animation_scope,
                local_object=self.snapshot.animation_context,
            )
        return self.evaluator.evaluate(self.frame)
