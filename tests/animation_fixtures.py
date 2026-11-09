"""Deterministic test-only scene fixtures for animation evaluation and rig solvers."""

from typing import TYPE_CHECKING, Literal
from uuid import NAMESPACE_URL, uuid5

from rigora.domain.entities import (
    AnimationClip,
    Bone,
    Character,
    Constraint,
    Group,
    Keyframe,
    SceneObject,
    Skeleton,
    Timeline,
    Track,
    Transform,
)
from rigora.domain.project import Project, Scene, SceneSettings

if TYPE_CHECKING:
    from rigora.presentation.viewmodels.main_window import MainWindowViewModel


def open_animation_fixture(model: "MainWindowViewModel") -> None:
    """Populate an ordinary new test document through the shared command service."""
    from rigora.application_services.commands import ProjectPatch

    sample = animation_example()
    document = model.workspace.new(sample.name)
    assert document.project is not None
    document.execute(
        ProjectPatch(
            "Load test animation",
            {"scenes": document.project.scenes},
            {"scenes": sample.scenes},
        )
    )
    model.welcome_selected = False
    model.changed.emit()


def _identity(label: str) -> str:
    """Derive reproducible sample UUIDs without relying on user-facing names for references."""
    return str(uuid5(NAMESPACE_URL, f"urn:rigora:animation-example:{label}"))


def _track(
    label: str,
    owner: str,
    path: str,
    values: tuple[tuple[float, float], ...],
    *,
    blend: Literal["override", "additive"] = "override",
    weight: float = 1.0,
    interpolation: Literal["step", "linear", "bezier"] = "bezier",
) -> Track:
    """Build a scalar sample track with stable key identities and explicit blending."""
    return Track(
        id=_identity(label),
        name=label,
        owner_id=owner,
        property_path=path,
        blend_mode=blend,
        weight=weight,
        keyframes=tuple(
            Keyframe(
                id=_identity(f"{label}-{index}"),
                name=f"Key {index + 1}",
                frame=frame,
                value=value,
                interpolation=interpolation,
            )
            for index, (frame, value) in enumerate(values)
        ),
    )


def animation_example() -> Project:
    """Create three animated objects and three hierarchical bones across two reusable clips."""
    group = Group(id=_identity("group"), name="Object group", transform=Transform(x=230, y=180))
    sway = SceneObject(id=_identity("sway"), name="Sway", parent_id=group.id)
    bounce = SceneObject(
        id=_identity("bounce"), name="Bounce", parent_id=group.id, transform=Transform(x=110, y=100)
    )
    pulse = SceneObject(
        id=_identity("pulse"),
        name="Pulse",
        parent_id=group.id,
        transform=Transform(x=210, y=40, pivot_x=12),
    )
    root = Bone(
        id=_identity("root"),
        name="Root",
        length=120,
        transform=Transform(x=520, y=320, rotation=-30),
    )
    middle = Bone(
        id=_identity("middle"),
        name="Middle",
        parent_id=root.id,
        length=90,
        transform=Transform(x=120, rotation=25),
    )
    tip = Bone(
        id=_identity("tip"),
        name="Tip",
        parent_id=middle.id,
        length=70,
        transform=Transform(x=90, rotation=30),
    )
    main = Timeline(
        id=_identity("main-timeline"),
        name="Objects and bones",
        tracks=(
            _track("Group rotation", group.id, "transform.rotation", ((0, -8), (30, 8), (60, -8))),
            _track("Sway X", sway.id, "transform.x", ((0, -40), (30, 50), (60, -40))),
            _track("Sway blend", sway.id, "transform.x", ((0, 20),), weight=0.25),
            _track("Bounce Y", bounce.id, "transform.y", ((0, 100), (30, 25), (60, 100))),
            _track(
                "Pulse scale",
                pulse.id,
                "transform.scale_x",
                ((0, 1), (30, 1.8), (60, 1)),
                blend="additive",
                weight=0.5,
            ),
            _track("Root rotation", root.id, "transform.rotation", ((0, -30), (30, 20), (60, -30))),
            _track(
                "Middle rotation", middle.id, "transform.rotation", ((0, 25), (30, -40), (60, 25))
            ),
            _track("Tip rotation", tip.id, "transform.rotation", ((0, 30), (30, -25), (60, 30))),
        ),
    )
    slow = Timeline(
        id=_identity("slow-timeline"),
        name="Slow arc",
        tracks=(
            _track("Slow group X", group.id, "transform.x", ((0, 230), (60, 300), (120, 230))),
            _track(
                "Slow root rotation",
                root.id,
                "transform.rotation",
                ((0, -30), (60, 80), (120, -30)),
            ),
        ),
    )
    clips = (
        AnimationClip(
            id=_identity("main-clip"),
            name="Objects & bones · 2 seconds",
            timeline_id=main.id,
            out_frame=59,
            loop=True,
        ),
        AnimationClip(
            id=_identity("slow-clip"),
            name="Slow arc · 4 seconds",
            timeline_id=slow.id,
            out_frame=119,
            loop=True,
        ),
    )
    scene = Scene(
        id=_identity("scene"),
        name="Animation study",
        settings=SceneSettings(width=900, height=540, fps=30, end_frame=119),
        groups=(group,),
        objects=(sway, bounce, pulse),
        skeletons=(
            Skeleton(id=_identity("skeleton"), name="Three bone chain", bones=(root, middle, tip)),
        ),
        timelines=(main, slow),
        clips=clips,
        draw_order=(sway.id, bounce.id, pulse.id),
    )
    return Project(id=_identity("project"), name="Animation playground", scenes=(scene,))


