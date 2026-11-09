"""Original full-body action choreography expressed as reusable rest-relative bone data."""

import math
from dataclasses import dataclass, replace

from rigora.domain.content import ContentItem
from rigora.domain.illustration_catalog import design_by_id
from rigora.infrastructure.illustration_motion import Joint, offset, two_link, world_joints
from rigora.infrastructure.motion_catalog import WALKS, gait_joints, motion_item, turn_branch

type Pose = dict[str, float]


@dataclass(frozen=True)
class Action:
    """Own cosine-eased local pose beats, timing and optional planted-foot crouching."""

    name: str
    category: str
    poses: tuple[Pose, ...]
    frames: int = 72
    loop: bool = False
    planted: bool = True


def arms(left: float, right: float, elbows: float = -35, **extra: float) -> Pose:
    """Describe both shoulders and elbows without changing wrist sockets or limb lengths."""
    return {
        "upper_arm.L": left,
        "upper_arm.R": right,
        "forearm.L": elbows,
        "forearm.R": elbows,
        **extra,
    }


def actions() -> tuple[Action, ...]:
    """Provide independently staged interactions, combat, social, dance and movement actions."""
    neutral: Pose = {}
    raised = arms(-150, -150, -15)
    guard = arms(-50, -60, -70)
    return (
        Action(
            "Push",
            "Work & interactions",
            (arms(-65, -65, -20), arms(-85, -85, 0, spine=12), arms(-65, -65, -20)),
            90,
            True,
        ),
        Action(
            "Pull",
            "Work & interactions",
            (arms(-85, -85, 0, spine=8), arms(-35, -35, -90, spine=-9), arms(-85, -85, 0, spine=8)),
            90,
            True,
        ),
        Action(
            "Lift a box",
            "Work & interactions",
            (neutral, arms(-40, -40, -20, spine=20, **{"@y": 30}), arms(-65, -65, -70), neutral),
            108,
        ),
        Action(
            "Carry a box",
            "Work & interactions",
            (arms(-40, -40, -75), arms(-44, -44, -78, head=2), arms(-40, -40, -75)),
            120,
            True,
        ),
        Action(
            "Throw",
            "Work & interactions",
            (neutral, arms(20, -170, -65, spine=-12), arms(-15, -80, 0, spine=16), neutral),
            66,
        ),
        Action(
            "Catch",
            "Work & interactions",
            (neutral, arms(-90, -90, -10), arms(-45, -45, -100, spine=-5), neutral),
            72,
        ),
        Action(
            "Pick up",
            "Work & interactions",
            (neutral, arms(-20, -40, -10, spine=38, **{"@y": 22}), arms(-45, -45, -80), neutral),
            105,
        ),
        Action(
            "Open a door",
            "Work & interactions",
            (neutral, arms(-15, -75, -12), arms(-15, -30, -80, spine=-4), neutral),
            90,
        ),
        Action(
            "Jab",
            "Combat & reactions",
            (guard, {**guard, "upper_arm.R": -85, "forearm.R": 5, "spine": 7}, guard),
            30,
        ),
        Action(
            "Cross punch",
            "Combat & reactions",
            (guard, {**guard, "upper_arm.L": -90, "forearm.L": 0, "spine": 12}, guard),
            36,
        ),
        Action(
            "Uppercut",
            "Combat & reactions",
            (
                guard,
                {**guard, "@y": 17, "spine": 12},
                {**guard, "upper_arm.R": -150, "forearm.R": -70, "spine": -4},
                guard,
            ),
            45,
        ),
        Action(
            "Front kick",
            "Combat & reactions",
            (
                guard,
                {**guard, "thigh.R": -75, "shin.R": 65},
                {**guard, "thigh.R": -90, "shin.R": 0, "spine": -8},
                guard,
            ),
            48,
            planted=False,
        ),
        Action(
            "High kick",
            "Combat & reactions",
            (
                guard,
                {**guard, "thigh.L": -100, "shin.L": 65},
                {**guard, "thigh.L": -135, "shin.L": 5, "spine": -10},
                guard,
            ),
            54,
            planted=False,
        ),
        Action(
            "Sword slash",
            "Combat & reactions",
            (neutral, arms(-20, -175, -45, spine=-8), arms(-20, -45, -5, spine=16), neutral),
            60,
        ),
        Action(
            "Dodge", "Combat & reactions", (guard, {**guard, "spine": -22, "@y": 28}, guard), 42
        ),
        Action(
            "Hit reaction",
            "Combat & reactions",
            (neutral, arms(20, 25, -45, spine=-20, head=-15), neutral),
            42,
        ),
        Action(
            "Fall backwards",
            "Combat & reactions",
            (
                neutral,
                arms(-55, -55, -70, spine=-20),
                arms(-30, -20, -40, **{"hips": -90, "@y": 64}),
            ),
            78,
            planted=False,
        ),
        Action(
            "Salute",
            "Social gestures",
            (
                neutral,
                {"upper_arm.R": -125, "forearm.R": -105},
                {"upper_arm.R": -125, "forearm.R": -105},
                neutral,
            ),
            90,
        ),
        Action("Nod yes", "Social gestures", (neutral, {"head": 12}, {"head": -4}, neutral), 60),
        Action(
            "Shake head no",
            "Social gestures",
            (neutral, {"head": -10}, {"head": 10}, {"head": -8}, neutral),
            84,
        ),
        Action(
            "Shrug",
            "Social gestures",
            (neutral, arms(-50, -50, -115, head=-5, spine=-3), neutral),
            90,
        ),
        Action(
            "Clap",
            "Social gestures",
            (arms(-60, -60, -60), arms(-85, -85, -12), arms(-60, -60, -60)),
            36,
            True,
        ),
        Action(
            "Laugh",
            "Social gestures",
            (arms(-25, -30, -70), arms(-30, -35, -80, spine=8, head=9), arms(-25, -30, -70)),
            48,
            True,
        ),
        Action(
            "Talk with hands",
            "Social gestures",
            (
                arms(-15, -25, -40),
                arms(-45, -70, -65, head=4),
                arms(-70, -25, -20, head=-3),
                arms(-15, -25, -40),
            ),
            120,
            True,
        ),
        Action(
            "Stretch overhead",
            "Exercise & poses",
            (neutral, raised, {**raised, "spine": -8, "head": -8}, neutral),
            132,
        ),
        Action(
            "Jumping jacks",
            "Exercise & poses",
            (
                neutral,
                {**raised, "thigh.L": -18, "thigh.R": 18, "shin.L": 0, "shin.R": 0, "@y": -20},
                neutral,
            ),
            42,
            True,
            False,
        ),
        Action(
            "Squat",
            "Exercise & poses",
            (neutral, arms(-85, -85, 0, spine=8, **{"@y": 37}), neutral),
            96,
            True,
        ),
        Action(
            "Sit down",
            "Exercise & poses",
            (neutral, arms(-20, -20, -30, spine=5, **{"@y": 42})),
            84,
        ),
        Action(
            "Stand up",
            "Exercise & poses",
            (arms(-20, -20, -30, spine=5, **{"@y": 42}), neutral),
            84,
        ),
        Action(
            "Side groove",
            "Dance & celebrations",
            (
                arms(-40, -75, -55, spine=-8, head=5),
                arms(-75, -40, -55, spine=8, head=-5),
                arms(-40, -75, -55, spine=-8, head=5),
            ),
            60,
            True,
        ),
        Action(
            "Disco point",
            "Dance & celebrations",
            (
                arms(-20, -160, 0, spine=-6),
                arms(-30, -45, -65, spine=8),
                arms(-20, -160, 0, spine=-6),
            ),
            60,
            True,
        ),
        Action(
            "Victory bounce",
            "Dance & celebrations",
            (raised, {**raised, "@y": -24, "spine": -4}, raised),
            40,
            True,
            False,
        ),
        Action(
            "Balance",
            "Exercise & poses",
            (
                arms(-85, -85, -5, **{"thigh.L": -70, "shin.L": 95}),
                arms(-90, -80, -10, head=5, **{"thigh.L": -73, "shin.L": 98}),
                arms(-85, -85, -5, **{"thigh.L": -70, "shin.L": 95}),
            ),
            120,
            True,
            False,
        ),
        Action(
            "Climb ladder",
            "Jumps & climbing",
            (
                arms(-155, -70, -40, **{"thigh.L": -70, "shin.L": 95}),
                arms(-70, -155, -40, **{"thigh.R": -70, "shin.R": 95}),
                arms(-155, -70, -40, **{"thigh.L": -70, "shin.L": 95}),
            ),
            72,
            True,
            False,
        ),
        Action(
            "Swim crawl",
            "Jumps & climbing",
            (
                arms(-150, 30, -15, **{"hips": -85, "thigh.L": -15, "thigh.R": 15}),
                arms(30, -150, -15, **{"hips": -85, "thigh.L": 15, "thigh.R": -15}),
                arms(-150, 30, -15, **{"hips": -85, "thigh.L": -15, "thigh.R": 15}),
            ),
            66,
            True,
            False,
        ),
    )


