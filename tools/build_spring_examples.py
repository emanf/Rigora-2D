"""Build original SVG spring studies through the same services used by Spring Editor.

The examples retain live spring constraints, named editable groups, bound vector
parts and keyed wind drivers. Pots/bases remain stationary; no baked fake physics
or externally referenced artwork is needed after packaging.
"""

# SVG contour literals remain contiguous for artwork editing.
# ruff: noqa: E501

import json
import math
from dataclasses import replace
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from build_content_thumbnails import bake_thumbnails
from cast_art import ellipse, path

from rigora.application_services.characters import CharacterService
from rigora.application_services.documents import DocumentService
from rigora.application_services.dynamics import DynamicsService
from rigora.application_services.meshes import MeshService
from rigora.application_services.skinning import SkinService
from rigora.domain.content import ContentItem, ContentPack
from rigora.domain.entities import (
    AnimationClip,
    Bone,
    Keyframe,
    Skeleton,
    Timeline,
    Track,
    Transform,
)
from rigora.domain.geometry import transform_point
from rigora.domain.project import SceneSettings
from rigora.infrastructure.content_packs import write_pack


def identity(value: str) -> str:
    """Keep offline example identities stable across artwork and physics revisions."""
    return str(uuid5(NAMESPACE_URL, f"rigora:spring-studies:{value}"))


def leaf(length: float, width: float, color: str) -> str:
    """Draw an isolated pointed leaf with an explicit petiole, midrib and lateral veins."""
    s = path(
        f"M-7 0Q{length * 0.38} {-width} {length} 0Q{length * 0.38} {width} -7 0Z",
        color,
        "#345d45",
        1.5,
    )
    s += path(f"M-8 0H{length - 5}", "none", "#c0cc83", 2)
    for t in (0.25, 0.45, 0.65):
        x = length * t
        s += path(
            f"M{x} 0L{x - 12} {-width * 0.40}M{x} 0L{x - 12} {width * 0.40}", "none", "#a6bb76", 1
        )
    return s


def blossom(sunflower: bool) -> str:
    """Draw layered vector petals, inner rays and individually placed seed highlights."""
    s = ""
    petals = 18 if sunflower else 12
    for i in range(petals):
        angle = i * 360 / petals
        s += f'<g transform="translate(25 0) rotate({angle})">'
        s += path(
            "M13 -7Q31 -23 59 -2Q61 8 43 11Q25 13 13 7Z",
            "#e7aa35" if sunflower else "#d7cbdc",
            "#bf8d32" if sunflower else "#aca1b6",
            1.2,
        )
        s += path("M15 -4Q34 -13 54 0Q34 8 15 4Z", "#f7d85c" if sunflower else "#fff8e9", "none")
        s += "</g>"
    s += ellipse(
        25,
        0,
        24 if sunflower else 19,
        24 if sunflower else 19,
        "#775342" if sunflower else "#e1ad45",
        "#5c5138",
    )
    for i in range(24 if sunflower else 14):
        angle = i * 2.399963
        radius = math.sqrt(i) * 3.7
        s += ellipse(
            25 + math.cos(angle) * radius,
            math.sin(angle) * radius,
            1.6,
            1.8,
            "#c8a96c" if sunflower else "#f7d66c",
        )
    return s


def cluster(length: float, berry: bool) -> str:
    """Layer small pointed leaves and berries into a flexible bush bough."""
    s = path(f"M-5 0H{length}", "none", "#665b3d", 5)
    for i, (x, y, angle) in enumerate(
        ((15, -12, -35), (30, 11, 35), (48, -17, -25), (65, 12, 35), (78, -6, 0))
    ):
        s += f'<g transform="translate({x} {y}) rotate({angle})">{leaf(38, 15, ("#528153", "#71944d", "#426b4b")[i % 3])}</g>'
        if berry:
            s += ellipse(x + 15, y, 5, 5, "#a94c65", "#7a4553") + ellipse(
                x + 14, y - 1, 1.5, 1.5, "#e59e9d"
            )
    return s