def rigging_example() -> Project:
    """Create symmetric IK chains with animated independent targets and stable fixture UUIDs."""
    bones: list[Bone] = []
    targets: list[SceneObject] = []
    constraints: list[Constraint] = []
    tracks: list[Track] = []
    for side, x, angle, sy, bend in (("L", 250, 0, 1, 1), ("R", 650, 180, -1, -1)):
        root = Bone(
            id=_identity(f"rig-root-{side}"),
            name=f"Arm.{side}",
            length=100,
            group="Arms",
            transform=Transform(x=x, y=240, rotation=angle, scale_y=sy),
        )
        child = Bone(
            id=_identity(f"rig-child-{side}"),
            name=f"Forearm.{side}",
            parent_id=root.id,
            length=100,
            group="Arms",
            transform=Transform(x=100, rotation=30),
        )
        control = SceneObject(
            id=_identity(f"rig-target-{side}"),
            name=f"Hand target.{side}",
            transform=Transform(x=400 if side == "L" else 500, y=330),
        )
        bones.extend((root, child))
        targets.append(control)
        constraints.append(
            Constraint(
                id=_identity(f"rig-ik-{side}"),
                name=f"Arm IK.{side}",
                owner_id=root.id,
                target_id=control.id,
                kind="two_bone_ik",
                parameters={"end_bone_id": child.id, "bend": bend, "mode": "ik", "stretch": False},
            )
        )
        values = (
            ((0, 400), (30, 330), (60, 400)) if side == "L" else ((0, 500), (30, 570), (60, 500))
        )
        tracks.extend(
            (
                _track(f"Target X.{side}", control.id, "transform.x", values),
                _track(
                    f"Target Y.{side}", control.id, "transform.y", ((0, 330), (30, 220), (60, 330))
                ),
            )
        )
    skeleton = Skeleton(id=_identity("rig-skeleton"), name="Symmetric arms", bones=tuple(bones))
    timeline = Timeline(
        id=_identity("rig-timeline"), name="Animated IK targets", tracks=tuple(tracks)
    )
    clip = AnimationClip(
        id=_identity("rig-clip"),
        name="Symmetric reach",
        timeline_id=timeline.id,
        out_frame=59,
        loop=True,
    )
    scene = Scene(
        id=_identity("rig-scene"),
        name="IK / FK study",
        settings=SceneSettings(width=900, height=540, fps=30, end_frame=59),
        skeletons=(skeleton,),
        objects=tuple(targets),
        constraints=tuple(constraints),
        timelines=(timeline,),
        clips=(clip,),
        characters=(
            Character(id=_identity("rig-character"), name="Arms study", skeleton_id=skeleton.id),
        ),
    )
    return Project(id=_identity("rig-project"), name="Rigging playground", scenes=(scene,))
