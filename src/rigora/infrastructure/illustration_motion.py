"""Continuous full-body performances for original bipeds and animal anatomies.

Foot targets and fixed segment lengths define the legs. Body, arms, head, wrists,
ears and hair have independently phased motion; no hand sprites switch in a gait.
The resulting local transforms are baked to ordinary editable Bézier keys.
"""

import math
from dataclasses import dataclass, replace

from rigora.domain.character_recipe import RUN_ACTIONS
from rigora.domain.entities import Transform
from rigora.domain.illustration_catalog import Design
from rigora.infrastructure.run_motion import RUN_STYLES

type Point = tuple[float, float]


def offset(point: Point, angle: float, length: float) -> Point:
    """Advance along a screen-space direction in degrees."""
    a = math.radians(angle)
    return point[0] + math.cos(a) * length, point[1] + math.sin(a) * length


def two_link(root: Point, target: Point, upper: float, lower: float) -> tuple[Point, Point]:
    """Solve a forward-bending leg with constant lengths and a small reach margin."""
    dx, dy = target[0] - root[0], target[1] - root[1]
    distance = max(abs(upper - lower) + 0.01, min(math.hypot(dx, dy), (upper + lower) * 0.998))
    heading = math.atan2(dy, dx)
    angle = math.acos(
        max(
            -1.0,
            min(
                1.0, (upper * upper + distance * distance - lower * lower) / (2 * upper * distance)
            ),
        )
    )
    knee = offset(root, math.degrees(heading - angle), upper)
    foot = (root[0] + distance * math.cos(heading), root[1] + distance * math.sin(heading))
    return knee, foot


@dataclass(frozen=True)
class Joint:
    """A world-space authored segment with an explicit anatomical parent."""

    parent: str | None
    root: Point
    tip: Point

    @property
    def angle(self) -> float:
        """Return the world orientation without imposing any joint-limit correction."""
        return math.degrees(math.atan2(self.tip[1] - self.root[1], self.tip[0] - self.root[0]))

    @property
    def length(self) -> float:
        """Return the invariant authored segment length."""
        return math.dist(self.root, self.tip)


def duration(design: Design, action: str) -> int:
    """Return a design-specific cycle length at thirty frames per second."""
    if style := RUN_STYLES.get(action):
        return max(16, min(48, round(style.frames * design.run_frames / 28)))
    return {
        "Walk": design.walk_frames,
        "Run": design.run_frames,
        "Idle": 150 + round(design.phase * 20),
        "Stand": 120 + round(design.phase * 12),
        "Jump": 35,
        "Hop": 24,
        "High jump": 60,
        "Crouch": 48,
        "Stretch": 90,
        "Wave": 78,
        "Bow": 72,
        "Cheer": 84,
        "Point": 70,
    }[action]


