"""Build portable original SVG Objects with ordinary editable transform and FFD animation."""

import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from rigora.application_services.content_thumbnails import render_content_thumbnail
from rigora.application_services.template_effects import smooth_keys
from rigora.domain.content import ContentItem, ContentPack
from rigora.domain.entities import (
    AnimationClip,
    Asset,
    Deformer,
    Group,
    Keyframe,
    Mesh,
    SceneObject,
    Timeline,
    Track,
    Transform,
)
from rigora.domain.mesh_geometry import grid_mesh
from rigora.domain.project import Project, Scene, SceneSettings
from rigora.infrastructure.animated_object_catalog import (
    AnimatedObject,
    animated_objects,
    layer_values,
)
from rigora.infrastructure.content_packs import write_pack
from rigora.infrastructure.motion_catalog import identity, item
from rigora.infrastructure.object_catalog import ObjectArt, original_objects, svg


@dataclass(frozen=True)
class BuiltTemplate:
    """Own an immutable template description and its portable source members before publication."""

    item: ContentItem
    files: dict[str, bytes]


def build_artwork(art: ObjectArt) -> BuiltTemplate:
    """Keep the original vector as editable artwork; its PNG is only a browsing poster."""
    source = "sources/" + identity(art.category + "/" + art.name) + ".svg"
    return BuiltTemplate(
        item(
            art.name,
            "artwork",
            art.category,
            {"source": source, "object_template": True},
            source_format="SVG",
            prop_family=art.family,
            tags=("original", "svg", "editable", art.family),
            description=(
                "Original flat SVG Object. Drag into a scene, then edit, recolor or rig"
                " its artwork."
            ),
        ),
        {source: svg(art.body)},
    )


