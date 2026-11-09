"""Build portable layered illustrations with canonical rigs, choices and editable actions."""

import hashlib
import json
from collections.abc import Callable, Sequence
from concurrent.futures import CancelledError
from dataclasses import dataclass, replace
from uuid import NAMESPACE_URL, uuid5

from rigora.application_services.commands import ProjectPatch
from rigora.application_services.content_library import ContentService
from rigora.application_services.documents import DocumentService
from rigora.domain.character_recipe import RUN_ACTIONS, CharacterRecipe
from rigora.domain.content import ContentItem
from rigora.domain.creator_options import outfit_values, retained_choices
from rigora.domain.entities import (
    AnimationClip,
    Asset,
    Bone,
    Character,
    Deformer,
    Group,
    Keyframe,
    Mesh,
    SceneObject,
    Skeleton,
    Timeline,
    Track,
    Transform,
    Vertex,
)
from rigora.domain.geometry import affine
from rigora.domain.project import Project, ProjectError, Scene, SceneSettings
from rigora.infrastructure.illustration import artwork, portrait, svg
from rigora.infrastructure.illustration_motion import duration, local_transforms, world_joints
from rigora.resources import asset_path

HEAD_BOUNDS = (-90.0, -330.0, 180.0, 180.0)
IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


@dataclass(frozen=True)
class CharacterBuild:
    """A complete portable specimen independent of any live destination document."""

    item: ContentItem
    files: dict[str, bytes]
    root_id: str


def character_portrait(recipe: CharacterRecipe) -> bytes:
    """Render the newly authored visible composition without loading retired resources."""
    return portrait(recipe)


def character_preview_frame(recipe: CharacterRecipe) -> tuple[float, float, float, float]:
    """Return a stable wardrobe-independent framing box anchored to the soles."""
    d, joints, _ = artwork(recipe)
    top = min(min(j.root[1], j.tip[1]) for j in joints.values()) - d.head * 1.5
    return 0.0, 12.0, max(260.0, d.width * 3), 12 - top


def raster_source(source: bytes, height: int = 512) -> bytes:
    """Render disposable PNG posters from vector sources for the local preview cache."""
    try:
        import resvg_py
    except ImportError as error:
        raise ProjectError(
            "SVG preview rendering requires Rigora's render dependencies."
        ) from error
    return bytes(
        resvg_py.svg_to_bytes(svg_string=source.decode(), height=height, skip_system_fonts=True)
    )


