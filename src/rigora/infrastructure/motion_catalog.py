"""Original portable skeletons and smooth, rest-relative motion presets for reusable rigs."""

import math
from dataclasses import dataclass, replace
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from rigora.domain.content import ContentItem
from rigora.domain.entities import Bone, Skeleton
from rigora.domain.illustration_catalog import design_by_id
from rigora.domain.rig_roots import rooted_skeleton
from rigora.infrastructure.illustration_motion import (
    Joint,
    local_transforms,
    offset,
    world_joints,
)


def identity(value: str) -> str:
    """Give generated data stable identities independent of cache location and generation time."""
    return str(uuid5(NAMESPACE_URL, "rigora/creative-library/v1/" + value))


def item(name: str, kind: Any, category: str, payload: dict[str, Any], **extra: Any) -> ContentItem:
    """Describe original reusable data and retain its authoring provenance."""
    return ContentItem(
        id=identity(category + "/" + name),
        name=name,
        kind=kind,
        category=category,
        author="Rigora contributors",
        license="CC0-1.0",
        payload=payload,
        description=extra.pop(
            "description",
            "Original editable Rigora preset. Drag onto a compatible object or into empty space.",
        ),
        tags=tuple(extra.pop("tags", ("original", "editable"))),
        extra=extra,
    )


def skeleton_item(name: str, joints: dict[str, Joint], anatomy: str) -> ContentItem:
    """Encode an anatomical joint graph as editable bones with explicit semantic identities."""
    ids = {key: identity(name + "/" + key) for key in joints}
    local = local_transforms(joints)
    rig = Skeleton(
        id=identity(name + "/rig"),
        name=name,
        bones=tuple(
            Bone(
                id=ids[key],
                name=key,
                parent_id=ids.get(j.parent or ""),
                length=j.length,
                transform=local[key],
            )
            for key, j in joints.items()
        ),
        extra={
            "anatomy": anatomy,
            "semantic_mapping": ids,
            "template_family": anatomy,
            "library_bind": (1, 0, 0, 1, 0, 0),
        },
    )
    points = [point for joint in joints.values() for point in (joint.root, joint.tip)]
    primary = next(joint for joint in joints.values() if joint.parent is None)
    rig = rooted_skeleton(rig, position=primary.root)
    bounds = [
        min(p[0] for p in points),
        min(p[1] for p in points),
        max(p[0] for p in points),
        max(p[1] for p in points),
    ]
    return item(
        name,
        "rig",
        "Skeleton templates",
        {"skeleton": rig.to_dict(), "rig_bounds": bounds, "object_template": True},
        description=(
            "Editable bones with a selectable Object container. Drop onto artwork "
            "to add the rig, or into empty space to create an empty Object."
        ),
        source_format="RIG",
    )


def chain_joints(count: int = 5, *, length: float = 32, angle: float = 90) -> dict[str, Joint]:
    """Create a connected flexible chain with one independently editable root."""
    result = {}
    root = (0.0, -count * length / 2)
    for index in range(count):
        key = f"chain.{index}"
        tip = offset(root, angle, length)
        result[key] = Joint(f"chain.{index - 1}" if index else None, root, tip)
        root = tip
    return result


def skeletons() -> tuple[ContentItem, ...]:
    """Supply biped, quadruped, wing, hand and flexible-bone templates without artwork."""
    human = world_joints(design_by_id("nova"), "Side", rest=True)
    values = [
        skeleton_item("Human · full body", human, "human"),
        skeleton_item(
            "Human · simple",
            {k: j for k, j in human.items() if k not in ("cloth", "hair.back", "hair.front")},
            "human",
        ),
        skeleton_item(
            "Child · full body",
            world_joints(replace(design_by_id("nova"), body=60, leg=38, arm=29), "Side", rest=True),
            "human",
        ),
    ]
    for design, name in (
        ("sumi", "Quadruped · cat"),
        ("ember", "Quadruped · fox"),
        ("clover", "Quadruped · rabbit"),
    ):
        values.append(
            skeleton_item(
                name,
                world_joints(design_by_id(design), "Side", rest=True),
                design_by_id(design).anatomy,
            )
        )
    wings = {"body": Joint(None, (0, 25), (0, -35)), "head": Joint("body", (0, -35), (0, -62))}
    for side, sign in (("L", -1), ("R", 1)):
        shoulder, elbow, tip = (sign * 8, -30), (sign * 60, -45), (sign * 100, -25)
        wings["wing." + side] = Joint("body", shoulder, elbow)
        wings["wing.tip." + side] = Joint("wing." + side, elbow, tip)
    values.append(skeleton_item("Bird · wings", wings, "bird"))
    for count, name in ((3, "Flexible spine"), (5, "Hair / tail chain"), (8, "Rope / tentacle")):
        values.append(skeleton_item(name, chain_joints(count), "chain"))
    hand = {"palm": Joint(None, (0, 35), (0, 0))}
    for index, finger in enumerate(("thumb", "index", "middle", "ring", "little")):
        root = ((index - 2) * 13.0, 0.0)
        for joint in range(3):
            finger_tip = offset(
                root, -120 if finger == "thumb" else -90, 17 if finger == "middle" else 14
            )
            key = f"{finger}.{joint}"
            hand[key] = Joint("palm" if joint == 0 else f"{finger}.{joint - 1}", root, finger_tip)
            root = finger_tip
    values.append(skeleton_item("Hand · five fingers", hand, "hand"))
    return tuple(values)