def build_effect(spec: AnimatedObject) -> BuiltTemplate:
    """Assemble a layered Object with canonical keys, optional FFD and no executable payload."""

    def key(label: str) -> str:
        """Keep generated asset, node and track identities stable across cache rebuilds."""
        return identity("animated-object/" + spec.name + "/" + label)

    root = Group(
        id=key("root"),
        name=spec.name,
        transform=Transform(pivot_x=128, pivot_y=128),
        extra={"object_container": True},
    )
    assets = []
    objects = []
    meshes: list[Mesh] = []
    stages = []
    tracks = []
    files = {}
    for layer in spec.layers:
        data = svg(layer.body)
        asset_id = key("asset/" + layer.name)
        source = "assets/" + asset_id + "/art.svg"
        files[source] = data
        assets.append(
            Asset(
                id=asset_id,
                name=layer.name + ".svg",
                source=source,
                storage="embedded",
                kind="vector",
                media_type="image/svg+xml",
                sha256=hashlib.sha256(data).hexdigest(),
            )
        )
        obj = SceneObject(
            id=key("object/" + layer.name),
            name=layer.name,
            parent_id=root.id,
            asset_id=asset_id,
            transform=Transform(pivot_x=layer.pivot[0], pivot_y=layer.pivot[1]),
        )
        objects.append(obj)
        mesh = grid_mesh(
            256, 256, 8 if layer.motion == "wave" else 1, 8 if layer.motion == "wave" else 1
        )
        ids = {
            v.id: key("vertex/" + layer.name + "/" + str(index))
            for index, v in enumerate(mesh.vertices)
        }
        mesh = replace(
            mesh,
            id=key("mesh/" + layer.name),
            name=layer.name + " mesh",
            asset_id=asset_id,
            object_id=obj.id,
            vertices=tuple(replace(v, id=ids[v.id]) for v in mesh.vertices),
            triangles=tuple((ids[a], ids[b], ids[c]) for a, b, c in mesh.triangles),
        )
        meshes.append(mesh)
        samples = [layer_values(layer, i / 48) for i in range(49)]
        paths = sorted({path for sample in samples for path in sample})
        for path in paths:
            values = [(i * spec.frames / 48, sample[path]) for i, sample in enumerate(samples)]
            keys = (
                tuple(Keyframe(frame=t, value=v) for t, v in values)
                if layer.motion == "spin"
                else smooth_keys(values, loop=True)
            )
            tracks.append(
                Track(
                    id=key("track/" + layer.name + "/" + path),
                    name=layer.name + " · " + path.rsplit(".", 1)[-1],
                    owner_id=obj.id,
                    property_path=path,
                    keyframes=keys,
                )
            )
        if layer.motion == "wave":
            stage = Deformer(
                id=key("wave/" + layer.name),
                name="Water / cloth wave",
                owner_id=mesh.id,
                kind="ffd",
                parameters={
                    "bounds": [0, 0, 256, 256],
                    "columns": 4,
                    "rows": 4,
                    "controls": [[0, 0] for _ in range(16)],
                    "intensity": 1,
                },
            )
            stages.append(stage)
            for point in range(16):
                column = point % 4
                values = [
                    (
                        i * spec.frames / 48,
                        7
                        * (column / 3) ** 1.5
                        * math.sin(math.tau * (i / 48 + layer.phase) - column * 0.8),
                    )
                    for i in range(49)
                ]
                tracks.append(
                    Track(
                        id=key("ffd-track/" + layer.name + "/" + str(point)),
                        name=f"{layer.name} · wave dot {point}",
                        owner_id=stage.id,
                        property_path=f"parameters.controls.{point}.1",
                        keyframes=smooth_keys(values, loop=True),
                    )
                )
    tracks = [
        replace(
            track,
            keyframes=tuple(
                replace(frame, id=identity(track.id + "/key/" + str(index)))
                for index, frame in enumerate(track.keyframes)
            ),
        )
        for track in tracks
    ]
    timeline = Timeline(id=key("timeline"), name=spec.name + " loop", tracks=tuple(tracks))
    clip = AnimationClip(
        id=key("clip"),
        name=spec.name,
        timeline_id=timeline.id,
        out_frame=spec.frames - 1,
        loop=True,
        extra={"object_id": root.id, "continuous_loop": True},
    )
    scene = Scene(
        id=key("scene"),
        name=spec.name,
        settings=SceneSettings(width=256, height=256, fps=30, end_frame=spec.frames - 1),
        groups=(root,),
        objects=tuple(objects),
        meshes=tuple(meshes),
        deformers=tuple(stages),
        timelines=(timeline,),
        clips=(clip,),
        draw_order=tuple(obj.id for obj in objects),
    )
    project = Project(id=key("project"), name=spec.name, scenes=(scene,), assets=tuple(assets))
    source = "projects/" + key("content") + ".json"
    files[source] = json.dumps(project.to_dict(), ensure_ascii=False).encode()
    entry = item(
        spec.name,
        "scene",
        spec.category,
        {
            "project_source": source,
            "sources": {asset.id: asset.source for asset in assets},
            "selected_clip": clip.id,
            "performance_clips": [{"id": clip.id, "name": spec.name}],
            "object_template": True,
            "preview_bounds": [0, 0, 256, 256],
        },
        source_format="SVG",
        tags=("original", "animated", "svg", "editable"),
        description=(
            "Original layered SVG Object with editable looped transform/FFD "
            "animation. Drag into a scene to start using it."
        ),
    )
    return BuiltTemplate(entry, files)


def object_template_count() -> int:
    """Return real catalog size for startup progress before any preview is generated."""
    return len(original_objects()) + len(animated_objects())


def write_object_catalog(target: Path, advance: Callable[[str], None]) -> tuple[str, ...]:
    """Generate source packs and actual PNG posters atomically inside the owned staging folder."""
    output = []
    for name, specs in (
        ("shapes", tuple(a for a in original_objects() if a.category == "Shapes")),
        ("objects", tuple(a for a in original_objects() if a.category != "Shapes")),
        ("animated-objects", animated_objects()),
    ):
        items = []
        files: dict[str, bytes] = {}
        for spec in specs:
            advance(spec.category + " · " + spec.name)
            built = build_effect(spec) if isinstance(spec, AnimatedObject) else build_artwork(spec)
            poster = "posters/object-" + built.item.id + ".png"
            png = render_content_thumbnail(built.item, built.files)
            (target / poster).write_bytes(png)
            output.append(poster)
            items.append(replace(built.item, thumbnail=poster))
            files.update(built.files)
            files[poster] = png
        pack = ContentPack(
            id=identity("pack/" + name),
            name="Rigora · " + name.replace("-", " "),
            author="Rigora contributors",
            license="CC0-1.0",
            items=tuple(items),
        )
        filename = name + ".rigpack"
        write_pack(target / filename, pack, files)
        output.append(filename)
    return tuple(output)