def build_character(
    recipe: CharacterRecipe,
    *,
    cancelled: Callable[[], bool] | None = None,
    scratch: DocumentService | None = None,
) -> CharacterBuild:
    """Build editable layered artwork, a fixed-length rig and smooth full-body cycles.

    Sources are original SVG vectors. Every part has an
    independent rigid bind, and source actions use ordinary portable Bézier tracks.
    An optional empty scratch document receives the completed graph atomically.
    """
    if scratch is not None and scratch.project is not None:
        raise ProjectError("Character preparation needs an empty scratch document.")

    def checkpoint() -> None:
        if cancelled and cancelled():
            raise CancelledError()

    checkpoint()
    d, joints, parts = artwork(recipe)
    signature = hashlib.sha256(json.dumps(recipe.to_dict(), sort_keys=True).encode()).hexdigest()

    def identity(label: str) -> str:
        return str(uuid5(NAMESPACE_URL, "rigora.illustration.v2/" + signature + "/" + label))

    root = Group(id=identity("root"), name=recipe.name or d.name, extra={"object_container": True})
    local = local_transforms(joints)
    bones = tuple(
        Bone(
            id=identity("bone/" + name),
            name=name,
            parent_id=identity("bone/" + joint.parent) if joint.parent else None,
            length=joint.length,
            transform=local[name],
            extra={"minimum_joint_angle": 0},
        )
        for name, joint in joints.items()
    )
    rig = Skeleton(
        id=identity("skeleton"),
        name=recipe.name + " rig",
        bones=bones,
        extra={
            "object_id": root.id,
            "anatomy": d.anatomy,
            "semantic_mapping": {b.name: b.id for b in bones},
            "library_bind": IDENTITY,
        },
    )
    from rigora.domain.rig_roots import rooted_skeleton

    attachment = next(j.root for j in joints.values() if j.parent is None)
    rig = rooted_skeleton(rig, position=attachment)
    assets, objects, meshes, deformers = [], [], [], []
    files: dict[str, bytes] = {}
    groups = [root]
    mouth_groups = {}
    for style in retained_choices(recipe, "Mouth"):
        group = Group(
            id=identity("mouth-group/" + style),
            name=style + " mouth set",
            parent_id=root.id,
            extra={"visible": style == recipe.mouth_style},
        )
        groups.append(group)
        mouth_groups[style] = group.id
    choices: dict[str, dict[str, list[str]]] = {}
    choice_visible: dict[tuple[str, str], bool] = {}
    mouth_sets: dict[str, dict[str, str]] = {style: {} for style in mouth_groups}
    eyes, brows = [], []
    for index, part in enumerate(parts):
        checkpoint()
        source = svg(part.markup, part.bounds)
        extension = "svg"
        key = identity("asset/" + part.name)
        source_path = f"assets/{key}/{index}.{extension}"
        asset = Asset(
            id=key,
            name=part.name + "." + extension,
            source=source_path,
            storage="embedded",
            kind="vector",
            media_type="image/svg+xml",
            sha256=hashlib.sha256(source).hexdigest(),
        )
        assets.append(asset)
        files[source_path] = source
        mouth = part.name.startswith("Mouth · ")
        parent = mouth_groups[part.variant] if mouth else root.id
        shape = part.name.rsplit(" · ", 1)[-1]
        x, y, w, h = part.bounds
        obj = SceneObject(
            id=identity("object/" + part.name),
            name=part.name,
            parent_id=parent,
            asset_id=key,
            transform=Transform(pivot_x=x + w / 2, pivot_y=y + h / 2),
            visible=(
                shape
                == {"Happy": "E", "Surprised": "O", "Angry": "MBP"}.get(
                    recipe.feeling, recipe.mouth_pose
                )
            )
            if mouth
            else part.visible,
            extra={"illustration_part": True, "source_format": recipe.source_format},
        )
        vertices = tuple(
            Vertex(
                id=identity("vertex/" + part.name + "/" + str(i)),
                x=px,
                y=py,
                uv=uv,
                weights={identity("bone/" + part.bone): 1.0},
            )
            for i, (px, py, uv) in enumerate(
                (
                    (x, y, (0.0, 0.0)),
                    (x + w, y, (1.0, 0.0)),
                    (x + w, y + h, (1.0, 1.0)),
                    (x, y + h, (0.0, 1.0)),
                )
            )
        )
        mesh = Mesh(
            id=identity("mesh/" + part.name),
            name=part.name,
            object_id=obj.id,
            asset_id=key,
            vertices=vertices,
            triangles=(
                (vertices[0].id, vertices[1].id, vertices[2].id),
                (vertices[0].id, vertices[2].id, vertices[3].id),
            ),
        )
        joint = joints[part.bone]
        bind = affine(*joint.root, joint.angle, 1, 1, 0, 0)
        stage = Deformer(
            id=identity("skin/" + part.name),
            name="Rigid part binding",
            kind="skinning",
            owner_id=mesh.id,
            parameters={
                "bind_matrices": {identity("bone/" + part.bone): bind},
                "object_bind": IDENTITY,
                "object_group": root.id,
                "object_group_bind": IDENTITY,
                "local_controls": part.name.startswith(("Eye ", "Brow ", "Mouth · ")),
            },
        )
        objects.append(obj)
        meshes.append(mesh)
        deformers.append(stage)
        if part.family:
            choices.setdefault(part.family, {}).setdefault(part.variant, []).append(mesh.id)
            choice_visible[(part.family, part.variant)] = (
                choice_visible.get((part.family, part.variant), False) or part.visible
            )
        if mouth:
            mouth_sets[part.variant][shape] = obj.id
        elif part.name.startswith("Eye "):
            eyes.append(obj.id)
        elif part.name.startswith("Brow "):
            brows.append(obj.id)
    outfits = []
    for family, variants in choices.items():
        values = []
        for name, variant_meshes in variants.items():
            visible = choice_visible[family, name]
            variant = {
                "id": identity("choice/" + family + "/" + name),
                "name": name,
                "meshes": variant_meshes,
                "visible": visible,
            }
            if family == "Mouth style":
                variant["visibility_roots"] = [mouth_groups[name]]
            values.append(variant)
        outfits.append(
            {
                "id": identity("choices/" + family),
                "name": family,
                "multiple": False,
                "variants": values,
                "default": next((v["id"] for v in values if v["visible"]), values[0]["id"]),
            }
        )
    face = {
        "kind": "character-mouth",
        "mouths": mouth_sets.get(recipe.mouth_style, {}),
        "mouth_sets": mouth_sets,
        "mouth_groups": mouth_groups,
        "eyes": eyes,
        "pupils": [],
        "brows": brows,
    }
    root = replace(
        root,
        extra={
            **root.extra,
            "character_recipe": recipe.to_dict(),
            "illustration_version": 3,
            "anatomy": d.anatomy,
            "outfits": outfits,
            **({"face": face} if len(face["mouths"]) == 10 else {}),
            "source_format": recipe.source_format,
            "creator_outfit_sets": {name: outfit_values(name) for name in recipe.outfit_sets},
        },
    )
    groups[0] = root
    timelines, clips = [], []
    for action in recipe.motions:
        checkpoint()
        length = duration(d, action)
        # Fast knee recovery needs per-frame keys to preserve the source ankle arc.
        step = (
            1
            if action in (*RUN_ACTIONS, "Jump", "Hop", "High jump")
            and d.anatomy in ("human", "robot")
            else 2
        )
        times: Sequence[float] = list(range(0, length, step)) + [length]
        if action in RUN_ACTIONS and action != "Run" and d.anatomy in ("human", "robot"):
            # Short sprint cycles still need enough samples for sharp knee recovery.
            times = [i / 2 for i in range(length * 2)] + [length]
        samples = [
            local_transforms(world_joints(d, recipe.view, action, t / length)) for t in times
        ]
        tracks = []
        for bone in bones:
            for channel in ("x", "y", "rotation"):
                raw = [getattr(s[bone.name], channel) for s in samples]
                rest_value = getattr(bone.transform, channel)
                if bone.parent_id is None and channel in ("x", "y"):
                    shift = attachment[0 if channel == "x" else 1]
                    raw = [value - shift for value in raw]
                    rest_value -= shift
                if channel == "rotation":
                    for i in range(1, len(raw)):
                        raw[i] = raw[i - 1] + (raw[i] - raw[i - 1] + 180) % 360 - 180
                if max(raw) - min(raw) < 1e-8 and abs(raw[0] - rest_value) < 1e-8:
                    continue
                keys: list[Keyframe] = []
                for i, (time, value) in enumerate(zip(times, raw, strict=True)):
                    # Centered periodic derivatives give matching velocity at cycle seams.
                    prev = raw[i - 1] if i else raw[-2]
                    following = raw[i + 1] if i + 1 < len(raw) else raw[1]
                    prev_time = times[i - 1] if i else times[-2] - length
                    next_time = times[i + 1] if i + 1 < len(times) else length + times[1]
                    slope = (following - prev) / (next_time - prev_time)
                    incoming = (time - prev_time) / 3
                    outgoing = (next_time - time) / 3
                    keys.append(
                        Keyframe(
                            id=identity(f"key/{action}/{bone.name}/{channel}/{i}"),
                            frame=time,
                            value=value,
                            interpolation="bezier",
                            tangent_in=(-incoming, -incoming * slope),
                            tangent_out=(outgoing, outgoing * slope),
                        )
                    )
                tracks.append(
                    Track(
                        id=identity(f"track/{action}/{bone.name}/{channel}"),
                        name=bone.name + " " + channel,
                        owner_id=bone.id,
                        property_path="transform." + channel,
                        keyframes=tuple(keys),
                    )
                )
        timeline = Timeline(id=identity("timeline/" + action), name=action, tracks=tuple(tracks))
        clip = AnimationClip(
            id=identity("clip/" + action),
            name=action,
            timeline_id=timeline.id,
            out_frame=length - 1 if action in ("Stand", "Idle", "Walk", *RUN_ACTIONS) else length,
            loop=action in ("Stand", "Idle", "Walk", *RUN_ACTIONS),
            annotation=d.name + " · " + action,
            extra={
                "object_id": root.id,
                "recipe_motion": action,
                "continuous_loop": action in ("Stand", "Idle", "Walk", *RUN_ACTIONS),
                "fk_bones": [b.id for b in bones],
            },
        )
        timelines.append(timeline)
        clips.append(clip)
    actor = Character(
        id=identity("actor"),
        name=recipe.name,
        skeleton_id=rig.id,
        object_ids=tuple(o.id for o in objects),
        mesh_ids=tuple(m.id for m in meshes),
        extra={"object_id": root.id},
    )
    scene = Scene(
        id=identity("scene"),
        name=recipe.name,
        settings=SceneSettings(fps=30),
        groups=tuple(groups),
        skeletons=(rig,),
        characters=(actor,),
        objects=tuple(objects),
        meshes=tuple(meshes),
        deformers=tuple(deformers),
        timelines=tuple(timelines),
        clips=tuple(clips),
        draw_order=tuple(o.id for o in objects),
    )
    project = Project(
        id=identity("project"), name=recipe.name, assets=tuple(assets), scenes=(scene,)
    )
    if scratch is not None:
        scratch._link_objects = False
        scratch.new(recipe.name)
        assert scratch.project is not None
        scratch.execute(
            ProjectPatch(
                "Prepare illustrated character",
                {"scenes": scratch.project.scenes, "assets": scratch.project.assets},
                {"scenes": project.scenes, "assets": project.assets},
            )
        )
        scratch._asset_data.update(files)
        if clips:
            scratch.select_animation_clip(clips[0].id)
    files["character.json"] = json.dumps(project.to_dict(), ensure_ascii=False).encode()
    supplied_hands = any(p.family == "Hands" and "data-source-hand=" in p.markup for p in parts)
    if supplied_hands:
        files["GLOVE-NOTICE.md"] = asset_path("characters/hands/NOTICE.md").read_bytes()
    item = ContentItem(
        id=identity("content"),
        name=recipe.name,
        kind="scene",
        category="Characters" if d.anatomy in ("human", "robot") else "Animals",
        author="Rigora",
        license="Mixed; see GLOVE-NOTICE.md" if supplied_hands else "CC0-1.0",
        tags=(d.anatomy, d.style.lower(), "illustration-v2", recipe.source_format.lower()),
        payload={
            "project_source": "character.json",
            "sources": {a.id: a.source for a in assets},
            "object_template": True,
            "performance_clips": [{"id": c.id, "name": c.name} for c in clips],
            "selected_clip": clips[0].id if clips else None,
        },
    )
    return CharacterBuild(item, files, root.id)


class CharacterCreationService:
    """Insert a portable specimen through the shared undoable content application service."""

    def __init__(self, document: DocumentService) -> None:
        self.document = document

    def create(self, built: CharacterBuild) -> str:
        """Embed referenced sources and preserve the rig, outfits, face and source actions."""
        if self.document.project is None:
            raise ProjectError("Create a project before adding a character.")
        service = ContentService(self.document)
        before = {g.id for g in service.scene.groups}
        with self.document.command_group("Create character"):
            service.place(
                built.item,
                built.files,
                position=(service.scene.settings.width / 2, service.scene.settings.height / 2),
            )
            return next(
                g.id
                for g in service.scene.groups
                if g.id not in before and g.extra.get("object_container")
            )