def world_joints(
    design: Design, view: str, action: str = "Stand", phase: float = 0.0, *, rest: bool = False
) -> dict[str, Joint]:
    """Evaluate an anatomy in place, including deterministic periodic secondary movement."""
    style = RUN_STYLES.get(action)
    if design.anatomy in ("cat", "fox", "rabbit"):
        if style:
            return quadruped(
                replace(
                    design, energy=design.energy * style.energy, stride=design.stride * style.stride
                ),
                view,
                "Run",
                phase,
                rest=rest,
                fixed_spine=True,
            )
        if action in ("Hop", "High jump", "Crouch", "Stretch") and not rest:
            return animal_gesture(design, view, action, phase)
        if action in ("Jump", "Wave", "Bow", "Cheer", "Point") and not rest:
            return animal_gesture(design, view, action, phase)
        return quadruped(design, view, action, phase, rest=rest)
    d = replace(design, energy=design.energy * style.energy) if style else design
    running, moving = action in RUN_ACTIONS, action in (*RUN_ACTIONS, "Walk")
    run = None
    jump = None
    jump_scale = 0.55 if action == "Hop" else 1.2 if action == "High jump" else 1
    if action in ("Jump", "Hop", "High jump") and not rest:
        from rigora.infrastructure.jump_motion import jump_sample

        jump = jump_sample(action, phase)
    if running and not rest:
        from rigora.infrastructure.run_motion import run_sample

        run = run_sample(phase, style.reference if style else "base")
    p = phase * math.tau
    gesture = (
        action in ("Jump", "Hop", "High jump", "Crouch", "Stretch", "Wave", "Bow", "Cheer", "Point")
        and not rest
    )
    envelope = math.sin(math.pi * phase) ** 2 if gesture else 0
    side = view in ("Side", "Front 3/4", "Back 3/4")
    spread = d.width * (0.15 if view == "Side" else 0.39)
    bob = (
        0
        if rest
        else (0.8 if running else 0.35 if moving else 0.7)
        * (1 - math.cos(p * 2 if moving else p))
        * d.energy
    )
    sway = (
        0
        if rest
        else math.sin(p + d.phase) * (1.1 if moving else 2.3 if action == "Idle" else 0.45)
    )
    leg_height = 0.945 if running and not rest else 0.965 if moving and not rest else 0.98
    if gesture:
        sway = bob = 0
    if action == "Jump" and gesture:
        bob = d.leg * 1.05 * envelope
    hips = (sway, -2 * d.leg * leg_height - 12 - bob)
    if run is not None:
        hips = (sway * 0.4, -12 - 2 * d.leg * (0.95 + (run["height"] - 1) * 0.1))
        if style:
            hips = (hips[0], hips[1] - style.bob * (1 - math.cos(p * 2)))
    if jump is not None:
        hips = (0, -12 - 2 * d.leg * (0.98 + jump["height"] * jump_scale))
    elif action == "Crouch" and gesture:
        hips = (0, hips[1] + d.leg * 0.65 * envelope)
    lean = (
        0
        if rest
        else (
            (style.lean if style else min(3.0, d.lean * 0.1)) + math.sin(p * 2) * 0.18
            if running
            else 0.25 + math.sin(p * 2) * 0.1
            if moving
            else 0
        )
        if side
        else 0
    )
    torso_angle = -90 + lean
    if gesture:
        lean = {
            "Bow": 34,
            "Point": 6,
            "Wave": -3,
            "Cheer": -3,
            "Jump": 2,
            "Hop": 2,
            "High jump": 3,
            "Crouch": 8,
            "Stretch": -3,
        }[action] * envelope
        torso_angle = -90 + lean
    shoulder = offset(hips, torso_angle, d.body)
    neck = offset(shoulder, torso_angle, 16)
    head_angle = (
        -90
        + (lean * 0.32 if side else 0)
        + (
            0
            if rest
            else math.sin(p - 0.25) * (0.9 if moving else 1.8 if action == "Idle" else 0.35)
        )
    )
    head_tip = offset(neck, head_angle, d.head * 0.9)
    if gesture:
        head_angle = -90 + lean * 0.35
        head_tip = offset(neck, head_angle, d.head * 0.9)
    joints = {
        "hips": Joint(None, hips, offset(hips, 0, 1)),
        "spine": Joint("hips", hips, shoulder),
        "neck": Joint("spine", shoulder, neck),
        "head": Joint("neck", neck, head_tip),
    }
    cloth_angle = 90 + (0 if rest else math.sin(p - 0.5) * (7 if moving else 1.2))
    joints["cloth"] = Joint("hips", hips, offset(hips, cloth_angle, d.leg))
    hair_root = offset(neck, head_angle, d.head * 0.72)
    for name, base, amplitude, lag in (("hair.back", 105, 8, 0.6), ("hair.front", 70, 3.5, 0.35)):
        angle = (
            base
            + lean * 0.25
            + (
                0
                if rest
                else math.sin(p - lag) * (amplitude if moving else amplitude * 0.22) * d.energy
            )
        )
        joints[name] = Joint("head", hair_root, offset(hair_root, angle, d.head * 0.8))
    for index, suffix in enumerate(("R", "L")):
        sign = -1 if index == 0 else 1
        q = p + index * math.pi
        half_width = d.width * (0.25 if view == "Side" else 0.34)
        rectangular = d.body_shape == "Rounded rectangle"
        hip = (hips[0] + sign * half_width * 0.45, hips[1]) if rectangular else hips
        if moving and not rest:
            reach = d.stride * (0.62 if running else 0.48) * (1 if side else 0.35)
            ankle = (
                sign * spread * 0.55 + reach * math.cos(q),
                -12 - (d.leg * 0.28 if running else d.leg * 0.13) * max(0.0, -math.sin(q)) ** 2,
            )
            if running:
                ankle = (ankle[0], ankle[1] - 1.2 * (1 - math.cos(p * 2)))
            if run is not None:
                side_key = suffix.lower()
                stride = min(0.95, max(0.7, d.stride / d.leg))
                lift = max(0, run["height"] - run["foot." + side_key + ".y"])
                if style:
                    stride *= style.stride
                    lift *= style.lift
                ankle = (
                    hip[0]
                    + run["foot." + side_key + ".x"] * d.leg * 2 * stride * (1 if side else 0.35),
                    -12 - lift * d.leg * 1.5,
                )
        else:
            ankle = (sign * spread, -12.0)
        if gesture and action == "Jump":
            ankle = (sign * spread, -12 - d.leg * 1.5 * envelope)
        if jump is not None:
            ankle = (
                sign * spread
                + jump["foot." + suffix.lower() + ".x"] * d.leg * 2 * (1 if side else 0.35),
                -12 - jump["lift." + suffix.lower()] * d.leg * 2 * jump_scale,
            )
        knee, ankle = two_link(hip, ankle, d.leg, d.leg)
        joints["thigh." + suffix] = Joint("hips", hip, knee)
        joints["shin." + suffix] = Joint("thigh." + suffix, knee, ankle)
        foot_angle = (
            0 if rest or not moving else -18 * max(0.0, -math.sin(q)) ** 2 - 6 * math.sin(q)
        )
        if run is not None:
            foot_angle = 65 * math.tanh(run["foot." + suffix.lower()] / 95)
        elif jump is not None:
            foot_angle = 35 * math.tanh(jump["foot." + suffix.lower()] / 60)
        outward = -1 if view in ("Front", "Back") and suffix == "R" else 1
        foot_angle = (180 if outward < 0 else 0) + outward * foot_angle
        joints["foot." + suffix] = Joint("shin." + suffix, ankle, offset(ankle, foot_angle, 20))
        arm_root = offset(shoulder, torso_angle + 180, 9)
        if rectangular:
            arm_root = offset(arm_root, torso_angle + 90, sign * (half_width - 2))
        swing = (
            0
            if rest
            else math.cos(q - 0.14)
            * (
                style.arms
                if style
                else 36
                if running
                else 18
                if moving
                else 3.2
                if action == "Idle"
                else 0.6
            )
            * d.energy
        )
        upper_angle = 90 - sign * (9 if side else 13) + swing + lean
        if action == "Anime run" and not rest:
            upper_angle = 128 + math.cos(q - 0.14) * 8 + lean
        elbow = offset(arm_root, upper_angle, d.arm)
        bend = (
            14
            if rest or not moving
            else (style.elbow if style else 94 if running else 12) + 4 * math.sin(q - 0.15)
        )
        fore_angle = upper_angle - bend if moving and not rest else upper_angle + sign * bend * 0.55
        if gesture:
            upper_angle = 90 - sign * (9 if side else 13)
            fore_angle = upper_angle + sign * 7.7
            target_upper, target_fore = upper_angle, fore_angle
            if action == "Wave" and index == 0:
                target_upper, target_fore = 218, 265 + 16 * math.sin(p * 3)
            elif action in ("Cheer", "Jump", "Hop", "High jump", "Stretch"):
                target_upper = 215 if index == 0 else -35
                target_fore = 240 if index == 0 else -60
            elif action == "Point" and index == 0:
                target_upper, target_fore = -8, 0
            elif action == "Bow":
                target_upper -= 12
                target_fore -= 4
            reach = envelope
            if jump is not None:
                air = max(0, min(1, (jump["lift.r"] + jump["lift.l"]) * 1.5))
                reach = air * air * (3 - 2 * air)
                anticipation = max(0, -jump["height"]) * 45
                upper_angle += anticipation
                fore_angle += anticipation
            upper_angle += (target_upper - upper_angle) * reach
            fore_angle += (target_fore - fore_angle) * reach
            elbow = offset(arm_root, upper_angle, d.arm)
        wrist = offset(elbow, fore_angle, d.arm * 0.88)
        joints["upper_arm." + suffix] = Joint("spine", arm_root, elbow)
        joints["forearm." + suffix] = Joint("upper_arm." + suffix, elbow, wrist)
        hand_angle = fore_angle + (0 if rest else math.sin(q - 0.35) * (8 if moving else 1.5))
        joints["hand." + suffix] = Joint("forearm." + suffix, wrist, offset(wrist, hand_angle, 16))
    return joints


