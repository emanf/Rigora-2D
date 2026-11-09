"""Create an original, portable example of the complete authoring data contract."""

import argparse
import hashlib
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from rigora.domain.entities import (
    AnimationClip,
    Asset,
    AssetReference,
    Attachment,
    Bone,
    Character,
    Constraint,
    Deformer,
    Group,
    Keyframe,
    Layer,
    Mesh,
    PluginExtension,
    SceneObject,
    Skeleton,
    Slot,
    Timeline,
    Track,
    Transform,
    Vertex,
)
from rigora.domain.project import Project, Scene, SceneSettings
from rigora.infrastructure.project_storage import ProjectStorage

ART = b"""<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160" viewBox="0 0 160 160">
<path fill="#dedede" d="M24 140V20h64l40 40v40H76v40zm28-68h44V60L80 44H52z"/>
</svg>"""


def identity(label: str) -> str:
    """Derive repeatable example UUIDs from semantic labels rather than display names."""
    return str(uuid5(NAMESPACE_URL, f"urn:rigora:authoring-example:{label}"))


def example_project() -> tuple[Project, dict[str, bytes]]:
    """Connect all entity families and return the model plus its embedded source bytes."""
    asset = Asset(
        id=identity("asset"),
        name="Original geometric artwork",
        kind="vector",
        source="assets/art/geometric-r.svg",
        storage="embedded",
        media_type="image/svg+xml",
        sha256=hashlib.sha256(ART).hexdigest(),
    )
    layer = Layer(id=identity("layer"), name="Artwork")
    group = Group(id=identity("group"), name="Character root", layer_id=layer.id)
    obj = SceneObject(
        id=identity("object"),
        name="Geometric body",
        asset_id=asset.id,
        parent_id=group.id,
        layer_id=layer.id,
        transform=Transform(x=200, y=200),
    )
    root = Bone(id=identity("bone-root"), name="Root bone", length=80)
    tip = Bone(
        id=identity("bone-tip"),
        name="Tip bone",
        parent_id=root.id,
        transform=Transform(x=80),
        length=60,
    )
    skeleton = Skeleton(id=identity("skeleton"), name="Two bone rig", bones=(root, tip))
    vertices = tuple(
        Vertex(
            id=identity(f"vertex-{i}"),
            name=f"Vertex {i}",
            x=x,
            y=y,
            uv=(x / 160, y / 160),
            weights={root.id: 1.0},
        )
        for i, (x, y) in enumerate(((0, 0), (160, 0), (0, 160)))
    )
    mesh = Mesh(
        id=identity("mesh"),
        name="Triangle mesh",
        asset_id=asset.id,
        vertices=vertices,
        triangles=(tuple(v.id for v in vertices),),
    )
    character = Character(
        id=identity("character"),
        name="Example character",
        skeleton_id=skeleton.id,
        object_ids=(obj.id,),
        mesh_ids=(mesh.id,),
    )
    attachment = Attachment(
        id=identity("attachment"),
        name="Body attachment",
        slot_id=identity("slot"),
        asset_id=asset.id,
        mesh_id=mesh.id,
    )
    slot = Slot(
        id=identity("slot"),
        name="Body slot",
        owner_id=root.id,
        attachment_ids=(attachment.id,),
        active_attachment_id=attachment.id,
    )
    track = Track(
        id=identity("track"),
        name="Horizontal movement",
        owner_id=obj.id,
        property_path="transform.x",
        keyframes=(
            Keyframe(id=identity("key-0"), name="Start", frame=0, value=200),
            Keyframe(id=identity("key-24"), name="End", frame=24, value=320),
        ),
    )
    timeline = Timeline(id=identity("timeline"), name="Movement data", tracks=(track,))
    clip = AnimationClip(
        id=identity("clip"), name="Movement clip", timeline_id=timeline.id, out_frame=24, loop=True
    )
    scene = Scene(
        id=identity("scene"),
        name="Authoring model",
        settings=SceneSettings(width=800, height=600, end_frame=24),
        layers=(layer,),
        groups=(group,),
        objects=(obj,),
        skeletons=(skeleton,),
        characters=(character,),
        meshes=(mesh,),
        slots=(slot,),
        attachments=(attachment,),
        timelines=(timeline,),
        clips=(clip,),
        deformers=(
            Deformer(
                id=identity("deformer"),
                name="Lattice data",
                owner_id=mesh.id,
                kind="lattice",
                parameters={"columns": 3, "rows": 3},
            ),
        ),
        constraints=(
            Constraint(
                id=identity("constraint"),
                name="Aim data",
                owner_id=tip.id,
                target_id=obj.id,
                kind="aim",
            ),
        ),
        draw_order=(obj.id, slot.id),
    )
    project = Project(
        id=identity("project"),
        name="Rigora authoring model example",
        scenes=(scene,),
        assets=(asset,),
        asset_references=(
            AssetReference(id=identity("reference"), name="Source reference", asset_id=asset.id),
        ),
        extensions=(
            PluginExtension(
                id=identity("extension"),
                name="Example metadata",
                plugin_id="org.rigora.example",
                payload={"note": "Inert JSON; never executed"},
            ),
        ),
    )
    return project, {asset.source: ART}


def main() -> None:
    """Write a sample package, requiring an explicit flag before replacing an existing path."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output", nargs="?", type=Path, default=Path("build/examples/authoring-model.rigora")
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    project, assets = example_project()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    ProjectStorage().save(args.output, project, {}, asset_data=assets, overwrite=args.overwrite)
    print(args.output.resolve())


if __name__ == "__main__":
    main()