def example(slug: str, title: str, files: dict[str, bytes]) -> ContentItem:
    """Assemble one spring rig and publish real wind motion plus independently editable parts."""
    doc = DocumentService()
    doc.new(title, SceneSettings(width=1080, height=900, fps=24, end_frame=192))
    service = MeshService(doc)
    bones: list[Bone] = []
    art: dict[str, tuple[str, tuple[float, float, float, float]]] = {}
    groups: dict[str, list[str]] = {}
    base_y = 730

    def bone(
        name: str,
        parent: str | None,
        length: float,
        rotation: float = 0,
        attach: float | None = None,
    ) -> Bone:
        """Append one attached joint and retain parent-first order for every evaluator."""
        prior = next((b for b in bones if b.name == parent), None)
        b = Bone(
            name=name,
            parent_id=prior.id if prior else None,
            length=length,
            transform=Transform(
                x=(prior.length if attach is None else attach) if prior else 540,
                y=0 if prior else base_y,
                rotation=rotation if prior else -90,
            ),
        )
        bones.append(b)
        return b

    root = bone("Base driver", None, 70 if slug != "windsock" else 310)
    stems = []
    if slug == "windsock":
        art[root.name] = (
            path("M-8 -6H318V6H-8Z", "#626e72") + path("M290 -10V10", "none", "#a2aeae", 3),
            (-15, -16, 340, 32),
        )
        previous = root.name
        for i in range(5):
            b = bone(f"Fabric {i + 1}", previous, 58, 90 if i == 0 else 0)
            color = "#ce7657" if i % 2 == 0 else "#efe5c7"
            width = 25 - i * 3
            art[b.name] = (
                path(f"M-7 {-width}H64L64 {width - 2}H-7Z", color, "#8a7664", 1.3)
                + path(f"M-6 {-width + 5}H64", "none", "#f8edd4", 1),
                (-12, -width - 5, 84, width * 2 + 12),
            )
            groups.setdefault("Windsock · Fabric", []).append(b.id)
            previous = b.name
        driver = bones[1]
    else:
        previous = root.name
        count = 4 if slug == "willow" else 3 if slug == "sunflower" else 2
        for i in range(count):
            b = bone(
                f"Stem {i + 1}", previous, 64 if slug == "mushroom" else 75, (-3 if i % 2 else 3)
            )
            stems.append(b)
            groups.setdefault(f"{title} · Stems", []).append(b.id)
            previous = b.name
        for b in [root, *stems]:
            width = 11 if slug == "mushroom" else 5 if slug in ("daisy", "sunflower") else 8
            art[b.name] = (
                path(
                    f"M-9 {-width}H{b.length + 9}V{width}H-9Z",
                    "#d9c79f" if slug == "mushroom" else "#5a7d4b",
                    "#4e6541",
                    1.3,
                )
                + path(f"M1 {-width + 3}H{b.length + 5}", "none", "#b5ba77", 1.2),
                (-15, -width - 7, b.length + 32, width * 2 + 14),
            )
        if slug in ("daisy", "sunflower"):
            head = bone("Flower head", previous, 30)
            art[head.name] = (blossom(slug == "sunflower"), (-45, -70, 145, 140))
            groups[f"{title} · Blossom"] = [head.id]
            for i, stem in enumerate(stems):
                for side in (-1, 1):
                    b = bone(
                        f"Leaf {i + 1} {side}",
                        stem.name,
                        75 + i * 8,
                        side * (50 + i * 9),
                        attach=stem.length * 0.5,
                    )
                    art[b.name] = (
                        leaf(b.length, 25, "#6d924e" if side > 0 else "#477c54"),
                        (-14, -33, b.length + 30, 66),
                    )
                    groups.setdefault(f"{title} · Leaves", []).append(b.id)
        elif slug == "bush":
            for index, angle in enumerate((-68, -36, 0, 34, 66)):
                b = bone(f"Berry bough {index + 1}", root.name, 76, angle)
                groups.setdefault("Berry bush · Boughs", []).append(b.id)
                tip = bone(f"Leaf cluster {index + 1}", b.name, 85, (-12 if index % 2 else 12))
                art[b.name] = (cluster(65, True), (-15, -45, 135, 90))
                art[tip.name] = (cluster(82, True), (-15, -45, 150, 90))
                groups.setdefault("Berry bush · Foliage", []).append(tip.id)
            # Keep the central scaffold behind the five visibly independent boughs.
        elif slug == "willow":
            for index, stem in enumerate(stems):
                for side in (-1, 1):
                    b = bone(
                        f"Willow branch {index} {side}", stem.name, 90, side * (55 + index * 4)
                    )
                    groups.setdefault("Willow · Branches", []).append(b.id)
                    droop = bone(f"Hanging spray {index} {side}", b.name, 72, side * 55)
                    art[b.name] = (leaf(92, 15, "#638a60"), (-14, -28, 124, 56))
                    spray = path("M-7 0H78", "none", "#7b8957", 3)
                    for j in range(5):
                        spray += f'<g transform="translate({j * 15} 0) rotate({35 if side > 0 else -35})">{leaf(38, 7, "#91a363")}</g>'
                    art[droop.name] = (spray, (-14, -40, 130, 80))
                    groups.setdefault("Willow · Hanging leaves", []).append(droop.id)
        else:
            cap = bone("Mushroom cap", previous, 22)
            s = path("M-12 -85Q83 -90 100 0Q83 90 -12 85Q17 0 -12 -85Z", "#bf6b61", "#815753", 2)
            s += path("M-12 -85Q18 0 -12 85Q-26 0 -12 -85Z", "#ead5b3", "#a18c6d", 1.5)
            for x, y, rx, ry in (
                (48, -43, 12, 8),
                (71, 8, 15, 10),
                (39, 46, 10, 8),
                (65, -17, 7, 6),
            ):
                s += ellipse(x, y, rx, ry, "#f3dcb5")
            art[cap.name] = (s, (-34, -98, 148, 196))
            groups["Mushroom · Cap"] = [cap.id]
        driver = root
    rig = Skeleton(
        name=title,
        bones=tuple(bones),
        extra={"semantic_mapping": {b.name: b.id for b in bones}, "anatomy": f"spring-{slug}"},
    )
    service.commit("Create spring study rig", skeletons=(rig,))
    sources = {}
    folder = Path("assets/examples/springs") / slug
    folder.mkdir(parents=True, exist_ok=True)
    fragments = []
    for index, b in enumerate(bones):
        if b.name not in art:
            continue
        fragment, bounds = art[b.name]
        x, y, w, h = bounds
        data = f'<svg xmlns="http://www.w3.org/2000/svg" width="{math.ceil(w)}" height="{math.ceil(h)}" viewBox="{x} {y} {math.ceil(w)} {math.ceil(h)}"><title>{title} · {b.name}</title>{fragment}</svg>'.encode()
        source = f"parts/{slug}/{index}.svg"
        files[source] = data
        (folder / f"{index:02d}.svg").write_bytes(data)
        matrix = doc.animation.pose.nodes[b.id].world_matrix
        px, py = transform_point(matrix, x, y)
        key = service.import_image_bytes(f"{slug}-{index}.svg", data, columns=2, rows=2)
        mesh = service.mesh(key)
        service.commit(
            "Position spring vector",
            objects=tuple(
                replace(
                    o,
                    name=b.name,
                    transform=Transform(
                        x=px, y=py, rotation=math.degrees(math.atan2(matrix[1], matrix[0]))
                    ),
                )
                if o.id == mesh.object_id
                else o
                for o in service.scene.objects
            ),
        )
        SkinService(doc).bind(key, (b.id,))
        sources[mesh.asset_id] = source
        fragments.append(
            f'<g transform="matrix({" ".join(str(v) for v in matrix)})">{fragment}</g>'
        )
    # A separate, unskinned pot/base keeps the support stationary during any spring preview.
    base = path("M-77 0H77L62 103Q0 121 -62 103Z", "#bd8061", "#805d50", 2) + path(
        "M-86 -10H86V14H-86Z", "#d49a77", "#805d50", 2
    )
    if slug == "windsock":
        base = path("M-58 0H58L83 32H-83Z", "#717b7e", "#465159", 2)
    data = f'<svg xmlns="http://www.w3.org/2000/svg" width="190" height="145" viewBox="-95 -17 190 145">{base}</svg>'.encode()
    source = f"parts/{slug}/base.svg"
    files[source] = data
    (folder / "base.svg").write_bytes(data)
    key = service.import_image_bytes(f"{slug}-base.svg", data, columns=2, rows=2)
    mesh = service.mesh(key)
    service.commit(
        "Place stationary support",
        objects=tuple(
            replace(o, name="Stationary base", transform=Transform(x=445, y=base_y - 17))
            if o.id == mesh.object_id
            else o
            for o in service.scene.objects
        ),
    )
    sources[mesh.asset_id] = source
    fragments.append(f'<g transform="translate(540 {base_y})">{base}</g>')
    dynamics = DynamicsService(doc)
    for index, (name, keys) in enumerate(groups.items()):
        dynamics.configure(
            tuple(keys),
            group=name,
            frequency=(2.2 if index == 0 else 1.6 if "Blossom" in name else 3.4),
            damping=0.65 if index == 0 else 0.38,
            inertia=0.8,
            gravity=35 if slug != "mushroom" else 80,
            clockwise=38,
            counterclockwise=38,
            translate=slug == "mushroom" and index == 0,
            stretch=35 if slug == "mushroom" else 0,
            squash=25 if slug == "mushroom" else 0,
        )
    motions = []
    for action, duration, amplitude, active in (
        ("Breeze", 96, 8, 48),
        ("Strong gust", 128, 18, 64),
    ):
        keys = []
        for frame in range(0, duration + 1, 4):
            t = min(1, frame / active)
            value = (
                amplitude * math.sin(math.pi * t) ** 2 * math.sin(t * math.tau * 1.5)
                if frame < active
                else 0
            )
            keys.append(Keyframe(frame=frame, value=driver.transform.rotation + value))
        timeline = Timeline(
            name=f"{title} · {action}",
            tracks=(
                Track(
                    owner_id=driver.id, property_path="transform.rotation", keyframes=tuple(keys)
                ),
            ),
        )
        motions.append(
            (
                timeline,
                AnimationClip(
                    name=action,
                    timeline_id=timeline.id,
                    out_frame=duration,
                    loop=True,
                    annotation="A keyed wind driver with live spring follow-through and a settling tail.",
                ),
            )
        )
    root = CharacterService(doc).create_object(tuple(o.id for o in service.scene.objects), title)
    motions = [(t, replace(c, extra={**c.extra, "object_id": root})) for t, c in motions]
    service.commit(
        "Publish spring study",
        skeletons=tuple(
            replace(r, extra={**r.extra, "object_id": root}) for r in service.scene.skeletons
        ),
        timelines=tuple(t for t, c in motions),
        clips=tuple(c for t, c in motions),
        extra={
            **service.scene.extra,
            "spring_example": slug,
            "spring_notes": "Open Spring Editor, select a named group and change a preset or its properties. Move Base driver to test live follow-through.",
        },
    )
    doc.select_animation_clip(motions[0][1].id)
    assert doc.project is not None
    member = f"scenes/{slug}.json"
    files[member] = json.dumps(doc.project.to_dict(), separators=(",", ":")).encode()
    portrait = f'<svg xmlns="http://www.w3.org/2000/svg" width="440" height="420" viewBox="190 170 700 710">{"".join(fragments)}</svg>'.encode()
    thumbnail = f"portraits/{slug}.svg"
    files[thumbnail] = portrait
    (folder / "example.svg").write_bytes(portrait)
    review = Path("build/spring-studies")
    review.mkdir(parents=True, exist_ok=True)
    doc.save(review / f"{slug}.rigora", overwrite=True)
    return ContentItem(
        id=identity(slug),
        name=title,
        kind="scene",
        category="Plants & springs",
        version="2.0",
        author="Rigora contributors",
        license="CC0-1.0",
        tags=("spring-example", "spring", "svg", "vector", "rigged", "physics", slug),
        thumbnail=thumbnail,
        description="Separate original SVG parts, editable Spring Editor groups, stationary support and Breeze / Strong gust performances. Select a spring group to tune its response.",
        payload={
            "object_template": True,
            "project_source": member,
            "sources": sources,
            "performance_clips": [{"id": c.id, "name": c.name} for t, c in motions],
        },
    )


def build() -> None:
    """Publish six portable vector examples without changing user projects or preferences."""
    files: dict[str, bytes] = {}
    items = tuple(
        example(slug, name, files)
        for slug, name in (
            ("daisy", "Daisy · Spring flower"),
            ("sunflower", "Sunflower · Heavy blossom"),
            ("bush", "Berry bush · Flexible boughs"),
            ("willow", "Willow · Hanging leaves"),
            ("windsock", "Windsock · Fabric follow-through"),
            ("mushroom", "Mushroom · Elastic stem"),
        )
    )
    pack = ContentPack(
        id=identity("pack"),
        name="Rigora Studio · Spring studies",
        author="Rigora contributors",
        license="CC0-1.0",
        items=items,
    )
    pack = bake_thumbnails(pack, files)
    write_pack(Path("assets/library/studio-springs.rigpack"), pack, files, overwrite=True)
    print("Published six SVG spring studies", flush=True)


if __name__ == "__main__":
    build()