def quadruped(
    d: Design,
    view: str,
    action: str,
    phase: float,
    *,
    rest: bool = False,
    fixed_spine: bool = False,
) -> dict[str, Joint]:
    """Use a species-specific walk, gallop or rabbit hop with a supple spine and tail."""
    p, moving, running = phase * math.tau, action in ("Walk", "Run"), action == "Run"
    bounce = (
        0
        if rest
        else (5 if running else 1.5 if moving else 0.6)
        * (1 - math.cos(p * 2 if moving else p))
        * d.energy
    )
    hips = (-d.body * 0.36, -d.leg * 1.65 - 12 - bounce)
    chest = (
        d.body * 0.35,
        hips[1] - d.width * 0.10 + (0 if rest else math.sin(p - 0.2) * (3 if running else 0.7)),
    )
    if fixed_spine:
        heading = math.degrees(math.atan2(chest[1] - hips[1], chest[0] - hips[0]))
        chest = offset(hips, heading, math.hypot(d.body * 0.71, d.width * 0.1))
    neck = (chest[0] + d.head * 0.23, chest[1] - d.head * 0.35)
    head_tip = offset(
        neck, -12 + (0 if rest else math.sin(p - 0.4) * (3 if moving else 1.2)), d.head * 0.8
    )
    joints = {
        "hips": Joint(None, hips, offset(hips, 0, 1)),
        "spine": Joint("hips", hips, chest),
        "neck": Joint("spine", chest, neck),
        "head": Joint("neck", neck, head_tip),
    }
    for index, suffix in enumerate(("R", "L")):
        depth = -5 if index == 0 else 5
        for front in (False, True):
            root = (chest[0] + depth, chest[1] + 6) if front else (hips[0] + depth, hips[1] + 5)
            if d.anatomy == "rabbit" and running:
                shift = 0 if front else 0.48
            elif running:
                shift = (0.10 * index) + (0 if front else 0.53)
            else:
                shift = index * 0.5 + (0.5 if front else 0)
            q = p + shift * math.tau
            stride = d.stride * (0.82 if running else 0.43)
            foot = (
                root[0] + (stride * math.cos(q) if moving and not rest else 4),
                -6 - (d.leg * 0.6 if running else d.leg * 0.32) * max(0.0, -math.sin(q)) ** 2
                if moving and not rest
                else -6,
            )
            knee, foot = two_link(root, foot, d.leg * 0.92, d.leg * 0.96)
            a, b, c = ("upper_arm.", "forearm.", "hand.") if front else ("thigh.", "shin.", "foot.")
            joints[a + suffix] = Joint("spine" if front else "hips", root, knee)
            joints[b + suffix] = Joint(a + suffix, knee, foot)
            joints[c + suffix] = Joint(
                b + suffix, foot, offset(foot, -9 * math.sin(q) if moving and not rest else 0, 17)
            )
    tail_angle = -155 + (0 if rest else math.sin(p - 0.65) * (14 if moving else 7))
    tail_tip = offset(hips, tail_angle, d.head * 1.4)
    joints["tail"] = Joint("hips", hips, tail_tip)
    joints["tail.tip"] = Joint(
        "tail",
        tail_tip,
        offset(tail_tip, tail_angle - 25 + (0 if rest else math.sin(p - 1.1) * 15), d.head * 0.75),
    )
    for index, suffix in enumerate(("R", "L")):
        root = (neck[0] + index * d.head * 0.34, neck[1] - d.head * 0.5)
        angle = (-112 if d.hair != "lop" else -155) + (
            0 if rest else math.sin(p - 0.3 - index * 0.2) * (9 if moving else 3)
        )
        joints["ear." + suffix] = Joint(
            "head", root, offset(root, angle, d.head * (1.6 if d.anatomy == "rabbit" else 0.72))
        )
    return joints


