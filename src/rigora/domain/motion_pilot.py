"""Validated, data-only pointer mapping profiles owned by ordinary scene objects."""

from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
from typing import Any

from rigora.domain.project import ProjectError
from rigora.domain.validation import identifier, json_copy


@dataclass(frozen=True, slots=True)
class MotionPilotProfile:
    """Persist 2D mappings in pixels, seconds and pointer distance; retain target ownership."""

    move: bool = True
    move_x: float = 1
    move_y: float = 1
    move_x_axis: str = "X"
    move_y_axis: str = "Y"
    space: str = "World"
    rotate: bool = False
    rotation_gain: float = 0.25
    rotation_axis: str = "X"
    scale: bool = False
    width_gain: float = 0.005
    height_gain: float = 0.005
    width_axis: str = "X"
    height_axis: str = "Y"
    uniform: bool = True
    face: str = "Off"
    forward_angle: float = 0
    turn_smoothness: float = 0.15
    wave_move: bool = False
    wave_x: float = 0
    wave_y: float = 25
    wave_rotate: bool = False
    wave_angle: float = 10
    wave_scale: bool = False
    wave_width: float = 0.05
    wave_height: float = 0.05
    wave_speed: float = 1
    wave_mouse: bool = False
    motion_enabled: bool = False
    motion_clips: tuple[str, ...] = ()
    motion_speed: float = 1
    motion_reverse: bool = False
    motion_in_place: bool = True
    motion_trigger: str = "Automatic"
    delay_mode: str = "None"
    delay_frames: float = 2
    delay_min: int = 0
    delay_max: int = 12
    seed: int = 0
    followers: tuple[str, ...] = ()
    lazy_mouse: float = 0
    cursor_start: str = "Object"
    blend: bool = True
    optimize: bool = True
    tolerance: float = 0.5

    def __post_init__(self) -> None:
        """Reject nonfinite values, malformed axes and unsupported modes at every input boundary."""
        import math

        for field in fields(self):
            value = getattr(self, field.name)
            if type(field.default) is bool and type(value) is not bool:
                raise ProjectError(f"{field.name} must be a boolean.")
            if type(field.default) in (int, float) and (
                type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 100000
            ):
                raise ProjectError(f"{field.name} needs a finite, bounded number.")
        for name in ("move_x_axis", "move_y_axis", "rotation_axis", "width_axis", "height_axis"):
            if getattr(self, name) not in ("X", "Y", "-X", "-Y"):
                raise ProjectError("Pointer mappings use X, Y, -X or -Y.")
        for name, choices in {
            "space": ("World", "Local"),
            "face": ("Off", "Flip", "Turn"),
            "motion_trigger": ("Automatic", "Mouse movement", "Click to play", "Click to loop"),
            "delay_mode": ("None", "Uniform", "Random"),
            "cursor_start": ("Object", "Viewport center"),
        }.items():
            if getattr(self, name) not in choices:
                raise ProjectError(f"Choose a supported {name} mode.")
        if not (
            0 <= self.lazy_mouse <= 10
            and 0 <= self.turn_smoothness <= 10
            and 0 <= self.wave_speed <= 30
            and 0.01 <= self.motion_speed <= 100
            and 0 <= self.delay_frames <= 10000
            and 0 <= self.delay_min <= self.delay_max <= 10000
            and 0.001 <= self.tolerance <= 100
            and all(type(getattr(self, name)) is int for name in ("delay_min", "delay_max", "seed"))
        ):
            raise ProjectError("Motion Pilot timing or optimization settings exceed their ranges.")
        if not isinstance(self.motion_clips, tuple) or len(self.motion_clips) > 8:
            raise ProjectError("Choose at most eight native motion clips.")
        for key in self.motion_clips:
            identifier(key)
        if not isinstance(self.followers, tuple) or len(self.followers) > 127:
            raise ProjectError("A flock supports up to 127 distinct followers.")
        for key in self.followers:
            identifier(key)
        if len(set(self.followers)) != len(self.followers):
            raise ProjectError("A flock supports up to 127 distinct followers.")

    def to_dict(self) -> dict[str, Any]:
        """Encode inert project/profile JSON without runtime capture state."""
        return dict(json_copy(asdict(self)))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MotionPilotProfile":
        """Read an explicit profile schema, rejecting unsupported fields and malformed clips."""
        if not isinstance(value, Mapping) or set(value) - {field.name for field in fields(cls)}:
            raise ProjectError("Unsupported Motion Pilot profile fields.")
        data = dict(value)
        for name in ("motion_clips", "followers"):
            if name in data:
                if not isinstance(data[name], (tuple, list)):
                    raise ProjectError(f"{name} must be a list of identities.")
                data[name] = tuple(data[name])
        return cls(**data)