@dataclass(frozen=True)
class Gait:
    """Define choreography independently of artwork, with fixed limb lengths and periodic motion."""

    name: str
    stride: float = 45
    energy: float = 1
    lean: float = 0
    bounce: float = 0
    arm: float = 1
    head: float = 0
    frames: int = 48


WALKS = (
    Gait("Natural"),
    Gait("Relaxed", 35, 0.7, -1, 0.5, 0.6, 1, 60),
    Gait("Brisk", 54, 1.15, 1, 1, 1.15, 0.5, 36),
    Gait("Confident", 49, 1.05, -2, 1.3, 1.2, 1, 48),
    Gait("Sneak", 27, 0.45, 7, 0, 0.35, 2, 64),
    Gait("Heavy", 39, 1.2, 2, 2.5, 0.8, 2, 58),
    Gait("Funny strut", 60, 1.35, -4, 4, 1.65, 3, 50),
    Gait("Bouncy cartoon", 43, 1.1, -1, 5, 1.4, 3, 42),
    Gait("Anime stroll", 37, 0.75, -1, 0.4, 0.65, 0.5, 54),
    Gait("Anime determined", 53, 1.1, 2, 1, 1.15, 0, 40),
)
RUNS = (
    Gait("Jog", 42, 0.8, 2, 1, 0.8, 1, 32),
    Gait("Natural", 58, 1.1, 4, 2, 1, 1, 26),
    Gait("Sprint", 69, 1.3, 8, 3, 1.2, 0.5, 20),
    Gait("Heavy", 43, 1.2, 5, 4, 0.8, 2, 32),
    Gait("Funny dash", 63, 1.35, -2, 5, 1.6, 3, 24),
    Gait("Cartoon hurry", 55, 1.2, 5, 4, 1.4, 2, 22),
    Gait("Anime dash", 67, 1.1, 9, 1.5, 0.18, 0, 22),
    Gait("Anime heroic", 62, 1.15, 5, 2, 1.2, 0.5, 24),
)


def turn_branch(joints: dict[str, Joint], key: str, degrees: float) -> None:
    """Rotate a connected branch rigidly, retaining all segment lengths and joint connections."""
    pivot = joints[key].root
    angle = math.radians(degrees)

    def rotate(point: tuple[float, float]) -> tuple[float, float]:
        """Rotate a point about the selected branch's original base."""
        x, y = point[0] - pivot[0], point[1] - pivot[1]
        return pivot[0] + math.cos(angle) * x - math.sin(angle) * y, pivot[1] + math.sin(
            angle
        ) * x + math.cos(angle) * y

    for name, joint in tuple(joints.items()):
        ancestor: str | None = name
        while ancestor and ancestor != key:
            ancestor = joints[ancestor].parent
        if ancestor == key:
            joints[name] = replace(joint, root=rotate(joint.root), tip=rotate(joint.tip))


def gait_joints(profile: Gait, action: str, phase: float) -> dict[str, Joint]:
    """Author smooth style variations with secondary head/arm motion and consistent joins."""
    d = replace(design_by_id("nova"), stride=profile.stride, energy=profile.energy)
    joints = world_joints(d, "Side", action, phase)
    p = math.tau * phase
    turn_branch(joints, "spine", profile.lean)
    turn_branch(joints, "head", profile.head * math.sin(p - 0.25))
    for index, side in enumerate(("R", "L")):
        swing = (
            (36 if action == "Run" else 18) * profile.energy * math.cos(p + index * math.pi - 0.14)
        )
        turn_branch(joints, "upper_arm." + side, swing * (profile.arm - 1))
        if profile.name == "Anime dash":
            turn_branch(joints, "upper_arm." + side, -35)
            turn_branch(joints, "forearm." + side, 34)
    from rigora.infrastructure.illustration_motion import two_link

    ankles = {}
    required = []
    for index, side in enumerate(("R", "L")):
        q = p + index * math.pi
        sign = -1 if index == 0 else 1
        ankle = (
            joints["foot." + side].root
            if action == "Run"
            else (
                sign * d.width * 0.15 * 0.55 + d.stride * 0.48 * math.cos(q),
                -12 - d.leg * 0.13 * max(0, -math.sin(q)) ** 2,
            )
        )
        ankles[side] = ankle
        dx = ankle[0] - joints["thigh." + side].root[0]
        required.append(ankle[1] - math.sqrt((d.leg * 2 * 0.997) ** 2 - dx * dx))

    # Smooth maxima retain reachability without velocity corners as support changes sides.
    def upper(a: float, b: float) -> float:
        """Smoothly choose a reachable hip height without a support-switch velocity corner."""
        return (a + b + math.sqrt((a - b) ** 2 + 0.05**2)) / 2

    hip_y = joints["hips"].root[1]
    shift = upper(hip_y + profile.bounce * (1 - math.cos(p * 2)), upper(*required)) - hip_y
    for name, joint in tuple(joints.items()):
        if name.startswith(("thigh.", "shin.", "foot.")):
            continue
        joints[name] = replace(
            joint,
            root=(joint.root[0], joint.root[1] + shift),
            tip=(joint.tip[0], joint.tip[1] + shift),
        )
    for side in ("R", "L"):
        upper_leg, lower_leg = joints["thigh." + side], joints["shin." + side]
        root = (upper_leg.root[0], upper_leg.root[1] + shift)
        knee, ankle = two_link(root, ankles[side], upper_leg.length, lower_leg.length)
        joints["thigh." + side] = replace(upper_leg, root=root, tip=knee)
        joints["shin." + side] = replace(lower_leg, root=knee, tip=ankle)
        foot = joints["foot." + side]
        joints["foot." + side] = replace(
            foot, root=ankle, tip=offset(ankle, foot.angle, foot.length)
        )
    return joints