def animal_gesture(d: Design, view: str, action: str, phase: float) -> dict[str, Joint]:
    """Author a hop, paw greeting or bow without changing any quadruped segment length."""
    joints = quadruped(d, view, "Stand", 0, rest=True)
    amount = math.sin(math.pi * phase) ** 2

    def turn(root: str, angle: float) -> None:
        """Rotate an anatomical branch rigidly around its root joint."""
        pivot = joints[root].root

        def point(p: Point) -> Point:
            """Rotate one world point without changing its distance from the pivot."""
            heading = math.degrees(math.atan2(p[1] - pivot[1], p[0] - pivot[0]))
            return offset(pivot, heading + angle, math.dist(p, pivot))

        for name in tuple(joints):
            ancestor: str | None = name
            while ancestor and ancestor != root:
                ancestor = joints[ancestor].parent
            if ancestor == root:
                joint = joints[name]
                joints[name] = Joint(joint.parent, point(joint.root), point(joint.tip))

    if action in ("Jump", "Hop", "High jump", "Cheer"):
        shift = (
            -d.leg * {"Jump": 1.2, "Hop": 0.65, "High jump": 1.8, "Cheer": 0.65}[action] * amount
        )
        joints = {
            name: Joint(j.parent, (j.root[0], j.root[1] + shift), (j.tip[0], j.tip[1] + shift))
            for name, j in joints.items()
        }
        if action in ("Jump", "Hop", "High jump"):
            for side in ("R", "L"):
                turn("shin." + side, -35 * amount)
                turn("forearm." + side, -22 * amount)
    if action == "Crouch":
        shift = d.leg * 0.45 * amount
        for name, j in tuple(joints.items()):
            if not name.startswith(("thigh.", "shin.", "foot.", "upper_arm.", "forearm.", "hand.")):
                joints[name] = Joint(
                    j.parent, (j.root[0], j.root[1] + shift), (j.tip[0], j.tip[1] + shift)
                )
        for upper, lower, foot in (
            ("thigh.", "shin.", "foot."),
            ("upper_arm.", "forearm.", "hand."),
        ):
            for side in ("R", "L"):
                a, b, c = (joints[k + side] for k in (upper, lower, foot))
                root = (a.root[0], a.root[1] + shift)
                middle, end = two_link(root, c.root, a.length, b.length)
                joints[upper + side] = Joint(a.parent, root, middle)
                joints[lower + side] = Joint(b.parent, middle, end)
                joints[foot + side] = Joint(c.parent, end, offset(end, c.angle, c.length))
    if action == "Stretch":
        turn("spine", -8 * amount)
        turn("head", 17 * amount)
        for side in ("R", "L"):
            turn("upper_arm." + side, -28 * amount)
            turn("forearm." + side, 12 * amount)
    if action in ("Wave", "Point", "Cheer"):
        turn("upper_arm.L", (-120 if action != "Point" else -65) * amount)
        if action == "Wave":
            turn("forearm.L", math.sin(phase * math.tau * 3) * 18 * amount)
    if action == "Bow":
        turn("spine", 19 * amount)
        turn("head", 15 * amount)
    return joints


def local_transforms(joints: dict[str, Joint]) -> dict[str, Transform]:
    """Convert evaluated world segments into canonical FK transforms with fixed lengths."""
    result = {}
    for name, joint in joints.items():
        parent = joints.get(joint.parent or "")
        if parent:
            a = math.radians(-parent.angle)
            dx, dy = joint.root[0] - parent.root[0], joint.root[1] - parent.root[1]
            x, y = math.cos(a) * dx - math.sin(a) * dy, math.sin(a) * dx + math.cos(a) * dy
            angle = (joint.angle - parent.angle + 180) % 360 - 180
        else:
            x, y, angle = *joint.root, joint.angle
        result[name] = Transform(x=x, y=y, rotation=angle)
    return result