def action_pose(action: Action, phase: float) -> dict[str, Joint]:
    """Ease between whole-body pose beats and solve planted legs against unchanged ankles."""
    rest = world_joints(design_by_id("nova"), "Side", rest=True)
    position = phase * (len(action.poses) - 1)
    index = min(len(action.poses) - 2, int(position))
    blend = (1 - math.cos(math.pi * (position - index))) / 2
    left, right = action.poses[index : index + 2]
    values = {
        key: left.get(key, 0) * (1 - blend) + right.get(key, 0) * blend
        for key in left.keys() | right.keys()
    }
    joints = dict(rest)
    for key in rest:
        if key in values:
            turn_branch(joints, key, values[key])
    dx, dy = values.get("@x", 0), values.get("@y", 0)
    if dx or dy:
        joints = {
            key: replace(
                joint,
                root=(joint.root[0] + dx, joint.root[1] + dy),
                tip=(joint.tip[0] + dx, joint.tip[1] + dy),
            )
            for key, joint in joints.items()
        }
    if action.planted and dy:
        for side in ("L", "R"):
            thigh, shin, foot = (joints[key + "." + side] for key in ("thigh", "shin", "foot"))
            knee, ankle = two_link(thigh.root, rest["foot." + side].root, thigh.length, shin.length)
            joints["thigh." + side] = replace(thigh, tip=knee)
            joints["shin." + side] = replace(shin, root=knee, tip=ankle)
            joints["foot." + side] = replace(
                foot, root=ankle, tip=offset(ankle, rest["foot." + side].angle, foot.length)
            )
    return joints


def human_actions() -> tuple[ContentItem, ...]:
    """Bake actions to normal portable channels; no new playback runtime is introduced."""
    rest = world_joints(design_by_id("nova"), "Side", rest=True)
    result = [
        motion_item(
            action.name,
            action.category,
            rest,
            [action_pose(action, i / 48) for i in range(49)],
            action.frames,
            loop=action.loop,
        )
        for action in actions()
    ]
    result.append(
        motion_item(
            "Walk backwards",
            "Human walks",
            rest,
            [gait_joints(WALKS[0], "Walk", 1 - i / 48) for i in range(49)],
            60,
        )
    )
    return tuple(result)