def motion_item(
    name: str,
    category: str,
    rest: dict[str, Joint],
    poses: list[dict[str, Joint]],
    frames: float,
    *,
    anatomy: str = "human",
    loop: bool = True,
) -> ContentItem:
    """Bake normalized FK deltas; target rigs retain their own rest poses and limb lengths."""
    baseline = local_transforms(rest)
    samples = [local_transforms(pose) for pose in poses]
    channels = []
    for bone, transform in baseline.items():
        for axis in ("rotation", "x", "y") if rest[bone].parent is None else ("rotation",):
            values = []
            previous = 0.0
            for index, sample in enumerate(samples):
                value = getattr(sample[bone], axis) - getattr(transform, axis)
                if axis == "rotation":
                    value = (value + 180) % 360 - 180
                    if index:
                        value = previous + (value - previous + 180) % 360 - 180
                values.append([index * frames / (len(samples) - 1), value])
                previous = value
            if (
                max(v[1] for v in values) - min(v[1] for v in values) < 1e-7
                and abs(values[0][1]) < 1e-7
            ):
                continue
            channels.append(
                {
                    "semantic": bone,
                    "path": axis,
                    "keys": values,
                    "optional": bone.startswith(("hair.", "cloth", "ear.", "tail")),
                }
            )
    return item(
        name,
        "action",
        category,
        {
            "anatomy": anatomy,
            "channels": channels,
            "duration": frames,
            "fps": 30,
            "loop": loop,
            "relative": True,
            "reference_leg_length": 104,
            "fallback_rig": "human" if anatomy == "human" else anatomy,
        },
        source_format="ANIM",
        tags=("motion", "editable", anatomy, name.casefold()),
        description=(
            "Rest-relative, editable skeletal animation. Drag onto a rig; empty "
            "space creates a rigged empty Object. Timing follows the scene FPS."
        ),
    )


def motions() -> tuple[ContentItem, ...]:
    """Build diverse locomotion, gestures and animal cycles as ordinary portable keyframes."""
    d = design_by_id("nova")
    rest = world_joints(d, "Side", rest=True)
    result = []
    for action, profiles in (("Walk", WALKS), ("Run", RUNS)):
        for profile in profiles:
            result.append(
                motion_item(
                    profile.name + " · " + action,
                    "Human walks" if action == "Walk" else "Human runs",
                    rest,
                    [gait_joints(profile, action, i / 48) for i in range(49)],
                    profile.frames,
                )
            )
    for action, frames in (
        ("Stand", 120),
        ("Idle", 150),
        ("Jump", 35),
        ("Hop", 24),
        ("High jump", 60),
        ("Crouch", 48),
        ("Stretch", 90),
        ("Wave", 78),
        ("Bow", 72),
        ("Cheer", 84),
        ("Point", 70),
    ):
        result.append(
            motion_item(
                action,
                "Human idle & stand" if action in ("Stand", "Idle") else "Gestures & actions",
                rest,
                [world_joints(d, "Side", action, i / 48) for i in range(49)],
                frames,
                loop=action in ("Stand", "Idle"),
            )
        )
    for key, species in (("sumi", "Cat"), ("ember", "Fox"), ("clover", "Rabbit")):
        animal = design_by_id(key)
        source = world_joints(animal, "Side", rest=True)
        for action, frames in (
            ("Walk", animal.walk_frames),
            ("Run", animal.run_frames),
            ("Idle", 120),
            ("Jump", 54),
        ):
            result.append(
                motion_item(
                    species + " · " + action,
                    "Animal motions",
                    source,
                    [world_joints(animal, "Side", action, i / 48) for i in range(49)],
                    frames,
                    anatomy=animal.anatomy,
                    loop=action != "Jump",
                )
            )
    return tuple(result)
